"""Killable macOS Keychain credential storage for Google OAuth."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
import hashlib
import os
import sys
from typing import Protocol, cast

from kaji.integrations.errors import IntegrationAuthError
from kaji.integrations.oauth import (
    OAuthCredentialRecord,
    _canonical_wire,
    _require_principal,
)
from kaji.runtime.agents.cancellation import CancellationToken


_SECURITY = "/usr/bin/security"
_SERVICE = "dev.kaji.oauth.gmail"
_OPERATION_SECONDS = 10.0
_STDOUT_BYTES = 16 * 1024 + 1
_STDERR_BYTES = 8 * 1024
_TERM_GRACE_SECONDS = 0.25


class _KeychainProcess(Protocol):
    async def run(
        self,
        args: tuple[str, ...],
        *,
        stdin: str | None,
        cancellation: CancellationToken,
        deadline_monotonic: float | None,
        timeout_seconds: float,
        max_stdout_bytes: int,
    ) -> tuple[int, str]: ...


class _AsyncioKeychainProcess:
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
        loop = asyncio.get_running_loop()
        operation_deadline = loop.time() + timeout_seconds
        if deadline_monotonic is not None:
            operation_deadline = min(operation_deadline, deadline_monotonic)
        spawn = asyncio.create_task(
            asyncio.create_subprocess_exec(
                _SECURITY,
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        )
        cancelled = asyncio.create_task(cancellation.wait())
        process: asyncio.subprocess.Process | None = None
        owned_tasks: tuple[asyncio.Task[object], ...] = ()
        try:
            remaining = operation_deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError("Keychain operation timed out")
            done, _ = await asyncio.wait(
                {spawn, cancelled},
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancelled in done:
                cancellation.raise_if_cancelled()
            if spawn not in done:
                raise TimeoutError("Keychain operation timed out")
            process = await spawn
            assert process.stdin is not None
            assert process.stdout is not None
            assert process.stderr is not None
            stdin_writer = process.stdin
            stdout_reader = process.stdout
            stderr_reader = process.stderr

            async def write_input() -> None:
                try:
                    if stdin is not None:
                        stdin_writer.write(stdin.encode("utf-8"))
                        await stdin_writer.drain()
                finally:
                    stdin_writer.close()
                    await stdin_writer.wait_closed()

            async def read_bounded(stream: asyncio.StreamReader, maximum: int) -> bytes:
                result = bytearray()
                while True:
                    chunk = await stream.read(min(8_192, maximum + 1 - len(result)))
                    if not chunk:
                        return bytes(result)
                    result.extend(chunk)
                    if len(result) > maximum:
                        raise IntegrationAuthError("keychain_corrupt")

            writer = asyncio.create_task(write_input())
            stdout = asyncio.create_task(read_bounded(stdout_reader, max_stdout_bytes))
            stderr = asyncio.create_task(read_bounded(stderr_reader, _STDERR_BYTES))
            waiter = asyncio.create_task(process.wait())
            owned_tasks = (
                cast(asyncio.Task[object], writer),
                cast(asyncio.Task[object], stdout),
                cast(asyncio.Task[object], stderr),
                cast(asyncio.Task[object], waiter),
            )
            remaining = operation_deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError("Keychain operation timed out")
            done, _ = await asyncio.wait(
                {waiter, cancelled},
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancelled in done:
                cancellation.raise_if_cancelled()
            if waiter not in done:
                raise TimeoutError("Keychain operation timed out")
            await writer
            output, _discarded = await asyncio.gather(stdout, stderr)
            try:
                return await waiter, output.decode("utf-8")
            except UnicodeDecodeError:
                raise IntegrationAuthError("keychain_corrupt") from None
        except asyncio.CancelledError:
            process = await self._settle_spawn(spawn, process)
            if process is not None:
                await self._terminate_and_reap(process, owned_tasks)
            raise
        except IntegrationAuthError:
            process = await self._settle_spawn(spawn, process)
            if process is not None:
                await self._terminate_and_reap(process, owned_tasks)
            raise
        except Exception:
            process = await self._settle_spawn(spawn, process)
            if process is not None:
                await self._terminate_and_reap(process, owned_tasks)
            raise IntegrationAuthError("keychain_locked") from None
        finally:
            cancelled.cancel()
            if not spawn.done():
                spawn.cancel()
            await asyncio.gather(spawn, cancelled, return_exceptions=True)

    async def _settle_spawn(
        self,
        spawn: asyncio.Task[asyncio.subprocess.Process],
        process: asyncio.subprocess.Process | None,
    ) -> asyncio.subprocess.Process | None:
        if process is not None:
            return process
        if not spawn.done():
            spawn.cancel()
        result = (await asyncio.gather(spawn, return_exceptions=True))[0]
        return result if isinstance(result, asyncio.subprocess.Process) else None

    async def _terminate_and_reap(
        self,
        process: asyncio.subprocess.Process,
        tasks: Sequence[asyncio.Task[object]],
    ) -> None:
        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), _TERM_GRACE_SECONDS)
            except TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _account(principal_id: str) -> str:
    principal_id = _require_principal(principal_id)
    return hashlib.sha256(f"{_SERVICE}\0{principal_id}".encode("utf-8")).hexdigest()


class MacOSKeychainTokenStorage:
    """Async OAuth credential store backed by fixed ``/usr/bin/security``."""

    def __init__(self) -> None:
        self._initialize(
            process=_AsyncioKeychainProcess(),
            platform=sys.platform,
            executable=os.access(_SECURITY, os.X_OK),
        )

    def _initialize(
        self, *, process: _KeychainProcess, platform: str, executable: bool
    ) -> None:
        self._process = process
        self._platform = platform
        self._executable = executable

    def _preflight(self, principal_id: str) -> str:
        account = _account(principal_id)
        if self._platform != "darwin" or not self._executable:
            raise IntegrationAuthError("keychain_unsupported")
        return account

    async def load(
        self,
        principal_id: str,
        cancellation: CancellationToken,
        deadline_monotonic: float | None,
    ) -> OAuthCredentialRecord | None:
        account = self._preflight(principal_id)
        code, stdout = await self._run(
            (
                "find-generic-password",
                "-a",
                account,
                "-s",
                _SERVICE,
                "-w",
            ),
            stdin=None,
            cancellation=cancellation,
            deadline_monotonic=deadline_monotonic,
        )
        if code == 44:
            return None
        if code != 0:
            raise IntegrationAuthError("keychain_locked")
        if stdout.endswith("\n"):
            stdout = stdout[:-1]
        try:
            encoded = stdout.encode("utf-8")
            if len(encoded) > 16 * 1024:
                raise ValueError
            import json

            value = json.loads(stdout)
            record, _ = _canonical_wire(value)
            return record
        except Exception:
            raise IntegrationAuthError("keychain_corrupt") from None

    async def save(
        self,
        principal_id: str,
        record: OAuthCredentialRecord,
        cancellation: CancellationToken,
        deadline_monotonic: float | None,
    ) -> None:
        account = self._preflight(principal_id)
        _, encoded = _canonical_wire(record.to_wire())
        code, _stdout = await self._run(
            (
                "add-generic-password",
                "-a",
                account,
                "-s",
                _SERVICE,
                "-U",
                "-w",
            ),
            stdin=encoded.decode("utf-8"),
            cancellation=cancellation,
            deadline_monotonic=deadline_monotonic,
        )
        if code != 0:
            raise IntegrationAuthError("keychain_locked")

    async def delete(
        self,
        principal_id: str,
        cancellation: CancellationToken,
        deadline_monotonic: float | None,
    ) -> None:
        account = self._preflight(principal_id)
        code, _stdout = await self._run(
            (
                "delete-generic-password",
                "-a",
                account,
                "-s",
                _SERVICE,
            ),
            stdin=None,
            cancellation=cancellation,
            deadline_monotonic=deadline_monotonic,
        )
        if code not in {0, 44}:
            raise IntegrationAuthError("keychain_locked")

    async def _run(
        self,
        args: tuple[str, ...],
        *,
        stdin: str | None,
        cancellation: CancellationToken,
        deadline_monotonic: float | None,
    ) -> tuple[int, str]:
        try:
            return await self._process.run(
                args,
                stdin=stdin,
                cancellation=cancellation,
                deadline_monotonic=deadline_monotonic,
                timeout_seconds=_OPERATION_SECONDS,
                max_stdout_bytes=_STDOUT_BYTES,
            )
        except asyncio.CancelledError:
            raise
        except IntegrationAuthError:
            raise
        except Exception:
            raise IntegrationAuthError("keychain_locked") from None


def _create_macos_keychain_storage_for_test(
    *, process: _KeychainProcess, platform: str, executable: bool
) -> MacOSKeychainTokenStorage:
    storage = object.__new__(MacOSKeychainTokenStorage)
    storage._initialize(
        process=process,
        platform=platform,
        executable=executable,
    )
    return storage


__all__ = ["MacOSKeychainTokenStorage"]
