from cwtrack.catalog import Catalog
from cwtrack.study import Study


class StaticPlatform:
    def __init__(self, connection_id, platform, class_title):
        self.connection = {
            "id": connection_id,
            "platform": platform,
            "origin": "https://{}.example".format(platform),
        }
        self.class_title = class_title
        self.coverage = "complete"
        self.status = "ok"
        self.assignment_status = "ok"
        self.assignment_failure_kind = None
        self.observed_at = "2026-10-17T00:00:00Z"
        self.failure = None

    def observe(self, request, context):
        if self.failure:
            raise ConnectionError("platform is unavailable")
        if request["scope"] == "assignments":
            result = {
                "status": self.assignment_status,
                "scope": "assignments",
                "coverage": "complete" if self.assignment_status == "ok" else "incomplete",
                "observed_at": self.observed_at,
                "nodes": [],
            }
            if self.assignment_failure_kind:
                result["failure_kind"] = self.assignment_failure_kind
            return result
        return {
            "status": self.status,
            "scope": "classes",
            "coverage": self.coverage,
            "observed_at": self.observed_at,
            "nodes": [
                {
                    "kind": "class",
                    "ref": {
                        "connection_id": self.connection["id"],
                        "class_id": "17",
                    },
                    "title": self.class_title,
                }
            ],
        }


def test_equal_class_ids_from_different_platforms_remain_independent(tmp_path):
    study = Study(
        {"data": tmp_path},
        platforms=[
            StaticPlatform("cw-account", "cw", "ساختمان داده در CW"),
            StaticPlatform("quera-account", "quera", "ساختمان داده در کوئرا"),
        ],
        protected_state=None,
        content_reader=None,
        clock=lambda: "2026-10-17T00:00:00Z",
    )

    result = study.refresh()
    view = Study(
        {"data": tmp_path},
        platforms=[],
        protected_state=None,
        content_reader=None,
        clock=lambda: "2026-10-17T00:00:00Z",
    ).view()

    assert result["status"] == "ok"
    assert {
        (item["ref"]["connection_id"], item["ref"]["class_id"])
        for item in view["classes"]
    } == {("cw-account", "17"), ("quera-account", "17")}


def test_incomplete_class_inventory_is_not_reported_as_a_success(tmp_path):
    adapter = StaticPlatform("cw-account", "cw", "ساختمان داده")
    adapter.coverage = "incomplete"
    study = Study(
        {"data": tmp_path},
        platforms=[adapter],
        protected_state=None,
        content_reader=None,
        clock=lambda: "2026-10-17T00:00:00Z",
    )

    result = study.refresh()

    assert result["status"] == "partial"
    assert result["targets"][0]["status"] == "partial"
    assert study.view()["classes"] == []


def test_failed_refresh_keeps_last_success_and_records_the_latest_attempt(tmp_path):
    adapter = StaticPlatform("quera-account", "quera", "ساختمان داده")
    adapter.observed_at = "2026-10-17T09:00:00Z"
    times = iter(("2026-10-17T09:00:00Z", "2026-10-17T10:00:00Z"))
    study = Study(
        {"data": tmp_path},
        platforms=[adapter],
        protected_state=None,
        content_reader=None,
        clock=lambda: next(times),
    )
    study.refresh()
    adapter.status = "unavailable"
    adapter.coverage = "incomplete"

    result = study.refresh()
    view = Study(
        {"data": tmp_path},
        platforms=[],
        protected_state=None,
        content_reader=None,
        clock=lambda: "2026-10-17T11:00:00Z",
    ).view()

    assert result["status"] == "partial"
    assert view["classes"][0]["title"] == "ساختمان داده"
    assert view["connections"] == [
        {
            "connection_id": "quera-account",
            "platform": "quera",
            "scope": "classes",
            "coverage": "incomplete",
            "last_attempt_at": "2026-10-17T10:00:00Z",
            "last_success_at": "2026-10-17T09:00:00Z",
            "last_success_coverage": "complete",
            "last_attempt_status": "unavailable",
        }
    ]


def test_refresh_exposes_only_allowlisted_assignment_failure_categories(tmp_path):
    adapter = StaticPlatform("cw-account", "cw", "کلاس نمونه")
    adapter.assignment_status = "unavailable"
    adapter.assignment_failure_kind = "unexpected_response"
    study = Study(
        {"data": tmp_path},
        platforms=[adapter],
        protected_state=None,
        content_reader=None,
        clock=lambda: "2026-10-17T12:00:00Z",
    )

    result = study.refresh()
    view = Study(
        {"data": tmp_path}, platforms=[], protected_state=None, content_reader=None,
        clock=lambda: "2026-10-17T13:00:00Z",
    ).view()

    assert result["targets"][0]["assignment_failure_counts"] == {
        "unexpected_response": 1
    }
    assert view["assignment_observations"][0]["failure_kind"] == "unexpected_response"


def test_refresh_skips_assignment_observations_for_archived_classes(tmp_path):
    class CountingPlatform(StaticPlatform):
        def __init__(self):
            super().__init__("quera-account", "quera", "نظریه بازی‌ها")
            self.scopes = []

        def observe(self, request, context):
            self.scopes.append(request["scope"])
            return super().observe(request, context)

    adapter = CountingPlatform()
    study = Study(
        {"data": tmp_path},
        platforms=[adapter],
        protected_state=None,
        content_reader=None,
        clock=lambda: "2026-10-17T00:00:00Z",
    )
    study.refresh()
    adapter.scopes.clear()
    archived = Catalog(tmp_path).class_tracking(
        {"connection_id": "quera-account", "class_id": "17"},
        "archived",
        expected_revision=0,
    )

    result = study.refresh()

    assert archived["status"] == "ok"
    assert result["status"] == "ok"
    assert adapter.scopes == ["classes"]
    assert study.view()["classes"][0]["tracking"]["state"] == "archived"


def test_one_connection_failure_does_not_stop_the_other_platform(tmp_path):
    cw = StaticPlatform("cw-account", "cw", "CW old class")
    quera = StaticPlatform("quera-account", "quera", "Quera old class")
    times = iter(
        (
            "2026-10-17T09:00:00Z",
            "2026-10-17T09:01:00Z",
            "2026-10-17T10:00:00Z",
            "2026-10-17T10:01:00Z",
        )
    )
    study = Study(
        {"data": tmp_path},
        platforms=[cw, quera],
        protected_state=None,
        content_reader=None,
        clock=lambda: next(times),
    )
    study.refresh()
    cw.class_title = "CW changed while unavailable"
    cw.failure = True
    quera.class_title = "Quera refreshed class"

    result = study.refresh()
    titles = {item["title"] for item in study.view()["classes"]}
    targets = {item["connection_id"]: item["status"] for item in result["targets"]}

    assert result["status"] == "partial"
    assert targets == {"cw-account": "unavailable", "quera-account": "ok"}
    assert titles == {"CW old class", "Quera refreshed class"}


def test_refresh_without_a_configured_platform_does_not_claim_success(tmp_path):
    study = Study(
        {"data": tmp_path},
        platforms=[],
        protected_state=None,
        content_reader=None,
        clock=lambda: "2026-10-17T00:00:00Z",
    )

    result = study.refresh()

    assert result == {"status": "unavailable", "targets": []}


def test_refresh_exposes_resumable_login_challenges_instead_of_losing_them(tmp_path):
    class ChallengePlatform(StaticPlatform):
        def observe(self, request, context):
            return {
                "status": "challenge_required",
                "scope": request["scope"],
                "coverage": "incomplete",
                "nodes": [],
                "continuation_id": "continue-123",
                "challenge": {
                    "kind": "otp",
                    "display": "کد را وارد کن",
                    "expires_at": "2026-10-17T12:10:00+03:30",
                },
            }

    adapter = ChallengePlatform("quera-account", "quera", "Quera")
    study = Study(
        {"data": tmp_path},
        platforms=[adapter],
        protected_state=None,
        content_reader=None,
        clock=lambda: "2026-10-17T12:00:00+03:30",
    )

    result = study.refresh()

    assert result["status"] == "partial"
    assert result["targets"][0]["status"] == "challenge_required"
    assert result["actions"] == [{
        "connection_id": "quera-account",
        "platform": "quera",
        "scope": "classes",
        "continuation_id": "continue-123",
        "challenge": {
            "kind": "otp",
            "display": "کد را وارد کن",
            "expires_at": "2026-10-17T12:10:00+03:30",
        },
    }]


def test_assignment_ids_are_scoped_to_their_connection_and_class(tmp_path):
    class Platform(StaticPlatform):
        def observe(self, request, context):
            if request["scope"] == "classes":
                result = super().observe(request, context)
                result["nodes"][0]["ref"]["class_id"] = "same-class-id"
                return result
            class_ref = request["class_ref"]
            return {
                "status": "ok",
                "scope": "assignments",
                "coverage": "complete",
                "observed_at": self.observed_at,
                "nodes": [{
                    "kind": "assignment",
                    "ref": {
                        **class_ref,
                        "assignment_id": "same-assignment-id",
                    },
                    "title": "تمرین مشترک",
                    "submission": {"state": "not_submitted"},
                    "evaluation": {"state": "unknown"},
                    "deadlines": [],
                }],
            }

    study = Study(
        {"data": tmp_path},
        platforms=[
            Platform("cw-account", "cw", "درس CW"),
            Platform("quera-account", "quera", "درس کوئرا"),
        ],
        protected_state=None,
        content_reader=None,
        clock=lambda: "2026-10-17T00:00:00Z",
    )

    result = study.refresh()
    view = study.view()

    assert result["status"] == "ok"
    assert {
        (
            assignment["ref"]["connection_id"],
            assignment["ref"]["class_id"],
            assignment["ref"]["assignment_id"],
        )
        for assignment in view["assignments"]
    } == {
        ("cw-account", "same-class-id", "same-assignment-id"),
        ("quera-account", "same-class-id", "same-assignment-id"),
    }


def test_incomplete_assignment_refresh_keeps_the_last_complete_class_inventory(tmp_path):
    class Platform(StaticPlatform):
        assignment_title = "نسخهٔ معتبر تکلیف"
        assignment_unavailable = False

        def observe(self, request, context):
            if request["scope"] == "classes":
                return super().observe(request, context)
            if self.assignment_unavailable:
                raise ConnectionError("assignment page is unavailable")
            return {
                "status": "ok",
                "scope": "assignments",
                "coverage": "complete",
                "observed_at": self.observed_at,
                "nodes": [{
                    "kind": "assignment",
                    "ref": {
                        **request["class_ref"],
                        "assignment_id": "hw-1",
                    },
                    "title": self.assignment_title,
                }],
            }

    adapter = Platform("quera-account", "quera", "ساختمان داده")
    study = Study(
        {"data": tmp_path},
        platforms=[adapter],
        protected_state=None,
        content_reader=None,
        clock=lambda: "2026-10-17T00:00:00Z",
    )
    study.refresh()
    adapter.assignment_title = "نسخهٔ تازه ولی دریافت‌نشده"
    adapter.assignment_unavailable = True

    result = study.refresh()
    current = Study(
        {"data": tmp_path},
        platforms=[],
        protected_state=None,
        content_reader=None,
        clock=lambda: "2026-10-17T01:00:00Z",
    ).view()

    assert result["status"] == "partial"
    assert current["assignments"][0]["title"] == "نسخهٔ معتبر تکلیف"
