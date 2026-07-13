from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from kaji.integrations.errors import IntegrationAuthError, IntegrationPolicyError
from kaji.integrations.keychain import (
    _AsyncioKeychainProcess,
    _create_macos_keychain_storage_for_test,
)
from kaji.integrations.oauth import OAuthCredentialRecord, OAuthTokenSet
from kaji.runtime.agents.cancellation import CancellationToken


PRINCIPAL = "User:123"
SERVICE = "dev.kaji.oauth.gmail"
ACCOUNT = hashlib.sha256(f"{SERVICE}\0{PRINCIPAL}".encode()).hexdigest()


def record() -> OAuthCredentialRecord:
    return OAuthCredentialRecord(
        schema_version=1,
        state="active",
        tokens=OAuthTokenSet(
            access_token="secret-access",
            refresh_token="secret-refresh",
            expires_at_epoch_ms=1_700_000_000_000,
            granted_scopes=("scope/a",),
        ),
    )


class Process:
    def __init__(self, results: list[tuple[int, str]] | None = None) -> None:
        self.results = list(results or [(0, "")])
        self.calls: list[tuple[tuple[str, ...], str | None]] = []

    async def run(
        self,
        args: tuple[str, ...],
        *,
        stdin: str | None,
        cancellation: CancellationToken,
        deadline_monotonic: float | None,
        timeout_seconds: float,
        max_stdout_bytes: int,
    ) -> tuple[int, str]:
        cancellation.raise_if_cancelled()
        self.calls.append((args, stdin))
        return self.results.pop(0)


def storage(process: Process, *, platform: str = "darwin", executable: bool = True):
    return _create_macos_keychain_storage_for_test(
        process=process, platform=platform, executable=executable
    )


@pytest.mark.asyncio
async def test_keychain_uses_hashed_account_exact_argv_and_json_stdin() -> None:
    process = Process()
    keychain = storage(process)
    await keychain.save(PRINCIPAL, record(), CancellationToken(), None)
    args, stdin = process.calls[0]
    assert args == (
        "add-generic-password",
        "-a",
        ACCOUNT,
        "-s",
        SERVICE,
        "-U",
        "-w",
    )
    assert (
        stdin is not None
        and json.loads(stdin)["tokens"]["accessToken"] == "secret-access"
    )
    assert PRINCIPAL not in repr(process.calls)


@pytest.mark.asyncio
async def test_keychain_load_and_delete_use_fixed_commands() -> None:
    wire = json.dumps(record().to_wire(), separators=(",", ":"), sort_keys=True)
    process = Process([(0, wire + "\n"), (0, "")])
    keychain = storage(process)
    assert await keychain.load(PRINCIPAL, CancellationToken(), None) == record()
    await keychain.delete(PRINCIPAL, CancellationToken(), None)
    assert process.calls[0][0] == (
        "find-generic-password",
        "-a",
        ACCOUNT,
        "-s",
        SERVICE,
        "-w",
    )
    assert process.calls[1][0] == (
        "delete-generic-password",
        "-a",
        ACCOUNT,
        "-s",
        SERVICE,
    )


@pytest.mark.asyncio
async def test_keychain_missing_is_none_and_corrupt_is_typed() -> None:
    missing = storage(Process([(44, "")]))
    assert await missing.load(PRINCIPAL, CancellationToken(), None) is None
    corrupt = storage(Process([(0, "private-corrupt")]))
    with pytest.raises(IntegrationAuthError) as captured:
        await corrupt.load(PRINCIPAL, CancellationToken(), None)
    assert captured.value.reason_code == "keychain_corrupt"
    assert "private-corrupt" not in str(captured.value)


@pytest.mark.asyncio
async def test_keychain_rejects_principal_and_platform_before_process() -> None:
    process = Process()
    with pytest.raises(IntegrationPolicyError):
        await storage(process).load("bad@principal", CancellationToken(), None)
    with pytest.raises(IntegrationAuthError) as captured:
        await storage(process, platform="linux").load(
            PRINCIPAL, CancellationToken(), None
        )
    assert captured.value.reason_code == "keychain_unsupported"
    assert process.calls == []


@pytest.mark.asyncio
async def test_keychain_never_retains_secret_or_principal_in_error() -> None:
    process = Process([(1, "secret-access")])
    with pytest.raises(IntegrationAuthError) as captured:
        await storage(process).save(PRINCIPAL, record(), CancellationToken(), None)
    rendered = repr(captured.value) + str(captured.value)
    assert "secret-access" not in rendered
    assert PRINCIPAL not in rendered


@pytest.mark.asyncio
async def test_keychain_record_stdout_exact_bound_and_plus_one() -> None:
    wire = json.dumps(record().to_wire(), separators=(",", ":"), sort_keys=True)
    exact = wire + " " * (16 * 1024 - len(wire))
    assert (
        await storage(Process([(0, exact)])).load(PRINCIPAL, CancellationToken(), None)
        == record()
    )
    with pytest.raises(IntegrationAuthError) as captured:
        await storage(Process([(0, exact + " ")])).load(
            PRINCIPAL, CancellationToken(), None
        )
    assert captured.value.reason_code == "keychain_corrupt"


@pytest.mark.asyncio
async def test_keychain_save_does_not_report_before_late_process_settles() -> None:
    class LateProcess(Process):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            self.mutated = False

        async def run(self, *args: object, **kwargs: object) -> tuple[int, str]:
            cancellation = kwargs["cancellation"]
            assert isinstance(cancellation, CancellationToken)
            self.entered.set()
            await cancellation.wait()
            await self.release.wait()
            self.mutated = True
            raise RuntimeError("private late failure")

    process = LateProcess()
    cancellation = CancellationToken()
    pending = asyncio.create_task(
        storage(process).save(PRINCIPAL, record(), cancellation, None)
    )
    await process.entered.wait()
    cancellation.cancel()
    await asyncio.sleep(0)
    assert not pending.done()
    process.release.set()
    with pytest.raises(IntegrationAuthError):
        await pending
    assert process.mutated


@pytest.mark.asyncio
async def test_keychain_cancellation_owns_spawn_before_child_materializes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()
    spawn_cancelled = asyncio.Event()

    async def blocked_spawn(*_args: object, **_kwargs: object):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            spawn_cancelled.set()
            raise

    monkeypatch.setattr(asyncio, "create_subprocess_exec", blocked_spawn)
    cancellation = CancellationToken()
    pending = asyncio.create_task(
        _AsyncioKeychainProcess().run(
            ("find-generic-password",),
            stdin=None,
            cancellation=cancellation,
            deadline_monotonic=None,
            timeout_seconds=10.0,
            max_stdout_bytes=16 * 1024 + 1,
        )
    )
    await entered.wait()
    cancellation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert spawn_cancelled.is_set()


@pytest.mark.asyncio
async def test_keychain_cancellation_terms_kills_and_reaps_spawned_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Stdin:
        def write(self, _data: bytes) -> None:
            pass

        async def drain(self) -> None:
            pass

        def close(self) -> None:
            pass

        async def wait_closed(self) -> None:
            pass

    class Child:
        def __init__(self) -> None:
            self.stdin = Stdin()
            self.stdout = asyncio.StreamReader()
            self.stderr = asyncio.StreamReader()
            self.returncode: int | None = None
            self.exited = asyncio.Event()
            self.waiting = asyncio.Event()
            self.signals: list[str] = []
            self.wait_calls = 0

        async def wait(self) -> int:
            self.wait_calls += 1
            self.waiting.set()
            await self.exited.wait()
            assert self.returncode is not None
            return self.returncode

        def terminate(self) -> None:
            self.signals.append("TERM")

        def kill(self) -> None:
            self.signals.append("KILL")
            self.returncode = -9
            self.stdout.feed_eof()
            self.stderr.feed_eof()
            self.exited.set()

    child = Child()

    async def spawn(*_args: object, **_kwargs: object) -> Child:
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr("kaji.integrations.keychain._TERM_GRACE_SECONDS", 0)
    cancellation = CancellationToken()
    pending = asyncio.create_task(
        _AsyncioKeychainProcess().run(
            ("delete-generic-password",),
            stdin=None,
            cancellation=cancellation,
            deadline_monotonic=None,
            timeout_seconds=10.0,
            max_stdout_bytes=16 * 1024 + 1,
        )
    )
    await child.waiting.wait()
    cancellation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert child.signals == ["TERM", "KILL"]
    assert child.wait_calls >= 2
    assert child.returncode == -9
