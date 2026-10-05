"""Login, and the captcha.

cw.sharif.ir puts an image captcha (local_logincaptcha) on the login form. The
image is saved and a human is asked to read it. It is not solved automatically -
see SKILL.md for why. Everything here is read-only against the site.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .client import DEFAULT_BASE, Client, CwError


def ask(prompt: str) -> str:
    """Prompt, but turn a closed stdin into a clean error instead of a traceback.

    Without this, running the script from a scheduler or a piped context dies on
    a bare EOFError, which tells the user nothing about what went wrong.
    """
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt) as exc:
        raise CwError(
            "ورودی از ترمینال در دسترس نیست. مقدار را در متغیر محیطی بگذارید "
            "(CW_USER و CW_PASS) و دوباره اجرا کنید."
        ) from exc


def do_login(client: Client, user: str, pw: str, base_dir: Path) -> None:
    page = client.get("/login/index.php")

    found = re.findall(r'name="logintoken"\s+value="([^"]+)"', page)
    if not found:
        raise CwError(
            "no logintoken on the login form - the site changed its login markup. "
            "Run with --debug-page to dump what it returned."
        )

    payload = {
        "username": user,
        "password": pw,
        "logintoken": found[0],
        "anchor": "",
    }

    # local_logincaptcha injects its image field with JS, so the served HTML has
    # the script but not the input. Detect the script, not the input.
    has_captcha = "local_logincaptcha" in page or "logincaptcha" in page
    if has_captcha:
        shot = base_dir / "captcha.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        shot.write_bytes(
            client.get_bytes("/local/logincaptcha/image.php?v={}".format(int(time.time() * 1000)))
        )
        print("این سایت روی ورود کپچا تصویری دارد.")
        print("تصویر اینجا ذخیره شد، بازش کن: {}".format(shot.resolve()))
        answer = ask("حروف/اعداد داخل تصویر را بنویس: ")
        if not answer:
            raise CwError("پاسخ کپچا خالی بود، لغو شد.")
        payload["logincaptcha"] = answer

    result = client.post("/login/index.php", payload)

    if client.logged_in():
        print("ورود موفق بود.")
        save_marker(base_dir, user)
        return

    low = result.lower()
    hints = [
        ("captchaincorrect", "پاسخ کپچا رد شد - صفحه را دوباره باز کن و با دقت بیشتری بخوان"),
        ("invalidlogin", "نام کاربری یا رمز اشتباه است"),
        ("invalid login", "نام کاربری یا رمز اشتباه است"),
        ("loginerror", "ورود ناموفق بود"),
        ("لطفا", "پیام خطای سایت: بررسی کنید رمز را از طریق «فراموشی رمز» بازنشانی کرده‌اید"),
    ]
    for needle, msg in hints:
        if needle in low:
            raise CwError(msg)
    raise CwError(
        "ورود ناموفق بود ولی پیام مشخصی نداد. توجه: صفحهٔ ورود cw.sharif.ir "
        "فعلاً از همهٔ کاربران می‌خواهد رمز را از طریق «فراموشی رمز» بازنشانی کنند."
    )


def save_marker(base_dir: Path, user: str) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    (base_dir / "session.json").write_text(
        json.dumps({"user": user, "saved": int(time.time()), "base": DEFAULT_BASE}, indent=2),
        encoding="utf-8",
    )


def has_session(base_dir: Path) -> bool:
    return (base_dir / "session.json").is_file()
