from pathlib import Path
from zipfile import ZipFile

import pytest

from cwtrack import api
from cwtrack.resources import ResourceLibrary


def test_a_local_resource_can_be_attached_to_one_course_and_reopened(tmp_path):
    book = tmp_path / "algorithms.pdf"
    book.write_bytes(b"%PDF-1.7 sample course resource")
    paths = {"data": tmp_path / "state"}
    target = {"offering_id": "algorithms-1405"}
    library = ResourceLibrary(paths, clock=lambda: "2026-10-17T12:00:00Z")

    attached = library.attach(
        {
            "title": "Algorithms textbook",
            "location": {"kind": "file", "path": str(book)},
        },
        to=target,
        extent={"pages": "14-22"},
    )
    reopened = ResourceLibrary(paths, clock=lambda: "2026-10-17T13:00:00Z")

    view = reopened.view(target=target)
    assert attached["resource_id"]
    assert attached["binding_id"]
    assert view["resources"][0]["title"] == "Algorithms textbook"
    assert view["resources"][0]["provenance"] == "student"
    assert view["bindings"][0]["target"] == target
    assert view["bindings"][0]["extent"] == {"pages": "14-22"}
    assert view["captures"] == []


def test_each_local_capture_keeps_the_exact_bytes_as_an_unused_version(tmp_path):
    book = tmp_path / "algorithms.pdf"
    book.write_bytes(b"%PDF-1.7 original source")
    library = ResourceLibrary(
        {"data": tmp_path / "state"}, clock=lambda: "2026-10-17T12:00:00Z"
    )
    attached = library.attach(
        {
            "title": "Algorithms textbook",
            "location": {"kind": "file", "path": str(book)},
        },
        to={"offering_id": "algorithms-1405"},
        extent={"pages": "14-22"},
    )

    first = library.capture(attached["resource_id"], extent={"pages": "14-22"})
    first_artifact = Path(first["artifact_path"])
    book.write_bytes(b"%PDF-1.7 updated source")
    second = library.capture(attached["resource_id"], extent={"pages": "14-22"})

    assert first["sha256"] == "5d65eb506bdf01f247b60edafee18c3abd2b8afe475bd50ad1374239538fe978"
    assert second["sha256"] == "21fd69edfff14544aecfa439c406e0cc5746c8afbdaf4fa0823cfa49ae7ed3b0"
    assert first_artifact.read_bytes() == b"%PDF-1.7 original source"
    assert Path(second["artifact_path"]).read_bytes() == b"%PDF-1.7 updated source"
    assert first["acquired_extent"] == {"kind": "whole_file"}
    captures = library.view(target={"offering_id": "algorithms-1405"})["captures"]
    assert [capture["capture_id"] for capture in captures] == [
        first["capture_id"], second["capture_id"]
    ]
    assert [capture["sha256"] for capture in captures] == [
        first["sha256"], second["sha256"]
    ]
    assert all(capture["status"] == "captured" for capture in captures)


def test_work_checkpoint_records_only_a_real_capture_as_used(tmp_path):
    data = tmp_path / "state"
    work = tmp_path / "work"
    book = tmp_path / "algorithms.pdf"
    book.write_bytes(b"%PDF-1.7 source read for proof")
    library = ResourceLibrary({"data": data}, clock=lambda: "2026-10-17T12:00:00Z")
    attached = library.attach(
        {
            "title": "Algorithms textbook",
            "location": {"kind": "file", "path": str(book)},
        },
        to={"offering_id": "algorithms-1405"},
    )
    capture = library.capture(attached["resource_id"], extent={"pages": "14-22"})
    started = api.work_start(
        {
            "manual": {
                "course": "Algorithms",
                "title": "Proof exercise",
                "prompt": "Prove the invariant.",
            }
        },
        data=data,
        work=work,
    )

    saved = api.work_save(
        started["work_id"],
        {
            "stage": "in_progress",
            "sections": [{"id": "proof", "title": "Proof", "content": "..."}],
            "open_questions": [],
            "requirements": [{
                "id": "proof",
                "description": "Prove the invariant",
                "deliverable_roles": ["pdf"],
                "verification_method": "review the proof",
            }],
            "resource_uses": [{
                "capture_id": capture["capture_id"],
                "part_ids": ["pages-14-17"],
                "used_extent": {"pages": "14-17"},
                "section_ids": ["proof"],
                "requirement_ids": ["proof"],
                "purpose": "check the invariant definition",
            }],
        },
        expected_revision=started["revision"],
        data=data,
        work=work,
    )
    current = api.work_get(started["work_id"], data=data, work=work)

    assert saved["status"] == "ok"
    assert current["resource_uses"] == [{
        "capture_id": capture["capture_id"],
        "resource_id": attached["resource_id"],
        "sha256": capture["sha256"],
        "part_ids": ["pages-14-17"],
        "used_extent": {"pages": "14-17"},
        "section_ids": ["proof"],
        "requirement_ids": ["proof"],
        "purpose": "check the invariant definition",
    }]


def test_capture_cannot_exceed_the_extent_attached_to_the_course(tmp_path):
    book = tmp_path / "algorithms.pdf"
    book.write_bytes(b"%PDF-1.7 source")
    library = ResourceLibrary(
        {"data": tmp_path / "state"}, clock=lambda: "2026-10-17T12:00:00Z"
    )
    attached = library.attach(
        {
            "title": "Algorithms textbook",
            "location": {"kind": "file", "path": str(book)},
        },
        to={"offering_id": "algorithms-1405"},
        extent={"pages": "14-22"},
    )

    try:
        library.capture(attached["resource_id"], extent={"pages": "100-120"})
    except ValueError as error:
        assert str(error) == "capture extent is outside every active binding"
    else:
        raise AssertionError("capture exceeded the course's selected pages")


def test_work_refuses_resource_use_for_an_unknown_requirement(tmp_path):
    data = tmp_path / "state"
    work = tmp_path / "work"
    book = tmp_path / "algorithms.pdf"
    book.write_bytes(b"%PDF-1.7 source")
    library = ResourceLibrary({"data": data}, clock=lambda: "2026-10-17T12:00:00Z")
    attached = library.attach(
        {
            "title": "Algorithms textbook",
            "location": {"kind": "file", "path": str(book)},
        },
        to={"offering_id": "algorithms-1405"},
    )
    capture = library.capture(attached["resource_id"], extent={"pages": "14-22"})
    started = api.work_start(
        {
            "manual": {
                "course": "Algorithms",
                "title": "Proof exercise",
                "prompt": "Prove the invariant.",
            }
        },
        data=data,
        work=work,
    )

    result = api.work_save(
        started["work_id"],
        {
            "stage": "in_progress",
            "sections": [{"id": "proof", "title": "Proof", "content": "..."}],
            "open_questions": [],
            "requirements": [{
                "id": "proof",
                "description": "Prove the invariant",
                "deliverable_roles": ["pdf"],
                "verification_method": "review the proof",
            }],
            "resource_uses": [{
                "capture_id": capture["capture_id"],
                "part_ids": ["pages-14-17"],
                "used_extent": {"pages": "14-17"},
                "section_ids": ["proof"],
                "requirement_ids": ["unknown-requirement"],
                "purpose": "check the invariant definition",
            }],
        },
        expected_revision=started["revision"],
        data=data,
        work=work,
    )

    assert result["status"] == "invalid_input"


def test_the_caller_api_can_attach_and_read_a_course_resource(tmp_path):
    book = tmp_path / "algorithms.pdf"
    book.write_bytes(b"%PDF-1.7 source")
    data = tmp_path / "state"

    attached = api.resource_attach(
        {
            "title": "Algorithms textbook",
            "location": {"kind": "file", "path": str(book)},
        },
        to={"offering_id": "algorithms-1405"},
        extent={"pages": "14-22"},
        data=data,
    )
    view = api.resource_view(
        data=data, target={"offering_id": "algorithms-1405"}
    )

    assert attached["status"] == "ok"
    assert view["resources"][0]["id"] == attached["resource_id"]


def test_detaching_one_course_keeps_the_resource_version_for_another(tmp_path):
    book = tmp_path / "algorithms.pdf"
    book.write_bytes(b"%PDF-1.7 source")
    library = ResourceLibrary(
        {"data": tmp_path / "state"}, clock=lambda: "2026-10-17T12:00:00Z"
    )
    first_binding = library.attach(
        {
            "title": "Algorithms textbook",
            "location": {"kind": "file", "path": str(book)},
        },
        to={"offering_id": "algorithms-1405"},
    )
    capture = library.capture(
        first_binding["resource_id"], extent={"pages": "14-22"}
    )
    next_binding = library.attach(
        first_binding["resource_id"], to={"offering_id": "algorithms-1406"}
    )

    detached = library.detach(
        first_binding["binding_id"], expected_revision=library.view()["revision"]
    )
    old_course = library.view(target={"offering_id": "algorithms-1405"})
    next_course = library.view(target={"offering_id": "algorithms-1406"})

    assert detached["status"] == "ok"
    assert old_course["resources"] == []
    assert next_course["resources"][0]["id"] == first_binding["resource_id"]
    assert next_course["captures"][0]["capture_id"] == capture["capture_id"]
    assert next_binding["resource_id"] == first_binding["resource_id"]


def test_the_caller_api_can_detach_a_resource_binding(tmp_path):
    book = tmp_path / "algorithms.pdf"
    book.write_bytes(b"%PDF-1.7 source")
    data = tmp_path / "state"
    attached = api.resource_attach(
        {
            "title": "Algorithms textbook",
            "location": {"kind": "file", "path": str(book)},
        },
        to={"offering_id": "algorithms-1405"},
        data=data,
    )

    detached = api.resource_detach(
        attached["binding_id"], expected_revision=attached["revision"], data=data
    )

    assert detached["status"] == "ok"
    assert api.resource_view(
        data=data, target={"offering_id": "algorithms-1405"}
    )["bindings"] == []


def test_folder_capture_contains_only_the_explicit_members_as_an_immutable_snapshot(tmp_path):
    folder = tmp_path / "lectures"
    folder.mkdir()
    (folder / "week-1.md").write_text("one", encoding="utf-8")
    (folder / "week-2.md").write_text("two", encoding="utf-8")
    library = ResourceLibrary(
        {"data": tmp_path / "state"}, clock=lambda: "2026-10-17T12:00:00Z"
    )
    attached = library.attach(
        {
            "title": "Lecture notes",
            "location": {"kind": "folder", "path": str(folder)},
        },
        to={"offering_id": "algorithms-1405"},
        extent={"files": ["week-1.md", "week-2.md"]},
    )

    capture = library.capture(
        attached["resource_id"], extent={"files": ["week-1.md"]}
    )
    (folder / "week-3.md").write_text("new file after capture", encoding="utf-8")

    with ZipFile(capture["artifact_path"]) as archive:
        assert archive.namelist() == ["week-1.md"]
        assert archive.read("week-1.md") == b"one"
    assert capture["acquired_extent"] == {"files": ["week-1.md"]}


def test_folder_capture_rejects_symlinked_members(tmp_path):
    folder = tmp_path / "lectures"
    folder.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("private content", encoding="utf-8")
    try:
        (folder / "linked.md").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")

    library = ResourceLibrary(
        {"data": tmp_path / "state"}, clock=lambda: "2026-10-17T12:00:00Z"
    )
    attached = library.attach(
        {
            "title": "Lecture notes",
            "location": {"kind": "folder", "path": str(folder)},
        },
        to={"offering_id": "algorithms-1405"},
    )

    with pytest.raises(ValueError, match="selected folder member is unavailable"):
        library.capture(attached["resource_id"], extent={"files": ["linked.md"]})


def test_public_web_capture_uses_the_injected_reader_and_video_stays_reference_only(tmp_path):
    calls = []

    def reader(url):
        calls.append(url)
        return {
            "content": b"<main>lecture notes</main>",
            "content_type": "text/html; charset=utf-8",
            "final_url": url,
        }

    library = ResourceLibrary(
        {"data": tmp_path / "state"},
        clock=lambda: "2026-10-17T12:00:00Z",
        content_reader=reader,
    )
    page = library.attach(
        {
            "title": "Course notes",
            "location": {"kind": "web", "url": "https://example.test/notes"},
        },
        to={"offering_id": "algorithms-1405"},
    )
    video = library.attach(
        {
            "title": "Lecture video",
            "location": {"kind": "video", "url": "https://example.test/video"},
        },
        to={"offering_id": "algorithms-1405"},
    )

    captured = library.capture(page["resource_id"], extent={"section": "main"})
    reference = library.capture(video["resource_id"], extent={"time": "00:10-00:30"})

    assert captured["status"] == "captured"
    assert Path(captured["artifact_path"]).read_bytes() == b"<main>lecture notes</main>"
    assert calls == ["https://example.test/notes"]
    assert reference["status"] == "reference_only"


def test_source_update_creates_a_new_head_without_rewriting_captured_versions(tmp_path):
    data = tmp_path / "data"
    first_source = tmp_path / "first.md"
    second_source = tmp_path / "second.md"
    first_source.write_bytes(b"version one")
    second_source.write_bytes(b"version two")
    library = ResourceLibrary({"data": data}, clock=lambda: "2026-10-17T00:00:00Z")
    attached = library.attach(
        {"title": "Notes", "location": {"kind": "file", "path": str(first_source)}},
        to={"offering_id": "math-1405"},
    )
    old_capture = library.capture(attached["resource_id"], extent={"pages": "1-2"})

    updated = library.update(
        attached["resource_id"],
        {"location": {"kind": "file", "path": str(second_source)}},
        expected_revision=1,
    )
    stale = library.update(
        attached["resource_id"],
        {"title": "Stale edit"},
        expected_revision=1,
    )
    new_capture = library.capture(attached["resource_id"], extent={"pages": "1-2"})
    view = library.view(target={"offering_id": "math-1405"})

    assert updated["status"] == "ok"
    assert updated["resource"]["revision"] == 2
    assert stale["status"] == "conflict"
    assert old_capture["sha256"] != new_capture["sha256"]
    assert Path(old_capture["artifact_path"]).read_bytes() == b"version one"
    assert Path(new_capture["artifact_path"]).read_bytes() == b"version two"
    assert {item["sha256"] for item in view["captures"]} == {
        old_capture["sha256"], new_capture["sha256"]
    }


def test_the_caller_api_can_update_a_resource_head(tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("source", encoding="utf-8")
    data = tmp_path / "data"
    attached = api.resource_attach(
        {"title": "Notes", "location": {"kind": "file", "path": str(source)}},
        to={"offering_id": "math-1405"},
        data=data,
    )

    result = api.resource_update(
        attached["resource_id"], {"title": "Updated notes"},
        expected_revision=1, data=data,
    )

    assert result["status"] == "ok"
    assert result["resource"]["title"] == "Updated notes"
