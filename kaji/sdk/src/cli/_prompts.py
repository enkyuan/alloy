"""Stdlib-only interactive prompts.

Falls back to numeric input on non-TTY. Arrow-key UI deliberately omitted --
that would require curses/termios complexity for marginal UX gain. Numeric
selection is fine and is what most CI scripts want anyway.
"""

from __future__ import annotations

import sys


def select(message: str, options: list[tuple[str, str]]) -> str:
    """options is a list of (value, label). Returns the chosen value."""
    print(f"{message}")
    for i, (_, label) in enumerate(options, start=1):
        print(f"  {i}) {label}")
    while True:
        raw = input("? ").strip()
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1][0]
        for value, _ in options:
            if raw == value:
                return value
        print(f"Choose 1-{len(options)} (or type the value).", file=sys.stderr)


def confirm(message: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    raw = input(f"{message} {suffix} ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def text(message: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    raw = input(f"{message}{suffix}: ").strip()
    return raw or (default or "")
