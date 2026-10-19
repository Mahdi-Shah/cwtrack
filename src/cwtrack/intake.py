"""Normalize assignment text and local attachment references for a work item."""

from __future__ import annotations

import hashlib
import os
import re
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

from .client import CwError

_TEXT_SUFFIXES = {".txt", ".md", ".csv"}


class _AssignmentPage(HTMLParser):
    """Extract readable page text and links from one assignment detail page."""

    _BLOCKS = {"br", "div", "h1", "h2", "h3", "li", "p", "section", "tr"}
    _SKIP = {"script", "style", "nav", "header", "footer"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.links: list[str] = []
        self._skip_depth = 0
        self._link_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag in self._SKIP:
            self._skip_depth += 1
        if self._skip_depth:
            return
        if tag in self._BLOCKS:
            self.text.append("\n")
        if tag == "a":
            self._link_depth += 1
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag: str):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        if self._skip_depth:
            return
        if tag == "a" and self._link_depth:
            self._link_depth -= 1
        if tag in self._BLOCKS:
            self.text.append("\n")

    def handle_data(self, data: str):
        if not self._skip_depth:
            self.text.append(data)


class _CourseResourcePage(HTMLParser):
    """Extract labelled links from a Moodle course or resources page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._label: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._label = []

    def handle_data(self, data):
        if self._href is not None:
            self._label.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._label).split())))
            self._href = None
            self._label = []


def collect_site(cmid: int, assignment: dict, client, home: Path) -> dict:
    """Fetch and normalize the selected assignment, plus its prompt attachments."""
    page = client.get("/mod/assign/view.php", {"id": cmid})
    lowered = page.lower()
    if "login-form" in lowered or re.search(r'name=["\']password["\']', lowered):
        return {
            "status": "authentication_required",
            "message": "نشست سامانه منقضی شده است؛ دوباره وارد شو.",
        }
    parsed = _AssignmentPage()
    parsed.feed(page)
    prompt = re.sub(r"[ \t\r\f\v]+", " ", "".join(parsed.text))
    prompt = "\n".join(line.strip() for line in prompt.splitlines() if line.strip())

    base = urllib.parse.urlsplit(getattr(client, "base", "https://cw.sharif.ir"))
    folder = home / "assignment-files" / str(assignment["course_id"]) / str(cmid)
    attachments = []
    for href in parsed.links:
        url = urllib.parse.urlsplit(urllib.parse.urljoin(base.geturl(), href))
        if url.scheme != base.scheme or url.hostname != base.hostname:
            continue
        if not url.path.startswith("/pluginfile.php/") or "/mod_assign/introattachment/" not in url.path:
            continue
        filename = Path(urllib.parse.unquote(url.path)).name
        if not filename or filename in {".", ".."}:
            continue
        params = urllib.parse.parse_qs(url.query, keep_blank_values=True)
        content = client.get_bytes(url.path, params or None)
        prefix = content[:4096].lower()
        if b"login-form" in prefix or re.search(rb'name=["\']password["\']', prefix):
            return {
                "status": "authentication_required",
                "message": "نشست سامانه هنگام دریافت پیوست منقضی شده است؛ دوباره وارد شو.",
            }
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / filename
        temp = target.with_name(target.name + ".tmp")
        temp.write_bytes(content)
        os.replace(temp, target)
        attachments.append({"name": filename, "role": "prompt", "path": str(target.resolve())})

    received = {
        "source": "site",
        "course_id": assignment["course_id"],
        "course": assignment["course"],
        "term": assignment["term"],
        "cmid": cmid,
        "title": assignment["name"],
        "prompt": prompt,
        "due": assignment.get("due"),
        "due_text": assignment.get("due_text", ""),
        "url": assignment.get("url", ""),
        "attachments": attachments,
    }
    missing = []
    if not prompt:
        missing.append("متن صورت تکلیف در صفحه پیدا نشد؛ پیوست‌ها را بررسی کن.")
    if not attachments and not prompt:
        missing.append("هیچ متن یا پیوستی برای تکلیف دریافت نشد.")
    return {
        "status": "needs_input" if missing else "ok",
        "input": received,
        "open_questions": missing,
    }


def collect_course_materials(course_id: int, client, home: Path) -> dict:
    """Download visible course files from the Moodle class and resources pages."""
    base = urllib.parse.urlsplit(getattr(client, "base", "https://cw.sharif.ir"))
    root = home / "course-materials" / str(course_id)
    pages = [
        ("/course/view.php", {"id": course_id}),
        ("/course/resources.php", {"id": course_id}),
    ]
    links: dict[str, str] = {}
    issues = []

    def looks_like_login(page: str) -> bool:
        lowered = page.lower()
        return "login-form" in lowered or bool(
            re.search(r'name=["\']password["\']', lowered)
        )

    def read_page(path: str, params: dict | None = None) -> str | None:
        try:
            page = client.get(path, params)
        except (ConnectionError, TimeoutError, OSError, ValueError, CwError):
            issues.append({"url": path, "status": "unavailable"})
            return None
        if looks_like_login(page):
            issues.append({"url": path, "status": "authentication_required"})
            return None
        return page

    for path, params in pages:
        page = read_page(path, params)
        if page is None:
            continue
        parsed = _CourseResourcePage()
        parsed.feed(page)
        for href, label in parsed.links:
            url = urllib.parse.urlsplit(urllib.parse.urljoin(base.geturl(), href))
            if url.scheme != base.scheme or url.hostname != base.hostname:
                continue
            if url.path.startswith("/pluginfile.php/"):
                links.setdefault(url.geturl(), label)
            elif url.path.startswith(("/mod/resource/view.php", "/mod/folder/view.php")):
                detail = read_page(url.path, urllib.parse.parse_qs(url.query))
                if detail is None:
                    continue
                detail_links = _CourseResourcePage()
                detail_links.feed(detail)
                for detail_href, detail_label in detail_links.links:
                    target = urllib.parse.urlsplit(
                        urllib.parse.urljoin(base.geturl(), detail_href)
                    )
                    if (
                        target.scheme == base.scheme
                        and target.hostname == base.hostname
                        and target.path.startswith("/pluginfile.php/")
                    ):
                        links.setdefault(
                            target.geturl(), detail_label or label
                        )

    materials = []
    for address, label in links.items():
        url = urllib.parse.urlsplit(address)
        filename = Path(urllib.parse.unquote(url.path)).name
        if not filename or filename in {".", ".."}:
            issues.append({"url": address, "status": "invalid_filename"})
            continue
        try:
            content = client.get_bytes(url.path, urllib.parse.parse_qs(url.query) or None)
        except (ConnectionError, TimeoutError, OSError, ValueError, CwError):
            issues.append({"url": address, "status": "download_failed"})
            continue
        if looks_like_login(content[:4096].decode("utf-8", "replace")):
            issues.append({"url": address, "status": "authentication_required"})
            continue
        root.mkdir(parents=True, exist_ok=True)
        target = root / filename
        if target.exists() and target.read_bytes() != content:
            digest = hashlib.sha256(address.encode("utf-8")).hexdigest()[:10]
            target = root / (target.stem + "-" + digest + target.suffix)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_bytes(content)
        os.replace(temporary, target)
        materials.append({
            "title": label or filename,
            "url": address,
            "path": str(target.resolve()),
            "role": "material",
        })

    return {
        "status": "ok" if not issues else "partial",
        "course_materials": materials,
        "coverage": "complete" if not issues else "incomplete",
        "issues": issues,
    }


def collect(source: dict) -> dict:
    """Collect student-provided text without prompting, printing, or writing files."""
    if not isinstance(source, dict) or set(source) != {"manual"}:
        return {"status": "invalid_input", "message": "یک ورودی دستی لازم است"}
    manual = source["manual"]
    if not isinstance(manual, dict):
        return {"status": "invalid_input", "message": "ساختار ورودی دستی نامعتبر است"}

    title = manual.get("title", "")
    course = manual.get("course", "")
    prompt = manual.get("prompt", "")
    attachments = manual.get("attachments", [])
    if not all(isinstance(value, str) for value in (title, course, prompt)):
        return {"status": "invalid_input", "message": "مشخصات تکلیف باید متن باشند"}
    if not isinstance(attachments, list):
        return {"status": "invalid_input", "message": "پیوست‌ها باید فهرست باشند"}

    records = []
    prompt_parts = [prompt.strip()] if prompt.strip() else []
    missing = []
    for attachment in attachments:
        if not isinstance(attachment, dict) or not isinstance(attachment.get("path"), str):
            return {"status": "invalid_input", "message": "مسیر هر پیوست لازم است"}
        role = attachment.get("role", "material")
        if role not in {"prompt", "material"}:
            return {"status": "invalid_input", "message": "نقش پیوست باید prompt یا material باشد"}
        path = Path(attachment["path"]).expanduser()
        record = {"name": path.name, "role": role, "path": str(path.resolve())}
        records.append(record)
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            if role == "prompt" and not prompt_parts:
                missing.append("متن پیوست متنی نیست و باید خوانده شود: {}".format(path.name))
            continue
        try:
            text = path.read_text(encoding="utf-8-sig").strip()
        except (OSError, UnicodeError):
            missing.append("خواندن پیوست ممکن نشد: {}".format(path.name))
            continue
        if role == "prompt" and text:
            prompt_parts.append(text)

    received = {
        "source": "manual",
        "course": course.strip(),
        "title": title.strip(),
        "prompt": "\n\n".join(prompt_parts),
        "attachments": records,
    }
    if not title.strip():
        missing.append("عنوان تکلیف لازم است.")
    if not received["prompt"]:
        missing.append("متن کامل تکلیف لازم است.")
    return {
        "status": "needs_input" if missing else "ok",
        "input": received,
        "open_questions": missing,
    }
