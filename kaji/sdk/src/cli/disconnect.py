"""`kaji disconnect`: revoke or explicitly remove a local OAuth grant."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping
import os

from kaji.integrations import (
    IntegrationNotFound,
    Manifest,
    ManifestError,
    load_manifest,
)
from kaji.integrations.errors import IntegrationExecutionError
from kaji.integrations.oauth import DisconnectResult, _require_principal

from .connect import UniqueValue, _production_client, qualified_command, render_recovery


_environment: Mapping[str, str] = os.environ


def add_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("disconnect", help="disconnect an integration OAuth grant")
    parser.add_argument("name")
    parser.add_argument("--principal", required=True, action=UniqueValue, default=None)
    parser.add_argument("--force-local", action="store_true")
    parser.set_defaults(func=run)


def oauth_manifest(name: str) -> Manifest:
    manifest = load_manifest(name)
    if manifest.auth.kind != "oauth":
        raise ValueError(f"Integration {name!r} does not use OAuth.")
    if manifest.auth.provider != "google":
        raise ValueError(f"Integration {name!r} has an unsupported OAuth provider.")
    return manifest


async def _disconnect(
    client,
    principal: str,
    *,
    force_local: bool,
) -> DisconnectResult:
    from kaji.runtime.agents.cancellation import CancellationToken

    return await client.disconnect(
        principal, CancellationToken(), force_local=force_local
    )


def run(args: argparse.Namespace) -> int:
    command = qualified_command(args.name, "disconnect")
    try:
        principal = _require_principal(args.principal)
    except IntegrationExecutionError:
        print("INTEGRATION_POLICY_REJECTED: The principal identifier is invalid.")
        print(f"Command: {command}")
        return 1
    try:
        manifest = oauth_manifest(args.name)
    except IntegrationNotFound:
        print(f"Unknown integration: {args.name!r}.")
        return 1
    except (ManifestError, ValueError) as error:
        print(str(error))
        return 1

    try:
        client = _production_client(
            manifest=manifest,
            principal=principal,
            client_id=None,
            client_secret=None,
        )
        result = asyncio.run(
            _disconnect(client, principal, force_local=args.force_local)
        )
    except (asyncio.CancelledError, KeyboardInterrupt):
        print("INTEGRATION_AUTH_ERROR: OAuth disconnect was cancelled.")
        print(f"Command: {command}")
        return 1
    except IntegrationExecutionError as error:
        render_recovery(error, command=command)
        return 1

    if result.local_state == "revocation_pending":
        print("INTEGRATION_AUTH_ERROR: Remote OAuth revocation is not confirmed.")
        print("Cause: The provider revocation result is ambiguous.")
        print(f"Retry: {command}")
        print("Or revoke Kaji manually in Google Account security settings.")
        return 1
    if result.local_state == "missing":
        print(
            f"No stored {manifest.name} credentials were found for the requested principal."
        )
        return 0
    if args.force_local and not result.remote_revoked:
        print(f"Deleted local {manifest.name} credentials for the requested principal.")
        print(
            "Warning: remote access may remain until manually revoked in Google Account settings."
        )
        return 0
    print(f"Disconnected {manifest.name} for the requested principal.")
    print("Confirmed remote OAuth revocation and removed local credentials.")
    return 0
