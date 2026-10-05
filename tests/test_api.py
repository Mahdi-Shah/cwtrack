"""The surface a skill drives.

The API exists for one caller — an agent, working from a shell, on the user's
machine. Three properties make that caller possible and each of them has been a real
blocker rather than a preference, so each has a test here that fails if it regresses:

- it never prompts, because `input()` from a shell with no terminal raises EOFError
  and produces an error telling the user to set an environment variable;
- it never prints, because Persian on a stock Windows console is cp1252 and the
  workaround was a temp file the agent had to remember to create;
- it never claims more than the store holds, because a missing store reported as
  "you have nothing due" is how a deadline gets missed.

Everything runs on the sanitised fixture. No network, no account, no real capture.
"""

from __future__ import annotations

import ast
import builtins
import io
import json
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from cwtrack import api, auth, parse, tracker
from cwtrack.client import CwError

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def store(tmp_path: Path, dump_dir, now) -> Path:
    """A populated store built from the sanitised fixture."""
    rows = [r.__dict__ if hasattr(r, "__dict__") else r
            for r in parse.parse_dump(dump_dir, now)]
    data = tmp_path / "cw-data"
    tracker.store(data, {"fullname": "Test", "username": "00000000", "userid": "1"}, rows)
    return data


class TestItNeverAsksAnything:
    """A prompt is the one thing this surface is not allowed to do."""

    @pytest.fixture(autouse=True)
    def _no_input(self, monkeypatch):
        def refuse(*a, **k):  # pragma: no cover - the point is that it never runs
            raise AssertionError("the API prompted; a skill has no terminal to answer")

        monkeypatch.setattr(builtins, "input", refuse)
        monkeypatch.setattr(auth, "input", refuse, raising=False)

    def test_reading_the_store_does_not_prompt(self, store):
        api.status(store)
        api.gaps_text(store)
        api.open_text(store)
        api.report_text(store)
        api.outstanding(store)
        api.paths(store)

    def test_reading_the_store_prints_nothing(self, store):
        """Returning a string and printing it are different contracts.

        The agent reads the return value; anything on stdout has already been through
        a codepage that cannot represent the answer.
        """
        buf = io.StringIO()
        with redirect_stdout(buf):
            api.status(store)
            api.gaps_text(store)
            api.open_text(store)
            api.report_text(store)
        assert buf.getvalue() == ""

    def test_the_source_contains_no_call_to_input(self):
        """Static, because a prompt added later would only show up on a live fetch.

        Parsed rather than grepped: the module docstring explains *why* there is no
        prompt, so it contains the word ``input()``, and a regex reads its own
        justification as a violation.
        """
        source = (ROOT / "src" / "cwtrack" / "api.py").read_text(encoding="utf-8")
        called = {
            node.func.id
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert not called & {"input", "getpass", "raw_input"}
        for banned in ("getpass", "sys.stdout"):
            assert banned not in called, banned


class TestAMissingStoreIsNotAnEmptyOne:
    def test_it_raises_rather_than_reporting_zero(self, tmp_path):
        with pytest.raises(CwError):
            api.status(tmp_path / "nowhere")

    def test_an_empty_store_raises_too(self, tmp_path):
        """An empty folder is not a store with nothing in it."""
        (tmp_path / "cw-data").mkdir()
        with pytest.raises(CwError):
            api.status(tmp_path / "cw-data")

    def test_the_error_names_the_path_it_looked_in(self, tmp_path):
        with pytest.raises(CwError) as e:
            api.status(tmp_path / "nowhere")
        assert "nowhere" in str(e.value)


class TestStatus:
    def test_counts_agree_with_the_stored_rows(self, store):
        s = api.status(store)
        _, items = tracker.load(store)
        assert s["counts"]["total"] == len(items)
        assert s["counts"]["open"] + s["counts"]["done"] == len(items)

    def test_urgent_leads_so_the_consequence_comes_first(self, store):
        """Ordering is the product here, so it is asserted rather than assumed."""
        s = api.status(store)
        assert set(s) >= {"counts", "urgent", "soon", "unscheduled", "unknown", "per_course"}
        assert s["counts"]["urgent"] == len(s["urgent"])

    def test_every_item_carries_the_human_countdown(self, store):
        """A caller narrating to a student should not reimplement the wording."""
        for item in api.status(store)["soon"]:
            assert item["remaining"]
            assert "مهلت" in item["remaining"] or "مانده" in item["remaining"]

    def test_unknown_is_reported_and_never_folded_into_done(self, store):
        """The refusal to guess has to be visible, or it is not a refusal."""
        rows = json.loads((store / "assignments.json").read_text(encoding="utf-8"))
        rows[0]["bucket"] = "unknown"
        (store / "assignments.json").write_text(
            json.dumps(rows, ensure_ascii=False), encoding="utf-8"
        )
        s = api.status(store)

        assert len(s["unknown"]) == 1
        assert s["unknown"][0]["bucket_fa"] != "ارسال شده"
        # The count a student reads must not include it: `done` is derived from the
        # open buckets, and an unrecognised status is deliberately not one.
        settled = sum(1 for r in rows if r["bucket"] in ("graded", "submitted"))
        assert s["counts"]["done"] == settled
        assert settled < s["counts"]["total"]

    def test_it_says_how_old_the_status_is(self, store):
        """Countdowns are live; the statuses are only as fresh as the last fetch."""
        assert api.status(store)["refreshed"]

    def test_the_store_path_is_reported(self, store):
        assert Path(api.status(store)["paths"]["store"]) == store.resolve()


class TestTheBriefHandoff:
    def test_two_open_items_ask_which_one(self, store):
        """Guessing would put the wrong brief in front of the user."""
        result = api.make_brief(data=store)
        assert result["status"] == "needs_choice"
        assert len(result["candidates"]) >= 2
        assert all(c["cmid"] for c in result["candidates"])

    def test_a_named_cmid_writes_the_folder(self, store, tmp_path):
        wanted = api.outstanding(store)[0]["cmid"]
        result = api.make_brief(cmid=wanted, data=store, work=tmp_path / "w")
        assert result["status"] == "ok"
        folder = Path(result["briefs"][0]["folder"])
        assert (folder / "brief.md").is_file()
        assert (folder / "HANDOFF.md").is_file()
        assert (folder / "draft.md").is_file()
        assert (folder / "source").is_dir()

    def test_it_refuses_to_overwrite_someone_writing(self, store, tmp_path):
        """Sections 2 to 7 are the student's, so replacing the folder loses work."""
        wanted = api.outstanding(store)[0]["cmid"]
        work = tmp_path / "w"
        api.make_brief(cmid=wanted, data=store, work=work)
        folder = Path(api.make_brief(cmid=wanted, data=store, work=work)["briefs"][0]["folder"])
        (folder / "draft.md").write_text("my work", encoding="utf-8")

        again = api.make_brief(cmid=wanted, data=store, work=work)
        assert again["briefs"][0]["existed"] is True
        assert (folder / "draft.md").read_text(encoding="utf-8") == "my work"

    def test_force_is_the_way_through(self, store, tmp_path):
        wanted = api.outstanding(store)[0]["cmid"]
        work = tmp_path / "w"
        api.make_brief(cmid=wanted, data=store, work=work)
        forced = api.make_brief(cmid=wanted, data=store, work=work, force=True)
        assert forced["briefs"][0]["written"]

    def test_the_assignment_text_is_marked_as_missing(self, store, tmp_path):
        """The site does not give it, and pretending otherwise solves the wrong thing."""
        wanted = api.outstanding(store)[0]["cmid"]
        result = api.make_brief(cmid=wanted, data=store, work=tmp_path / "w")
        brief = (Path(result["briefs"][0]["folder"]) / "brief.md").read_text(encoding="utf-8")
        assert "[نیازمند متن تکلیف]" in brief

    def test_nothing_outstanding_is_a_state_not_an_exception(self, store, tmp_path):
        _, items = tracker.load(store)
        for path in (store / "assignments.json",):
            rows = json.loads(path.read_text(encoding="utf-8"))
            for r in rows:
                r["bucket"] = "graded"
            path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        result = api.make_brief(data=store, work=tmp_path / "w")
        assert result["status"] == "nothing_outstanding"
        assert items


class TestTheCaptchaHandshake:
    """A login that blocks on stdin is a login a skill cannot complete."""

    @staticmethod
    def _page(has_captcha: bool = True) -> str:
        token = '<input name="logintoken" value="TOK">'
        plug = "local_logincaptcha" if has_captcha else ""
        return "<html><form>{}</form><script>{}</script></html>".format(token, plug)

    def _client(self, page: str, logged_in: bool = False):
        page_text = page

        class Fake:
            def __init__(self):
                self.posts = []

            def get(self, path, params=None):
                return page_text

            def get_bytes(self, path, params=None):
                return b"\x89PNG fake"

            def post(self, path, data):
                self.posts.append(data)
                # A rejected captcha re-serves the form with Moodle's own error
                # token, which is what auth.submit() matches on.
                return page_text.replace("</form>", "<p>captchaincorrect</p></form>")

            def logged_in(self):
                return logged_in

        return Fake()

    def test_no_answer_gives_back_an_image_and_a_viewer(self, tmp_path):
        c = self._client(self._page())
        state = auth.submit(c, "u", "p", tmp_path)
        assert state["status"] == auth.CAPTCHA_REQUIRED
        assert state["image"].is_file()
        assert state["viewer"].is_file()

    def test_the_viewer_actually_enlarges_it(self, tmp_path):
        """190x40 is the site's size. A viewer that does not scale it is decoration."""
        c = self._client(self._page())
        state = auth.submit(c, "u", "p", tmp_path)
        html = state["viewer"].read_text(encoding="utf-8")
        assert state["image"].name in html
        assert "760px" in html and "160px" in html
        assert "pixelated" in html

    def test_an_answer_that_is_rejected_comes_back_with_a_new_image(self, tmp_path):
        c = self._client(self._page())
        state = auth.submit(c, "u", "p", tmp_path, captcha="WRONG")
        assert state["status"] == auth.CAPTCHA_REJECTED
        assert state["image"].is_file(), "a spent captcha must not be re-shown"

    def test_a_good_answer_logs_in(self, tmp_path):
        """The success path. The fake accepts one exact answer and nothing else."""
        page = self._page()

        class Accepts:
            def __init__(self):
                self.posts = []

            def get(self, path, params=None):
                return page

            def get_bytes(self, path, params=None):
                return b"\x89PNG"

            def post(self, path, data):
                self.posts.append(data)
                return page

            def logged_in(self):
                return self.posts and self.posts[-1].get("logincaptcha") == "GOOD"

        c = Accepts()
        state = auth.submit(c, "u", "p", tmp_path, captcha="GOOD")
        assert state["status"] == auth.OK
        assert c.posts[0]["logincaptcha"] == "GOOD"

    def test_a_wrong_answer_is_never_logged_in(self, tmp_path):
        """The dangerous direction: a rejection must not read as success."""
        c = self._client(self._page())
        state = auth.submit(c, "u", "p", tmp_path, captcha="WRONG")
        assert state["status"] == auth.CAPTCHA_REJECTED

    def test_no_captcha_on_the_form_is_not_a_captcha_flow(self, tmp_path):
        c = self._client(self._page(has_captcha=False))
        state = auth.submit(c, "u", "p", tmp_path)
        assert state["status"] == auth.FAILED
        assert "logincaptcha" not in c.posts[0]

    def test_a_missing_token_is_an_error_not_a_guess(self, tmp_path):
        c = self._client("<html><form>no token</form></html>")
        with pytest.raises(CwError):
            auth.submit(c, "u", "p", tmp_path)


class TestRefreshRefusesToGuess:
    def test_no_credentials_is_a_state_not_a_prompt(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CW_USER", raising=False)
        monkeypatch.delenv("CW_PASS", raising=False)
        result = api.refresh(home=tmp_path)
        assert result["status"] == "needs_credentials"
        assert "CW_USER" in result["message"]

    def test_no_network_is_touched_before_credentials_are_checked(self, monkeypatch, tmp_path):
        """The credential check happens before a socket exists.

        Checked by patching Client itself rather than the request methods, because
        `logged_in()` is a GET: with the client built first, some network *would* be
        attempted and the test would have to accept that.
        """
        monkeypatch.delenv("CW_USER", raising=False)
        monkeypatch.delenv("CW_PASS", raising=False)

        def explode(*a, **k):  # pragma: no cover - the point is that it never runs
            raise AssertionError("an HTTP client was built without credentials")

        monkeypatch.setattr("cwtrack.client.Client.__init__", explode)
        assert api.refresh(home=tmp_path)["status"] == "needs_credentials"


class TestTheCliAndTheSkillAgree:
    """They are the same code path, so this is a test that it stays that way."""

    def test_gaps_text_is_what_the_cli_prints(self, store, capsys):
        from cwtrack import cli

        cli.main(["gaps", "--data", str(store)])
        printed = capsys.readouterr().out.strip()
        assert printed == api.gaps_text(store).strip()

    def test_report_text_is_what_the_cli_prints(self, store, capsys):
        from cwtrack import cli

        cli.main(["report", "--data", str(store)])
        printed = capsys.readouterr().out.strip()
        assert printed == api.report_text(store).strip()


class TestTheDashboard:
    def test_it_returns_a_path_and_opens_nothing(self, store, tmp_path, monkeypatch):
        """Showing the page is the caller's privilege."""
        def explode(*a, **k):  # pragma: no cover - the point is that it never runs
            raise AssertionError("build_dashboard opened a browser")

        monkeypatch.setattr("os.startfile", explode)
        out = api.build_dashboard(store, tmp_path / "index.html")
        assert out.is_file()
        assert "font-face" in out.read_text(encoding="utf-8")

    def test_it_sees_a_file_dropped_in_after_the_last_fetch(self, store, tmp_path):
        cid = next((store / "courses").iterdir())
        folder = cid / "materials"
        (folder / "new.pdf").write_bytes(b"%PDF-1.4")
        page = api.build_dashboard(store, tmp_path / "index.html").read_text(encoding="utf-8")
        assert "new.pdf" in page


class TestTheSkillsPointAtThisCheckout:
    """A copied skill is a fork, and this one already was.

    The installed skill under the agent's config directory had drifted until it no
    longer had a `brief` command at all — the seam between the two skills — so a
    skill-driven session could not hand work over and had no way to know it. The fix
    is a file link, and this is the test that keeps it one.
    """

    def test_no_skill_is_installed_as_a_separate_copy(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import link_skills

        config = link_skills.config_skills_dir()
        if not config.is_dir():
            pytest.skip("no agent config skills directory on this machine")

        for name in ("sharif-cw", "university-assignment"):
            installed = config / name
            if not installed.exists():
                continue  # not installed here; nothing to drift from
            assert link_skills.is_link(installed), (
                "{} is a real directory, so it is a fork of .agents/skills/{}".format(
                    installed, name
                )
            )
            assert Path(installed.resolve()) == (link_skills.SKILLS / name).resolve()

    def test_every_api_call_named_in_the_skill_exists(self):
        """The skill is the product now, so a renamed function breaks it."""
        skill = (ROOT / ".agents" / "skills" / "sharif-cw" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        mentioned = set(re.findall(r"\bapi\.([a-z_]+)\s*\(", skill))
        assert mentioned, "the guard found nothing to check - it is not guarding"
        for name in sorted(mentioned):
            assert callable(getattr(api, name, None)), (
                "SKILL.md calls api.{}() but cwtrack.api has no such function".format(name)
            )

    def test_every_module_the_skill_names_exists(self):
        skill = (ROOT / ".agents" / "skills" / "sharif-cw" / "SKILL.md").read_text(
            encoding="utf-8")
        for name in sorted(set(re.findall(r"`([a-z_]+\.py)`", skill))):
            assert (ROOT / "src" / "cwtrack" / name).is_file(), name

    def test_every_reference_the_skill_names_exists(self):
        base = ROOT / ".agents" / "skills" / "sharif-cw"
        skill = (base / "SKILL.md").read_text(encoding="utf-8")
        for rel in sorted(set(re.findall(r"`(references/[A-Za-z0-9_.-]+)`", skill))):
            assert (base / rel).is_file(), rel

    def test_the_skill_still_contains_no_identifying_data(self):
        """A skill is the one file people copy between machines by hand.

        The registered copy of this one carried a real student number and a note
        about a password that had been pasted into a chat. Neither belongs in a file
        whose whole purpose is to be shared.
        """
        skill = (ROOT / ".agents" / "skills" / "sharif-cw" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        assert not re.search(r"\b40[0-9]{7}\b", skill)
        assert not re.search(r"@sharif\.edu", skill)
        assert "CW_USER" in skill, "the credential path must stay documented"
        # Whatever example is given, it must not look like a real credential.
        for value in re.findall(r"CW_(?:USER|PASS)\s*=\s*\"?([^\"\n]+)", skill):
            assert not re.search(r"\d{6,}", value), value
