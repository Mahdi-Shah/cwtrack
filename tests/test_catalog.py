from cwtrack.catalog import Catalog


def test_class_links_are_explicit_revisioned_and_do_not_merge_platform_ids(tmp_path):
    catalog = Catalog(tmp_path)
    cw = {"connection_id": "cw-a", "class_id": "17"}
    quera = {"connection_id": "quera-b", "class_id": "17"}

    linked = catalog.link_classes(
        [cw, quera],
        {"title": "ساختمان داده", "term": "پاییز ۱۴۰۵"},
        expected_revision=0,
    )
    view = catalog.offerings()
    conflict = catalog.link_classes(
        [cw], {"title": "درس دیگر", "term": "پاییز ۱۴۰۵"},
        expected_revision=linked["revision"],
    )

    assert linked["status"] == "ok"
    assert len(view["offerings"]) == 1
    assert view["offerings"][0]["class_refs"] == [cw, quera]
    assert conflict["status"] == "conflict"
    assert catalog.offerings()["offerings"] == view["offerings"]


def test_archiving_a_class_keeps_its_course_link_and_local_history(tmp_path):
    catalog = Catalog(tmp_path)
    class_ref = {"connection_id": "quera-b", "class_id": "17"}
    linked = catalog.link_classes(
        [class_ref], {"title": "ریاضی", "term": "۱۴۰۵"}, expected_revision=0
    )

    archived = catalog.class_tracking(
        class_ref, "archived", expected_revision=linked["revision"]
    )

    assert archived["status"] == "ok"
    assert catalog.offering_for(class_ref)["id"] == linked["offering"]["id"]
    assert catalog.class_tracking_view()[0]["state"] == "archived"


def test_related_assignments_require_explicit_references_and_stay_independent(tmp_path):
    catalog = Catalog(tmp_path)
    cw = {
        "connection_id": "cw-a", "class_id": "17", "assignment_id": "812"
    }
    quera = {
        "connection_id": "quera-b", "class_id": "course-x", "assignment_id": "a-9"
    }

    related = catalog.relate_assignments(
        [cw, quera], "موضوع مشترک؛ خروجی و تحویل مستقل", expected_revision=0
    )
    duplicate = catalog.relate_assignments(
        [quera, cw], "موضوع مشترک؛ خروجی و تحویل مستقل", expected_revision=1
    )

    assert related["status"] == "ok"
    assert duplicate["status"] == "exists"
    assert catalog.assignment_relations() == [related["relation"]]
    assert related["relation"]["task_refs"] == [cw, quera]


def test_related_assignments_reject_duplicates_and_stale_catalog_revisions(tmp_path):
    catalog = Catalog(tmp_path)
    task = {
        "connection_id": "quera-b", "class_id": "course-x", "assignment_id": "a-9"
    }
    other = {
        "connection_id": "quera-b", "class_id": "course-x", "assignment_id": "a-10"
    }

    duplicate_ref = catalog.relate_assignments(
        [task, task], "هم‌موضوع", expected_revision=0
    )
    related = catalog.relate_assignments(
        [task, other], "هم‌موضوع", expected_revision=0
    )
    stale = catalog.relate_assignments(
        [task, other], "توضیح دیگر", expected_revision=0
    )

    assert duplicate_ref["status"] == "invalid_input"
    assert related["status"] == "ok"
    assert stale["status"] == "conflict"
