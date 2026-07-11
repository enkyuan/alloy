from __future__ import annotations

import ast
import subprocess
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
BETA_GATE = REPO_ROOT / "kaji" / "scripts" / "beta_release_check.py"
ROOT_PACKAGE = REPO_ROOT / "package.json"
ROOT_LOCK = REPO_ROOT / "bun.lock"
ROOT_GITIGNORE = REPO_ROOT / ".gitignore"
RULE_DIR = REPO_ROOT / "tools" / "ast-grep" / "rules"
RULE_TEST_DIR = REPO_ROOT / "tools" / "ast-grep" / "rule-tests"
SGCONFIG = REPO_ROOT / "sgconfig.yml"
AST_GREP_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ast-grep.yml"


def test_beta_release_check_python_syntax() -> None:
    subprocess.run([sys.executable, "-m", "py_compile", str(BETA_GATE)], check=True)


def test_beta_release_check_rejects_unknown_flag_before_gates() -> None:
    result = subprocess.run(
        [sys.executable, str(BETA_GATE), "--unknown"],
        capture_output=True,
        check=False,
        env={"PATH": "/usr/bin:/bin"},
        text=True,
    )

    assert result.returncode == 2
    assert "usage:" in result.stderr
    assert "PASS:" not in result.stdout + result.stderr


def test_protected_provider_proof_requires_openai_before_success() -> None:
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    proof = REPO_ROOT / "kaji" / "scripts" / "live_provider_proof.py"
    result = subprocess.run(
        [sys.executable, str(proof)],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 2
    assert "OPENAI_API_KEY is required for keyed provider proof" in output
    assert "STATUS: openai=passed" not in output
    assert "PASS:" not in output


def test_release_success_line_disclaims_protected_evidence() -> None:
    literals = {
        node.value
        for node in ast.walk(ast.parse(BETA_GATE.read_text()))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert (
        "PASS: offline release rehearsal; keyed/provider/publish readiness NOT claimed"
        in literals
    )
    assert "PASS: Kaji beta release checks completed" not in literals


def test_beta_release_check_wraps_required_gates() -> None:
    script = BETA_GATE.read_text()

    for expected in [
        '"pytest", "-m", "not integration"',
        '"scripts/check_types.py"',
        '"scripts/release_smoke.py"',
        '"package:smoke"',
        "live_provider_proof.py",
        "KAJI_REQUIRE_LIVE_KEYS",
        "KAJI_RUN_KEYED_LIVE",
        "UV_SYSTEM_CERTS",
        '"audit:ast-grep"',
        "check_sdk_parity.py",
        "run_beta_benchmarks.py",
        '"--quick"',
    ]:
        assert expected in script

    assert "run_optional_ast_grep" not in script
    assert "SKIP: ast-grep CLI not installed" not in script

    parity = script.index('"Cross-SDK behavioral parity"')
    assert parity < script.index('"TypeScript package smoke"')
    assert parity < script.index('"Python artifact smoke"')


def test_root_package_pins_structural_and_benchmark_gates() -> None:
    package = ROOT_PACKAGE.read_text()
    for expected in [
        '"@ast-grep/cli": "0.44.1"',
        '"ast-grep:test": "sg test -t tools/ast-grep/rule-tests --skip-snapshot-tests"',
        '"ast-grep:scan": "sg scan --config sgconfig.yml kaji"',
        '"audit:ast-grep": "bun run ast-grep:test && bun run ast-grep:scan"',
        '"benchmark:kaji-beta": "uv run --project kaji/sdk python kaji/scripts/run_beta_benchmarks.py --quick"',
        '"benchmark:kaji-beta:full": "uv run --project kaji/sdk python kaji/scripts/run_beta_benchmarks.py --full"',
        '"soak:kaji-beta": "uv run --project kaji/sdk python kaji/scripts/run_beta_soak.py --minutes 30"',
    ]:
        assert expected in package


def test_root_bun_lock_is_present_and_not_ignored() -> None:
    assert ROOT_LOCK.is_file()
    assert '"@ast-grep/cli": "0.44.1"' in ROOT_LOCK.read_text()

    ignore_lines = ROOT_GITIGNORE.read_text().splitlines()
    assert "!bun.lock" in ignore_lines
    assert ignore_lines.index("!bun.lock") > ignore_lines.index("bun.lock")


def test_beta_structural_audit_rules_cover_sdk_boundaries() -> None:
    rule_text = "\n".join(path.read_text() for path in sorted(RULE_DIR.glob("*.yml")))

    existing_rule_ids = [
        "python-sdk-no-service-imports",
        "python-core-no-upward-imports",
        "python-runtime-no-legacy-tooldefinition",
        "ts-no-provider-value-imports",
        "no-generic-ts-cancelled-error",
    ]
    task_14_rule_ids = [
        "python-runtime-no-direct-event-append",
        "ts-runtime-no-direct-event-append",
        "python-no-hardcoded-builder-identity",
        "ts-no-hardcoded-builder-identity",
        "python-planner-no-unbounded-gather",
        "ts-planner-no-unbounded-tool-map",
        "ts-registry-no-direct-fetch",
        "python-runtime-no-replay-in-loop",
    ]

    for expected in existing_rule_ids + task_14_rule_ids:
        assert f"id: {expected}" in rule_text

    for expected in task_14_rule_ids:
        rule_test = RULE_TEST_DIR / f"{expected}-test.yml"
        assert rule_test.is_file()
        assert rule_test.read_text().startswith(f"id: {expected}\n")

    assert "tools/ast-grep/rules" in SGCONFIG.read_text()


def test_ast_grep_is_mandatory_in_ci() -> None:
    workflow = AST_GREP_WORKFLOW.read_text()
    assert "bun-version: 1.3.11" in workflow
    assert "install-args: --frozen-lockfile" in workflow
    assert "test result: ok. 8 passed; 0 failed;" in workflow
    assert workflow.index("bun run ast-grep:test") < workflow.index(
        "bun run ast-grep:scan"
    )

    benchmark_workflow = (
        REPO_ROOT / ".github" / "workflows" / "kaji.benchmark.yml"
    ).read_text()
    assert benchmark_workflow.count("install-args: --frozen-lockfile") == 3


def test_release_docs_reference_beta_release_check() -> None:
    combined = "\n".join(
        [
            (REPO_ROOT / "kaji" / "RELEASE_MATRIX.md").read_text(),
            (REPO_ROOT / "kaji" / "sdk" / "README.md").read_text(),
            (REPO_ROOT / "kaji" / "ts" / "README.md").read_text(),
            (REPO_ROOT / "docs" / "MVP.md").read_text(),
        ]
    )

    assert (
        "uv run --project kaji/sdk python kaji/scripts/beta_release_check.py"
        in combined
    )
    assert "KAJI_RUN_KEYED_LIVE=1" in combined
    assert "SDK/service boundary" in combined
    assert "TypeScript optional provider imports" in combined
