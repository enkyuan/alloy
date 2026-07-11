"""`kaji list-integrations` -- enumerate the registry."""

from __future__ import annotations

import argparse
import json as _json

from kaji.integrations import ManifestError, list_integrations as _list, load_manifest


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "list-integrations",
        help="list integrations available via `kaji add`",
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    try:
        manifests = [load_manifest(name) for name in _list()]
    except ManifestError as error:
        print(f"Registry error: {error}")
        return 1
    if args.json:
        data = [
            {
                "name": manifest.name,
                "version": manifest.version,
                "namespace": manifest.namespace,
                "description": manifest.description,
                "auth_kind": manifest.auth.kind,
                "tools": [tool.name for tool in manifest.tools],
                "stability": manifest.stability,
                "runtimes": list(manifest.runtimes),
            }
            for manifest in manifests
        ]
        print(_json.dumps(data, indent=2))
        return 0

    if not manifests:
        print("No integrations available.")
        return 0

    for manifest in manifests:
        print(
            f"  {manifest.name:<16} [{manifest.stability}] "
            f"v{manifest.version:<8} {manifest.description}"
        )
    return 0
