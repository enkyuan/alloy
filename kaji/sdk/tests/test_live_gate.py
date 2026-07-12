from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


SDK_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SDK_ROOT.parents[1]
OPENAI_LOOP_CHECK = REPO_ROOT / "kaji" / "scripts" / "verify_openai_loop.py"


def _load_root_script(name: str) -> ModuleType:
    path = REPO_ROOT / "kaji" / "scripts" / name
    scripts = str(path.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location(f"test_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _env_without_openai_key(*, require: bool = False) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    env.pop("KAJI_LIVE_OPENAI_MODEL", None)
    if require:
        env["KAJI_REQUIRE_LIVE_KEYS"] = "1"
    else:
        env.pop("KAJI_REQUIRE_LIVE_KEYS", None)
    return env


def test_openai_loop_check_skips_cleanly_without_openai_key() -> None:
    proc = subprocess.run(
        [sys.executable, str(OPENAI_LOOP_CHECK)],
        cwd=REPO_ROOT,
        env=_env_without_openai_key(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0
    assert "SKIP: OPENAI_API_KEY not set" in proc.stdout
    assert "Running Python OpenAI live tool-loop" not in proc.stdout
    assert "Running TypeScript OpenAI live tool-loop" not in proc.stdout


def test_openai_loop_check_fails_without_key_when_required() -> None:
    proc = subprocess.run(
        [sys.executable, str(OPENAI_LOOP_CHECK)],
        cwd=REPO_ROOT,
        env=_env_without_openai_key(require=True),
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 2
    assert "FAIL: OPENAI_API_KEY required for live readiness" in proc.stderr
    assert "Running Python OpenAI live tool-loop" not in proc.stdout
    assert "Running TypeScript OpenAI live tool-loop" not in proc.stdout


def _configure_provider_proof(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[ModuleType, Path]:
    module = _load_root_script("live_provider_proof.py")
    evidence = tmp_path / "provider-evidence.json"
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test-key")
    monkeypatch.setenv("KAJI_RELEASE_COMMIT", "a" * 40)
    monkeypatch.setenv("KAJI_PROVIDER_STATUS_FILE", str(evidence))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    return module, evidence


def test_protected_provider_proof_requires_both_keys_and_retains_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module, evidence = _configure_provider_proof(monkeypatch, tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY")

    assert module.main() == 2

    retained = json.loads(evidence.read_text())
    assert retained["commit"] == "a" * 40
    assert retained["conclusion"] == "failed"
    assert retained["failureCode"] == "missing_required_key"
    assert {(row["sdk"], row["provider"]) for row in retained["proofs"]} == {
        ("python", "openai"),
        ("typescript", "openai"),
        ("python", "anthropic"),
        ("typescript", "anthropic"),
    }
    assert {row["status"] for row in retained["proofs"]} == {"not_run"}


def test_protected_provider_proof_runs_four_real_tool_loops_and_records_commit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module, evidence = _configure_provider_proof(monkeypatch, tmp_path)
    calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def pass_command(
        command: list[str], *, environment: dict[str, str], **_kwargs: object
    ) -> int:
        calls.append((tuple(command), environment))
        return 0

    monkeypatch.setattr(module, "run", pass_command)

    assert module.main() == 0

    retained = json.loads(evidence.read_text())
    assert retained["schemaVersion"] == 1
    assert retained["commit"] == "a" * 40
    assert retained["conclusion"] == "passed"
    assert [
        (row["sdk"], row["provider"], row["status"]) for row in retained["proofs"]
    ] == [
        ("python", "openai", "passed"),
        ("typescript", "openai", "passed"),
        ("python", "anthropic", "passed"),
        ("typescript", "anthropic", "passed"),
    ]
    assert all(
        row["proof"] == "real_normalized_tool_loop" for row in retained["proofs"]
    )
    assert len(calls) == 4
    commands = [command for command, _environment in calls]
    rendered = [" ".join(command) for command in commands]
    assert any("test_openai_tools.py" in command for command in rendered)
    assert any("openai-tools.test.ts" in command for command in rendered)
    assert any("test_anthropic_provider.py" in command for command in rendered)
    assert any("anthropic-live.test.ts" in command for command in rendered)
    assert all(
        command[:3] == (sys.executable, "-m", "pytest") for command in commands[::2]
    )
    assert all("uv" not in command for command in commands)
    for index, (_command, environment) in enumerate(calls):
        expected_key = "OPENAI_API_KEY" if index < 2 else "ANTHROPIC_API_KEY"
        other_key = "ANTHROPIC_API_KEY" if index < 2 else "OPENAI_API_KEY"
        assert environment[expected_key] == (
            "openai-test-key" if index < 2 else "anthropic-test-key"
        )
        assert other_key not in environment


def test_provider_child_environment_does_not_mutate_parent() -> None:
    module = _load_root_script("live_provider_proof.py")
    parent = {
        "OPENAI_API_KEY": "openai-test-key",
        "ANTHROPIC_API_KEY": "anthropic-test-key",
        "PATH": "/usr/bin",
    }

    openai = module._child_environment(parent, "openai")
    anthropic = module._child_environment(parent, "anthropic")

    assert openai == {"OPENAI_API_KEY": "openai-test-key", "PATH": "/usr/bin"}
    assert anthropic == {
        "ANTHROPIC_API_KEY": "anthropic-test-key",
        "PATH": "/usr/bin",
    }
    assert set(parent) == {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "PATH"}


def test_protected_provider_proof_uses_three_minute_per_command_budget() -> None:
    module = _load_root_script("live_provider_proof.py")

    assert module.KEYED_PROOF_BUDGET.timeout_seconds == 180


def test_protected_provider_proof_retains_partial_rows_on_command_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module, evidence = _configure_provider_proof(monkeypatch, tmp_path)
    statuses = iter((0, 17))
    monkeypatch.setattr(module, "run", lambda *_args, **_kwargs: next(statuses))

    assert module.main() == 17

    retained = json.loads(evidence.read_text())
    assert retained["conclusion"] == "failed"
    assert retained["failureCode"] == "proof_command_failed"
    assert [row["status"] for row in retained["proofs"]] == [
        "passed",
        "failed",
        "not_run",
        "not_run",
    ]


@pytest.mark.parametrize(
    "script",
    [
        "verify_openai_loop.py",
        "live_provider_proof.py",
        "run_beta_benchmarks.py",
    ],
)
def test_root_script_runners_normalize_signal_exit_status(
    script: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_root_script(script)

    def fail(*_args: object, **_kwargs: object) -> None:
        raise module.CommandExitError(-15)

    monkeypatch.setattr(module, "run_checked", fail)

    if script == "verify_openai_loop.py":
        status = module.run_command(["tool"], cwd=REPO_ROOT, environment={})
    elif script == "run_beta_benchmarks.py":
        status = module.run(["tool"])
    else:
        status = module.run(["tool"], cwd=REPO_ROOT, environment={})

    assert status == 143
