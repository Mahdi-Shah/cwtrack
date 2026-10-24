"""Connect template preparation/builds to existing durable assignment work."""

from __future__ import annotations

import uuid
from pathlib import Path

from . import latex_reports, work_application
from .client import CwError
from .paths import find_data_dir


def _library(data) -> Path:
    return find_data_dir(str(data) if data else "").parent / ".cw" / "latex-templates"


def templates(*, data=None) -> dict:
    return {"status": "ok", "templates": latex_reports.catalogue(_library(data))}


def _progress(current: dict, report: dict, stage: str) -> dict:
    return {"stage": stage, "sections": current["sections"],
            "open_questions": current["open_questions"], "report": report}


def _current(work_id, expected_revision, data, work) -> dict:
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 1:
        return {"status": "invalid_input", "message": "شمارهٔ نسخه نامعتبر است"}
    current = work_application.get(work_id, data=data, work=work)
    if current.get("status") == "not_found":
        return current
    if current["revision"] != expected_revision:
        return {"status": "conflict", "revision": current["revision"]}
    return current


def prepare(work_id: str, template_id: str, metadata: dict, reason: str, *,
            expected_revision: int, data=None, work=None) -> dict:
    try:
        current = _current(work_id, expected_revision, data, work)
        if current.get("status") in {"conflict", "not_found", "invalid_input"}:
            return current
        relative = Path("reports") / uuid.uuid4().hex
        project = Path(current["workspace"]) / relative
        result = latex_reports.prepare(template_id, project, metadata, reason, _library(data))
        if result["status"] != "ok":
            spec = latex_reports.TEMPLATES.get(template_id) if isinstance(template_id, str) else None
            if spec and isinstance(reason, str) and reason.strip():
                report = {"template_id": template_id, "template_sha256": spec["sha256"],
                          "recipe_version": latex_reports.RECIPE_VERSION, "selection_reason": reason,
                          "status": "failed", "project": relative.as_posix(),
                          "message": result["message"]}
                saved = work_application.save(work_id, _progress(current, report, "needs_completion"),
                                              expected_revision=expected_revision, data=data, work=work)
                return {**result, **saved, "status": result["status"] if saved["status"] == "ok" else saved["status"], "report": report}
            return result
        report = {**result["report"], "project": relative.as_posix()}
        saved = work_application.save(work_id, _progress(current, report, "in_progress"),
                                      expected_revision=expected_revision, data=data, work=work)
        return {**result, **saved, "report": report}
    except (CwError, OSError, ValueError) as exc:
        return {"status": "invalid_input", "message": str(exc)}


def build(work_id: str, *, expected_revision: int, data=None, work=None,
          timeout: int = 120) -> dict:
    try:
        current = _current(work_id, expected_revision, data, work)
        if current.get("status") in {"conflict", "not_found", "invalid_input"}:
            return current
        selected = current.get("report", {})
        if not selected.get("project"):
            return {"status": "invalid_input", "message": "ابتدا قالب گزارش را آماده کنید"}
        workspace = Path(current["workspace"]).resolve()
        project = (workspace / selected["project"]).resolve()
        project.relative_to(workspace)
        result = latex_reports.build(project, workspace / "report-builds", timeout=timeout)
        report = result.get("report", {**selected, "status": "failed",
                                      "message": result.get("message", "ساخت ناموفق بود")})
        report = {**report, "project": selected["project"],
                  "input_fingerprint": current["input_fingerprint"],
                  "answer_fingerprint": current["answer_fingerprint"]}
        for key in ("pdf_path", "source_path", "log_path"):
            if key in report:
                report[key] = Path(report[key]).relative_to(Path(current["folder"])).as_posix()
        stage = "under_verification" if result["status"] == "built" else "needs_completion"
        saved = work_application.save(work_id, _progress(current, report, stage),
                                      expected_revision=expected_revision, data=data, work=work)
        if saved["status"] != "ok":
            return {**result, **saved, "report": report}
        return {**result, **saved, "status": result["status"], "report": report}
    except (CwError, OSError, ValueError) as exc:
        return {"status": "invalid_input", "message": str(exc)}
