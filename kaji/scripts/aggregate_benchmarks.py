#!/usr/bin/env python3
"""Aggregate exactly three protected Kaji paired benchmark replicas."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parent))

from paired_benchmark import (
    CASES,
    RUNTIMES,
    THRESHOLD,
    _json_sha256,
    _load_json,
    _validate_replica_report,
    _write,
)


def _verdict(ratios: list[float]) -> str:
    if all(ratio <= THRESHOLD for ratio in ratios):
        return "pass"
    if all(ratio > THRESHOLD for ratio in ratios):
        return "regression"
    return "inconclusive"


def _aggregate_case(
    reports: list[dict[str, Any]], runtime: str, case: str
) -> dict[str, Any]:
    duration_ratios = [
        report["cases"][runtime][case]["durationRatio"] for report in reports
    ]
    rss_ratios = [report["cases"][runtime][case]["maxRssRatio"] for report in reports]
    duration_verdict = _verdict(duration_ratios)
    rss_verdict = _verdict(rss_ratios)
    verdict = (
        "regression"
        if "regression" in (duration_verdict, rss_verdict)
        else "inconclusive"
        if "inconclusive" in (duration_verdict, rss_verdict)
        else "pass"
    )
    return {
        "durationRatios": duration_ratios,
        "rssRatios": rss_ratios,
        "durationVerdict": duration_verdict,
        "rssVerdict": rss_verdict,
        "verdict": verdict,
    }


def _aggregate(reports: list[dict[str, Any]]) -> dict[str, Any]:
    if len(reports) != 3:
        raise RuntimeError(
            "paired benchmark aggregation requires exactly three reports"
        )
    validated = [_validate_replica_report(report) for report in reports]
    by_replica = {report["replica"]: report for report in validated}
    if set(by_replica) != {1, 2, 3} or len(by_replica) != len(validated):
        raise RuntimeError("paired benchmark reports must be replicas 1, 2, and 3")
    ordered = [by_replica[replica] for replica in (1, 2, 3)]
    first = ordered[0]
    for report in ordered[1:]:
        for field in (
            "protocolHash",
            "threshold",
            "referenceRecordSha256",
            "reference",
            "candidate",
            "referenceReceiptSha256",
            "candidateReceiptSha256",
        ):
            if report[field] != first[field]:
                raise RuntimeError(f"paired benchmark reports disagree on {field}")
        for field in ("versions", "dependencyLockHash"):
            if report["runnerEvidence"][field] != first["runnerEvidence"][field]:
                raise RuntimeError(
                    f"paired benchmark runner evidence disagrees on {field}"
                )
        for field in ("runId", "runAttempt", "job", "workflowRef", "workflowSha"):
            if (
                report["runnerEvidence"]["invocation"][field]
                != first["runnerEvidence"]["invocation"][field]
            ):
                raise RuntimeError(
                    f"paired benchmark invocation evidence disagrees on {field}"
                )
    failures: list[str] = []
    cases: dict[str, dict[str, Any]] = {runtime: {} for runtime in RUNTIMES}
    for runtime in RUNTIMES:
        for case in CASES:
            evidence = _aggregate_case(ordered, runtime, case)
            if evidence["verdict"] != "pass":
                failures.append(
                    f"{runtime} {case} paired benchmark verdict is "
                    f"{evidence['verdict']}"
                )
            cases[runtime][case] = evidence

    result: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "kaji-paired-benchmark-aggregate",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "protocolHash": first["protocolHash"],
        "threshold": THRESHOLD,
        "referenceRecordSha256": first["referenceRecordSha256"],
        "reference": first["reference"],
        "candidate": first["candidate"],
        "referenceReceiptSha256": first["referenceReceiptSha256"],
        "candidateReceiptSha256": first["candidateReceiptSha256"],
        "replicas": {
            str(report["replica"]): {
                "reportReceiptSha256": report["reportReceiptSha256"],
                "runnerEvidence": report["runnerEvidence"],
            }
            for report in ordered
        },
        "cases": cases,
        "failures": failures,
        "passed": not failures,
    }
    result["reportReceiptSha256"] = _json_sha256(result)
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--replica-report",
        action="append",
        required=True,
        type=Path,
        help="Repeat exactly three times, once for each replica report.",
    )
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        reports = [_load_json(path) for path in args.replica_report]
        result = _aggregate(reports)
        _write(args.output, result)
    except (OSError, RuntimeError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    for failure in result["failures"]:
        print(f"FAIL: {failure}", file=sys.stderr)
    if not result["passed"]:
        return 1
    print("PASS: three paired benchmark replicas unanimously pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
