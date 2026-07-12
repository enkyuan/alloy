#!/usr/bin/env python3
"""Run and retain the four protected keyed provider tool-loop proofs."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
from typing import Any

from process_runner import (
    CommandBudget,
    CommandError,
    CommandExitError,
    CommandStartError,
    run_checked,
)


ROOT = Path(__file__).resolve().parents[2]
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
KEYED_PROOF_BUDGET = CommandBudget(timeout_seconds=180, terminate_grace_seconds=1)
PROVIDER_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def run(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    budget: CommandBudget = KEYED_PROOF_BUDGET,
) -> int:
    try:
        run_checked(command, cwd=cwd, env=environment, budget=budget)
        return 0
    except CommandExitError as error:
        return error.returncode if error.returncode >= 0 else 128 - error.returncode
    except CommandStartError:
        print("FAIL: command could not be started", file=sys.stderr)
        return 127
    except CommandError as error:
        print(
            f"FAIL: provider proof command failed ({type(error).__name__})",
            file=sys.stderr,
        )
        return 1


def _proof_rows() -> list[dict[str, str]]:
    return [
        {
            "sdk": sdk,
            "provider": provider,
            "proof": "real_normalized_tool_loop",
            "status": "not_run",
        }
        for sdk, provider in (
            ("python", "openai"),
            ("typescript", "openai"),
            ("python", "anthropic"),
            ("typescript", "anthropic"),
        )
    ]


def _commands() -> list[tuple[list[str], Path]]:
    return [
        (
            [
                sys.executable,
                "-m",
                "pytest",
                "-m",
                "integration",
                "tests/integration/test_openai_tools.py",
                "-q",
            ],
            ROOT / "kaji" / "sdk",
        ),
        (
            [
                "bun",
                "run",
                "test:integration",
                "tests/integration/openai-tools.test.ts",
            ],
            ROOT / "kaji" / "ts",
        ),
        (
            [
                sys.executable,
                "-m",
                "pytest",
                "-m",
                "integration",
                "tests/integration/test_anthropic_provider.py",
                "-k",
                "agent_executes_tool_and_finishes",
                "-q",
            ],
            ROOT / "kaji" / "sdk",
        ),
        (
            [
                "bun",
                "run",
                "test:integration",
                "tests/integration/anthropic-live.test.ts",
                "-t",
                "executes a real model-requested tool and then emits final text",
            ],
            ROOT / "kaji" / "ts",
        ),
    ]


def _child_environment(environment: dict[str, str], provider: str) -> dict[str, str]:
    """Give each proof only the credential for the provider it exercises."""
    child = environment.copy()
    for key in PROVIDER_KEYS.values():
        child.pop(key, None)
    key = PROVIDER_KEYS[provider]
    child[key] = environment[key]
    return child


def _write_evidence(evidence: dict[str, Any], environment: dict[str, str]) -> None:
    status_file = environment.get("KAJI_PROVIDER_STATUS_FILE")
    if status_file:
        path = Path(status_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")


def _retain_final(evidence: dict[str, Any], environment: dict[str, str]) -> None:
    _write_evidence(evidence, environment)
    rendered = json.dumps(evidence, sort_keys=True)
    print(f"PROVIDER_EVIDENCE: {rendered}")
    summary_file = environment.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        rows = "\n".join(
            f"- {row['sdk']} / {row['provider']}: `{row['status']}`"
            for row in evidence["proofs"]
        )
        with Path(summary_file).open("a", encoding="utf-8") as stream:
            stream.write(
                "## Keyed provider proof\n\n"
                f"- Commit: `{evidence['commit']}`\n"
                f"- Conclusion: `{evidence['conclusion']}`\n"
                f"{rows}\n"
            )


def main() -> int:
    environment = os.environ.copy()
    commit = (
        environment.get("KAJI_RELEASE_COMMIT")
        or environment.get("GITHUB_SHA")
        or "unknown"
    )
    evidence: dict[str, Any] = {
        "schemaVersion": 1,
        "commit": commit,
        "conclusion": "running",
        "proofs": _proof_rows(),
    }
    _write_evidence(evidence, environment)

    missing = [
        key
        for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")
        if not environment.get(key, "").strip()
    ]
    if missing:
        evidence.update(conclusion="failed", failureCode="missing_required_key")
        _retain_final(evidence, environment)
        print(
            "FAIL: "
            + "; ".join(
                f"{key} is required for keyed provider proof" for key in missing
            ),
            file=sys.stderr,
        )
        return 2
    if COMMIT_PATTERN.fullmatch(commit) is None:
        evidence.update(conclusion="failed", failureCode="invalid_release_commit")
        _retain_final(evidence, environment)
        print(
            "FAIL: KAJI_RELEASE_COMMIT must be exactly 40 lowercase hex characters",
            file=sys.stderr,
        )
        return 2

    for index, (command, cwd) in enumerate(_commands()):
        row = evidence["proofs"][index]
        print(
            f"Running {row['sdk']} {row['provider']} real normalized tool loop",
            flush=True,
        )
        status = run(
            command,
            cwd=cwd,
            environment=_child_environment(environment, row["provider"]),
        )
        row["status"] = "passed" if status == 0 else "failed"
        _write_evidence(evidence, environment)
        if status != 0:
            evidence.update(conclusion="failed", failureCode="proof_command_failed")
            _retain_final(evidence, environment)
            return status

    evidence["conclusion"] = "passed"
    _retain_final(evidence, environment)
    print("PASS: four required provider tool loops completed on the release commit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
