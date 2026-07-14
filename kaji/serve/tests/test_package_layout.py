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
