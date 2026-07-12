#!/usr/bin/env python3
"""Combine and validate Python and TypeScript soak artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from beta_benchmark_gate import performance_provenance


ROOT = Path(__file__).resolve().parents[2]
BUDGETS = json.loads((ROOT / "kaji" / "benchmarks" / "beta-budgets.json").read_text())[
    "soak"
]


def _load(path: Path, runtime: str) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return None, [f"{runtime} soak artifact is unreadable: {error}"]
    required = {
        "schemaVersion",
        "runtime",
        "requestedMinutes",
        "elapsedSeconds",
        "minimumTurns",
        "attemptedTurns",
        "completedTurns",
        "failedTurns",
        "lateWindowHeapGrowthPercent",
        "memorySamples",
        "internal",
        "passed",
    }
    missing = sorted(required - value.keys())
    if missing:
        return value, [f"{runtime} soak artifact is missing: {', '.join(missing)}"]
    if value["schemaVersion"] != 1 or value["runtime"] != runtime:
        return value, [f"{runtime} soak artifact has the wrong schema identity"]
    return value, []


def _failures(value: dict[str, Any], runtime: str, minutes: float) -> list[str]:
    failures: list[str] = []
    if value["requestedMinutes"] != minutes:
        failures.append(f"{runtime} soak requested duration does not match the runner")
    required_minutes = max(float(BUDGETS["durationMinutes"]), minutes)
    if minutes < BUDGETS["durationMinutes"]:
        failures.append(
            f"{runtime} soak requested {minutes} minutes; protected minimum is "
            f"{BUDGETS['durationMinutes']}"
        )
    if value["elapsedSeconds"] < required_minutes * 60:
        failures.append(f"{runtime} soak ended before {required_minutes} minutes")
    if value["attemptedTurns"] < BUDGETS["minimumTurns"]:
        failures.append(
            f"{runtime} soak attempted {value['attemptedTurns']} turns; "
            f"minimum is {BUDGETS['minimumTurns']}"
        )
    growth = value["lateWindowHeapGrowthPercent"]
    if growth is None or growth > BUDGETS["maxLateWindowHeapGrowthPercent"]:
        failures.append(
            f"{runtime} soak late-window heap growth {growth!r} exceeds "
            f"{BUDGETS['maxLateWindowHeapGrowthPercent']}% or is unavailable"
        )
    internal = value["internal"]
    provider = value.get("provider", {})
    if (
        internal.get("coordinatorEntries") != 0
        or internal.get("coordinatorWaiters") != 0
    ):
        failures.append(f"{runtime} soak leaked coordinator state")
    if internal.get("stuckToolCalls") != 0:
        failures.append(f"{runtime} soak leaked tool handlers")
    if internal.get("maxSubscriberQueueDepth", 1_025) > 1_024:
        failures.append(f"{runtime} soak exceeded subscriber queue capacity")
    if internal.get("subscriberOverflows", 0) < 1:
        failures.append(f"{runtime} soak did not exercise subscriber overflow")
    if internal.get("projectionCacheSize", 1) > internal.get("projectionCacheLimit", 0):
        failures.append(f"{runtime} soak exceeded projection cache capacity")
    ledger_size = internal.get("ledgerSize")
    if isinstance(ledger_size, (int, float)):
        if ledger_size > internal.get("ledgerLimit", 0):
            failures.append(f"{runtime} soak exceeded ledger capacity")
        if internal.get("ledgerPeakSize", ledger_size) > internal.get("ledgerLimit", 0):
            failures.append(f"{runtime} soak ledger peak exceeded capacity")
        counts = internal.get("ledgerCounts")
        if isinstance(counts, dict) and counts.get("running") != 0:
            failures.append(f"{runtime} soak left running ledger entries")
    else:
        failures.append(f"{runtime} soak did not report a measured ledger size")
    if runtime == "python":
        bridge_requests = provider.get("approvalBridgeRequests")
        if not isinstance(bridge_requests, int) or bridge_requests < 1:
            failures.append("python soak did not exercise the approval bridge")
        provider_messages = provider.get("maxMessages")
        provider_characters = provider.get("maxCharacters")
        metric_messages = internal.get("maxContextMessages")
        metric_characters = internal.get("maxContextCharacters")
        if (
            not isinstance(provider_messages, int)
            or provider_messages < 1
            or provider_messages != metric_messages
        ):
            failures.append("python soak provider/context message diagnostics diverged")
        if (
            not isinstance(provider_characters, int)
            or not isinstance(metric_characters, int)
            or provider_characters > 100_000
            or metric_characters > 100_000
            or provider_characters > metric_characters
        ):
            failures.append(
                "python soak exceeded or misreported the context character bound"
            )
    if not value["passed"]:
        failures.append(f"{runtime} soak program reported failure")
    return failures


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", required=True, type=float)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--typescript", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--protected", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    provenance = performance_provenance(protected=getattr(args, "protected", False))
    failures: list[str] = []
    results: dict[str, Any] = {}
    for runtime, path in (("python", args.python), ("typescript", args.typescript)):
        value, load_failures = _load(path, runtime)
        failures.extend(load_failures)
        if value is not None:
            results[runtime] = value
            if not load_failures:
                failures.extend(_failures(value, runtime, args.minutes))
    report = {
        "schemaVersion": 1,
        **provenance,
        "requestedMinutes": args.minutes,
        "budgets": BUDGETS,
        "results": results,
        "failures": failures,
        "passed": not failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
