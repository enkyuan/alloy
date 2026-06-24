"""`kaji doctor` -- environment sanity checks."""

from __future__ import annotations

import argparse
import json as _json
import os
import sys

from ._pkg import get_version
from ._style import color

PROVIDER_KEYS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "KIMI_API_KEY",
)


def run_checks(env: dict, python_version: str, kaji_version: str) -> dict:
    checks = []
    major, minor = (int(x) for x in python_version.split(".")[:2])
    checks.append(
        {
            "name": "python >= 3.11",
            "ok": (major, minor) >= (3, 11),
            "detail": python_version,
        }
    )
    checks.append(
        {
            "name": "kaji installed",
            "ok": kaji_version != "0.0.0",
            "detail": kaji_version,
        }
    )
    has_provider = any((env.get(k) or "") for k in PROVIDER_KEYS)
    checks.append(
        {
            "name": "provider key",
            "ok": has_provider,
            "detail": " | ".join(PROVIDER_KEYS),
        }
    )
    failed = any(not c["ok"] for c in checks)
    return {"checks": checks, "failed": failed}


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "doctor", help="check the environment for common kaji issues"
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    py = ".".join(str(v) for v in sys.version_info[:3])
    out = run_checks(
        env=dict(os.environ), python_version=py, kaji_version=get_version()
    )
    if args.json:
        print(_json.dumps(out, indent=2))
    else:
        for c in out["checks"]:
            mark = color("✓", "green") if c["ok"] else color("✗", "red")
            detail = color(f" ({c['detail']})", "gray") if c.get("detail") else ""
            print(f"{mark} {c['name']}{detail}")
    return 1 if out["failed"] else 0
