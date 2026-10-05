"""Dates.

This module is where most of the real bugs were, and every one of them was
invisible until the invariants were written down. The tests here are mostly
properties over a range rather than examples, because the failures were
off-by-ones in the middle of a century.

The short "33-year formula" Jalali conversions that circulate online are the
thing to guard against: two attempts in this project produced Nowruz on 22 March
and 364- and 367-day years. These tests exist to catch that if it ever creeps back.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from cwtrack import dates


class TestJalaliConversion:
    """Properties, not examples. A single anchor would have passed the buggy
    versions."""

    @pytest.mark.parametrize("jy", range(1380, 1441))
    def test_nowruz_is_20_or_21_march(self, jy):
        g = dates._jalali_to_gregorian(jy, 1, 1)
        assert g is not None, jy
        assert g[1] == 3
        assert g[2] in (20, 21), "jalali {} started on {}".format(jy, g)

    @pytest.mark.parametrize("jy", range(1380, 1441))
    def test_year_length_is_365_or_366(self, jy):
        if jy + 1 > 1442:
            pytest.skip("needs a Nowruz one year past the embedded table")
        a = date(*dates._jalali_to_gregorian(jy, 1, 1))
        b = date(*dates._jalali_to_gregorian(jy + 1, 1, 1))
        assert (b - a).days in (365, 366)

    def test_documented_table_range_matches_the_code(self):
        """Pin the fallback's stated coverage so the docs cannot drift from it.

        The table is a *fallback* for when jdatetime is absent, and it only needs
        to cover current and near-future terms. Outside it, the fallback must
        return None rather than invent a date - though when jdatetime is
        installed it covers any year, which is the better answer.
        """
        import importlib.util

        assert dates.NOWRUZ_FIRST_YEAR == 1380
        last_covered = dates.NOWRUZ_FIRST_YEAR + len(dates.NOWRUZ) - 1
        assert last_covered == 1442
        # In range: both paths must answer.
        assert dates._jalali_to_gregorian(last_covered, 1, 1) is not None
        assert dates._jalali_to_gregorian(1380, 1, 1) is not None
        if not importlib.util.find_spec("jdatetime"):
            assert dates._jalali_to_gregorian(last_covered + 1, 1, 1) is None

    @pytest.mark.parametrize("start", [c for c in range(1380, 1441, 33) if c + 33 <= 1442])
    def test_exactly_eight_leap_years_per_33_year_cycle(self, start):
        """Only for cycles entirely inside the table.

        A cycle straddling the table edge cannot be evaluated from the fallback,
        and pretending otherwise by widening the table to satisfy a test would be
        moving the goalposts rather than fixing anything.
        """
        leaps = 0
        for jy in range(start, start + 33):
            a = date(*dates._jalali_to_gregorian(jy, 1, 1))
            b = date(*dates._jalali_to_gregorian(jy + 1, 1, 1))
            leaps += (b - a).days == 366
        assert leaps == 8, "cycle starting {} had {} leap years".format(start, leaps)

    @pytest.mark.parametrize("jy", [1399, 1400, 1403, 1404, 1405])
    def test_every_day_of_a_year_is_consecutive(self, jy):
        leap = dates._is_jalali_leap(jy)
        seq = []
        for jm in range(1, 13):
            n = 31 if jm <= 6 else (30 if jm <= 11 else (30 if leap else 29))
            for jd in range(1, n + 1):
                g = dates._jalali_to_gregorian(jy, jm, jd)
                assert g is not None, (jy, jm, jd)
                seq.append(date(*g))
        assert len(seq) in (365, 366)
        for a, b in zip(seq, seq[1:]):
            assert b - a == timedelta(days=1)

    def test_known_anchors(self):
        assert dates._jalali_to_gregorian(1404, 1, 1) == (2025, 3, 21)
        assert dates._jalali_to_gregorian(1405, 1, 1) == (2026, 3, 21)
        assert dates._jalali_to_gregorian(1404, 7, 21) == (2025, 10, 13)
        # 1403 was a leap year, so Esfand had 30 days.
        assert dates._jalali_to_gregorian(1403, 12, 30) == (2025, 3, 20)
        assert dates._jalali_to_gregorian(1399, 12, 30) == (2021, 3, 20)

    @pytest.mark.parametrize("bad", [
        (1404, 12, 31), (1404, 13, 1), (1404, 7, 31), (1404, 1, 0),
        (1404, 0, 1), (1404, 1, 32),
    ])
    def test_rejects_impossible_dates(self, bad):
        assert dates._jalali_to_gregorian(*bad) is None

    def test_outside_the_embedded_table_is_refused_not_guessed(self):
        # The table covers 1380-1442. Outside it the fallback must return None
        # rather than invent a date - but only when jdatetime is absent, because
        # jdatetime covers any year and is the preferred path when installed.
        import importlib.util

        if importlib.util.find_spec("jdatetime"):
            pytest.skip("jdatetime installed; it covers years outside the table")
        assert dates._jalali_to_gregorian(1300, 1, 1) is None
        assert dates._jalali_to_gregorian(1500, 1, 1) is None

    @pytest.mark.parametrize("d", [date(2001, 3, 21), date(2026, 3, 21), date(2025, 10, 13)])
    def test_round_trip_gregorian_jalali_gregorian(self, d):
        j = dates.gregorian_to_jalali(d)
        assert j is not None
        assert dates._jalali_to_gregorian(*j) == (d.year, d.month, d.day)


class TestParseDue:
    """The formats this site actually emits, all of them year-less or mixed."""

    def test_relative_word_with_persian_month_and_meridiem(self, now):
        text, epoch = dates.parse_due("Tomorrow, 14 مهر, 7:30 صبح", now)
        assert text == "Tomorrow, 14 مهر, 7:30 صبح"
        assert epoch == int(datetime(2026, 10, 6, 7, 30).timestamp())

    def test_jalali_digits_with_numeric_separators(self, now):
        _, epoch = dates.parse_due("۱۴۰۴/۰۸/۱۴، ۲۳:۵۹", now)
        assert epoch is not None

    def test_jalali_month_name_with_explicit_year(self, now):
        _, epoch = dates.parse_due("شنبه ۲۱ مهر ۱۴۰۴، ۲۳:۵۹", now)
        from datetime import datetime as dt
        assert dt.fromtimestamp(epoch).strftime("%Y-%m-%d") == "2025-10-13"

    def test_gregorian_passthrough(self, now):
        _, epoch = dates.parse_due("2026-11-20, 23:59", now)
        assert epoch == int(datetime(2026, 11, 20, 23, 59).timestamp())

    @pytest.mark.parametrize("empty", ["", "-", "—", "–", None])
    def test_empty_and_placeholder_cells(self, now, empty):
        text, epoch = dates.parse_due(empty, now)
        assert epoch is None
        assert text in ("", None)

    def test_year_is_inferred_from_today(self, now):
        """A bare day+month must not default to some arbitrary year."""
        _, epoch = dates.parse_due("14 مهر", now)
        assert epoch is not None
        assert date.fromtimestamp(epoch).year in (2025, 2026)

    def test_unparseable_text_yields_no_epoch(self, now):
        """Guessing here would mislabel a deadline, so it must return None."""
        _, epoch = dates.parse_due("س۳ روز دیگر", now)
        assert epoch is None

    def test_afternoon_meridiem_shifts_the_hour(self, now):
        _, pm = dates.parse_due("۱۴۰۴/۰۸/۱۴، ۷:۳۰ عصر", now)
        _, am = dates.parse_due("۱۴۰۴/۰۸/۱۴، ۷:۳۰ صبح", now)
        assert pm - am == 12 * 3600


class TestEpoch:
    def test_jalali_years_do_not_crash(self, now):
        """datetime.timestamp() raises OSError on Windows for Jalali-era years.

        That is why _epoch() does date arithmetic instead. This test exists to
        fail loudly if someone 'simplifies' it back.
        """
        epoch = dates._epoch_jalali(1404, 7, 21, 12, 0)
        assert epoch is not None and epoch > 0

    def test_site_timezone_offset_is_applied(self):
        """Tehran is UTC+03:30, so a 23:59 deadline is not on a round UTC hour."""
        from datetime import datetime as dt

        naive = dates._epoch(2026, 10, 6, 23, 59)
        as_utc = dt.fromtimestamp(naive, tz=timezone.utc)
        assert as_utc.hour == 20 and as_utc.minute == 29, as_utc
        assert int(3.5 * 3600) == dates.SITE_TZ_OFFSET
