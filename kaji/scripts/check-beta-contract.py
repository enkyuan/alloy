#!/usr/bin/env python3
"""Validate Kaji's canonical production-beta contracts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "kaji" / "contracts"
RELEASE_MATRIX = ROOT / "kaji" / "RELEASE_MATRIX.md"
PACKAGE_CONTRACT_TARGETS = (
    ROOT / "kaji" / "sdk" / "src" / "contracts",
    ROOT / "kaji" / "ts" / "contracts",
)
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
REQUIRED_JSON = {
    "beta-core-v1.json",
    "feature-tiers-v1.json",
    "errors/error-codes.json",
    "events/conformance.json",
    "events/new-kaji-event-v1.schema.json",
    "events/stored-kaji-event-v1.schema.json",
    "tools/conformance-invalid.json",
    "tools/conformance-valid.json",
    "tools/tool-schema-v1.schema.json",
}
APPROVAL_FAILURE_RETRYABILITY = {
    "APPROVAL_REJECTED": False,
    "APPROVAL_TIMEOUT": True,
    "TOOL_CANCELLED": True,
    "APPROVAL_UNAVAILABLE": False,
}


class ContractError(RuntimeError):
    pass


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


def check_events(documents: dict[str, dict[str, Any]], codes: set[str]) -> None:
    path = CONTRACTS / "events" / "conformance.json"
    events = documents["events/conformance.json"].get("events")
    if not isinstance(events, list) or not events:
        raise fail(path, "/events", "expected a non-empty array")

    new_schema = documents["events/new-kaji-event-v1.schema.json"]
    stored_schema = documents["events/stored-kaji-event-v1.schema.json"]
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


def check_release_matrix(features: dict[str, Any]) -> None:
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


def check_contracts() -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
    documents = load_contract_documents()
    beta_path = CONTRACTS / "beta-core-v1.json"
    if documents["beta-core-v1.json"].get("contractVersion") != "1.0.0":
        raise fail(beta_path, "/contractVersion", "expected 1.0.0")
    codes = error_codes(documents)
    check_events(documents, codes)
    check_tools(documents, codes)
    check_packaged_contracts()
    return documents, feature_sets(documents["feature-tiers-v1.json"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contracts-only", action="store_true")
    args = parser.parse_args()
    try:
        documents, _ = check_contracts()
        if not args.contracts_only:
            check_release_matrix(documents["feature-tiers-v1.json"])
    except ContractError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("OK: beta contracts are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
