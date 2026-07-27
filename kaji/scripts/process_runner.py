#!/usr/bin/env python3
"""Bounded child-process ownership for foreground Kaji release commands.

Successful commands must not intentionally daemonize descendants. Every failure,
timeout, output overflow, or interrupted parent tears down the original process
group before returning control.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from typing import BinaryIO


@dataclass(frozen=True, slots=True)
class CommandBudget:
    timeout_seconds: float
    max_output_bytes: int = 1_048_576
    terminate_grace_seconds: float = 2.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be positive and finite")
        if (
            isinstance(self.max_output_bytes, bool)
            or not isinstance(self.max_output_bytes, int)
            or self.max_output_bytes <= 0
        ):
            raise ValueError("max_output_bytes must be a positive integer")
        if (
            isinstance(self.terminate_grace_seconds, bool)
            or not isinstance(self.terminate_grace_seconds, (int, float))
            or not math.isfinite(self.terminate_grace_seconds)
            or self.terminate_grace_seconds < 0
        ):
            raise ValueError("terminate_grace_seconds must be finite and non-negative")


METADATA_BUDGET = CommandBudget(timeout_seconds=30, terminate_grace_seconds=1)
LOCAL_COMMAND_BUDGET = CommandBudget(timeout_seconds=600, terminate_grace_seconds=1)
LOCAL_ORCHESTRATOR_BUDGET = CommandBudget(
    timeout_seconds=1_200, terminate_grace_seconds=5
)
PACKAGE_COMMAND_BUDGET = CommandBudget(timeout_seconds=900, terminate_grace_seconds=1)
PACKAGE_ORCHESTRATOR_BUDGET = CommandBudget(
    timeout_seconds=1_800, terminate_grace_seconds=5
)
BENCHMARK_COMMAND_BUDGET = CommandBudget(timeout_seconds=600, terminate_grace_seconds=1)
BENCHMARK_ORCHESTRATOR_BUDGET = CommandBudget(
    timeout_seconds=2_100, terminate_grace_seconds=5
)
PROVIDER_PROOF_BUDGET = CommandBudget(timeout_seconds=300, terminate_grace_seconds=1)
PROVIDER_ORCHESTRATOR_BUDGET = CommandBudget(
    timeout_seconds=900, terminate_grace_seconds=5
)
RELEASE_COMMAND_BUDGET = CommandBudget(timeout_seconds=3_600, terminate_grace_seconds=9)
CLEANUP_SETTLE_SECONDS = 1.0
CLEANUP_TAIL_SECONDS = CLEANUP_SETTLE_SECONDS * 3


@dataclass(frozen=True, slots=True)
class CompletedCommand:
    returncode: int
    stdout: bytes = b""
    stderr: bytes = b""


class CommandError(RuntimeError):
    """A redaction-safe child-process failure."""


class UnsupportedReleaseHostError(CommandError):
    def __init__(self) -> None:
        super().__init__("release process cleanup requires macOS or Linux")


class CommandStartError(CommandError):
    def __init__(self) -> None:
        super().__init__("release command could not be started")


class CommandExitError(CommandError):
    def __init__(self, returncode: int, *, command_index: int | None = None) -> None:
        self.returncode = returncode
        self.command_index = command_index
        super().__init__(f"release command exited with status {returncode}")


class CommandTimeoutError(CommandError):
    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        super().__init__("release command exceeded its time budget")


class CommandOutputLimitError(CommandError):
    def __init__(self, *, stream: str, captured_bytes: int) -> None:
        self.stream = stream
        self.captured_bytes = captured_bytes
        super().__init__(f"release command exceeded its {stream} capture budget")


class CommandCaptureError(CommandError):
    def __init__(self, stream: str) -> None:
        self.stream = stream
        super().__init__(f"release command {stream} capture failed")


class CommandInputError(CommandError):
    def __init__(self) -> None:
        super().__init__("release command input delivery failed")


class CommandCleanupError(CommandError):
    def __init__(self) -> None:
        super().__init__("release command cleanup did not settle")


class CommandInterruptedError(CommandError):
    def __init__(self, signum: int) -> None:
        self.signum = signum
        super().__init__(f"release command interrupted by signal {signum}")


class CommandThreadError(CommandError):
    def __init__(self) -> None:
        super().__init__("release commands must run on the main thread")


@dataclass(frozen=True, slots=True)
class CommandSpec:
    command: Sequence[str]
    cwd: Path
    budget: CommandBudget
    capture: bool = False
    env: Mapping[str, str] | None = None
    check: bool = True
    input_bytes: bytes | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.command, (str, bytes)):
            raise ValueError("command must be a sequence of arguments")
        command = tuple(self.command)
        if not command or any(
            not isinstance(part, str) or not part for part in command
        ):
            raise ValueError("command must contain non-empty strings")
        if any("\0" in part for part in command):
            raise CommandStartError
        if self.input_bytes is not None and not isinstance(self.input_bytes, bytes):
            raise ValueError("input_bytes must be bytes or None")
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "cwd", Path(self.cwd))


class _Capture:
    def __init__(self, stream: str, pipe: BinaryIO, maximum: int) -> None:
        self.stream = stream
        self.pipe = pipe
        self.maximum = maximum
        self.buffer = bytearray()
        self.total = 0
        self.overflowed = threading.Event()
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self._drain, daemon=True)

    def _drain(self) -> None:
        try:
            while chunk := os.read(self.pipe.fileno(), 65_536):
                self.total += len(chunk)
                remaining = self.maximum - len(self.buffer)
                if remaining > 0:
                    self.buffer.extend(chunk[:remaining])
                if self.total > self.maximum:
                    self.overflowed.set()
        except BaseException as error:
            self.error = error
        finally:
            self.pipe.close()


class _InputWriter:
    def __init__(self, pipe: BinaryIO, input_bytes: bytes) -> None:
        self.pipe = pipe
        self._input_bytes: bytes | None = input_bytes
        self.expected_bytes = len(input_bytes)
        self.written_bytes = 0
        self.abort_requested = threading.Event()
        self.failed = threading.Event()
        self.finished = threading.Event()
        self.thread = threading.Thread(
            target=self._write,
            name="kaji-process-input-writer",
            daemon=True,
        )

    def _write(self) -> None:
        input_bytes = self._input_bytes
        assert input_bytes is not None
        view = memoryview(input_bytes)
        try:
            while self.written_bytes < self.expected_bytes:
                if self.abort_requested.is_set():
                    break
                try:
                    written = os.write(
                        self.pipe.fileno(),
                        view[self.written_bytes : self.written_bytes + 65_536],
                    )
                except BlockingIOError:
                    self.abort_requested.wait(0.005)
                    continue
                except InterruptedError:
                    continue
                except BaseException:
                    self.failed.set()
                    break
                if written <= 0:
                    self.failed.set()
                    break
                self.written_bytes += written
            if self.written_bytes != self.expected_bytes:
                self.failed.set()
        finally:
            view.release()
            self._input_bytes = None
            try:
                self.pipe.close()
            except OSError:
                self.failed.set()
            self.finished.set()

    def abort(self) -> None:
        self.abort_requested.set()


@dataclass(slots=True)
class _RunningCommand:
    spec: CommandSpec
    process: subprocess.Popen[bytes]
    deadline: float
    captures: tuple[_Capture, ...]
    input_writer: _InputWriter | None

    def streams_closed(self) -> bool:
        captures_closed = all(
            not capture.thread.is_alive() for capture in self.captures
        )
        input_closed = self.input_writer is None or (
            self.input_writer.finished.is_set()
            and not self.input_writer.thread.is_alive()
        )
        return captures_closed and input_closed

    def completed(self) -> bool:
        return self.process.poll() is not None and self.streams_closed()

    def result(self) -> CompletedCommand:
        stdout = next(
            (bytes(item.buffer) for item in self.captures if item.stream == "stdout"),
            b"",
        )
        stderr = next(
            (bytes(item.buffer) for item in self.captures if item.stream == "stderr"),
            b"",
        )
        return CompletedCommand(
            returncode=int(self.process.returncode or 0),
            stdout=stdout,
            stderr=stderr,
        )


def _supported_release_host() -> bool:
    return os.name == "posix" and sys.platform in {"darwin", "linux"}


def _thread_started(thread: threading.Thread) -> bool:
    return thread.ident is not None


def _close_pipe(pipe: BinaryIO | None) -> bool:
    if pipe is None:
        return True
    try:
        pipe.close()
    except BaseException:
        return False
    return True


def _cleanup_failed_spawn(
    process: subprocess.Popen[bytes],
    *,
    input_writer: _InputWriter | None,
    captures: Sequence[_Capture],
) -> None:
    """Tear down a process whose post-Popen setup did not complete."""
    cleanup_failed = False
    if input_writer is not None:
        input_writer.abort()

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except BaseException:
        cleanup_failed = True
        try:
            process.kill()
        except BaseException:
            pass

    deadline = time.monotonic() + CLEANUP_SETTLE_SECONDS
    try:
        process.wait(timeout=max(0, deadline - time.monotonic()))
    except BaseException:
        cleanup_failed = True

    threads = [
        capture.thread for capture in captures if _thread_started(capture.thread)
    ]
    if input_writer is not None and _thread_started(input_writer.thread):
        threads.append(input_writer.thread)
    for thread in threads:
        try:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        except BaseException:
            cleanup_failed = True

    pipes = [process.stdin, process.stdout, process.stderr]
    for pipe in pipes:
        if not _close_pipe(pipe):
            cleanup_failed = True

    for thread in threads:
        if thread.is_alive():
            try:
                thread.join(timeout=max(0, deadline - time.monotonic()))
            except BaseException:
                cleanup_failed = True
        if thread.is_alive():
            cleanup_failed = True

    while True:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            break
        except BaseException:
            cleanup_failed = True
            break
        if time.monotonic() >= deadline:
            cleanup_failed = True
            break
        time.sleep(0.005)

    if process.poll() is None:
        cleanup_failed = True
    if cleanup_failed:
        raise CommandCleanupError


def _spawn(spec: CommandSpec) -> _RunningCommand:
    if not _supported_release_host():
        raise UnsupportedReleaseHostError
    try:
        process = subprocess.Popen(
            spec.command,
            cwd=spec.cwd,
            env=None if spec.env is None else dict(spec.env),
            stdin=(
                subprocess.PIPE if spec.input_bytes is not None else subprocess.DEVNULL
            ),
            stdout=subprocess.PIPE if spec.capture else None,
            stderr=subprocess.PIPE if spec.capture else None,
            start_new_session=True,
        )
    except (OSError, ValueError):
        raise CommandStartError from None

    captures: list[_Capture] = []
    input_writer: _InputWriter | None = None
    try:
        if spec.input_bytes is not None:
            assert process.stdin is not None
            os.set_blocking(process.stdin.fileno(), False)
            input_writer = _InputWriter(process.stdin, spec.input_bytes)
            input_writer.thread.start()
        if spec.capture:
            assert process.stdout is not None and process.stderr is not None
            captures = [
                _Capture("stdout", process.stdout, spec.budget.max_output_bytes),
                _Capture("stderr", process.stderr, spec.budget.max_output_bytes),
            ]
            for capture in captures:
                capture.thread.start()
        return _RunningCommand(
            spec=spec,
            process=process,
            deadline=time.monotonic() + spec.budget.timeout_seconds,
            captures=tuple(captures),
            input_writer=input_writer,
        )
    except BaseException:
        try:
            _cleanup_failed_spawn(
                process,
                input_writer=input_writer,
                captures=captures,
            )
        except BaseException:
            raise CommandCleanupError from None
        raise CommandStartError from None


def _signal_group(running: _RunningCommand, signum: signal.Signals) -> None:
    permission_deadline = time.monotonic() + 0.05
    while True:
        try:
            os.killpg(running.process.pid, signum)
            return
        except ProcessLookupError:
            return
        except PermissionError:
            running.process.poll()
            if time.monotonic() >= permission_deadline:
                raise CommandCleanupError from None
            time.sleep(0.001)


def _group_exists(running: _RunningCommand) -> bool:
    permission_deadline = time.monotonic() + 0.05
    while True:
        try:
            os.killpg(running.process.pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            running.process.poll()
            if time.monotonic() >= permission_deadline:
                raise CommandCleanupError from None
            time.sleep(0.001)


def _cleanup(running: Sequence[_RunningCommand]) -> None:
    if not running:
        return
    cleanup_failed = False
    for item in running:
        if item.input_writer is not None:
            item.input_writer.abort()
    try:
        for item in running:
            item.process.poll()
            if _group_exists(item):
                _signal_group(item, signal.SIGTERM)
        grace_deadlines = {
            item.process.pid: time.monotonic()
            + item.spec.budget.terminate_grace_seconds
            for item in running
        }
        pending = {item.process.pid: item for item in running if _group_exists(item)}
        while pending:
            now = time.monotonic()
            for pid, item in tuple(pending.items()):
                item.process.poll()
                if not _group_exists(item):
                    pending.pop(pid)
                elif now >= grace_deadlines[pid]:
                    _signal_group(item, signal.SIGKILL)
                    pending.pop(pid)
            if not pending:
                break
            time.sleep(0.005)
    except CommandCleanupError:
        cleanup_failed = True
        for item in running:
            try:
                item.process.kill()
            except OSError:
                pass
    wait_deadline = time.monotonic() + CLEANUP_SETTLE_SECONDS
    for item in running:
        try:
            item.process.wait(timeout=max(0, wait_deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            cleanup_failed = True
    group_deadline = time.monotonic() + CLEANUP_SETTLE_SECONDS
    try:
        while any(_group_exists(item) for item in running):
            if time.monotonic() >= group_deadline:
                cleanup_failed = True
                break
            time.sleep(0.005)
    except CommandCleanupError:
        cleanup_failed = True
    pipe_deadline = time.monotonic() + CLEANUP_SETTLE_SECONDS
    captures = [capture for item in running for capture in item.captures]
    for capture in captures:
        capture.thread.join(timeout=max(0, pipe_deadline - time.monotonic()))
    for capture in captures:
        if capture.thread.is_alive():
            capture.pipe.close()
    for capture in captures:
        capture.thread.join(timeout=max(0, pipe_deadline - time.monotonic()))
        if capture.thread.is_alive():
            cleanup_failed = True
    input_deadline = time.monotonic() + CLEANUP_SETTLE_SECONDS
    input_writers = [
        item.input_writer for item in running if item.input_writer is not None
    ]
    for writer in input_writers:
        writer.thread.join(timeout=max(0, input_deadline - time.monotonic()))
        if writer.thread.is_alive() or not writer.finished.is_set():
            cleanup_failed = True
    if cleanup_failed:
        raise CommandCleanupError


def _validate_io_state(item: _RunningCommand, *, terminal: bool = False) -> None:
    capture_error = next(
        (capture for capture in item.captures if capture.error is not None),
        None,
    )
    if capture_error is not None:
        raise CommandCaptureError(capture_error.stream) from capture_error.error
    overflow = next(
        (capture for capture in item.captures if capture.overflowed.is_set()),
        None,
    )
    if overflow is not None:
        raise CommandOutputLimitError(
            stream=overflow.stream,
            captured_bytes=len(overflow.buffer),
        )

    writer = item.input_writer
    if writer is not None and writer.failed.is_set():
        raise CommandInputError
    if not terminal:
        return
    if any(capture.thread.is_alive() for capture in item.captures):
        raise CommandCleanupError
    if writer is not None:
        if not writer.finished.is_set() or writer.thread.is_alive():
            raise CommandCleanupError
        if writer.written_bytes != writer.expected_bytes:
            raise CommandInputError


@dataclass(slots=True)
class _SignalState:
    launching: bool = False
    cleaning: bool = False
    pending: int | None = None


def _install_signal_handlers() -> tuple[dict[signal.Signals, object], _SignalState]:
    state = _SignalState()
    if threading.current_thread() is not threading.main_thread():
        raise CommandThreadError
    previous: dict[signal.Signals, object] = {}

    def interrupt(signum: int, _frame: object) -> None:
        if state.launching or state.cleaning:
            if state.pending is None:
                state.pending = signum
            return
        raise CommandInterruptedError(signum)

    for signum in (signal.SIGTERM, signal.SIGINT):
        previous[signum] = signal.signal(signum, interrupt)
    return previous, state


def _restore_signal_handlers(previous: Mapping[signal.Signals, object]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _run_specs(specs: Sequence[CommandSpec]) -> tuple[CompletedCommand, ...]:
    if not specs:
        raise ValueError("at least one command is required")
    running: list[_RunningCommand] = []
    owned: list[_RunningCommand] = []
    previous_handlers, signal_state = _install_signal_handlers()
    try:
        for spec in specs:
            signal_state.launching = True
            try:
                spawned = _spawn(spec)
                running.append(spawned)
                owned.append(spawned)
            finally:
                signal_state.launching = False
            if signal_state.pending is not None:
                raise CommandInterruptedError(signal_state.pending)
        pending = set(range(len(running)))
        results: list[CompletedCommand | None] = [None] * len(running)
        while pending:
            now = time.monotonic()
            for index in tuple(pending):
                item = running[index]
                _validate_io_state(item)
                if now >= item.deadline:
                    raise CommandTimeoutError(item.spec.budget.timeout_seconds)
                returncode = item.process.poll()
                if returncode is None:
                    continue
                if _group_exists(item):
                    signal_state.cleaning = True
                    try:
                        _cleanup((item,))
                    finally:
                        signal_state.cleaning = False
                    if signal_state.pending is not None:
                        raise CommandInterruptedError(signal_state.pending)
                if not item.streams_closed():
                    continue
                _validate_io_state(item, terminal=True)
                result = item.result()
                if item.spec.check and result.returncode != 0:
                    raise CommandExitError(
                        result.returncode,
                        command_index=index,
                    )
                results[index] = result
                pending.remove(index)
                owned.remove(item)
            if pending:
                time.sleep(0.005)
        return tuple(result for result in results if result is not None)
    except BaseException:
        signal_state.cleaning = True
        _cleanup(owned)
        raise
    finally:
        _restore_signal_handlers(previous_handlers)


def run_checked(
    command: Sequence[str],
    *,
    cwd: Path,
    budget: CommandBudget,
    capture: bool = False,
    env: Mapping[str, str] | None = None,
    check: bool = True,
    input_bytes: bytes | None = None,
) -> CompletedCommand:
    """Run one bounded command without retaining or echoing its arguments."""

    return _run_specs(
        (
            CommandSpec(
                command=command,
                cwd=cwd,
                budget=budget,
                capture=capture,
                env=env,
                check=check,
                input_bytes=input_bytes,
            ),
        )
    )[0]


def run_parallel_checked(
    commands: Sequence[CommandSpec],
) -> tuple[CompletedCommand, ...]:
    """Run sibling release commands and clean up every group on first failure."""

    return _run_specs(tuple(commands))
