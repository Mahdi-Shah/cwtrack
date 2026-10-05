"""Local course tracker: a store on disk plus the gap analysis that drives the UI.

Layout it creates under --data (default ./cw-data):

    cw-data/
      user.json              who this belongs to, and when it was last refreshed
      assignments.json       every assignment across every course, one flat list
      courses/
        2824/
          course.json        id, title, term, url
          assignments.json   just this course's rows
          materials/         the files. yours, or fetched.
          notes.md           free-form scratch space

Materials are a folder convention, not a guess about the site's markup: whatever
is in materials/ is counted, and anything else is simply not claimed to exist.
That way a file you saved by hand and a file a future fetcher downloaded are the
same thing to everything downstream.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

MATERIAL_EXT = {
    ".pdf": "PDF", ".ppt": "اسلاید", ".pptx": "اسلاید", ".odp": "اسلاید",
    ".doc": "متن", ".docx": "متن", ".odt": "متن", ".txt": "متن", ".md": "متن",
    ".zip": "آرشیو", ".rar": "آرشیو", ".7z": "آرشیو",
    ".ipynb": "نوت‌بوک", ".py": "کد", ".m": "کد", ".tex": "کد",
    ".png": "تصویر", ".jpg": "تصویر", ".jpeg": "تصویر", ".mp4": "ویدیو",
}


@dataclass
class Material:
    name: str
    bytes: int
    kind: str
    modified: str


@dataclass
class Assignment:
    course_id: int
    course: str
    term: str
    name: str
    cmid: int
    due: int | None
    due_text: str
    status_text: str
    grade: str
    bucket: str
    url: str
    materials: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return "{}:{}".format(self.course_id, self.cmid)


def read_json(path: Path):
    """JSON read that tolerates a BOM.

    Anything on Windows that rewrites these files - PowerShell's
    `Set-Content -Encoding UTF8`, Notepad, some sync clients - puts a UTF-8 BOM in
    front, and stock json.loads refuses the file outright. utf-8-sig reads both.
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def course_dir(data: Path, cid: int) -> Path:
    return data / "courses" / str(cid)


def split_title(title: str) -> tuple[str, str]:
    """Course titles look like 'درس کارگاه عمومی - 330181 | نیمسال اول 1405'.

    Returns (course, term). Without the split the term lands in the middle of
    every course name in the UI.
    """
    if "|" in title:
        left, right = title.split("|", 1)
        return left.strip(), right.strip()
    return title.strip(), ""


def scan_materials(folder: Path) -> list[Material]:
    if not folder.is_dir():
        return []
    out = []
    for p in sorted(folder.rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        if p.suffix.lower() == ".json":
            continue
        st = p.stat()
        out.append(
            Material(
                name=str(p.relative_to(folder)).replace("\\", "/"),
                bytes=st.st_size,
                kind=MATERIAL_EXT.get(p.suffix.lower(), "فایل"),
                modified=datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
            )
        )
    return out


def store(data: Path, info: dict, rows: list[dict], materials_root: Path | None = None) -> dict:
    """Write the whole tracker state. Returns a small summary of what changed."""
    data.mkdir(parents=True, exist_ok=True)
    by_course: dict[int, list[dict]] = {}
    for row in rows:
        by_course.setdefault(row["course_id"], []).append(row)

    all_assignments: list[Assignment] = []
    new_courses = 0

    for cid, crows in by_course.items():
        cdir = course_dir(data, cid)
        cdir.mkdir(parents=True, exist_ok=True)
        title, term = split_title(crows[0].get("course", str(cid)))

        meta = {
            "id": cid,
            "title": title,
            "term": term,
            "url": "https://cw.sharif.ir/course/view.php?id={}".format(cid),
            "assignments_url": "https://cw.sharif.ir/mod/assign/index.php?id={}".format(cid),
        }
        (cdir / "course.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if not (cdir / "notes.md").exists():
            new_courses += 1

        (cdir / "materials").mkdir(exist_ok=True)
        if not (cdir / "notes.md").exists():
            (cdir / "notes.md").write_text(
                "# یادداشت‌های {}\n\n".format(title), encoding="utf-8"
            )

        mats = scan_materials(cdir / "materials")
        write_json(cdir / "materials.json", [asdict(m) for m in mats])
        write_json(cdir / "assignments.json", crows)

        for row in crows:
            all_assignments.append(
                Assignment(
                    course_id=cid,
                    course=title,
                    term=term,
                    name=row["name"],
                    cmid=row["cmid"],
                    due=row["due"],
                    due_text=row["due_text"],
                    status_text=row["status_text"],
                    grade=row["grade"],
                    bucket=row["bucket"],
                    url=row["url"],
                    materials=[m.name for m in mats],
                )
            )

    write_json(data / "assignments.json", [asdict(a) for a in all_assignments])
    write_json(
        data / "user.json",
        {
            "fullname": info.get("fullname", ""),
            "username": info.get("username", ""),
            "userid": info.get("userid", ""),
            "site": "https://cw.sharif.ir",
            "refreshed": datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
    )
    return {"courses": len(by_course), "assignments": len(all_assignments), "new": new_courses}


def load(data: Path) -> tuple[dict, list[Assignment]]:
    user_p = data / "user.json"
    user = read_json(user_p) if user_p.is_file() else {}
    a_p = data / "assignments.json"
    if not a_p.is_file():
        return user, []
    raw = read_json(a_p)
    return user, [Assignment(**r) for r in raw]


# --------------------------------------------------------------------------
# gap analysis
# --------------------------------------------------------------------------

OPEN = {"overdue", "closed", "draft", "open"}


def gaps(assignments: list[Assignment], now_epoch: int) -> dict:
    """What is actually left, ordered so the consequence comes first."""
    open_items = [a for a in assignments if a.bucket in OPEN]
    urgent = [a for a in open_items if a.bucket in ("overdue", "closed")]
    soon = [
        a for a in open_items
        if a.bucket in ("open", "draft") and a.due is not None
        and 0 < a.due - now_epoch <= 14 * 86400
    ]
    unscheduled = [
        a for a in open_items if a.due is None or (a.due is not None and a.due < now_epoch and a.bucket == "open")
    ]

    per_course: dict[int, dict] = {}
    for a in assignments:
        slot = per_course.setdefault(
            a.course_id,
            {"course_id": a.course_id, "course": a.course, "term": a.term,
             "total": 0, "done": 0, "open": 0, "overdue": 0, "soonest": None, "items": []},
        )
        slot["total"] += 1
        if a.bucket in ("graded", "submitted"):
            slot["done"] += 1
        if a.bucket in OPEN:
            slot["open"] += 1
        if a.bucket == "overdue":
            slot["overdue"] += 1
        if a.due and (slot["soonest"] is None or a.due < slot["soonest"][0]):
            slot["soonest"] = (a.due, a.name)
        slot["items"].append(a)

    unknown = [a for a in assignments if a.bucket == "unknown"]
    # Named states, not the complement. `total - open` counted an `unknown` row as
    # finished, because `unknown` is deliberately not in OPEN - so the one bucket
    # this tool refuses to interpret was the one reported as handed in. That is the
    # failure the whole module exists to prevent, and it was in the headline number
    # rather than in a detail. `done` here and `done` in per_course must agree.
    done = [a for a in assignments if a.bucket in ("graded", "submitted")]

    return {
        "urgent": urgent,
        "soon": soon,
        "unscheduled": unscheduled,
        "unknown": unknown,
        "per_course": sorted(per_course.values(), key=lambda c: (-c["overdue"], -c["open"], c["course"])),
        "counts": {
            "total": len(assignments),
            "open": len(open_items),
            "urgent": len(urgent),
            "done": len(done),
            "unknown": len(unknown),
        },
    }
