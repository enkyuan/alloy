from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


SDK_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SDK_ROOT.parents[1]
LIVE_GATE = REPO_ROOT / "kaji" / "scripts" / "live_openai_tool_loop.py"


def _load_root_script(name: str) -> ModuleType:
    path = REPO_ROOT / "kaji" / "scripts" / name
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


def test_live_gate_skips_cleanly_without_openai_key() -> None:
    proc = subprocess.run(
        [sys.executable, str(LIVE_GATE)],
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


def test_live_gate_fails_without_key_when_required() -> None:
    proc = subprocess.run(
        [sys.executable, str(LIVE_GATE)],
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


@pytest.mark.parametrize(
    "script",
    [
        "live_openai_tool_loop.py",
        "live_provider_proof.py",
        "run_beta_benchmarks.py",
    ],
)
def test_root_script_runners_normalize_signal_exit_status(
    script: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_root_script(script)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=-15),
    )

    if script == "run_beta_benchmarks.py":
        status = module.run(["tool"])
    else:
        status = module.run(["tool"], cwd=REPO_ROOT, environment={})

    assert status == 143
