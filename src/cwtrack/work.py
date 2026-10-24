"""Durable local state for assignment work.

The module owns snapshots and their revision rules. A caller supplies the work to
save; it never executes a solution or interprets the meaning of its contents.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .client import CwError

_SAFE_ID = re.compile(r"[0-9a-f]{32}\Z")
_WRITABLE_STAGES = {"in_progress", "under_verification", "needs_completion"}
_CONTENT_FIELDS = (
    "source", "course_id", "course", "term", "cmid", "assignment_ref", "title", "prompt"
)


class _LockBusy(Exception):
    """Another process currently owns this work item's write lock."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_id(work_id: str) -> None:
    if not isinstance(work_id, str) or not _SAFE_ID.fullmatch(work_id):
        raise CwError("شناسهٔ کار نامعتبر است")


def _snapshot_path(root: Path, work_id: str, revision: int) -> Path:
    _validate_id(work_id)
    return root / work_id / "versions" / "{:06d}.json".format(revision)


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise CwError("خواندن پروندهٔ کار ناموفق بود: {}".format(path)) from exc


def _latest(root: Path, work_id: str) -> dict:
    _validate_id(work_id)
    versions = root / work_id / "versions"
    if not versions.is_dir():
        raise CwError("کار {} پیدا نشد".format(work_id))
    candidates = sorted(versions.glob("[0-9]*.json"))
    if not candidates:
        raise CwError("کار {} نسخهٔ سالمی ندارد".format(work_id))
    return _read(candidates[-1])


def _write_snapshot(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".{}.{}.tmp".format(path.stem, uuid.uuid4().hex))
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, path)
    except OSError as exc:
        raise CwError("ذخیرهٔ کار ناموفق بود: {}".format(path)) from exc
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _copy_attachments(root: Path, work_id: str, revision: int, files: list[dict]) -> list[dict]:
    if not files:
        return []
    folder = root / work_id / "versions" / "{:06d}.files-{}".format(
        revision, uuid.uuid4().hex
    )
    temporary = folder.with_name("." + folder.name + ".tmp")
    records = []
    names = set()
    try:
        temporary.mkdir(parents=True)
        for item in files:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise CwError("ساختار یکی از پیوست‌ها نامعتبر است")
            role = item.get("role", "material")
            if role not in {"prompt", "material"}:
                raise CwError("نقش پیوست باید prompt یا material باشد")
            source = Path(item["path"]).expanduser().resolve()
            if not source.is_file():
                raise CwError("پیوست پیدا نشد: {}".format(source))
            name = source.name
            stem, suffix = source.stem, source.suffix
            index = 2
            while name.casefold() in names:
                name = "{}-{}{}".format(stem, index, suffix)
                index += 1
            names.add(name.casefold())
            target = temporary / name
            shutil.copyfile(source, target)
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            records.append({
                "name": name,
                "role": role,
                "path": str((folder / name).relative_to(root)),
                "sha256": digest,
            })
        os.replace(temporary, folder)
    except (OSError, CwError) as exc:
        with contextlib.suppress(OSError):
            shutil.rmtree(temporary)
        if isinstance(exc, CwError):
            raise
        raise CwError("کپی پیوست ناموفق بود: {}".format(exc)) from exc
    return records


def _copy_deliverables(
    root: Path, work_id: str, revision: int, files: list[dict]
) -> list[dict]:
    if not files:
        return []
    folder = root / work_id / "deliveries" / "{:06d}-{}".format(revision, uuid.uuid4().hex)
    temporary = folder.with_name("." + folder.name + ".tmp")
    records = []
    names: set[str] = set()
    try:
        temporary.mkdir(parents=True)
        for item in files:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise CwError("مسیر هر فایل خروجی لازم است")
            role = item.get("role")
            if not isinstance(role, str) or not role.strip():
                raise CwError("نقش هر فایل خروجی لازم است")
            source = Path(item["path"]).expanduser().resolve()
            if not source.is_file() or source.stat().st_size == 0:
                raise CwError("فایل خروجی پیدا نشد یا خالی است: {}".format(source))
            name = source.name
            stem, suffix = source.stem, source.suffix
            index = 2
            while name.casefold() in names:
                name = "{}-{}{}".format(stem, index, suffix)
                index += 1
            names.add(name.casefold())
            target = temporary / name
            shutil.copyfile(source, target)
            records.append({
                "name": name,
                "role": role.strip(),
                "path": str((folder / name).relative_to(root)),
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "bytes": target.stat().st_size,
            })
        os.replace(temporary, folder)
    except (OSError, CwError) as exc:
        with contextlib.suppress(OSError):
            shutil.rmtree(temporary)
        if isinstance(exc, CwError):
            raise
        raise CwError("کپی فایل خروجی ناموفق بود: {}".format(exc)) from exc
    return records


def _fingerprint(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _input_fingerprint(input_data: dict, attachments: list[dict]) -> str:
    content = {key: input_data.get(key) for key in _CONTENT_FIELDS if key in input_data}
    files = [
        {"name": item["name"], "role": item["role"], "sha256": item.get("sha256", "")}
        for item in attachments
    ]
    return _fingerprint({"input": content, "attachments": files})


def _answer_fingerprint(sections: list[dict]) -> str:
    return _fingerprint(sections)


def _valid_report(report) -> bool:
    if not isinstance(report, dict) or report.get("status") not in {"prepared", "built", "failed"}:
        return False
    if not all(isinstance(report.get(key), str) and report[key].strip()
               for key in ("template_id", "recipe_version", "selection_reason", "project")):
        return False
    if not isinstance(report.get("template_sha256"), str) or not re.fullmatch(
        r"[0-9a-f]{64}", report["template_sha256"]
    ):
        return False
    if report["status"] == "built":
        return all(isinstance(report.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", report[key])
                   for key in ("source_digest", "source_sha256", "pdf_sha256",
                               "input_fingerprint", "answer_fingerprint"))
    return report["status"] != "failed" or bool(str(report.get("message", "")).strip())


def _resource_basis_digest(uses: list[dict], requirement_id: str | None = None) -> str:
    relevant = [
        use for use in uses
        if requirement_id is None or requirement_id in use.get("requirement_ids", [])
    ]
    return _fingerprint(relevant)


def _resource_check_basis(uses: list[dict], requirements: list[dict]) -> dict:
    return {
        requirement["id"]: _resource_basis_digest(uses, requirement["id"])
        for requirement in requirements
    }


def _hydrate(root: Path, value: dict) -> dict:
    """Return absolute attachment paths while keeping stored paths relocatable."""
    result = dict(value)
    if "report" in result:
        result["report_basis_digest"] = _fingerprint(result["report"])
    result.setdefault("resource_uses", [])
    result.setdefault("resource_basis_digest", _resource_basis_digest(result["resource_uses"]))
    result.setdefault(
        "resource_check_basis",
        _resource_check_basis(result["resource_uses"], result.get("requirements", [])),
    )
    result["folder"] = str((root / value["work_id"]).resolve())
    result["workspace"] = str((root / value["work_id"] / "workspace").resolve())
    result["attachments"] = [
        {**item, "path": str((root / item["path"]).resolve())}
        for item in value.get("attachments", [])
    ]
    if isinstance(value.get("delivery"), dict):
        result["delivery"] = {
            **value["delivery"],
            "files": [
                {**item, "path": str((root / item["path"]).resolve())}
                for item in value["delivery"].get("files", [])
            ],
        }
    return result


@contextlib.contextmanager
def _work_lock(path: Path):
    """Serialize revision checks and writes across processes on Windows and Unix."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            if path.stat().st_size == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                if getattr(exc, "winerror", None) in (33, 36):
                    raise _LockBusy from exc
                raise
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise _LockBusy from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _valid_assignment_ref(value) -> bool:
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


def start(request: dict, root: Path) -> dict:
    """Create one selected assignment and its first durable snapshot."""
    if not isinstance(request, dict) or len(request) != 1:
        return {"status": "invalid_input", "message": "یک ورودی تکلیف لازم است"}
    if "manual" in request:
        manual = request["manual"]
        if not isinstance(manual, dict):
            return {"status": "invalid_input", "message": "ساختار ورودی دستی نامعتبر است"}
        source = "manual"
        title, course, prompt = (
            manual.get("title"), manual.get("course", ""), manual.get("prompt", "")
        )
        attachments = manual.get("attachments", [])
        priority = manual.get("priority", 0)
        input_data = {"source": source, "course": course, "title": title, "prompt": prompt}
    elif "received" in request:
        received = request["received"]
        if not isinstance(received, dict):
            return {"status": "invalid_input", "message": "ساختار ورودی دریافت‌شده نامعتبر است"}
        source = received.get("source")
        title, course, prompt = (
            received.get("title"), received.get("course", ""), received.get("prompt", "")
        )
        attachments = received.get("attachments", [])
        priority = received.get("priority", 0)
        if source not in {"manual", "site", "quera"}:
            return {"status": "invalid_input", "message": "منشأ تکلیف نامعتبر است"}
        if source == "site" and any(
            not isinstance(received.get(key), int) or isinstance(received.get(key), bool)
            for key in ("cmid", "course_id")
        ):
            return {"status": "invalid_input", "message": "شناسهٔ تکلیف سامانه نامعتبر است"}
        if source == "quera" and not _valid_assignment_ref(received.get("assignment_ref")):
            return {"status": "invalid_input", "message": "شناسهٔ تکلیف کوئرا نامعتبر است"}
        input_data = {
            key: received[key]
            for key in (
                "source", "course_id", "course", "term", "cmid", "title", "prompt",
                "due", "due_text", "url", "assignment_ref",
            )
            if key in received
        }
    else:
        return {"status": "invalid_input", "message": "ورودی باید دستی یا دریافت‌شده باشد"}

    if not isinstance(title, str) or not title.strip():
        return {"status": "invalid_input", "message": "عنوان تکلیف لازم است"}
    if not isinstance(course, str) or not isinstance(prompt, str):
        return {"status": "invalid_input", "message": "مشخصات تکلیف باید متن باشند"}
    if not isinstance(attachments, list):
        return {"status": "invalid_input", "message": "پیوست‌ها باید فهرست باشند"}
    if not isinstance(priority, int) or isinstance(priority, bool):
        return {"status": "invalid_input", "message": "اولویت باید عدد صحیح باشد"}

    root = Path(root)
    if source in {"site", "quera"}:
        try:
            signatures = _attachment_signatures(attachments)
        except (CwError, OSError) as exc:
            return {"status": "invalid_input", "message": str(exc)}
        fingerprint_files = [
            {"name": name, "role": role, "sha256": digest}
            for name, role, digest in signatures
        ]
        incoming_fingerprint = _input_fingerprint(input_data, fingerprint_files)
        for existing in list_all(root):
            existing_input = existing.get("input", {})
            if (
                existing_input.get("source") == source
                and (
                    (
                        source == "site"
                        and existing_input.get("course_id") == input_data.get("course_id")
                        and existing_input.get("cmid") == input_data.get("cmid")
                    )
                    or (
                        source == "quera"
                        and existing_input.get("assignment_ref")
                        == input_data.get("assignment_ref")
                    )
                )
            ):
                return {
                    "status": "exists",
                    "input_changed": existing.get("input_fingerprint") != incoming_fingerprint,
                    "requested_input_fingerprint": incoming_fingerprint,
                    **existing,
                }
    work_id = uuid.uuid4().hex
    now = _now()
    needs_prompt = not prompt.strip()
    open_questions = (
        ["متن کامل تکلیف برای شروع حل لازم است."] if needs_prompt else []
    )
    value = {
        "work_id": work_id,
        "revision": 1,
        "stage": "ready_to_start",
        "priority": priority,
        "created_at": now,
        "updated_at": now,
        "input": {
            **input_data,
            "course": course.strip(),
            "title": title.strip(),
            "prompt": prompt.strip(),
        },
        "attachments": _copy_attachments(root, work_id, 1, attachments),
        "sections": [],
        "sources": [],
        "resource_uses": [],
        "resource_basis_digest": _resource_basis_digest([]),
        "resource_check_basis": {},
        "requirements": [],
        "checks": [],
        "open_questions": open_questions,
        "needs_reassessment": False,
    }
    value["input_fingerprint"] = _input_fingerprint(value["input"], value["attachments"])
    value["answer_fingerprint"] = _answer_fingerprint(value["sections"])
    _write_snapshot(_snapshot_path(root, work_id, 1), value)
    return {
        "status": "needs_input" if needs_prompt else "ok",
        "missing": ["prompt"] if needs_prompt else [],
        **_hydrate(root, value),
    }


def get(work_id: str, root: Path, revision: int | None = None) -> dict:
    """Read the latest snapshot or one immutable historical snapshot."""
    root = Path(root)
    if revision is None:
        return _hydrate(root, _latest(root, work_id))
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise CwError("شمارهٔ نسخه نامعتبر است")
    return _hydrate(root, _read(_snapshot_path(root, work_id, revision)))


def list_all(root: Path) -> list[dict]:
    """Read saved work snapshots for presentation and selection."""
    root = Path(root)
    if not root.is_dir():
        return []
    items = [_hydrate(root, _latest(root, folder.name)) for folder in root.iterdir()
             if folder.is_dir() and _SAFE_ID.fullmatch(folder.name)]
    return sorted(items, key=lambda item: (item["updated_at"], item["work_id"]), reverse=True)


def start_group(requests: list[dict], root: Path) -> dict:
    """Start an explicitly selected batch and persist its fixed membership/order."""
    if not isinstance(requests, list) or not requests or not all(
        isinstance(request, dict) for request in requests
    ):
        return {"status": "invalid_input", "message": "فهرست تکالیف انتخاب‌شده لازم است"}

    def order(request: dict) -> tuple[int, float]:
        payload = request.get("received", request.get("manual", {}))
        if not isinstance(payload, dict):
            payload = {}
        priority = payload.get("priority", 0)
        if not isinstance(priority, int) or isinstance(priority, bool):
            priority = 0
        due = payload.get("due")
        if isinstance(due, (int, float)) and not isinstance(due, bool):
            due_order = float(due)
        elif isinstance(due, str) and due.strip():
            try:
                due_order = datetime.fromisoformat(due.replace("Z", "+00:00")).timestamp()
            except ValueError:
                due_order = float("inf")
        else:
            due_order = float("inf")
        return (-priority, due_order)

    selected = sorted(requests, key=order)
    root = Path(root)
    group_id = uuid.uuid4().hex
    members = []
    successful = 0
    for request in selected:
        try:
            result = start(request, root)
        except CwError as exc:
            result = {"status": "failed", "message": str(exc)}
        member = {"status": result.get("status", "failed")}
        if result.get("work_id"):
            member["work_id"] = result["work_id"]
            member["title"] = result.get("input", {}).get("title", "")
            member["priority"] = result.get("priority", 0)
            member["requested_input_fingerprint"] = result.get(
                "requested_input_fingerprint", result.get("input_fingerprint", "")
            )
            successful += 1
        else:
            member["message"] = result.get("message", "شروع این تکلیف ناموفق بود")
        members.append(member)

    result_status = "ok" if successful == len(selected) else "partial" if successful else "failed"
    group = {
        "group_id": group_id,
        "status": result_status,
        "created_at": _now(),
        "updated_at": _now(),
        "members": members,
    }
    _write_snapshot(root / "groups" / (group_id + ".json"), group)
    return {"status": result_status, **get_group(group_id, root)}


def get_group(group_id: str, root: Path) -> dict:
    """Read a stable group manifest and hydrate its currently saved work items."""
    _validate_id(group_id)
    root = Path(root)
    group_path = root / "groups" / (group_id + ".json")
    group = _read(group_path)
    members = []
    for member in group.get("members", []):
        if "work_id" not in member:
            members.append(dict(member))
            continue
        try:
            current = _hydrate(root, _latest(root, member["work_id"]))
        except CwError:
            members.append({**member, "status": "not_found"})
        else:
            hydrated = {**current, "group_status": member["status"]}
            if member.get("requested_input_fingerprint"):
                hydrated["input_changed"] = (
                    member["requested_input_fingerprint"] != current.get("input_fingerprint")
                )
            members.append(hydrated)
    return {**group, "members": members}


def sync(work_id: str, received: dict, expected_revision: int, root: Path) -> dict:
    """Append a fresh intake snapshot and mark changed assignment content for review."""
    _validate_id(work_id)
    if not isinstance(received, dict):
        return {"status": "invalid_input", "message": "ورودی دریافت‌شده باید یک شیء باشد"}
    source = received.get("source")
    title, course, prompt = (
        received.get("title"), received.get("course", ""), received.get("prompt", "")
    )
    files = received.get("attachments", [])
    if source not in {"manual", "site", "quera"}:
        return {"status": "invalid_input", "message": "منشأ تکلیف نامعتبر است"}
    if not isinstance(title, str) or not title.strip() or not isinstance(course, str) or not isinstance(prompt, str):
        return {"status": "invalid_input", "message": "عنوان، درس و متن تکلیف باید معتبر باشند"}
    if not isinstance(files, list):
        return {"status": "invalid_input", "message": "پیوست‌ها باید فهرست باشند"}
    if not prompt.strip() and not files:
        return {"status": "needs_input", "message": "دریافت تازه متن یا پیوستی ندارد؛ نسخهٔ قبلی حفظ شد"}
    if source == "site" and any(
        not isinstance(received.get(key), int) or isinstance(received.get(key), bool)
        for key in ("cmid", "course_id")
    ):
        return {"status": "invalid_input", "message": "شناسهٔ تکلیف سامانه نامعتبر است"}
    if source == "quera" and not _valid_assignment_ref(received.get("assignment_ref")):
        return {"status": "invalid_input", "message": "شناسهٔ تکلیف کوئرا نامعتبر است"}
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 1:
        return {"status": "invalid_input", "message": "شمارهٔ نسخه نامعتبر است"}

    input_data = {
        key: received[key]
        for key in (
            "source", "course_id", "course", "term", "cmid", "title", "prompt",
            "due", "due_text", "url", "assignment_ref",
        )
        if key in received
    }
    input_data.update({"course": course.strip(), "title": title.strip(), "prompt": prompt.strip()})
    try:
        signatures = _attachment_signatures(files)
    except (CwError, OSError) as exc:
        return {"status": "invalid_input", "message": str(exc)}

    root = Path(root)
    lock_path = root / work_id / ".write.lock"
    try:
        with _work_lock(lock_path):
            current = _latest(root, work_id)
            if current["revision"] != expected_revision:
                return {"status": "conflict", "revision": current["revision"]}
            old_signatures = [
                (item["name"], item["role"], item.get("sha256", ""))
                for item in current.get("attachments", [])
            ]
            content_changed = (
                any(current.get("input", {}).get(key) != input_data.get(key) for key in _CONTENT_FIELDS)
                or old_signatures != signatures
            )
            metadata_changed = current.get("input", {}) != input_data
            if not content_changed and not metadata_changed:
                return {
                    "status": "exists",
                    "work_id": work_id,
                    "revision": current["revision"],
                    "needs_reassessment": current.get("needs_reassessment", False),
                }
            revision = current["revision"] + 1
            attachments = (
                _copy_attachments(root, work_id, revision, files)
                if content_changed else current.get("attachments", [])
            )
            has_progress = current["stage"] != "ready_to_start" or any(
                current.get(key)
                for key in ("sections", "sources", "requirements", "checks", "delivery")
            )
            needs_reassessment = current.get("needs_reassessment", False) or (
                content_changed and has_progress
            )
            stage = "needs_completion" if needs_reassessment else current["stage"]
            open_questions = list(current.get("open_questions", []))
            if input_data["prompt"].strip():
                open_questions = [
                    question for question in open_questions
                    if question != "متن کامل تکلیف برای شروع حل لازم است."
                ]
            value = {
                **current,
                "revision": revision,
                "stage": stage,
                "updated_at": _now(),
                "input": input_data,
                "attachments": attachments,
                "needs_reassessment": needs_reassessment,
                "open_questions": open_questions,
            }
            value["input_fingerprint"] = _input_fingerprint(input_data, attachments)
            _write_snapshot(_snapshot_path(root, work_id, revision), value)
    except _LockBusy:
        return {"status": "busy", "message": "کار در حال ذخیره توسط فراخوان دیگری است"}
    except OSError as exc:
        raise CwError("ثبت دریافت تازه ناموفق بود: {}".format(exc)) from exc
    return {
        "status": "ok",
        "work_id": work_id,
        "revision": revision,
        "content_changed": content_changed,
        "metadata_changed": metadata_changed,
        "needs_reassessment": needs_reassessment,
        "stage": stage,
    }


def _attachment_signatures(files: list[dict]) -> list[tuple[str, str, str]]:
    signatures = []
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise CwError("ساختار یکی از پیوست‌ها نامعتبر است")
        role = item.get("role", "material")
        if role not in {"prompt", "material"}:
            raise CwError("نقش پیوست باید prompt یا material باشد")
        path = Path(item["path"]).expanduser()
        if not path.is_file():
            raise CwError("پیوست پیدا نشد: {}".format(path))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        signatures.append((path.name, role, digest))
    return signatures


def save(work_id: str, progress: dict, expected_revision: int, root: Path) -> dict:
    """Append a checkpoint if it was based on the latest revision."""
    _validate_id(work_id)
    if not isinstance(progress, dict):
        return {"status": "invalid_input", "message": "پیشرفت باید یک شیء باشد"}
    if "report" in progress and not _valid_report(progress["report"]):
        return {"status": "invalid_input", "message": "مشخصات قالب یا ساخت گزارش نامعتبر است"}
    stage = progress.get("stage")
    sections = progress.get("sections")
    questions = progress.get("open_questions")
    if stage not in _WRITABLE_STAGES:
        return {"status": "invalid_input", "message": "مرحلهٔ کار نامعتبر است"}
    if not isinstance(sections, list) or not isinstance(questions, list):
        return {"status": "invalid_input", "message": "بخش‌ها و سؤال‌ها باید فهرست باشند"}
    for section in sections:
        if not isinstance(section, dict) or not all(
            isinstance(section.get(key), str) for key in ("id", "title", "content")
        ):
            return {"status": "invalid_input", "message": "ساختار یکی از بخش‌ها نامعتبر است"}
    if not all(isinstance(question, str) for question in questions):
        return {"status": "invalid_input", "message": "سؤال‌های باز باید متن باشند"}
    for key in ("requirements", "checks", "sources", "limitations"):
        if key in progress and not isinstance(progress[key], list):
            return {"status": "invalid_input", "message": "{} باید فهرست باشد".format(key)}
    for requirement in progress.get("requirements", []):
        if not isinstance(requirement, dict) or not all(
            isinstance(requirement.get(key), str) and requirement.get(key).strip()
            for key in ("id", "description", "verification_method")
        ) or not isinstance(requirement.get("deliverable_roles"), list) or not requirement[
            "deliverable_roles"
        ] or not all(
            isinstance(role, str) and role for role in requirement["deliverable_roles"]
        ):
            return {"status": "invalid_input", "message": "ساختار یکی از الزام‌ها نامعتبر است"}
    for check in progress.get("checks", []):
        if not isinstance(check, dict) or not all(
            isinstance(check.get(key), str)
            for key in (
                "requirement_id", "method", "result", "evidence",
                "input_fingerprint", "answer_fingerprint",
            )
        ) or check["result"] not in {"pass", "fail", "not_run"}:
            return {"status": "invalid_input", "message": "ساختار یکی از بررسی‌ها نامعتبر است"}
        deliverables = check.get("deliverables", [])
        if not isinstance(deliverables, list) or any(
            not isinstance(item, dict)
            or not isinstance(item.get("role"), str)
            or not isinstance(item.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
            for item in deliverables
        ):
            return {"status": "invalid_input", "message": "اثر انگشت فایل بررسی‌شده نامعتبر است"}
    for source in progress.get("sources", []):
        if not isinstance(source, dict) or not isinstance(source.get("title"), str) or not isinstance(
            source.get("reference"), str
        ):
            return {"status": "invalid_input", "message": "ساختار یکی از منابع نامعتبر است"}
    for use in progress.get("resource_uses", []):
        if not isinstance(use, dict) or not all(
            isinstance(use.get(key), str) and use.get(key).strip()
            for key in ("capture_id", "resource_id", "sha256", "purpose")
        ) or not re.fullmatch(r"[0-9a-f]{64}", use["sha256"]):
            return {"status": "invalid_input", "message": "نسخهٔ منبع استفاده‌شده نامعتبر است"}
        if not isinstance(use.get("used_extent"), dict) or not all(
            isinstance(use.get(key), list)
            and use[key]
            and all(isinstance(item, str) and item.strip() for item in use[key])
            for key in ("part_ids", "section_ids", "requirement_ids")
        ):
            return {"status": "invalid_input", "message": "محدودهٔ استفاده از منبع نامعتبر است"}
    if "limitations" in progress and not all(
        isinstance(item, str) for item in progress["limitations"]
    ):
        return {"status": "invalid_input", "message": "محدودیت‌ها باید متن باشند"}
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 1:
        return {"status": "invalid_input", "message": "شمارهٔ نسخه نامعتبر است"}

    root = Path(root)
    lock_path = root / work_id / ".write.lock"
    try:
        with _work_lock(lock_path):
            current = _latest(root, work_id)
            if current["revision"] != expected_revision:
                return {"status": "conflict", "revision": current["revision"]}
            requirement_ids = {
                item["id"] for item in progress.get(
                    "requirements", current.get("requirements", [])
                )
            }
            section_ids = {section["id"] for section in sections}
            if any(
                not set(use["requirement_ids"]).issubset(requirement_ids)
                or not set(use["section_ids"]).issubset(section_ids)
                for use in progress.get("resource_uses", [])
            ):
                return {
                    "status": "invalid_input",
                    "message": "منبع باید به الزام و بخش ثبت‌شدهٔ همین پاسخ وصل شود",
                }
            revision = current["revision"] + 1
            resource_uses = progress.get("resource_uses", current.get("resource_uses", []))
            resource_uses_changed = resource_uses != current.get("resource_uses", [])
            needs_reassessment = current.get("needs_reassessment", False) or (
                resource_uses_changed and bool(current.get("checks"))
            )
            saved_stage = "needs_completion" if needs_reassessment else stage
            value = {
                **current,
                "revision": revision,
                "stage": saved_stage,
                "sections": sections,
                "open_questions": questions,
                "updated_at": _now(),
                "resource_uses": resource_uses,
                "resource_basis_digest": _resource_basis_digest(resource_uses),
                "needs_reassessment": needs_reassessment,
            }
            for key in ("requirements", "checks", "sources", "limitations", "report"):
                if key in progress:
                    value[key] = progress[key]
            value["answer_fingerprint"] = _answer_fingerprint(sections)
            value["resource_check_basis"] = _resource_check_basis(
                resource_uses, value.get("requirements", [])
            )
            if sections != current.get("sections", []) and current.get("checks"):
                value["needs_reassessment"] = True
            if "report" in value:
                value["report_basis_digest"] = _fingerprint(value["report"])
                if value["report"] != current.get("report") and current.get("checks"):
                    value["needs_reassessment"] = True
                if value["report"]["status"] == "failed":
                    saved_stage = value["stage"] = "needs_completion"
            path = _snapshot_path(root, work_id, revision)
            if path.exists():
                return {"status": "conflict", "revision": current["revision"]}
            _write_snapshot(path, value)
    except _LockBusy:
        return {"status": "busy", "message": "کار در حال ذخیره توسط فراخوان دیگری است"}
    except OSError as exc:
        raise CwError("ذخیرهٔ کار ناموفق بود: {}".format(exc)) from exc

    return {
        "status": "ok", "work_id": work_id, "revision": revision, "stage": saved_stage,
        "input_fingerprint": value["input_fingerprint"],
        "answer_fingerprint": value["answer_fingerprint"],
        "resource_basis_digest": value["resource_basis_digest"],
        "resource_check_basis": value["resource_check_basis"],
        **({"report_basis_digest": value["report_basis_digest"]} if "report" in value else {}),
    }


def finish(work_id: str, delivery: dict, expected_revision: int, root: Path) -> dict:
    """Persist deliverables and decide whether the student can review them."""
    _validate_id(work_id)
    if not isinstance(delivery, dict):
        return {"status": "invalid_input", "message": "اطلاعات خروجی باید یک شیء باشد"}
    files = delivery.get("files")
    note = delivery.get("note")
    limitations = delivery.get("limitations", [])
    if not isinstance(files, list) or not isinstance(note, str) or not isinstance(limitations, list):
        return {"status": "invalid_input", "message": "ساختار خروجی نامعتبر است"}
    if not all(isinstance(item, str) for item in limitations):
        return {"status": "invalid_input", "message": "محدودیت‌ها باید متن باشند"}
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 1:
        return {"status": "invalid_input", "message": "شمارهٔ نسخه نامعتبر است"}

    root = Path(root)
    lock_path = root / work_id / ".write.lock"
    try:
        with _work_lock(lock_path):
            current = _latest(root, work_id)
            if current["revision"] != expected_revision:
                return {"status": "conflict", "revision": current["revision"]}
            revision = current["revision"] + 1
            stored_files = _copy_deliverables(root, work_id, revision, files)
            requirements = current.get("requirements", [])
            checks = current.get("checks", [])
            roles = {item["role"] for item in stored_files}
            missing = []
            report = current.get("report")
            if report:
                if (
                    report.get("status") != "built"
                    or report.get("input_fingerprint") != current.get("input_fingerprint")
                    or report.get("answer_fingerprint") != current.get("answer_fingerprint")
                ):
                    missing.append("PDF این نسخهٔ پاسخ با قالب انتخاب‌شده ساخته نشده است")
                for role, key in (("pdf", "pdf_sha256"), ("latex_source", "source_sha256")):
                    if not any(item["role"] == role and item["sha256"] == report.get(key)
                               for item in stored_files):
                        missing.append("خروجی ساخته‌شده با نقش {} لازم است".format(role))
            if not note.strip():
                missing.append("یادداشت تحویل لازم است")
            if not stored_files:
                missing.append("حداقل یک فایل خروجی لازم است")
            if not requirements:
                missing.append("الزام‌های تکلیف ثبت نشده‌اند")
            all_current_checks = []
            for requirement in requirements:
                required_roles = requirement.get("deliverable_roles", [])
                for role in required_roles:
                    if role not in roles:
                        missing.append("فایل خروجی با نقش {} لازم است".format(role))
                current_checks = [
                    check for check in checks
                    if check.get("requirement_id") == requirement.get("id")
                    and check.get("result") == "pass"
                    and check.get("method", "").strip() == requirement.get("verification_method")
                    and check.get("evidence", "").strip()
                    and check.get("input_fingerprint") == current.get("input_fingerprint")
                    and check.get("answer_fingerprint") == current.get("answer_fingerprint")
                    and (not report or check.get("report_basis_digest") == _fingerprint(report))
                    and check.get("resource_basis_digest", _resource_basis_digest([]))
                    == current.get("resource_check_basis", {}).get(
                        requirement.get("id"), _resource_basis_digest([])
                    )
                    and all(
                        any(
                            evidence.get("role") == role
                            and any(
                                output.get("role") == role
                                and output.get("sha256") == evidence.get("sha256")
                                for output in stored_files
                            )
                            for evidence in check.get("deliverables", [])
                        )
                        for role in requirement.get("deliverable_roles", [])
                    )
                ]
                if not current_checks:
                    missing.append(
                        "بررسی معتبر پاسخ و فایل‌ها برای الزام {} ثبت نشده است".format(
                            requirement.get("id", "؟")
                        )
                    )
                else:
                    all_current_checks.extend(current_checks)
            verified_files = {
                (file.get("role"), file.get("sha256"))
                for check in all_current_checks
                for file in check.get("deliverables", [])
            }
            for output in stored_files:
                if (output["role"], output["sha256"]) not in verified_files:
                    missing.append("فایل خروجی {} بررسی نشده است".format(output["name"]))
            if current.get("open_questions"):
                missing.append("{} سؤال هنوز منتظر پاسخ است".format(len(current["open_questions"])))

            stage = "ready_for_student_review" if not missing else "needs_completion"
            value = {
                **current,
                "revision": revision,
                "stage": stage,
                "updated_at": _now(),
                "needs_reassessment": bool(missing and current.get("needs_reassessment", False)),
                "delivery": {
                    "files": stored_files,
                    "note": note.strip(),
                    "limitations": limitations,
                    "created_at": _now(),
                },
            }
            _write_snapshot(_snapshot_path(root, work_id, revision), value)
    except _LockBusy:
        return {"status": "busy", "message": "کار در حال ذخیره توسط فراخوان دیگری است"}
    except CwError as exc:
        return {"status": "invalid_input", "message": str(exc)}
    except OSError as exc:
        raise CwError("ثبت خروجی ناموفق بود: {}".format(exc)) from exc

    return {
        "status": "ok" if stage == "ready_for_student_review" else "needs_completion",
        "work_id": work_id,
        "revision": revision,
        "stage": stage,
        "missing": missing,
        "files": _hydrate(root, value)["delivery"]["files"],
    }
