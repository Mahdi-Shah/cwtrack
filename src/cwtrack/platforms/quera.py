"""First-party Quera authentication and conservative coursework observations.

Quera's current login page is a multi-step client flow. Its route map is not a
public API contract, so this adapter treats unrecognized responses and pages as
incomplete instead of replacing a prior complete observation with an empty list.
"""

from __future__ import annotations

import hashlib
import http.cookiejar
import json
import re
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

from ..diagnostics import is_failure_kind


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

    def download(self, url: str, folder: str | Path) -> str:
        """Download a Quera or Arvan asset with an origin and size check."""
        parsed = urllib.parse.urlsplit(url)
        base = urllib.parse.urlsplit(self.base)
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or not _allowed_asset_host(parsed.hostname, base.hostname)
        ):
            raise ValueError("asset host is not allowed")
        request = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140.0 Safari/537.36",
        })
        response = self.opener.open(request, timeout=self.timeout)
        final = urllib.parse.urlsplit(response.geturl())
        if (
            final.scheme != "https"
            or final.username is not None
            or final.password is not None
            or final.port not in (None, 443)
            or not _allowed_asset_host(final.hostname, base.hostname)
        ):
            raise ValueError("asset redirect left the allowed hosts")
        content = response.read(20 * 1024 * 1024 + 1)
        if not content or len(content) > 20 * 1024 * 1024:
            raise ValueError("asset is empty or exceeds the 20 MB limit")
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        source_name = Path(urllib.parse.unquote(final.path)).name
        if source_name in {"", ".", ".."}:
            source_name = "assignment.pdf" if "get_pdf_file" in final.path else "asset"
        source_name = re.sub(r"[^A-Za-z0-9._-]+", "_", source_name).strip("._") or "asset"
        if "get_pdf_file" in final.path and not Path(source_name).suffix:
            source_name += ".pdf"
        stem, suffix = Path(source_name).stem, Path(source_name).suffix[:12]
        filename = "{}-{}{}".format(stem[:90], digest[:10], suffix)
        target_dir = Path(folder)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / filename
        target.write_bytes(content)
        return str(target)

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
                 clock: Callable[[], str], download_root: str | Path | None = None):
        self.connection = connection
        self._client_factory = client_factory
        self._clock = clock
        self._download_root = Path(download_root) if download_root else (
            Path(tempfile.gettempdir()) / "cwtrack-attachments" /
            str(connection.get("id", "quera"))
        )

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
        result = {
            "status": "ok" if observation.get("status") == "ok" else "unavailable",
            "observation": observation,
            "private_state": {"cookies": client.export_cookies()},
        }
        if is_failure_kind(observation.get("failure_kind")):
            result["failure_kind"] = observation["failure_kind"]
        return result

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
            return {"status": "challenge_unavailable"}
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
        if request["scope"] == "course_materials":
            class_id = request["class_ref"]["class_id"]
            materials, coverage, issues = self._course_materials(
                client, {"class_id": class_id}, self._download_root
            )
            return {
                "status": "ok",
                "scope": "course_materials",
                "coverage": coverage,
                "observed_at": observed_at,
                "course_materials": materials,
                "course_materials_issues": issues,
            }
        if request["scope"] == "assignments":
            class_id = request["class_ref"]["class_id"]
            # Quera's canonical course page has no trailing slash. The slash
            # variant currently responds with a redirect that urllib surfaces
            # as HTTP 308 instead of following, which made every assignment
            # observation look like a transport failure.
            path = "/course/{}".format(urllib.parse.quote(class_id, safe=""))
            try:
                url, page = client.get(path)
            except (OSError, TimeoutError, ConnectionError, ValueError):
                return _failed("assignments", observed_at, "transport_error")
            if _is_login_url(url):
                return _failed("assignments", observed_at, "authentication_required")
            nodes = _course_assignment_nodes(
                page,
                class_id=class_id,
                connection_id=self.connection["id"],
                origin=self.connection.get("origin", "https://quera.org"),
            )
            if nodes is None:
                return _failed("assignments", observed_at, "unexpected_response")
            return _complete("assignments", observed_at, nodes)
        if request["scope"] == "assignment_detail":
            task_ref = request["task_ref"]
            assignment_id = urllib.parse.quote(task_ref["assignment_id"], safe="")
            path = "/course/assignments/{}/problems".format(assignment_id)
            try:
                url, page = client.get(path)
            except (OSError, TimeoutError, ConnectionError, ValueError):
                return _failed("assignment_detail", observed_at)
            if _is_login_url(url):
                return _failed("assignment_detail", observed_at)
            prompt = _problem_prompt(page)
            if not prompt:
                return _failed("assignment_detail", observed_at)
            assignment = request["assignment"]
            attachments, attachment_issues = _problem_attachments(
                client, prompt, url, self._download_root / assignment_id
            )
            class_materials, materials_coverage, materials_issues = self._course_materials(
                client, task_ref, self._download_root
            )
            return {
                "status": "ok",
                "scope": "assignment_detail",
                "coverage": "complete",
                "observed_at": observed_at,
                "input": {
                    "source": "quera",
                    "assignment_ref": task_ref,
                    "course": assignment.get("course", ""),
                    "term": assignment.get("term", ""),
                    "title": assignment.get("title", ""),
                    "due": assignment.get("due"),
                    "url": assignment.get("url", url),
                    "prompt": prompt,
                    "attachments": attachments,
                    "course_materials": class_materials,
                    "course_materials_coverage": materials_coverage,
                    "course_materials_issues": materials_issues,
                    "attachment_issues": attachment_issues,
                },
            }
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

    def _course_materials(self, client, task_ref: dict, root: Path):
        path = "/course/{}".format(urllib.parse.quote(task_ref["class_id"], safe=""))
        try:
            url, page = client.get(path)
        except (OSError, TimeoutError, ConnectionError, ValueError):
            return [], "incomplete", [{"kind": "course_page_unavailable"}]
        if _is_login_url(url):
            return [], "incomplete", [{"kind": "course_page_requires_login"}]
        links = _material_links(page, url)
        lectures = _course_lectures(page, task_ref["class_id"])
        materials = []
        issues = []
        for title, asset_url in links:
            try:
                local_path = client.download(asset_url, root / task_ref["class_id"])
            except (OSError, TimeoutError, ConnectionError, ValueError) as exc:
                issues.append({"url": asset_url, "reason": str(exc)})
                continue
            materials.append({
                "title": title or Path(urllib.parse.urlsplit(asset_url).path).name,
                "url": asset_url,
                "path": local_path,
                "role": "material",
            })
        coverage = "complete" if lectures == [] and not issues else "page_links"
        return materials, coverage, issues

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


class _ProblemPrompt(HTMLParser):
    """Read Quera's server-rendered Markdown source for one problem."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if self._depth:
            self._depth += 1
        elif attributes.get("id", "").startswith("description_md-"):
            self._depth = 1

    def handle_endtag(self, tag):
        if self._depth:
            self._depth -= 1

    def handle_data(self, data):
        if self._depth:
            self.parts.append(data)


def _problem_prompt(page: str) -> str:
    parser = _ProblemPrompt()
    parser.feed(page)
    return "".join(parser.parts).strip()


_MARKDOWN_LINK = re.compile(r"!?\[([^\]]*)\]\(([^)]+)\)")
_MATERIAL_SUFFIXES = {
    ".pdf", ".ppt", ".pptx", ".doc", ".docx", ".odt", ".rtf", ".txt",
    ".md", ".zip", ".rar", ".7z", ".png", ".jpg", ".jpeg", ".gif",
}


def _problem_attachments(client, prompt: str, page_url: str, root: Path):
    attachments = []
    issues = []
    seen = set()
    for match in _MARKDOWN_LINK.finditer(prompt):
        label, raw_url = match.groups()
        asset_url = urllib.parse.urljoin(page_url, raw_url.strip())
        path = urllib.parse.urlsplit(asset_url).path.lower()
        is_image = match.group(0).startswith("!")
        suffix = Path(path).suffix
        is_file = suffix in _MATERIAL_SUFFIXES or "get_pdf_file" in path
        is_pdf = suffix == ".pdf" or "get_pdf_file" in path
        if not (is_image or is_file) or asset_url in seen:
            continue
        seen.add(asset_url)
        try:
            local_path = client.download(asset_url, root)
        except (OSError, TimeoutError, ConnectionError, ValueError) as exc:
            issues.append({"url": asset_url, "reason": str(exc)})
            continue
        # Quera's PDF endpoint omits its suffix; preserve a useful local filename.
        local = Path(local_path)
        if is_pdf and not local.suffix:
            renamed = local.with_suffix(".pdf")
            local.replace(renamed)
            local_path = str(renamed)
        attachments.append({
            "path": local_path,
            "role": "material" if is_image else "prompt",
            "title": label.strip(),
            "url": asset_url,
        })
    return attachments, issues


class _MaterialLinks(HTMLParser):
    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.links: list[tuple[str, str]] = []
        self.href = ""
        self.text: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignored += 1
        elif tag == "a":
            self.href = dict(attrs).get("href", "") or ""
            self.text = []

    def handle_data(self, data):
        if self.href and not self.ignored:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.ignored:
            self.ignored -= 1
        elif tag == "a" and self.href:
            url = urllib.parse.urljoin(self.page_url, self.href)
            suffix = Path(urllib.parse.urlsplit(url).path).suffix.lower()
            if suffix in _MATERIAL_SUFFIXES:
                self.links.append((" ".join(" ".join(self.text).split()), url))
            self.href = ""
            self.text = []


def _material_links(page: str, page_url: str) -> list[tuple[str, str]]:
    parser = _MaterialLinks(page_url)
    parser.feed(page)
    unique = {}
    for title, url in parser.links:
        unique.setdefault(url, title)
    return [(title, url) for url, title in unique.items()]


def _course_lectures(page: str, class_id: str) -> list | None:
    """Return the server-provided lecture list only for the requested class."""
    match = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        page,
        re.S | re.I,
    )
    if not match:
        return None
    try:
        course = json.loads(match.group(1)).get("props", {}).get("pageProps", {}).get("course")
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(course, dict) or str(course.get("id")) != class_id:
        return None
    lectures = course.get("lectures")
    return lectures if isinstance(lectures, list) else None


def _allowed_asset_host(host: str | None, quera_host: str | None) -> bool:
    if not host:
        return False
    normalized = host.lower().rstrip(".")
    return normalized == (quera_host or "").lower().rstrip(".") or (
        normalized == "dns-sut.s3.ir-central1.arvanstorage.ir"
    )


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
    if request.get("scope") == "course_materials":
        class_ref = request.get("class_ref")
        return (
            set(request) == {"scope", "class_ref"}
            and isinstance(class_ref, dict)
            and set(class_ref) == {"connection_id", "class_id"}
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
