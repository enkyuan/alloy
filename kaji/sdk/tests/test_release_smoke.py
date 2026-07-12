import importlib.util
import re
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest


SDK_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SDK_ROOT.parents[1]


def _load_script(name: str) -> ModuleType:
    path = SDK_ROOT / "scripts" / name
    scripts = str(path.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location(f"test_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_release_smoke_preserves_build_verify_install_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script("release_smoke.py")
    sdk_root = tmp_path / "sdk"
    scripts = sdk_root / "scripts"
    dist = sdk_root / "dist"
    scripts.mkdir(parents=True)
    dist.mkdir()
    wheel = dist / "kaji.whl"
    sdist = dist / "kaji.tar.gz"
    wheel.touch()
    sdist.touch()
    commands: list[list[str]] = []

    monkeypatch.setattr(module, "SDK_ROOT", sdk_root)
    monkeypatch.setattr(module, "SCRIPTS", scripts)
    monkeypatch.setattr(
        module,
        "run",
        lambda command, **_kwargs: commands.append(command),
    )
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    module.release_smoke(Path("dist"))

    assert commands[0] == [sys.executable, str(scripts / "clean_caches.py")]
    assert commands[1][:4] == ["uv", "build", "--sdist", "--wheel"]
    verify = [
        index
        for index, command in enumerate(commands)
        if str(scripts / "verify_archives.py") in command
    ]
    archive = next(
        index
        for index, command in enumerate(commands)
        if str(scripts / "test_archive_verifier.py") in command
    )
    installed_smokes = [
        index
        for index, command in enumerate(commands)
        if str(scripts / "smoke_install.py") in command
    ]

    assert len(verify) == 2
    assert len(installed_smokes) == 2
    assert verify[0] < archive < installed_smokes[0] < installed_smokes[1] < verify[1]
    assert any(command[:2] == ["uv", "export"] for command in commands)
    assert (
        sum(
            len(command) >= 3 and command[1:3] == ["-m", "venv"] for command in commands
        )
        == 2
    )
    assert all(isinstance(command, list) for command in commands)


def test_release_smoke_normalizes_signal_exit_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script("release_smoke.py")

    def fail(*_args: object, **_kwargs: object) -> None:
        raise module.CommandExitError(-15)

    monkeypatch.setattr(module, "run_checked", fail)

    with pytest.raises(SystemExit, match="143"):
        module.run(["tool"])


def test_installed_smoke_requires_the_missing_key_failure() -> None:
    script = (SDK_ROOT / "scripts" / "smoke_install.py").read_text()

    assert 'kaji.get_provider("openai")' in script
    assert "except kaji.ProviderConfigError as error:" in script
    assert "FAIL: OpenAI provider accepted a missing API key" in script
    assert "key checked at instantiation/call time" not in script


def test_archive_verifier_compares_all_packaged_contract_bytes() -> None:
    script = (SDK_ROOT / "scripts" / "verify_archives.py").read_text()

    assert "argparse.ArgumentParser" in script
    assert "def load_archives(dist_dir: Path)" in script
    assert "def verify_archives()" in script
    assert "tomllib.loads" in script
    assert "canonical_contracts" in script
    assert "packaged_contracts" in script
    assert "wheel contract set mismatch" in script
    assert "differs from canonical bytes" in script
    assert 'entry.get("manifest")' in script
    assert "sdist" in script
    assert "LICENSE" in script
    assert "expected_source_bytes" in script
    assert "forbidden_artifacts" in script
    for expected in (
        "checked_archive_path",
        "checked_zip_members",
        "checked_tar_members",
        "duplicate member path",
        "symlink member",
        "link member",
        "non-regular member",
        "non-file member",
        "unexpected executable payload",
        "unexpected payloads in wheel",
        "unexpected payloads in sdist",
        "wheel runtime source differs from checkout",
        "sdist runtime source differs from checkout",
        "validate_core_metadata",
        "validate_wheel_metadata",
        "validate_entry_points",
        "validate_record",
        "RECORD hash mismatch",
        "RECORD size mismatch",
        "Requires-Dist differs from pyproject",
        "setup.cfg is not the canonical",
        "SOURCES.txt differs from expected source manifest",
        "MAX_ARCHIVE_MEMBER_BYTES",
        "MAX_ARCHIVE_UNCOMPRESSED_BYTES",
        "generated metadata exceeds size limit",
    ):
        assert expected in script


def test_adversarial_archive_verifier_covers_generated_metadata_and_size_bombs() -> (
    None
):
    script = (SDK_ROOT / "scripts" / "test_archive_verifier.py").read_text()

    for expected in (
        "mutate_metadata",
        "mutate_entry_point",
        "mutate_recorded_payload",
        "mutate_oversized_metadata",
        "mutate_setup_cfg",
        "mutate_sdist_metadata",
        "archive verifier rejected all adversarial metadata cases",
    ):
        assert expected in script


def test_python_release_metadata_and_versions_are_self_contained() -> None:
    pyproject = tomllib.loads((SDK_ROOT / "pyproject.toml").read_text())
    source = (SDK_ROOT / "src" / "__init__.py").read_text()
    version = re.search(r'^__version__ = "([^"]+)"$', source, re.MULTILINE)

    assert version is not None
    assert pyproject["project"]["version"] == version.group(1) == "0.2.0b1"
    assert pyproject["project"]["license"] == {"file": "LICENSE"}
    assert (SDK_ROOT / "LICENSE").read_bytes() == (REPO_ROOT / "LICENSE").read_bytes()
    assert (SDK_ROOT / "MANIFEST.in").is_file()
    build_requirements = (SDK_ROOT / "build-requirements.txt").read_text()
    assert set(pyproject["build-system"]["requires"]) == {
        "setuptools==83.0.0",
        "editables==0.6",
    }

    dev = set(pyproject["dependency-groups"]["dev"])
    assert "twine==6.2.0" in dev
    assert "pip-audit==2.10.1" in dev
    assert "setuptools==83.0.0" in build_requirements
    assert "editables==0.6" in build_requirements
    assert build_requirements.count("--hash=sha256:") == 4

    setup_action = (
        REPO_ROOT / ".github/actions/setup-python-uv/action.yml"
    ).read_text()
    assert 'version: "0.11.25"' in setup_action


def test_clean_caches_removes_project_caches_without_touching_venv(
    tmp_path: Path,
) -> None:
    module = _load_script("clean_caches.py")
    generated = [
        tmp_path / "src" / "package" / "__pycache__" / "module.pyc",
        tmp_path / "tests" / "case.pyc",
        tmp_path / "scripts" / "__pycache__" / "tool.pyo",
        tmp_path / ".pytest_cache" / "state",
        tmp_path / ".ruff_cache" / "state",
        tmp_path / "htmlcov" / "index.html",
        tmp_path / ".coverage",
    ]
    preserved = tmp_path / ".venv" / "lib" / "keep.pyc"
    for path in [*generated, preserved]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    module.clean_caches(tmp_path)

    assert all(not path.exists() for path in generated)
    assert preserved.is_file()


def test_release_docs_reference_release_smoke() -> None:
    combined = "\n".join(
        [
            (SDK_ROOT / "README.md").read_text(),
            (REPO_ROOT / "docs" / "MVP.md").read_text(),
        ]
    )

    assert "scripts/release_smoke.py" in combined
    assert "scripts/clean_caches.py" in combined


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


def test_parity_contract_package_is_declared() -> None:
    pyproject = tomllib.loads((SDK_ROOT / "pyproject.toml").read_text())
    packages = set(pyproject["tool"]["setuptools"]["packages"])
    package_dir = pyproject["tool"]["setuptools"]["package-dir"]
    package_data = pyproject["tool"]["setuptools"]["package-data"]

    assert "kaji.contracts.parity" in packages
    assert "kaji.contracts.integrations" in packages
    assert package_dir["kaji.contracts.parity"] == "src/contracts/parity"
    assert package_dir["kaji.contracts.integrations"] == "src/contracts/integrations"
    assert package_data["kaji.contracts.parity"] == ["*.json"]
    assert package_data["kaji.contracts.integrations"] == ["*.json"]
