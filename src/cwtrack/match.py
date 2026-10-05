"""Fuzzy-matching an unsubmitted assignment against a file on disk.

This is how work you finished but never uploaded gets found.
"""

from __future__ import annotations

import re
from pathlib import Path

from .classify import OPEN_BUCKETS

DOC_EXT = {".pdf", ".docx", ".doc", ".tex", ".md", ".zip", ".rar", ".7z"}

def _norm(text: str) -> set[str]:
    """Persian/Arabic shape folding plus digit folding, for fuzzy filename match."""
    text = re.sub(r"[ً-ْ‌]", "", text)
    text = re.sub(r"[کگ]", "ك", text)
    text = re.sub(r"ی", "ي", text)
    text = re.sub(r"[۰-۹]", lambda m: chr(ord("0") + int(m.group(0), 36)), text)
    text = re.sub(r"[٠-٩]", lambda m: chr(ord("0") + int(m.group(0), 36)), text)
    return set(re.findall(r"[^\W_]+", text.lower(), re.UNICODE))


def match_local(rows: list[dict], folder: Path) -> dict[str, list[str]]:
    """Unsubmitted assignments that have a lookalike document on disk.

    This is the part that finds work you finished and forgot to upload. It is a
    lead, not a conclusion - the user confirms.
    """
    if not folder.is_dir():
        return {}
    files = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in DOC_EXT]
    if not files:
        return {}
    stems = {p: _norm(p.stem) for p in files}
    out: dict[str, list[str]] = {}
    for row in rows:
        if row["bucket"] not in OPEN_BUCKETS:
            continue
        target = _norm("{} {}".format(row["name"], row["course"]))
        if not target:
            continue
        hits = [str(p.relative_to(folder)) for p in files if len(stems[p] & target) >= 2]
        if hits:
            out["{}|{}".format(row["name"], row["course"])] = hits
    return out
