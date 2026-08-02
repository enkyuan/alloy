import importlib.util
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from types import MappingProxyType, ModuleType, SimpleNamespace

import pytest


SDK_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SDK_ROOT.parent

GITHUB_PACKAGE_PROOF = {
    "schemaVersion": 1,
    "evidenceClass": "offline_exact_artifact_smoke",
    "integration": "github",
    "runtime": "python",
    "network": "scripted",
    "liveProvider": False,
    "contractVersion": "1.0.0",
    "caseCount": 23,
    "toolCount": 6,
    "approvalDeniedBeforeCredentialAccess": True,
    "mutationRetries": 0,
    "unknownMutationPreserved": True,
    "sourceRuntimeDetected": False,
    "conclusion": "passed",
    "failureCode": None,
}


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
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script("release_smoke.py")
    sdk_root = tmp_path / "sdk"
    scripts = sdk_root / "scripts"
    dist = sdk_root / "dist"
    scripts.mkdir(parents=True)
    (scripts / "installed_github_smoke.py").write_text("# fixture\n")
    dist.mkdir()
    wheel = dist / "kaji.whl"
    sdist = dist / "kaji.tar.gz"
    wheel.touch()
    sdist.touch()
    commands: list[list[str]] = []
    receipt_path = tmp_path / "receipt.json"

    monkeypatch.setattr(module, "SDK_ROOT", sdk_root)
    monkeypatch.setattr(module, "SCRIPTS", scripts)
    monkeypatch.setattr(
        module,
        "run",
        lambda command, **_kwargs: commands.append(command),
    )

    def fake_run_capture(command: list[str], **_kwargs: object) -> str:
        commands.append(command)
        if command == ["uv", "--version"]:
            return "uv 0.11.25 (Homebrew 2026-07-25)\n"
        if any("installed_github_smoke.py" in part for part in command):
            return json.dumps(GITHUB_PACKAGE_PROOF)
        if command == ["kaji", "--help"]:
            return "kaji (conflicting fixture) 9.9.9\n"
        if command[1:4] == ["-m", "kaji.cli", "--help"]:
            return "kaji (Python distribution kaji-sdk) 0.2.0b1\n"
        return "text=mock\nturn_id=turn-1\nfinal_sequence=1\n"

    monkeypatch.setattr(module, "run_capture", fake_run_capture)
    monkeypatch.setattr(module, "installed_registry_root", lambda _venv: tmp_path)
    monkeypatch.setattr(module, "assert_init_cli_output", lambda *_args: None)
    monkeypatch.setattr(module, "assert_echo_cli_output", lambda *_args: None)
    monkeypatch.setattr(module, "assert_github_cli_output", lambda *_args: None)
    monkeypatch.setattr(module, "assert_list_integrations_output", lambda *_args: None)
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    assert (
        module.main(
            [
                "--dist-dir",
                str(dist),
                "--output",
                str(receipt_path),
            ]
        )
        == 0
    )
    receipt = json.loads(receipt_path.read_text())

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
    installed_github_smokes = [
        command
        for command in commands
        if any("installed_github_smoke.py" in part for part in command)
    ]
    assert len(installed_github_smokes) == 2
    assert all(command[1] == "-I" for command in installed_github_smokes)
    assert all("--sandbox-root" in command for command in installed_github_smokes)
    assert all("--bundle-root" in command for command in installed_github_smokes)
    assert all("--package-root" in command for command in installed_github_smokes)
    assert receipt["githubPackageProofs"] == {
        "sdist": GITHUB_PACKAGE_PROOF,
        "wheel": GITHUB_PACKAGE_PROOF,
    }
    assert all(isinstance(command, list) for command in commands)
    assert sum(command[1:3] == ["--no-color", "init"] for command in commands) == 2
    assert (
        sum(command[1:4] == ["--no-color", "add", "echo"] for command in commands) == 2
    )
    assert (
        sum(command[1:4] == ["--no-color", "add", "github"] for command in commands)
        == 2
    )
    assert (
        sum(command[1:4] == ["-m", "kaji.cli", "--help"] for command in commands) == 2
    )
    assert sum(command == ["kaji", "--help"] for command in commands) == 2
    assert (
        sum(
            command[1:5] == ["-m", "kaji.cli", "--no-color", "list-integrations"]
            and command[-1] == "--json"
            for command in commands
        )
        == 2
    )
    timings = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if '"artifact"' in line and '"coldSetupToOutputMs"' in line
    ]
    assert len(timings) == 2
    assert all(
        type(timing[field]) is int
        for timing in timings
        for field in ("coldSetupToOutputMs", "warmRunMs")
    )
    assert set(receipt["timings"]) == {"wheel", "sdist"}
    assert set(receipt["timings"]["wheel"]) == {
        "coldSetupToOutputMs",
        "warmRunMs",
    }
    assert set(receipt["timings"]["sdist"]) == {
        "coldSetupToOutputMs",
        "warmRunMs",
    }
    assert all(
        type(value) is int and value >= 0
        for timing in receipt["timings"].values()
        for value in timing.values()
    )
    assert receipt["conclusion"] == "passed"
    assert receipt["toolchain"] == {
        "python": module.platform.python_version(),
        "uv": "0.11.25",
        "node": "not-used",
        "npm": "not-used",
        "bun": "not-used",
        "typescript": "not-used",
    }


@pytest.mark.parametrize(
    ("elapsed_ns", "expected_ms"),
    [
        (0, 0),
        (1, 1),
        (999_999, 1),
        (1_000_000, 1),
        (1_000_001, 2),
    ],
)
def test_elapsed_milliseconds_ceil_normalizes_nanoseconds(
    elapsed_ns: int, expected_ms: int
) -> None:
    module = _load_script("release_smoke.py")

    elapsed_ms = module.elapsed_milliseconds(10, 10 + elapsed_ns)

    assert elapsed_ms == expected_ms
    assert type(elapsed_ms) is int


def test_elapsed_milliseconds_rejects_negative_monotonic_delta() -> None:
    module = _load_script("release_smoke.py")

    with pytest.raises(ValueError, match="monotonic clock moved backwards"):
        module.elapsed_milliseconds(11, 10)


def test_elapsed_milliseconds_bounds_safe_integer_output() -> None:
    module = _load_script("release_smoke.py")
    max_safe = 9_007_199_254_740_991

    assert module.elapsed_milliseconds(0, max_safe * 1_000_000) == max_safe
    with pytest.raises(
        ValueError, match="elapsed milliseconds exceed Number.MAX_SAFE_INTEGER"
    ):
        module.elapsed_milliseconds(0, (max_safe + 1) * 1_000_000)


def test_run_capture_can_assert_an_expected_stderr_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script("release_smoke.py")
    monkeypatch.setattr(
        module,
        "run_checked",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stdout=b"",
            stderr=b"experimental opt-in required\n",
        ),
    )

    assert (
        module.run_capture(
            ["kaji", "add", "github"],
            cwd=tmp_path,
            expected_status=1,
            include_stderr=True,
        )
        == "experimental opt-in required\n"
    )


def test_github_package_proof_receipt_is_closed_and_fail_closed() -> None:
    module = _load_script("release_smoke.py")

    assert (
        module.validate_github_package_proof(
            json.dumps(GITHUB_PACKAGE_PROOF), runtime="python"
        )
        == GITHUB_PACKAGE_PROOF
    )

    mutants = []
    for key, value in (
        ("liveProvider", True),
        ("caseCount", 22),
        ("toolCount", 5),
        ("mutationRetries", 1),
        ("sourceRuntimeDetected", True),
        ("conclusion", "failed"),
    ):
        mutant = dict(GITHUB_PACKAGE_PROOF)
        mutant[key] = value
        mutants.append(mutant)
    extra = dict(GITHUB_PACKAGE_PROOF)
    extra["repository"] = "private/repository"
    mutants.append(extra)

    for mutant in mutants:
        with pytest.raises(SystemExit, match="GitHub package proof"):
            module.validate_github_package_proof(json.dumps(mutant), runtime="python")


@pytest.mark.asyncio
async def test_installed_github_proof_uses_current_approval_handler_contract() -> None:
    module = _load_script("installed_github_smoke.py")
    bundle = SDK_ROOT / "src/kaji/integrations/registry/github"
    client, integration = module._load_copied_modules(bundle)

    assert await module._approval_precedes_credentials(
        client, integration, "octo/widgets"
    )


@pytest.mark.asyncio
async def test_installed_github_proof_closes_factory_owned_transport() -> None:
    module = _load_script("installed_github_smoke.py")
    bundle = SDK_ROOT / "src/kaji/integrations/registry/github"
    _, integration = module._load_copied_modules(bundle)

    assert await module._factory_closes_owned_transport(integration)


def test_release_smoke_consumes_verified_archives_without_building(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script("release_smoke.py")
    artifacts = tmp_path / "release"
    artifacts.mkdir()
    wheel = artifacts / "kaji_sdk-0.2.0b1-py3-none-any.whl"
    sdist = artifacts / "kaji_sdk-0.2.0b1.tar.gz"
    npm = artifacts / "kaji-sdk-0.2.0-beta.10.tgz"
    for path in (wheel, sdist, npm):
        path.write_bytes(path.name.encode())
    commit = "a" * 40
    hashes = MappingProxyType(
        {path.name: f"hash-{path.name}" for path in (wheel, sdist, npm)}
    )
    identity = SimpleNamespace(
        root=artifacts.resolve(),
        commit=commit,
        manifest_sha256="manifest-hash",
        python_wheel=wheel.resolve(),
        python_sdist=sdist.resolve(),
        npm_tarball=npm.resolve(),
        artifact_sha256=hashes,
    )
    verified: list[tuple[Path, str]] = []
    smoked: list[tuple[Path, Path, object]] = []
    receipt_path = tmp_path / "receipt.json"

    monkeypatch.setattr(
        module.verify_release_artifacts,
        "verify",
        lambda root, expected: verified.append((root, expected)) or identity,
    )
    monkeypatch.setattr(
        module,
        "build_archives",
        lambda _dist: pytest.fail("consume-only mode must not build archives"),
    )

    def fake_smoke(
        supplied_wheel: Path,
        supplied_sdist: Path,
        *,
        identity: object,
    ) -> dict[str, object]:
        smoked.append((supplied_wheel, supplied_sdist, identity))
        return {
            "schemaVersion": 1,
            "commit": commit,
            "releaseManifestSha256": "manifest-hash",
            "artifactSha256": dict(hashes),
            "runtime": {"implementation": "CPython", "version": "3.test"},
            "artifacts": {
                "wheel": str(wheel.resolve()),
                "sdist": str(sdist.resolve()),
            },
            "conclusion": "passed",
            "failureCode": None,
        }

    monkeypatch.setattr(module, "smoke_archives", fake_smoke)

    assert (
        module.main(
            [
                "--artifacts-dir",
                str(artifacts),
                "--expected-commit",
                commit,
                "--output",
                str(receipt_path),
            ]
        )
        == 0
    )

    assert verified == [(artifacts, commit)]
    assert smoked == [(wheel.resolve(), sdist.resolve(), identity)]
    receipt = json.loads(receipt_path.read_text())
    assert receipt == json.loads(capsys.readouterr().out.splitlines()[-1])
    assert receipt["commit"] == commit
    assert receipt["releaseManifestSha256"] == "manifest-hash"
    assert receipt["artifactSha256"] == dict(hashes)
    assert receipt["runtime"]["version"] == "3.test"
    assert receipt["conclusion"] == "passed"


def test_python_compatibility_identity_excludes_unconsumed_npm_hash(
    tmp_path: Path,
) -> None:
    module = _load_script("release_smoke.py")
    wheel = tmp_path / "kaji_sdk-0.2.0b1-py3-none-any.whl"
    sdist = tmp_path / "kaji_sdk-0.2.0b1.tar.gz"
    npm = tmp_path / "kaji-sdk-0.2.0-beta.10.tgz"
    hashes = MappingProxyType(
        {
            wheel.name: "a" * 64,
            sdist.name: "b" * 64,
            npm.name: "c" * 64,
        }
    )
    identity = module.verify_release_artifacts.VerifiedReleaseArtifacts(
        root=tmp_path,
        commit="d" * 40,
        manifest_sha256="e" * 64,
        python_wheel=wheel,
        python_sdist=sdist,
        npm_tarball=npm,
        artifact_sha256=hashes,
    )

    assert module.python_artifact_sha256(identity) == {
        wheel.name: "a" * 64,
        sdist.name: "b" * 64,
    }


def test_release_smoke_consume_failure_overwrites_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script("release_smoke.py")
    artifacts = tmp_path / "release"
    artifacts.mkdir()
    receipt_path = tmp_path / "receipt.json"

    def reject(_root: Path, _expected: str) -> None:
        raise SystemExit("FAIL: artifact file set mismatch")

    monkeypatch.setattr(module.verify_release_artifacts, "verify", reject)

    with pytest.raises(SystemExit, match="artifact file set mismatch"):
        module.main(
            [
                "--artifacts-dir",
                str(artifacts),
                "--expected-commit",
                "a" * 40,
                "--output",
                str(receipt_path),
            ]
        )

    receipt = json.loads(receipt_path.read_text())
    assert receipt["commit"] == "a" * 40
    assert receipt["conclusion"] == "failed"
    assert receipt["failureCode"] == "artifact_verification_failed"
    assert "timings" not in receipt
    assert "toolchain" not in receipt


def test_release_smoke_failure_overwrites_partial_timings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script("release_smoke.py")
    artifacts = tmp_path / "release"
    artifacts.mkdir()
    wheel = artifacts / "kaji_sdk-0.2.0b1-py3-none-any.whl"
    sdist = artifacts / "kaji_sdk-0.2.0b1.tar.gz"
    npm = artifacts / "kaji-sdk-0.2.0-beta.10.tgz"
    for path in (wheel, sdist, npm):
        path.touch()
    identity = SimpleNamespace(
        root=artifacts.resolve(),
        commit="a" * 40,
        manifest_sha256="b" * 64,
        python_wheel=wheel.resolve(),
        python_sdist=sdist.resolve(),
        npm_tarball=npm.resolve(),
        artifact_sha256=MappingProxyType(
            {
                wheel.name: "c" * 64,
                sdist.name: "d" * 64,
                npm.name: "e" * 64,
            }
        ),
    )
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(
        json.dumps(
            {
                "timings": {
                    "wheel": {
                        "coldSetupToOutputMs": 1,
                        "warmRunMs": 2,
                    }
                }
            }
        )
    )

    monkeypatch.setattr(
        module.verify_release_artifacts,
        "verify",
        lambda _root, _expected: identity,
    )
    monkeypatch.setattr(
        module,
        "smoke_archives",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            SystemExit("FAIL: sdist smoke failed")
        ),
    )

    with pytest.raises(SystemExit, match="sdist smoke failed"):
        module.main(
            [
                "--artifacts-dir",
                str(artifacts),
                "--expected-commit",
                identity.commit,
                "--output",
                str(receipt_path),
            ]
        )

    receipt = json.loads(receipt_path.read_text())
    assert receipt["conclusion"] == "failed"
    assert receipt["failureCode"] == "python_smoke_failed"
    assert "timings" not in receipt
    assert "toolchain" not in receipt


def test_release_smoke_asserts_all_installed_stable_cli_results(
    tmp_path: Path,
) -> None:
    module = _load_script("release_smoke.py")
    scaffold = tmp_path / "scaffold"
    scaffold.mkdir()
    for name in ("agent.py", ".env.example"):
        (scaffold / name).write_text(name)
    module.assert_init_cli_output(
        f"{scaffold / 'agent.py'}\n{scaffold / '.env.example'}\n",
        scaffold,
    )

    registry = tmp_path / "installed-registry"
    destination = tmp_path / "echo-copy"
    (registry / "echo").mkdir(parents=True)
    destination.mkdir()
    body = "packaged echo.py\n"
    (registry / "echo" / "echo.py").write_text(body)
    copied = destination / "echo.py"
    copied.write_text(body)
    output = [f"  wrote {copied.resolve()}"]
    output.append("Installed integration: echo v0.1.0")
    module.assert_echo_cli_output("\n".join(output), destination, registry)

    module.assert_list_integrations_output(
        json.dumps(
            [
                {
                    "name": "echo",
                    "version": "0.1.0",
                    "stability": "beta",
                    "runtimes": ["python", "typescript"],
                    "auth": {"kind": "none", "provider": None},
                    "experimental_opt_in_required": False,
                    "next_commands": {
                        "python": "python -m kaji.cli add echo",
                        "typescript": "bun --no-install -e 'import(\"kaji-sdk/cli\")' -- add echo",
                    },
                },
                {
                    "name": "github",
                    "stability": "beta",
                    "auth": {"kind": "env", "provider": None},
                    "next_commands": {
                        "python": "python -m kaji.cli add github",
                        "typescript": "bun --no-install -e 'import(\"kaji-sdk/cli\")' -- add github",
                    },
                },
            ]
        )
    )

    (destination / "echo.py").write_text("checkout source must not be accepted")
    with pytest.raises(SystemExit, match="packaged Echo asset"):
        module.assert_echo_cli_output("\n".join(output), destination, registry)
    with pytest.raises(SystemExit, match="emitted invalid JSON"):
        module.assert_list_integrations_output("No integrations available.")


def test_release_smoke_runs_the_installed_no_key_scaffold_cold_and_warm() -> None:
    script = (SDK_ROOT / "scripts" / "release_smoke.py").read_text()
    tiers = json.loads(
        (REPO_ROOT / "kaji" / "contracts" / "feature-tiers-v1.json").read_text()
    )

    assert tiers["cliCommands"]["python"]["stable"] == [
        "add",
        "connect",
        "disconnect",
        "init",
        "list-integrations",
    ]

    for required in (
        '"init",',
        '"--provider",',
        '"mock",',
        '"--yes",',
        'lines.get("text")',
        'lines.get("turn_id")',
        'lines.get("final_sequence", "0")',
        'EXPECTED_MOCK_REPLY = "mock"',
        "cold_result = assert_scaffold_output(cold_output)",
        "warm_result = assert_scaffold_output(warm_output)",
        "assert_matching_scaffold_outputs(cold_result, warm_result)",
        "coldSetupToOutputMs",
        "warmRunMs",
        '"add", "echo", "--out"',
        '"add", "github", "--out"',
        "assert_github_cli_output(github_output, github, registry)",
        "from kaji.integrations.registry.github.github import inspect_integration; ",
        '"assert len(inspect_integration().tools()) == 6"',
        "import owner_integrations.github.client as owner_client; ",
        "from owner_integrations.github.github import ",
        "GitHubClient, inspect_integration; ",
        "'owner_integrations.github.client'",
        "Path(owner_client.__file__).resolve() == ",
        'str(github / "client.py")',
        '"list-integrations"',
        "assert_init_cli_output(init_output, scaffold)",
        "assert_echo_cli_output(add_output, integration, registry)",
        "assert_list_integrations_output(list_output)",
        'environment.pop("PYTHONPATH", None)',
        'environment.pop("PYTHONHOME", None)',
        'environment["PYTHONNOUSERSITE"] = "1"',
        "install_conflicting_kaji_binary(workdir)",
        '["kaji", "--help"]',
        '[str(python), "-m", "kaji.cli", "--help"]',
        '"kaji (Python distribution kaji-sdk) 0.2.0b1"',
        "copied.read_bytes() != packaged.read_bytes()",
    ):
        assert required in script


def test_release_smoke_rejects_wrong_or_nondeterministic_mock_output() -> None:
    module = _load_script("release_smoke.py")
    valid = "text=mock\nturn_id=turn-1\nfinal_sequence=1\n"

    assert module.assert_scaffold_output(valid) == ("mock", 1)
    with pytest.raises(SystemExit, match="exact deterministic mock reply"):
        module.assert_scaffold_output(
            "text=plausible but wrong\nturn_id=turn-1\nfinal_sequence=1\n"
        )
    with pytest.raises(SystemExit, match="cold and warm scaffold outputs differed"):
        module.assert_matching_scaffold_outputs(("mock", 1), ("mock", 2))


def test_python_package_metadata_has_canonical_project_urls() -> None:
    pyproject = tomllib.loads((SDK_ROOT / "pyproject.toml").read_text())

    assert pyproject["project"]["urls"] == {
        "Documentation": "https://github.com/enkyuan/alloy/blob/main/docs/kaji/README.md",
        "Issues": "https://github.com/enkyuan/alloy/issues",
        "Repository": "https://github.com/enkyuan/alloy",
    }


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
        "Project-URL differs from pyproject",
        "setup.cfg is not the canonical",
        "SOURCES.txt differs from expected source manifest",
        "MAX_ARCHIVE_MEMBER_BYTES",
        "MAX_ARCHIVE_UNCOMPRESSED_BYTES",
        "generated metadata exceeds size limit",
    ):
        assert expected in script


def test_archive_verifier_allows_only_declared_github_owner_fixture() -> None:
    module = _load_script("verify_archives.py")
    manifest_path = "kaji/integrations/registry/github/manifest.json"
    owner_fixture = "kaji/integrations/registry/github/tests/test_github.py"
    arbitrary_test = "kaji/integrations/registry/github/tests/test_extra.py"
    manifest: dict[str, object] = {
        "files": [
            "github.py",
            "tests/test_github.py",
            "tests/test_extra.py",
        ]
    }

    def declared_paths(document: dict[str, object]) -> set[str]:
        payloads = {manifest_path: json.dumps(document).encode()}
        return module.manifest_declared_owner_fixture_paths(
            {manifest_path, owner_fixture, arbitrary_test},
            payloads.__getitem__,
        )

    allowed = declared_paths(manifest)

    assert allowed == {owner_fixture}
    assert module.forbidden_artifacts(
        {owner_fixture, arbitrary_test},
        allowed_test_paths=allowed,
    ) == [arbitrary_test]

    manifest["files"] = ["github.py", "tests/test_extra.py"]
    assert declared_paths(manifest) == set()
    assert module.forbidden_artifacts({owner_fixture}) == [owner_fixture]


def test_adversarial_archive_verifier_covers_generated_metadata_and_size_bombs() -> (
    None
):
    script = (SDK_ROOT / "scripts" / "test_archive_verifier.py").read_text()

    for expected in (
        "mutate_metadata",
        "mutate_wheel_project_url_extra",
        "mutate_entry_point",
        "mutate_recorded_payload",
        "mutate_oversized_metadata",
        "mutate_wheel_package_test",
        "mutate_setup_cfg",
        "mutate_sdist_metadata",
        "mutate_sdist_project_url_mismatch",
        "mutate_sdist_package_test",
        "archive verifier rejected all adversarial metadata cases",
    ):
        assert expected in script


def test_python_release_metadata_and_versions_are_self_contained() -> None:
    pyproject = tomllib.loads((SDK_ROOT / "pyproject.toml").read_text())
    source = (SDK_ROOT / "src" / "kaji" / "__init__.py").read_text()
    version = re.search(r'^__version__ = "([^"]+)"$', source, re.MULTILINE)

    assert version is not None
    assert pyproject["project"]["version"] == version.group(1) == "0.2.0b1"
    assert pyproject["project"]["license"] == "FSL-1.1-ALv2"
    assert pyproject["project"]["license-files"] == ["LICENSE"]
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


def test_package_readmes_describe_fsl_license_accurately() -> None:
    expected = (
        "Kaji is source-available under the "
        "[Functional Source License 1.1, ALv2 Future License]"
        "(https://spdx.org/licenses/FSL-1.1-ALv2.html). "
        "It permits internal commercial use, modification, and redistribution for "
        "permitted purposes, but excludes competing commercial products and services; "
        "each version becomes Apache-2.0 after two years. "
        "FSL is not an OSI-approved open-source license."
    )

    for path in (SDK_ROOT / "README.md", SDK_ROOT / "ts" / "README.md"):
        readme = " ".join(path.read_text().split())
        assert expected in readme
        assert "redistribution are not permitted" not in readme
        assert "commercial use is not permitted" not in readme


def test_npm_verifier_derives_expected_files_from_package_allowlist(
    tmp_path: Path,
) -> None:
    module = _load_script("verify_npm_package.py")
    ts_root = tmp_path / "ts"
    package = {
        "files": [
            "LICENSE",
            "dist",
            "registry/index.json",
            "registry/github/client.ts",
        ]
    }
    files = {
        "LICENSE": "license\n",
        "README.md": "readme\n",
        "package.json": json.dumps(package),
        "dist/index.js": "export {};\n",
        "registry/index.json": "{}\n",
        "registry/github/client.ts": "export {};\n",
        "registry/github/private-fixture.py": "# must not ship\n",
    }
    for relative, payload in files.items():
        path = ts_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload)

    actual_package, expected = module.expected_package_bytes(ts_root)

    assert actual_package == package
    assert set(expected) == {
        "LICENSE",
        "README.md",
        "package.json",
        "dist/index.js",
        "registry/index.json",
        "registry/github/client.ts",
    }


def test_clean_caches_removes_project_caches_without_touching_venv(
    tmp_path: Path,
) -> None:
    module = _load_script("clean_caches.py")
    generated = [
        tmp_path / "src" / "package" / "__pycache__" / "module.pyc",
        tmp_path / "tests" / "case.pyc",
        tmp_path / "scripts" / "__pycache__" / "tool.pyo",
        tmp_path / "benchmarks" / "__pycache__" / "runtime.pyc",
        tmp_path / ".pytest_cache" / "state",
        tmp_path / ".ruff_cache" / "state",
        tmp_path / "htmlcov" / "index.html",
        tmp_path / "logs" / "kaji.log",
        tmp_path / "kaji.egg-info" / "SOURCES.txt",
        tmp_path / "src" / "kaji_sdk.egg-info" / "SOURCES.txt",
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
    setuptools = pyproject["tool"]["setuptools"]
    discovery = setuptools["packages"]["find"]

    assert setuptools["package-dir"] == {"": "src"}
    assert discovery == {
        "where": ["src"],
        "include": ["kaji", "kaji.*"],
        "namespaces": False,
    }
    for relative in ("registry", "registry/echo", "registry/github"):
        assert (
            SDK_ROOT / "src" / "kaji" / "integrations" / relative / "__init__.py"
        ).is_file()


def test_parity_contract_package_is_declared() -> None:
    pyproject = tomllib.loads((SDK_ROOT / "pyproject.toml").read_text())
    package_data = pyproject["tool"]["setuptools"]["package-data"]

    assert (SDK_ROOT / "src/kaji/contracts/parity/__init__.py").is_file()
    assert (SDK_ROOT / "src/kaji/contracts/integrations/__init__.py").is_file()
    assert package_data["kaji.contracts.parity"] == ["*.json"]
    assert package_data["kaji.contracts.integrations"] == ["*.json"]


def test_provider_cost_contract_package_is_declared() -> None:
    pyproject = tomllib.loads((SDK_ROOT / "pyproject.toml").read_text())
    package_data = pyproject["tool"]["setuptools"]["package-data"]

    assert (SDK_ROOT / "src/kaji/contracts/providers/__init__.py").is_file()
    assert package_data["kaji.contracts.providers"] == ["*.json"]


def test_cli_and_release_contract_data_are_declared() -> None:
    pyproject = tomllib.loads((SDK_ROOT / "pyproject.toml").read_text())
    package_data = pyproject["tool"]["setuptools"]["package-data"]

    assert "cli/*.json" in package_data["kaji.contracts"]
    assert "release/*.json" in package_data["kaji.contracts"]


def test_repo_root_editable_import_resolves_sdk_package() -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, kaji; print(json.dumps({'file': kaji.__file__}))",
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    imported = Path(json.loads(result.stdout)["file"]).resolve()
    assert imported == SDK_ROOT / "src" / "kaji" / "__init__.py"


def test_github_exact_artifact_proof_is_source_only_and_contract_is_packaged() -> None:
    source_tools = (
        SDK_ROOT / "scripts" / "live_github_proof.py",
        SDK_ROOT / "scripts" / "github_proof_cleanup.py",
        SDK_ROOT / "scripts" / "github_proof_control.py",
        SDK_ROOT / "scripts" / "installed_github_live.py",
        REPO_ROOT / "kaji" / "ts" / "scripts" / "installed-github-live.mts",
    )
    assert all(path.is_file() for path in source_tools)
    assert all(not path.is_relative_to(SDK_ROOT / "src") for path in source_tools)

    canonical = (
        REPO_ROOT / "kaji" / "contracts" / "release" / "github-proof-v1.schema.json"
    ).read_bytes()
    assert (
        SDK_ROOT
        / "src"
        / "kaji"
        / "contracts"
        / "release"
        / "github-proof-v1.schema.json"
    ).read_bytes() == canonical
    assert (
        REPO_ROOT
        / "kaji"
        / "ts"
        / "contracts"
        / "release"
        / "github-proof-v1.schema.json"
    ).read_bytes() == canonical
