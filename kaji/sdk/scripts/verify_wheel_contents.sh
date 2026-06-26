#!/usr/bin/env bash
# Verifies the built wheel ships everything the SDK needs at runtime.
# Run after `uv build --wheel`. Exits non-zero on any missing artifact.
set -euo pipefail

WHEEL=$(ls -t dist/*.whl 2>/dev/null | head -1)
if [ -z "$WHEEL" ]; then
  echo "FAIL: no wheel under dist/. Run 'uv build --wheel' first." >&2
  exit 1
fi

echo "Inspecting $WHEEL"

# Capture listing once to avoid SIGPIPE from grep -q under pipefail on macOS.
LISTING=$(unzip -l "$WHEEL")

# Top-level package present, remap worked.
echo "$LISTING" | grep -q 'kaji/__init__.py' \
  || { echo "FAIL: kaji/__init__.py missing from wheel (sources remap broken)"; exit 1; }

# py.typed shipped.
echo "$LISTING" | grep -q 'kaji/py.typed' \
  || { echo "FAIL: kaji/py.typed missing from wheel"; exit 1; }

# Registry data files of every format.
for ext in json py md ts; do
  COUNT=$(echo "$LISTING" | grep -cE "kaji/integrations/registry/.*\.${ext}\$" || true)
  if [ "$COUNT" -eq 0 ]; then
    echo "FAIL: no .${ext} files under kaji/integrations/registry/ in wheel" >&2
    echo "      hatchling force-include is misconfigured. install_integration() will break for end users." >&2
    exit 1
  fi
  echo "  ok: $COUNT .${ext} files"
done

echo "PASS: wheel contents verified"
