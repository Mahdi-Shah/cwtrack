"""Reading the login captcha, when it is asked for and the machine can be trusted.

Default behaviour is unchanged: a human reads the captcha, because the captcha is the
site stating that a person is at the keyboard. This module is an opt-in extra
(`pip install -e ".[ocr]"`, a tesseract binary on the machine) and it is measured, not
assumed.

Measured on 20 generated samples of the plugin's style — 190x40, thin curves through
the glyphs, light noise:

    crop alone, best single strategy   14/20 exact
    crop_x4 (upscale 4x)               13/20  <- upscaling HURT
    5-strategy ensemble                13/20 exact
    ensemble, auto-submit at >=70%     5 of 20, 5 right, 0 wrong
    ensemble, auto-submit at >=50%     9 of 20, 8 right, 1 wrong

Three findings shaped this code, none of them what the guides say:

- **`--psm 7` reads nothing at all.** The textbook mode for a single line returns
  empty on every sample, because the plugin's curved strokes defeat its baseline
  estimate. `--psm 8` (a single word) is the right model for a short token.
- **Upscaling hurt.** 4x LANCZOS scored 13/20 against 14/20 for no resampling at all.
  Cropping to the ink bounding box is what helps.
- **tesseract's confidence is not a usable gate.** Correct readings came back at
  conf 0.0 and a wrong one at 48, so a threshold on it discards right answers without
  ever proving one. What does work is *agreement across strategies* — at >=70% it was
  5 right and 0 wrong.

So: read five ways, submit only when at least 70% of the readings agree, otherwise
fall back to the human. At the measured rate that automates roughly a quarter of
logins and never automates a wrong one. That is a modest win and the honest one; the
alternative, submitting the best guess every time, would look better in a demo and
would loop on failures.

The engine also gets **one attempt per login**, not one per image. A captcha is a
short random string, so a second identical-looking reading is likely to be the same
mistake — and an uncapped loop against a login endpoint is exactly the failure this
feature could inflict on someone who installed it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections import Counter
from pathlib import Path

#: The charset `local_logincaptcha` accepts. `sanitise()` filters to it, so an
#: impossible string is never submitted.
ALLOWED = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

#: What tesseract may emit. Both cases, deliberately: restricting it to uppercase
#: alone made it read a lowercase `b` as `D`, turning "Ab3xK" into "AD3XK" — a
#: silent, confident, wrong answer. Case is folded in Python instead, where folding
#: it wrongly shows up as a visible diff.
WHITELIST = ALLOWED + ALLOWED.lower()

#: Fraction of readings that must agree before the guess is submitted unattended.
#: Measured: at 0.7 it was 5 right / 0 wrong; at 0.5 it was 8 right / 1 wrong.
DEFAULT_MIN_AGREEMENT = 0.70

#: Page segmentation modes. psm 8 first because psm 7 reads nothing here.
PSM_MODES = ("8", "7", "13")


class OcrUnavailable(Exception):
    """No usable tesseract. Not something the user has to act on."""


def enabled() -> bool:
    """`CW_OCR=0` / off / false / no turns this off explicitly."""
    flag = os.environ.get("CW_OCR", "").strip().lower()
    return flag not in {"0", "off", "false", "no"}


def tesseract_path() -> str:
    """Locate the binary.

    `CW_TESSERACT` wins, then PATH, then the known install locations — because a
    Windows installer does not extend the PATH of a shell that is already open, which
    is exactly the shell this runs in.
    """
    explicit = os.environ.get("CW_TESSERACT", "").strip()
    if explicit and Path(explicit).is_file():
        return explicit
    found = shutil.which("tesseract")
    if found:
        return found
    for candidate in (
        Path.home() / "AppData/Local/Programs/Tesseract-OCR/tesseract.exe",
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path("/usr/bin/tesseract"),
        Path("/usr/local/bin/tesseract"),
    ):
        if candidate.is_file():
            return str(candidate)
    raise OcrUnavailable(
        "tesseract not found. Install it (winget install UB-Mannheim.TesseractOCR), "
        "or set CW_OCR=0 to keep reading the captcha yourself."
    )


def sanitise(text: str) -> str:
    """Fold to uppercase, drop everything the plugin would reject.

    Nothing is *mapped* — not `l` to `1`, not `O` to `0`. Guessing which one the
    plugin meant is precisely the confident wrong answer that costs a round trip.
    """
    return "".join(ch for ch in text.upper() if ch in ALLOWED)


def looks_like_one_line(image: Path) -> bool:
    """A sanity check before spending any time on OCR.

    A truncated download or an HTML error page would otherwise be OCR'd into a
    plausible string and rejected for reasons that look like a bug here.
    """
    try:
        from PIL import Image, ImageStat
    except ImportError:  # pragma: no cover - without Pillow, do not block
        return True
    try:
        # `with`, so the file is closed on every path out. An unclosed handle here
        # became a ResourceWarning that pytest's -W error turned into a test failure,
        # which is the correct outcome but for the wrong reason.
        with Image.open(image) as im:
            w, h = im.size
            if w < 40 or h < 12 or w < h:
                return False
            # Reject blank: tesseract returns "" with high confidence on it, which
            # reads as a clean failure rather than as "there was nothing to read".
            return ImageStat.Stat(im.convert("L")).stddev[0] > 12.0
    except Exception:
        return False


def _ink_bbox(im):
    inv = im.convert("L").point(lambda v: 255 - v)
    return inv.point(lambda v: 255 if v > 40 else 0).getbbox()


def _variants(image: Path, workdir: Path) -> dict:
    """The five readings the ensemble votes over.

    `crop` leads because it measured best (14/20 against 13/20 for the 4x upscale) —
    the ink bounding box is what matters, and resampling the glyphs is not free.
    """
    from PIL import Image, ImageFilter, ImageOps

    with Image.open(image) as handle:
        base = handle.convert("L")  # a copy, so the closed handle cannot matter
    box = _ink_bbox(base) or (0, 0, base.width, base.height)
    crop = base.crop(box)
    big = crop.resize((crop.width * 3, crop.height * 3), Image.LANCZOS)
    med = ImageOps.expand(big, border=24, fill=255).filter(ImageFilter.MedianFilter(3))
    sharp = med.filter(ImageFilter.UnsharpMask(radius=2, percent=180, threshold=2))

    out = {"crop": crop, "big": big, "med_pad": med, "sharp": sharp}
    out["otsu"] = ImageOps.expand(
        sharp.point(lambda p: 255 if p > otsu_threshold(sharp) else 0),
        border=24, fill=255,
    )
    paths = {}
    for name, img in out.items():
        p = workdir / "{}.png".format(name)
        img.save(p)
        paths[name] = p
    return paths


def otsu_threshold(grey) -> int:
    """Otsu's method. Exact, and avoids a numpy dependency for one number."""
    hist = grey.histogram()
    total = sum(hist)
    if not total:
        return 128
    sum_all = sum(i * h for i, h in enumerate(hist))
    sum_b = w_b = 0
    best = 0.0
    threshold = 128
    for t, count in enumerate(hist):
        w_b += count
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * count
        between = w_b * w_f * (sum_b / w_b - (sum_all - sum_b) / w_f) ** 2
        if between > best:
            best = between
            threshold = t
    return threshold


def _read_once(binary: str, image: Path, psm: str) -> tuple[str, float]:
    """One tesseract call: (text, mean confidence).

    `tsv` rather than `stdout`, because it is the only renderer that reports
    confidence — this build writes nothing to stderr, so a parser reading stderr
    returns 0.0 for every reading and any confidence gate then silently trusts
    everything.
    """
    proc = subprocess.run(
        [binary, str(image), "stdout", "--psm", psm,
         "-c", "tessedit_char_whitelist=" + WHITELIST, "tsv"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    words, confs = [], []
    for line in proc.stdout.splitlines()[1:]:
        cells = line.split("\t")
        if len(cells) < 12 or cells[0] != "5":
            continue  # only word-level rows carry text
        text = cells[11].strip()
        if text:
            words.append(text)
            try:
                confs.append(float(cells[10]))
            except ValueError:
                confs.append(0.0)
    if not words:
        return "", 0.0
    return "".join(words), sum(confs) / len(confs)


def guess(image: Path, min_agreement: float = DEFAULT_MIN_AGREEMENT) -> dict:
    """Try to read the captcha. Never raises for an unreadable image.

    Returns `{"ok": False, "reason": ...}` rather than a guess it does not believe,
    so the caller falls back to the human with a reason worth showing.
    """
    if not enabled():
        return {"ok": False, "reason": "disabled", "text": "", "agreement": 0.0}
    if not looks_like_one_line(image):
        return {"ok": False, "reason": "not_captcha_shaped", "text": "",
                "agreement": 0.0}
    try:
        binary = tesseract_path()
    except OcrUnavailable as exc:
        return {"ok": False, "reason": "unavailable", "text": "", "agreement": 0.0,
                "detail": str(exc)}

    import tempfile

    votes: Counter = Counter()
    total = 0
    seen: dict = {}
    with tempfile.TemporaryDirectory(prefix="cwocr-") as tmp:
        workdir = Path(tmp)
        try:
            variants = _variants(image, workdir)
        except ImportError as exc:
            # The `ocr` extra was not installed. Reported, not raised: the caller
            # asks the human, and a traceback here would be a bug report about a
            # feature the user did not ask for.
            return {"ok": False, "reason": "no_pillow", "text": "",
                    "agreement": 0.0, "detail": str(exc)}
        except OSError as exc:  # an unreadable or truncated file
            return {"ok": False, "reason": "preprocess_failed", "text": "",
                    "agreement": 0.0, "detail": str(exc)}

        for name, path in variants.items():
            for psm in PSM_MODES:
                try:
                    raw, conf = _read_once(binary, path, psm)
                except (subprocess.TimeoutExpired, OSError) as exc:
                    return {"ok": False, "reason": "tesseract_failed", "text": "",
                            "agreement": 0.0, "detail": str(exc)}
                total += 1
                text = sanitise(raw)
                if text:
                    votes[text] += 1
                    seen.setdefault(text, {"confidence": conf, "variant": name,
                                           "psm": psm})

    if not votes:
        return {"ok": False, "reason": "no_reading", "text": "", "agreement": 0.0}

    text, count = votes.most_common(1)[0]
    agreement = count / total
    result = {
        "ok": agreement >= min_agreement,
        "text": text,
        "agreement": agreement,
        "votes": count,
        "total": total,
        "alternatives": len(votes),
        **seen[text],
    }
    if not result["ok"]:
        result["reason"] = "low_agreement"
        result["detail"] = (
            "خواندنها با هم اختلاف دارند؛ خودت بخوان: {}".format(text)
        )
    return result


def probe(samples: list[tuple], min_agreement: float = DEFAULT_MIN_AGREEMENT) -> dict:
    """Score against known answers, with the per-image detail attached.

    A rate on its own cannot be acted on: what matters is whether the readings it
    would have auto-submitted were right, and which ones it handed back.
    """
    total = exact = auto = auto_right = 0
    details = []
    for path, truth in samples:
        result = guess(Path(path), min_agreement)
        total += 1
        ok = bool(result.get("ok")) and result.get("text") == truth
        exact += int(result.get("text") == truth)
        if result.get("ok"):
            auto += 1
            auto_right += int(ok)
        details.append({
            "file": Path(path).name,
            "expected": truth,
            "read": result.get("text", ""),
            "agreement": result.get("agreement", 0.0),
            "submitted": bool(result.get("ok")),
            "ok": ok,
        })
    return {
        "total": total,
        "exact": exact,
        "read_rate": (exact / total) if total else 0.0,
        "submitted": auto,
        "submitted_right": auto_right,
        "safe": auto == auto_right,
        "details": details,
    }
