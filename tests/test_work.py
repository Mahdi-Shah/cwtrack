"""Public-interface tests for coursework work that must survive a Codex pause."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from cwtrack import api

ROOT = Path(__file__).resolve().parent.parent


def test_selected_work_without_a_prompt_waits_for_the_assignment_text(tmp_path):
    result = api.work_start(
        {"manual": {"course": "منطق", "title": "تمرین استقرا"}},
        data=tmp_path / "no-cw-store",
        work=tmp_path / "work",
    )

    assert result["status"] == "needs_input"
    assert result["stage"] == "ready_to_start"
    assert "متن کامل تکلیف" in result["open_questions"][0]


def test_quera_assignment_work_uses_opaque_identity_and_resumes_the_same_record(tmp_path):
    assignment = {
        "source": "quera",
        "assignment_ref": {
            "connection_id": "quera-account",
            "class_id": "class-17",
            "assignment_id": "assignment-42",
            "question_id": "question-3",
        },
        "course": "ساختمان داده",
        "term": "ترم پاییز",
        "title": "تمرین گراف",
        "prompt": "کوتاه‌ترین مسیر را تحلیل کنید.",
        "attachments": [],
    }
    work_root = tmp_path / "work"
    first = api.work_start(
        {"received": assignment}, data=tmp_path / "data", work=work_root
    )
    repeated = api.work_start(
        {"received": assignment}, data=tmp_path / "data", work=work_root
    )

    assert first["status"] == "ok"
    assert repeated["status"] == "exists"
    assert repeated["work_id"] == first["work_id"]
    assert repeated["input"]["assignment_ref"] == assignment["assignment_ref"]


def test_related_quera_assignments_keep_independent_work_records(tmp_path):
    base = {
        "source": "quera",
        "assignment_ref": {
            "connection_id": "quera-account",
            "class_id": "class-17",
            "assignment_id": "assignment-42",
        },
        "course": "ساختمان داده",
        "title": "تمرین گراف",
        "prompt": "صورت مشترک",
        "attachments": [],
    }

    first = api.work_start({"received": base}, work=tmp_path / "work")
    second = api.work_start(
        {"received": {
            **base,
            "assignment_ref": {**base["assignment_ref"], "question_id": "q-2"},
            "title": "تمرین گراف - سؤال دوم",
        }},
        work=tmp_path / "work",
    )

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert first["work_id"] != second["work_id"]


def test_missing_prompt_can_be_added_before_work_starts(tmp_path):
    data_dir = tmp_path / "no-cw-store"
    work_dir = tmp_path / "work"
    started = api.work_start(
        {"manual": {"course": "منطق", "title": "تمرین"}},
        data=data_dir,
        work=work_dir,
    )
    received = api.collect_assignment(
        {"manual": {"course": "منطق", "title": "تمرین", "prompt": "اثبات کنید."}}
    )

    synced = api.work_sync(
        started["work_id"],
        received["input"],
        expected_revision=started["revision"],
        data=data_dir,
        work=work_dir,
    )
    current = api.work_get(started["work_id"], data=data_dir, work=work_dir)

    assert synced["status"] == "ok"
    assert synced["needs_reassessment"] is False
    assert current["stage"] == "ready_to_start"
    assert current["open_questions"] == []
    assert current["input"]["prompt"] == "اثبات کنید."


def test_work_list_reads_saved_work_without_starting_or_mutating_work(tmp_path):
    data_dir = tmp_path / "no-cw-store"
    work_dir = tmp_path / "work"
    first = api.work_start(
        {"manual": {"course": "منطق", "title": "اول", "prompt": "الف", "priority": 1}},
        data=data_dir,
        work=work_dir,
    )
    api.work_start(
        {"manual": {"course": "منطق", "title": "دوم", "prompt": "ب", "priority": 3}},
        data=data_dir,
        work=work_dir,
    )

    before = api.work_list(data=data_dir, work=work_dir)

    assert [item["input"]["title"] for item in before] == ["دوم", "اول"]
    assert api.work_list(
        selection=[first["work_id"]], data=data_dir, work=work_dir
    )[0]["work_id"] == first["work_id"]
    assert api.work_get(first["work_id"], data=data_dir, work=work_dir)["revision"] == 1
    assert len(api.work_list(data=data_dir, work=work_dir)) == len(before) == 2


def test_selected_group_keeps_its_members_and_order_after_new_work_is_added(tmp_path):
    data_dir = tmp_path / "no-cw-store"
    work_dir = tmp_path / "work"
    due_soon = {
        "source": "site", "course_id": 1, "course": "منطق", "term": "پاییز",
        "cmid": 101, "title": "نزدیک", "prompt": "الف", "due": 100,
        "attachments": [],
    }
    high_priority = {
        "source": "site", "course_id": 1, "course": "منطق", "term": "پاییز",
        "cmid": 102, "title": "اولویت‌دار", "prompt": "ب", "due": 200,
        "priority": 2, "attachments": [],
    }
    group = api.work_group_start(
        [{"received": due_soon}, {"received": high_priority}],
        data=data_dir,
        work=work_dir,
    )
    updated_group = api.work_group_start(
        [{"received": {**due_soon, "prompt": "نسخهٔ جدید سؤال"}}, {"received": high_priority}],
        data=data_dir,
        work=work_dir,
    )
    later = api.work_start(
        {"manual": {"course": "منطق", "title": "بعدی", "prompt": "ج"}},
        data=data_dir,
        work=work_dir,
    )
    changed_member = updated_group["members"][1]
    current_changed_work = api.work_get(changed_member["work_id"], data=data_dir, work=work_dir)
    api.work_sync(
        changed_member["work_id"],
        {**due_soon, "prompt": "نسخهٔ جدید سؤال"},
        expected_revision=current_changed_work["revision"],
        data=data_dir,
        work=work_dir,
    )

    resumed = api.work_group_get(group["group_id"], data=data_dir, work=work_dir)
    updated_resumed = api.work_group_get(updated_group["group_id"], data=data_dir, work=work_dir)

    assert group["status"] == "ok"
    assert [member["input"]["title"] for member in group["members"]] == ["اولویت‌دار", "نزدیک"]
    assert [member["input"]["title"] for member in resumed["members"]] == ["اولویت‌دار", "نزدیک"]
    assert later["work_id"] not in [member["work_id"] for member in resumed["members"]]
    assert updated_group["members"][1]["input_changed"] is True
    assert updated_resumed["members"][1]["input_changed"] is False


def test_manual_text_attachment_becomes_the_assignment_prompt(tmp_path):
    prompt_file = tmp_path / "assignment.txt"
    prompt_file.write_text("برای هر n، رابطهٔ بازگشتی را با استقرا ثابت کنید.", encoding="utf-8")

    received = api.collect_assignment(
        {
            "manual": {
                "course": "ریاضی گسسته",
                "title": "تمرین استقرا",
                "attachments": [{"path": str(prompt_file), "role": "prompt"}],
            }
        }
    )

    assert received["status"] == "ok"
    assert received["input"]["prompt"] == (
        "برای هر n، رابطهٔ بازگشتی را با استقرا ثابت کنید."
    )
    assert received["input"]["attachments"] == [
        {"name": "assignment.txt", "role": "prompt", "path": str(prompt_file)}
    ]


def test_site_assignment_collects_its_prompt_and_attachment(
    tmp_path, dump_dir, monkeypatch
):
    monkeypatch.delenv("CW_USER", raising=False)
    monkeypatch.delenv("CW_PASS", raising=False)
    data_dir = tmp_path / "cw-data"
    api.ingest(dump_dir, data_dir)
    assignment = api.outstanding(data_dir)[0]
    page = (
        "<html><body><main><h1>تمرین منتخب</h1>"
        "<p>برای تابع مشخص‌شده، الگوریتم بازگشتی را اثبات کنید.</p>"
        "<a href='/pluginfile.php/90000/mod_assign/introattachment/0/task.pdf'>"
        "صورت تکلیف</a><a href='https://example.com/pluginfile.php/1/"
        "mod_assign/introattachment/0/untrusted.pdf'>پیوند بیرونی</a></main></body></html>"
    )

    class SiteAdapter:
        def logged_in(self):
            return True

        def get(self, path, params=None):
            assert path == "/mod/assign/view.php"
            assert str(params["id"]) == str(assignment["cmid"])
            return page

        def get_bytes(self, path, params=None):
            assert path.startswith("/pluginfile.php/")
            return b"%PDF-1.4 sanitized assignment attachment"

    class UnauthenticatedAdapter:
        def logged_in(self):
            return False

    missing_credentials = api.collect_assignment(
        {"site": {"cmid": assignment["cmid"]}},
        data=data_dir,
        home=tmp_path / ".cw",
        client=UnauthenticatedAdapter(),
    )
    assert missing_credentials["status"] == "needs_credentials"

    class ExpiredSessionAdapter:
        def logged_in(self):
            return True

        def get(self, path, params=None):
            return '<form class="login-form"><input name="password"></form>'

    expired = api.collect_assignment(
        {"site": {"cmid": assignment["cmid"]}},
        data=data_dir,
        home=tmp_path / ".cw",
        client=ExpiredSessionAdapter(),
    )
    assert expired["status"] == "authentication_required"

    class ExpiredDuringDownloadAdapter(SiteAdapter):
        def get_bytes(self, path, params=None):
            return b'<form class="login-form"><input name="password"></form>'

    expired_during_download = api.collect_assignment(
        {"site": {"cmid": assignment["cmid"]}},
        data=data_dir,
        home=tmp_path / ".cw",
        client=ExpiredDuringDownloadAdapter(),
    )
    assert expired_during_download["status"] == "authentication_required"

    received = api.collect_assignment(
        {"site": {"cmid": assignment["cmid"]}},
        data=data_dir,
        home=tmp_path / ".cw",
        client=SiteAdapter(),
    )

    assert received["status"] == "ok"
    assert "برای تابع مشخص‌شده" in received["input"]["prompt"]
    assert len(received["input"]["attachments"]) == 1
    attachment = received["input"]["attachments"][0]
    assert attachment["role"] == "prompt"
    assert Path(attachment["path"]).read_bytes().startswith(b"%PDF-1.4")

    started = api.work_start(
        {"received": received["input"]},
        data=data_dir,
        work=tmp_path / "work",
    )

    assert started["status"] == "ok"
    assert started["input"]["source"] == "site"
    assert started["input"]["cmid"] == assignment["cmid"]
    assert Path(started["attachments"][0]["path"]).read_bytes().startswith(b"%PDF-1.4")
    repeated = api.work_start(
        {"received": received["input"]},
        data=data_dir,
        work=tmp_path / "work",
    )
    assert repeated["status"] == "exists"
    assert repeated["work_id"] == started["work_id"]


def test_assignment_file_is_copied_into_saved_work(tmp_path):
    prompt_file = tmp_path / "assignment.pdf"
    contents = b"%PDF-1.4 sanitized assignment bytes"
    prompt_file.write_bytes(contents)

    started = api.work_start(
        {
            "manual": {
                "course": "طراحی",
                "title": "صورت پروژه",
                "attachments": [{"path": str(prompt_file), "role": "prompt"}],
            }
        },
        data=tmp_path / "no-cw-store",
        work=tmp_path / "work",
    )
    resumed = api.work_get(
        started["work_id"], data=tmp_path / "no-cw-store", work=tmp_path / "work"
    )

    assert started["status"] == "needs_input"
    assert resumed["attachments"][0]["name"] == "assignment.pdf"
    saved_file = Path(resumed["attachments"][0]["path"])
    assert saved_file != prompt_file.resolve()
    assert saved_file.read_bytes() == contents


def test_sync_marks_changed_question_for_review_but_not_deadline(tmp_path):
    data_dir = tmp_path / "no-cw-store"
    work_dir = tmp_path / "work"
    old_prompt_file = tmp_path / "old-task.pdf"
    old_prompt_file.write_bytes(b"old assignment file")
    original = {
        "source": "site",
        "course_id": 12,
        "course": "منطق",
        "term": "پاییز",
        "cmid": 345,
        "title": "تمرین",
        "prompt": "بخش الف را حل کنید.",
        "due": "2026-10-20",
        "attachments": [{"path": str(old_prompt_file), "role": "prompt"}],
    }
    started = api.work_start({"received": original}, data=data_dir, work=work_dir)
    saved = api.work_save(
        started["work_id"],
        {
            "stage": "in_progress",
            "sections": [],
            "open_questions": [],
            "requirements": [{
                "id": "part-a",
                "description": "حل بخش الف",
                "deliverable_roles": ["pdf"],
                "verification_method": "بازبینی پاسخ",
            }],
            "checks": [{
                "requirement_id": "part-a",
                "method": "بازبینی پاسخ",
                "result": "pass",
                "evidence": "متن دریافت‌شده بررسی شد.",
                "input_fingerprint": started["input_fingerprint"],
                "answer_fingerprint": started["answer_fingerprint"],
            }],
        },
        expected_revision=started["revision"],
        data=data_dir,
        work=work_dir,
    )

    deadline_update = api.work_sync(
        started["work_id"],
        {**original, "due": "2026-10-25"},
        expected_revision=saved["revision"],
        data=data_dir,
        work=work_dir,
    )
    assert deadline_update["status"] == "ok"
    assert deadline_update["needs_reassessment"] is False
    assert api.work_get(started["work_id"], data=data_dir, work=work_dir)["stage"] == "in_progress"
    assert "نیازمند بازبینی است" not in (tmp_path / "index.html").read_text(encoding="utf-8")

    new_prompt_file = tmp_path / "new-task.pdf"
    new_prompt_file.write_bytes(b"new assignment file")
    content_update = api.work_sync(
        started["work_id"],
        {
            **original,
            "due": "2026-10-25",
            "prompt": "بخش الف و ب را حل کنید.",
            "attachments": [{"path": str(new_prompt_file), "role": "prompt"}],
        },
        expected_revision=deadline_update["revision"],
        data=data_dir,
        work=work_dir,
    )
    current = api.work_get(started["work_id"], data=data_dir, work=work_dir)
    assert content_update["status"] == "ok"
    assert content_update["needs_reassessment"] is True
    assert current["stage"] == "needs_completion"
    assert current["input"]["prompt"] == "بخش الف و ب را حل کنید."
    assert current["checks"][0]["input_fingerprint"] != current["input_fingerprint"]
    assert Path(current["attachments"][0]["path"]).read_bytes() == b"new assignment file"
    assert Path(api.work_get(
        started["work_id"], revision=1, data=data_dir, work=work_dir
    )["attachments"][0]["path"]).read_bytes() == b"old assignment file"
    assert "نیازمند بازبینی است" in (tmp_path / "index.html").read_text(encoding="utf-8")


def test_finish_requires_real_files_and_current_check_evidence(tmp_path):
    data_dir = tmp_path / "no-cw-store"
    work_dir = tmp_path / "work"
    started = api.work_start(
        {"manual": {"course": "منطق", "title": "تمرین", "prompt": "اثبات کنید."}},
        data=data_dir,
        work=work_dir,
    )
    requirements = [{
        "id": "proof",
        "description": "اثبات کامل و خوانا",
        "deliverable_roles": ["pdf", "editable"],
        "verification_method": "بازبینی استدلال و رندر سند",
    }]
    draft = api.work_save(
        started["work_id"],
        {
            "stage": "under_verification",
            "sections": [{"id": "proof", "title": "اثبات", "content": "پایه و گام."}],
            "requirements": requirements,
            "checks": [],
            "open_questions": [],
        },
        expected_revision=started["revision"],
        data=data_dir,
        work=work_dir,
    )
    pdf_contents = b"%PDF-1.4 solution"
    pdf = tmp_path / "solution.pdf"
    pdf.write_bytes(pdf_contents)
    incomplete = api.work_finish(
        started["work_id"],
        {"files": [{"path": str(pdf), "role": "pdf"}], "note": "پاسخ آماده شد."},
        expected_revision=draft["revision"],
        data=data_dir,
        work=work_dir,
    )

    assert incomplete["status"] == "needs_completion"
    assert "editable" in " ".join(incomplete["missing"])
    assert "بررسی" in " ".join(incomplete["missing"])

    current = api.work_get(started["work_id"], data=data_dir, work=work_dir)
    editable = tmp_path / "solution.md"
    editable.write_text("اثبات کامل و خوانا", encoding="utf-8")
    checked = api.work_save(
        started["work_id"],
        {
            "stage": "under_verification",
            "sections": current["sections"],
            "requirements": requirements,
            "checks": [{
                "requirement_id": "proof",
                "method": "بازبینی استدلال و رندر سند",
                "result": "pass",
                "evidence": "استدلال و PDF رندرشده بررسی شد.",
                "input_fingerprint": current["input_fingerprint"],
                "answer_fingerprint": current["answer_fingerprint"],
                "deliverables": [],
            }],
            "open_questions": [],
        },
        expected_revision=current["revision"],
        data=data_dir,
        work=work_dir,
    )
    unverified_files = api.work_finish(
        started["work_id"],
        {
            "files": [
                {"path": str(pdf), "role": "pdf"},
                {"path": str(editable), "role": "editable"},
            ],
            "note": "فایل قابل ویرایش و PDF آماده‌اند.",
        },
        expected_revision=checked["revision"],
        data=data_dir,
        work=work_dir,
    )
    assert unverified_files["status"] == "needs_completion"
    assert "فایل" in " ".join(unverified_files["missing"])

    current = api.work_get(started["work_id"], data=data_dir, work=work_dir)
    checked_with_files = api.work_save(
        started["work_id"],
        {
            "stage": "under_verification",
            "sections": current["sections"],
            "requirements": requirements,
            "checks": [{
                **current["checks"][0],
                "deliverables": [
                    {"role": "pdf", "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest()},
                    {
                        "role": "editable",
                        "sha256": hashlib.sha256(editable.read_bytes()).hexdigest(),
                    },
                ],
            }],
            "open_questions": [],
        },
        expected_revision=current["revision"],
        data=data_dir,
        work=work_dir,
    )
    notes = tmp_path / "notes.txt"
    notes.write_text("extra output", encoding="utf-8")
    unverified_extra = api.work_finish(
        started["work_id"],
        {
            "files": [
                {"path": str(pdf), "role": "pdf"},
                {"path": str(editable), "role": "editable"},
                {"path": str(notes), "role": "notes"},
            ],
            "note": "فایل‌های تحویل آماده‌اند.",
        },
        expected_revision=checked_with_files["revision"],
        data=data_dir,
        work=work_dir,
    )
    assert unverified_extra["status"] == "needs_completion"
    assert "notes.txt" in " ".join(unverified_extra["missing"])
    current = api.work_get(started["work_id"], data=data_dir, work=work_dir)
    pdf.write_bytes(b"%PDF-1.4 changed after checking")
    changed_after_check = api.work_finish(
        started["work_id"],
        {
            "files": [
                {"path": str(pdf), "role": "pdf"},
                {"path": str(editable), "role": "editable"},
            ],
            "note": "فایل قابل ویرایش و PDF آماده‌اند.",
        },
        expected_revision=current["revision"],
        data=data_dir,
        work=work_dir,
    )
    assert changed_after_check["status"] == "needs_completion"
    pdf.write_bytes(pdf_contents)
    current = api.work_get(started["work_id"], data=data_dir, work=work_dir)
    ready = api.work_finish(
        started["work_id"],
        {
            "files": [
                {"path": str(pdf), "role": "pdf"},
                {"path": str(editable), "role": "editable"},
            ],
            "note": "فایل قابل ویرایش و PDF آماده‌اند.",
        },
        expected_revision=current["revision"],
        data=data_dir,
        work=work_dir,
    )

    assert ready["status"] == "ok"
    assert ready["stage"] == "ready_for_student_review"
    resumed = api.work_get(started["work_id"], data=data_dir, work=work_dir)
    assert {file["role"] for file in resumed["delivery"]["files"]} == {"pdf", "editable"}
    assert all(Path(file["path"]).is_file() for file in resumed["delivery"]["files"])
    dashboard = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "solution.pdf" in dashboard
    assert "solution.md" in dashboard
    assert "آمادهٔ بررسی دانشجو" in dashboard


def test_manual_work_can_be_saved_and_read_again(tmp_path):
    work_dir = tmp_path / "work"
    data_dir = tmp_path / "no-cw-store"
    started = api.work_start(
        {
            "manual": {
                "course": "ریاضی گسسته",
                "title": "اثبات رابطهٔ بازگشتی",
                "prompt": "با استقرا درستی رابطه را ثابت کنید.",
            }
        },
        data=data_dir,
        work=work_dir,
    )

    assert started["status"] == "ok"
    assert started["stage"] == "ready_to_start"

    saved = api.work_save(
        started["work_id"],
        {
            "stage": "in_progress",
            "sections": [
                {"id": "proof", "title": "اثبات", "content": "پایه و گام استقرا."}
            ],
            "open_questions": ["آیا روش خاصی مدنظر استاد است؟"],
        },
        expected_revision=started["revision"],
        data=data_dir,
        work=work_dir,
    )

    assert saved["status"] == "ok"
    assert saved["revision"] == 2

    source_root = str(ROOT / "src")
    read_saved_work = (
        "import json, sys; sys.path.insert(0, {!r}); "
        "from cwtrack import api; "
        "print(json.dumps(api.work_get(sys.argv[1], data=sys.argv[3], work=sys.argv[2]), "
        "ensure_ascii=True))"
    ).format(source_root)
    fresh_process = subprocess.run(
        [
            sys.executable, "-c", read_saved_work,
            started["work_id"], str(work_dir), str(data_dir),
        ],
        check=False,
        capture_output=True,
        encoding="utf-8",
    )
    assert fresh_process.returncode == 0, fresh_process.stderr
    resumed = json.loads(fresh_process.stdout)

    assert resumed["stage"] == "in_progress"
    assert resumed["revision"] == 2
    assert resumed["input"]["prompt"] == "با استقرا درستی رابطه را ثابت کنید."
    assert resumed["sections"] == [
        {"id": "proof", "title": "اثبات", "content": "پایه و گام استقرا."}
    ]
    assert resumed["open_questions"] == ["آیا روش خاصی مدنظر استاد است؟"]


def test_dashboard_shows_manually_selected_work_without_a_course_store(tmp_path):
    work_dir = tmp_path / "work"
    started = api.work_start(
        {"manual": {"course": "منطق", "title": "تمرین استقرا", "prompt": "اثبات کنید."}},
        data=tmp_path / "no-cw-store",
        work=work_dir,
    )
    api.work_save(
        started["work_id"],
        {"stage": "in_progress", "sections": [], "open_questions": []},
        expected_revision=started["revision"],
        data=tmp_path / "no-cw-store",
        work=work_dir,
    )

    refreshed_page = tmp_path / "index.html"
    assert refreshed_page.is_file()
    assert "تمرین استقرا" in refreshed_page.read_text(encoding="utf-8")

    page_path = api.build_dashboard(
        tmp_path / "no-cw-store", tmp_path / "dashboard.html", work=work_dir
    )
    page = page_path.read_text(encoding="utf-8")

    assert "تمرین استقرا" in page
    assert "در حال انجام" in page
    assert "اطلاعات درس از سامانه در دسترس نیست" in page
