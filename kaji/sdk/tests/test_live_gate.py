from __future__ import annotations

import os
import subprocess
from pathlib import Path


SDK_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SDK_ROOT.parents[1]
LIVE_GATE = REPO_ROOT / "kaji" / "scripts" / "live-openai-tool-loop.sh"


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
        ["bash", str(LIVE_GATE)],
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
        ["bash", str(LIVE_GATE)],
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
