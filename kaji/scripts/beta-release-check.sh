#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Codex and some CI runners invoke scripts with a minimal PATH. Include common
# local tool locations without depending on a user-specific shell profile.
export PATH="$HOME/.local/bin:$HOME/.bun/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

# Use the platform trust store by default so uv works on developer machines with
# managed/corporate certificates. Callers can override this environment variable.
export UV_SYSTEM_CERTS="${UV_SYSTEM_CERTS:-true}"

section() {
  printf '\n==> %s\n' "$1"
}

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

require_command() {
  local command_name="$1"
  local reason="$2"

  if ! command -v "$command_name" >/dev/null 2>&1; then
    fail "$command_name is required for $reason"
  fi
}

run_in_dir() {
  local label="$1"
  local dir="$2"
  shift 2

  section "$label"
  (
    cd "$dir"
    "$@"
  )
}

run_no_key_live_skip() {
  section "No-key live gate skip hygiene"
  (
    unset OPENAI_API_KEY KAJI_LIVE_OPENAI_MODEL KAJI_REQUIRE_LIVE_KEYS
    bash "$ROOT/kaji/scripts/live-openai-tool-loop.sh"
  )
}

run_required_key_failure() {
  section "Required-key live gate failure hygiene"

  local output
  local status
  set +e
  output="$(
    unset OPENAI_API_KEY KAJI_LIVE_OPENAI_MODEL
    KAJI_REQUIRE_LIVE_KEYS=1 bash "$ROOT/kaji/scripts/live-openai-tool-loop.sh" 2>&1
  )"
  status=$?
  set -e

  if [ "$status" -ne 2 ]; then
    printf '%s\n' "$output" >&2
    fail "expected live gate to exit 2 without OPENAI_API_KEY when keys are required; got $status"
  fi

  printf '%s\n' "$output"
}

require_command bun "TypeScript SDK release gates"
require_command uv "cross-SDK parity and Python SDK release gates"

run_no_key_live_skip
run_required_key_failure

run_in_dir "ast-grep structural audit" "$ROOT" bun run audit:ast-grep

run_in_dir "Cross-SDK behavioral parity" "$ROOT" uv run --project kaji/sdk python kaji/scripts/check-sdk-parity.py
run_in_dir "Deterministic complexity and quick benchmark smoke" "$ROOT" bash kaji/scripts/run-beta-benchmarks.sh --quick

run_in_dir "TypeScript unit tests" "$ROOT/kaji/ts" bun run test
run_in_dir "TypeScript typecheck" "$ROOT/kaji/ts" bun run typecheck
run_in_dir "TypeScript build" "$ROOT/kaji/ts" bun run build
run_in_dir "TypeScript package smoke" "$ROOT/kaji/ts" bun run scripts/smoke.mts

run_in_dir "Python unit tests" "$ROOT/kaji/sdk" uv run pytest -m "not integration"
run_in_dir "Python typecheck" "$ROOT/kaji/sdk" uv run python scripts/typecheck_ty.py --output-format concise
run_in_dir "Python lint" "$ROOT/kaji/sdk" uv run ruff check src tests
run_in_dir "Python wheel smoke" "$ROOT/kaji/sdk" bash scripts/release_smoke.sh

if [ "${KAJI_RUN_KEYED_LIVE:-0}" = "1" ]; then
  if [ -z "${OPENAI_API_KEY:-}" ]; then
    fail "OPENAI_API_KEY is required when KAJI_RUN_KEYED_LIVE=1"
  fi
  section "Keyed OpenAI live proof"
  bash "$ROOT/kaji/scripts/live-openai-tool-loop.sh"
else
  section "Keyed OpenAI live proof"
  echo "SKIP: not requested; set KAJI_RUN_KEYED_LIVE=1 with OPENAI_API_KEY before claiming live readiness."
fi

echo
echo "PASS: non-keyed beta release checks completed"
