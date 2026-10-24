"""Application operations for the local resource library."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .paths import find_data_dir
from .resources import ResourceLibrary


def library(data: str | Path | None) -> ResourceLibrary:
    data_dir = find_data_dir(str(data) if data else "")
    return ResourceLibrary(
        {"data": data_dir},
        clock=lambda: datetime.now().astimezone().isoformat(timespec="seconds"),
    )


def attach(
    spec_or_id,
    *,
    to: dict,
    extent: dict | None = None,
    data: str | Path | None = None,
) -> dict:
    """Register or reuse a resource and bind it to one course/task."""
    resource_library = library(data)
    try:
        attached = resource_library.attach(spec_or_id, to=to, extent=extent)
    except (OSError, ValueError) as exc:
        return {"status": "invalid_input", "message": str(exc)}
    return {"status": "ok", **attached, "revision": resource_library.view()["revision"]}


def capture(
    resource_id: str,
    *,
    extent: dict,
    data: str | Path | None = None,
) -> dict:
    """Snapshot available resource content without marking it as used."""
    try:
        return library(data).capture(resource_id, extent=extent)
    except (OSError, ValueError) as exc:
        return {"status": "unavailable", "message": str(exc)}


def detach(
    binding_id: str,
    *,
    expected_revision: int,
    data: str | Path | None = None,
) -> dict:
    """Disable one resource binding while preserving captured history."""
    try:
        return library(data).detach(binding_id, expected_revision=expected_revision)
    except (OSError, ValueError):
        return {"status": "unavailable"}


def update(
    resource_id: str,
    replacement: dict,
    *,
    expected_revision: int,
    data: str | Path | None = None,
) -> dict:
    """Update a resource's current head without changing captured history."""
    try:
        return library(data).update(
            resource_id, replacement, expected_revision=expected_revision
        )
    except (OSError, ValueError):
        return {"status": "unavailable"}


def view(*, target: dict | None = None, data: str | Path | None = None) -> dict:
    """Read the active resource library for a course or task."""
    return library(data).view(target=target)


def resolve_uses(resource_uses: list[dict], *, data: str | Path | None = None) -> list[dict]:
    """Resolve declared use against captured resource versions."""
    return library(data).resolve_uses(resource_uses)
