#!/usr/bin/env python3
"""No-network cross-runtime integration microbenchmark and estimator."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import statistics
import sys
import tempfile
import time
from typing import Any, NoReturn, cast

from process_runner import (
    BENCHMARK_COMMAND_BUDGET,
    METADATA_BUDGET,
    CommandError,
    run_checked,
)


KAJI_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = KAJI_ROOT.parent
DEFAULT_BUDGETS = KAJI_ROOT / "benchmarks" / "integration-budgets.json"
TYPESCRIPT_RUNNER = KAJI_ROOT / "ts" / "scripts" / "integration-benchmark.ts"
RUNTIMES = ("python", "typescript")
CASE_NAMES = (
    "fixedOriginPreflight",
    "fixedOriginCapRejection",
    "githubDtoMaxBounds",
    "keychainRecordParse",
    "oauthRefreshSingleFlight",
)
MODE_NAMES = ("quick", "full", "calibrate")
_CALIBRATION_DIGEST_PREFIX = "sha256:"
_EXPECTED_P99_MS = {
    "fixedOriginPreflight": 5.0,
    "fixedOriginCapRejection": 5.0,
    "githubDtoMaxBounds": 25.0,
    "keychainRecordParse": 20.0,
    "oauthRefreshSingleFlight": 20.0,
}
_EXPECTED_INPUT_SHA256 = {
    "fixedOriginPreflight": "aa7d6eecaf6c4a469a5224a23933ea1182286044643f8859874775a3af5df8e7",
    "fixedOriginCapRejection": "a4b4289307f2f54631116c0a05db56dfa48aba899ae671327f4c943f0e48391a",
    "githubDtoMaxBounds": "d0bbeaf2597ae71c2b8b1ff4c279149a18da0ebeb81d9df247323ef99a867089",
    "keychainRecordParse": "a8a7b8b0530289ef9be67ecda8803439bf5714fa3ab8fd8d86df79ad0642bdf1",
    "oauthRefreshSingleFlight": "eb614f8ecd21653faab7a2995eab7601c3051bd50c9d3eb9707af6da3fd41d57",
}


class BenchmarkError(RuntimeError):
    """Closed benchmark configuration, execution, or evidence failure."""


def _fail(message: str) -> NoReturn:
    raise BenchmarkError(message)


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _reject_constant(_value: str) -> NoReturn:
    _fail("integration benchmark JSON contains a non-finite number")


def _reject_duplicate_keys(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            _fail("integration benchmark JSON contains a duplicate key")
        result[key] = value
    return result


def decode_json(value: bytes | str) -> object:
    try:
        text = value.decode("utf-8") if isinstance(value, bytes) else value
        return json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BenchmarkError("integration benchmark JSON is malformed") from error


def _closed_mapping(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        _fail(f"{label} must be a closed object")
    return cast(dict[str, Any], value)


def _positive_integer(value: object, label: str, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if type(value) is not int or value < minimum:
        _fail(f"{label} must be an integer >= {minimum}")
    return value


def _finite_number(value: object, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < (sys.float_info.min if positive else 0.0):
        _fail(f"{label} must be finite and non-negative")
    return result


def _validate_case_input(name: str, value: object) -> dict[str, Any]:
    keys = {
        "fixedOriginPreflight": {"origin", "safePath", "hostilePath", "responseBytes"},
        "fixedOriginCapRejection": {"origin", "path", "limitBytes", "overflowBytes"},
        "githubDtoMaxBounds": {
            "repository",
            "rowCount",
            "titleCharacters",
            "bodyBytes",
        },
        "keychainRecordParse": {
            "integration",
            "principal",
            "accessTokenCharacters",
            "refreshTokenCharacters",
            "scopeCharacters",
        },
        "oauthRefreshSingleFlight": {"principal", "waiters", "scopes"},
    }[name]
    document = _closed_mapping(value, keys, f"input for {name}")
    for key, item in document.items():
        if key in {
            "responseBytes",
            "limitBytes",
            "overflowBytes",
            "rowCount",
            "titleCharacters",
            "bodyBytes",
            "accessTokenCharacters",
            "refreshTokenCharacters",
            "scopeCharacters",
            "waiters",
        }:
            _positive_integer(item, f"{name}.{key}")
        elif key == "scopes":
            if (
                type(item) is not list
                or not item
                or any(not isinstance(scope, str) or not scope for scope in item)
            ):
                _fail(f"{name}.scopes must be a non-empty string array")
        elif not isinstance(item, str) or not item:
            _fail(f"{name}.{key} must be a non-empty string")
    return document


def validate_budgets(value: object) -> dict[str, Any]:
    document = _closed_mapping(
        value,
        {
            "schemaVersion",
            "runtimes",
            "percentileMethod",
            "noise",
            "artifactLimits",
            "modes",
            "cases",
            "deviations",
        },
        "integration budgets",
    )
    if document["schemaVersion"] != 1:
        _fail("integration budgets schemaVersion must be 1")
    if document["runtimes"] != list(RUNTIMES):
        _fail("integration budgets runtimes are not canonical")
    if document["percentileMethod"] != "nearest-rank":
        _fail("integration budgets percentile method is not nearest-rank")

    noise = _closed_mapping(
        document["noise"],
        {"relativeP99Spread", "absoluteP99SpreadMs"},
        "noise thresholds",
    )
    relative_noise = _finite_number(
        noise["relativeP99Spread"], "relative p99 spread", positive=True
    )
    absolute_noise = _finite_number(
        noise["absoluteP99SpreadMs"], "absolute p99 spread", positive=True
    )
    if relative_noise != 0.25 or absolute_noise != 2.0:
        _fail("integration benchmark noise thresholds changed")

    limits = _closed_mapping(
        document["artifactLimits"],
        {"summaryBytes", "rawSamplesBytes"},
        "artifact limits",
    )
    _positive_integer(limits["summaryBytes"], "summary byte limit")
    _positive_integer(limits["rawSamplesBytes"], "raw sample byte limit")
    if limits != {"summaryBytes": 32 * 1024, "rawSamplesBytes": 1024 * 1024}:
        _fail("integration benchmark artifact limits changed")

    modes = _closed_mapping(document["modes"], set(MODE_NAMES), "benchmark modes")
    for name in MODE_NAMES:
        mode = _closed_mapping(
            modes[name],
            {
                "warmups",
                "batches",
                "samplesPerBatch",
                "enforceTiming",
                "requiresProtectedRunner",
            },
            f"mode {name}",
        )
        _positive_integer(mode["warmups"], f"{name} warmups", allow_zero=True)
        _positive_integer(mode["batches"], f"{name} batches")
        _positive_integer(mode["samplesPerBatch"], f"{name} samples")
        if (
            type(mode["enforceTiming"]) is not bool
            or type(mode["requiresProtectedRunner"]) is not bool
        ):
            _fail(f"mode {name} flags must be booleans")
    if modes["full"] != {
        "warmups": 20,
        "batches": 3,
        "samplesPerBatch": 200,
        "enforceTiming": True,
        "requiresProtectedRunner": False,
    }:
        _fail("full mode must remain 20 warmups and three batches of 200")
    if modes["calibrate"] != {
        "warmups": 20,
        "batches": 3,
        "samplesPerBatch": 200,
        "enforceTiming": False,
        "requiresProtectedRunner": True,
    }:
        _fail("calibration mode contract changed")
    if modes["quick"] != {
        "warmups": 1,
        "batches": 1,
        "samplesPerBatch": 3,
        "enforceTiming": False,
        "requiresProtectedRunner": False,
    }:
        _fail("quick mode contract changed")

    cases = document["cases"]
    if type(cases) is not list or len(cases) != len(CASE_NAMES):
        _fail("integration budgets cases are incomplete")
    for expected, raw_case in zip(CASE_NAMES, cases, strict=True):
        case = _closed_mapping(raw_case, {"name", "p99Ms", "input"}, f"case {expected}")
        if case["name"] != expected:
            _fail("integration budget case order changed")
        p99 = _closed_mapping(
            case["p99Ms"], set(RUNTIMES), f"p99 budget for {expected}"
        )
        for runtime in RUNTIMES:
            value = _finite_number(
                p99[runtime], f"{expected}.{runtime} p99", positive=True
            )
            if value != _EXPECTED_P99_MS[expected]:
                _fail(f"{expected}.{runtime} p99 budget changed")
        validated_input = _validate_case_input(expected, case["input"])
        if input_digest(validated_input) != _EXPECTED_INPUT_SHA256[expected]:
            _fail(f"{expected} input corpus changed")

    deviations = document["deviations"]
    expected_deviation = {
        "case": "gmailMimeMaxBounds",
        "status": "hold",
        "reasonCode": "GMAIL_RUNTIME_NOT_IN_REVIEWED_CHECKPOINT",
        "ownerTask": 8,
        "included": False,
    }
    if deviations != [expected_deviation]:
        _fail("the Gmail benchmark hold must remain explicit and machine-readable")
    return document


def load_budgets(path: Path = DEFAULT_BUDGETS) -> dict[str, Any]:
    try:
        value = decode_json(path.read_bytes())
    except (OSError, BenchmarkError) as error:
        raise BenchmarkError("integration budgets could not be loaded") from error
    return validate_budgets(value)


def case_input(budgets: Mapping[str, Any], name: str) -> dict[str, Any]:
    for case in cast(list[dict[str, Any]], budgets["cases"]):
        if case["name"] == name:
            return cast(dict[str, Any], case["input"])
    _fail(f"unknown integration benchmark case: {name}")


def input_digest(value: object) -> str:
    return sha256_bytes(canonical_bytes(value))


def corpus_digest(budgets: Mapping[str, Any]) -> str:
    corpus = [
        {"name": case["name"], "input": case["input"]}
        for case in cast(list[dict[str, Any]], budgets["cases"])
    ]
    return sha256_bytes(canonical_bytes(corpus))


def nearest_rank(samples: Sequence[float], percentile: float) -> float:
    if isinstance(percentile, bool) or not isinstance(percentile, (int, float)):
        _fail("percentile must be numeric")
    if not math.isfinite(float(percentile)) or not 0 < percentile <= 1:
        _fail("percentile must be in (0, 1]")
    validated = [
        _finite_number(sample, f"sample {index}")
        for index, sample in enumerate(samples)
    ]
    if not validated:
        _fail("percentile samples must not be empty")
    ordered = sorted(validated)
    return ordered[math.ceil(float(percentile) * len(ordered)) - 1]


def summarize_batch(samples: Sequence[float]) -> dict[str, float | int]:
    return {
        "samples": len(samples),
        "p50Ms": nearest_rank(samples, 0.50),
        "p95Ms": nearest_rank(samples, 0.95),
        "p99Ms": nearest_rank(samples, 0.99),
        "maxMs": nearest_rank(samples, 1.0),
    }


def noisy_p99(
    p99_values: Sequence[float], *, relative: float, absolute_ms: float
) -> bool:
    values = [_finite_number(value, "batch p99") for value in p99_values]
    if len(values) < 2:
        return False
    spread = max(values) - min(values)
    threshold = max(relative * statistics.median(values), absolute_ms)
    return spread > threshold


def _expected_semantic_keys(case: str) -> set[str]:
    return {
        "fixedOriginPreflight": {
            "safeRequests",
            "hostileRequests",
            "rejected",
            "responseBytes",
        },
        "fixedOriginCapRejection": {
            "requests",
            "rejected",
            "closed",
            "limitBytes",
            "observedBytes",
        },
        "githubDtoMaxBounds": {
            "rows",
            "titleCharacters",
            "bodyPreviewBytes",
            "serializedBytes",
        },
        "keychainRecordParse": {
            "records",
            "processCalls",
            "recordBytes",
            "scopes",
        },
        "oauthRefreshSingleFlight": {
            "waiters",
            "httpCalls",
            "saveCalls",
            "uniqueTokens",
        },
    }[case]


def validate_semantics(
    case: str, semantics: object, inputs: Mapping[str, Any]
) -> dict[str, int]:
    values = _closed_mapping(
        semantics, _expected_semantic_keys(case), f"{case} semantics"
    )
    if any(type(value) is not int or value < 0 for value in values.values()):
        _fail(f"{case} semantic counters must be non-negative integers")
    expected: dict[str, int]
    if case == "fixedOriginPreflight":
        expected = {
            "safeRequests": 1,
            "hostileRequests": 0,
            "rejected": 1,
            "responseBytes": inputs["responseBytes"],
        }
    elif case == "fixedOriginCapRejection":
        expected = {
            "requests": 1,
            "rejected": 1,
            "closed": 1,
            "limitBytes": inputs["limitBytes"],
            "observedBytes": inputs["limitBytes"] + inputs["overflowBytes"],
        }
    elif case == "githubDtoMaxBounds":
        expected = {
            "rows": inputs["rowCount"],
            "titleCharacters": inputs["titleCharacters"],
            "bodyPreviewBytes": inputs["bodyBytes"],
            "serializedBytes": values["serializedBytes"],
        }
        if not 0 < values["serializedBytes"] <= 32 * 1024:
            _fail("GitHub DTO exceeded its 32 KiB result bound")
    elif case == "keychainRecordParse":
        expected = {
            "records": 1,
            "processCalls": 1,
            "recordBytes": values["recordBytes"],
            "scopes": 1,
        }
        if not 0 < values["recordBytes"] <= 16 * 1024:
            _fail("Keychain record did not exercise the bounded parser")
    else:
        expected = {
            "waiters": inputs["waiters"],
            "httpCalls": 1,
            "saveCalls": 1,
            "uniqueTokens": 1,
        }
    if values != expected:
        _fail(f"{case} semantic result changed")
    return cast(dict[str, int], values)


def validate_raw_result(
    value: object,
    *,
    runtime: str,
    case: str,
    inputs: Mapping[str, Any],
    warmups: int,
    batches: int,
    samples_per_batch: int,
) -> dict[str, Any]:
    result = _closed_mapping(
        value,
        {
            "schemaVersion",
            "runtime",
            "case",
            "inputSha256",
            "warmups",
            "batches",
            "semantics",
        },
        f"{runtime} {case} result",
    )
    if (
        result["schemaVersion"] != 1
        or result["runtime"] != runtime
        or result["case"] != case
        or result["inputSha256"] != input_digest(inputs)
        or result["warmups"] != warmups
    ):
        _fail(f"{runtime} {case} result identity changed")
    raw_batches = result["batches"]
    if type(raw_batches) is not list or len(raw_batches) != batches:
        _fail(f"{runtime} {case} emitted the wrong batch count")
    for batch in raw_batches:
        if type(batch) is not list or len(batch) != samples_per_batch:
            _fail(f"{runtime} {case} emitted the wrong sample count")
        for sample in batch:
            _finite_number(sample, f"{runtime} {case} duration")
    result["semantics"] = validate_semantics(case, result["semantics"], inputs)
    return result


def _case_budget(budgets: Mapping[str, Any], case_name: str, runtime: str) -> float:
    for case in cast(list[dict[str, Any]], budgets["cases"]):
        if case["name"] == case_name:
            return float(case["p99Ms"][runtime])
    _fail(f"missing budget for {case_name}")


def summarize_results(
    results: Sequence[Mapping[str, Any]], budgets: Mapping[str, Any], mode: str
) -> list[dict[str, Any]]:
    mode_config = cast(dict[str, Any], budgets["modes"][mode])
    summarized: list[dict[str, Any]] = []
    by_case: dict[str, dict[str, Mapping[str, Any]]] = {}
    for result in results:
        runtime = cast(str, result["runtime"])
        case_name = cast(str, result["case"])
        batches = [
            summarize_batch(batch)
            for batch in cast(list[list[float]], result["batches"])
        ]
        p99_values = [float(batch["p99Ms"]) for batch in batches]
        if mode_config["enforceTiming"]:
            budget = _case_budget(budgets, case_name, runtime)
            if any(value > budget for value in p99_values):
                _fail(f"{runtime} {case_name} exceeded its p99 budget")
        noise = cast(dict[str, float], budgets["noise"])
        if noisy_p99(
            p99_values,
            relative=float(noise["relativeP99Spread"]),
            absolute_ms=float(noise["absoluteP99SpreadMs"]),
        ):
            _fail(f"{runtime} {case_name} p99 samples are noisy")
        summarized.append(
            {
                "runtime": runtime,
                "case": case_name,
                "inputSha256": result["inputSha256"],
                "warmups": result["warmups"],
                "batches": batches,
                "semantics": result["semantics"],
            }
        )
        by_case.setdefault(case_name, {})[runtime] = result
    for case_name in CASE_NAMES:
        pair = by_case.get(case_name, {})
        if set(pair) != set(RUNTIMES):
            _fail(f"cross-runtime result missing for {case_name}")
        if pair["python"]["semantics"] != pair["typescript"]["semantics"]:
            _fail(f"cross-runtime semantic mismatch for {case_name}")
    return summarized


def verify_raw_digest(raw_bytes: bytes, expected: str) -> None:
    if sha256_bytes(raw_bytes) != expected:
        _fail("raw sample digest mismatch")


def _tool_version(command: str, fallback: str) -> str:
    executable = shutil.which(command)
    if executable is None:
        candidate = Path(fallback)
        executable = str(candidate) if candidate.is_file() else None
    if executable is None:
        return "unavailable"
    try:
        completed = run_checked(
            [executable, "--version"],
            cwd=REPOSITORY_ROOT,
            budget=METADATA_BUDGET,
            capture=True,
        )
    except CommandError:
        return "unavailable"
    try:
        return completed.stdout.decode("utf-8").strip().splitlines()[0][:128]
    except (IndexError, UnicodeDecodeError):
        return "unavailable"


def source_digest(budget_bytes: bytes) -> str:
    digest = hashlib.sha256()
    for path in (Path(__file__).resolve(), TYPESCRIPT_RUNNER.resolve()):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    digest.update(budget_bytes)
    return digest.hexdigest()


def machine_fingerprint(budget_bytes: bytes) -> dict[str, str]:
    return {
        "system": platform.system().lower(),
        "machine": platform.machine().lower(),
        "python": platform.python_version(),
        "node": _tool_version("node", "/usr/local/bin/node"),
        "bun": _tool_version("bun", "/opt/homebrew/bin/bun"),
        "runnerImageDigest": os.environ.get(
            "KAJI_BENCHMARK_RUNNER_IMAGE_DIGEST", "local-unpinned"
        ),
        "budgetSha256": sha256_bytes(budget_bytes),
        "sourceSha256": source_digest(budget_bytes),
    }


def require_protected_calibration() -> None:
    if os.environ.get("KAJI_BENCHMARK_CALIBRATION") != "1":
        _fail("calibration requires KAJI_BENCHMARK_CALIBRATION=1")
    if os.environ.get("KAJI_BENCHMARK_PINNED_RUNNER") != "1":
        _fail("calibration requires KAJI_BENCHMARK_PINNED_RUNNER=1")
    digest = os.environ.get("KAJI_BENCHMARK_RUNNER_IMAGE_DIGEST", "")
    if (
        not digest.startswith(_CALIBRATION_DIGEST_PREFIX)
        or len(digest) != len(_CALIBRATION_DIGEST_PREFIX) + 64
        or any(character not in "0123456789abcdef" for character in digest[7:])
    ):
        _fail("calibration requires a reviewed sha256 runner image digest")


def _python_context(principal: str = "benchmark-principal") -> Any:
    from kaji.runtime.agents.cancellation import CancellationToken
    from kaji.runtime.context import ToolExecutionContext

    return ToolExecutionContext(
        principal_id=principal,
        session_id="benchmark-session",
        turn_id="benchmark-turn",
        request_id="benchmark-request",
        trace_id="benchmark-trace",
        tool_call_id="benchmark-call",
        idempotency_key="benchmark-session:benchmark-call",
        cancellation_token=CancellationToken(),
        deadline_monotonic=None,
        db=None,
        metadata={},
    )


_Operation = Callable[[], Awaitable[dict[str, int]]]
_Closer = Callable[[], Awaitable[None]]


async def _fixed_origin_preflight(
    inputs: Mapping[str, Any],
) -> tuple[_Operation, _Closer]:
    import httpx

    from kaji.integrations.errors import IntegrationPolicyError
    from kaji.integrations.fixed_origin import FixedOriginClient

    transport_calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal transport_calls
        transport_calls += 1
        return httpx.Response(200, content=b"{}")

    client = FixedOriginClient._for_test(
        cast(str, inputs["origin"]), transport=httpx.MockTransport(handler)
    )

    async def operation() -> dict[str, int]:
        before = transport_calls
        response = await client.request(
            cast(str, inputs["safePath"]),
            method="GET",
            headers={},
            body=None,
            context=_python_context(),
        )
        after_safe = transport_calls
        rejected = 0
        try:
            await client.request(
                cast(str, inputs["hostilePath"]),
                method="GET",
                headers={},
                body=None,
                context=_python_context(),
            )
        except IntegrationPolicyError:
            rejected = 1
        return {
            "safeRequests": after_safe - before,
            "hostileRequests": transport_calls - after_safe,
            "rejected": rejected,
            "responseBytes": len(response.body),
        }

    return operation, client.aclose


async def _fixed_origin_cap(inputs: Mapping[str, Any]) -> tuple[_Operation, _Closer]:
    import httpx

    from kaji.integrations.errors import IntegrationTransportError
    from kaji.integrations.fixed_origin import FixedOriginClient

    payload = b"x" * (inputs["limitBytes"] + inputs["overflowBytes"])
    transport_calls = 0
    closed = 0

    class OverflowStream(httpx.AsyncByteStream):
        async def __aiter__(self):  # type: ignore[no-untyped-def]
            yield payload

        async def aclose(self) -> None:
            nonlocal closed
            closed += 1

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal transport_calls
        transport_calls += 1
        return httpx.Response(200, stream=OverflowStream())

    client = FixedOriginClient._for_test(
        cast(str, inputs["origin"]),
        transport=httpx.MockTransport(handler),
        max_response_bytes=cast(int, inputs["limitBytes"]),
    )

    async def operation() -> dict[str, int]:
        calls_before = transport_calls
        closed_before = closed
        rejected = 0
        try:
            await client.request(
                cast(str, inputs["path"]),
                method="GET",
                headers={},
                body=None,
                context=_python_context(),
            )
        except IntegrationTransportError as error:
            if error.error_code != "INTEGRATION_RESPONSE_LIMIT":
                raise
            rejected = 1
        return {
            "requests": transport_calls - calls_before,
            "rejected": rejected,
            "closed": closed - closed_before,
            "limitBytes": cast(int, inputs["limitBytes"]),
            "observedBytes": len(payload),
        }

    return operation, client.aclose


async def _github_dto(inputs: Mapping[str, Any]) -> tuple[_Operation, _Closer]:
    from kaji.integrations.fixed_origin import IntegrationResponse
    from kaji.integrations.registry.github.client import GitHubClient

    repository = cast(str, inputs["repository"])
    rows = [
        {
            "number": index + 1,
            "state": "open",
            "title": "t" * cast(int, inputs["titleCharacters"]),
            "body": "b" * cast(int, inputs["bodyBytes"]),
        }
        for index in range(cast(int, inputs["rowCount"]))
    ]
    response_body = canonical_bytes(rows)

    class Http:
        async def request(self, *_args: Any, **_kwargs: Any) -> IntegrationResponse:
            return IntegrationResponse(200, {}, response_body)

    async def token_for(_context: Any) -> str:
        return "benchmark-token"

    client = GitHubClient(
        token_for=token_for,
        repositories=[repository],
        http=cast(Any, Http()),
    )

    async def operation() -> dict[str, int]:
        result = await client.list_issues(
            _python_context(),
            repository=repository,
            state="all",
            page=1,
            per_page=20,
        )
        result_rows = cast(Sequence[Mapping[str, Any]], result["items"])
        serialized = canonical_bytes(result)
        return {
            "rows": len(result_rows),
            "titleCharacters": len(cast(str, result_rows[0]["title"])),
            "bodyPreviewBytes": len(cast(str, result_rows[0]["body_preview"]).encode()),
            "serializedBytes": len(serialized),
        }

    async def close() -> None:
        return None

    return operation, close


async def _keychain_parse(inputs: Mapping[str, Any]) -> tuple[_Operation, _Closer]:
    from kaji.integrations.keychain import _create_macos_keychain_storage_for_test
    from kaji.integrations.oauth import (
        OAuthCredentialRecord,
        OAuthTokenSet,
        _canonical_wire,
    )
    from kaji.runtime.agents.cancellation import CancellationToken

    record = OAuthCredentialRecord(
        1,
        "active",
        OAuthTokenSet(
            access_token="a" * cast(int, inputs["accessTokenCharacters"]),
            refresh_token="r" * cast(int, inputs["refreshTokenCharacters"]),
            expires_at_epoch_ms=1_700_003_600_000,
            granted_scopes=("s" * cast(int, inputs["scopeCharacters"]),),
        ),
    )
    _, encoded = _canonical_wire(record.to_wire())

    class Process:
        calls = 0

        async def run(self, _args: Any, **_kwargs: Any) -> tuple[int, str]:
            self.calls += 1
            return 0, encoded.decode("utf-8") + "\n"

    process = Process()
    storage = _create_macos_keychain_storage_for_test(
        process=cast(Any, process),
        platform="darwin",
        executable=True,
        integration_name=cast(str, inputs["integration"]),
    )

    async def operation() -> dict[str, int]:
        before = process.calls
        loaded = await storage.load(
            cast(str, inputs["principal"]), CancellationToken(), None
        )
        if loaded is None:
            _fail("Keychain benchmark record disappeared")
        return {
            "records": 1,
            "processCalls": process.calls - before,
            "recordBytes": len(encoded),
            "scopes": len(loaded.tokens.granted_scopes),
        }

    async def close() -> None:
        return None

    return operation, close


async def _oauth_single_flight(inputs: Mapping[str, Any]) -> tuple[_Operation, _Closer]:
    from kaji.integrations.oauth import (
        OAuthCredentialRecord,
        OAuthTokenSet,
        _OAuthHttpResponse,
        _create_google_oauth_client_for_test,
    )

    principal = cast(str, inputs["principal"])
    waiters = cast(int, inputs["waiters"])
    scopes = tuple(cast(list[str], inputs["scopes"]))

    class Clock:
        def now_wall_seconds(self) -> float:
            return 1_700_000_000.0

        def now_monotonic(self) -> float:
            return 100.0

    class CallbackFactory:
        async def open(self, *_args: Any, **_kwargs: Any) -> Any:
            _fail("refresh benchmark opened a callback listener")

    class Browser:
        async def open(self, *_args: Any, **_kwargs: Any) -> None:
            _fail("refresh benchmark opened a browser")

    async def operation() -> dict[str, int]:
        old_record = OAuthCredentialRecord(
            1,
            "active",
            OAuthTokenSet("old", "refresh", 1, scopes),
        )

        class Store:
            loads = 0
            saves = 0
            value = old_record

            async def load(self, *_args: Any, **_kwargs: Any) -> OAuthCredentialRecord:
                self.loads += 1
                return self.value

            async def save(
                self, _principal: str, value: OAuthCredentialRecord, *_args: Any
            ) -> None:
                self.saves += 1
                self.value = value

            async def delete(self, *_args: Any, **_kwargs: Any) -> None:
                _fail("refresh benchmark unexpectedly deleted the grant")

        class Http:
            calls = 0
            entered = asyncio.Event()
            release = asyncio.Event()

            async def post_form(
                self, *_args: Any, **_kwargs: Any
            ) -> _OAuthHttpResponse:
                self.calls += 1
                self.entered.set()
                await self.release.wait()
                return _OAuthHttpResponse(
                    200,
                    b'{"access_token":"new","expires_in":3600,"token_type":"Bearer"}',
                )

        store = Store()
        http = Http()
        oauth = _create_google_oauth_client_for_test(
            client_id="client-id",
            client_secret=None,
            scopes=scopes,
            credential_store=cast(Any, store),
            http=cast(Any, http),
            callback_factory=cast(Any, CallbackFactory()),
            browser=cast(Any, Browser()),
            clock=cast(Any, Clock()),
            random_bytes=lambda count: bytes(range(count)),
        )
        tasks = [
            asyncio.create_task(oauth.access_token(_python_context(principal)))
            for _ in range(waiters)
        ]
        await http.entered.wait()
        for _ in range(waiters * 4):
            if store.loads == waiters:
                break
            await asyncio.sleep(0)
        if store.loads != waiters:
            _fail("refresh waiters did not join deterministically")
        await asyncio.sleep(0)
        http.release.set()
        tokens = await asyncio.gather(*tasks)
        return {
            "waiters": len(tokens),
            "httpCalls": http.calls,
            "saveCalls": store.saves,
            "uniqueTokens": len(set(tokens)),
        }

    async def close() -> None:
        return None

    return operation, close


async def _python_case_factory(
    case: str, inputs: Mapping[str, Any]
) -> tuple[_Operation, _Closer]:
    factories: dict[
        str, Callable[[Mapping[str, Any]], Awaitable[tuple[_Operation, _Closer]]]
    ] = {
        "fixedOriginPreflight": _fixed_origin_preflight,
        "fixedOriginCapRejection": _fixed_origin_cap,
        "githubDtoMaxBounds": _github_dto,
        "keychainRecordParse": _keychain_parse,
        "oauthRefreshSingleFlight": _oauth_single_flight,
    }
    try:
        return await factories[case](inputs)
    except KeyError:
        _fail(f"unknown Python integration benchmark case: {case}")


async def run_python_case(
    case: str,
    inputs: Mapping[str, Any],
    *,
    warmups: int,
    batches: int,
    samples_per_batch: int,
) -> dict[str, Any]:
    operation, close = await _python_case_factory(case, inputs)
    semantics: dict[str, int] | None = None

    async def invoke(*, measured: bool) -> float:
        nonlocal semantics
        started = time.perf_counter_ns()
        current = await operation()
        elapsed = (time.perf_counter_ns() - started) / 1_000_000
        if semantics is None:
            semantics = current
        elif current != semantics:
            _fail(f"Python {case} semantics changed between samples")
        return elapsed if measured else 0.0

    try:
        for _ in range(warmups):
            await invoke(measured=False)
        measured_batches: list[list[float]] = []
        for _ in range(batches):
            measured_batches.append(
                [await invoke(measured=True) for _ in range(samples_per_batch)]
            )
    finally:
        await close()
    assert semantics is not None
    return {
        "schemaVersion": 1,
        "runtime": "python",
        "case": case,
        "inputSha256": input_digest(inputs),
        "warmups": warmups,
        "batches": measured_batches,
        "semantics": semantics,
    }


def _safe_child_environment(home: Path) -> dict[str, str]:
    path = os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    return {
        "PATH": path,
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "TMPDIR": str(home / "tmp"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "TZ": "UTC",
    }


def _bun_binary() -> str:
    discovered = shutil.which("bun")
    if discovered is not None:
        return discovered
    fallback = Path("/opt/homebrew/bin/bun")
    if fallback.is_file():
        return str(fallback)
    _fail("Bun is required for the TypeScript integration benchmark")


def _run_child(
    runtime: str,
    case: str,
    *,
    budgets_path: Path,
    warmups: int,
    batches: int,
    samples_per_batch: int,
    environment: Mapping[str, str],
) -> object:
    common = [
        "--child-case",
        case,
        "--budgets",
        str(budgets_path),
        "--warmups",
        str(warmups),
        "--batches",
        str(batches),
        "--samples-per-batch",
        str(samples_per_batch),
    ]
    if runtime == "python":
        command = [sys.executable, str(Path(__file__).resolve()), *common]
        cwd = REPOSITORY_ROOT
    elif runtime == "typescript":
        command = [_bun_binary(), "scripts/integration-benchmark.ts", *common]
        cwd = KAJI_ROOT / "ts"
    else:
        _fail(f"unknown integration benchmark runtime: {runtime}")
    completed = run_checked(
        command,
        cwd=cwd,
        budget=BENCHMARK_COMMAND_BUDGET,
        env=dict(environment),
        capture=True,
        check=False,
    )
    if completed.returncode != 0:
        _fail(f"{runtime} {case} benchmark child failed")
    try:
        return decode_json(completed.stdout)
    except BenchmarkError as error:
        raise BenchmarkError(f"{runtime} {case} emitted invalid JSON") from error


def run_orchestrator(
    *,
    mode: str,
    budgets_path: Path,
    raw_output: Path | None,
    summary_output: Path | None,
) -> dict[str, Any]:
    budgets = load_budgets(budgets_path)
    if mode not in MODE_NAMES:
        _fail("unknown integration benchmark mode")
    mode_config = cast(dict[str, Any], budgets["modes"][mode])
    if mode_config["requiresProtectedRunner"]:
        require_protected_calibration()
    if (raw_output is None) != (summary_output is None):
        _fail("raw and summary outputs must be supplied together")
    if mode != "quick" and (raw_output is None or summary_output is None):
        _fail("full and calibration modes require separate raw and summary outputs")

    warmups = cast(int, mode_config["warmups"])
    batches = cast(int, mode_config["batches"])
    samples_per_batch = cast(int, mode_config["samplesPerBatch"])
    raw_results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="kaji-integration-benchmark-") as temporary:
        home = Path(temporary)
        (home / "tmp").mkdir()
        environment = _safe_child_environment(home)
        for case_name in CASE_NAMES:
            inputs = case_input(budgets, case_name)
            for runtime in RUNTIMES:
                value = _run_child(
                    runtime,
                    case_name,
                    budgets_path=budgets_path.resolve(),
                    warmups=warmups,
                    batches=batches,
                    samples_per_batch=samples_per_batch,
                    environment=environment,
                )
                raw_results.append(
                    validate_raw_result(
                        value,
                        runtime=runtime,
                        case=case_name,
                        inputs=inputs,
                        warmups=warmups,
                        batches=batches,
                        samples_per_batch=samples_per_batch,
                    )
                )

    budget_bytes = budgets_path.read_bytes()
    budget_sha = sha256_bytes(budget_bytes)
    raw_document = {
        "schemaVersion": 1,
        "mode": mode,
        "budgetSha256": budget_sha,
        "corpusSha256": corpus_digest(budgets),
        "results": raw_results,
    }
    raw_bytes = canonical_bytes(raw_document)
    if len(raw_bytes) > budgets["artifactLimits"]["rawSamplesBytes"]:
        _fail("raw integration benchmark artifact exceeds its byte limit")
    raw_sha = sha256_bytes(raw_bytes)
    summary = {
        "schemaVersion": 1,
        "mode": mode,
        "budgetSha256": budget_sha,
        "corpusSha256": corpus_digest(budgets),
        "rawSamplesSha256": raw_sha,
        "fingerprint": machine_fingerprint(budget_bytes),
        "deviations": budgets["deviations"],
        "results": summarize_results(raw_results, budgets, mode),
    }
    summary_bytes = canonical_bytes(summary)
    if len(summary_bytes) > budgets["artifactLimits"]["summaryBytes"]:
        _fail("integration benchmark summary exceeds 32 KiB")
    verify_raw_digest(raw_bytes, summary["rawSamplesSha256"])
    if raw_output is not None and summary_output is not None:
        raw_output.parent.mkdir(parents=True, exist_ok=True)
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        raw_output.write_bytes(raw_bytes)
        summary_output.write_bytes(summary_bytes)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=MODE_NAMES)
    parser.add_argument("--budgets", type=Path, default=DEFAULT_BUDGETS)
    parser.add_argument("--raw-output", type=Path)
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument("--child-case", choices=CASE_NAMES, help=argparse.SUPPRESS)
    parser.add_argument("--warmups", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--batches", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--samples-per-batch", type=int, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        budgets = load_budgets(args.budgets)
        if args.child_case is not None:
            if (
                args.mode is not None
                or args.raw_output is not None
                or args.summary_output is not None
            ):
                _fail("child mode does not accept orchestrator arguments")
            warmups = _positive_integer(args.warmups, "child warmups", allow_zero=True)
            batches = _positive_integer(args.batches, "child batches")
            samples = _positive_integer(args.samples_per_batch, "child samples")
            result = asyncio.run(
                run_python_case(
                    args.child_case,
                    case_input(budgets, args.child_case),
                    warmups=warmups,
                    batches=batches,
                    samples_per_batch=samples,
                )
            )
            print(canonical_bytes(result).decode("utf-8"))
            return 0
        if args.mode is None:
            _fail("--mode is required")
        summary = run_orchestrator(
            mode=args.mode,
            budgets_path=args.budgets,
            raw_output=args.raw_output,
            summary_output=args.summary_output,
        )
        print(canonical_bytes(summary).decode("utf-8"))
        return 0
    except BenchmarkError as error:
        print(f"integration benchmark failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
