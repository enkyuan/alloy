#!/usr/bin/env python3
"""Run Kaji's local beta gates or the full offline release rehearsal."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
SDK = ROOT / "kaji" / "sdk"
TYPESCRIPT = ROOT / "kaji" / "ts"
SCRIPTS = ROOT / "kaji" / "scripts"


class GateFailure(RuntimeError):
    """A gate failed with a process-compatible exit status."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"gate exited with status {status}")


def section(label: str) -> None:
    print(f"\n==> {label}", flush=True)


def fail(message: str, *, status: int = 1) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise GateFailure(status)


def process_status(status: int) -> int:
    return status if status >= 0 else 128 - status


def run_checked(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
) -> None:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            check=False,
        )
    except FileNotFoundError as error:
        fail(f"command not found: {error.filename}", status=127)
    if completed.returncode != 0:
        raise GateFailure(process_status(completed.returncode))


def run_in_dir(
    label: str,
    directory: Path,
    command: list[str],
    environment: dict[str, str],
) -> None:
    section(label)
    run_checked(command, cwd=directory, environment=environment)


def require_command(command: str, reason: str, environment: dict[str, str]) -> None:
    if shutil.which(command, path=environment.get("PATH")) is None:
        fail(f"{command} is required for {reason}")


def release_environment() -> dict[str, str]:
    environment = os.environ.copy()
    home = environment.get("HOME", "")
    existing_path = environment.get("PATH", "")
    environment["PATH"] = os.pathsep.join(
        [
            f"{home}/.local/bin",
            f"{home}/.bun/bin",
            "/opt/homebrew/bin",
            "/usr/local/bin",
            existing_path,
        ]
    )
    environment["UV_SYSTEM_CERTS"] = environment.get("UV_SYSTEM_CERTS") or "true"
    return environment


def run_no_key_live_skip(environment: dict[str, str]) -> None:
    section("No-key live gate skip hygiene")
    child_environment = environment.copy()
    for key in (
        "OPENAI_API_KEY",
        "KAJI_LIVE_OPENAI_MODEL",
        "KAJI_REQUIRE_LIVE_KEYS",
    ):
        child_environment.pop(key, None)
    run_checked(
        [sys.executable, str(SCRIPTS / "live_openai_tool_loop.py")],
        cwd=ROOT,
        environment=child_environment,
    )


def run_required_key_failure(environment: dict[str, str]) -> None:
    section("Required-key live gate failure hygiene")
    child_environment = environment.copy()
    child_environment.pop("OPENAI_API_KEY", None)
    child_environment.pop("KAJI_LIVE_OPENAI_MODEL", None)
    child_environment["KAJI_REQUIRE_LIVE_KEYS"] = "1"
    try:
        completed = subprocess.run(
            [sys.executable, str(SCRIPTS / "live_openai_tool_loop.py")],
            cwd=ROOT,
            env=child_environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            text=True,
        )
    except FileNotFoundError as error:
        fail(f"command not found: {error.filename}", status=127)
    if completed.returncode != 2:
        fail(
            "required OpenAI key check returned "
            f"{process_status(completed.returncode)} instead of 2"
        )
    print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")


def run_common_checks(environment: dict[str, str]) -> None:
    run_no_key_live_skip(environment)
    run_required_key_failure(environment)
    run_in_dir(
        "ast-grep structural audit",
        ROOT,
        ["bun", "run", "audit:ast-grep"],
        environment,
    )
    run_in_dir(
        "Cross-SDK behavioral parity",
        ROOT,
        [
            "uv",
            "run",
            "--project",
            "kaji/sdk",
            "python",
            "kaji/scripts/check_sdk_parity.py",
        ],
        environment,
    )
    run_in_dir(
        "Shared beta contract",
        ROOT,
        [
            "uv",
            "run",
            "--project",
            "kaji/sdk",
            "python",
            "kaji/scripts/check_beta_contract.py",
        ],
        environment,
    )
    run_in_dir(
        "Packaged beta contract synchronization",
        ROOT,
        [
            "uv",
            "run",
            "--project",
            "kaji/sdk",
            "python",
            "kaji/scripts/sync_beta_contracts.py",
            "--check",
        ],
        environment,
    )
    run_in_dir(
        "Integration contract synchronization",
        ROOT,
        [
            "uv",
            "run",
            "--project",
            "kaji/sdk",
            "python",
            "kaji/scripts/sync_integration_contracts.py",
            "--check",
        ],
        environment,
    )
    run_in_dir(
        "Deterministic complexity and quick benchmark smoke",
        ROOT,
        [sys.executable, str(SCRIPTS / "run_beta_benchmarks.py"), "--quick"],
        environment,
    )

    run_in_dir(
        "TypeScript unit tests",
        TYPESCRIPT,
        ["bun", "run", "test"],
        environment,
    )
    run_in_dir(
        "TypeScript typecheck",
        TYPESCRIPT,
        ["bun", "run", "typecheck"],
        environment,
    )
    run_in_dir(
        "TypeScript build",
        TYPESCRIPT,
        ["bun", "run", "build"],
        environment,
    )
    run_in_dir(
        "TypeScript package smoke",
        TYPESCRIPT,
        ["bun", "run", "package:smoke"],
        environment,
    )

    run_in_dir(
        "Python unit tests",
        SDK,
        ["uv", "run", "pytest", "-m", "not integration"],
        environment,
    )
    run_in_dir(
        "Python typecheck",
        SDK,
        [
            "uv",
            "run",
            "python",
            "scripts/typecheck_ty.py",
            "--output-format",
            "concise",
        ],
        environment,
    )
    run_in_dir(
        "Python lint",
        SDK,
        ["uv", "run", "ruff", "check", "src", "tests"],
        environment,
    )
    run_in_dir(
        "Python artifact smoke",
        SDK,
        ["uv", "run", "python", "scripts/release_smoke.py"],
        environment,
    )


def run_release_checks(environment: dict[str, str]) -> None:
    artifacts = ROOT / ".artifacts" / "kaji-release"
    temporary_parent = environment.get("TMPDIR") or None
    with tempfile.TemporaryDirectory(
        prefix="kaji-release.", dir=temporary_parent
    ) as temporary:
        release_temporary = Path(temporary)
        shutil.rmtree(artifacts, ignore_errors=True)
        artifacts.mkdir(parents=True)

        run_in_dir(
            "Python format",
            SDK,
            ["uv", "run", "ruff", "format", "--check", "src", "tests"],
            environment,
        )
        run_in_dir(
            "Python lint (release)",
            SDK,
            ["uv", "run", "ruff", "check", "src", "tests"],
            environment,
        )
        run_in_dir(
            "Python typecheck (release)",
            SDK,
            [
                "uv",
                "run",
                "python",
                "scripts/typecheck_ty.py",
                "--output-format",
                "concise",
            ],
            environment,
        )
        run_in_dir(
            "Python tests (release)",
            SDK,
            ["uv", "run", "pytest"],
            environment,
        )
        run_in_dir(
            "Python release artifacts",
            SDK,
            ["uv", "run", "python", "scripts/release_smoke.py"],
            environment,
        )
        distributions = sorted(
            path for path in (SDK / "dist").iterdir() if not path.name.startswith(".")
        )
        if not distributions:
            fail("Python release produced no distributions")
        run_in_dir(
            "Python metadata",
            SDK,
            [
                "uv",
                "run",
                "twine",
                "check",
                *(str(path) for path in distributions),
            ],
            environment,
        )

        for label, command in (
            ("TypeScript format", ["bun", "run", "format:check"]),
            ("TypeScript lint", ["bun", "run", "lint"]),
            ("TypeScript typecheck (release)", ["bun", "run", "typecheck"]),
            (
                "TypeScript registry typecheck",
                ["bun", "run", "typecheck:registry"],
            ),
            (
                "TypeScript registry validation",
                ["bun", "run", "validate:registry"],
            ),
            (
                "TypeScript integration validation",
                ["bun", "run", "check:integrations"],
            ),
            ("TypeScript tests (release)", ["bun", "run", "test"]),
            ("TypeScript build (release)", ["bun", "run", "build"]),
            (
                "TypeScript package smoke (release)",
                ["bun", "run", "package:smoke"],
            ),
            ("TypeScript publint", ["bun", "x", "publint"]),
        ):
            run_in_dir(label, TYPESCRIPT, command, environment)

        attw_environment = environment.copy()
        attw_environment["npm_config_cache"] = str(release_temporary / "attw-npm-cache")
        run_in_dir(
            "TypeScript type artifact audit",
            TYPESCRIPT,
            ["bun", "x", "attw", "--pack", "."],
            attw_environment,
        )

        section("Locked production dependency audits")
        requirements = release_temporary / "requirements.txt"
        run_checked(
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
                str(requirements),
            ],
            cwd=SDK,
            environment=environment,
        )
        run_checked(
            [
                "uv",
                "run",
                "pip-audit",
                "--require-hashes",
                "--requirement",
                str(requirements),
            ],
            cwd=SDK,
            environment=environment,
        )
        run_checked(
            [
                "uv",
                "run",
                "pip-audit",
                "--require-hashes",
                "--requirement",
                "build-requirements.txt",
            ],
            cwd=SDK,
            environment=environment,
        )
        run_checked(
            ["bun", "audit", "--production"],
            cwd=TYPESCRIPT,
            environment=environment,
        )

        section("Construct release npm tarball")
        npm_environment = environment.copy()
        npm_environment["npm_config_cache"] = str(release_temporary / "npm-cache")
        run_checked(
            [
                "npm",
                "pack",
                "--ignore-scripts",
                "--pack-destination",
                str(artifacts),
                str(TYPESCRIPT),
            ],
            cwd=ROOT,
            environment=npm_environment,
        )
        tarballs = sorted(artifacts.glob("*.tgz"))
        if len(tarballs) != 1:
            fail(f"expected exactly one npm tarball, found {len(tarballs)}")
        tarball = tarballs[0]

        run_in_dir(
            "Exact TypeScript artifact contents",
            ROOT,
            [
                "uv",
                "run",
                "--project",
                "kaji/sdk",
                "python",
                "kaji/scripts/verify_npm_package.py",
                str(tarball),
            ],
            environment,
        )
        run_in_dir(
            "Exact TypeScript artifact install smoke",
            TYPESCRIPT,
            ["bun", "scripts/smoke-installed.mts", str(tarball)],
            environment,
        )
        run_in_dir(
            "Reverify final Python artifacts",
            SDK,
            ["uv", "run", "python", "scripts/verify_wheel.py", "dist"],
            environment,
        )

        commit = environment.get("KAJI_RELEASE_COMMIT") or environment.get("GITHUB_SHA")
        metadata_command = [
            "uv",
            "run",
            "--project",
            "kaji/sdk",
            "python",
            "kaji/scripts/verify_package_metadata.py",
        ]
        if commit:
            metadata_command.extend(
                [
                    "--release",
                    "--commit",
                    commit,
                    "--artifacts-dir",
                    str(artifacts),
                ]
            )
            label = "Package metadata and checksum manifest"
        else:
            metadata_command.extend(["--artifacts-dir", str(artifacts)])
            label = "Local package metadata and checksum manifest"
        run_in_dir(label, ROOT, metadata_command, environment)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    environment = release_environment()
    try:
        require_command("bun", "TypeScript SDK release gates", environment)
        require_command("node", "installed npm package proof", environment)
        require_command("npm", "npm artifact construction", environment)
        require_command("uv", "Python SDK release gates", environment)
        run_common_checks(environment)
        if args.release:
            run_release_checks(environment)

        if not args.release:
            section("Protected keyed provider proof")
            if environment.get("KAJI_RUN_KEYED_LIVE") == "1":
                run_checked(
                    [sys.executable, str(SCRIPTS / "live_provider_proof.py")],
                    cwd=ROOT,
                    environment=environment,
                )
            else:
                print("SKIP: not requested; no keyed provider evidence is claimed.")
    except GateFailure as error:
        return error.status

    print()
    if args.release:
        print(
            "PASS: offline release rehearsal; "
            "keyed/provider/publish readiness NOT claimed"
        )
    else:
        print("PASS: Kaji beta checks completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
