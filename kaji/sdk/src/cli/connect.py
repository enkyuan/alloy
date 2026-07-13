"""`kaji connect`: explicitly establish a manifest-declared OAuth grant."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping, Sequence
import os
from typing import Any

from kaji.integrations import (
    IntegrationNotFound,
    Manifest,
    ManifestError,
    load_manifest,
)
from kaji.integrations.errors import IntegrationExecutionError
from kaji.integrations.keychain import MacOSKeychainTokenStorage
from kaji.integrations.oauth import GoogleOAuthClient, OAuthError, _require_principal
from kaji.integrations.recovery import recovery_for_reason
from kaji.runtime.agents.cancellation import CancellationToken


_environment: Mapping[str, str] = os.environ


class UniqueValue(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        if getattr(namespace, self.dest, None) is not None:
            parser.error(f"{option_string} may be specified only once")
        setattr(namespace, self.dest, values)


def add_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("connect", help="connect an integration OAuth grant")
    parser.add_argument("name")
    parser.add_argument("--principal", required=True, action=UniqueValue, default=None)
    parser.set_defaults(func=run)


def qualified_command(name: str, action: str) -> str:
    return f"python -m kaji.cli {action} {name} --principal <stable-host-principal-id>"


def oauth_manifest(name: str) -> Manifest:
    manifest = load_manifest(name)
    if manifest.auth.kind != "oauth":
        raise ValueError(f"Integration {name!r} does not use OAuth.")
    if manifest.auth.provider != "google":
        raise ValueError(f"Integration {name!r} has an unsupported OAuth provider.")
    return manifest


def _production_client(
    *,
    manifest: Manifest,
    principal: str,
    client_id: str | None,
    client_secret: str | None,
) -> GoogleOAuthClient:
    storage = MacOSKeychainTokenStorage(manifest.name)
    storage._preflight(principal)
    return GoogleOAuthClient(
        client_id=client_id,
        client_secret=client_secret,
        scopes=manifest.auth.scopes,
        credential_store=storage,
    )


def render_recovery(error: IntegrationExecutionError, *, command: str) -> None:
    recovery = recovery_for_reason(error.reason_code)
    print(recovery.error_code)
    print(f"Problem: {recovery.problem}")
    print(f"Cause: {recovery.cause}")
    print(f"Fix: {recovery.fix}")
    print(f"Command: {command}")


async def _connect(client: GoogleOAuthClient, principal: str) -> None:
    await client.connect(principal, CancellationToken())


def run(args: argparse.Namespace) -> int:
    command = qualified_command(args.name, "connect")
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

    client_id_name = manifest.auth.client_id_env
    if client_id_name is None:
        print("INTEGRATION_AUTH_REQUIRED: OAuth client ID metadata is missing.")
        print(f"Command: {command}")
        return 1
    client_id = _environment.get(client_id_name)
    if not client_id:
        print(f"INTEGRATION_AUTH_REQUIRED: {client_id_name} is not set.")
        print(
            f"Create a Google Desktop OAuth client, load {client_id_name}, then rerun:"
        )
        print(command)
        return 1
    client_secret = (
        _environment.get(manifest.auth.client_secret_env)
        if manifest.auth.client_secret_env is not None
        else None
    )
    try:
        client = _production_client(
            manifest=manifest,
            principal=principal,
            client_id=client_id,
            client_secret=client_secret,
        )
        asyncio.run(_connect(client, principal))
    except asyncio.CancelledError:
        print("INTEGRATION_AUTH_ERROR: OAuth connection was cancelled.")
        print("Cause: The operation was cancelled before grant storage completed.")
        print(f"Command: {command}")
        return 1
    except KeyboardInterrupt:
        print("INTEGRATION_AUTH_ERROR: OAuth connection was cancelled.")
        print("Cause: The operation was interrupted before grant storage completed.")
        print(f"Command: {command}")
        return 1
    except IntegrationExecutionError as error:
        render_recovery(error, command=command)
        return 1
    except OAuthError:
        print("INTEGRATION_AUTH_ERROR: Google OAuth consent did not complete.")
        print("Cause: The provider denied or failed the installed-app consent flow.")
        print(f"Command: {command}")
        return 1

    print(f"Connected {manifest.name} for the requested principal.")
    print(
        "Stored refresh credentials in macOS Keychain service "
        f"dev.kaji.oauth.{manifest.name}."
    )
    return 0
