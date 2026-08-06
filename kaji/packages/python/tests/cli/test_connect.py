from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import json
from pathlib import Path
from types import MappingProxyType

import pytest

from kaji.integrations import IntegrationNotFound, Manifest, ManifestAuth
from kaji.integrations.errors import IntegrationAuthError
from kaji.integrations.oauth import DisconnectResult, OAuthError


def oauth_manifest() -> Manifest:
    return Manifest(
        name="gmail",
        version="0.1.0",
        namespace="gmail",
        description="Gmail fixture.",
        auth=ManifestAuth(
            kind="oauth",
            provider="google",
            client_id_env="GOOGLE_CLIENT_ID",
            client_secret_env="GOOGLE_CLIENT_SECRET",
            scopes=("scope.a", "scope.b"),
        ),
        files=("gmail.py",),
        tools=(),
        extras=(),
        peer_deps=MappingProxyType({}),
        stability="experimental",
        runtimes=("python", "typescript"),
        path=Path("/fixture/gmail/manifest.json"),
    )


def namespace(**values: object) -> argparse.Namespace:
    return argparse.Namespace(
        name=values.pop("name", "gmail"),
        principal=values.pop("principal", "host:user"),
        **values,
    )


class UnreadableEnvironment:
    def get(self, _name: str) -> str | None:
        pytest.fail("environment read too early")


def test_parser_registers_exact_connect_and_disconnect_grammar() -> None:
    from kaji.cli._main import _build_parser

    parser = _build_parser()
    connected = parser.parse_args(["connect", "gmail", "--principal", "host:user"])
    disconnected = parser.parse_args(
        ["disconnect", "gmail", "--principal", "host:user", "--force-local"]
    )
    assert (connected.command, connected.name, connected.principal) == (
        "connect",
        "gmail",
        "host:user",
    )
    assert disconnected.force_local is True
    for argv in (
        ["connect", "gmail"],
        ["connect", "gmail", "--principal", "a", "--principal", "b"],
        ["disconnect", "gmail", "--principal", "a", "--unknown"],
        [
            "disconnect",
            "gmail",
            "--principal",
            "a",
            "--force-local",
            "--force-local",
        ],
    ):
        with pytest.raises(SystemExit) as error:
            parser.parse_args(argv)
        assert error.value.code == 2


def test_connect_validates_principal_before_registry_or_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from kaji.cli import connect

    monkeypatch.setattr(
        connect, "load_manifest", lambda _name: pytest.fail("registry read too early")
    )
    monkeypatch.setattr(connect, "_environment", UnreadableEnvironment())

    assert connect.run(namespace(principal="bad principal")) == 1
    output = capsys.readouterr().out
    assert "INTEGRATION_POLICY_REJECTED" in output
    assert "bad principal" not in output


def test_connect_orders_manifest_auth_and_environment_before_construction(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from kaji.cli import connect

    class Environment:
        def get(self, name: str) -> str | None:
            assert name == "GOOGLE_CLIENT_ID"
            return None

    monkeypatch.setattr(connect, "load_manifest", lambda _name: oauth_manifest())
    monkeypatch.setattr(connect, "_environment", Environment())
    monkeypatch.setattr(
        connect,
        "_production_client",
        lambda **_kwargs: pytest.fail("constructed too early"),
    )

    assert connect.run(namespace()) == 1
    output = capsys.readouterr().out
    assert "INTEGRATION_AUTH_REQUIRED: GOOGLE_CLIENT_ID is not set." in output
    assert (
        "python -m kaji.cli connect gmail --principal <stable-host-principal-id>"
        in output
    )


@pytest.mark.parametrize(
    ("manifest", "expected"),
    [
        (
            lambda: replace(oauth_manifest(), auth=ManifestAuth(kind="none")),
            "does not use OAuth",
        ),
        (
            lambda: replace(
                oauth_manifest(),
                auth=ManifestAuth(
                    kind="oauth",
                    provider=None,
                    client_id_env="GOOGLE_CLIENT_ID",
                    scopes=("scope.a",),
                ),
            ),
            "unsupported OAuth provider",
        ),
    ],
)
def test_connect_rejects_non_oauth_or_unsupported_provider_without_env(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    manifest,
    expected: str,
) -> None:
    from kaji.cli import connect

    class Environment:
        def get(self, _name: str) -> str | None:
            pytest.fail("environment read too early")

    monkeypatch.setattr(connect, "load_manifest", lambda _name: manifest())
    monkeypatch.setattr(connect, "_environment", Environment())
    assert connect.run(namespace()) == 1
    assert expected in capsys.readouterr().out


def test_connect_rejects_overlong_manifest_name_before_env_or_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import kaji.integrations as integrations
    from kaji.cli import connect

    packaged_registry = integrations._registry_root()
    registry = tmp_path / "registry"
    integration = registry / "oversize"
    integration.mkdir(parents=True)
    for schema in ("schema.json", "index.schema.json"):
        (registry / schema).write_bytes((packaged_registry / schema).read_bytes())
    (registry / "index.json").write_text(
        json.dumps(
            {
                "$schema": "./index.schema.json",
                "version": "0.1.0",
                "integrations": {
                    "oversize": {
                        "manifest": "oversize/manifest.json",
                        "stability": "experimental",
                        "runtimes": ["python"],
                    }
                },
            }
        )
    )
    (integration / "manifest.json").write_text(
        json.dumps(
            {
                "name": "a" * 129,
                "version": "0.1.0",
                "namespace": "oversize",
                "description": "Overlong fixture.",
                "auth": {
                    "kind": "oauth",
                    "provider": "google",
                    "clientIdEnv": "GOOGLE_CLIENT_ID",
                    "scopes": ["scope.read"],
                },
                "files": ["oversize.py"],
                "tools": [
                    {
                        "name": "ping",
                        "description": "Fixture tool.",
                        "parameters": {"type": "object"},
                        "risk": "read",
                        "parallel_safe": True,
                    }
                ],
            }
        )
    )
    (integration / "oversize.py").write_text("")
    monkeypatch.setattr(integrations, "_registry_root", lambda: registry)
    monkeypatch.setattr(connect, "_environment", UnreadableEnvironment())
    monkeypatch.setattr(
        connect,
        "_production_client",
        lambda **_kwargs: pytest.fail("storage constructed too early"),
    )

    assert connect.run(namespace(name="oversize")) == 1
    output = capsys.readouterr().out
    assert "maxLength" in output
    assert "/name" in output


@pytest.mark.parametrize("command", ["connect", "disconnect"])
def test_oauth_commands_accept_generic_google_manifest_with_matching_guidance(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    from kaji.cli import connect, disconnect, list_integrations
    from kaji.cli._main import _build_parser

    module = connect if command == "connect" else disconnect
    calendar = replace(oauth_manifest(), name="calendar", namespace="calendar")
    constructed: list[str] = []

    class Client:
        async def connect(self, _principal: str, _cancellation) -> None:
            return None

        async def disconnect(
            self, _principal: str, _cancellation, *, force_local: bool = False
        ) -> DisconnectResult:
            assert force_local is False
            return DisconnectResult("missing", False)

    def production_client(**kwargs: object) -> Client:
        manifest = kwargs["manifest"]
        assert isinstance(manifest, Manifest)
        constructed.append(manifest.name)
        return Client()

    monkeypatch.setattr(module, "load_manifest", lambda _name: calendar)
    monkeypatch.setattr(
        module,
        "_production_client",
        production_client,
    )

    if command == "disconnect":
        args = namespace(name="calendar")
        monkeypatch.setattr(module, "_environment", UnreadableEnvironment())
        args.force_local = False
    else:
        advertised = list_integrations._next_commands(calendar)["python"]
        argv = advertised.replace("<stable-host-principal-id>", "host:user").split()[3:]
        args = _build_parser().parse_args(argv)
        monkeypatch.setattr(
            module,
            "_environment",
            {"GOOGLE_CLIENT_ID": "client-secret-value"},
        )
    assert module.run(args) == 0
    assert constructed == ["calendar"]
    output = capsys.readouterr().out
    assert "gmail" not in output
    assert "calendar" in output
    assert "client-secret-value" not in output
    if command == "connect":
        assert "dev.kaji.oauth.calendar" in output


def test_production_client_passes_manifest_name_to_keychain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kaji.cli import connect

    calendar = replace(oauth_manifest(), name="calendar", namespace="calendar")
    calls: list[tuple[str, str]] = []

    class Storage:
        def __init__(self, integration_name: str) -> None:
            calls.append(("storage", integration_name))

        def _preflight(self, principal: str) -> None:
            calls.append(("preflight", principal))

    class Client:
        def __init__(self, **kwargs: object) -> None:
            assert isinstance(kwargs["credential_store"], Storage)

    monkeypatch.setattr(connect, "MacOSKeychainTokenStorage", Storage)
    monkeypatch.setattr(connect, "GoogleOAuthClient", Client)
    connect._production_client(
        manifest=calendar,
        principal="host:user",
        client_id=None,
        client_secret=None,
    )
    assert calls == [("storage", "calendar"), ("preflight", "host:user")]


def test_connect_delegates_once_and_prints_only_bounded_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from kaji.cli import connect

    calls: list[tuple[str, bool]] = []

    class Client:
        async def connect(self, principal: str, _cancellation) -> None:
            calls.append((principal, True))

    monkeypatch.setattr(connect, "load_manifest", lambda _name: oauth_manifest())
    monkeypatch.setattr(
        connect,
        "_environment",
        {"GOOGLE_CLIENT_ID": "client-secret-value", "GOOGLE_CLIENT_SECRET": "secret"},
    )
    monkeypatch.setattr(connect, "_production_client", lambda **_kwargs: Client())

    assert connect.run(namespace()) == 0
    assert calls == [("host:user", True)]
    assert capsys.readouterr().out == (
        "Connected gmail for the requested principal.\n"
        "Stored refresh credentials in macOS Keychain service dev.kaji.oauth.gmail.\n"
    )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (IntegrationAuthError("keychain_unsupported"), "INTEGRATION_AUTH_ERROR"),
        (OAuthError(), "INTEGRATION_AUTH_ERROR"),
        (asyncio.CancelledError(), "OAuth connection was cancelled"),
    ],
)
def test_connect_maps_redacted_failures_to_qualified_recovery(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: BaseException,
    expected: str,
) -> None:
    from kaji.cli import connect

    class Client:
        async def connect(self, _principal: str, _cancellation) -> None:
            raise error

    monkeypatch.setattr(connect, "load_manifest", lambda _name: oauth_manifest())
    monkeypatch.setattr(connect, "_environment", {"GOOGLE_CLIENT_ID": "configured"})
    monkeypatch.setattr(connect, "_production_client", lambda **_kwargs: Client())
    assert connect.run(namespace()) == 1
    output = capsys.readouterr().out
    assert expected in output
    assert (
        "python -m kaji.cli connect gmail --principal <stable-host-principal-id>"
        in output
    )
    assert "host:user" not in output


def test_disconnect_never_reads_client_environment_and_passes_force_local(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from kaji.cli import disconnect

    calls: list[tuple[str, bool]] = []

    class Environment:
        def get(self, _name: str) -> str | None:
            pytest.fail("disconnect read client environment")

        def __getitem__(self, _name: str) -> str:
            pytest.fail("disconnect read client environment")

    class Client:
        async def disconnect(
            self, principal: str, _cancellation, *, force_local: bool = False
        ) -> DisconnectResult:
            calls.append((principal, force_local))
            return DisconnectResult("deleted", False)

    monkeypatch.setattr(disconnect, "load_manifest", lambda _name: oauth_manifest())
    monkeypatch.setattr(disconnect, "_environment", Environment())
    monkeypatch.setattr(disconnect, "_production_client", lambda **_kwargs: Client())

    assert disconnect.run(namespace(force_local=True)) == 0
    assert calls == [("host:user", True)]
    output = capsys.readouterr().out
    assert "remote access may remain" in output
    assert "host:user" not in output


def test_disconnect_pending_is_retryable_and_manual_without_secret_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from kaji.cli import disconnect

    class Client:
        async def disconnect(self, *_args, **_kwargs) -> DisconnectResult:
            return DisconnectResult("revocation_pending", False)

    monkeypatch.setattr(disconnect, "load_manifest", lambda _name: oauth_manifest())
    monkeypatch.setattr(disconnect, "_production_client", lambda **_kwargs: Client())
    assert disconnect.run(namespace(force_local=False)) == 1
    output = capsys.readouterr().out
    assert "revocation is not confirmed" in output
    assert "Google Account" in output
    assert (
        "python -m kaji.cli disconnect gmail --principal <stable-host-principal-id>"
        in output
    )


def test_unknown_integration_is_bounded_and_does_not_read_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from kaji.cli import connect

    monkeypatch.setattr(
        connect,
        "load_manifest",
        lambda _name: (_ for _ in ()).throw(IntegrationNotFound("missing")),
    )
    monkeypatch.setattr(connect, "_environment", UnreadableEnvironment())
    assert connect.run(namespace()) == 1
    assert "Unknown integration" in capsys.readouterr().out
