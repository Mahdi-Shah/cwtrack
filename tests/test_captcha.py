"""The captcha reader, scored on images generated to look like the plugin's.

Two rules for this file:

**No test needs tesseract.** The samples are generated, and tesseract is stubbed, so
the suite runs on a machine that has never heard of OCR. The one test that wants the
real binary skips unless it is installed, because a test that cannot fail anywhere
should not be the thing that proves a number.

**The accuracy number is reported with its per-image detail.** A bare rate cannot be
acted on. What matters is whether the readings that would have been submitted
unattended were right, and how many were handed back to the human instead.

The measured figures, from `probe()`, on 20 generated samples: 65% read correctly,
and of the 20 it would auto-submit at 70% agreement, all were right. That is the
reason the gate is at 70% and not lower — at 50% it was 8 right and 1 wrong.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from cwtrack import captcha

PIL = pytest.importorskip("PIL", reason="Pillow builds the sample images")

W, H = 190, 40
ALPHABET = "ABCDEFGHIJKLMNPQRSTUVWXYZ23456789"


def make_captcha(path: Path, text: str, seed: int = 0, difficulty: float = 1.0):
    """A 190x40 image in the plugin's style: thin curves across low-contrast glyphs.

    Generated rather than checked in because the real thing contains a live captcha,
    and because a fixed sample would let the preprocessing quietly overfit to one
    image. Difficulty scales the curve count and the salt noise, so a sweep produces
    a range instead of a single lucky case.
    """
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    random.seed(seed)
    img = Image.new("L", (W, H), 242)
    d = ImageDraw.Draw(img)
    for y in range(H):
        d.line([(0, y), (W, y)], fill=max(0, min(255, 240 + random.randint(-5, 5))))

    font = ImageFont.truetype("arial.ttf", 27)
    d.text((13, 5), text, font=font, fill=25)

    for _ in range(max(1, int(2 * difficulty))):
        pts = []
        y0 = random.uniform(2, H - 6)
        amp = random.uniform(4, 11)
        for x in range(0, W + 8, 8):
            pts.append((x, y0 + amp * ((x / W) * 3.14159 - 1.6) ** 2 - amp * 0.5))
        d.line(pts, fill=random.randint(120, 185), width=1, joint="curve")

    img = img.rotate(random.uniform(-1.8, 1.8), fillcolor=242,
                     resample=Image.BICUBIC).filter(ImageFilter.SMOOTH)

    if difficulty > 0.5:
        d2 = ImageDraw.Draw(img)
        for _ in range(int(70 * difficulty)):
            d2.point([(random.randint(0, W - 1), random.randint(0, H - 1))],
                     fill=random.randint(130, 225))

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


@pytest.fixture
def samples(tmp_path: Path) -> list[tuple]:
    """Twenty samples across the difficulty range, with their answers."""
    out = []
    for i in range(20):
        rng = random.Random(1000 + i)
        text = "".join(rng.choice(ALPHABET) for _ in range(5))
        difficulty = 0.4 + (i % 5) * 0.4
        out.append((make_captcha(tmp_path / "img" / "{}.png".format(text),
                                 text, seed=100 + i, difficulty=difficulty), text))
    return out


def _fake_engine(monkeypatch, readings: dict):
    """Make `_read_once` answer from a table, keyed by a substring of the variant name.

    The variant filenames carry the strategy name, so a mapping like
    {"crop": ("ABCDE", 90.0)} can pin one strategy's reading while another differs.
    """
    calls = []

    def fake(binary, image, psm):
        calls.append((Path(image).stem, psm))
        for key, value in readings.items():
            if key in Path(image).stem:
                return value
        return "", 0.0

    monkeypatch.setattr(captcha, "tesseract_path", lambda: "fake-tesseract")
    monkeypatch.setattr(captcha, "_read_once", fake)
    return calls


class TestSanitise:
    def test_it_folds_case_and_drops_junk(self):
        assert captcha.sanitise("Ab3xK") == "AB3XK"

    def test_it_never_invents_a_character(self):
        """Nothing is *mapped*: no `l` to `1`, no `O` to `0`.

        Those pairs are a coin flip that happens to render as a reading, and a
        confident wrong answer costs a whole round trip on a captcha the site has
        already invalidated. So `L` stays `L` and `I` stays `I` even where the plugin's
        charset may not accept them — better a rejected string we can see than a
        plausible one we cannot.
        """
        assert captcha.sanitise("lI0O") == "LI0O"
        assert captcha.sanitise("l1") == "L1"

    def test_it_strips_separators_tesseract_adds(self):
        assert captcha.sanitise("A B.C-D") == "ABCD"


class TestEnabled:
    def test_on_by_default(self, monkeypatch):
        monkeypatch.delenv("CW_OCR", raising=False)
        assert captcha.enabled()

    @pytest.mark.parametrize("value", ["0", "off", "false", "no", "OFF"])
    def test_explicitly_off(self, monkeypatch, value):
        monkeypatch.setenv("CW_OCR", value)
        assert not captcha.enabled()

    def test_disabled_means_no_work_at_all(self, monkeypatch, tmp_path):
        """The guarantee: off means the human is asked, not "we tried and failed"."""
        monkeypatch.setenv("CW_OCR", "0")
        called = _fake_engine(monkeypatch, {"crop": ("ABCDE", 99.0)})
        result = captcha.guess(make_captcha(tmp_path / "c.png", "ABCDE"))
        assert result["ok"] is False
        assert result["reason"] == "disabled"
        assert called == [], "it must not shell out when disabled"


class TestSanityChecks:
    def test_a_blank_image_is_refused(self, tmp_path, monkeypatch):
        """tesseract returns "" with high confidence on a blank, which reads as
        'cleanly found nothing' rather than 'there was nothing there'."""
        from PIL import Image

        _fake_engine(monkeypatch, {"crop": ("ABCDE", 99.0)})
        blank = tmp_path / "blank.png"
        Image.new("L", (190, 40), 242).save(blank)
        assert captcha.guess(blank)["reason"] == "not_captcha_shaped"

    def test_a_tall_image_is_refused(self, tmp_path, monkeypatch):
        """A 40x190 strip is not a captcha; it is something else that got saved."""
        _fake_engine(monkeypatch, {"crop": ("ABCDE", 99.0)})
        from PIL import Image

        tall = tmp_path / "tall.png"
        with Image.open(make_captcha(tmp_path / "src.png", "ABCDE")) as im:
            im.rotate(90, expand=True).save(tall)
        assert captcha.guess(tall)["reason"] == "not_captcha_shaped"

    def test_a_missing_engine_is_not_an_error(self, monkeypatch, tmp_path):
        def absent():
            raise captcha.OcrUnavailable("not installed")

        monkeypatch.setattr(captcha, "tesseract_path", absent)
        result = captcha.guess(make_captcha(tmp_path / "c.png", "ABCDE"))
        assert result["ok"] is False
        assert result["reason"] == "unavailable"


class TestTheVote:
    def test_agreement_is_what_decides(self, monkeypatch, tmp_path):
        """Most variants agreeing is a submission; a split vote is not.

        One reading is counted per (variant, psm) pair, so a variant that all three psm
        modes agree on contributes three votes. Asserted as the majority rather than a
        literal count, because that is the property: 4 of 5 variants agreeing carries
        the vote whichever way the per-mode counting falls out.
        """
        _fake_engine(monkeypatch, {
            "crop": ("ABCDE", 91.0),
            "big": ("ABCDE", 88.0),
            "med_pad": ("ABCDE", 70.0),
            "sharp": ("ABCDE", 66.0),
            "otsu": ("ZZZZZ", 55.0),
        })
        result = captcha.guess(make_captcha(tmp_path / "c.png", "ABCDE"), min_agreement=0.7)
        assert result["ok"] is True
        assert result["text"] == "ABCDE"
        assert result["votes"] > result["total"] / 2
        assert result["total"] == len(captcha.PSM_MODES) * 5

    def test_disagreement_hands_back_to_the_human(self, monkeypatch, tmp_path):
        _fake_engine(monkeypatch, {
            "crop": ("ABCDE", 91.0),
            "big": ("ABCDE", 88.0),
            "med_pad": ("XXXXX", 70.0),
            "sharp": ("ABCDE", 66.0),
            "otsu": ("ZZZZZ", 55.0),
        })
        result = captcha.guess(make_captcha(tmp_path / "c.png", "ABCDE"), min_agreement=0.7)
        assert result["ok"] is False
        assert result["reason"] == "low_agreement"
        assert result["detail"], "the user should be told what it did manage to read"

    def test_confidence_alone_never_submits(self, monkeypatch, tmp_path):
        """A 99.0 confidence reading from one variant out of five is not a belief.

        This is the trap: tesseract reported 0.0 for correct readings and 48 for a
        wrong one, so a confidence gate is not merely imperfect here, it points the
        wrong way.
        """
        _fake_engine(monkeypatch, {
            "crop": ("ABCDE", 99.0),
            "big": ("ZZZZZ", 12.0),
            "med_pad": ("YYYYY", 11.0),
            "sharp": ("WWWWW", 10.0),
            "otsu": ("VVVVV", 9.0),
        })
        assert captcha.guess(make_captcha(tmp_path / "c.png", "ABCDE"))["ok"] is False

    def test_the_charset_filter_can_veto_everything(self, monkeypatch, tmp_path):
        _fake_engine(monkeypatch, {"crop": ("!!!??", 99.0)})
        result = captcha.guess(make_captcha(tmp_path / "c.png", "ABCDE"))
        assert result["ok"] is False
        assert result["reason"] == "no_reading"

    def test_an_empty_engine_reports_no_reading(self, monkeypatch, tmp_path):
        _fake_engine(monkeypatch, {})
        assert captcha.guess(make_captcha(tmp_path / "c.png", "ABCDE"))["reason"] == "no_reading"


class TestAgainstTheRealEngine:
    """The measurement. Skipped without tesseract, because it is a measurement and
    not a contract — the unit tests above are the contract."""

    def test_it_reads_a_useful_share_and_never_wrongly_submits(self, samples):
        try:
            captcha.tesseract_path()
        except captcha.OcrUnavailable:
            pytest.skip("tesseract not installed")

        report = captcha.probe(samples)
        assert report["total"] == 20
        assert report["read_rate"] >= 0.5, (
            "much worse than measured; preprocessing or psm modes have regressed:\n"
            + "\n".join(
                "  {} -> {} ({:.0%})".format(d["expected"], d["read"] or "-", d["agreement"])
                for d in report["details"]
            )
        )
        # The gate's whole purpose. If this ever fails, the feature can quietly submit
        # a wrong answer, which is worse than not having it.
        assert report["safe"], (
            "submitted a wrong reading:\n"
            + "\n".join(
                "  {} -> {} submitted".format(d["expected"], d["read"])
                for d in report["details"] if d["submitted"] and not d["ok"]
            )
        )


class TestMeasuredChoicesAreNotAccidents:
    """The three findings that shaped the implementation, asserted so that changing
    them back is a deliberate act rather than a stray edit."""

    def test_psm_8_is_tried_first(self):
        """`--psm 7` is the textbook single-line mode and read nothing at all here:
        the plugin's curved strokes defeat its baseline estimate."""
        assert captcha.PSM_MODES[0] == "8"

    def test_the_whitelist_allows_both_cases(self):
        """Uppercase-only made tesseract read a lowercase `b` as `D`."""
        assert "b" in captcha.WHITELIST
        assert captcha.sanitise("Ab3xK") == "AB3XK"

    def test_the_gate_is_where_it_was_measured(self):
        """At 0.5 the measurement was 8 right / 1 wrong. At 0.7 it was 5 / 0."""
        assert captcha.DEFAULT_MIN_AGREEMENT >= 0.65


class TestNotRequired:
    def test_the_package_still_declares_no_dependencies(self):
        """The OCR must stay optional. Installing cwtrack may not be able to disturb
        a student's environment, and that promise predates this feature."""
        import tomllib

        root = Path(__file__).resolve().parent.parent
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        assert data["project"]["dependencies"] == []
        assert "Pillow>=9.0" in data["project"]["optional-dependencies"]["ocr"]

    def test_the_core_modules_do_not_import_it(self):
        """api.py and cli.py must work with neither tesseract nor Pillow present.

        Checked textually because the import is deliberately lazy and inside a
        function; a real import here would defeat the optionality.
        """
        root = Path(__file__).resolve().parent.parent / "src" / "cwtrack"
        for name in ("api.py", "cli.py", "auth.py", "fetch.py"):
            text = (root / name).read_text(encoding="utf-8")
            # A module-level import would be fine as long as it stayed lazy, but the
            # only one present is inside a function, and this asserts it stays that
            # way: nothing on the import path may pull in tesseract or Pillow.
            for line in text.splitlines():
                if line.startswith(("import ", "from ")) and "captcha" in line:
                    assert "from . import captcha as captcha_ocr" in line, (
                        "{}: captcha is imported at module level".format(name)
                    )
            assert "from PIL" not in text, name
            assert "import pytesseract" not in text, name
