import importlib.util
import json
from pathlib import Path
import shutil
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
FEATURE_TIERS = REPO_ROOT / "kaji" / "contracts" / "feature-tiers-v1.json"
RELEASE_MATRIX = REPO_ROOT / "kaji" / "RELEASE_MATRIX.md"
CONTRACT_CHECKER = REPO_ROOT / "kaji" / "scripts" / "check_beta_contract.py"
DOC_PATHS = [
    REPO_ROOT / "kaji" / "RELEASE_MATRIX.md",
    REPO_ROOT / "kaji" / "sdk" / "README.md",
    REPO_ROOT / "kaji" / "ts" / "README.md",
    REPO_ROOT / "docs" / "MVP.md",
]


def test_stability_tiers_are_documented_in_sdk_docs() -> None:
    combined = "\n".join(path.read_text() for path in DOC_PATHS)

    for phrase in [
        "Stable core",
        "Experimental Python-only",
        "TS not ported",
        "Redis realtime",
        "voice/TTS",
        "DocumentRAG",
        "OpenAI-compatible factories",
    ]:
        assert phrase in combined


def test_docs_do_not_claim_experimental_surfaces_are_production_hardened() -> None:
    combined = "\n".join(path.read_text() for path in DOC_PATHS)

    assert "Redis realtime/history" in combined
    assert "not production-hardened" in combined
    assert "not implemented in\n  TypeScript" in combined


def test_release_matrix_preserves_cross_sdk_contract() -> None:
    combined = "\n".join(path.read_text() for path in DOC_PATHS)

    for phrase in [
        "Stable core",
        "Experimental Python-only",
        "TypeScript Not Ported",
        "OpenAI-compatible factories",
        "Redis realtime/history",
        "voice/TTS",
        "DocumentRAG",
        "Keyed OpenAI live proof",
        "gpt-5.4-mini",
    ]:
        assert phrase in combined


def test_release_matrix_lists_non_core_promotion_criteria() -> None:
    matrix = (REPO_ROOT / "kaji" / "RELEASE_MATRIX.md").read_text()

    for phrase in [
        "Promotion criteria",
        "Redis realtime/history",
        "voice/TTS",
        "DocumentRAG",
        "native Gemini/Kimi",
        "tool retrieval",
        "not a beta release gate",
    ]:
        assert phrase in matrix


def test_release_matrix_matches_machine_readable_feature_tiers() -> None:
    tiers = json.loads(FEATURE_TIERS.read_text())
    matrix = RELEASE_MATRIX.read_text()

    for tier in ("stable", "experimental"):
        marker = next(
            line
            for line in matrix.splitlines()
            if line.startswith(f"<!-- beta-{tier}:")
        )
        actual = {
            value.strip()
            for value in marker.split(":", 1)[1].removesuffix("-->").split(",")
        }
        assert actual == {entry["id"] for entry in tiers[tier]}

    stable_section = matrix.split("## Stable Core", 1)[1].split("\n## ", 1)[0]
    for entry in tiers["stable"]:
        assert f"| {entry['surface']} | Stable core | Stable core |" in stable_section


def test_release_matrix_matches_registry_stability() -> None:
    matrix = RELEASE_MATRIX.read_text()
    assert "<!-- beta-integrations: echo -->" in matrix
    assert "<!-- experimental-integrations: fs,http,sqlite,web -->" in matrix
    assert "| echo | beta | python, typescript |" in matrix
    for name in ("fs", "http", "sqlite", "web"):
        assert f"| {name} | experimental | typescript |" in matrix


def test_contract_checker_reports_fixture_path_and_json_pointer(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    shutil.copytree(REPO_ROOT / "kaji" / "contracts", contracts)
    fixture_path = contracts / "tools" / "conformance-invalid.json"
    fixture = json.loads(fixture_path.read_text())
    fixture["cases"][0]["expectedPath"] = "/wrong"
    fixture_path.write_text(json.dumps(fixture))

    spec = importlib.util.spec_from_file_location(
        "check_beta_contract", CONTRACT_CHECKER
    )
    assert spec is not None and spec.loader is not None
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    setattr(checker, "CONTRACTS", contracts)

    with pytest.raises(checker.ContractError) as caught:
        checker.check_contracts()

    assert str(fixture_path) in str(caught.value)
    assert "/cases/0/expectedPath" in str(caught.value)


def test_contract_checker_rejects_unknown_integration_error_code(
    tmp_path: Path,
) -> None:
    contracts = tmp_path / "contracts"
    shutil.copytree(REPO_ROOT / "kaji" / "contracts", contracts)
    fixture_path = contracts / "integrations" / "conformance-invalid.json"
    fixture = json.loads(fixture_path.read_text())
    fixture["cases"][0]["expectedCode"] = "UNKNOWN_INTEGRATION_ERROR"
    fixture_path.write_text(json.dumps(fixture))

    spec = importlib.util.spec_from_file_location(
        "check_beta_contract", CONTRACT_CHECKER
    )
    assert spec is not None and spec.loader is not None
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    setattr(checker, "CONTRACTS", contracts)

    with pytest.raises(checker.ContractError) as caught:
        checker.check_contracts()

    assert str(fixture_path) in str(caught.value)
    assert "/cases/0/expectedCode" in str(caught.value)


def _integration_checker(tmp_path: Path):
    contracts = tmp_path / "contracts"
    shutil.copytree(REPO_ROOT / "kaji" / "contracts", contracts)
    spec = importlib.util.spec_from_file_location(
        "check_beta_contract_integrations", CONTRACT_CHECKER
    )
    assert spec is not None and spec.loader is not None
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    setattr(checker, "CONTRACTS", contracts)
    return checker, contracts


def _check_integration_contracts(checker) -> None:
    documents = checker.load_contract_documents()
    checker.check_integrations(documents, checker.error_codes(documents))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target", "unknown"),
        ("expectedCode", "INVALID_TOOL_ARGUMENTS"),
        ("expectedPath", "/wrong"),
    ],
)
def test_contract_checker_rejects_corrupt_integration_fixture_metadata(
    tmp_path: Path, field: str, value: str
) -> None:
    checker, contracts = _integration_checker(tmp_path)
    fixture_path = contracts / "integrations" / "conformance-invalid.json"
    fixture = json.loads(fixture_path.read_text())
    fixture["cases"][0][field] = value
    fixture_path.write_text(json.dumps(fixture))

    with pytest.raises(checker.ContractError) as caught:
        _check_integration_contracts(checker)

    assert str(fixture_path) in str(caught.value)
    assert f"/cases/0/{field}" in str(caught.value)


def test_contract_checker_rejects_valid_document_in_invalid_integration_fixture(
    tmp_path: Path,
) -> None:
    checker, contracts = _integration_checker(tmp_path)
    invalid_path = contracts / "integrations" / "conformance-invalid.json"
    valid_path = contracts / "integrations" / "conformance-valid.json"
    fixture = json.loads(invalid_path.read_text())
    valid_fixture = json.loads(valid_path.read_text())
    fixture["cases"][0]["document"] = valid_fixture["cases"][0]["document"]
    invalid_path.write_text(json.dumps(fixture))

    with pytest.raises(checker.ContractError) as caught:
        _check_integration_contracts(checker)

    assert str(invalid_path) in str(caught.value)
    assert "/cases/0/document" in str(caught.value)


def test_contract_checker_rejects_integration_schema_drift(tmp_path: Path) -> None:
    checker, contracts = _integration_checker(tmp_path)
    schema_path = contracts / "integrations" / "manifest.schema.json"
    schema = json.loads(schema_path.read_text())
    schema["properties"]["description"]["minLength"] = 100
    schema_path.write_text(json.dumps(schema))

    with pytest.raises(checker.ContractError) as caught:
        _check_integration_contracts(checker)

    valid_path = contracts / "integrations" / "conformance-valid.json"
    assert str(valid_path) in str(caught.value)
    assert "/cases/0/document/description" in str(caught.value)


REGISTRY_INVALID_CASE_NAMES = (
    "index key does not match manifest name",
    "index points to missing manifest",
    "manifest references missing file",
)


def _find_integration_case(
    fixture: dict[str, Any], name: str
) -> tuple[int, dict[str, Any]]:
    return next(
        (index, case)
        for index, case in enumerate(fixture["cases"])
        if case["name"] == name
    )


def _repair_registry_case(case: dict[str, Any]) -> None:
    integration_name, entry = next(iter(case["index"]["integrations"].items()))
    manifest_path = entry["manifest"]
    manifest = case["manifests"].get(manifest_path)
    if manifest is None:
        manifest = {
            "name": integration_name,
            "version": "0.1.0",
            "namespace": integration_name.replace("-", "_"),
            "description": integration_name,
            "auth": {"kind": "none"},
            "files": ["index.ts"],
            "tools": [{"name": "run", "description": "Run.", "risk": "read"}],
        }
        case["manifests"][manifest_path] = manifest
    manifest["name"] = integration_name
    manifest_root = Path(manifest_path).parent
    for file_value in manifest["files"]:
        relative_file = str(file_value)
        virtual_file = (manifest_root / relative_file).as_posix()
        if virtual_file not in case["files"]:
            case["files"].append(virtual_file)


@pytest.mark.parametrize("case_name", REGISTRY_INVALID_CASE_NAMES)
def test_contract_checker_rejects_wrong_registry_fixture_pointer(
    tmp_path: Path, case_name: str
) -> None:
    checker, contracts = _integration_checker(tmp_path)
    fixture_path = contracts / "integrations" / "conformance-invalid.json"
    fixture = json.loads(fixture_path.read_text())
    case_index, case = _find_integration_case(fixture, case_name)
    case["expectedPath"] = "/wrong"
    fixture_path.write_text(json.dumps(fixture))

    with pytest.raises(checker.ContractError) as caught:
        _check_integration_contracts(checker)

    assert str(fixture_path) in str(caught.value)
    assert f"/cases/{case_index}/expectedPath" in str(caught.value)


@pytest.mark.parametrize("case_name", REGISTRY_INVALID_CASE_NAMES)
def test_contract_checker_rejects_repaired_registry_invalid_fixture(
    tmp_path: Path, case_name: str
) -> None:
    checker, contracts = _integration_checker(tmp_path)
    fixture_path = contracts / "integrations" / "conformance-invalid.json"
    fixture = json.loads(fixture_path.read_text())
    case_index, case = _find_integration_case(fixture, case_name)
    _repair_registry_case(case)
    fixture_path.write_text(json.dumps(fixture))

    with pytest.raises(checker.ContractError) as caught:
        _check_integration_contracts(checker)

    assert str(fixture_path) in str(caught.value)
    assert f"/cases/{case_index}" in str(caught.value)
