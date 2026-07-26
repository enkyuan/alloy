#!/usr/bin/env python3
"""Run the protected exact-artifact GitHub comment proof and cleanup."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sys
from typing import Any
import unicodedata

from github_proof_cleanup import reconcile_state
from github_proof_control import (
    GitHubProofControl,
    GitHubProofError,
    canonical_issue_url,
    decode_json_object,
    new_proof_state,
    normalize_private_path,
    private_state_lock,
    read_private_json,
    remove_private_file,
    state_lock_path,
    update_proof_cell,
    validate_proof_token,
    validate_private_fixture,
    validate_proof_state,
    write_private_json,
)
from installed_release_runtime import InstalledReleaseRuntime, installed_release_runtime
from jsonschema import Draft202012Validator
from process_runner import CommandBudget, CommandError, run_checked
from validate_release_evidence import validate_compatibility
from verify_release_artifacts import VerifiedReleaseArtifacts, verify


ROOT = Path(__file__).resolve().parents[2]
MAX_COMPATIBILITY_RECEIPT_BYTES = 1024 * 1024
MAX_CHILD_RECEIPT_BYTES = 64 * 1024
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
WORKFLOW_RUN_PATTERN = re.compile(
    r"https://github\.com/[^/]+/[^/]+/actions/runs/[1-9][0-9]*"
)
PYTHON_WHEEL = "kaji_sdk-0.2.0b1-py3-none-any.whl"
PYTHON_SDIST = "kaji_sdk-0.2.0b1.tar.gz"
TYPESCRIPT_TARBALL = "kaji-sdk-0.2.0-beta.3.tgz"
RELEASE_FILES = (
    PYTHON_WHEEL,
    PYTHON_SDIST,
    TYPESCRIPT_TARBALL,
    "manifest.json",
    "SHA256SUMS",
)
PYTHON_RUNNER = ROOT / "kaji" / "scripts" / "installed_github_live.py"
CONTROL_HELPER = ROOT / "kaji" / "scripts" / "github_proof_control.py"
TYPESCRIPT_RUNNER = ROOT / "kaji" / "ts" / "scripts" / "installed-github-live.mts"
PUBLIC_SCHEMA = ROOT / "kaji" / "contracts" / "release" / "github-proof-v1.schema.json"
PYTHON_CHILD_BOOTSTRAP = "\n".join(
    (
        "import importlib.util, runpy, sys",
        "root, helper, runner, *arguments = sys.argv[1:]",
        "sys.path.insert(0, root)",
        (
            "spec = importlib.util.spec_from_file_location("
            "'github_proof_control', helper)"
        ),
        "if spec is None or spec.loader is None: raise RuntimeError('helper_invalid')",
        "module = importlib.util.module_from_spec(spec)",
        "sys.modules['github_proof_control'] = module",
        "spec.loader.exec_module(module)",
        "sys.argv = [runner, *arguments]",
        "runpy.run_path(runner, run_name='__main__')",
    )
)
CHILD_BUDGET = CommandBudget(
    timeout_seconds=60,
    max_output_bytes=MAX_CHILD_RECEIPT_BYTES,
    terminate_grace_seconds=1,
)
PREPARE_BUDGET = CommandBudget(
    timeout_seconds=60,
    max_output_bytes=MAX_CHILD_RECEIPT_BYTES,
    terminate_grace_seconds=1,
)
COMPATIBILITY_KEYS = {
    "schemaVersion",
    "commit",
    "releaseManifestSha256",
    "artifactSha256",
    "runtime",
    "artifacts",
    "githubPackageProofs",
    "conclusion",
    "failureCode",
    "workflowRun",
    "workflowRunAttempt",
}


CompatibilityValidator = Callable[
    [dict[str, Any], str, str, VerifiedReleaseArtifacts, argparse.Namespace],
    None,
]
ReleaseVerifier = Callable[[Path, str], VerifiedReleaseArtifacts]
RuntimeFactory = Callable[..., AbstractContextManager[InstalledReleaseRuntime]]
RuntimePreparer = Callable[[InstalledReleaseRuntime], None]
ChildRunner = Callable[[InstalledReleaseRuntime, str, Path, str], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ProofPrerequisites:
    commit: str
    release_manifest_sha256: str
    workflow_run: str
    workflow_run_attempt: int
    artifact_sha256: dict[str, str]
    package_proof_sha256: dict[str, str]
    release: VerifiedReleaseArtifacts


PrerequisiteLoader = Callable[..., ProofPrerequisites]


def validate_child_receipt(encoded: bytes, runtime: str) -> dict[str, Any]:
    if len(encoded) > MAX_CHILD_RECEIPT_BYTES or runtime not in {
        "python",
        "typescript",
    }:
        raise GitHubProofError("child_receipt_invalid")
    document = decode_json_object(encoded, code="child_receipt_invalid")
    if (
        set(document)
        != {
            "runtime",
            "readPassed",
            "approvedCommentPassed",
            "commentId",
        }
        or document.get("runtime") != runtime
        or document.get("readPassed") is not True
        or document.get("approvedCommentPassed") is not True
        or type(document.get("commentId")) is not int
        or not 1 <= document["commentId"] <= 9_007_199_254_740_991
    ):
        raise GitHubProofError("child_receipt_invalid")
    return document


def _read_receipt(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        metadata = path.lstat()
        if (
            path.is_symlink()
            or not path.is_file()
            or metadata.st_size > MAX_COMPATIBILITY_RECEIPT_BYTES
        ):
            raise OSError
        encoded = path.read_bytes()
    except OSError:
        raise GitHubProofError("prerequisite_invalid") from None
    if len(encoded) > MAX_COMPATIBILITY_RECEIPT_BYTES:
        raise GitHubProofError("prerequisite_invalid")
    try:
        return decode_json_object(encoded, code="prerequisite_invalid"), encoded
    except GitHubProofError:
        raise


def _is_source_path(value: Any, workspace: Path) -> bool:
    if not isinstance(value, str) or not value:
        return True
    path = Path(value)
    if not path.is_absolute():
        return True
    resolved = path.resolve(strict=False)
    checkout = workspace.resolve(strict=False)
    normalized = resolved.as_posix()
    return (
        resolved == checkout
        or resolved.is_relative_to(checkout)
        or any(
            marker in normalized
            for marker in ("/kaji/src/", "/kaji/ts/src/", "/kaji/ts/dist/")
        )
    )


def _validate_closed_identity(
    document: dict[str, Any],
    *,
    runtime: str,
    expected_commit: str,
    release: VerifiedReleaseArtifacts,
    workflow_run: str,
    workflow_run_attempt: int,
    workspace: Path,
) -> None:
    if (
        set(document) != COMPATIBILITY_KEYS
        or document.get("schemaVersion") != 1
        or document.get("commit") != expected_commit
        or document.get("releaseManifestSha256") != release.manifest_sha256
        or document.get("workflowRun") != workflow_run
        or document.get("workflowRunAttempt") != workflow_run_attempt
        or document.get("conclusion") != "passed"
        or document.get("failureCode") is not None
    ):
        raise GitHubProofError("prerequisite_invalid")
    runtime_value = document.get("runtime")
    artifacts = document.get("artifacts")
    hashes = document.get("artifactSha256")
    if runtime == "python":
        if (
            type(runtime_value) is not dict
            or set(runtime_value) != {"implementation", "version", "executable"}
            or runtime_value.get("implementation") != "CPython"
            or not isinstance(runtime_value.get("version"), str)
            or re.fullmatch(r"3\.11\.[0-9]+", runtime_value["version"]) is None
            or not isinstance(runtime_value.get("executable"), str)
            or not runtime_value["executable"]
            or type(artifacts) is not dict
            or set(artifacts) != {"wheel", "sdist"}
            or Path(str(artifacts.get("wheel"))).name != PYTHON_WHEEL
            or Path(str(artifacts.get("sdist"))).name != PYTHON_SDIST
            or hashes
            != {
                PYTHON_WHEEL: release.artifact_sha256[PYTHON_WHEEL],
                PYTHON_SDIST: release.artifact_sha256[PYTHON_SDIST],
            }
        ):
            raise GitHubProofError("prerequisite_invalid")
        return
    if (
        runtime != "typescript"
        or type(runtime_value) is not dict
        or set(runtime_value) != {"version"}
        or not isinstance(runtime_value.get("version"), str)
        or re.fullmatch(r"v22\.[0-9]+\.[0-9]+", runtime_value["version"]) is None
        or type(artifacts) is not dict
        or set(artifacts) != {"tarball", "package"}
        or Path(str(artifacts.get("tarball"))).name != TYPESCRIPT_TARBALL
        or _is_source_path(artifacts.get("package"), workspace)
        or hashes
        != {
            TYPESCRIPT_TARBALL: release.artifact_sha256[TYPESCRIPT_TARBALL],
        }
    ):
        raise GitHubProofError("prerequisite_invalid")


def _default_compatibility_validator(
    document: dict[str, Any],
    runtime: str,
    version: str,
    release: VerifiedReleaseArtifacts,
    args: argparse.Namespace,
) -> None:
    validate_compatibility(
        document,
        runtime=runtime,
        version=version,
        release=release,
        args=args,
    )


def validate_prerequisites(
    artifacts_dir: Path,
    expected_commit: str,
    python_compatibility: Path,
    typescript_compatibility: Path,
    *,
    verifier: ReleaseVerifier = verify,
    compatibility_validator: CompatibilityValidator = _default_compatibility_validator,
    workspace: Path = ROOT,
) -> ProofPrerequisites:
    if COMMIT_PATTERN.fullmatch(expected_commit) is None:
        raise GitHubProofError("prerequisite_invalid")
    try:
        release = verifier(artifacts_dir, expected_commit)
    except (OSError, RuntimeError, SystemExit):
        raise GitHubProofError("prerequisite_invalid") from None
    if (
        release.commit != expected_commit
        or release.manifest_sha256 is None
        or release.artifact_sha256.get(PYTHON_WHEEL) is None
        or release.artifact_sha256.get(PYTHON_SDIST) is None
        or release.artifact_sha256.get(TYPESCRIPT_TARBALL) is None
    ):
        raise GitHubProofError("prerequisite_invalid")
    python, python_bytes = _read_receipt(python_compatibility)
    typescript, typescript_bytes = _read_receipt(typescript_compatibility)
    workflow_run = python.get("workflowRun")
    workflow_attempt = python.get("workflowRunAttempt")
    if (
        not isinstance(workflow_run, str)
        or WORKFLOW_RUN_PATTERN.fullmatch(workflow_run) is None
        or type(workflow_attempt) is not int
        or workflow_attempt < 1
        or typescript.get("workflowRun") != workflow_run
        or typescript.get("workflowRunAttempt") != workflow_attempt
    ):
        raise GitHubProofError("prerequisite_invalid")
    _validate_closed_identity(
        python,
        runtime="python",
        expected_commit=expected_commit,
        release=release,
        workflow_run=workflow_run,
        workflow_run_attempt=workflow_attempt,
        workspace=workspace,
    )
    _validate_closed_identity(
        typescript,
        runtime="typescript",
        expected_commit=expected_commit,
        release=release,
        workflow_run=workflow_run,
        workflow_run_attempt=workflow_attempt,
        workspace=workspace,
    )
    args = argparse.Namespace(
        expected_commit=expected_commit,
        workflow_run=workflow_run,
        workflow_run_attempt=workflow_attempt,
        workspace=workspace,
    )
    try:
        compatibility_validator(python, "python", "3.11", release, args)
        compatibility_validator(typescript, "typescript", "22", release, args)
    except (OSError, RuntimeError, SystemExit):
        raise GitHubProofError("prerequisite_invalid") from None
    return ProofPrerequisites(
        commit=expected_commit,
        release_manifest_sha256=release.manifest_sha256,
        workflow_run=workflow_run,
        workflow_run_attempt=workflow_attempt,
        artifact_sha256={
            "python": release.artifact_sha256[PYTHON_WHEEL],
            "typescript": release.artifact_sha256[TYPESCRIPT_TARBALL],
        },
        package_proof_sha256={
            "python": hashlib.sha256(python_bytes).hexdigest(),
            "typescript": hashlib.sha256(typescript_bytes).hexdigest(),
        },
        release=release,
    )


def _validate_runtime_identity(
    runtime: InstalledReleaseRuntime, prerequisites: ProofPrerequisites
) -> None:
    identity = runtime.identity()
    artifacts = identity.get("artifacts")
    if (
        identity.get("commit") != prerequisites.commit
        or identity.get("releaseManifestSha256")
        != prerequisites.release_manifest_sha256
        or type(artifacts) is not dict
        or artifacts.get("python")
        != {
            "file": PYTHON_WHEEL,
            "sha256": prerequisites.artifact_sha256["python"],
        }
        or artifacts.get("typescript")
        != {
            "file": TYPESCRIPT_TARBALL,
            "sha256": prerequisites.artifact_sha256["typescript"],
        }
    ):
        raise GitHubProofError("installed_runtime_invalid")


def _prepare_runtime(runtime: InstalledReleaseRuntime) -> None:
    python_runner = runtime.root / PYTHON_RUNNER.name
    control_helper = runtime.root / CONTROL_HELPER.name
    typescript_runner = runtime.typescript_workdir / TYPESCRIPT_RUNNER.name
    bundle = runtime.root / "owner_integrations" / "github"
    try:
        shutil.copy2(PYTHON_RUNNER, python_runner)
        shutil.copy2(CONTROL_HELPER, control_helper)
        shutil.copy2(TYPESCRIPT_RUNNER, typescript_runner)
        completed = run_checked(
            [
                str(runtime.python_executable),
                "-I",
                "-m",
                "kaji.cli",
                "--no-color",
                "add",
                "github",
                "--allow-experimental",
                "--out",
                str(bundle),
            ],
            cwd=runtime.root,
            env=runtime.environment,
            capture=True,
            budget=PREPARE_BUDGET,
        )
    except (CommandError, OSError):
        raise GitHubProofError("installed_runtime_invalid") from None
    if completed.stderr or not bundle.is_dir() or bundle.is_symlink():
        raise GitHubProofError("installed_runtime_invalid")


def _default_child_runner(
    runtime: InstalledReleaseRuntime,
    runtime_name: str,
    input_path: Path,
    token: str,
) -> dict[str, Any]:
    environment = dict(runtime.environment)
    environment["KAJI_GITHUB_PROOF_TOKEN"] = token
    environment.pop("KAJI_GITHUB_PROOF_INPUT", None)
    if runtime_name == "python":
        runner = runtime.root / PYTHON_RUNNER.name
        helper = runtime.root / CONTROL_HELPER.name
        command = [
            str(runtime.python_executable),
            "-I",
            "-c",
            PYTHON_CHILD_BOOTSTRAP,
            str(runtime.root),
            str(helper),
            str(runner),
            "--sandbox-root",
            str(runtime.root),
            "--bundle-root",
            str(runtime.root / "owner_integrations" / "github"),
            "--package-root",
            str(runtime.resolved_python_package.parent),
            "--input",
            str(input_path),
        ]
        cwd = runtime.root
    elif runtime_name == "typescript":
        bun = shutil.which("bun", path=environment.get("PATH"))
        if bun is None:
            raise GitHubProofError("installed_runtime_invalid")
        try:
            encoded_input = json.dumps(
                read_private_json(input_path),
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (GitHubProofError, TypeError, ValueError):
            raise GitHubProofError("private_input_invalid") from None
        if len(encoded_input.encode()) > MAX_CHILD_RECEIPT_BYTES:
            raise GitHubProofError("private_input_invalid")
        environment["KAJI_GITHUB_PROOF_INPUT"] = encoded_input
        command = [
            bun,
            str(runtime.typescript_workdir / TYPESCRIPT_RUNNER.name),
            "--sandbox-root",
            str(runtime.root),
            "--package-root",
            str(runtime.resolved_typescript_package),
        ]
        cwd = runtime.typescript_workdir
    else:
        raise GitHubProofError("installed_runtime_invalid")
    try:
        completed = run_checked(
            command,
            cwd=cwd,
            env=environment,
            capture=True,
            budget=CHILD_BUDGET,
        )
    except CommandError:
        raise GitHubProofError("installed_child_failed") from None
    if completed.stderr:
        raise GitHubProofError("installed_child_failed")
    return validate_child_receipt(completed.stdout, runtime_name)


def _input_document(
    state: Mapping[str, Any], cell: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "runtime": cell["runtime"],
        "owner": state["owner"],
        "repository": state["repository"],
        "issueNumber": state["issueNumber"],
        "marker": cell["marker"],
    }


def _output_receipt(
    prerequisites: ProofPrerequisites, state: Mapping[str, Any]
) -> dict[str, Any]:
    cells = state["cells"]
    if (
        type(cells) is not list
        or [cell.get("phase") for cell in cells] != ["cleaned", "cleaned"]
        or any(
            not (
                cell.get("readPassed") is True
                and cell.get("approvedCommentPassed") is True
                and cell.get("controlReadbackPassed") is True
                and cell.get("reconciliationRequired") is False
            )
            for cell in cells
        )
    ):
        raise GitHubProofError("proof_not_clean")
    return {
        "schemaVersion": "1.0.0",
        "commit": prerequisites.commit,
        "releaseManifestSha256": prerequisites.release_manifest_sha256,
        "cells": [
            {
                "runtime": runtime,
                "artifactSha256": prerequisites.artifact_sha256[runtime],
                "packageProofSha256": prerequisites.package_proof_sha256[runtime],
                "conclusion": "passed",
            }
            for runtime in ("python", "typescript")
        ],
        "approvalRejectedBeforeTransport": True,
        "readPassed": True,
        "approvedCommentPassed": True,
        "controlReadbackPassed": True,
        "ambiguousMutationRetried": False,
        "cleanup": {"required": True, "conclusion": "passed"},
        "redacted": True,
    }


def _write_public_receipt(path: Path, document: Mapping[str, Any]) -> None:
    try:
        schema = json.loads(PUBLIC_SCHEMA.read_bytes())
        errors = list(Draft202012Validator(schema).iter_errors(document))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise GitHubProofError("public_receipt_invalid") from None
    if errors:
        raise GitHubProofError("public_receipt_invalid")
    try:
        encoded = (
            json.dumps(
                document,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and (path.is_symlink() or not path.is_file()):
            raise OSError
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(12)}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                descriptor = -1
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory_flags = os.O_RDONLY
            if hasattr(os, "O_DIRECTORY"):
                directory_flags |= os.O_DIRECTORY
            directory = os.open(path.parent, directory_flags)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    except (OSError, TypeError, ValueError, UnicodeError):
        raise GitHubProofError("public_receipt_invalid") from None


def _mark_cell_failure(
    state_path: Path,
    state: dict[str, Any],
    runtime_name: str,
    *,
    origin: str,
    dispatched: bool,
) -> None:
    update_proof_cell(
        state,
        runtime_name,
        phase="failed",
        dispatchAttempted=dispatched,
        reconciliationRequired=dispatched,
        failureOrigin=origin,
    )
    write_private_json(state_path, state)


async def _run_cell(
    *,
    state_path: Path,
    state: dict[str, Any],
    runtime: InstalledReleaseRuntime,
    runtime_name: str,
    input_path: Path,
    token: str,
    child_runner: ChildRunner,
    control_factory: Callable[[str], Any],
) -> None:
    cell = next(item for item in state["cells"] if item["runtime"] == runtime_name)
    marker = cell["marker"]
    issue_url = canonical_issue_url(
        state["owner"], state["repository"], state["issueNumber"]
    )
    async with control_factory(token) as control:
        try:
            comments = await control.list_issue_comments(
                state["owner"], state["repository"], state["issueNumber"]
            )
        except asyncio.CancelledError:
            raise
        except GitHubProofError:
            _mark_cell_failure(
                state_path,
                state,
                runtime_name,
                origin="preflight",
                dispatched=False,
            )
            raise
    if any(comment.get("issueUrl") != issue_url for comment in comments):
        _mark_cell_failure(
            state_path,
            state,
            runtime_name,
            origin="preflight",
            dispatched=False,
        )
        raise GitHubProofError("control_readback_invalid")
    if any(comment.get("body") == marker for comment in comments):
        _mark_cell_failure(
            state_path,
            state,
            runtime_name,
            origin="preflight",
            dispatched=False,
        )
        raise GitHubProofError("preflight_marker_present")

    update_proof_cell(
        state,
        runtime_name,
        phase="dispatched",
        dispatchAttempted=True,
        reconciliationRequired=True,
    )
    write_private_json(state_path, state)
    try:
        write_private_json(input_path, _input_document(state, cell))
        try:
            raw_receipt = child_runner(runtime, runtime_name, input_path, token)
        except GitHubProofError:
            _mark_cell_failure(
                state_path,
                state,
                runtime_name,
                origin="child",
                dispatched=True,
            )
            raise
        except (OSError, RuntimeError):
            _mark_cell_failure(
                state_path,
                state,
                runtime_name,
                origin="child",
                dispatched=True,
            )
            raise GitHubProofError("installed_child_failed") from None
        finally:
            if input_path.exists():
                remove_private_file(input_path)
        try:
            child_receipt = validate_child_receipt(
                json.dumps(
                    raw_receipt,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode(),
                runtime_name,
            )
        except GitHubProofError:
            _mark_cell_failure(
                state_path,
                state,
                runtime_name,
                origin="receipt",
                dispatched=True,
            )
            raise
        except (TypeError, ValueError):
            _mark_cell_failure(
                state_path,
                state,
                runtime_name,
                origin="receipt",
                dispatched=True,
            )
            raise GitHubProofError("child_receipt_invalid") from None
        update_proof_cell(
            state,
            runtime_name,
            phase="identified",
            commentId=child_receipt["commentId"],
            readPassed=True,
            approvedCommentPassed=True,
        )
        write_private_json(state_path, state)
        try:
            async with control_factory(token) as control:
                comment = await control.get_comment(
                    state["owner"],
                    state["repository"],
                    child_receipt["commentId"],
                )
            if (
                comment is None
                or comment.get("body") != marker
                or comment.get("issueUrl") != issue_url
            ):
                raise GitHubProofError("control_readback_invalid")
            update_proof_cell(
                state,
                runtime_name,
                phase="cleanup_required",
                controlReadbackPassed=True,
            )
            write_private_json(state_path, state)
        except asyncio.CancelledError:
            _mark_cell_failure(
                state_path,
                state,
                runtime_name,
                origin="control",
                dispatched=True,
            )
            raise
        except GitHubProofError:
            _mark_cell_failure(
                state_path,
                state,
                runtime_name,
                origin="control",
                dispatched=True,
            )
            raise
    finally:
        current = validate_proof_state(
            read_private_json(state_path),
            expected_commit=state["commit"],
            expected_manifest_sha256=state["releaseManifestSha256"],
        )
        current_cell = next(
            item for item in current["cells"] if item["runtime"] == runtime_name
        )
        if current_cell["reconciliationRequired"]:
            if not await reconcile_state(
                state_path,
                state["commit"],
                environment={"KAJI_GITHUB_PROOF_TOKEN": token},
                control_factory=control_factory,
            ):
                raise GitHubProofError("cleanup_incomplete")


def _normalize_public_path(path: Path) -> Path:
    try:
        return Path(os.path.abspath(os.path.normpath(os.fspath(path))))
    except (OSError, TypeError, ValueError):
        raise GitHubProofError("path_collision") from None


def _path_identity(path: Path) -> str:
    try:
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError):
        raise GitHubProofError("path_collision") from None
    return unicodedata.normalize("NFD", os.fspath(resolved)).casefold()


def _proof_paths(
    artifacts_dir: Path,
    python_compatibility: Path,
    typescript_compatibility: Path,
    fixture_path: Path,
    state_path: Path,
    output_path: Path,
) -> tuple[Path, Path, Path, dict[str, Path]]:
    artifacts = _normalize_public_path(artifacts_dir)
    python_compatibility = _normalize_public_path(python_compatibility)
    typescript_compatibility = _normalize_public_path(typescript_compatibility)
    fixture = normalize_private_path(fixture_path)
    state = normalize_private_path(state_path)
    output = _normalize_public_path(output_path)
    if state.parent != fixture.parent:
        raise GitHubProofError("private_input_invalid")
    inputs = {
        runtime: normalize_private_path(
            state.with_name(f".{runtime}-github-input-{secrets.token_hex(16)}.json")
        )
        for runtime in ("python", "typescript")
    }
    proof_paths = [
        fixture,
        state,
        state_lock_path(state),
        output,
        python_compatibility,
        typescript_compatibility,
        *inputs.values(),
    ]
    artifact_paths = [artifacts, *(artifacts / name for name in RELEASE_FILES)]
    proof_identities = [_path_identity(path) for path in proof_paths]
    artifact_identities = [_path_identity(path) for path in artifact_paths]
    identities = [*proof_identities, *artifact_identities]
    if len(set(identities)) != len(identities) or any(
        Path(identity).is_relative_to(Path(artifact_identities[0]))
        for identity in proof_identities
    ):
        raise GitHubProofError("path_collision")
    return fixture, state, output, inputs


async def _run_proof_locked(
    *,
    artifacts_dir: Path,
    expected_commit: str,
    python_compatibility: Path,
    typescript_compatibility: Path,
    fixture_path: Path,
    state_path: Path,
    output_path: Path,
    environment: Mapping[str, str],
    prerequisite_loader: PrerequisiteLoader = validate_prerequisites,
    runtime_factory: RuntimeFactory = installed_release_runtime,
    runtime_preparer: RuntimePreparer = _prepare_runtime,
    child_runner: ChildRunner = _default_child_runner,
    control_factory: Callable[[str], Any] = GitHubProofControl,
    proof_paths: tuple[Path, Path, Path, dict[str, Path]],
) -> dict[str, Any]:
    fixture_path, state_path, output_path, input_paths = proof_paths
    prerequisites = prerequisite_loader(
        artifacts_dir,
        expected_commit,
        python_compatibility,
        typescript_compatibility,
    )
    fixture = validate_private_fixture(read_private_json(fixture_path))
    if state_path.exists():
        state = validate_proof_state(
            read_private_json(state_path),
            expected_commit=expected_commit,
            expected_manifest_sha256=prerequisites.release_manifest_sha256,
        )
        if all(cell["phase"] == "cleaned" for cell in state["cells"]):
            receipt = _output_receipt(prerequisites, state)
            _write_public_receipt(output_path, receipt)
            return receipt
        if any(cell["reconciliationRequired"] for cell in state["cells"]):
            await reconcile_state(
                state_path,
                expected_commit,
                environment=environment,
                control_factory=control_factory,
            )
        raise GitHubProofError("previous_proof_incomplete")
    token = environment.get("KAJI_GITHUB_PROOF_TOKEN", "")
    if not token:
        raise GitHubProofError("proof_token_missing")
    token = validate_proof_token(token)
    state = new_proof_state(
        commit=expected_commit,
        release_manifest_sha256=prerequisites.release_manifest_sha256,
        owner=fixture["owner"],
        repository=fixture["repository"],
        issue_number=fixture["issueNumber"],
        markers={
            runtime_name: (
                f"kaji-proof/{expected_commit}/{runtime_name}/{secrets.token_hex(16)}"
            )
            for runtime_name in ("python", "typescript")
        },
    )
    write_private_json(state_path, state)
    if output_path.exists():
        try:
            if output_path.is_symlink() or not output_path.is_file():
                raise OSError
            output_path.unlink()
        except OSError:
            raise GitHubProofError("public_receipt_invalid") from None

    try:
        with runtime_factory(
            artifacts_dir,
            expected_commit=expected_commit,
            include_openai=False,
        ) as runtime:
            _validate_runtime_identity(runtime, prerequisites)
            runtime_preparer(runtime)
            for runtime_name in ("python", "typescript"):
                state = validate_proof_state(
                    read_private_json(state_path),
                    expected_commit=expected_commit,
                    expected_manifest_sha256=prerequisites.release_manifest_sha256,
                )
                await _run_cell(
                    state_path=state_path,
                    state=state,
                    runtime=runtime,
                    runtime_name=runtime_name,
                    input_path=input_paths[runtime_name],
                    token=token,
                    child_runner=child_runner,
                    control_factory=control_factory,
                )
    except GitHubProofError:
        raise
    except (CommandError, OSError, RuntimeError):
        raise GitHubProofError("installed_runtime_invalid") from None
    state = validate_proof_state(
        read_private_json(state_path),
        expected_commit=expected_commit,
        expected_manifest_sha256=prerequisites.release_manifest_sha256,
    )
    receipt = _output_receipt(prerequisites, state)
    _write_public_receipt(output_path, receipt)
    return receipt


async def run_proof(
    *,
    artifacts_dir: Path,
    expected_commit: str,
    python_compatibility: Path,
    typescript_compatibility: Path,
    fixture_path: Path,
    state_path: Path,
    output_path: Path,
    environment: Mapping[str, str],
    prerequisite_loader: PrerequisiteLoader = validate_prerequisites,
    runtime_factory: RuntimeFactory = installed_release_runtime,
    runtime_preparer: RuntimePreparer = _prepare_runtime,
    child_runner: ChildRunner = _default_child_runner,
    control_factory: Callable[[str], Any] = GitHubProofControl,
) -> dict[str, Any]:
    proof_paths = _proof_paths(
        artifacts_dir,
        python_compatibility,
        typescript_compatibility,
        fixture_path,
        state_path,
        output_path,
    )
    with private_state_lock(proof_paths[1]):
        return await _run_proof_locked(
            artifacts_dir=artifacts_dir,
            expected_commit=expected_commit,
            python_compatibility=python_compatibility,
            typescript_compatibility=typescript_compatibility,
            fixture_path=fixture_path,
            state_path=state_path,
            output_path=output_path,
            environment=environment,
            prerequisite_loader=prerequisite_loader,
            runtime_factory=runtime_factory,
            runtime_preparer=runtime_preparer,
            child_runner=child_runner,
            control_factory=control_factory,
            proof_paths=proof_paths,
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", required=True, type=Path)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--python-compat", required=True, type=Path)
    parser.add_argument("--typescript-compat", required=True, type=Path)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        asyncio.run(
            run_proof(
                artifacts_dir=args.artifacts_dir,
                expected_commit=args.expected_commit,
                python_compatibility=args.python_compat,
                typescript_compatibility=args.typescript_compat,
                fixture_path=args.fixture,
                state_path=args.state,
                output_path=args.output,
                environment=os.environ,
            )
        )
    except (GitHubProofError, OSError):
        print("GitHub proof failed", file=sys.stderr)
        return 1
    print("GitHub exact-artifact proof passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
