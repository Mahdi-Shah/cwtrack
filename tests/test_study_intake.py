from cwtrack.study_intake import IntakeServices, collect_platform_assignment

TASK_REF = {
    "connection_id": "connection-1",
    "class_id": "course-1",
    "assignment_id": "assignment-1",
}


class _Study:
    def view(self):
        return {
            "assignments": [{"ref": TASK_REF, "platform": "quera", "title": "نمونه"}],
            "classes": [{
                "ref": {"connection_id": "connection-1", "class_id": "course-1"},
                "title": "درس نمونه",
            }],
        }


class _Manager:
    def __init__(self, result):
        self.result = result

    def observe(self, _connection_id, _request):
        return self.result


def _services(result):
    return IntakeServices(
        load_legacy=lambda _data: None,
        attempt_captcha=lambda *_args: {},
        study_context=lambda _data: _Study(),
        manager_factory=lambda *_args, **_kwargs: _Manager(result),
    )


def test_platform_assignment_failure_preserves_only_a_known_diagnostic_category():
    result = collect_platform_assignment(
        {"task_ref": TASK_REF}, services=_services({
            "status": "unavailable", "failure_kind": "unexpected_response",
            "message": "raw server response must not leave the adapter",
        }),
    )

    assert result == {"status": "unavailable", "failure_kind": "unexpected_response"}


def test_platform_assignment_failure_drops_unknown_diagnostic_values():
    result = collect_platform_assignment(
        {"task_ref": TASK_REF}, services=_services({
            "status": "unavailable", "failure_kind": "server-body: private details",
        }),
    )

    assert result == {"status": "unavailable"}
