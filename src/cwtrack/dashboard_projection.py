"""Pure view-model projections for the local dashboard."""

from __future__ import annotations

from datetime import datetime, timezone

WORK_STAGE_FA = {
    "ready_to_start": "آمادهٔ شروع",
    "in_progress": "در حال انجام",
    "under_verification": "در حال بررسی",
    "needs_completion": "نیازمند تکمیل",
    "ready_for_student_review": "آمادهٔ بررسی دانشجو",
}


SUBMISSION_LABELS = {
    "not_submitted": ("ارسال نشده", "todo"),
    "not submitted": ("ارسال نشده", "todo"),
    "no submission": ("ارسال نشده", "todo"),
    "open": ("باز؛ منتظر ارسال", "todo"),
    "draft": ("پیش‌نویس", "todo"),
    "overdue": ("مهلت گذشته؛ ارسال نشده", "overdue"),
    "closed": ("مهلت بسته شده؛ وضعیت تحویل را بررسی کن", "overdue"),
    "submitted": ("ارسال شده", "done"),
    "submitted for grading": ("ارسال شده؛ در انتظار ارزیابی", "done"),
    "sent for grading": ("ارسال شده؛ در انتظار ارزیابی", "done"),
    "sent for marking": ("ارسال شده؛ در انتظار ارزیابی", "done"),
    "graded": ("ارزیابی شده", "done"),
    "accepted": ("پذیرفته شده", "done"),
    "rejected": ("نیازمند اصلاح", "todo"),
    "ارسال نشده": ("ارسال نشده", "todo"),
    "ارسال‌نشده": ("ارسال نشده", "todo"),
    "ارسال شده": ("ارسال شده", "done"),
    "ارسال‌شده": ("ارسال شده", "done"),
    "تحویل شده": ("ارسال شده", "done"),
    "تحویل‌شده": ("ارسال شده", "done"),
    "مهلت گذشته": ("مهلت گذشته؛ ارسال نشده", "overdue"),
}


def _task_key(ref: dict) -> tuple:
    return tuple(
        ref.get(key)
        for key in ("connection_id", "class_id", "assignment_id", "question_id")
    )


def _due_epoch(value) -> int | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except (ValueError, OverflowError, OSError):
        return None


def _legacy_platform_assignments(assignments: list, study: dict, refreshed: str) -> list[dict]:
    """Adapt legacy CW tasks, linking only a unique exact CW class identifier."""
    classes_by_id: dict[str, list[dict]] = {}
    for item in study.get("classes", []):
        if (
            item.get("platform") == "cw"
            and item.get("observed_in_latest_class_list", True)
        ):
            classes_by_id.setdefault(str(item.get("ref", {}).get("class_id")), []).append(item)
    known = {
        (
            str(item.get("class_ref", {}).get("class_id")),
            str(item.get("ref", {}).get("assignment_id")),
        )
        for item in study.get("platform_assignments", [])
        if item.get("platform") == "cw"
    }
    rows = []
    for item in assignments:
        class_id, assignment_id = str(item.course_id), str(item.cmid)
        matches = classes_by_id.get(class_id, [])
        matched_class = matches[0] if len(matches) == 1 else None
        if matched_class and (class_id, assignment_id) in known:
            continue
        connection_id = (
            matched_class.get("ref", {}).get("connection_id")
            if matched_class else "cw-legacy"
        )
        ref = {
            "connection_id": connection_id,
            "class_id": class_id,
            "assignment_id": assignment_id,
        }
        deadlines = []
        if item.due:
            try:
                deadline = datetime.fromtimestamp(item.due, timezone.utc).isoformat()
            except (OverflowError, OSError, ValueError):
                deadline = ""
            if deadline:
                deadlines.append({"kind": "regular", "at": deadline, "raw": item.due_text})
        rows.append({
            "kind": "assignment",
            "ref": ref,
            "class_ref": {key: ref[key] for key in ("connection_id", "class_id")},
            "title": item.name,
            "course_title": item.course,
            "url": item.url,
            "platform": "cw",
            "submission": {
                "state": item.status_text or "unknown",
                "raw": item.status_text or "",
            },
            "evaluation": {
                "state": "graded" if item.grade and item.grade != "-" else "unknown",
                "grade": item.grade or None,
            },
            "deadlines": deadlines,
            "last_success_at": refreshed or "",
            "legacy_course_id": item.course_id,
            "legacy_assignment_id": item.cmid,
            "legacy_link_status": (
                "linked" if matched_class
                else "ambiguous" if len(matches) > 1
                else "unmatched"
            ),
        })
    return rows


def _submission_presentation(platform: str, submission: dict) -> tuple[str, str, str, str]:
    state = str(submission.get("state") or "unknown").strip()
    raw = str(submission.get("raw") or "").strip()
    canonical = state.casefold()
    if canonical in {"", "unknown", "none"} and raw:
        canonical = raw.casefold()
    known = SUBMISSION_LABELS.get(canonical)
    if known:
        filter_state = (
            "submitted" if known[1] == "done"
            else "check" if canonical == "closed"
            else "todo"
        )
        return known[0], known[1], filter_state, ""
    if canonical in {"", "unknown", "none", "-", "—"}:
        if platform == "quera":
            return (
                "وضعیت ارسال از کوئرا دریافت نمی‌شود",
                "unknown",
                "check",
                "برای اطمینان در کوئرا بررسی شود",
            )
        return (
            "وضعیت ارسال از سامانه دریافت نشده",
            "unknown",
            "check",
            "وضعیت تحویل را در خود سامانه بررسی کن",
        )
    # CW may expose a localized status added by the site. Keep that source text
    # visible rather than silently converting a new value into a known state.
    return raw or state, "unknown", "check", "این عبارت مستقیماً از سامانه آمده است"


def _dashboard_tasks(study: dict, now_epoch: int) -> list[dict]:
    """Build the one deduplicated assignment view used by dashboard summaries."""
    rows = []
    seen = set()
    classes = {
        (item.get("ref", {}).get("connection_id"), item.get("ref", {}).get("class_id")): item
        for item in study.get("classes", [])
    }
    for item in study.get("platform_assignments", []):
        ref = item.get("ref") or {}
        key = _task_key(ref)
        has_stable_key = (
            ref.get("connection_id") is not None
            and ref.get("class_id") is not None
            and (ref.get("assignment_id") is not None or ref.get("question_id") is not None)
        )
        if has_stable_key:
            if key in seen:
                continue
            seen.add(key)
        deadlines = item.get("deadlines", []) or []
        regular = next((d for d in deadlines if isinstance(d, dict) and d.get("kind") in {"regular", "normal"}), None)
        late = next((d for d in deadlines if isinstance(d, dict) and d.get("kind") == "late"), None)
        # Older records may only have one untyped deadline.
        if regular is None:
            regular = next((d for d in deadlines if isinstance(d, dict) and not d.get("kind")), None)
        regular_due = _due_epoch(regular.get("at")) if regular else None
        late_due = _due_epoch(late.get("at")) if late else None
        state = _submission_presentation(
            item.get("platform", ""), item.get("submission", {}) or {}
        )[2]
        due = late_due if late_due and (regular_due is None or regular_due < now_epoch < late_due) else regular_due
        class_ref = item.get("class_ref", {})
        class_item = classes.get((
            class_ref.get("connection_id"), class_ref.get("class_id")
        ), {})
        offering = class_item.get("offering") or {}
        if offering.get("title"):
            course = offering["title"]
        elif class_item:
            course = "کلاس بی‌نگاشت · {}".format(class_item.get("title") or "نام نامشخص")
        elif item.get("legacy_link_status") in {"unmatched", "ambiguous"}:
            course = "دادهٔ قدیمی CW · {}".format(item.get("course_title") or "درس بی‌نام")
        else:
            course = item.get("course_title") or "درس نامشخص"
        rows.append({
            "name": str(item.get("title") or "تکلیف بدون عنوان"),
            "course": str(course),
            "url": item.get("url") or "#",
            "state": state,
            "due": due,
            "regular_due": regular_due,
            "late_due": late_due,
        })
    return rows


def _action_items(tasks: list[dict], now_epoch: int, horizon_days: int = 14) -> list[dict]:
    horizon = now_epoch + horizon_days * 86400
    return [
        item for item in tasks
        if item["state"] in {"todo", "check"} and (
            item["due"] is None or item["due"] <= horizon
            or item["regular_due"] is not None and item["regular_due"] < now_epoch
        )
    ]


def _class_group_key(item: dict) -> tuple:
    ref = item.get("ref", {})
    offering_id = (item.get("offering") or {}).get("id")
    if offering_id:
        return ("offering", offering_id)
    return ("class", ref.get("connection_id"), ref.get("class_id"))


def _assignment_freshness_index(study: dict) -> dict[tuple, dict]:
    return {
        (
            item.get("class_ref", {}).get("connection_id"),
            item.get("class_ref", {}).get("class_id"),
        ): item
        for item in study.get("assignment_observations", [])
    }


def _class_freshness_text(item: dict, freshness_by_class: dict[tuple, dict]) -> str:
    ref = item.get("ref", {})
    observation = freshness_by_class.get((ref.get("connection_id"), ref.get("class_id")))
    if not observation:
        return "تکلیف‌های این کلاس هنوز دریافت نشده‌اند."
    status = observation.get("last_attempt_status") or "نامشخص"
    coverage = observation.get("coverage") or "نامشخص"
    if status == "ok" and coverage == "complete":
        state = "آخرین تلاش کامل بود"
    elif status == "unavailable":
        state = "سامانه در آخرین تلاش در دسترس نبود"
    elif status == "challenge_required":
        state = "برای دریافت تازه ورود یا تأیید لازم است"
    else:
        state = "آخرین تلاش ناقص یا ناموفق بود"
    last_attempt = observation.get("last_attempt_at") or "ثبت نشده"
    last_success = observation.get("last_success_at")
    success_text = (
        "آخرین دریافت کامل: {}".format(last_success)
        if last_success else "هنوز دریافت کامل موفقی ثبت نشده"
    )
    if last_success and observation.get("last_attempt_at") and last_success < observation["last_attempt_at"]:
        state += "؛ دادهٔ قدیمیِ آخرین دریافت موفق نمایش داده می‌شود"
    failure_labels = {
        "transport_error": "خطای ارتباط با سامانه",
        "authentication_required": "ورود دوباره لازم است",
        "parser_error": "خطا هنگام خواندن صفحه",
        "unexpected_response": "ساختار پاسخ سامانه شناخته نشد",
    }
    failure = failure_labels.get(observation.get("failure_kind"))
    if failure:
        state += "؛ علت: {}".format(failure)
    return "{} · آخرین تلاش: {} · {}".format(state, last_attempt, success_text)


def _class_freshness_label(item: dict, freshness_by_class: dict[tuple, dict]) -> str:
    ref = item.get("ref", {})
    observation = freshness_by_class.get((ref.get("connection_id"), ref.get("class_id")))
    if not observation:
        return "دریافت تکلیف هنوز انجام نشده"
    status = observation.get("last_attempt_status")
    coverage = observation.get("coverage")
    if status == "ok" and coverage == "complete":
        label = "تلاش تکلیف کامل"
    elif status == "unavailable":
        label = "سامانه در تلاش تکلیف در دسترس نبود"
    elif status == "challenge_required":
        label = "ورود یا تأیید برای دریافت تکلیف لازم است"
    else:
        label = "تلاش تکلیف ناقص یا ناموفق"
    failure_labels = {
        "transport_error": "خطای ارتباط",
        "authentication_required": "ورود لازم است",
        "parser_error": "خطای خواندن صفحه",
        "unexpected_response": "پاسخ ناشناخته",
    }
    failure = failure_labels.get(observation.get("failure_kind"))
    if failure:
        label += " · {}".format(failure)
    last_success = observation.get("last_success_at")
    return "{} · موفق: {}".format(label, last_success or "ثبت نشده")
