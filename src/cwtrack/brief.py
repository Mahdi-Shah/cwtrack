"""Turning a tracked assignment into a working folder.

This is the seam between the two skills. `cwtrack` knows an assignment exists and
when it is due; `university-assignment` knows how to produce the document. Neither
knows about the other, and asking a person to copy a title, a deadline and a URL
into a template by hand is exactly where the gap leaks.

So this module writes the brief. It fills in everything the site actually knows,
and is explicit about the one thing it does not: the assignment text. That has to
come from the page or from the student, and pretending otherwise is how a brief
ends up confidently solving the wrong question.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path

from .classify import OPEN_BUCKETS
from .report import BUCKET_FA

BRIEF_TEMPLATE = """# {title}

<!--
این پرونده با `cwtrack brief` ساخته شده و برای مهارت `university-assignment` آماده است.
هر چه زیر «نیازمند» علامت خورده، از روی سایت قابل استخراج نبود و باید پر شود.
-->

## ۱. مشخصات (از سایت — قابل اعتماد)

| مورد | مقدار |
|---|---|
| **عنوان** | {title} |
| **درس** | {course} |
| **ترم** | {term} |
| **مهلت** | {due_text} |
| **باقی‌مانده** | {remaining} |
| **وضعیت سایت** | {bucket_fa} |
| **لینک** | {url} |
| **شناسهٔ فعالیت** | `cmid={cmid}` |

## ۲. متن تکلیف

<!-- نیازمند: متن تکلیف از صفحهٔ سایت یا جزوهٔ استاد. -->

[نیازمند متن تکلیف]

> اگر صفحهٔ تکلیف جزئیات بیشتری دارد (تعداد سؤال، قالب تحویل، نمرهٔ
> هر بخش، فرمت مجاز) اینجا بیاورید — تصمیم‌های مهارت
> `university-assignment` بر اساس همین متن گرفته می‌شود.

## ۳. محدودیت‌ها

| مورد | مقدار | از کجا |
|---|---|---|
| نوع تکلیف | `[نیازمند]` | متن تکلیف |
| قالب خروجی | `[نیازمند]` | متن تکلیف |
| محدودیت حجم | `[نیازمند]` | متن تکلیف |
| ارجاع‌دهی | `[نیازمند]` | متن تکلیف |
| منابع مجاز | `[نیازمند]` | متن تکلیف |

## ۴. منابع

پوشهٔ منابع این درس: `{course_materials}`

فایل‌های موجود در حال حاضر:

{materials_list}

<!-- هر فایلی که استاد گفته لازم است، اینجا فهرست شود. -->

## ۵. داده‌های ورودی

اگر تکلیف آزمایشگاه یا نیازمند اندازه‌گیری است:

| کمیت | مقدار | واحد | منبع |
|---|---|---|---|
|  |  |  |  |

داده‌هایی که در دسترس نیستند: `[نیازمند داده]`

## ۶. آنچه هنوز نامعلوم است

- [ ] متن تکلیف
- [ ] قالب مجاز تحویل
- [ ] حجم مجاز
- [ ] اینکه تکلیف چند سؤال دارد

## ۷. یادداشت

{notes_placeholder}
"""

HANDOFF = """# راهنمای تحویل — {title}

این پوشه با `cwtrack brief` ساخته شده. مهارت `university-assignment` را روی
همین پوشه اجرا کنید:

1. متن تکلیف را از `brief.md` بخش ۲ پر کنید (از صفحهٔ سایت یا جزوه).
2. منابع لازم را در `source/` بگذارید.
3. مهارت `university-assignment` را صدا بزنید و همین پوشه را بدهید.
4. خروجی را با `render.py` به PDF تبدیل کنید.
5. **بارگذاری را خودتان در مرورگر انجام دهید.** ابزار هیچ چیزی ارسال نمی‌کند.

## وضعیت سایت هنگام ساخت این پوشه

{meta}

## دستورها

```powershell
# رندر پیش‌نویس
python <path-to-university-assignment>/scripts/render.py draft.md --title "{title}"
```
"""


def slugify(text: str, maxlen: int = 60) -> str:
    """A filesystem-safe name that still reads as Persian where possible."""
    text = unicodedata.normalize("NFKC", text).strip()
    text = re.sub(r"[\\/:*?\"<>|]+", "", text)          # illegal on Windows
    text = re.sub(r"\s+", " ", text).strip(" .")
    if len(text) > maxlen:
        text = text[:maxlen].rstrip(" .")
    # Windows rejects names ending in a dot, and reserved device names exist.
    if text.upper().split(".")[0] in {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10)),
    }:
        text = "_" + text
    return text or "untitled"


def course_materials_dir(data_dir: Path, course_id: int) -> Path:
    return data_dir / "courses" / str(course_id) / "materials"


def remaining_text(epoch: int | None, now_epoch: int) -> str:
    if not epoch:
        return "بدون مهلت"
    d = epoch - now_epoch
    if d < 0:
        n = -d // 86400
        return "گذشته {} روز".format(n) if n >= 1 else "گذشته: کمتر از ۱ روز"
    n = d // 86400
    if n >= 1:
        return "{} روز مانده".format(n)
    return "{} ساعت مانده".format(max(d // 3600, 0))


def build_workfolder(
    assignment: dict,
    course: dict,
    data_dir: Path,
    work_root: Path,
    now_epoch: int,
    overwrite: bool = False,
) -> tuple[Path, list[Path]]:
    """Create the folder and write the brief. Returns (folder, written files).

    Refuses to overwrite by default: an existing folder means work has started,
    and silently replacing the brief would throw away whatever the student wrote
    in sections 2 to 7.
    """
    course_slug = slugify(course.get("title") or str(assignment["course_id"]))
    title_slug = slugify(assignment["name"])
    folder = work_root / course_slug / title_slug
    if folder.exists() and any(folder.iterdir()) and not overwrite:
        return folder, []

    (folder / "source").mkdir(parents=True, exist_ok=True)

    mats_dir = course_materials_dir(data_dir, assignment["course_id"])
    material_lines = ["- (هیچ فایلی در پوشهٔ منابع این درس نیست)"]
    if mats_dir.is_dir():
        found = sorted(
            p for p in mats_dir.rglob("*")
            if p.is_file() and p.suffix.lower() != ".json" and not p.name.startswith(".")
        )
        if found:
            material_lines = [
                "- `{}`  ({} کیلوبایت)".format(
                    p.relative_to(mats_dir).as_posix(), p.stat().st_size // 1024
                )
                for p in found
            ]

    brief = BRIEF_TEMPLATE.format(
        title=assignment["name"],
        course=course.get("title") or assignment["course_id"],
        term=course.get("term") or "—",
        due_text=assignment.get("due_text") or "—",
        remaining=remaining_text(assignment.get("due"), now_epoch),
        bucket_fa=BUCKET_FA.get(assignment["bucket"], assignment["bucket"]),
        url=assignment["url"],
        cmid=assignment["cmid"],
        course_materials=mats_dir,
        materials_list="\n".join(material_lines),
        notes_placeholder=(
            "این بخش را نگه دارید. برای هر چیزی که در حین حل به آن رسیدید و "
            "بعداً به آن نیاز دارید بنویسید."
        ),
    )

    handoff = HANDOFF.format(
        title=assignment["name"],
        meta="\n".join([
            "- **وضعیت:** {}".format(BUCKET_FA.get(assignment["bucket"], assignment["bucket"])),
            "- **مهلت:** {}".format(assignment.get("due_text") or "—"),
            "- **باقی‌مانده:** {}".format(remaining_text(assignment.get("due"), now_epoch)),
            "- **لینک:** {}".format(assignment["url"]),
            "- **ساخته شده:** {}".format(datetime.now().strftime("%Y-%m-%d %H:%M")),
        ]),
    )

    written = []
    for name, text in (("brief.md", brief), ("HANDOFF.md", handoff),
                       ("draft.md", "# پیش‌نویس پاسخ\n\n"),
                       (".gitkeep", "")):
        p = folder / name
        p.write_text(text, encoding="utf-8")
        written.append(p)
    return folder, written


def open_items(assignments: list, now_epoch: int, course_filter: str = "") -> list:
    """Outstanding work, soonest first, so `brief` defaults to what actually needs
    doing rather than making the user look up an id."""
    picked = [a for a in assignments if a.bucket in OPEN_BUCKETS]
    if course_filter:
        picked = [a for a in picked if str(a.course_id) == str(course_filter)]
    return sorted(picked, key=lambda a: (a.due is None, a.due or 0, a.name))
