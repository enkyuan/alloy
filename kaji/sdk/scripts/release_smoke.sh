#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

bash scripts/clean_generated.sh
rm -rf build
uv build --wheel --clear
bash scripts/verify_wheel.sh

TMP_PARENT="${TMPDIR:-/tmp}"
WORKDIR="$(mktemp -d "${TMP_PARENT%/}/kaji-sdk-release-smoke.XXXXXX")"
cleanup() {
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

python3 -m venv "$WORKDIR/venv"
WHEEL="$(ls -t dist/*.whl 2>/dev/null | head -1)"
if [ -z "$WHEEL" ]; then
  echo "FAIL: no wheel under dist/. Run 'uv build --wheel' first." >&2
  exit 1
fi

"$WORKDIR/venv/bin/python" -m pip install "$WHEEL"
"$WORKDIR/venv/bin/python" scripts/smoke_install.py

echo "PASS: release smoke verified"
