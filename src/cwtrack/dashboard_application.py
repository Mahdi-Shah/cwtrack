"""Application assembly for the read-only dashboard artifacts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from . import tracker
from .paths import find_data_dir, store_is_readable


def build(
    data,
    out,
    work,
    *,
    load_legacy: Callable,
    list_work: Callable,
    read_study: Callable,
    render_page: Callable,
    render_resources: Callable,
) -> Path:
    """Assemble the legacy and shared study projections into local HTML files."""
    data_dir = find_data_dir(str(data) if data else "")
    has_course_data = store_is_readable(data_dir)
    if has_course_data:
        data_dir, user, assignments, gap = load_legacy(data_dir)
    else:
        user = {}
        assignments = []
        gap = {}
        now = datetime.now()
        gap.update({"now": now, "now_epoch": int(now.timestamp())})
    work_root = Path(work) if work is not None else data_dir.parent / "work"
    work_items = list_work(data=data, work=work)
    common_study_view = read_study(data=data, work=work)

    materials = {}
    if has_course_data:
        for course_dir in (data_dir / "courses").glob("*"):
            if not course_dir.is_dir():
                continue
            try:
                course_id = int(course_dir.name)
            except ValueError:
                continue
            materials[course_id] = tracker.scan_materials(course_dir / "materials")

    page = render_page(
        user,
        assignments,
        gap,
        gap["now"],
        gap["now_epoch"],
        materials=materials,
        work_items=work_items,
        has_course_data=has_course_data,
        study_view=common_study_view,
    )
    target = Path(out) if out else (
        (data_dir if has_course_data else work_root.parent) / "index.html"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding="utf-8")
    resource_page = target.with_name("resources.html")
    resource_page.write_text(
        render_resources(common_study_view, target.name), encoding="utf-8"
    )
    return target.resolve()
