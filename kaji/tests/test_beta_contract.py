from copy import deepcopy
import json
from pathlib import Path
import runpy
import subprocess
import sys

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
