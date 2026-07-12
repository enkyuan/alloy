#!/usr/bin/env python3
"""Build, verify, and smoke-test the Python SDK release archives."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
from tempfile import TemporaryDirectory
import time

from _repo_process import (
    PACKAGE_COMMAND_BUDGET,
    PACKAGE_ORCHESTRATOR_BUDGET,
    CommandBudget,
    CommandExitError,
    run_checked,
)


SDK_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SDK_ROOT / "scripts"
EXPECTED_MOCK_REPLY = "mock"
EXPECTED_ECHO_DESCRIPTION = (
    "Trivial echo integration. Two pure functions, no auth, no network. "
    "Proves the cross-language registry contract."
)
EXPECTED_GITHUB_DESCRIPTION = "Repository-scoped GitHub code, issue, and comment tools."


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
) -> str:
    """Run a bounded command and return UTF-8 stdout."""

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
    try:
        return completed.stdout.decode("utf-8", errors="strict")
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
    for name in ("echo.py", "echo.ts"):
        copied = destination / name
        packaged = registry / "echo" / name
        if not copied.is_file() or copied.read_bytes() != packaged.read_bytes():
            raise SystemExit(
                "FAIL: installed add did not copy the packaged Echo assets"
            )
        if f"wrote {copied.resolve()}" not in output:
            raise SystemExit(
                "FAIL: installed add did not report every copied Echo asset"
            )
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
    echo = re.compile(
        rf"^  echo\s+\[beta\]\s+v0\.1\.0\s+{re.escape(EXPECTED_ECHO_DESCRIPTION)}$",
        re.MULTILINE,
    )
    github = re.compile(
        rf"^  github\s+\[experimental\]\s+v0\.1\.0\s+{re.escape(EXPECTED_GITHUB_DESCRIPTION)}$",
        re.MULTILINE,
    )
    if echo.search(output) is None:
        raise SystemExit(
            "FAIL: installed list-integrations omitted the packaged Echo entry"
        )
    if github.search(output) is None:
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


def release_smoke(dist_dir: Path) -> None:
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

        wheel = next(dist_dir.glob("*.whl"), None)
        sdist = next(dist_dir.glob("*.tar.gz"), None)
        if wheel is None or sdist is None:
            raise SystemExit(f"FAIL: expected wheel and sdist under {dist_dir}")

        for package in (wheel, sdist):
            cold_started = time.perf_counter()
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
            registry = installed_registry_root(venv)
            kaji = str(venv_kaji(venv))

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
            )
            assert_experimental_denial(denial_output, denied_github)

            github = workdir / f"github-{safe_name}"
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

            list_output = run_capture(
                [kaji, "--no-color", "list-integrations"],
                cwd=artifact_workdir,
                environment=environment,
            )
            assert_list_integrations_output(list_output)

            cold_output = run_capture(
                [str(python), "agent.py"],
                cwd=scaffold,
                environment=environment,
            )
            cold_ms = round((time.perf_counter() - cold_started) * 1000, 3)
            cold_result = assert_scaffold_output(cold_output)

            warm_started = time.perf_counter()
            warm_output = run_capture(
                [str(python), "agent.py"],
                cwd=scaffold,
                environment=environment,
            )
            warm_ms = round((time.perf_counter() - warm_started) * 1000, 3)
            warm_result = assert_scaffold_output(warm_output)
            assert_matching_scaffold_outputs(cold_result, warm_result)
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=Path(os.environ.get("DIST_DIR") or "dist"),
        help="artifact output directory (default: DIST_DIR or dist)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    release_smoke(args.dist_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
