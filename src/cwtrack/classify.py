"""Turning the site's submission state into a verdict.

The precedence in classify() is the whole module. Two substring facts drive it:
"not submitted" contains "submitted", and a draft is not a submission. Getting
either backwards marks undone work as handed in.
"""

from __future__ import annotations

import re

from .dates import FA_DIGITS

OPEN_BUCKETS = {"overdue", "closed", "draft", "open"}



SUBMITTED_WORDS = (
    "submitted", "ارسال شده", "ارسال‌شده", "تحویل شده", "تحویل‌شده",
    "sent for marking", "sent for grading",
)
DRAFT_WORDS = ("draft", "پیش‌نویس", "پیش نویس")
NOT_SUBMITTED_WORDS = (
    "not submitted", "no submission", "none", "ارسال نشده", "ارسال‌نشده",
    "نامشخص", "بدون ارسال",
)
CLOSED_WORDS = ("closed", "بسته", "پایان یافته", "بسته شده")
GRADED_WORDS = ("graded", "نمره داده", "تصحیح شده", "نمره‌گذاری شده")

def _grade_score(text):
    """A mark, if the cell is one. Rejects '-' and dates.

    Persian digits and the Persian decimal separator show up in a Persian UI, so
    both are normalised first - otherwise "۱۹٫۵" reads as "not a grade" and a real
    mark is dropped from the dashboard.
    """
    if text is None:
        return None
    t = str(text).strip()
    if not t:
        return None
    t = t.translate(FA_DIGITS).replace("٫", ".").replace("٬", "")
    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?:\s*/\s*\d+)?", t):
        return None
    try:
        return float(t.split("/")[0].strip())
    except ValueError:
        return None


def _status_score(text: str) -> int:
    """How many status keywords a cell carries. Picks the status column reliably."""
    low = text.lower()
    return sum(1 for group in (SUBMITTED_WORDS, NOT_SUBMITTED_WORDS, DRAFT_WORDS,
                               CLOSED_WORDS, GRADED_WORDS) for w in group if w in low)


def classify(status: str, grade: str, due_epoch: int | None, now_epoch: int) -> str:
    """Bucket one assignment from its status cell, grade cell and deadline.

    Precedence is the whole logic, and it is driven by two facts:

    **"not submitted" contains "submitted"**, so testing the positive form first
    marks every undone assignment as handed in - the single failure this tool
    exists to prevent. That is why the status cell is passed in separately rather
    than matching against the concatenated row.

    **A draft is not a submission.** So the draft test outranks a number in the
    grade column: a stray mark next to "Draft" must not hide work that was never
    handed in.
    """
    low = status.lower().strip()

    if any(w in low for w in GRADED_WORDS):
        return "graded"
    if any(w in low for w in CLOSED_WORDS):
        return "closed"
    if any(w in low for w in DRAFT_WORDS):
        return "draft"
    # Negative before positive - see the docstring.
    if any(w in low for w in NOT_SUBMITTED_WORDS):
        return "overdue" if due_epoch and due_epoch < now_epoch else "open"
    if _grade_score(grade) is not None:
        return "graded"
    if any(w in low for w in SUBMITTED_WORDS):
        return "submitted"
    # No recognisable status: fall back to the deadline, never to optimism.
    if due_epoch and due_epoch < now_epoch:
        return "overdue"
    return "unknown"
