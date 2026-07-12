import ast
import tomllib
from pathlib import Path


SDK_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SDK_ROOT.parents[1]
PACKAGE_ROOT = SDK_ROOT / "src"


def _python_files(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("*.py") if "__pycache__" not in path.parts
    )


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _matches(import_name: str, root: str) -> bool:
    return import_name == root or import_name.startswith(f"{root}.")


def test_sdk_does_not_import_service_only_dependencies():
    banned_roots = {
        "kaji_serve",
        "fastapi",
        "sqlalchemy",
        "taskiq",
        "taskiq_redis",
        "websockets",
    }
    violations: list[str] = []

    for path in _python_files(PACKAGE_ROOT):
        rel = path.relative_to(SDK_ROOT)
        for import_name in _imports(path):
            for root in banned_roots:
                if _matches(import_name, root):
                    violations.append(f"{rel}: imports {import_name}")

    assert violations == []


def test_core_package_has_no_infra_or_runtime_dependencies():
    banned_roots = {
        "kaji.infra",
        "kaji.knowledge",
        "kaji.modalities",
        "kaji.runtime",
        "kaji_serve",
        "redis",
    }
    violations: list[str] = []

    for path in _python_files(PACKAGE_ROOT / "core"):
        rel = path.relative_to(SDK_ROOT)
        for import_name in _imports(path):
            for root in banned_roots:
                if _matches(import_name, root):
                    violations.append(f"{rel}: imports {import_name}")

    assert violations == []


def test_redis_client_is_confined_to_realtime_boundary():
    allowed = Path("src/infra/realtime/redis.py")
    violations: list[str] = []

    for path in _python_files(PACKAGE_ROOT):
        rel = path.relative_to(SDK_ROOT)
        if rel == allowed:
            continue
        if any(_matches(import_name, "redis") for import_name in _imports(path)):
            violations.append(str(rel))

    assert violations == []


def test_redis_dependency_is_an_explicit_realtime_extra():
    sdk_pyproject = tomllib.loads((SDK_ROOT / "pyproject.toml").read_text())
    # PEP 621: optional deps live under [project.optional-dependencies].
    optional_deps = sdk_pyproject["project"]["optional-dependencies"]
    realtime_extra = optional_deps["realtime"]

    assert any("redis" in dep for dep in realtime_extra)


def test_provider_sdks_are_explicit_optional_extras():
    pyproject = tomllib.loads((SDK_ROOT / "pyproject.toml").read_text())
    # PEP 621: optional deps live under [project.optional-dependencies].
    extras = pyproject["project"]["optional-dependencies"]

    assert any("openai" in dep for dep in extras["openai"])
    assert any("anthropic" in dep for dep in extras["anthropic"])
    assert any("google-genai" in dep for dep in extras["gemini"])
    provider_deps = " ".join(extras["providers"])
    assert "anthropic" in provider_deps
    assert "google-genai" in provider_deps
    assert "openai" in provider_deps


def test_runtime_tools_do_not_import_legacy_tool_definition() -> None:
    """runtime/tools/ must not depend on the legacy kaji.types.tool module.

    The legacy ToolDefinition ABC lives in kaji/types/tool.py. The current
    runtime tool model uses kaji.runtime.tools.registry.ToolSpec. No file
    under runtime/tools/ may still import the legacy ABC.
    """
    runtime_tools_dir = PACKAGE_ROOT / "runtime" / "tools"
    violations: list[str] = []

    for path in _python_files(runtime_tools_dir):
        rel = path.relative_to(SDK_ROOT)
        if any(_matches(imp, "kaji.types.tool") for imp in _imports(path)):
            violations.append(str(rel))

    assert violations == [], (
        "These runtime/tools files import the legacy ToolDefinition model. "
        "Use ToolSpec from kaji.runtime.tools.registry instead:\n"
        + "\n".join(violations)
    )


def test_sdk_third_party_integration_registry_uses_the_closed_allowlist() -> None:
    """Only reviewed GitHub/Gmail provider bundles may ship."""
    registry_root = PACKAGE_ROOT / "integrations" / "registry"
    known = {"github", "gmail", "gcal"}
    allowed = {"github", "gmail"}
    shipped = (
        {
            path.name
            for path in registry_root.iterdir()
            if path.is_dir() and path.name in known
        }
        if registry_root.exists()
        else set()
    )

    assert shipped == {"github"}
    assert shipped <= allowed
    assert "gcal" not in shipped


def test_sdk_does_not_ship_legacy_tooldefinition_surface() -> None:
    """Legacy ToolDefinition surfaces must not be packaged in the SDK."""
    legacy_paths = [
        PACKAGE_ROOT / "types" / "tool.py",
        PACKAGE_ROOT / "modalities" / "voice" / "legacy",
    ]
    shipped = [
        str(path.relative_to(PACKAGE_ROOT)) for path in legacy_paths if path.exists()
    ]

    assert shipped == [], (
        "Legacy ToolDefinition surfaces are still packaged: " + ", ".join(shipped)
    )


def test_non_integration_tests_do_not_use_redis_event_bus() -> None:
    """Tests that do not opt in to Redis must use InMemoryEventBus.

    A bare ``EventBus()`` call in a test file hits a live Redis connection.
    Tests that need Redis must be in ``tests/integration/`` or contain the
    comment ``# redis-integration`` somewhere in the file.
    """
    tests_root = SDK_ROOT / "tests"
    violations: list[str] = []

    for path in _python_files(tests_root):
        # Skip integration tests — they may legitimately use Redis.
        if "integration" in path.parts:
            continue

        source = path.read_text()

        # Explicit opt-in marker allows Redis bus in that file.
        if "# redis-integration" in source:
            continue

        # Check whether the file imports EventBus (the Redis-backed class).
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == "kaji.infra.events.bus"
            ):
                for alias in node.names:
                    if alias.name == "EventBus":
                        violations.append(str(path.relative_to(SDK_ROOT)))
                        break

    assert violations == [], (
        "These test files import the Redis-backed EventBus outside of an "
        "integration context. Use InMemoryEventBus instead, or add "
        "# redis-integration to the file if Redis is intentionally under test:\n"
        + "\n".join(violations)
    )
