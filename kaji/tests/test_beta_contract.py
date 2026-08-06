from copy import deepcopy
import json
from pathlib import Path
import runpy
import subprocess
import sys
from typing import Any

import pytest
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = REPO_ROOT / "kaji" / "contracts" / "beta-core-v1.json"
FEATURE_TIERS = REPO_ROOT / "kaji" / "contracts" / "feature-tiers-v1.json"
ERROR_CODES = REPO_ROOT / "kaji" / "contracts" / "errors" / "error-codes.json"
EVENT_FIXTURE = REPO_ROOT / "kaji" / "contracts" / "events" / "conformance.json"
MIGRATION_CHECK = REPO_ROOT / "kaji" / "scripts" / "check_event_migration.py"
CONTRACT_CHECK = REPO_ROOT / "kaji" / "scripts" / "check_beta_contract.py"
PACKAGE_CONTRACTS = REPO_ROOT / "kaji" / "src" / "kaji" / "contracts"
GITHUB_TYPESCRIPT_ABI = (
    REPO_ROOT
    / "kaji"
    / "contracts"
    / "integrations"
    / "github-tool-abi-typescript-v1.json"
)
EVENT_SCHEMAS = (
    REPO_ROOT / "kaji" / "contracts" / "events" / "new-kaji-event-v1.schema.json",
    REPO_ROOT / "kaji" / "contracts" / "events" / "stored-kaji-event-v1.schema.json",
)
TS_HANDOFF_SCHEMA_RELATIVE = Path("release/kaji-ts-consumer-handoff-v1.schema.json")
TS_HANDOFF_SCHEMA = REPO_ROOT / "kaji" / "contracts" / TS_HANDOFF_SCHEMA_RELATIVE
TS_ONBOARDING_SCHEMA_RELATIVE = Path(
    "release/typescript-onboarding-evidence-v1.schema.json"
)
TS_ONBOARDING_SCHEMA = REPO_ROOT / "kaji" / "contracts" / TS_ONBOARDING_SCHEMA_RELATIVE
PUBLISHER_IDENTITY_SCHEMA_RELATIVE = Path(
    "release/publisher-identity-receipt-v1.schema.json"
)
PUBLISHER_IDENTITY_SCHEMA = (
    REPO_ROOT / "kaji" / "contracts" / PUBLISHER_IDENTITY_SCHEMA_RELATIVE
)
REMOVED_TTHW_CONTRACTS = (
    Path("release/tthw-evidence-v1.schema.json"),
    Path("release/tthw-participant.template.json"),
)


def test_beta_contract_defaults_are_public_and_stable() -> None:
    contract = json.loads(CONTRACT.read_text())

    assert contract["runtime"]["sameSessionTurns"] == "serialized"
    assert contract["runtime"]["maxToolIterations"] == 5
    assert contract["runtime"]["contextWindowTurns"] == 32
    assert contract["runtime"]["turnTimeoutMs"] == 120_000
    assert contract["runtime"]["providerCancellationGraceMs"] == 5_000
    assert contract["runtime"]["providerTextMaxBytes"] == 262_144
    assert contract["runtime"]["providerToolArgumentsMaxBytes"] == 65_536
    assert contract["runtime"]["providerResponseMaxBytes"] == 524_288
    assert contract["runtime"]["providerToolCallsMax"] == 64
    assert contract["tools"]["maxConcurrency"] == 4
    assert contract["tools"]["timeoutMs"] == 30_000
    assert contract["events"]["subscriberQueueCapacity"] == 1024
    assert contract["events"]["maxDurableToolResultBytes"] == 65_536
    assert contract["events"]["maxDurableEventBytes"] == 1_048_576
    assert contract["events"]["inMemoryStoreMaxEventsPerSession"] == 10_000


def test_event_schemas_annotate_durable_event_and_tool_result_caps() -> None:
    for path in EVENT_SCHEMAS:
        schema = json.loads(path.read_text())
        assert schema["x-maxSerializedBytes"] == 1_048_576
        assert (
            schema["$defs"]["toolCallCompleted"]["allOf"][1]["properties"]["result"][
                "x-maxSerializedBytes"
            ]
            == 65_536
        )


def test_python_package_contract_copy_matches_canonical_files() -> None:
    canonical = REPO_ROOT / "kaji" / "contracts"
    for source in canonical.rglob("*"):
        if source.is_file() and source.suffix in {".json", ".md"}:
            packaged = PACKAGE_CONTRACTS / source.relative_to(canonical)
            assert packaged.read_bytes() == source.read_bytes()


def test_typescript_handoff_schema_is_required_valid_and_packaged_for_both_runtimes() -> (
    None
):
    checker = runpy.run_path(str(CONTRACT_CHECK), run_name="handoff_contract_test")
    assert TS_HANDOFF_SCHEMA_RELATIVE.as_posix() in checker["REQUIRED_JSON"]

    schema_bytes = TS_HANDOFF_SCHEMA.read_bytes()
    Draft202012Validator.check_schema(json.loads(schema_bytes))
    for package_root in (
        REPO_ROOT / "kaji" / "src" / "kaji" / "contracts",
        REPO_ROOT / "kaji" / "ts" / "contracts",
    ):
        assert (package_root / TS_HANDOFF_SCHEMA_RELATIVE).read_bytes() == schema_bytes


def _onboarding_proof(manager: str) -> dict[str, object]:
    return {
        "manager": manager,
        "phases": {
            "artifactInstall": True,
            "scaffoldInit": True,
            "noKeyRun": True,
            "echoSetup": True,
            "echoRun": True,
            "coldRun": True,
            "warmRun": True,
        },
        "assertions": {
            "noKeyText": "The mock provider has completed the tool loop.",
            "deterministicText": "The mock provider has completed the tool loop.",
            "turnIdPresent": True,
            "finalSequencePositive": True,
            "echoLifecycle": ["requested", "started", "completed"],
            "echoLifecycleCounts": {
                "requested": 1,
                "started": 1,
                "completed": 1,
            },
            "echoToolCallIdentityCount": 1,
            "echoToolCallIdNonempty": True,
            "echoResult": {"message": "hello"},
            "echoFinalText": "The mock provider has completed the tool loop.",
            "forbiddenTerminalEventsAbsent": True,
            "coldWarmEqual": True,
        },
    }


def _onboarding_cell(major: int, source_id: int) -> dict[str, object]:
    commit = "a" * 40
    run_id = 123
    return {
        "executionMode": "protected",
        "sourceArtifact": {
            "name": f"kaji-node-compat-{major}",
            "id": source_id,
            "digest": "sha256:" + str(major)[0] * 64,
            "runId": run_id,
            "runAttempt": 1,
            "headSha": commit,
            "receiptSha256": str(major)[-1] * 64,
        },
        "runtime": {"version": f"v{major}.14.0"},
        "runner": {
            "configuredLabel": f"ubuntu-{major}.04",
            "environment": "github-hosted",
            "runnerOS": "Linux",
            "runnerArch": "X64",
            "platformOS": "linux",
            "platformArch": "x64",
            "imageOS": f"ubuntu{major}",
            "imageVersion": "20260720.1.0",
        },
        "invocation": {
            "workflowRun": f"https://github.com/enkyuan/alloy/actions/runs/{run_id}",
            "runId": run_id,
            "runAttempt": 1,
            "workflowRef": (
                "enkyuan/alloy/.github/workflows/kaji.rehearsal.yml@refs/heads/main"
            ),
            "workflowSha": commit,
            "job": "node-compat",
        },
        "onboardingProofs": {
            "npm": _onboarding_proof("npm"),
            "bun": _onboarding_proof("bun"),
        },
        "timings": {
            "npm": {"coldSetupToOutputMs": 11, "warmRunMs": 2},
            "bun": {"coldSetupToOutputMs": 13, "warmRunMs": 3},
        },
        "toolchain": {
            "python": "not-used",
            "uv": "not-used",
            "node": f"v{major}.14.0",
            "npm": "11.4.2",
            "bun": "1.3.11",
            "typescript": "5.7.3 and 6.0.2",
        },
        "conclusion": "passed",
        "failureCode": None,
    }


def _onboarding_document() -> dict[str, Any]:
    return {
        "schemaVersion": "1.0.0",
        "commit": "a" * 40,
        "releaseManifestSha256": "b" * 64,
        "packageArtifact": {
            "name": "kaji-sdk-0.2.0-beta.11.tgz",
            "size": 123,
            "sha256": "c" * 64,
        },
        "producerArtifact": {
            "name": "kaji-beta-artifacts",
            "id": 456,
            "digest": "sha256:" + "d" * 64,
            "runId": 123,
            "runAttempt": 1,
            "headSha": "a" * 40,
        },
        "cells": [
            _onboarding_cell(22, 2201),
            _onboarding_cell(24, 2401),
        ],
    }


def test_typescript_onboarding_schema_replaces_tthw_contract_inventory() -> None:
    checker = runpy.run_path(str(CONTRACT_CHECK), run_name="onboarding_contract_test")
    required = checker["REQUIRED_JSON"]
    relative = TS_ONBOARDING_SCHEMA_RELATIVE.as_posix()
    assert relative in required
    for removed in REMOVED_TTHW_CONTRACTS:
        assert removed.as_posix() not in required
        assert removed.as_posix() not in checker["DATA_DOCUMENTS"]
    assert relative not in checker["DATA_DOCUMENTS"]

    schema_bytes = TS_ONBOARDING_SCHEMA.read_bytes()
    schema = json.loads(schema_bytes)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    valid = _onboarding_document()
    validator.validate(valid)
    for package_root in (
        REPO_ROOT / "kaji" / "contracts",
        REPO_ROOT / "kaji" / "src" / "kaji" / "contracts",
        REPO_ROOT / "kaji" / "ts" / "contracts",
    ):
        assert (
            package_root / TS_ONBOARDING_SCHEMA_RELATIVE
        ).read_bytes() == schema_bytes
        for removed in REMOVED_TTHW_CONTRACTS:
            assert not (package_root / removed).exists()

    wrong_order = deepcopy(valid)
    wrong_order["cells"].reverse()
    extra_nested = deepcopy(valid)
    extra_nested["cells"][0]["runner"]["unexpected"] = True
    missing_nested = deepcopy(valid)
    missing_nested["cells"][0]["onboardingProofs"]["npm"]["phases"].pop("echoRun")
    boolean_id = deepcopy(valid)
    boolean_id["producerArtifact"]["id"] = True
    boolean_timing = deepcopy(valid)
    boolean_timing["cells"][0]["timings"]["npm"]["warmRunMs"] = True
    third_cell = deepcopy(valid)
    third_cell["cells"].append(deepcopy(third_cell["cells"][1]))
    for invalid in (
        wrong_order,
        extra_nested,
        missing_nested,
        boolean_id,
        boolean_timing,
        third_cell,
    ):
        assert not validator.is_valid(invalid)


def _publisher_identity_receipt() -> dict[str, object]:
    return {
        "schemaVersion": "1.0.0",
        "commit": "a" * 40,
        "tag": "kaji-v0.2.0-beta.11",
        "workflowRun": "https://github.com/enkyuan/alloy/actions/runs/123456789",
        "workflowRunAttempt": 1,
        "workflowPath": ".github/workflows/kaji.publish.yml",
        "workflowSha": "a" * 40,
        "expectedPublisher": "kaji-publisher",
        "actualPublisher": "kaji-publisher",
        "conclusion": "passed",
        "exitCode": 0,
        "failureCode": None,
    }


def test_publisher_identity_schema_is_required_closed_and_exactly_packaged() -> None:
    checker = runpy.run_path(str(CONTRACT_CHECK), run_name="publisher_contract_test")
    relative = PUBLISHER_IDENTITY_SCHEMA_RELATIVE.as_posix()
    assert relative in checker["REQUIRED_JSON"]
    assert relative not in checker["DATA_DOCUMENTS"]

    schema_bytes = PUBLISHER_IDENTITY_SCHEMA.read_bytes()
    schema = json.loads(schema_bytes)
    Draft202012Validator.check_schema(schema)
    assert set(schema["required"]) == set(_publisher_identity_receipt())
    assert schema["additionalProperties"] is False

    expected_release_inventory = {
        "github-proof-v1.schema.json",
        "kaji-ts-consumer-handoff-v1.schema.json",
        "publisher-identity-receipt-v1.schema.json",
        "typescript-onboarding-evidence-v1.schema.json",
    }
    for package_root in (
        REPO_ROOT / "kaji" / "contracts",
        REPO_ROOT / "kaji" / "src" / "kaji" / "contracts",
        REPO_ROOT / "kaji" / "ts" / "contracts",
    ):
        release_root = package_root / "release"
        assert {
            path.name for path in release_root.iterdir() if path.is_file()
        } == expected_release_inventory
        assert (
            package_root / PUBLISHER_IDENTITY_SCHEMA_RELATIVE
        ).read_bytes() == schema_bytes


def test_publisher_identity_schema_accepts_only_closed_fail_safe_states() -> None:
    schema = json.loads(PUBLISHER_IDENTITY_SCHEMA.read_text())
    validator = Draft202012Validator(schema)
    passed = _publisher_identity_receipt()
    validator.validate(passed)

    variants = []
    for failure_code, expected, actual, exit_code in (
        ("identity_check_incomplete", None, None, None),
        ("expected_publisher_missing", None, None, 1),
        ("expected_publisher_invalid", None, None, 1),
        ("token_missing", "kaji-publisher", None, 1),
        ("npm_whoami_failed", "kaji-publisher", None, 7),
        ("npm_whoami_output_invalid", "kaji-publisher", None, 1),
        ("publisher_mismatch", "kaji-publisher", "other-publisher", 1),
    ):
        receipt = deepcopy(passed)
        receipt.update(
            {
                "expectedPublisher": expected,
                "actualPublisher": actual,
                "conclusion": "failed",
                "exitCode": exit_code,
                "failureCode": failure_code,
            }
        )
        variants.append(receipt)
    for valid in variants:
        validator.validate(valid)

    for field in passed:
        missing = deepcopy(passed)
        missing.pop(field)
        assert not validator.is_valid(missing), field

    for secret_field in (
        "token",
        "npmConfig",
        "home",
        "env",
        "inheritedEnvironment",
        "rawOutput",
        "stdout",
        "stderr",
    ):
        secret_bearing = deepcopy(passed)
        secret_bearing[secret_field] = "must-not-be-retained"
        assert not validator.is_valid(secret_bearing), secret_field

    malformed_fields = {
        "commit": "A" * 40,
        "tag": "kaji-v0.2.0-beta.8",
        "workflowRun": (
            "https://github.com/enkyuan/alloy/actions/runs/123?token=npm_secret"
        ),
        "workflowRunAttempt": True,
        "workflowPath": ".github/workflows/other.yml",
        "workflowSha": "b" * 39,
        "expectedPublisher": "npm_" + "a" * 36,
        "actualPublisher": "github_pat_" + "a" * 36,
        "conclusion": "not_run",
        "exitCode": 256,
        "failureCode": "arbitrary_failure",
    }
    for field, value in malformed_fields.items():
        malformed = deepcopy(passed)
        malformed[field] = value
        assert not validator.is_valid(malformed), field

    invalid_combinations = []
    for updates in (
        {"actualPublisher": None},
        {"expectedPublisher": None},
        {"exitCode": 1},
        {"failureCode": "publisher_mismatch"},
        {"conclusion": "failed"},
        {
            "conclusion": "failed",
            "exitCode": None,
            "failureCode": "identity_check_incomplete",
            "actualPublisher": "kaji-publisher",
        },
        {
            "conclusion": "failed",
            "exitCode": 1,
            "failureCode": "identity_check_incomplete",
            "actualPublisher": None,
        },
        {
            "conclusion": "failed",
            "expectedPublisher": None,
            "actualPublisher": None,
            "exitCode": 1,
            "failureCode": "token_missing",
        },
        {
            "conclusion": "failed",
            "actualPublisher": None,
            "exitCode": 0,
            "failureCode": "npm_whoami_failed",
        },
        {
            "conclusion": "failed",
            "actualPublisher": None,
            "exitCode": 1,
            "failureCode": "publisher_mismatch",
        },
        {
            "conclusion": "failed",
            "actualPublisher": "other-publisher",
            "exitCode": 0,
            "failureCode": "publisher_mismatch",
        },
        {
            "conclusion": "failed",
            "expectedPublisher": "kaji-publisher",
            "actualPublisher": None,
            "exitCode": 1,
            "failureCode": "expected_publisher_missing",
        },
        {
            "conclusion": "failed",
            "actualPublisher": "npm_" + "a" * 36,
            "exitCode": 1,
            "failureCode": "publisher_mismatch",
        },
    ):
        invalid = deepcopy(passed)
        invalid.update(updates)
        invalid_combinations.append(invalid)
    for invalid in invalid_combinations:
        assert not validator.is_valid(invalid)


def test_typescript_handoff_policy_receipt_names_the_executed_regression() -> None:
    schema = json.loads(TS_HANDOFF_SCHEMA.read_text())
    properties = schema["$defs"]["policyEvidence"]["properties"]
    root_properties = schema["$defs"]["securityEvidence"]["properties"][
        "policyBeforeRequest"
    ]["properties"]

    for policy_properties in (properties, root_properties):
        assert policy_properties["testFile"] == {
            "const": "kaji/ts/tests/github-registry.test.ts"
        }
        assert policy_properties["testName"] == {
            "const": "rejects approval for github_create_issue before token or HTTP"
        }


def test_typescript_github_package_abi_is_closed_and_rejects_drift() -> None:
    checker = runpy.run_path(str(CONTRACT_CHECK), run_name="github_package_abi_test")
    documents = checker["load_contract_documents"]()
    check = checker["check_github_typescript_abi"]
    contract_error = checker["ContractError"]

    check(documents)
    package_abi = json.loads(GITHUB_TYPESCRIPT_ABI.read_text())
    assert package_abi["schema_version"] == "1.0.0"
    assert package_abi["catalog_version"] == "0.2.0"
    assert len(package_abi["tools"]) == 15
    assert sum(tool["risk"] == "read" for tool in package_abi["tools"]) == 13

    reordered = deepcopy(documents)
    reordered["integrations/github-tool-abi-typescript-v1.json"]["tools"][6:8] = (
        reversed(
            reordered["integrations/github-tool-abi-typescript-v1.json"]["tools"][6:8]
        )
    )
    with pytest.raises(contract_error, match="tool order differs"):
        check(reordered)

    shared_drift = deepcopy(documents)
    shared_drift["integrations/github-tool-abi-typescript-v1.json"]["tools"][0][
        "description"
    ] = "drift"
    with pytest.raises(contract_error, match="shared-six prefix differs"):
        check(shared_drift)

    schema_drift = deepcopy(documents)
    schema_drift["integrations/github-tool-abi-typescript-v1.json"]["tools"][6][
        "parameters"
    ]["properties"]["per_page"]["maximum"] = 100
    with pytest.raises(contract_error, match="parameter schema differs"):
        check(schema_drift)


def test_every_packaged_cli_command_has_one_stability_tier() -> None:
    matrix = json.loads(FEATURE_TIERS.read_text())["cliCommands"]
    assert matrix == {
        "python": {
            "stable": ["add", "connect", "disconnect", "init", "list-integrations"],
            "experimental": ["doctor", "gen", "info", "secret", "upgrade"],
        },
        "typescript": {
            "stable": [
                "add",
                "connect",
                "disconnect",
                "init",
                "list-integrations",
                "replay",
            ],
            "experimental": [],
        },
    }


def test_cli_init_contract_has_exact_current_cases() -> None:
    checker = runpy.run_path(str(CONTRACT_CHECK), run_name="cli_init_contract_test")
    document = checker["load_contract_documents"]()["cli/init-cases-v1.json"]
    check = checker["check_cli_init_cases"]
    contract_error = checker["ContractError"]

    check(document)

    missing = deepcopy(document)
    missing["cases"].pop()
    with pytest.raises(contract_error, match="case set differs"):
        check(missing)

    unexpected = deepcopy(document)
    unexpected["cases"][0]["name"] = "removed-option"
    with pytest.raises(contract_error, match="unexpected=\\['removed-option'\\]"):
        check(unexpected)


def test_package_subpath_contract_covers_every_typed_esm_and_cjs_export() -> None:
    document = json.loads(FEATURE_TIERS.read_text())
    assert set(document["packageSubpaths"]["typescript"]) == {
        "./anthropic",
        "./auth",
        "./cli",
        "./integrations",
        "./integrations/github",
        "./openai",
        "./testing",
    }
    assert document["packageSubpaths"]["typescript"]["./integrations/github"] == {
        "tier": "experimental",
        "exports": [
            "CreateGitHubIntegrationOptions",
            "GitHubIntegration",
            "createGithubIntegration",
            "inspectIntegration",
        ],
    }
    checker = runpy.run_path(str(CONTRACT_CHECK), run_name="package_subpath_test")
    checker["check_package_subpaths"](document)


def test_package_subpath_contract_rejects_an_unclassified_manifest_export() -> None:
    document = json.loads(FEATURE_TIERS.read_text())
    del document["packageSubpaths"]["typescript"]["./testing"]
    checker = runpy.run_path(str(CONTRACT_CHECK), run_name="package_subpath_test")
    with pytest.raises(checker["ContractError"], match="coverage mismatch"):
        checker["check_package_subpaths"](document)


def test_beta_error_vocabulary_includes_event_boundary_failures() -> None:
    codes = json.loads(ERROR_CODES.read_text())["codes"]
    assert len(codes) == len(set(codes))
    assert {
        "INVALID_DURABLE_VALUE",
        "INVALID_TOOL_RESULT",
        "EVENT_PAYLOAD_TOO_LARGE",
        "PROVIDER_OUTPUT_LIMIT",
        "PROVIDER_CANCELLATION_CONTRACT_VIOLATION",
        "EVENT_SCHEMA_INCOMPATIBLE",
        "TURN_TIMEOUT",
    }.issubset(codes)


def _migration_check(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MIGRATION_CHECK), str(path)],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )


def test_event_migration_preflight_is_read_only_and_reports_every_bad_line(
    tmp_path: Path,
) -> None:
    events = json.loads(EVENT_FIXTURE.read_text())["events"]
    valid_log = tmp_path / "valid.jsonl"
    valid_log.write_text("\n".join(json.dumps(event) for event in events[:2]) + "\n")
    valid_before = valid_log.read_bytes()
    valid = _migration_check(valid_log)
    assert valid.returncode == 0, valid.stderr
    assert valid_log.read_bytes() == valid_before

    missing_id = dict(events[0])
    missing_id.pop("id")
    unsafe = dict(events[0])
    unsafe["metadata"] = {"n": 2**53}
    invalid_log = tmp_path / "invalid.jsonl"
    invalid_log.write_text(
        "\n" + json.dumps(missing_id) + "\n" + json.dumps(unsafe) + "\n{not-json}\n"
    )
    invalid_before = invalid_log.read_bytes()
    invalid = _migration_check(invalid_log)
    assert invalid.returncode == 1
    assert invalid_log.read_bytes() == invalid_before
    assert "invalid.jsonl:2: EVENT_SCHEMA_INCOMPATIBLE /id" in invalid.stderr
    assert "invalid.jsonl:3: EVENT_SCHEMA_INCOMPATIBLE /metadata/n" in invalid.stderr
    assert "invalid.jsonl:4: EVENT_SCHEMA_INCOMPATIBLE /" in invalid.stderr
    assert invalid.stderr.count("EVENT_SCHEMA_INCOMPATIBLE") == 3


def test_event_migration_preflight_reports_malformed_utf8_without_mutation(
    tmp_path: Path,
) -> None:
    event = json.loads(EVENT_FIXTURE.read_text())["events"][0]
    log = tmp_path / "malformed-utf8.jsonl"
    log.write_bytes(json.dumps(event).encode() + b"\n" + b'{"id":"\xff"}\n')
    before = log.read_bytes()

    result = _migration_check(log)

    assert result.returncode == 1
    assert log.read_bytes() == before
    assert "malformed-utf8.jsonl:2: EVENT_SCHEMA_INCOMPATIBLE /" in result.stderr
    assert "Traceback" not in result.stderr


def test_event_contract_checker_rejects_structural_mutations() -> None:
    checker = runpy.run_path(str(CONTRACT_CHECK), run_name="beta_contract_test")
    documents = checker["load_contract_documents"]()
    codes = checker["error_codes"](documents)
    contract_error = checker["ContractError"]
    check_events = checker["check_events"]

    rogue_union = deepcopy(documents)
    rogue_schema = rogue_union["events/new-kaji-event-v1.schema.json"]
    rogue_schema["$defs"]["rogueEvent"] = {
        "allOf": [
            {"$ref": "#/$defs/base"},
            {
                "type": "object",
                "properties": {"type": {"const": "rogue.event"}},
                "required": ["type"],
            },
        ],
        "unevaluatedProperties": False,
    }
    rogue_schema["oneOf"].append({"$ref": "#/$defs/rogueEvent"})
    with pytest.raises(contract_error, match="oneOf discriminants"):
        check_events(rogue_union, codes)

    stored_drift = deepcopy(documents)
    stored_drift["events/stored-kaji-event-v1.schema.json"]["$defs"]["sessionCreated"][
        "allOf"
    ][1]["properties"]["stored_only"] = {"type": "string"}
    with pytest.raises(contract_error, match="structural parity"):
        check_events(stored_drift, codes)

    stored_top_level_drift = deepcopy(documents)
    stored_top_level_drift["events/stored-kaji-event-v1.schema.json"]["properties"] = {
        "timestamp": {"minimum": 0}
    }
    with pytest.raises(contract_error, match="structural parity"):
        check_events(stored_top_level_drift, codes)

    removed_negative = deepcopy(documents)
    cases = removed_negative["events/conformance-invalid.json"]["cases"]
    removed_negative["events/conformance-invalid.json"]["cases"] = [
        case for case in cases if case["name"] != "missing-event-id"
    ]
    with pytest.raises(contract_error, match="required negative cases"):
        check_events(removed_negative, codes)


def test_provider_cost_checker_rejects_contract_drift() -> None:
    checker = runpy.run_path(str(CONTRACT_CHECK), run_name="beta_contract_test")
    document = checker["load_contract_documents"]()["providers/cost-conformance.json"]
    contract_error = checker["ContractError"]
    check_provider_costs = checker["check_provider_costs"]

    arithmetic = deepcopy(document)
    arithmetic["arithmetic"]["rounding"] = "half_up"
    with pytest.raises(contract_error, match="arithmetic contract"):
        check_provider_costs(arithmetic)

    extra_case_field = deepcopy(document)
    extra_case_field["cases"][0]["currency"] = "USD"
    with pytest.raises(contract_error, match="exactly one model or rates"):
        check_provider_costs(extra_case_field)

    invalid_rate = deepcopy(document)
    invalid_rate["cases"][0]["rates"]["inputPer1M"] = "1e33"
    with pytest.raises(
        contract_error, match=r"/cases/0/rates/inputPer1M.*bounded canonical"
    ):
        check_provider_costs(invalid_rate)

    missing_invalid = deepcopy(document)
    missing_invalid["invalidTokenCounts"].pop()
    with pytest.raises(contract_error, match="invalid token fixtures"):
        check_provider_costs(missing_invalid)

    missing_invalid_rate = deepcopy(document)
    missing_invalid_rate["invalidRates"].pop()
    with pytest.raises(contract_error, match="invalid rate fixtures"):
        check_provider_costs(missing_invalid_rate)
