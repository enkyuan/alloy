#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
MINUTES=30
if [[ $# -gt 0 ]]; then
  if [[ $# -ne 2 || "$1" != --minutes ]]; then
    echo "usage: $0 [--minutes N]" >&2
    exit 2
  fi
  MINUTES=$2
fi

if command -v uv >/dev/null 2>&1; then
  PYTHON=(uv run --project "$ROOT/kaji/sdk" python)
elif [[ -x "$ROOT/kaji/sdk/.venv/bin/python" ]]; then
  PYTHON=("$ROOT/kaji/sdk/.venv/bin/python")
else
  echo "uv or kaji/sdk/.venv is required" >&2
  exit 2
fi

ARTIFACTS="$ROOT/.artifacts/kaji-soak"
mkdir -p "$ARTIFACTS"
PYTHON_RESULT="$ARTIFACTS/python.json"
TYPESCRIPT_RESULT="$ARTIFACTS/typescript.json"

"${PYTHON[@]}" "$ROOT/kaji/sdk/benchmarks/runtime_soak.py" \
  --minutes "$MINUTES" \
  --minimum-turns 10000 \
  --seed 13 \
  --artifacts-dir "$ARTIFACTS" \
  --json >"$PYTHON_RESULT" &
PYTHON_PID=$!

bun "$ROOT/kaji/ts/benchmarks/runtime-soak.ts" \
  --minutes "$MINUTES" \
  --seed 13 \
  --artifacts-dir "$ARTIFACTS" \
  --json >"$TYPESCRIPT_RESULT" &
TYPESCRIPT_PID=$!

set +e
wait "$PYTHON_PID"
PYTHON_STATUS=$?
wait "$TYPESCRIPT_PID"
TYPESCRIPT_STATUS=$?
set -e
set +e
"${PYTHON[@]}" "$ROOT/kaji/scripts/beta-soak-gate.py" \
  --minutes "$MINUTES" \
  --python "$PYTHON_RESULT" \
  --typescript "$TYPESCRIPT_RESULT" \
  --output "$ARTIFACTS/results.json"
GATE_STATUS=$?
set -e

if [[ $PYTHON_STATUS -ne 0 || $TYPESCRIPT_STATUS -ne 0 || $GATE_STATUS -ne 0 ]]; then
  exit 1
fi
echo "PASS: Python and TypeScript soak budgets"
