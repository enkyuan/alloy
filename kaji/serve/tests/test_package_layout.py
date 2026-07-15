from pathlib import Path
import tomllib

import kaji_serve


SERVE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVE_ROOT.parents[1]


def test_editable_import_uses_conventional_source_package() -> None:
    assert (
        Path(kaji_serve.__file__).resolve().parent
        == (SERVE_ROOT / "src" / "kaji_serve").resolve()
    )


def test_setuptools_discovers_packages_below_src() -> None:
    project = tomllib.loads((SERVE_ROOT / "pyproject.toml").read_text())
    setuptools = project["tool"]["setuptools"]

    assert setuptools["package-dir"] == {"": "src"}
    assert setuptools["packages"]["find"] == {
        "where": ["src"],
        "include": ["kaji_serve", "kaji_serve.*"],
        "namespaces": False,
    }


def test_service_installs_only_its_provider_and_validation_extras() -> None:
    project = tomllib.loads((SERVE_ROOT / "pyproject.toml").read_text())
    dependencies = project["project"]["dependencies"]

    assert "kaji-sdk[gemini]" in dependencies
    assert not any("kaji-sdk[providers]" in dep for dep in dependencies)
    assert any(dep.startswith("pydantic[email]") for dep in dependencies)


def test_compose_build_context_targets_repository_dockerfile() -> None:
    compose_file = REPO_ROOT / "docker" / "kaji" / "docker-compose.yml"
    compose = compose_file.read_text()
    build_context = (compose_file.parent / "../..").resolve()

    assert "context: ../.." in compose
    assert build_context == REPO_ROOT
    assert (build_context / "Dockerfile").is_file()


def test_reference_service_examples_use_only_canonical_configuration_names() -> None:
    root_env = (REPO_ROOT / ".env.example").read_text()
    docker_env = (REPO_ROOT / "docker" / "kaji" / ".env.example").read_text()
    compose = (REPO_ROOT / "docker" / "kaji" / "docker-compose.yml").read_text()
    service_block = compose.split("\n  kong:", 1)[0]
    auth_block = compose.split("\n  auth:", 1)[1].split("\n  db:", 1)[0]

    for stale in (
        "SUPABASE_URL=",
        "SUPABASE_SERVICE_KEY=",
        "JWT_ALGORITHM=",
        "ACCESS_TOKEN_EXPIRE_MINUTES=",
        "PROJECT_NAME=AgentKit SDK",
    ):
        assert stale not in root_env
    for required in ("JWT_ISSUER=", "JWT_AUDIENCE="):
        assert required in root_env
        assert required in docker_env
    assert "JWT_ISSUER: ${JWT_ISSUER}" in service_block
    assert "JWT_AUDIENCE: ${JWT_AUDIENCE}" in service_block
    assert "GOTRUE_JWT_ISSUER: ${JWT_ISSUER}" in auth_block
    assert "JWT_ALGORITHM:" not in service_block
    assert "ACCESS_TOKEN_EXPIRE_MINUTES:" not in service_block


def test_database_fixture_does_not_restore_removed_pgvector_dependency() -> None:
    fixture = (SERVE_ROOT / "tests" / "conftest.py").read_text()
    assert "CREATE EXTENSION IF NOT EXISTS vector" not in fixture
