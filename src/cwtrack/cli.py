"""Command-line entry point."""

from __future__ import annotations

import argparse
import contextlib
import getpass
import json
import os
from datetime import datetime
from pathlib import Path

from .auth import ask, do_login
from .classify import OPEN_BUCKETS
from .client import DEFAULT_BASE, Client, CwError
from .fetch import fetch_all
from .match import match_local
from .parse import parse_dump
from .report import fmt_delta, report, table

STATE_DIR = Path(os.environ.get("CW_HOME", ".cw"))
DUMP_DIR = STATE_DIR / "dump"

def find_data_dir(explicit: str) -> Path:
    """Locate cw-data/ without needing the right working directory.

    The default used to be a bare relative "cw-data", which silently found
    nothing when the script was run by absolute path from another folder - and
    then reported zero assignments, which reads like "you have no homework"
    rather than "I looked in the wrong place". That is the wrong failure mode
    for a tool whose whole job is telling you what you owe.

    Order: the explicit flag, then any cw-data/ found walking up from the
    working directory, then one next to this script's project, then CWD.
    """
    if explicit:
        return Path(explicit)
    cwd = Path.cwd()
    for base in (cwd, Path(__file__).resolve().parent.parent.parent):
        for candidate in [base, *base.parents]:
            probe = candidate / "cw-data"
            if probe.is_dir() and any(probe.iterdir()):
                return probe
    return cwd / "cw-data"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="cwtrack",
        description="Track your own assignments and course materials on a Sharif Moodle site.",
    )
    ap.add_argument(
        "command",
        choices=[
            "fetch", "report", "open", "raw", "store", "ui", "gaps",
            "material", "brief",
        ],
    )
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--home", default=str(STATE_DIR), help="page-dump folder (default .cw)")
    ap.add_argument("--data", default="", help="tracker data folder (default: the nearest cw-data)")
    ap.add_argument("--user", help="username; default $CW_USER")
    ap.add_argument("--local", default="", help="folder to cross-reference local files")
    ap.add_argument("--days", type=int, default=0, help="only items due within N days")
    ap.add_argument(
        "-o", "--out",
        help="write output to this file instead of stdout. Honoured by every "
             "text-producing command, which matters because Persian output is "
             "mangled by a stock Windows console",
    )
    ap.add_argument("--course", default="", help="course id, for the material command")
    ap.add_argument("--cmid", default="", help="assignment id, for the brief command")
    ap.add_argument(
        "--work", default="", help="where brief writes working folders (default: ./work)"
    )
    ap.add_argument("--force", action="store_true", help="overwrite an existing brief")
    ap.add_argument("--json", action="store_true")
    return ap


def emit(text: str, out: str = "") -> None:
    """Write a command's output to stdout, or to ``--out``.

    Persian text on a stock Windows console is cp1252 and comes out as mojibake,
    so "-o writes a file you can read" is the documented workaround. It has to
    work for every text-producing command, not just `report`, or the advice is
    useless for `gaps` - which is the one people actually run.
    """
    if out:
        p = Path(out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        print("نوشته شد: {}".format(p.resolve()))
    else:
        print(text)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    base_dir = Path(args.home)
    dump = base_dir / "dump"
    data_dir = find_data_dir(args.data)
    client = Client(args.base)

    if args.command == "raw":
        if not dump.is_dir():
            raise CwError("nothing saved yet; run `cwtrack fetch` first")
        for p in sorted(dump.glob("*.html")):
            print(p, p.stat().st_size, "bytes")
        return 0

    if args.command == "fetch":
        if not client.logged_in():
            user = args.user or os.environ.get("CW_USER")
            if not user:
                user = ask("نام کاربری: ")
            pw = os.environ.get("CW_PASS") or getpass.getpass("رمز عبور: ")
            do_login(client, user, pw, base_dir)
        else:
            print("نشست معتبر است، نیازی به ورود دوباره نیست.")
        fetch_all(client, base_dir)
        # A fetch that never lands in the store is a fetch you cannot query, so it
        # happens here rather than as a separate step that gets forgotten.
        now = datetime.now()
        rows = parse_dump(dump, now)
        info = {"fullname": "", "username": os.environ.get("CW_USER", ""), "userid": ""}
        prev = data_dir / "user.json"
        if prev.is_file():
            with contextlib.suppress(json.JSONDecodeError):
                info = json.loads(prev.read_text(encoding="utf-8-sig"))
        from . import tracker

        summary = tracker.store(data_dir, info, rows)
        print("ذخیره شد: {} درس، {} تکلیف در {}".format(
            summary["courses"], summary["assignments"], data_dir.resolve()))
        return 0

    # ---- everything below reads the store, not the network ------------------
    from . import tracker

    # A missing store must never look like an empty one. "You have no
    # assignments" and "I could not find your data" are opposite claims, and
    # printing zeros for the second one is how a real deadline gets missed.
    if not data_dir.is_dir() or not (data_dir / "assignments.json").is_file():
        raise CwError(
            "پوشهٔ داده پیدا نشد: {}\n"
            "اگر تازه شروع کرده‌اید:  cwtrack fetch\n"
            "اگر جای دیگری است:      cwtrack <command> --data <مسیر>".format(data_dir.resolve())
        )

    user, assignments = tracker.load(data_dir)
    now = datetime.now()
    now_epoch = int(now.timestamp())
    gap = tracker.gaps(assignments, now_epoch)

    if args.command == "material":
        if not args.course:
            raise CwError("--course <id> is required for the material command")
        folder = tracker.course_dir(data_dir, int(args.course)) / "materials"
        folder.mkdir(parents=True, exist_ok=True)
        mats = tracker.scan_materials(folder)
        lines = [
            "منابع این درس را اینجا بگذارید:",
            "  {}".format(folder.resolve()),
            "",
            "-" * 60,
            "در حال حاضر {} فایل:".format(len(mats)),
        ]
        lines += [
            "  {:>10}  {:<8}  {}".format("{:,}".format(m.bytes), m.kind, m.name)
            for m in mats
        ]
        if not mats:
            lines.append("  (خالی)")
        emit("\n".join(lines), args.out)
        return 0

    if args.command == "store":
        rows = parse_dump(dump, now) if dump.is_dir() else []
        if not rows:
            raise CwError("no dump to store; run `cwtrack fetch` first")
        summary = tracker.store(data_dir, user or {}, rows)
        print("ذخیره شد: {} درس، {} تکلیف".format(summary["courses"], summary["assignments"]))
        return 0

    if args.command == "gaps":
        if args.json:
            text = json.dumps(
                {
                    "counts": gap["counts"],
                    "urgent": [a.name for a in gap["urgent"]],
                    "soon": [a.name for a in gap["soon"]],
                    "per_course": [
                        {k: v for k, v in c.items() if k != "items"} for c in gap["per_course"]
                    ],
                },
                ensure_ascii=False, indent=2,
            )
        else:
            c = gap["counts"]
            lines = [
                "کل {} · ارسال‌نشده {} · گذشته از مهلت {} · انجام‌شده {}".format(
                    c["total"], c["open"], c["urgent"], c["done"]
                ),
                "",
            ]
            lines += ["  [گذشته]  {} — {}".format(a.course, a.name) for a in gap["urgent"]]
            lines += [
                "  [نزدیک]  {} — {}  ({})".format(
                    a.course, a.name, fmt_delta(a.due, now_epoch)
                )
                for a in gap["soon"]
            ]
            lines.append("")
            for c in gap["per_course"]:
                mark = "!!" if c["overdue"] else (" *" if c["open"] else "  ")
                lines.append(
                    " {} {:<46} {}/{}".format(mark, c["course"][:46], c["done"], c["total"])
                )
            if not (gap["urgent"] or gap["soon"]):
                lines.append("  (مورد بازی ثبت نشده است)")
            text = "\n".join(lines)
        emit(text, args.out)
        return 0

    if args.command == "brief":
        from . import brief as briefmod

        work_root = Path(args.work) if args.work else (data_dir.parent / "work")
        candidates = briefmod.open_items(assignments, now_epoch, args.course)

        if args.cmid:
            chosen = [a for a in assignments if str(a.cmid) == str(args.cmid)]
            if not chosen:
                raise CwError(
                    "no assignment with cmid={} in the store".format(args.cmid)
                )
        elif len(candidates) == 1:
            chosen = candidates
        elif not candidates:
            raise CwError(
                "nothing outstanding to brief. Check `cwtrack gaps`, or pass "
                "--cmid to work on a specific assignment anyway."
            )
        else:
            lines = ["چند مورد باز دارید. کدام را بریف کنم؟", ""]
            lines += [
                "  [{}] {} — {}   ({})".format(
                    i, a.name, a.course, briefmod.remaining_text(a.due, now_epoch)
                )
                for i, a in enumerate(candidates, 1)
            ]
            lines += [
                "",
                "  با --cmid <عدد> یک مورد مشخص را انتخاب کنید",
                "  فهرست کامل:  cwtrack open",
            ]
            emit("\n".join(lines), args.out)
            return 0

        results = []
        for a in chosen:
            course_meta = {"title": a.course, "term": a.term}
            folder, written = briefmod.build_workfolder(
                a.__dict__, course_meta, data_dir, work_root, now_epoch, overwrite=args.force
            )
            results.append((a, folder, written))

        if args.json:
            text = json.dumps(
                [
                    {"cmid": a.cmid, "name": a.name, "folder": str(folder),
                     "written": [p.name for p in written]}
                    for a, folder, written in results
                ],
                ensure_ascii=False, indent=2,
            )
        else:
            lines = []
            for a, folder, written in results:
                lines.append("بریف ساخته شد: {}".format(folder.resolve()))
                lines.append(
                    "  {}".format(", ".join(p.name for p in written)) if written
                    else "  (از قبل وجود داشت؛ تغییری نکرد. --force برای بازنویسی)"
                )
                lines.append("  منابع: {}".format(
                    briefmod.course_materials_dir(data_dir, a.course_id).resolve()))
                lines.append("")
            text = "\n".join(lines)
        emit(text, args.out)
        return 0

    if args.command == "ui":
        from . import dashboard

        # Material counts are read from disk here rather than from the store, so a
        # file you just dropped into a course folder shows up on the next `ui` run
        # without needing a `store` refresh.
        mats = {}
        for cid_dir in (data_dir / "courses").glob("*"):
            if not cid_dir.is_dir():
                continue
            try:
                cid = int(cid_dir.name)
            except ValueError:
                continue
            mats[cid] = tracker.scan_materials(cid_dir / "materials")

        page = dashboard.build(user, assignments, gap, now, now_epoch, materials=mats)
        out = Path(args.out) if args.out else data_dir / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page, encoding="utf-8")
        print("نوشته شد: {}".format(out.resolve()))
        with contextlib.suppress(AttributeError, OSError):
            os.startfile(str(out.resolve()))  # noqa: S606 - opens the local page
        return 0

    if not assignments:
        raise CwError(
            "store is empty ({}). Run `cwtrack fetch` first, or point --data at an "
            "existing cw-data folder.".format(data_dir.resolve()))

    rows = [a.__dict__ for a in assignments]
    local = match_local(rows, Path(args.local)) if args.local else {}

    if args.command == "open":
        picked = [a for a in assignments if a.bucket in OPEN_BUCKETS]
        if args.days:
            picked = [
                a for a in picked
                if a.due is not None and 0 < a.due - now_epoch <= args.days * 86400
            ]
        if args.json:
            text = json.dumps([a.__dict__ for a in picked], ensure_ascii=False, indent=2)
        else:
            text = table([a.__dict__ for a in picked], now_epoch, local)
            text += "\n\n{} مورد باز".format(len(picked))
        emit(text, args.out)
        return 0

    emit(report(rows, local, now), args.out)
    return 0
