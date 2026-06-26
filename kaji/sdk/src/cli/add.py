"""`kaji add <name>` -- install an integration from the registry.

shadcn-style: copies the integration's source files into the user's
project so they own and can edit the copies.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from kaji.integrations import (
    IntegrationNotFound,
    ManifestError,
    install_integration,
    list_integrations,
    load_manifest,
)

from ._style import color


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "add",
        help="install an integration into your project (shadcn-style copy)",
    )
    p.add_argument("name", help="integration name (see `kaji list-integrations`)")
    p.add_argument(
        "--out",
        default="./integrations",
        help="destination directory (default: ./integrations)",
    )
    p.add_argument("--force", action="store_true", help="overwrite existing files")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    name = args.name
    dest = Path(args.out).resolve()
    try:
        manifest = load_manifest(name)
    except IntegrationNotFound:
        available = ", ".join(list_integrations()) or "(none)"
        print(color(f"Unknown integration: {name!r}.", "red"))
        print(f"Available: {available}")
        return 1
    except ManifestError as e:
        print(color(f"Manifest error: {e}", "red"))
        return 1

    try:
        written = install_integration(name, dest, force=args.force)
    except FileExistsError as e:
        print(color(str(e), "red"))
        return 1
    except ManifestError as e:
        print(color(f"Install error: {e}", "red"))
        return 1

    for p in written:
        print(f"  wrote {p}")
    print()
    print(color(f"Installed integration: {manifest.name} v{manifest.version}", "green"))
    print(f"  {manifest.description}")
    if manifest.auth.kind == "env" and manifest.auth.env:
        msg = f"  next: set {manifest.auth.env} in your environment"
        if manifest.auth.docs:
            msg += f" (see {manifest.auth.docs})"
        print(color(msg, "yellow"))
    elif manifest.auth.kind == "oauth":
        scopes = ", ".join(manifest.auth.scopes) or "(none declared)"
        print(color(f"  next: complete OAuth setup; scopes: {scopes}", "yellow"))
        if manifest.auth.docs:
            print(f"        docs: {manifest.auth.docs}")
    if manifest.extras:
        print(color(f"  also: pip install {' '.join(manifest.extras)}", "yellow"))
    return 0
