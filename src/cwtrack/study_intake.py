"""Application flow for collecting a manual, CW, or Quera assignment input."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import auth
from .client import DEFAULT_BASE, Client, CwError
from .diagnostics import is_failure_kind
from .intake import collect as collect_assignment_input
from .intake import collect_site as collect_site_assignment
from .paths import STATE_DIR
from .task_refs import valid_task_ref


@dataclass(frozen=True)
class IntakeServices:
    load_legacy: Callable
    attempt_captcha: Callable
    study_context: Callable
    manager_factory: Callable


def collect(
    source: dict,
    *,
    services: IntakeServices,
    data: str | Path | None = None,
    home: str | Path | None = None,
    client=None,
    user: str | None = None,
    password: str | None = None,
    captcha: str | None = None,
    base: str | None = None,
    adapters=None,
    vault=None,
) -> dict:
    """Collect a manually supplied assignment or one selected course-site item.

    The optional client is the public test seam: tests can exercise the same intake
    path using a sanitized adapter without connecting to cw.sharif.ir.
    """
    if not isinstance(source, dict):
        return {"status": "invalid_input", "message": "ساختار منبع تکلیف نامعتبر است"}
    if "manual" in source:
        if len(source) != 1:
            return {"status": "invalid_input", "message": "فقط یک منبع تکلیف انتخاب کن"}
        return collect_assignment_input(source)
    if set(source) == {"platform"} and isinstance(source["platform"], dict):
        return collect_platform_assignment(
            source["platform"], services=services, data=data, home=home, adapters=adapters, vault=vault
        )
    if set(source) != {"site"} or not isinstance(source["site"], dict):
        return {"status": "invalid_input", "message": "منبع باید دستی یا سامانه باشد"}

    raw_cmid = source["site"].get("cmid")
    if isinstance(raw_cmid, bool) or not str(raw_cmid or "").isdigit():
        return {"status": "invalid_input", "message": "شناسهٔ تکلیف در سامانه لازم است"}
    cmid = int(raw_cmid)
    try:
        _, _, assignments, _ = services.load_legacy(data)
    except CwError as exc:
        return {"status": "needs_course_store", "message": str(exc)}
    selected = [assignment for assignment in assignments if assignment.cmid == cmid]
    if len(selected) != 1:
        return {"status": "not_found", "message": "این تکلیف در استور محلی پیدا نشد"}
    assignment = selected[0]
    item = {
        "course_id": assignment.course_id,
        "course": assignment.course,
        "term": assignment.term,
        "cmid": assignment.cmid,
        "name": assignment.name,
        "due": assignment.due,
        "due_text": assignment.due_text,
        "url": assignment.url,
    }

    base_dir = Path(home) if home else STATE_DIR
    name = user or os.environ.get("CW_USER")
    pw = password or os.environ.get("CW_PASS")
    if client is None and (not name or not pw):
        return {
            "status": "needs_credentials",
            "message": "برای دریافت تکلیف، CW_USER و CW_PASS لازم است.",
        }
    if client is None:
        client = Client(base or DEFAULT_BASE)
    if not client.logged_in():
        if not name or not pw:
            return {
                "status": "needs_credentials",
                "message": "برای ورود، CW_USER و CW_PASS لازم است.",
            }
        state = services.attempt_captcha(client, name, pw, base_dir, captcha)
        if state["status"] != auth.OK:
            return state

    try:
        return collect_site_assignment(cmid, item, client, base_dir)
    except (CwError, OSError, ValueError) as exc:
        return {"status": "failed", "message": str(exc)}


def collect_platform_assignment(
    selection: dict, *,
    services: IntakeServices, data=None, home=None, adapters=None, vault=None
) -> dict:
    task_ref = selection.get("task_ref")
    if not valid_task_ref(task_ref):
        return {"status": "invalid_input", "message": "TaskRef نامعتبر است"}
    study = services.study_context(data).view()
    assignments = [item for item in study["assignments"] if item.get("ref") == task_ref]
    if len(assignments) != 1:
        return {"status": "not_found", "message": "تکلیف انتخاب‌شده در مشاهدهٔ محلی نیست"}
    assignment = assignments[0]
    class_ref = {
        "connection_id": task_ref["connection_id"],
        "class_id": task_ref["class_id"],
    }
    classes = [item for item in study["classes"] if item.get("ref") == class_ref]
    course = classes[0].get("title", "") if len(classes) == 1 else ""
    metadata = {
        "course": course,
        "term": classes[0].get("term", "") if len(classes) == 1 else "",
        "title": assignment.get("title", ""),
        "due": (assignment.get("deadlines") or [{}])[0].get("at"),
        "url": assignment.get("url", ""),
    }
    platform = assignment.get("platform")
    if platform == "cw":
        if not task_ref["class_id"].isdigit() or not task_ref["assignment_id"].isdigit():
            return {"status": "invalid_input", "message": "شناسهٔ CW نامعتبر است"}
        metadata.update({
            "source": "site",
            "course_id": int(task_ref["class_id"]),
            "cmid": int(task_ref["assignment_id"]),
            "assignment_ref": task_ref,
        })
    elif platform == "quera":
        metadata.update({"source": "quera", "assignment_ref": task_ref})
    else:
        return {"status": "adapter_unavailable", "message": "این سامانه پشتیبانی نمی‌شود"}

    manager = services.manager_factory(home, adapters=adapters, vault=vault)
    if manager is None:
        return {"status": "secure_store_unavailable"}
    result = manager.observe(
        task_ref["connection_id"],
        {
            "scope": "assignment_detail",
            "task_ref": task_ref,
            "assignment": metadata,
        },
    )
    if result.get("status") == "challenge_required":
        return result
    if result.get("status") != "ok":
        failure = {"status": result.get("status", "unavailable")}
        if is_failure_kind(result.get("failure_kind")):
            failure["failure_kind"] = result["failure_kind"]
        return failure
    receipt = result.get("receipt", {})
    received = receipt.get("input")
    if not isinstance(received, dict):
        return {"status": "needs_input", "message": "متن تکلیف از سامانه دریافت نشد"}
    received.setdefault("assignment_ref", task_ref)
    received.setdefault("source", metadata["source"])
    questions = receipt.get("open_questions", [])
    return {
        "status": "needs_input" if questions else "ok",
        "input": received,
        "open_questions": questions,
    }
