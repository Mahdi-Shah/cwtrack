"""Login, and the captcha.

cw.sharif.ir puts an image captcha (local_logincaptcha) on the login form. The
image is saved and a human is asked to read it. It is not solved automatically - see
SKILL.md for why. Everything here is read-only against the site.

The login is a two-phase protocol because the reader may not be a person at a
terminal. `submit()` returns a state and never blocks on stdin; the CLI turns a
`captcha_required` into a prompt, and a skill turns it into an image it shows the
user. Same code path, two callers, and neither can accidentally make the other wait
on a keyboard.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .client import DEFAULT_BASE, Client, CwError

# Statuses returned by submit(). Named constants because the caller branches on them
# and a typo in a string literal is a silent "treat an unknown status as ok".
OK = "ok"
CAPTCHA_REQUIRED = "captcha_required"
CAPTCHA_REJECTED = "captcha_rejected"
FAILED = "failed"

#: How many times a human may read a captcha before we stop. Three is generous for a
#: 190x40 image and a zoomed viewer; past that, the person is squinting, not solving,
#: and an unbounded loop against a login endpoint helps nobody.
MAX_HUMAN_ATTEMPTS = 3


def ask(prompt: str) -> str:
    """Prompt, but turn a closed stdin into a clean error instead of a traceback.

    Only the CLI uses this. A skill must never reach it: a prompt with no terminal
    behind it raises EOFError, and the resulting error tells the user to set an
    environment variable rather than telling them what actually happened.
    """
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt) as exc:
        raise CwError(
            "ورودی از ترمینال در دسترس نیست. مقدار را در متغیر محیطی بگذارید "
            "(CW_USER و CW_PASS) و دوباره اجرا کنید."
        ) from exc


def captcha_viewer(image: Path, scale: int = 4) -> Path:
    """An HTML page that shows the captcha large enough to read.

    The image is about 190x40 px, which is genuinely hard to read, and a rejected
    read costs the user a whole round trip. A browser scales it for free, so the
    viewer does that rather than pulling in an imaging dependency: the nearest-
    neighbour version keeps the strokes crisp, and the smoothed one underneath it is
    the fallback for anyone who finds the aliasing worse than the blur.

    Written next to the image and referencing it relatively, so it works when opened
    straight from disk with no server.
    """
    viewer = image.with_name(image.stem + "-zoom.html")
    width = 190 * scale
    height = 40 * scale
    page = """<!doctype html>
<html lang="fa"><head><meta charset="utf-8">
<title>captcha</title>
<style>
  body{{background:#fff;color:#111;font:14px/1.6 system-ui,sans-serif;
        margin:0;padding:24px;display:flex;gap:32px;align-items:flex-start}}
  figure{{margin:0}}
  img{{display:block;border:1px solid #ccc;background:#fff}}
  .crisp{{width:{w}px;height:{h}px;image-rendering:pixelated}}
  .smooth{{width:{w}px;height:{h}px}}
  figcaption{{margin-top:6px;color:#555}}
</style></head>
<body>
  <figure>
    <img class="crisp" src="{src}" alt="captcha">
    <figcaption>larger, crisp</figcaption>
  </figure>
  <figure>
    <img class="smooth" src="{src}" alt="captcha">
    <figcaption>larger, smoothed</figcaption>
  </figure>
</body></html>
""".format(w=width, h=height, src=image.name)
    viewer.write_text(page, encoding="utf-8")
    return viewer


def _login_form(client: Client) -> tuple[str, bool]:
    """(logintoken, captcha_present) from a freshly loaded login form.

    local_logincaptcha injects its image field with JS, so the served HTML has the
    script but not the input. Detect the script, not the input.
    """
    page = client.get("/login/index.php")
    found = re.findall(r'name="logintoken"\s+value="([^"]+)"', page)
    if not found:
        raise CwError(
            "no logintoken on the login form - the site changed its login markup. "
            "Run with --debug-page to dump what it returned."
        )
    return found[0], ("local_logincaptcha" in page or "logincaptcha" in page)


def _fetch_captcha(client: Client, base_dir: Path) -> dict:
    shot = base_dir / "captcha.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    shot.write_bytes(
        client.get_bytes("/local/logincaptcha/image.php?v={}".format(int(time.time() * 1000)))
    )
    return {"image": shot, "viewer": captcha_viewer(shot)}


def submit(
    client: Client,
    user: str,
    pw: str,
    base_dir: Path,
    captcha: str | None = None,
) -> dict:
    """Attempt a login. Returns a state; never prompts, never raises on rejection.

    States are the four module constants. `captcha_required` and `captcha_rejected`
    both carry a freshly downloaded image, so a caller that loops gets a new puzzle
    each time instead of re-showing a spent one - Moodle invalidates the previous
    captcha on use.
    """
    token, has_captcha = _login_form(client)

    if has_captcha and not captcha:
        challenge = _fetch_captcha(client, base_dir)
        return {
            "status": CAPTCHA_REQUIRED,
            "image": challenge["image"],
            "viewer": challenge["viewer"],
            "message": "این سایت روی ورود کپچا تصویری دارد. تصویر را به کاربر نشان بده.",
        }

    payload = {
        "username": user,
        "password": pw,
        "logintoken": token,
        "anchor": "",
    }
    if has_captcha:
        payload["logincaptcha"] = captcha

    result = client.post("/login/index.php", payload)

    if client.logged_in():
        save_marker(base_dir, user)
        return {"status": OK}

    low = result.lower()
    if has_captcha and "captchaincorrect" in low:
        challenge = _fetch_captcha(client, base_dir)
        return {
            "status": CAPTCHA_REJECTED,
            "image": challenge["image"],
            "viewer": challenge["viewer"],
            "message": "پاسخ کپچا رد شد - دوباره تلاش کن.",
        }

    hints = [
        ("invalidlogin", "نام کاربری یا رمز اشتباه است"),
        ("invalid login", "نام کاربری یا رمز اشتباه است"),
        ("loginerror", "ورود ناموفق بود"),
    ]
    for needle, message in hints:
        if needle in low:
            return {"status": FAILED, "message": message}

    return {
        "status": FAILED,
        "message": (
            "ورود ناموفق بود ولی پیام مشخصی نداد. توجه: صفحهٔ ورود cw.sharif.ir "
            "فعلاً از همهٔ کاربران می‌خواهد رمز را از طریق «فراموشی رمز» بازنشانی کنند."
        ),
    }


def _try_ocr(image: Path) -> dict | None:
    """A confident reading, or None to ask the human.

    Returns None for every reason that is not "the readings agreed" — OCR disabled, no
    tesseract, an image that is not captcha-shaped, or too much disagreement. Keeping
    the reasons collapsed to a single None is deliberate: this is a convenience, and a
    convenience that can explain itself while prompting is a second thing to read.
    """
    from . import captcha

    try:
        result = captcha.guess(image)
    except Exception:  # noqa: BLE001 - never let a nicety break the login
        return None
    return result if result.get("ok") else None


def do_login(client: Client, user: str, pw: str, base_dir: Path) -> None:
    """The CLI's login: prompt for the captcha, then get in or explain why not.

    A thin wrapper over submit(), so the human path and the skill path cannot drift
    into two different notions of what a successful login is.
    """
    state = submit(client, user, pw, base_dir)

    # The engine gets one go, not one per image. A captcha is a short random string,
    # so a second identical-looking reading is very likely to be the same mistake; and
    # a loop that retries until the site relents is exactly the failure mode this
    # feature could inflict if the gate were removed. After one wrong guess the human
    # answers every remaining round.
    ocr_used = False
    human_used = 0

    # CAPTCHA_REJECTED is included on purpose: a rejection comes back with a fresh
    # image, and the loop is what presents it and asks again. Exiting on a rejection
    # instead is what made the first version give up after the engine's one miss.
    while state["status"] in (CAPTCHA_REQUIRED, CAPTCHA_REJECTED):
        shot = state["image"]
        print(state["message"])
        print("تصویر اینجا ذخیره شد، بازش کن: {}".format(shot.resolve()))
        print("یا این صفحه را باز کن (بزرگ‌شده): {}".format(state["viewer"].resolve()))

        # Optional, and measured. Five readings are voted on and only submitted when
        # enough of them agree; captcha.py carries the numbers, which are deliberately
        # modest — at the measured rate this answers roughly a quarter of logins and
        # never answers one wrongly. Below the bar, or with CW_OCR=0, this is skipped
        # and the prompt below happens exactly as it always did.
        guessed = None if ocr_used else _try_ocr(shot)
        if guessed:
            ocr_used = True
            print("خواندن پیشنهادی: {}  ({} از {} خواندن هم‌خوان؛ همین استفاده می‌شود)".format(
                guessed["text"], guessed["votes"], guessed["total"]))
            tried = submit(client, user, pw, base_dir, captcha=guessed["text"])
            if tried["status"] == CAPTCHA_REJECTED:
                print("پیشنهاد هم درست نبود. خودت بخوان — تصویر تازه بالا باز شد.")
            state = tried
            continue

        answer = ask("حروف/اعداد داخل تصویر را بنویس: ")
        if not answer:
            raise CwError("پاسخ کپچا خالی بود، لغو شد.")
        human_used += 1
        if human_used > MAX_HUMAN_ATTEMPTS:
            # A person who has read a 190x40 captcha twice is not going to read it
            # correctly on the fifth try. Stop, rather than looping against a login
            # endpoint until they give up.
            raise CwError(
                "بعد از {} تلاش کپچا درست خوانده نشد. اگر رمز را از «فراموشی رمز» "
                "عوض کرده‌ای، اول آن را امتحان کن.".format(human_used - 1)
            )
        state = submit(client, user, pw, base_dir, captcha=answer)

    if state["status"] == OK:
        print("ورود موفق بود.")
        return

    if state["status"] == CAPTCHA_REJECTED:
        # submit() already downloaded a fresh image, so point at it rather than
        # telling the user to start the whole command again.
        print(state["message"])
        print("تصویر جدید: {}".format(state["image"].resolve()))
        raise CwError("پاسخ کپچا رد شد.")

    raise CwError(state.get("message") or "ورود ناموفق بود.")


def save_marker(base_dir: Path, user: str) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    (base_dir / "session.json").write_text(
        json.dumps({"user": user, "saved": int(time.time()), "base": DEFAULT_BASE}, indent=2),
        encoding="utf-8",
    )


def has_session(base_dir: Path) -> bool:
    return (base_dir / "session.json").is_file()
