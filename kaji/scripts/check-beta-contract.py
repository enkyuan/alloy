#!/usr/bin/env python3
"""Validate Kaji's canonical production-beta contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "kaji" / "contracts"
RELEASE_MATRIX = ROOT / "kaji" / "RELEASE_MATRIX.md"


class ContractError(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"{path}: /: {exc}") from exc


def pointer(parts: Any) -> str:
    encoded = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(encoded) if encoded else "/"


def validate_schema(path: Path) -> dict[str, Any]:
    schema = load_json(path)
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        raise ContractError(f"{path}: /: invalid Draft 2020-12 schema: {exc}") from exc
    return schema


def validate_instance(path: Path, schema: dict[str, Any], instance: Any) -> None:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(instance),
        key=lambda error: (list(error.absolute_path), list(error.absolute_schema_path)),
    )
    if errors:
        error = errors[0]
        raise ContractError(f"{path}: {pointer(error.absolute_path)}: {error.message}")


def check_contracts() -> None:
    beta = load_json(CONTRACTS / "beta-core-v1.json")
    if beta.get("contractVersion") != "1.0.0":
        raise ContractError(
            f"{CONTRACTS / 'beta-core-v1.json'}: /contractVersion: expected 1.0.0"
        )

    new_schema = validate_schema(CONTRACTS / "events" / "new-kaji-event-v1.schema.json")
    stored_schema = validate_schema(
        CONTRACTS / "events" / "stored-kaji-event-v1.schema.json"
    )
    validate_schema(CONTRACTS / "tools" / "tool-schema-v1.schema.json")

    event_fixture_path = CONTRACTS / "events" / "conformance.json"
    event_fixture = load_json(event_fixture_path)
    events = event_fixture.get("events")
    if not isinstance(events, list) or not events:
        raise ContractError(
            f"{event_fixture_path}: /events: expected a non-empty array"
        )

    ids: set[str] = set()
    sequences: dict[str, set[int]] = {}
    error_codes = set(
        load_json(CONTRACTS / "errors" / "error-codes.json").get("codes", [])
    )
    for index, event in enumerate(events):
        validate_instance(event_fixture_path, stored_schema, event)
        event_id = event["id"]
        if event_id in ids:
            raise ContractError(
                f"{event_fixture_path}: /events/{index}/id: duplicate event id"
            )
        ids.add(event_id)
        session_sequences = sequences.setdefault(event["session_id"], set())
        sequence = event["sequence"]
        if sequence in session_sequences:
            raise ContractError(
                f"{event_fixture_path}: /events/{index}/sequence: duplicate sequence"
            )
        session_sequences.add(sequence)
        code = event.get("error_code")
        if code is not None and code not in error_codes:
            raise ContractError(
                f"{event_fixture_path}: /events/{index}/error_code: unknown code {code!r}"
            )

    draft = dict(events[0])
    draft.pop("sequence")
    validate_instance(event_fixture_path, new_schema, draft)

    for filename, should_pass in (
        ("conformance-valid.json", True),
        ("conformance-invalid.json", False),
    ):
        fixture_path = CONTRACTS / "tools" / filename
        fixture = load_json(fixture_path)
        for index, case in enumerate(fixture.get("cases", [])):
            schema = case.get("schema")
            try:
                Draft202012Validator.check_schema(schema)
            except Exception as exc:
                raise ContractError(
                    f"{fixture_path}: /cases/{index}/schema: {exc}"
                ) from exc
            valid = not list(
                Draft202012Validator(
                    schema, format_checker=FormatChecker()
                ).iter_errors(case.get("arguments"))
            )
            if valid is not should_pass:
                expectation = "pass" if should_pass else "fail"
                raise ContractError(
                    f"{fixture_path}: /cases/{index}: expected arguments to {expectation} validation"
                )


def check_release_matrix() -> None:
    text = RELEASE_MATRIX.read_text()
    required = {
        "<!-- beta-stable: echo -->",
        "<!-- beta-experimental: http,web,fs,sqlite -->",
    }
    missing = sorted(required.difference(text.splitlines()))
    if missing:
        raise ContractError(
            f"{RELEASE_MATRIX}: /: missing markers: {', '.join(missing)}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contracts-only", action="store_true")
    args = parser.parse_args()
    try:
        check_contracts()
        if not args.contracts_only:
            check_release_matrix()
    except ContractError as exc:
        print(f"FAIL: {exc}")
        return 1
    print("OK: beta contracts are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
