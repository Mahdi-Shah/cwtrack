"""Deadlines, which on this site are Jalali and rarely carry a year.

Everything here is pure: no network, no filesystem, no clock other than the
`now` passed in. That is what makes it testable, and it is where most of the
bugs lived.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
PERSIAN_MONTHS = (
    ("فروردین", 1), ("اردیبهشت", 2), ("خرداد", 3), ("تیر", 4), ("مرداد", 5),
    ("شهریور", 6), ("مهر", 7), ("آبان", 8), ("آذر", 9), ("دی", 10),
    ("بهمن", 11), ("اسفند", 12),
)
SITE_TZ_OFFSET = int(3.5 * 3600)
NOWRUZ = (
    "2001-03-21", "2002-03-21", "2003-03-21", "2004-03-20", "2005-03-21", "2006-03-21",
    "2007-03-21", "2008-03-20", "2009-03-21", "2010-03-21", "2011-03-21", "2012-03-20",
    "2013-03-21", "2014-03-21", "2015-03-21", "2016-03-20", "2017-03-21", "2018-03-21",
    "2019-03-21", "2020-03-20", "2021-03-21", "2022-03-21", "2023-03-21", "2024-03-20",
    "2025-03-21", "2026-03-21", "2027-03-21", "2028-03-20", "2029-03-20", "2030-03-21",
    "2031-03-21", "2032-03-20", "2033-03-20", "2034-03-21", "2035-03-21", "2036-03-20",
    "2037-03-20", "2038-03-21", "2039-03-21", "2040-03-20", "2041-03-20", "2042-03-21",
    "2043-03-21", "2044-03-20", "2045-03-20", "2046-03-21", "2047-03-21", "2048-03-20",
    "2049-03-20", "2050-03-21", "2051-03-21", "2052-03-20", "2053-03-20", "2054-03-21",
    "2055-03-21", "2056-03-20", "2057-03-20", "2058-03-21", "2059-03-21", "2060-03-20",
    "2061-03-20", "2062-03-20", "2063-03-21",
)
NOWRUZ_FIRST_YEAR = 1380
JALALI_MONTH_LENGTHS = (31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29)
RELATIVE_WORDS = {
    "today": 0, "امروز": 0, "فردا": 1, "tomorrow": 1, "دیروز": -1, "yesterday": -1,
}
AM_PM = (
    ("صبح", 0), ("قبل از ظهر", 0), ("ق.ظ", 0), ("am", 0),
    ("بعد از ظهر", 12), ("بعدازظهر", 12), ("ب.ظ", 12), ("pm", 12),
    ("عصر", 12), ("شب", 12),
)

def _nowruz(jy: int) -> date | None:
    i = jy - NOWRUZ_FIRST_YEAR
    if 0 <= i < len(NOWRUZ):
        try:
            return date.fromisoformat(NOWRUZ[i])
        except ValueError:
            return None
    return None


def _is_jalali_leap(jy: int) -> bool | None:
    """Leap = this year is 366 days, read off the Nowruz table."""
    a, b = _nowruz(jy), _nowruz(jy + 1)
    if not a or not b:
        return None
    return (b - a).days == 366


def _jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int] | None:
    """Jalali (Solar Hijri) to Gregorian.

    Needed because a Persian course site prints 1404 meaning 2025-2026, not the
    year 1404 CE. Read as Gregorian, every deadline lands 580 years in the past
    and the whole term reports as overdue.

    Prefers jdatetime when installed; otherwise uses the NOWRUZ table above.
    """
    if not 1 <= jm <= 12 or jd < 1:
        return None

    try:
        import jdatetime  # noqa: PLC0415 - optional dependency, imported on demand

        g = jdatetime.date(jy, jm, jd).togregorian()
        return g.year, g.month, g.day
    except ImportError:
        pass
    except (ValueError, OverflowError):
        return None

    start = _nowruz(jy)
    if start is None:
        return None
    month_len = list(JALALI_MONTH_LENGTHS)
    if jm == 12:
        # Esfand is the only month whose length depends on the leap flag.
        leap = _is_jalali_leap(jy)
        if leap is None:
            return None
        month_len[11] = 30 if leap else 29
    if jd > month_len[jm - 1]:
        return None
    g = start + timedelta(days=sum(month_len[: jm - 1]) + jd - 1)
    return g.year, g.month, g.day


def _epoch(y: int, m: int, d: int, hour: int = 23, minute: int = 59) -> int | None:
    """Epoch for a Gregorian wall-clock date via calendar arithmetic.

    datetime(...).timestamp() routes through the OS mktime, which fails on Windows
    for Jalali-era years with OSError 22 - a hard crash on exactly the dates this
    site shows. Subtracting two date objects needs no syscall and no tz database.
    """
    try:
        days = (date(y, m, d) - date(1970, 1, 1)).days
    except ValueError:
        return None
    return days * 86400 + hour * 3600 + minute * 60 - SITE_TZ_OFFSET


def _epoch_jalali(jy: int, jm: int, jd: int, hour: int = 23, minute: int = 59) -> int | None:
    g = _jalali_to_gregorian(jy, jm, jd)
    if not g:
        return None
    return _epoch(g[0], g[1], g[2], hour, minute)


def gregorian_to_jalali(g: date) -> tuple[int, int, int] | None:
    """Gregorian -> Jalali. Needed because this site prints deadlines with no year
    at all - "Tomorrow, 14 مهر" - so the year has to come from somewhere."""
    try:
        import jdatetime  # noqa: PLC0415

        j = jdatetime.date.fromgregorian(date=g)
        return j.year, j.month, j.day
    except ImportError:
        pass
    except (ValueError, OverflowError):
        return None
    # Fallback: walk the Nowruz table, which is sorted.
    for i in range(len(NOWRUZ) - 1):
        start = date.fromisoformat(NOWRUZ[i])
        end = date.fromisoformat(NOWRUZ[i + 1])
        if start <= g < end:
            jy = NOWRUZ_FIRST_YEAR + i
            leap = _is_jalali_leap(jy)
            month_len = list(JALALI_MONTH_LENGTHS)
            if leap is not None:
                month_len[11] = 30 if leap else 29
            offset = (g - start).days
            for jm in range(1, 13):
                if offset < month_len[jm - 1]:
                    return jy, jm, offset + 1
                offset -= month_len[jm - 1]
            return None
    return None


def _jdatetime_to_epoch(jy: int, jm: int, jd: int, hour: int, minute: int) -> int | None:
    g = _jalali_to_gregorian(jy, jm, jd)
    if not g:
        return None
    return _epoch(g[0], g[1], g[2], hour, minute)


def parse_due(text: str, now: datetime) -> tuple[str, int | None]:
    """Pull a deadline out of a date cell. Returns (raw text, epoch or None).

    This site's real format is mixed and year-less, e.g.

        Tomorrow, 14 مهر, 7:30 صبح
        ۱۴۰۴/۰۸/۱۴، ۲۳:۵۹
        2026-11-20, 23:59

    so: a relative word may lead, the year is often absent, and the meridiem may
    be Persian. The year comes from today's Jalali date, corrected forward if the
    result would land more than half a year ahead - which is how a December
    deadline shown in November is read as next year rather than 11 months early.

    Anything unparsed returns None and the row keeps the site's own text, so a
    student never has to trust our arithmetic over what the site displayed.
    """
    if not text or text.strip() in {"—", "-", "–", "‏", "﻿"}:
        return "", None

    norm = text.translate(FA_DIGITS)
    low = norm.lower()
    today_g = now.date()

    # ---- 1. relative prefix -------------------------------------------------
    day_shift = None
    for word, delta in RELATIVE_WORDS.items():
        if word in low:
            day_shift = delta
            break
    if day_shift is not None:
        # "Tomorrow, 14 مهر" and "Tomorrow" mean the same day; trust the explicit
        # date if present, otherwise fall back to the relative offset.
        rest = re.sub(r"^[^0-9۰-۹]*", "", norm)
        _, epoch = parse_due(rest, now)
        if epoch is not None:
            return text, epoch
        target = today_g + timedelta(days=day_shift)
        hour, minute = 23, 59
        m = re.search(r"(\d{1,2})\s*:\s*(\d{2})", norm)
        if m:
            hour, minute = int(m.group(1)), int(m.group(2))
        return text, _epoch(target.year, target.month, target.day, hour, minute)

    # ---- 2. clock time and meridiem ----------------------------------------
    hour, minute = 23, 59
    m = re.search(r"(\d{1,2})\s*:\s*(\d{2})", norm)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        for word, offset in AM_PM:
            if word in low:
                if offset == 12 and hour < 12:
                    hour += 12
                elif offset == 0 and hour == 12:
                    hour = 0
                break

    # ---- 3. full ISO numeric ------------------------------------------------
    m = re.search(r"(\d{4})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})", norm)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        if y < 1700:
            return text, _jdatetime_to_epoch(y, mo, d, hour, minute)
        return text, _epoch(y, mo, d, hour, minute)

    m = re.search(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{1,2}):(\d{2})", norm)
    if m:
        y, mo, d, hh, mm = (int(x) for x in m.groups())
        return text, _epoch(y, mo, d, hh, mm)

    # ---- 4. Jalali month name, with or without a year ----------------------
    # Month names are matched on token boundaries: Persian letters are \w under
    # Python's Unicode regex, so \b is what keeps "دی" from matching inside "دیگر".
    month = next(
        (num for name, num in PERSIAN_MONTHS if re.search(r"\b" + name + r"\b", norm)),
        None,
    )
    if month:
        tokens = [int(t) for t in re.findall(r"\d{1,4}", norm)]
        year = next((t for t in tokens if 1000 <= t <= 3500), None)
        day = next((t for t in tokens if 1 <= t <= 31 and t != year), None)
        if day is None:
            return text, None
        if year is None:
            today_j = gregorian_to_jalali(today_g)
            if not today_j:
                return text, None
            year = today_j[0]
            epoch = _jdatetime_to_epoch(year, month, day, hour, minute)
            # No year on the page: if that lands us over six months out, it is
            # next year's date being displayed early.
            if epoch is not None and epoch - int(now.timestamp()) > 182 * 86400:
                epoch = _jdatetime_to_epoch(year - 1, month, day, hour, minute)
            return text, epoch
        return text, _jdatetime_to_epoch(year, month, day, hour, minute)

    return text, None
