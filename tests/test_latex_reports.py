"""Template cache, build isolation, and durable report verification contracts."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from cwtrack import api, latex_reports


def _zip(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return stream.getvalue()


@pytest.fixture
def templates(monkeypatch):
    exercise = _zip({
        "main.tex": r"""\documentclass{exam}
\usepackage{xepersian}
\settextfont{XB Niloofar}
\newcommand{\class}{sample course}
\newcommand{\term}{sample term}
\newcommand{\college}{sample college}
\newcommand{\prof}{sample professor}
\begin{document}
\include{info}
\include{cover-page}
• پرسش نمونه
SHOULD NOT BE DELIVERED
\end{document}
""",
        "info.tex": "SAMPLE IDENTITY", "cover-page.tex": r"\ThesisTitle",
        "images/logo.png": b"test asset",
    })
    report = _zip({
        "Seminar.tex": r"\documentclass{article}\begin{document}\include{chapters/context}\end{document}",
        "styles/common.tex": r"\settextfont[Scale=1.166666666666666]{XBNiloofar}\setdigitfont{Yas}",
        "front/template/title.tex": r"\CourseReportTitle",
        "chapters/context.tex": "SAMPLE REPORT",
        "styles/fonts/XB Niloofar.ttf": b"test font",
        "styles/fonts/XB NiloofarBd.ttf": b"test bold font",
    })
    payloads = {}
    for template_id, spec in list(latex_reports.TEMPLATES.items()):
        payload = report if template_id == "sharif-project-report" else exercise
        updated = {**spec, "sha256": hashlib.sha256(payload).hexdigest()}
        monkeypatch.setitem(latex_reports.TEMPLATES, template_id, updated)
        payloads[latex_reports._source_url(updated)] = payload
    font_zip = _zip({"Niloofar/XB Niloofar.ttf": b"font", "Niloofar/XB NiloofarBd.ttf": b"bold",
                     "Niloofar/OFL.txt": "test license"})
    font_spec = {"source_url": "https://example.invalid/fonts.zip", "sha256": hashlib.sha256(font_zip).hexdigest()}
    monkeypatch.setattr(latex_reports, "FONT_SOURCE", font_spec)
    payloads[font_spec["source_url"]] = font_zip
    calls = []

    def download(url):
        calls.append(url)
        return payloads[url]

    monkeypatch.setattr(latex_reports, "_download", download)
    return calls


@pytest.fixture
def compiler(monkeypatch):
    """Stand in for the external tool, not for the report/work modules."""
    monkeypatch.setattr(latex_reports.shutil, "which", lambda _: "xelatex")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if "--version" in command:
            return SimpleNamespace(stdout=b"XeTeX test engine\n", returncode=0)
        output = next(arg.split("=", 1)[1] for arg in command if arg.startswith("-output-directory="))
        compiled = Path(output)
        (compiled / "main.pdf").write_bytes(b"%PDF-1.7\ntest output\n")
        (compiled / "main.aux").write_text("", encoding="utf-8")
        return SimpleNamespace(stdout=b"test compiler output", returncode=0)

    monkeypatch.setattr(latex_reports.subprocess, "run", run)
    return calls


def _start(tmp_path):
    return api.work_start({"manual": {"title": "گزارش آزمایشی", "prompt": "پاسخ دهید"}},
                          data=tmp_path / "data", work=tmp_path / "work")


def _prepare(tmp_path, current, template="sharif-exercise", **kwargs):
    return api.report_prepare(
        current["work_id"], template, {"title": "گزارش آزمایشی", **kwargs}, "متناسب با صورت تکلیف",
        expected_revision=current["revision"], data=tmp_path / "data", work=tmp_path / "work",
    )


def _get(tmp_path, work_id, **kwargs):
    return api.work_get(work_id, data=tmp_path / "data", work=tmp_path / "work", **kwargs)


def _build(tmp_path, prepared):
    Path(prepared["content_path"]).write_text(r"\section*{پاسخ} پاسخ محاسبه شده", encoding="utf-8")
    return api.report_build(prepared["work_id"], expected_revision=prepared["revision"],
                            data=tmp_path / "data", work=tmp_path / "work")


def test_catalogue_is_read_only_and_does_not_download(tmp_path, templates, capsys):
    result = api.report_templates(data=tmp_path / "absent" / "data")
    assert result["status"] == "ok"
    assert {row["id"] for row in result["templates"]} == set(latex_reports.TEMPLATES)
    assert not (tmp_path / "absent").exists()
    assert templates == []
    assert capsys.readouterr().out == ""


def test_template_cache_is_pinned_and_reused_offline(tmp_path, templates, monkeypatch):
    first = _prepare(tmp_path, _start(tmp_path))
    assert first["status"] == "ok"
    assert len(templates) == 2  # Exercise source and the pinned font source.
    monkeypatch.setattr(latex_reports, "_download", lambda _: pytest.fail("unexpected download"))
    second = _prepare(tmp_path, first)
    assert second["status"] == "ok"
    assert first["project"] != second["project"]
    assert Path(first["content_path"]).exists()
    source = (Path(first["project"]) / "main.tex").read_text(encoding="utf-8")
    assert "SHOULD NOT BE DELIVERED" not in source
    assert "sample course" not in source
    assert (Path(first["project"]) / "fonts/XB Niloofar.ttf").is_file()


def test_changed_upstream_is_not_silently_adopted(tmp_path, templates, monkeypatch):
    monkeypatch.setattr(latex_reports, "_download", lambda _: _zip({"main.tex": "changed"}))
    started = _start(tmp_path)
    assert _prepare(tmp_path, started)["status"] == "needs_completion"
    current = _get(tmp_path, started["work_id"])
    assert current["revision"] > started["revision"]
    assert current["stage"] == "needs_completion"
    assert current["report"]["status"] == "failed"


@pytest.mark.parametrize("name", ["../escape.tex", "/escape.tex", "C:/escape.tex", "a\\escape.tex", "a/NUL.tex", "a/b. /x.tex"])
def test_archive_paths_cannot_escape_or_alias_on_windows(name):
    payload = _zip({name: "bad"})
    if "\\" in name:
        # ZipInfo normalizes the host separator when writing on Windows.
        payload = payload.replace(name.replace("\\", "/").encode(), name.encode())
    with pytest.raises(ValueError):
        latex_reports._archive_files(payload)


def test_metadata_is_tex_escaped_and_does_not_execute_commands(tmp_path, templates):
    prepared = _prepare(tmp_path, _start(tmp_path), "sharif-exercise-cover",
                        authors=[r"A & B \input{secret}"])
    assert prepared["status"] == "ok"
    info = (Path(prepared["project"]) / "info.tex").read_text(encoding="utf-8")
    assert r"A \& B \textbackslash{}input\{secret\}" in info
    assert "SAMPLE IDENTITY" not in info


def test_build_freezes_inputs_and_keeps_full_source_archive(tmp_path, templates, compiler):
    prepared = _prepare(tmp_path, _start(tmp_path))
    built = _build(tmp_path, prepared)
    assert built["status"] == "built"
    assert built["stage"] == "under_verification"
    assert all("-no-shell-escape" in call for call in compiler if "--version" not in call)
    source = next(Path(item["path"]) for item in built["files"] if item["role"] == "latex_source")
    original = source.read_bytes()
    with zipfile.ZipFile(source) as bundle:
        assert {"content.tex", "main.tex", "images/logo.png", "fonts/XB Niloofar.ttf", "report.json", "BUILD.md"} <= set(bundle.namelist())
        assert bundle.read("content.tex").decode() == Path(prepared["content_path"]).read_text(encoding="utf-8")
    Path(prepared["content_path"]).write_text("changed later", encoding="utf-8")
    assert source.read_bytes() == original
    current = _get(tmp_path, prepared["work_id"])
    assert current["report"]["status"] == "built"
    assert current["report_basis_digest"] == built["report_basis_digest"]
    assert not Path(current["report"]["project"]).is_absolute()


def test_build_failure_is_checkpointed_and_cannot_be_finished(tmp_path, templates, monkeypatch):
    prepared = _prepare(tmp_path, _start(tmp_path))
    monkeypatch.setattr(latex_reports.shutil, "which", lambda _: None)
    built = _build(tmp_path, prepared)
    assert built["status"] == "needs_completion"
    current = _get(tmp_path, prepared["work_id"])
    assert current["stage"] == "needs_completion"
    assert current["report"]["status"] == "failed"
    assert current["report"]["message"]
    assert Path(built["files"][0]["path"]).is_file()
    finished = api.work_finish(prepared["work_id"], {"files": built["files"], "note": "ناموفق"},
                               expected_revision=current["revision"], data=tmp_path / "data", work=tmp_path / "work")
    assert finished["status"] == "needs_completion"


def test_empty_answer_failure_is_saved_instead_of_marking_ready(tmp_path, templates):
    prepared = _prepare(tmp_path, _start(tmp_path))
    failed = api.report_build(prepared["work_id"], expected_revision=prepared["revision"],
                             data=tmp_path / "data", work=tmp_path / "work")
    assert failed["status"] == "needs_completion"
    assert _get(tmp_path, prepared["work_id"])["report"]["status"] == "failed"


def _verify(tmp_path, built):
    current = _get(tmp_path, built["work_id"])
    required = {"id": "report", "description": "فایل‌ها و نمایش سند", "verification_method": "render-and-source-review",
                "deliverable_roles": ["pdf", "latex_source"]}
    check = {"requirement_id": "report", "method": required["verification_method"], "result": "pass",
             "evidence": "Test evidence for a fake compiler; not a real PDF layout claim.",
             "input_fingerprint": current["input_fingerprint"], "answer_fingerprint": current["answer_fingerprint"],
             "report_basis_digest": current["report_basis_digest"],
             "deliverables": [{"role": item["role"], "sha256": hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest()}
                              for item in built["files"]]}
    saved = api.work_save(current["work_id"], {"stage": "under_verification", "sections": current["sections"],
                          "open_questions": [], "requirements": [required], "checks": [check]},
                          expected_revision=current["revision"], data=tmp_path / "data", work=tmp_path / "work")
    assert saved["status"] == "ok"
    return saved


def test_pdf_and_source_can_finish_only_with_current_report_evidence(tmp_path, templates, compiler):
    prepared = _prepare(tmp_path, _start(tmp_path))
    built = _build(tmp_path, prepared)
    verified = _verify(tmp_path, built)
    finished = api.work_finish(prepared["work_id"], {"files": built["files"], "note": "بررسی شد"},
                               expected_revision=verified["revision"], data=tmp_path / "data", work=tmp_path / "work")
    assert finished["status"] == "ok"
    assert {item["role"] for item in finished["files"]} == {"pdf", "latex_source"}
    old_revision = finished["revision"]
    old = json.dumps(_get(tmp_path, prepared["work_id"], revision=old_revision), sort_keys=True)
    alternate = _prepare(tmp_path, {**prepared, "revision": old_revision}, "sharif-exercise-cover")
    assert alternate["status"] == "ok"
    stale = api.work_finish(prepared["work_id"], {"files": built["files"], "note": "قدیمی"},
                            expected_revision=alternate["revision"], data=tmp_path / "data", work=tmp_path / "work")
    assert stale["status"] == "needs_completion"
    assert json.dumps(_get(tmp_path, prepared["work_id"], revision=old_revision), sort_keys=True) == old
    assert all(Path(item["path"]).is_file() for item in finished["files"])


def test_prepare_conflict_does_not_download(tmp_path, templates):
    started = _start(tmp_path)
    result = api.report_prepare(started["work_id"], "sharif-exercise", {"title": "گزارش"}, "دلیل",
                                expected_revision=99, data=tmp_path / "data", work=tmp_path / "work")
    assert result["status"] == "conflict"
    assert templates == []


def test_timeout_keeps_sources_and_error(tmp_path, templates, monkeypatch):
    prepared = _prepare(tmp_path, _start(tmp_path))
    monkeypatch.setattr(latex_reports.shutil, "which", lambda _: "xelatex")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1)

    monkeypatch.setattr(latex_reports.subprocess, "run", timeout)
    failed = _build(tmp_path, prepared)
    assert failed["status"] == "needs_completion"
    assert Path(failed["files"][0]["path"]).is_file()
    assert _get(tmp_path, prepared["work_id"])["stage"] == "needs_completion"


def test_changed_answer_requires_a_new_pdf_even_with_new_check_records(tmp_path, templates, compiler):
    prepared = _prepare(tmp_path, _start(tmp_path))
    built = _build(tmp_path, prepared)
    changed = api.work_save(built["work_id"], {
        "stage": "in_progress", "sections": [{"id": "answer", "title": "پاسخ", "content": "پاسخ اصلاح شده"}],
        "open_questions": [],
    }, expected_revision=built["revision"], data=tmp_path / "data", work=tmp_path / "work")
    assert changed["status"] == "ok"
    verified = _verify(tmp_path, built)
    result = api.work_finish(built["work_id"], {"files": built["files"], "note": "بررسی تازه روی فایل قبلی کافی نیست"},
                             expected_revision=verified["revision"], data=tmp_path / "data", work=tmp_path / "work")
    assert result["status"] == "needs_completion"


def test_corrupt_project_manifest_is_checkpointed_as_failed(tmp_path, templates):
    prepared = _prepare(tmp_path, _start(tmp_path))
    (Path(prepared["project"]) / "report.json").write_text("[]", encoding="utf-8")
    failed = _build(tmp_path, prepared)
    assert failed["status"] == "needs_completion"
    assert _get(tmp_path, prepared["work_id"])["report"]["status"] == "failed"


def test_missing_glyph_warning_does_not_count_as_a_successful_build(tmp_path, templates, monkeypatch):
    prepared = _prepare(tmp_path, _start(tmp_path))
    monkeypatch.setattr(latex_reports.shutil, "which", lambda _: "xelatex")

    def run(command, **kwargs):
        if "--version" in command:
            return SimpleNamespace(stdout=b"XeTeX test\n", returncode=0)
        output = next(arg.split("=", 1)[1] for arg in command if arg.startswith("-output-directory="))
        (Path(output) / "main.pdf").write_bytes(b"%PDF-1.7\n")
        return SimpleNamespace(stdout=b"Missing character: no glyph in font", returncode=0)

    monkeypatch.setattr(latex_reports.subprocess, "run", run)
    failed = _build(tmp_path, prepared)
    assert failed["status"] == "needs_completion"
    assert {item["role"] for item in failed["files"]} == {"latex_source"}
