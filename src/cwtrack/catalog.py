"""Durable, connection-scoped observations from assignment platforms."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .diagnostics import is_failure_kind


class Catalog:
    """Store complete class observations without merging platform identities."""

    def __init__(self, data: str | Path):
        self._catalog_root = Path(data) / "catalog-v2"
        self._root = self._catalog_root / "connections"
        self._offerings_path = self._catalog_root / "offerings.json"

    def link_classes(
        self,
        class_refs: list[dict],
        offering: dict,
        *,
        expected_revision: int,
        replace_existing: bool = False,
    ) -> dict:
        """Explicitly connect platform classes to one local term offering."""
        state = self._read_offerings()
        if not _valid_revision(expected_revision):
            return {"status": "invalid_input", "revision": state["revision"]}
        if expected_revision != state["revision"]:
            return {"status": "conflict", "revision": state["revision"]}
        if (
            not isinstance(class_refs, list)
            or not class_refs
            or not all(_valid_class_ref(item) for item in class_refs)
            or not isinstance(offering, dict)
            or not isinstance(offering.get("title"), str)
            or not offering["title"].strip()
            or (offering.get("term") is not None and not isinstance(offering.get("term"), str))
            or ("id" in offering and (not isinstance(offering["id"], str) or not offering["id"]))
            or not isinstance(replace_existing, bool)
        ):
            return {"status": "invalid_input", "revision": state["revision"]}
        normalized = list(dict.fromkeys(_class_ref_key(item) for item in class_refs))
        if len(normalized) != len(class_refs):
            return {"status": "invalid_input", "revision": state["revision"]}
        offering_id = offering.get("id") or uuid.uuid4().hex
        existing = state["offerings"].get(offering_id)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if existing is None:
            existing = {
                "id": offering_id,
                "title": offering["title"].strip(),
                "term": (offering.get("term") or "").strip(),
                "class_refs": [],
                "created_at": now,
                "archived": False,
            }
        elif (
            existing["title"] != offering["title"].strip()
            or existing.get("term", "") != (offering.get("term") or "").strip()
        ):
            return {"status": "conflict", "revision": state["revision"]}

        owners = state.setdefault("class_offerings", {})
        for ref in class_refs:
            key = _class_ref_key(ref)
            owner = owners.get(key)
            if owner and owner != offering_id and not replace_existing:
                return {"status": "conflict", "revision": state["revision"]}
        if replace_existing:
            for ref in class_refs:
                key = _class_ref_key(ref)
                old_id = owners.get(key)
                if old_id and old_id != offering_id and old_id in state["offerings"]:
                    state["offerings"][old_id]["class_refs"] = [
                        item for item in state["offerings"][old_id]["class_refs"]
                        if _class_ref_key(item) != key
                    ]
        for ref in class_refs:
            if ref not in existing["class_refs"]:
                existing["class_refs"].append(dict(ref))
            owners[_class_ref_key(ref)] = offering_id
        state["offerings"][offering_id] = existing
        state["revision"] += 1
        self._write_offerings(state)
        return {
            "status": "ok",
            "offering": existing,
            "revision": state["revision"],
        }

    def class_tracking(
        self,
        class_ref: dict,
        state_name: str,
        *,
        expected_revision: int,
        term: str | None = None,
    ) -> dict:
        """Set current/archive/unknown visibility without deleting class history."""
        state = self._read_offerings()
        if not _valid_revision(expected_revision):
            return {"status": "invalid_input", "revision": state["revision"]}
        if expected_revision != state["revision"]:
            return {"status": "conflict", "revision": state["revision"]}
        if (
            not _valid_class_ref(class_ref)
            or state_name not in {"current", "archived", "unknown"}
            or (term is not None and not isinstance(term, str))
        ):
            return {"status": "invalid_input", "revision": state["revision"]}
        key = _class_ref_key(class_ref)
        state.setdefault("tracking", {})[key] = {
            "class_ref": dict(class_ref),
            "state": state_name,
            "term": term.strip() if isinstance(term, str) else None,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        state["revision"] += 1
        self._write_offerings(state)
        return {"status": "ok", "revision": state["revision"]}

    def offerings(self) -> dict:
        state = self._read_offerings()
        return {
            "revision": state["revision"],
            "offerings": sorted(state["offerings"].values(), key=lambda item: item["id"]),
        }

    def offering_for(self, class_ref: dict) -> dict | None:
        if not _valid_class_ref(class_ref):
            return None
        state = self._read_offerings()
        offering_id = state.get("class_offerings", {}).get(_class_ref_key(class_ref))
        return state["offerings"].get(offering_id) if offering_id else None

    def class_tracking_view(self) -> list[dict]:
        state = self._read_offerings()
        by_key = state.get("tracking", {})
        refs = {
            _class_ref_key(ref): dict(ref)
            for offering in state["offerings"].values()
            for ref in offering.get("class_refs", [])
        }
        for key, record in by_key.items():
            refs[key] = record["class_ref"]
        return [
            by_key.get(key, {"class_ref": ref, "state": "unknown", "term": None})
            for key, ref in sorted(refs.items())
        ]

    def relate_assignments(
        self, task_refs: list[dict], reason: str, *, expected_revision: int,
        relation_type: str = "related",
    ) -> dict:
        """Record a student-confirmed relation without merging work records."""
        state = self._read_offerings()
        if not _valid_revision(expected_revision):
            return {"status": "invalid_input", "revision": state["revision"]}
        if expected_revision != state["revision"]:
            return {"status": "conflict", "revision": state["revision"]}
        if (
            not isinstance(task_refs, list)
            or len(task_refs) < 2
            or not all(_valid_task_ref(item) for item in task_refs)
            or not isinstance(reason, str)
            or not reason.strip()
            or not isinstance(relation_type, str)
            or relation_type not in {"related", "same_assignment"}
        ):
            return {"status": "invalid_input", "revision": state["revision"]}
        keyed = sorted((_task_ref_key(item), dict(item)) for item in task_refs)
        keys = [key for key, _ in keyed]
        if len(keys) != len(set(keys)):
            return {"status": "invalid_input", "revision": state["revision"]}
        normalized_refs = [item for _, item in keyed]
        relations = state.setdefault("assignment_relations", {})
        existing = next((
            relation for relation in relations.values()
            if [_task_ref_key(item) for item in relation.get("task_refs", [])] == keys
        ), None)
        clean_reason = reason.strip()
        if (
            existing
            and existing["reason"] == clean_reason
            and existing.get("relation_type", "related") == relation_type
        ):
            return {
                "status": "exists",
                "relation": existing,
                "revision": state["revision"],
            }
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if existing:
            existing.update({
                "reason": clean_reason,
                "relation_type": relation_type,
                "revision": existing["revision"] + 1,
                "updated_at": now,
            })
            relation = existing
        else:
            relation_id = uuid.uuid4().hex
            relation = {
                "id": relation_id,
                "task_refs": normalized_refs,
                "reason": clean_reason,
                "relation_type": relation_type,
                "revision": 1,
                "created_at": now,
                "updated_at": now,
            }
            relations[relation_id] = relation
        state["revision"] += 1
        self._write_offerings(state)
        return {"status": "ok", "relation": relation, "revision": state["revision"]}

    def assignment_relations(self) -> list[dict]:
        state = self._read_offerings()
        return sorted(
            state.get("assignment_relations", {}).values(), key=lambda item: item["id"]
        )

    def _read_offerings(self) -> dict:
        if not self._offerings_path.is_file():
            return {
                "schema_version": 1,
                "revision": 0,
                "offerings": {},
                "class_offerings": {},
                "tracking": {},
                "assignment_relations": {},
            }
        result = json.loads(self._offerings_path.read_text(encoding="utf-8"))
        if not isinstance(result, dict) or not isinstance(result.get("revision"), int):
            raise ValueError("offering manifest is invalid")
        result.setdefault("offerings", {})
        result.setdefault("class_offerings", {})
        result.setdefault("tracking", {})
        result.setdefault("assignment_relations", {})
        return result

    def _write_offerings(self, state: dict) -> None:
        self._catalog_root.mkdir(parents=True, exist_ok=True)
        temporary = self._offerings_path.with_name(".offerings.{}.tmp".format(uuid.uuid4().hex))
        try:
            temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self._offerings_path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def record_classes(
        self, connection: dict, observation: dict, attempted_at: str
    ) -> bool:
        """Record an attempt and replace classes only after complete coverage."""
        if (
            not isinstance(connection, dict)
            or not isinstance(connection.get("id"), str)
            or not connection["id"]
            or not isinstance(connection.get("platform"), str)
        ):
            raise ValueError("adapter connection identity is invalid")
        if not isinstance(observation, dict):
            raise ValueError("platform observation is invalid")
        successful = (
            observation.get("status") == "ok"
            and observation.get("scope") == "classes"
            and observation.get("coverage") == "complete"
        )

        key = hashlib.sha256(connection["id"].encode("utf-8")).hexdigest()
        target = self._root / key / "classes.json"
        previous = {}
        if target.is_file():
            previous = json.loads(target.read_text(encoding="utf-8"))
            if previous.get("connection", {}).get("id") != connection["id"]:
                raise ValueError("stored connection identity does not match")

        nodes = previous.get("nodes", [])
        last_success_at = previous.get("last_success_at")
        last_success_coverage = previous.get(
            "last_success_coverage", previous.get("coverage")
        )
        if successful:
            nodes = observation.get("nodes")
            if not isinstance(nodes, list):
                raise ValueError("complete class observation has no node list")
            class_ids = set()
            for node in nodes:
                if not isinstance(node, dict) or node.get("kind") != "class":
                    raise ValueError("class observation contains an invalid node")
                ref = node.get("ref")
                if (
                    not isinstance(ref, dict)
                    or ref.get("connection_id") != connection["id"]
                    or not isinstance(ref.get("class_id"), str)
                    or not ref["class_id"]
                ):
                    raise ValueError("class observation contains an invalid reference")
                class_id = ref["class_id"]
                if class_id in class_ids:
                    raise ValueError("class observation contains a duplicate class")
                class_ids.add(class_id)
            last_success_at = observation.get("observed_at") or attempted_at
            last_success_coverage = "complete"

        record = {
            "schema_version": 1,
            "connection": {
                "id": connection["id"],
                "platform": connection["platform"],
                "origin": connection.get("origin"),
            },
            "scope": "classes",
            "coverage": observation.get("coverage", "unknown"),
            "last_attempt_at": attempted_at,
            "last_success_at": last_success_at,
            "last_success_coverage": last_success_coverage,
            "last_attempt_status": observation.get("status", "failed"),
            "nodes": nodes,
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(".classes.{}.tmp".format(uuid.uuid4().hex))
        try:
            temporary.write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
        return successful

    def record_assignments(
        self, connection: dict, class_ref: dict, observation: dict, attempted_at: str
    ) -> bool:
        """Record one class inventory, retaining its last complete observation."""
        if (
            not isinstance(connection, dict)
            or not isinstance(connection.get("id"), str)
            or not connection["id"]
            or not isinstance(connection.get("platform"), str)
        ):
            raise ValueError("adapter connection identity is invalid")
        if (
            not isinstance(class_ref, dict)
            or class_ref.get("connection_id") != connection["id"]
            or not isinstance(class_ref.get("class_id"), str)
            or not class_ref["class_id"]
        ):
            raise ValueError("assignment class reference is invalid")
        if not isinstance(observation, dict):
            raise ValueError("platform observation is invalid")
        successful = (
            observation.get("status") == "ok"
            and observation.get("scope") == "assignments"
            and observation.get("coverage") == "complete"
        )

        connection_key = hashlib.sha256(connection["id"].encode("utf-8")).hexdigest()
        class_key = hashlib.sha256(class_ref["class_id"].encode("utf-8")).hexdigest()
        target = self._root / connection_key / "assignments" / (class_key + ".json")
        previous = {}
        if target.is_file():
            previous = json.loads(target.read_text(encoding="utf-8"))
            if (
                previous.get("connection", {}).get("id") != connection["id"]
                or previous.get("class_ref") != class_ref
            ):
                raise ValueError("stored assignment identity does not match")

        nodes = previous.get("nodes", [])
        last_success_at = previous.get("last_success_at")
        last_success_coverage = previous.get(
            "last_success_coverage", previous.get("coverage")
        )
        if successful:
            nodes = observation.get("nodes")
            if not isinstance(nodes, list):
                raise ValueError("complete assignment observation has no node list")
            refs = set()
            for node in nodes:
                if not isinstance(node, dict) or node.get("kind") != "assignment":
                    raise ValueError("assignment observation contains an invalid node")
                ref = node.get("ref")
                if (
                    not isinstance(ref, dict)
                    or ref.get("connection_id") != connection["id"]
                    or ref.get("class_id") != class_ref["class_id"]
                    or not isinstance(ref.get("assignment_id"), str)
                    or not ref["assignment_id"]
                    or (
                        ref.get("question_id") is not None
                        and (not isinstance(ref["question_id"], str) or not ref["question_id"])
                    )
                ):
                    raise ValueError("assignment observation contains an invalid reference")
                identity = (ref["assignment_id"], ref.get("question_id"))
                if identity in refs:
                    raise ValueError("assignment observation contains a duplicate task")
                refs.add(identity)
                if not isinstance(node.get("submission", {}), dict):
                    raise ValueError("assignment submission state is invalid")
                if not isinstance(node.get("evaluation", {}), dict):
                    raise ValueError("assignment evaluation state is invalid")
                if not isinstance(node.get("deadlines", []), list):
                    raise ValueError("assignment deadlines are invalid")
            last_success_at = observation.get("observed_at") or attempted_at
            last_success_coverage = "complete"

        record = {
            "schema_version": 1,
            "connection": {
                "id": connection["id"],
                "platform": connection["platform"],
                "origin": connection.get("origin"),
            },
            "class_ref": class_ref,
            "scope": "assignments",
            "coverage": observation.get("coverage", "unknown"),
            "last_attempt_at": attempted_at,
            "last_success_at": last_success_at,
            "last_success_coverage": last_success_coverage,
            "last_attempt_status": observation.get("status", "failed"),
            "nodes": nodes,
        }
        if is_failure_kind(observation.get("failure_kind")):
            record["failure_kind"] = observation["failure_kind"]
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(".assignments.{}.tmp".format(uuid.uuid4().hex))
        try:
            temporary.write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
        return successful

    def connections(self) -> list[dict]:
        """Read the latest attempt and last successful time for each connection."""
        if not self._root.is_dir():
            return []
        records = []
        for path in sorted(self._root.glob("*/classes.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            connection = record.get("connection", {})
            item = {
                "connection_id": connection.get("id"),
                "platform": connection.get("platform"),
                "scope": record.get("scope"),
                "coverage": record.get("coverage"),
                "last_attempt_at": record.get("last_attempt_at"),
                "last_success_at": record.get("last_success_at"),
                "last_success_coverage": record.get("last_success_coverage"),
                "last_attempt_status": record.get("last_attempt_status"),
            }
            if connection.get("label"):
                item["label"] = connection["label"]
            records.append(item)
        return records

    def assignment_observations(self) -> list[dict]:
        """Expose freshness per class without replacing the last complete data."""
        if not self._root.is_dir():
            return []
        observations = []
        for path in sorted(self._root.glob("*/assignments/*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            connection = record.get("connection", {})
            class_ref = record.get("class_ref", {})
            if (
                record.get("scope") != "assignments"
                or not isinstance(connection.get("id"), str)
                or not isinstance(class_ref, dict)
            ):
                raise ValueError("stored assignment observation is invalid: {}".format(path))
            item = {
                "connection_id": connection["id"],
                "platform": connection.get("platform"),
                "class_ref": class_ref,
                "coverage": record.get("coverage"),
                "last_attempt_at": record.get("last_attempt_at"),
                "last_attempt_status": record.get("last_attempt_status"),
                "last_success_at": record.get("last_success_at"),
                "last_success_coverage": record.get("last_success_coverage"),
            }
            if is_failure_kind(record.get("failure_kind")):
                item["failure_kind"] = record["failure_kind"]
            if connection.get("label"):
                item["label"] = connection["label"]
            observations.append(item)
        return observations

    def classes(self) -> list[dict]:
        """Read the last complete class observations for every connection."""
        if not self._root.is_dir():
            return []
        nodes = []
        for path in sorted(self._root.glob("*/classes.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get(
                "last_success_coverage", record.get("coverage")
            ) != "complete":
                continue
            if (
                record.get("scope") != "classes"
                or not isinstance(record.get("nodes"), list)
            ):
                raise ValueError("stored class observation is invalid: {}".format(path))
            platform = record["connection"]["platform"]
            for node in record["nodes"]:
                nodes.append({**node, "platform": platform})
        return nodes

    def assignments(self) -> list[dict]:
        """Read assignments from each class's last complete observation."""
        if not self._root.is_dir():
            return []
        nodes = []
        for path in sorted(self._root.glob("*/assignments/*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get(
                "last_success_coverage", record.get("coverage")
            ) != "complete":
                continue
            if (
                record.get("scope") != "assignments"
                or not isinstance(record.get("nodes"), list)
            ):
                raise ValueError("stored assignment observation is invalid: {}".format(path))
            connection = record["connection"]
            class_ref = record["class_ref"]
            for node in record["nodes"]:
                nodes.append({
                    **node,
                    "platform": connection["platform"],
                    "last_success_at": record.get("last_success_at"),
                    "class_ref": class_ref,
                })
        return nodes


def _valid_revision(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _valid_class_ref(value) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"connection_id", "class_id"}
        and all(isinstance(item, str) and item for item in value.values())
    )


def _class_ref_key(value: dict) -> str:
    return json.dumps([value["connection_id"], value["class_id"]], ensure_ascii=True)


def _valid_task_ref(value) -> bool:
    required = {"connection_id", "class_id", "assignment_id"}
    return (
        isinstance(value, dict)
        and required.issubset(value)
        and not set(value) - (required | {"question_id"})
        and all(isinstance(value[key], str) and value[key] for key in required)
        and (
            value.get("question_id") is None
            or isinstance(value.get("question_id"), str) and bool(value["question_id"])
        )
    )


def _task_ref_key(value: dict) -> str:
    return json.dumps(
        [
            value["connection_id"],
            value["class_id"],
            value["assignment_id"],
            value.get("question_id"),
        ],
        ensure_ascii=True,
    )
