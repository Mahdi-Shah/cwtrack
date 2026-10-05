"""Shared fixtures.

The HTML fixtures are sanitised captures: the shape is the real one, the
identifying content is not. Tests must never depend on a real course id, a real
student number, or a real capture of somebody's coursework.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

FIXTURES = Path(__file__).parent / "fixtures"

# A fixed clock. Every date test is meaningless without one: "3 days left"
# computed against the wall clock stops being true the moment the suite is slow.
NOW = datetime(2026, 10, 5, 12, 0, 0)
NOW_EPOCH = int(NOW.timestamp())


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def now_epoch() -> int:
    return NOW_EPOCH


@pytest.fixture
def assign_page() -> str:
    return (FIXTURES / "course_90000_assign.html").read_text(encoding="utf-8")


@pytest.fixture
def dump_dir(tmp_path: Path) -> Path:
    """A page dump directory holding the sanitised fixture."""
    d = tmp_path / "dump"
    d.mkdir()
    for f in FIXTURES.glob("course_*.html"):
        (d / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    return d
