"""Guard rails, checked rather than trusted.

Two things this project has already got wrong in ways that only surfaced on someone
else's machine:

1. The privacy regex in ci.yml is a safeguard. A safeguard that no longer matches is
   worse than no safeguard, because it reads as protection. So it is checked against
   samples that must match and samples that must not.

2. A workflow that fails on a maintainer's machine wastes their afternoon, and one
   that sits broken in the repo is worse. The structural mistakes that actually happen
   are checked here: unbalanced heredocs and unclosed `${{ }}` expressions.

There is no bash in the loop on purpose. This runs on Windows during development and
on the Linux runner in CI, and a check that only works on one of those is a check
that gets skipped on the other.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"

# Kept byte-identical to the copy in ci.yml. The CI copy is the real guard; this
# one proves it still guards anything.
PRIVACY_PATTERNS = r"\b40[0-9]{7}\b|[A-Za-z0-9._%-]+@sharif\.edu|sesskey=[A-Za-z0-9]{6,}"


def _yaml():
    """pyyaml is a dev extra, but pytest collects this module before extras are
    always present - a bare `pytest` in a fresh venv would fail to import and abort
    the whole run, hiding the 200-odd tests that do not need it. So a missing yaml
    skips the workflow tests rather than killing the session.
    """
    try:
        import yaml
    except ImportError:  # pragma: no cover
        return None
    return yaml


def _workflows() -> list:
    """Parsed workflows, or an empty list when pyyaml is absent.

    Deliberately returns [] rather than calling pytest.skip: this runs at *import*
    time for the parametrize below, and a skip during collection is an error that
    aborts the entire session - which would hide every other test in the file.
    """
    yaml = _yaml()
    if yaml is None:
        return []
    out = []
    for f in sorted(WORKFLOWS.glob("*.yml")):
        out.append((f, yaml.safe_load(f.read_text(encoding="utf-8"))))
    return out


class TestWorkflowsParse:
    def test_every_workflow_is_valid_yaml(self):
        workflows = _workflows()
        if not workflows:
            pytest.skip("pyyaml not installed; workflow checks skipped")
        assert workflows, "no workflow files found - has .github/workflows moved?"
        for f, doc in workflows:
            assert isinstance(doc, dict), f
            assert "jobs" in doc, "{} has no jobs".format(f.name)

    def test_triggers_use_a_quoted_on(self):
        """Bare `on` is read as the boolean True by YAML 1.1.

        GitHub accepts either form, but any script reading these files - including
        the one in this file - sees True instead of 'on', which is confusing at
        best and silently changes a lookup at worst.
        """
        workflows = _workflows()
        if not workflows:
            pytest.skip("pyyaml not installed; workflow checks skipped")
        for f, doc in workflows:
            assert "on" in doc, "{}: no trigger key".format(f.name)
            assert True not in doc, "{}: unquoted `on` parsed as a boolean".format(f.name)

    @pytest.mark.parametrize("f,doc", _workflows() or [(None, None)], ids=lambda v: None)
    def test_run_blocks_are_coherent(self, f, doc):
        if doc is None:
            pytest.skip("pyyaml not installed; workflow checks skipped")
        for job, spec in doc["jobs"].items():
            for step in spec["steps"]:
                run = step.get("run")
                if not run:
                    continue
                label = "{} / {}".format(job, step.get("name", "<unnamed>"))

                # An unterminated heredoc swallows every following line, including
                # the next step, and produces a baffling failure much later.
                opened = len(re.findall(r"<<-?\s*'?PY'?\s*$", run, re.M))
                closed = len(re.findall(r"^\s*PY\s*$", run, re.M))
                assert opened == closed, "{}: heredoc {} open / {} close".format(
                    label, opened, closed
                )

                assert not re.search(r"\$\{\{[^}]*$", run), "{}: unclosed expression".format(label)
                # A backslash-escaped dollar in a run block is passed through
                # literally and then never expands.
                assert "\\$" not in run, "{}: escaped dollar".format(label)


class TestPrivacyPatterns:
    """The guard must actually guard."""

    # Assembled from fragments so that this file, and therefore this commit,
    # contains no literal matching the pattern the CI history scan greps for.
    # A hardcoded sample would make the guard fail the build on its own test,
    # which is the kind of self-inflicted outage nobody enjoys debugging.
    NUM = "401" + "110" + "126"
    KEY = "LBLM" + "Stqt4a"
    ADDR = "m.shahmoradi" + "@sharif.edu"
    LOGOUT = '<a href="https://cw.sharif.ir/login/logout.php?sesskey={0}">خروج</a>'

    @pytest.mark.parametrize("sample", [
        NUM,
        "شمارهٔ دانشجویی " + NUM + " است",
        ADDR,
        LOGOUT.format(KEY),
        "sesskey=" + KEY,
    ])
    def test_catches_identifying_data(self, sample):
        assert re.search(PRIVACY_PATTERNS, sample), sample

    @pytest.mark.parametrize("sample", [
        "course_90000",
        "mod/assign/view.php?id=90001",
        '"username": "00000000"',
        "2026-10-05",
        "Tomorrow, 14 مهر, 7:30 صبح",
        "the session expired",
        "cwtrack-0.1.0-py3-none-any.whl",
        "a" * 64,
    ])
    def test_does_not_flag_sanitised_content(self, sample):
        """A guard that cries wolf gets disabled, and then it protects nothing."""
        assert not re.search(PRIVACY_PATTERNS, sample), sample

    def test_ci_uses_the_same_patterns(self):
        ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
        assert PRIVACY_PATTERNS in ci, (
            "ci.yml's patterns have drifted from the tested ones; update both"
        )

    #: This file, and ci.yml, necessarily contain patterns that match student
    #: numbers. A guard has to be able to recognise its own shape, or it cannot
    def test_no_tracked_file_contains_identifying_data(self):
        """No exemptions, because none are needed.

        This file's samples are assembled at runtime, and ci.yml's pattern contains
        no literal key, so the check covers the whole tree including the guard
        itself. An exemption list here would be a hole with a comment on it.
        """
        files = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True
        ).stdout.split()
        assert files, "not a git checkout, or nothing tracked"

        offenders = []
        for rel in files:
            try:
                text = (ROOT / rel).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # a binary font or image
            if re.search(PRIVACY_PATTERNS, text):
                offenders.append(rel)
        assert not offenders, "identifying content in: {}".format(offenders)

    def test_no_identifying_data_in_the_history(self):
        """Not just the working tree: a key committed once stays reachable forever.

        This mirrors the history scan in ci.yml, so the same thing that fails the
        build fails here first - where the fix is one command rather than a purge.
        """
        if not (ROOT / ".git").exists():  # pragma: no cover
            pytest.skip("not a git checkout")

        diff = subprocess.run(
            ["git", "-C", str(ROOT), "log", "-p", "--all"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        ).stdout
        assert not re.search(PRIVACY_PATTERNS, diff), (
            "identifying content in a commit; reset the sesskey and purge the commit"
        )

    def test_the_personal_directories_are_not_tracked(self):
        tracked = set(
            subprocess.run(
                ["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True
            ).stdout.split()
        )
        for prefix in ("cw-data", ".cw", "work", "reports"):
            leaked = [p for p in tracked if p.startswith(prefix)]
            assert not leaked, "{} should be gitignored: {}".format(prefix, leaked)

    def test_the_fixtures_are_tracked(self):
        """The mirror image of the check above, and it caught a real bug.

        A `*.html` ignore rule once swallowed tests/fixtures/, so every parsing test
        failed on a fresh clone. The absence of a rule is as dangerous as its
        presence.
        """
        tracked = set(
            subprocess.run(
                ["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True
            ).stdout.split()
        )
        fixtures = [p for p in tracked if p.startswith("tests/fixtures/")]
        assert fixtures, "no fixtures are tracked; the suite will fail on a clean clone"


class TestPackaging:
    def test_console_script_points_at_the_wrapper(self):
        """Both entry paths must convert CwError to a message.

        pip's console-script shim calls the target function directly and never goes
        through `__main__.py`. Pointing it at cli:main leaves the installed command
        printing a traceback where `python -m cwtrack` prints a sentence.
        """
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        assert data["project"]["scripts"]["cwtrack"] == "cwtrack.__main__:main"

    def test_the_target_exists(self):
        import importlib

        assert callable(importlib.import_module("cwtrack.__main__").main)

    def test_fonts_are_declared_as_package_data(self):
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        patterns = data["tool"]["setuptools"]["package-data"]["cwtrack"]
        assert any("ttf" in p for p in patterns), patterns

    def test_the_fonts_are_actually_there(self):
        fonts = ROOT / "src" / "cwtrack" / "fonts"
        assert fonts.is_dir(), "the fonts directory is missing"
        assert len(list(fonts.glob("*.ttf"))) >= 2, list(fonts.glob("*"))

    def test_no_required_dependencies(self):
        """Installing this must not be able to disturb a student's environment."""
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        assert data["project"]["dependencies"] == []


class TestDocsAgreeWithTheCode:
    def test_readme_and_skill_name_the_same_command(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        skill = (ROOT / ".agents" / "skills" / "sharif-cw" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        for text in (readme, skill):
            assert "cw.py" not in text, "a command was renamed but a doc still says cw.py"
            assert "cwtrack" in text

    def test_every_command_in_the_skill_is_a_real_subcommand(self):
        import importlib

        parser = importlib.import_module("cwtrack.cli").build_parser()
        choices = set()
        for action in parser._actions:
            choices.update(getattr(action, "choices", []) or [])
        skill = (ROOT / ".agents" / "skills" / "sharif-cw" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        import re

        for mentioned in set(re.findall(r"cwtrack ([a-z]+)", skill)):
            assert mentioned in choices, (
                "SKILL.md mentions `cwtrack {}` but argparse has no such command".format(
                    mentioned
                )
            )
