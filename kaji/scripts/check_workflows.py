#!/usr/bin/env python3
"""Validate GitHub Actions locally, optionally followed by the Kaji CI gate."""

from __future__ import annotations

import argparse

from beta_release_check import (
    GateFailure,
    LOCAL_ORCHESTRATOR_BUDGET,
    PACKAGE_ORCHESTRATOR_BUDGET,
    ROOT,
    release_environment,
    require_command,
    run_ci_checks,
    run_in_dir,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gate",
        action="store_true",
        help="also run the repository-owned Kaji pull-request commands locally",
    )
    return parser.parse_args()


def run_workflow_checks(environment: dict[str, str], *, include_gate: bool) -> None:
    run_in_dir(
        "GitHub Actions static analysis",
        ROOT,
        ["actionlint"],
        environment,
    )
    run_in_dir(
        "Python lockfile freshness",
        ROOT / "kaji",
        ["uv", "lock", "--check"],
        environment,
    )
    run_in_dir(
        "Frozen Python dependencies",
        ROOT / "kaji",
        ["uv", "sync", "--frozen"],
        environment,
        PACKAGE_ORCHESTRATOR_BUDGET,
    )
    run_in_dir(
        "Frozen Bun dependencies",
        ROOT,
        ["bun", "install", "--frozen-lockfile"],
        environment,
        PACKAGE_ORCHESTRATOR_BUDGET,
    )
    run_in_dir(
        "Executable Kaji workflow contracts",
        ROOT,
        [
            "bun",
            "run",
            "--cwd",
            "kaji/ts",
            "test",
            "--",
            "tests/release-security.test.ts",
        ],
        environment,
        LOCAL_ORCHESTRATOR_BUDGET,
    )
    if include_gate:
        run_ci_checks(environment)


def main() -> int:
    args = parse_args()
    environment = release_environment()
    try:
        require_command(
            "actionlint",
            "GitHub Actions validation (install with `brew install actionlint`)",
            environment,
        )
        require_command(
            "shellcheck",
            "shell diagnostics (installed with Homebrew actionlint)",
            environment,
        )
        require_command("bun", "executable Kaji workflow contracts", environment)
        require_command("node", "TypeScript workflow contracts", environment)
        require_command("uv", "Python lockfile and Kaji CI checks", environment)
        run_workflow_checks(environment, include_gate=args.gate)
    except GateFailure as error:
        return error.status

    print()
    if args.gate:
        print(
            "PASS: local workflow validation and Kaji CI gate completed; "
            "protected matrix, provider, and publication evidence NOT claimed"
        )
    else:
        print(
            "PASS: local workflow validation completed; GitHub runner execution "
            "NOT claimed"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
