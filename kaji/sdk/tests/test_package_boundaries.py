import ast
import tomllib
from pathlib import Path


SDK_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SDK_ROOT.parents[1]
PACKAGE_ROOT = SDK_ROOT / "kaji"


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
    allowed = Path("kaji/infra/realtime/redis.py")
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
    redis_dep = sdk_pyproject["tool"]["poetry"]["dependencies"]["redis"]
    realtime_extra = sdk_pyproject["tool"]["poetry"]["extras"]["realtime"]

    assert redis_dep["optional"] is True
    assert "redis" in realtime_extra

    serve_pyproject = tomllib.loads(
        (REPO_ROOT / "kaji" / "serve" / "pyproject.toml").read_text()
    )
    serve_kaji_dep = serve_pyproject["tool"]["poetry"]["dependencies"]["kaji"]
    assert "realtime" in serve_kaji_dep["extras"]
    assert "providers" in serve_kaji_dep["extras"]


def test_provider_sdks_are_explicit_optional_extras():
    pyproject = tomllib.loads((SDK_ROOT / "pyproject.toml").read_text())
    dependencies = pyproject["tool"]["poetry"]["dependencies"]
    extras = pyproject["tool"]["poetry"]["extras"]

    for name in ["anthropic", "google-genai", "openai", "rich"]:
        assert dependencies[name]["optional"] is True

    assert extras["openai"] == ["openai"]
    assert extras["anthropic"] == ["anthropic"]
    assert extras["gemini"] == ["google-genai"]
    assert set(extras["providers"]) == {"anthropic", "google-genai", "openai"}


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
