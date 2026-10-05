"""Where things live: the page dump, the store, and the working folder.

Split out of cli.py because both entry points need it. The CLI is for a person at a
terminal; `api.py` is for a skill driving this from a shell. Neither should own the
answer to "which folder is the store in", because the one that owns it is the one
that has to be trusted when the other is not looking.

The rule this module exists to enforce: a missing store is never silently replaced by
an empty one. "You have no assignments" and "I could not find your data" are opposite
claims, and only one of them is safe to act on.
"""

from __future__ import annotations

import os
from pathlib import Path

STATE_DIR = Path(os.environ.get("CW_HOME", ".cw"))
DUMP_DIR = STATE_DIR / "dump"
DEFAULT_WORK_DIR = "work"


def find_data_dir(explicit: str = "") -> Path:
    """Locate cw-data/ without needing the right working directory.

    A bare relative "cw-data" silently finds nothing when the tool is run from
    another folder - and then reports zero assignments, which reads like "you have
    no homework" rather than "I looked in the wrong place".

    Order: the explicit flag, then any non-empty cw-data/ found walking up from the
    working directory, then one next to this project's checkout, then CWD.
    """
    if explicit:
        return Path(explicit)
    cwd = Path.cwd()
    for base in (cwd, Path(__file__).resolve().parent.parent.parent):
        for candidate in [base, *base.parents]:
            probe = candidate / "cw-data"
            if probe.is_dir() and any(probe.iterdir()):
                return probe
    return cwd / "cw-data"


def store_is_readable(data: Path) -> bool:
    """True only when there is a store worth reading, not merely a folder."""
    return data.is_dir() and (data / "assignments.json").is_file()


def describe_paths(data: Path, home: Path, work: Path | None = None) -> dict:
    """The paths a caller needs, as data rather than as prose.

    A skill reporting to a person wants to say "the brief is in <folder>" without
    reconstructing it from three defaults and a current directory.
    """
    return {
        "store": str(data.resolve()),
        "dump": str((home / "dump").resolve()),
        "work": str((work or data.parent / DEFAULT_WORK_DIR).resolve()),
    }
