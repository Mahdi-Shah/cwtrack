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
import warnings
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
            "material", "brief", "connect", "study", "account", "resource",
            "relation", "work",
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


def _selection(items: list[dict], prompt: str, *, multiple: bool = False) -> list[dict] | None:
    if not items:
        print("موردی برای انتخاب وجود ندارد.")
        return None
    raw = input(prompt).strip()
    if raw.casefold() in {"q", "لغو"}:
        return None
    try:
        indexes = [int(part.strip()) for part in raw.split(",")]
    except ValueError:
        print("شمارهٔ انتخاب را وارد کن؛ برای لغو q بنویس.")
        return None
    if not multiple and len(indexes) != 1:
        print("فقط یک شماره انتخاب کن.")
        return None
    if len(set(indexes)) != len(indexes) or any(index < 1 or index > len(items) for index in indexes):
        print("شمارهٔ انتخاب‌شده در فهرست نیست یا تکراری است.")
        return None
    return [items[index - 1] for index in indexes]


def _show_study_inventory(view: dict) -> None:
    classes = view.get("classes", [])
    if not classes:
        print("فهرست کلاس‌های دریافت‌شده خالی است. ابتدا درس‌های سامانه را تازه‌سازی کن.")
        return
    state_labels = {"current": "جاری", "archived": "بایگانی‌شده", "unknown": "نامشخص"}
    for index, item in enumerate(classes, 1):
        offering = item.get("offering") or {}
        tracking = item.get("tracking") or {}
        platform = {"cw": "CW شریف", "quera": "کوئرا"}.get(item.get("platform"), item.get("platform", "سامانه"))
        mapped = offering.get("title") or "بی‌نگاشت"
        state = state_labels.get(tracking.get("state"), "نامشخص")
        term = offering.get("term") or tracking.get("term") or "ترم نامشخص"
        print("  [{}] {} · {} · {} · {} · {}".format(
            index, platform, item.get("title") or "کلاس بدون عنوان", mapped, term, state
        ))
    print("شناسه‌های داخلی برای جلوگیری از اشتباه در انتخاب نمایش داده نمی‌شوند.")


def _study_management(data: str) -> int:
    if not sys.stdin.isatty():
        raise CwError("مدیریت درس‌ها به ترمینال تعاملی نیاز دارد.")
    while True:
        view = api.study_view(data=data)
        print("\nمدیریت کلاس‌ها و درس‌های نیم‌سال")
        _show_study_inventory(view)
        print("\n[1] پیوند کلاس به درس · [2] تغییر وضعیت نیم‌سال · [q] پایان")
        action = input("انتخاب: ").strip().casefold()
        if action in {"q", "quit", "خروج"}:
            return 0
        classes = view.get("classes", [])
        revision = view.get("catalog_revision", 0)
        if action == "1":
            linkable_classes = [
                item for item in classes
                if item.get("observed_in_latest_class_list", True)
            ]
            print("برای نگاشت فقط کلاس‌های دیده‌شده در فهرست موفق اخیر را انتخاب کن:")
            _show_study_inventory({"classes": linkable_classes})
            selected = _selection(linkable_classes, "شمارهٔ کلاس‌ها برای پیوند (با ویرگول جدا کن): ", multiple=True)
            if not selected:
                continue
            offerings = view.get("offerings", [])
            print("درس‌های ثبت‌شده:")
            for index, item in enumerate(offerings, 1):
                suffix = " · {}".format(item.get("term")) if item.get("term") else ""
                print("  [{}] {}{}".format(index, item.get("title", "درس بدون عنوان"), suffix))
            print("  [0] ساخت درسِ نیم‌سال تازه")
            choice = input("شمارهٔ درس: ").strip()
            if choice == "0":
                title = input("نام درس: ").strip()
                term = input("نیم‌سال (اختیاری): ").strip()
                if not title:
                    print("نام درس نمی‌تواند خالی باشد.")
                    continue
                offering = {"title": title, "term": term}
            else:
                try:
                    offering = offerings[int(choice) - 1]
                except (ValueError, IndexError):
                    print("شمارهٔ درس معتبر نیست.")
                    continue
                offering = {key: offering[key] for key in ("id", "title", "term") if key in offering}
            result = api.course_link(
                [item["ref"] for item in selected], offering,
                expected_revision=revision, data=data,
            )
            if result.get("status") == "conflict":
                answer = input("برخی کلاس‌ها به درس دیگری پیوند دارند. جایگزین شود؟ [y/N]: ").strip().casefold()
                if answer not in {"y", "yes", "بله"}:
                    print("پیوند قبلی حفظ شد.")
                    continue
                result = api.course_link(
                    [item["ref"] for item in selected], offering,
                    expected_revision=result.get("revision", revision),
                    data=data, replace_existing=True,
                )
            print("نتیجهٔ پیوند: {}".format(result.get("status", "نامشخص")))
        elif action == "2":
            selected = _selection(classes, "شمارهٔ کلاس‌ها برای تغییر وضعیت (با ویرگول جدا کن): ", multiple=True)
            if not selected:
                continue
            print("[1] جاری · [2] بایگانی‌شده · [3] نامشخص")
            state_choice = input("وضعیت: ").strip()
            state = {"1": "current", "2": "archived", "3": "unknown"}.get(state_choice)
            if state is None:
                print("وضعیت معتبر نیست.")
                continue
            new_term = input("نام نیم‌سال (Enter برای نگه‌داشتن مقدار فعلی): ").strip()
            current_revision = revision
            for item in selected:
                old_tracking = item.get("tracking") or {}
                old_offering = item.get("offering") or {}
                term = new_term or old_tracking.get("term") or old_offering.get("term")
                result = api.class_tracking(
                    item["ref"], state, expected_revision=current_revision,
                    term=term, data=data,
                )
                print("{}: {}".format(item.get("title") or "کلاس", result.get("status", "نامشخص")))
                if result.get("status") != "ok":
                    break
                current_revision = result.get("revision", current_revision)
        else:
            print("انتخاب معتبر نیست.")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_streams()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    domain_commands = {"account", "resource", "relation", "work", "study"}
    if raw_argv and raw_argv[0] in domain_commands and any(
        flag in {"-h", "--help"} for flag in raw_argv[1:]
    ):
        from .cli_domain import run as run_domain
        return run_domain(raw_argv[0], raw_argv[1:])
    parser = build_parser()
    args, extra = parser.parse_known_args(raw_argv)
    if extra and args.command not in domain_commands:
        parser.error("آرگومان ناشناخته: {}".format(" ".join(extra)))
    base_dir = Path(args.home)
    dump = base_dir / "dump"
    client = Client(args.base)

    if args.command in {"account", "resource", "relation", "work"}:
        from .cli_domain import run as run_domain
        return run_domain(args.command, extra, default_data=args.data, default_home=args.home, default_json=args.json)

    if args.command == "connect":
        if not sys.stdin.isatty():
            raise CwError("برای گرفتن رمز به‌صورت مخفی، cwtrack را در ترمینال تعاملی اجرا کنید.")
        label = input("نام محلی اتصال CW: ").strip()
        username = ask("نام کاربری CW: ")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                password = getpass.getpass("رمز عبور CW (ورودی مخفی): ")
        except getpass.GetPassWarning as exc:
            raise CwError("ترمینال امکان گرفتن مخفی رمز را ندارد؛ اطلاعات ورود ذخیره نشد.") from exc
        if not password:
            raise CwError("رمز خالی است؛ اطلاعات ورود ذخیره نشد.")
        result = api.access_configure(
            "cw", {"username": username, "password": password}, home=base_dir,
            label=label or None,
        )
        if result.get("status") != "ok":
            raise CwError("اتصال CW ذخیره نشد: {}".format(result.get("status", "unavailable")))
        print("اتصال CW در ذخیره‌ساز امن ویندوز ثبت شد.")
        return 0

    if args.command == "study":
        from .cli_domain import run as run_domain
        return run_domain("study", extra, default_data=args.data, default_home=args.home, default_json=args.json)

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
