#!/usr/bin/env python3
"""Build, verify, and smoke-test the Python SDK release archives."""

from __future__ import annotations

import argparse
import json
import os
import platform
from pathlib import Path
import re
import shutil
import sys
from tempfile import TemporaryDirectory
import time

from process_runner import (
    PACKAGE_COMMAND_BUDGET,
    PACKAGE_ORCHESTRATOR_BUDGET,
    CommandBudget,
    CommandExitError,
    run_checked,
)


SDK_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SDK_ROOT / "scripts"
import verify_release_artifacts  # noqa: E402

EXPECTED_MOCK_REPLY = "mock"
EXPECTED_ECHO_DESCRIPTION = (
    "Trivial echo integration. Two pure functions, no auth, no network. "
    "Proves the cross-language registry contract."
)
EXPECTED_GITHUB_DESCRIPTION = "Repository-scoped GitHub code, issue, and comment tools."
GITHUB_PROOF_ENVIRONMENT = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PATH",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "TEMP",
        "TMP",
        "TMPDIR",
    }
)
MAX_SAFE_INTEGER = 9_007_199_254_740_991
UV_VERSION = re.compile(r"^uv ([0-9]+\.[0-9]+\.[0-9]+)(?: .*)?$")


def elapsed_milliseconds(started_ns: int, ended_ns: int) -> int:
    elapsed_ns = ended_ns - started_ns
    if elapsed_ns < 0:
        raise ValueError("monotonic clock moved backwards")
    elapsed_ms = (elapsed_ns + 999_999) // 1_000_000
    if elapsed_ms > MAX_SAFE_INTEGER:
        raise ValueError("elapsed milliseconds exceed Number.MAX_SAFE_INTEGER")
    return elapsed_ms


def measured_toolchain() -> dict[str, str]:
    match = UV_VERSION.fullmatch(run_capture(["uv", "--version"]).strip())
    if match is None:
        raise SystemExit("FAIL: uv returned an invalid version")
    return {
        "python": platform.python_version(),
        "uv": match.group(1),
        "node": "not-used",
        "npm": "not-used",
        "bun": "not-used",
        "typescript": "not-used",
    }


def run(command: list[str], *, budget: CommandBudget = PACKAGE_COMMAND_BUDGET) -> None:
    """Run one release command from the SDK root and fail on any error."""
    try:
        run_checked(command, cwd=SDK_ROOT, budget=budget)
    except CommandExitError as error:
        raise SystemExit(
            error.returncode if error.returncode >= 0 else 128 - error.returncode
        ) from None


def run_capture(
    command: list[str],
    *,
    cwd: Path = SDK_ROOT,
    budget: CommandBudget = PACKAGE_COMMAND_BUDGET,
    environment: dict[str, str] | None = None,
    expected_status: int = 0,
    include_stderr: bool = False,
) -> str:
    """Run a bounded command and return the selected UTF-8 output."""

    try:
        completed = run_checked(
            command,
            cwd=cwd,
            budget=budget,
            capture=True,
            env=environment,
            check=False,
        )
    except CommandExitError as error:
        raise SystemExit(
            error.returncode if error.returncode >= 0 else 128 - error.returncode
        ) from None
    if completed.returncode != expected_status:
        raise SystemExit(
            f"FAIL: installed command exited {completed.returncode}, expected {expected_status}"
        )
    output = completed.stdout + (completed.stderr if include_stderr else b"")
    try:
        return output.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise SystemExit("FAIL: installed scaffold emitted non-UTF-8 output") from None


def venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def venv_kaji(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "kaji.exe"
    return venv / "bin" / "kaji"


def artifact_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def github_proof_environment(environment: dict[str, str]) -> dict[str, str]:
    proof = {
        name: environment[name]
        for name in GITHUB_PROOF_ENVIRONMENT
        if name in environment
    }
    proof.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONSAFEPATH": "1",
        }
    )
    return proof


def validate_github_package_proof(output: str, *, runtime: str) -> dict[str, object]:
    try:
        document = json.loads(output)
    except json.JSONDecodeError:
        raise SystemExit("FAIL: GitHub package proof emitted invalid JSON") from None
    expected = {
        "schemaVersion": 1,
        "evidenceClass": "offline_exact_artifact_smoke",
        "integration": "github",
        "runtime": runtime,
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
    if document != expected:
        raise SystemExit("FAIL: GitHub package proof receipt is invalid")
    return document


def install_conflicting_kaji_binary(workdir: Path) -> Path:
    """Install a deterministic conflicting ``kaji`` executable for ownership tests."""

    binary_dir = workdir / "conflicting-kaji-bin"
    binary_dir.mkdir()
    if os.name == "nt":
        binary = binary_dir / "kaji.bat"
        binary.write_text("@echo off\necho kaji (conflicting fixture) 9.9.9\n")
    else:
        binary = binary_dir / "kaji"
        binary.write_text(
            "#!/bin/sh\nprintf '%s\\n' 'kaji (conflicting fixture) 9.9.9'\n"
        )
        binary.chmod(0o755)
    return binary_dir


def installed_registry_root(venv: Path) -> Path:
    candidates = [
        venv / "Lib" / "site-packages" / "kaji" / "integrations" / "registry",
        *venv.glob("lib/python*/site-packages/kaji/integrations/registry"),
    ]
    matches = [candidate.resolve() for candidate in candidates if candidate.is_dir()]
    if len(matches) != 1:
        raise SystemExit(
            "FAIL: installed artifact registry could not be located uniquely"
        )
    try:
        matches[0].relative_to(venv.resolve())
    except ValueError:
        raise SystemExit(
            "FAIL: integration registry was not loaded from the artifact venv"
        ) from None
    return matches[0]


def assert_init_cli_output(output: str, scaffold: Path) -> None:
    expected = (scaffold / "agent.py", scaffold / ".env.example")
    if any(not path.is_file() or str(path) not in output for path in expected):
        raise SystemExit(
            "FAIL: installed init did not report and write its scaffold files"
        )


def assert_echo_cli_output(output: str, destination: Path, registry: Path) -> None:
    copied = destination / "echo.py"
    packaged = registry / "echo" / "echo.py"
    if not copied.is_file() or copied.read_bytes() != packaged.read_bytes():
        raise SystemExit("FAIL: installed add did not copy the packaged Echo asset")
    if f"wrote {copied.resolve()}" not in output:
        raise SystemExit("FAIL: installed add did not report the copied Echo asset")
    if "Installed integration: echo v0.1.0" not in output:
        raise SystemExit("FAIL: installed add did not report the Echo integration")


def assert_experimental_denial(output: str, destination: Path) -> None:
    if "experimental" not in output or "--allow-experimental" not in output:
        raise SystemExit("FAIL: installed add did not explain the experimental opt-in")
    if destination.exists():
        raise SystemExit("FAIL: denied experimental add created its destination")


def assert_github_cli_output(output: str, destination: Path, registry: Path) -> None:
    packaged_root = registry / "github"
    manifest = json.loads((packaged_root / "manifest.json").read_text())
    for name in manifest["files"]:
        copied = destination / name
        packaged = packaged_root / name
        if not copied.is_file() or copied.read_bytes() != packaged.read_bytes():
            raise SystemExit(
                "FAIL: installed add did not copy the packaged GitHub assets"
            )
        if f"wrote {copied.resolve()}" not in output:
            raise SystemExit(
                "FAIL: installed add did not report every copied GitHub asset"
            )
    provenance = json.loads(
        (destination / ".kaji-integration-provenance.json").read_text()
    )
    if (
        provenance.get("integration") != "github"
        or provenance.get("runtime") != "python"
        or not provenance.get("abiSha256")
        or set(provenance.get("files", {})) != set(manifest["files"])
    ):
        raise SystemExit("FAIL: installed GitHub provenance is incomplete")
    if (destination / "LICENSE").read_bytes() != (
        packaged_root / "LICENSE"
    ).read_bytes():
        raise SystemExit("FAIL: installed GitHub license differs from the package")
    if "Installed integration: github v0.1.0" not in output:
        raise SystemExit("FAIL: installed add did not report the GitHub integration")


def assert_list_integrations_output(output: str) -> None:
    try:
        rows = json.loads(output)
    except json.JSONDecodeError:
        raise SystemExit(
            "FAIL: installed list-integrations emitted invalid JSON"
        ) from None
    if not isinstance(rows, list):
        raise SystemExit("FAIL: installed list-integrations emitted a non-list payload")
    by_name = {row.get("name"): row for row in rows if isinstance(row, dict)}
    if by_name.get("echo") != {
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
    }:
        raise SystemExit(
            "FAIL: installed list-integrations omitted the packaged Echo entry"
        )
    github = by_name.get("github")
    if (
        not isinstance(github, dict)
        or github.get("stability") != "experimental"
        or github.get("auth") != {"kind": "env", "provider": None}
        or github.get("next_commands")
        != {
            "python": "python -m kaji.cli add github --allow-experimental",
            "typescript": "bun --no-install -e 'import(\"kaji-sdk/cli\")' -- add github --allow-experimental",
        }
    ):
        raise SystemExit(
            "FAIL: installed list-integrations omitted the packaged GitHub entry"
        )


def assert_scaffold_output(output: str) -> tuple[str, int]:
    lines = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    if lines.get("text") != EXPECTED_MOCK_REPLY:
        raise SystemExit(
            "FAIL: installed scaffold omitted the exact deterministic mock reply"
        )
    if not lines.get("turn_id"):
        raise SystemExit("FAIL: installed scaffold omitted a non-empty turn id")
    try:
        final_sequence = int(lines.get("final_sequence", "0"))
    except ValueError:
        final_sequence = 0
    if final_sequence <= 0:
        raise SystemExit("FAIL: installed scaffold omitted a positive final sequence")
    return EXPECTED_MOCK_REPLY, final_sequence


def assert_matching_scaffold_outputs(
    cold: tuple[str, int], warm: tuple[str, int]
) -> None:
    if cold != warm:
        raise SystemExit("FAIL: cold and warm scaffold outputs differed")


def archive_paths(dist_dir: Path) -> tuple[Path, Path]:
    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise SystemExit(
            f"FAIL: expected exactly one wheel and one sdist under {dist_dir}"
        )
    return wheels[0].resolve(), sdists[0].resolve()


def build_archives(dist_dir: Path) -> tuple[Path, Path]:
    dist_dir = dist_dir if dist_dir.is_absolute() else SDK_ROOT / dist_dir

    run([sys.executable, str(SCRIPTS / "clean_caches.py")])
    shutil.rmtree(SDK_ROOT / "build", ignore_errors=True)
    run(
        [
            "uv",
            "build",
            "--sdist",
            "--wheel",
            "--clear",
            "--out-dir",
            str(dist_dir),
            "--build-constraints",
            "build-requirements.txt",
            "--require-hashes",
        ]
    )
    return archive_paths(dist_dir)


def python_artifact_sha256(
    identity: verify_release_artifacts.VerifiedReleaseArtifacts,
) -> dict[str, str]:
    return {
        identity.python_wheel.name: identity.artifact_sha256[
            identity.python_wheel.name
        ],
        identity.python_sdist.name: identity.artifact_sha256[
            identity.python_sdist.name
        ],
    }


def smoke_archives(
    wheel: Path,
    sdist: Path,
    *,
    identity: verify_release_artifacts.VerifiedReleaseArtifacts | None,
) -> dict[str, object]:
    wheel = wheel.resolve()
    sdist = sdist.resolve()
    if wheel.parent != sdist.parent:
        raise SystemExit("FAIL: wheel and sdist must share one artifact directory")
    if identity is not None and (
        wheel != identity.python_wheel or sdist != identity.python_sdist
    ):
        raise SystemExit("FAIL: supplied Python archives differ from verified identity")
    dist_dir = wheel.parent

    run([sys.executable, str(SCRIPTS / "verify_archives.py"), str(dist_dir)])
    run(
        [
            sys.executable,
            str(SCRIPTS / "test_archive_verifier.py"),
            str(dist_dir),
        ],
        budget=PACKAGE_ORCHESTRATOR_BUDGET,
    )

    temporary_parent = Path(os.environ.get("TMPDIR") or "/tmp")
    with TemporaryDirectory(
        prefix="kaji-sdk-release-smoke.",
        dir=temporary_parent,
    ) as temporary:
        workdir = Path(temporary)
        runtime_requirements = workdir / "runtime-requirements.txt"
        run(
            [
                "uv",
                "export",
                "--locked",
                "--no-dev",
                "--no-emit-project",
                "--extra",
                "openai",
                "--extra",
                "anthropic",
                "--output-file",
                str(runtime_requirements),
            ]
        )

        conflicting_bin = install_conflicting_kaji_binary(workdir)
        github_package_proofs: dict[str, dict[str, object]] = {}
        timings: dict[str, dict[str, int]] = {}

        for package in (wheel, sdist):
            cold_started_ns = time.perf_counter_ns()
            safe_name = re.sub(r"[^a-zA-Z0-9]", "-", package.name)
            venv = workdir / f"venv-{safe_name}"
            run([sys.executable, "-m", "venv", str(venv)])
            python = venv_python(venv)
            run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--require-hashes",
                    "--requirement",
                    "build-requirements.txt",
                ]
            )
            run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--require-hashes",
                    "--requirement",
                    str(runtime_requirements),
                ]
            )
            run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--no-deps",
                    "--no-build-isolation",
                    str(package),
                ]
            )
            run([str(python), str(SCRIPTS / "smoke_install.py")])

            artifact_workdir = workdir / f"artifact-{safe_name}"
            artifact_workdir.mkdir()
            environment = artifact_environment()
            environment["PATH"] = os.pathsep.join(
                [str(conflicting_bin), environment.get("PATH", "")]
            )
            registry = installed_registry_root(venv)
            kaji = str(venv_kaji(venv))

            conflicting_output = run_capture(
                ["kaji", "--help"],
                cwd=artifact_workdir,
                environment=environment,
            )
            if conflicting_output.strip() != "kaji (conflicting fixture) 9.9.9":
                raise SystemExit(
                    "FAIL: conflicting Python CLI fixture was not selected"
                )

            help_output = run_capture(
                [str(python), "-m", "kaji.cli", "--help"],
                cwd=artifact_workdir,
                environment=environment,
            )
            if "kaji (Python distribution kaji-sdk) 0.2.0b1" not in help_output:
                raise SystemExit("FAIL: qualified Python CLI owner/version mismatch")

            scaffold = workdir / f"scaffold-{safe_name}"
            init_output = run_capture(
                [
                    kaji,
                    "--no-color",
                    "init",
                    str(scaffold),
                    "--provider",
                    "mock",
                    "--yes",
                ],
                cwd=artifact_workdir,
                environment=environment,
            )
            assert_init_cli_output(init_output, scaffold)

            integration = workdir / f"integration-{safe_name}"
            add_output = run_capture(
                [kaji, "--no-color", "add", "echo", "--out", str(integration)],
                cwd=artifact_workdir,
                environment=environment,
            )
            assert_echo_cli_output(add_output, integration, registry)

            denied_github = workdir / f"denied-github-{safe_name}"
            denial_output = run_capture(
                [kaji, "--no-color", "add", "github", "--out", str(denied_github)],
                cwd=artifact_workdir,
                environment=environment,
                expected_status=1,
                include_stderr=True,
            )
            assert_experimental_denial(denial_output, denied_github)

            github = workdir / f"owner-{safe_name}" / "owner_integrations" / "github"
            github_output = run_capture(
                [
                    kaji,
                    "--no-color",
                    "add",
                    "github",
                    "--allow-experimental",
                    "--out",
                    str(github),
                ],
                cwd=artifact_workdir,
                environment=environment,
            )
            assert_github_cli_output(github_output, github, registry)
            proof_runner = artifact_workdir / "installed_github_smoke.py"
            shutil.copy2(SCRIPTS / "installed_github_smoke.py", proof_runner)
            proof_output = run_capture(
                [
                    str(python),
                    "-I",
                    str(proof_runner),
                    "--sandbox-root",
                    str(workdir),
                    "--bundle-root",
                    str(github),
                    "--package-root",
                    str(registry.parents[1]),
                ],
                cwd=artifact_workdir,
                environment=github_proof_environment(environment),
            )
            artifact_kind = "wheel" if package == wheel else "sdist"
            github_package_proofs[artifact_kind] = validate_github_package_proof(
                proof_output, runtime="python"
            )
            run_capture(
                [
                    str(python),
                    "-c",
                    "from kaji.integrations.registry.github.github import inspect_integration; "
                    "assert len(inspect_integration().tools()) == 6",
                ],
                cwd=artifact_workdir,
                environment=environment,
            )
            run_capture(
                [
                    str(python),
                    "-c",
                    "import sys; from pathlib import Path; "
                    "sys.path.insert(0, sys.argv[1]); "
                    "import owner_integrations.github.client as owner_client; "
                    "from owner_integrations.github.github import "
                    "GitHubClient, inspect_integration; "
                    "assert GitHubClient.__module__ == "
                    "'owner_integrations.github.client'; "
                    "assert Path(owner_client.__file__).resolve() == "
                    "Path(sys.argv[2]).resolve(); "
                    "assert len(inspect_integration().tools()) == 6",
                    str(github.parents[1]),
                    str(github / "client.py"),
                ],
                cwd=artifact_workdir,
                environment=environment,
            )

            list_output = run_capture(
                [
                    str(python),
                    "-m",
                    "kaji.cli",
                    "--no-color",
                    "list-integrations",
                    "--json",
                ],
                cwd=artifact_workdir,
                environment=environment,
            )
            assert_list_integrations_output(list_output)

            cold_output = run_capture(
                [str(python), "agent.py"],
                cwd=scaffold,
                environment=environment,
            )
            cold_ms = elapsed_milliseconds(cold_started_ns, time.perf_counter_ns())
            cold_result = assert_scaffold_output(cold_output)

            warm_started_ns = time.perf_counter_ns()
            warm_output = run_capture(
                [str(python), "agent.py"],
                cwd=scaffold,
                environment=environment,
            )
            warm_ms = elapsed_milliseconds(warm_started_ns, time.perf_counter_ns())
            warm_result = assert_scaffold_output(warm_output)
            assert_matching_scaffold_outputs(cold_result, warm_result)
            timings[artifact_kind] = {
                "coldSetupToOutputMs": cold_ms,
                "warmRunMs": warm_ms,
            }
            print(
                json.dumps(
                    {
                        "artifact": package.name,
                        "coldSetupToOutputMs": cold_ms,
                        "warmRunMs": warm_ms,
                    },
                    sort_keys=True,
                )
            )

    run([sys.executable, str(SCRIPTS / "verify_archives.py"), str(dist_dir)])
    print("PASS: release smoke verified")

    return {
        "schemaVersion": 1,
        "commit": (
            identity.commit
            if identity is not None
            else os.environ.get("KAJI_RELEASE_COMMIT")
            or os.environ.get("GITHUB_SHA")
            or "uncommitted-local-build"
        ),
        "releaseManifestSha256": (
            identity.manifest_sha256 if identity is not None else None
        ),
        "artifactSha256": (
            python_artifact_sha256(identity)
            if identity is not None
            else {
                wheel.name: verify_release_artifacts.sha256(wheel),
                sdist.name: verify_release_artifacts.sha256(sdist),
            }
        ),
        "runtime": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "executable": str(Path(sys.executable).resolve()),
        },
        "artifacts": {"wheel": str(wheel), "sdist": str(sdist)},
        "githubPackageProofs": github_package_proofs,
        "timings": timings,
        "toolchain": measured_toolchain(),
        "conclusion": "passed",
        "failureCode": None,
    }


def release_smoke(dist_dir: Path) -> dict[str, object]:
    wheel, sdist = build_archives(dist_dir)
    return smoke_archives(wheel, sdist, identity=None)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=Path(os.environ.get("DIST_DIR") or "dist"),
        help="artifact output directory (default: DIST_DIR or dist)",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        help="verified release artifact directory to consume without rebuilding",
    )
    parser.add_argument(
        "--expected-commit",
        default=os.environ.get("EXPECTED_COMMIT"),
        help="exact release commit required with --artifacts-dir",
    )
    parser.add_argument("--output", type=Path, help="write the final JSON receipt")
    return parser.parse_args(argv)


def emit_receipt(receipt: dict[str, object], output: Path | None) -> None:
    encoded = json.dumps(receipt, sort_keys=True)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded + "\n")
    print(encoded)


def failure_receipt(
    *,
    commit: str | None,
    artifacts: Path | None,
    identity: verify_release_artifacts.VerifiedReleaseArtifacts | None,
    failure_code: str,
) -> dict[str, object]:
    root = artifacts.resolve() if artifacts is not None else None
    return {
        "schemaVersion": 1,
        "commit": identity.commit if identity is not None else commit,
        "releaseManifestSha256": (
            identity.manifest_sha256 if identity is not None else None
        ),
        "artifactSha256": (
            python_artifact_sha256(identity) if identity is not None else {}
        ),
        "runtime": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "executable": str(Path(sys.executable).resolve()),
        },
        "artifacts": {
            "wheel": (
                str(root / "kaji_sdk-0.2.0b1-py3-none-any.whl") if root else None
            ),
            "sdist": str(root / "kaji_sdk-0.2.0b1.tar.gz") if root else None,
        },
        "githubPackageProofs": {},
        "conclusion": "failed",
        "failureCode": failure_code,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    identity: verify_release_artifacts.VerifiedReleaseArtifacts | None = None
    stage = "build"
    try:
        if args.artifacts_dir is None:
            receipt = release_smoke(args.dist_dir)
        else:
            stage = "verification"
            if args.expected_commit is None:
                raise SystemExit(
                    "FAIL: --expected-commit or EXPECTED_COMMIT is required with --artifacts-dir"
                )
            identity = verify_release_artifacts.verify(
                args.artifacts_dir, args.expected_commit
            )
            stage = "smoke"
            receipt = smoke_archives(
                identity.python_wheel,
                identity.python_sdist,
                identity=identity,
            )
    except (Exception, SystemExit):
        failure_code = {
            "verification": "artifact_verification_failed",
            "smoke": "python_smoke_failed",
        }.get(stage, "python_build_failed")
        emit_receipt(
            failure_receipt(
                commit=args.expected_commit,
                artifacts=args.artifacts_dir,
                identity=identity,
                failure_code=failure_code,
            ),
            args.output,
        )
        raise
    emit_receipt(receipt, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
