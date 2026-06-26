"""Minimal ANSI styling with TTY detection."""

from __future__ import annotations

import os
import sys

_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

_CODES = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "cyan": "\033[36m",
    "gray": "\033[90m",
}


def color(text: str, *codes: str) -> str:
    if not _USE_COLOR or not codes:
        return text
    prefix = "".join(_CODES.get(c, "") for c in codes)
    return f"{prefix}{text}{_CODES['reset']}"
