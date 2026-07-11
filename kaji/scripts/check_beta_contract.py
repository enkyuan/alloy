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


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "kaji" / "contracts"
RELEASE_MATRIX = ROOT / "kaji" / "RELEASE_MATRIX.md"
REGISTRY_INDEXES = (
    ROOT / "kaji" / "sdk" / "src" / "integrations" / "registry" / "index.json",
    ROOT / "kaji" / "ts" / "registry" / "index.json",
)
PACKAGE_CONTRACT_TARGETS = (
    ROOT / "kaji" / "sdk" / "src" / "contracts",
    ROOT / "kaji" / "ts" / "contracts",
)
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
REQUIRED_JSON = {
    "beta-core-v1.json",
    "feature-tiers-v1.json",
    "errors/error-codes.json",
    "errors/provider-normalization.json",
    "events/conformance.json",
    "events/conformance-invalid.json",
    "events/new-kaji-event-v1.schema.json",
    "events/stored-kaji-event-v1.schema.json",
    "integrations/conformance-invalid.json",
    "integrations/conformance-valid.json",
    "parity/expected-normalized.json",
    "parity/scenarios.json",
    "parity/scenarios.schema.json",
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
        if relative == "parity/expected-normalized.json":
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


def runtime_event_types() -> set[str]:
    python_source = (
        ROOT / "kaji" / "sdk" / "src" / "infra" / "events" / "types.py"
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


def check_events(documents: dict[str, dict[str, Any]], codes: set[str]) -> None:
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
                seen: set[str] = set()
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
    for source in (ROOT / "kaji" / "sdk" / "src" / "cli").glob("*.py"):
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
    check_events(documents, codes)
    check_tools(documents, codes)
    check_integrations(documents, codes)
    check_parity(documents)
    check_packaged_contracts()
    check_cli_command_tiers(documents["feature-tiers-v1.json"])
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
