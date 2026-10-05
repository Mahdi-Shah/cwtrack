"""HTTP transport for cw.sharif.ir.

Cookie-persisting session, plus the retry that the site's TLS needs: under load
it drops the handshake, which surfaces as SSLEOFError rather than an HTTP error.
"""

from __future__ import annotations

import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

DEFAULT_BASE = os.environ.get("CW_BASE", "https://cw.sharif.ir")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

class CwError(Exception):
    pass


class Client:
    """Cookie-persisting HTTP client with retries for the site's TLS flakiness."""

    def __init__(self, base: str = DEFAULT_BASE, timeout: int = 30, retries: int = 3):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        # The SSL context goes on the handler; OpenerDirectory.open() forwards
        # kwargs to protocol handlers and rejects `context`. Verification stays
        # on: a login script that cannot tell the real site from an impostor is
        # worse than one that refuses to run.
        ctx = ssl.create_default_context()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar()),
            urllib.request.HTTPSHandler(context=ctx),
        )

    def _open(self, req: urllib.request.Request):
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                return self.opener.open(req, timeout=self.timeout)
            except urllib.error.HTTPError:
                raise
            except Exception as exc:  # noqa: BLE001 - transient network layer
                last = exc
                time.sleep(1.5 * (attempt + 1))
        raise CwError("network failure after {} tries: {}".format(self.retries, last))

    def get(self, path: str, params: dict | None = None) -> str:
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        return self._open(req).read().decode("utf-8", "replace")

    def get_bytes(self, path: str, params: dict | None = None) -> bytes:
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        return self._open(req).read()

    def post(self, path: str, data: dict) -> str:
        body = urllib.parse.urlencode(data, doseq=True).encode()
        req = urllib.request.Request(
            self.base + path,
            data=body,
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        return self._open(req).read().decode("utf-8", "replace")

    def logged_in(self) -> bool:
        """True when the session cookie buys us a real page instead of the form."""
        try:
            page = self.get("/my/")
        except CwError:
            return False
        return 'name="password"' not in page and "login-form" not in page
