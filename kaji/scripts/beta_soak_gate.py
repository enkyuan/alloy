#!/usr/bin/env python3
"""Combine and validate Python and TypeScript soak artifacts."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from beta_benchmark_gate import COMMIT_PATTERN, HASH_PATTERN, performance_provenance


ROOT = Path(__file__).resolve().parents[2]
BUDGETS = json.loads((ROOT / "kaji" / "benchmarks" / "beta-budgets.json").read_text())[
    "soak"
]
EXPECTED_ARTIFACTS = {
    "python": "kaji_sdk-0.2.0b1-py3-none-any.whl",
    "typescript": "kaji-sdk-0.2.0-beta.6.tgz",
}


def _load(path: Path, runtime: str) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None, [f"{runtime} soak artifact is unreadable"]
    if not isinstance(value, dict):
        return None, [f"{runtime} soak artifact is not an object"]
    required = {
        "schemaVersion",
        "runtime",
        "resolvedPackage",
        "seed",
        "offline",
        "requestedMinutes",
        "elapsedSeconds",
        "attemptedTurns",
        "completedTurns",
        "failedTurns",
        "terminalOutcomes",
        "memorySamples",
        "provider",
        "internal",
    }
    missing = sorted(required - value.keys())
    if missing:
        return None, [f"{runtime} soak artifact is missing: {', '.join(missing)}"]
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 2:
        return None, [f"{runtime} soak artifact has the wrong schema identity"]
    if value["runtime"] != runtime:
        return None, [f"{runtime} soak artifact has the wrong schema identity"]
    if type(value["seed"]) is not int or value["seed"] != 13:
        return None, [f"{runtime} soak artifact is not the fixed offline workload"]
    if value["offline"] is not True:
        return None, [f"{runtime} soak artifact is not the fixed offline workload"]
    return _sanitize_result(value, runtime), []


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _safe_number(value: Any) -> int | float | None:
    number = _finite_number(value)
    if number is None or number < 0:
        return None
    return value


def _safe_counts(value: Any, names: tuple[str, ...]) -> dict[str, int | None]:
    source = value if isinstance(value, dict) else {}
    return {name: _count(source.get(name)) for name in names}


def _sanitize_result(value: dict[str, Any], runtime: str) -> dict[str, Any]:
    memory_fields = (
        ("minute", "heapMiB", "rssMiB")
        if runtime == "python"
        else (
            "minute",
            "elapsedMs",
            "heapUsedMiB",
            "heapTotalMiB",
            "rssMiB",
            "maxRssMiB",
        )
    )
    samples = value.get("memorySamples")
    safe_samples: list[dict[str, int | float | None] | None] = []
    if isinstance(samples, list):
        for sample in samples:
            safe_samples.append(
                (
                    {name: _safe_number(sample.get(name)) for name in memory_fields}
                    if isinstance(sample, dict)
                    else None
                )
            )

    provider_names = (
        "calls",
        "active",
        "maxActive",
        "maxMessages",
        "maxCharacters",
        "multiToolBatches",
        "chargeRequests",
        "approvalBridgeRequests",
    )
    internal_names = (
        "coordinatorEntries",
        "coordinatorWaiters",
        "stuckToolCalls",
        "maxToolActive",
        "maxSubscriberQueueDepth",
        "subscriberOverflows",
        "projectionCacheSize",
        "projectionCacheLimit",
        "ledgerSize",
        "ledgerPeakSize",
        "ledgerLimit",
        "releasedLedgerEntries",
        "subscriberCount",
        "metricSubscriberOverflows",
        "subscriberResumes",
        "maxContextMessages",
        "maxContextCharacters",
    )
    internal_source = value.get("internal")
    internal_source = internal_source if isinstance(internal_source, dict) else {}
    internal: dict[str, Any] = _safe_counts(internal_source, internal_names)
    internal["ledgerCounts"] = _safe_counts(
        internal_source.get("ledgerCounts"),
        ("running", "completed", "unknown"),
    )
    internal["scenarios"] = _safe_counts(
        internal_source.get("scenarios"),
        (
            "sameSessionTurns",
            "crossSessionTurns",
            "toolCallsRequested",
            "approvals",
            "cancellations",
            "cooperativeTimeouts",
            "nonCooperativeTimeouts",
            "sessionClosures",
        ),
    )
    gc_available = internal_source.get("gcAvailable")
    internal["gcAvailable"] = gc_available if isinstance(gc_available, bool) else None

    resolved_package = value.get("resolvedPackage")
    return {
        "schemaVersion": 2,
        "runtime": runtime,
        "resolvedPackage": (
            resolved_package if isinstance(resolved_package, str) else None
        ),
        "seed": _count(value.get("seed")),
        "offline": value.get("offline")
        if isinstance(value.get("offline"), bool)
        else None,
        "requestedMinutes": _safe_number(value.get("requestedMinutes")),
        "elapsedSeconds": _safe_number(value.get("elapsedSeconds")),
        "attemptedTurns": _count(value.get("attemptedTurns")),
        "completedTurns": _count(value.get("completedTurns")),
        "failedTurns": _count(value.get("failedTurns")),
        "throughputTurnsPerSecond": _safe_number(value.get("throughputTurnsPerSecond")),
        "cooperativeTimeouts": _count(value.get("cooperativeTimeouts")),
        "noncooperativeTimeouts": _count(value.get("noncooperativeTimeouts")),
        "terminalOutcomes": _safe_counts(
            value.get("terminalOutcomes"),
            ("completed", "failed", "cancelled"),
        ),
        "memorySamples": safe_samples if isinstance(samples, list) else None,
        "provider": _safe_counts(value.get("provider"), provider_names),
        "internal": internal,
    }


def _memory_summary(
    value: dict[str, Any], runtime: str
) -> tuple[dict[str, float] | None, list[str]]:
    samples = value.get("memorySamples")
    if not isinstance(samples, list):
        return None, [f"{runtime} soak memory samples are not an array"]
    memory_fields = (
        ("minute", "heapMiB", "rssMiB")
        if runtime == "python"
        else (
            "minute",
            "elapsedMs",
            "heapUsedMiB",
            "heapTotalMiB",
            "rssMiB",
            "maxRssMiB",
        )
    )
    heap_field = memory_fields[1] if runtime == "python" else memory_fields[2]
    buckets: dict[int, tuple[float, float]] = {}
    observed_buckets: set[int] = set()
    failures: list[str] = []
    elapsed_seconds = _finite_number(value.get("elapsedSeconds"))
    prior_minute: float | None = None
    for sample in samples:
        if not isinstance(sample, dict):
            failures.append(f"{runtime} soak memory samples contain a non-object")
            continue
        measured = {name: _finite_number(sample.get(name)) for name in memory_fields}
        if any(number is None or number < 0 for number in measured.values()):
            failures.append(f"{runtime} soak memory samples contain invalid values")
            continue
        minute = measured["minute"]
        heap_mib = measured[heap_field]
        rss_mib = measured["rssMiB"]
        assert minute is not None and heap_mib is not None and rss_mib is not None
        if prior_minute is not None and minute <= prior_minute:
            failures.append(f"{runtime} soak memory sample times are not increasing")
        prior_minute = minute
        bucket = math.floor(minute)
        if bucket in observed_buckets:
            failures.append(f"{runtime} soak memory samples duplicate minute {bucket}")
        else:
            observed_buckets.add(bucket)
        if elapsed_seconds is None or minute * 60 > elapsed_seconds + 0.001:
            failures.append(
                f"{runtime} soak memory sample exceeds reported elapsed time"
            )
        if runtime == "typescript":
            sample_elapsed_ms = measured["elapsedMs"]
            assert sample_elapsed_ms is not None
            if not math.isclose(
                sample_elapsed_ms,
                minute * 60_000,
                rel_tol=0,
                abs_tol=0.001,
            ):
                failures.append(
                    "typescript soak memory sample elapsed time does not match its minute"
                )
        if 21 <= minute < 31:
            if bucket in buckets:
                continue
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
    requested_minutes = _finite_number(value.get("requestedMinutes"))
    if requested_minutes != minutes:
        failures.append(f"{runtime} soak requested duration does not match the runner")
    required_minutes = max(float(BUDGETS["durationMinutes"]), minutes)
    if minutes < BUDGETS["durationMinutes"]:
        failures.append(
            f"{runtime} soak requested {minutes} minutes; protected minimum is "
            f"{BUDGETS['durationMinutes']}"
        )
    elapsed_seconds = _finite_number(value.get("elapsedSeconds"))
    if elapsed_seconds is None or elapsed_seconds < required_minutes * 60:
        failures.append(f"{runtime} soak ended before {required_minutes} minutes")
    attempted = _count(value.get("attemptedTurns"))
    completed = _count(value.get("completedTurns"))
    failed = _count(value.get("failedTurns"))
    if attempted is None or attempted < BUDGETS["minimumTurns"]:
        failures.append(f"{runtime} soak did not reach the minimum turn count")
    if (
        attempted is None
        or completed is None
        or failed is None
        or attempted != completed + failed
    ):
        failures.append(f"{runtime} soak turn accounting diverged")
    terminal = value.get("terminalOutcomes")
    terminal_counts = (
        {
            name: _count(terminal.get(name))
            for name in ("completed", "failed", "cancelled")
        }
        if isinstance(terminal, dict)
        else {}
    )
    terminal_completed = terminal_counts.get("completed")
    terminal_failed = terminal_counts.get("failed")
    terminal_cancelled = terminal_counts.get("cancelled")
    if (
        len(terminal_counts) != 3
        or any(count is None for count in terminal_counts.values())
        or terminal_completed != completed
        or (
            terminal_failed is not None
            and terminal_cancelled is not None
            and terminal_failed + terminal_cancelled != failed
        )
    ):
        failures.append(f"{runtime} soak terminal outcomes diverged")
    if terminal_failed is not None and terminal_failed != 0:
        failures.append(f"{runtime} soak recorded unexpected failed turns")
    if terminal_cancelled is None or terminal_cancelled < 1:
        failures.append(f"{runtime} soak did not exercise cancellation")
    summary, memory_failures = _memory_summary(value, runtime)
    failures.extend(memory_failures)
    if summary is not None:
        if summary["heapGrowthPercent"] > BUDGETS["maxLateWindowHeapGrowthPercent"]:
            failures.append(
                f"{runtime} soak late-window heap growth exceeds its budget"
            )
        rss_growth_limit_mib = max(
            float(BUDGETS["maxLateWindowRssGrowthMiB"]),
            summary["priorRssMiB"]
            * float(BUDGETS["maxLateWindowRssGrowthPercent"])
            / 100,
        )
        if summary["rssGrowthMiB"] > rss_growth_limit_mib:
            failures.append(f"{runtime} soak late-window RSS growth exceeds its budget")
    internal = value.get("internal")
    provider = value.get("provider")
    if not isinstance(internal, dict):
        return [*failures, f"{runtime} soak internal diagnostics are invalid"]
    if not isinstance(provider, dict):
        return [*failures, f"{runtime} soak provider diagnostics are invalid"]
    if (
        internal.get("coordinatorEntries") != 0
        or internal.get("coordinatorWaiters") != 0
    ):
        failures.append(f"{runtime} soak leaked coordinator state")
    if internal.get("stuckToolCalls") != 0:
        failures.append(f"{runtime} soak leaked tool handlers")
    max_tool_active = _count(internal.get("maxToolActive"))
    if max_tool_active is None or max_tool_active > 4:
        failures.append(f"{runtime} soak exceeded tool concurrency")
    max_subscriber_depth = _count(internal.get("maxSubscriberQueueDepth"))
    if max_subscriber_depth is None or max_subscriber_depth > 1_024:
        failures.append(f"{runtime} soak exceeded subscriber queue capacity")
    subscriber_overflows = _count(internal.get("subscriberOverflows"))
    if subscriber_overflows is None or subscriber_overflows < 1:
        failures.append(f"{runtime} soak did not exercise subscriber overflow")
    projection_size = _count(internal.get("projectionCacheSize"))
    projection_limit = _count(internal.get("projectionCacheLimit"))
    if projection_size is None or projection_limit is None:
        failures.append(f"{runtime} soak projection cache diagnostics are invalid")
    elif projection_size != 0:
        failures.append(f"{runtime} soak left projection cache entries")
    ledger_size = _count(internal.get("ledgerSize"))
    ledger_limit = _count(internal.get("ledgerLimit"))
    if ledger_size is not None and ledger_limit is not None:
        if ledger_size != 0:
            failures.append(f"{runtime} soak left ledger entries")
        ledger_peak = _count(internal.get("ledgerPeakSize"))
        if (
            ledger_peak is None
            or ledger_peak < ledger_size
            or ledger_peak > ledger_limit
        ):
            failures.append(f"{runtime} soak ledger peak exceeded capacity")
        counts = internal.get("ledgerCounts")
        count_names = {"running", "completed", "unknown"}
        if (
            not isinstance(counts, dict)
            or set(counts) != count_names
            or any(_count(counts.get(name)) is None for name in count_names)
            or sum(counts[name] for name in count_names) != ledger_size
            or any(counts[name] != 0 for name in count_names)
        ):
            failures.append(f"{runtime} soak ledger counts are invalid or inconsistent")
    else:
        failures.append(f"{runtime} soak did not report a measured ledger size")
    if _count(provider.get("active")) != 0:
        failures.append(f"{runtime} soak left provider requests active")
    if runtime == "python":
        if _count(internal.get("subscriberCount")) != 0:
            failures.append("python soak leaked a subscriber")
        if max_subscriber_depth != 1_024:
            failures.append("python soak did not reach subscriber queue capacity")
        metric_overflows = _count(internal.get("metricSubscriberOverflows"))
        if metric_overflows != subscriber_overflows:
            failures.append("python soak overflow diagnostics diverged")
        subscriber_resumes = _count(internal.get("subscriberResumes"))
        if subscriber_resumes != subscriber_overflows:
            failures.append("python soak subscriber resume count diverged")
        if _count(provider.get("multiToolBatches")) in (None, 0):
            failures.append("python soak did not exercise a multi-tool batch")
        if _count(provider.get("chargeRequests")) in (None, 0):
            failures.append("python soak did not exercise the approval tool")
        bridge_requests = provider.get("approvalBridgeRequests")
        if not isinstance(bridge_requests, int) or bridge_requests < 1:
            failures.append("python soak did not exercise the approval bridge")
        if _count(value.get("cooperativeTimeouts")) in (None, 0):
            failures.append("python soak did not exercise a cooperative timeout")
        if _count(value.get("noncooperativeTimeouts")) in (None, 0):
            failures.append("python soak did not exercise a non-cooperative timeout")
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
    else:
        scenarios = internal.get("scenarios")
        if not isinstance(scenarios, dict):
            failures.append("typescript soak scenario diagnostics are invalid")
        else:
            for name in (
                "toolCallsRequested",
                "approvals",
                "cancellations",
                "cooperativeTimeouts",
                "nonCooperativeTimeouts",
                "sessionClosures",
            ):
                if _count(scenarios.get(name)) in (None, 0):
                    failures.append(f"typescript soak did not exercise {name}")
    return failures


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", required=True, type=float)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--typescript", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--protected", action="store_true")
    parser.add_argument("--runtime-identity", type=Path)
    parser.add_argument("--runner-image-data", type=Path)
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
    except (OSError, json.JSONDecodeError):
        return empty, ["installed runtime identity is unreadable"]
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
    protected = getattr(args, "protected", False)
    runner_image_data = getattr(args, "runner_image_data", None)
    if protected and runner_image_data is None:
        raise RuntimeError("protected soak requires --runner-image-data")
    provenance = performance_provenance(
        protected=protected,
        image_data_path=runner_image_data,
    )
    failures: list[str] = []
    results: dict[str, Any] = {}
    identity: dict[str, Any] = {}
    if protected:
        identity, identity_failures = _load_identity(
            getattr(args, "runtime_identity", None)
        )
        failures.extend(identity_failures)
        if identity.get("identityCommit") != provenance["commit"]:
            failures.append("installed runtime commit differs from soak provenance")
    for runtime, path in (("python", args.python), ("typescript", args.typescript)):
        value, load_failures = _load(path, runtime)
        failures.extend(load_failures)
        if value is not None and not load_failures:
            failures.extend(_failures(value, runtime, args.minutes))
            expected_package = identity.get("resolvedPackages", {}).get(runtime)
            if protected and value.get("resolvedPackage") != expected_package:
                failures.append(
                    f"{runtime} soak resolved a different installed package"
                )
            results[runtime] = value
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
