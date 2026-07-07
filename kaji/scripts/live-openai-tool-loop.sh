#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODEL="${KAJI_LIVE_OPENAI_MODEL:-gpt-5.4-mini}"

if [ -z "${OPENAI_API_KEY:-}" ]; then
  if [ "${KAJI_REQUIRE_LIVE_KEYS:-}" = "1" ]; then
    echo "FAIL: OPENAI_API_KEY required for live readiness" >&2
    exit 2
  fi
  echo "SKIP: OPENAI_API_KEY not set"
  exit 0
fi

echo "Running Python OpenAI live tool-loop with ${MODEL}"
(
  cd "$ROOT/kaji/sdk"
  KAJI_LIVE_OPENAI_MODEL="$MODEL" uv run pytest -m integration tests/integration/test_openai_tools.py -q
)

echo "Running TypeScript OpenAI live tool-loop with ${MODEL}"
(
  cd "$ROOT/kaji/ts"
  KAJI_LIVE_OPENAI_MODEL="$MODEL" bun run test:integration tests/integration/openai-tools.test.ts
)

echo "PASS: OpenAI live tool-loop readiness verified"
