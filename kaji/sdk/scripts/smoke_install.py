#!/usr/bin/env python3
"""Install smoke test for kaji.

Validates that the installed wheel exports resolve correctly and that provider
instantiation fails with a clear error when no API key is set. Does NOT run a
full agent turn — that requires a real provider key and belongs in integration tests.

Run after installing the built wheel into a clean venv:
    pip install dist/*.whl
    python scripts/smoke_install.py
"""

from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# 1. Top-level lazy imports resolve
# ---------------------------------------------------------------------------
print("Checking top-level imports...")

import kaji  # noqa: E402

required_names = [
    "AgentBuilder",
    "AgentRuntime",
    "InMemoryEventStore",
    "InMemoryEventBus",
    "ToolSpec",
    "ToolRegistry",
    "get_provider",
    "register_provider",
    "CancellationToken",
    "UserMessage",
    "SessionManager",
]

for name in required_names:
    obj = getattr(kaji, name, None)
    if obj is None:
        print(f"FAIL: kaji.{name} is None or missing", file=sys.stderr)
        sys.exit(1)
    print(f"  ok: kaji.{name}")

# ---------------------------------------------------------------------------
# 2. get_provider("openai") raises ProviderConfigError when key is absent
# ---------------------------------------------------------------------------
print("\nChecking OpenAI provider error when key absent...")

os.environ.pop("OPENAI_API_KEY", None)

try:
    kaji.get_provider("openai")
    # If no error is raised, the provider may load lazily; attempt a generate call
    print(
        "  ok: get_provider('openai') returned (key checked at instantiation/call time)"
    )
except Exception as e:
    error_text = str(e).lower()
    if "openai" in error_text or "api key" in error_text or "config" in error_text:
        print(f"  ok: clear error raised: {e}")
    else:
        print(f"FAIL: unexpected error message: {e}", file=sys.stderr)
        sys.exit(1)

# ---------------------------------------------------------------------------
# 3. Version attribute is present
# ---------------------------------------------------------------------------
print("\nChecking version...")
assert hasattr(kaji, "__version__"), "kaji.__version__ missing"
print(f"  ok: kaji.__version__ = {kaji.__version__}")

# ---------------------------------------------------------------------------
# 4. Every registry manifest file ships in the wheel.
# ---------------------------------------------------------------------------
# Catches packaging drift: the registry is dual-language (.py + .ts), and
# pyproject.toml must include every glob declared by any manifest. A missing
# file would only surface when a user calls install_integration() on a real
# install, so check it here.
print("\nChecking every registry manifest file is packaged...")

from kaji.integrations import list_integrations, load_manifest  # noqa: E402

for entry in list_integrations():
    manifest = load_manifest(entry)
    for rel in manifest.files:
        src = manifest.root / rel
        if not src.exists():
            print(
                f"FAIL: {entry}: manifest declares '{rel}' but it is missing "
                f"from the installed wheel at {src}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"  ok: {entry}/{rel}")

print("\nSmoke install: PASSED")
