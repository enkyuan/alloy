import json
from pathlib import Path
import re
import tomllib

from kaji.core.config import Settings as SDKSettings
import kaji_serve
from kaji_serve.config import Settings as ServeSettings


SERVE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVE_ROOT.parents[2]


def _env_names(contents: str) -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", contents, flags=re.MULTILINE))


def test_editable_import_uses_flattened_source_package() -> None:
    assert Path(kaji_serve.__file__).resolve().parent == (SERVE_ROOT / "src").resolve()


def test_setuptools_maps_flattened_src_to_kaji_serve() -> None:
    project = tomllib.loads((SERVE_ROOT / "pyproject.toml").read_text())
    setuptools = project["tool"]["setuptools"]

    assert setuptools["package-dir"] == {"kaji_serve": "src"}
    assert "kaji_serve" in setuptools["packages"]
    assert not (SERVE_ROOT / "src" / "kaji_serve").exists()


def test_service_installs_only_its_provider_and_validation_extras() -> None:
    project = tomllib.loads((SERVE_ROOT / "pyproject.toml").read_text())
    dependencies = project["project"]["dependencies"]

    assert "kaji[gemini]" in dependencies
    assert not any("kaji[providers]" in dep for dep in dependencies)
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


def test_root_env_documents_every_kaji_setting() -> None:
    root_env = (REPO_ROOT / ".env.example").read_text()

    assert set(SDKSettings.model_fields) | set(
        ServeSettings.model_fields
    ) <= _env_names(root_env)


def test_root_exposes_pinned_dotenvx_workflows() -> None:
    package = json.loads((REPO_ROOT / "package.json").read_text())

    assert package["devDependencies"]["@dotenvx/dotenvx"] == "2.9.0"
    assert package["scripts"]["env:example"] == "dotenvx genexample"
    assert package["scripts"]["dev:kaji-serve"].startswith(
        "dotenvx run --ignore=MISSING_ENV_FILE -- "
    )


def test_docker_build_context_excludes_dotenvx_secrets() -> None:
    ignore_rules = {
        line.strip()
        for line in (REPO_ROOT / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert {".env*", "**/.env*"} <= ignore_rules


def test_docker_env_matches_compose_and_has_no_legacy_duplicate() -> None:
    docker_root = REPO_ROOT / "docker" / "kaji"
    docker_env = (docker_root / ".env.example").read_text()
    compose = (docker_root / "docker-compose.yml").read_text()
    compose_names = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", compose))

    assert compose_names == _env_names(docker_env)
    assert not (docker_root / "supabase" / ".env.example").exists()
    for stale in (
        "AgentKit",
        "TOKEN_ENCRYPTION_KEY=",
        "LOG_LEVEL=",
        "SUPABASE_PUBLIC_URL=",
        "STUDIO_DEFAULT_ORGANIZATION=",
        "DASHBOARD_USERNAME=",
        "PGRST_DB_SCHEMAS=",
        "IMGPROXY_ENABLE_WEBP_DETECTION=",
        "LOGFLARE_PUBLIC_ACCESS_TOKEN=",
        "DOCKER_SOCKET_LOCATION=",
    ):
        assert stale not in docker_env


def test_database_fixture_does_not_restore_removed_pgvector_dependency() -> None:
    fixture = (SERVE_ROOT / "tests" / "conftest.py").read_text()
    assert "CREATE EXTENSION IF NOT EXISTS vector" not in fixture
