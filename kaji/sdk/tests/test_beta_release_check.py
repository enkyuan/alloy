from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import os
import shutil
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
BETA_GATE = REPO_ROOT / "kaji" / "scripts" / "beta_release_check.py"
ROOT_PACKAGE = REPO_ROOT / "package.json"
ROOT_LOCK = REPO_ROOT / "bun.lock"
ROOT_GITIGNORE = REPO_ROOT / ".gitignore"
RULE_DIR = REPO_ROOT / "tools" / "ast-grep" / "rules"
RULE_TEST_DIR = REPO_ROOT / "tools" / "ast-grep" / "rule-tests"
SGCONFIG = REPO_ROOT / "sgconfig.yml"
AST_GREP_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ast-grep.yml"


def _load_beta_gate():
    scripts = str(BETA_GATE.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("test_beta_gate_module", BETA_GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_root_script(name: str):
    path = BETA_GATE.parent / name
    scripts = str(path.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location(f"test_{path.stem}_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
    assert parity < script.index("run_gates(common_gates(), environment)")
    assert parity < script.index('"Python artifact smoke"')


def test_typescript_build_precedes_every_artifact_consumer() -> None:
    module = _load_beta_gate()
    common = [gate.label for gate in module.common_gates()]
    release = [gate.label for gate in module.release_gates()]

    assert common.index("TypeScript build") < common.index("TypeScript unit tests")
    assert common.index("TypeScript build") < common.index("TypeScript package smoke")
    assert release.index("TypeScript build (release)") < release.index(
        "TypeScript tests (release)"
    )
    assert release.index("TypeScript build (release)") < release.index(
        "TypeScript package smoke (release)"
    )


def test_canonical_typescript_test_script_selects_node() -> None:
    package = json.loads((REPO_ROOT / "kaji" / "ts" / "package.json").read_text())
    command = package["scripts"]["test"]

    assert command.startswith(
        'PATH="${PATH#*:}:/usr/local/bin:/opt/homebrew/bin" /bin/sh -c '
    )
    assert 'exec "$(command -v node)"' in command
    assert '"$@"' in command
    assert "vitest" in command
    assert ("bun", "run", "test") in {
        gate.command for gate in _load_beta_gate().common_gates()
    }


def test_release_wrapper_builds_before_consumers_from_checkout_without_dist(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    scripts = checkout / "kaji" / "scripts"
    sdk = checkout / "kaji" / "sdk"
    typescript = checkout / "kaji" / "ts"
    scripts.mkdir(parents=True)
    sdk.mkdir(parents=True)
    typescript.mkdir(parents=True)
    shutil.copy2(BETA_GATE, scripts / BETA_GATE.name)
    shutil.copy2(
        REPO_ROOT / "kaji" / "scripts" / "process_runner.py",
        scripts / "process_runner.py",
    )
    (scripts / "run_beta_benchmarks.py").write_text("raise SystemExit(0)\n")
    (scripts / "verify_openai_loop.py").write_text(
        "import os\n"
        "if os.environ.get('KAJI_REQUIRE_LIVE_KEYS') == '1':\n"
        "    print('FAIL: OPENAI_API_KEY required for live readiness')\n"
        "    raise SystemExit(2)\n"
        "print('SKIP: OPENAI_API_KEY not set')\n"
    )

    home = tmp_path / "home"
    binaries = home / ".local" / "bin"
    binaries.mkdir(parents=True)
    log = tmp_path / "commands.log"
    fake_tool = f"""#!{sys.executable}
import os
from pathlib import Path
import shutil
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
checkout = Path(os.environ["FAKE_CHECKOUT"])
with Path(os.environ["FAKE_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write(name + "|" + str(Path.cwd()) + "|" + " ".join(args) + "\\n")

if name == "bun":
    dist = checkout / "kaji" / "ts" / "dist"
    if args[:2] == ["run", "build"]:
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "index.js").write_text("built")
    consumer = args[:2] in (["run", "test"], ["run", "test:quickstart"], ["run", "package:smoke"])
    consumer = consumer or (args and args[0] == "scripts/smoke_package.mts")
    if consumer and not dist.is_dir():
        print("artifact consumer ran before build", file=sys.stderr)
        raise SystemExit(17)

if name == "uv":
    if "scripts/release_smoke.py" in args:
        dist = checkout / "kaji" / "sdk" / "dist"
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "kaji.whl").write_bytes(b"wheel")
        (dist / "kaji.tar.gz").write_bytes(b"sdist")
        shutil.rmtree(checkout / "kaji" / "ts" / "dist", ignore_errors=True)
    if "--output-file" in args:
        output = Path(args[args.index("--output-file") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("requirements")

if name == "npm" and args and args[0] == "pack":
    destination = Path(args[args.index("--pack-destination") + 1])
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "kaji-sdk-0.2.0-beta.1.tgz").write_bytes(b"npm")
"""
    for name in ("bun", "node", "npm", "uv"):
        executable = binaries / name
        executable.write_text(fake_tool)
        executable.chmod(0o755)

    assert not (typescript / "dist").exists()
    environment = os.environ.copy()
    environment.update(
        {
            "FAKE_CHECKOUT": str(checkout),
            "FAKE_LOG": str(log),
            "HOME": str(home),
            "PATH": str(binaries),
        }
    )
    completed = subprocess.run(
        [sys.executable, str(scripts / "beta_release_check.py"), "--release"],
        cwd=checkout,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    output = completed.stdout.strip().splitlines()
    assert output[-1] == (
        "PASS: offline release rehearsal; keyed/provider/publish readiness NOT claimed"
    )
    assert "PASS: Kaji beta checks completed" not in completed.stdout
    commands = log.read_text().splitlines()
    build_indices = [
        index
        for index, command in enumerate(commands)
        if command.endswith("|run build")
    ]
    test_indices = [
        index for index, command in enumerate(commands) if command.endswith("|run test")
    ]
    assert len(build_indices) == len(test_indices) == 2
    assert all(build < test for build, test in zip(build_indices, test_indices))


def test_soak_budget_is_duration_plus_cleanup_margin() -> None:
    module = _load_root_script("run_beta_soak.py")

    assert module.soak_minutes("0.25") == 0.25
    for invalid in ("0", "-1", "nan", "inf", "not-a-number"):
        with pytest.raises(ValueError):
            module.soak_minutes(invalid)

    source = (BETA_GATE.parent / "run_beta_soak.py").read_text()
    assert "run_parallel_checked" in source
    assert "minutes * 60 + 120" in source
    assert "subprocess" not in source


def test_benchmark_child_and_orchestrator_budgets_are_distinct() -> None:
    module = _load_root_script("process_runner.py")

    assert module.BENCHMARK_COMMAND_BUDGET.timeout_seconds == 600
    assert (
        module.BENCHMARK_ORCHESTRATOR_BUDGET.timeout_seconds
        > module.BENCHMARK_COMMAND_BUDGET.timeout_seconds
    )
    assert (
        module.RELEASE_COMMAND_BUDGET.timeout_seconds
        > module.BENCHMARK_ORCHESTRATOR_BUDGET.timeout_seconds
    )


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
