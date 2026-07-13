#!/usr/bin/env python3
"""Run Kaji's local beta gates or the full offline release rehearsal."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys
import tempfile

from process_runner import (
    CommandBudget,
    CommandError,
    CompletedCommand,
    CommandExitError,
    CommandOutputLimitError,
    CommandInterruptedError,
    CommandStartError,
    CommandTimeoutError,
    LOCAL_COMMAND_BUDGET,
    LOCAL_ORCHESTRATOR_BUDGET,
    PACKAGE_COMMAND_BUDGET,
    PACKAGE_ORCHESTRATOR_BUDGET,
    PROVIDER_ORCHESTRATOR_BUDGET,
    RELEASE_COMMAND_BUDGET,
    run_checked as run_process,
)


ROOT = Path(__file__).resolve().parents[2]
SDK = ROOT / "kaji" / "sdk"
TYPESCRIPT = ROOT / "kaji" / "ts"
SCRIPTS = ROOT / "kaji" / "scripts"


class GateFailure(RuntimeError):
    """A gate failed with a process-compatible exit status."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"gate exited with status {status}")


@dataclass(frozen=True, slots=True)
class Gate:
    label: str
    directory: Path
    command: tuple[str, ...]
    budget: CommandBudget = LOCAL_COMMAND_BUDGET


def offline_command(*command: str) -> tuple[str, ...]:
    return (sys.executable, str(SCRIPTS / "offline_gate.py"), "--", *command)


TS_COMMON_GATES = (
    Gate("TypeScript typecheck", TYPESCRIPT, ("bun", "run", "typecheck")),
    Gate("TypeScript build", TYPESCRIPT, ("bun", "run", "build")),
    Gate(
        "TypeScript unit tests (offline)",
        TYPESCRIPT,
        offline_command("bun", "run", "test"),
    ),
    Gate(
        "TypeScript package smoke",
        TYPESCRIPT,
        ("bun", "run", "package:smoke"),
        PACKAGE_ORCHESTRATOR_BUDGET,
    ),
)


TS_RELEASE_GATES = (
    Gate("TypeScript format", TYPESCRIPT, ("bun", "run", "format:check")),
    Gate("TypeScript lint", TYPESCRIPT, ("bun", "run", "lint")),
    Gate(
        "TypeScript typecheck (release)",
        TYPESCRIPT,
        ("bun", "run", "typecheck"),
    ),
    Gate(
        "TypeScript registry typecheck",
        TYPESCRIPT,
        ("bun", "run", "typecheck:registry"),
    ),
    Gate(
        "TypeScript registry validation",
        TYPESCRIPT,
        ("bun", "run", "validate:registry"),
    ),
    Gate(
        "TypeScript integration validation",
        TYPESCRIPT,
        ("bun", "run", "check:integrations"),
    ),
    Gate("TypeScript build (release)", TYPESCRIPT, ("bun", "run", "build")),
    Gate(
        "TypeScript tests (release, offline)",
        TYPESCRIPT,
        offline_command("bun", "run", "test"),
    ),
    Gate(
        "TypeScript quickstart (release)",
        TYPESCRIPT,
        offline_command("bun", "run", "test:quickstart"),
    ),
    Gate(
        "TypeScript package smoke (release)",
        TYPESCRIPT,
        ("bun", "run", "package:smoke"),
        PACKAGE_ORCHESTRATOR_BUDGET,
    ),
    Gate("TypeScript publint", TYPESCRIPT, ("bun", "x", "publint")),
)


def common_gates() -> tuple[Gate, ...]:
    return TS_COMMON_GATES


def release_gates() -> tuple[Gate, ...]:
    return TS_RELEASE_GATES


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
    budget: CommandBudget = LOCAL_COMMAND_BUDGET,
    capture: bool = False,
    check: bool = True,
) -> CompletedCommand:
    try:
        return run_process(
            command,
            cwd=cwd,
            env=environment,
            budget=budget,
            capture=capture,
            check=check,
        )
    except CommandExitError as error:
        raise GateFailure(process_status(error.returncode)) from None
    except CommandStartError:
        fail("release command could not be started", status=127)
    except CommandTimeoutError:
        fail("release command exceeded its time budget")
    except CommandOutputLimitError as error:
        fail(f"release command exceeded its {error.stream} capture budget")
    except CommandInterruptedError as error:
        raise GateFailure(128 + error.signum) from None
    except CommandError as error:
        fail(f"release command failed: {error}")


def run_in_dir(
    label: str,
    directory: Path,
    command: list[str],
    environment: dict[str, str],
    budget: CommandBudget = LOCAL_COMMAND_BUDGET,
) -> None:
    section(label)
    run_checked(command, cwd=directory, environment=environment, budget=budget)


def run_gates(gates: tuple[Gate, ...], environment: dict[str, str]) -> None:
    for gate in gates:
        run_in_dir(
            gate.label,
            gate.directory,
            list(gate.command),
            environment,
            gate.budget,
        )


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
        [sys.executable, str(SCRIPTS / "verify_openai_loop.py")],
        cwd=ROOT,
        environment=child_environment,
        budget=PROVIDER_ORCHESTRATOR_BUDGET,
    )


def run_required_key_failure(environment: dict[str, str]) -> None:
    section("Required-key live gate failure hygiene")
    child_environment = environment.copy()
    child_environment.pop("OPENAI_API_KEY", None)
    child_environment.pop("KAJI_LIVE_OPENAI_MODEL", None)
    child_environment["KAJI_REQUIRE_LIVE_KEYS"] = "1"
    completed = run_checked(
        [sys.executable, str(SCRIPTS / "verify_openai_loop.py")],
        cwd=ROOT,
        environment=child_environment,
        budget=PROVIDER_ORCHESTRATOR_BUDGET,
        capture=True,
        check=False,
    )
    if completed.returncode != 2:
        fail(
            "required OpenAI key check returned "
            f"{process_status(completed.returncode)} instead of 2"
        )
    output = (completed.stdout + completed.stderr).decode("utf-8", errors="replace")
    print(output, end="" if output.endswith("\n") else "\n")


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
        list(
            offline_command(
                "uv",
                "run",
                "--project",
                "kaji/sdk",
                "--no-sync",
                "python",
                "kaji/scripts/check_sdk_parity.py",
            )
        ),
        environment,
        LOCAL_ORCHESTRATOR_BUDGET,
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
        LOCAL_ORCHESTRATOR_BUDGET,
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
        list(
            offline_command(
                "uv",
                "run",
                "--project",
                "kaji/sdk",
                "--no-sync",
                "python",
                "kaji/scripts/run_beta_benchmarks.py",
                "--quick",
            )
        ),
        environment,
        RELEASE_COMMAND_BUDGET,
    )
    run_in_dir(
        "Deterministic integration quick benchmark",
        ROOT,
        list(
            offline_command(
                "uv",
                "run",
                "--project",
                "kaji/sdk",
                "--no-sync",
                "python",
                "kaji/scripts/integration_benchmark.py",
                "--mode",
                "quick",
            )
        ),
        environment,
        RELEASE_COMMAND_BUDGET,
    )
    run_gates(common_gates(), environment)

    run_in_dir(
        "Python unit tests",
        SDK,
        list(
            offline_command(
                "uv",
                "run",
                "--no-sync",
                "pytest",
                "-m",
                "not integration",
            )
        ),
        environment,
    )
    run_in_dir(
        "Python typecheck",
        SDK,
        [
            "uv",
            "run",
            "python",
            "scripts/check_types.py",
            "--output-format",
            "concise",
        ],
        environment,
        LOCAL_ORCHESTRATOR_BUDGET,
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
        RELEASE_COMMAND_BUDGET,
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
                "scripts/check_types.py",
                "--output-format",
                "concise",
            ],
            environment,
            LOCAL_ORCHESTRATOR_BUDGET,
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
            RELEASE_COMMAND_BUDGET,
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

        run_gates(release_gates(), environment)

        attw_environment = environment.copy()
        attw_environment["npm_config_cache"] = str(release_temporary / "attw-npm-cache")
        run_in_dir(
            "TypeScript type artifact audit",
            TYPESCRIPT,
            ["bun", "x", "attw", "--pack", "."],
            attw_environment,
            PACKAGE_COMMAND_BUDGET,
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
            ["bun", "scripts/smoke_package.mts", str(tarball)],
            environment,
            PACKAGE_ORCHESTRATOR_BUDGET,
        )
        run_in_dir(
            "Reverify final Python artifacts",
            SDK,
            ["uv", "run", "python", "scripts/verify_archives.py", "dist"],
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
        run_in_dir(
            label,
            ROOT,
            metadata_command,
            environment,
            LOCAL_ORCHESTRATOR_BUDGET,
        )


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
                    budget=RELEASE_COMMAND_BUDGET,
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
