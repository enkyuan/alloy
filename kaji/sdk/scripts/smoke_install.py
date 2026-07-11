#!/usr/bin/env python3
"""Install smoke test for kaji.

Validates that the installed wheel exports resolve, provider configuration
fails safely without a key, and the canonical no-key docs quickstart runs.

Run after installing the built wheel into a clean venv:
    pip install dist/*.whl
    python scripts/smoke_install.py
"""

from __future__ import annotations

import os
from pathlib import Path
import re
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
    "EffectiveRuntimeLimits",
    "NormalizedProviderError",
    "ProviderConfigError",
    "ProviderError",
    "ToolExecutionContext",
    "UserMessage",
    "SessionManager",
    "normalize_provider_error",
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
except kaji.ProviderConfigError as error:
    print(f"  ok: ProviderConfigError raised: {error}")
except Exception as error:
    print(
        f"FAIL: expected ProviderConfigError, received {type(error).__name__}: {error}",
        file=sys.stderr,
    )
    sys.exit(1)
else:
    print("FAIL: OpenAI provider accepted a missing API key", file=sys.stderr)
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

# ---------------------------------------------------------------------------
# 5. The canonical docs quickstart runs against this installed artifact.
# ---------------------------------------------------------------------------
print("\nRunning installed-package Python quickstart...")

docs_path = Path(__file__).resolve().parents[3] / "docs" / "kaji" / "production-beta.md"
docs = docs_path.read_text()
match = re.search(
    r"<!-- installed-quickstart:python:start -->\s*```python\n(.*?)\n```\s*"
    r"<!-- installed-quickstart:python:end -->",
    docs,
    flags=re.DOTALL,
)
if match is None:
    print("FAIL: canonical Python quickstart block is missing", file=sys.stderr)
    sys.exit(1)
exec(compile(match.group(1), str(docs_path), "exec"), {"__name__": "__main__"})
print("  ok: canonical Python quickstart")

print("\nSmoke install: PASSED")
