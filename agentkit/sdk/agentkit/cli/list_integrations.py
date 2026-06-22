"""`agentkit list-integrations` -- enumerate the registry."""

from __future__ import annotations

import argparse
import json as _json

from agentkit.integrations import list_integrations as _list, load_manifest


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "list-integrations",
        help="list integrations available via `agentkit add`",
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    names = _list()
    if args.json:
        data = []
        for name in names:
            m = load_manifest(name)
            data.append(
                {
                    "name": m.name,
                    "version": m.version,
                    "namespace": m.namespace,
                    "description": m.description,
                    "auth_kind": m.auth.kind,
                    "tools": [t.name for t in m.tools],
                }
            )
        print(_json.dumps(data, indent=2))
        return 0

    if not names:
        print("No integrations available.")
        return 0

    for name in names:
        m = load_manifest(name)
        print(f"  {m.name:<16} v{m.version:<8} {m.description}")
    return 0
