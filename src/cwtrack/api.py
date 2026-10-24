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

from pathlib import Path

from . import access as access_store  # noqa: F401 - retained adapter injection seam
from . import (
    access_application,
    catalog_application,
    dashboard_application,
    legacy_application,
    platform_runtime,
    report_application,
    resource_application,
    study_application,
    study_intake,
    study_preparation,
    study_sources,
    work_application,
)
from .client import Client, CwError
from .dashboard import build as _build_page
from .dashboard import resource_library_page as _build_resource_page
from .paths import find_data_dir
from .platforms import CWAdapter as CWAdapter
from .platforms import QueraAdapter as QueraAdapter
from .read_model import study_view as _study_view
from .resources import ResourceLibrary
from .study_application import refresh as _refresh_study

__all__ = [
    "status", "gaps_text", "open_text", "report_text", "build_dashboard",
    "materials_text", "outstanding", "make_brief", "ingest", "refresh", "paths",
    "work_start", "work_get", "work_save", "work_sync", "work_finish", "work_list",
    "work_group_start", "work_group_get",
    "report_templates", "report_prepare", "report_build",
    "resource_attach", "resource_capture", "resource_detach", "resource_update",
    "resource_view",
    "study_view", "study_refresh", "course_link", "class_tracking", "assignment_relate",
    "access_configure", "access_update", "access_forget",
    "access_view", "access_label_update", "access_rename", "access_forget_named",
    "access_update_named",
    "study_continue", "study_challenges", "study_prepare", "collect_assignment", "CwError",
]

# ---------------------------------------------------------------------------
# reading the store
# ---------------------------------------------------------------------------


def _store(data: str | Path | None) -> Path:
    return legacy_application.store(data)


def _load(data: str | Path | None) -> tuple[Path, dict, list, dict]:
    return legacy_application.load(data)


def paths(data: str | Path | None = None, home: str | Path | None = None) -> dict:
    return legacy_application.paths(data, home)


def _work_root(data: str | Path | None, work: str | Path | None) -> Path:
    """Resolve the working root beside the selected course store by default."""
    if work is not None:
        return Path(work)
    return find_data_dir(str(data) if data else "").parent / "work"


def _resource_library(data: str | Path | None) -> ResourceLibrary:
    """Build the resource Module with the same explicit data path as work APIs."""
    return resource_application.library(data)


def report_templates(*, data=None) -> dict:
    """List available PDF templates; the agent selects one for the assignment."""
    return report_application.templates(data=data)


def report_prepare(work_id: str, template_id: str, metadata: dict, reason: str, *,
                   expected_revision: int, data=None, work=None) -> dict:
    """Cache pinned sources and prepare a fresh report in this work's workspace."""
    return report_application.prepare(work_id, template_id, metadata, reason,
                                      expected_revision=expected_revision, data=data, work=work)


def report_build(work_id: str, *, expected_revision: int, data=None, work=None,
                 timeout: int = 120) -> dict:
    """Freeze/build PDF and source ZIP, checkpointing success or failure."""
    return report_application.build(work_id, expected_revision=expected_revision,
                                    data=data, work=work, timeout=timeout)


def resource_attach(
    spec_or_id,
    *,
    to: dict,
    extent: dict | None = None,
    data: str | Path | None = None,
) -> dict:
    """Register or reuse a resource and bind it to one course/task."""
    return resource_application.attach(spec_or_id, to=to, extent=extent, data=data)


def resource_capture(
    resource_id: str,
    *,
    extent: dict,
    data: str | Path | None = None,
) -> dict:
    """Snapshot available resource content without marking it as used."""
    return resource_application.capture(resource_id, extent=extent, data=data)


def resource_detach(
    binding_id: str,
    *,
    expected_revision: int,
    data: str | Path | None = None,
) -> dict:
    """Disable one resource binding while preserving captured history."""
    return resource_application.detach(
        binding_id, expected_revision=expected_revision, data=data
    )


def resource_update(
    resource_id: str,
    replacement: dict,
    *,
    expected_revision: int,
    data: str | Path | None = None,
) -> dict:
    """Update a resource's current head without changing captured history."""
    return resource_application.update(
        resource_id, replacement, expected_revision=expected_revision, data=data
    )


def resource_view(
    *,
    target: dict | None = None,
    data: str | Path | None = None,
) -> dict:
    """Read the active resource library for a course or task."""
    return resource_application.view(target=target, data=data)


def course_link(
    class_refs: list[dict],
    offering: dict,
    *,
    expected_revision: int,
    data: str | Path | None = None,
    replace_existing: bool = False,
) -> dict:
    """Link platform classes to a student-defined course and term."""
    return catalog_application.link_classes(
        class_refs, offering, expected_revision=expected_revision, data=data,
        replace_existing=replace_existing,
    )


def class_tracking(
    class_ref: dict,
    state: str,
    *,
    expected_revision: int,
    term: str | None = None,
    data: str | Path | None = None,
) -> dict:
    """Set a class's current/archive visibility while preserving its history."""
    return catalog_application.class_tracking(
        class_ref, state, expected_revision=expected_revision, term=term, data=data
    )


def assignment_relate(
    task_refs: list[dict],
    reason: str,
    *,
    expected_revision: int,
    data: str | Path | None = None,
    relation_type: str = "related",
) -> dict:
    """Record a student-confirmed relation without merging work records."""
    return catalog_application.relate_assignments(
        task_refs, reason, expected_revision=expected_revision, data=data,
        relation_type=relation_type,
    )


_study_context = platform_runtime.study_context
_platform_adapters = platform_runtime.platform_adapters
_AccessBackedPlatform = platform_runtime.AccessBackedPlatform
def _access_manager(home=None, *, adapters=None, vault=None):
    return platform_runtime.access_manager(
        home, adapters=adapters, vault=vault, adapter_factory=_platform_adapters
    )


def study_refresh(
    platforms: list[str] | None = None,
    *,
    data: str | Path | None = None,
    adapters=None,
    home: str | Path | None = None,
    vault=None,
    connection_ids: list[str] | None = None,
    connection_labels: list[str] | None = None,
) -> dict:
    """Refresh configured platform adapters and keep each result independent.

    ``adapters`` is the integration seam used by the application bootstrap and by
    sanitized adapter tests. A normal caller selects platform names only.
    """
    return _refresh_study(
        platforms, data=data, adapters=adapters, home=home, vault=vault,
        connection_ids=connection_ids, connection_labels=connection_labels,
        context_factory=_study_context, manager_factory=_access_manager,
        adapter_factory=_AccessBackedPlatform,
    )


def study_view(
    query: dict | None = None,
    *,
    data: str | Path | None = None,
    work: str | Path | None = None,
) -> dict:
    """Read the common coursework view without refreshing or migrating data."""
    return _study_view(query, data=data, work=work)


def access_configure(
    platform: str,
    credentials: dict,
    *,
    origin: str | None = None,
    home: str | Path | None = None,
    label: str | None = None,
    adapters=None,
    vault=None,
) -> dict:
    """Save login material in the OS-protected store for one platform account."""
    return access_application.configure(
        platform, credentials, origin=origin, home=home, label=label,
        adapters=adapters, vault=vault, manager_factory=_access_manager,
    )


def access_view(*, home: str | Path | None = None, adapters=None, vault=None) -> dict:
    """List configured connections with local labels and without usernames or IDs."""
    return access_application.view(
        home=home, adapters=adapters, vault=vault, manager_factory=_access_manager
    )


def access_label_update(
    connection_id: str, label: str, *, home: str | Path | None = None,
    adapters=None, vault=None,
) -> dict:
    """Rename a local connection label; never changes the protected account."""
    return access_application.label_update(
        connection_id, label, home=home, adapters=adapters, vault=vault,
        manager_factory=_access_manager,
    )


def access_rename(
    current_label: str, label: str, *, home: str | Path | None = None,
    adapters=None, vault=None,
) -> dict:
    """Rename a selected connection by its visible name, keeping IDs private."""
    return access_application.rename(
        current_label, label, home=home, adapters=adapters, vault=vault,
        manager_factory=_access_manager,
    )


def access_forget_named(
    label: str, *, home: str | Path | None = None, adapters=None, vault=None,
) -> dict:
    """Forget a connection selected by its local label, without exposing its ID."""
    return access_application.forget_named(
        label, home=home, adapters=adapters, vault=vault, manager_factory=_access_manager,
    )


def access_update_named(
    label: str, credentials: dict, *, home: str | Path | None = None,
    adapters=None, vault=None,
) -> dict:
    """Rotate credentials for the uniquely named local connection."""
    return access_application.update_named(
        label, credentials, home=home, adapters=adapters, vault=vault,
        manager_factory=_access_manager,
    )


def access_forget(
    connection_id: str,
    *,
    home: str | Path | None = None,
    adapters=None,
    vault=None,
) -> dict:
    """Remove protected login/session state and invalidate pending challenges."""
    return access_application.forget(
        connection_id, home=home, adapters=adapters, vault=vault,
        manager_factory=_access_manager,
    )


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
    return access_application.update(
        connection_id, credentials, expected_generation=expected_generation,
        home=home, adapters=adapters, vault=vault, manager_factory=_access_manager,
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
    return study_application.continue_operation(
        continuation_id,
        response,
        home=home,
        adapters=adapters,
        vault=vault,
        data=data,
        manager_factory=_access_manager,
        refresh_operation=study_refresh,
    )


def study_challenges(*, home: str | Path | None = None, adapters=None, vault=None) -> dict:
    """List pending challenges with local connection names for the interactive CLI."""
    return study_application.challenges(
        home=home, adapters=adapters, vault=vault, manager_factory=_access_manager
    )


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
    services = study_preparation.PrepareServices(
        work_start=work_start,
        work_group_start=work_group_start,
        valid_task_ref=_valid_task_ref,
        attach_quera_course_materials=_attach_quera_course_materials,
        fetch_linked_course_materials=_fetch_linked_course_materials,
        resources_for_task=_resources_for_task,
        course_materials_summary=_course_materials_summary,
        course_source_reports=_course_source_reports,
        course_materials_coverage_issue=_course_materials_coverage_issue,
        collect_assignment=collect_assignment,
    )
    return study_preparation.prepare(
        selection, services=services, data=data, home=home, work=work,
        vault=vault, adapters=adapters,
    )


# Stable private aliases retained for callers/tests while implementation lives in study_sources.
_resources_for_task = study_sources._resources_for_task
_course_source_reports = study_sources._course_source_reports
_course_code_from_title = study_sources._course_code_from_title
_course_term_from_title = study_sources._course_term_from_title
_attach_quera_course_materials = study_sources._attach_quera_course_materials
_attach_course_material_files = study_sources._attach_course_material_files
_course_materials_summary = study_sources._course_materials_summary
_course_materials_coverage_issue = study_sources._course_materials_coverage_issue

def _fetch_linked_course_materials(
    task_ref: dict, *, data=None, home=None, vault=None, adapters=None
) -> dict | None:
    return study_sources._fetch_linked_course_materials(
        task_ref, data=data, home=home, vault=vault, adapters=adapters,
        manager_factory=_access_manager,
    )


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
    result = work_application.start(request, data=data, work=work)
    return _refresh_dashboard_after_work(result, data, work)


def work_get(
    work_id: str,
    *,
    revision: int | None = None,
    data: str | Path | None = None,
    work: str | Path | None = None,
) -> dict:
    """Read a saved snapshot without opening a prompt, printing, or browsing."""
    return work_application.get(work_id, revision=revision, data=data, work=work)


def work_save(
    work_id: str,
    progress: dict,
    *,
    expected_revision: int,
    data: str | Path | None = None,
    work: str | Path | None = None,
) -> dict:
    """Persist one progress checkpoint based on the caller's known revision."""
    result = work_application.save(
        work_id, progress, expected_revision=expected_revision, data=data, work=work
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
    result = work_application.sync(
        work_id, received_input, expected_revision=expected_revision,
        data=data, work=work,
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
    result = work_application.finish(
        work_id, delivery, expected_revision=expected_revision,
        data=data, work=work,
    )
    return _refresh_dashboard_after_work(result, data, work)


def work_list(
    *,
    selection: list[str] | None = None,
    data: str | Path | None = None,
    work: str | Path | None = None,
) -> list[dict]:
    """List saved work by explicit priority, then deadline, without starting work."""
    return work_application.list_work(selection=selection, data=data, work=work)


def work_group_start(
    requests: list[dict],
    *,
    data: str | Path | None = None,
    work: str | Path | None = None,
) -> dict:
    """Start a selected group once and retain the exact membership for resumption."""
    result = work_application.start_group(requests, data=data, work=work)
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
    return work_application.get_group(group_id, data=data, work=work)


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
    """Collect a manually supplied assignment or one selected course-site item."""
    services = study_intake.IntakeServices(
        load_legacy=_load,
        attempt_captcha=_attempt_captcha,
        study_context=_study_context,
        manager_factory=_access_manager,
    )
    return study_intake.collect(
        source, services=services, data=data, home=home, client=client,
        user=user, password=password, captcha=captcha, base=base,
        adapters=adapters, vault=vault,
    )


_collect_platform_assignment = study_intake.collect_platform_assignment
_valid_task_ref = study_intake.valid_task_ref


def status(data: str | Path | None = None) -> dict:
    return legacy_application.status(data)


def _refreshed_at(data_dir: Path) -> str:
    return legacy_application.refreshed_at(data_dir)


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def gaps_text(data: str | Path | None = None) -> str:
    return legacy_application.gaps_text(data)


def open_text(
    data: str | Path | None = None,
    days: int | None = None,
    local: str | Path | None = None,
) -> str:
    return legacy_application.open_text(data, days, local)


def report_text(data: str | Path | None = None, local: str | Path | None = None) -> str:
    return legacy_application.report_text(data, local)


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
    return dashboard_application.build(
        data,
        out,
        work,
        load_legacy=_load,
        list_work=work_list,
        read_study=study_view,
        render_page=_build_page,
        render_resources=_build_resource_page,
    )


def materials_text(data: str | Path | None = None, course: str | int | None = None) -> dict:
    return legacy_application.materials_text(data, course)


# ---------------------------------------------------------------------------
# the brief handoff
# ---------------------------------------------------------------------------


def outstanding(
    data: str | Path | None = None,
    course: str | int | None = None,
    days: int | None = None,
) -> list[dict]:
    return legacy_application.outstanding(data, course, days)


def make_brief(
    cmid: str | int | None = None,
    course: str | int | None = None,
    data: str | Path | None = None,
    work: str | Path | None = None,
    force: bool = False,
) -> dict:
    return legacy_application.make_brief(cmid, course, data, work, force)


# ---------------------------------------------------------------------------
# the network side
# ---------------------------------------------------------------------------


def ingest(dump: str | Path | None = None, data: str | Path | None = None) -> dict:
    return legacy_application.ingest(dump, data)


def _attempt_captcha(
    client, user: str, pw: str, base_dir: Path, given: str | None
) -> dict:
    return legacy_application._attempt_captcha(client, user, pw, base_dir, given)


def refresh(
    captcha: str | None = None,
    home: str | Path | None = None,
    data: str | Path | None = None,
    user: str | None = None,
    password: str | None = None,
    base: str | None = None,
) -> dict:
    return legacy_application.refresh(
        captcha=captcha, home=home, data=data, user=user, password=password, base=base,
        client_factory=Client,
    )
