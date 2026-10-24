"""cw.sharif.ir adapter for the common coursework observation interface."""

from __future__ import annotations

import re
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from .. import auth
from ..client import DEFAULT_BASE, Client, CwError
from ..diagnostics import is_failure_kind
from ..fetch import course_title
from ..intake import collect_course_materials, collect_site
from ..parse import map_header, parse_assignment_detail, parse_dump


class CWAdapter:
    """Fetch authenticated CW class and assignment observations.

    Cookies are returned only as private state so ``AccessManager`` can protect
    them with the operating system vault. Captcha images are temporary local files
    and the public challenge contains only their paths.
    """

    def __init__(
        self,
        connection: dict,
        *,
        client_factory=Client,
        challenge_root: str | Path,
        clock: Callable[[], str],
        captcha_reader=None,
    ):
        self.connection = connection
        self._client_factory = client_factory
        self._challenge_root = Path(challenge_root).expanduser().resolve()
        self._clock = clock
        self._captcha_reader = captcha_reader

    def observe(self, request: dict, context: dict) -> dict:
        if not _valid_request(request, self.connection):
            return {"status": "invalid_input"}
        credentials = context.get("credentials") if isinstance(context, dict) else None
        session = context.get("session", {}) if isinstance(context, dict) else {}
        client = self._client(session)
        if not self._is_logged_in(client):
            if not _valid_credentials(credentials):
                return {"status": "needs_credentials"}
            login_result = self._login(client, credentials)
            if login_result[0] == "challenge_required":
                return self._challenge_result(
                    client, request, credentials, login_result[1]
                )
            if login_result[0] != "ok":
                return {"status": "unavailable"}
            observation = self._observe_authenticated(client, request)
            return self._success(client, observation)

        observation = self._observe_authenticated(client, request)
        return self._success(client, observation)

    def resume(self, private_state: dict, response: dict) -> dict:
        request = private_state.get("request") if isinstance(private_state, dict) else None
        credentials = private_state.get("credentials") if isinstance(private_state, dict) else None
        if not _valid_request(request, self.connection) or not _valid_credentials(credentials):
            return {"status": "invalid_input"}
        if not isinstance(response, dict) or response.get("kind") != "readable_code":
            return {"status": "invalid_input"}
        client = self._client(private_state)
        attempt_dir = Path(private_state.get("attempt_dir", ""))
        try:
            state = auth.submit(
                client,
                credentials["username"],
                credentials["password"],
                attempt_dir,
                captcha=response.get("value"),
            )
        except (OSError, CwError, ValueError):
            return {"status": "unavailable"}
        old_image = Path(private_state.get("captcha_image", ""))
        if state["status"] in {auth.CAPTCHA_REQUIRED, auth.CAPTCHA_REJECTED}:
            if old_image.is_file() and old_image != state["image"]:
                old_image.unlink(missing_ok=True)
            return self._challenge_result(client, request, credentials, state, attempt_dir)
        if state["status"] != auth.OK:
            self._discard_attempt(attempt_dir)
            return {"status": "unavailable"}
        self._discard_attempt(attempt_dir)
        return self._success(client, self._observe_authenticated(client, request))

    def _client(self, session: dict) -> Client:
        client = self._client_factory(self.connection.get("origin") or DEFAULT_BASE)
        cookies = session.get("cookies") if isinstance(session, dict) else None
        if cookies:
            client.import_cookies(cookies)
        return client

    @staticmethod
    def _is_logged_in(client) -> bool:
        try:
            return bool(client.logged_in())
        except (ConnectionError, TimeoutError, OSError, CwError):
            return False

    def _login(self, client, credentials: dict) -> tuple[str, dict]:
        attempt_dir = self._new_attempt_dir()
        try:
            state = auth._attempt_captcha(
                client,
                credentials["username"],
                credentials["password"],
                attempt_dir,
                captcha_reader=self._captcha_reader,
            )
        except (OSError, CwError, ValueError):
            self._discard_attempt(attempt_dir)
            return "unavailable", {}
        if state["status"] == auth.OK:
            self._discard_attempt(attempt_dir)
            return "ok", {}
        if state["status"] in {auth.CAPTCHA_REQUIRED, auth.CAPTCHA_REJECTED}:
            state["attempt_dir"] = attempt_dir
            return "challenge_required", state
        self._discard_attempt(attempt_dir)
        return "unavailable", {}

    def _challenge_result(
        self, client, request: dict, credentials: dict, state: dict, attempt_dir=None
    ) -> dict:
        attempt_dir = Path(attempt_dir or state.get("attempt_dir", ""))
        image = Path(state["image"]).resolve()
        return {
            "status": "challenge_required",
            "challenge": {
                "kind": "readable_code",
                "display": {
                    "image": str(image),
                    "viewer": str(Path(state["viewer"]).resolve()),
                    "message": state.get("message", "کد تصویر ورود را بخوان."),
                    **({"ocr": state["ocr"]} if "ocr" in state else {}),
                },
                "expires_at": _expires(self._clock()),
            },
            "private_state": {
                "request": request,
                "credentials": credentials,
                "cookies": client.export_cookies(),
                "attempt_dir": str(attempt_dir),
                "captcha_image": str(image),
            },
        }

    def _success(self, client, observation: dict) -> dict:
        return {
            # Login succeeded even if reading the course page did not. Keep the
            # authenticated cookies so the next refresh can retry observation
            # without sending the user through CAPTCHA again.
            "status": "ok",
            "observation": observation,
            "private_state": {"cookies": client.export_cookies()},
        }

    def _observe_authenticated(self, client, request: dict) -> dict:
        scope = request["scope"]
        observed_at = self._clock()
        if scope == "assignment_detail":
            task_ref = request["task_ref"]
            assignment = request["assignment"]
            try:
                result = collect_site(
                    int(task_ref["assignment_id"]),
                    {
                        "course_id": int(task_ref["class_id"]),
                        "course": assignment["course"],
                        "term": assignment.get("term", ""),
                        "name": assignment["title"],
                        "due": assignment.get("due"),
                        "due_text": assignment.get("due_text", ""),
                        "url": assignment.get("url", ""),
                    },
                    client,
                    self._challenge_root.parent,
                )
            except (ConnectionError, TimeoutError, OSError, CwError, ValueError):
                return _failed(scope, observed_at, "transport_error")
            if result.get("status") == "authentication_required":
                return _failed(scope, observed_at, "authentication_required")
            if not isinstance(result.get("input"), dict):
                return _failed(scope, observed_at, "unexpected_response")
            received = {
                **result["input"],
                "assignment_ref": task_ref,
            }
            return {
                "status": "ok",
                "scope": scope,
                "coverage": "complete" if not result.get("open_questions") else "incomplete",
                "observed_at": observed_at,
                "input": received,
                "open_questions": result.get("open_questions", []),
            }
        if scope == "course_materials":
            try:
                result = collect_course_materials(
                    int(request["class_ref"]["class_id"]),
                    client,
                    self._challenge_root.parent,
                )
            except (ConnectionError, TimeoutError, OSError, CwError, ValueError):
                return {
                    "status": "partial",
                    "scope": scope,
                    "coverage": "incomplete",
                    "observed_at": observed_at,
                    "course_materials": [],
                    "course_materials_issues": [{"status": "unavailable"}],
                }
            return {
                "status": "ok",
                "scope": scope,
                "coverage": result.get("coverage", "incomplete"),
                "observed_at": observed_at,
                "course_materials": result.get("course_materials", []),
                "course_materials_issues": result.get("issues", []),
            }
        if scope == "classes":
            try:
                page = client.get("/my/courses.php")
            except (ConnectionError, TimeoutError, OSError, CwError):
                return _failed(scope, observed_at)
            ids = list(dict.fromkeys(re.findall(r"course/view\.php\?id=(\d+)", page)))
            if not ids:
                return _failed(scope, observed_at)
            nodes = []
            for course_id in ids:
                try:
                    course_page = client.get("/course/view.php", {"id": int(course_id)})
                except (ConnectionError, TimeoutError, OSError, CwError):
                    return _partial(
                        scope,
                        observed_at,
                        nodes,
                        {"course_id": course_id, "reason": "course_page_unavailable"},
                    )
                title = course_title(course_page)
                if not title:
                    return _partial(
                        scope,
                        observed_at,
                        nodes,
                        {"course_id": course_id, "reason": "course_title_not_found"},
                    )
                nodes.append({
                    "kind": "class",
                    "ref": {
                        "connection_id": self.connection["id"],
                        "class_id": course_id,
                    },
                    "title": title,
                    "url": "{}/course/view.php?id={}".format(
                        self.connection["origin"].rstrip("/"), course_id
                    ),
                })
            return _complete(scope, observed_at, nodes)

        class_ref = request["class_ref"]
        class_id = class_ref["class_id"]
        try:
            # The legacy assignment index now redirects to the global course
            # overview on CW. The per-course page is the canonical source used
            # by class discovery and contains the assignment rows.
            page = client.get("/course/view.php", {"id": int(class_id)})
        except (ConnectionError, TimeoutError, OSError, CwError):
            return _failed(scope, observed_at, "transport_error")
        if _login_page(page):
            return _failed(scope, observed_at, "authentication_required")
        try:
            with tempfile.TemporaryDirectory(prefix="cwtrack-cw-parse-") as folder:
                path = Path(folder) / "course_{}.html".format(class_id)
                path.write_text(page, encoding="utf-8")
                rows = parse_dump(Path(folder), datetime.now())
        except (OSError, CwError, ValueError):
            return _failed(scope, observed_at, "parser_error")
        if (
            not rows
            and not _recognizable_empty_assignment_page(page)
            and (_has_assignment_activity(page) or not _recognizable_course_page(page))
        ):
            return _failed(scope, observed_at, "unexpected_response")
        for row in rows:
            if row.get("status_text") != "unknown":
                continue
            try:
                detail_page = client.get(
                    "/mod/assign/view.php", {"id": int(row["cmid"])}
                )
            except (ConnectionError, TimeoutError, OSError, CwError):
                continue
            if _login_page(detail_page):
                continue
            row.update(parse_assignment_detail(detail_page, datetime.now()))
        nodes = []
        for row in rows:
            due = row.get("due")
            due_at = (
                datetime.fromtimestamp(due, timezone.utc).isoformat()
                if isinstance(due, int) else None
            )
            grade = str(row.get("grade") or "").strip()
            nodes.append({
                "kind": "assignment",
                "ref": {
                    "connection_id": self.connection["id"],
                    "class_id": class_id,
                    "assignment_id": str(row["cmid"]),
                },
                "title": row.get("name") or "تکلیف بدون عنوان",
                "url": row.get("url"),
                "submission": {
                    "state": row.get("status_text") or "unknown",
                    "raw": row.get("status_text") or "",
                },
                "evaluation": {
                    "state": "graded" if grade and grade != "-" else "unknown",
                    "grade": grade or None,
                },
                "deadlines": ([{
                    "kind": "regular",
                    "at": due_at,
                    "raw": row.get("due_text") or "",
                }] if row.get("due_text") else []),
            })
        return _complete(scope, observed_at, nodes)

    def _new_attempt_dir(self) -> Path:
        target = self._challenge_root / ("cw-" + uuid.uuid4().hex)
        target.mkdir(parents=True, exist_ok=False)
        return target

    @staticmethod
    def _discard_attempt(path: Path) -> None:
        shutil.rmtree(path, ignore_errors=True)


def _valid_request(request: dict, connection: dict) -> bool:
    if not isinstance(request, dict):
        return False
    if request.get("scope") == "classes":
        return set(request) == {"scope"}
    class_ref = request.get("class_ref")
    if request.get("scope") == "course_materials":
        return (
            set(request) == {"scope", "class_ref"}
            and isinstance(class_ref, dict)
            and set(class_ref) == {"connection_id", "class_id"}
            and class_ref.get("connection_id") == connection.get("id")
            and isinstance(class_ref.get("class_id"), str)
            and class_ref["class_id"].isdigit()
        )
    if request.get("scope") == "assignments":
        return (
            set(request) == {"scope", "class_ref"}
            and isinstance(class_ref, dict)
            and class_ref.get("connection_id") == connection.get("id")
            and isinstance(class_ref.get("class_id"), str)
            and class_ref["class_id"].isdigit()
        )
    task_ref = request.get("task_ref")
    required = {"connection_id", "class_id", "assignment_id"}
    return (
        request.get("scope") == "assignment_detail"
        and set(request) == {"scope", "task_ref", "assignment"}
        and isinstance(task_ref, dict)
        and required.issubset(task_ref)
        and not set(task_ref) - (required | {"question_id"})
        and task_ref.get("connection_id") == connection.get("id")
        and task_ref["class_id"].isdigit()
        and task_ref["assignment_id"].isdigit()
        and isinstance(request.get("assignment"), dict)
        and isinstance(request["assignment"].get("title"), str)
        and isinstance(request["assignment"].get("course"), str)
    )


def _valid_credentials(value) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("username"), str)
        and bool(value["username"])
        and isinstance(value.get("password"), str)
        and bool(value["password"])
    )


def _complete(scope: str, observed_at: str, nodes: list[dict]) -> dict:
    return {
        "status": "ok",
        "scope": scope,
        "coverage": "complete",
        "observed_at": observed_at,
        "nodes": nodes,
    }


def _failed(scope: str, observed_at: str, failure_kind: str | None = None) -> dict:
    result = {
        "status": "unavailable",
        "scope": scope,
        "coverage": "incomplete",
        "observed_at": observed_at,
        "nodes": [],
    }
    if is_failure_kind(failure_kind):
        result["failure_kind"] = failure_kind
    return result


def _partial(
    scope: str, observed_at: str, nodes: list[dict], failure: dict | None = None
) -> dict:
    result = {
        "status": "partial",
        "scope": scope,
        "coverage": "incomplete",
        "observed_at": observed_at,
        "nodes": nodes,
    }
    if failure is not None:
        result["failure"] = failure
    return result


def _login_page(page: str) -> bool:
    lowered = page.lower()
    return "login-form" in lowered or bool(re.search(r'name=["\']password["\']', lowered))


def _recognizable_empty_assignment_page(page: str) -> bool:
    lowered = page.lower()
    if any(needle in lowered for needle in ("noassignments", "no assignments")):
        return True
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", page, re.S | re.I):
        cells = [
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", cell)).strip()
            for cell in re.findall(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", row, re.S | re.I)
        ]
        header = map_header(cells)
        if "name" in header and ("due" in header or "status" in header):
            return True
    return False


def _has_assignment_activity(page: str) -> bool:
    return bool(
        re.search(r"\bmodtype_assign\b", page, re.I)
        or re.search(r"mod/assign/view\.php\?id=\d+", page, re.I)
    )


def _recognizable_course_page(page: str) -> bool:
    """Recognize a complete Moodle course section list as an empty assignment list."""
    return bool(
        re.search(r"<h1\b", page, re.I)
        and re.search(r"data-for=[\"']course_sectionlist[\"']", page, re.I)
        and re.search(
            r"class=[\"'][^\"']*\bcourse-section\b[^\"']*[\"']",
            page,
            re.I,
        )
    )


def _expires(now: str) -> str:
    try:
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        current = datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (current + timedelta(minutes=10)).isoformat()
