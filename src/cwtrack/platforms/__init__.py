"""Adapters for the course platforms supported by the shared coursework view."""

from .cw import CWAdapter
from .quera import QueraAdapter

__all__ = ["CWAdapter", "QueraAdapter"]
