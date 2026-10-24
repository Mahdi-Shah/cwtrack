"""Application operations for independent assignment work records."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import work as work_store
from .client import CwError
from .paths import find_data_dir
from .resource_application import resolve_uses


def _root(data: str | Path | None, work: str | Path | None) -> Path:
    if work is not None:
        return Path(work)
    return find_data_dir(str(data) if data else "").parent / "work"


def start(request: dict, *, data=None, work=None) -> dict:
    """Start work from student-provided assignment text."""
    return work_store.start(request, _root(data, work))


def get(work_id: str, *, revision: int | None = None, data=None, work=None) -> dict:
    """Read a saved work snapshot."""
    return work_store.get(work_id, _root(data, work), revision)


def save(
    work_id: str,
    progress: dict,
    *,
    expected_revision: int,
    data=None,
    work=None,
) -> dict:
    """Save one checkpoint and resolve resource use against captured versions."""
    if isinstance(progress, dict) and "resource_uses" in progress:
        try:
            progress = {
                **progress,
                "resource_uses": resolve_uses(
                    progress["resource_uses"], data=data
                ),
            }
        except (OSError, ValueError):
            return {
                "status": "invalid_input",
                "message": "استفاده باید به نسخه و محدودهٔ منبع واقعی اشاره کند.",
            }
    return work_store.save(work_id, progress, expected_revision, _root(data, work))


def sync(
    work_id: str,
    received_input: dict,
    *,
    expected_revision: int,
    data=None,
    work=None,
) -> dict:
    """Record newly fetched assignment content and flag affected work."""
    return work_store.sync(
        work_id, received_input, expected_revision, _root(data, work)
    )


def finish(
    work_id: str,
    delivery: dict,
    *,
    expected_revision: int,
    data=None,
    work=None,
) -> dict:
    """Record output files and assess current verification evidence."""
    return work_store.finish(
        work_id, delivery, expected_revision, _root(data, work)
    )


def list_work(*, selection: list[str] | None = None, data=None, work=None) -> list[dict]:
    """List saved work by priority and then deadline."""
    items = work_store.list_all(_root(data, work))
    if selection is not None:
        if not isinstance(selection, list) or not all(
            isinstance(item, str) for item in selection
        ):
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


def start_group(requests: list[dict], *, data=None, work=None) -> dict:
    """Start a selected group, keeping each assignment's work independent."""
    return work_store.start_group(requests, _root(data, work))


def get_group(group_id: str, *, data=None, work=None) -> dict:
    """Resume an exact saved group selection."""
    return work_store.get_group(group_id, _root(data, work))
