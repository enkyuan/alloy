#!/usr/bin/env python3
"""Install smoke test for kaji.

Validates that the installed wheel exports resolve, provider configuration
fails safely without a key, and the canonical no-key docs quickstart runs.

Run after installing the built wheel into a clean venv:
    pip install dist/*.whl
    python scripts/smoke_install.py
"""

from __future__ import annotations

from contextlib import chdir
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
import textwrap


def marked_snippet(path: Path, name: str, language: str) -> str:
    escaped = re.escape(name)

    def marker(edge: str) -> str:
        return rf"(?:<!-- {escaped}:{edge} -->|\{{/\* {escaped}:{edge} \*/\}})"

    matches = re.findall(
        rf"{marker('start')}\s*```{language}\n"
        rf"(.*?)\n[ \t]*```\s*{marker('end')}",
        path.read_text(),
        flags=re.DOTALL,
    )
    if len(matches) != 1:
        print(
            f"FAIL: expected exactly one {name} block in {path}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return textwrap.dedent(matches[0])


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

for protected_name in (
    "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
):
    os.environ.pop(protected_name, None)

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

from kaji.integrations.registry.github.github import inspect_integration  # noqa: E402

github_tools = inspect_integration().tools()
if len(github_tools) != 6:
    print(
        "FAIL: side-effect-free GitHub inspector returned the wrong ABI",
        file=sys.stderr,
    )
    sys.exit(1)
print("  ok: github inspector")

# ---------------------------------------------------------------------------
# 5. The canonical docs quickstart runs against this installed artifact.
# ---------------------------------------------------------------------------
print("\nRunning installed-package Python quickstart...")

docs_path = Path(__file__).resolve().parents[2] / "docs" / "kaji" / "production-beta.md"
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

# ---------------------------------------------------------------------------
# 6. The exact Getting Started no-key block runs against the wheel.
# ---------------------------------------------------------------------------
print("\nRunning installed-package Getting Started no-key guide...")
getting_started_path = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "docs"
    / "content"
    / "getting-started.mdx"
)
getting_started = marked_snippet(
    getting_started_path, "getting-started:no-key:python", "python"
)
exec(
    compile(getting_started, str(getting_started_path), "exec"),
    {"__name__": "__main__"},
)
print("  ok: Getting Started no-key guide")

# ---------------------------------------------------------------------------
# 7. The installed CLI stages Echo and the exact TTHW block runs unchanged.
# ---------------------------------------------------------------------------
print("\nRunning installed-package TTHW Echo guide...")
from kaji.cli import main as cli_main  # noqa: E402

tthw_path = Path(__file__).resolve().parents[2] / "docs" / "kaji" / "tthw-evidence.md"
tthw = marked_snippet(tthw_path, "tthw-echo:python", "python")
with TemporaryDirectory(prefix="kaji-installed-tthw-") as directory:
    root = Path(directory)
    if cli_main(["--no-color", "add", "echo", "--out", str(root / "echo")]) != 0:
        print("FAIL: installed CLI could not stage Echo", file=sys.stderr)
        raise SystemExit(1)
    script = root / "echo_loop.py"
    script.write_text(tthw)
    sys.path.insert(0, str(root))
    try:
        with chdir(root):
            exec(compile(tthw, str(script), "exec"), {"__name__": "__main__"})
    finally:
        sys.path.remove(str(root))
print("  ok: TTHW Echo guide")

print("\nSmoke install: PASSED")
