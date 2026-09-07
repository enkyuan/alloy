"""Fail CI when new Kaji source filenames exceed two semantic components."""

from __future__ import annotations

import sys

if __name__ == "__main__":
    sys.path.pop(0)

from pathlib import Path
import re

KAJI_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "contracts").is_dir() and (parent / "packages").is_dir()
)
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"}
IGNORED_DIRECTORIES = {".git", ".venv", "__pycache__", "dist", "node_modules", "alembic"}
EXEMPT_FILES = {
    "packages/ts/scripts/check_integration_sources.ts",
    "packages/ts/scripts/installed-github-live.mts",
    "packages/ts/scripts/installed-github-smoke.mts",
    "packages/ts/scripts/installed-provider-proof.mts",
    "packages/ts/src/cli/integration-copy-worker.mjs",
    "packages/ts/src/cli/package-entry-cjs.ts",
    "packages/ts/tests/contracts/cross-sdk-fixtures.test.ts",
    "packages/ts/tests/events/split-blocker-gc-probe.ts",
    "packages/ts/tests/integrations/github-observability-wiring.test.ts",
    "packages/serve/tests/test_api_auth_jwt.py",
    "packages/serve/tests/test_modalities_voice_stt.py",
    "packages/serve/tests/test_modalities_voice_stt_helpers.py",
    "packages/py/tests/context_rss_probe.py",
    "packages/py/tests/contracts/test_cross_sdk_fixtures.py",
    "packages/py/tests/events/test_event_payload_limits.py",
    "packages/py/tests/integrations/test_github_proof_cleanup.py",
    "packages/py/tests/providers/test_provider_stream_limits.py",
    "packages/py/tests/providers/test_providers_gemini_stream.py",
    "packages/py/tests/release/test_approve_typescript_onboarding_gate.py",
    "packages/py/tests/release/test_beta_release_check.py",
    "packages/py/tests/release/test_live_github_proof.py",
    "packages/py/tests/release/test_live_gmail_proof.py",
    "packages/py/tests/release/test_production_beta_docs.py",
    "packages/py/tests/release/test_typescript_onboarding_evidence.py",
    "packages/py/tests/release/test_validate_ts_consumer_handoff.py",
    "packages/py/tests/release/test_verify_ts_handoff_source.py",
    "packages/py/tests/runtime/test_effective_runtime_limits.py",
    "packages/py/tests/tools/test_tool_execution_limits.py",
    "packages/py/tests/tools/test_tool_schema_conformance.py",
}


def components(path: Path) -> list[str]:
    stem = path.stem.removeprefix("test_")
    return [part for part in re.split(r"[_-]+", stem) if part]


def main() -> int:
    violations = []
    for path in KAJI_ROOT.rglob("*"):
        relative = path.relative_to(KAJI_ROOT)
        if (
            not path.is_file()
            or path.suffix not in SOURCE_SUFFIXES
            or any(part in IGNORED_DIRECTORIES for part in relative.parts)
            or relative.as_posix() in EXEMPT_FILES
            or path.stem in {"__init__", "__main__", "conftest"}
        ):
            continue
        if len(components(path)) > 2:
            violations.append(relative.as_posix())
    if violations:
        print("filename convention violations:", *violations, sep="\n  ", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
