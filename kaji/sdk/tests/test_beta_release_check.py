from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
BETA_GATE = REPO_ROOT / "kaji" / "scripts" / "beta-release-check.sh"


def test_beta_release_check_shell_syntax() -> None:
    subprocess.run(["bash", "-n", str(BETA_GATE)], check=True)


def test_beta_release_check_wraps_required_gates() -> None:
    script = BETA_GATE.read_text()

    for expected in [
        "uv run pytest -m \"not integration\"",
        "uv run python scripts/typecheck_ty.py --output-format concise",
        "uv run ruff check src tests",
        "bash scripts/release_smoke.sh",
        "bun run test",
        "bun run typecheck",
        "bun run build",
        "bun run scripts/smoke.mts",
        "live-openai-tool-loop.sh",
        "KAJI_REQUIRE_LIVE_KEYS",
        "KAJI_RUN_KEYED_LIVE",
        "UV_SYSTEM_CERTS",
        "sg scan --config sgconfig.yml kaji",
    ]:
        assert expected in script


def test_release_docs_reference_beta_release_check() -> None:
    combined = "\n".join(
        [
            (REPO_ROOT / "kaji" / "RELEASE_MATRIX.md").read_text(),
            (REPO_ROOT / "kaji" / "sdk" / "README.md").read_text(),
            (REPO_ROOT / "kaji" / "ts" / "README.md").read_text(),
            (REPO_ROOT / "docs" / "MVP.md").read_text(),
        ]
    )

    assert "bash kaji/scripts/beta-release-check.sh" in combined
    assert "KAJI_RUN_KEYED_LIVE=1" in combined
