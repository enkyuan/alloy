#!/usr/bin/env python3
"""Validate Kaji's canonical production-beta contracts."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError
from kaji.integrations.validation import parameter_schema_issue


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "kaji" / "contracts"
RELEASE_MATRIX = ROOT / "kaji" / "RELEASE_MATRIX.md"
REGISTRY_INDEXES = (
    ROOT / "kaji" / "src" / "kaji" / "integrations" / "registry" / "index.json",
    ROOT / "kaji" / "ts" / "registry" / "index.json",
)
PACKAGE_CONTRACT_TARGETS = (
    ROOT / "kaji" / "src" / "kaji" / "contracts",
    ROOT / "kaji" / "ts" / "contracts",
)
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
REQUIRED_JSON = {
    "beta-core-v1.json",
    "cli/init-cases-v1.json",
    "feature-tiers-v1.json",
    "errors/error-codes.json",
    "errors/integration-recovery-v1.json",
    "errors/provider-normalization.json",
    "events/conformance.json",
    "events/conformance-invalid.json",
    "events/new-kaji-event-v1.schema.json",
    "events/stored-kaji-event-v1.schema.json",
    "integrations/conformance-invalid.json",
    "integrations/conformance-valid.json",
    "integrations/abi-index-v1.json",
    "integrations/copy-provenance-v1.schema.json",
    "integrations/echo-tool-abi-v1.json",
    "integrations/github-tool-abi-v1.json",
    "integrations/github-tool-abi-typescript-v1.json",
    "parity/expected-normalized.json",
    "parity/scenarios.json",
    "parity/scenarios.schema.json",
    "providers/cost-conformance.json",
    "release/github-proof-v1.schema.json",
    "release/publisher-identity-receipt-v1.schema.json",
    "release/typescript-onboarding-evidence-v1.schema.json",
    "release/kaji-ts-consumer-handoff-v1.schema.json",
    "tools/conformance-invalid.json",
    "tools/conformance-valid.json",
    "tools/tool-schema-v1.schema.json",
}
DATA_DOCUMENTS = {
    "integrations/abi-index-v1.json",
    "parity/expected-normalized.json",
}
APPROVAL_FAILURE_RETRYABILITY = {
    "APPROVAL_REJECTED": False,
    "APPROVAL_TIMEOUT": True,
    "TURN_TIMEOUT": True,
    "TOOL_CANCELLED": True,
    "APPROVAL_UNAVAILABLE": False,
}
EXPECTED_TOOL_RISKS = ["read", "write", "external_effect", "destructive", "admin"]
REQUIRED_EVENT_NEGATIVE_CASES = {
    "missing-event-id",
    "missing-version",
    "missing-timestamp",
    "missing-session-id",
    "missing-event-type",
    "empty-event-id",
    "empty-session-id",
    "empty-present-turn-id",
    "unknown-event-type",
    "extra-field",
    "draft-has-sequence",
    "stored-missing-sequence",
    "unsafe-integral-number",
}
SAFE_JSON_INTEGER_MAX = 9_007_199_254_740_991
GITHUB_TYPESCRIPT_TOOL_NAMES = [
    "add_comment",
    "create_issue",
    "get_file",
    "get_issue",
    "list_issues",
    "search_code",
    "get_commit",
    "get_pull_request",
    "list_pull_request_files",
    "list_check_runs",
    "get_workflow_run",
    "list_workflow_jobs",
    "list_file_commits",
    "get_release",
    "list_deployments",
]
GITHUB_TYPESCRIPT_EXTENSION_NAMES = GITHUB_TYPESCRIPT_TOOL_NAMES[6:]
REQUIRED_PROVIDER_COST_CASES = [
    "tie-even-down",
    "tie-even-up",
    "carry-across-unit",
    "sum-before-rounding",
    "gemini-small",
    "gemini-large",
    "maximum-safe-token-counts",
    "unknown-model",
]
PROVIDER_RATE_MAX_SIGNIFICANT_DIGITS = 32
PROVIDER_RATE_MAX_FRACTIONAL_DIGITS = 32
PROVIDER_RATE_MAX_ABSOLUTE_EXPONENT = 32
PROVIDER_RATE_MAX_TEXT_LENGTH = 65
PROVIDER_RATE_DECIMAL = re.compile(r"^(0|[1-9][0-9]*)(?:\.([0-9]*[1-9]))?$")
PROVIDER_RATE_SCIENTIFIC = re.compile(r"^([1-9])(?:\.([0-9]*[1-9]))?e(-?[1-9][0-9]*)$")
REQUIRED_INVALID_PROVIDER_RATES = [
    ("negative-number", "number", "-0.1"),
    ("negative-string", "string", "-0.1"),
    ("nan-number", "number", "NaN"),
    ("nan-string", "string", "NaN"),
    ("infinity-number", "number", "Infinity"),
    ("infinity-string", "string", "Infinity"),
    ("empty", "string", ""),
    ("leading-zero", "string", "01"),
    ("bare-fraction", "string", ".5"),
    ("trailing-point", "string", "1."),
    ("trailing-fraction-zero", "string", "1.0"),
    ("uppercase-exponent", "string", "1E1"),
    ("positive-exponent-sign", "string", "1e+1"),
    ("zero-exponent", "string", "1e0"),
    ("leading-zero-exponent", "string", "1e01"),
    ("wide-scientific-significand", "string", "12e1"),
    (
        "excessive-significant-digits",
        "string",
        "1.23456789012345678901234567890123",
    ),
    (
        "excessive-fractional-digits",
        "string",
        "0.000000000000000000000000000000001",
    ),
    ("excessive-positive-exponent", "string", "1e33"),
    ("excessive-negative-exponent", "string", "1e-33"),
]


class ContractError(RuntimeError):
    pass


def provider_rate_is_valid(value: str) -> bool:
    if not 0 < len(value) <= PROVIDER_RATE_MAX_TEXT_LENGTH:
        return False
    match = PROVIDER_RATE_DECIMAL.fullmatch(value)
    exponent = 0
    if match is None:
        match = PROVIDER_RATE_SCIENTIFIC.fullmatch(value)
        if match is None:
            return False
        exponent_text = match.group(3).removeprefix("-")
        if len(exponent_text) > 2:
            return False
        exponent = int(match.group(3))
    fraction = match.group(2) or ""
    significant = (match.group(1) + fraction).lstrip("0") or "0"
    return (
        len(significant) <= PROVIDER_RATE_MAX_SIGNIFICANT_DIGITS
        and len(fraction) <= PROVIDER_RATE_MAX_FRACTIONAL_DIGITS
        and abs(exponent) <= PROVIDER_RATE_MAX_ABSOLUTE_EXPONENT
    )


def pointer(parts: Any) -> str:
    encoded = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(encoded) if encoded else "/"


def fail(path: Path, location: str, message: str) -> ContractError:
    return ContractError(f"{path}: {location}: {message}")


def load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise fail(path, "/", str(exc)) from exc
    if not isinstance(document, dict):
        raise fail(path, "/", "expected a JSON object")
    return document


def first_error(
    validator: Draft202012Validator, instance: Any
) -> ValidationError | None:
    errors = sorted(
        validator.iter_errors(instance),
        key=lambda error: (list(error.absolute_path), list(error.absolute_schema_path)),
    )
    return errors[0] if errors else None


def check_schema(schema: Any) -> SchemaError | None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        return exc
    return None


def check_tool_risk_vocabulary(documents: dict[str, dict[str, Any]]) -> None:
    locations = {
        "tools/tool-schema-v1.schema.json": (
            "/properties/risk/enum",
            documents["tools/tool-schema-v1.schema.json"]["properties"]["risk"]["enum"],
        ),
        "integrations/manifest.schema.json": (
            "/properties/tools/items/properties/risk/enum",
            documents["integrations/manifest.schema.json"]["properties"]["tools"][
                "items"
            ]["properties"]["risk"]["enum"],
        ),
    }
    for relative in (
        "events/new-kaji-event-v1.schema.json",
        "events/stored-kaji-event-v1.schema.json",
    ):
        approval_rule = (
            documents[relative].get("$defs", {}).get("toolApprovalRequested")
        )
        if not isinstance(approval_rule, dict):
            raise fail(
                CONTRACTS / relative,
                "/$defs/toolApprovalRequested",
                "missing approval request variant",
            )
        payload = approval_rule["allOf"][1]
        locations[relative] = (
            "/$defs/toolApprovalRequested/allOf/1/properties/risk/enum",
            payload["properties"]["risk"]["enum"],
        )

    for relative, (location, actual) in locations.items():
        if actual != EXPECTED_TOOL_RISKS:
            raise fail(
                CONTRACTS / relative,
                location,
                f"expected canonical tool risks {EXPECTED_TOOL_RISKS!r}",
            )


def check_provider_costs(document: dict[str, Any]) -> None:
    path = CONTRACTS / "providers" / "cost-conformance.json"
    if set(document) != {
        "$schema",
        "contractVersion",
        "arithmetic",
        "cases",
        "invalidTokenCounts",
        "invalidRates",
    }:
        raise fail(path, "/", "invalid provider cost fixture envelope")
    if document["contractVersion"] != "1.0.0":
        raise fail(path, "/contractVersion", "expected 1.0.0")
    if document["arithmetic"] != {
        "currency": "USD",
        "tokensPerRateUnit": 1_000_000,
        "fractionalDigits": 10,
        "rounding": "half_even",
        "tokenMaximum": SAFE_JSON_INTEGER_MAX,
        "conversion": "canonical_decimal_to_host_number",
        "rateSyntax": {
            "form": "canonical_non_negative_decimal_or_single_digit_scientific_ascii",
            "maxSignificantDigits": PROVIDER_RATE_MAX_SIGNIFICANT_DIGITS,
            "maxFractionalDigits": PROVIDER_RATE_MAX_FRACTIONAL_DIGITS,
            "maxAbsoluteExponent": PROVIDER_RATE_MAX_ABSOLUTE_EXPONENT,
        },
    }:
        raise fail(path, "/arithmetic", "invalid provider cost arithmetic contract")

    cases = document["cases"]
    if not isinstance(cases, list) or not cases:
        raise fail(path, "/cases", "expected a non-empty array")
    names: list[str] = []
    canonical_pattern = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{0,9}[1-9])?\Z")
    for index, case in enumerate(cases):
        location = f"/cases/{index}"
        if not isinstance(case, dict):
            raise fail(path, location, "expected an object")
        common = {
            "name",
            "inputTokens",
            "outputTokens",
            "expectedCanonicalUsd",
        }
        if set(case) not in (common | {"model"}, common | {"rates"}):
            raise fail(path, location, "expected exactly one model or rates field")
        name = case["name"]
        if not isinstance(name, str) or not name:
            raise fail(path, f"{location}/name", "expected a non-empty string")
        names.append(name)
        for field in ("inputTokens", "outputTokens"):
            value = case[field]
            if type(value) is not int or not 0 <= value <= SAFE_JSON_INTEGER_MAX:
                raise fail(
                    path,
                    f"{location}/{field}",
                    "expected a non-negative I-JSON safe integer",
                )
        expected = case["expectedCanonicalUsd"]
        if (
            not isinstance(expected, str)
            or canonical_pattern.fullmatch(expected) is None
        ):
            raise fail(
                path,
                f"{location}/expectedCanonicalUsd",
                "expected canonical USD with at most 10 fractional digits",
            )
        if "model" in case:
            if not isinstance(case["model"], str) or not case["model"]:
                raise fail(path, f"{location}/model", "expected a non-empty string")
        else:
            rates = case["rates"]
            if not isinstance(rates, dict) or set(rates) != {
                "inputPer1M",
                "outputPer1M",
            }:
                raise fail(path, f"{location}/rates", "invalid rate pair")
            for field, value in rates.items():
                if not isinstance(value, str) or not provider_rate_is_valid(value):
                    raise fail(
                        path,
                        f"{location}/rates/{field}",
                        "expected a bounded canonical non-negative rate",
                    )
    if names != REQUIRED_PROVIDER_COST_CASES:
        raise fail(path, "/cases", "provider cost cases or order differ")

    invalid = document["invalidTokenCounts"]
    expected_invalid = (
        ("negative", -1, int),
        ("fractional", 0.5, float),
        ("boolean", True, bool),
        ("unsafe", SAFE_JSON_INTEGER_MAX + 1, int),
    )
    if not isinstance(invalid, list) or len(invalid) != len(expected_invalid):
        raise fail(path, "/invalidTokenCounts", "invalid token fixtures differ")
    for index, (case, (name, value, value_type)) in enumerate(
        zip(invalid, expected_invalid, strict=True)
    ):
        location = f"/invalidTokenCounts/{index}"
        if not isinstance(case, dict) or set(case) != {"name", "value"}:
            raise fail(path, location, "invalid token fixture envelope")
        if (
            case["name"] != name
            or type(case["value"]) is not value_type
            or case["value"] != value
        ):
            raise fail(path, location, "invalid token fixture differs")

    invalid_rates = document["invalidRates"]
    if not isinstance(invalid_rates, list) or len(invalid_rates) != len(
        REQUIRED_INVALID_PROVIDER_RATES
    ):
        raise fail(path, "/invalidRates", "invalid rate fixtures differ")
    for index, (case, expected) in enumerate(
        zip(invalid_rates, REQUIRED_INVALID_PROVIDER_RATES, strict=True)
    ):
        location = f"/invalidRates/{index}"
        if not isinstance(case, dict) or set(case) != {"name", "kind", "value"}:
            raise fail(path, location, "invalid rate fixture envelope")
        actual = (case["name"], case["kind"], case["value"])
        if actual != expected:
            raise fail(path, location, "invalid rate fixture differs")
        if provider_rate_is_valid(case["value"]):
            raise fail(path, f"{location}/value", "invalid rate fixture is valid")


def load_contract_documents() -> dict[str, dict[str, Any]]:
    paths = sorted(CONTRACTS.rglob("*.json"))
    relative_paths = {path.relative_to(CONTRACTS).as_posix() for path in paths}
    missing = sorted(REQUIRED_JSON - relative_paths)
    if missing:
        raise fail(CONTRACTS, "/", f"missing canonical JSON: {', '.join(missing)}")

    documents: dict[str, dict[str, Any]] = {}
    schema_ids: dict[str, Path] = {}
    for path in paths:
        relative = path.relative_to(CONTRACTS).as_posix()
        document = load_json(path)
        if relative == "parity/scenarios.json":
            if document.get("$schema") != "./scenarios.schema.json":
                raise fail(path, "/$schema", "expected './scenarios.schema.json'")
            documents[relative] = document
            continue
        if relative in DATA_DOCUMENTS:
            documents[relative] = document
            continue
        if document.get("$schema") != DRAFT_2020_12:
            raise fail(path, "/$schema", f"expected {DRAFT_2020_12!r}")
        error = check_schema(document)
        if error is not None:
            raise fail(path, pointer(error.absolute_path), error.message)
        if path.name.endswith(".schema.json"):
            schema_id = document.get("$id")
            if not isinstance(schema_id, str) or not schema_id:
                raise fail(path, "/$id", "schema document requires a non-empty $id")
            if schema_id in schema_ids:
                raise fail(
                    path,
                    "/$id",
                    f"duplicate schema id also used by {schema_ids[schema_id]}",
                )
            schema_ids[schema_id] = path
        documents[relative] = document
    return documents


def check_parity(documents: dict[str, dict[str, Any]]) -> None:
    scenarios_path = CONTRACTS / "parity" / "scenarios.json"
    expected_path = CONTRACTS / "parity" / "expected-normalized.json"
    scenarios = documents["parity/scenarios.json"]
    schema = documents["parity/scenarios.schema.json"]
    validate_instance(scenarios_path, "/", schema, scenarios)

    normalization = scenarios["normalization"]
    required_normalization = {
        "stripKeys": ["timestamp", "duration_ms"],
        "replaceKeys": {
            "request_id": "<request>",
            "trace_id": "<trace>",
        },
        "preserveKeys": [
            "id",
            "sequence",
            "turn_id",
            "tool_call_id",
            "error_code",
        ],
    }
    if normalization != required_normalization:
        raise fail(
            scenarios_path,
            "/normalization",
            "normalization must remain the production-beta allowlist",
        )

    rows = scenarios["scenarios"]
    scenario_ids = [row["id"] for row in rows]
    if len(scenario_ids) != len(set(scenario_ids)):
        raise fail(scenarios_path, "/scenarios", "scenario ids must be unique")
    controls = set(scenarios["controlSets"])
    for index, row in enumerate(rows):
        control = row.get("controls")
        if control is not None and control not in controls:
            raise fail(
                scenarios_path,
                f"/scenarios/{index}/controls",
                f"unknown control set {control!r}",
            )

    referenced_tool_cases = {
        (row["fixtureFile"], row["fixture"])
        for row in rows
        if row["kind"] == "tool-schema"
    }
    canonical_tool_cases = {
        (filename, case["name"])
        for filename in ("conformance-valid.json", "conformance-invalid.json")
        for case in documents[f"tools/{filename}"]["cases"]
    }
    if referenced_tool_cases != canonical_tool_cases:
        missing = sorted(canonical_tool_cases - referenced_tool_cases)
        extra = sorted(referenced_tool_cases - canonical_tool_cases)
        raise fail(
            scenarios_path,
            "/scenarios",
            f"tool fixture coverage mismatch; missing={missing}, extra={extra}",
        )

    expected = documents["parity/expected-normalized.json"]
    if expected.get("version") != scenarios["version"]:
        raise fail(expected_path, "/version", "must match scenario contract version")
    snapshots = expected.get("scenarios")
    if not isinstance(snapshots, list):
        raise fail(expected_path, "/scenarios", "expected an array")
    expected_ids = [item.get("id") for item in snapshots if isinstance(item, dict)]
    if expected_ids != scenario_ids:
        raise fail(
            expected_path,
            "/scenarios",
            "snapshot ids must exactly match scenario file order",
        )
    snapshot_keys = {
        "events",
        "operation_trace",
        "provider_requests",
        "provider_responses",
        "replay",
        "result",
    }
    known_error_codes = set(documents["errors/error-codes.json"]["codes"])
    for index, item in enumerate(snapshots):
        if not isinstance(item, dict) or set(item) != {"id", "snapshot"}:
            raise fail(
                expected_path, f"/scenarios/{index}", "invalid scenario envelope"
            )
        snapshot = item["snapshot"]
        if not isinstance(snapshot, dict) or set(snapshot) != snapshot_keys:
            raise fail(
                expected_path,
                f"/scenarios/{index}/snapshot",
                "incomplete snapshot envelope",
            )
        result = snapshot["result"]
        if not isinstance(result, dict):
            raise fail(
                expected_path,
                f"/scenarios/{index}/snapshot/result",
                "expected an object",
            )
        provider_error = result.get("provider_error")
        if provider_error is None:
            continue
        required_error_keys = {
            "type",
            "code",
            "service",
            "action",
            "status",
            "retryable",
        }
        if (
            not isinstance(provider_error, dict)
            or set(provider_error) != required_error_keys
        ):
            raise fail(
                expected_path,
                f"/scenarios/{index}/snapshot/result/provider_error",
                "invalid normalized provider error envelope",
            )
        if provider_error["code"] not in known_error_codes:
            raise fail(
                expected_path,
                f"/scenarios/{index}/snapshot/result/provider_error/code",
                f"unknown code {provider_error['code']!r}",
            )
        if provider_error["type"] not in {
            "api",
            "auth",
            "config",
            "network",
            "rate_limit",
        }:
            raise fail(
                expected_path,
                f"/scenarios/{index}/snapshot/result/provider_error/type",
                f"unknown provider error type {provider_error['type']!r}",
            )
        for field in ("service", "action"):
            if not isinstance(provider_error[field], str) or not provider_error[field]:
                raise fail(
                    expected_path,
                    f"/scenarios/{index}/snapshot/result/provider_error/{field}",
                    "expected a non-empty string",
                )
        status = provider_error["status"]
        if status is not None and (
            not isinstance(status, int) or isinstance(status, bool)
        ):
            raise fail(
                expected_path,
                f"/scenarios/{index}/snapshot/result/provider_error/status",
                "expected an integer or null",
            )
        if not isinstance(provider_error["retryable"], bool):
            raise fail(
                expected_path,
                f"/scenarios/{index}/snapshot/result/provider_error/retryable",
                "expected a boolean",
            )


def check_packaged_contracts() -> None:
    expected = {
        path.relative_to(CONTRACTS)
        for path in CONTRACTS.rglob("*")
        if path.is_file() and path.suffix in {".json", ".md"}
    }
    for target in PACKAGE_CONTRACT_TARGETS:
        actual = {
            path.relative_to(target)
            for path in target.rglob("*")
            if path.is_file() and path.suffix in {".json", ".md"}
        }
        if actual != expected:
            missing = sorted(path.as_posix() for path in expected - actual)
            extra = sorted(path.as_posix() for path in actual - expected)
            raise fail(
                target,
                "/",
                f"packaged contract set mismatch; missing={missing}, extra={extra}",
            )
        for relative in sorted(expected):
            if (target / relative).read_bytes() != (CONTRACTS / relative).read_bytes():
                raise fail(target / relative, "/", "packaged contract is out of sync")


def check_github_typescript_abi(documents: dict[str, dict[str, Any]]) -> None:
    relative = "integrations/github-tool-abi-typescript-v1.json"
    path = CONTRACTS / relative
    document = documents[relative]
    if set(document) != {
        "$schema",
        "schema_version",
        "catalog_version",
        "namespace",
        "tools",
    }:
        raise fail(path, "/", "expected the closed TypeScript GitHub ABI envelope")
    if document.get("schema_version") != "1.0.0":
        raise fail(path, "/schema_version", "expected '1.0.0'")
    if document.get("catalog_version") != "0.2.0":
        raise fail(path, "/catalog_version", "expected '0.2.0'")
    if document.get("namespace") != "github":
        raise fail(path, "/namespace", "expected 'github'")

    tools = document.get("tools")
    if not isinstance(tools, list):
        raise fail(path, "/tools", "expected an array")
    names = [tool.get("name") if isinstance(tool, dict) else None for tool in tools]
    if names != GITHUB_TYPESCRIPT_TOOL_NAMES:
        raise fail(path, "/tools", "TypeScript GitHub package tool order differs")
    if len(names) != len(set(names)):
        raise fail(path, "/tools", "TypeScript GitHub package tools are not unique")

    shared_tools = documents["integrations/github-tool-abi-v1.json"]["tools"]
    if tools[:6] != shared_tools:
        raise fail(path, "/tools", "shared-six prefix differs from the cross-SDK ABI")

    repository = {
        "type": "string",
        "pattern": "^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$",
    }
    safe_id = {
        "type": "integer",
        "minimum": 1,
        "maximum": SAFE_JSON_INTEGER_MAX,
    }
    page = {"type": "integer", "minimum": 1, "maximum": 1000, "default": 1}
    per_page = {"type": "integer", "minimum": 1, "maximum": 20, "default": 10}
    ref = {"type": "string", "minLength": 1, "maxLength": 100}
    path_value = {"type": "string", "minLength": 1, "maxLength": 512}
    filter_value = {
        "type": "string",
        "enum": ["latest", "all"],
        "default": "latest",
    }

    def parameters(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
        return {
            "$schema": DRAFT_2020_12,
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }

    expected_parameters = {
        "get_commit": parameters(
            {"repository": repository, "ref": ref, "page": page, "per_page": per_page},
            ["repository", "ref"],
        ),
        "get_pull_request": parameters(
            {"repository": repository, "pull_number": safe_id},
            ["repository", "pull_number"],
        ),
        "list_pull_request_files": parameters(
            {
                "repository": repository,
                "pull_number": safe_id,
                "page": page,
                "per_page": per_page,
            },
            ["repository", "pull_number"],
        ),
        "list_check_runs": parameters(
            {
                "repository": repository,
                "ref": ref,
                "filter": filter_value,
                "page": page,
                "per_page": per_page,
            },
            ["repository", "ref"],
        ),
        "get_workflow_run": parameters(
            {"repository": repository, "run_id": safe_id},
            ["repository", "run_id"],
        ),
        "list_workflow_jobs": parameters(
            {
                "repository": repository,
                "run_id": safe_id,
                "filter": filter_value,
                "page": page,
                "per_page": per_page,
            },
            ["repository", "run_id"],
        ),
        "list_file_commits": parameters(
            {
                "repository": repository,
                "path": path_value,
                "ref": ref,
                "page": page,
                "per_page": per_page,
            },
            ["repository", "path"],
        ),
        "get_release": parameters(
            {"repository": repository, "tag": ref},
            ["repository", "tag"],
        ),
        "list_deployments": parameters(
            {
                "repository": repository,
                "ref": ref,
                "sha": {"type": "string", "pattern": "^[0-9A-Fa-f]{1,64}$"},
                "environment": ref,
                "task": ref,
                "page": page,
                "per_page": per_page,
            },
            ["repository"],
        ),
    }
    for index, name in enumerate(GITHUB_TYPESCRIPT_EXTENSION_NAMES, start=6):
        tool = tools[index]
        location = f"/tools/{index}"
        if not isinstance(tool, dict) or set(tool) != {
            "name",
            "description",
            "parameters",
            "risk",
            "parallel_safe",
            "timeout_ms",
        }:
            raise fail(path, location, "invalid TypeScript extension tool envelope")
        if not isinstance(tool["description"], str) or not tool["description"]:
            raise fail(path, f"{location}/description", "expected a non-empty string")
        if tool["parameters"] != expected_parameters[name]:
            raise fail(
                path, f"{location}/parameters", "extension parameter schema differs"
            )
        if (
            tool["risk"] != "read"
            or tool["parallel_safe"] is not True
            or tool["timeout_ms"] != 10000
        ):
            raise fail(path, location, "extension read invariants differ")
        schema_issue = parameter_schema_issue(tool["parameters"])
        if schema_issue is not None:
            raise fail(
                path,
                f"{location}/parameters{pointer(schema_issue)}",
                "invalid parameter schema",
            )
        schema_error = check_schema(tool["parameters"])
        if schema_error is not None:
            raise fail(
                path,
                f"{location}/parameters{pointer(schema_error.absolute_path)}",
                "invalid parameter schema",
            )

    for manifest_path in (
        ROOT / "kaji" / "ts" / "registry" / "github" / "manifest.json",
        ROOT
        / "kaji"
        / "src"
        / "kaji"
        / "integrations"
        / "registry"
        / "github"
        / "manifest.json",
    ):
        manifest = load_json(manifest_path)
        manifest_tools = manifest.get("tools")
        if manifest.get("version") != "0.1.0" or manifest_tools != shared_tools:
            raise fail(
                manifest_path,
                "/tools",
                "copied GitHub manifest must remain 0.1.0 with the shared six tools",
            )


def validate_instance(
    path: Path, location: str, schema: dict[str, Any], value: Any
) -> None:
    error = first_error(
        Draft202012Validator(schema, format_checker=FormatChecker()), value
    )
    if error is not None:
        suffix = pointer(error.absolute_path)
        joined = location.rstrip("/") + (suffix if suffix != "/" else "")
        raise fail(path, joined or "/", error.message)


def error_codes(documents: dict[str, dict[str, Any]]) -> set[str]:
    path = CONTRACTS / "errors" / "error-codes.json"
    codes = documents["errors/error-codes.json"].get("codes")
    if (
        not isinstance(codes, list)
        or not codes
        or not all(isinstance(code, str) for code in codes)
    ):
        raise fail(path, "/codes", "expected a non-empty array of strings")
    if len(codes) != len(set(codes)):
        raise fail(path, "/codes", "error codes must be unique")
    return set(codes)


def integration_recovery_entries(
    document: dict[str, Any], codes: set[str]
) -> dict[str, dict[str, str]]:
    path = CONTRACTS / "errors" / "integration-recovery-v1.json"
    if set(document) != {"$schema", "$id", "version", "entries"}:
        raise fail(path, "/", "unexpected integration recovery contract fields")
    if document.get("version") != "1.0.0":
        raise fail(path, "/version", "expected 1.0.0")
    entries = document.get("entries")
    if not isinstance(entries, dict) or not entries:
        raise fail(path, "/entries", "expected a non-empty object")
    expected_fields = {
        "errorCode",
        "recoveryCode",
        "docUrl",
        "problem",
        "cause",
        "fix",
    }
    for reason, entry in entries.items():
        location = f"/entries/{reason}"
        if (
            not isinstance(reason, str)
            or re.fullmatch(r"[a-z][a-z0-9_]*", reason) is None
        ):
            raise fail(path, location, "expected a stable snake-case reason")
        if not isinstance(entry, dict) or set(entry) != expected_fields:
            raise fail(path, location, "unexpected recovery fields")
        if entry["errorCode"] not in codes:
            raise fail(path, f"{location}/errorCode", "unknown error code")
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", entry["recoveryCode"]) is None:
            raise fail(path, f"{location}/recoveryCode", "invalid recovery code")
        if not entry["docUrl"].startswith(
            "https://kaji.dev/docs/integrations/recovery-v1#"
        ):
            raise fail(path, f"{location}/docUrl", "unexpected documentation origin")
        for field in ("problem", "cause", "fix"):
            value = entry[field]
            if not isinstance(value, str) or not value or "{" in value or "}" in value:
                raise fail(
                    path, f"{location}/{field}", "expected fixed redaction-safe text"
                )
    from kaji.contracts.integration_recovery import (  # noqa: PLC0415
        INTEGRATION_RECOVERY,
    )

    runtime_entries = {
        reason: {
            "errorCode": recovery.error_code,
            "recoveryCode": recovery.recovery_code,
            "docUrl": recovery.doc_url,
            "problem": recovery.problem,
            "cause": recovery.cause,
            "fix": recovery.fix,
        }
        for reason, recovery in INTEGRATION_RECOVERY.items()
    }
    if entries != runtime_entries:
        raise fail(path, "/entries", "Python recovery map differs from the contract")
    return entries


def runtime_event_types() -> set[str]:
    python_source = (
        ROOT / "kaji" / "src" / "kaji" / "infra" / "events" / "types.py"
    ).read_text()
    typescript_source = (
        ROOT / "kaji" / "ts" / "src" / "events" / "types.ts"
    ).read_text()
    python_types = set(
        re.findall(r'^\s+[A-Z_]+\s*=\s*"([^"]+)"', python_source, re.MULTILINE)
    )
    typescript_types = set(
        re.findall(r'^\s+[A-Z_]+:\s*"([^"]+)"', typescript_source, re.MULTILINE)
    )
    if python_types != typescript_types:
        raise fail(
            ROOT / "kaji",
            "/events/EventType",
            f"runtime EventType drift; python={sorted(python_types)}, typescript={sorted(typescript_types)}",
        )
    return python_types


def _event_schema_def_name(event_type: str) -> str:
    head, *tail = event_type.split(".")
    return head + "".join(part.title() for part in tail)


def _event_schema_union_discriminants(path: Path, schema: dict[str, Any]) -> list[str]:
    union = schema.get("oneOf")
    definitions = schema.get("$defs")
    if not isinstance(union, list) or not union:
        raise fail(path, "/oneOf", "expected a non-empty event union")
    if not isinstance(definitions, dict):
        raise fail(path, "/$defs", "expected event definitions")

    discriminants: list[str] = []
    prefix = "#/$defs/"
    for index, member in enumerate(union):
        location = f"/oneOf/{index}"
        if (
            not isinstance(member, dict)
            or set(member) != {"$ref"}
            or not isinstance(member["$ref"], str)
            or not member["$ref"].startswith(prefix)
        ):
            raise fail(path, location, "expected one local event-variant reference")
        definition_name = member["$ref"][len(prefix) :]
        variant = definitions.get(definition_name)
        try:
            event_type = variant["allOf"][1]["properties"]["type"]["const"]
        except (KeyError, IndexError, TypeError):
            raise fail(
                path,
                location,
                "event union member requires one literal type discriminant",
            ) from None
        if not isinstance(event_type, str) or not event_type:
            raise fail(path, location, "event type discriminant must be non-empty")
        discriminants.append(event_type)
    return discriminants


def _event_schema_for_parity(
    path: Path, schema: dict[str, Any], *, stored: bool
) -> dict[str, Any]:
    normalized = deepcopy(schema)
    normalized.pop("$id", None)
    normalized.pop("title", None)
    definitions = normalized.get("$defs")
    union = normalized.get("oneOf")
    if not isinstance(definitions, dict) or not isinstance(union, list):
        raise fail(path, "/", "event schema requires $defs and oneOf")
    base = definitions.get("base")
    if not isinstance(base, dict):
        raise fail(path, "/$defs/base", "missing event base definition")
    properties = base.get("properties")
    required = base.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise fail(path, "/$defs/base", "event base requires properties and required")

    if stored:
        if properties.pop("sequence", None) != {"$ref": "#/$defs/positiveInteger"}:
            raise fail(
                path,
                "/$defs/base/properties/sequence",
                "stored events require the canonical sequence definition",
            )
        if required.count("sequence") != 1:
            raise fail(
                path,
                "/$defs/base/required",
                "stored events must require sequence exactly once",
            )
        base["required"] = [field for field in required if field != "sequence"]
    elif "sequence" in properties or "sequence" in required:
        raise fail(
            path,
            "/$defs/base",
            "new events must not define or require sequence",
        )
    return normalized


def check_event_schema_structure(
    new_schema: dict[str, Any],
    stored_schema: dict[str, Any],
    event_types: set[str],
) -> None:
    schemas = (
        (CONTRACTS / "events" / "new-kaji-event-v1.schema.json", new_schema),
        (CONTRACTS / "events" / "stored-kaji-event-v1.schema.json", stored_schema),
    )
    for path, schema in schemas:
        discriminants = _event_schema_union_discriminants(path, schema)
        actual = set(discriminants)
        if len(discriminants) != len(actual) or actual != event_types:
            raise fail(
                path,
                "/oneOf",
                "oneOf discriminants must exactly match runtime EventType; "
                f"missing={sorted(event_types - actual)}, "
                f"extra={sorted(actual - event_types)}",
            )

    new_structure = _event_schema_for_parity(schemas[0][0], new_schema, stored=False)
    stored_structure = _event_schema_for_parity(
        schemas[1][0], stored_schema, stored=True
    )
    if new_structure != stored_structure:
        raise fail(
            schemas[1][0],
            "/",
            "new/stored event schema structural parity differs beyond sequence",
        )


def _flatten_validation_errors(error: ValidationError) -> list[ValidationError]:
    result = [error]
    for child in error.context:
        result.extend(_flatten_validation_errors(child))
    return result


def _normalized_event_error(error: ValidationError) -> str:
    parts = list(error.absolute_path)
    if error.validator == "required" and isinstance(error.instance, dict):
        missing = next(
            (field for field in error.validator_value if field not in error.instance),
            None,
        )
        if missing is not None:
            parts.append(missing)
    elif error.validator in {"additionalProperties", "unevaluatedProperties"}:
        unexpected = sorted(set(re.findall(r"'([^']+)'", error.message)))
        if unexpected:
            parts.append(unexpected[0])
    return pointer(parts)


def event_validation_pointer(
    schema: dict[str, Any], value: Any, *, stored: bool, event_types: set[str]
) -> str | None:
    if not isinstance(value, dict):
        return "/"
    for field in ("id", "version", "timestamp", "type", "session_id"):
        if field not in value:
            return f"/{field}"
    for field in ("id", "session_id", "turn_id"):
        if value.get(field) == "":
            return f"/{field}"
    if stored and "sequence" not in value:
        return "/sequence"
    if not stored and "sequence" in value:
        return "/sequence"
    event_type = value.get("type")
    if event_type not in event_types:
        return "/type"

    variant = schema["$defs"][_event_schema_def_name(event_type)]
    allowed = set(schema["$defs"]["base"]["properties"])
    allowed.update(variant["allOf"][1]["properties"])
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        return pointer([unexpected[0]])

    recovery_fields = tuple(
        value.get(field) for field in ("reason_code", "recovery_code", "doc_url")
    )
    if any(field is not None for field in recovery_fields):
        recovery_validator = Draft202012Validator(
            schema["$defs"]["integrationRecoveryFields"]
        )
        if not recovery_validator.is_valid(value):
            return "/reason_code"

    validator = Draft202012Validator(
        {
            "$schema": DRAFT_2020_12,
            "$defs": schema["$defs"],
            "$ref": f"#/$defs/{_event_schema_def_name(event_type)}",
        },
        format_checker=FormatChecker(),
    )
    errors = list(validator.iter_errors(value))
    if not errors:
        return None
    candidates = [
        _normalized_event_error(item)
        for error in errors
        for item in _flatten_validation_errors(error)
        if item.validator not in {"allOf", "oneOf", "unevaluatedProperties"}
    ]
    return min(candidates, key=lambda item: (item == "/", item)) if candidates else "/"


def check_events(
    documents: dict[str, dict[str, Any]],
    codes: set[str],
    recoveries: dict[str, dict[str, str]] | None = None,
) -> None:
    if recoveries is None:
        recoveries = integration_recovery_entries(
            documents["errors/integration-recovery-v1.json"], codes
        )
    path = CONTRACTS / "events" / "conformance.json"
    events = documents["events/conformance.json"].get("events")
    if not isinstance(events, list) or not events:
        raise fail(path, "/events", "expected a non-empty array")

    event_types = runtime_event_types()
    fixture_types = {event.get("type") for event in events if isinstance(event, dict)}
    if fixture_types != event_types:
        raise fail(
            path,
            "/events",
            "event fixture coverage mismatch; "
            f"missing={sorted(event_types - fixture_types)}, "
            f"extra={sorted(fixture_types - event_types)}",
        )

    new_schema = documents["events/new-kaji-event-v1.schema.json"]
    stored_schema = documents["events/stored-kaji-event-v1.schema.json"]
    check_event_schema_structure(new_schema, stored_schema, event_types)
    new_validator = Draft202012Validator(new_schema, format_checker=FormatChecker())
    stored_validator = Draft202012Validator(
        stored_schema, format_checker=FormatChecker()
    )
    ids: set[str] = set()
    last_sequences: dict[str, int] = {}
    tool_requests: dict[tuple[str, str, str, str], tuple[int, dict[str, Any]]] = {}
    tool_terminals: dict[
        tuple[str, str, str, str], list[tuple[int, dict[str, Any]]]
    ] = {}
    approval_requests: dict[tuple[str, str, str, str], tuple[int, dict[str, Any]]] = {}
    approval_decisions: dict[tuple[str, str, str, str], tuple[int, dict[str, Any]]] = {}
    tool_failures: dict[
        tuple[str, str, str, str], list[tuple[int, dict[str, Any]]]
    ] = {}
    for index, event in enumerate(events):
        location = f"/events/{index}"
        error = first_error(stored_validator, event)
        if error is not None:
            raise fail(path, location + pointer(error.absolute_path), error.message)
        event_id = event["id"]
        if event_id in ids:
            raise fail(path, f"{location}/id", "duplicate event id")
        ids.add(event_id)
        previous_sequence = last_sequences.get(event["session_id"], 0)
        expected_sequence = previous_sequence + 1
        if event["sequence"] != expected_sequence:
            raise fail(
                path,
                f"{location}/sequence",
                f"expected contiguous session sequence {expected_sequence}",
            )
        last_sequences[event["session_id"]] = event["sequence"]

        draft = dict(event)
        draft.pop("sequence")
        validate_instance(path, location, new_schema, draft)
        if first_error(new_validator, event) is None:
            raise fail(
                path, f"{location}/sequence", "new-event schema must reject sequence"
            )
        if first_error(stored_validator, draft) is None:
            raise fail(path, location, "stored-event schema must require sequence")

        code = event.get("error_code")
        if code is not None and code not in codes:
            raise fail(path, f"{location}/error_code", f"unknown code {code!r}")
        event_type = event.get("type")
        if event_type in {
            "tool.call.requested",
            "tool.call.completed",
            "tool.call.failed",
        } and all(
            isinstance(event.get(field), str) and event[field]
            for field in ("turn_id", "tool_call_id", "tool_name")
        ):
            key = (
                event["session_id"],
                event["turn_id"],
                event["tool_call_id"],
                event["tool_name"],
            )
            if event_type == "tool.call.requested":
                if key in tool_requests:
                    raise fail(path, location, "duplicate tool request key")
                tool_requests[key] = (index, event)
            else:
                tool_terminals.setdefault(key, []).append((index, event))

        if event_type == "tool.call.failed":
            if not isinstance(event.get("retryable"), bool):
                raise fail(path, f"{location}/retryable", "expected a boolean")
            if event.get("outcome") not in {"not_started", "failed", "unknown"}:
                raise fail(path, f"{location}/outcome", "unknown tool outcome")
            recovery_values = tuple(
                event.get(field)
                for field in ("reason_code", "recovery_code", "doc_url")
            )
            if any(value is not None for value in recovery_values):
                reason_code, recovery_code, doc_url = recovery_values
                recovery = recoveries.get(reason_code)
                if recovery is None or (
                    recovery_code,
                    doc_url,
                    event.get("error_code"),
                ) != (
                    recovery["recoveryCode"],
                    recovery["docUrl"],
                    recovery["errorCode"],
                ):
                    raise fail(
                        path,
                        f"{location}/reason_code",
                        "integration recovery tuple differs from the closed contract",
                    )
            if all(
                isinstance(event.get(field), str) and event[field]
                for field in ("turn_id", "tool_call_id", "tool_name")
            ):
                key = (
                    event["session_id"],
                    event["turn_id"],
                    event["tool_call_id"],
                    event["tool_name"],
                )
                tool_failures.setdefault(key, []).append((index, event))

        if event_type in {
            "tool.approval.requested",
            "tool.approval.approved",
            "tool.approval.rejected",
        }:
            key = (
                event["session_id"],
                event["turn_id"],
                event["tool_call_id"],
                event["tool_name"],
            )
            if event_type == "tool.approval.requested":
                if key in approval_requests:
                    raise fail(path, location, "duplicate approval request key")
                tool_request = tool_requests.get(key)
                if tool_request is None:
                    raise fail(
                        path, location, "approval request has no prior tool request"
                    )
                if event["sequence"] <= tool_request[1]["sequence"]:
                    raise fail(
                        path,
                        f"{location}/sequence",
                        "approval request precedes tool request",
                    )
                approval_requests[key] = (index, event)
                continue

            requested = approval_requests.get(key)
            if requested is None:
                raise fail(path, location, "approval decision has no prior request")
            if event["sequence"] <= requested[1]["sequence"]:
                raise fail(
                    path, f"{location}/sequence", "approval decision precedes request"
                )
            if key in approval_decisions:
                raise fail(path, location, "duplicate approval decision key")
            approval_decisions[key] = (index, event)

            if event_type == "tool.approval.rejected":
                code = event["error_code"]
                if code not in APPROVAL_FAILURE_RETRYABILITY:
                    raise fail(path, f"{location}/error_code", "unknown approval code")

    missing_decisions = approval_requests.keys() - approval_decisions.keys()
    if missing_decisions:
        request_index, _ = approval_requests[sorted(missing_decisions)[0]]
        raise fail(path, f"/events/{request_index}", "approval request has no decision")
    unexpected_decisions = approval_decisions.keys() - approval_requests.keys()
    if unexpected_decisions:
        decision_index, _ = approval_decisions[sorted(unexpected_decisions)[0]]
        raise fail(
            path, f"/events/{decision_index}", "approval decision has no request"
        )

    for key, (decision_index, decision) in approval_decisions.items():
        terminals = tool_terminals.get(key, [])
        if len(terminals) != 1:
            raise fail(
                path,
                f"/events/{decision_index}",
                "approval decision requires exactly one matching tool terminal",
            )
        terminal_index, terminal = terminals[0]
        if terminal["sequence"] <= decision["sequence"]:
            raise fail(
                path,
                f"/events/{terminal_index}/sequence",
                "tool terminal must follow approval decision",
            )

        if decision.get("type") != "tool.approval.rejected":
            continue
        matching = tool_failures.get(key, [])
        if len(matching) != 1:
            raise fail(
                path,
                f"/events/{decision_index}",
                "approval rejection requires exactly one matching tool failure",
            )
        failure_index, failure = matching[0]
        code = decision["error_code"]
        if failure.get("error_code") != code:
            raise fail(
                path,
                f"/events/{failure_index}/error_code",
                "approval rejection and tool failure codes differ",
            )
        if failure.get("retryable") is not APPROVAL_FAILURE_RETRYABILITY[code]:
            raise fail(
                path,
                f"/events/{failure_index}/retryable",
                "approval failure retryability does not match its code",
            )
        if failure.get("outcome") != "not_started":
            raise fail(
                path,
                f"/events/{failure_index}/outcome",
                "approval failure must be not_started",
            )

    for key, failures in tool_failures.items():
        for failure_index, failure in failures:
            if failure.get("error_code") not in APPROVAL_FAILURE_RETRYABILITY:
                continue
            decision = approval_decisions.get(key)
            if decision is None or decision[1].get("type") != "tool.approval.rejected":
                raise fail(
                    path,
                    f"/events/{failure_index}/error_code",
                    "approval-coded tool failure has no matching rejection",
                )

    invalid_path = CONTRACTS / "events" / "conformance-invalid.json"
    invalid_cases = documents["events/conformance-invalid.json"].get("cases")
    if not isinstance(invalid_cases, list) or not invalid_cases:
        raise fail(invalid_path, "/cases", "expected a non-empty array")
    names: set[str] = set()
    for index, case in enumerate(invalid_cases):
        location = f"/cases/{index}"
        if not isinstance(case, dict) or set(case) != {
            "name",
            "kind",
            "event",
            "path",
        }:
            raise fail(invalid_path, location, "invalid event fixture envelope")
        name = case["name"]
        if not isinstance(name, str) or not name or name in names:
            raise fail(
                invalid_path, f"{location}/name", "expected a unique non-empty name"
            )
        names.add(name)
        kind = case["kind"]
        if kind not in {"new", "stored"}:
            raise fail(invalid_path, f"{location}/kind", "expected new or stored")
        expected_path = case["path"]
        if (
            not isinstance(expected_path, str)
            or not expected_path.startswith("/")
            or re.search(r"~(?:[^01]|$)", expected_path) is not None
        ):
            raise fail(
                invalid_path, f"{location}/path", "expected a normalized JSON pointer"
            )
        schema = stored_schema if kind == "stored" else new_schema
        actual_path = event_validation_pointer(
            schema,
            case["event"],
            stored=kind == "stored",
            event_types=event_types,
        )
        if actual_path is None:
            raise fail(
                invalid_path, f"{location}/event", "expected event to fail validation"
            )
        if actual_path != expected_path:
            raise fail(
                invalid_path,
                f"{location}/path",
                f"expected {expected_path!r}, normalized first error is {actual_path!r}",
            )
    missing_required = REQUIRED_EVENT_NEGATIVE_CASES - names
    if missing_required:
        raise fail(
            invalid_path,
            "/cases",
            "missing required negative cases: " + ", ".join(sorted(missing_required)),
        )


def check_tools(documents: dict[str, dict[str, Any]], codes: set[str]) -> None:
    valid_path = CONTRACTS / "tools" / "conformance-valid.json"
    valid_cases = documents["tools/conformance-valid.json"].get("cases")
    if not isinstance(valid_cases, list) or not valid_cases:
        raise fail(valid_path, "/cases", "expected a non-empty array")
    for index, case in enumerate(valid_cases):
        schema = case.get("schema")
        schema_error = check_schema(schema)
        if schema_error is not None:
            raise fail(
                valid_path,
                f"/cases/{index}/schema{pointer(schema_error.absolute_path)}",
                schema_error.message,
            )
        error = first_error(
            Draft202012Validator(schema, format_checker=FormatChecker()),
            case.get("arguments"),
        )
        if error is not None:
            raise fail(
                valid_path,
                f"/cases/{index}/arguments{pointer(error.absolute_path)}",
                error.message,
            )

    invalid_path = CONTRACTS / "tools" / "conformance-invalid.json"
    invalid_cases = documents["tools/conformance-invalid.json"].get("cases")
    if not isinstance(invalid_cases, list) or not invalid_cases:
        raise fail(invalid_path, "/cases", "expected a non-empty array")
    for index, case in enumerate(invalid_cases):
        base = f"/cases/{index}"
        expected_code = case.get("expectedCode")
        if expected_code not in codes:
            raise fail(
                invalid_path, f"{base}/expectedCode", f"unknown code {expected_code!r}"
            )
        if not isinstance(case.get("retryable"), bool):
            raise fail(invalid_path, f"{base}/retryable", "expected a boolean")
        if case.get("outcome") not in {"not_started", "failed", "unknown"}:
            raise fail(invalid_path, f"{base}/outcome", "unknown tool outcome")

        kind = case.get("kind")
        schema_error = check_schema(case.get("schema"))
        if kind == "invalid_schema":
            if expected_code != "INVALID_TOOL_SCHEMA":
                raise fail(
                    invalid_path,
                    f"{base}/expectedCode",
                    "invalid schemas require INVALID_TOOL_SCHEMA",
                )
            if schema_error is None:
                raise fail(invalid_path, f"{base}/schema", "expected an invalid schema")
            actual_path = pointer(schema_error.absolute_path)
        elif kind == "invalid_arguments":
            if expected_code != "INVALID_TOOL_ARGUMENTS":
                raise fail(
                    invalid_path,
                    f"{base}/expectedCode",
                    "invalid arguments require INVALID_TOOL_ARGUMENTS",
                )
            if schema_error is not None:
                raise fail(
                    invalid_path,
                    f"{base}/schema{pointer(schema_error.absolute_path)}",
                    schema_error.message,
                )
            error = first_error(
                Draft202012Validator(case["schema"], format_checker=FormatChecker()),
                case.get("arguments"),
            )
            if error is None:
                raise fail(
                    invalid_path,
                    f"{base}/arguments",
                    "expected arguments to fail validation",
                )
            actual_path = pointer(error.absolute_path)
        else:
            raise fail(
                invalid_path,
                f"{base}/kind",
                "expected invalid_schema or invalid_arguments",
            )

        if case.get("expectedPath") != actual_path:
            raise fail(
                invalid_path,
                f"{base}/expectedPath",
                f"expected {case.get('expectedPath')!r}, normalized first error is {actual_path!r}",
            )


def check_integrations(documents: dict[str, dict[str, Any]], codes: set[str]) -> None:
    manifest_schema = documents["integrations/manifest.schema.json"]
    index_schema = documents["integrations/index.schema.json"]
    validators = {
        "manifest": Draft202012Validator(
            manifest_schema, format_checker=FormatChecker()
        ),
        "index": Draft202012Validator(index_schema, format_checker=FormatChecker()),
    }

    def parameter_schema_path(parameters: dict[str, Any]) -> str | None:
        issue = parameter_schema_issue(parameters)
        if issue is not None:
            return pointer(issue)
        schema_error = check_schema(parameters)
        if schema_error is None:
            return None
        return pointer(schema_error.absolute_path)

    valid_path = CONTRACTS / "integrations" / "conformance-valid.json"
    valid_cases = documents["integrations/conformance-valid.json"].get("cases")
    if not isinstance(valid_cases, list) or not valid_cases:
        raise fail(valid_path, "/cases", "expected a non-empty array")
    for index, case in enumerate(valid_cases):
        base = f"/cases/{index}"
        if not isinstance(case, dict):
            raise fail(valid_path, base, "expected an object")
        target = case.get("target")
        if target not in validators:
            raise fail(valid_path, f"{base}/target", f"unknown target {target!r}")
        if set(case) != {"name", "target", "document"}:
            raise fail(valid_path, base, "invalid conformance case envelope")
        if not isinstance(case.get("name"), str) or not case["name"]:
            raise fail(valid_path, f"{base}/name", "expected a non-empty string")
        if not isinstance(case.get("document"), dict):
            raise fail(valid_path, f"{base}/document", "expected an object")
        error = first_error(validators[target], case["document"])
        if error is not None:
            error_path = pointer(error.absolute_path)
            raise fail(
                valid_path,
                f"{base}/document{error_path if error_path != '/' else ''}",
                error.message,
            )
        if target == "manifest":
            for tool_index, tool in enumerate(case["document"]["tools"]):
                schema_path = parameter_schema_path(tool["parameters"])
                if schema_path is None:
                    continue
                location = f"{base}/document/tools/{tool_index}/parameters"
                if schema_path != "/":
                    location += schema_path
                raise fail(
                    valid_path, location, "invalid Draft 2020-12 parameter schema"
                )

    abi_index_path = CONTRACTS / "integrations" / "abi-index-v1.json"
    abi_index = documents["integrations/abi-index-v1.json"]
    if set(abi_index) != {"schemaVersion", "integrations"}:
        raise fail(abi_index_path, "/", "expected the closed ABI index envelope")
    if abi_index.get("schemaVersion") != "1.0.0":
        raise fail(abi_index_path, "/schemaVersion", "expected '1.0.0'")
    abi_entries = abi_index.get("integrations")
    if not isinstance(abi_entries, dict) or not abi_entries:
        raise fail(abi_index_path, "/integrations", "expected a non-empty object")
    for integration_name, relative in sorted(abi_entries.items()):
        entry_path = f"/integrations/{integration_name}"
        if (
            not isinstance(integration_name, str)
            or re.fullmatch(r"[a-z][a-z0-9_-]*", integration_name) is None
        ):
            raise fail(abi_index_path, entry_path, "invalid integration name")
        if not isinstance(relative, str):
            raise fail(abi_index_path, entry_path, "expected a relative path")
        posix_path = PurePosixPath(relative)
        if (
            not relative
            or "\\" in relative
            or posix_path.is_absolute()
            or re.match(r"^[A-Za-z]:", relative) is not None
            or any(part in {"", ".", ".."} for part in relative.split("/"))
        ):
            raise fail(abi_index_path, entry_path, "expected a safe relative path")
        relative_key = f"integrations/{posix_path.as_posix()}"
        if relative_key not in documents:
            raise fail(abi_index_path, entry_path, "referenced ABI file is missing")
        abi_path = CONTRACTS / relative_key
        abi = documents[relative_key]
        if set(abi) != {"$schema", "version", "namespace", "tools"}:
            raise fail(abi_path, "/", "expected a closed integration ABI envelope")
        if abi.get("version") != "1.0.0":
            raise fail(abi_path, "/version", "expected '1.0.0'")
        if abi.get("namespace") != integration_name:
            raise fail(abi_path, "/namespace", "must match the ABI index key")
        tools = abi.get("tools")
        if not isinstance(tools, list) or not tools:
            raise fail(abi_path, "/tools", "expected a non-empty tool array")
        abi_manifest = {
            "name": integration_name,
            "version": "0.1.0",
            "namespace": integration_name.replace("-", "_"),
            "description": "Integration ABI contract.",
            "auth": {"kind": "none"},
            "files": ["index.ts"],
            "tools": tools,
        }
        error = first_error(validators["manifest"], abi_manifest)
        if error is not None:
            error_path = pointer(error.absolute_path)
            raise fail(abi_path, error_path, error.message)
        tool_names = [tool["name"] for tool in tools]
        if tool_names != sorted(set(tool_names)):
            raise fail(
                abi_path, "/tools", "tools must have unique names in sorted order"
            )
        for tool_index, tool in enumerate(tools):
            schema_path = parameter_schema_path(tool["parameters"])
            if schema_path is not None:
                location = f"/tools/{tool_index}/parameters"
                if schema_path != "/":
                    location += schema_path
                raise fail(abi_path, location, "invalid Draft 2020-12 parameter schema")

    provenance_path = CONTRACTS / "integrations" / "copy-provenance-v1.schema.json"
    provenance = documents["integrations/copy-provenance-v1.schema.json"]
    provenance_validator = Draft202012Validator(
        provenance, format_checker=FormatChecker()
    )
    digest = "0" * 64
    sample_provenance = {
        "schemaVersion": "1.0.0",
        "integration": "echo",
        "sdkVersion": "0.1.0",
        "runtime": "python",
        "stability": "beta",
        "registryEntrySha256": digest,
        "abiSha256": digest,
        "manifestSha256": digest,
        "license": {
            "identifier": "FSL-1.1-ALv2",
            "url": "https://spdx.org/licenses/FSL-1.1-ALv2.html",
            "sha256": digest,
        },
        "files": {"index.ts": digest},
    }
    echo_provenance = deepcopy(sample_provenance)
    echo_provenance["files"] = {"echo.py": digest}
    if first_error(provenance_validator, echo_provenance) is not None:
        raise fail(provenance_path, "/", "schema rejects valid Echo provenance")
    echo_provenance["abiSha256"] = None
    if first_error(provenance_validator, echo_provenance) is None:
        raise fail(
            provenance_path,
            "/properties/abiSha256",
            "schema permits null ABI digest for indexed Echo",
        )

    missing_runtime = deepcopy(sample_provenance)
    del missing_runtime["runtime"]
    if first_error(provenance_validator, missing_runtime) is None:
        raise fail(
            provenance_path, "/required", "schema permits missing runtime identity"
        )
    invalid_runtime = deepcopy(sample_provenance)
    invalid_runtime["runtime"] = "ruby"
    if first_error(provenance_validator, invalid_runtime) is None:
        raise fail(
            provenance_path, "/properties/runtime", "schema permits unknown runtime"
        )

    self_referential = deepcopy(sample_provenance)
    self_referential["files"] = {".kaji-integration-provenance.json": digest}
    if first_error(provenance_validator, self_referential) is None:
        raise fail(
            provenance_path, "/properties/files", "schema permits self-reference"
        )

    invalid_path = CONTRACTS / "integrations" / "conformance-invalid.json"
    invalid_cases = documents["integrations/conformance-invalid.json"].get("cases")
    if not isinstance(invalid_cases, list) or not invalid_cases:
        raise fail(invalid_path, "/cases", "expected a non-empty array")
    if "INTEGRATION_SCHEMA_INVALID" not in codes:
        raise fail(
            CONTRACTS / "errors" / "error-codes.json",
            "/codes",
            "missing INTEGRATION_SCHEMA_INVALID",
        )
    if "INTEGRATION_ABI_MISMATCH" not in codes:
        raise fail(
            CONTRACTS / "errors" / "error-codes.json",
            "/codes",
            "missing INTEGRATION_ABI_MISMATCH",
        )
    for index, case in enumerate(invalid_cases):
        base = f"/cases/{index}"
        if not isinstance(case, dict):
            raise fail(invalid_path, base, "expected an object")
        target = case.get("target")
        if target not in {"manifest", "index", "registry"}:
            raise fail(invalid_path, f"{base}/target", f"unknown target {target!r}")
        expected_keys = (
            {"name", "target", "document", "expectedPath", "expectedCode"}
            if target != "registry"
            else {
                "name",
                "target",
                "index",
                "manifests",
                "files",
                "expectedPath",
                "expectedCode",
            }
        )
        if set(case) != expected_keys:
            raise fail(invalid_path, base, "invalid conformance case envelope")
        if not isinstance(case.get("name"), str) or not case["name"]:
            raise fail(invalid_path, f"{base}/name", "expected a non-empty string")
        if case.get("expectedCode") != "INTEGRATION_SCHEMA_INVALID":
            raise fail(
                invalid_path,
                f"{base}/expectedCode",
                "expected INTEGRATION_SCHEMA_INVALID",
            )
        expected_path = case.get("expectedPath")
        if (
            not isinstance(expected_path, str)
            or not expected_path.startswith("/")
            or re.search(r"~(?:[^01]|$)", expected_path) is not None
        ):
            raise fail(
                invalid_path,
                f"{base}/expectedPath",
                "expected a normalized JSON pointer",
            )

        if target in validators:
            document = case.get("document")
            if not isinstance(document, dict):
                raise fail(invalid_path, f"{base}/document", "expected an object")
            error = first_error(validators[target], document)
            actual_path: str | None = (
                pointer(error.absolute_path) if error is not None else None
            )
            if target == "manifest" and error is None:
                for tool_index, tool in enumerate(document["tools"]):
                    schema_path = parameter_schema_path(tool["parameters"])
                    if schema_path is None:
                        continue
                    actual_path = f"/tools/{tool_index}/parameters"
                    if schema_path != "/":
                        actual_path += schema_path
                    break
                seen: set[str] = set()
                if actual_path is None:
                    for tool_index, tool in enumerate(document["tools"]):
                        name = tool["name"]
                        if name in seen:
                            actual_path = f"/tools/{tool_index}/name"
                            break
                        seen.add(name)
            if actual_path is None:
                raise fail(
                    invalid_path,
                    f"{base}/document",
                    "expected document to fail validation",
                )
            if expected_path != actual_path:
                raise fail(
                    invalid_path,
                    f"{base}/expectedPath",
                    f"expected {expected_path!r}, normalized first error is {actual_path!r}",
                )
            continue

        registry_index = case.get("index")
        manifests = case.get("manifests")
        files = case.get("files")
        if not isinstance(registry_index, dict):
            raise fail(invalid_path, f"{base}/index", "expected an object")
        error = first_error(validators["index"], registry_index)
        if error is not None:
            error_path = pointer(error.absolute_path)
            raise fail(
                invalid_path,
                f"{base}/index{error_path if error_path != '/' else ''}",
                error.message,
            )
        if not isinstance(manifests, dict):
            raise fail(invalid_path, f"{base}/manifests", "expected an object")
        for manifest_path, manifest in manifests.items():
            if not isinstance(manifest_path, str) or not manifest_path:
                raise fail(
                    invalid_path,
                    f"{base}/manifests",
                    "manifest paths must be non-empty strings",
                )
            if not isinstance(manifest, dict):
                raise fail(
                    invalid_path,
                    f"{base}/manifests/{pointer([manifest_path]).lstrip('/')}",
                    "expected an object",
                )
            error = first_error(validators["manifest"], manifest)
            if error is not None:
                manifest_pointer = pointer([manifest_path]).lstrip("/")
                error_path = pointer(error.absolute_path)
                raise fail(
                    invalid_path,
                    f"{base}/manifests/{manifest_pointer}"
                    f"{error_path if error_path != '/' else ''}",
                    error.message,
                )
        if (
            not isinstance(files, list)
            or not all(isinstance(file, str) and file for file in files)
            or len(files) != len(set(files))
        ):
            raise fail(
                invalid_path,
                f"{base}/files",
                "expected unique non-empty string paths",
            )

        actual_path = None
        virtual_files = set(files)
        for integration_name, entry in registry_index["integrations"].items():
            manifest_path = entry["manifest"]
            manifest = manifests.get(manifest_path)
            if manifest is None:
                actual_path = pointer(("integrations", integration_name, "manifest"))
                break
            if manifest["name"] != integration_name:
                actual_path = "/name"
                break
            manifest_root = PurePosixPath(manifest_path).parent
            for file_index, relative_file in enumerate(manifest["files"]):
                if (manifest_root / relative_file).as_posix() not in virtual_files:
                    actual_path = f"/files/{file_index}"
                    break
            if actual_path is not None:
                break
        if actual_path is None:
            raise fail(
                invalid_path,
                base,
                "expected virtual registry to fail validation",
            )
        if expected_path != actual_path:
            raise fail(
                invalid_path,
                f"{base}/expectedPath",
                f"expected {expected_path!r}, normalized first error is {actual_path!r}",
            )


def feature_sets(document: dict[str, Any]) -> dict[str, set[str]]:
    path = CONTRACTS / "feature-tiers-v1.json"
    result: dict[str, set[str]] = {}
    all_ids: set[str] = set()
    for tier in ("stable", "experimental"):
        entries = document.get(tier)
        if not isinstance(entries, list) or not entries:
            raise fail(path, f"/{tier}", "expected a non-empty array")
        ids: set[str] = set()
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise fail(path, f"/{tier}/{index}", "expected an object")
            feature_id = entry.get("id")
            if not isinstance(feature_id, str) or not feature_id:
                raise fail(path, f"/{tier}/{index}/id", "expected a non-empty string")
            if feature_id in all_ids:
                raise fail(path, f"/{tier}/{index}/id", "duplicate feature id")
            if not isinstance(entry.get("surface"), str) or not entry["surface"]:
                raise fail(
                    path, f"/{tier}/{index}/surface", "expected a non-empty string"
                )
            ids.add(feature_id)
            all_ids.add(feature_id)
        result[tier] = ids
    return result


def check_cli_command_tiers(document: dict[str, Any]) -> None:
    path = CONTRACTS / "feature-tiers-v1.json"
    matrix = document.get("cliCommands")
    if not isinstance(matrix, dict) or set(matrix) != {"python", "typescript"}:
        raise fail(path, "/cliCommands", "expected python and typescript command tiers")

    python_commands: set[str] = set()
    for source in (ROOT / "kaji" / "src" / "kaji" / "cli").glob("*.py"):
        python_commands.update(
            re.findall(r'\.add_parser\(\s*["\']([^"\']+)["\']', source.read_text())
        )
    typescript_source = (ROOT / "kaji" / "ts" / "src" / "cli" / "index.ts").read_text()
    command_block = typescript_source.split("export const COMMANDS", 1)[1].split(
        "\n};", 1
    )[0]
    typescript_commands = {
        quoted or bare
        for quoted, bare in re.findall(
            r'^  (?:(?:"([^"]+)")|([a-z][\w-]*)):\s*\{',
            command_block,
            re.MULTILINE,
        )
    }
    actual = {"python": python_commands, "typescript": typescript_commands}

    for runtime, commands in actual.items():
        tiers = matrix[runtime]
        if not isinstance(tiers, dict) or set(tiers) != {"stable", "experimental"}:
            raise fail(
                path,
                f"/cliCommands/{runtime}",
                "expected stable and experimental arrays",
            )
        classified: set[str] = set()
        for tier in ("stable", "experimental"):
            values = tiers[tier]
            if (
                not isinstance(values, list)
                or not all(isinstance(value, str) and value for value in values)
                or values != sorted(set(values))
            ):
                raise fail(
                    path,
                    f"/cliCommands/{runtime}/{tier}",
                    "expected sorted unique command names",
                )
            overlap = classified.intersection(values)
            if overlap:
                raise fail(
                    path,
                    f"/cliCommands/{runtime}/{tier}",
                    f"commands classified twice: {sorted(overlap)}",
                )
            classified.update(values)
        if classified != commands:
            raise fail(
                path,
                f"/cliCommands/{runtime}",
                f"command coverage mismatch; missing={sorted(commands - classified)}, extra={sorted(classified - commands)}",
            )


def check_package_subpaths(document: dict[str, Any]) -> None:
    path = CONTRACTS / "feature-tiers-v1.json"
    package_path = ROOT / "kaji" / "ts" / "package.json"
    package = load_json(package_path)
    package_exports = package.get("exports")
    if not isinstance(package_exports, dict):
        raise fail(package_path, "/exports", "expected an object")

    matrix = document.get("packageSubpaths")
    if not isinstance(matrix, dict) or set(matrix) != {"typescript"}:
        raise fail(path, "/packageSubpaths", "expected a typescript subpath matrix")
    typescript = matrix["typescript"]
    if not isinstance(typescript, dict):
        raise fail(path, "/packageSubpaths/typescript", "expected an object")

    shipped_subpaths = {key for key in package_exports if key != "."}
    classified_subpaths = set(typescript)
    if classified_subpaths != shipped_subpaths:
        raise fail(
            path,
            "/packageSubpaths/typescript",
            "package subpath coverage mismatch; "
            f"missing={sorted(shipped_subpaths - classified_subpaths)}, "
            f"extra={sorted(classified_subpaths - shipped_subpaths)}",
        )

    for subpath_name in sorted(shipped_subpaths):
        entry = typescript[subpath_name]
        if not isinstance(entry, dict) or set(entry) != {"tier", "exports"}:
            raise fail(
                path,
                f"/packageSubpaths/typescript/{subpath_name}",
                "expected tier and exports",
            )
        if entry["tier"] not in {"stable", "experimental"}:
            raise fail(
                path,
                f"/packageSubpaths/typescript/{subpath_name}/tier",
                "expected stable or experimental",
            )
        exports = entry["exports"]
        if (
            not isinstance(exports, list)
            or not all(isinstance(name, str) and name for name in exports)
            or exports != sorted(set(exports))
        ):
            raise fail(
                path,
                f"/packageSubpaths/typescript/{subpath_name}/exports",
                "expected sorted unique public export names",
            )

        package_target = package_exports[subpath_name]
        if not isinstance(package_target, dict):
            raise fail(
                package_path,
                f"/exports/{subpath_name.replace('/', '~1')}",
                "expected typed ESM and CJS targets",
            )
        stem = subpath_name.removeprefix("./")
        if stem == "cli":
            expected_targets = {
                "./dist/cli/package-entry.js",
                "./dist/cli/package-entry.d.ts",
                "./dist/cli/package-entry-cjs.cjs",
                "./dist/cli/package-entry-cjs.d.cts",
            }
            target_pattern = (
                r"\./dist/cli/package-entry(?:-cjs)?\.(?:js|cjs|d\.ts|d\.cts)"
            )
        else:
            expected_targets = {
                f"./dist/{stem}.js",
                f"./dist/{stem}.cjs",
                f"./dist/{stem}.d.ts",
                f"./dist/{stem}.d.cts",
            }
            target_pattern = rf"\./dist/{re.escape(stem)}\.(?:js|cjs|d\.ts|d\.cts)"
        actual_targets = set(re.findall(target_pattern, json.dumps(package_target)))
        if actual_targets != expected_targets:
            raise fail(
                package_path,
                f"/exports/{subpath_name.replace('/', '~1')}",
                "unexpected package targets",
            )


def check_cli_init_cases(document: dict[str, Any]) -> None:
    path = CONTRACTS / "cli" / "init-cases-v1.json"
    if document.get("schemaVersion") != 1:
        raise fail(path, "/schemaVersion", "expected 1")
    if document.get("grammar") != (
        "kaji [--no-color] [--verbose] init [path] "
        "--provider mock|openai|anthropic --yes --force"
    ):
        raise fail(path, "/grammar", "canonical init grammar differs")
    if document.get("defaults") != {"path": ".", "provider": "mock"}:
        raise fail(path, "/defaults", "canonical init defaults differ")
    if document.get("exitCodes") != {
        "successOrHelp": 0,
        "validationRuntimeOrConflict": 1,
        "usage": 2,
    }:
        raise fail(path, "/exitCodes", "canonical CLI exit codes differ")
    cases = document.get("cases")
    if not isinstance(cases, list):
        raise fail(path, "/cases", "expected an array")
    names: list[str] = []
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise fail(path, f"/cases/{index}", "expected an object")
        name = case.get("name")
        args = case.get("args")
        if not isinstance(name, str) or not name:
            raise fail(path, f"/cases/{index}/name", "expected a non-empty string")
        if not isinstance(args, list) or not all(
            isinstance(value, str) for value in args
        ):
            raise fail(path, f"/cases/{index}/args", "expected string arguments")
        if case.get("exitCode") not in {0, 1, 2}:
            raise fail(path, f"/cases/{index}/exitCode", "expected 0, 1, or 2")
        if case.get("setup") not in {None, "existing-file"}:
            raise fail(
                path,
                f"/cases/{index}/setup",
                "expected existing-file when setup is present",
            )
        if "typescriptOnly" in case and not isinstance(case["typescriptOnly"], bool):
            raise fail(
                path,
                f"/cases/{index}/typescriptOnly",
                "expected a boolean",
            )
        names.append(name)
    if len(names) != len(set(names)):
        raise fail(path, "/cases", "case names must be unique")
    required = {
        "defaults",
        "explicit-path",
        "mock-provider",
        "openai-provider",
        "anthropic-provider",
        "yes",
        "force",
        "unknown-provider",
        "missing-provider-value",
        "unknown-option",
        "existing-file-refusal",
    }
    actual = set(names)
    if actual != required:
        raise fail(
            path,
            "/cases",
            f"case set differs; missing={sorted(required - actual)}, "
            f"unexpected={sorted(actual - required)}",
        )


def public_export_tiers(document: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    path = CONTRACTS / "feature-tiers-v1.json"
    matrix = document.get("publicExports")
    if not isinstance(matrix, dict) or set(matrix) != {"python", "typescript"}:
        raise fail(path, "/publicExports", "expected python and typescript exports")
    for runtime, tiers in matrix.items():
        if not isinstance(tiers, dict) or set(tiers) != {
            "stable",
            "experimental",
            "deprecated",
        }:
            raise fail(
                path,
                f"/publicExports/{runtime}",
                "expected stable, experimental, and deprecated arrays",
            )
        classified: set[str] = set()
        for tier in ("stable", "experimental", "deprecated"):
            values = tiers[tier]
            if (
                not isinstance(values, list)
                or not all(isinstance(value, str) and value for value in values)
                or values != sorted(set(values))
            ):
                raise fail(
                    path,
                    f"/publicExports/{runtime}/{tier}",
                    "expected sorted unique export names",
                )
            overlap = classified.intersection(values)
            if overlap:
                raise fail(
                    path,
                    f"/publicExports/{runtime}/{tier}",
                    f"exports classified twice: {sorted(overlap)}",
                )
            classified.update(values)
    return matrix


def render_public_exports_fragment(runtime: str, tiers: dict[str, list[str]]) -> str:
    title = "Python" if runtime == "python" else "TypeScript"
    lines = [f"### {title} public exports"]
    for tier in ("stable", "experimental", "deprecated"):
        values = ", ".join(f"`{value}`" for value in tiers[tier]) or "none"
        lines.append(f"- {tier.title()}: {values}")
    return "\n".join(lines)


def check_public_exports(document: dict[str, Any]) -> None:
    import kaji

    path = CONTRACTS / "feature-tiers-v1.json"
    matrix = public_export_tiers(document)
    python_exports = {value for values in matrix["python"].values() for value in values}
    if python_exports != set(kaji.__all__):
        raise fail(
            path,
            "/publicExports/python",
            "classification must exactly cover kaji.__all__",
        )

    docs_path = ROOT / "docs" / "kaji" / "api-parity.md"
    try:
        docs = docs_path.read_text()
    except OSError as exc:
        raise fail(docs_path, "/", str(exc)) from exc
    for runtime, tiers in matrix.items():
        marker = re.search(
            rf"<!-- public-exports:{runtime}:start -->\n(.*?)\n"
            rf"<!-- public-exports:{runtime}:end -->",
            docs,
            re.DOTALL,
        )
        if marker is None:
            raise fail(docs_path, f"/#public-exports:{runtime}", "missing fragment")
        expected = render_public_exports_fragment(runtime, tiers)
        if marker.group(1) != expected:
            raise fail(
                docs_path,
                f"/#public-exports:{runtime}",
                "generated public-export fragment differs from contract",
            )


def check_beta_limits(document: dict[str, Any]) -> None:
    path = CONTRACTS / "beta-core-v1.json"
    expected = {
        "runtime": {
            "turnTimeoutMs": 120_000,
            "providerCancellationGraceMs": 5_000,
            "providerTextMaxBytes": 262_144,
            "providerToolArgumentsMaxBytes": 65_536,
            "providerResponseMaxBytes": 524_288,
            "providerToolCallsMax": 64,
        },
        "events": {
            "maxDurableToolArgumentBytes": 65_536,
            "maxDurableToolResultBytes": 65_536,
            "maxDurableEventBytes": 1_048_576,
        },
    }
    for section, fields in expected.items():
        actual = document.get(section)
        if not isinstance(actual, dict):
            raise fail(path, f"/{section}", "expected an object")
        for field, value in fields.items():
            if actual.get(field) != value:
                raise fail(path, f"/{section}/{field}", f"expected {value}")


def _registry_entries() -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for path in REGISTRY_INDEXES:
        index = load_json(path)
        integrations = index.get("integrations")
        if not isinstance(integrations, dict):
            raise fail(path, "/integrations", "expected an object")
        for name, entry in integrations.items():
            if not isinstance(entry, dict):
                raise fail(path, f"/integrations/{name}", "expected an object")
            normalized = {
                "stability": entry.get("stability"),
                "runtimes": entry.get("runtimes"),
            }
            existing = entries.get(name)
            if existing is not None and existing != normalized:
                raise fail(
                    path,
                    f"/integrations/{name}",
                    "registry indexes disagree on stability or runtimes",
                )
            entries[name] = normalized
    return entries


def check_release_matrix(features: dict[str, Any], beta_core: dict[str, Any]) -> None:
    try:
        text = RELEASE_MATRIX.read_text()
    except OSError as exc:
        raise fail(RELEASE_MATRIX, "/", str(exc)) from exc
    expected = feature_sets(features)
    matches = re.findall(r"<!-- beta-(stable|experimental):\s*([^>]*) -->", text)
    found: dict[str, set[str]] = {}
    for tier, values in matches:
        if tier in found:
            raise fail(RELEASE_MATRIX, f"/#beta-{tier}", "duplicate feature marker")
        found[tier] = {value.strip() for value in values.split(",") if value.strip()}
    for tier in ("stable", "experimental"):
        if tier not in found:
            raise fail(RELEASE_MATRIX, f"/#beta-{tier}", "missing feature marker")
        if found[tier] != expected[tier]:
            missing = sorted(expected[tier] - found[tier])
            extra = sorted(found[tier] - expected[tier])
            raise fail(
                RELEASE_MATRIX,
                f"/#beta-{tier}",
                f"marker mismatch; missing={missing}, extra={extra}",
            )

    stable_section = text.split("## Stable Core", 1)[1].split("\n## ", 1)[0]
    for index, entry in enumerate(features["stable"]):
        row = f"| {entry['surface']} | Stable core | Stable core |"
        if row not in stable_section:
            raise fail(
                RELEASE_MATRIX,
                f"/stable/{index}",
                f"missing stable row for {entry['surface']!r}",
            )

    registry_entries = _registry_entries()
    integration_sets = {
        tier: {
            name
            for name, entry in registry_entries.items()
            if entry.get("stability") == tier
        }
        for tier in ("beta", "experimental")
    }
    configured_stable = beta_core.get("integrations", {}).get("stable")
    if configured_stable != sorted(integration_sets["beta"]):
        raise fail(
            CONTRACTS / "beta-core-v1.json",
            "/integrations/stable",
            "must exactly match beta registry integrations",
        )
    if beta_core.get("integrations", {}).get("experimentalRequiresOptIn") is not True:
        raise fail(
            CONTRACTS / "beta-core-v1.json",
            "/integrations/experimentalRequiresOptIn",
            "experimental integrations must require opt-in",
        )

    for tier in ("beta", "experimental"):
        marker_matches = re.findall(rf"<!-- {tier}-integrations:\s*([^>]*) -->", text)
        if len(marker_matches) != 1:
            raise fail(
                RELEASE_MATRIX,
                f"/#-{tier}-integrations",
                "expected exactly one integration marker",
            )
        actual = {
            value.strip() for value in marker_matches[0].split(",") if value.strip()
        }
        if actual != integration_sets[tier]:
            raise fail(
                RELEASE_MATRIX,
                f"/#-{tier}-integrations",
                f"marker mismatch; expected={sorted(integration_sets[tier])}",
            )

    catalog_section = text.split("## Catalog Stability", 1)[1].split("\n## ", 1)[0]
    for name, entry in sorted(registry_entries.items()):
        runtimes = ", ".join(entry["runtimes"])
        row = f"| {name} | {entry['stability']} | {runtimes} |"
        if row not in catalog_section:
            raise fail(
                RELEASE_MATRIX,
                f"/catalog/{name}",
                f"missing registry row {row!r}",
            )


def check_contracts() -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
    documents = load_contract_documents()
    beta_path = CONTRACTS / "beta-core-v1.json"
    if documents["beta-core-v1.json"].get("contractVersion") != "1.0.0":
        raise fail(beta_path, "/contractVersion", "expected 1.0.0")
    check_beta_limits(documents["beta-core-v1.json"])
    check_tool_risk_vocabulary(documents)
    codes = error_codes(documents)
    recoveries = integration_recovery_entries(
        documents["errors/integration-recovery-v1.json"], codes
    )
    check_events(documents, codes, recoveries)
    check_tools(documents, codes)
    check_integrations(documents, codes)
    check_github_typescript_abi(documents)
    check_parity(documents)
    check_provider_costs(documents["providers/cost-conformance.json"])
    check_packaged_contracts()
    check_cli_command_tiers(documents["feature-tiers-v1.json"])
    check_package_subpaths(documents["feature-tiers-v1.json"])
    check_cli_init_cases(documents["cli/init-cases-v1.json"])
    check_public_exports(documents["feature-tiers-v1.json"])
    return documents, feature_sets(documents["feature-tiers-v1.json"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contracts-only", action="store_true")
    args = parser.parse_args()
    try:
        documents, _ = check_contracts()
        if not args.contracts_only:
            check_release_matrix(
                documents["feature-tiers-v1.json"], documents["beta-core-v1.json"]
            )
    except ContractError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("OK: beta contracts are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
