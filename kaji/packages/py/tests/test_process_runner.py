from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from types import ModuleType, SimpleNamespace
from typing import Any, Iterable, cast

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
RUNNER = REPO_ROOT / "kaji" / "scripts" / "process_runner.py"


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("test_process_runner_module", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _wait_until_gone(pid: int) -> None:
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.01)
    pytest.fail(f"process {pid} survived process-group cleanup")


def _assert_group_gone(pid: int) -> None:
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return
    pytest.fail(f"process group {pid} survived process-group cleanup")


def test_run_checked_returns_bounded_bytes_and_check_false_status(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    budget = runner.CommandBudget(timeout_seconds=1, max_output_bytes=32)

    completed = runner.run_checked(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('ok'); sys.stderr.write('err'); raise SystemExit(7)",
        ],
        cwd=tmp_path,
        budget=budget,
        capture=True,
        check=False,
    )

    assert completed.returncode == 7
    assert completed.stdout == b"ok"
    assert completed.stderr == b"err"


def test_run_checked_delivers_exact_stdin_bytes(tmp_path: Path) -> None:
    runner = _load_runner()
    destination = tmp_path / "stdin.bin"
    input_bytes = b"\x00exact\nstdin\xffbytes"

    runner.run_checked(
        [
            sys.executable,
            "-c",
            (
                "import pathlib,sys;"
                f"pathlib.Path({str(destination)!r}).write_bytes("
                "sys.stdin.buffer.read())"
            ),
        ],
        cwd=tmp_path,
        budget=runner.CommandBudget(timeout_seconds=1),
        input_bytes=input_bytes,
    )

    assert destination.read_bytes() == input_bytes


def test_none_uses_devnull_but_empty_input_uses_a_pipe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    real_popen = runner.subprocess.Popen
    observed_stdin: list[int] = []

    def popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        stdin = kwargs["stdin"]
        assert isinstance(stdin, int)
        observed_stdin.append(stdin)
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    command = [sys.executable, "-c", "import sys; assert not sys.stdin.buffer.read()"]
    budget = runner.CommandBudget(timeout_seconds=1)

    runner.run_checked(command, cwd=tmp_path, budget=budget)
    runner.run_checked(command, cwd=tmp_path, budget=budget, input_bytes=b"")

    assert observed_stdin == [subprocess.DEVNULL, subprocess.PIPE]


def test_parallel_specs_deliver_independent_exact_stdin_bytes(tmp_path: Path) -> None:
    runner = _load_runner()
    budget = runner.CommandBudget(timeout_seconds=1)
    destinations = [tmp_path / "first.bin", tmp_path / "second.bin"]
    inputs = [b"first\x00payload", b"second\npayload"]
    specs = [
        runner.CommandSpec(
            [
                sys.executable,
                "-c",
                (
                    "import pathlib,sys;"
                    f"pathlib.Path({str(destination)!r}).write_bytes("
                    "sys.stdin.buffer.read())"
                ),
            ],
            cwd=tmp_path,
            budget=budget,
            input_bytes=input_bytes,
        )
        for destination, input_bytes in zip(destinations, inputs, strict=True)
    ]

    completed = runner.run_parallel_checked(specs)

    assert [item.returncode for item in completed] == [0, 0]
    assert [path.read_bytes() for path in destinations] == inputs


def test_child_closing_stdin_fails_closed_without_exposing_input(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    secret = b"opaque-secret-that-must-not-appear" + (b"x" * 1_048_576)

    with pytest.raises(runner.CommandInputError) as captured:
        runner.run_checked(
            [
                sys.executable,
                "-c",
                "import os,time; os.close(0); time.sleep(.2)",
            ],
            cwd=tmp_path,
            budget=runner.CommandBudget(
                timeout_seconds=1,
                terminate_grace_seconds=0.05,
            ),
            input_bytes=secret,
        )

    rendered = f"{captured.value!s} {captured.value!r}"
    assert b"opaque-secret-that-must-not-appear".decode() not in rendered
    assert not hasattr(captured.value, "input_bytes")
    assert not hasattr(captured.value, "command")


def test_zero_length_write_is_a_redaction_safe_input_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    monkeypatch.setattr(runner.os, "write", lambda *_args: 0)

    with pytest.raises(runner.CommandInputError) as captured:
        runner.run_checked(
            [sys.executable, "-c", "import time; time.sleep(.2)"],
            cwd=tmp_path,
            budget=runner.CommandBudget(
                timeout_seconds=1,
                terminate_grace_seconds=0.05,
            ),
            input_bytes=b"short-write-secret",
        )

    assert "short-write-secret" not in str(captured.value)


@pytest.mark.parametrize("check", [True, False])
def test_immediate_zero_exit_never_accepts_partial_megabyte_input(
    tmp_path: Path,
    check: bool,
) -> None:
    runner = _load_runner()
    input_bytes = b"x" * 1_048_576

    for _ in range(20):
        with pytest.raises(runner.CommandInputError):
            runner.run_checked(
                [sys.executable, "-c", "raise SystemExit(0)"],
                cwd=tmp_path,
                budget=runner.CommandBudget(timeout_seconds=1),
                check=check,
                input_bytes=input_bytes,
            )


@pytest.mark.parametrize(
    ("failure", "expected_error"),
    [
        ("capture-error", "CommandCaptureError"),
        ("capture-overflow", "CommandOutputLimitError"),
        ("writer-failed", "CommandInputError"),
        ("writer-incomplete", "CommandInputError"),
    ],
)
@pytest.mark.parametrize("check", [True, False])
def test_terminal_state_is_revalidated_after_residual_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    expected_error: str,
    check: bool,
) -> None:
    runner = _load_runner()
    real_cleanup = runner._cleanup

    def cleanup_with_late_failure(items: object) -> None:
        real_cleanup(items)
        item = tuple(cast(Iterable[Any], items))[0]
        if failure == "capture-error":
            item.captures[0].error = RuntimeError("late capture failure")
        elif failure == "capture-overflow":
            item.captures[0].overflowed.set()
        else:
            writer = item.input_writer
            assert writer is not None
            if failure == "writer-failed":
                writer.failed.set()
            else:
                writer.written_bytes -= 1

    monkeypatch.setattr(runner, "_cleanup", cleanup_with_late_failure)
    descendant = (
        "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)"
    )
    leader = (
        "import subprocess,sys;"
        "sys.stdin.buffer.read();"
        "subprocess.Popen([sys.executable,'-c',"
        f"{descendant!r}],stdin=subprocess.DEVNULL,"
        "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
        "print('ready')"
    )

    with pytest.raises(getattr(runner, expected_error)):
        runner.run_checked(
            [sys.executable, "-c", leader],
            cwd=tmp_path,
            budget=runner.CommandBudget(
                timeout_seconds=2,
                terminate_grace_seconds=0.05,
            ),
            capture=True,
            check=check,
            input_bytes=b"x" * 65_536,
        )


def test_terminal_state_requires_finished_input_writer() -> None:
    runner = _load_runner()
    writer = SimpleNamespace(
        failed=runner.threading.Event(),
        finished=runner.threading.Event(),
        thread=SimpleNamespace(is_alive=lambda: False),
        written_bytes=0,
        expected_bytes=0,
    )
    item = SimpleNamespace(captures=(), input_writer=writer)

    with pytest.raises(runner.CommandCleanupError):
        runner._validate_io_state(item, terminal=True)


def test_timeout_aborts_blocked_input_writer_and_reaps_child(tmp_path: Path) -> None:
    runner = _load_runner()
    child_pid = tmp_path / "blocked-input.pid"
    program = (
        "import pathlib,signal,time,os;"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
        f"pathlib.Path({str(child_pid)!r}).write_text(str(os.getpid()));"
        "time.sleep(60)"
    )

    with pytest.raises(runner.CommandTimeoutError):
        runner.run_checked(
            [sys.executable, "-c", program],
            cwd=tmp_path,
            budget=runner.CommandBudget(
                timeout_seconds=0.2,
                terminate_grace_seconds=0.05,
            ),
            input_bytes=b"x" * 4_194_304,
        )

    assert child_pid.is_file()
    _wait_until_gone(int(child_pid.read_text()))
    assert not any(
        thread.name == "kaji-process-input-writer" and thread.is_alive()
        for thread in runner.threading.enumerate()
    )


def test_run_checked_classifies_nonzero_without_retaining_argv(tmp_path: Path) -> None:
    runner = _load_runner()
    secret = "sk-release-secret"

    with pytest.raises(runner.CommandExitError) as captured:
        runner.run_checked(
            [sys.executable, "-c", "raise SystemExit(9)", secret],
            cwd=tmp_path,
            budget=runner.CommandBudget(timeout_seconds=1),
        )

    assert captured.value.returncode == 9
    assert secret not in str(captured.value)
    assert secret not in repr(captured.value)
    assert not hasattr(captured.value, "command")


@pytest.mark.parametrize("stream", [1, 2])
def test_run_checked_caps_each_output_stream(tmp_path: Path, stream: int) -> None:
    runner = _load_runner()
    with pytest.raises(runner.CommandOutputLimitError) as captured:
        runner.run_checked(
            [sys.executable, "-c", f"import os; os.write({stream}, b'x' * 8192)"],
            cwd=tmp_path,
            budget=runner.CommandBudget(
                timeout_seconds=1,
                max_output_bytes=64,
                terminate_grace_seconds=0.05,
            ),
            capture=True,
        )

    assert captured.value.stream == ("stdout" if stream == 1 else "stderr")
    assert captured.value.captured_bytes <= 64


def test_output_cap_beats_timeout_when_child_writes_cap_plus_one_then_hangs(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    with pytest.raises(runner.CommandOutputLimitError):
        runner.run_checked(
            [
                sys.executable,
                "-c",
                "import os,time; os.write(1, b'x' * 65); time.sleep(60)",
            ],
            cwd=tmp_path,
            budget=runner.CommandBudget(
                timeout_seconds=0.5,
                max_output_bytes=64,
                terminate_grace_seconds=0.05,
            ),
            capture=True,
            input_bytes=b"x" * 1_048_576,
        )

    assert not any(
        thread.name == "kaji-process-input-writer" and thread.is_alive()
        for thread in runner.threading.enumerate()
    )


def test_exact_output_cap_is_returned_without_truncation(tmp_path: Path) -> None:
    runner = _load_runner()
    completed = runner.run_checked(
        [sys.executable, "-c", "import os; os.write(1, b'x' * 64)"],
        cwd=tmp_path,
        budget=runner.CommandBudget(timeout_seconds=1, max_output_bytes=64),
        capture=True,
    )
    assert completed.stdout == b"x" * 64


def test_timeout_kills_ignored_term_descendant_and_waits_for_pipe_eof(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    child_pid = tmp_path / "child.pid"
    program = (
        "import pathlib,signal,subprocess,sys,time;"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
        "child=subprocess.Popen([sys.executable,'-c',"
        "'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)']);"
        f"pathlib.Path({str(child_pid)!r}).write_text(str(child.pid));"
        "print('ready', flush=True);"
        "time.sleep(60)"
    )

    with pytest.raises(runner.CommandTimeoutError):
        runner.run_checked(
            [sys.executable, "-c", program],
            cwd=tmp_path,
            budget=runner.CommandBudget(
                timeout_seconds=0.2,
                terminate_grace_seconds=0.05,
            ),
            capture=True,
        )

    assert child_pid.is_file()
    _wait_until_gone(int(child_pid.read_text()))


def test_parallel_failure_terminates_and_reaps_sibling(tmp_path: Path) -> None:
    runner = _load_runner()
    sibling_pid = tmp_path / "sibling.pid"
    budget = runner.CommandBudget(timeout_seconds=1, terminate_grace_seconds=0.05)
    failing = runner.CommandSpec(
        [sys.executable, "-c", "import time; time.sleep(.1); raise SystemExit(4)"],
        cwd=tmp_path,
        budget=budget,
    )
    hanging = runner.CommandSpec(
        [
            sys.executable,
            "-c",
            f"import pathlib,time,os; pathlib.Path({str(sibling_pid)!r}).write_text(str(os.getpid())); time.sleep(60)",
        ],
        cwd=tmp_path,
        budget=budget,
    )

    with pytest.raises(runner.CommandExitError) as captured:
        runner.run_parallel_checked((failing, hanging))

    assert captured.value.command_index == 0
    assert sibling_pid.is_file()
    _wait_until_gone(int(sibling_pid.read_text()))


@pytest.mark.parametrize("status", [0, 7])
def test_leader_exit_cleans_stdio_detached_descendant(
    tmp_path: Path, status: int
) -> None:
    runner = _load_runner()
    child_pid = tmp_path / f"detached-{status}.pid"
    program = (
        "import pathlib,subprocess,sys;"
        "child=subprocess.Popen([sys.executable,'-c',"
        "'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
        f"pathlib.Path({str(child_pid)!r}).write_text(str(child.pid));"
        f"raise SystemExit({status})"
    )

    completed = runner.run_checked(
        [sys.executable, "-c", program],
        cwd=tmp_path,
        budget=runner.CommandBudget(timeout_seconds=1, terminate_grace_seconds=0.05),
        check=False,
    )

    assert completed.returncode == status
    _wait_until_gone(int(child_pid.read_text()))


def test_nonzero_leader_with_pipe_holding_descendant_preserves_exit_status(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    program = (
        "import subprocess,sys;"
        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']);"
        "raise SystemExit(11)"
    )

    with pytest.raises(runner.CommandExitError) as captured:
        runner.run_checked(
            [sys.executable, "-c", program],
            cwd=tmp_path,
            budget=runner.CommandBudget(
                timeout_seconds=1, terminate_grace_seconds=0.05
            ),
            capture=True,
        )

    assert captured.value.returncode == 11


def test_nested_runner_gets_time_to_clean_its_leaf(tmp_path: Path) -> None:
    runner = _load_runner()
    leaf_pid = tmp_path / "nested-leaf.pid"
    scripts = REPO_ROOT / "kaji" / "scripts"
    leaf = (
        "import pathlib,signal,time,os; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"pathlib.Path({str(leaf_pid)!r}).write_text(str(os.getpid())); "
        "time.sleep(60)"
    )
    inner = (
        "import pathlib,sys;"
        f"sys.path.insert(0,{str(scripts)!r});"
        "from process_runner import CommandBudget,run_checked;"
        f"leaf={leaf!r};"
        "run_checked([sys.executable,'-c',leaf],cwd=pathlib.Path.cwd(),"
        "budget=CommandBudget(timeout_seconds=60,terminate_grace_seconds=.05))"
    )

    with pytest.raises(runner.CommandTimeoutError):
        runner.run_checked(
            [sys.executable, "-c", inner],
            cwd=tmp_path,
            budget=runner.CommandBudget(
                timeout_seconds=0.25, terminate_grace_seconds=0.5
            ),
            capture=True,
        )

    assert leaf_pid.is_file()
    _wait_until_gone(int(leaf_pid.read_text()))


def test_budget_and_host_validation_happen_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner()
    for kwargs in (
        {"timeout_seconds": 0},
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": True},
        {"timeout_seconds": "1"},
        {"timeout_seconds": 1, "max_output_bytes": 0},
        {"timeout_seconds": 1, "max_output_bytes": True},
        {"timeout_seconds": 1, "terminate_grace_seconds": -1},
    ):
        with pytest.raises(ValueError):
            runner.CommandBudget(**kwargs)

    monkeypatch.setattr(runner, "_supported_release_host", lambda: False)
    with pytest.raises(runner.UnsupportedReleaseHostError):
        runner.run_checked(
            [sys.executable, "-c", "raise SystemExit(0)"],
            cwd=tmp_path,
            budget=runner.CommandBudget(timeout_seconds=1),
        )

    with pytest.raises(ValueError):
        runner.CommandSpec(
            "python",
            cwd=tmp_path,
            budget=runner.CommandBudget(timeout_seconds=1),
        )

    with pytest.raises(ValueError, match="input_bytes"):
        runner.CommandSpec(
            [sys.executable, "-c", "raise SystemExit(0)"],
            cwd=tmp_path,
            budget=runner.CommandBudget(timeout_seconds=1),
            input_bytes=bytearray(b"not-exact-bytes"),
        )

    secret_bytes = b"secret-input"
    spec = runner.CommandSpec(
        [sys.executable, "-c", "raise SystemExit(0)"],
        cwd=tmp_path,
        budget=runner.CommandBudget(timeout_seconds=1),
        input_bytes=secret_bytes,
    )
    assert secret_bytes.decode() not in repr(spec)

    secret = "sk-secret\0argument"
    with pytest.raises(runner.CommandStartError) as captured:
        runner.run_checked(
            [sys.executable, secret],
            cwd=tmp_path,
            budget=runner.CommandBudget(timeout_seconds=1),
        )
    assert "sk-secret" not in str(captured.value)


@pytest.mark.parametrize(
    "failure",
    [
        "set-blocking",
        "input-construction",
        "input-start",
        "capture-construction",
        "first-capture-start",
        "second-capture-start",
    ],
)
def test_post_popen_setup_failure_closes_pipes_and_reaps_process_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    runner = _load_runner()
    real_popen = runner.subprocess.Popen
    real_input_writer = runner._InputWriter
    real_capture = runner._Capture
    real_thread_start = runner.threading.Thread.start
    spawned: list[subprocess.Popen[bytes]] = []
    writers: list[Any] = []
    captures: list[Any] = []
    capture_starts = 0

    def popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        process = real_popen(*args, **kwargs)
        spawned.append(process)
        return process

    class ObservedInputWriter(real_input_writer):
        def __init__(self, *args: object, **kwargs: object) -> None:
            if failure == "input-construction":
                raise RuntimeError("sensitive input setup detail")
            super().__init__(*args, **kwargs)
            writers.append(self)

    class ObservedCapture(real_capture):
        def __init__(self, *args: object, **kwargs: object) -> None:
            if failure == "capture-construction":
                raise RuntimeError("sensitive capture setup detail")
            super().__init__(*args, **kwargs)
            captures.append(self)

    def start(thread: threading.Thread) -> None:
        nonlocal capture_starts
        if failure == "input-start" and thread.name == "kaji-process-input-writer":
            raise RuntimeError("sensitive input start detail")
        if thread.name != "kaji-process-input-writer":
            capture_starts += 1
            expected = 1 if failure == "first-capture-start" else 2
            if failure.endswith("capture-start") and capture_starts == expected:
                raise RuntimeError("sensitive capture start detail")
        real_thread_start(thread)

    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    monkeypatch.setattr(runner, "_InputWriter", ObservedInputWriter)
    monkeypatch.setattr(runner, "_Capture", ObservedCapture)
    monkeypatch.setattr(runner.threading.Thread, "start", start)
    if failure == "set-blocking":
        monkeypatch.setattr(
            runner.os,
            "set_blocking",
            lambda *_args: (_ for _ in ()).throw(
                OSError("sensitive set-blocking detail")
            ),
        )

    with pytest.raises(runner.CommandStartError) as captured_error:
        runner.run_checked(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=tmp_path,
            budget=runner.CommandBudget(timeout_seconds=2),
            capture=failure.startswith("capture") or "capture-start" in failure,
            input_bytes=b"x" * 1_048_576,
        )

    assert str(captured_error.value) == "release command could not be started"
    assert captured_error.value.__cause__ is None
    assert len(spawned) == 1
    process = spawned[0]
    assert process.poll() is not None
    _wait_until_gone(process.pid)
    _assert_group_gone(process.pid)
    assert all(
        pipe is None or pipe.closed
        for pipe in (process.stdin, process.stdout, process.stderr)
    )
    assert all(not item.thread.is_alive() for item in [*writers, *captures])


def test_setup_failure_terminates_descendant_in_new_process_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    real_popen = runner.subprocess.Popen
    descendant_pid = tmp_path / "setup-descendant.pid"
    descendant = (
        "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)"
    )
    leader = (
        "import os,pathlib,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c',"
        f"{descendant!r}]);"
        f"pathlib.Path({str(descendant_pid)!r}).write_text(str(child.pid));"
        "time.sleep(60)"
    )

    def popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        process = real_popen(*args, **kwargs)
        _wait_for_file(descendant_pid)
        return process

    def fail_set_blocking(*_args: object) -> None:
        raise OSError("sensitive setup detail")

    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    monkeypatch.setattr(runner.os, "set_blocking", fail_set_blocking)

    with pytest.raises(runner.CommandStartError):
        runner.run_checked(
            [sys.executable, "-c", leader],
            cwd=tmp_path,
            budget=runner.CommandBudget(timeout_seconds=2),
            input_bytes=b"sensitive-input-bytes",
        )

    _wait_until_gone(int(descendant_pid.read_text()))


def test_unexpected_setup_teardown_failure_is_generic_after_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    real_popen = runner.subprocess.Popen
    real_cleanup = runner._cleanup_failed_spawn
    spawned: list[subprocess.Popen[bytes]] = []

    def popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        process = real_popen(*args, **kwargs)
        spawned.append(process)
        return process

    def cleanup_then_fail(*args: object, **kwargs: object) -> None:
        real_cleanup(*args, **kwargs)
        raise RuntimeError("sensitive cleanup detail")

    def fail_set_blocking(*_args: object) -> None:
        raise OSError("sensitive setup detail")

    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    monkeypatch.setattr(runner.os, "set_blocking", fail_set_blocking)
    monkeypatch.setattr(runner, "_cleanup_failed_spawn", cleanup_then_fail)

    with pytest.raises(runner.CommandCleanupError) as captured:
        runner.run_checked(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=tmp_path,
            budget=runner.CommandBudget(timeout_seconds=2),
            input_bytes=b"sensitive-input-bytes",
        )

    assert str(captured.value) == "release command cleanup did not settle"
    assert captured.value.__cause__ is None
    assert len(spawned) == 1
    process = spawned[0]
    _wait_until_gone(process.pid)
    _assert_group_gone(process.pid)
    assert process.stdin is not None and process.stdin.closed


def test_named_nested_budgets_have_strict_cleanup_margins() -> None:
    runner = _load_runner()
    leaf_graces = {
        runner.LOCAL_COMMAND_BUDGET.terminate_grace_seconds,
        runner.PACKAGE_COMMAND_BUDGET.terminate_grace_seconds,
        runner.PROVIDER_PROOF_BUDGET.terminate_grace_seconds,
        runner.BENCHMARK_COMMAND_BUDGET.terminate_grace_seconds,
    }
    assert runner.LOCAL_ORCHESTRATOR_BUDGET.terminate_grace_seconds > max(leaf_graces)
    assert runner.PACKAGE_ORCHESTRATOR_BUDGET.terminate_grace_seconds > 2
    assert runner.PROVIDER_ORCHESTRATOR_BUDGET.terminate_grace_seconds > max(
        leaf_graces
    )
    assert runner.BENCHMARK_ORCHESTRATOR_BUDGET.terminate_grace_seconds > max(
        leaf_graces
    )
    assert runner.RELEASE_COMMAND_BUDGET.terminate_grace_seconds > max(
        runner.LOCAL_ORCHESTRATOR_BUDGET.terminate_grace_seconds,
        runner.PACKAGE_ORCHESTRATOR_BUDGET.terminate_grace_seconds,
        runner.PROVIDER_ORCHESTRATOR_BUDGET.terminate_grace_seconds,
        runner.BENCHMARK_ORCHESTRATOR_BUDGET.terminate_grace_seconds,
    )
    for orchestrator in (
        runner.LOCAL_ORCHESTRATOR_BUDGET,
        runner.PACKAGE_ORCHESTRATOR_BUDGET,
        runner.PROVIDER_ORCHESTRATOR_BUDGET,
        runner.BENCHMARK_ORCHESTRATOR_BUDGET,
    ):
        assert orchestrator.terminate_grace_seconds > (
            max(leaf_graces) + runner.CLEANUP_TAIL_SECONDS
        )
    assert runner.RELEASE_COMMAND_BUDGET.terminate_grace_seconds > (
        max(
            runner.LOCAL_ORCHESTRATOR_BUDGET.terminate_grace_seconds,
            runner.PACKAGE_ORCHESTRATOR_BUDGET.terminate_grace_seconds,
            runner.PROVIDER_ORCHESTRATOR_BUDGET.terminate_grace_seconds,
            runner.BENCHMARK_ORCHESTRATOR_BUDGET.terminate_grace_seconds,
        )
        + runner.CLEANUP_TAIL_SECONDS
    )
    assert (
        runner.LOCAL_ORCHESTRATOR_BUDGET.timeout_seconds
        > runner.LOCAL_COMMAND_BUDGET.timeout_seconds
    )
    assert (
        runner.PACKAGE_ORCHESTRATOR_BUDGET.timeout_seconds
        > runner.PACKAGE_COMMAND_BUDGET.timeout_seconds
    )
    assert (
        runner.PROVIDER_ORCHESTRATOR_BUDGET.timeout_seconds
        > runner.PROVIDER_PROOF_BUDGET.timeout_seconds
    )
    assert (
        runner.BENCHMARK_ORCHESTRATOR_BUDGET.timeout_seconds
        > runner.BENCHMARK_COMMAND_BUDGET.timeout_seconds
    )
    assert runner.RELEASE_COMMAND_BUDGET.timeout_seconds > max(
        runner.LOCAL_ORCHESTRATOR_BUDGET.timeout_seconds,
        runner.PACKAGE_ORCHESTRATOR_BUDGET.timeout_seconds,
        runner.PROVIDER_ORCHESTRATOR_BUDGET.timeout_seconds,
        runner.BENCHMARK_ORCHESTRATOR_BUDGET.timeout_seconds,
    )


def _wait_for_file(path: Path) -> None:
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if path.is_file():
            return
        time.sleep(0.005)
    pytest.fail(f"timed out waiting for {path}")


def test_signal_during_residual_cleanup_is_reported_after_child_reap(
    tmp_path: Path,
) -> None:
    scripts = REPO_ROOT / "kaji" / "scripts"
    descendant_pid = tmp_path / "signal-descendant.pid"
    program = tmp_path / "signal_runner.py"
    descendant = (
        "import os,pathlib,signal,time; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        f"pathlib.Path({str(descendant_pid)!r}).write_text(str(os.getpid())); "
        "time.sleep(60)"
    )
    leader = (
        "import pathlib,subprocess,sys,time\n"
        f"subprocess.Popen([sys.executable, '-c', {descendant!r}], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
        "stderr=subprocess.DEVNULL)\n"
        f"ready = pathlib.Path({str(descendant_pid)!r})\n"
        "deadline = time.monotonic() + 1\n"
        "while not ready.exists() and time.monotonic() < deadline:\n"
        "    time.sleep(.005)\n"
    )
    program.write_text(
        "import pathlib,sys\n"
        f"sys.path.insert(0, {str(scripts)!r})\n"
        "from process_runner import CommandBudget,CommandInterruptedError,run_checked\n"
        "try:\n"
        f"    run_checked([sys.executable, '-c', {leader!r}], cwd=pathlib.Path.cwd(), "
        "budget=CommandBudget(timeout_seconds=2, terminate_grace_seconds=.3))\n"
        "except CommandInterruptedError as error:\n"
        "    raise SystemExit(128 + error.signum)\n"
    )
    parent = subprocess.Popen([sys.executable, str(program)], cwd=tmp_path)
    _wait_for_file(descendant_pid)
    time.sleep(0.02)
    parent.send_signal(signal.SIGTERM)

    assert parent.wait(timeout=2) == 143
    _wait_until_gone(int(descendant_pid.read_text()))


def test_repeated_signal_does_not_interrupt_leaf_cleanup(tmp_path: Path) -> None:
    scripts = REPO_ROOT / "kaji" / "scripts"
    leaf_pid = tmp_path / "signal-leaf.pid"
    program = tmp_path / "active_signal_runner.py"
    leaf = (
        "import pathlib,signal,time,os; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        f"pathlib.Path({str(leaf_pid)!r}).write_text(str(os.getpid())); "
        "time.sleep(60)"
    )
    program.write_text(
        "import pathlib,sys\n"
        f"sys.path.insert(0, {str(scripts)!r})\n"
        "from process_runner import CommandBudget,CommandInterruptedError,run_checked\n"
        "try:\n"
        f"    run_checked([sys.executable, '-c', {leaf!r}], cwd=pathlib.Path.cwd(), "
        "budget=CommandBudget(timeout_seconds=60, terminate_grace_seconds=.2), "
        "input_bytes=b'x' * 4194304)\n"
        "except CommandInterruptedError as error:\n"
        "    raise SystemExit(128 + error.signum)\n"
    )
    parent = subprocess.Popen([sys.executable, str(program)], cwd=tmp_path)
    _wait_for_file(leaf_pid)
    parent.send_signal(signal.SIGTERM)
    time.sleep(0.02)
    parent.send_signal(signal.SIGTERM)

    assert parent.wait(timeout=2) == 143
    _wait_until_gone(int(leaf_pid.read_text()))
