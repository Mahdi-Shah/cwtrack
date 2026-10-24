"""Human and file-driven CLI for the cross-platform coursework domains.

Payloads that may contain assignment text, answers, credentials, or evidence are
read from protected prompts or JSON files. They are never accepted as argv text.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import api
from .client import CwError
from .dates import SITE_TZ_OFFSET, gregorian_to_jalali

_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _read_input(path: str | None) -> dict:
    if not path:
        if not sys.stdin.isatty():
            raise CwError("این عملیات به --input-file با یک شیء JSON نیاز دارد.")
        print("اطلاعات حساس و متن پاسخ را در آرگومان فرمان ننویس؛ یک فایل JSON انتخاب کن.")
        path = input("مسیر فایل JSON ورودی: ").strip()
        if not path:
            raise CwError("مسیر فایل ورودی وارد نشد.")
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CwError("خواندن JSON ورودی ناموفق بود: {}".format(exc)) from exc
    if not isinstance(value, dict):
        raise CwError("ریشهٔ فایل ورودی باید یک شیء JSON باشد.")
    return value


def _emit(value, *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
        return
    if isinstance(value, dict):
        status = value.get("status", "ok")
        print("وضعیت: {}".format(status))
        for key in ("message", "stage", "revision", "missing", "extraction_status", "extracted_path"):
            if key in value:
                print("{}: {}".format(key, value[key]))
        failure_labels = {
            "transport_error": "خطای ارتباط با سامانه",
            "authentication_required": "ورود دوباره لازم است",
            "parser_error": "خطا هنگام خواندن صفحه",
            "unexpected_response": "ساختار پاسخ سامانه شناخته نشد",
        }
        if "targets" in value:
            for item in value["targets"]:
                platform = {"cw": "CW شریف", "quera": "کوئرا"}.get(
                    item.get("platform"), item.get("platform", "سامانه")
                )
                print("  {}: {}".format(platform, item.get("status", "نامشخص")))
                for kind, count in item.get("assignment_failure_counts", {}).items():
                    if kind in failure_labels:
                        print("    تکلیف‌ها: {} · {} مورد".format(failure_labels[kind], count))
                if item.get("status") in {"challenge_required", "challenge_unavailable"}:
                    if item.get("platform") == "quera":
                        print("    کوئرا در مرورگر: https://quera.org/accounts/login")
                        print("    تکمیل challenge در مرورگر، نشست API محلی را وارد نمی‌کند.")
                    print("    عملیات متوقف شد؛ ادامهٔ خودکار انجام نمی‌شود.")
        for action in value.get("actions", []):
            if action.get("status") == "challenge_unavailable" and action.get("guidance"):
                print("راهنما: {}".format(action["guidance"]))
        return
    if isinstance(value, list):
        for item in value:
            print(json.dumps(item, ensure_ascii=False, default=str))
    else:
        print(value)


def _study_report_text(view: dict) -> str:
    """Render the shared projection with source, delivery state, and freshness."""
    lines = [
        "نمای مشترک درس‌ها و تکالیف",
        "کلاس‌ها: {} · تکلیف‌های سامانه: {}".format(
            len(view.get("classes", [])), len(view.get("platform_assignments", []))
        ),
    ]
    platform_names = {"cw": "CW شریف", "quera": "کوئرا"}
    labels = {
        item.get("connection_id"): item.get("label")
        for item in view.get("connections", [])
    }
    freshness = {
        (item.get("connection_id"), item.get("class_ref", {}).get("class_id")): item
        for item in view.get("assignment_observations", [])
    }
    assignment_counts = {}
    assignments_by_class = {}
    for assignment in view.get("platform_assignments", []):
        assignment_counts[assignment.get("platform", "unknown")] = (
            assignment_counts.get(assignment.get("platform", "unknown"), 0) + 1
        )
        ref = assignment.get("ref") or {}
        class_key = (ref.get("connection_id"), ref.get("class_id"))
        assignments_by_class[class_key] = assignments_by_class.get(class_key, 0) + 1
    lines.append("تکلیف به تفکیک سامانه: {}".format(
        " · ".join(
            "{} {}".format(platform_names.get(platform, platform), count)
            for platform, count in sorted(assignment_counts.items())
        ) or "داده‌ای ثبت نشده"
    ))
    lines.append("تازگی اتصال‌ها:")
    for item in view.get("connections", []):
        label = labels.get(item.get("connection_id")) or platform_names.get(item.get("platform"), "اتصال")
        lines.append("  {} · تلاش: {} ({}) · موفق: {} ({})".format(
            label, item.get("last_attempt_at") or "ندارد",
            item.get("last_attempt_status") or "نامشخص",
            item.get("last_success_at") or "ندارد",
            item.get("last_success_coverage") or "نامشخص",
        ))

    classes_by_ref = {
        (item.get("ref", {}).get("connection_id"), item.get("ref", {}).get("class_id")): item
        for item in view.get("classes", [])
    }
    lines.append("وضعیت کلاس‌ها:")
    for item in view.get("classes", []):
        platform = platform_names.get(item.get("platform"), item.get("platform", "سامانه"))
        offering = item.get("offering") or {}
        tracking = item.get("tracking") or {}
        ref = item.get("ref") or {}
        source = labels.get(ref.get("connection_id")) or platform
        observed = freshness.get((ref.get("connection_id"), ref.get("class_id")), {})
        lines.append("  {} · {} · درس نیم‌سال: {} · پیگیری: {} · دریافت تکلیف: {} / {}".format(
            source, item.get("title", "کلاس"), offering.get("title", "بی‌نگاشت"),
            tracking.get("state", "unknown"),
            observed.get("last_attempt_status", "ندارد"),
            observed.get("last_success_coverage", "ندارد"),
        ))
        class_key = (ref.get("connection_id"), ref.get("class_id"))
        attempt = observed.get("last_attempt_at") or "ثبت نشده"
        success = observed.get("last_success_at") or "ثبت نشده"
        count = assignments_by_class.get(class_key, 0)
        lines.append("    آخرین تلاش: {} · آخرین دریافت موفق: {} · تکلیف‌های مشاهده‌شده: {}".format(
            attempt, success, count,
        ))
        if (
            observed.get("last_success_at")
            and observed.get("last_attempt_at")
            and observed["last_success_at"] < observed["last_attempt_at"]
        ):
            lines.append("    دادهٔ تکلیف از آخرین دریافت موفق است و ممکن است کهنه باشد.")
        failure_labels = {
            "transport_error": "خطای ارتباط",
            "authentication_required": "ورود دوباره لازم است",
            "parser_error": "خطای خواندن صفحه",
            "unexpected_response": "پاسخ با ساختار ناشناخته",
        }
        failure_kind = observed.get("failure_kind")
        if failure_kind in failure_labels:
            lines.append("    علت تلاش اخیر: {}".format(failure_labels[failure_kind]))

    lines.append("تکلیف‌ها:")
    for item in view.get("platform_assignments", []):
        ref = item.get("ref") or {}
        class_item = classes_by_ref.get((ref.get("connection_id"), ref.get("class_id")), {})
        course = (class_item.get("offering") or {}).get("title") or class_item.get("title") or item.get("course") or "درس نامشخص"
        source = labels.get(ref.get("connection_id")) or platform_names.get(item.get("platform"), "سامانه")
        submission = item.get("submission") or {}
        state = submission.get("state") or "نامشخص"
        state_key = str(state).strip().casefold()
        state = {
            "unknown": "نامشخص؛ سامانه وضعیت تحویل را گزارش نکرد",
            "no submissions have been made yet": "ارسالی ثبت نشده",
            "submitted for grading": "برای تصحیح تحویل داده شده",
        }.get(state_key, state)
        deadlines = item.get("deadlines", [])
        due = next((deadline.get("at") for deadline in deadlines
                    if isinstance(deadline, dict) and deadline.get("kind") in {"regular", "normal"} and deadline.get("at")), None)
        if due is None:
            due = "مهلت ثبت نشده"
        else:
            try:
                due_at = datetime.fromisoformat(due.replace("Z", "+00:00"))
                site_timezone = timezone(timedelta(seconds=SITE_TZ_OFFSET))
                local_due = due_at.astimezone(site_timezone)
                jalali = gregorian_to_jalali(local_due.date())
                if jalali:
                    due = "{:04d}/{:02d}/{:02d} {:02d}:{:02d}".format(
                        *jalali, local_due.hour, local_due.minute
                    ).translate(_PERSIAN_DIGITS)
                else:
                    due = local_due.strftime("%Y-%m-%d %H:%M")
            except (AttributeError, TypeError, ValueError, OverflowError):
                due = str(due)
        lines.append("  {} · {} · {} · وضعیت تحویل: {} · مهلت: {}".format(
            source, course, item.get("title", "بدون عنوان"), state, due
        ))
    return "\n".join(lines)


def _parser(command: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cwtrack {}".format(command))
    parser.add_argument("--data", default="")
    parser.add_argument("--home", default=None)
    parser.add_argument("--work", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--input-file")
    parser.add_argument("--platform", choices=("cw", "quera"))
    parser.add_argument("--connection", help="نام محلی اتصال؛ شناسهٔ داخلی لازم نیست")
    parser.add_argument("--id", help="شناسهٔ رکورد Work یا گروه")
    parser.add_argument("--revision", type=int)
    return parser


def run(
    command: str, argv: list[str], *, default_data: str = "",
    default_home: str | None = None, default_json: bool = False,
) -> int:
    """Run one domain command while retaining the legacy top-level CLI."""
    parser = _parser(command)
    if command == "account":
        parser.add_argument("action", choices=("list", "connect", "update", "rename", "forget"), nargs="?", default="list")
    elif command == "study":
        parser.add_argument("action", choices=("view", "report", "refresh", "manage", "continue"), nargs="?", default="manage")
    elif command == "resource":
        parser.add_argument("action", choices=("view", "attach", "capture", "detach", "update"))
    elif command == "relation":
        parser.add_argument("action", choices=("list", "add"), nargs="?", default="list")
    elif command == "work":
        parser.add_argument("action", choices=("list", "get", "start", "group-start", "group-get", "save", "sync", "finish"))
    args = parser.parse_args(argv)
    data = args.data or default_data
    home = args.home or default_home
    args.json = args.json or default_json

    if command == "account":
        if args.action == "list":
            inventory = api.access_view(home=home)
            if args.json:
                _emit(inventory, as_json=True)
                return 0
            if not args.json:
                for index, item in enumerate(inventory.get("connections", []), 1):
                    print("  [{}] {} · {} · {}".format(index, item["platform"], item["label"], item["state"]))
            return 0
        if not sys.stdin.isatty():
            raise CwError("مدیریت اتصال به ترمینال تعاملی نیاز دارد.")
        if args.action == "connect":
            platform = args.platform or input("سامانه (cw/quera): ").strip().casefold()
            label = args.connection or input("نام محلی اتصال: ").strip()
            username = input("نام کاربری: ").strip()
            password = getpass.getpass("رمز عبور (ورودی مخفی): ")
            if not label or not username or not password:
                raise CwError("نام اتصال و اطلاعات ورود نمی‌توانند خالی باشند.")
            result = api.access_configure(
                platform, {"username": username, "password": password}, home=home, label=label
            )
            visible = {"status": result.get("status"), "platform": platform, "label": label}
            _emit(visible, as_json=args.json)
            return 0 if result.get("status") == "ok" else 1
        if args.action == "update":
            label = args.connection or input("نام محلی اتصال: ").strip()
            username = input("نام کاربری همان حساب: ").strip()
            password = getpass.getpass("رمز تازه (ورودی مخفی): ")
            if not username or not password:
                raise CwError("اطلاعات ورود نمی‌توانند خالی باشند.")
            result = api.access_update_named(
                label, {"username": username, "password": password}, home=home
            )
            _emit({"status": result.get("status"), "label": label}, as_json=args.json)
            return 0 if result.get("status") == "ok" else 1
        if args.action == "rename":
            old = args.connection or input("نام فعلی اتصال: ").strip()
            new = input("نام تازهٔ اتصال: ").strip()
            result = api.access_rename(old, new, home=home)
            _emit(result, as_json=args.json)
            return 0 if result.get("status") == "ok" else 1
        label = args.connection or input("نام اتصال برای فراموش‌کردن: ").strip()
        if input("اطلاعات ورود و نشست اتصال «{}» پاک شود؟ [y/N] ".format(label)).strip().casefold() not in {"y", "yes", "بله"}:
            print("عملیات لغو شد.")
            return 1
        result = api.access_forget_named(label, home=home)
        _emit(result, as_json=args.json)
        return 0 if result.get("status") == "ok" else 1

    if command == "study":
        if args.action == "manage":
            from .cli import _study_management
            return _study_management(data)
        if args.action == "view":
            _emit(api.study_view(data=data), as_json=args.json)
            return 0
        if args.action == "report":
            view = api.study_view(data=data)
            if args.json:
                _emit(view, as_json=True)
            else:
                print(_study_report_text(view))
            return 0
        if args.action == "continue":
            if not sys.stdin.isatty():
                raise CwError("ادامهٔ challenge به ورودی امن ترمینال نیاز دارد.")
            pending = api.study_challenges(home=home).get("challenges", [])
            if args.connection:
                pending = [item for item in pending if item.get("label") == args.connection]
            if not pending:
                print("challenge معلقی برای این اتصال پیدا نشد.")
                return 1
            if len(pending) == 1:
                selected = pending[0]
            else:
                for index, item in enumerate(pending, 1):
                    print("  [{}] {} · {} · {} · {}".format(index, item.get("platform"), item.get("label"), item.get("scope"), item.get("kind")))
                try:
                    selected = pending[int(input("شمارهٔ challenge: ").strip()) - 1]
                except (ValueError, IndexError) as exc:
                    raise CwError("انتخاب challenge معتبر نیست.") from exc
            if selected.get("kind") == "interactive":
                print("کوئرا را در مرورگر باز کن: https://quera.org/accounts/login")
                print("حل challenge مرورگر نشست API محلی را احراز نمی‌کند؛ دریافت خودکار متوقف است.")
                return 1
            print(selected.get("display", "کد challenge را وارد کن."))
            answer = input("پاسخ challenge: ").strip()
            if not answer:
                raise CwError("پاسخ خالی است؛ challenge ادامه نیافت.")
            result = api.study_continue(
                selected["continuation_id"],
                {"kind": selected["kind"], "value": answer},
                home=home, data=data,
            )
            _emit(result, as_json=args.json)
            return 0 if result.get("status") == "ok" else 1
        labels = [args.connection] if args.connection else None
        platforms = [args.platform] if args.platform else None
        result = api.study_refresh(platforms, data=data, home=home, connection_labels=labels)
        _emit(result, as_json=args.json)
        return 0 if result.get("status") == "ok" else 1

    if command == "resource":
        payload = _read_input(args.input_file) if args.action != "view" or args.input_file else {}
        if args.action == "view":
            result = api.resource_view(target=payload.get("target"), data=data)
        elif args.action == "attach":
            result = api.resource_attach(payload.get("spec_or_id"), to=payload.get("to", {}), extent=payload.get("extent"), data=data)
        elif args.action == "capture":
            result = api.resource_capture(payload.get("resource_id", ""), extent=payload.get("extent", {}), data=data)
        elif args.action == "detach":
            if not sys.stdin.isatty() or input("این پیوند منبع غیرفعال شود؟ [y/N] ").strip().casefold() not in {"y", "yes", "بله"}:
                print("عملیات لغو شد.")
                return 1
            result = api.resource_detach(payload.get("binding_id", ""), expected_revision=payload.get("expected_revision", -1), data=data)
        else:
            result = api.resource_update(payload.get("resource_id", ""), payload.get("replacement", {}), expected_revision=payload.get("expected_revision", -1), data=data)
        _emit(result, as_json=args.json)
        return 0 if result.get("status") in {"ok", "captured", "needs_extraction"} else 1

    if command == "relation":
        if args.action == "list":
            _emit(api.study_view(data=data).get("assignment_relations", []), as_json=args.json)
            return 0
        payload = _read_input(args.input_file)
        result = api.assignment_relate(
            payload.get("task_refs", []), payload.get("reason", ""),
            expected_revision=payload.get("expected_revision", -1), data=data,
            relation_type=payload.get("relation_type", "related"),
        )
        _emit(result, as_json=args.json)
        return 0 if result.get("status") == "ok" else 1

    if command == "work":
        if args.action == "list":
            result = api.work_list(data=data, work=args.work)
        elif args.action == "get":
            if not args.id:
                raise CwError("برای work get شناسهٔ رکورد لازم است.")
            result = api.work_get(args.id, revision=args.revision, data=data, work=args.work)
        elif args.action in {"start", "group-start"}:
            payload = _read_input(args.input_file)
            result = api.work_start(payload, data=data, work=args.work) if args.action == "start" else api.work_group_start(payload.get("requests", []), data=data, work=args.work)
        elif args.action == "group-get":
            if not args.id:
                raise CwError("برای work group-get شناسهٔ گروه لازم است.")
            result = api.work_group_get(args.id, data=data, work=args.work)
        else:
            if not args.id:
                raise CwError("برای تغییر Work شناسهٔ رکورد لازم است.")
            payload = _read_input(args.input_file)
            revision = payload.get("expected_revision", args.revision)
            if revision is None:
                raise CwError("expected_revision را در JSON یا با --revision تعیین کن.")
            if args.action == "save":
                result = api.work_save(args.id, payload.get("progress", {}), expected_revision=revision, data=data, work=args.work)
            elif args.action == "sync":
                result = api.work_sync(args.id, payload.get("received_input", {}), expected_revision=revision, data=data, work=args.work)
            else:
                if not sys.stdin.isatty() or input("خروجی و وضعیت بررسی در Work ثبت شود؟ [y/N] ").strip().casefold() not in {"y", "yes", "بله"}:
                    print("عملیات لغو شد.")
                    return 1
                result = api.work_finish(args.id, payload.get("delivery", {}), expected_revision=revision, data=data, work=args.work)
        _emit(result, as_json=args.json)
        status = result.get("status") if isinstance(result, dict) else "ok"
        return 0 if status in {"ok", "ready_for_student_review", "needs_completion", "partial"} else 1
    return 2
