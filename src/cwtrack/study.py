"""Prepare a shared coursework view from independently observed platforms."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .catalog import Catalog


class Study:
    """Coordinate platform observations and expose their combined local view."""

    def __init__(
        self,
        paths: dict,
        *,
        platforms,
        protected_state,
        content_reader,
        clock: Callable[[], str],
    ):
        if not isinstance(paths, dict) or not paths.get("data"):
            raise ValueError("Study requires an explicit data path")
        self._catalog = Catalog(Path(paths["data"]))
        if isinstance(platforms, dict):
            platforms = platforms.values()
        self._platforms = tuple(platforms)
        self._protected_state = protected_state
        self._content_reader = content_reader
        self._clock = clock

    def refresh(self, platforms=None) -> dict:
        """Refresh class lists while retaining each connection's own observation."""
        selected = self._platforms
        if platforms is not None:
            wanted = set(platforms)
            selected = tuple(
                adapter for adapter in selected
                if adapter.connection.get("platform") in wanted
            )

        targets = []
        actions = []
        for adapter in selected:
            connection = adapter.connection
            attempted_at = self._clock()
            try:
                observation = adapter.observe({"scope": "classes"}, {})
            except (ConnectionError, TimeoutError, OSError):
                observation = {
                    "status": "unavailable",
                    "scope": "classes",
                    "coverage": "incomplete",
                }
            saved = self._catalog.record_classes(
                connection, observation, attempted_at
            )
            target_status = observation.get("status", "partial")
            if not saved and target_status == "ok":
                target_status = "partial"
            if target_status == "challenge_required":
                action = _challenge_action(connection, observation, "classes")
                if action:
                    actions.append(action)
            if saved:
                archived_refs = {
                    (
                        item["class_ref"]["connection_id"],
                        item["class_ref"]["class_id"],
                    )
                    for item in self._catalog.class_tracking_view()
                    if item.get("state") == "archived"
                }
                for node in observation["nodes"]:
                    class_ref = node["ref"]
                    if (
                        class_ref["connection_id"], class_ref["class_id"]
                    ) in archived_refs:
                        continue
                    try:
                        assignments = adapter.observe(
                            {"scope": "assignments", "class_ref": class_ref}, {}
                        )
                    except (ConnectionError, TimeoutError, OSError):
                        assignments = {
                            "status": "unavailable",
                            "scope": "assignments",
                            "coverage": "incomplete",
                        }
                    assignment_saved = self._catalog.record_assignments(
                        connection, class_ref, assignments, attempted_at
                    )
                    if not assignment_saved or assignments.get("status") != "ok":
                        if assignments.get("status") == "challenge_required":
                            action = _challenge_action(
                                connection, assignments, "assignments"
                            )
                            if action:
                                actions.append(action)
                        if target_status != "challenge_required":
                            target_status = "partial"
            targets.append({
                "connection_id": connection["id"],
                "platform": connection["platform"],
                "status": target_status,
            })
        if not targets:
            return {"status": "unavailable", "targets": []}
        status = "ok" if all(target["status"] == "ok" for target in targets) else "partial"
        result = {"status": status, "targets": targets}
        if actions:
            result["actions"] = actions
        return result

    def view(self) -> dict:
        """Return the durable class inventory using connection-scoped identities."""
        classes = self._catalog.classes()
        offerings = self._catalog.offerings()
        tracking = self._catalog.class_tracking_view()
        tracking_by_ref = {
            (item["class_ref"]["connection_id"], item["class_ref"]["class_id"]): item
            for item in tracking
        }
        for item in classes:
            ref = item["ref"]
            offering = self._catalog.offering_for(ref)
            item["offering"] = (
                {key: offering[key] for key in ("id", "title", "term", "archived")
                 if key in offering}
                if offering else None
            )
            tracking_item = tracking_by_ref.get((ref["connection_id"], ref["class_id"]))
            item["tracking"] = (
                {key: tracking_item.get(key) for key in ("state", "term")}
                if tracking_item else {"state": "unknown", "term": None}
            )
        return {
            "classes": classes,
            "assignments": self._catalog.assignments(),
            "connections": self._catalog.connections(),
            "offerings": offerings["offerings"],
            "catalog_revision": offerings["revision"],
            "class_tracking": tracking,
            "assignment_relations": self._catalog.assignment_relations(),
        }


def _challenge_action(connection: dict, result: dict, scope: str) -> dict | None:
    continuation_id = result.get("continuation_id")
    challenge = result.get("challenge")
    if not isinstance(continuation_id, str) or not isinstance(challenge, dict):
        return None
    return {
        "connection_id": connection["id"],
        "platform": connection["platform"],
        "scope": scope,
        "continuation_id": continuation_id,
        "challenge": {
            key: challenge[key]
            for key in ("kind", "display", "expires_at")
            if key in challenge
        },
    }
