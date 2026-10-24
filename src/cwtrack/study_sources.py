"""Course-source discovery and resource capture for assignment preparation."""

from __future__ import annotations

import re
from pathlib import Path

from . import catalog as catalog_store
from . import resource_application
from .paths import find_data_dir
from .task_refs import valid_task_ref as _valid_task_ref


def _resources_for_task(task_ref: dict, data: str | Path | None) -> dict:
    """Combine resources bound to the exact task and its explicitly linked course."""
    data_dir = find_data_dir(str(data) if data else "")
    library = resource_application.library(data_dir)
    views = [library.view(target={"task_ref": task_ref})]
    class_ref = {
        "connection_id": task_ref["connection_id"],
        "class_id": task_ref["class_id"],
    }
    offering = catalog_store.Catalog(data_dir).offering_for(class_ref)
    if offering:
        views.append(library.view(target={"offering_id": offering["id"]}))

    def unique(key):
        result = {}
        for view in views:
            for item in view.get(key, []):
                result[item["id"] if key != "captures" else item["capture_id"]] = item
        return list(result.values())

    return {
        "task_ref": task_ref,
        "offering_id": offering["id"] if offering else None,
        "revision": max((view.get("revision", 0) for view in views), default=0),
        "resources": unique("resources"),
        "bindings": unique("bindings"),
        "captures": unique("captures"),
    }


def _course_source_reports(
    task_ref: dict, received: dict, task_resources: dict,
    data: str | Path | None, *, observations: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    """Report which platform course sources were checked or still need linking."""
    data_dir = find_data_dir(str(data) if data else "")
    catalog = catalog_store.Catalog(data_dir)
    task_class_ref = {
        "connection_id": task_ref["connection_id"],
        "class_id": task_ref["class_id"],
    }
    task_class = next((
        node for node in catalog.classes()
        if node.get("ref") == task_class_ref
    ), None)
    tracking_by_class = {
        (item["class_ref"]["connection_id"], item["class_ref"]["class_id"]): item
        for item in catalog.class_tracking_view()
    }
    task_platform = (task_class or {}).get("platform", received.get("source"))
    materials = received.get("course_materials", [])
    quera_coverage = received.get("course_materials_coverage", "not_observed")
    current_source_observation = (observations or {}).get(task_ref["connection_id"])
    current_coverage = (
        current_source_observation.get("coverage")
        if task_platform == "cw" and current_source_observation
        else quera_coverage
    )
    current_status = (
        current_source_observation.get("status")
        if task_platform == "cw" and current_source_observation
        else ("checked" if quera_coverage == "complete" else "incomplete")
    )
    reports = [{
        "task_ref": task_ref,
        "platform": task_platform,
        "connection_id": task_ref["connection_id"],
        "status": current_status,
        "coverage": current_coverage,
        "resources_found": (
            current_source_observation.get("resources_found", 0)
            if task_platform == "cw" and current_source_observation
            else len(materials) if isinstance(materials, list) else 0
        ),
    }]
    task_term = (
        (tracking_by_class.get((task_ref["connection_id"], task_ref["class_id"])) or {}).get("term")
        or _course_term_from_title((task_class or {}).get("title", ""))
    )
    if task_term:
        reports[0]["term"] = task_term
    if current_source_observation and current_source_observation.get("issues"):
        reports[0]["issues"] = current_source_observation["issues"]
    issues = []
    offerings = catalog.offerings().get("offerings", [])
    linked_by_class = {
        (ref["connection_id"], ref["class_id"]): offering
        for offering in offerings
        for ref in offering.get("class_refs", [])
    }
    class_nodes = catalog.classes()
    task_class = next((
        node for node in class_nodes if node.get("ref") == {
            "connection_id": task_ref["connection_id"],
            "class_id": task_ref["class_id"],
        }
    ), None)
    task_course_code = (
        received.get("course_code")
        or _course_code_from_title((task_class or {}).get("title", ""))
    )
    if task_course_code:
        reports[0]["course_code"] = task_course_code
    connections = [
        item for item in catalog.connections()
        if item.get("platform") != task_platform
    ]
    counterpart_platforms = {
        "cw": "quera",
        "quera": "cw",
    }
    counterpart = counterpart_platforms.get(task_platform)
    task_offering = catalog.offering_for(task_class_ref)
    task_offering_id = task_offering.get("id") if task_offering else None

    for connection in connections:
        platform = connection.get("platform")
        connection_id = connection.get("connection_id")
        linked_nodes = [
            node for node in class_nodes
            if node.get("platform") == platform
            and node.get("ref", {}).get("connection_id") == connection_id
            and task_offering_id
            and linked_by_class.get((connection_id, node["ref"]["class_id"]), {}).get("id")
            == task_offering_id
        ]
        if linked_nodes:
            offering_resource_ids = {
                binding["resource_id"]
                for binding in task_resources.get("bindings", [])
                if binding.get("target") == {"offering_id": task_offering_id}
            }
            observed = (observations or {}).get(connection_id)
            report = {
                "task_ref": task_ref,
                "platform": platform,
                "connection_id": connection_id,
                "status": observed.get("status", "linked") if observed else "linked",
                "coverage": observed.get("coverage", "local_library_only") if observed else "local_library_only",
                "class_refs": [node["ref"] for node in linked_nodes],
                "resources_found": (
                    observed.get("resources_found", len(offering_resource_ids))
                    if observed else len(offering_resource_ids)
                ),
            }
            if observed and observed.get("issues"):
                report["issues"] = observed["issues"]
            reports.append(report)
            continue

        candidates = []
        for node in class_nodes:
            ref = node.get("ref", {})
            key = (ref.get("connection_id"), ref.get("class_id"))
            if (
                node.get("platform") == platform
                and ref.get("connection_id") == connection_id
                and key not in linked_by_class
            ):
                candidate = {"ref": ref, "title": node.get("title", "")}
                course_code = _course_code_from_title(candidate["title"])
                if course_code:
                    candidate["course_code"] = course_code
                candidate_term = (
                    (tracking_by_class.get((ref.get("connection_id"), ref.get("class_id"))) or {}).get("term")
                    or _course_term_from_title(candidate["title"])
                )
                if candidate_term:
                    candidate["term"] = candidate_term
                candidates.append(candidate)

        complete_inventory = bool(connection.get("last_success_at"))
        if candidates:
            status = "link_required"
            coverage = "not_checked"
            message = "کلاس‌های این سامانه هنوز به درسِ نیم‌سال تکلیف پیوند نخورده‌اند؛ منابع آن‌ها بررسی نشده است."
        elif complete_inventory:
            status = "no_candidate"
            coverage = "class_inventory_complete"
            message = "در فهرست کامل کلاس‌های این سامانه، کلاسِ پیوندخورده یا نامزد پیوند پیدا نشد."
        else:
            status = "needs_refresh"
            coverage = "not_observed"
            message = "فهرست کامل کلاس‌های این سامانه برای بررسی منبع در دسترس نیست."
        reports.append({
            "task_ref": task_ref,
            "platform": platform,
            "connection_id": connection_id,
            "status": status,
            "coverage": coverage,
            "candidates": candidates,
            "resources_found": 0,
        })
        if status in {"link_required", "needs_refresh"}:
            issues.append({
                "kind": "course_source",
                "platform": platform,
                "status": status,
                "message": message,
            })
    if counterpart and not any(
        item.get("platform") == counterpart for item in connections
    ):
        reports.append({
            "task_ref": task_ref,
            "platform": counterpart,
            "status": "not_configured",
            "coverage": "not_checked",
            "resources_found": 0,
        })
    return reports, issues


def _course_code_from_title(title: str) -> str | None:
    digits = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    normalized = title.translate(digits)
    match = re.search(r"\((\d{5,8})\)", normalized)
    if not match:
        match = re.search(r"(?<!\d)(\d{5,8})(?!\d)", normalized)
    return match.group(1) if match else None


def _course_term_from_title(title: str) -> str | None:
    digits = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    normalized = title.translate(digits)
    match = re.search(r"نیم[\s\u200c-]*سال\s*اول\s*(\d{4})", normalized)
    if match:
        return match.group(1) + "-1"
    match = re.search(r"نیم[\s\u200c-]*سال\s*دوم\s*(\d{4})", normalized)
    if match:
        return match.group(1) + "-2"
    return None


def _attach_quera_course_materials(received: dict, *, data=None) -> list[dict]:
    """Persist downloaded course files in the existing resource library."""
    task_ref = received.get("assignment_ref")
    materials = received.get("course_materials", [])
    if not _valid_task_ref(task_ref) or not isinstance(materials, list):
        return []
    data_dir = find_data_dir(str(data) if data else "")
    class_ref = {
        "connection_id": task_ref["connection_id"],
        "class_id": task_ref["class_id"],
    }
    offering = catalog_store.Catalog(data_dir).offering_for(class_ref)
    target = {"offering_id": offering["id"]} if offering else {"task_ref": task_ref}
    return _attach_course_material_files(materials, target=target, data=data_dir)


def _attach_course_material_files(
    materials: list[dict], *, target: dict, data: str | Path | None
) -> list[dict]:
    """Register and snapshot the downloaded course files exactly once."""
    library = resource_application.library(data)
    library_view = library.view()
    resources_by_source = {
        item.get("provenance"): item
        for item in library_view.get("resources", [])
        if item.get("provenance")
    }
    target_sources = {
        item.get("provenance")
        for item in library.view(target=target).get("resources", [])
    }
    captured_resource_ids = {
        item.get("resource_id") for item in library_view.get("captures", [])
    }
    issues = []
    for material in materials:
        if not isinstance(material, dict):
            issues.append({"status": "invalid_material"})
            continue
        url, path = material.get("url"), material.get("path")
        if not isinstance(url, str) or not isinstance(path, str):
            issues.append({"status": "invalid_material"})
            continue
        if url in target_sources:
            continue
        existing_resource = resources_by_source.get(url)
        if existing_resource:
            result = resource_application.attach(existing_resource["id"], to=target, data=data)
        else:
            result = resource_application.attach(
                {
                    "title": material.get("title") or Path(path).name,
                    "location": {"kind": "file", "path": path},
                    "provenance": url,
                },
                to=target,
                data=data,
            )
        if result.get("status") != "ok":
            issues.append({"url": url, "status": result.get("status")})
        else:
            target_sources.add(url)
            if result["resource_id"] not in captured_resource_ids:
                snapshot = resource_application.capture(
                    result["resource_id"],
                    extent={"section": "whole file"},
                    data=data,
                )
                if snapshot.get("status") != "captured":
                    issues.append({"url": url, "status": "snapshot_failed"})
                else:
                    captured_resource_ids.add(result["resource_id"])
    return issues


def _fetch_linked_course_materials(
    task_ref: dict, *, data=None, home=None, vault=None, adapters=None,
    manager_factory,
) -> dict | None:
    """Fetch course materials only from the selected or explicitly linked classes."""
    data_dir = find_data_dir(str(data) if data else "")
    catalog = catalog_store.Catalog(data_dir)
    class_ref = {
        "connection_id": task_ref["connection_id"],
        "class_id": task_ref["class_id"],
    }
    offering = catalog.offering_for(class_ref)
    class_nodes = catalog.classes()
    task_class = next((
        node for node in class_nodes
        if node.get("ref") == class_ref
    ), None)
    task_platform = task_class.get("platform") if task_class else None
    if task_platform not in {"cw", "quera"}:
        return None
    linked_refs = {tuple(sorted(item.items())) for item in (offering or {}).get("class_refs", [])}
    targets = []
    if task_platform == "cw":
        targets.append((task_class, class_ref))
    if offering:
        for node in class_nodes:
            ref = node.get("ref", {})
            if (
                node.get("platform") != task_platform
                and tuple(sorted(ref.items())) in linked_refs
            ):
                targets.append((node, ref))
    if not targets:
        return None

    manager = manager_factory(home, adapters=adapters, vault=vault)
    if manager is None:
        return {
            "status": "unavailable",
            "coverage": "not_checked",
            "resources_found": 0,
            "issues": [{"status": "secure_store_unavailable"}],
            "by_connection": {
                item["connection_id"]: {
                    "status": "unavailable", "coverage": "not_checked",
                    "resources_found": 0,
                    "issues": [{"status": "secure_store_unavailable"}],
                }
                for _, item in targets
            },
        }
    materials = []
    issues = []
    by_connection = {}
    coverage_complete = True
    offering_id = offering.get("id") if offering else None
    target = {"offering_id": offering_id} if offering_id else {"task_ref": task_ref}
    for source_class, source_ref in targets:
        platform = source_class["platform"]
        if platform == task_platform == "quera":
            continue
        result = manager.observe(
            source_ref["connection_id"],
            {"scope": "course_materials", "class_ref": source_ref},
        )
        if result.get("status") == "challenge_required":
            challenge_issue = {
                "status": "challenge_required",
                "continuation_id": result.get("continuation_id"),
                "challenge": result.get("challenge"),
                "connection_id": source_ref["connection_id"],
            }
            issues.append(challenge_issue)
            by_connection[source_ref["connection_id"]] = {
                "status": "needs_input", "coverage": "not_checked",
                "resources_found": 0, "issues": [challenge_issue],
            }
            coverage_complete = False
            continue
        if result.get("status") != "ok":
            source_issue = {
                "status": result.get("status", "unavailable"),
                "connection_id": source_ref["connection_id"],
            }
            issues.append(source_issue)
            by_connection[source_ref["connection_id"]] = {
                "status": "unavailable", "coverage": "not_checked",
                "resources_found": 0, "issues": [source_issue],
            }
            coverage_complete = False
            continue
        receipt = result.get("receipt", {})
        if receipt.get("scope") != "course_materials":
            source_issue = {"status": "invalid_course_materials_receipt"}
            issues.append(source_issue)
            by_connection[source_ref["connection_id"]] = {
                "status": "incomplete", "coverage": "incomplete",
                "resources_found": 0, "issues": [source_issue],
            }
            coverage_complete = False
            continue
        source_materials = receipt.get("course_materials", [])
        source_issues = receipt.get("course_materials_issues", [])
        source_complete = receipt.get("coverage") == "complete" and not source_issues
        by_connection[source_ref["connection_id"]] = {
            "status": "checked" if source_complete else "incomplete",
            "coverage": receipt.get("coverage", "incomplete"),
            "resources_found": len(source_materials),
            "issues": source_issues,
        }
        if not source_complete:
            coverage_complete = False
        materials.extend(source_materials)
        issues.extend(source_issues)

    attach_issues = _attach_course_material_files(
        materials, target=target, data=data
    )
    issues.extend(attach_issues)
    if attach_issues:
        coverage_complete = False
        for source in by_connection.values():
            source["status"] = "incomplete"
            source["coverage"] = "incomplete"
            source.setdefault("issues", []).extend(attach_issues)
    return {
        "status": "checked" if coverage_complete else "incomplete",
        "coverage": "complete" if coverage_complete else "incomplete",
        "resources_found": len(materials),
        "issues": issues,
        "by_connection": by_connection,
    }


def _course_materials_summary(received: dict) -> dict:
    materials = received.get("course_materials", [])
    return {
        "task_ref": received.get("assignment_ref"),
        "coverage": received.get("course_materials_coverage", "not_observed"),
        "downloaded": len(materials) if isinstance(materials, list) else 0,
        "issues": received.get("course_materials_issues", []),
        "attachment_issues": received.get("attachment_issues", []),
    }


def _course_materials_coverage_issue(received: dict) -> dict | None:
    coverage = received.get("course_materials_coverage")
    issues = received.get("course_materials_issues", [])
    if (coverage is None or coverage == "complete") and not issues:
        return None
    return {
        "kind": "course_materials",
        "coverage": coverage,
        "issues": issues,
        "message": "فقط پیوندهای قابل‌مشاهدهٔ صفحهٔ درس بررسی شدند؛ کامل‌بودن جزوه‌ها تأیید نشد.",
    }
