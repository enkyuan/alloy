#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
MODE=${1:-}

case "$MODE" in
  --quick) MODE_NAME=quick ;;
  --full) MODE_NAME=full ;;
  --calibrate) MODE_NAME=calibrate ;;
  *)
    echo "usage: $0 --quick|--full|--calibrate" >&2
    exit 2
    ;;
esac

if command -v uv >/dev/null 2>&1; then
  PYTHON=(uv run --project "$ROOT/kaji/sdk" python)
  PYTEST=(uv run --project "$ROOT/kaji/sdk" pytest)
elif [[ -x "$ROOT/kaji/sdk/.venv/bin/python" ]]; then
  PYTHON=("$ROOT/kaji/sdk/.venv/bin/python")
  PYTEST=("$ROOT/kaji/sdk/.venv/bin/pytest")
else
  echo "uv or kaji/sdk/.venv is required" >&2
  exit 2
fi

if [[ "$MODE_NAME" == quick ]]; then
  "${PYTEST[@]}" \
    "$ROOT/kaji/sdk/tests/test_runtime_complexity.py" \
    "$ROOT/kaji/sdk/tests/test_runtime_faults.py" \
    "$ROOT/kaji/sdk/tests/test_events_journal.py" \
    "$ROOT/kaji/sdk/tests/test_runtime_concurrency.py" \
    "$ROOT/kaji/sdk/tests/test_tool_execution_limits.py" \
    "$ROOT/kaji/sdk/tests/test_approval_lifecycle.py" \
    -q --no-cov
  (
    cd "$ROOT/kaji/ts"
    bun run vitest run \
      tests/runtime-complexity.test.ts \
      tests/runtime-faults.test.ts \
      tests/event-delivery.test.ts \
      tests/runtime-concurrency.test.ts \
      tests/tool-execution-limits.test.ts \
      tests/approval-lifecycle.test.ts \
      tests/safe-fetch.test.ts \
      tests/registry-resource-limits.test.ts
  )
  TEMP_DIR=$(mktemp -d)
  trap 'rm -rf "$TEMP_DIR"' EXIT
  OUTPUT="$TEMP_DIR/quick-results.json"
  "${PYTHON[@]}" "$ROOT/kaji/scripts/beta-benchmark-gate.py" \
    --mode quick \
    --output "$OUTPUT"
  "${PYTHON[@]}" -c \
    'import json,sys; value=json.load(open(sys.argv[1])); assert value["passed"] and value["mode"] == "quick"' \
    "$OUTPUT"
  echo "PASS: deterministic complexity/fault gates and quick benchmark smoke"
  exit 0
fi

ARTIFACTS="$ROOT/.artifacts/kaji-benchmarks"
mkdir -p "$ARTIFACTS"
if [[ "$MODE_NAME" == full ]]; then
  "${PYTHON[@]}" "$ROOT/kaji/scripts/beta-benchmark-gate.py" \
    --mode full \
    --output "$ARTIFACTS/results.json"
  echo "PASS: full benchmark budgets and calibrated regression baseline"
else
  "${PYTHON[@]}" "$ROOT/kaji/scripts/beta-benchmark-gate.py" \
    --mode calibrate \
    --output "$ARTIFACTS/calibration-results.json" \
    --candidate-baseline "$ARTIFACTS/beta-baseline.candidate.json"
  echo "PASS: candidate baseline written for review"
fi
