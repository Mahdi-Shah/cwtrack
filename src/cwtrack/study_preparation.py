"""Application workflow for preparing one or more selected assignments."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class PrepareServices:
    """Ports used by the preparation workflow; concrete owners stay outside."""

    work_start: Callable
    work_group_start: Callable
    valid_task_ref: Callable
    attach_quera_course_materials: Callable
    fetch_linked_course_materials: Callable
    resources_for_task: Callable
    course_materials_summary: Callable
    course_source_reports: Callable
    course_materials_coverage_issue: Callable
    collect_assignment: Callable


def prepare(
    selection: dict,
    *,
    services: PrepareServices,
    data: str | Path | None = None,
    home: str | Path | None = None,
    work: str | Path | None = None,
    vault=None,
    adapters=None,
) -> dict:
    """Prepare durable work for only assignment references the student selected."""
    if not isinstance(selection, dict) or len(selection) != 1:
        return {"status": "invalid_input", "message": "یک انتخاب صریح لازم است"}
    if "manual" in selection:
        started = services.work_start(selection, data=data, work=work)
        return {"status": started.get("status"), "work": started}
    if "received" in selection:
        received = selection["received"]
        started = services.work_start(selection, data=data, work=work)
        result = {"status": started.get("status"), "work": started}
        if (
            isinstance(received, dict)
            and received.get("source") in {"quera", "site"}
            and services.valid_task_ref(received.get("assignment_ref"))
        ):
            material_issues = (
                services.attach_quera_course_materials(received, data=data)
                if received.get("source") == "quera" else []
            )
            cw_observation = services.fetch_linked_course_materials(
                received["assignment_ref"], data=data, home=home,
                vault=vault, adapters=adapters,
            )
            result["resources"] = services.resources_for_task(received["assignment_ref"], data)
            result["course_materials"] = services.course_materials_summary(received)
            source_reports, source_issues = services.course_source_reports(
                received["assignment_ref"], received, result["resources"], data,
                observations=(cw_observation or {}).get("by_connection", {}),
            )
            result["course_sources"] = source_reports
            if isinstance(received.get("attachment_issues"), list):
                material_issues.extend(received["attachment_issues"])
            coverage_issue = (
                services.course_materials_coverage_issue(received)
                if received.get("source") == "quera" else None
            )
            if coverage_issue:
                material_issues.append(coverage_issue)
            material_issues.extend(source_issues)
            if cw_observation and cw_observation.get("issues"):
                material_issues.extend(cw_observation["issues"])
            if material_issues:
                result["status"] = "partial"
                result["issues"] = material_issues
        return result
    if "task_ref" in selection:
        task_refs = [selection["task_ref"]]
    elif "task_refs" in selection:
        task_refs = selection["task_refs"]
    else:
        return {"status": "invalid_input", "message": "انتخاب باید TaskRef صریح داشته باشد"}
    if not isinstance(task_refs, list) or not task_refs or any(
        not services.valid_task_ref(reference) for reference in task_refs
    ):
        return {"status": "invalid_input", "message": "فهرست TaskRef نامعتبر است"}

    received = []
    issues = []
    course_observations = {}
    for reference in task_refs:
        intake = services.collect_assignment(
            {"platform": {"task_ref": reference}},
            data=data,
            home=home,
            vault=vault,
            adapters=adapters,
        )
        if intake.get("status") == "ok":
            material_issues = services.attach_quera_course_materials(
                intake["input"], data=data
            )
            cw_observation = services.fetch_linked_course_materials(
                reference, data=data, home=home, vault=vault, adapters=adapters
            )
            if cw_observation:
                course_observations[
                    (reference["connection_id"], reference["class_id"], reference["assignment_id"])
                ] = cw_observation.get("by_connection", {})
                if cw_observation.get("status") != "checked":
                    material_issues.extend(cw_observation.get("issues", []))
            if intake["input"].get("attachment_issues"):
                material_issues.extend(intake["input"]["attachment_issues"])
            coverage_issue = (
                services.course_materials_coverage_issue(intake["input"])
                if intake["input"].get("source") == "quera" else None
            )
            if coverage_issue:
                material_issues.append(coverage_issue)
            if material_issues:
                issues.extend({"task_ref": reference, **issue} for issue in material_issues)
            received.append({"received": intake["input"]})
        else:
            issues.append({"task_ref": reference, **intake})

    if not received:
        status = "challenge_required" if any(
            issue.get("status") == "challenge_required" for issue in issues
        ) else "unavailable"
        return {"status": status, "issues": issues}
    if len(received) == 1:
        started = services.work_start(received[0], data=data, work=work)
        work_items = [started]
        result = {"status": started.get("status"), "work": started}
    else:
        grouped = services.work_group_start(received, data=data, work=work)
        work_items = grouped.get("members", [])
        result = {"status": grouped.get("status"), "group": grouped}
    if issues:
        result["status"] = "partial"
        result["issues"] = issues
    result["resources"] = [
        services.resources_for_task(reference, data) for reference in task_refs
    ]
    result["course_materials"] = [
        services.course_materials_summary(item["received"])
        for item in received if item["received"].get("source") == "quera"
    ]
    result["work_items"] = work_items
    source_reports = []
    for item, resource_view in zip(received, result["resources"]):
        reference = item["received"].get("assignment_ref")
        if item["received"].get("source") not in {"quera", "site"} or not services.valid_task_ref(reference):
            continue
        task_sources, source_issues = services.course_source_reports(
            reference, item["received"], resource_view, data,
            observations=course_observations.get((
                reference["connection_id"],
                reference["class_id"],
                reference["assignment_id"],
            ), {}),
        )
        source_reports.extend(task_sources)
        if source_issues:
            result.setdefault("issues", []).extend(
                {"task_ref": reference, **issue} for issue in source_issues
            )
            result["status"] = "partial"
    result["course_sources"] = source_reports
    return result
