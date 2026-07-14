"""`kaji upgrade` - bring installed kaji packages up to date."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from importlib.metadata import distributions

from ._style import color


_KAJI_DISTRIBUTIONS = frozenset({"kaji-sdk", "kaji-serve"})


def _parse_version(v: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in v.split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def fetch_latest_pypi(name: str, opener=urllib.request.urlopen) -> str | None:
    try:
        with opener(f"https://pypi.org/pypi/{name}/json", timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        return (data.get("info") or {}).get("version")
    except Exception:
        return None


def list_installed_kaji() -> dict[str, str]:
    out: dict[str, str] = {}
    for d in distributions():
        name = d.metadata["Name"] or ""
        if name.lower() in _KAJI_DISTRIBUTIONS:
            out[name] = d.version
    return out


def find_outdated(installed: dict[str, str], fetcher=fetch_latest_pypi) -> list[dict]:
    out = []
    for name, current in installed.items():
        latest = fetcher(name)
        if not latest:
            continue
        if _parse_version(current) < _parse_version(latest):
            out.append({"name": name, "current": current, "latest": latest})
    return out


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("upgrade", help="upgrade kaji packages")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    installed = list_installed_kaji()
    if not installed:
        print("No kaji packages found in this environment.")
        return 0
    outdated = find_outdated(installed)
    if not outdated:
        print("All kaji packages are up to date.")
        return 0
    print("\nThe following packages can be upgraded:\n")
    for u in outdated:
        print(
            f"  {color(u['name'], 'cyan')} {color(u['current'], 'gray')} → {color(u['latest'], 'green')}"
        )
    if not args.yes:
        ans = input("\nUpgrade these packages? [Y/n] ").strip().lower()
        if ans and ans not in ("y", "yes"):
            print("Cancelled.")
            return 0
    specs = [f"{u['name']}=={u['latest']}" for u in outdated]
    rc = subprocess.call([sys.executable, "-m", "pip", "install", "--upgrade", *specs])
    return 0 if rc == 0 else 1
