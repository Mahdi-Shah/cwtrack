"""Application boundary for the historical CW-only coursework workflows."""

from __future__ import annotations

import contextlib
import json
import os
from datetime import datetime
from pathlib import Path

from . import auth, tracker
from .brief import build_workfolder, open_items
from .classify import OPEN_BUCKETS
from .client import DEFAULT_BASE, Client, CwError
from .fetch import fetch_all
from .match import match_local
from .parse import parse_dump
from .paths import STATE_DIR, describe_paths, find_data_dir, store_is_readable
from .read_model import assignment as project_assignment
from .report import fmt_delta, report, table


def store(data: str | Path | None) -> Path:
    """Resolve the legacy store and reject missing data instead of implying zeroes."""
    path = find_data_dir(str(data) if data else "")
    if not store_is_readable(path):
        raise CwError(
            "پوشهٔ داده پیدا نشد: {}\n"
            "اگر تازه شروع کرده‌اید:  cwtrack fetch\n"
            "اگر جای دیگری است:      --data <مسیر>".format(path.resolve())
        )
    return path


def load(data: str | Path | None = None) -> tuple[Path, dict, list, dict]:
    """Load a consistent CW-only snapshot and its gap analysis."""
    data_dir = store(data)
    user, assignments = tracker.load(data_dir)
    if not assignments:
        raise CwError(
            "استور خالی است ({}). اول cwtrack fetch را اجرا کن، یا با --data "
            "مسیر یک cw-data موجود را نشان بده.".format(data_dir.resolve())
        )
    now = datetime.now()
    now_epoch = int(now.timestamp())
    gap = tracker.gaps(assignments, now_epoch)
    gap.update({"now": now, "now_epoch": now_epoch})
    return data_dir, user, assignments, gap


def paths(data: str | Path | None = None, home: str | Path | None = None) -> dict:
    data_dir = find_data_dir(str(data) if data else "")
    return describe_paths(data_dir, Path(home) if home else STATE_DIR)


def status(data: str | Path | None = None) -> dict:
    data_dir, _, _, gap = load(data)
    now_epoch = gap["now_epoch"]
    return {
        "refreshed": refreshed_at(data_dir),
        "counts": gap["counts"],
        "urgent": [project_assignment(a, now_epoch) for a in gap["urgent"]],
        "soon": [project_assignment(a, now_epoch) for a in gap["soon"]],
        "unscheduled": [project_assignment(a, now_epoch) for a in gap["unscheduled"]],
        "unknown": [project_assignment(a, now_epoch) for a in gap["unknown"]],
        "per_course": [
            {key: value for key, value in course.items() if key != "items"}
            for course in gap["per_course"]
        ],
        "paths": paths(data),
    }


def refreshed_at(data_dir: Path) -> str:
    """Return the age of the stored submission status, not the live countdown."""
    user_path = data_dir / "user.json"
    if not user_path.is_file():
        return ""
    try:
        return json.loads(user_path.read_text(encoding="utf-8-sig")).get("refreshed", "")
    except ValueError:
        return ""


def gaps_text(data: str | Path | None = None) -> str:
    _, _, _, gap = load(data)
    counts = gap["counts"]
    lines = [
        "کل {} · ارسال‌نشده {} · گذشته از مهلت {} · انجام‌شده {}".format(
            counts["total"], counts["open"], counts["urgent"], counts["done"]
        ),
        "",
    ]
    lines += ["  [گذشته]  {} — {}".format(a.course, a.name) for a in gap["urgent"]]
    lines += [
        "  [نزدیک]  {} — {}  ({})".format(
            a.course, a.name, fmt_delta(a.due, gap["now_epoch"])
        )
        for a in gap["soon"]
    ]
    lines.append("")
    for course in gap["per_course"]:
        mark = "!!" if course["overdue"] else (" *" if course["open"] else "  ")
        lines.append(
            " {} {:<46} {}/{}".format(
                mark, course["course"][:46], course["done"], course["total"]
            )
        )
    if not (gap["urgent"] or gap["soon"]):
        lines.append("  (مورد بازی ثبت نشده است)")
    return "\n".join(lines)


def open_text(
    data: str | Path | None = None,
    days: int | None = None,
    local: str | Path | None = None,
) -> str:
    _, _, assignments, gap = load(data)
    picked = [assignment for assignment in assignments if assignment.bucket in OPEN_BUCKETS]
    if days:
        picked = [
            assignment for assignment in picked
            if assignment.due is not None
            and 0 < assignment.due - gap["now_epoch"] <= days * 86400
        ]
    rows = [assignment.__dict__ for assignment in picked]
    found = match_local(rows, Path(local)) if local else {}
    return table(rows, gap["now_epoch"], found) + "\n\n{} مورد باز".format(len(picked))


def report_text(
    data: str | Path | None = None,
    local: str | Path | None = None,
) -> str:
    data_dir, _, assignments, gap = load(data)
    rows = [assignment.__dict__ for assignment in assignments]
    found = match_local(rows, Path(local)) if local else {}
    return report(rows, found, gap["now"])


def materials_text(
    data: str | Path | None = None,
    course: str | int | None = None,
) -> dict:
    if course is None:
        raise CwError("course id لازم است")
    data_dir = store(data)
    course_id = int(course)
    folder = tracker.course_dir(data_dir, course_id) / "materials"
    folder.mkdir(parents=True, exist_ok=True)
    materials = tracker.scan_materials(folder)
    return {
        "course_id": course_id,
        "folder": str(folder.resolve()),
        "count": len(materials),
        "materials": [
            {"name": item.name, "bytes": item.bytes, "kind": item.kind,
             "modified": item.modified}
            for item in materials
        ],
    }


def outstanding(
    data: str | Path | None = None,
    course: str | int | None = None,
    days: int | None = None,
) -> list[dict]:
    _, _, assignments, gap = load(data)
    picked = open_items(assignments, gap["now_epoch"], str(course or ""))
    if days:
        picked = [
            assignment for assignment in picked
            if assignment.due is not None
            and 0 < assignment.due - gap["now_epoch"] <= days * 86400
        ]
    return [project_assignment(item, gap["now_epoch"]) for item in picked]


def make_brief(
    cmid: str | int | None = None,
    course: str | int | None = None,
    data: str | Path | None = None,
    work: str | Path | None = None,
    force: bool = False,
) -> dict:
    data_dir, _, assignments, gap = load(data)
    work_root = Path(work) if work else data_dir.parent / "work"
    candidates = open_items(assignments, gap["now_epoch"], str(course or ""))
    if cmid is not None:
        chosen = [item for item in assignments if str(item.cmid) == str(cmid)]
        if not chosen:
            raise CwError("no assignment with cmid={} in the store".format(cmid))
    elif len(candidates) == 1:
        chosen = candidates
    elif not candidates:
        return {"status": "nothing_outstanding", "candidates": []}
    else:
        return {
            "status": "needs_choice",
            "candidates": [project_assignment(a, gap["now_epoch"]) for a in candidates],
        }

    results = []
    for assignment in chosen:
        meta = {"title": assignment.course, "term": assignment.term}
        folder, written = build_workfolder(
            assignment.__dict__, meta, data_dir, work_root, gap["now_epoch"],
            overwrite=force,
        )
        results.append({
            "cmid": assignment.cmid,
            "name": assignment.name,
            "course": assignment.course,
            "folder": str(folder.resolve()),
            "written": [path.name for path in written],
            "existed": not written,
            "source": str((data_dir / "courses" / str(assignment.course_id) / "materials").resolve()),
        })
    return {"status": "ok", "briefs": results}


def ingest(
    dump: str | Path | None = None,
    data: str | Path | None = None,
) -> dict:
    """Reparse saved CW pages without contacting the network."""
    dump_dir = Path(dump) if dump else STATE_DIR / "dump"
    if not dump_dir.is_dir():
        raise CwError("هیچ صفحه‌ای ذخیره نشده. اول fetch را اجرا کن.")
    data_dir = find_data_dir(str(data) if data else "")
    rows = parse_dump(dump_dir, datetime.now())
    if not rows:
        raise CwError("از صفحه‌های ذخیره‌شده هیچ تکلیفی درنیامد.")
    info = {"fullname": "", "username": "", "userid": ""}
    previous = data_dir / "user.json"
    if previous.is_file():
        with contextlib.suppress(ValueError):
            info = json.loads(previous.read_text(encoding="utf-8-sig"))
    summary = tracker.store(data_dir, info, rows)
    summary["store"] = str(data_dir.resolve())
    return summary


def _attempt_captcha(client, user: str, password: str, base_dir: Path, given: str | None) -> dict:
    return auth._attempt_captcha(client, user, password, base_dir, given)


def refresh(
    captcha: str | None = None,
    home: str | Path | None = None,
    data: str | Path | None = None,
    user: str | None = None,
    password: str | None = None,
    base: str | None = None,
    client_factory=Client,
) -> dict:
    """Run the legacy CW-only login, fetch, and ingest flow."""
    base_dir = Path(home) if home else STATE_DIR
    data_dir = find_data_dir(str(data) if data else "")
    name = user or os.environ.get("CW_USER")
    secret = password or os.environ.get("CW_PASS")
    if not name or not secret:
        return {
            "status": "needs_credentials",
            "message": "CW_USER و CW_PASS را در متغیر محیطی بگذار، یا user/password بده.",
        }
    client = client_factory(base or DEFAULT_BASE)
    if not client.logged_in():
        state = _attempt_captcha(client, name, secret, base_dir, captcha)
        if state["status"] != auth.OK:
            return state
    count = fetch_all(client, base_dir)
    summary = ingest(base_dir / "dump", data_dir)
    summary.update({
        "status": "ok",
        "pages": count,
        "refreshed": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    return summary
