from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "kaji" / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "integration_benchmark", SCRIPTS / "integration_benchmark.py"
)
assert SPEC is not None and SPEC.loader is not None
integration_benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(integration_benchmark)


def budgets() -> dict[str, Any]:
    return integration_benchmark.load_budgets()


def semantics(case: str, values: dict[str, Any]) -> dict[str, int]:
    if case == "fixedOriginPreflight":
        return {
            "safeRequests": 1,
            "hostileRequests": 0,
            "rejected": 1,
            "responseBytes": values["responseBytes"],
        }
    if case == "fixedOriginCapRejection":
        return {
            "requests": 1,
            "rejected": 1,
            "closed": 1,
            "limitBytes": values["limitBytes"],
            "observedBytes": values["limitBytes"] + values["overflowBytes"],
        }
    if case == "githubDtoMaxBounds":
        return {
            "rows": values["rowCount"],
            "titleCharacters": values["titleCharacters"],
            "bodyPreviewBytes": values["bodyBytes"],
            "serializedBytes": 26_762,
        }
    if case == "keychainRecordParse":
        return {
            "records": 1,
            "processCalls": 1,
            "recordBytes": 15_157,
            "scopes": 1,
        }
    return {
        "waiters": values["waiters"],
        "httpCalls": 1,
        "saveCalls": 1,
        "uniqueTokens": 1,
    }


def complete_results(sample: float = 1.0) -> list[dict[str, Any]]:
    document = budgets()
    results: list[dict[str, Any]] = []
    for case in document["cases"]:
        for runtime in document["runtimes"]:
            results.append(
                {
                    "schemaVersion": 1,
                    "runtime": runtime,
                    "case": case["name"],
                    "inputSha256": integration_benchmark.input_digest(case["input"]),
                    "warmups": 20,
                    "batches": [[sample] * 200 for _ in range(3)],
                    "semantics": semantics(case["name"], case["input"]),
                }
            )
    return results


def test_budget_contract_is_closed_and_records_the_gmail_hold() -> None:
    document = budgets()

    assert [case["name"] for case in document["cases"]] == list(
        integration_benchmark.CASE_NAMES
    )
    assert "gmailMimeMaxBounds" not in integration_benchmark.CASE_NAMES
    assert document["deviations"] == [
        {
            "case": "gmailMimeMaxBounds",
            "status": "hold",
            "reasonCode": "GMAIL_RUNTIME_NOT_IN_REVIEWED_CHECKPOINT",
            "ownerTask": 8,
            "included": False,
        }
    ]
    assert document["modes"]["full"] == {
        "warmups": 20,
        "batches": 3,
        "samplesPerBatch": 200,
        "enforceTiming": True,
        "requiresProtectedRunner": False,
    }


def test_budget_contract_rejects_unknown_fields(tmp_path: Path) -> None:
    document = budgets()
    document["unknown"] = True
    path = tmp_path / "budgets.json"
    path.write_text(json.dumps(document))

    with pytest.raises(integration_benchmark.BenchmarkError, match="closed object"):
        integration_benchmark.load_budgets(path)


@pytest.mark.parametrize("mutation", ["budget", "input"])
def test_budget_contract_rejects_weakened_workload(
    tmp_path: Path, mutation: str
) -> None:
    document = budgets()
    if mutation == "budget":
        document["cases"][0]["p99Ms"]["python"] = 500
    else:
        document["cases"][2]["input"]["rowCount"] = 1
    path = tmp_path / "budgets.json"
    path.write_text(json.dumps(document))

    with pytest.raises(integration_benchmark.BenchmarkError, match="changed"):
        integration_benchmark.load_budgets(path)


def test_nearest_rank_uses_ceil_rank_per_batch() -> None:
    samples = list(map(float, range(200)))

    assert integration_benchmark.nearest_rank(samples, 0.50) == 99
    assert integration_benchmark.nearest_rank(samples, 0.95) == 189
    assert integration_benchmark.nearest_rank(samples, 0.99) == 197
    assert integration_benchmark.nearest_rank(samples, 1.0) == 199


@pytest.mark.parametrize("value", [True, -1, math.inf, math.nan])
def test_estimator_rejects_non_samples(value: object) -> None:
    with pytest.raises(integration_benchmark.BenchmarkError):
        integration_benchmark.nearest_rank([value], 0.99)  # type: ignore[list-item]


def test_noise_fails_only_above_both_thresholds() -> None:
    assert not integration_benchmark.noisy_p99(
        [10.0, 10.0, 12.0], relative=0.25, absolute_ms=2.0
    )
    assert not integration_benchmark.noisy_p99(
        [10.0, 10.0, 12.5], relative=0.25, absolute_ms=2.0
    )
    assert integration_benchmark.noisy_p99(
        [10.0, 10.0, 12.5001], relative=0.25, absolute_ms=2.0
    )


def test_full_estimator_rejects_any_failing_batch() -> None:
    results = complete_results()
    results[0]["batches"][1] = [6.0] * 200

    with pytest.raises(integration_benchmark.BenchmarkError, match="exceeded its p99"):
        integration_benchmark.summarize_results(results, budgets(), "full")


def test_raw_digest_verification_is_fail_closed() -> None:
    raw = b'{"samples":[1]}'
    digest = hashlib.sha256(raw).hexdigest()

    integration_benchmark.verify_raw_digest(raw, digest)
    with pytest.raises(integration_benchmark.BenchmarkError, match="digest mismatch"):
        integration_benchmark.verify_raw_digest(raw + b" ", digest)


def test_json_decoder_rejects_duplicates_and_non_finite_numbers() -> None:
    with pytest.raises(integration_benchmark.BenchmarkError, match="duplicate"):
        integration_benchmark.decode_json('{"sample":1,"sample":2}')
    with pytest.raises(integration_benchmark.BenchmarkError, match="non-finite"):
        integration_benchmark.decode_json('{"sample":NaN}')


def test_calibration_requires_flag_and_github_hosted_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KAJI_BENCHMARK_CALIBRATION", raising=False)
    with pytest.raises(integration_benchmark.BenchmarkError, match="CALIBRATION"):
        integration_benchmark.require_protected_calibration()

    expected = {
        "environment": "github-hosted",
        "os": "Darwin",
        "arch": "arm64",
        "platformVersion": "15.7.7",
        "imageOS": "macos15",
        "imageLabel": "macos-15-arm64",
        "imageVersion": "20260715.0234.1",
        "imageDataSha256": "a" * 64,
    }
    monkeypatch.setenv("KAJI_BENCHMARK_CALIBRATION", "1")
    monkeypatch.setattr(
        integration_benchmark,
        "require_github_hosted_macos_arm64",
        lambda **kwargs: expected,
    )

    assert integration_benchmark.require_protected_calibration() == expected


def test_integration_source_digest_includes_platform_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    budget_bytes = b'{"schemaVersion":1}'
    provenance = tmp_path / "benchmark_platform.py"
    provenance.write_text("first\n")
    monkeypatch.setattr(integration_benchmark, "BENCHMARK_PLATFORM", provenance)
    first = integration_benchmark.source_digest(budget_bytes)

    provenance.write_text("second\n")

    assert integration_benchmark.source_digest(budget_bytes) != first


def test_quick_orchestrator_runs_both_runtimes_and_binds_raw_artifact(
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "raw.json"
    summary_path = tmp_path / "summary.json"

    summary = integration_benchmark.run_orchestrator(
        mode="quick",
        budgets_path=integration_benchmark.DEFAULT_BUDGETS,
        raw_output=raw_path,
        summary_output=summary_path,
    )

    assert len(summary["results"]) == 10
    assert {row["runtime"] for row in summary["results"]} == {
        "python",
        "typescript",
    }
    assert summary["deviations"][0]["case"] == "gmailMimeMaxBounds"
    assert (
        hashlib.sha256(raw_path.read_bytes()).hexdigest() == summary["rawSamplesSha256"]
    )
    assert json.loads(summary_path.read_text()) == summary
    assert len(summary_path.read_bytes()) <= 32 * 1024
