from __future__ import annotations

from pathlib import Path

from cwtrack.platforms.cw import CWAdapter
from cwtrack.platforms.quera import QueraAdapter, QueraHTTPClient


class FakeCwClient:
    def __init__(self, base):
        self.base = base
        self.cookies = {"MoodleSession": "private-cookie"}

    def import_cookies(self, cookies):
        self.cookies = dict(cookies)

    def export_cookies(self):
        return dict(self.cookies)

    def logged_in(self):
        return True

    def get(self, path, params=None):
        if path == "/my/courses.php":
            return '<a href="/course/view.php?id=101">Algorithms</a>'
        if path == "/course/view.php" and params == {"id": 101}:
            fixture = Path(__file__).parent / "fixtures" / "course_90000_assign.html"
            return fixture.read_text(encoding="utf-8")
        if path == "/mod/assign/index.php" and params == {"id": 101}:
            fixture = Path(__file__).parent / "fixtures" / "course_90000_assign.html"
            return fixture.read_text(encoding="utf-8")
        raise AssertionError((path, params))


def test_cw_adapter_observes_classes_and_assignments_with_a_private_session(tmp_path):
    adapter = CWAdapter(
        {
            "id": "cw-account",
            "platform": "cw",
            "origin": "https://cw.sharif.ir",
        },
        client_factory=FakeCwClient,
        challenge_root=tmp_path,
        clock=lambda: "2026-10-17T12:00:00+03:30",
    )

    classes = adapter.observe(
        {"scope": "classes"},
        {"credentials": {"username": "student", "password": "private"}},
    )
    class_ref = classes["observation"]["nodes"][0]["ref"]
    assignments = adapter.observe(
        {"scope": "assignments", "class_ref": class_ref},
        {
            "credentials": {"username": "student", "password": "private"},
            "session": classes["private_state"],
        },
    )

    assert classes["status"] == "ok"
    assert classes["observation"]["coverage"] == "complete"
    assert class_ref == {"connection_id": "cw-account", "class_id": "101"}
    assert classes["private_state"]["cookies"] == {"MoodleSession": "private-cookie"}
    assert assignments["status"] == "ok"
    assert assignments["observation"]["coverage"] == "complete"
    assert assignments["observation"]["nodes"][0]["ref"] == {
        "connection_id": "cw-account",
        "class_id": "101",
        "assignment_id": "90001",
    }
    assert assignments["observation"]["nodes"][0]["submission"]["state"]


def test_cw_assignment_unrecognized_page_has_a_safe_failure_kind(tmp_path):
    class UnexpectedAssignmentPage(FakeCwClient):
        def get(self, path, params=None):
            if path == "/course/view.php":
                return "<html><body>unrecognized page</body></html>"
            return super().get(path, params)

    adapter = CWAdapter(
        {"id": "cw-account", "platform": "cw", "origin": "https://cw.sharif.ir"},
        client_factory=UnexpectedAssignmentPage,
        challenge_root=tmp_path,
        clock=lambda: "2026-10-17T12:00:00+03:30",
    )
    result = adapter.observe(
        {"scope": "assignments", "class_ref": {"connection_id": "cw-account", "class_id": "101"}},
        {"credentials": {"username": "student", "password": "private"}},
    )

    assert result["observation"]["status"] == "unavailable"
    assert result["observation"]["failure_kind"] == "unexpected_response"


def test_cw_assignments_are_read_from_the_course_page_after_legacy_index_redirects(tmp_path):
    clients = []

    class CoursePageClient(FakeCwClient):
        def __init__(self, base):
            super().__init__(base)
            self.requests = []
            clients.append(self)

        def get(self, path, params=None):
            self.requests.append((path, params))
            if path == "/mod/assign/index.php":
                return '<html><body><h1>Course overview</h1></body></html>'
            if path == "/course/view.php" and params == {"id": 101}:
                return '''
                    <html lang="fa" dir="rtl"><body>
                    <h1>نمونه درس</h1>
                    <ul data-for="course_sectionlist">
                      <li class="activity assign modtype_assign hasinfo">
                        <a href="/mod/assign/view.php?id=90001">تکلیف نمونه</a>
                        <p><strong>مهلت:</strong> 2026-11-01, 23:59</p>
                      </li>
                    </ul></body></html>
                '''
            if path == "/mod/assign/view.php" and params == {"id": 90001}:
                return (
                    "<table><tr><th>Submission status</th><td>No submission</td></tr>"
                    "<tr><th>Grade</th><td>-</td></tr></table>"
                )
            return super().get(path, params)

    adapter = CWAdapter(
        {"id": "cw-account", "platform": "cw", "origin": "https://cw.sharif.ir"},
        client_factory=CoursePageClient,
        challenge_root=tmp_path,
        clock=lambda: "2026-10-17T12:00:00+03:30",
    )
    result = adapter.observe(
        {"scope": "assignments", "class_ref": {"connection_id": "cw-account", "class_id": "101"}},
        {"credentials": {"username": "student", "password": "private"}},
    )

    assert result["observation"]["status"] == "ok"
    assert result["observation"]["coverage"] == "complete"
    assert result["observation"]["nodes"][0]["ref"]["assignment_id"] == "90001"
    assert result["observation"]["nodes"][0]["submission"]["state"] == "No submission"
    assert result["observation"]["nodes"][0]["evaluation"]["grade"] == "-"
    assert ("/course/view.php", {"id": 101}) in clients[0].requests
    assert not any(path == "/mod/assign/index.php" for path, _ in clients[0].requests)
    assert result["observation"]["nodes"][0]["deadlines"][0]["at"].startswith("2026-11-01")


def test_cw_course_page_with_unrelated_empty_table_is_not_complete_assignment_coverage(tmp_path):
    class UnrelatedTableClient(FakeCwClient):
        def get(self, path, params=None):
            if path == "/course/view.php":
                return "<html><table class='generaltable'><tr><th>Topic</th></tr></table></html>"
            return super().get(path, params)

    adapter = CWAdapter(
        {"id": "cw-account", "platform": "cw", "origin": "https://cw.sharif.ir"},
        client_factory=UnrelatedTableClient,
        challenge_root=tmp_path,
        clock=lambda: "2026-10-17T12:00:00+03:30",
    )
    result = adapter.observe(
        {"scope": "assignments", "class_ref": {"connection_id": "cw-account", "class_id": "101"}},
        {"credentials": {"username": "student", "password": "private"}},
    )

    assert result["observation"]["status"] == "unavailable"
    assert result["observation"]["failure_kind"] == "unexpected_response"


def test_cw_course_page_with_assignment_table_header_can_confirm_empty_list(tmp_path):
    class EmptyAssignmentTableClient(FakeCwClient):
        def get(self, path, params=None):
            if path == "/course/view.php":
                return (
                    "<html><table><thead><tr><th>Name</th><th>Due</th>"
                    "<th>Status</th></tr></thead><tbody></tbody></table></html>"
                )
            return super().get(path, params)

    adapter = CWAdapter(
        {"id": "cw-account", "platform": "cw", "origin": "https://cw.sharif.ir"},
        client_factory=EmptyAssignmentTableClient,
        challenge_root=tmp_path,
        clock=lambda: "2026-10-17T12:00:00+03:30",
    )
    result = adapter.observe(
        {"scope": "assignments", "class_ref": {"connection_id": "cw-account", "class_id": "101"}},
        {"credentials": {"username": "student", "password": "private"}},
    )

    assert result["observation"]["status"] == "ok"
    assert result["observation"]["coverage"] == "complete"
    assert result["observation"]["nodes"] == []


def test_cw_complete_course_activity_list_without_assign_modules_is_complete_empty(tmp_path):
    class NoAssignmentActivityClient(FakeCwClient):
        def get(self, path, params=None):
            if path == "/course/view.php":
                return (
                    '<html><h1>Course</h1><ul data-for="course_sectionlist">'
                    '<li class="course-section"><li class="activity forum modtype_forum">'
                    '</li></li></ul></html>'
                )
            return super().get(path, params)

    adapter = CWAdapter(
        {"id": "cw-account", "platform": "cw", "origin": "https://cw.sharif.ir"},
        client_factory=NoAssignmentActivityClient,
        challenge_root=tmp_path,
        clock=lambda: "2026-10-17T12:00:00+03:30",
    )
    result = adapter.observe(
        {"scope": "assignments", "class_ref": {"connection_id": "cw-account", "class_id": "101"}},
        {"credentials": {"username": "student", "password": "private"}},
    )

    assert result["observation"]["status"] == "ok"
    assert result["observation"]["coverage"] == "complete"
    assert result["observation"]["nodes"] == []


def test_cw_partial_class_scan_identifies_the_unreadable_course(tmp_path):
    class MissingTitleClient(FakeCwClient):
        def get(self, path, params=None):
            if path == "/my/courses.php":
                return (
                    '<a href="/course/view.php?id=101">Algorithms</a>'
                    '<a href="/course/view.php?id=102">Databases</a>'
                )
            if path == "/course/view.php" and params == {"id": 102}:
                return "<html><title>Unexpected page</title></html>"
            return super().get(path, params)

    adapter = CWAdapter(
        {"id": "cw-account", "platform": "cw", "origin": "https://cw.sharif.ir"},
        client_factory=MissingTitleClient,
        challenge_root=tmp_path,
        clock=lambda: "2026-10-17T12:00:00+03:30",
    )

    result = adapter.observe(
        {"scope": "classes"},
        {"session": {"cookies": {"MoodleSession": "private-cookie"}}},
    )

    assert result["status"] == "ok"
    assert result["observation"]["status"] == "partial"
    assert result["observation"]["failure"] == {
        "course_id": "102",
        "reason": "course_title_not_found",
    }


def test_cw_class_inventory_does_not_depend_on_assignment_index(tmp_path):
    class AssignmentIndexUnavailableClient(FakeCwClient):
        def get(self, path, params=None):
            if path == "/my/courses.php":
                return '<a href="/course/view.php?id=101">Algorithms</a>'
            if path == "/course/view.php" and params == {"id": 101}:
                return "<html><h1>Algorithms</h1></html>"
            if path == "/mod/assign/index.php":
                raise OSError("this course has no assignment index")
            return super().get(path, params)

    adapter = CWAdapter(
        {"id": "cw-account", "platform": "cw", "origin": "https://cw.sharif.ir"},
        client_factory=AssignmentIndexUnavailableClient,
        challenge_root=tmp_path,
        clock=lambda: "2026-10-17T12:00:00+03:30",
    )

    result = adapter.observe(
        {"scope": "classes"},
        {"session": {"cookies": {"MoodleSession": "private-cookie"}}},
    )

    assert result["observation"]["status"] == "ok"
    assert result["observation"]["coverage"] == "complete"
    assert result["observation"]["nodes"][0]["title"] == "Algorithms"


class FakeQueraClient:
    def __init__(self, base):
        self.base = base
        self.cookies = [{"name": "csrf", "value": "private"}]
        self.calls = []

    def import_cookies(self, cookies):
        self.cookies = list(cookies)

    def export_cookies(self):
        return list(self.cookies)

    def get(self, path):
        self.calls.append(("get", path))
        return "https://quera.org/accounts/login", "<html>login</html>"

    def post_json(self, path, payload):
        self.calls.append(("post", path, payload))
        return {"next_step": "otp", "user_wait": 45}


def test_quera_assignment_unrecognized_page_has_a_safe_failure_kind(tmp_path):
    class UnexpectedCoursePage:
        def __init__(self, base):
            self.base = base

        def import_cookies(self, cookies):
            self.cookies = cookies

        def export_cookies(self):
            return []

        def get(self, path):
            if path == "/course/":
                return "https://quera.org/course/", (
                    '<script id="__NEXT_DATA__">'
                    '{"props":{"pageProps":{"globalServerValues":'
                    '{"currentUser":{"is_authenticated":true}}}}}</script>'
                )
            return "https://quera.org/course/123/", "<html>unrecognized</html>"

    adapter = QueraAdapter(
        {"id": "quera-account", "platform": "quera", "origin": "https://quera.org"},
        client_factory=UnexpectedCoursePage,
        clock=lambda: "2026-10-17T12:00:00+03:30",
    )
    result = adapter.observe(
        {"scope": "assignments", "class_ref": {"connection_id": "quera-account", "class_id": "123"}},
        {"credentials": {"username": "student", "password": "private"}},
    )

    assert result["status"] == "unavailable"
    assert result["failure_kind"] == "unexpected_response"
    assert result["observation"]["failure_kind"] == "unexpected_response"


def test_quera_login_returns_a_resumable_otp_challenge_without_secrets(tmp_path):
    clients = []

    def make_client(base):
        client = FakeQueraClient(base)
        clients.append(client)
        return client

    adapter = QueraAdapter(
        {
            "id": "quera-account",
            "platform": "quera",
            "origin": "https://quera.org",
        },
        client_factory=make_client,
        clock=lambda: "2026-10-17T12:00:00+03:30",
    )

    result = adapter.observe(
        {"scope": "classes"},
        {"credentials": {"username": "student@example.test", "password": "private"}},
    )

    assert result["status"] == "challenge_required"
    assert result["challenge"]["kind"] == "otp"
    assert result["challenge"]["display"]["user_wait"] == 45
    assert result["private_state"]["credentials"]["password"] == "private"
    assert "password" not in repr(result["challenge"])
    assert clients[0].calls[-1][1] == "/accounts/api/login/"
    assert clients[0].calls[-1][2] == {
        "identifier": "student@example.test",
        "captcha_token": "",
        "preferred_process": "password",
    }


def test_quera_recaptcha_is_reported_as_interactive_not_readable(tmp_path):
    class CaptchaClient(FakeQueraClient):
        def post_json(self, path, payload):
            return {
                "_http_status": 400,
                "recaptcha_site_key": "public-key",
                "recaptcha_domain": "quera.org",
            }

    adapter = QueraAdapter(
        {
            "id": "quera-account",
            "platform": "quera",
            "origin": "https://quera.org",
        },
        client_factory=CaptchaClient,
        clock=lambda: "2026-10-17T12:00:00+03:30",
    )

    result = adapter.observe(
        {"scope": "classes"},
        {"credentials": {"username": "student@example.test", "password": "private"}},
    )

    assert result["status"] == "challenge_required"
    assert result["challenge"]["kind"] == "interactive"
    assert "image" not in result["challenge"]["display"]
    assert result["private_state"]["request"] == {"scope": "classes"}

    resumed = adapter.resume(
        {
            "request": {"scope": "classes"},
            "credentials": {"username": "student@example.test", "password": "private"},
        },
        {"kind": "interactive_completed"},
    )
    assert resumed == {"status": "challenge_unavailable"}


def test_quera_class_links_are_scoped_to_the_authenticated_connection():
    class AuthenticatedClient:
        def __init__(self, base):
            self.base = base

        def import_cookies(self, cookies):
            pass

        def export_cookies(self):
            return [{"name": "session", "value": "private"}]

        def get(self, path):
            assert path == "/course/"
            return "https://quera.org/course/", (
                '<script id="__NEXT_DATA__">'
                '{"props":{"pageProps":{"globalServerValues":'
                '{"currentUser":{"is_authenticated":true}}}}}</script>'
                '<a href="/course/db101/">'
                '<style>.css-title{padding:0;}</style>'
                '<span>پایگاه داده</span>'
                '<script>client-side metadata</script>'
                '</a>'
            )

    adapter = QueraAdapter(
        {"id": "quera-account", "platform": "quera", "origin": "https://quera.org"},
        client_factory=AuthenticatedClient,
        clock=lambda: "2026-10-17T12:00:00+03:30",
    )

    result = adapter.observe(
        {"scope": "classes"},
        {"session": {"cookies": [{"name": "session", "value": "private"}]}},
    )

    assert result["status"] == "ok"
    assert result["observation"]["coverage"] == "complete"
    assert result["observation"]["nodes"] == [{
        "kind": "class",
        "ref": {"connection_id": "quera-account", "class_id": "db101"},
        "title": "پایگاه داده",
        "url": "https://quera.org/course/db101/",
    }]


def test_quera_reads_assignments_from_the_authenticated_course_page():
    class AuthenticatedClient:
        def __init__(self, base):
            self.base = base
            self.calls = []

        def import_cookies(self, cookies):
            pass

        def export_cookies(self):
            return [{"name": "session", "value": "private"}]

        def get(self, path):
            self.calls.append(path)
            if path == "/course/":
                return "https://quera.org/course/", (
                    '<script id="__NEXT_DATA__">'
                    '{"props":{"pageProps":{"globalServerValues":'
                    '{"currentUser":{"is_authenticated":true}}}}}</script>'
                )
            assert path == "/course/db101"
            return "https://quera.org/course/db101", (
                '<script id="__NEXT_DATA__">'
                '{"props":{"pageProps":{"globalServerValues":'
                '{"currentUser":{"is_authenticated":true}},"course":'
                '{"id":"db101","name":"پایگاه داده",'
                '"assignments":[{"pk":781,"name":"تمرین اول",'
                '"start_time":"2026-10-01T00:00:00Z",'
                '"finish_time":"2026-10-20T20:30:00Z",'
                '"problem_count":2,"state":"PUBLISHED"}]}}}}</script>'
            )

    clients = []

    def make_client(base):
        client = AuthenticatedClient(base)
        clients.append(client)
        return client

    adapter = QueraAdapter(
        {"id": "quera-account", "platform": "quera", "origin": "https://quera.org"},
        client_factory=make_client,
        clock=lambda: "2026-10-17T12:00:00+03:30",
    )

    result = adapter.observe(
        {
            "scope": "assignments",
            "class_ref": {"connection_id": "quera-account", "class_id": "db101"},
        },
        {"session": {"cookies": [{"name": "session", "value": "private"}]}},
    )

    assert result["status"] == "ok", result
    assert result["observation"]["coverage"] == "complete"
    assert clients[0].calls == ["/course/", "/course/db101"]
    assert result["observation"]["nodes"] == [{
        "kind": "assignment",
        "ref": {
            "connection_id": "quera-account",
            "class_id": "db101",
            "assignment_id": "781",
        },
        "title": "تمرین اول",
        "url": "https://quera.org/course/assignments/781/problems",
        "submission": {"state": "unknown", "raw": ""},
        "evaluation": {"state": "unknown", "grade": None},
        "deadlines": [{
            "kind": "regular",
            "at": "2026-10-20T20:30:00Z",
            "raw": "2026-10-20T20:30:00Z",
        }],
    }]


def test_quera_assignment_list_count_mismatch_stays_incomplete():
    class AuthenticatedClient:
        def __init__(self, base):
            self.base = base

        def import_cookies(self, cookies):
            pass

        def export_cookies(self):
            return []

        def get(self, path):
            return "https://quera.org/course/db101/", (
                '<script id="__NEXT_DATA__">'
                '{"props":{"pageProps":{"globalServerValues":'
                '{"currentUser":{"is_authenticated":true}},"course":'
                '{"id":"db101","assignment_count":2,"assignments":[]}}}}</script>'
            )

    adapter = QueraAdapter(
        {"id": "quera-account", "platform": "quera", "origin": "https://quera.org"},
        client_factory=AuthenticatedClient,
        clock=lambda: "2026-10-17T12:00:00+03:30",
    )

    result = adapter.observe(
        {
            "scope": "assignments",
            "class_ref": {"connection_id": "quera-account", "class_id": "db101"},
        },
        {"session": {"cookies": []}},
    )

    assert result["status"] == "unavailable"
    assert result["observation"]["coverage"] == "incomplete"
    assert result["observation"]["nodes"] == []


def test_quera_assignment_detail_returns_the_published_problem_prompt():
    class AuthenticatedClient:
        def __init__(self, base):
            self.base = base

        def import_cookies(self, cookies):
            pass

        def export_cookies(self):
            return []

        def get(self, path):
            if path == "/course/assignments/781/problems":
                return "https://quera.org" + path, (
                    '<title>تمرین اول - پایگاه داده</title>'
                    '<div id="description_md-358899">'
                    'صورت سؤال: کلید خارجی را توضیح دهید. '
                    '![نمودار](https://dns-sut.s3.ir-central1.arvanstorage.ir/course/schema.png) '
                    '[صورت تمرین](https://quera.org/assignment/781/get_pdf_file)'
                    '</div>'
                )
            if path == "/course/db101":
                return "https://quera.org" + path, (
                    '<a href="/course/db101/files/notes.pdf">جزوهٔ درس</a>'
                    '<script id="__NEXT_DATA__">'
                    '{"props":{"pageProps":{"course":{"id":"db101",'
                    '"lectures":[]}}}}</script>'
                )
            return "https://quera.org/course/", (
                '<script id="__NEXT_DATA__">'
                '{"props":{"pageProps":{"globalServerValues":'
                '{"currentUser":{"is_authenticated":true}}}}}</script>'
            )

        def download(self, url, folder):
            folder = Path(folder)
            folder.mkdir(parents=True, exist_ok=True)
            if "schema.png" in url:
                filename = "schema.png"
            elif "notes.pdf" in url:
                filename = "notes.pdf"
            else:
                filename = "assignment.pdf"
            path = folder / filename
            path.write_bytes(b"test attachment bytes")
            return str(path)

    adapter = QueraAdapter(
        {"id": "quera-account", "platform": "quera", "origin": "https://quera.org"},
        client_factory=AuthenticatedClient,
        clock=lambda: "2026-10-17T12:00:00+03:30",
    )

    result = adapter.observe(
        {
            "scope": "assignment_detail",
            "task_ref": {
                "connection_id": "quera-account",
                "class_id": "db101",
                "assignment_id": "781",
            },
            "assignment": {"title": "تمرین اول"},
        },
        {"session": {"cookies": []}},
    )

    assert result["status"] == "ok"
    assert result["observation"]["scope"] == "assignment_detail"
    assert result["observation"]["input"]["prompt"] == (
        "صورت سؤال: کلید خارجی را توضیح دهید. "
        "![نمودار](https://dns-sut.s3.ir-central1.arvanstorage.ir/course/schema.png) "
        "[صورت تمرین](https://quera.org/assignment/781/get_pdf_file)"
    )
    assert [item["role"] for item in result["observation"]["input"]["attachments"]] == [
        "material", "prompt"
    ]
    assert [Path(item["path"]).name for item in result["observation"]["input"]["attachments"]] == [
        "schema.png", "assignment.pdf"
    ]
    assert result["observation"]["input"]["course_materials_coverage"] == "complete"
    course_material = result["observation"]["input"]["course_materials"][0]
    assert course_material["title"] == "جزوهٔ درس"
    assert course_material["url"] == "https://quera.org/course/db101/files/notes.pdf"
    assert course_material["role"] == "material"
    assert Path(course_material["path"]).name == "notes.pdf"


def test_quera_course_material_scope_reports_visible_links_separately():
    class AuthenticatedClient:
        def __init__(self, base):
            self.base = base

        def import_cookies(self, cookies):
            pass

        def export_cookies(self):
            return []

        def get(self, path):
            return "https://quera.org/course/db101", (
                '<a href="/course/db101/files/notes.pdf">جزوهٔ درس</a>'
                '<script id="__NEXT_DATA__">'
                '{"props":{"pageProps":{"globalServerValues":'
                '{"currentUser":{"is_authenticated":true}},"course":'
                '{"id":"db101","lectures":[]}}}}</script>'
            )

        def download(self, url, folder):
            folder = Path(folder)
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / "notes.pdf"
            path.write_bytes(b"course notes")
            return str(path)

    adapter = QueraAdapter(
        {"id": "quera-account", "platform": "quera", "origin": "https://quera.org"},
        client_factory=AuthenticatedClient,
        clock=lambda: "2026-10-19T12:00:00+03:30",
    )

    result = adapter.observe(
        {
            "scope": "course_materials",
            "class_ref": {"connection_id": "quera-account", "class_id": "db101"},
        },
        {"session": {"cookies": []}},
    )

    assert result["status"] == "ok"
    observation = result["observation"]
    assert observation["scope"] == "course_materials"
    assert observation["coverage"] == "complete"
    assert observation["course_materials"][0]["title"] == "جزوهٔ درس"
    assert Path(observation["course_materials"][0]["path"]).read_bytes() == b"course notes"


def test_quera_asset_download_rejects_untrusted_hosts_before_network_access(tmp_path):
    client = QueraHTTPClient("https://quera.org")

    try:
        client.download("https://untrusted.example/file.pdf", tmp_path)
    except ValueError as exc:
        assert "not allowed" in str(exc)
    else:
        raise AssertionError("untrusted host should be rejected before download")


def test_quera_asset_download_persists_bounded_response_bytes(tmp_path):
    class Response:
        status = 200

        def geturl(self):
            return "https://quera.org/assignment/file.pdf"

        def read(self, limit):
            assert limit == 20 * 1024 * 1024 + 1
            return b"%PDF-fake response"

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == "https://quera.org/assignment/file.pdf"
            return Response()

    client = QueraHTTPClient("https://quera.org")
    client.opener = Opener()

    path = Path(client.download("https://quera.org/assignment/file.pdf", tmp_path))

    assert path.suffix == ".pdf"
    assert path.read_bytes() == b"%PDF-fake response"
