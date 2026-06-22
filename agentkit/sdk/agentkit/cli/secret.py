"""`agentkit secret` -- generate a random 32-byte hex secret."""

from __future__ import annotations

import argparse
import json
import secrets

from ._style import color


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("secret", help="generate a random 32-byte hex secret")
    p.add_argument("--name", default="AGENTKIT_SECRET")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    value = secrets.token_hex(32)
    if args.json:
        print(json.dumps({"name": args.name, "value": value}))
        return 0
    print("\nAdd the following to your .env file:")
    print(color("# agentkit secret", "gray"))
    print(color(f"{args.name}={value}\n", "green"))
    return 0
