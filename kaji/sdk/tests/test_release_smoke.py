import re
import tomllib
from pathlib import Path


SDK_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SDK_ROOT.parents[1]


def test_release_smoke_invokes_wheel_verifier_and_install_smoke() -> None:
    script = (SDK_ROOT / "scripts" / "release_smoke.sh").read_text()

    assert "uv build --sdist --wheel" in script
    assert "--build-constraints build-requirements.txt --require-hashes" in script
    assert "scripts/clean_generated.sh" in script
    assert "rm -rf build" in script
    assert 'PYTHON_CMD=("$PYTHON")' in script
    assert "PYTHON_CMD=(uv run --no-sync python)" in script
    assert "PYTHON_CMD=(python3)" in script
    assert script.count('bash scripts/verify_wheel.sh "$DIST_DIR"') == 2
    assert '"${PYTHON_CMD[@]}" scripts/test_archive_verifier.py "$DIST_DIR"' in script
    assert "scripts/smoke_install.py" in script
    assert "uv run --no-sync python -m venv" in script
    assert "python3 -m venv" not in script
    assert "uv export --locked --no-dev --no-emit-project" in script
    assert "--extra openai --extra anthropic" in script
    assert "pip install --require-hashes" in script
    assert "--requirement build-requirements.txt" in script
    assert '--requirement "$WORKDIR/runtime-requirements.txt"' in script
    assert "pip install --no-deps --no-build-isolation" in script
    assert script.rindex('bash scripts/verify_wheel.sh "$DIST_DIR"') > script.index(
        '"$venv/bin/python" scripts/smoke_install.py'
    )
    assert "PASS: release smoke verified" in script


def test_installed_smoke_requires_the_missing_key_failure() -> None:
    script = (SDK_ROOT / "scripts" / "smoke_install.py").read_text()

    assert 'kaji.get_provider("openai")' in script
    assert "except kaji.ProviderConfigError as error:" in script
    assert "FAIL: OpenAI provider accepted a missing API key" in script
    assert "key checked at instantiation/call time" not in script


def test_wheel_verifier_compares_all_packaged_contract_bytes() -> None:
    script = (SDK_ROOT / "scripts" / "verify_wheel.sh").read_text()

    assert 'PYTHON_CMD=("$PYTHON")' in script
    assert "PYTHON_CMD=(uv run --no-sync python)" in script
    assert "PYTHON_CMD=(python3)" in script
    assert "\"${PYTHON_CMD[@]}\" - <<'PY'" in script
    assert "canonical_contracts" in script
    assert "packaged_contracts" in script
    assert "wheel contract set mismatch" in script
    assert "differs from canonical bytes" in script
    assert 'entry.get("manifest")' in script
    assert "SDIST" in script
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


def test_clean_generated_removes_project_caches_without_touching_venv() -> None:
    script = (SDK_ROOT / "scripts" / "clean_generated.sh").read_text()

    assert "find src tests" in script
    assert "__pycache__" in script
    assert "*.pyc" in script
    assert "*.pyo" in script
    assert ".pytest_cache" in script
    assert ".ruff_cache" in script
    assert ".venv" not in script


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
