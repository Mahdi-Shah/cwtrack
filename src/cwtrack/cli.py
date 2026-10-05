"""Command-line entry point.

A human-facing wrapper. Every answer it prints comes from `cwtrack.api`, which is
also what the skill calls, so the two can never drift into disagreeing about what is
outstanding. What the CLI adds is the three things the API deliberately refuses to do:
prompting for the captcha, opening the dashboard, and writing to a file for a console
that cannot show Persian.
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import json
import os
import sys
from pathlib import Path

from . import api
from .auth import ask, do_login
from .client import DEFAULT_BASE, Client, CwError
from .fetch import fetch_all
from .paths import STATE_DIR


def _force_utf8_streams() -> None:
    """Make the Persian output survive a stock Windows console.

    A default Windows console is cp1252, which has no Persian letters, so every
    message in this tool would raise UnicodeEncodeError on its way out. Reconfiguring
    the streams fixes pipes and files. An *interactive* console that still shows
    mojibake is the terminal's own codepage and needs `chcp 65001` - not something
    this program can fix - which is why `-o` exists.

    Done in a function rather than at import so that importing the package does not
    mutate global state: a library that silently reconfigures a caller's stdout is
    a nuisance to debug.
    """
    for stream in (sys.stdout, sys.stderr):
        # Older streams and already-detached ones have nothing to reconfigure.
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8", errors="replace")


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
    _force_utf8_streams()
    args = build_parser().parse_args(argv)
    base_dir = Path(args.home)
    dump = base_dir / "dump"
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
        summary = api.ingest(dump, args.data)
        print("ذخیره شد: {} درس، {} تکلیف در {}".format(
            summary["courses"], summary["assignments"], summary["store"]))
        return 0

    if args.command == "store":
        summary = api.ingest(dump, args.data)
        print("ذخیره شد: {} درس، {} تکلیف".format(
            summary["courses"], summary["assignments"]))
        return 0

    # ---- everything below reads the store, not the network ------------------
    # api raises CwError on a missing or empty store. That is the point: a caller
    # that got zeros would report "you have no homework" when the truth is that it
    # looked in the wrong place.
    store = args.data

    if args.command == "material":
        if not args.course:
            raise CwError("--course <id> is required for the material command")
        info = api.materials_text(store, args.course)
        lines = [
            "منابع این درس را اینجا بگذارید:",
            "  {}".format(info["folder"]),
            "",
            "-" * 60,
            "در حال حاضر {} فایل:".format(info["count"]),
        ]
        lines += [
            "  {:>10}  {:<8}  {}".format("{:,}".format(m["bytes"]), m["kind"], m["name"])
            for m in info["materials"]
        ]
        if not info["materials"]:
            lines.append("  (خالی)")
        emit("\n".join(lines), args.out)
        return 0

    if args.command == "gaps":
        if args.json:
            text = json.dumps(api.status(store), ensure_ascii=False, indent=2, default=str)
        else:
            text = api.gaps_text(store)
        emit(text, args.out)
        return 0

    if args.command == "open":
        if args.json:
            picked = api.outstanding(store, args.course or None, args.days or None)
            text = json.dumps(picked, ensure_ascii=False, indent=2, default=str)
        else:
            text = api.open_text(store, args.days or None, args.local or None)
        emit(text, args.out)
        return 0

    if args.command == "brief":
        result = api.make_brief(
            cmid=args.cmid or None,
            course=args.course or None,
            data=store,
            work=args.work or None,
            force=args.force,
        )
        if args.json:
            emit(json.dumps(result, ensure_ascii=False, indent=2, default=str), args.out)
            return 0

        if result["status"] == "needs_choice":
            lines = ["چند مورد باز دارید. کدام را بریف کنم؟", ""]
            lines += [
                "  [{}] {} — {}   ({})".format(
                    i, c["name"], c["course"], c["remaining"])
                for i, c in enumerate(result["candidates"], 1)
            ]
            lines += [
                "",
                "  با --cmid <عدد> یک مورد مشخص را انتخاب کنید",
                "  فهرست کامل:  cwtrack open",
            ]
            emit("\n".join(lines), args.out)
            return 0

        if result["status"] == "nothing_outstanding":
            raise CwError(
                "nothing outstanding to brief. Check `cwtrack gaps`, or pass "
                "--cmid to work on a specific assignment anyway."
            )

        lines = []
        for b in result["briefs"]:
            lines.append("بریف ساخته شد: {}".format(b["folder"]))
            lines.append(
                "  {}".format(", ".join(b["written"])) if b["written"]
                else "  (از قبل وجود داشت؛ تغییری نکرد. --force برای بازنویسی)"
            )
            lines.append("  منابع: {}".format(b["source"]))
            lines.append("")
        emit("\n".join(lines), args.out)
        return 0

    if args.command == "ui":
        target = api.build_dashboard(store, args.out or None)
        print("نوشته شد: {}".format(target))
        # Opening the page is a CLI privilege. api.build_dashboard deliberately does
        # not, so that a skill can decide what "showing" the user means.
        with contextlib.suppress(AttributeError, OSError):
            os.startfile(str(target))  # noqa: S606 - opens the local page
        return 0

    emit(api.report_text(store, args.local or None), args.out)
    return 0
