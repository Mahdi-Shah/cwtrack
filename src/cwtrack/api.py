"""The surface a skill drives. No terminal, no stdout, no prompts.

Everything here returns Python values. Nothing prints, nothing reads stdin, nothing
opens a browser. That is the whole point of the module, and each of those three
omissions was a real blocker rather than a style preference:

- **No printing.** Persian output on a stock Windows console is cp1252, so a skill
  that ran the CLI and read its stdout either got mojibake or wrote a temp file and
  read it back. Returning `str` skips the round trip.
- **No prompts.** `auth.submit()` used to call `input()`, which from a shell with no
  terminal behind it raises EOFError and tells the user to set an environment
  variable. The login is now a two-phase call - ask for the image, hand back the
  answer - so a non-interactive caller is the normal case rather than an error path.
- **No browser.** `ui` opened the page. A caller that wants to show it to the user
  asks for the path and decides; opening a window is the caller's privilege, not
  this module's.

Expected conditions are returned as states, not raised. A missing store, a captcha
needing an answer, and "pick one of these" are all things a caller must handle, and a
caller cannot handle an exception it was never told the shape of.
"""

from __future__ import annotations

import contextlib
import json
import os
from datetime import datetime
from pathlib import Path

from . import auth, tracker
from . import captcha as captcha_ocr
from .brief import build_workfolder, open_items, remaining_text
from .classify import OPEN_BUCKETS
from .client import DEFAULT_BASE, Client, CwError
from .dashboard import build as _build_page
from .fetch import fetch_all
from .match import match_local
from .parse import parse_dump
from .paths import STATE_DIR, describe_paths, find_data_dir, store_is_readable
from .report import BUCKET_FA, fmt_delta, report, table

__all__ = [
    "status", "gaps_text", "open_text", "report_text", "build_dashboard",
    "materials_text", "outstanding", "make_brief", "ingest", "refresh", "paths",
    "CwError",
]


# ---------------------------------------------------------------------------
# reading the store
# ---------------------------------------------------------------------------


def _store(data: str | Path | None) -> Path:
    """Resolve the store path, refusing to invent one that is not there.

    Raising beats returning empty. A caller that gets an empty list will report zero
    assignments, and a student who reads that will believe they have no homework.
    """
    path = find_data_dir(str(data) if data else "")
    if not store_is_readable(path):
        raise CwError(
            "پوشهٔ داده پیدا نشد: {}\n"
            "اگر تازه شروع کرده‌اید:  cwtrack fetch\n"
            "اگر جای دیگری است:      --data <مسیر>".format(path.resolve())
        )
    return path


def _load(data: str | Path | None) -> tuple[Path, dict, list, dict]:
    """(store path, user, assignments, gap analysis) for one consistent read."""
    data_dir = _store(data)
    user, assignments = tracker.load(data_dir)
    if not assignments:
        raise CwError(
            "استور خالی است ({}). اول cwtrack fetch را اجرا کن، یا با --data "
            "مسیر یک cw-data موجود را نشان بده.".format(data_dir.resolve())
        )
    now = datetime.now()
    now_epoch = int(now.timestamp())
    return data_dir, user, assignments, tracker.gaps(assignments, now_epoch) | {"now": now, "now_epoch": now_epoch}


def _item(a, now_epoch: int) -> dict:
    """One assignment as a plain dict, with the human countdown already resolved.

    A caller narrating to a student should not have to reimplement the "۳ روز مانده"
    wording, and two implementations of it would eventually disagree.
    """
    return {
        "course_id": a.course_id,
        "course": a.course,
        "term": a.term,
        "cmid": a.cmid,
        "name": a.name,
        "bucket": a.bucket,
        "bucket_fa": BUCKET_FA.get(a.bucket, a.bucket),
        "due": a.due,
        "due_text": a.due_text,
        "remaining": remaining_text(a.due, now_epoch),
        "status_text": a.status_text,
        "grade": a.grade,
        "url": a.url,
    }


def paths(data: str | Path | None = None, home: str | Path | None = None) -> dict:
    """Every folder this tool uses, resolved."""
    data_dir = find_data_dir(str(data) if data else "")
    return describe_paths(data_dir, Path(home) if home else STATE_DIR)


def status(data: str | Path | None = None) -> dict:
    """Everything left to do, ordered so the consequence comes first.

    The shape a caller should lead its answer from: `urgent`, then `soon`, then the
    per-course counts, then `unknown` - which is the list of things this tool refused
    to call done, and must be reported rather than dropped.
    """
    data_dir, _, assignments, gap = _load(data)
    now_epoch = gap["now_epoch"]
    return {
        "refreshed": _refreshed_at(data_dir),
        "counts": gap["counts"],
        "urgent": [_item(a, now_epoch) for a in gap["urgent"]],
        "soon": [_item(a, now_epoch) for a in gap["soon"]],
        "unscheduled": [_item(a, now_epoch) for a in gap["unscheduled"]],
        "unknown": [_item(a, now_epoch) for a in gap["unknown"]],
        "per_course": [
            {k: v for k, v in c.items() if k != "items"} for c in gap["per_course"]
        ],
        "paths": paths(data),
    }


def _refreshed_at(data_dir: Path) -> str:
    """When the store was last written.

    Countdowns are recomputed live, so this is the age of the *submission status*,
    not of the deadline. A caller saying "still open" should be able to say how old
    that claim is.
    """
    user_p = data_dir / "user.json"
    if not user_p.is_file():
        return ""
    try:
        return json.loads(user_p.read_text(encoding="utf-8-sig")).get("refreshed", "")
    except ValueError:
        return ""


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def gaps_text(data: str | Path | None = None) -> str:
    """The short Persian answer: what is left, worst first."""
    _, _, assignments, gap = _load(data)
    c = gap["counts"]
    lines = [
        "کل {} · ارسال‌نشده {} · گذشته از مهلت {} · انجام‌شده {}".format(
            c["total"], c["open"], c["urgent"], c["done"]
        ),
        "",
    ]
    lines += ["  [گذشته]  {} — {}".format(a.course, a.name) for a in gap["urgent"]]
    lines += [
        "  [نزدیک]  {} — {}  ({})".format(a.course, a.name, fmt_delta(a.due, gap["now_epoch"]))
        for a in gap["soon"]
    ]
    lines.append("")
    for c in gap["per_course"]:
        mark = "!!" if c["overdue"] else (" *" if c["open"] else "  ")
        lines.append(" {} {:<46} {}/{}".format(mark, c["course"][:46], c["done"], c["total"]))
    if not (gap["urgent"] or gap["soon"]):
        lines.append("  (مورد بازی ثبت نشده است)")
    return "\n".join(lines)


def open_text(
    data: str | Path | None = None,
    days: int | None = None,
    local: str | Path | None = None,
) -> str:
    """The outstanding list as a markdown table, optionally cross-referenced on disk."""
    _, _, assignments, gap = _load(data)
    picked = [a for a in assignments if a.bucket in OPEN_BUCKETS]
    if days:
        picked = [
            a for a in picked
            if a.due is not None and 0 < a.due - gap["now_epoch"] <= days * 86400
        ]
    rows = [a.__dict__ for a in picked]
    found = match_local(rows, Path(local)) if local else {}
    return table(rows, gap["now_epoch"], found) + "\n\n{} مورد باز".format(len(picked))


def report_text(data: str | Path | None = None, local: str | Path | None = None) -> str:
    """The full Persian markdown report."""
    data_dir, _, assignments, gap = _load(data)
    rows = [a.__dict__ for a in assignments]
    found = match_local(rows, Path(local)) if local else {}
    return report(rows, found, gap["now"])


def build_dashboard(
    data: str | Path | None = None, out: str | Path | None = None
) -> Path:
    """Write the single-page dashboard and return its path.

    Does not open it. Material counts are read from disk here rather than from the
    store, so a file dropped into a course folder shows up without a store refresh.
    """
    data_dir, user, assignments, gap = _load(data)
    mats = {}
    for cid_dir in (data_dir / "courses").glob("*"):
        if not cid_dir.is_dir():
            continue
        try:
            cid = int(cid_dir.name)
        except ValueError:
            continue
        mats[cid] = tracker.scan_materials(cid_dir / "materials")

    page = _build_page(
        user, assignments, gap, gap["now"], gap["now_epoch"], materials=mats
    )
    target = Path(out) if out else data_dir / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding="utf-8")
    return target.resolve()


def materials_text(data: str | Path | None = None, course: str | int | None = None) -> dict:
    """Where a course's material folder is and what is in it."""
    if course is None:
        raise CwError("course id لازم است")
    data_dir = _store(data)
    cid = int(course)
    folder = tracker.course_dir(data_dir, cid) / "materials"
    folder.mkdir(parents=True, exist_ok=True)
    mats = tracker.scan_materials(folder)
    return {
        "course_id": cid,
        "folder": str(folder.resolve()),
        "count": len(mats),
        "materials": [
            {"name": m.name, "bytes": m.bytes, "kind": m.kind, "modified": m.modified}
            for m in mats
        ],
    }


# ---------------------------------------------------------------------------
# the brief handoff
# ---------------------------------------------------------------------------


def outstanding(
    data: str | Path | None = None,
    course: str | int | None = None,
    days: int | None = None,
) -> list[dict]:
    """Open work, soonest first - what a brief would be built for by default.

    `days` narrows to deadlines still ahead and within N days, so "what should I do
    tonight" is a filter rather than a re-derivation of the same list.
    """
    _, _, assignments, gap = _load(data)
    picked = open_items(assignments, gap["now_epoch"], str(course or ""))
    if days:
        picked = [
            a for a in picked
            if a.due is not None and 0 < a.due - gap["now_epoch"] <= days * 86400
        ]
    return [_item(a, gap["now_epoch"]) for a in picked]


def make_brief(
    cmid: str | int | None = None,
    course: str | int | None = None,
    data: str | Path | None = None,
    work: str | Path | None = None,
    force: bool = False,
) -> dict:
    """Create the working folder for one assignment.

    With no `cmid` and more than one candidate, returns `needs_choice` rather than
    picking for the user: two open assignments due the same day are not the same
    problem, and guessing which one they meant would put the wrong brief in front of
    them.

    Returns `exists` rather than overwriting when the folder is already populated,
    because sections 2 to 7 of a brief are the student's own writing.
    """
    data_dir, _, assignments, gap = _load(data)
    work_root = Path(work) if work else (data_dir.parent / "work")
    candidates = open_items(assignments, gap["now_epoch"], str(course or ""))

    if cmid is not None:
        chosen = [a for a in assignments if str(a.cmid) == str(cmid)]
        if not chosen:
            raise CwError("no assignment with cmid={} in the store".format(cmid))
    elif len(candidates) == 1:
        chosen = candidates
    elif not candidates:
        return {"status": "nothing_outstanding", "candidates": []}
    else:
        return {
            "status": "needs_choice",
            "candidates": [_item(a, gap["now_epoch"]) for a in candidates],
        }

    results = []
    for a in chosen:
        meta = {"title": a.course, "term": a.term}
        folder, written = build_workfolder(
            a.__dict__, meta, data_dir, work_root, gap["now_epoch"], overwrite=force
        )
        results.append({
            "cmid": a.cmid,
            "name": a.name,
            "course": a.course,
            "folder": str(folder.resolve()),
            "written": [p.name for p in written],
            "existed": not written,
            "source": str((data_dir / "courses" / str(a.course_id) / "materials").resolve()),
        })
    return {"status": "ok", "briefs": results}


# ---------------------------------------------------------------------------
# the network side
# ---------------------------------------------------------------------------


def ingest(dump: str | Path | None = None, data: str | Path | None = None) -> dict:
    """Parse pages already on disk into the store. No network, no login.

    Separate from refresh() because "the pages are already saved, just read them" and
    "go and get them" are different requests, and a caller repairing a parse after the
    site changed its markup needs the first without a captcha in the way.
    """
    dump_dir = Path(dump) if dump else (STATE_DIR / "dump")
    if not dump_dir.is_dir():
        raise CwError("هیچ صفحه‌ای ذخیره نشده. اول fetch را اجرا کن.")

    data_dir = find_data_dir(str(data) if data else "")
    rows = parse_dump(dump_dir, datetime.now())
    if not rows:
        raise CwError("از صفحه‌های ذخیره‌شده هیچ تکلیفی درنیامد.")

    info = {"fullname": "", "username": "", "userid": ""}
    prev = data_dir / "user.json"
    if prev.is_file():
        with contextlib.suppress(ValueError):
            info = json.loads(prev.read_text(encoding="utf-8-sig"))

    summary = tracker.store(data_dir, info, rows)
    summary["store"] = str(data_dir.resolve())
    return summary


def _attempt_captcha(
    client, user: str, pw: str, base_dir: Path, given: str | None
) -> dict:
    """Log in, using `given` when the caller supplied it.

    With no answer, a confident OCR reading is tried once. If it does not land, the
    result is `captcha_required` with a *fresh* image, which is the same state the
    human path has always got — so the skill still shows an image and asks, and the
    feature cannot introduce a third outcome for it to handle.
    """
    state = auth.submit(client, user, pw, base_dir, captcha=given)
    if given or state["status"] != auth.CAPTCHA_REQUIRED:
        return state

    # `guess` returns ok=False rather than raising for every "could not read it" case,
    # but a decode error or an OS problem while writing a variant would escape it, and
    # that must not take the login down with it.
    try:
        guess = captcha_ocr.guess(state["image"])
    except Exception:  # noqa: BLE001 - a nicety must not break the login
        state.setdefault("ocr", {"read": "", "agreement": 0.0, "reason": "error"})
        return state
    if not guess.get("ok"):
        # Carry the disagreement into the state so the caller can say why it did not
        # simply answer — except when OCR is switched off, which is a choice rather
        # than a failure and has nothing to report.
        if guess.get("reason") != "disabled":
            state["ocr"] = {
                "read": guess.get("text", ""),
                "agreement": guess.get("agreement", 0.0),
                "reason": guess.get("reason", ""),
            }
        return state

    tried = auth.submit(client, user, pw, base_dir, captcha=guess["text"])
    if tried["status"] == auth.CAPTCHA_REJECTED:
        # The OCR read this confidently and was still wrong. Do not try again: hand
        # back the fresh image and let the human read it, with the reason recorded.
        tried["ocr"] = {
            "read": guess["text"],
            "agreement": guess.get("agreement", 0.0),
            "reason": "rejected_by_site",
        }
    return tried


def refresh(
    captcha: str | None = None,
    home: str | Path | None = None,
    data: str | Path | None = None,
    user: str | None = None,
    password: str | None = None,
    base: str | None = None,
) -> dict:
    """Log in if needed, download every course's assignment page, write the store.

    `captcha` is the answer to a previous `captcha_required`. The states are:

    - `{"status": "captcha_required", "viewer": Path, ...}` - show `viewer` to the
      user, read the characters, call this again with `captcha=`. The image is
      190x40 px on the site; `viewer` is the same image at 4x, which is the
      difference between one round trip and several.
    - `{"status": "ok", "courses": n, "assignments": n, "store": Path}` - done.
    - `{"status": "captcha_rejected", "viewer": Path, ...}` - wrong read, new image
      already downloaded, try again.
    - `{"status": "failed", "message": str}` - credentials or something else. Do
      not retry this without changing something.

    Credentials come from the arguments or the `CW_USER` / `CW_PASS` environment.
    Nothing is ever read from argv, because argv lands in shell history.

    Credentials are checked before the HTTP client is even built. The session cookie
    lives in memory, so a fresh process can never be logged in already; without a
    username and password this call cannot do anything, and finding that out without
    opening a socket is both faster and easier to read.
    """
    base_dir = Path(home) if home else STATE_DIR
    data_dir = find_data_dir(str(data) if data else "")
    name = user or os.environ.get("CW_USER")
    pw = password or os.environ.get("CW_PASS")
    if not name or not pw:
        return {
            "status": "needs_credentials",
            "message": "CW_USER و CW_PASS را در متغیر محیطی بگذار، یا user/password بده.",
        }

    client = Client(base or DEFAULT_BASE)

    if not client.logged_in():
        # Try the OCR reading before asking, and fall back to asking. Either way the
        # states are the ones the human path already produces, so the skill file
        # needs no new branch for the feature.
        state = _attempt_captcha(client, name, pw, base_dir, captcha)
        if state["status"] != auth.CAPTCHA_REQUIRED:
            return state

    count = fetch_all(client, base_dir)
    summary = ingest(base_dir / "dump", data_dir)
    summary.update({
        "status": "ok",
        "pages": count,
        "refreshed": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    return summary
