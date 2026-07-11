#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DIST_DIR="${DIST_DIR:-dist}"
if [ -n "${PYTHON:-}" ]; then
  PYTHON_CMD=("$PYTHON")
elif command -v uv >/dev/null 2>&1; then
  PYTHON_CMD=(uv run --no-sync python)
else
  PYTHON_CMD=(python3)
fi

bash scripts/clean_generated.sh
rm -rf build
uv build --sdist --wheel --clear --out-dir "$DIST_DIR" \
  --build-constraints build-requirements.txt --require-hashes
bash scripts/verify_wheel.sh "$DIST_DIR"
"${PYTHON_CMD[@]}" scripts/test_archive_verifier.py "$DIST_DIR"

TMP_PARENT="${TMPDIR:-/tmp}"
WORKDIR="$(mktemp -d "${TMP_PARENT%/}/kaji-sdk-release-smoke.XXXXXX")"
cleanup() {
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

WHEEL="$(find "$DIST_DIR" -maxdepth 1 -type f -name '*.whl' -print | head -1)"
SDIST="$(find "$DIST_DIR" -maxdepth 1 -type f -name '*.tar.gz' -print | head -1)"
if [ -z "$WHEEL" ] || [ -z "$SDIST" ]; then
  echo "FAIL: expected wheel and sdist under $DIST_DIR" >&2
  exit 1
fi

uv export --locked --no-dev --no-emit-project \
  --extra openai --extra anthropic \
  --output-file "$WORKDIR/runtime-requirements.txt"

for package in "$WHEEL" "$SDIST"; do
  name="$(basename "$package")"
  venv="$WORKDIR/venv-${name//[^a-zA-Z0-9]/-}"
  uv run --no-sync python -m venv "$venv"
  "$venv/bin/python" -m pip install --require-hashes \
    --requirement build-requirements.txt
  "$venv/bin/python" -m pip install --require-hashes \
    --requirement "$WORKDIR/runtime-requirements.txt"
  "$venv/bin/python" -m pip install --no-deps --no-build-isolation "$package"
  "$venv/bin/python" scripts/smoke_install.py
done

bash scripts/verify_wheel.sh "$DIST_DIR"

echo "PASS: release smoke verified"
