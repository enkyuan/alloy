"""`kaji add <name>` -- install an integration from the registry.

shadcn-style: copies the integration's source files into the user's
project so they own and can edit the copies.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import sys

from kaji.integrations import (
    IntegrationNotFound,
    ManifestError,
    list_integrations,
    load_manifest,
)
from kaji.integrations.copy import (
    BundleStatus,
    BundleTransitionError,
    classify_integration_bundle,
    install_integration_bundle,
)

from ._pkg import TYPESCRIPT_SDK_CLI
from ._style import color


ADD_USAGE = (
    "usage: kaji add <name> [--out <dir>] [--force] "
    "[--allow-experimental] [--check] [--json]"
)


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "add",
        help="install an integration into your project (shadcn-style copy)",
    )
    p.add_argument("name", help="integration name (see `kaji list-integrations`)")
    p.add_argument(
        "--out",
        help="destination directory (default: ./integrations/<name>)",
    )
    p.add_argument(
        "--force", action="store_true", help="replace an unmodified outdated bundle"
    )
    p.add_argument(
        "--allow-experimental",
        action="store_true",
        help="allow copying an experimental integration",
    )
    p.add_argument("--check", action="store_true", help="classify without writing")
    p.add_argument("--json", action="store_true", help="print closed JSON output")
    p.set_defaults(func=run)


def _next_command(status: BundleStatus, manifest_name: str, experimental: bool) -> str:
    command = ["python", "-m", "kaji.cli", "add", manifest_name]
    if experimental:
        command.append("--allow-experimental")
    command.extend(("--out", str(status.destination)))
    if status.state == "outdated":
        command.append("--force")
    elif status.state not in {"absent"}:
        command.append("--check")
    return shlex.join(command)


def _render_status(
    status: BundleStatus, manifest_name: str, experimental: bool, json_output: bool
) -> None:
    next_command = _next_command(status, manifest_name, experimental)
    if json_output:
        print(
            json.dumps(
                {
                    "state": status.state,
                    "integration": manifest_name,
                    "runtime": "python",
                    "destination": str(status.destination),
                    "reason_code": status.reason_code,
                    "next_command": next_command,
                },
                separators=(",", ":"),
            )
        )
        return
    print(
        f"{status.state}: {manifest_name} at {status.destination} ({status.reason_code})"
    )
    print(f"next: {next_command}")


def run(args: argparse.Namespace) -> int:
    name = args.name
    dest = (Path(args.out) if args.out else Path("./integrations") / name).absolute()
    if args.check and args.force:
        print(
            color("--check cannot be combined with --force", "red"),
            file=sys.stderr,
        )
        print(ADD_USAGE, file=sys.stderr)
        return 2
    try:
        manifest = load_manifest(name)
    except IntegrationNotFound:
        available = ", ".join(list_integrations()) or "(none)"
        print(color(f"Unknown integration: {name!r}.", "red"), file=sys.stderr)
        print(f"Available: {available}", file=sys.stderr)
        return 1
    except ManifestError as e:
        print(color(f"Manifest error: {e}", "red"), file=sys.stderr)
        return 1

    if manifest.stability == "experimental" and not (
        args.allow_experimental or args.check
    ):
        print(
            color(
                f"Integration {name!r} is experimental. Re-run with --allow-experimental.",
                "red",
            ),
            file=sys.stderr,
        )
        return 1

    if args.check:
        status = classify_integration_bundle(manifest, dest, runtime="python")
        _render_status(
            status, manifest.name, manifest.stability == "experimental", args.json
        )
        return status.exit_code

    try:
        status = install_integration_bundle(
            manifest, dest, runtime="python", force=args.force
        )
    except BundleTransitionError as error:
        _render_status(
            error.status,
            manifest.name,
            manifest.stability == "experimental",
            args.json,
        )
        return error.status.exit_code
    except ManifestError as e:
        print(color(f"Install error: {e}", "red"), file=sys.stderr)
        return 1

    if args.json:
        _render_status(
            status, manifest.name, manifest.stability == "experimental", True
        )
        return 0
    if not status.written:
        _render_status(
            status, manifest.name, manifest.stability == "experimental", False
        )
        return 0
    for p in status.written:
        print(f"  wrote {p}")
    print()
    print(color(f"Installed integration: {manifest.name} v{manifest.version}", "green"))
    print(f"  {manifest.description}")
    if manifest.auth.kind == "env" and manifest.auth.env:
        if manifest.name == "github":
            print(
                color(
                    f"next: set {manifest.auth.env} to a fine-grained token limited to the configured repositories",
                    "yellow",
                )
            )
            print(f"docs: {manifest.auth.docs}")
        else:
            msg = f"  next: set {manifest.auth.env} in your environment"
            if manifest.auth.docs:
                msg += f" (see {manifest.auth.docs})"
            print(color(msg, "yellow"))
    elif manifest.auth.kind == "oauth":
        scopes = ", ".join(manifest.auth.scopes) or "(none declared)"
        print(color(f"  client ID env: {manifest.auth.client_id_env}", "yellow"))
        if manifest.auth.client_secret_env:
            print(
                color(
                    f"  client secret env: {manifest.auth.client_secret_env}", "yellow"
                )
            )
        print(color(f"  scopes: {scopes}", "yellow"))
        if manifest.auth.docs:
            print(f"  docs: {manifest.auth.docs}")
        print(
            "  connect (Python): "
            f"python -m kaji.cli connect {manifest.name} "
            "--principal <stable-host-principal-id>"
        )
        print(
            "  connect (TypeScript): "
            f"{TYPESCRIPT_SDK_CLI} connect {manifest.name} "
            "--principal <stable-host-principal-id>"
        )
    if manifest.extras and manifest.auth.kind != "oauth":
        print(color(f"  also: pip install {' '.join(manifest.extras)}", "yellow"))
    return 0
