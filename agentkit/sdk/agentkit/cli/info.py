"""`agentkit info` -- environment + installed providers."""

from __future__ import annotations

import argparse
import importlib.util
import json as _json
import platform as _platform
import sys

from ._pkg import get_version


PROVIDERS = ["openai", "anthropic", "google.genai"]


def collect() -> dict:
    providers = []
    for mod in PROVIDERS:
        try:
            spec = importlib.util.find_spec(mod)
        except (ImportError, ValueError):
            spec = None
        if spec is not None:
            providers.append({"name": mod, "installed": True})
    return {
        "python": {"version": sys.version.split()[0], "executable": sys.executable},
        "platform": {"system": _platform.system(), "machine": _platform.machine(), "release": _platform.release()},
        "agentkit": {"version": get_version()},
        "providers": providers,
    }


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("info", help="display environment and agentkit configuration")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    data = collect()
    if args.json:
        print(_json.dumps(data, indent=2))
        return 0
    print(f"agentkit info\n{'=' * 40}")
    print(f"python:   {data['python']['version']} ({data['python']['executable']})")
    print(f"platform: {data['platform']['system']} {data['platform']['machine']}")
    print(f"agentkit: {data['agentkit']['version']}")
    if data["providers"]:
        names = ", ".join(p["name"] for p in data["providers"])
        print(f"providers: {names}")
    else:
        print("providers: (none installed)")
    return 0
