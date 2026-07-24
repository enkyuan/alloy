from __future__ import annotations

import ast
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import subprocess
import os
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BETA_GATE = REPO_ROOT / "kaji" / "scripts" / "beta_release_check.py"
WORKFLOW_CHECK = REPO_ROOT / "kaji" / "scripts" / "check_workflows.py"
ROOT_PACKAGE = REPO_ROOT / "package.json"
ROOT_LOCK = REPO_ROOT / "bun.lock"
ROOT_GITIGNORE = REPO_ROOT / ".gitignore"
RULE_DIR = REPO_ROOT / "tools" / "ast-grep" / "rules"
RULE_TEST_DIR = REPO_ROOT / "tools" / "ast-grep" / "rule-tests"
SGCONFIG = REPO_ROOT / "sgconfig.yml"
AST_GREP_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ast-grep.test.yml"


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


def _load_sdk_benchmark(name: str):
    path = REPO_ROOT / "kaji" / "benchmarks" / "python" / name
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


def test_beta_release_check_help_distinguishes_local_rehearsal() -> None:
    result = subprocess.run(
        [sys.executable, str(BETA_GATE), "--help"],
        capture_output=True,
        check=False,
        env={"PATH": "/usr/bin:/bin"},
        text=True,
    )

    assert result.returncode == 0
    help_text = " ".join(result.stdout.split())
    assert "non-promotable local rehearsal" in help_text
    assert "commit and pinned-toolchain enforcement" in help_text


def test_local_ci_entrypoints_use_the_canonical_python_checks() -> None:
    package = json.loads(ROOT_PACKAGE.read_text())

    assert package["scripts"]["check:workflows"] == (
        "uv run --project kaji --no-sync python kaji/scripts/check_workflows.py"
    )
    assert package["scripts"]["ci:kaji"] == (
        "uv run --project kaji --no-sync python "
        "kaji/scripts/beta_release_check.py --gate"
    )
    assert package["scripts"]["ci:local"] == (
        "uv run --project kaji --no-sync python kaji/scripts/check_workflows.py --gate"
    )
    assert WORKFLOW_CHECK.is_file()


def test_local_ci_gate_is_exact_and_non_promotable() -> None:
    module = _load_beta_gate()

    assert [gate.command for gate in module.ci_gates()] == [
        (
            "uv",
            "run",
            "--project",
            "kaji",
            "python",
            "kaji/scripts/check_beta_contract.py",
        ),
        (
            "uv",
            "run",
            "--project",
            "kaji",
            "python",
            "kaji/scripts/sync_beta_contracts.py",
            "--check",
        ),
        (
            "uv",
            "run",
            "--project",
            "kaji",
            "python",
            "kaji/scripts/sync_integration_contracts.py",
            "--check",
        ),
        (
            "uv",
            "run",
            "--project",
            "kaji",
            "python",
            "kaji/scripts/check_integration_abi.py",
            "--explain",
        ),
        module.offline_command(
            "uv",
            "run",
            "--project",
            "kaji",
            "--no-sync",
            "python",
            "kaji/scripts/check_sdk_parity.py",
        ),
        ("bun", "run", "audit:ast-grep"),
        module.offline_command(
            "uv",
            "run",
            "--project",
            "kaji",
            "--no-sync",
            "python",
            "kaji/scripts/run_beta_benchmarks.py",
            "--quick",
        ),
        module.offline_command(
            "uv",
            "run",
            "--project",
            "kaji",
            "--no-sync",
            "python",
            "kaji/scripts/integration_benchmark.py",
            "--mode",
            "quick",
        ),
        module.offline_command(
            "uv",
            "run",
            "--project",
            "kaji",
            "--no-sync",
            "pytest",
            "kaji/tests",
            "-m",
            "not integration",
            "--cov-fail-under=80",
        ),
        module.offline_command("bun", "run", "--cwd", "kaji/ts", "build"),
        module.offline_command("bun", "run", "--cwd", "kaji/ts", "test:coverage"),
    ]
    literals = {
        node.value
        for node in ast.walk(ast.parse(BETA_GATE.read_text()))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert (
        "PASS: local Kaji CI gate completed; protected matrix, provider, and "
        "publication evidence NOT claimed" in literals
    )


def test_workflow_check_prepares_frozen_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_root_script("check_workflows.py")
    calls: list[tuple[str, Path, list[str]]] = []
    gate_calls: list[dict[str, str]] = []

    def capture(
        label: str,
        directory: Path,
        command: list[str],
        environment: dict[str, str],
        *_args: object,
    ) -> None:
        calls.append((label, directory, command))

    monkeypatch.setattr(module, "run_in_dir", capture)
    monkeypatch.setattr(module, "run_ci_checks", gate_calls.append)

    environment = {"PATH": "/usr/bin:/bin"}
    module.run_workflow_checks(environment, include_gate=True)

    assert [(label, directory, command) for label, directory, command in calls] == [
        ("GitHub Actions static analysis", REPO_ROOT, ["actionlint"]),
        (
            "Python lockfile freshness",
            REPO_ROOT / "kaji",
            ["uv", "lock", "--check"],
        ),
        (
            "Frozen Python dependencies",
            REPO_ROOT / "kaji",
            ["uv", "sync", "--frozen"],
        ),
        (
            "Frozen Bun dependencies",
            REPO_ROOT,
            ["bun", "install", "--frozen-lockfile"],
        ),
        (
            "Executable Kaji workflow contracts",
            REPO_ROOT,
            [
                "bun",
                "run",
                "--cwd",
                "kaji/ts",
                "test",
                "--",
                "tests/release-security.test.ts",
            ],
        ),
    ]
    assert gate_calls == [environment]


def test_protected_provider_proof_requires_both_keys_before_success(
    tmp_path: Path,
) -> None:
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    env.pop("ANTHROPIC_API_KEY", None)
    env["KAJI_RELEASE_COMMIT"] = "a" * 40
    proof = REPO_ROOT / "kaji" / "scripts" / "live_provider_proof.py"
    result = subprocess.run(
        [
            sys.executable,
            str(proof),
            "--protected",
            "--artifacts-dir",
            str(tmp_path / "artifacts"),
            "--expected-commit",
            "a" * 40,
        ],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 2
    assert "required provider credentials are unavailable" in output
    assert '"failureCode": "missing_required_key"' in output
    assert "PASS:" not in output


def test_protected_provider_proof_uses_one_installed_runtime_for_four_cells() -> None:
    module = _load_root_script("live_provider_proof.py")
    source = (BETA_GATE.parent / "live_provider_proof.py").read_text()

    assert module.CELLS == (
        ("python", "openai"),
        ("typescript", "openai"),
        ("python", "anthropic"),
        ("typescript", "anthropic"),
    )
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "installed_release_runtime"
    ]
    assert len(calls) == 1
    assert "--protected" in source
    assert "--artifacts-dir" in source
    assert "--expected-commit" in source


def test_beta_wrapper_fails_closed_without_frozen_provider_identity(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_beta_gate()

    with pytest.raises(module.GateFailure) as missing_artifacts:
        module.run_keyed_provider_proof({})
    assert missing_artifacts.value.status == 2
    assert "KAJI_RELEASE_ARTIFACTS_DIR is required" in capsys.readouterr().err

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    with pytest.raises(module.GateFailure) as missing_commit:
        module.run_keyed_provider_proof({"KAJI_RELEASE_ARTIFACTS_DIR": str(artifacts)})
    assert missing_commit.value.status == 2
    assert (
        "KAJI_RELEASE_COMMIT must be exactly 40 lowercase hex"
        in capsys.readouterr().err
    )


def test_beta_wrapper_passes_protected_artifact_arguments_to_provider_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_beta_gate()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    environment = {
        "KAJI_RELEASE_ARTIFACTS_DIR": str(artifacts),
        "KAJI_RELEASE_COMMIT": "a" * 40,
    }
    calls: list[tuple[list[str], dict[str, object]]] = []

    def capture(command: list[str], **kwargs: object) -> None:
        calls.append((command, kwargs))

    monkeypatch.setattr(module, "run_checked", capture)

    module.run_keyed_provider_proof(environment)

    assert calls == [
        (
            [
                sys.executable,
                str(BETA_GATE.parent / "live_provider_proof.py"),
                "--protected",
                "--artifacts-dir",
                str(artifacts.resolve()),
                "--expected-commit",
                "a" * 40,
            ],
            {
                "cwd": REPO_ROOT,
                "environment": environment,
                "budget": module.PROVIDER_ORCHESTRATOR_BUDGET,
            },
        )
    ]


def test_release_success_line_disclaims_protected_evidence() -> None:
    literals = {
        node.value
        for node in ast.walk(ast.parse(BETA_GATE.read_text()))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert (
        "PASS: local offline release rehearsal only; commit and pinned-toolchain "
        "enforcement NOT claimed; keyed/provider/publish readiness NOT claimed"
        in literals
    )
    assert (
        "PASS: commit-bound offline release rehearsal; "
        "keyed/provider/publish readiness NOT claimed" in literals
    )
    assert "PASS: Kaji beta release checks completed" not in literals


def test_release_metadata_command_distinguishes_local_and_commit_bound(
    tmp_path: Path,
) -> None:
    module = _load_beta_gate()

    local_label, local_command = module.package_metadata_command({}, tmp_path)
    assert local_label == "Local non-promotable package metadata and checksum manifest"
    assert local_command[-2:] == ["--artifacts-dir", str(tmp_path)]
    assert "--release" not in local_command

    commit = "a" * 40
    release_label, release_command = module.package_metadata_command(
        {"KAJI_RELEASE_COMMIT": commit}, tmp_path
    )
    assert release_label == "Commit-bound package metadata and checksum manifest"
    assert release_command[-5:] == [
        "--release",
        "--commit",
        commit,
        "--artifacts-dir",
        str(tmp_path),
    ]


def test_release_environment_preserves_explicit_toolchain_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_beta_gate()
    pinned_bin = "/private/tmp/kaji-release-bun-1.3.11/.bun/bin"
    monkeypatch.setenv("HOME", "/Users/release")
    monkeypatch.setenv("PATH", f"{pinned_bin}:/usr/bin:/bin")

    environment = module.release_environment()

    assert environment["PATH"].split(os.pathsep)[0] == pinned_bin
    assert "/Users/release/.bun/bin" in environment["PATH"].split(os.pathsep)


def test_beta_release_check_wraps_required_gates() -> None:
    script = BETA_GATE.read_text()

    for expected in [
        '"pytest"',
        '"not integration"',
        '"--cov-fail-under=80"',
        '"scripts/check_types.py"',
        '"scripts/release_smoke.py"',
        '"package:smoke"',
        "live_provider_proof.py",
        "KAJI_REQUIRE_LIVE_KEYS",
        "KAJI_RUN_KEYED_LIVE",
        "UV_SYSTEM_CERTS",
        '"audit:ast-grep"',
        "check_sdk_parity.py",
        "check_integration_abi.py",
        "run_beta_benchmarks.py",
        "integration_benchmark.py",
        "offline_gate.py",
        '"--no-sync"',
        '"--quick"',
    ]:
        assert expected in script

    assert "run_optional_ast_grep" not in script
    assert "SKIP: ast-grep CLI not installed" not in script
    assert script.count('"--cov-fail-under=80"') == 2
    python_workflow = (
        REPO_ROOT / ".github" / "workflows" / "python.test.yml"
    ).read_text()
    assert (
        'pytest tests/ -m "not integration" --cov=kaji --cov-report=xml '
        "--cov-fail-under=80"
    ) in python_workflow
    assert (
        "- uses: ./.github/actions/setup-bun-cache\n"
        "        with:\n"
        "          working-directory: kaji/ts"
    ) in python_workflow
    gate_workflow = (REPO_ROOT / ".github" / "workflows" / "kaji.gate.yml").read_text()
    assert "  pull_request:\n  workflow_dispatch:\n" in gate_workflow
    typescript_workflow = (
        REPO_ROOT / ".github" / "workflows" / "ts.test.yml"
    ).read_text()
    assert "run: bun run test:coverage" in typescript_workflow
    assert 'node-version: "24"' in typescript_workflow

    parity = script.index('"Cross-SDK behavioral parity"')
    assert parity < script.index("run_gates(common_gates(), environment)")
    assert parity < script.index('"Python artifact smoke"')


def test_typescript_build_precedes_every_artifact_consumer() -> None:
    module = _load_beta_gate()
    common = [gate.label for gate in module.common_gates()]
    release = [gate.label for gate in module.release_gates()]

    assert common.index("TypeScript build") < common.index(
        "TypeScript unit tests (offline)"
    )
    assert common.index("TypeScript build") < common.index("TypeScript package smoke")
    assert release.index("TypeScript build (release)") < release.index(
        "TypeScript tests (release, offline)"
    )
    assert release.index("TypeScript build (release)") < release.index(
        "TypeScript package smoke (release)"
    )


def test_integration_quick_benchmark_immediately_follows_core_quick_gate() -> None:
    script = BETA_GATE.read_text()
    core = script.index('"kaji/scripts/run_beta_benchmarks.py"')
    integration = script.index('"kaji/scripts/integration_benchmark.py"')
    common = script.index("run_gates(common_gates(), environment)")
    assert core < integration < common


def test_canonical_typescript_test_script_selects_node() -> None:
    package = json.loads((REPO_ROOT / "kaji" / "ts" / "package.json").read_text())
    command = package["scripts"]["test"]
    coverage_command = package["scripts"]["test:coverage"]
    assert package["devDependencies"]["vitest"] == "4.1.9"
    assert package["devDependencies"]["@vitest/coverage-v8"] == "4.1.9"

    assert command.startswith(
        'PATH="${PATH#*:}:/usr/local/bin:/opt/homebrew/bin" /bin/sh -c '
    )
    assert 'exec "$(command -v node)"' in command
    assert '"$@"' in command
    assert "vitest" in command
    assert '--coverage.include="src/**/*.ts"' in coverage_command
    assert '--coverage.include="registry/**/*.ts"' in coverage_command
    for metric in ("lines", "functions", "branches", "statements"):
        assert f"--coverage.thresholds.{metric}=80" in coverage_command
    commands = {gate.command for gate in _load_beta_gate().common_gates()}
    assert any(command[-3:] == ("bun", "run", "test:coverage") for command in commands)


def test_release_wrapper_runs_superset_once_and_builds_before_consumers(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    scripts = checkout / "kaji" / "scripts"
    typescript = checkout / "kaji" / "ts"
    scripts.mkdir(parents=True)
    typescript.mkdir(parents=True)
    shutil.copy2(BETA_GATE, scripts / BETA_GATE.name)
    shutil.copy2(
        REPO_ROOT / "kaji" / "scripts" / "process_runner.py",
        scripts / "process_runner.py",
    )
    shutil.copy2(
        REPO_ROOT / "kaji" / "scripts" / "offline_gate.py",
        scripts / "offline_gate.py",
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
checkout = Path({str(checkout)!r})
with Path({str(log)!r}).open("a", encoding="utf-8") as stream:
    stream.write(name + "|" + str(Path.cwd()) + "|" + " ".join(args) + "\\n")

if name == "bun":
    dist = checkout / "kaji" / "ts" / "dist"
    if args[:2] == ["run", "build"]:
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "index.js").write_text("built")
    consumer = args[:2] in (["run", "test:coverage"], ["run", "test:quickstart"], ["run", "package:smoke"])
    consumer = consumer or (args and args[0] == "scripts/smoke_package.mts")
    if consumer and not dist.is_dir():
        print("artifact consumer ran before build", file=sys.stderr)
        raise SystemExit(17)

if name == "uv":
    if "scripts/release_smoke.py" in args:
        dist = checkout / "kaji" / "dist"
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
    (destination / "kaji-sdk-0.2.0-beta.2.tgz").write_bytes(b"npm")
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
    environment.pop("GITHUB_SHA", None)
    environment.pop("KAJI_RELEASE_COMMIT", None)
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
    assert "LOCAL REHEARSAL ONLY:" in completed.stdout
    assert "commit and pinned-toolchain enforcement are not active" in completed.stdout
    assert output[-1] == (
        "PASS: local offline release rehearsal only; commit and pinned-toolchain "
        "enforcement NOT claimed; keyed/provider/publish readiness NOT claimed"
    )
    assert "PASS: Kaji beta checks completed" not in completed.stdout
    commands = log.read_text().splitlines()
    build_indices = [
        index
        for index, command in enumerate(commands)
        if command.endswith("|run build")
    ]
    test_indices = [
        index
        for index, command in enumerate(commands)
        if command.endswith("|run test:coverage")
    ]
    assert len(build_indices) == len(test_indices) == 1
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


def test_protected_soak_validates_commit_before_starting_children(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_root_script("run_beta_soak.py")
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: module.argparse.Namespace(
            minutes="30", protected=True, artifacts_dir=tmp_path / "release"
        ),
    )
    monkeypatch.setattr(
        module,
        "release_commit",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("commit mismatch")),
    )
    monkeypatch.setattr(
        module,
        "python_command",
        lambda: (_ for _ in ()).throw(AssertionError("child setup started")),
    )

    assert module.main() == 2
    assert "FAIL: commit mismatch" in capsys.readouterr().err


@pytest.mark.parametrize("failure", ["invalid_minutes", "invalid_args", "missing_uv"])
def test_soak_preflight_atomically_replaces_stale_pass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: str,
) -> None:
    module = _load_root_script("run_beta_soak.py")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    output = tmp_path / ".artifacts" / "kaji-soak" / "results.json"
    output.parent.mkdir(parents=True)
    output.write_text(json.dumps({"passed": True}))
    if failure == "invalid_args":
        monkeypatch.setattr(
            module,
            "parse_args",
            lambda: (_ for _ in ()).throw(SystemExit(2)),
        )
        expected = 2
    else:
        monkeypatch.setattr(
            module,
            "parse_args",
            lambda: module.argparse.Namespace(
                minutes="nan" if failure == "invalid_minutes" else "30",
                protected=False,
                artifacts_dir=None,
            ),
        )
        if failure == "missing_uv":
            monkeypatch.setattr(module, "python_command", lambda: None)
        expected = 2

    assert module.main() == expected
    receipt = json.loads(output.read_text())
    assert receipt["passed"] is False
    assert receipt["failureCode"] != "passed"


def test_soak_receipt_write_failure_removes_stale_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_root_script("run_beta_soak.py")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    output = tmp_path / ".artifacts" / "kaji-soak" / "results.json"
    output.parent.mkdir(parents=True)
    output.write_text(json.dumps({"passed": True}))
    monkeypatch.setattr(
        module,
        "_write_failure_receipt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("write failed")),
    )

    assert module.main() == 1
    assert not output.exists()


def test_protected_soak_context_exit_tamper_overwrites_passed_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_root_script("run_beta_soak.py")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    for name, value in {
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "RUNNER_OS": "macOS",
        "RUNNER_ARCH": "ARM64",
        "ImageOS": "macos15",
        "ImageVersion": "20260715.0234.1",
    }.items():
        monkeypatch.setenv(name, value)
    release = tmp_path / "release"
    release.mkdir()
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: module.argparse.Namespace(
            minutes="30", protected=True, artifacts_dir=release
        ),
    )
    monkeypatch.setattr(module, "release_commit", lambda **_kwargs: "a" * 40)
    monkeypatch.setattr(module, "python_command", lambda: [sys.executable])
    runtime_root = tmp_path / "runtime"
    typescript = runtime_root / "typescript"
    typescript.mkdir(parents=True)
    typescript_soak = typescript / "runtime-soak.ts"
    typescript_soak.write_text("")
    identity = {
        "commit": "a" * 40,
        "releaseManifestSha256": "b" * 64,
        "artifacts": {
            "python": {
                "file": "kaji_sdk-0.2.0b1-py3-none-any.whl",
                "sha256": "c" * 64,
            },
            "typescript": {
                "file": "kaji-sdk-0.2.0-beta.2.tgz",
                "sha256": "d" * 64,
            },
        },
        "resolvedPackages": {
            "python": str(runtime_root / "python/kaji/__init__.py"),
            "typescript": str(typescript / "node_modules/kaji-sdk"),
        },
        "typescriptConsumerLock": {
            "templateSha256": "e" * 64,
            "renderedSha256": "f" * 64,
        },
    }
    runtime = SimpleNamespace(
        python_executable=Path(sys.executable),
        root=runtime_root,
        environment={},
        typescript_workdir=typescript,
        typescript_soak=typescript_soak,
        identity=lambda: identity,
    )

    @contextmanager
    def changed_runtime(*_args: object, **_kwargs: object):
        yield runtime
        raise RuntimeError("release artifact identity changed")

    monkeypatch.setattr(module, "installed_release_runtime", changed_runtime)
    completed = SimpleNamespace(stdout=b"{}")
    commands: list[tuple[str, ...]] = []

    def run_parallel(specs: tuple[object, ...]) -> tuple[object, object]:
        for spec in specs:
            command = getattr(spec, "command")
            assert isinstance(command, tuple)
            commands.append(command)
        return completed, completed

    monkeypatch.setattr(module, "run_parallel_checked", run_parallel)

    def passed_gate(command: list[str], **_kwargs: object) -> SimpleNamespace:
        output = Path(command[command.index("--output") + 1])
        output.write_text(json.dumps({"passed": True, **identity}))
        return completed

    monkeypatch.setattr(module, "run_checked", passed_gate)

    assert module.main() == 1
    receipt = json.loads(
        (tmp_path / ".artifacts" / "kaji-soak" / "results.json").read_text()
    )
    assert receipt["passed"] is False
    assert receipt["failureCode"] == "installed_runtime_failed"
    assert receipt["releaseManifestSha256"] == "b" * 64
    assert "--artifact-dir" in commands[1]
    assert "--artifacts-dir" not in commands[1]


@pytest.mark.parametrize(
    ("mode", "protected"),
    [("quick", True), ("full", False), ("calibrate", False)],
)
def test_installed_benchmark_modes_require_artifacts_before_command_setup(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    protected: bool,
) -> None:
    module = _load_root_script("run_beta_benchmarks.py")
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: module.argparse.Namespace(
            mode=mode,
            protected=protected,
            artifacts_dir=None,
        ),
    )
    monkeypatch.setattr(
        module,
        "commands",
        lambda: (_ for _ in ()).throw(AssertionError("command setup started")),
    )

    assert module.main() == 2
    assert "--artifacts-dir is required" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("mode", "protected"),
    [("full", True), ("calibrate", False)],
)
def test_protected_benchmark_modes_retain_hosted_image_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
    protected: bool,
) -> None:
    module = _load_root_script("run_beta_benchmarks.py")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: module.argparse.Namespace(
            mode=mode,
            protected=protected,
            artifacts_dir=tmp_path / "release",
        ),
    )
    monkeypatch.setattr(module, "commands", lambda: (["python"], ["pytest"]))
    monkeypatch.setenv("KAJI_RELEASE_COMMIT", "a" * 40)
    retained: list[Path] = []

    def successful_gate(command: list[str], **_kwargs: object) -> int:
        output = Path(command[command.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("{}")
        if "--candidate-baseline" in command:
            Path(command[command.index("--candidate-baseline") + 1]).write_text("{}")
        return 0

    monkeypatch.setattr(module, "run", successful_gate)
    monkeypatch.setattr(
        module,
        "retain_reported_github_image_data",
        lambda report: retained.append(report),
    )

    assert module.main() == 0
    assert retained == [
        tmp_path
        / ".artifacts"
        / "kaji-benchmarks"
        / ("results.json" if mode == "full" else "calibration-results.json")
    ]


def test_protected_soak_retains_hosted_image_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_root_script("run_beta_soak.py")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    commit = "a" * 40
    runner_environment = {
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "RUNNER_OS": "macOS",
        "RUNNER_ARCH": "ARM64",
        "ImageOS": "macos15",
        "ImageVersion": "20260715.0234.1",
    }
    monkeypatch.setenv("KAJI_RELEASE_COMMIT", commit)
    for name, value in runner_environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("KAJI_RUNNER_IMAGE_DATA_PATH", "/attacker/imagedata.json")
    monkeypatch.setenv("KAJI_SECRET_CANARY", "sk-parent-secret")
    parent_image_data = tmp_path / "runner-home" / "imagedata.json"
    parent_image_data.parent.mkdir()
    parent_image_data.write_text("parent image data")
    monkeypatch.setattr(module, "IMAGE_DATA_PATH", parent_image_data)
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: module.argparse.Namespace(
            minutes="30", protected=True, artifacts_dir=tmp_path / "release"
        ),
    )
    monkeypatch.setattr(module, "release_commit", lambda **_kwargs: commit)
    monkeypatch.setattr(module, "python_command", lambda: [sys.executable])
    runtime_root = tmp_path / "runtime"
    isolated_home = runtime_root / "home"
    typescript = runtime_root / "typescript"
    typescript.mkdir(parents=True)
    typescript_soak = typescript / "runtime-soak.ts"
    typescript_soak.write_text("")
    runtime = SimpleNamespace(
        python_executable=Path(sys.executable),
        root=runtime_root,
        environment={"HOME": str(isolated_home)},
        typescript_workdir=typescript,
        typescript_soak=typescript_soak,
        identity=lambda: {},
    )

    @contextmanager
    def isolated_runtime(*_args: object, **_kwargs: object):
        yield runtime

    monkeypatch.setattr(module, "installed_release_runtime", isolated_runtime)
    completed = SimpleNamespace(stdout=b"{}")
    monkeypatch.setattr(
        module,
        "run_parallel_checked",
        lambda _specs: (completed, completed),
    )
    gate_commands: list[list[str]] = []
    gate_environments: list[object] = []

    def successful_gate(command: list[str], **kwargs: object) -> SimpleNamespace:
        gate_commands.append(command)
        gate_environments.append(kwargs["env"])
        Path(command[command.index("--output") + 1]).write_text("{}")
        return completed

    monkeypatch.setattr(module, "run_checked", successful_gate)
    retained: list[Path] = []
    monkeypatch.setattr(
        module,
        "retain_reported_github_image_data",
        lambda report: retained.append(report),
    )

    assert module.main() == 0
    assert retained == [tmp_path / ".artifacts" / "kaji-soak" / "results.json"]
    assert gate_commands[0][gate_commands[0].index("--runner-image-data") + 1] == str(
        parent_image_data
    )
    assert gate_environments == [
        {
            "HOME": str(isolated_home),
            "KAJI_RELEASE_COMMIT": commit,
            **runner_environment,
        }
    ]


@pytest.mark.parametrize(
    "missing",
    [
        "GITHUB_ACTIONS",
        "RUNNER_ENVIRONMENT",
        "RUNNER_OS",
        "RUNNER_ARCH",
        "ImageOS",
        "ImageVersion",
    ],
)
def test_protected_soak_gate_environment_requires_parent_runner_identity(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    module = _load_root_script("run_beta_soak.py")
    for name, value in {
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "RUNNER_OS": "macOS",
        "RUNNER_ARCH": "ARM64",
        "ImageOS": "macos15",
        "ImageVersion": "20260715.0234.1",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(missing)

    with pytest.raises(RuntimeError, match=missing):
        module._protected_gate_environment({"HOME": "/isolated"}, "a" * 40)


def test_protected_soak_requires_artifacts_before_child_setup(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_root_script("run_beta_soak.py")
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: module.argparse.Namespace(
            minutes="30", protected=True, artifacts_dir=None
        ),
    )
    monkeypatch.setattr(
        module,
        "python_command",
        lambda: (_ for _ in ()).throw(AssertionError("child setup started")),
    )

    assert module.main() == 2
    assert "--artifacts-dir is required" in capsys.readouterr().err


def test_installed_runtime_rejects_source_and_workspace_resolution(
    tmp_path: Path,
) -> None:
    module = _load_root_script("installed_release_runtime.py")
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    installed = isolated / "site-packages" / "kaji" / "__init__.py"
    installed.parent.mkdir(parents=True)
    installed.write_text("")

    assert (
        module._require_contained(installed, isolated, "python") == installed.resolve()
    )
    for unsafe in (
        REPO_ROOT / "kaji" / "src" / "kaji" / "__init__.py",
        REPO_ROOT / "kaji" / "ts" / "src",
        REPO_ROOT / "kaji" / "ts" / "package.json",
    ):
        with pytest.raises(RuntimeError, match="outside the isolated runtime"):
            module._require_contained(unsafe, isolated, "package")


def test_installed_runtime_renders_only_verified_tarball_integrity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_root_script("installed_release_runtime.py")
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    manifest = fixture / "package.json"
    lock = fixture / "package-lock.json"
    manifest.write_text(
        json.dumps(
            {
                "name": "kaji-installed-release-runtime",
                "private": True,
                "type": "module",
                "dependencies": {
                    "kaji-sdk": "file:kaji-sdk-0.2.0-beta.2.tgz",
                    "zod": "4.4.3",
                },
            }
        )
    )
    template = {
        "name": "kaji-installed-release-runtime",
        "lockfileVersion": 3,
        "requires": True,
        "packages": {
            "": {
                "name": "kaji-installed-release-runtime",
                "dependencies": {
                    "kaji-sdk": "file:kaji-sdk-0.2.0-beta.2.tgz",
                    "zod": "4.4.3",
                },
            },
            "node_modules/kaji-sdk": {
                "version": "0.2.0-beta.2",
                "resolved": "file:kaji-sdk-0.2.0-beta.2.tgz",
                "integrity": "sha512-template",
            },
            "node_modules/zod": {
                "version": "4.4.3",
                "resolved": "https://registry.npmjs.org/zod/-/zod-4.4.3.tgz",
                "integrity": "sha512-zod",
            },
        },
    }
    lock.write_text(json.dumps(template))
    tarball = tmp_path / "kaji-sdk-0.2.0-beta.2.tgz"
    tarball.write_bytes(b"verified tarball bytes")
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    monkeypatch.setattr(module, "TS_CONSUMER_MANIFEST", manifest)
    monkeypatch.setattr(module, "TS_CONSUMER_LOCK", lock)

    template_hash, rendered_hash = module._render_typescript_consumer(consumer, tarball)

    rendered = json.loads((consumer / "package-lock.json").read_text())
    assert template_hash == hashlib.sha256(lock.read_bytes()).hexdigest()
    assert (
        rendered_hash
        == hashlib.sha256((consumer / "package-lock.json").read_bytes()).hexdigest()
    )
    assert (
        rendered["packages"]["node_modules/zod"]
        == template["packages"]["node_modules/zod"]
    )
    assert rendered["packages"]["node_modules/kaji-sdk"]["integrity"].startswith(
        "sha512-"
    )
    assert lock.read_text() == json.dumps(template)


def test_installed_typescript_consumer_uses_frozen_npm_ci_contract() -> None:
    module = _load_root_script("installed_release_runtime.py")
    manifest = json.loads(module.TS_CONSUMER_MANIFEST.read_text())
    lock = json.loads(module.TS_CONSUMER_LOCK.read_text())

    assert lock["lockfileVersion"] == 3
    assert lock["packages"][""]["dependencies"] == manifest["dependencies"]
    assert lock["packages"]["node_modules/kaji-sdk"]["resolved"] == (
        "file:kaji-sdk-0.2.0-beta.2.tgz"
    )
    for name, package in lock["packages"].items():
        if not name or name == "node_modules/kaji-sdk":
            continue
        assert package["resolved"].startswith("https://registry.npmjs.org/")
        assert re.fullmatch(r"sha512-[A-Za-z0-9+/]+={0,2}", package["integrity"])
    source = module._install_typescript.__code__.co_consts
    assert "ci" in source
    assert "install" not in source


@pytest.mark.parametrize(
    ("include_providers", "expected_extras"),
    [
        (False, []),
        (True, ["openai", "anthropic"]),
    ],
)
def test_installed_python_provider_dependencies_are_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    include_providers: bool,
    expected_extras: list[str],
) -> None:
    module = _load_root_script("installed_release_runtime.py")
    root = tmp_path / "runtime"
    package = root / "python" / "site-packages" / "kaji" / "__init__.py"
    package.parent.mkdir(parents=True)
    package.write_text("")
    wheel = tmp_path / "kaji_sdk-0.2.0b1-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    release = SimpleNamespace(python_wheel=wheel)
    commands: list[list[str]] = []

    monkeypatch.setattr(
        module.shutil,
        "which",
        lambda command, **_kwargs: "/tools/uv" if command == "uv" else None,
    )
    monkeypatch.setattr(
        module,
        "run_checked",
        lambda command, **_kwargs: commands.append(command),
    )
    monkeypatch.setattr(module, "_capture_json", lambda *_args, **_kwargs: str(package))

    module._install_python(
        root,
        release,
        {"PATH": "/tools"},
        include_providers=include_providers,
    )

    export = next(command for command in commands if command[1] == "export")
    extras = [
        export[index + 1]
        for index, argument in enumerate(export)
        if argument == "--extra"
    ]
    assert extras == expected_extras


@pytest.mark.parametrize(
    ("include_providers", "expected_providers"),
    [
        (False, set()),
        (True, {"openai", "@anthropic-ai/sdk"}),
    ],
)
def test_installed_typescript_provider_dependencies_are_opt_in(
    include_providers: bool,
    expected_providers: set[str],
) -> None:
    module = _load_root_script("installed_release_runtime.py")
    manifest, lock = module._typescript_consumer_fixture(include_providers)
    manifest_dependencies = json.loads(manifest.read_text())["dependencies"]
    lock_dependencies = json.loads(lock.read_text())["packages"][""]["dependencies"]
    providers = {"openai", "@anthropic-ai/sdk"}

    assert providers.intersection(manifest_dependencies) == expected_providers
    assert providers.intersection(lock_dependencies) == expected_providers
    assert manifest_dependencies == lock_dependencies


def test_installed_runtime_rejects_wrong_commit_before_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_root_script("installed_release_runtime.py")
    monkeypatch.setattr(
        module,
        "verify",
        lambda *_args: (_ for _ in ()).throw(SystemExit("FAIL: commit mismatch")),
    )
    monkeypatch.setattr(
        module,
        "_install_python",
        lambda *_args: (_ for _ in ()).throw(AssertionError("install started")),
    )

    with pytest.raises(SystemExit, match="commit mismatch"):
        with module.installed_release_runtime(tmp_path, expected_commit="a" * 40):
            pass


def test_installed_runtime_environment_drops_loader_injection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_root_script("installed_release_runtime.py")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    for name in ("PYTHONPATH", "PYTHONHOME", "NODE_PATH", "NODE_OPTIONS"):
        monkeypatch.setenv(name, f"unsafe-{name.lower()}")

    environment = module._safe_environment(tmp_path)

    assert environment["HOME"].startswith(str(tmp_path))
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert environment["PYTHONSAFEPATH"] == "1"
    for name in ("PYTHONPATH", "PYTHONHOME", "NODE_PATH", "NODE_OPTIONS"):
        assert name not in environment


def test_installed_runtime_reverifies_hashes_after_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_root_script("installed_release_runtime.py")
    wheel = tmp_path / "kaji_sdk-0.2.0b1-py3-none-any.whl"
    sdist = tmp_path / "kaji_sdk-0.2.0b1.tar.gz"
    tarball = tmp_path / "kaji-sdk-0.2.0-beta.2.tgz"
    for path in (wheel, sdist, tarball):
        path.write_bytes(b"artifact")

    def release(manifest_hash: str):
        return module.VerifiedReleaseArtifacts(
            root=tmp_path,
            commit="a" * 40,
            manifest_sha256=manifest_hash,
            python_wheel=wheel,
            python_sdist=sdist,
            npm_tarball=tarball,
            artifact_sha256={path.name: "c" * 64 for path in (wheel, sdist, tarball)},
        )

    verified = iter((release("b" * 64), release("d" * 64)))
    monkeypatch.setattr(module, "verify", lambda *_args: next(verified))

    def fake_python(root: Path, *_args, **_kwargs):
        executable = root / "python" / "bin" / "python"
        package = root / "python" / "site-packages" / "kaji" / "__init__.py"
        executable.parent.mkdir(parents=True)
        package.parent.mkdir(parents=True)
        executable.write_text("")
        package.write_text("")
        return executable, package

    def fake_typescript(root: Path, *_args, **_kwargs):
        consumer = root / "typescript"
        package = consumer / "node_modules" / "kaji-sdk"
        consumer.mkdir()
        package.mkdir(parents=True)
        benchmark = consumer / "runtime-benchmark.ts"
        soak = consumer / "runtime-soak.ts"
        benchmark.write_text("")
        soak.write_text("")
        return consumer, benchmark, soak, package, "e" * 64, "f" * 64

    monkeypatch.setattr(module, "_install_python", fake_python)
    monkeypatch.setattr(module, "_install_typescript", fake_typescript)

    with pytest.raises(RuntimeError, match="changed while evidence was running"):
        with module.installed_release_runtime(tmp_path, expected_commit="a" * 40):
            pass


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


def _valid_worst_case_sample(case: str) -> dict[str, object]:
    common: dict[str, object] = {"durationMs": 1.0, "peakMiB": 32.0}
    cases: dict[str, dict[str, object]] = {
        "replay10k": {"eventsApplied": 10_000, "cursor": 10_000},
        "crossSession100": {
            "maxActive": 100,
            "turns": 100,
            "coordinatorEntries": 0,
            "coordinatorWaiters": 0,
        },
        "sameSession25": {
            "maxActive": 1,
            "turns": 25,
            "coordinatorEntries": 0,
            "coordinatorWaiters": 0,
        },
        "toolBatch100": {"maxActive": 4, "calls": 100, "stuckCalls": 0},
        "context10kIterations5": {
            "historyEvents": 10_000,
            "fullHistoryScans": 1,
            "providerIterations": 5,
            "coldEvents": 10_000,
            "incrementalEvents": 21,
            "suffixCalls": 5,
            "copiedPayloadBytes": 0,
            "retainedTurns": 32,
            "turnIndexEntries": 32,
            "sentinelEntries": 1,
            "totalIndexEntries": 33,
            "maxVisitedTurnEntries": 32,
            "incrementalRssBytes": 1_024,
            "timerLeaks": 0,
            "providerTaskLeaks": 0,
        },
        "crossSessionCommit100": {
            "sessions": 100,
            "commits": 100,
            "overlappingSessions": 99,
            "contiguousSessions": 100,
            "laneEntriesAfter": 0,
            "reservationEntriesAfter": 0,
        },
        "streamDeltas10k": {
            "characters": 10_000,
            "deltaEvents": 3,
            "inputFragments": 10_000,
            "deltaJoinOperations": 3,
            "responseJoinOperations": 1,
            "providerTextMaxBytes": 262_144,
            "providerResponseMaxBytes": 524_288,
            "completionEvents": 1,
            "completionEventsAfterFailure": 0,
            "timerLeaks": 0,
            "providerTaskLeaks": 0,
        },
        "toolArgDeltas10k": {
            "argumentBytes": 65_536,
            "responseMaxBytes": 524_288,
            "argumentFragments": 10_000,
            "rawFragments": 10_002,
            "fragmentJoins": 1,
            "overLimitBytes": 65_537,
            "overLimitRejectedBeforeParse": True,
            "iteratorLeaks": 0,
            "parserLeaks": 0,
            "providerTaskLeaks": 0,
        },
    }
    return {**common, **cases[case]}


def test_beta_benchmark_gate_defines_all_eight_cases_and_semantic_budgets() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    budgets = json.loads(
        (REPO_ROOT / "kaji" / "benchmarks" / "beta-budgets.json").read_text()
    )

    assert module.CASES == (
        "replay10k",
        "crossSession100",
        "sameSession25",
        "toolBatch100",
        "context10kIterations5",
        "crossSessionCommit100",
        "streamDeltas10k",
        "toolArgDeltas10k",
    )
    assert budgets["context10kIterations5"] == {
        "maxFullHistoryScans": 1,
        "maxProviderIterations": 5,
        "maxCopiedPayloadBytes": 0,
        "maxIndexEntriesPerRetainedTurn": 1.01,
        "maxIncrementalRssBytes": 67_108_864,
        "maxSentinelEntries": 1,
        "maxSuffixTurnVisits": 32,
        "maxTimerLeaks": 0,
        "maxProviderTaskLeaks": 0,
    }
    assert budgets["crossSessionCommit100"] == {
        "minOverlappingSessions": 2,
        "maxLaneEntriesAfter": 0,
        "maxReservationEntriesAfter": 0,
    }
    assert budgets["streamDeltas10k"] == {
        "maxDeltaEvents": 16,
        "expectedCharacters": 10_000,
        "maxProviderTextBytes": 262_144,
        "maxProviderResponseBytes": 524_288,
        "maxTimerLeaks": 0,
        "maxProviderTaskLeaks": 0,
    }
    assert budgets["toolArgDeltas10k"] == {
        "maxArgumentBytes": 65_536,
        "maxResponseBytes": 524_288,
        "maxFragmentJoins": 1,
        "maxIteratorLeaks": 0,
        "maxParserLeaks": 0,
        "maxProviderTaskLeaks": 0,
    }


def test_beta_benchmark_gate_rejects_missing_counter_in_each_sample() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    budgets = json.loads(module.BUDGETS_PATH.read_text())
    sample = _valid_worst_case_sample("context10kIterations5")
    sample.pop("timerLeaks")

    failures = module._sample_failures(
        "python", "context10kIterations5", sample, budgets["context10kIterations5"]
    )

    assert any("timerLeaks" in failure for failure in failures)


@pytest.mark.parametrize(
    "case",
    [
        "replay10k",
        "crossSession100",
        "sameSession25",
        "toolBatch100",
        "context10kIterations5",
        "crossSessionCommit100",
        "streamDeltas10k",
        "toolArgDeltas10k",
    ],
)
def test_beta_benchmark_gate_accepts_valid_semantics_for_every_case(case: str) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    budgets = json.loads(module.BUDGETS_PATH.read_text())

    assert (
        module._sample_failures(
            "python", case, _valid_worst_case_sample(case), budgets[case]
        )
        == []
    )


@pytest.mark.parametrize(
    ("case", "field", "value"),
    [
        ("replay10k", "eventsApplied", 9_999),
        ("crossSession100", "turns", 99),
        ("sameSession25", "turns", 24),
        ("toolBatch100", "calls", 99),
        ("context10kIterations5", "providerIterations", 4),
        ("crossSessionCommit100", "sessions", 99),
        ("streamDeltas10k", "characters", 9_999),
        ("toolArgDeltas10k", "argumentBytes", 65_535),
    ],
)
def test_beta_benchmark_gate_rejects_invalid_semantics_for_every_case(
    case: str, field: str, value: int
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    budgets = json.loads(module.BUDGETS_PATH.read_text())
    sample = {**_valid_worst_case_sample(case), field: value}

    failures = module._sample_failures("python", case, sample, budgets[case])

    assert any(field in failure for failure in failures)


@pytest.mark.parametrize(
    ("case", "expected"), [("crossSession100", 100), ("sameSession25", 25)]
)
@pytest.mark.parametrize("value", [None, -1, 1])
def test_beta_benchmark_gate_requires_exact_concurrency_turns(
    case: str, expected: int, value: int | None
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    budgets = json.loads(module.BUDGETS_PATH.read_text())
    sample = _valid_worst_case_sample(case)
    if value is None:
        sample.pop("turns")
    else:
        sample["turns"] = expected + value

    failures = module._sample_failures("typescript", case, sample, budgets[case])

    assert any("turns" in failure for failure in failures)


def test_beta_benchmark_gate_rejects_non_object_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    payload = {
        "schemaVersion": 1,
        "runtime": "python",
        "case": "replay10k",
        "samples": 1,
        "warmups": 1,
        "seed": 13,
        "sampleResults": [42],
        "medianMs": 1.0,
        "maxPeakMiB": 32.0,
    }
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(payload).encode()
    )
    monkeypatch.setattr(module, "run_checked", lambda *_args, **_kwargs: completed)

    with pytest.raises(RuntimeError, match="sample 1 is not an object"):
        module._run_case("python", "replay10k", 1, 1)


def test_beta_benchmark_gate_rejects_wrong_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    payload = {
        "schemaVersion": 1,
        "runtime": "python",
        "case": "replay10k",
        "samples": 1,
        "warmups": 1,
        "seed": 14,
        "sampleResults": [{"durationMs": 1.0, "peakMiB": 32.0}],
        "medianMs": 1.0,
        "maxPeakMiB": 32.0,
    }
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(payload).encode()
    )
    monkeypatch.setattr(module, "run_checked", lambda *_args, **_kwargs: completed)

    with pytest.raises(RuntimeError, match="wrong seed"):
        module._run_case("python", "replay10k", 1, 1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("medianMs", float("nan")),
        ("maxPeakMiB", float("nan")),
        ("medianMs", -1.0),
        ("maxPeakMiB", -1.0),
    ],
)
def test_beta_benchmark_gate_rejects_invalid_runtime_aggregate(
    monkeypatch: pytest.MonkeyPatch, field: str, value: float
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    payload = {
        "schemaVersion": 1,
        "runtime": "python",
        "case": "replay10k",
        "samples": 3,
        "warmups": 2,
        "seed": 13,
        "sampleResults": [
            {"durationMs": 1.0, "peakMiB": 30.0},
            {"durationMs": 2.0, "peakMiB": 32.0},
            {"durationMs": 3.0, "peakMiB": 31.0},
        ],
        "medianMs": 2.0,
        "maxPeakMiB": 32.0,
    }
    payload[field] = value
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(payload).encode()
    )
    monkeypatch.setattr(module, "run_checked", lambda *_args, **_kwargs: completed)

    with pytest.raises(RuntimeError, match=f"{field} must be finite and non-negative"):
        module._run_case("python", "replay10k", 3, 2)


@pytest.mark.parametrize(
    ("field", "value", "derived"),
    [("medianMs", 1.0, "median"), ("maxPeakMiB", 31.0, "maximum")],
)
def test_beta_benchmark_gate_rejects_mismatched_runtime_aggregate(
    monkeypatch: pytest.MonkeyPatch, field: str, value: float, derived: str
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    payload = {
        "schemaVersion": 1,
        "runtime": "python",
        "case": "replay10k",
        "samples": 3,
        "warmups": 2,
        "seed": 13,
        "sampleResults": [
            {"durationMs": 1.0, "peakMiB": 30.0},
            {"durationMs": 2.0, "peakMiB": 32.0},
            {"durationMs": 3.0, "peakMiB": 31.0},
        ],
        "medianMs": 2.0,
        "maxPeakMiB": 32.0,
    }
    payload[field] = value
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(payload).encode()
    )
    monkeypatch.setattr(module, "run_checked", lambda *_args, **_kwargs: completed)

    with pytest.raises(RuntimeError, match=f"does not match sample {derived}"):
        module._run_case("python", "replay10k", 3, 2)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), -1.0])
def test_beta_benchmark_gate_rejects_non_finite_or_negative_counter(
    value: float,
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    budgets = json.loads(module.BUDGETS_PATH.read_text())
    sample = {**_valid_worst_case_sample("streamDeltas10k"), "deltaEvents": value}

    failures = module._sample_failures(
        "python", "streamDeltas10k", sample, budgets["streamDeltas10k"]
    )

    assert any(
        "deltaEvents" in failure and "non-finite or negative" in failure
        for failure in failures
    )


def test_beta_benchmark_gate_enforces_every_measured_sample() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    budgets = json.loads(module.BUDGETS_PATH.read_text())
    first = _valid_worst_case_sample("streamDeltas10k")
    second = {**first, "deltaEvents": 17}
    results = {
        "streamDeltas10k": {
            "sampleResults": [first, second],
            "medianMs": 1.0,
            "maxPeakMiB": 32.0,
        }
    }

    failures = module._case_failures(
        "python", "streamDeltas10k", results["streamDeltas10k"], budgets, False
    )

    assert any(
        "sample 2" in failure and "deltaEvents" in failure for failure in failures
    )


@pytest.mark.parametrize(
    ("updates", "counter"),
    [
        ({"retainedTurns": 0}, "retainedTurns"),
        ({"turnIndexEntries": 33}, "turnIndexEntries"),
        ({"sentinelEntries": 2, "totalIndexEntries": 34}, "sentinelEntries"),
    ],
)
def test_beta_benchmark_gate_validates_context_entry_ratio_and_sentinel(
    updates: dict[str, object], counter: str
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    budgets = json.loads(module.BUDGETS_PATH.read_text())
    sample = {**_valid_worst_case_sample("context10kIterations5"), **updates}

    failures = module._sample_failures(
        "python", "context10kIterations5", sample, budgets["context10kIterations5"]
    )

    assert any(counter in failure for failure in failures)


def test_beta_benchmark_timing_runs_only_in_full_mode() -> None:
    module = _load_root_script("beta_benchmark_gate.py")

    assert module._include_timing("quick") is False
    assert module._include_timing("calibrate") is False
    assert module._include_timing("full") is True


def _github_image_data(
    *,
    os_version: str = "15.7.7",
    os_build: str = "24G720",
    image_label: str = "macos-15-arm64",
    image_version: str = "20260715.0234.1",
    included_software: str | None = None,
    image_release: str | None = None,
) -> list[dict[str, str]]:
    release_version = ".".join(image_version.split(".")[:2])
    included_software = included_software or (
        "https://github.com/actions/runner-images/blob/"
        f"{image_label}/{release_version}/images/macos/{image_label}-Readme.md"
    )
    image_release = image_release or (
        "https://github.com/actions/runner-images/releases/tag/"
        f"{image_label}%2F{release_version}"
    )
    return [
        {
            "group": "Operating System",
            "detail": f"macOS\n{os_version}\n{os_build}",
        },
        {
            "group": "Runner Image",
            "detail": (
                f"Image: {image_label}\n"
                f"Version: {image_version}\n"
                f"Included Software: {included_software}\n"
                f"Image Release: {image_release}"
            ),
        },
    ]


def _hosted_runner_environment(
    module: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    image_data: object | None = None,
    encoded: bytes | None = None,
) -> Path:
    home = tmp_path / "runner-home"
    home.mkdir()
    path = home / "imagedata.json"
    path.write_bytes(
        encoded
        if encoded is not None
        else json.dumps(
            _github_image_data() if image_data is None else image_data
        ).encode()
    )
    monkeypatch.setattr(module, "IMAGE_DATA_PATH", path)
    for name, value in {
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "RUNNER_OS": "macOS",
        "RUNNER_ARCH": "ARM64",
        "ImageOS": "macos15",
        "ImageVersion": "20260715.0234.1",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(module.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        module.platform, "mac_ver", lambda: ("15.7.7", ("", "", ""), "")
    )
    return path


def test_protected_benchmark_runner_measures_closed_github_hosted_fingerprint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_root_script("benchmark_platform.py")
    image_data = _hosted_runner_environment(module, monkeypatch, tmp_path)

    runner = module.require_github_hosted_macos_arm64(protected=True, calibrating=False)

    assert runner == {
        "environment": "github-hosted",
        "os": "Darwin",
        "arch": "arm64",
        "platformVersion": "15.7.7",
        "imageOS": "macos15",
        "imageLabel": "macos-15-arm64",
        "imageVersion": "20260715.0234.1",
        "imageDataSha256": hashlib.sha256(image_data.read_bytes()).hexdigest(),
    }
    assert module.validate_retained_runner(runner) == runner


@pytest.mark.parametrize("image_version", ["20250226.766", "20260715.0234.1"])
def test_protected_benchmark_runner_accepts_official_image_version_shapes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, image_version: str
) -> None:
    module = _load_root_script("benchmark_platform.py")
    document = _github_image_data(image_version=image_version)
    _hosted_runner_environment(module, monkeypatch, tmp_path, image_data=document)
    monkeypatch.delenv("ImageOS")
    monkeypatch.delenv("ImageVersion")

    runner = module.require_github_hosted_macos_arm64(protected=True, calibrating=False)

    assert runner["imageOS"] == "macos15"
    assert runner["imageVersion"] == image_version


def test_protected_benchmark_runner_uses_explicit_parent_image_data_with_isolated_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_root_script("benchmark_platform.py")
    parent_image_data = _hosted_runner_environment(module, monkeypatch, tmp_path)
    isolated_home = tmp_path / "isolated-home"
    isolated_home.mkdir()
    monkeypatch.setenv("HOME", str(isolated_home))
    monkeypatch.setattr(module, "IMAGE_DATA_PATH", isolated_home / "imagedata.json")

    runner = module.require_github_hosted_macos_arm64(
        protected=True,
        calibrating=False,
        image_data_path=parent_image_data,
    )

    assert (
        runner["imageDataSha256"]
        == hashlib.sha256(parent_image_data.read_bytes()).hexdigest()
    )
    assert not (isolated_home / "imagedata.json").exists()


@pytest.mark.parametrize("case", ["missing", "forged", "relative"])
def test_protected_benchmark_runner_rejects_invalid_explicit_image_data_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, case: str
) -> None:
    module = _load_root_script("benchmark_platform.py")
    _hosted_runner_environment(module, monkeypatch, tmp_path)
    image_data_path = tmp_path / "missing-imagedata.json"
    if case == "forged":
        image_data_path.write_text(
            json.dumps(_github_image_data(image_version="20260708.0157.1"))
        )
    elif case == "relative":
        image_data_path = Path("relative-imagedata.json")

    with pytest.raises(RuntimeError, match="image data"):
        module.require_github_hosted_macos_arm64(
            protected=True,
            calibrating=False,
            image_data_path=image_data_path,
        )


@pytest.mark.parametrize(
    ("name", "value", "expected"),
    [
        ("GITHUB_ACTIONS", "false", "GitHub Actions"),
        ("RUNNER_ENVIRONMENT", "self-hosted", "GitHub-hosted runner"),
        ("RUNNER_OS", "Linux", "runner OS"),
        ("RUNNER_ARCH", "X64", "runner architecture"),
        ("ImageOS", "macos14", "ImageOS"),
        ("ImageVersion", "20260708.0157.1", "ImageVersion"),
    ],
)
def test_protected_benchmark_runner_rejects_wrong_runner_classification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    name: str,
    value: str,
    expected: str,
) -> None:
    module = _load_root_script("benchmark_platform.py")
    _hosted_runner_environment(module, monkeypatch, tmp_path)
    monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match=expected):
        module.require_github_hosted_macos_arm64(protected=True, calibrating=False)


@pytest.mark.parametrize(
    ("system", "machine", "version", "expected"),
    [
        ("Linux", "arm64", "15.7.7", "arm64 macOS"),
        ("Darwin", "x86_64", "15.7.7", "arm64 macOS"),
        ("Darwin", "arm64", "", "macOS 15 version"),
        ("Darwin", "arm64", "15", "macOS 15 version"),
        ("Darwin", "arm64", "15.7.7-beta", "macOS 15 version"),
        ("Darwin", "arm64", "16.0", "macOS 15 version"),
    ],
)
def test_protected_benchmark_runner_rejects_wrong_actual_host(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    system: str,
    machine: str,
    version: str,
    expected: str,
) -> None:
    module = _load_root_script("benchmark_platform.py")
    _hosted_runner_environment(module, monkeypatch, tmp_path)
    monkeypatch.setattr(module.platform, "system", lambda: system)
    monkeypatch.setattr(module.platform, "machine", lambda: machine)
    monkeypatch.setattr(module.platform, "mac_ver", lambda: (version, ("", "", ""), ""))

    with pytest.raises(RuntimeError, match=expected):
        module.require_github_hosted_macos_arm64(protected=True, calibrating=False)


@pytest.mark.parametrize(
    "case",
    [
        "missing-file",
        "directory",
        "symlink",
        "oversize",
        "raced",
    ],
)
def test_protected_benchmark_runner_rejects_unsafe_image_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, case: str
) -> None:
    module = _load_root_script("benchmark_platform.py")
    image_data = _hosted_runner_environment(module, monkeypatch, tmp_path)
    if case == "missing-file":
        monkeypatch.setattr(module, "IMAGE_DATA_PATH", tmp_path / "missing.json")
    elif case == "directory":
        monkeypatch.setattr(module, "IMAGE_DATA_PATH", tmp_path)
    elif case == "symlink":
        link = tmp_path / "imagedata-link.json"
        link.symlink_to(image_data)
        monkeypatch.setattr(module, "IMAGE_DATA_PATH", link)
    elif case == "oversize":
        image_data.write_bytes(b"x" * (8 * 1024 + 1))
    elif case == "raced":
        real_fstat = module.os.fstat
        calls = 0

        def raced_fstat(descriptor: int) -> Any:
            nonlocal calls
            calls += 1
            measured = real_fstat(descriptor)
            if calls == 2:
                return SimpleNamespace(
                    st_dev=measured.st_dev,
                    st_ino=measured.st_ino,
                    st_mode=measured.st_mode,
                    st_size=measured.st_size,
                    st_mtime_ns=measured.st_mtime_ns + 1,
                )
            return measured

        monkeypatch.setattr(module.os, "fstat", raced_fstat)

    with pytest.raises(RuntimeError, match="image data"):
        module.require_github_hosted_macos_arm64(protected=True, calibrating=False)


@pytest.mark.parametrize(
    "case",
    [
        "malformed-json",
        "duplicate-key",
        "extra-row",
        "extra-key",
        "wrong-group",
        "wrong-os-version",
        "wrong-image-label",
        "malformed-image-version",
        "wrong-included-software",
        "wrong-image-release",
    ],
)
def test_protected_benchmark_runner_rejects_invalid_image_data_schema(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, case: str
) -> None:
    module = _load_root_script("benchmark_platform.py")
    document = _github_image_data()
    encoded: bytes | None = None
    if case == "malformed-json":
        encoded = b"{"
    elif case == "duplicate-key":
        encoded = (
            b'[{"group":"Operating System","group":"Runner Image",'
            b'"detail":"macOS\\n15.7.7\\n24G720"},'
            + json.dumps(document[1]).encode()
            + b"]"
        )
    elif case == "extra-row":
        document.append({"group": "extra", "detail": "extra"})
    elif case == "extra-key":
        document[0]["extra"] = "not closed"
    elif case == "wrong-group":
        document.reverse()
    elif case == "wrong-os-version":
        document[0]["detail"] = "macOS\n15.7.6\n24G720"
    elif case == "wrong-image-label":
        document = _github_image_data(image_label="macos-15")
    elif case == "malformed-image-version":
        document = _github_image_data(image_version="latest")
    elif case == "wrong-included-software":
        document = _github_image_data(
            included_software="https://example.invalid/software"
        )
    elif case == "wrong-image-release":
        document = _github_image_data(image_release="https://example.invalid/release")
    _hosted_runner_environment(
        module,
        monkeypatch,
        tmp_path,
        image_data=document,
        encoded=encoded,
    )

    with pytest.raises(RuntimeError, match="image data"):
        module.require_github_hosted_macos_arm64(protected=True, calibrating=False)


def test_validated_image_data_can_be_retained_with_its_exact_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_root_script("benchmark_platform.py")
    source = _hosted_runner_environment(module, monkeypatch, tmp_path)
    runner = module.require_github_hosted_macos_arm64(protected=True, calibrating=False)
    destination = tmp_path / "artifacts" / "imagedata.json"
    destination.parent.mkdir()

    retained = module.retain_github_image_data(
        destination, image_data_sha256=runner["imageDataSha256"]
    )

    assert retained == runner["imageDataSha256"]
    assert destination.read_bytes() == source.read_bytes()
    assert hashlib.sha256(destination.read_bytes()).hexdigest() == retained


@pytest.mark.parametrize(
    "case", ["hash-mismatch", "existing", "symlink", "parent-link"]
)
def test_image_data_retention_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, case: str
) -> None:
    module = _load_root_script("benchmark_platform.py")
    source = _hosted_runner_environment(module, monkeypatch, tmp_path)
    runner = module.require_github_hosted_macos_arm64(protected=True, calibrating=False)
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    destination = artifact_dir / "imagedata.json"
    expected = runner["imageDataSha256"]
    if case == "hash-mismatch":
        source.write_bytes(source.read_bytes() + b"\n")
    elif case == "existing":
        destination.write_text("owned")
    elif case == "symlink":
        target = tmp_path / "target"
        target.write_text("owned")
        destination.symlink_to(target)
    elif case == "parent-link":
        real_parent = tmp_path / "real-artifacts"
        real_parent.mkdir()
        linked_parent = tmp_path / "linked-artifacts"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        destination = linked_parent / "imagedata.json"

    with pytest.raises(RuntimeError, match="retain|hash"):
        module.retain_github_image_data(destination, image_data_sha256=expected)

    if case != "hash-mismatch":
        assert not destination.is_file() or destination.read_text() == "owned"


@pytest.mark.parametrize(
    "runner",
    [
        {
            "os": "Darwin",
            "arch": "arm64",
            "platformVersion": "15.7.7",
            "imageDigest": "sha256:" + "a" * 64,
        },
        {
            "environment": "github-hosted",
            "os": "Darwin",
            "arch": "arm64",
            "platformVersion": "15.7.7",
            "imageOS": "macos15",
            "imageLabel": "macos-15-arm64",
            "imageVersion": "20260715.0234.1",
            "bootstrapManifestSha256": "a" * 64,
            "extra": True,
        },
        {
            "environment": "self-hosted",
            "os": "Darwin",
            "arch": "arm64",
            "platformVersion": "15.7.7",
            "imageOS": "macos15",
            "imageLabel": "macos-15-arm64",
            "imageVersion": "20260715.0234.1",
            "imageDataSha256": "a" * 64,
        },
    ],
)
def test_retained_benchmark_runner_shape_is_closed(runner: dict[str, object]) -> None:
    module = _load_root_script("benchmark_platform.py")

    with pytest.raises(RuntimeError, match="runner fingerprint"):
        module.validate_retained_runner(runner)


def test_reported_github_image_data_is_retained_with_fingerprint_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_root_script("benchmark_platform.py")
    source = _hosted_runner_environment(module, monkeypatch, tmp_path)
    runner = module.require_github_hosted_macos_arm64(protected=True, calibrating=False)
    assert runner is not None
    report = tmp_path / "evidence" / "results.json"
    report.parent.mkdir()
    report.write_text(json.dumps({"fingerprint": {"runner": runner}}))

    destination = module.retain_reported_github_image_data(report)

    assert destination == report.parent / "imagedata.json"
    assert destination.read_bytes() == source.read_bytes()
    assert (
        hashlib.sha256(destination.read_bytes()).hexdigest()
        == runner["imageDataSha256"]
    )


def test_beta_benchmark_candidate_requires_all_eight_cases() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    incomplete = {"python": {}, "typescript": {}}

    with pytest.raises(RuntimeError, match="missing python cases"):
        module._candidate_baseline(incomplete, {})


def _complete_benchmark_results(module: object) -> dict[str, dict[str, Any]]:
    cases = getattr(module, "CASES")
    return {
        runtime: {
            case: {
                "medianMs": 3.0,
                "maxPeakMiB": 95.0,
                "sampleResults": [
                    {"durationMs": float(index), "peakMiB": 90.0 + index}
                    for index in range(1, 6)
                ],
            }
            for case in cases
        }
        for runtime in ("python", "typescript")
    }


def _closed_benchmark_runner() -> dict[str, str]:
    return {
        "environment": "github-hosted",
        "os": "Darwin",
        "arch": "arm64",
        "platformVersion": "15.7.7",
        "imageOS": "macos15",
        "imageLabel": "macos-15-arm64",
        "imageVersion": "20260715.0234.1",
        "imageDataSha256": "a" * 64,
    }


def _complete_benchmark_baseline(module: object) -> dict[str, Any]:
    cases = getattr(module, "CASES")
    return {
        "schemaVersion": 1,
        "status": "calibrated",
        "calibrationCommit": "a" * 40,
        "runner": _closed_benchmark_runner(),
        "versions": {"python": "3", "node": "24", "bun": "1"},
        "dependencyLockHash": "lock",
        "sourceHash": "b" * 64,
        "medians": {
            runtime: {case: 10.0 for case in cases}
            for runtime in ("python", "typescript")
        },
        "rawSamples": {
            runtime: {case: [10.0] * 5 for case in cases}
            for runtime in ("python", "typescript")
        },
        "maxPeakMiB": {
            runtime: {case: 100.0 for case in cases}
            for runtime in ("python", "typescript")
        },
        "rawPeakMiB": {
            runtime: {case: [100.0] * 5 for case in cases}
            for runtime in ("python", "typescript")
        },
    }


@pytest.mark.parametrize("mode", ["quick"])
def test_beta_benchmark_non_full_modes_do_not_read_baseline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mode: str,
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    output = tmp_path / f"{mode}.json"
    candidate = tmp_path / "candidate.json" if mode == "calibrate" else None
    monkeypatch.setattr(module, "BASELINE_PATH", tmp_path / "missing-baseline.json")
    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: module.argparse.Namespace(
            mode=mode, output=output, candidate_baseline=candidate
        ),
    )
    current = {"runner": _closed_benchmark_runner()}
    monkeypatch.setattr(module, "_checked_out_commit", lambda: "a" * 40)
    monkeypatch.setenv("KAJI_RELEASE_COMMIT", "a" * 40)
    monkeypatch.setattr(module, "fingerprint", lambda **_kwargs: current)
    monkeypatch.setattr(
        module,
        "_run_case",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("benchmark sentinel")
        ),
    )
    monkeypatch.setenv("KAJI_BENCHMARK_CALIBRATION", "1")

    assert module.main() == 1
    report = json.loads(output.read_text())
    assert report["failures"] == ["benchmark sentinel"]
    assert report["commit"] == "a" * 40
    assert report["fingerprint"] == current
    assert report["protected"] is False
    assert "FAIL: benchmark sentinel" in capsys.readouterr().err


def test_beta_benchmark_full_mode_reports_malformed_baseline_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    baseline = tmp_path / "baseline.json"
    baseline.write_text("{")
    output = tmp_path / "full.json"
    monkeypatch.setattr(module, "BASELINE_PATH", baseline)
    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: module.argparse.Namespace(
            mode="full", output=output, candidate_baseline=None
        ),
    )
    monkeypatch.setattr(module, "fingerprint", lambda **_kwargs: {})

    assert module.main() == 1
    report = json.loads(output.read_text())
    assert report["passed"] is False
    assert any("baseline" in failure for failure in report["failures"])


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (None, "KAJI_RELEASE_COMMIT is required"),
        ("A" * 40, "exactly 40 lowercase hex characters"),
        ("b" * 40, "does not match checked-out commit"),
    ],
)
def test_protected_performance_provenance_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    configured: str | None,
    expected: str,
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    monkeypatch.delenv("KAJI_RELEASE_COMMIT", raising=False)
    if configured is not None:
        monkeypatch.setenv("KAJI_RELEASE_COMMIT", configured)
    monkeypatch.setattr(module, "_checked_out_commit", lambda: "a" * 40)
    monkeypatch.setattr(module, "fingerprint", lambda **_kwargs: {"runner": "exact"})

    with pytest.raises(RuntimeError, match=expected):
        module.performance_provenance(protected=True)


def test_performance_provenance_binds_commit_and_local_mode_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    commit = "a" * 40
    fingerprint = {
        "runner": _closed_benchmark_runner(),
        "versions": {"python": "3.11.9", "node": "v22.14.0", "bun": "1.3.11"},
        "dependencyLockHash": "b" * 64,
    }
    monkeypatch.setattr(module, "_checked_out_commit", lambda: commit)
    monkeypatch.setattr(module, "fingerprint", lambda **_kwargs: fingerprint)
    monkeypatch.setenv("KAJI_RELEASE_COMMIT", commit)

    assert module.performance_provenance(protected=True) == {
        "commit": commit,
        "fingerprint": fingerprint,
        "protected": True,
    }

    monkeypatch.delenv("KAJI_RELEASE_COMMIT")
    assert module.performance_provenance(protected=False) == {
        "commit": commit,
        "fingerprint": fingerprint,
        "protected": False,
    }


@pytest.mark.parametrize("resolved", [None, "/unexpected/source/kaji/__init__.py"])
def test_benchmark_child_must_report_matching_installed_package(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    resolved: str | None,
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    expected = tmp_path / "python" / "site-packages" / "kaji" / "__init__.py"
    expected.parent.mkdir(parents=True)
    expected.write_text("")
    result: dict[str, object] = {
        "schemaVersion": 1,
        "runtime": "python",
        "case": "replay10k",
        "samples": 1,
        "warmups": 1,
        "seed": 13,
        "sampleResults": [{"durationMs": 1.0, "peakMiB": 2.0}],
        "medianMs": 1.0,
        "maxPeakMiB": 2.0,
    }
    if resolved is not None:
        result["resolvedPackage"] = resolved
    monkeypatch.setattr(
        module,
        "run_checked",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(result).encode("utf-8"),
            stderr=b"",
        ),
    )
    installed = SimpleNamespace(
        python_executable=Path(sys.executable),
        root=tmp_path,
        environment={},
        resolved_python_package=expected.resolve(),
    )

    with pytest.raises(RuntimeError, match="missing fields|different package"):
        module._run_case("python", "replay10k", 1, 1, installed)


def test_benchmark_child_failure_identifies_runtime_and_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")

    def fail(*_args: object, **_kwargs: object) -> None:
        raise module.CommandError("redacted child failure")

    monkeypatch.setattr(module, "run_checked", fail)

    with pytest.raises(RuntimeError) as error:
        module._run_case("python", "replay10k", 1, 1)

    assert str(error.value) == "python replay10k failed"
    assert "redacted child failure" not in str(error.value)


@pytest.mark.parametrize(
    ("failure_index", "variant", "status"),
    [(0, "replay", 1), (1, "indexed", -9)],
)
def test_python_context_benchmark_emits_only_structured_inner_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure_index: int,
    variant: str,
    status: int,
) -> None:
    module = _load_sdk_benchmark("runtime_benchmark.py")
    secret = "sk-hosted-child-secret"
    calls = 0

    def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        index = calls
        calls += 1
        if index == failure_index:
            return subprocess.CompletedProcess(
                args=[],
                returncode=status,
                stdout=secret,
                stderr=secret,
            )
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"peakBytes": 1}),
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: SimpleNamespace(
            case="context10kIterations5",
            samples=1,
            warmups=0,
            seed=13,
            json=True,
            _sample=False,
            _context_variant=None,
        ),
    )

    assert module.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"KAJI_BENCHMARK_SAMPLE_FAILURE variant={variant} status={status}\n"
    )
    assert secret not in captured.out + captured.err


def test_python_benchmark_keeps_non_context_sample_failure_generic(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_sdk_benchmark("runtime_benchmark.py")
    secret = "sk-hosted-child-secret"
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=7,
            stdout=secret,
            stderr=secret,
        ),
    )
    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: SimpleNamespace(
            case="replay10k",
            samples=1,
            warmups=0,
            seed=13,
            json=True,
            _sample=False,
            _context_variant=None,
        ),
    )

    assert module.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert secret not in captured.out + captured.err


def test_benchmark_gate_reports_only_strict_python_context_failure_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    secret = b"sk-hosted-child-secret"
    calls: list[dict[str, object]] = []

    def run(*_args: object, **kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            returncode=1,
            stdout=(
                secret + b"\nKAJI_BENCHMARK_SAMPLE_FAILURE variant=replay status=7\n"
            ),
            stderr=(
                secret
                + b"\nKAJI_BENCHMARK_SAMPLE_FAILURE variant=indexed status=-9\n"
                + secret
            ),
        )

    monkeypatch.setattr(module, "run_checked", run)

    with pytest.raises(RuntimeError) as error:
        module._run_case("python", "context10kIterations5", 1, 1)

    assert str(error.value) == (
        "python context10kIterations5 failed: variant=indexed status=-9"
    )
    assert secret.decode() not in str(error.value)
    assert calls == [
        {
            "cwd": module.ROOT,
            "budget": module.BENCHMARK_COMMAND_BUDGET,
            "capture": True,
            "env": None,
            "check": False,
        }
    ]


@pytest.mark.parametrize(
    ("runtime", "case", "stderr"),
    [
        (
            "python",
            "context10kIterations5",
            b"KAJI_BENCHMARK_SAMPLE_FAILURE variant=unknown status=-9",
        ),
        (
            "python",
            "context10kIterations5",
            b"KAJI_BENCHMARK_SAMPLE_FAILURE variant=replay status=-9\n"
            b"KAJI_BENCHMARK_SAMPLE_FAILURE variant=indexed status=-9",
        ),
        (
            "python",
            "context10kIterations5",
            b"KAJI_BENCHMARK_SAMPLE_FAILURE variant=replay status=0",
        ),
        (
            "python",
            "context10kIterations5",
            b"KAJI_BENCHMARK_SAMPLE_FAILURE variant=replay status=-2147483649",
        ),
        (
            "python",
            "replay10k",
            b"KAJI_BENCHMARK_SAMPLE_FAILURE variant=replay status=-9",
        ),
        (
            "typescript",
            "context10kIterations5",
            b"KAJI_BENCHMARK_SAMPLE_FAILURE variant=replay status=-9",
        ),
    ],
)
def test_benchmark_gate_keeps_unknown_child_failures_generic(
    monkeypatch: pytest.MonkeyPatch,
    runtime: str,
    case: str,
    stderr: bytes,
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    secret = b"sk-hosted-child-secret"
    monkeypatch.setattr(
        module,
        "run_checked",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stdout=(
                secret + b"\nKAJI_BENCHMARK_SAMPLE_FAILURE variant=indexed status=-9"
            ),
            stderr=stderr + b"\n" + secret,
        ),
    )

    with pytest.raises(RuntimeError) as error:
        module._run_case(runtime, case, 1, 1)

    assert str(error.value) == f"{runtime} {case} failed"
    assert secret.decode() not in str(error.value)


def _complete_soak_receipt(
    runtime: str = "python",
    *,
    prior_rss_mib: float = 100.0,
    late_rss_mib: float = 100.0,
) -> dict[str, Any]:
    samples = [
        {
            "minute": float(minute),
            "heapMiB": 100.0,
            "heapUsedMiB": 100.0,
            "rssMiB": prior_rss_mib if minute <= 25 else late_rss_mib,
        }
        for minute in range(21, 31)
    ]
    return {
        "schemaVersion": 2,
        "runtime": runtime,
        "resolvedPackage": f"/installed/{runtime}",
        "requestedMinutes": 30.0,
        "elapsedSeconds": 1_800.0,
        "attemptedTurns": 10_000,
        "completedTurns": 9_998,
        "failedTurns": 2,
        "terminalOutcomes": {"completed": 9_998, "failed": 1, "cancelled": 1},
        "noncooperativeTimeouts": 1,
        "cooperativeTimeouts": 1,
        "memorySamples": samples,
        "internal": {
            "coordinatorEntries": 0,
            "coordinatorWaiters": 0,
            "stuckToolCalls": 0,
            "maxToolActive": 4,
            "maxSubscriberQueueDepth": 1_024,
            "subscriberOverflows": 1,
            "metricSubscriberOverflows": 1,
            "subscriberResumes": 1,
            "subscriberCount": 0,
            "projectionCacheSize": 0,
            "projectionCacheLimit": 1,
            "ledgerSize": 0,
            "ledgerLimit": 10_000,
            "ledgerPeakSize": 0,
            "ledgerCounts": {"running": 0},
            "maxContextMessages": 1,
            "maxContextCharacters": 100,
            "scenarios": {
                "toolCallsRequested": 1,
                "approvals": 1,
                "cancellations": 1,
                "cooperativeTimeouts": 1,
                "nonCooperativeTimeouts": 1,
                "sessionClosures": 1,
            },
        },
        "provider": {
            "active": 0,
            "approvalBridgeRequests": 1,
            "multiToolBatches": 1,
            "chargeRequests": 1,
            "maxMessages": 1,
            "maxCharacters": 100,
        },
    }


@pytest.mark.parametrize("runtime", ["python", "typescript"])
def test_soak_gate_accepts_trustworthy_memory_windows(runtime: str) -> None:
    module = _load_root_script("beta_soak_gate.py")

    assert module._failures(_complete_soak_receipt(runtime), runtime, 30.0) == []


@pytest.mark.parametrize("runtime", ["python", "typescript"])
def test_soak_gate_loads_measurement_only_child_receipts(
    runtime: str, tmp_path: Path
) -> None:
    module = _load_root_script("beta_soak_gate.py")
    path = tmp_path / f"{runtime}.json"
    path.write_text(json.dumps(_complete_soak_receipt(runtime)))

    value, failures = module._load(path, runtime)

    assert value is not None
    assert failures == []


def test_soak_gate_rejects_late_window_rss_leak() -> None:
    module = _load_root_script("beta_soak_gate.py")
    receipt = _complete_soak_receipt(
        "typescript", prior_rss_mib=10.0, late_rss_mib=1_000.0
    )

    failures = module._failures(receipt, "typescript", 30.0)

    assert any("RSS growth" in failure for failure in failures)


@pytest.mark.parametrize("case", ["sparse", "duplicate", "nonfinite"])
def test_soak_gate_rejects_untrustworthy_memory_windows(case: str) -> None:
    module = _load_root_script("beta_soak_gate.py")
    receipt = _complete_soak_receipt("typescript")
    samples = receipt["memorySamples"]
    assert isinstance(samples, list)
    if case == "sparse":
        samples.pop(3)
    elif case == "duplicate":
        samples.append(dict(samples[0]))
    else:
        samples[0]["rssMiB"] = float("inf")

    failures = module._failures(receipt, "typescript", 30.0)

    assert any("memory samples" in failure for failure in failures)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("completedTurns",), 9_997, "turn accounting"),
        (("terminalOutcomes", "completed"), 9_997, "terminal outcomes"),
        (("internal", "maxToolActive"), 5, "tool concurrency"),
        (("provider", "active"), 1, "provider requests"),
    ],
)
def test_soak_gate_rejects_common_runtime_invariant_drift(
    path: tuple[str, ...], value: object, message: str
) -> None:
    module = _load_root_script("beta_soak_gate.py")
    receipt = _complete_soak_receipt("typescript")
    target = receipt
    for key in path[:-1]:
        nested = target[key]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = value

    failures = module._failures(receipt, "typescript", 30.0)

    assert any(message in failure for failure in failures)


def test_soak_gate_requires_cancelled_turns() -> None:
    module = _load_root_script("beta_soak_gate.py")
    receipt = _complete_soak_receipt("typescript")
    receipt["terminalOutcomes"] = {"completed": 9_998, "failed": 2, "cancelled": 0}

    failures = module._failures(receipt, "typescript", 30.0)

    assert any("cancellation" in failure for failure in failures)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("internal", "subscriberCount"), 1, "subscriber"),
        (("internal", "metricSubscriberOverflows"), 0, "overflow diagnostics"),
        (("internal", "subscriberResumes"), 0, "subscriber resume"),
        (("provider", "multiToolBatches"), 0, "multi-tool"),
        (("provider", "chargeRequests"), 0, "approval tool"),
        (("cooperativeTimeouts",), 0, "cooperative timeout"),
        (("noncooperativeTimeouts",), 0, "non-cooperative timeout"),
    ],
)
def test_soak_gate_rejects_python_scenario_gaps(
    path: tuple[str, ...], value: int, message: str
) -> None:
    module = _load_root_script("beta_soak_gate.py")
    receipt = _complete_soak_receipt("python")
    target = receipt
    for key in path[:-1]:
        nested = target[key]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = value

    failures = module._failures(receipt, "python", 30.0)

    assert any(message in failure for failure in failures)


@pytest.mark.parametrize(
    "scenario",
    [
        "toolCallsRequested",
        "approvals",
        "cancellations",
        "cooperativeTimeouts",
        "nonCooperativeTimeouts",
        "sessionClosures",
    ],
)
def test_soak_gate_rejects_typescript_scenario_gaps(scenario: str) -> None:
    module = _load_root_script("beta_soak_gate.py")
    receipt = _complete_soak_receipt("typescript")
    scenarios = receipt["internal"]["scenarios"]
    assert isinstance(scenarios, dict)
    scenarios[scenario] = 0

    failures = module._failures(receipt, "typescript", 30.0)

    assert any(scenario in failure for failure in failures)


def test_python_soak_sampling_records_minute_30_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_sdk_benchmark("runtime_soak.py")
    monkeypatch.setattr(module, "_sample_memory", lambda minute: {"minute": minute})
    samples: list[dict[str, float]] = []

    module._append_memory_sample(samples, 21.0)
    module._append_memory_sample(samples, 30.0)
    module._append_memory_sample(samples, 30.5)

    assert [sample["minute"] for sample in samples] == [21.0, 30.0]


def test_soak_gate_is_the_only_soak_policy_authority() -> None:
    budgets = json.loads(
        (REPO_ROOT / "kaji" / "benchmarks" / "beta-budgets.json").read_text()
    )["soak"]
    assert budgets["maxLateWindowRssGrowthPercent"] > 0
    assert budgets["maxLateWindowRssGrowthMiB"] > 0

    for relative in (
        Path("kaji/benchmarks/python/runtime_soak.py"),
        Path("kaji/ts/benchmarks/runtime-soak.ts"),
    ):
        source = (REPO_ROOT / relative).read_text()
        assert "MAX_LATE_WINDOW_" not in source
        assert "minimumTurns" not in source
        assert '"passed"' not in source
        assert "const passed" not in source
        assert "const checks" not in source

    typescript = (
        REPO_ROOT / "kaji" / "ts" / "benchmarks" / "runtime-soak.ts"
    ).read_text()
    assert "Math.min(failed, scenarios.cancellations)" not in typescript
    assert "noncooperativeTimeouts:" not in typescript
    assert "boundedConcurrency" not in typescript


def test_soak_identity_rejects_missing_fields_and_child_path_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_root_script("beta_soak_gate.py")
    commit = "a" * 40
    identity_path = tmp_path / "identity.json"
    identity = {
        "commit": commit,
        "releaseManifestSha256": "b" * 64,
        "artifacts": {
            "python": {
                "file": "kaji_sdk-0.2.0b1-py3-none-any.whl",
                "sha256": "c" * 64,
            },
            "typescript": {
                "file": "kaji-sdk-0.2.0-beta.2.tgz",
                "sha256": "d" * 64,
            },
        },
        "resolvedPackages": {
            "python": "/isolated/python/kaji/__init__.py",
            "typescript": "/isolated/typescript/kaji-sdk",
        },
        "typescriptConsumerLock": {
            "templateSha256": "e" * 64,
            "renderedSha256": "f" * 64,
        },
    }
    identity_path.write_text(json.dumps(identity))
    loaded, failures = module._load_identity(identity_path)
    assert failures == []
    assert loaded["releaseManifestSha256"] == "b" * 64

    del identity["artifacts"]["python"]["sha256"]
    identity_path.write_text(json.dumps(identity))
    assert "invalid python artifact" in " ".join(
        module._load_identity(identity_path)[1]
    )
    identity["artifacts"]["python"]["sha256"] = "c" * 64
    identity_path.write_text(json.dumps(identity))

    output = tmp_path / "soak.json"
    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: module.argparse.Namespace(
            minutes=30.0,
            python=tmp_path / "python.json",
            typescript=tmp_path / "typescript.json",
            output=output,
            protected=True,
            runtime_identity=identity_path,
            runner_image_data=tmp_path / "parent-imagedata.json",
        ),
    )
    monkeypatch.setattr(
        module,
        "performance_provenance",
        lambda **_kwargs: {"commit": commit, "fingerprint": {}, "protected": True},
    )
    monkeypatch.setattr(
        module,
        "_load",
        lambda _path, runtime: (
            {"runtime": runtime, "resolvedPackage": f"/source/{runtime}"},
            [],
        ),
    )
    monkeypatch.setattr(module, "_failures", lambda *_args: [])

    assert module.main() == 1
    report = json.loads(output.read_text())
    assert report["passed"] is False
    assert (
        sum("different installed package" in failure for failure in report["failures"])
        == 2
    )


def test_performance_source_hash_covers_runtime_benchmarks_and_gate_inputs() -> None:
    module = _load_root_script("beta_benchmark_gate.py")

    assert module.SOURCE_TREE_ROOTS == (
        Path("kaji/src/kaji"),
        Path("kaji/ts/src"),
    )
    assert {
        Path("kaji/benchmarks/python/runtime_benchmark.py"),
        Path("kaji/ts/benchmarks/runtime-benchmark.ts"),
        Path("kaji/benchmarks/python/runtime_soak.py"),
        Path("kaji/ts/benchmarks/runtime-soak.ts"),
        Path("kaji/scripts/beta_benchmark_gate.py"),
        Path("kaji/scripts/run_beta_benchmarks.py"),
        Path("kaji/scripts/beta_soak_gate.py"),
        Path("kaji/scripts/run_beta_soak.py"),
        Path("kaji/scripts/process_runner.py"),
        Path("kaji/scripts/benchmark_platform.py"),
        Path("kaji/scripts/installed_release_runtime.py"),
        Path("kaji/scripts/verify_release_artifacts.py"),
        Path("kaji/benchmarks/beta-budgets.json"),
        Path("kaji/pyproject.toml"),
        Path("kaji/ts/package.json"),
        Path("kaji/ts/tsconfig.json"),
        Path("kaji/scripts/installed-typescript-runtime/package.core.json"),
        Path("kaji/scripts/installed-typescript-runtime/package-lock.core.json"),
        Path("kaji/scripts/installed-typescript-runtime/package.json"),
        Path("kaji/scripts/installed-typescript-runtime/package-lock.json"),
    } <= set(module.SOURCE_INPUTS)
    assert Path("kaji/benchmarks/beta-baseline.json") not in module.SOURCE_INPUTS


def test_typescript_source_benchmark_maps_every_public_subpath() -> None:
    config = (REPO_ROOT / "kaji" / "ts" / "tsconfig.json").read_text()

    for package, source in {
        "kaji-sdk": "./src/index.ts",
        "kaji-sdk/openai": "./src/providers/openai.ts",
        "kaji-sdk/anthropic": "./src/providers/anthropic.ts",
        "kaji-sdk/testing": "./src/testing.ts",
    }.items():
        assert f'"{package}": ["{source}"]' in config


def test_release_runbook_requires_checkout_bound_single_rehearsal_command() -> None:
    runbook = (REPO_ROOT / "docs" / "kaji" / "releasing.md").read_text()

    assert "real Git checkout with its `.git` metadata present" in runbook
    assert "Source archives are unsupported" in runbook
    assert (
        runbook.count(
            "uv run --project kaji python kaji/scripts/beta_release_check.py --release"
        )
        == 1
    )
    assert (
        "uv run --project kaji python kaji/scripts/verify_package_metadata.py"
        not in runbook
    )


@pytest.mark.parametrize(
    "mutated",
    [
        Path("python-runtime/runtime.py"),
        Path("typescript-runtime/runtime.ts"),
        Path("python-benchmark.py"),
        Path("typescript-benchmark.ts"),
        Path("beta-budgets.json"),
    ],
)
def test_performance_source_hash_rejects_mutated_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutated: Path
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    roots = (Path("python-runtime"), Path("typescript-runtime"))
    inputs = (
        Path("python-benchmark.py"),
        Path("typescript-benchmark.ts"),
        Path("beta-budgets.json"),
    )
    monkeypatch.setattr(module, "SOURCE_TREE_ROOTS", roots)
    monkeypatch.setattr(module, "SOURCE_INPUTS", inputs)
    for relative in (*inputs, *(root / "runtime.py" for root in roots)):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative.as_posix())
    typescript_runtime = tmp_path / "typescript-runtime/runtime.py"
    typescript_runtime.rename(tmp_path / "typescript-runtime/runtime.ts")

    original = module._source_hash(tmp_path)
    path = tmp_path / mutated
    path.write_text(path.read_text() + "\nmutated")

    assert module._source_hash(tmp_path) != original


def test_beta_benchmark_baseline_rejects_stale_source_hash() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    baseline = _complete_benchmark_baseline(module)
    current = module._baseline_fingerprint(baseline)
    current["sourceHash"] = "c" * 64

    with pytest.raises(RuntimeError, match="source hash"):
        module._validate_baseline(baseline, current)


def test_beta_benchmark_baseline_rejects_legacy_runner_shape() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    baseline = _complete_benchmark_baseline(module)
    baseline["runner"] = {"imageDigest": "sha256:" + "a" * 64}

    with pytest.raises(RuntimeError, match="runner fingerprint"):
        module._baseline_fingerprint(baseline)


def test_tracked_calibrated_baseline_retains_provenance_and_validates() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    baseline = json.loads(module.BASELINE_PATH.read_text())

    assert baseline["status"] == "calibrated"
    assert baseline["commit"] == baseline["calibrationCommit"]
    assert module.COMMIT_PATTERN.fullmatch(baseline["calibrationCommit"])
    assert baseline["sourceHash"] == module._source_hash()
    assert baseline["dependencyLockHash"] == module._lock_hash()
    assert module.HASH_PATTERN.fullmatch(baseline["releaseManifestSha256"])
    assert set(baseline["artifacts"]) == {"python", "typescript"}
    assert all(
        module.HASH_PATTERN.fullmatch(artifact["sha256"])
        for artifact in baseline["artifacts"].values()
    )
    module._validate_baseline(baseline, module._baseline_fingerprint(baseline))


@pytest.mark.parametrize("commit", [None, "A" * 40, "a" * 39])
def test_beta_benchmark_baseline_requires_valid_calibration_commit(
    commit: str | None,
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    baseline = _complete_benchmark_baseline(module)
    baseline["calibrationCommit"] = commit
    current = module._baseline_fingerprint(baseline)

    with pytest.raises(RuntimeError, match="calibrationCommit"):
        module._validate_baseline(baseline, current)


def test_soak_report_reuses_complete_performance_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_root_script("beta_soak_gate.py")
    output = tmp_path / "soak.json"
    runner_image_data = tmp_path / "parent-imagedata.json"
    provenance = {
        "commit": "a" * 40,
        "fingerprint": {
            "runner": _closed_benchmark_runner(),
            "versions": {
                "python": "3.11.9",
                "node": "v22.14.0",
                "bun": "1.3.11",
            },
            "dependencyLockHash": "b" * 64,
        },
        "protected": True,
    }
    identity = {
        "commit": provenance["commit"],
        "releaseManifestSha256": "c" * 64,
        "artifacts": {
            "python": {
                "file": "kaji_sdk-0.2.0b1-py3-none-any.whl",
                "sha256": "d" * 64,
            },
            "typescript": {
                "file": "kaji-sdk-0.2.0-beta.2.tgz",
                "sha256": "e" * 64,
            },
        },
        "resolvedPackages": {
            "python": "/installed/python",
            "typescript": "/installed/typescript",
        },
        "typescriptConsumerLock": {
            "templateSha256": "f" * 64,
            "renderedSha256": "a" * 64,
        },
    }
    identity_path = tmp_path / "identity.json"
    identity_path.write_text(json.dumps(identity))
    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: module.argparse.Namespace(
            minutes=30.0,
            python=tmp_path / "python.json",
            typescript=tmp_path / "typescript.json",
            output=output,
            protected=True,
            runtime_identity=identity_path,
            runner_image_data=runner_image_data,
        ),
    )
    provenance_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        module,
        "performance_provenance",
        lambda **kwargs: provenance_calls.append(kwargs) or provenance,
    )
    monkeypatch.setattr(
        module,
        "_load",
        lambda _path, runtime: (
            {
                "runtime": runtime,
                "resolvedPackage": identity["resolvedPackages"][runtime],
            },
            [],
        ),
    )
    monkeypatch.setattr(module, "_failures", lambda *_args: [])

    assert module.main() == 0
    report = json.loads(output.read_text())
    assert report["commit"] == provenance["commit"]
    assert report["fingerprint"] == provenance["fingerprint"]
    assert report["protected"] is True
    assert report["releaseManifestSha256"] == "c" * 64
    assert report["resolvedPackages"] == identity["resolvedPackages"]
    assert report["typescriptConsumerLock"] == identity["typescriptConsumerLock"]
    assert provenance_calls == [
        {"protected": True, "image_data_path": runner_image_data}
    ]


def test_protected_soak_gate_requires_explicit_runner_image_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_root_script("beta_soak_gate.py")
    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: module.argparse.Namespace(
            minutes=30.0,
            python=tmp_path / "python.json",
            typescript=tmp_path / "typescript.json",
            output=tmp_path / "soak.json",
            protected=True,
            runtime_identity=tmp_path / "identity.json",
            runner_image_data=None,
        ),
    )
    monkeypatch.setattr(
        module,
        "performance_provenance",
        lambda **_kwargs: pytest.fail("provenance ran without explicit image data"),
    )

    with pytest.raises(RuntimeError, match="--runner-image-data"):
        module.main()


def test_beta_benchmark_full_mode_reports_malformed_nested_baseline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    baseline_value = _complete_benchmark_baseline(module)
    current = module._baseline_fingerprint(baseline_value)
    baseline_value["rawSamples"]["python"]["replay10k"] = 1
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(baseline_value))
    output = tmp_path / "full.json"
    monkeypatch.setattr(module, "BASELINE_PATH", baseline)
    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: module.argparse.Namespace(
            mode="full", output=output, candidate_baseline=None
        ),
    )
    monkeypatch.setattr(module, "fingerprint", lambda **_kwargs: current)

    assert module.main() == 1
    report = json.loads(output.read_text())
    assert report["passed"] is False
    assert any(
        "rawSamples.python.replay10k" in failure for failure in report["failures"]
    )


@pytest.mark.parametrize("rss_field", ["maxPeakMiB", "rawPeakMiB"])
def test_beta_benchmark_baseline_requires_rss_case_coverage(rss_field: str) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    baseline = _complete_benchmark_baseline(module)
    baseline[rss_field]["python"].pop("toolArgDeltas10k")
    current = module._baseline_fingerprint(baseline)

    with pytest.raises(RuntimeError, match="RSS cases"):
        module._validate_baseline(baseline, current)


def test_beta_benchmark_baseline_requires_five_rss_samples() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    baseline = _complete_benchmark_baseline(module)
    baseline["rawPeakMiB"]["python"]["streamDeltas10k"] = [100.0]
    current = module._baseline_fingerprint(baseline)

    with pytest.raises(RuntimeError, match="RSS samples must contain five values"):
        module._validate_baseline(baseline, current)


@pytest.mark.parametrize(
    ("field", "raw"),
    [
        ("medians", False),
        ("rawSamples", True),
        ("maxPeakMiB", False),
        ("rawPeakMiB", True),
    ],
)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0])
def test_beta_benchmark_baseline_rejects_non_finite_or_negative_evidence(
    field: str, raw: bool, value: float
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    baseline = _complete_benchmark_baseline(module)
    case_value = baseline[field]["python"]["streamDeltas10k"]
    if raw:
        case_value[0] = value
    else:
        baseline[field]["python"]["streamDeltas10k"] = value
    current = module._baseline_fingerprint(baseline)

    with pytest.raises(RuntimeError, match="finite non-negative"):
        module._validate_baseline(baseline, current)


def test_beta_benchmark_baseline_rejects_mismatched_rss_aggregate() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    baseline = _complete_benchmark_baseline(module)
    baseline["maxPeakMiB"]["python"]["streamDeltas10k"] = 99.0
    current = module._baseline_fingerprint(baseline)

    with pytest.raises(RuntimeError, match="RSS aggregate"):
        module._validate_baseline(baseline, current)


def test_beta_benchmark_baseline_rejects_mismatched_duration_median() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    baseline = _complete_benchmark_baseline(module)
    baseline["medians"]["python"]["streamDeltas10k"] = 9.0
    current = module._baseline_fingerprint(baseline)

    with pytest.raises(RuntimeError, match="duration median"):
        module._validate_baseline(baseline, current)


def test_beta_benchmark_semantic_validation_rejects_mismatched_aggregate() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    budgets = json.loads(module.BUDGETS_PATH.read_text())
    result = _complete_benchmark_results(module)["python"]["streamDeltas10k"]
    result["medianMs"] = 2.0

    with pytest.raises(RuntimeError, match="does not match sample median"):
        module._case_failures(
            "python", "streamDeltas10k", result, budgets, include_timing=False
        )


def test_beta_benchmark_candidate_rejects_mismatched_aggregate() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    results = _complete_benchmark_results(module)
    results["python"]["streamDeltas10k"]["maxPeakMiB"] = 94.0

    with pytest.raises(RuntimeError, match="does not match sample maximum"):
        module._candidate_baseline(results, {})


def test_beta_benchmark_regression_rejects_mismatched_aggregate() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    baseline = _complete_benchmark_baseline(module)
    results = _complete_benchmark_results(module)
    results["python"]["streamDeltas10k"]["medianMs"] = 2.0

    with pytest.raises(RuntimeError, match="does not match sample median"):
        module._regression_failures(results, baseline, 20.0)


def test_beta_benchmark_full_regression_checks_duration_and_rss() -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    baseline = _complete_benchmark_baseline(module)
    results = _complete_benchmark_results(module)
    results["python"]["streamDeltas10k"]["sampleResults"][-1]["peakMiB"] = 121.0
    results["python"]["streamDeltas10k"]["maxPeakMiB"] = 121.0

    failures = module._regression_failures(results, baseline, 20.0)

    assert any(
        "streamDeltas10k" in failure and "peak RSS" in failure for failure in failures
    )


def test_beta_benchmark_candidate_records_five_rss_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    results = _complete_benchmark_results(module)
    current = {"sourceHash": "b" * 64}
    identity = {
        "commit": "a" * 40,
        "releaseManifestSha256": "c" * 64,
        "artifacts": {"python": {}, "typescript": {}},
        "resolvedPackages": {"python": "/tmp/python", "typescript": "/tmp/ts"},
        "typescriptConsumerLock": {
            "templateSha256": "d" * 64,
            "renderedSha256": "e" * 64,
        },
    }
    monkeypatch.setattr(module, "_commit", lambda: "a" * 40)

    candidate = module._candidate_baseline(results, current, identity)

    assert candidate["calibrationCommit"] == "a" * 40
    assert candidate["sourceHash"] == "b" * 64
    assert candidate["commit"] == "a" * 40
    assert candidate["releaseManifestSha256"] == "c" * 64
    assert candidate["resolvedPackages"] == identity["resolvedPackages"]
    assert candidate["typescriptConsumerLock"] == identity["typescriptConsumerLock"]
    assert candidate["maxPeakMiB"]["python"]["context10kIterations5"] == 95.0
    assert candidate["rawPeakMiB"]["typescript"]["toolArgDeltas10k"] == [
        91.0,
        92.0,
        93.0,
        94.0,
        95.0,
    ]


def test_root_package_pins_structural_and_benchmark_gates() -> None:
    package = ROOT_PACKAGE.read_text()
    for expected in [
        '"@ast-grep/cli": "0.44.1"',
        '"ast-grep:test": "sg test -t tools/ast-grep/rule-tests --skip-snapshot-tests"',
        '"ast-grep:scan": "sg scan --config sgconfig.yml kaji"',
        '"audit:ast-grep": "bun run ast-grep:test && bun run ast-grep:scan"',
        '"benchmark:kaji-beta": "uv run --project kaji python kaji/scripts/run_beta_benchmarks.py --quick"',
        '"benchmark:kaji-beta:full": "uv run --project kaji python kaji/scripts/run_beta_benchmarks.py --full"',
        '"soak:kaji-beta": "uv run --project kaji python kaji/scripts/run_beta_soak.py --minutes 30"',
    ]:
        assert expected in package


def test_root_bun_lock_is_present_and_not_ignored() -> None:
    assert ROOT_LOCK.is_file()
    assert '"@ast-grep/cli": "0.44.1"' in ROOT_LOCK.read_text()

    ignore_lines = ROOT_GITIGNORE.read_text().splitlines()
    assert "!bun.lock" in ignore_lines
    assert ignore_lines.index("!bun.lock") > ignore_lines.index("bun.lock")


def test_beta_structural_audit_rule_and_fixture_ids_match() -> None:
    def ids_by_path(directory: Path) -> dict[str, Path]:
        result: dict[str, Path] = {}
        for path in sorted(directory.glob("*.yml")):
            matches = re.findall(r"(?m)^id:\s*([a-z0-9-]+)\s*$", path.read_text())
            assert len(matches) == 1, f"{path} must declare exactly one rule id"
            rule_id = matches[0]
            assert rule_id not in result, f"duplicate ast-grep id: {rule_id}"
            result[rule_id] = path
        return result

    rules = ids_by_path(RULE_DIR)
    fixtures = ids_by_path(RULE_TEST_DIR)

    assert rules
    assert set(rules) == set(fixtures)
    for rule_id, fixture in fixtures.items():
        assert fixture.name == f"{rule_id}-test.yml"

    assert "tools/ast-grep/rules" in SGCONFIG.read_text()


def test_ast_grep_is_mandatory_in_ci() -> None:
    workflow = AST_GREP_WORKFLOW.read_text()
    assert "bun-version: 1.3.11" in workflow
    assert "install-args: --frozen-lockfile" in workflow
    assert "test result: ok." not in workflow
    assert "AST_GREP_OUTPUT" not in workflow
    assert "| tee" not in workflow
    assert "grep -q" not in workflow
    assert workflow.index("bun run ast-grep:test") < workflow.index(
        "bun run ast-grep:scan"
    )

    benchmark_workflow = (
        REPO_ROOT / ".github" / "workflows" / "kaji.benchmark.yml"
    ).read_text()
    assert benchmark_workflow.count("install-args: --frozen-lockfile") == 3


def test_release_docs_reference_beta_release_check() -> None:
    readmes = [
        (REPO_ROOT / "kaji" / "README.md").read_text(),
        (REPO_ROOT / "kaji" / "ts" / "README.md").read_text(),
    ]
    combined = "\n".join(
        [
            (REPO_ROOT / "kaji" / "RELEASE_MATRIX.md").read_text(),
            *readmes,
            (REPO_ROOT / "docs" / "MVP.md").read_text(),
        ]
    )

    assert "uv run --project kaji python kaji/scripts/beta_release_check.py" in combined
    assert "KAJI_RUN_KEYED_LIVE=1" in combined
    assert "SDK/service boundary" in combined
    assert "TypeScript optional provider imports" in combined
    for readme in readmes:
        assert "OPENAI_API_KEY=... ANTHROPIC_API_KEY=..." in readme
        assert "KAJI_RELEASE_ARTIFACTS_DIR=" in readme
        assert "KAJI_RELEASE_COMMIT=<40-character-commit>" in readme
        assert "OPENAI_API_KEY=... KAJI_RUN_KEYED_LIVE=1" not in readme


def test_release_matrix_names_pending_protected_release_gate_truthfully() -> None:
    matrix = (REPO_ROOT / "kaji" / "RELEASE_MATRIX.md").read_text()
    row = next(
        line
        for line in matrix.splitlines()
        if line.startswith("| Shared schemas and registry |")
    )

    assert "`gate / kaji` / `beta release gate`" in row
    assert row.endswith("| locally proven; protected PR run pending |")
    assert "passed" not in row.lower()


def test_beta_benchmark_calibration_requires_explicit_operator_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    output = tmp_path / "calibration.json"
    monkeypatch.delenv("KAJI_BENCHMARK_CALIBRATION", raising=False)
    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: module.argparse.Namespace(
            mode="calibrate",
            output=output,
            candidate_baseline=tmp_path / "candidate.json",
        ),
    )
    monkeypatch.setattr(module, "fingerprint", lambda **_kwargs: {})

    assert module.main() == 1
    assert (
        "calibration requires KAJI_BENCHMARK_CALIBRATION=1"
        in json.loads(output.read_text())["failures"]
    )


def test_beta_benchmark_calibration_requests_protected_runner_measurement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_root_script("beta_benchmark_gate.py")
    output = tmp_path / "calibration.json"
    calls: list[dict[str, object]] = []
    monkeypatch.setenv("KAJI_BENCHMARK_CALIBRATION", "1")
    monkeypatch.setattr(
        module,
        "_parse_args",
        lambda: module.argparse.Namespace(
            mode="calibrate",
            output=output,
            candidate_baseline=tmp_path / "candidate.json",
        ),
    )
    monkeypatch.setattr(
        module,
        "fingerprint",
        lambda **kwargs: calls.append(kwargs) or {"runner": _closed_benchmark_runner()},
    )

    assert module.main() == 1
    assert calls == [{"protected": False, "calibrating": True, "image_data_path": None}]
