"""Drive the captcha loop against a fake client, with OCR on and off.

The loop is where this feature actually lives, and it is three states deep, so this
exercises the order of events: does it read before asking, does a wrong reading
re-submit with a fresh image, and does a split vote never reach the site at all.

`tesseract_path` and `_read_once` are stubbed, so no OCR engine is needed. The image
is a real generated PNG, because the reader's first act is to sanity-check the shape
of the file it was handed — a fake byte string would be rejected before the interesting
code ran, and the test would pass for the wrong reason.
"""

import builtins
from pathlib import Path

import pytest

from cwtrack import api, auth, captcha
from cwtrack.client import CwError

# tests/ has no __init__.py, so this is a sibling import rather than a relative one.
from test_captcha import make_captcha


def _page(has_captcha=True):
    token = '<input name="logintoken" value="TOK">'
    plug = "local_logincaptcha" if has_captcha else ""
    return "<html><form>{}</form><script>{}</script></html>".format(token, plug)


class FakeClient:
    """Rejects any captcha except `accept`, and invalidates it once used, the way the
    real site does. That is what makes a retry loop a real loop."""

    def __init__(self, accept="GOOD", page=None, image: Path | None = None):
        self.page = page if page is not None else _page()
        self.accept = accept
        self.image = image
        self.posts = []
        self.spent = set()

    def get(self, path, params=None):
        return self.page

    def get_bytes(self, path, params=None):
        return self.image.read_bytes() if self.image else b""

    def post(self, path, data):
        self.posts.append(dict(data))
        given = data.get("logincaptcha")
        if given == self.accept and given not in self.spent:
            self.spent.add(given)
            return "<html>ok</html>"
        return self.page.replace("</form>", "<p>captchaincorrect</p></form>")

    def logged_in(self):
        return bool(self.posts) and self.posts[-1].get("logincaptcha") == self.accept


@pytest.fixture
def png(tmp_path) -> Path:
    """A captcha-shaped PNG the reader will accept."""
    return make_captcha(tmp_path / "challenge.png", "ABCDE", seed=5, difficulty=0.5)


@pytest.fixture
def harness(monkeypatch, png):
    """Install a fake client and credentials, and make any prompt a test failure."""
    monkeypatch.setenv("CW_USER", "00000000")
    monkeypatch.setenv("CW_PASS", "x")
    monkeypatch.delenv("CW_OCR", raising=False)

    def install(client: FakeClient, readings: dict | None = None):
        monkeypatch.setattr("cwtrack.client.Client", lambda *a, **k: client)
        monkeypatch.setattr(captcha, "tesseract_path", lambda: "fake")

        def read(binary, image, psm):
            for key, value in (readings or {}).items():
                if key in Path(image).stem:
                    return value
            return "", 0.0

        monkeypatch.setattr(captcha, "_read_once", read)

        def refuse(*a, **k):
            raise AssertionError("prompted, but the readings should have decided")

        monkeypatch.setattr(auth, "input", refuse, raising=False)
        monkeypatch.setattr(builtins, "input", refuse)
        return client

    return install


def _agreeing(text: str) -> dict:
    """Every variant reads the same thing — the case that should submit."""
    return dict.fromkeys(("crop", "big", "med_pad", "sharp", "otsu"), (text, 90.0))


class TestItReadsBeforeAsking:
    def test_a_correct_reading_logs_in_without_asking(self, harness, tmp_path, png):
        client = harness(FakeClient(accept="ABCDE", image=png), _agreeing("ABCDE"))
        state = api._attempt_captcha(client, "u", "p", tmp_path, None)
        assert state["status"] == auth.OK
        assert [p["logincaptcha"] for p in client.posts] == ["ABCDE"]

    def test_a_wrong_reading_comes_back_with_a_fresh_image(self, harness, tmp_path, png):
        """The dangerous path, and the reason the gate exists.

        The engine is confident and wrong. The result must still be a readable
        challenge, and the reason must be recorded — a silent wrong submission here
        would look to the user like a broken password.
        """
        client = harness(FakeClient(accept="NEVER", image=png), _agreeing("ABCDE"))
        state = api._attempt_captcha(client, "u", "p", tmp_path, None)
        assert state["status"] == auth.CAPTCHA_REJECTED
        assert state["ocr"]["reason"] == "rejected_by_site"
        assert state["image"].is_file()
        assert state["viewer"].is_file()

    def test_a_split_vote_never_reaches_the_site(self, harness, tmp_path, png):
        client = harness(FakeClient(accept="ABCDE", image=png), {
            "crop": ("ABCDE", 90.0), "big": ("ZZZZZ", 50.0),
            "med_pad": ("YYYYY", 40.0), "sharp": ("WWWWW", 35.0),
            "otsu": ("VVVVV", 30.0),
        })
        state = api._attempt_captcha(client, "u", "p", tmp_path, None)
        assert state["status"] == auth.CAPTCHA_REQUIRED
        assert client.posts == [], "a split vote must not be submitted"
        assert state["ocr"]["reason"] == "low_agreement"

    def test_confidence_alone_does_not_submit(self, harness, tmp_path, png):
        """One variant at 99.0 and four at 10.0 is not a belief, whatever the score."""
        client = harness(FakeClient(accept="ABCDE", image=png), {
            "crop": ("ABCDE", 99.0), "big": ("ZZZZZ", 12.0),
            "med_pad": ("YYYYY", 11.0), "sharp": ("WWWWW", 10.0),
            "otsu": ("VVVVV", 9.0),
        })
        state = api._attempt_captcha(client, "u", "p", tmp_path, None)
        assert state["status"] == auth.CAPTCHA_REQUIRED
        assert client.posts == []


class TestTheHumanAlwaysWins:
    def test_a_given_answer_is_used_verbatim(self, harness, tmp_path, png):
        """The OCR never second-guesses a person, however sure it is."""
        client = harness(FakeClient(accept="HUMAN", image=png), _agreeing("ABCDE"))
        state = api._attempt_captcha(client, "u", "p", tmp_path, "HUMAN")
        assert state["status"] == auth.OK
        assert client.posts[0]["logincaptcha"] == "HUMAN"
        assert len(client.posts) == 1, "an answer was supplied, so no reading was needed"

    def test_a_wrong_human_answer_gets_a_new_challenge(self, harness, tmp_path, png):
        """So the retry the skill performs is a different puzzle, not the same one."""
        client = harness(FakeClient(accept="RIGHT", image=png), _agreeing("ABCDE"))
        state = api._attempt_captcha(client, "u", "p", tmp_path, "WRONG")
        assert state["status"] == auth.CAPTCHA_REJECTED
        assert state["image"].is_file()


class TestNothingBreaks:
    def test_disabled_means_the_engine_is_not_even_looked_for(
        self, monkeypatch, harness, tmp_path, png
    ):
        monkeypatch.setenv("CW_OCR", "0")
        client = harness(FakeClient(accept="HUMAN", image=png))
        monkeypatch.setattr(
            captcha, "tesseract_path",
            lambda: (_ for _ in ()).throw(AssertionError("looked for the engine")),
        )
        state = api._attempt_captcha(client, "u", "p", tmp_path, None)
        assert state["status"] == auth.CAPTCHA_REQUIRED
        assert "ocr" not in state, "disabled is not a failure, it is not a thing"

    def test_no_engine_installed_is_quiet(self, monkeypatch, harness, tmp_path, png):
        client = harness(FakeClient(accept="HUMAN", image=png))

        def absent():
            raise captcha.OcrUnavailable("not installed")

        monkeypatch.setattr(captcha, "tesseract_path", absent)
        state = api._attempt_captcha(client, "u", "p", tmp_path, None)
        assert state["status"] == auth.CAPTCHA_REQUIRED
        assert state["ocr"]["reason"] == "unavailable"

    def test_an_engine_that_throws_does_not_take_the_login_down(
        self, monkeypatch, harness, tmp_path, png
    ):
        client = harness(FakeClient(accept="HUMAN", image=png))

        def explode(*a, **k):
            raise OSError("engine died")

        monkeypatch.setattr(captcha, "guess", explode)
        state = api._attempt_captcha(client, "u", "p", tmp_path, None)
        assert state["status"] == auth.CAPTCHA_REQUIRED
        assert state["image"].is_file()

    def test_no_pillow_is_reported_not_raised(self, monkeypatch, harness, tmp_path, png):
        """The `ocr` extra absent is a configuration fact, not a crash."""
        client = harness(FakeClient(accept="HUMAN", image=png), _agreeing("ABCDE"))

        real_import = builtins.__import__

        def no_pillow(name, *a, **k):
            if name.startswith("PIL"):
                raise ImportError("no Pillow")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", no_pillow)
        state = api._attempt_captcha(client, "u", "p", tmp_path, None)
        assert state["status"] == auth.CAPTCHA_REQUIRED
        assert state["ocr"]["reason"] == "no_pillow"


class TestTheCliPath:
    def test_a_successful_reading_skips_the_prompt(self, monkeypatch, tmp_path, capsys):
        """The CLI's own loop, so both entry points behave the same on the feature."""
        client = FakeClient(accept="ABCDE",
                            image=make_captcha(tmp_path / "c.png", "ABCDE", 5, 0.5))
        monkeypatch.setattr(auth, "input", lambda p: "SHOULD NOT BE ASKED",
                            raising=False)
        monkeypatch.setattr(captcha, "tesseract_path", lambda: "fake")
        monkeypatch.setattr(
            captcha, "_read_once",
            lambda b, i, p: ("ABCDE", 90.0),
        )
        auth.do_login(client, "u", "p", tmp_path)
        out = capsys.readouterr().out
        assert "ABCDE" in out
        assert client.logged_in()

    def test_the_engine_gets_only_one_attempt(self, monkeypatch, tmp_path):
        """Even when every image disagrees with reality, the loop must terminate.

        The cap is the point. Without it this is an infinite retry against a login
        endpoint, which is worse than the human prompt it replaced.
        """
        client = FakeClient(accept="NEVER",
                            image=make_captcha(tmp_path / "c.png", "ABCDE", 5, 0.5))
        monkeypatch.setattr(builtins, "input", lambda prompt: "ALSO WRONG")
        monkeypatch.setattr(captcha, "tesseract_path", lambda: "fake")
        monkeypatch.setattr(captcha, "_read_once", lambda b, i, p: ("ABCDE", 92.0))

        with pytest.raises(CwError):
            # Bounded by the loop giving up, not by this timeout.
            auth.do_login(client, "u", "p", tmp_path)

        posted = [p.get("logincaptcha") for p in client.posts]
        assert posted.count("ABCDE") == 1, "the engine must not retry per image"
        assert "ALSO WRONG" in posted

    def test_a_rejected_reading_hands_back_to_the_prompt(
        self, monkeypatch, tmp_path, capsys
    ):
        """After the engine tries and fails, the human is asked — and told why.

        The engine is stubbed to always answer "ABCDE" and the site only accepts
        "HUMAN", so the reading is confidently wrong every time. That is the case the
        gate cannot catch and this test is here for.
        """
        client = FakeClient(accept="HUMAN",
                            image=make_captcha(tmp_path / "c.png", "ABCDE", 5, 0.5))
        asked = []

        def prompt(text):
            asked.append(text)
            return "HUMAN"

        # `ask` reads the builtin, so patch that rather than a name on the module.
        monkeypatch.setattr(builtins, "input", prompt)
        monkeypatch.setattr(captcha, "tesseract_path", lambda: "fake")
        monkeypatch.setattr(captcha, "_read_once", lambda b, i, p: ("ABCDE", 92.0))

        auth.do_login(client, "u", "p", tmp_path)
        out = capsys.readouterr().out

        assert asked, "the human should have been asked after the reading was rejected"
        # And it says the reading failed, so a wrong guess is visible rather than
        # looking like a wrong password.
        assert "پیشنهاد هم درست نبود" in out
        # The engine gets exactly one attempt, then the human answers. Asserted as a
        # count because "one attempt, ever" is the property: a per-image retry loop is
        # the failure this feature could inflict, since a second read of the same glyphs
        # is very likely the same mistake.
        assert [p.get("logincaptcha") for p in client.posts] == ["ABCDE", "HUMAN"]
        assert client.logged_in()
