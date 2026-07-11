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

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CONTRACTS_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/../../contracts" && pwd)

# Capture listing once to avoid SIGPIPE from grep -q under pipefail on macOS.
LISTING=$(unzip -l "$WHEEL")

# Top-level package present, remap worked.
echo "$LISTING" | grep -q 'kaji/__init__.py' \
  || { echo "FAIL: kaji/__init__.py missing from wheel (sources remap broken)"; exit 1; }

# py.typed shipped.
echo "$LISTING" | grep -q 'kaji/py.typed' \
  || { echo "FAIL: kaji/py.typed missing from wheel"; exit 1; }

# Registry index, schema, manifests, and every file declared by a manifest.
# The registry may not contain every historical file type. The contract that
# matters for users is that `kaji add <name>` can copy each manifest file.
PYTHON_BIN="${PYTHON:-python3}"
WHEEL="$WHEEL" CONTRACTS_DIR="$CONTRACTS_DIR" "$PYTHON_BIN" - <<'PY'
from __future__ import annotations

import json
import os
import posixpath
import sys
import zipfile
from pathlib import Path

wheel = os.environ["WHEEL"]
contracts_dir = Path(os.environ["CONTRACTS_DIR"])
registry_root = "kaji/integrations/registry"


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    print(
        "      The built wheel does not match its canonical runtime artifacts. "
        "Check [tool.setuptools.package-data] and the contract sync step.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def registry_path(base: str, rel: str) -> str:
    if rel.startswith("/") or ".." in rel.split("/"):
        fail(f"manifest declares unsafe path: {rel}")
    path = posixpath.normpath(posixpath.join(base, rel))
    if not path.startswith(f"{registry_root}/"):
        fail(f"manifest path escapes registry root: {rel}")
    return path


with zipfile.ZipFile(wheel) as zf:
    names = set(zf.namelist())
    index_path = f"{registry_root}/index.json"
    schema_path = f"{registry_root}/schema.json"
    package_markers = [
        f"{registry_root}/__init__.py",
        f"{registry_root}/echo/__init__.py",
        "kaji/contracts/__init__.py",
        "kaji/contracts/beta-core-v1.json",
        "kaji/contracts/events/new-kaji-event-v1.schema.json",
        "kaji/contracts/events/stored-kaji-event-v1.schema.json",
    ]

    generated = sorted(path for path in names if "__pycache__" in path or path.endswith(".pyc"))
    if generated:
        fail(f"generated Python cache files present: {generated[:5]}")

    stale_modules = [
        "kaji/infra/realtime/redis_common.py",
        "kaji/infra/realtime/redis_dedup.py",
        "kaji/infra/realtime/redis_dlq.py",
        "kaji/infra/realtime/redis_history_ops.py",
        "kaji/infra/realtime/redis_publish.py",
        "kaji/infra/realtime/redis_streams.py",
    ]
    stale = sorted(path for path in stale_modules if path in names)
    if stale:
        fail(f"stale renamed modules present: {stale}")

    for path in (index_path, schema_path, *package_markers):
        if path not in names:
            fail(f"{path} missing from wheel")
        print(f"  ok: {path}")

    canonical_contracts = {
        path.relative_to(contracts_dir).as_posix(): path.read_bytes()
        for path in contracts_dir.rglob("*")
        if path.is_file() and path.suffix in {".json", ".md"}
    }
    packaged_contracts = {
        path.removeprefix("kaji/contracts/")
        for path in names
        if path.startswith("kaji/contracts/") and Path(path).suffix in {".json", ".md"}
    }
    expected_contracts = set(canonical_contracts)
    if packaged_contracts != expected_contracts:
        missing = sorted(expected_contracts - packaged_contracts)
        extra = sorted(packaged_contracts - expected_contracts)
        fail(f"wheel contract set mismatch; missing={missing}, extra={extra}")
    for relative, expected in sorted(canonical_contracts.items()):
        packaged = zf.read(f"kaji/contracts/{relative}")
        if packaged != expected:
            fail(f"kaji/contracts/{relative} differs from canonical bytes")
        print(f"  ok: contract {relative}")

    index = json.loads(zf.read(index_path))
    integrations = index.get("integrations") or {}
    if not integrations:
        fail("registry index declares no integrations")

    for name, entry in sorted(integrations.items()):
        manifest_rel = entry.get("manifest") if isinstance(entry, dict) else entry
        if not isinstance(manifest_rel, str) or not manifest_rel:
            fail(f"{name}: registry entry has no manifest path")
        manifest_path = registry_path(registry_root, manifest_rel)
        if manifest_path not in names:
            fail(f"{name}: manifest {manifest_rel} missing from wheel")
        print(f"  ok: {name}/{manifest_rel}")

        manifest = json.loads(zf.read(manifest_path))
        files = manifest.get("files") or []
        if not files:
            fail(f"{name}: manifest declares no files")

        manifest_root = posixpath.dirname(manifest_path)
        for rel in files:
            file_path = registry_path(manifest_root, rel)
            if file_path not in names:
                fail(f"{name}: manifest file {rel} missing from wheel")
            print(f"  ok: {name}/{rel}")
PY

echo "PASS: wheel contents verified"
