"""Automatic CAPTCHA rounds through the three approved login interfaces."""

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

Image = pytest.importorskip("PIL.Image", reason="CAPTCHA fixtures need Pillow")

from cwtrack import api, auth, captcha
from cwtrack.platforms.cw import CWAdapter
from test_captcha import make_captcha


class MemoryVault:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def put(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


class Moodle:
    def __init__(self, image, success_on=10):
        self.image = image
        self.success_on = success_on
        self.authenticated = False
        self.images = []
        self.posts = []

    def logged_in(self):
        return self.authenticated

    def import_cookies(self, cookies):
        pass

    def export_cookies(self):
        return {"MoodleSession": "test-session"}

    def get(self, path, params=None):
        if path == "/login/index.php":
            return '<input name="logintoken" value="TOKEN"><script>local_logincaptcha</script>'
        if path == "/my/courses.php":
            return '<a href="/course/view.php?id=101">Course</a>'
        if path == "/course/view.php":
            return "<html><h1>Course</h1></html>"
        if path == "/my/":
            return "<html></html>"
        if path == "/mod/assign/index.php":
            return (Path(__file__).parent / "fixtures/course_90000_assign.html").read_text(encoding="utf-8")
        raise AssertionError(path)

    def get_bytes(self, path, params=None):
        with Image.open(self.image) as source:
            image = source.convert("RGB")
        image.putpixel((0, 0), (len(self.images), 0, 0))
        stream = BytesIO()
        image.save(stream, format="PNG")
        data = stream.getvalue()
        self.images.append(data)
        return data

    def post(self, path, data):
        self.posts.append(dict(data))
        if self.success_on is not None and len(self.images) >= self.success_on:
            self.authenticated = data["logincaptcha"] == "ABCDE"
        return "ok" if self.authenticated else "<p>captchaincorrect</p>"


@pytest.fixture
def login_setup(monkeypatch, tmp_path):
    binary = tmp_path / "tesseract.exe"
    binary.touch()
    monkeypatch.setenv("CW_TESSERACT", str(binary))
    monkeypatch.setenv("CW_OCR", "1")
    image = make_captcha(tmp_path / "source.png", "ABCDE", seed=5, difficulty=0.5)
    client = Moodle(image)
    home, data = tmp_path / "home", tmp_path / "data"
    vault = MemoryVault()

    def run(args, **kwargs):
        row = "5\t1\t1\t1\t1\t1\t0\t0\t100\t30\t90\tABCDE"
        return SimpleNamespace(stdout="header\n" + row + "\n")

    monkeypatch.setattr(captcha.subprocess, "run", run)
    monkeypatch.setattr(api, "Client", lambda *a, **kw: client)
    monkeypatch.setattr(api, "_platform_adapters", lambda root: {
        "cw": lambda connection: CWAdapter(
            connection, client_factory=lambda base: client,
            challenge_root=root / "access-challenges",
            clock=lambda: "2026-10-19T12:00:00+03:30",
        )
    })
    api.access_configure("cw", {"username": "student", "password": "example"}, home=home, vault=vault)
    return client, home, data, vault


def test_shared_refresh_can_succeed_on_tenth_automatic_captcha(login_setup):
    client, home, data, vault = login_setup

    result = api.study_refresh(platforms=["cw"], home=home, data=data, vault=vault)

    assert result["status"] == "ok"
    assert len(client.posts) == 10
    assert len(set(client.images)) == 10
    assert api.study_view(data=data)["platform_assignments"]


def test_authenticated_session_is_saved_when_course_listing_fails(login_setup):
    client, home, data, vault = login_setup
    original_get = client.get

    def fail_course_listing(path, params=None):
        if path == "/my/courses.php":
            raise OSError("course listing unavailable")
        return original_get(path, params)

    client.get = fail_course_listing

    result = api.study_refresh(platforms=["cw"], home=home, data=data, vault=vault)

    assert result["status"] == "partial"
    assert result["targets"][0]["status"] == "unavailable"
    assert any(key.startswith("session:") for key in vault.values)


def test_shared_refresh_asks_user_after_ten_unreadable_fresh_captchas(login_setup, monkeypatch):
    client, home, data, vault = login_setup

    def split_readings(args, **kwargs):
        text = {"crop": "AAAAA", "big": "BBBBB", "med_pad": "CCCCC",
                "sharp": "DDDDD", "otsu": "EEEEE"}[Path(args[1]).stem]
        row = "5\t1\t1\t1\t1\t1\t0\t0\t100\t30\t90\t" + text
        return SimpleNamespace(stdout="header\n" + row + "\n")

    monkeypatch.setattr(captcha.subprocess, "run", split_readings)
    result = api.study_refresh(platforms=["cw"], home=home, data=data, vault=vault)

    action = result["actions"][0]
    diagnostic = action["challenge"]["display"]["ocr"]
    assert diagnostic["attempts"] == 10
    assert diagnostic["exhausted"] is True
    assert diagnostic["reason"] == "low_agreement"
    assert client.posts == []
    assert len(set(client.images)) == 11  # Ten OCR images and the user's fresh image.
    assert Path(action["challenge"]["display"]["image"]).read_bytes() == client.images[-1]


def test_legacy_refresh_can_succeed_on_tenth_automatic_captcha(login_setup):
    client, home, data, vault = login_setup

    result = api.refresh(home=home, data=data, user="student", password="example")

    assert result["status"] == "ok"
    assert len(client.posts) == 10
    assert result["assignments"] > 0


def test_terminal_can_succeed_on_tenth_captcha_without_prompt(login_setup, monkeypatch):
    client, home, data, vault = login_setup

    def unexpected_prompt(prompt):
        pytest.fail("Asked for CAPTCHA before the ten automatic rounds finished")

    monkeypatch.setattr("builtins.input", unexpected_prompt)
    auth.do_login(client, "student", "example", home)

    assert client.logged_in()
    assert len(client.posts) == 10


@pytest.mark.parametrize("interface", ["shared", "legacy", "terminal"])
def test_success_stops_automatic_rounds_immediately(interface, login_setup):
    client, home, data, vault = login_setup
    client.success_on = 1

    if interface == "shared":
        result = api.study_refresh(platforms=["cw"], home=home, data=data, vault=vault)
        assert result["status"] == "ok"
    elif interface == "legacy":
        result = api.refresh(home=home, data=data, user="student", password="example")
        assert result["status"] == "ok"
    else:
        auth.do_login(client, "student", "example", home)

    assert client.logged_in()
    assert len(client.images) == len(client.posts) == 1


def test_shared_rejected_readings_exhaust_ten_rounds_before_manual_action(login_setup):
    client, home, data, vault = login_setup
    client.success_on = None

    result = api.study_refresh(platforms=["cw"], home=home, data=data, vault=vault)

    diagnostic = result["actions"][0]["challenge"]["display"]["ocr"]
    assert diagnostic["attempts"] == 10
    assert diagnostic["exhausted"] is True
    assert diagnostic["reason"] == "rejected_by_site"
    assert len(client.posts) == 10
    assert len(set(client.images)) == 11


@pytest.mark.parametrize("reason", ["disabled", "unavailable"])
def test_shared_configuration_failure_is_reported_without_fake_retries(
    reason, login_setup, monkeypatch
):
    client, home, data, vault = login_setup
    if reason == "disabled":
        monkeypatch.setenv("CW_OCR", "0")
    else:
        monkeypatch.delenv("CW_TESSERACT")
        monkeypatch.setattr(captcha.shutil, "which", lambda binary: None)
        # Isolate the external installation lookup; CAPTCHA image paths still exist.
        original = Path.is_file
        monkeypatch.setattr(Path, "is_file", lambda p: False if p.name.startswith("tesseract") else original(p))

    result = api.study_refresh(platforms=["cw"], home=home, data=data, vault=vault)

    display = result["actions"][0]["challenge"]["display"]
    assert client.posts == []
    assert len(client.images) == 1
    if reason == "unavailable":
        assert display["ocr"]["reason"] == "unavailable"
    else:
        assert "ocr" not in display


def test_invalid_credentials_do_not_start_another_captcha_round(login_setup, monkeypatch):
    client, home, data, vault = login_setup

    def reject_credentials(path, data):
        client.posts.append(dict(data))
        return "<p>invalidlogin</p>"

    monkeypatch.setattr(client, "post", reject_credentials)
    result = api.refresh(home=home, data=data, user="student", password="wrong")

    assert result["status"] == "failed"
    assert len(client.posts) == len(client.images) == 1
