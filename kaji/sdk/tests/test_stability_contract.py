from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
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
