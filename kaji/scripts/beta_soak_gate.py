#!/usr/bin/env python3
"""Combine and validate Python and TypeScript soak artifacts."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics
from typing import Any

from beta_benchmark_gate import COMMIT_PATTERN, HASH_PATTERN, performance_provenance


ROOT = Path(__file__).resolve().parents[2]
BUDGETS = json.loads((ROOT / "kaji" / "benchmarks" / "beta-budgets.json").read_text())[
    "soak"
]
EXPECTED_ARTIFACTS = {
    "python": "kaji-0.2.0b1-py3-none-any.whl",
    "typescript": "kaji-sdk-0.2.0-beta.1.tgz",
}


def _load(path: Path, runtime: str) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return None, [f"{runtime} soak artifact is unreadable: {error}"]
    required = {
        "schemaVersion",
        "runtime",
        "resolvedPackage",
        "requestedMinutes",
        "elapsedSeconds",
        "minimumTurns",
        "attemptedTurns",
        "completedTurns",
        "failedTurns",
        "lateWindowHeapGrowthPercent",
        "lateWindowRssGrowthPercent",
        "lateWindowRssGrowthMiB",
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


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _memory_summary(
    value: dict[str, Any], runtime: str
) -> tuple[dict[str, float] | None, list[str]]:
    samples = value.get("memorySamples")
    if not isinstance(samples, list):
        return None, [f"{runtime} soak memory samples are not an array"]
    heap_field = "heapMiB" if runtime == "python" else "heapUsedMiB"
    buckets: dict[int, tuple[float, float]] = {}
    failures: list[str] = []
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            failures.append(
                f"{runtime} soak memory samples contain a non-object at index {index}"
            )
            continue
        minute = _finite_number(sample.get("minute"))
        heap_mib = _finite_number(sample.get(heap_field))
        rss_mib = _finite_number(sample.get("rssMiB"))
        if minute is None or heap_mib is None or rss_mib is None:
            failures.append(
                f"{runtime} soak memory samples contain missing or non-finite values"
            )
            continue
        if 21 <= minute < 31:
            bucket = math.floor(minute)
            if bucket in buckets:
                failures.append(
                    f"{runtime} soak memory samples duplicate minute {bucket}"
                )
            else:
                buckets[bucket] = (heap_mib, rss_mib)
    missing = sorted(set(range(21, 31)) - buckets.keys())
    if missing:
        failures.append(
            f"{runtime} soak memory samples are missing late-window minutes: "
            + ", ".join(str(minute) for minute in missing)
        )
    if failures:
        return None, failures

    prior_heap = statistics.median(buckets[minute][0] for minute in range(21, 26))
    late_heap = statistics.median(buckets[minute][0] for minute in range(26, 31))
    prior_rss = statistics.median(buckets[minute][1] for minute in range(21, 26))
    late_rss = statistics.median(buckets[minute][1] for minute in range(26, 31))
    if prior_heap <= 0 or prior_rss <= 0:
        return None, [f"{runtime} soak memory samples have a non-positive baseline"]
    heap_growth_mib = late_heap - prior_heap
    rss_growth_mib = late_rss - prior_rss
    return (
        {
            "heapGrowthPercent": heap_growth_mib / prior_heap * 100,
            "rssGrowthPercent": rss_growth_mib / prior_rss * 100,
            "rssGrowthMiB": rss_growth_mib,
            "priorRssMiB": prior_rss,
        },
        [],
    )


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
    summary, memory_failures = _memory_summary(value, runtime)
    failures.extend(memory_failures)
    if summary is not None:
        reported_fields = {
            "lateWindowHeapGrowthPercent": summary["heapGrowthPercent"],
            "lateWindowRssGrowthPercent": summary["rssGrowthPercent"],
            "lateWindowRssGrowthMiB": summary["rssGrowthMiB"],
        }
        for field, expected in reported_fields.items():
            reported = _finite_number(value.get(field))
            if reported is None or not math.isclose(
                reported, expected, rel_tol=1e-9, abs_tol=1e-9
            ):
                failures.append(
                    f"{runtime} soak memory summary {field} does not match samples"
                )
        if summary["heapGrowthPercent"] > BUDGETS["maxLateWindowHeapGrowthPercent"]:
            failures.append(
                f"{runtime} soak late-window heap growth "
                f"{summary['heapGrowthPercent']!r} exceeds "
                f"{BUDGETS['maxLateWindowHeapGrowthPercent']}%"
            )
        rss_growth_limit_mib = max(
            float(BUDGETS["maxLateWindowRssGrowthMiB"]),
            summary["priorRssMiB"]
            * float(BUDGETS["maxLateWindowRssGrowthPercent"])
            / 100,
        )
        if summary["rssGrowthMiB"] > rss_growth_limit_mib:
            failures.append(
                f"{runtime} soak late-window RSS growth "
                f"{summary['rssGrowthMiB']!r} MiB exceeds "
                f"{rss_growth_limit_mib!r} MiB"
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
    parser.add_argument("--runtime-identity", type=Path)
    return parser.parse_args()


def _load_identity(path: Path | None) -> tuple[dict[str, Any], list[str]]:
    empty = {
        "releaseManifestSha256": None,
        "artifacts": {},
        "resolvedPackages": {},
        "typescriptConsumerLock": {
            "templateSha256": None,
            "renderedSha256": None,
        },
    }
    if path is None:
        return empty, ["protected soak is missing installed runtime identity"]
    try:
        identity = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return empty, [f"installed runtime identity is unreadable: {error}"]
    if not isinstance(identity, dict):
        return empty, ["installed runtime identity is not an object"]
    failures: list[str] = []
    commit = identity.get("commit")
    manifest = identity.get("releaseManifestSha256")
    artifacts = identity.get("artifacts")
    resolved = identity.get("resolvedPackages")
    consumer_lock = identity.get("typescriptConsumerLock")
    if not isinstance(commit, str) or COMMIT_PATTERN.fullmatch(commit) is None:
        failures.append("installed runtime identity has an invalid commit")
    if not isinstance(manifest, str) or HASH_PATTERN.fullmatch(manifest) is None:
        failures.append("installed runtime identity has an invalid manifest hash")
    if not isinstance(artifacts, dict) or set(artifacts) != {"python", "typescript"}:
        failures.append("installed runtime identity has invalid artifacts")
    else:
        for runtime in ("python", "typescript"):
            value = artifacts[runtime]
            if (
                not isinstance(value, dict)
                or set(value) != {"file", "sha256"}
                or value["file"] != EXPECTED_ARTIFACTS[runtime]
                or not isinstance(value["sha256"], str)
                or HASH_PATTERN.fullmatch(value["sha256"]) is None
            ):
                failures.append(
                    f"installed runtime identity has invalid {runtime} artifact"
                )
    if (
        not isinstance(resolved, dict)
        or set(resolved) != {"python", "typescript"}
        or any(
            not isinstance(resolved.get(runtime), str)
            or not Path(resolved[runtime]).is_absolute()
            for runtime in resolved
        )
    ):
        failures.append("installed runtime identity has invalid package paths")
    if (
        not isinstance(consumer_lock, dict)
        or set(consumer_lock) != {"templateSha256", "renderedSha256"}
        or any(
            not isinstance(consumer_lock.get(name), str)
            or HASH_PATTERN.fullmatch(consumer_lock[name]) is None
            for name in ("templateSha256", "renderedSha256")
        )
    ):
        failures.append("installed runtime identity has invalid consumer lock hashes")
    return (
        {
            "releaseManifestSha256": manifest,
            "artifacts": artifacts if isinstance(artifacts, dict) else {},
            "resolvedPackages": resolved if isinstance(resolved, dict) else {},
            "typescriptConsumerLock": (
                consumer_lock if isinstance(consumer_lock, dict) else {}
            ),
            "identityCommit": commit,
        },
        failures,
    )


def main() -> int:
    args = _parse_args()
    provenance = performance_provenance(protected=getattr(args, "protected", False))
    failures: list[str] = []
    results: dict[str, Any] = {}
    identity: dict[str, Any] = {}
    if getattr(args, "protected", False):
        identity, identity_failures = _load_identity(
            getattr(args, "runtime_identity", None)
        )
        failures.extend(identity_failures)
        if identity.get("identityCommit") != provenance["commit"]:
            failures.append("installed runtime commit differs from soak provenance")
    for runtime, path in (("python", args.python), ("typescript", args.typescript)):
        value, load_failures = _load(path, runtime)
        failures.extend(load_failures)
        if value is not None:
            results[runtime] = value
            if not load_failures:
                failures.extend(_failures(value, runtime, args.minutes))
                expected_package = identity.get("resolvedPackages", {}).get(runtime)
                if (
                    getattr(args, "protected", False)
                    and value.get("resolvedPackage") != expected_package
                ):
                    failures.append(
                        f"{runtime} soak resolved a different installed package"
                    )
    identity.pop("identityCommit", None)
    report = {
        "schemaVersion": 1,
        **provenance,
        **identity,
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
