from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any, cast

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "kaji" / "scripts"
PYTHON_SOAK = REPO_ROOT / "kaji" / "benchmarks" / "python" / "runtime_soak.py"


def _load(path: Path):
    scripts = str(SCRIPTS)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location(f"test_{path.stem}_focused", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_soak_gate_help_starts_in_installed_runtime_safe_environment(
    tmp_path: Path,
) -> None:
    installed_runtime = _load(SCRIPTS / "installed_release_runtime.py")
    environment = installed_runtime._safe_environment(tmp_path)

    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "beta_soak_gate.py"), "--help"],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


def _memory_samples(runtime: str) -> list[dict[str, float]]:
    samples: list[dict[str, float]] = []
    for minute in range(21, 31):
        sample = {
            "minute": minute + 0.01,
            "rssMiB": 100.0,
        }
        if runtime == "python":
            sample["heapMiB"] = 50.0
        else:
            sample.update(
                {
                    "elapsedMs": (minute + 0.01) * 60_000,
                    "heapUsedMiB": 50.0,
                    "heapTotalMiB": 60.0,
                    "maxRssMiB": 110.0,
                }
            )
        samples.append(sample)
    return samples


def _object_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _object_list(value: object) -> list[object]:
    assert isinstance(value, list)
    return cast(list[object], value)


def _receipt_sample(receipt: dict[str, object], index: int) -> dict[str, object]:
    return _object_dict(_object_list(receipt["memorySamples"])[index])


def _valid_receipt(runtime: str) -> dict[str, object]:
    internal: dict[str, object] = {
        "coordinatorEntries": 0,
        "coordinatorWaiters": 0,
        "stuckToolCalls": 0,
        "maxToolActive": 4,
        "maxSubscriberQueueDepth": 1_024,
        "subscriberOverflows": 1,
        "projectionCacheSize": 0,
        "projectionCacheLimit": 1_000,
        "ledgerSize": 0,
        "ledgerPeakSize": 1,
        "ledgerLimit": 10_000,
        "ledgerCounts": {"running": 0, "completed": 0, "unknown": 0},
    }
    provider: dict[str, object] = {"active": 0}
    value: dict[str, object] = {
        "schemaVersion": 2,
        "runtime": runtime,
        "resolvedPackage": f"/installed/{runtime}",
        "seed": 13,
        "offline": True,
        "requestedMinutes": 30.0,
        "elapsedSeconds": 1_801.0,
        "attemptedTurns": 10_000,
        "completedTurns": 9_999,
        "failedTurns": 1,
        "terminalOutcomes": {"completed": 9_999, "failed": 0, "cancelled": 1},
        "memorySamples": _memory_samples(runtime),
        "provider": provider,
        "internal": internal,
    }
    if runtime == "python":
        value.update({"cooperativeTimeouts": 1, "noncooperativeTimeouts": 1})
        provider.update(
            {
                "multiToolBatches": 1,
                "chargeRequests": 1,
                "approvalBridgeRequests": 1,
                "maxMessages": 1,
                "maxCharacters": 10,
            }
        )
        internal.update(
            {
                "subscriberCount": 0,
                "metricSubscriberOverflows": 1,
                "subscriberResumes": 1,
                "maxContextMessages": 1,
                "maxContextCharacters": 10,
            }
        )
    else:
        internal["scenarios"] = {
            "toolCallsRequested": 1,
            "approvals": 1,
            "cancellations": 1,
            "cooperativeTimeouts": 1,
            "nonCooperativeTimeouts": 1,
            "sessionClosures": 1,
        }
    return value


def test_python_soak_reclaims_closed_sessions_before_store_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load(PYTHON_SOAK)
    store_type = module.InMemoryEventStore
    stores: list[Any] = []

    def bounded_store(**kwargs: object):
        store = store_type(
            max_sessions=16,
            max_events_per_session=kwargs["max_events_per_session"],
        )
        stores.append(store)
        return store

    monkeypatch.setattr(module, "InMemoryEventStore", bounded_store)

    async def run_and_fill_store() -> dict[str, Any]:
        result = await module._run(0.03, 13)
        assert len(stores) == 1
        for index in range(16):
            await stores[0].append(
                module.UserMessage(
                    id=f"capacity-{index}",
                    timestamp=0.0,
                    session_id=f"capacity-{index}",
                    content="post-soak capacity probe",
                )
            )
        return cast(dict[str, Any], result)

    result = asyncio.run(run_and_fill_store())

    assert result["attemptedTurns"] >= 16
    assert result["failedTurns"] == result["terminalOutcomes"]["cancelled"]
    assert result["terminalOutcomes"]["failed"] == 0
    assert result["internal"]["projectionCacheSize"] == 0
    assert result["internal"]["ledgerSize"] == 0
    assert result["internal"]["ledgerPeakSize"] > 0
    assert result["offline"] is True


def test_python_timeout_probes_survive_slow_ledger_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load(PYTHON_SOAK)
    original_claim = module.InMemoryToolIdempotencyLedger.claim

    async def delayed_claim(self: object, **kwargs: object):
        await asyncio.sleep(0.01)
        return await original_claim(self, **kwargs)

    monkeypatch.setattr(
        module.InMemoryToolIdempotencyLedger,
        "claim",
        delayed_claim,
    )

    async def exercise_probes() -> tuple[int, int]:
        return (
            await module._exercise_cooperative_timeout(1),
            await module._exercise_noncooperative_timeouts(1),
        )

    cooperative, noncooperative = asyncio.run(exercise_probes())

    assert cooperative == 1
    assert noncooperative == 4


def test_python_soak_samples_after_subscriber_probe_is_purged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load(PYTHON_SOAK)
    store_type = module.InMemoryEventStore
    journal_type = module.InMemoryEventJournal
    stores: list[Any] = []
    journals: list[Any] = []
    sample_states: list[tuple[tuple[str, ...], tuple[str, ...], int]] = []

    def tracked_store(**kwargs: object):
        store = store_type(**kwargs)
        stores.append(store)
        return store

    def tracked_journal(*args: object, **kwargs: object):
        journal = journal_type(*args, **kwargs)
        journals.append(journal)
        return journal

    def tracked_sample(minute: float) -> dict[str, float]:
        assert len(stores) == 1
        assert len(journals) == 1
        sample_states.append(
            (
                tuple(stores[0]._events),
                tuple(journals[0]._subscribers),
                stores[0].active_listener_count,
            )
        )
        return {"minute": minute, "heapMiB": 50.0, "rssMiB": 100.0}

    monkeypatch.setattr(module, "InMemoryEventStore", tracked_store)
    monkeypatch.setattr(module, "InMemoryEventJournal", tracked_journal)
    monkeypatch.setattr(module, "_sample_memory", tracked_sample)

    result = asyncio.run(module._run(0.0001, 13))

    assert sample_states
    assert all(
        not any(session.startswith("slow-subscriber-") for session in sessions)
        and not any(
            session.startswith("slow-subscriber-") for session in subscriber_sessions
        )
        and listener_count == 0
        for sessions, subscriber_sessions, listener_count in sample_states
    )
    assert result["internal"]["maxSubscriberQueueDepth"] == 1_024
    assert result["internal"]["subscriberOverflows"] == 1
    assert result["internal"]["metricSubscriberOverflows"] == 1
    assert result["internal"]["subscriberResumes"] == 1
    assert result["internal"]["subscriberCount"] == 0


@pytest.mark.parametrize("runtime", ["python", "typescript"])
def test_soak_gate_rejects_unexpected_non_cancelled_turn_failures(
    runtime: str,
) -> None:
    module = _load(SCRIPTS / "beta_soak_gate.py")
    receipt = {
        "requestedMinutes": 30,
        "elapsedSeconds": 1_800,
        "attemptedTurns": 10_000,
        "completedTurns": 9_997,
        "failedTurns": 3,
        "terminalOutcomes": {"completed": 9_997, "failed": 1, "cancelled": 2},
        "memorySamples": [],
        "internal": {},
        "provider": {},
    }

    failures = module._failures(receipt, runtime, 30.0)

    assert any("unexpected failed turns" in failure for failure in failures)


@pytest.mark.parametrize(
    ("index", "runtime", "failure_code"),
    [
        (0, "python", "python_soak_failed"),
        (1, "typescript", "typescript_soak_failed"),
        (None, None, "soak_child_failed"),
    ],
)
def test_soak_child_failure_is_classified_without_command_details(
    index: int | None,
    runtime: str | None,
    failure_code: str,
) -> None:
    module = _load(SCRIPTS / "run_beta_soak.py")
    error = module.CommandExitError(9, command_index=index)

    assert module._child_failure(error) == (
        failure_code,
        {
            "phase": "child",
            "runtime": runtime,
            "exitStatus": 9,
        },
    )


def test_soak_failure_receipt_retains_safe_child_diagnostics(tmp_path: Path) -> None:
    module = _load(SCRIPTS / "run_beta_soak.py")
    output = tmp_path / "results.json"

    module._write_failure_receipt(
        output,
        protected=False,
        failure_code="python_soak_failed",
        commit=None,
        diagnostics={"phase": "child", "runtime": "python", "exitStatus": 1},
    )

    assert json.loads(output.read_text())["diagnostics"] == {
        "phase": "child",
        "runtime": "python",
        "exitStatus": 1,
    }


def test_soak_detailed_gate_failure_is_preserved(tmp_path: Path) -> None:
    module = _load(SCRIPTS / "run_beta_soak.py")
    output = tmp_path / "results.json"
    report = {
        "schemaVersion": 1,
        "requestedMinutes": 30,
        "budgets": {"durationMinutes": 30},
        "results": {"python": {}, "typescript": {}},
        "passed": False,
        "failures": ["python soak leaked coordinator state"],
    }
    output.write_text(json.dumps(report))

    assert module._has_detailed_gate_failure(output) is True
    assert json.loads(output.read_text()) == report


@pytest.mark.parametrize(
    "value",
    [
        {"passed": True, "failures": []},
        {"passed": False, "failures": []},
        {"passed": False, "failures": [""]},
        [],
    ],
)
def test_soak_invalid_gate_failure_report_is_not_preserved(
    tmp_path: Path, value: object
) -> None:
    module = _load(SCRIPTS / "run_beta_soak.py")
    output = tmp_path / "results.json"
    output.write_text(json.dumps(value))

    assert module._has_detailed_gate_failure(output) is False


def test_soak_preflight_failure_is_not_a_detailed_gate_report(
    tmp_path: Path,
) -> None:
    module = _load(SCRIPTS / "run_beta_soak.py")
    output = tmp_path / "results.json"
    module._write_failure_receipt(
        output,
        protected=False,
        failure_code="validating",
        commit=None,
    )

    assert module._has_detailed_gate_failure(output) is False


@pytest.mark.parametrize("value", [[], "secret", 1, None])
def test_soak_loader_rejects_non_object_json_safely(
    tmp_path: Path, value: object
) -> None:
    module = _load(SCRIPTS / "beta_soak_gate.py")
    artifact = tmp_path / "artifact.json"
    artifact.write_text(json.dumps(value))

    loaded, failures = module._load(artifact, "python")

    assert loaded is None
    assert failures == ["python soak artifact is not an object"]


def test_soak_loader_does_not_echo_decode_errors(tmp_path: Path) -> None:
    module = _load(SCRIPTS / "beta_soak_gate.py")
    artifact = tmp_path / "sk-secret.json"
    artifact.write_text('{"secret":"sk-child-secret"')

    loaded, failures = module._load(artifact, "typescript")

    assert loaded is None
    assert failures == ["typescript soak artifact is unreadable"]
    assert "secret" not in " ".join(failures)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("seed", 12),
        ("seed", 13.0),
        ("offline", False),
        ("offline", 1),
    ],
)
def test_soak_loader_requires_fixed_offline_workload(
    tmp_path: Path, field: str, value: object
) -> None:
    module = _load(SCRIPTS / "beta_soak_gate.py")
    artifact = tmp_path / "artifact.json"
    receipt = _valid_receipt("python")
    receipt[field] = value
    artifact.write_text(json.dumps(receipt))

    loaded, failures = module._load(artifact, "python")

    assert loaded is None
    assert failures == ["python soak artifact is not the fixed offline workload"]


@pytest.mark.parametrize("runtime", ["python", "typescript"])
@pytest.mark.parametrize("value", [-1.0, float("inf"), float("nan")])
def test_soak_gate_rejects_negative_or_nonfinite_memory(
    runtime: str, value: float
) -> None:
    module = _load(SCRIPTS / "beta_soak_gate.py")
    receipt = _valid_receipt(runtime)
    _receipt_sample(receipt, 0)["rssMiB"] = value

    summary, failures = module._memory_summary(receipt, runtime)

    assert summary is None
    assert any("invalid values" in failure for failure in failures)


def test_soak_gate_rejects_duplicate_actual_minute_bucket() -> None:
    module = _load(SCRIPTS / "beta_soak_gate.py")
    receipt = _valid_receipt("python")
    _receipt_sample(receipt, 1)["minute"] = 21.5

    summary, failures = module._memory_summary(receipt, "python")

    assert summary is None
    assert any("duplicate minute 21" in failure for failure in failures)
    assert any("missing late-window minutes: 22" in failure for failure in failures)


def test_typescript_soak_gate_rejects_minute_elapsed_mismatch() -> None:
    module = _load(SCRIPTS / "beta_soak_gate.py")
    receipt = _valid_receipt("typescript")
    _receipt_sample(receipt, 0)["elapsedMs"] = 1.0

    summary, failures = module._memory_summary(receipt, "typescript")

    assert summary is None
    assert any(
        "elapsed time does not match its minute" in failure for failure in failures
    )


def test_soak_gate_rejects_samples_beyond_reported_elapsed_time() -> None:
    module = _load(SCRIPTS / "beta_soak_gate.py")
    receipt = _valid_receipt("python")
    receipt["elapsedSeconds"] = 29 * 60

    failures = module._failures(receipt, "python", 30.0)

    assert any(
        "memory sample exceeds reported elapsed time" in failure for failure in failures
    )


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({"projectionCacheSize": 1}, "projection cache"),
        ({"ledgerSize": 1}, "ledger entries"),
        (
            {"ledgerCounts": {"running": 1, "completed": 0, "unknown": 0}},
            "ledger counts",
        ),
        (
            {"ledgerCounts": {"running": 0, "completed": 1, "unknown": 0}},
            "ledger counts",
        ),
        (
            {"ledgerCounts": {"running": 0, "completed": 0}},
            "ledger counts",
        ),
    ],
)
def test_soak_gate_requires_empty_final_caches_and_ledger(
    updates: dict[str, object], expected: str
) -> None:
    module = _load(SCRIPTS / "beta_soak_gate.py")
    receipt = _valid_receipt("typescript")
    _object_dict(receipt["internal"]).update(updates)

    failures = module._failures(receipt, "typescript", 30.0)

    assert any(expected in failure for failure in failures)


@pytest.mark.parametrize("value", [None, -1, 1.0])
def test_soak_gate_requires_measured_ledger_peak(value: object) -> None:
    module = _load(SCRIPTS / "beta_soak_gate.py")
    receipt = _valid_receipt("python")
    _object_dict(receipt["internal"])["ledgerPeakSize"] = value

    failures = module._failures(receipt, "python", 30.0)

    assert any("ledger peak" in failure for failure in failures)


def test_soak_gate_report_does_not_preserve_untrusted_child_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load(SCRIPTS / "beta_soak_gate.py")
    python = tmp_path / "python.json"
    typescript = tmp_path / "typescript.json"
    output = tmp_path / "results.json"
    secret = "sk-child-secret"
    for runtime, path in (("python", python), ("typescript", typescript)):
        receipt = _valid_receipt(runtime)
        receipt["secret"] = secret
        _object_dict(receipt["provider"])["secret"] = secret
        _receipt_sample(receipt, 0)["secret"] = secret
        path.write_text(json.dumps(receipt))
    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: SimpleNamespace(
            minutes=30.0,
            python=python,
            typescript=typescript,
            output=output,
            protected=False,
            runtime_identity=None,
            runner_image_data=None,
        ),
    )
    monkeypatch.setattr(
        module,
        "performance_provenance",
        lambda **_kwargs: {"commit": "a" * 40, "fingerprint": {}, "protected": False},
    )

    assert module.main() == 0
    assert secret not in output.read_text()


@pytest.mark.parametrize("resolved_package", [None, ""])
def test_passed_soak_gate_requires_resolved_package(
    tmp_path: Path, resolved_package: str | None
) -> None:
    module = _load(SCRIPTS / "run_beta_soak.py")
    output = tmp_path / "results.json"
    python_result = {"schemaVersion": 2, "runtime": "python"}
    if resolved_package is not None:
        python_result["resolvedPackage"] = resolved_package
    output.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "requestedMinutes": 0.01,
                "budgets": {},
                "results": {
                    "python": python_result,
                    "typescript": {
                        "schemaVersion": 2,
                        "runtime": "typescript",
                        "resolvedPackage": "/installed/typescript",
                    },
                },
                "failures": [],
                "passed": True,
            }
        )
    )

    assert module._passed_gate_results(output) is None


def test_successful_soak_retains_only_sanitized_runtime_sidecars(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load(SCRIPTS / "run_beta_soak.py")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: SimpleNamespace(minutes="0.01", protected=False, artifacts_dir=None),
    )
    monkeypatch.setattr(module, "python_command", lambda: [sys.executable])
    secret = "sk-child-secret"
    completed = SimpleNamespace(
        stdout=json.dumps({"secret": secret}).encode(),
        returncode=0,
    )
    monkeypatch.setattr(
        module,
        "run_parallel_checked",
        lambda _specs: (completed, completed),
    )
    results = {
        "python": {
            "schemaVersion": 2,
            "runtime": "python",
            "resolvedPackage": "/installed/python",
            "attemptedTurns": 10,
        },
        "typescript": {
            "schemaVersion": 2,
            "runtime": "typescript",
            "resolvedPackage": "/installed/typescript",
            "attemptedTurns": 11,
        },
    }

    def successful_gate(command: list[str], **_kwargs: object) -> SimpleNamespace:
        for name in ("--python", "--typescript"):
            child = Path(command[command.index(name) + 1])
            assert secret in child.read_text()
        output = Path(command[command.index("--output") + 1])
        output.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "requestedMinutes": 0.01,
                    "budgets": {},
                    "results": results,
                    "failures": [],
                    "passed": True,
                }
            )
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module, "run_checked", successful_gate)

    assert module.main() == 0
    artifacts = tmp_path / ".artifacts" / "kaji-soak"
    assert {path.name for path in artifacts.iterdir()} == {
        "python.json",
        "results.json",
        "typescript.json",
    }
    assert json.loads((artifacts / "python.json").read_text()) == results["python"]
    assert (
        json.loads((artifacts / "typescript.json").read_text())
        == (results["typescript"])
    )
    assert secret not in "".join(
        path.read_text() for path in artifacts.iterdir() if path.is_file()
    )


def test_soak_zero_status_invalid_gate_report_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load(SCRIPTS / "run_beta_soak.py")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: SimpleNamespace(minutes="0.01", protected=False, artifacts_dir=None),
    )
    monkeypatch.setattr(module, "python_command", lambda: [sys.executable])
    completed = SimpleNamespace(stdout=b"{}", returncode=0)
    monkeypatch.setattr(
        module,
        "run_parallel_checked",
        lambda _specs: (completed, completed),
    )

    def invalid_gate(command: list[str], **_kwargs: object) -> SimpleNamespace:
        output = Path(command[command.index("--output") + 1])
        output.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "requestedMinutes": 0.01,
                    "budgets": {},
                    "results": {"python": {}},
                    "failures": [],
                    "passed": True,
                }
            )
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module, "run_checked", invalid_gate)

    assert module.main() == 1
    artifacts = tmp_path / ".artifacts" / "kaji-soak"
    assert {path.name for path in artifacts.iterdir()} == {"results.json"}
    assert json.loads((artifacts / "results.json").read_text())["failureCode"] == (
        "soak_gate_failed"
    )


def test_soak_child_cannot_prewrite_retained_gate_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load(SCRIPTS / "run_beta_soak.py")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: SimpleNamespace(minutes="0.01", protected=False, artifacts_dir=None),
    )
    monkeypatch.setattr(module, "python_command", lambda: [sys.executable])
    artifacts = tmp_path / ".artifacts" / "kaji-soak"
    output = artifacts / "results.json"
    sidecar = artifacts / "python-heap-samples.json"
    secret = "sk-child-prewrite"
    artifact_directories: list[Path] = []
    completed = SimpleNamespace(stdout=b"{}")

    def prewriting_children(specs: tuple[object, ...]) -> tuple[object, object]:
        for spec in specs:
            command = tuple(getattr(spec, "command"))
            flag = (
                "--artifacts-dir" if "--artifacts-dir" in command else "--artifact-dir"
            )
            artifact_directories.append(Path(command[command.index(flag) + 1]))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "requestedMinutes": 30,
                    "budgets": {},
                    "results": {},
                    "passed": False,
                    "failures": [secret],
                }
            )
        )
        sidecar.write_text(secret)
        return completed, completed

    gate_saw_output: list[bool] = []

    def failing_gate(_command: list[str], **_kwargs: object) -> SimpleNamespace:
        gate_saw_output.append(output.exists())
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(module, "run_parallel_checked", prewriting_children)
    monkeypatch.setattr(module, "run_checked", failing_gate)

    assert module.main() == 1
    receipt = json.loads(output.read_text())
    assert artifact_directories[0] == artifact_directories[1]
    assert artifact_directories[0] != artifacts
    assert gate_saw_output == [False]
    assert receipt["failureCode"] == "soak_gate_failed"
    assert receipt["failures"] == ["soak_gate_failed"]
    assert set(path.name for path in artifacts.iterdir()) == {"results.json"}
    assert secret not in output.read_text()


def test_soak_child_failure_removes_stale_sibling_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load(SCRIPTS / "run_beta_soak.py")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: SimpleNamespace(minutes="0.01", protected=False, artifacts_dir=None),
    )
    monkeypatch.setattr(module, "python_command", lambda: [sys.executable])
    artifacts = tmp_path / ".artifacts" / "kaji-soak"
    artifacts.mkdir(parents=True)
    (artifacts / "stale-heap-samples.json").write_text("stale")
    monkeypatch.setattr(
        module,
        "run_parallel_checked",
        lambda _specs: (_ for _ in ()).throw(
            module.CommandExitError(9, command_index=0)
        ),
    )

    assert module.main() == 1
    assert set(path.name for path in artifacts.iterdir()) == {"results.json"}
    assert json.loads((artifacts / "results.json").read_text())["failureCode"] == (
        "python_soak_failed"
    )


def test_soak_failure_receipt_whitelists_codes_and_diagnostics(tmp_path: Path) -> None:
    module = _load(SCRIPTS / "run_beta_soak.py")
    output = tmp_path / "results.json"
    secret = "sk-child-secret"

    module._write_failure_receipt(
        output,
        protected=False,
        failure_code=secret,
        commit=secret,
        diagnostics={
            "phase": "child",
            "runtime": "python",
            "exitStatus": 7,
            "secret": secret,
        },
    )

    receipt = json.loads(output.read_text())
    assert receipt["failureCode"] == "soak_failed"
    assert receipt["failures"] == ["soak_failed"]
    assert receipt["diagnostics"] == {
        "phase": "child",
        "runtime": "python",
        "exitStatus": 7,
    }
    assert secret not in output.read_text()
