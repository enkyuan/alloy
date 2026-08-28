"""`kaji list-integrations` -- enumerate the registry."""

from __future__ import annotations

import argparse
import json as _json
from typing import TypedDict

from kaji.integrations import (
    Manifest,
    ManifestError,
    list_integrations as _list,
    load_manifest,
)

from ._pkg import TYPESCRIPT_SDK_CLI


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "list-integrations",
        help="list integrations available via `kaji add`",
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)


class _AuthRow(TypedDict):
    kind: str
    provider: str | None


class _IntegrationRow(TypedDict):
    name: str
    version: str
    stability: str
    runtimes: list[str]
    auth: _AuthRow
    experimental_opt_in_required: bool
    next_commands: dict[str, str]


def _next_commands(manifest: Manifest) -> dict[str, str]:
    experimental = manifest.stability == "experimental"
    commands: dict[str, str] = {}
    for runtime in sorted(manifest.runtimes):
        if manifest.auth.kind == "oauth":
            if runtime == "python":
                command = (
                    f"python -m kaji.cli connect {manifest.name} "
                    "--principal <stable-host-principal-id>"
                )
            else:
                command = (
                    f"{TYPESCRIPT_SDK_CLI} connect {manifest.name} "
                    "--principal <stable-host-principal-id>"
                )
        elif runtime == "python":
            command = f"python -m kaji.cli add {manifest.name}"
            if experimental:
                command += " --allow-experimental"
        else:
            command = f"{TYPESCRIPT_SDK_CLI} add {manifest.name}"
            if experimental:
                command += " --allow-experimental"
        commands[runtime] = command
    return commands


def _row(manifest: Manifest) -> _IntegrationRow:
    return {
        "name": manifest.name,
        "version": manifest.version,
        "stability": manifest.stability,
        "runtimes": sorted(manifest.runtimes),
        "auth": {
            "kind": manifest.auth.kind,
            "provider": manifest.auth.provider,
        },
        "experimental_opt_in_required": manifest.stability == "experimental",
        "next_commands": _next_commands(manifest),
    }


def run(args: argparse.Namespace) -> int:
    try:
        manifests = [load_manifest(name) for name in sorted(_list())]
    except ManifestError as error:
        print(f"Registry error: {error}")
        return 1
    rows = [_row(manifest) for manifest in manifests]
    if args.json:
        data = rows
        print(_json.dumps(data, indent=2))
        return 0

    if not manifests:
        print("No integrations available.")
        return 0

    for row in rows:
        auth = row["auth"]
        provider = auth["provider"]
        auth_label = auth["kind"] if provider is None else f"{auth['kind']}:{provider}"
        runtimes = ",".join(row["runtimes"])
        print(
            f"{row['name']}  [{row['stability']}]  v{row['version']}  "
            f"auth={auth_label}  runtimes={runtimes}"
        )
        commands = row["next_commands"]
        for runtime, command in commands.items():
            print(f"  {runtime}: {command}")
    return 0
