from __future__ import annotations

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]
RULE_DIR = REPO_ROOT / "tools" / "ast-grep" / "rules"
RULE_TEST_DIR = REPO_ROOT / "tools" / "ast-grep" / "rule-tests"
EXPECTED_RULES = REPO_ROOT / "tools" / "ast-grep" / "expected-rules.txt"


def _ids_by_path(directory: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in sorted(directory.glob("*.yml")):
        matches = re.findall(r"(?m)^id:\s*([a-z0-9-]+)\s*$", path.read_text())
        assert len(matches) == 1, f"{path} must declare exactly one rule id"
        rule_id = matches[0]
        assert rule_id not in result, f"duplicate ast-grep id: {rule_id}"
        result[rule_id] = path
    return result


def test_task9_structural_rule_inventory_is_exact_and_executable() -> None:
    expected = EXPECTED_RULES.read_text().splitlines()
    assert expected
    assert expected == sorted(set(expected))
    assert all(re.fullmatch(r"[a-z0-9-]+", rule_id) for rule_id in expected)

    rules = _ids_by_path(RULE_DIR)
    tests = _ids_by_path(RULE_TEST_DIR)
    assert set(expected) == set(rules) == set(tests)

    for rule_id, test in tests.items():
        assert test.name == f"{rule_id}-test.yml"
        source = test.read_text()
        assert re.search(r"(?m)^valid:\s*$", source)
        assert re.search(r"(?m)^invalid:\s*$", source)


def test_offline_vitest_setup_is_unit_only() -> None:
    unit = (REPO_ROOT / "kaji" / "ts" / "vitest.config.ts").read_text()
    integration = (
        REPO_ROOT / "kaji" / "ts" / "vitest.integration.config.ts"
    ).read_text()
    assert 'setupFiles: ["./tests/offline-setup.ts"]' in unit
    assert "offline-setup" not in integration
