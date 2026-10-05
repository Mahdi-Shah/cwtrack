"""Downloading the pages the parser needs."""

from __future__ import annotations

import html
import re
import sys
import time
from pathlib import Path

from .client import Client, CwError

COURSE_RE = re.compile(r"course/view\.php\?id=(\d+)")
ASSIGN_RE = re.compile(r"mod/assign/view\.php\?id=(\d+)")

def course_ids(client: Client) -> list[int]:
    """Course ids for the logged-in student, from the My courses page."""
    page = client.get("/my/courses.php")
    ids: list[int] = []
    for raw in COURSE_RE.findall(page):
        cid = int(raw)
        if cid > 1 and cid not in ids:  # id 1 is the site home pseudo-course
            ids.append(cid)
    if not ids:
        raise CwError(
            "no courses found in /my/courses.php - the page layout must have changed. "
            "The raw page was not saved, so re-run and check the URL."
        )
    return ids


def course_title(page: str) -> str:
    m = re.search(r'<h1[^>]*>(.*?)</h1>', page, re.S)
    if not m:
        return ""
    text = re.sub(r"<[^>]+>", " ", m.group(1))
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def fetch_all(client: Client, base_dir: Path) -> int:
    dump = base_dir / "dump"
    dump.mkdir(parents=True, exist_ok=True)

    (dump / "_my_courses.html").write_text(client.get("/my/courses.php"), encoding="utf-8")
    (dump / "_dashboard.html").write_text(client.get("/my/"), encoding="utf-8")

    ids = course_ids(client)
    print("{} درس پیدا شد.".format(len(ids)))

    ok = 0
    for cid in ids:
        try:
            page = client.get("/mod/assign/index.php", {"id": cid})
        except CwError as exc:
            print("  ! درس {} نخوانده شد: {}".format(cid, exc))
            continue
        (dump / "course_{}.html".format(cid)).write_text(page, encoding="utf-8")
        ok += 1
        sys.stdout.write("\r  خوانده شد: {}/{}".format(ok, len(ids)))
        sys.stdout.flush()
        time.sleep(0.3)  # be polite; the site sits behind a WAF
    print()
    print("صفحه‌ها در {} ذخیره شدند.".format(dump.resolve()))
    return ok
