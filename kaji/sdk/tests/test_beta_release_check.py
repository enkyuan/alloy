from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
BETA_GATE = REPO_ROOT / "kaji" / "scripts" / "beta_release_check.py"
ROOT_PACKAGE = REPO_ROOT / "package.json"
ROOT_LOCK = REPO_ROOT / "bun.lock"
ROOT_GITIGNORE = REPO_ROOT / ".gitignore"
RULE_DIR = REPO_ROOT / "tools" / "ast-grep" / "rules"
RULE_TEST_DIR = REPO_ROOT / "tools" / "ast-grep" / "rule-tests"
SGCONFIG = REPO_ROOT / "sgconfig.yml"
AST_GREP_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ast-grep.yml"


def _load_beta_gate():
    scripts = str(BETA_GATE.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("test_beta_gate_module", BETA_GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_root_script(name: str):
    path = BETA_GATE.parent / name
    scripts = str(path.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location(f"test_{path.stem}_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_beta_release_check_python_syntax() -> None:
    subprocess.run([sys.executable, "-m", "py_compile", str(BETA_GATE)], check=True)


def test_beta_release_check_rejects_unknown_flag_before_gates() -> None:
    result = subprocess.run(
        [sys.executable, str(BETA_GATE), "--unknown"],
        capture_output=True,
        check=False,
        env={"PATH": "/usr/bin:/bin"},
        text=True,
    )

    assert result.returncode == 2
    assert "usage:" in result.stderr
    assert "PASS:" not in result.stdout + result.stderr


def test_protected_provider_proof_requires_openai_before_success() -> None:
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    proof = REPO_ROOT / "kaji" / "scripts" / "live_provider_proof.py"
    result = subprocess.run(
        [sys.executable, str(proof)],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 2
    assert "OPENAI_API_KEY is required for keyed provider proof" in output
    assert "STATUS: openai=passed" not in output
    assert "PASS:" not in output


def test_release_success_line_disclaims_protected_evidence() -> None:
    literals = {
        node.value
        for node in ast.walk(ast.parse(BETA_GATE.read_text()))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert (
        "PASS: offline release rehearsal; keyed/provider/publish readiness NOT claimed"
        in literals
    )
    assert "PASS: Kaji beta release checks completed" not in literals


def test_beta_release_check_wraps_required_gates() -> None:
    script = BETA_GATE.read_text()

    for expected in [
        '"pytest", "-m", "not integration"',
        '"scripts/check_types.py"',
        '"scripts/release_smoke.py"',
        '"package:smoke"',
        "live_provider_proof.py",
        "KAJI_REQUIRE_LIVE_KEYS",
        "KAJI_RUN_KEYED_LIVE",
        "UV_SYSTEM_CERTS",
        '"audit:ast-grep"',
        "check_sdk_parity.py",
        "run_beta_benchmarks.py",
        '"--quick"',
    ]:
        assert expected in script

    assert "run_optional_ast_grep" not in script
    assert "SKIP: ast-grep CLI not installed" not in script

    parity = script.index('"Cross-SDK behavioral parity"')
    assert parity < script.index("run_gates(common_gates(), environment)")
    assert parity < script.index('"Python artifact smoke"')


def test_typescript_build_precedes_every_artifact_consumer() -> None:
    module = _load_beta_gate()
    common = [gate.label for gate in module.common_gates()]
    release = [gate.label for gate in module.release_gates()]

    assert common.index("TypeScript build") < common.index("TypeScript unit tests")
    assert common.index("TypeScript build") < common.index("TypeScript package smoke")
    assert release.index("TypeScript build (release)") < release.index(
        "TypeScript tests (release)"
    )
    assert release.index("TypeScript build (release)") < release.index(
        "TypeScript package smoke (release)"
    )


def test_canonical_typescript_test_script_selects_node() -> None:
    package = json.loads((REPO_ROOT / "kaji" / "ts" / "package.json").read_text())
    command = package["scripts"]["test"]

    assert command.startswith(
        'PATH="${PATH#*:}:/usr/local/bin:/opt/homebrew/bin" /bin/sh -c '
    )
    assert 'exec "$(command -v node)"' in command
    assert '"$@"' in command
    assert "vitest" in command
    assert ("bun", "run", "test") in {
        gate.command for gate in _load_beta_gate().common_gates()
    }


def test_release_wrapper_builds_before_consumers_from_checkout_without_dist(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    scripts = checkout / "kaji" / "scripts"
    sdk = checkout / "kaji" / "sdk"
    typescript = checkout / "kaji" / "ts"
    scripts.mkdir(parents=True)
    sdk.mkdir(parents=True)
    typescript.mkdir(parents=True)
    shutil.copy2(BETA_GATE, scripts / BETA_GATE.name)
    shutil.copy2(
        REPO_ROOT / "kaji" / "scripts" / "process_runner.py",
        scripts / "process_runner.py",
    )
    (scripts / "run_beta_benchmarks.py").write_text("raise SystemExit(0)\n")
    (scripts / "verify_openai_loop.py").write_text(
        "import os\n"
        "if os.environ.get('KAJI_REQUIRE_LIVE_KEYS') == '1':\n"
        "    print('FAIL: OPENAI_API_KEY required for live readiness')\n"
        "    raise SystemExit(2)\n"
        "print('SKIP: OPENAI_API_KEY not set')\n"
    )

    home = tmp_path / "home"
    binaries = home / ".local" / "bin"
    binaries.mkdir(parents=True)
    log = tmp_path / "commands.log"
    fake_tool = f"""#!{sys.executable}
import os
from pathlib import Path
import shutil
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
checkout = Path(os.environ["FAKE_CHECKOUT"])
with Path(os.environ["FAKE_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write(name + "|" + str(Path.cwd()) + "|" + " ".join(args) + "\\n")

if name == "bun":
    dist = checkout / "kaji" / "ts" / "dist"
    if args[:2] == ["run", "build"]:
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "index.js").write_text("built")
    consumer = args[:2] in (["run", "test"], ["run", "test:quickstart"], ["run", "package:smoke"])
    consumer = consumer or (args and args[0] == "scripts/smoke_package.mts")
    if consumer and not dist.is_dir():
        print("artifact consumer ran before build", file=sys.stderr)
        raise SystemExit(17)

if name == "uv":
    if "scripts/release_smoke.py" in args:
        dist = checkout / "kaji" / "sdk" / "dist"
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "kaji.whl").write_bytes(b"wheel")
        (dist / "kaji.tar.gz").write_bytes(b"sdist")
        shutil.rmtree(checkout / "kaji" / "ts" / "dist", ignore_errors=True)
    if "--output-file" in args:
        output = Path(args[args.index("--output-file") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("requirements")

if name == "npm" and args and args[0] == "pack":
    destination = Path(args[args.index("--pack-destination") + 1])
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "kaji-sdk-0.2.0-beta.1.tgz").write_bytes(b"npm")
"""
    for name in ("bun", "node", "npm", "uv"):
        executable = binaries / name
        executable.write_text(fake_tool)
        executable.chmod(0o755)

    assert not (typescript / "dist").exists()
    environment = os.environ.copy()
    environment.update(
        {
            "FAKE_CHECKOUT": str(checkout),
            "FAKE_LOG": str(log),
            "HOME": str(home),
            "PATH": str(binaries),
        }
    )
    completed = subprocess.run(
        [sys.executable, str(scripts / "beta_release_check.py"), "--release"],
        cwd=checkout,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    output = completed.stdout.strip().splitlines()
    assert output[-1] == (
        "PASS: offline release rehearsal; keyed/provider/publish readiness NOT claimed"
    )
    assert "PASS: Kaji beta checks completed" not in completed.stdout
    commands = log.read_text().splitlines()
    build_indices = [
        index
        for index, command in enumerate(commands)
        if command.endswith("|run build")
    ]
    test_indices = [
        index for index, command in enumerate(commands) if command.endswith("|run test")
    ]
    assert len(build_indices) == len(test_indices) == 2
    assert all(build < test for build, test in zip(build_indices, test_indices))


def test_soak_budget_is_duration_plus_cleanup_margin() -> None:
    module = _load_root_script("run_beta_soak.py")

    assert module.soak_minutes("0.25") == 0.25
    for invalid in ("0", "-1", "nan", "inf", "not-a-number"):
        with pytest.raises(ValueError):
            module.soak_minutes(invalid)

    source = (BETA_GATE.parent / "run_beta_soak.py").read_text()
    assert "run_parallel_checked" in source
    assert "minutes * 60 + 120" in source
    assert "subprocess" not in source


def test_benchmark_child_and_orchestrator_budgets_are_distinct() -> None:
    module = _load_root_script("process_runner.py")

    assert module.BENCHMARK_COMMAND_BUDGET.timeout_seconds == 600
    assert (
        module.BENCHMARK_ORCHESTRATOR_BUDGET.timeout_seconds
        > module.BENCHMARK_COMMAND_BUDGET.timeout_seconds
    )
    assert (
        module.RELEASE_COMMAND_BUDGET.timeout_seconds
        > module.BENCHMARK_ORCHESTRATOR_BUDGET.timeout_seconds
    )


def _valid_worst_case_sample(case: str) -> dict[str, object]:
    common: dict[str, object] = {"durationMs": 1.0, "peakMiB": 32.0}
    cases: dict[str, dict[str, object]] = {
        "replay10k": {"eventsApplied": 10_000, "cursor": 10_000},
        "crossSession100": {
            "maxActive": 100,
            "turns": 100,
            "coordinatorEntries": 0,
            "coordinatorWaiters": 0,
        },
        "sameSession25": {
            "maxActive": 1,
            "turns": 25,
            "coordinatorEntries": 0,
            "coordinatorWaiters": 0,
        },
        "toolBatch100": {"maxActive": 4, "calls": 100, "stuckCalls": 0},
        "context10kIterations5": {
            "historyEvents": 10_000,
            "fullHistoryScans": 1,
            "providerIterations": 5,
            "coldEvents": 10_000,
            "incrementalEvents": 21,
            "suffixCalls": 5,
            "copiedPayloadBytes": 0,
            "retainedTurns": 32,
            "turnIndexEntries": 32,
            "sentinelEntries": 1,
            "totalIndexEntries": 33,
            "maxVisitedTurnEntries": 32,
            "incrementalRssBytes": 1_024,
            "timerLeaks": 0,
            "providerTaskLeaks": 0,
        },
        "crossSessionCommit100": {
            "sessions": 100,
            "commits": 100,
            "overlappingSessions": 99,
            "contiguousSessions": 100,
            "laneEntriesAfter": 0,
            "reservationEntriesAfter": 0,
        },
        "streamDeltas10k": {
            "characters": 10_000,
            "deltaEvents": 3,
            "inputFragments": 10_000,
            "deltaJoinOperations": 3,
            "responseJoinOperations": 1,
            "providerTextMaxBytes": 262_144,
            "providerResponseMaxBytes": 524_288,
            "completionEvents": 1,
            "completionEventsAfterFailure": 0,
            "timerLeaks": 0,
            "providerTaskLeaks": 0,
        },
        "toolArgDeltas10k": {
            "argumentBytes": 65_536,
            "responseMaxBytes": 524_288,
            "argumentFragments": 10_000,
            "rawFragments": 10_002,
            "fragmentJoins": 1,
            "overLimitBytes": 65_537,
            "overLimitRejectedBeforeParse": True,
            "iteratorLeaks": 0,
            "parserLeaks": 0,
            "providerTaskLeaks": 0,
        },
    }
    return {**common, **cases[case]}


def test_beta_benchmark_gate_defines_all_eight_cases_and_semantic_budgets() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    budgets = json.loads(
        (REPO_ROOT / "kaji" / "benchmarks" / "beta-budgets.json").read_text()
    )

    assert module.CASES == (
        "replay10k",
        "crossSession100",
        "sameSession25",
        "toolBatch100",
        "context10kIterations5",
        "crossSessionCommit100",
        "streamDeltas10k",
        "toolArgDeltas10k",
    )
    assert budgets["context10kIterations5"] == {
        "maxFullHistoryScans": 1,
        "maxProviderIterations": 5,
        "maxCopiedPayloadBytes": 0,
        "maxIndexEntriesPerRetainedTurn": 1.01,
        "maxIncrementalRssBytes": 67_108_864,
        "maxSentinelEntries": 1,
        "maxSuffixTurnVisits": 32,
        "maxTimerLeaks": 0,
        "maxProviderTaskLeaks": 0,
    }
    assert budgets["crossSessionCommit100"] == {
        "minOverlappingSessions": 2,
        "maxLaneEntriesAfter": 0,
        "maxReservationEntriesAfter": 0,
    }
    assert budgets["streamDeltas10k"] == {
        "maxDeltaEvents": 16,
        "expectedCharacters": 10_000,
        "maxProviderTextBytes": 262_144,
        "maxProviderResponseBytes": 524_288,
        "maxTimerLeaks": 0,
        "maxProviderTaskLeaks": 0,
    }
    assert budgets["toolArgDeltas10k"] == {
        "maxArgumentBytes": 65_536,
        "maxResponseBytes": 524_288,
        "maxFragmentJoins": 1,
        "maxIteratorLeaks": 0,
        "maxParserLeaks": 0,
        "maxProviderTaskLeaks": 0,
    }


def test_beta_benchmark_gate_rejects_missing_counter_in_each_sample() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    budgets = json.loads(module.BUDGETS_PATH.read_text())
    sample = _valid_worst_case_sample("context10kIterations5")
    sample.pop("timerLeaks")

    failures = module._sample_failures(
        "python", "context10kIterations5", sample, budgets["context10kIterations5"]
    )

    assert any("timerLeaks" in failure for failure in failures)


@pytest.mark.parametrize(
    "case",
    [
        "replay10k",
        "crossSession100",
        "sameSession25",
        "toolBatch100",
        "context10kIterations5",
        "crossSessionCommit100",
        "streamDeltas10k",
        "toolArgDeltas10k",
    ],
)
def test_beta_benchmark_gate_accepts_valid_semantics_for_every_case(case: str) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    budgets = json.loads(module.BUDGETS_PATH.read_text())

    assert (
        module._sample_failures(
            "python", case, _valid_worst_case_sample(case), budgets[case]
        )
        == []
    )


@pytest.mark.parametrize(
    ("case", "field", "value"),
    [
        ("replay10k", "eventsApplied", 9_999),
        ("crossSession100", "turns", 99),
        ("sameSession25", "turns", 24),
        ("toolBatch100", "calls", 99),
        ("context10kIterations5", "providerIterations", 4),
        ("crossSessionCommit100", "sessions", 99),
        ("streamDeltas10k", "characters", 9_999),
        ("toolArgDeltas10k", "argumentBytes", 65_535),
    ],
)
def test_beta_benchmark_gate_rejects_invalid_semantics_for_every_case(
    case: str, field: str, value: int
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    budgets = json.loads(module.BUDGETS_PATH.read_text())
    sample = {**_valid_worst_case_sample(case), field: value}

    failures = module._sample_failures("python", case, sample, budgets[case])

    assert any(field in failure for failure in failures)


@pytest.mark.parametrize(
    ("case", "expected"), [("crossSession100", 100), ("sameSession25", 25)]
)
@pytest.mark.parametrize("value", [None, -1, 1])
def test_beta_benchmark_gate_requires_exact_concurrency_turns(
    case: str, expected: int, value: int | None
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    budgets = json.loads(module.BUDGETS_PATH.read_text())
    sample = _valid_worst_case_sample(case)
    if value is None:
        sample.pop("turns")
    else:
        sample["turns"] = expected + value

    failures = module._sample_failures("typescript", case, sample, budgets[case])

    assert any("turns" in failure for failure in failures)


def test_beta_benchmark_gate_rejects_non_object_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    payload = {
        "schemaVersion": 1,
        "runtime": "python",
        "case": "replay10k",
        "samples": 1,
        "warmups": 1,
        "seed": 13,
        "sampleResults": [42],
        "medianMs": 1.0,
        "maxPeakMiB": 32.0,
    }
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(payload).encode()
    )
    monkeypatch.setattr(module, "run_checked", lambda *_args, **_kwargs: completed)

    with pytest.raises(RuntimeError, match="sample 1 is not an object"):
        module._run_case("python", "replay10k", 1, 1)


def test_beta_benchmark_gate_rejects_wrong_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    payload = {
        "schemaVersion": 1,
        "runtime": "python",
        "case": "replay10k",
        "samples": 1,
        "warmups": 1,
        "seed": 14,
        "sampleResults": [{"durationMs": 1.0, "peakMiB": 32.0}],
        "medianMs": 1.0,
        "maxPeakMiB": 32.0,
    }
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(payload).encode()
    )
    monkeypatch.setattr(module, "run_checked", lambda *_args, **_kwargs: completed)

    with pytest.raises(RuntimeError, match="wrong seed"):
        module._run_case("python", "replay10k", 1, 1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("medianMs", float("nan")),
        ("maxPeakMiB", float("nan")),
        ("medianMs", -1.0),
        ("maxPeakMiB", -1.0),
    ],
)
def test_beta_benchmark_gate_rejects_invalid_runtime_aggregate(
    monkeypatch: pytest.MonkeyPatch, field: str, value: float
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    payload = {
        "schemaVersion": 1,
        "runtime": "python",
        "case": "replay10k",
        "samples": 3,
        "warmups": 2,
        "seed": 13,
        "sampleResults": [
            {"durationMs": 1.0, "peakMiB": 30.0},
            {"durationMs": 2.0, "peakMiB": 32.0},
            {"durationMs": 3.0, "peakMiB": 31.0},
        ],
        "medianMs": 2.0,
        "maxPeakMiB": 32.0,
    }
    payload[field] = value
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(payload).encode()
    )
    monkeypatch.setattr(module, "run_checked", lambda *_args, **_kwargs: completed)

    with pytest.raises(RuntimeError, match=f"{field} must be finite and non-negative"):
        module._run_case("python", "replay10k", 3, 2)


@pytest.mark.parametrize(
    ("field", "value", "derived"),
    [("medianMs", 1.0, "median"), ("maxPeakMiB", 31.0, "maximum")],
)
def test_beta_benchmark_gate_rejects_mismatched_runtime_aggregate(
    monkeypatch: pytest.MonkeyPatch, field: str, value: float, derived: str
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    payload = {
        "schemaVersion": 1,
        "runtime": "python",
        "case": "replay10k",
        "samples": 3,
        "warmups": 2,
        "seed": 13,
        "sampleResults": [
            {"durationMs": 1.0, "peakMiB": 30.0},
            {"durationMs": 2.0, "peakMiB": 32.0},
            {"durationMs": 3.0, "peakMiB": 31.0},
        ],
        "medianMs": 2.0,
        "maxPeakMiB": 32.0,
    }
    payload[field] = value
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(payload).encode()
    )
    monkeypatch.setattr(module, "run_checked", lambda *_args, **_kwargs: completed)

    with pytest.raises(RuntimeError, match=f"does not match sample {derived}"):
        module._run_case("python", "replay10k", 3, 2)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), -1.0])
def test_beta_benchmark_gate_rejects_non_finite_or_negative_counter(
    value: float,
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    budgets = json.loads(module.BUDGETS_PATH.read_text())
    sample = {**_valid_worst_case_sample("streamDeltas10k"), "deltaEvents": value}

    failures = module._sample_failures(
        "python", "streamDeltas10k", sample, budgets["streamDeltas10k"]
    )

    assert any(
        "deltaEvents" in failure and "non-finite or negative" in failure
        for failure in failures
    )


def test_beta_benchmark_gate_enforces_every_measured_sample() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    budgets = json.loads(module.BUDGETS_PATH.read_text())
    first = _valid_worst_case_sample("streamDeltas10k")
    second = {**first, "deltaEvents": 17}
    results = {
        "streamDeltas10k": {
            "sampleResults": [first, second],
            "medianMs": 1.0,
            "maxPeakMiB": 32.0,
        }
    }

    failures = module._case_failures(
        "python", "streamDeltas10k", results["streamDeltas10k"], budgets, False
    )

    assert any(
        "sample 2" in failure and "deltaEvents" in failure for failure in failures
    )


@pytest.mark.parametrize(
    ("updates", "counter"),
    [
        ({"retainedTurns": 0}, "retainedTurns"),
        ({"turnIndexEntries": 33}, "turnIndexEntries"),
        ({"sentinelEntries": 2, "totalIndexEntries": 34}, "sentinelEntries"),
    ],
)
def test_beta_benchmark_gate_validates_context_entry_ratio_and_sentinel(
    updates: dict[str, object], counter: str
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    budgets = json.loads(module.BUDGETS_PATH.read_text())
    sample = {**_valid_worst_case_sample("context10kIterations5"), **updates}

    failures = module._sample_failures(
        "python", "context10kIterations5", sample, budgets["context10kIterations5"]
    )

    assert any(counter in failure for failure in failures)


def test_beta_benchmark_timing_runs_only_in_full_mode() -> None:
    module = _load_root_script("beta_benchmark_gate.py")

    assert module._include_timing("quick") is False
    assert module._include_timing("calibrate") is False
    assert module._include_timing("full") is True


def test_beta_benchmark_candidate_requires_all_eight_cases() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    incomplete = {"python": {}, "typescript": {}}

    with pytest.raises(RuntimeError, match="missing python cases"):
        module._candidate_baseline(incomplete, {})


def _complete_benchmark_results(module: object) -> dict[str, dict[str, Any]]:
    cases = getattr(module, "CASES")
    return {
        runtime: {
            case: {
                "medianMs": 3.0,
                "maxPeakMiB": 95.0,
                "sampleResults": [
                    {"durationMs": float(index), "peakMiB": 90.0 + index}
                    for index in range(1, 6)
                ],
            }
            for case in cases
        }
        for runtime in ("python", "typescript")
    }


def _complete_benchmark_baseline(module: object) -> dict[str, Any]:
    cases = getattr(module, "CASES")
    return {
        "schemaVersion": 1,
        "status": "calibrated",
        "runner": {"imageDigest": "pinned"},
        "versions": {"python": "3", "node": "24", "bun": "1"},
        "dependencyLockHash": "lock",
        "medians": {
            runtime: {case: 10.0 for case in cases}
            for runtime in ("python", "typescript")
        },
        "rawSamples": {
            runtime: {case: [10.0] * 5 for case in cases}
            for runtime in ("python", "typescript")
        },
        "maxPeakMiB": {
            runtime: {case: 100.0 for case in cases}
            for runtime in ("python", "typescript")
        },
        "rawPeakMiB": {
            runtime: {case: [100.0] * 5 for case in cases}
            for runtime in ("python", "typescript")
        },
    }


@pytest.mark.parametrize("mode", ["quick", "calibrate"])
def test_beta_benchmark_non_full_modes_do_not_read_baseline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    output = tmp_path / f"{mode}.json"
    candidate = tmp_path / "candidate.json" if mode == "calibrate" else None
    monkeypatch.setattr(module, "BASELINE_PATH", tmp_path / "missing-baseline.json")
    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: module.argparse.Namespace(
            mode=mode, output=output, candidate_baseline=candidate
        ),
    )
    monkeypatch.setattr(
        module,
        "fingerprint",
        lambda: {"runner": {"imageDigest": "pinned"}},
    )
    monkeypatch.setattr(
        module,
        "_run_case",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("benchmark sentinel")
        ),
    )
    monkeypatch.setenv("KAJI_BENCHMARK_CALIBRATION", "1")
    monkeypatch.setenv("KAJI_BENCHMARK_PINNED_RUNNER", "1")

    assert module.main() == 1
    assert json.loads(output.read_text())["failures"] == ["benchmark sentinel"]


def test_beta_benchmark_full_mode_reports_malformed_baseline_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    baseline = tmp_path / "baseline.json"
    baseline.write_text("{")
    output = tmp_path / "full.json"
    monkeypatch.setattr(module, "BASELINE_PATH", baseline)
    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: module.argparse.Namespace(
            mode="full", output=output, candidate_baseline=None
        ),
    )
    monkeypatch.setattr(module, "fingerprint", lambda: {})

    assert module.main() == 1
    report = json.loads(output.read_text())
    assert report["passed"] is False
    assert any("baseline" in failure for failure in report["failures"])


def test_beta_benchmark_full_mode_reports_malformed_nested_baseline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    baseline_value = _complete_benchmark_baseline(module)
    current = module._baseline_fingerprint(baseline_value)
    baseline_value["rawSamples"]["python"]["replay10k"] = 1
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(baseline_value))
    output = tmp_path / "full.json"
    monkeypatch.setattr(module, "BASELINE_PATH", baseline)
    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: module.argparse.Namespace(
            mode="full", output=output, candidate_baseline=None
        ),
    )
    monkeypatch.setattr(module, "fingerprint", lambda: current)

    assert module.main() == 1
    report = json.loads(output.read_text())
    assert report["passed"] is False
    assert any(
        "rawSamples.python.replay10k" in failure for failure in report["failures"]
    )


@pytest.mark.parametrize("rss_field", ["maxPeakMiB", "rawPeakMiB"])
def test_beta_benchmark_baseline_requires_rss_case_coverage(rss_field: str) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    baseline = _complete_benchmark_baseline(module)
    baseline[rss_field]["python"].pop("toolArgDeltas10k")
    current = module._baseline_fingerprint(baseline)

    with pytest.raises(RuntimeError, match="RSS cases"):
        module._validate_baseline(baseline, current)


def test_beta_benchmark_baseline_requires_five_rss_samples() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    baseline = _complete_benchmark_baseline(module)
    baseline["rawPeakMiB"]["python"]["streamDeltas10k"] = [100.0]
    current = module._baseline_fingerprint(baseline)

    with pytest.raises(RuntimeError, match="RSS samples must contain five values"):
        module._validate_baseline(baseline, current)


@pytest.mark.parametrize(
    ("field", "raw"),
    [
        ("medians", False),
        ("rawSamples", True),
        ("maxPeakMiB", False),
        ("rawPeakMiB", True),
    ],
)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0])
def test_beta_benchmark_baseline_rejects_non_finite_or_negative_evidence(
    field: str, raw: bool, value: float
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    baseline = _complete_benchmark_baseline(module)
    case_value = baseline[field]["python"]["streamDeltas10k"]
    if raw:
        case_value[0] = value
    else:
        baseline[field]["python"]["streamDeltas10k"] = value
    current = module._baseline_fingerprint(baseline)

    with pytest.raises(RuntimeError, match="finite non-negative"):
        module._validate_baseline(baseline, current)


def test_beta_benchmark_baseline_rejects_mismatched_rss_aggregate() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    baseline = _complete_benchmark_baseline(module)
    baseline["maxPeakMiB"]["python"]["streamDeltas10k"] = 99.0
    current = module._baseline_fingerprint(baseline)

    with pytest.raises(RuntimeError, match="RSS aggregate"):
        module._validate_baseline(baseline, current)


def test_beta_benchmark_baseline_rejects_mismatched_duration_median() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    baseline = _complete_benchmark_baseline(module)
    baseline["medians"]["python"]["streamDeltas10k"] = 9.0
    current = module._baseline_fingerprint(baseline)

    with pytest.raises(RuntimeError, match="duration median"):
        module._validate_baseline(baseline, current)


def test_beta_benchmark_semantic_validation_rejects_mismatched_aggregate() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    budgets = json.loads(module.BUDGETS_PATH.read_text())
    result = _complete_benchmark_results(module)["python"]["streamDeltas10k"]
    result["medianMs"] = 2.0

    with pytest.raises(RuntimeError, match="does not match sample median"):
        module._case_failures(
            "python", "streamDeltas10k", result, budgets, include_timing=False
        )


def test_beta_benchmark_candidate_rejects_mismatched_aggregate() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    results = _complete_benchmark_results(module)
    results["python"]["streamDeltas10k"]["maxPeakMiB"] = 94.0

    with pytest.raises(RuntimeError, match="does not match sample maximum"):
        module._candidate_baseline(results, {})


def test_beta_benchmark_regression_rejects_mismatched_aggregate() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    baseline = _complete_benchmark_baseline(module)
    results = _complete_benchmark_results(module)
    results["python"]["streamDeltas10k"]["medianMs"] = 2.0

    with pytest.raises(RuntimeError, match="does not match sample median"):
        module._regression_failures(results, baseline, 20.0)


def test_beta_benchmark_full_regression_checks_duration_and_rss() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    baseline = _complete_benchmark_baseline(module)
    results = _complete_benchmark_results(module)
    results["python"]["streamDeltas10k"]["sampleResults"][-1]["peakMiB"] = 121.0
    results["python"]["streamDeltas10k"]["maxPeakMiB"] = 121.0

    failures = module._regression_failures(results, baseline, 20.0)

    assert any(
        "streamDeltas10k" in failure and "peak RSS" in failure for failure in failures
    )


def test_beta_benchmark_candidate_records_five_rss_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    results = _complete_benchmark_results(module)
    monkeypatch.setattr(module, "_commit", lambda: "commit")

    candidate = module._candidate_baseline(results, {})

    assert candidate["maxPeakMiB"]["python"]["context10kIterations5"] == 95.0
    assert candidate["rawPeakMiB"]["typescript"]["toolArgDeltas10k"] == [
        91.0,
        92.0,
        93.0,
        94.0,
        95.0,
    ]


def test_root_package_pins_structural_and_benchmark_gates() -> None:
    package = ROOT_PACKAGE.read_text()
    for expected in [
        '"@ast-grep/cli": "0.44.1"',
        '"ast-grep:test": "sg test -t tools/ast-grep/rule-tests --skip-snapshot-tests"',
        '"ast-grep:scan": "sg scan --config sgconfig.yml kaji"',
        '"audit:ast-grep": "bun run ast-grep:test && bun run ast-grep:scan"',
        '"benchmark:kaji-beta": "uv run --project kaji/sdk python kaji/scripts/run_beta_benchmarks.py --quick"',
        '"benchmark:kaji-beta:full": "uv run --project kaji/sdk python kaji/scripts/run_beta_benchmarks.py --full"',
        '"soak:kaji-beta": "uv run --project kaji/sdk python kaji/scripts/run_beta_soak.py --minutes 30"',
    ]:
        assert expected in package


def test_root_bun_lock_is_present_and_not_ignored() -> None:
    assert ROOT_LOCK.is_file()
    assert '"@ast-grep/cli": "0.44.1"' in ROOT_LOCK.read_text()

    ignore_lines = ROOT_GITIGNORE.read_text().splitlines()
    assert "!bun.lock" in ignore_lines
    assert ignore_lines.index("!bun.lock") > ignore_lines.index("bun.lock")


def test_beta_structural_audit_rule_and_fixture_ids_match() -> None:
    def ids_by_path(directory: Path) -> dict[str, Path]:
        result: dict[str, Path] = {}
        for path in sorted(directory.glob("*.yml")):
            matches = re.findall(r"(?m)^id:\s*([a-z0-9-]+)\s*$", path.read_text())
            assert len(matches) == 1, f"{path} must declare exactly one rule id"
            rule_id = matches[0]
            assert rule_id not in result, f"duplicate ast-grep id: {rule_id}"
            result[rule_id] = path
        return result

    rules = ids_by_path(RULE_DIR)
    fixtures = ids_by_path(RULE_TEST_DIR)

    assert rules
    assert set(rules) == set(fixtures)
    for rule_id, fixture in fixtures.items():
        assert fixture.name == f"{rule_id}-test.yml"

    assert "tools/ast-grep/rules" in SGCONFIG.read_text()


def test_ast_grep_is_mandatory_in_ci() -> None:
    workflow = AST_GREP_WORKFLOW.read_text()
    assert "bun-version: 1.3.11" in workflow
    assert "install-args: --frozen-lockfile" in workflow
    assert "test result: ok." not in workflow
    assert "AST_GREP_OUTPUT" not in workflow
    assert "| tee" not in workflow
    assert "grep -q" not in workflow
    assert workflow.index("bun run ast-grep:test") < workflow.index(
        "bun run ast-grep:scan"
    )

    benchmark_workflow = (
        REPO_ROOT / ".github" / "workflows" / "kaji.benchmark.yml"
    ).read_text()
    assert benchmark_workflow.count("install-args: --frozen-lockfile") == 3


def test_release_docs_reference_beta_release_check() -> None:
    combined = "\n".join(
        [
            (REPO_ROOT / "kaji" / "RELEASE_MATRIX.md").read_text(),
            (REPO_ROOT / "kaji" / "sdk" / "README.md").read_text(),
            (REPO_ROOT / "kaji" / "ts" / "README.md").read_text(),
            (REPO_ROOT / "docs" / "MVP.md").read_text(),
        ]
    )

    assert (
        "uv run --project kaji/sdk python kaji/scripts/beta_release_check.py"
        in combined
    )
    assert "KAJI_RUN_KEYED_LIVE=1" in combined
    assert "SDK/service boundary" in combined
    assert "TypeScript optional provider imports" in combined
