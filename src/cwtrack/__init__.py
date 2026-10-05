"""Coursework tracker for cw.sharif.ir (Moodle).

Reads your own assignments, submission status, deadlines and marks into a local
store, indexes a material folder per course, and renders a dashboard.

    from cwtrack import fetch_store, render_dashboard

Site-specific by design. The parsing, the calendar and the status vocabulary all
reflect cw.sharif.ir's theme and its Jalali dates; see README for the scope.

Read-only against the site: nothing is ever submitted, and no code path enumerates
another student's data.
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = [
    "CwError",
    "Client",
    "classify",
    "parse_due",
    "parse_dump",
    "gaps",
    "load",
    "store",
    "render_dashboard",
]


def __getattr__(name: str):
    # Lazy re-exports so `import cwtrack` stays cheap and so a broken optional
    # dependency in one module cannot break importing the rest.
    import importlib

    targets = {
        "CwError": "client",
        "Client": "client",
        "classify": "classify",
        "parse_due": "dates",
        "parse_dump": "parse",
        "gaps": "tracker",
        "load": "tracker",
        "store": "tracker",
        "render_dashboard": "dashboard",
    }
    if name in targets:
        return getattr(importlib.import_module("." + targets[name], __name__), name)
    raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
