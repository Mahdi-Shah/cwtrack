"""The store, the bridge, and the CLI surface.

These are the parts a user touches, so they get tested end to end on a temporary
directory. The point of the store tests in particular is that nothing here needs
a network or an account: everything below the `fetch` command reads disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cwtrack import brief as B
from cwtrack import tracker
from cwtrack.client import CwError


@pytest.fixture
def store(tmp_path: Path, dump_dir, now):
    """A populated store built from the sanitised fixture."""
    from cwtrack import parse

    rows = [r.__dict__ if hasattr(r, "__dict__") else r
            for r in parse.parse_dump(dump_dir, now)]
    data = tmp_path / "cw-data"
    tracker.store(data, {"fullname": "نمونه", "username": "00000000", "userid": "1"}, rows)
    return data


class TestTrackerStore:
    def test_writes_the_expected_layout(self, store):
        assert (store / "assignments.json").is_file()
        assert (store / "user.json").is_file()
        cid = list((store / "courses").iterdir())[0]
        assert (cid / "course.json").is_file()
        assert (cid / "assignments.json").is_file()
        assert (cid / "materials").is_dir()
        assert (cid / "notes.md").is_file()

    def test_round_trips_through_load(self, store):
        user, items = tracker.load(store)
        assert user["username"] == "00000000"
        assert len(items) == 6
        assert all(i.course == "نمونه درس آزمایشی - 000000" for i in items)

    def test_term_is_split_out_of_the_course_name(self, store):
        _, items = tracker.load(store)
        assert items[0].term, "the term must survive storing as its own field"
        assert "|" not in items[0].course

    def test_tolerates_a_utf8_bom(self, store):
        """PowerShell writes one, and stock json.loads refuses the file."""
        user_p = store / "user.json"
        user_p.write_text(user_p.read_text(encoding="utf-8"), encoding="utf-8-sig")
        user, _ = tracker.load(store)
        assert user["username"] == "00000000"

    def test_gaps_separates_urgent_from_soon(self, store, now_epoch):
        user, items = tracker.load(store)
        gap = tracker.gaps(items, now_epoch)
        assert gap["counts"]["total"] == 6
        assert set(gap["counts"]) == {"total", "open", "urgent", "done"}
        # urgent and soon must not overlap
        urgent = {a.name for a in gap["urgent"]}
        soon = {a.name for a in gap["soon"]}
        assert not (urgent & soon)

    def test_open_buckets_are_exactly_the_incomplete_ones(self, store, now_epoch):
        user, items = tracker.load(store)
        gap = tracker.gaps(items, now_epoch)
        open_names = {a.name for a in gap["urgent"] + gap["soon"] + gap["unscheduled"]}
        assert "تمرین نمونه چهار" not in open_names   # submitted
        assert "تمرین نمونه پنج" not in open_names     # graded
        assert "پروژه بدون مهلت" in open_names

    def test_materials_are_indexed_from_disk(self, store):
        cid = next((store / "courses").iterdir())
        (cid / "materials" / "lecture.pdf").write_bytes(b"%PDF-1.4")
        mats = tracker.scan_materials(cid / "materials")
        assert len(mats) == 1
        assert mats[0].kind == "PDF"
        assert mats[0].bytes > 0

    def test_json_files_in_materials_are_not_counted_as_files(self, store):
        cid = next((store / "courses").iterdir())
        mats = tracker.scan_materials(cid / "materials")
        assert not any(m.name.endswith(".json") for m in mats)


class TestBrief:
    def test_slugify_strips_path_illegal_characters(self):
        assert "/" not in B.slugify("الف/ب")
        assert ":" not in B.slugify("ساعت 12:30")

    def test_slugify_reserves_windows_device_names(self):
        assert B.slugify("CON") != "CON"
        assert B.slugify("com1.txt").startswith("_")

    def test_slugify_never_ends_with_a_dot(self):
        assert not B.slugify("نام.").endswith(".")

    def test_creates_a_folder_with_a_brief(self, store, now_epoch, tmp_path):
        user, items = tracker.load(store)
        target = items[0]
        folder, written = B.build_workfolder(
            target.__dict__, {"title": target.course, "term": target.term},
            store, tmp_path / "work", now_epoch,
        )
        assert (folder / "brief.md").is_file()
        assert (folder / "HANDOFF.md").is_file()
        assert (folder / "source").is_dir()
        assert written

    def test_brief_records_what_the_site_knows(self, store, now_epoch, tmp_path):
        user, items = tracker.load(store)
        target = items[0]
        folder, _ = B.build_workfolder(
            target.__dict__, {"title": target.course, "term": target.term},
            store, tmp_path / "work", now_epoch,
        )
        text = (folder / "brief.md").read_text(encoding="utf-8")
        assert target.name in text
        assert target.url in text
        assert str(target.cmid) in text

    def test_brief_admits_it_does_not_have_the_assignment_text(self, store, now_epoch, tmp_path):
        """The one thing the site does not give us. Claiming otherwise is how a
        brief ends up confidently solving the wrong question."""
        user, items = tracker.load(store)
        target = items[0]
        folder, _ = B.build_workfolder(
            target.__dict__, {"title": target.course, "term": target.term},
            store, tmp_path / "work", now_epoch,
        )
        text = (folder / "brief.md").read_text(encoding="utf-8")
        assert "نیازمند متن تکلیف" in text

    def test_refuses_to_clobber_existing_work(self, store, now_epoch, tmp_path):
        user, items = tracker.load(store)
        target = items[0]
        args = (target.__dict__, {"title": target.course, "term": target.term},
                store, tmp_path / "work", now_epoch)
        folder, first = B.build_workfolder(*args)
        (folder / "brief.md").write_text("my own notes", encoding="utf-8")

        _, second = B.build_workfolder(*args)
        assert first and not second, "a second call must not report writing anything"
        assert (folder / "brief.md").read_text(encoding="utf-8") == "my own notes"

    def test_force_overwrites(self, store, now_epoch, tmp_path):
        user, items = tracker.load(store)
        target = items[0]
        args = (target.__dict__, {"title": target.course, "term": target.term},
                store, tmp_path / "work", now_epoch)
        folder, _ = B.build_workfolder(*args)
        (folder / "brief.md").write_text("scratch", encoding="utf-8")
        B.build_workfolder(*args, overwrite=True)
        assert (folder / "brief.md").read_text(encoding="utf-8") != "scratch"

    def test_open_items_omits_finished_work(self, store, now_epoch):
        user, items = tracker.load(store)
        names = {a.name for a in B.open_items(items, now_epoch)}
        assert "تمرین نمونه چهار" not in names
        assert "تمرین نمونه پنج" not in names

    def test_open_items_are_soonest_first(self, store, now_epoch):
        user, items = tracker.load(store)
        with_due = [a for a in B.open_items(items, now_epoch) if a.due]
        assert with_due == sorted(with_due, key=lambda a: a.due)


class TestCli:
    """main() raises CwError; turning that into an exit code is __main__'s job.

    Error cases here therefore assert the exception, not a return code. Asserting
    the return code would be testing the four-line wrapper instead.
    """

    def _run(self, argv):
        from cwtrack.cli import main

        return main(argv)

    def test_gaps_runs_offline(self, store, capsys):
        assert self._run(["gaps", "--data", str(store)]) == 0
        assert "کل 6" in capsys.readouterr().out

    def test_missing_store_fails_loudly_not_with_zeroes(self, tmp_path, capsys):
        """'You have no assignments' and 'I could not find your data' are
        opposite claims, and printing zeros for the second one is how a real
        deadline gets missed."""
        with pytest.raises(CwError, match="پیدا نشد"):
            self._run(["gaps", "--data", str(tmp_path / "absent")])

    def test_ui_writes_a_self_contained_page(self, store, capsys):
        assert self._run(["ui", "--data", str(store)]) == 0
        html = (store / "index.html").read_text(encoding="utf-8")
        assert html.startswith("<!doctype html>")
        assert "font/ttf;base64" in html, "fonts must be inlined, not linked"
        assert "<script" in html

    def test_ui_is_valid_utf8_and_rtl(self, store, capsys):
        self._run(["ui", "--data", str(store)])
        html = (store / "index.html").read_text(encoding="utf-8")
        assert "dir='rtl'" in html or 'dir="rtl"' in html
        # A named font that is not embedded would silently fall back to Tahoma,
        # which is the bug that made the first dashboard look wrong.
        assert "Vazirmatn" in html or "Estedad" in html

    def test_report_writes_markdown(self, store, tmp_path, capsys):
        out_p = tmp_path / "r.md"
        assert self._run(["report", "--data", str(store), "-o", str(out_p)]) == 0
        assert "وضعیت تکالیف" in out_p.read_text(encoding="utf-8")

    @pytest.mark.parametrize("argv", [
        ["gaps"], ["open"], ["open", "--json"], ["report"], ["gaps", "--json"],
    ])
    def test_out_flag_honoured_by_every_text_command(self, store, tmp_path, argv, capsys):
        """Persian on a stock Windows console is cp1252 and comes out mojibake.

        So "-o and read the file" is the documented workaround. If -o only worked
        for `report` the advice would be useless for `gaps`, which is the command
        people actually run.
        """
        out_p = tmp_path / "out.txt"
        assert self._run(argv + ["--data", str(store), "-o", str(out_p)]) == 0
        body = out_p.read_text(encoding="utf-8")
        assert body.strip(), argv
        capsys.readouterr()

    def test_open_out_and_stdout_agree(self, store, tmp_path, capsys):
        out_p = tmp_path / "out.txt"
        self._run(["open", "--data", str(store), "-o", str(out_p)])
        from_file = out_p.read_text(encoding="utf-8").strip()
        capsys.readouterr()
        self._run(["open", "--data", str(store)])
        assert capsys.readouterr().out.strip() == from_file

    def test_material_out_file_is_utf8(self, store, tmp_path, capsys):
        out_p = tmp_path / "m.txt"
        assert self._run(
            ["material", "--data", str(store), "--course", "90000", "-o", str(out_p)]
        ) == 0
        text = out_p.read_text(encoding="utf-8")
        assert "منابع این درس را اینجا بگذارید" in text
        assert str((store / "courses" / "90000" / "materials").resolve()) in text

    def test_material_empty_folder_says_so_rather_than_going_blank(self, store, tmp_path):
        out_p = tmp_path / "m.txt"
        self._run(["material", "--data", str(store), "--course", "90000", "-o", str(out_p)])
        assert "(خالی)" in out_p.read_text(encoding="utf-8")

    def test_out_creates_missing_parent_directories(self, store, tmp_path, capsys):
        out_p = tmp_path / "deep" / "deeper" / "r.md"
        assert self._run(["report", "--data", str(store), "-o", str(out_p)]) == 0
        assert out_p.is_file()

    def test_gaps_says_so_when_nothing_is_open(self, store, tmp_path, capsys, monkeypatch):
        """Zero open items is a claim, and it should read as one."""
        import json as _json

        p = store / "assignments.json"
        rows = _json.loads(p.read_text(encoding="utf-8-sig"))
        for r in rows:
            r["bucket"] = "graded"
        p.write_text(_json.dumps(rows, ensure_ascii=False), encoding="utf-8")

        out_p = tmp_path / "g.txt"
        assert self._run(["gaps", "--data", str(store), "-o", str(out_p)]) == 0
        assert "مورد بازی ثبت نشده است" in out_p.read_text(encoding="utf-8")

    def test_brief_without_cmid_lists_choices_instead_of_guessing(self, store, capsys):
        assert self._run(["brief", "--data", str(store)]) == 0
        out = capsys.readouterr().out
        assert "کدام را بریف کنم" in out
        assert "cwtrack open" in out

    def test_brief_writes_for_a_named_assignment(self, store, tmp_path, capsys):
        _, items = tracker.load(store)
        assert self._run([
            "brief", "--data", str(store), "--cmid", str(items[0].cmid),
            "--work", str(tmp_path / "work"),
        ]) == 0
        assert list((tmp_path / "work").rglob("brief.md"))

    def test_unknown_cmid_is_a_clear_error(self, store, capsys):
        with pytest.raises(CwError, match="cmid"):
            self._run(["brief", "--data", str(store), "--cmid", "12345"])

    def test_material_creates_and_lists_the_folder(self, store, capsys):
        assert self._run(["material", "--data", str(store), "--course", "90000"]) == 0
        assert "materials" in capsys.readouterr().out

    def test_open_json_is_machine_readable(self, store, capsys):
        assert self._run(["open", "--data", str(store), "--json"]) == 0
        assert isinstance(json.loads(capsys.readouterr().out), list)
