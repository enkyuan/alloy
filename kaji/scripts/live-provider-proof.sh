#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "FAIL: OPENAI_API_KEY is required for keyed provider proof" >&2
  exit 2
fi

KAJI_REQUIRE_LIVE_KEYS=1 bash "$ROOT/kaji/scripts/live-openai-tool-loop.sh"

ANTHROPIC_STATUS="not_configured"
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  echo "Running Python Anthropic normalized tool-call proof"
  (
    cd "$ROOT/kaji/sdk"
    uv run --extra anthropic pytest -m integration \
      tests/integration/test_anthropic_provider.py -k normalized_tool_call -q
  )

  echo "Running TypeScript Anthropic normalized tool-call proof"
  (
    cd "$ROOT/kaji/ts"
    bun run test:integration tests/integration/anthropic-live.test.ts -t "normalized tool call"
  )
  ANTHROPIC_STATUS="passed"
fi

STATUS="STATUS: openai=passed\nSTATUS: anthropic=$ANTHROPIC_STATUS"
printf '%b\n' "$STATUS"
if [ -n "${KAJI_PROVIDER_STATUS_FILE:-}" ]; then
  printf '%b\n' "$STATUS" >"$KAJI_PROVIDER_STATUS_FILE"
fi
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  printf '## Keyed provider proof\n\n```text\n%b\n```\n' "$STATUS" >>"$GITHUB_STEP_SUMMARY"
fi

echo "PASS: required OpenAI keyed provider proof completed"
