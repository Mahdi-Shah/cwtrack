"""The surface a skill drives. No terminal, no stdout, no prompts.

Everything here returns Python values. Nothing prints, nothing reads stdin, nothing
opens a browser. That is the whole point of the module, and each of those three
omissions was a real blocker rather than a style preference:

- **No printing.** Persian output on a stock Windows console is cp1252, so a skill
  that ran the CLI and read its stdout either got mojibake or wrote a temp file and
  read it back. Returning `str` skips the round trip.
- **No prompts.** `auth.submit()` used to call `input()`, which from a shell with no
  terminal behind it raises EOFError and tells the user to set an environment
  variable. The login is now a two-phase call - ask for the image, hand back the
  answer - so a non-interactive caller is the normal case rather than an error path.
- **No browser.** `ui` opened the page. A caller that wants to show it to the user
  asks for the path and decides; opening a window is the caller's privilege, not
  this module's.

Expected conditions are returned as states, not raised. A missing store, a captcha
needing an answer, and "pick one of these" are all things a caller must handle, and a
caller cannot handle an exception it was never told the shape of.
"""

from __future__ import annotations

import contextlib
import json
import os
from datetime import datetime
from pathlib import Path

from . import access as access_store
from . import auth, tracker
from . import captcha as captcha_ocr
from . import catalog as catalog_store
from . import study as study_store
from . import work as work_store
from .brief import build_workfolder, open_items, remaining_text
from .classify import OPEN_BUCKETS
from .client import DEFAULT_BASE, Client, CwError
from .dashboard import build as _build_page
from .dashboard import resource_library_page as _build_resource_page
from .fetch import fetch_all
from .intake import collect as collect_assignment_input
from .intake import collect_site as collect_site_assignment
from .match import match_local
from .parse import parse_dump
from .paths import STATE_DIR, describe_paths, find_data_dir, store_is_readable
from .platforms import CWAdapter, QueraAdapter
from .report import BUCKET_FA, fmt_delta, report, table
from .resources import ResourceLibrary

__all__ = [
    "status", "gaps_text", "open_text", "report_text", "build_dashboard",
    "materials_text", "outstanding", "make_brief", "ingest", "refresh", "paths",
    "work_start", "work_get", "work_save", "work_sync", "work_finish", "work_list",
    "work_group_start", "work_group_get",
    "resource_attach", "resource_capture", "resource_detach", "resource_update",
    "resource_view",
    "study_view", "study_refresh", "course_link", "class_tracking", "assignment_relate",
    "access_configure", "access_update", "access_forget",
    "study_continue", "study_prepare", "collect_assignment", "CwError",
]


# ---------------------------------------------------------------------------
# reading the store
# ---------------------------------------------------------------------------


def _store(data: str | Path | None) -> Path:
    """Resolve the store path, refusing to invent one that is not there.

    Raising beats returning empty. A caller that gets an empty list will report zero
    assignments, and a student who reads that will believe they have no homework.
    """
    path = find_data_dir(str(data) if data else "")
    if not store_is_readable(path):
        raise CwError(
            "پوشهٔ داده پیدا نشد: {}\n"
            "اگر تازه شروع کرده‌اید:  cwtrack fetch\n"
            "اگر جای دیگری است:      --data <مسیر>".format(path.resolve())
        )
    return path


def _load(data: str | Path | None) -> tuple[Path, dict, list, dict]:
    """(store path, user, assignments, gap analysis) for one consistent read."""
    data_dir = _store(data)
    user, assignments = tracker.load(data_dir)
    if not assignments:
        raise CwError(
            "استور خالی است ({}). اول cwtrack fetch را اجرا کن، یا با --data "
            "مسیر یک cw-data موجود را نشان بده.".format(data_dir.resolve())
        )
    now = datetime.now()
    now_epoch = int(now.timestamp())
    return data_dir, user, assignments, tracker.gaps(assignments, now_epoch) | {"now": now, "now_epoch": now_epoch}


def _item(a, now_epoch: int) -> dict:
    """One assignment as a plain dict, with the human countdown already resolved.

    A caller narrating to a student should not have to reimplement the "۳ روز مانده"
    wording, and two implementations of it would eventually disagree.
    """
    return {
        "course_id": a.course_id,
        "course": a.course,
        "term": a.term,
        "cmid": a.cmid,
        "name": a.name,
        "bucket": a.bucket,
        "bucket_fa": BUCKET_FA.get(a.bucket, a.bucket),
        "due": a.due,
        "due_text": a.due_text,
        "remaining": remaining_text(a.due, now_epoch),
        "status_text": a.status_text,
        "grade": a.grade,
        "url": a.url,
    }


def paths(data: str | Path | None = None, home: str | Path | None = None) -> dict:
    """Every folder this tool uses, resolved."""
    data_dir = find_data_dir(str(data) if data else "")
    return describe_paths(data_dir, Path(home) if home else STATE_DIR)


def _work_root(data: str | Path | None, work: str | Path | None) -> Path:
    """Resolve the working root beside the selected course store by default."""
    if work is not None:
        return Path(work)
    return find_data_dir(str(data) if data else "").parent / "work"


def _resource_library(data: str | Path | None) -> ResourceLibrary:
    """Build the resource Module with the same explicit data path as work APIs."""
    data_dir = find_data_dir(str(data) if data else "")
    return ResourceLibrary(
        {"data": data_dir},
        clock=lambda: datetime.now().astimezone().isoformat(timespec="seconds"),
    )


def resource_attach(
    spec_or_id,
    *,
    to: dict,
    extent: dict | None = None,
    data: str | Path | None = None,
) -> dict:
    """Register or reuse a resource and bind it to one course/task."""
    library = _resource_library(data)
    try:
        attached = library.attach(spec_or_id, to=to, extent=extent)
    except (OSError, ValueError) as exc:
        return {"status": "invalid_input", "message": str(exc)}
    return {"status": "ok", **attached, "revision": library.view()["revision"]}


def resource_capture(
    resource_id: str,
    *,
    extent: dict,
    data: str | Path | None = None,
) -> dict:
    """Snapshot available resource content without marking it as used."""
    try:
        return _resource_library(data).capture(resource_id, extent=extent)
    except (OSError, ValueError) as exc:
        return {"status": "unavailable", "message": str(exc)}


def resource_detach(
    binding_id: str,
    *,
    expected_revision: int,
    data: str | Path | None = None,
) -> dict:
    """Disable one resource binding while preserving captured history."""
    try:
        return _resource_library(data).detach(
            binding_id, expected_revision=expected_revision
        )
    except (OSError, ValueError):
        return {"status": "unavailable"}


def resource_update(
    resource_id: str,
    replacement: dict,
    *,
    expected_revision: int,
    data: str | Path | None = None,
) -> dict:
    """Update a resource's current head without changing captured history."""
    try:
        return _resource_library(data).update(
            resource_id, replacement, expected_revision=expected_revision
        )
    except (OSError, ValueError):
        return {"status": "unavailable"}


def resource_view(
    *,
    target: dict | None = None,
    data: str | Path | None = None,
) -> dict:
    """Read the active resource library for a course or task."""
    return _resource_library(data).view(target=target)


def course_link(
    class_refs: list[dict],
    offering: dict,
    *,
    expected_revision: int,
    data: str | Path | None = None,
    replace_existing: bool = False,
) -> dict:
    """Link platform classes to a student-defined course and term."""
    catalog = catalog_store.Catalog(find_data_dir(str(data) if data else ""))
    try:
        return catalog.link_classes(
            class_refs,
            offering,
            expected_revision=expected_revision,
            replace_existing=replace_existing,
        )
    except (OSError, ValueError):
        return {"status": "unavailable"}


def class_tracking(
    class_ref: dict,
    state: str,
    *,
    expected_revision: int,
    term: str | None = None,
    data: str | Path | None = None,
) -> dict:
    """Set a class's current/archive visibility while preserving its history."""
    catalog = catalog_store.Catalog(find_data_dir(str(data) if data else ""))
    try:
        return catalog.class_tracking(
            class_ref, state, expected_revision=expected_revision, term=term
        )
    except (OSError, ValueError):
        return {"status": "unavailable"}


def assignment_relate(
    task_refs: list[dict],
    reason: str,
    *,
    expected_revision: int,
    data: str | Path | None = None,
) -> dict:
    """Record a student-declared relationship without merging assignment work."""
    catalog = catalog_store.Catalog(find_data_dir(str(data) if data else ""))
    try:
        return catalog.relate_assignments(
            task_refs, reason, expected_revision=expected_revision
        )
    except (OSError, ValueError):
        return {"status": "unavailable"}


def _study_context(data: str | Path | None, adapters=None) -> study_store.Study:
    data_dir = find_data_dir(str(data) if data else "")
    return study_store.Study(
        {"data": data_dir},
        platforms=adapters or [],
        protected_state=None,
        content_reader=None,
        clock=lambda: datetime.now().astimezone().isoformat(timespec="seconds"),
    )


def _platform_adapters(home: Path) -> dict:
    """Factories for supported live platform adapters."""

    def clock():
        return datetime.now().astimezone().isoformat(timespec="seconds")

    return {
        "cw": lambda connection: CWAdapter(
            connection,
            challenge_root=home / "access-challenges",
            clock=clock,
        ),
        "quera": lambda connection: QueraAdapter(connection, clock=clock),
    }


class _AccessBackedPlatform:
    """Present a protected account connection as a Study platform adapter."""

    def __init__(self, connection: dict, manager: access_store.AccessManager):
        self.connection = connection
        self._manager = manager

    def observe(self, request: dict, context: dict) -> dict:
        result = self._manager.observe(self.connection["id"], request)
        if result.get("status") == "ok":
            return result.get("receipt", {})
        observation = {
            "status": result.get("status", "unavailable"),
            "scope": request.get("scope"),
            "coverage": "incomplete",
            "nodes": [],
        }
        for key in ("continuation_id", "challenge"):
            if key in result:
                observation[key] = result[key]
        return observation


def study_refresh(
    platforms: list[str] | None = None,
    *,
    data: str | Path | None = None,
    adapters=None,
    home: str | Path | None = None,
    vault=None,
    connection_ids: list[str] | None = None,
) -> dict:
    """Refresh configured platform adapters and keep each result independent.

    ``adapters`` is the integration seam used by the application bootstrap and by
    sanitized adapter tests. A normal caller selects platform names only.
    """
    if adapters is not None:
        return _study_context(data, adapters).refresh(platforms=platforms)
    manager = _access_manager(home, vault=vault)
    if manager is None:
        return {"status": "secure_store_unavailable", "targets": []}
    connections = manager.connections()
    if connection_ids is not None:
        if not isinstance(connection_ids, list) or not all(
            isinstance(item, str) for item in connection_ids
        ):
            return {"status": "invalid_input", "targets": []}
        selected_ids = set(connection_ids)
        connections = [item for item in connections if item["id"] in selected_ids]
    if platforms is not None:
        selected_platforms = set(platforms)
        connections = [
            item for item in connections if item["platform"] in selected_platforms
        ]
    platform_adapters = [_AccessBackedPlatform(item, manager) for item in connections]
    return _study_context(data, platform_adapters).refresh()


def study_view(
    query: dict | None = None,
    *,
    data: str | Path | None = None,
    work: str | Path | None = None,
) -> dict:
    """Read the common coursework view without refreshing or migrating data."""
    if query not in (None, {}):
        return {"status": "invalid_input", "message": "این نمای خواندنی فقط query خالی می‌پذیرد."}

    data_dir = find_data_dir(str(data) if data else "")
    assignments = []
    if (data_dir / "assignments.json").is_file():
        _, stored = tracker.load(data_dir)
        now_epoch = int(datetime.now().timestamp())
        assignments = [_item(item, now_epoch) for item in stored]

    observed = _study_context(data_dir).view()
    library = ResourceLibrary(
        {"data": data_dir},
        clock=lambda: datetime.now().astimezone().isoformat(timespec="seconds"),
    ).view()
    return {
        "status": "ok",
        "assignments": assignments,
        "platform_assignments": observed["assignments"],
        "classes": observed["classes"],
        "connections": observed["connections"],
        "offerings": observed["offerings"],
        "catalog_revision": observed["catalog_revision"],
        "class_tracking": observed["class_tracking"],
        "assignment_relations": catalog_store.Catalog(data_dir).assignment_relations(),
        "resources": library["resources"],
        "resource_bindings": library["bindings"],
        "resource_captures": library["captures"],
        "work": work_store.list_all(_work_root(data_dir, work)),
    }


def _access_manager(home=None, *, adapters=None, vault=None) -> access_store.AccessManager | None:
    home_dir = Path(home) if home is not None else STATE_DIR
    protected = vault if vault is not None else access_store.default_vault(home_dir)
    if protected is None:
        return None
    return access_store.AccessManager(
        {"home": home_dir},
        adapters=adapters if adapters is not None else _platform_adapters(home_dir),
        vault=protected,
        clock=lambda: datetime.now().astimezone().isoformat(timespec="seconds"),
    )


def access_configure(
    platform: str,
    credentials: dict,
    *,
    origin: str | None = None,
    home: str | Path | None = None,
    adapters=None,
    vault=None,
) -> dict:
    """Save login material in the OS-protected store for one platform account."""
    origins = {"cw": "https://cw.sharif.ir", "quera": "https://quera.org"}
    manager = _access_manager(home, adapters=adapters, vault=vault)
    if manager is None:
        return {"status": "secure_store_unavailable"}
    return manager.configure(platform, origin or origins.get(platform, ""), credentials)


def access_forget(
    connection_id: str,
    *,
    home: str | Path | None = None,
    adapters=None,
    vault=None,
) -> dict:
    """Remove protected login/session state and invalidate pending challenges."""
    manager = _access_manager(home, adapters=adapters, vault=vault)
    if manager is None:
        return {"status": "secure_store_unavailable"}
    return manager.forget(connection_id)


def access_update(
    connection_id: str,
    credentials: dict,
    *,
    expected_generation: int,
    home: str | Path | None = None,
    adapters=None,
    vault=None,
) -> dict:
    """Rotate stored credentials and invalidate old sessions and challenges."""
    manager = _access_manager(home, adapters=adapters, vault=vault)
    if manager is None:
        return {"status": "secure_store_unavailable"}
    return manager.update_credentials(
        connection_id, credentials, expected_generation=expected_generation
    )


def study_continue(
    continuation_id: str,
    response: dict,
    *,
    home: str | Path | None = None,
    adapters=None,
    vault=None,
    data: str | Path | None = None,
) -> dict:
    """Resume the saved, stateful challenge that interrupted a platform operation."""
    manager = _access_manager(home, adapters=adapters, vault=vault)
    if manager is None:
        return {"status": "secure_store_unavailable"}
    result = manager.continue_operation(continuation_id, response)
    if result.get("status") == "ok" and adapters is None:
        refreshed = study_refresh(
            data=data,
            home=home,
            vault=vault,
            connection_ids=[result["connection_id"]],
        )
        result["refresh"] = refreshed
        if refreshed.get("status") != "ok":
            result["status"] = "partial"
    return result


def study_prepare(
    selection: dict,
    *,
    data: str | Path | None = None,
    home: str | Path | None = None,
    work: str | Path | None = None,
    vault=None,
    adapters=None,
) -> dict:
    """Prepare durable work for only assignment references the student selected."""
    if not isinstance(selection, dict) or len(selection) != 1:
        return {"status": "invalid_input", "message": "یک انتخاب صریح لازم است"}
    if "manual" in selection:
        started = work_start(selection, data=data, work=work)
        return {"status": started.get("status"), "work": started}
    if "received" in selection:
        received = selection["received"]
        started = work_start(selection, data=data, work=work)
        result = {"status": started.get("status"), "work": started}
        if (
            isinstance(received, dict)
            and received.get("source") == "quera"
            and _valid_task_ref(received.get("assignment_ref"))
        ):
            result["resources"] = _resources_for_task(
                received["assignment_ref"], data
            )
        return result
    if "task_ref" in selection:
        task_refs = [selection["task_ref"]]
    elif "task_refs" in selection:
        task_refs = selection["task_refs"]
    else:
        return {"status": "invalid_input", "message": "انتخاب باید TaskRef صریح داشته باشد"}
    if not isinstance(task_refs, list) or not task_refs or any(
        not _valid_task_ref(reference) for reference in task_refs
    ):
        return {"status": "invalid_input", "message": "فهرست TaskRef نامعتبر است"}

    received = []
    issues = []
    for reference in task_refs:
        intake = collect_assignment(
            {"platform": {"task_ref": reference}},
            data=data,
            home=home,
            vault=vault,
            adapters=adapters,
        )
        if intake.get("status") == "ok":
            received.append({"received": intake["input"]})
        else:
            issues.append({"task_ref": reference, **intake})

    if not received:
        status = "challenge_required" if any(
            issue.get("status") == "challenge_required" for issue in issues
        ) else "unavailable"
        return {"status": status, "issues": issues}
    if len(received) == 1:
        started = work_start(received[0], data=data, work=work)
        work_items = [started]
        result = {"status": started.get("status"), "work": started}
    else:
        grouped = work_group_start(received, data=data, work=work)
        work_items = grouped.get("members", [])
        result = {"status": grouped.get("status"), "group": grouped}
    if issues:
        result["status"] = "partial"
        result["issues"] = issues
    result["resources"] = [
        _resources_for_task(reference, data) for reference in task_refs
    ]
    result["work_items"] = work_items
    return result


def _resources_for_task(task_ref: dict, data: str | Path | None) -> dict:
    """Combine resources bound to the exact task and its explicitly linked course."""
    data_dir = find_data_dir(str(data) if data else "")
    library = _resource_library(data_dir)
    views = [library.view(target={"task_ref": task_ref})]
    class_ref = {
        "connection_id": task_ref["connection_id"],
        "class_id": task_ref["class_id"],
    }
    offering = catalog_store.Catalog(data_dir).offering_for(class_ref)
    if offering:
        views.append(library.view(target={"offering_id": offering["id"]}))

    def unique(key):
        result = {}
        for view in views:
            for item in view.get(key, []):
                result[item["id"] if key != "captures" else item["capture_id"]] = item
        return list(result.values())

    return {
        "task_ref": task_ref,
        "offering_id": offering["id"] if offering else None,
        "revision": max((view.get("revision", 0) for view in views), default=0),
        "resources": unique("resources"),
        "bindings": unique("bindings"),
        "captures": unique("captures"),
    }


def _refresh_dashboard_after_work(
    result: dict, data: str | Path | None, work: str | Path | None
) -> dict:
    if result.get("status") not in {"ok", "needs_input", "needs_completion"}:
        return result
    try:
        page = build_dashboard(data=data, work=work)
    except (CwError, OSError) as exc:
        result["dashboard_status"] = "failed"
        result["dashboard_message"] = str(exc)
    else:
        result["dashboard_status"] = "ok"
        result["dashboard_path"] = str(page)
    return result


def work_start(
    request: dict,
    *,
    data: str | Path | None = None,
    work: str | Path | None = None,
) -> dict:
    """Start work from student-provided assignment text and return its snapshot."""
    result = work_store.start(request, _work_root(data, work))
    return _refresh_dashboard_after_work(result, data, work)


def work_get(
    work_id: str,
    *,
    revision: int | None = None,
    data: str | Path | None = None,
    work: str | Path | None = None,
) -> dict:
    """Read a saved snapshot without opening a prompt, printing, or browsing."""
    return work_store.get(work_id, _work_root(data, work), revision)


def work_save(
    work_id: str,
    progress: dict,
    *,
    expected_revision: int,
    data: str | Path | None = None,
    work: str | Path | None = None,
) -> dict:
    """Persist one progress checkpoint based on the caller's known revision."""
    if isinstance(progress, dict) and "resource_uses" in progress:
        data_dir = find_data_dir(str(data) if data else "")
        library = ResourceLibrary(
            {"data": data_dir},
            clock=lambda: datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        try:
            progress = {
                **progress,
                "resource_uses": library.resolve_uses(progress["resource_uses"]),
            }
        except (OSError, ValueError):
            return {
                "status": "invalid_input",
                "message": "استفاده باید به نسخه و محدودهٔ منبع واقعی اشاره کند.",
            }
    result = work_store.save(
        work_id, progress, expected_revision, _work_root(data, work)
    )
    return _refresh_dashboard_after_work(result, data, work)


def work_sync(
    work_id: str,
    received_input: dict,
    *,
    expected_revision: int,
    data: str | Path | None = None,
    work: str | Path | None = None,
) -> dict:
    """Record newly fetched assignment content and flag affected work for review."""
    result = work_store.sync(
        work_id, received_input, expected_revision, _work_root(data, work)
    )
    return _refresh_dashboard_after_work(result, data, work)


def work_finish(
    work_id: str,
    delivery: dict,
    *,
    expected_revision: int,
    data: str | Path | None = None,
    work: str | Path | None = None,
) -> dict:
    """Record output files and report whether current requirements were verified."""
    result = work_store.finish(
        work_id, delivery, expected_revision, _work_root(data, work)
    )
    return _refresh_dashboard_after_work(result, data, work)


def work_list(
    *,
    selection: list[str] | None = None,
    data: str | Path | None = None,
    work: str | Path | None = None,
) -> list[dict]:
    """List saved work by explicit priority, then deadline, without starting work."""
    items = work_store.list_all(_work_root(data, work))
    if selection is not None:
        if not isinstance(selection, list) or not all(isinstance(item, str) for item in selection):
            raise CwError("فهرست انتخاب باید شامل شناسه‌های کار باشد")
        by_id = {item["work_id"]: item for item in items}
        return [by_id[work_id] for work_id in selection if work_id in by_id]

    def due_order(item: dict) -> tuple[int, float]:
        value = item.get("input", {}).get("due")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return (0, float(value))
        if isinstance(value, str) and value.strip():
            try:
                return (0, datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
            except ValueError:
                pass
        return (1, 0.0)

    return sorted(
        items,
        key=lambda item: (
            -item.get("priority", 0),
            *due_order(item),
            item["work_id"],
        ),
    )


def work_group_start(
    requests: list[dict],
    *,
    data: str | Path | None = None,
    work: str | Path | None = None,
) -> dict:
    """Start a selected group once and retain the exact membership for resumption."""
    result = work_store.start_group(requests, _work_root(data, work))
    if result.get("status") in {"ok", "partial"}:
        dashboard = _refresh_dashboard_after_work({"status": "ok"}, data, work)
        result.update({key: value for key, value in dashboard.items() if key.startswith("dashboard_")})
    return result


def work_group_get(
    group_id: str,
    *,
    data: str | Path | None = None,
    work: str | Path | None = None,
) -> dict:
    """Resume the exact saved selection, even if new assignments appeared later."""
    return work_store.get_group(group_id, _work_root(data, work))


def collect_assignment(
    source: dict,
    *,
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
        return _collect_platform_assignment(
            source["platform"], data=data, home=home, adapters=adapters, vault=vault
        )
    if set(source) != {"site"} or not isinstance(source["site"], dict):
        return {"status": "invalid_input", "message": "منبع باید دستی یا سامانه باشد"}

    raw_cmid = source["site"].get("cmid")
    if isinstance(raw_cmid, bool) or not str(raw_cmid or "").isdigit():
        return {"status": "invalid_input", "message": "شناسهٔ تکلیف در سامانه لازم است"}
    cmid = int(raw_cmid)
    try:
        _, _, assignments, _ = _load(data)
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
        state = _attempt_captcha(client, name, pw, base_dir, captcha)
        if state["status"] != auth.OK:
            return state

    try:
        return collect_site_assignment(cmid, item, client, base_dir)
    except (CwError, OSError, ValueError) as exc:
        return {"status": "failed", "message": str(exc)}


def _collect_platform_assignment(
    selection: dict, *, data=None, home=None, adapters=None, vault=None
) -> dict:
    task_ref = selection.get("task_ref")
    if not _valid_task_ref(task_ref):
        return {"status": "invalid_input", "message": "TaskRef نامعتبر است"}
    study = _study_context(data).view()
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

    manager = _access_manager(home, adapters=adapters, vault=vault)
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
        return {"status": result.get("status", "unavailable")}
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


def _valid_task_ref(value) -> bool:
    if not isinstance(value, dict):
        return False
    required = {"connection_id", "class_id", "assignment_id"}
    if not required.issubset(value) or set(value) - (required | {"question_id"}):
        return False
    if not all(isinstance(value[key], str) and value[key] for key in required):
        return False
    return value.get("question_id") is None or (
        isinstance(value.get("question_id"), str) and bool(value["question_id"])
    )


def status(data: str | Path | None = None) -> dict:
    """Everything left to do, ordered so the consequence comes first.

    The shape a caller should lead its answer from: `urgent`, then `soon`, then the
    per-course counts, then `unknown` - which is the list of things this tool refused
    to call done, and must be reported rather than dropped.
    """
    data_dir, _, assignments, gap = _load(data)
    now_epoch = gap["now_epoch"]
    return {
        "refreshed": _refreshed_at(data_dir),
        "counts": gap["counts"],
        "urgent": [_item(a, now_epoch) for a in gap["urgent"]],
        "soon": [_item(a, now_epoch) for a in gap["soon"]],
        "unscheduled": [_item(a, now_epoch) for a in gap["unscheduled"]],
        "unknown": [_item(a, now_epoch) for a in gap["unknown"]],
        "per_course": [
            {k: v for k, v in c.items() if k != "items"} for c in gap["per_course"]
        ],
        "paths": paths(data),
    }


def _refreshed_at(data_dir: Path) -> str:
    """When the store was last written.

    Countdowns are recomputed live, so this is the age of the *submission status*,
    not of the deadline. A caller saying "still open" should be able to say how old
    that claim is.
    """
    user_p = data_dir / "user.json"
    if not user_p.is_file():
        return ""
    try:
        return json.loads(user_p.read_text(encoding="utf-8-sig")).get("refreshed", "")
    except ValueError:
        return ""


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def gaps_text(data: str | Path | None = None) -> str:
    """The short Persian answer: what is left, worst first."""
    _, _, assignments, gap = _load(data)
    c = gap["counts"]
    lines = [
        "کل {} · ارسال‌نشده {} · گذشته از مهلت {} · انجام‌شده {}".format(
            c["total"], c["open"], c["urgent"], c["done"]
        ),
        "",
    ]
    lines += ["  [گذشته]  {} — {}".format(a.course, a.name) for a in gap["urgent"]]
    lines += [
        "  [نزدیک]  {} — {}  ({})".format(a.course, a.name, fmt_delta(a.due, gap["now_epoch"]))
        for a in gap["soon"]
    ]
    lines.append("")
    for c in gap["per_course"]:
        mark = "!!" if c["overdue"] else (" *" if c["open"] else "  ")
        lines.append(" {} {:<46} {}/{}".format(mark, c["course"][:46], c["done"], c["total"]))
    if not (gap["urgent"] or gap["soon"]):
        lines.append("  (مورد بازی ثبت نشده است)")
    return "\n".join(lines)


def open_text(
    data: str | Path | None = None,
    days: int | None = None,
    local: str | Path | None = None,
) -> str:
    """The outstanding list as a markdown table, optionally cross-referenced on disk."""
    _, _, assignments, gap = _load(data)
    picked = [a for a in assignments if a.bucket in OPEN_BUCKETS]
    if days:
        picked = [
            a for a in picked
            if a.due is not None and 0 < a.due - gap["now_epoch"] <= days * 86400
        ]
    rows = [a.__dict__ for a in picked]
    found = match_local(rows, Path(local)) if local else {}
    return table(rows, gap["now_epoch"], found) + "\n\n{} مورد باز".format(len(picked))


def report_text(data: str | Path | None = None, local: str | Path | None = None) -> str:
    """The full Persian markdown report."""
    data_dir, _, assignments, gap = _load(data)
    rows = [a.__dict__ for a in assignments]
    found = match_local(rows, Path(local)) if local else {}
    return report(rows, found, gap["now"])


def build_dashboard(
    data: str | Path | None = None,
    out: str | Path | None = None,
    *,
    work: str | Path | None = None,
) -> Path:
    """Write the dashboard and its companion resource library page.

    A course store, when available, supplies site-status data. A missing course store
    does not prevent this page from showing manually selected assignment work.
    Does not open the browser.
    """
    data_dir = find_data_dir(str(data) if data else "")
    has_course_data = store_is_readable(data_dir)
    if has_course_data:
        data_dir, user, assignments, gap = _load(data_dir)
    else:
        user = {}
        assignments = []
        gap = {}
        now = datetime.now()
        gap.update({"now": now, "now_epoch": int(now.timestamp())})
    work_root = _work_root(data, work)
    work_items = work_list(data=data, work=work)
    common_study_view = study_view(data=data, work=work)

    mats = {}
    if has_course_data:
        for cid_dir in (data_dir / "courses").glob("*"):
            if not cid_dir.is_dir():
                continue
            try:
                cid = int(cid_dir.name)
            except ValueError:
                continue
            mats[cid] = tracker.scan_materials(cid_dir / "materials")

    page = _build_page(
        user,
        assignments,
        gap,
        gap["now"],
        gap["now_epoch"],
        materials=mats,
        work_items=work_items,
        has_course_data=has_course_data,
        study_view=common_study_view,
    )
    target = Path(out) if out else (
        (data_dir if has_course_data else work_root.parent) / "index.html"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding="utf-8")
    resource_page = target.with_name("resources.html")
    resource_page.write_text(
        _build_resource_page(common_study_view, target.name), encoding="utf-8"
    )
    return target.resolve()


def materials_text(data: str | Path | None = None, course: str | int | None = None) -> dict:
    """Where a course's material folder is and what is in it."""
    if course is None:
        raise CwError("course id لازم است")
    data_dir = _store(data)
    cid = int(course)
    folder = tracker.course_dir(data_dir, cid) / "materials"
    folder.mkdir(parents=True, exist_ok=True)
    mats = tracker.scan_materials(folder)
    return {
        "course_id": cid,
        "folder": str(folder.resolve()),
        "count": len(mats),
        "materials": [
            {"name": m.name, "bytes": m.bytes, "kind": m.kind, "modified": m.modified}
            for m in mats
        ],
    }


# ---------------------------------------------------------------------------
# the brief handoff
# ---------------------------------------------------------------------------


def outstanding(
    data: str | Path | None = None,
    course: str | int | None = None,
    days: int | None = None,
) -> list[dict]:
    """Open work, soonest first - what a brief would be built for by default.

    `days` narrows to deadlines still ahead and within N days, so "what should I do
    tonight" is a filter rather than a re-derivation of the same list.
    """
    _, _, assignments, gap = _load(data)
    picked = open_items(assignments, gap["now_epoch"], str(course or ""))
    if days:
        picked = [
            a for a in picked
            if a.due is not None and 0 < a.due - gap["now_epoch"] <= days * 86400
        ]
    return [_item(a, gap["now_epoch"]) for a in picked]


def make_brief(
    cmid: str | int | None = None,
    course: str | int | None = None,
    data: str | Path | None = None,
    work: str | Path | None = None,
    force: bool = False,
) -> dict:
    """Create the working folder for one assignment.

    With no `cmid` and more than one candidate, returns `needs_choice` rather than
    picking for the user: two open assignments due the same day are not the same
    problem, and guessing which one they meant would put the wrong brief in front of
    them.

    Returns `exists` rather than overwriting when the folder is already populated,
    because sections 2 to 7 of a brief are the student's own writing.
    """
    data_dir, _, assignments, gap = _load(data)
    work_root = Path(work) if work else (data_dir.parent / "work")
    candidates = open_items(assignments, gap["now_epoch"], str(course or ""))

    if cmid is not None:
        chosen = [a for a in assignments if str(a.cmid) == str(cmid)]
        if not chosen:
            raise CwError("no assignment with cmid={} in the store".format(cmid))
    elif len(candidates) == 1:
        chosen = candidates
    elif not candidates:
        return {"status": "nothing_outstanding", "candidates": []}
    else:
        return {
            "status": "needs_choice",
            "candidates": [_item(a, gap["now_epoch"]) for a in candidates],
        }

    results = []
    for a in chosen:
        meta = {"title": a.course, "term": a.term}
        folder, written = build_workfolder(
            a.__dict__, meta, data_dir, work_root, gap["now_epoch"], overwrite=force
        )
        results.append({
            "cmid": a.cmid,
            "name": a.name,
            "course": a.course,
            "folder": str(folder.resolve()),
            "written": [p.name for p in written],
            "existed": not written,
            "source": str((data_dir / "courses" / str(a.course_id) / "materials").resolve()),
        })
    return {"status": "ok", "briefs": results}


# ---------------------------------------------------------------------------
# the network side
# ---------------------------------------------------------------------------


def ingest(dump: str | Path | None = None, data: str | Path | None = None) -> dict:
    """Parse pages already on disk into the store. No network, no login.

    Separate from refresh() because "the pages are already saved, just read them" and
    "go and get them" are different requests, and a caller repairing a parse after the
    site changed its markup needs the first without a captcha in the way.
    """
    dump_dir = Path(dump) if dump else (STATE_DIR / "dump")
    if not dump_dir.is_dir():
        raise CwError("هیچ صفحه‌ای ذخیره نشده. اول fetch را اجرا کن.")

    data_dir = find_data_dir(str(data) if data else "")
    rows = parse_dump(dump_dir, datetime.now())
    if not rows:
        raise CwError("از صفحه‌های ذخیره‌شده هیچ تکلیفی درنیامد.")

    info = {"fullname": "", "username": "", "userid": ""}
    prev = data_dir / "user.json"
    if prev.is_file():
        with contextlib.suppress(ValueError):
            info = json.loads(prev.read_text(encoding="utf-8-sig"))

    summary = tracker.store(data_dir, info, rows)
    summary["store"] = str(data_dir.resolve())
    return summary


def _attempt_captcha(
    client, user: str, pw: str, base_dir: Path, given: str | None
) -> dict:
    """Log in, using `given` when the caller supplied it.

    With no answer, a confident OCR reading is tried once. If it does not land, the
    result is `captcha_required` with a *fresh* image, which is the same state the
    human path has always got — so the skill still shows an image and asks, and the
    feature cannot introduce a third outcome for it to handle.
    """
    state = auth.submit(client, user, pw, base_dir, captcha=given)
    if given or state["status"] != auth.CAPTCHA_REQUIRED:
        return state

    # `guess` returns ok=False rather than raising for every "could not read it" case,
    # but a decode error or an OS problem while writing a variant would escape it, and
    # that must not take the login down with it.
    try:
        guess = captcha_ocr.guess(state["image"])
    except Exception:  # noqa: BLE001 - a nicety must not break the login
        state.setdefault("ocr", {"read": "", "agreement": 0.0, "reason": "error"})
        return state
    if not guess.get("ok"):
        # Carry the disagreement into the state so the caller can say why it did not
        # simply answer — except when OCR is switched off, which is a choice rather
        # than a failure and has nothing to report.
        if guess.get("reason") != "disabled":
            state["ocr"] = {
                "read": guess.get("text", ""),
                "agreement": guess.get("agreement", 0.0),
                "reason": guess.get("reason", ""),
            }
        return state

    tried = auth.submit(client, user, pw, base_dir, captcha=guess["text"])
    if tried["status"] == auth.CAPTCHA_REJECTED:
        # The OCR read this confidently and was still wrong. Do not try again: hand
        # back the fresh image and let the human read it, with the reason recorded.
        tried["ocr"] = {
            "read": guess["text"],
            "agreement": guess.get("agreement", 0.0),
            "reason": "rejected_by_site",
        }
    return tried


def refresh(
    captcha: str | None = None,
    home: str | Path | None = None,
    data: str | Path | None = None,
    user: str | None = None,
    password: str | None = None,
    base: str | None = None,
) -> dict:
    """Log in if needed, download every course's assignment page, write the store.

    `captcha` is the answer to a previous `captcha_required`. The states are:

    - `{"status": "captcha_required", "viewer": Path, ...}` - show `viewer` to the
      user, read the characters, call this again with `captcha=`. The image is
      190x40 px on the site; `viewer` is the same image at 4x, which is the
      difference between one round trip and several.
    - `{"status": "ok", "courses": n, "assignments": n, "store": Path}` - done.
    - `{"status": "captcha_rejected", "viewer": Path, ...}` - wrong read, new image
      already downloaded, try again.
    - `{"status": "failed", "message": str}` - credentials or something else. Do
      not retry this without changing something.

    Credentials come from the arguments or the `CW_USER` / `CW_PASS` environment.
    Nothing is ever read from argv, because argv lands in shell history.

    Credentials are checked before the HTTP client is even built. The session cookie
    lives in memory, so a fresh process can never be logged in already; without a
    username and password this call cannot do anything, and finding that out without
    opening a socket is both faster and easier to read.
    """
    base_dir = Path(home) if home else STATE_DIR
    data_dir = find_data_dir(str(data) if data else "")
    name = user or os.environ.get("CW_USER")
    pw = password or os.environ.get("CW_PASS")
    if not name or not pw:
        return {
            "status": "needs_credentials",
            "message": "CW_USER و CW_PASS را در متغیر محیطی بگذار، یا user/password بده.",
        }

    client = Client(base or DEFAULT_BASE)

    if not client.logged_in():
        # Try the OCR reading before asking, and fall back to asking. Either way the
        # states are the ones the human path already produces, so the skill file
        # needs no new branch for the feature.
        state = _attempt_captcha(client, name, pw, base_dir, captcha)
        if state["status"] != auth.OK:
            return state

    count = fetch_all(client, base_dir)
    summary = ingest(base_dir / "dump", data_dir)
    summary.update({
        "status": "ok",
        "pages": count,
        "refreshed": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    return summary
