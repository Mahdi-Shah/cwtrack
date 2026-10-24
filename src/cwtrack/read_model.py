"""Read-only projections that combine the durable coursework domain stores."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import catalog as catalog_store
from . import study as study_store
from . import tracker
from . import work as work_store
from .brief import remaining_text
from .paths import find_data_dir
from .report import BUCKET_FA
from .resources import ResourceLibrary


def assignment(item, now_epoch: int) -> dict:
    """Project one legacy assignment into a stable, human-readable record."""
    return {
        "course_id": item.course_id,
        "course": item.course,
        "term": item.term,
        "cmid": item.cmid,
        "name": item.name,
        "bucket": item.bucket,
        "bucket_fa": BUCKET_FA.get(item.bucket, item.bucket),
        "due": item.due,
        "due_text": item.due_text,
        "remaining": remaining_text(item.due, now_epoch),
        "status_text": item.status_text,
        "grade": item.grade,
        "url": item.url,
    }


def _work_root(data: Path, work: str | Path | None) -> Path:
    return Path(work) if work is not None else data.parent / "work"


def _library(data: Path) -> ResourceLibrary:
    return ResourceLibrary(
        {"data": data},
        clock=lambda: datetime.now().astimezone().isoformat(timespec="seconds"),
    )


def study_view(
    query: dict | None = None,
    *,
    data: str | Path | None = None,
    work: str | Path | None = None,
) -> dict:
    """Combine local assignments, observed platform data, resources and work."""
    if query not in (None, {}):
        return {"status": "invalid_input", "message": "این نمای خواندنی فقط query خالی می‌پذیرد."}

    data_dir = find_data_dir(str(data) if data else "")
    assignments = []
    if (data_dir / "assignments.json").is_file():
        _, stored = tracker.load(data_dir)
        now_epoch = int(datetime.now().timestamp())
        assignments = [assignment(item, now_epoch) for item in stored]

    observed = study_store.Study(
        {"data": data_dir}, platforms=[], protected_state=None,
        content_reader=None,
        clock=lambda: datetime.now().astimezone().isoformat(timespec="seconds"),
    ).view()
    library = _library(data_dir).view()
    return {
        "status": "ok",
        "assignments": assignments,
        "platform_assignments": observed["assignments"],
        "assignment_observations": observed["assignment_observations"],
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
