#!/usr/bin/env python3
"""Run four protected provider proofs from one verified installed artifact runtime."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any

from installed_release_runtime import installed_release_runtime
from process_runner import (
    CommandBudget,
    CommandError,
    CommandExitError,
    CommandInterruptedError,
    CommandTimeoutError,
    run_checked,
)


ROOT = Path(__file__).resolve().parents[2]
PYTHON_RUNNER = ROOT / "kaji" / "sdk" / "scripts" / "installed_provider_proof.py"
TYPESCRIPT_RUNNER = ROOT / "kaji" / "ts" / "scripts" / "installed-provider-proof.mts"
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
KEYED_PROOF_BUDGET = CommandBudget(timeout_seconds=180, terminate_grace_seconds=1)
PROVIDER_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}
MODEL_ENV = {
    "openai": "KAJI_LIVE_OPENAI_MODEL",
    "anthropic": "KAJI_LIVE_ANTHROPIC_MODEL",
}
DEFAULT_MODELS = {
    "openai": "gpt-5.4-mini",
    "anthropic": "claude-sonnet-4-6",
}
CELLS = (
    ("python", "openai"),
    ("typescript", "openai"),
    ("python", "anthropic"),
    ("typescript", "anthropic"),
)
CHILD_ENV_ALLOWLIST = {
    "ALL_PROXY",
    "CURL_CA_BUNDLE",
    "HOME",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "NODE_EXTRA_CA_CERTS",
    "NO_PROXY",
    "PATH",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "TEMP",
    "TMP",
    "TMPDIR",
    "all_proxy",
    "http_proxy",
    "https_proxy",
    "no_proxy",
}
RUNNER_ROW_KEYS = {
    "sdk",
    "provider",
    "proof",
    "status",
    "model",
    "resolvedPackage",
    "requestedToolCalls",
    "completedToolCalls",
    "requestedToolCallIds",
    "completedToolCallIds",
    "echoResultMatched",
    "finalTextPresent",
    "forbiddenTerminalEvents",
}


class ProofReceiptError(RuntimeError):
    """The child proof did not emit the exact redacted contract."""


def _proof_rows(models: Mapping[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "sdk": sdk,
            "provider": provider,
            "proof": "real_normalized_tool_loop",
            "status": "not_run",
            "model": models[provider],
            "artifactFile": None,
            "artifactSha256": None,
            "releaseManifestSha256": None,
            "resolvedPackage": None,
            "requestedToolCalls": 0,
            "completedToolCalls": 0,
            "requestedToolCallIds": [],
            "completedToolCallIds": [],
            "echoResultMatched": False,
            "finalTextPresent": False,
            "forbiddenTerminalEvents": [],
        }
        for sdk, provider in CELLS
    ]


def _initial_evidence(commit: str, models: Mapping[str, str]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "commit": commit,
        "releaseManifestSha256": None,
        "artifacts": {},
        "conclusion": "running",
        "failureCode": None,
        "proofs": _proof_rows(models),
    }


def _write_json_atomic(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(document, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _status_path(environment: Mapping[str, str]) -> Path | None:
    value = environment.get("KAJI_PROVIDER_STATUS_FILE", "").strip()
    return Path(value) if value else None


def _write_evidence(
    evidence: Mapping[str, Any], environment: Mapping[str, str]
) -> bool:
    path = _status_path(environment)
    if path is None:
        return True
    try:
        _write_json_atomic(path, evidence)
    except OSError:
        try:
            path.unlink()
        except OSError:
            pass
        print("FAIL: provider evidence could not be retained", file=sys.stderr)
        return False
    return True


def _retain_final(evidence: Mapping[str, Any], environment: Mapping[str, str]) -> bool:
    if not _write_evidence(evidence, environment):
        return False
    print(f"PROVIDER_EVIDENCE: {json.dumps(evidence, sort_keys=True)}")
    return True


def _retain_failure(
    evidence: dict[str, Any],
    environment: Mapping[str, str],
    failure_code: str,
) -> bool:
    evidence.update(conclusion="failed", failureCode=failure_code)
    return _retain_final(evidence, environment)


def _child_environment(
    base: Mapping[str, str],
    parent: Mapping[str, str],
    provider: str,
    model: str,
    commit: str,
) -> dict[str, str]:
    child = {name: base[name] for name in CHILD_ENV_ALLOWLIST if name in base}
    child["KAJI_RELEASE_COMMIT"] = commit
    child[PROVIDER_KEYS[provider]] = parent[PROVIDER_KEYS[provider]]
    child[MODEL_ENV[provider]] = model
    return child


def _run_proof(
    command: list[str], *, cwd: Path, environment: dict[str, str]
) -> dict[str, Any]:
    completed = run_checked(
        command,
        cwd=cwd,
        env=environment,
        capture=True,
        budget=KEYED_PROOF_BUDGET,
    )
    try:
        decoded = completed.stdout.decode("utf-8")
        document = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProofReceiptError from error
    if not isinstance(document, dict):
        raise ProofReceiptError
    return document


def _validate_runner_receipt(
    document: dict[str, Any],
    *,
    sdk: str,
    provider: str,
    model: str,
    resolved_package: Path,
) -> dict[str, Any]:
    if set(document) != RUNNER_ROW_KEYS:
        raise ProofReceiptError
    requested = document["requestedToolCallIds"]
    completed = document["completedToolCallIds"]
    if (
        document["sdk"] != sdk
        or document["provider"] != provider
        or document["proof"] != "real_normalized_tool_loop"
        or document["status"] != "passed"
        or document["model"] != model
        or document["resolvedPackage"] != str(resolved_package)
        or type(document["requestedToolCalls"]) is not int
        or document["requestedToolCalls"] != 1
        or type(document["completedToolCalls"]) is not int
        or document["completedToolCalls"] != 1
        or not isinstance(requested, list)
        or len(requested) != 1
        or not isinstance(requested[0], str)
        or not requested[0]
        or completed != requested
        or document["echoResultMatched"] is not True
        or document["finalTextPresent"] is not True
        or document["forbiddenTerminalEvents"] != []
    ):
        raise ProofReceiptError
    return document


def _enrich_runner_receipt(
    document: dict[str, Any], identity: Mapping[str, Any], sdk: str
) -> dict[str, Any]:
    artifact = identity["artifacts"][sdk]
    return {
        **document,
        "artifactFile": artifact["file"],
        "artifactSha256": artifact["sha256"],
        "releaseManifestSha256": identity["releaseManifestSha256"],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protected", action="store_true")
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    return parser.parse_args(argv)


def _argument_value(arguments: list[str], name: str) -> str | None:
    try:
        return arguments[arguments.index(name) + 1]
    except (ValueError, IndexError):
        return None


def _models(environment: Mapping[str, str]) -> dict[str, str]:
    return {
        provider: environment.get(MODEL_ENV[provider], "").strip()
        or DEFAULT_MODELS[provider]
        for provider in PROVIDER_KEYS
    }


def main(
    argv: list[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parent = dict(os.environ if environment is None else environment)
    models = _models(parent)
    commit = (
        _argument_value(arguments, "--expected-commit")
        or parent.get("KAJI_RELEASE_COMMIT")
        or "unknown"
    )
    evidence = _initial_evidence(commit, models)
    if not _write_evidence(evidence, parent):
        return 1
    try:
        args = parse_args(arguments)
    except SystemExit:
        _retain_failure(evidence, parent, "invalid_provider_arguments")
        return 2
    if not args.protected:
        _retain_failure(evidence, parent, "protected_mode_required")
        return 2
    if COMMIT_PATTERN.fullmatch(args.expected_commit) is None:
        _retain_failure(evidence, parent, "invalid_release_commit")
        return 2
    if parent.get("KAJI_RELEASE_COMMIT", "").strip() != args.expected_commit:
        _retain_failure(evidence, parent, "release_commit_mismatch")
        return 2
    missing = [
        name for name in PROVIDER_KEYS.values() if not parent.get(name, "").strip()
    ]
    if missing:
        _retain_failure(evidence, parent, "missing_required_key")
        print("FAIL: required provider credentials are unavailable", file=sys.stderr)
        return 2

    current_index: int | None = None
    try:
        with installed_release_runtime(
            args.artifacts_dir, expected_commit=args.expected_commit
        ) as runtime:
            identity = runtime.identity()
            if identity.get("commit") != args.expected_commit:
                raise RuntimeError("installed artifact commit mismatch")
            evidence.update(
                commit=identity["commit"],
                releaseManifestSha256=identity["releaseManifestSha256"],
                artifacts=identity["artifacts"],
            )
            if not _write_evidence(evidence, parent):
                return 1
            typescript_runner = runtime.typescript_workdir / TYPESCRIPT_RUNNER.name
            shutil.copy2(TYPESCRIPT_RUNNER, typescript_runner)
            bun = shutil.which("bun", path=runtime.environment["PATH"])
            if bun is None:
                raise RuntimeError("bun is required for TypeScript provider proof")

            for current_index, (sdk, provider) in enumerate(CELLS):
                model = models[provider]
                child = _child_environment(
                    runtime.environment,
                    parent,
                    provider,
                    model,
                    args.expected_commit,
                )
                if sdk == "python":
                    command = [
                        str(runtime.python_executable),
                        "-I",
                        str(PYTHON_RUNNER),
                        "--provider",
                        provider,
                        "--model",
                        model,
                    ]
                    cwd = runtime.root
                    resolved_package = runtime.resolved_python_package
                else:
                    command = [
                        bun,
                        str(typescript_runner),
                        "--provider",
                        provider,
                        "--model",
                        model,
                    ]
                    cwd = runtime.typescript_workdir
                    resolved_package = runtime.resolved_typescript_package
                raw = _run_proof(command, cwd=cwd, environment=child)
                row = _validate_runner_receipt(
                    raw,
                    sdk=sdk,
                    provider=provider,
                    model=model,
                    resolved_package=resolved_package,
                )
                evidence["proofs"][current_index] = _enrich_runner_receipt(
                    row, identity, sdk
                )
                if not _write_evidence(evidence, parent):
                    return 1
    except CommandInterruptedError:
        failure_code = "proof_command_interrupted"
    except CommandTimeoutError:
        failure_code = "proof_command_timed_out"
    except CommandExitError:
        failure_code = "proof_command_failed"
    except ProofReceiptError:
        failure_code = "proof_receipt_invalid"
    except (CommandError, OSError, RuntimeError):
        failure_code = "artifact_runtime_failed"
    else:
        evidence.update(conclusion="passed", failureCode=None)
        if not _retain_final(evidence, parent):
            return 1
        print("PASS: four installed provider tool loops completed")
        return 0

    if current_index is not None:
        evidence["proofs"][current_index]["status"] = "failed"
    _retain_failure(evidence, parent, failure_code)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
