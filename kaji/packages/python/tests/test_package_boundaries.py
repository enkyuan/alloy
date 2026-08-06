import ast
import subprocess
import sys
import tomllib
from pathlib import Path


SDK_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SDK_ROOT.parents[2]
PACKAGE_ROOT = SDK_ROOT / "src" / "kaji"


def test_python_sdk_owns_the_canonical_kaji_root() -> None:
    """The Python project must not drift back under a nested ``kaji/sdk`` root."""
    pyproject_path = SDK_ROOT / "pyproject.toml"

    assert SDK_ROOT == REPO_ROOT / "kaji" / "packages" / "python"
    assert pyproject_path.is_file()
    assert (PACKAGE_ROOT / "__init__.py").is_file()
    assert not (SDK_ROOT / "sdk").exists()

    pyproject = tomllib.loads(pyproject_path.read_text())
    assert pyproject["project"]["name"] == "kaji-sdk"
    assert pyproject["tool"]["setuptools"]["package-dir"] == {"": "src"}
    assert pyproject["tool"]["setuptools"]["packages"]["find"]["where"] == ["src"]


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


def test_runtime_sessions_owns_session_projection() -> None:
    """Session projection must not drift back into event infrastructure."""
    events_root = PACKAGE_ROOT / "infra" / "events"
    sessions_root = PACKAGE_ROOT / "runtime" / "sessions"
    replay_path = sessions_root / "replay.py"
    projection_names = {
        "ApprovalKey",
        "SessionState",
        "apply_event",
        "replay_session",
    }

    assert replay_path.is_file()
    assert not (events_root / "replay.py").exists()
    assert not (sessions_root / "state.py").exists()

    replay_tree = ast.parse(replay_path.read_text(), filename=str(replay_path))
    runtime_definitions = {
        node.name
        for node in replay_tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert projection_names <= runtime_definitions

    infra_owners: list[str] = []
    infra_runtime_imports: list[str] = []
    for path in _python_files(events_root):
        rel = path.relative_to(SDK_ROOT)
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in tree.body:
            if (
                isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in projection_names
            ):
                infra_owners.append(f"{rel}: defines {node.name}")
        for import_name in _imports(path):
            if _matches(import_name, "kaji.runtime.sessions"):
                infra_runtime_imports.append(f"{rel}: imports {import_name}")

    assert infra_owners == []
    assert infra_runtime_imports == []

    removed_import_roots = {
        "kaji.infra.events.replay",
        "kaji.runtime.sessions.state",
    }
    stale_imports: list[str] = []
    for root in (PACKAGE_ROOT, SDK_ROOT / "tests"):
        for path in _python_files(root):
            rel = path.relative_to(SDK_ROOT)
            for import_name in _imports(path):
                for removed_root in removed_import_roots:
                    if _matches(import_name, removed_root):
                        stale_imports.append(f"{rel}: imports {import_name}")

    assert stale_imports == []


def test_observability_and_provider_import_order_is_acyclic() -> None:
    """Session exports must stay lazy across observability/provider imports."""
    imports = (
        "import kaji.infra.observability\n"
        "from kaji.runtime.providers.errors import ProviderConfigError\n",
        "from kaji.runtime.providers.errors import ProviderConfigError\n"
        "import kaji.infra.observability\n",
        "from kaji.runtime.sessions.replay import SessionState\n"
        "from kaji.runtime.sessions.projector import SessionProjector\n"
        "from kaji.runtime.sessions import EventTimeline\n",
    )
    session_exports = (
        "from kaji.runtime.sessions import (\n"
        "    ApprovalKey, SessionState, apply_event, replay_session,\n"
        ")\n"
    )

    for import_order in imports:
        result = subprocess.run(
            [sys.executable, "-c", import_order + session_exports],
            cwd=SDK_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


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


def test_sdk_settings_do_not_own_service_infrastructure() -> None:
    config = (PACKAGE_ROOT / "core" / "config.py").read_text()
    service_only_settings = {
        "DATABASE_URL",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_KONG_URL",
        "SONIOX_API_KEY",
        "JWT_SECRET",
        "CORS_ALLOW_ORIGINS",
    }

    leaked = sorted(name for name in service_only_settings if name in config)
    assert leaked == [], f"Service-only settings leaked into SDK config: {leaked}"


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


def test_sdk_does_not_configure_host_process_logging() -> None:
    """The embedded SDK must not mutate host logging or create log files."""
    assert not (PACKAGE_ROOT / "core" / "logging.py").exists()


def test_redis_client_is_confined_to_realtime_boundary():
    allowed = Path("src/kaji/infra/realtime/redis.py")
    violations: list[str] = []

    for path in _python_files(PACKAGE_ROOT):
        rel = path.relative_to(SDK_ROOT)
        if rel == allowed:
            continue
        if any(_matches(import_name, "redis") for import_name in _imports(path)):
            violations.append(str(rel))

    assert violations == []


def test_realtime_dependencies_are_explicit_opt_in_extras():
    sdk_pyproject = tomllib.loads((SDK_ROOT / "pyproject.toml").read_text())
    # PEP 621: optional deps live under [project.optional-dependencies].
    core_dependencies = sdk_pyproject["project"]["dependencies"]
    optional_deps = sdk_pyproject["project"]["optional-dependencies"]
    realtime_extra = optional_deps["realtime"]

    assert not any("msgpack" in dep or "redis" in dep for dep in core_dependencies)
    assert not any(dep.startswith("pydantic[") for dep in core_dependencies)
    assert any("msgpack" in dep for dep in realtime_extra)
    assert any("redis" in dep for dep in realtime_extra)


def test_sdk_pytest_collection_is_confined_to_sdk_tests() -> None:
    pyproject = tomllib.loads((SDK_ROOT / "pyproject.toml").read_text())

    assert pyproject["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]


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


def test_runtime_tools_do_not_import_removed_tool_definition() -> None:
    """runtime/tools/ must not depend on the removed kaji.types.tool module.

    The current runtime tool model uses kaji.runtime.tools.registry.ToolSpec.
    No file under runtime/tools/ may import the removed ABC.
    """
    runtime_tools_dir = PACKAGE_ROOT / "runtime" / "tools"
    violations: list[str] = []

    for path in _python_files(runtime_tools_dir):
        rel = path.relative_to(SDK_ROOT)
        if any(_matches(imp, "kaji.types.tool") for imp in _imports(path)):
            violations.append(str(rel))

    assert violations == [], (
        "These runtime/tools files import the removed ToolDefinition model. "
        "Use ToolSpec from kaji.runtime.tools.registry instead:\n"
        + "\n".join(violations)
    )


def test_sdk_integration_registry_uses_the_closed_allowlist() -> None:
    """Only the reviewed Echo and GitHub bundles may ship."""
    registry_root = PACKAGE_ROOT / "integrations" / "registry"
    shipped = {
        path.name
        for path in registry_root.iterdir()
        if path.is_dir() and path.name != "__pycache__"
    }

    assert shipped == {"echo", "github", "gmail"}


def test_sdk_does_not_ship_removed_tooldefinition_surface() -> None:
    """Removed ToolDefinition surfaces must not be packaged in the SDK."""
    removed_paths = [
        PACKAGE_ROOT / "types" / "tool.py",
    ]
    shipped = [
        str(path.relative_to(PACKAGE_ROOT)) for path in removed_paths if path.exists()
    ]

    assert shipped == [], (
        "Removed ToolDefinition surfaces are still packaged: " + ", ".join(shipped)
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
