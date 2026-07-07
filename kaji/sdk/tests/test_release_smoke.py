from pathlib import Path
import tomllib


SDK_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SDK_ROOT.parents[1]


def test_release_smoke_invokes_wheel_verifier_and_install_smoke() -> None:
    script = (SDK_ROOT / "scripts" / "release_smoke.sh").read_text()

    assert "uv build --wheel" in script
    assert "scripts/clean_generated.sh" in script
    assert "rm -rf build" in script
    assert "scripts/verify_wheel.sh" in script
    assert "scripts/smoke_install.py" in script
    assert "PASS: release smoke verified" in script


def test_clean_generated_is_scoped_to_src_and_tests() -> None:
    script = (SDK_ROOT / "scripts" / "clean_generated.sh").read_text()

    assert "find src tests" in script
    assert "__pycache__" in script
    assert "*.pyc" in script
    assert "*.pyo" in script


def test_release_docs_reference_release_smoke() -> None:
    combined = "\n".join(
        [
            (SDK_ROOT / "README.md").read_text(),
            (REPO_ROOT / "docs" / "MVP.md").read_text(),
        ]
    )

    assert "scripts/release_smoke.sh" in combined
    assert "scripts/clean_generated.sh" in combined


def test_registry_namespace_packages_are_declared() -> None:
    pyproject = tomllib.loads((SDK_ROOT / "pyproject.toml").read_text())
    packages = set(pyproject["tool"]["setuptools"]["packages"])
    package_dir = pyproject["tool"]["setuptools"]["package-dir"]

    assert "kaji.integrations.registry" in packages
    assert "kaji.integrations.registry.echo" in packages
    assert package_dir["kaji.integrations.registry"] == "src/integrations/registry"
    assert (
        package_dir["kaji.integrations.registry.echo"]
        == "src/integrations/registry/echo"
    )
