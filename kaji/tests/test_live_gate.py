from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


SDK_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SDK_ROOT.parent
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


def _provider_arguments(tmp_path: Path) -> list[str]:
    return [
        "--protected",
        "--artifacts-dir",
        str(tmp_path / "artifacts"),
        "--expected-commit",
        "a" * 40,
    ]


def _fake_installed_runtime(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> SimpleNamespace:
    root = tmp_path / "installed"
    typescript = root / "typescript"
    python_package = root / "python/lib/python3.14/site-packages/kaji/__init__.py"
    typescript_package = typescript / "node_modules/kaji-sdk"
    typescript.mkdir(parents=True)
    python_package.parent.mkdir(parents=True)
    typescript_package.mkdir(parents=True)
    python_package.write_text("", encoding="utf-8")
    wheel = tmp_path / "artifacts/kaji_sdk-0.2.0b1-py3-none-any.whl"
    tarball = tmp_path / "artifacts/kaji-sdk-0.2.0-beta.7.tgz"
    wheel.parent.mkdir(parents=True)
    wheel.write_bytes(b"wheel")
    tarball.write_bytes(b"tarball")
    release = SimpleNamespace(
        commit="a" * 40,
        manifest_sha256="b" * 64,
        python_wheel=wheel,
        npm_tarball=tarball,
        artifact_sha256={wheel.name: "c" * 64, tarball.name: "d" * 64},
    )
    runtime = SimpleNamespace(
        root=root,
        python_executable=root / "python/bin/python",
        typescript_workdir=typescript,
        resolved_python_package=python_package,
        resolved_typescript_package=typescript_package,
        release=release,
        environment={
            "PATH": "/tools:/usr/bin",
            "HOME": str(root / "home"),
            "TMPDIR": str(root / "tmp"),
            "LANG": "C.UTF-8",
            "XDG_CACHE_HOME": str(root / "cache"),
            "UV_CACHE_DIR": str(root / "cache/uv"),
            "npm_config_cache": str(root / "cache/npm"),
            "PYTHONNOUSERSITE": "1",
            "UNRELATED_RUNTIME_VALUE": "must-not-leak",
        },
    )
    runtime.identity = lambda: {
        "commit": release.commit,
        "releaseManifestSha256": release.manifest_sha256,
        "artifacts": {
            "python": {"file": wheel.name, "sha256": "c" * 64},
            "typescript": {"file": tarball.name, "sha256": "d" * 64},
        },
        "resolvedPackages": {
            "python": str(python_package),
            "typescript": str(typescript_package),
        },
    }

    @contextmanager
    def installed_release_runtime(
        artifacts_dir: Path, *, expected_commit: str, include_openai: bool = False
    ) -> Iterator[SimpleNamespace]:
        assert artifacts_dir == tmp_path / "artifacts"
        assert expected_commit == "a" * 40
        assert include_openai is True
        yield runtime

    monkeypatch.setattr(
        module, "installed_release_runtime", installed_release_runtime, raising=False
    )
    monkeypatch.setattr(
        module.shutil,
        "which",
        lambda command, **_kwargs: "/tools/bun" if command == "bun" else None,
        raising=False,
    )
    return runtime


def _runner_receipt(
    *, sdk: str, provider: str, model: str, resolved_package: str
) -> dict[str, object]:
    call_id = f"{sdk}-{provider}-call"
    return {
        "sdk": sdk,
        "provider": provider,
        "proof": "real_normalized_tool_loop",
        "status": "passed",
        "model": model,
        "resolvedPackage": resolved_package,
        "requestedToolCalls": 1,
        "completedToolCalls": 1,
        "requestedToolCallIds": [call_id],
        "completedToolCallIds": [call_id],
        "echoResultMatched": True,
        "finalTextPresent": True,
        "forbiddenTerminalEvents": [],
    }


def test_protected_provider_proof_requires_openai_key_and_retains_failure(
    tmp_path: Path,
) -> None:
    module = _load_root_script("live_provider_proof.py")
    evidence = tmp_path / "provider-evidence.json"
    environment = {
        "ANTHROPIC_API_KEY": "wip-provider-key",
        "KAJI_RELEASE_COMMIT": "a" * 40,
        "KAJI_PROVIDER_STATUS_FILE": str(evidence),
    }

    assert module.main(_provider_arguments(tmp_path), environment=environment) == 2

    retained = json.loads(evidence.read_text())
    assert retained["commit"] == "a" * 40
    assert retained["conclusion"] == "failed"
    assert retained["failureCode"] == "missing_required_key"
    assert {(row["sdk"], row["provider"]) for row in retained["proofs"]} == {
        ("python", "openai"),
        ("typescript", "openai"),
    }
    assert {row["status"] for row in retained["proofs"]} == {"not_run"}


def test_protected_provider_proof_rejects_invalid_commit_before_install(
    tmp_path: Path,
) -> None:
    module = _load_root_script("live_provider_proof.py")
    evidence = tmp_path / "provider-evidence.json"
    arguments = _provider_arguments(tmp_path)
    arguments[-1] = "not-a-commit"
    environment = {
        "OPENAI_API_KEY": "openai-test-key",
        "ANTHROPIC_API_KEY": "anthropic-test-key",
        "KAJI_RELEASE_COMMIT": "a" * 40,
        "KAJI_PROVIDER_STATUS_FILE": str(evidence),
    }

    assert module.main(arguments, environment=environment) == 2

    retained = json.loads(evidence.read_text())
    assert retained["conclusion"] == "failed"
    assert retained["failureCode"] == "invalid_release_commit"


def test_protected_provider_proof_requires_parent_commit_binding_before_install(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_root_script("live_provider_proof.py")
    evidence = tmp_path / "provider-evidence.json"
    installed = False

    @contextmanager
    def unexpected_install(*_args: object, **_kwargs: object) -> Iterator[None]:
        nonlocal installed
        installed = True
        yield None

    monkeypatch.setattr(module, "installed_release_runtime", unexpected_install)
    environment = {
        "OPENAI_API_KEY": "openai-test-key",
        "ANTHROPIC_API_KEY": "anthropic-test-key",
        "KAJI_RELEASE_COMMIT": "b" * 40,
        "KAJI_PROVIDER_STATUS_FILE": str(evidence),
    }

    assert module.main(_provider_arguments(tmp_path), environment=environment) == 2

    retained = json.loads(evidence.read_text())
    assert retained["failureCode"] == "release_commit_mismatch"
    assert installed is False


def test_protected_provider_proof_retains_artifact_mismatch_without_details(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_root_script("live_provider_proof.py")
    evidence = tmp_path / "provider-evidence.json"

    @contextmanager
    def mismatched_runtime(*_args: object, **_kwargs: object) -> Iterator[None]:
        raise RuntimeError("artifact hash included secret detail")
        yield None

    monkeypatch.setattr(module, "installed_release_runtime", mismatched_runtime)
    environment = {
        "OPENAI_API_KEY": "openai-test-key",
        "ANTHROPIC_API_KEY": "anthropic-test-key",
        "KAJI_RELEASE_COMMIT": "a" * 40,
        "KAJI_PROVIDER_STATUS_FILE": str(evidence),
    }

    assert module.main(_provider_arguments(tmp_path), environment=environment) == 1

    retained = json.loads(evidence.read_text())
    assert retained["failureCode"] == "artifact_runtime_failed"
    assert "secret detail" not in evidence.read_text()
    captured = capsys.readouterr()
    assert "secret detail" not in captured.out + captured.err


def test_protected_provider_proof_runs_two_openai_tool_loops_and_records_commit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_root_script("live_provider_proof.py")
    evidence = tmp_path / "provider-evidence.json"
    runtime = _fake_installed_runtime(module, monkeypatch, tmp_path)
    calls: list[tuple[tuple[str, ...], Path, dict[str, str]]] = []

    def pass_command(
        command: list[str], *, cwd: Path, environment: dict[str, str]
    ) -> dict[str, object]:
        sdk = "python" if command[0] == str(runtime.python_executable) else "typescript"
        provider = command[command.index("--provider") + 1]
        model = command[command.index("--model") + 1]
        resolved = (
            runtime.resolved_python_package
            if sdk == "python"
            else runtime.resolved_typescript_package
        )
        calls.append((tuple(command), cwd, environment))
        return _runner_receipt(
            sdk=sdk,
            provider=provider,
            model=model,
            resolved_package=str(resolved),
        )

    monkeypatch.setattr(module, "_run_proof", pass_command, raising=False)
    environment = {
        "OPENAI_API_KEY": "openai-test-key",
        "ANTHROPIC_API_KEY": "anthropic-test-key",
        "AWS_SECRET_ACCESS_KEY": "aws-test-secret",
        "GITHUB_TOKEN": "github-test-secret",
        "NPM_TOKEN": "npm-test-secret",
        "KAJI_RELEASE_COMMIT": "a" * 40,
        "KAJI_PROVIDER_STATUS_FILE": str(evidence),
    }

    assert module.main(_provider_arguments(tmp_path), environment=environment) == 0

    retained = json.loads(evidence.read_text())
    assert retained["schemaVersion"] == 1
    assert retained["commit"] == "a" * 40
    assert retained["releaseManifestSha256"] == "b" * 64
    assert retained["artifacts"] == {
        "python": {
            "file": "kaji_sdk-0.2.0b1-py3-none-any.whl",
            "sha256": "c" * 64,
        },
        "typescript": {
            "file": "kaji-sdk-0.2.0-beta.7.tgz",
            "sha256": "d" * 64,
        },
    }
    assert retained["conclusion"] == "passed"
    assert retained["failureCode"] is None
    assert [
        (row["sdk"], row["provider"], row["status"]) for row in retained["proofs"]
    ] == [
        ("python", "openai", "passed"),
        ("typescript", "openai", "passed"),
    ]
    assert all(
        row["proof"] == "real_normalized_tool_loop" for row in retained["proofs"]
    )
    assert len(calls) == 2
    commands = [command for command, _cwd, _environment in calls]
    rendered = [" ".join(command) for command in commands]
    assert all("installed_provider_proof.py" in command for command in rendered[::2])
    assert all("installed-provider-proof.mts" in command for command in rendered[1::2])
    assert all(
        "-m pytest" not in command
        and "vitest" not in command
        and "test:integration" not in command
        for command in rendered
    )
    expected_row_keys = module.RUNNER_ROW_KEYS | {
        "artifactFile",
        "artifactSha256",
        "releaseManifestSha256",
    }
    assert all(set(row) == expected_row_keys for row in retained["proofs"])
    for command, _cwd, child in calls:
        provider = command[command.index("--provider") + 1]
        expected_key = module.PROVIDER_KEYS[provider]
        assert provider == "openai"
        assert child[expected_key] == "openai-test-key"
        assert "ANTHROPIC_API_KEY" not in child
        assert set(child) == {
            "PATH",
            "HOME",
            "TMPDIR",
            "LANG",
            "KAJI_RELEASE_COMMIT",
            expected_key,
            module.MODEL_ENV[provider],
        }
        assert child["KAJI_RELEASE_COMMIT"] == "a" * 40
    rendered_evidence = evidence.read_text()
    captured = capsys.readouterr()
    for secret in environment.values():
        if "secret" in secret or "test-key" in secret:
            assert secret not in rendered_evidence
            assert secret not in captured.out
            assert secret not in captured.err


def test_provider_child_environment_does_not_mutate_parent() -> None:
    module = _load_root_script("live_provider_proof.py")
    base = {
        "PATH": "/usr/bin",
        "HOME": "/isolated",
        "TMPDIR": "/isolated/tmp",
        "HTTPS_PROXY": "https://proxy.invalid",
        "UV_CACHE_DIR": "/isolated/cache/uv",
        "npm_config_cache": "/isolated/cache/npm",
        "UNRELATED_RUNTIME_VALUE": "must-not-leak",
    }
    parent = {
        "OPENAI_API_KEY": "openai-test-key",
        "ANTHROPIC_API_KEY": "anthropic-test-key",
        "AWS_SECRET_ACCESS_KEY": "aws-secret",
        "GITHUB_TOKEN": "github-secret",
    }

    openai = module._child_environment(base, parent, "openai", "gpt-5.4-mini", "a" * 40)
    assert openai == {
        "PATH": "/usr/bin",
        "HOME": "/isolated",
        "TMPDIR": "/isolated/tmp",
        "HTTPS_PROXY": "https://proxy.invalid",
        "KAJI_RELEASE_COMMIT": "a" * 40,
        "OPENAI_API_KEY": "openai-test-key",
        "KAJI_LIVE_OPENAI_MODEL": "gpt-5.4-mini",
    }
    assert set(parent) == {
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "GITHUB_TOKEN",
    }


def test_installed_provider_runners_use_only_public_package_imports() -> None:
    python = SDK_ROOT / "scripts/installed_provider_proof.py"
    typescript = REPO_ROOT / "kaji/ts/scripts/installed-provider-proof.mts"

    assert python.is_file()
    assert typescript.is_file()
    python_source = python.read_text(encoding="utf-8")
    typescript_source = typescript.read_text(encoding="utf-8")
    assert "from kaji" in python_source
    assert "kaji/src" not in python_source
    assert "AnthropicProvider" not in python_source
    assert "ANTHROPIC_API_KEY" not in python_source
    assert 'from "kaji-sdk"' in typescript_source
    assert 'from "kaji-sdk/openai"' in typescript_source
    assert 'from "kaji-sdk/anthropic"' not in typescript_source
    assert "ANTHROPIC_API_KEY" not in typescript_source
    assert 'from "@/' not in typescript_source
    assert "/dist/" not in typescript_source


def test_protected_provider_proof_uses_three_minute_per_command_budget() -> None:
    module = _load_root_script("live_provider_proof.py")

    assert module.KEYED_PROOF_BUDGET.timeout_seconds == 180


def test_protected_provider_proof_retains_partial_rows_on_command_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_root_script("live_provider_proof.py")
    evidence = tmp_path / "provider-evidence.json"
    runtime = _fake_installed_runtime(module, monkeypatch, tmp_path)
    calls = 0

    def fail_second(
        command: list[str], *, cwd: Path, environment: dict[str, str]
    ) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise module.CommandExitError(17)
        return _runner_receipt(
            sdk="python",
            provider="openai",
            model="gpt-5.4-mini",
            resolved_package=str(runtime.resolved_python_package),
        )

    monkeypatch.setattr(module, "_run_proof", fail_second)
    environment = {
        "OPENAI_API_KEY": "openai-test-key",
        "ANTHROPIC_API_KEY": "anthropic-test-key",
        "KAJI_RELEASE_COMMIT": "a" * 40,
        "KAJI_PROVIDER_STATUS_FILE": str(evidence),
    }

    assert module.main(_provider_arguments(tmp_path), environment=environment) == 1

    retained = json.loads(evidence.read_text())
    assert retained["conclusion"] == "failed"
    assert retained["failureCode"] == "proof_command_failed"
    assert [row["status"] for row in retained["proofs"]] == [
        "passed",
        "failed",
    ]


@pytest.mark.parametrize(
    ("mutation", "failure_code"),
    [
        ({"unexpectedFinalText": "raw output"}, "proof_receipt_invalid"),
        (
            {"resolvedPackage": "/workspace/kaji/ts/dist"},
            "proof_receipt_invalid",
        ),
    ],
)
def test_protected_provider_proof_rejects_malformed_or_source_receipts(
    mutation: dict[str, object],
    failure_code: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_root_script("live_provider_proof.py")
    evidence = tmp_path / "provider-evidence.json"
    runtime = _fake_installed_runtime(module, monkeypatch, tmp_path)

    def malformed(
        command: list[str], *, cwd: Path, environment: dict[str, str]
    ) -> dict[str, object]:
        row = _runner_receipt(
            sdk="python",
            provider="openai",
            model="gpt-5.4-mini",
            resolved_package=str(runtime.resolved_python_package),
        )
        row.update(mutation)
        return row

    monkeypatch.setattr(module, "_run_proof", malformed)
    environment = {
        "OPENAI_API_KEY": "openai-test-key",
        "ANTHROPIC_API_KEY": "anthropic-test-key",
        "KAJI_RELEASE_COMMIT": "a" * 40,
        "KAJI_PROVIDER_STATUS_FILE": str(evidence),
    }

    assert module.main(_provider_arguments(tmp_path), environment=environment) == 1

    retained = json.loads(evidence.read_text())
    assert retained["conclusion"] == "failed"
    assert retained["failureCode"] == failure_code
    assert "unexpectedFinalText" not in evidence.read_text()
    assert "raw output" not in capsys.readouterr().out


def test_protected_provider_proof_retains_interruption_without_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_root_script("live_provider_proof.py")
    evidence = tmp_path / "provider-evidence.json"
    _fake_installed_runtime(module, monkeypatch, tmp_path)
    monkeypatch.setattr(
        module,
        "_run_proof",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            module.CommandInterruptedError(15)
        ),
    )
    environment = {
        "OPENAI_API_KEY": "openai-test-key",
        "ANTHROPIC_API_KEY": "anthropic-test-key",
        "KAJI_RELEASE_COMMIT": "a" * 40,
        "KAJI_PROVIDER_STATUS_FILE": str(evidence),
    }

    assert module.main(_provider_arguments(tmp_path), environment=environment) == 1

    retained = json.loads(evidence.read_text())
    assert retained["failureCode"] == "proof_command_interrupted"
    captured = capsys.readouterr()
    assert "CommandInterruptedError" not in captured.out + captured.err


def test_provider_evidence_write_failure_removes_stale_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_root_script("live_provider_proof.py")
    evidence = tmp_path / "provider-evidence.json"
    evidence.write_text('{"conclusion":"passed"}\n', encoding="utf-8")
    monkeypatch.setattr(
        module,
        "_write_json_atomic",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("secret detail")),
    )
    environment = {
        "OPENAI_API_KEY": "openai-test-key",
        "ANTHROPIC_API_KEY": "anthropic-test-key",
        "KAJI_RELEASE_COMMIT": "a" * 40,
        "KAJI_PROVIDER_STATUS_FILE": str(evidence),
    }

    assert module.main(_provider_arguments(tmp_path), environment=environment) == 1
    assert not evidence.exists()


@pytest.mark.parametrize(
    "script",
    [
        "verify_openai_loop.py",
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
    assert status == 143
