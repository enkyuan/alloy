import importlib.util
import json
from pathlib import Path
import shutil

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
FEATURE_TIERS = REPO_ROOT / "kaji" / "contracts" / "feature-tiers-v1.json"
RELEASE_MATRIX = REPO_ROOT / "kaji" / "RELEASE_MATRIX.md"
CONTRACT_CHECKER = REPO_ROOT / "kaji" / "scripts" / "check-beta-contract.py"
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
