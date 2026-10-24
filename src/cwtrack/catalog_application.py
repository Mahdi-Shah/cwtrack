"""Application operations for course and assignment catalog decisions."""

from __future__ import annotations

from pathlib import Path

from .catalog import Catalog
from .paths import find_data_dir


def _catalog(data: str | Path | None) -> Catalog:
    return Catalog(find_data_dir(str(data) if data else ""))


def link_classes(
    class_refs: list[dict],
    offering: dict,
    *,
    expected_revision: int,
    data: str | Path | None = None,
    replace_existing: bool = False,
) -> dict:
    """Link platform classes to a student-defined course and term."""
    try:
        return _catalog(data).link_classes(
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
    try:
        return _catalog(data).class_tracking(
            class_ref, state, expected_revision=expected_revision, term=term
        )
    except (OSError, ValueError):
        return {"status": "unavailable"}


def relate_assignments(
    task_refs: list[dict],
    reason: str,
    *,
    expected_revision: int,
    data: str | Path | None = None,
    relation_type: str = "related",
) -> dict:
    """Record a student-declared relationship without merging assignment work."""
    try:
        return _catalog(data).relate_assignments(
            task_refs, reason, expected_revision=expected_revision,
            relation_type=relation_type,
        )
    except (OSError, ValueError):
        return {"status": "unavailable"}
