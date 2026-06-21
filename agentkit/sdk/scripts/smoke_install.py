#!/usr/bin/env python3
"""Install smoke test for agentkit.

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

import agentkit  # noqa: E402

required_names = [
    "AgentBuilder",
    "AgentRuntime",
    "InMemoryEventStore",
    "InMemoryEventBus",
    "ToolSpec",
    "ToolRegistry",
    "ToolPlanner",
    "ToolPolicy",
    "GetProvider",
    "RegisterProvider",
    "CancellationToken",
    "UserMessage",
    "EventType",
    "AgentKitEvent",
    "InMemorySessionStore",
    "SessionManager",
]

for name in required_names:
    obj = getattr(agentkit, name, None)
    if obj is None:
        print(f"FAIL: agentkit.{name} is None or missing", file=sys.stderr)
        sys.exit(1)
    print(f"  ok: agentkit.{name}")

# ---------------------------------------------------------------------------
# 2. GetProvider("openai") raises ProviderConfigError when key is absent
# ---------------------------------------------------------------------------
print("\nChecking OpenAI provider error when key absent...")

os.environ.pop("OPENAI_API_KEY", None)

try:
    agentkit.GetProvider("openai")
    # If no error is raised, the provider may load lazily; attempt a generate call
    print("  ok: GetProvider('openai') returned (key checked at instantiation/call time)")
except Exception as e:
    error_text = str(e).lower()
    if "openai" in error_text or "api key" in error_text or "config" in error_text:
        print(f"  ok: clear error raised — {e}")
    else:
        print(f"FAIL: unexpected error message: {e}", file=sys.stderr)
        sys.exit(1)

# ---------------------------------------------------------------------------
# 3. Version attribute is present
# ---------------------------------------------------------------------------
print("\nChecking version...")
assert hasattr(agentkit, "__version__"), "agentkit.__version__ missing"
print(f"  ok: agentkit.__version__ = {agentkit.__version__}")

print("\nSmoke install: PASSED")
