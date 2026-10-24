"""Reading assignments out of Moodle's HTML."""

from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path

from .classify import _grade_score, _status_score, classify
from .client import DEFAULT_BASE, CwError
from .dates import parse_due
from .fetch import course_title

HEADER_MAP = (
    # "name" was missing from the English needles, so an English UI mapped the
    # due date onto the title column and every row came out nameless.
    ("name", ("نام", "title", "name", "activity")),
    ("due", ("مهلت", "موعد", "due", "deadline")),
    ("status", ("وضعیت", "status", "تحویل")),
    ("grade", ("نمره", "grade", "mark")),
)
ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S | re.I)
CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
ASSIGN_ACTIVITY_RE = re.compile(
    r"<li\b(?=[^>]*\bmodtype_assign\b)[^>]*>(.*?)</li\s*>", re.S | re.I
)
ASSIGN_LINK_RE = re.compile(
    r"<a\b[^>]*href=[\"'][^\"']*mod/assign/view\.php\?id=(\d+)[^\"']*[\"'][^>]*>(.*?)</a>",
    re.S | re.I,
)

def cell_text(fragment: str) -> str:
    text = TAG_RE.sub(" ", fragment)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def map_header(header_cells: list[str]) -> dict[str, int]:
    """Column indices from the table's own header row.

    Reading the header beats assuming a fixed order: this theme emits
    نام | مهلت تحویل | وضعیت تحویل | نمره, and an English UI emits its own
    labels. Anything unmatched is simply absent, and the caller falls back to
    scoring cells by content.
    """
    out: dict[str, int] = {}
    for i, cell in enumerate(header_cells):
        low = cell.lower()
        for key, needles in HEADER_MAP:
            if key in out:
                continue
            if any(n in low for n in needles):
                out[key] = i
                break
    return out


def cell_at(header_idx: dict, cells: list, key: str) -> str:
    """Read one cell by its column name, or '' when the header lacks it.

    A module-level function rather than a closure over the loop variables: a
    closure here happens to work because it is called in the same iteration, but
    deferring that call by one row would silently read the previous row's cells.
    """
    i = header_idx.get(key)
    return cells[i] if i is not None and 0 <= i < len(cells) else ""


def parse_dump(dump: Path, now: datetime) -> list[dict]:
    now_epoch = int(now.timestamp())
    rows: list[dict] = []
    # One set for the whole dump, not per page: the overview page and the assign
    # page for the same course both list the same cmids, and a per-page set
    # happily returned every assignment twice.
    seen_cmid: set[int] = set()
    pages = sorted(dump.glob("*.html"))
    if not pages:
        raise CwError(
            "no saved pages in {}. Run `cwtrack fetch` first.".format(dump.resolve())
        )

    for page_path in pages:
        detail_match = re.match(r"assignment_(\d+)_(\d+)$", page_path.stem)
        if detail_match:
            continue
        # Two naming conventions exist: fetch_all writes course_<id>.html, and the
        # broader probe writes c<id>_<label>.html. Both must resolve to the id,
        # or every course collapses into a single None bucket.
        cid = None
        m = re.search(r"(?:^c|course_)(\d+)", page_path.stem)
        if m:
            cid = int(m.group(1))
        page = page_path.read_text(encoding="utf-8", errors="replace")
        title = course_title(page)

        # Locate the assignment table and learn its column order from the header.
        header_idx: dict[str, int] = {}
        for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", page, re.S | re.I):
            cells = [cell_text(c) for c in CELL_RE.findall(tr)]
            if len(cells) < 3:
                continue
            if not any("mod/assign/view.php" in c for c in cells):
                pass
            candidate = map_header(cells)
            if "name" in candidate and ("due" in candidate or "status" in candidate):
                header_idx = candidate
                break

        for row_html in ROW_RE.findall(page):
            cmid = re.search(r"mod/assign/view\.php\?id=(\d+)", row_html)
            if not cmid:
                continue
            cm = int(cmid.group(1))
            if cm in seen_cmid:
                continue  # the overview page and the assign page can both be dumped
            seen_cmid.add(cm)

            cells = [cell_text(c) for c in CELL_RE.findall(row_html)]
            if len(cells) < 2:
                continue

            link = re.search(r"<a\b[^>]*>(.*?)</a>", row_html, re.S)
            name = cell_text(link.group(1)) if link else cells[0]
            if not name:
                name = cells[0]

            due_text, due_epoch = parse_due(cell_at(header_idx, cells, "due"), now)

            rest = [c for c in cells if c not in (name, due_text)]
            status = cell_at(header_idx, cells, "status") or (
                max(rest, key=_status_score) if rest else ""
            )
            grade = cell_at(header_idx, cells, "grade") or next(
                (c for c in rest if c != status and _grade_score(c) is not None), ""
            )

            bucket = classify(status, grade, due_epoch, now_epoch)
            rows.append(
                {
                    "course_id": cid,
                    "course": title or (str(cid) if cid else "?"),
                    "name": name,
                    "cmid": cm,
                    "due_text": due_text,
                    "due": due_epoch,
                    "status_text": status,
                    "grade": grade,
                    "bucket": bucket,
                    "url": "{}/mod/assign/view.php?id={}".format(DEFAULT_BASE, cm),
                }
            )

        # Current CW course pages expose assignments as Moodle activity list
        # items rather than the legacy assignment-index table.
        for activity_html in ASSIGN_ACTIVITY_RE.findall(page):
            link = ASSIGN_LINK_RE.search(activity_html)
            if not link:
                continue
            cm = int(link.group(1))
            if cm in seen_cmid:
                continue
            seen_cmid.add(cm)

            name = cell_text(link.group(2)) or "تکلیف بدون عنوان"
            activity_text = cell_text(activity_html)
            deadline = re.search(
                r"(?:مهلت(?:\s+تحویل)?|due(?:\s+date)?|deadline)\s*[:：]\s*(.+)$",
                activity_text,
                re.I,
            )
            due_text, due_epoch = parse_due(
                deadline.group(1).strip() if deadline else "", now
            )
            rows.append({
                "course_id": cid,
                "course": title or (str(cid) if cid else "?"),
                "name": name,
                "cmid": cm,
                "due_text": due_text,
                "due": due_epoch,
                # The activity list shows open/deadline metadata, not a
                # student's submission or grade. Those stay explicitly unknown.
                "status_text": "unknown",
                "grade": "",
                "bucket": classify("unknown", "", due_epoch, now_epoch),
                "url": "{}/mod/assign/view.php?id={}".format(DEFAULT_BASE, cm),
            })

    # Legacy fetch stores an additional detail page for each assignment so its
    # report can retain submission and grading data from CW's activity view.
    for page_path in pages:
        detail_match = re.match(r"assignment_(\d+)_(\d+)$", page_path.stem)
        if not detail_match:
            continue
        course_id, assignment_id = map(int, detail_match.groups())
        detail = parse_assignment_detail(
            page_path.read_text(encoding="utf-8", errors="replace"), now
        )
        for row in rows:
            if row["course_id"] == course_id and row["cmid"] == assignment_id:
                row.update(detail)
    return rows


def parse_assignment_detail(page: str, now: datetime) -> dict:
    """Read only status, grade and deadline fields from an assignment detail page."""
    result: dict[str, str | int | None] = {}
    for row_html in ROW_RE.findall(page):
        cells = [cell_text(cell) for cell in CELL_RE.findall(row_html)]
        if len(cells) < 2:
            continue
        label = cells[0].casefold()
        value = cells[1]
        if any(term in label for term in ("grading status", "ارزیابی", "وضعیت نمره")):
            continue
        if any(term in label for term in ("submission status", "وضعیت تحویل", "وضعیت ارسال")):
            result["status_text"] = value
        elif any(term in label for term in ("grade", "نمره")):
            result["grade"] = value
        elif any(term in label for term in ("due date", "deadline", "مهلت")):
            due_text, due_epoch = parse_due(value, now)
            if due_text:
                result["due_text"] = due_text
                result["due"] = due_epoch
    return result
