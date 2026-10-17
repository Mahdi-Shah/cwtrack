"""First-party Quera authentication and conservative coursework observations.

Quera's current login page is a multi-step client flow. Its route map is not a
public API contract, so this adapter treats unrecognized responses and pages as
incomplete instead of replacing a prior complete observation with an empty list.
"""

from __future__ import annotations

import http.cookiejar
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Callable


class QueraHTTPClient:
    """Small JSON/HTML transport that retains cookies only in process memory."""

    def __init__(self, base: str, timeout: int = 30):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )

    def get(self, path: str) -> tuple[str, str]:
        response = self._open(self._request(path))
        return response.geturl(), response.read(12 * 1024 * 1024).decode("utf-8", "replace")

    def post_json(self, path: str, payload: dict) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        csrf = next(
            (cookie.value for cookie in self.cookie_jar if cookie.name == "csrftoken"),
            None,
        )
        if csrf:
            headers["X-CSRFToken"] = csrf
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = self._request(path, data=body, headers=headers)
        try:
            response = self.opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as error:
            raw = error.read(1024 * 1024).decode("utf-8", "replace")
            result = _json_object(raw)
            result["_http_status"] = error.code
            return result
        raw = response.read(1024 * 1024).decode("utf-8", "replace")
        result = _json_object(raw)
        result["_http_status"] = response.status
        return result

    def export_cookies(self) -> list[dict]:
        return [
            {
                "version": cookie.version,
                "name": cookie.name,
                "value": cookie.value,
                "port": cookie.port,
                "port_specified": cookie.port_specified,
                "domain": cookie.domain,
                "domain_specified": cookie.domain_specified,
                "domain_initial_dot": cookie.domain_initial_dot,
                "path": cookie.path,
                "path_specified": cookie.path_specified,
                "secure": cookie.secure,
                "expires": cookie.expires,
                "discard": cookie.discard,
                "rest": dict(cookie._rest),
                "rfc2109": cookie.rfc2109,
            }
            for cookie in self.cookie_jar
        ]

    def import_cookies(self, cookies: list[dict]) -> None:
        if not isinstance(cookies, list):
            raise ValueError("cookie state must be a list")
        for item in cookies:
            if not isinstance(item, dict) or not all(
                isinstance(item.get(field), str)
                for field in ("name", "value", "domain", "path")
            ):
                raise ValueError("cookie state is invalid")
            self.cookie_jar.set_cookie(http.cookiejar.Cookie(
                version=int(item.get("version", 0)),
                name=item["name"],
                value=item["value"],
                port=item.get("port"),
                port_specified=bool(item.get("port_specified", False)),
                domain=item["domain"],
                domain_specified=bool(item.get("domain_specified", False)),
                domain_initial_dot=bool(item.get("domain_initial_dot", False)),
                path=item["path"],
                path_specified=bool(item.get("path_specified", True)),
                secure=bool(item.get("secure", False)),
                expires=item.get("expires"),
                discard=bool(item.get("discard", True)),
                comment=None,
                comment_url=None,
                rest=dict(item.get("rest", {})),
                rfc2109=bool(item.get("rfc2109", False)),
            ))

    def _request(self, path: str, *, data=None, headers=None):
        url = urllib.parse.urljoin(self.base + "/", path.lstrip("/"))
        parsed = urllib.parse.urlsplit(url)
        base = urllib.parse.urlsplit(self.base)
        if parsed.scheme != base.scheme or parsed.netloc != base.netloc:
            raise ValueError("Quera request left the configured origin")
        request_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36"
            ),
            "Referer": self.base + "/accounts/login",
        }
        request_headers.update(headers or {})
        return urllib.request.Request(url, data=data, headers=request_headers)

    def _open(self, request):
        response = self.opener.open(request, timeout=self.timeout)
        return response


class QueraAdapter:
    """Authenticate to Quera and report only confidently parsed course data."""

    def __init__(self, connection: dict, *, client_factory=QueraHTTPClient,
                 clock: Callable[[], str]):
        self.connection = connection
        self._client_factory = client_factory
        self._clock = clock

    def observe(self, request: dict, context: dict) -> dict:
        if not _valid_request(request, self.connection):
            return {"status": "invalid_input"}
        credentials = context.get("credentials") if isinstance(context, dict) else None
        session = context.get("session", {}) if isinstance(context, dict) else {}
        client = self._client(session)
        if not self._logged_in(client):
            if not _valid_credentials(credentials):
                return {"status": "needs_credentials"}
            start = self._begin_login(client, credentials)
            if start.get("status") != "ok":
                return self._with_private_state(start, client, request, credentials)
            if not self._logged_in(client):
                return {"status": "unavailable"}
        observation = self._observe_authenticated(client, request)
        return {
            "status": "ok" if observation.get("status") == "ok" else "unavailable",
            "observation": observation,
            "private_state": {"cookies": client.export_cookies()},
        }

    def resume(self, private_state: dict, response: dict) -> dict:
        if not isinstance(private_state, dict) or not isinstance(response, dict):
            return {"status": "invalid_input"}
        request = private_state.get("request")
        credentials = private_state.get("credentials")
        if not _valid_request(request, self.connection) or not _valid_credentials(credentials):
            return {"status": "invalid_input"}
        client = self._client(private_state)
        if response.get("kind") == "otp":
            result = self._verify(client, credentials, "otp", response.get("value", ""))
            if result.get("status") == "challenge_required":
                return self._with_private_state(result, client, request, credentials)
            if result.get("status") != "ok" or not self._logged_in(client):
                return {"status": "unavailable"}
            observation = self._observe_authenticated(client, request)
            return {
                "status": "ok" if observation.get("status") == "ok" else "unavailable",
                "observation": observation,
                "private_state": {"cookies": client.export_cookies()},
            }
        # A reCAPTCHA token belongs to the interactive browser challenge. The
        # adapter never OCRs it, fabricates it, or treats a click as authentication.
        if response.get("kind") == "interactive_completed":
            return {"status": "unavailable"}
        return {"status": "invalid_input"}

    def _client(self, session: dict):
        client = self._client_factory(self.connection.get("origin") or "https://quera.org")
        if isinstance(session, dict) and session.get("cookies"):
            client.import_cookies(session["cookies"])
        return client

    def _logged_in(self, client) -> bool:
        try:
            url, page = client.get("/course/")
        except (OSError, TimeoutError, ConnectionError, ValueError):
            return False
        if _is_login_url(url):
            return False
        try:
            data = re.search(
                r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
                page,
                re.S | re.I,
            )
            parsed = json.loads(data.group(1)) if data else {}
            current = (
                parsed.get("props", {}).get("pageProps", {})
                .get("globalServerValues", {}).get("currentUser", {})
            )
            return current.get("is_authenticated") is True
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            return False

    def _begin_login(self, client, credentials: dict) -> dict:
        try:
            client.get("/accounts/login?next=%2Fcourse%2F")
            response = client.post_json("/accounts/api/login/", {
                "identifier": credentials["username"],
                "captcha_token": "",
                "preferred_process": "password",
            })
        except (OSError, TimeoutError, ConnectionError, ValueError):
            return {"status": "unavailable"}
        challenge = _recaptcha_challenge(response)
        if challenge:
            return challenge
        next_step = response.get("next_step")
        if next_step == "password":
            result = self._verify(client, credentials, "password", credentials["password"])
            return result
        if next_step == "otp":
            return {
                "status": "challenge_required",
                "challenge": {
                    "kind": "otp",
                    "display": {"message": "کد یک‌بارمصرف ارسال شد.",
                                 "user_wait": response.get("user_wait")},
                    "expires_at": _expires(self._clock()),
                },
            }
        return {"status": "unavailable"}

    def _verify(self, client, credentials: dict, step: str, value: str) -> dict:
        if not isinstance(value, str) or not value.strip():
            return {"status": "invalid_input"}
        try:
            response = client.post_json(
                "/accounts/api/login/verify?next=%2Fcourse%2F",
                {
                    "identifier": credentials["username"],
                    "step": step,
                    "credential": value,
                    "captcha_token": "",
                },
            )
        except (OSError, TimeoutError, ConnectionError, ValueError):
            return {"status": "unavailable"}
        challenge = _recaptcha_challenge(response)
        if challenge:
            return challenge
        redirect = response.get("redirect_url")
        if not isinstance(redirect, str):
            return {"status": "unavailable"}
        origin = self.connection.get("origin") or "https://quera.org"
        url = urllib.parse.urlsplit(urllib.parse.urljoin(origin + "/", redirect))
        expected = urllib.parse.urlsplit(origin)
        if url.scheme != expected.scheme or url.netloc != expected.netloc:
            return {"status": "unavailable"}
        try:
            client.get(urllib.parse.urlunsplit(("", "", url.path, url.query, "")))
        except (OSError, TimeoutError, ConnectionError, ValueError):
            return {"status": "unavailable"}
        return {"status": "ok"}

    def _with_private_state(
        self, result: dict, client, request: dict, credentials: dict
    ) -> dict:
        if result.get("status") != "challenge_required":
            return result
        return {
            **result,
            "private_state": {
                "request": request,
                "credentials": credentials,
                "cookies": client.export_cookies(),
            },
        }

    def _observe_authenticated(self, client, request: dict) -> dict:
        observed_at = self._clock()
        if request["scope"] == "assignments":
            class_id = request["class_ref"]["class_id"]
            path = "/course/{}/".format(urllib.parse.quote(class_id, safe=""))
            try:
                url, page = client.get(path)
            except (OSError, TimeoutError, ConnectionError, ValueError):
                return _failed("assignments", observed_at)
            if _is_login_url(url) or not self._page_is_authenticated(page):
                return _failed("assignments", observed_at)
            nodes = _course_assignment_nodes(
                page,
                class_id=class_id,
                connection_id=self.connection["id"],
                origin=self.connection.get("origin", "https://quera.org"),
            )
            if nodes is None:
                return _failed("assignments", observed_at)
            return _complete("assignments", observed_at, nodes)
        if request["scope"] == "assignment_detail":
            # The assignment index route is known, but the authenticated problem
            # statement and attachment markup have not been validated. Returning
            # a successful empty/partial brief could send the student down the
            # wrong work path, so keep the detail receipt explicitly incomplete.
            return _failed("assignment_detail", observed_at)
        try:
            url, page = client.get("/course/")
        except (OSError, TimeoutError, ConnectionError, ValueError):
            return _failed("classes", observed_at)
        if _is_login_url(url) or not self._page_is_authenticated(page):
            return _failed("classes", observed_at)
        links = _CourseLinks()
        links.feed(page)
        if not links.courses:
            return _failed("classes", observed_at)
        nodes = [
            {
                "kind": "class",
                "ref": {
                    "connection_id": self.connection["id"],
                    "class_id": course_id,
                },
                "title": title,
                "url": urllib.parse.urljoin(
                    self.connection.get("origin", "https://quera.org"), path
                ),
            }
            for course_id, path, title in links.courses
        ]
        return _complete("classes", observed_at, nodes)

    @staticmethod
    def _page_is_authenticated(page: str) -> bool:
        match = re.search(
            r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
            page,
            re.S | re.I,
        )
        if not match:
            return False
        try:
            current = (
                json.loads(match.group(1)).get("props", {}).get("pageProps", {})
                .get("globalServerValues", {}).get("currentUser", {})
            )
            return current.get("is_authenticated") is True
        except (TypeError, ValueError, json.JSONDecodeError):
            return False


class _CourseLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.courses: list[tuple[str, str, str]] = []
        self._href = ""
        self._text: list[str] = []
        self._ignored_text_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self._ignored_text_depth += 1
            return
        if tag == "a":
            self._href = dict(attrs).get("href", "") or ""
            self._text = []

    def handle_data(self, data):
        if self._href and not self._ignored_text_depth:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self._ignored_text_depth:
            self._ignored_text_depth -= 1
            return
        if tag != "a" or not self._href:
            return
        match = re.fullmatch(r"/course/([A-Za-z0-9_-]+)/?", self._href.split("?", 1)[0])
        title = " ".join(" ".join(self._text).split())
        if match and title and match.group(1).lower() not in {"create", "new", "search"}:
            self.courses.append((match.group(1), self._href, title))
        self._href = ""
        self._text = []


def _course_assignment_nodes(
    page: str, *, class_id: str, connection_id: str, origin: str
) -> list[dict] | None:
    match = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        page,
        re.S | re.I,
    )
    if not match:
        return None
    try:
        props = json.loads(match.group(1)).get("props", {}).get("pageProps", {})
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        return None
    course = props.get("course") if isinstance(props, dict) else None
    if not isinstance(course, dict) or str(course.get("id")) != class_id:
        return None
    assignments = course.get("assignments")
    assignment_count = course.get("assignment_count")
    if not isinstance(assignments, list):
        return None
    if assignment_count is not None and (
        type(assignment_count) is not int
        or assignment_count < 0
        or assignment_count != len(assignments)
    ):
        return None

    nodes = []
    seen = set()
    base = urllib.parse.urlsplit(origin)
    for assignment in assignments:
        if not isinstance(assignment, dict):
            return None
        raw_id = assignment.get("pk")
        if isinstance(raw_id, bool) or not isinstance(raw_id, (str, int)):
            return None
        assignment_id = str(raw_id).strip()
        title = assignment.get("name")
        finish_time = assignment.get("finish_time")
        if (
            not assignment_id
            or assignment_id in seen
            or not isinstance(title, str)
            or not title.strip()
            or (finish_time is not None and not isinstance(finish_time, str))
        ):
            return None
        seen.add(assignment_id)
        path = "/course/assignments/{}/problems".format(
            urllib.parse.quote(assignment_id, safe="")
        )
        node = {
            "kind": "assignment",
            "ref": {
                "connection_id": connection_id,
                "class_id": class_id,
                "assignment_id": assignment_id,
            },
            "title": title.strip(),
            "url": urllib.parse.urlunsplit((base.scheme, base.netloc, path, "", "")),
            "submission": {"state": "unknown", "raw": ""},
            "evaluation": {"state": "unknown", "grade": None},
            "deadlines": [],
        }
        if finish_time:
            node["deadlines"].append({
                "kind": "regular",
                "at": finish_time,
                "raw": finish_time,
            })
        nodes.append(node)
    return nodes


def _json_object(value: str) -> dict:
    try:
        result = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return result if isinstance(result, dict) else {}


def _recaptcha_challenge(response: dict) -> dict | None:
    if not isinstance(response, dict):
        return None
    site_key = response.get("recaptcha_site_key")
    domain = response.get("recaptcha_domain")
    if not site_key:
        return None
    return {
        "status": "challenge_required",
        "challenge": {
            "kind": "interactive",
            "display": {
                "url": "https://quera.org/accounts/login",
                "site_key": site_key,
                "domain": domain or "quera.org",
                "message": "کوئرا یک کپچای تعاملی Google reCAPTCHA خواسته است.",
            },
            "expires_at": _expires(datetime.now(timezone.utc).isoformat()),
        },
    }


def _complete(scope: str, observed_at: str, nodes: list[dict]) -> dict:
    return {
        "status": "ok",
        "scope": scope,
        "coverage": "complete",
        "observed_at": observed_at,
        "nodes": nodes,
    }


def _failed(scope: str, observed_at: str) -> dict:
    return {
        "status": "unavailable",
        "scope": scope,
        "coverage": "incomplete",
        "observed_at": observed_at,
        "nodes": [],
    }


def _valid_request(request: dict, connection: dict) -> bool:
    if not isinstance(request, dict):
        return False
    if request.get("scope") == "classes":
        return set(request) == {"scope"}
    if request.get("scope") == "assignments":
        class_ref = request.get("class_ref")
        return (
            set(request) == {"scope", "class_ref"}
            and isinstance(class_ref, dict)
            and class_ref.get("connection_id") == connection.get("id")
            and isinstance(class_ref.get("class_id"), str)
            and bool(class_ref["class_id"])
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
        and isinstance(request.get("assignment"), dict)
    )


def _valid_credentials(value) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("username"), str)
        and bool(value["username"])
        and isinstance(value.get("password"), str)
        and bool(value["password"])
    )


def _is_login_url(value: str) -> bool:
    return urllib.parse.urlsplit(value).path.rstrip("/") == "/accounts/login"


def _expires(now: str) -> str:
    try:
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        current = datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (current + timedelta(minutes=10)).isoformat()
