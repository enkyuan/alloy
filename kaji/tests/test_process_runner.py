from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
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

    with pytest.raises(runner.CommandExitError):
        runner.run_parallel_checked((failing, hanging))

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

    secret = "sk-secret\0argument"
    with pytest.raises(runner.CommandStartError) as captured:
        runner.run_checked(
            [sys.executable, secret],
            cwd=tmp_path,
            budget=runner.CommandBudget(timeout_seconds=1),
        )
    assert "sk-secret" not in str(captured.value)


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
        "budget=CommandBudget(timeout_seconds=60, terminate_grace_seconds=.2))\n"
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
