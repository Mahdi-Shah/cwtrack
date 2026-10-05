"""Rendering the markdown report."""

from __future__ import annotations

from datetime import datetime

from .classify import OPEN_BUCKETS
from .client import DEFAULT_BASE

BUCKET_FA = {
    "overdue": "گذشته از مهلت",
    "closed": "مهلت بسته شده",
    "draft": "پیش‌نویس",
    "open": "باز - ارسال نشده",
    "submitted": "ارسال شده",
    "graded": "نمره داده شده",
    "unknown": "نامشخص - دستی چک شود",
}
BUCKET_ORDER = ["overdue", "closed", "draft", "open", "submitted", "graded", "unknown"]

def fmt_delta(epoch: int | None, now_epoch: int) -> str:
    if not epoch:
        return ""
    delta = epoch - now_epoch
    if delta < 0:
        d = -delta // 86400
        return "گذشته: {} روز".format(d) if d >= 1 else "گذشته: کمتر از ۱ روز"
    d = delta // 86400
    if d >= 1:
        return "{} روز مانده".format(d)
    h = delta // 3600
    return "{} ساعت مانده".format(max(h, 0))


def _cell(text: str) -> str:
    """Make a value safe for a markdown table row.

    Course titles on this site carry a literal '|' as a separator - "درس کارگاه
    عمومی - 330181 | نیمسال اول سال تحصیلی 1405" - which silently shifts every
    column when rendered.
    """
    return (text or "").replace("|", "／").replace("\n", " ").strip()


def table(rows: list[dict], now_epoch: int, local: dict[str, list[str]]) -> str:
    head = "| وضعیت | مهلت | باقی‌مانده | درس | تکلیف | محلی |\n|---|---|---|---|---|---|"
    out = []
    for row in sorted(rows, key=lambda r: (BUCKET_ORDER.index(r["bucket"]), r["due"] or 1 << 62)):
        found = local.get("{}|{}".format(row["name"], row["course"]))
        loc = "📄 " + _cell(found[0]) if found else ""
        out.append(
            "| {} | {} | {} | {} | {} | {} |".format(
                BUCKET_FA[row["bucket"]],
                _cell(row["due_text"]) or "—",
                fmt_delta(row["due"], now_epoch),
                _cell(row["course"]),
                _cell(row["name"]),
                loc,
            )
        )
    return "\n".join([head] + out) if out else "_موردی نیست_"


def report(rows: list[dict], local: dict[str, list[str]], now: datetime) -> str:
    now_epoch = int(now.timestamp())
    open_rows = [r for r in rows if r["bucket"] in OPEN_BUCKETS]
    urgent = [r for r in rows if r["bucket"] in ("overdue", "closed")]
    # "Soon" means still ahead and close. A past deadline already has a home in
    # the urgent section, and letting it in here lists it twice under two headings
    # that read as different situations.
    soon = [
        r for r in open_rows
        if r["bucket"] in ("open", "draft")
        and r["due"] is not None
        and 0 < r["due"] - now_epoch <= 14 * 86400
    ]
    unknown = [r for r in rows if r["bucket"] == "unknown"]
    # Named states, never `total - open`. That arithmetic counted an unparsed row as
    # handed in, which is the one thing this tool refuses to do.
    settled = [r for r in rows if r["bucket"] in ("graded", "submitted")]

    out = ["# وضعیت تکالیف", ""]
    out.append("- **زمان گزارش:** {}".format(now.strftime("%Y-%m-%d %H:%M")))
    out.append("- **سایت:** {}".format(DEFAULT_BASE))
    out.append("")
    out += [
        "| | تعداد |",
        "|---|---|",
        "| کل تکالیف | {} |".format(len(rows)),
        "| ارسال‌نشده | {} |".format(len(open_rows)),
        "| گذشته از مهلت یا بسته‌شده | {} |".format(len(urgent)),
        "| ارسال‌شده یا نمره‌دار | {} |".format(len(settled)),
        "| نامشخص | {} |".format(len(unknown)),
        "",
    ]

    if urgent:
        out += ["## 🔴 فوری", "", "گذشته از مهلت، یا پنجرهٔ ارسال بسته شده و چیزی ثبت نشده.", "",
                table(urgent, now_epoch, local), ""]
    if soon:
        out += ["## 🟡 نزدیک", "", "کمتر از دو هفته.", "", table(soon, now_epoch, local), ""]
    if local:
        out += ["## 📄 فایل محلی پیدا شد", "",
                "ارسال نشده، ولی فایلی با نام مشابه روی دیسک هست. احتمالاً کار انجام شده و "
                "بارگذاری فراموش شده. حتماً خودت بررسی کن.", ""]
        for row in open_rows:
            key = "{}|{}".format(row["name"], row["course"])
            if key in local:
                out.append("- **{}** ({}) → {}".format(row["name"], row["course"], ", ".join(local[key])))
        out.append("")
    out += ["## همهٔ تکالیف", "", table(rows, now_epoch, local), ""]
    if unknown:
        out += ["## مواردی که این ابزار نفهمید", "",
                "وضعیتشان قابل تفسیر نبود و «انجام‌شده» حساب نشده‌اند. دستی چک کن:", ""]
        for row in unknown:
            out.append("- {} — {} — [باز کردن]({})".format(row["course"], row["name"], row["url"]))
        out.append("")
    return "\n".join(out)
