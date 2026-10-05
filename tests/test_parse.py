"""Classification and parsing.

classify() has one job and two traps. Both are here as tests because both were
real: an earlier version joined the whole row into one string, tested "submitted"
before "not submitted", and cheerfully reported four undone assignments as
handed in. That is the exact failure this tool exists to catch, so it gets a test
that would fail if anyone reorders the precedence.
"""

from __future__ import annotations

import pytest

from cwtrack import classify as C
from cwtrack import parse


class TestClassify:
    NOW = 1_760_000_000

    @pytest.mark.parametrize("status,grade,due,expected", [
        # the substring trap
        ("Not submitted", "", None, "open"),
        ("Not submitted", "", NOW - 86400, "overdue"),
        ("Not submitted", "", NOW + 86400, "open"),
        ("Submitted", "", NOW - 86400, "submitted"),
        # a grade means graded, even if the deadline has passed
        ("Submitted", "18.00", NOW - 86400, "graded"),
        ("Submitted", "17.5/20", NOW, "graded"),
        # a draft is not a submission, whatever the grade column says
        ("Draft", "12", NOW + 86400, "draft"),
        # an explicit "not submitted" beats a stray number
        ("Not submitted", "18.00", None, "open"),
        ("Submission window closed", "", NOW - 86400, "closed"),
        ("Graded", "", NOW - 86400, "graded"),
    ])
    def test_precedence(self, status, grade, due, expected):
        assert C.classify(status, grade, due, self.NOW) == expected

    @pytest.mark.parametrize("status,expected", [
        ("", "unknown"),
        ("something the site has never said before", "unknown"),
    ])
    def test_unknown_is_the_default_not_optimism(self, status, expected):
        assert C.classify(status, "", None, self.NOW) == expected

    def test_empty_status_falls_back_to_the_deadline(self):
        assert C.classify("", "", self.NOW - 86400, self.NOW) == "overdue"
        assert C.classify("", "", None, self.NOW) == "unknown"

    @pytest.mark.parametrize("status,expected", [
        ("ارسال نشده", "open"),
        ("ارسال‌نشده", "open"),
        ("ارسال شده", "submitted"),
        ("پیش‌نویس", "draft"),
        ("نمره داده شده", "graded"),
        ("مهلت بسته شده", "closed"),
    ])
    def test_persian_status_words(self, status, expected):
        assert C.classify(status, "", None, self.NOW) == expected

    def test_not_submitted_never_reaches_the_submitted_branch(self):
        """The regression guard, stated as a test on its own."""
        assert C.classify("Not submitted", "", self.NOW + 86400, self.NOW) != "submitted"
        assert C.classify("no submission", "", None, self.NOW) != "submitted"

    @pytest.mark.parametrize("text,want", [
        ("18.00", 18.0),
        ("17.5/20", 17.5),
        ("۱۹٫۵", 19.5),
    ])
    def test_grade_score_reads_numbers(self, text, want):
        assert C._grade_score(text) == want

    @pytest.mark.parametrize("text", ["-", "", "N/A", "23:59", "شنبه ۲۱ مهر", None])
    def test_grade_score_rejects_everything_else(self, text):
        assert C._grade_score(text) is None


class TestHeaderMapping:
    def test_reads_the_persian_header(self):
        idx = parse.map_header(["نام", "مهلت تحویل", "وضعیت تحویل", "نمره"])
        assert idx == {"name": 0, "due": 1, "status": 2, "grade": 3}

    def test_reads_an_english_header(self):
        idx = parse.map_header(["Name", "Due date", "Submission status", "Grade"])
        assert idx == {"name": 0, "due": 1, "status": 2, "grade": 3}

    def test_tolerates_reordered_columns(self):
        idx = parse.map_header(["نام", "وضعیت تحویل", "نمره", "مهلت تحویل"])
        assert idx == {"name": 0, "status": 1, "grade": 2, "due": 3}

    def test_partial_header_still_maps_what_it_can(self):
        idx = parse.map_header(["نام", "مهلت تحویل"])
        assert idx["name"] == 0 and idx["due"] == 1
        assert "status" not in idx and "grade" not in idx


class TestParseDump:
    def test_finds_every_assignment_row(self, dump_dir, now):
        rows = parse.parse_dump(dump_dir, now)
        # The Grade book row has no mod/assign link and must not be counted.
        assert len(rows) == 6

    def test_grade_book_row_is_skipped(self, dump_dir, now):
        rows = parse.parse_dump(dump_dir, now)
        assert not any(r["name"] == "Grade book" for r in rows)

    def test_course_id_comes_from_the_filename(self, dump_dir, now):
        rows = parse.parse_dump(dump_dir, now)
        assert {r["course_id"] for r in rows} == {90000}

    def test_parser_reports_the_raw_title(self, dump_dir, now):
        """parse_dump reports what the page said, verbatim, term included.

        Separating 'course - term' into two fields is tracker.store()'s job, not
        the parser's. Asserting the split here would be testing the wrong layer.
        """
        rows = parse.parse_dump(dump_dir, now)
        course = rows[0]["course"]
        assert "نمونه درس آزمایشی" in course
        assert "|" in course

    def test_title_keeps_the_course_id_for_orientation(self, dump_dir, now):
        rows = parse.parse_dump(dump_dir, now)
        assert "000000" in rows[0]["course"]

    def test_buckets_are_assigned_from_the_site_wording(self, dump_dir, now):
        by_name = {r["name"]: r["bucket"] for r in parse.parse_dump(dump_dir, now)}
        assert by_name["تمرین نمونه سه"] == "draft"
        assert by_name["تمرین نمونه پنج"] == "graded"
        assert by_name["پروژه بدون مهلت"] in ("open", "overdue")

    def test_grade_is_captured(self, dump_dir, now):
        rows = {r["name"]: r for r in parse.parse_dump(dump_dir, now)}
        assert rows["تمرین نمونه پنج"]["grade"] == "17.50"

    def test_no_deadline_yields_none_not_zero(self, dump_dir, now):
        rows = {r["name"]: r for r in parse.parse_dump(dump_dir, now)}
        # 0 would be 1970 and would read as "60 years overdue"
        assert rows["پروژه بدون مهلت"]["due"] is None

    def test_every_row_has_a_url(self, dump_dir, now):
        for r in parse.parse_dump(dump_dir, now):
            assert r["url"].startswith("https://cw.sharif.ir/mod/assign/view.php?id=")

    def test_missing_dump_is_a_clear_error(self, tmp_path, now):
        from cwtrack.client import CwError

        with pytest.raises(CwError):
            parse.parse_dump(tmp_path / "nothing", now)

    def test_duplicated_pages_do_not_duplicate_rows(self, dump_dir, now, tmp_path):
        """The overview page and the assign page can both land in the dump."""
        page = next(dump_dir.glob("course_*.html"))
        (dump_dir / (page.stem + "_dup.html")).write_text(
            page.read_text(encoding="utf-8"), encoding="utf-8"
        )
        rows = parse.parse_dump(dump_dir, now)
        cmids = [r["cmid"] for r in rows]
        assert len(cmids) == len(set(cmids))


class TestLocalMatch:
    def test_persian_folding_finds_the_file(self, tmp_path):
        from cwtrack.match import _norm

        assert _norm("تمرین شماره ۳ - تحلیل داده") == _norm("تمرين شماره 3 - تحليل داده")

    def test_english_abbreviations_are_not_claimed_to_match(self, tmp_path):
        """HW4 vs 'Homework 4' shares one token, not two.

        Asserting that they match would be asserting the bug; the threshold of two
        tokens is what keeps a whole course directory from matching everything.
        """
        from cwtrack.match import _norm

        assert _norm("HW4_Oscillator") != _norm("Homework 4 — Oscillator")

    def test_matches_only_open_work(self, tmp_path):
        from cwtrack.match import match_local

        docs = tmp_path / "materials"
        docs.mkdir()
        (docs / "تمرین نمونه دو.pdf").write_bytes(b"%PDF")
        rows = [
            {"name": "تمرین نمونه دو", "course": "نمونه", "course_id": 1, "bucket": "open"},
            {"name": "تمرین نمونه چهار", "course": "نمونه", "course_id": 1, "bucket": "submitted"},
        ]
        found = match_local(rows, docs)
        assert len(found) == 1
        assert "تمرین نمونه دو" in list(found)[0]

    def test_missing_folder_is_not_an_error(self, tmp_path):
        from cwtrack.match import match_local

        assert match_local([], tmp_path / "nope") == {}
