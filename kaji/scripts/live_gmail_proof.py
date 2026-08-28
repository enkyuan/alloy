#!/usr/bin/env python3
"""Run the protected exact-artifact Gmail send proof and cleanup.

STATUS: executable spec + skeleton, NOT a runnable proof yet.

This mirrors ``kaji/scripts/live_github_proof.py`` for Gmail. It ships as a
skeleton on purpose: the credentialed Gmail API calls, the OAuth token
resolution, and the per-SDK installed-runtime child runners can only be written
and validated against the live Gmail API on the real release commit, inside the
``kaji-release`` protected environment. See docs/kaji/NEXT.md (manual runbook).

What IS real and testable here now:
  * the CLI surface (mirrors the GitHub proof's flags exactly),
  * the receipt shape and its validation against the shipped contract
    ``kaji/contracts/release/gmail-proof-v1.schema.json``,
  * the ordered proof sequence, encoded as functions with explicit contracts.

What is STUBBED (raises OperatorTodo so it fails closed, never a silent pass):
  * prerequisite / compatibility-receipt validation (port from the GitHub proof),
  * the installed-runtime child runners (installed_gmail_live.py /
    installed-gmail-live.mts -- do not exist yet),
  * every live Gmail API call (get_message, send_message, read-back, delete),
  * the exclusive owner-lock + pending-absence cleanup (port
    github_proof_control.py / github_proof_cleanup.py).

The GitHub proof (and its ~1600 lines of control/cleanup/child-runner helpers)
is the reference. Port it deliberately, not by blind copy: it is a moving target
on the release branch, and Gmail differs from GitHub in ways this file flags
inline (notably: the Gmail client exposes no delete; cleanup deletes the proof
message through a raw authorized Gmail API call).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PUBLIC_SCHEMA = ROOT / "kaji" / "contracts" / "release" / "gmail-proof-v1.schema.json"

# Release artifact names. Keep in lockstep with live_github_proof.py; the beta
# tag drives these. (TS tarball tracks beta.11; Python wheel/sdist track 0.2.0b1.)
PYTHON_WHEEL = "kaji-0.2.0b1-py3-none-any.whl"
PYTHON_SDIST = "kaji-0.2.0b1.tar.gz"
TYPESCRIPT_TARBALL = "kaji-0.2.0-beta.11.tgz"

# Child runners that must exist before this proof can run. Neither is written.
PYTHON_RUNNER = ROOT / "kaji" / "scripts" / "installed_gmail_live.py"
TYPESCRIPT_RUNNER = (
    ROOT / "kaji" / "packages" / "ts" / "scripts" / "installed-gmail-live.mts"
)


class GmailProofError(RuntimeError):
    """A deterministic Gmail proof failure. Mirrors GitHubProofError."""


class OperatorTodo(GmailProofError):
    """A step that must be implemented by the operator in the protected window.

    Distinct type so a test can assert the skeleton fails closed at exactly the
    unimplemented boundaries, never reporting a pass without doing the work.
    """


# ---------------------------------------------------------------------------
# Receipt shape (REAL: validated against the shipped public schema).
# ---------------------------------------------------------------------------


def build_receipt(
    *,
    commit: str,
    release_manifest_sha256: str,
    python_cell: dict[str, Any],
    typescript_cell: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the redacted proof receipt.

    The literal booleans below are the proof's success contract: a real run must
    only reach this call after each corresponding step passed. They are asserted
    by the public schema (every one is a ``const``), so a receipt built with any
    other value fails ``validate_receipt`` immediately.
    """
    return {
        "schemaVersion": "1.0.0",
        "commit": commit,
        "releaseManifestSha256": release_manifest_sha256,
        "cells": [python_cell, typescript_cell],
        "approvalRejectedBeforeTransport": True,
        "readPassed": True,
        "approvedSendPassed": True,
        "controlReadbackPassed": True,
        "ambiguousMutationRetried": False,
        "cleanup": {"required": True, "conclusion": "passed"},
        "redacted": True,
    }


def build_cell(
    *, runtime: str, artifact_sha256: str, package_proof_sha256: str
) -> dict[str, Any]:
    """One per-SDK proof cell. ``runtime`` is 'python' or 'typescript'."""
    if runtime not in {"python", "typescript"}:
        raise GmailProofError("cell_runtime_invalid")
    return {
        "runtime": runtime,
        "artifactSha256": artifact_sha256,
        "packageProofSha256": package_proof_sha256,
        "conclusion": "passed",
    }


def validate_receipt(receipt: dict[str, Any]) -> None:
    """Validate a receipt against the shipped public schema. REAL check.

    Uses jsonschema like the GitHub proof. This is the one guarantee the
    skeleton fully enforces today: whatever the finished proof emits must satisfy
    gmail-proof-v1.schema.json or this raises.
    """
    try:
        from jsonschema import Draft202012Validator
    except ModuleNotFoundError as error:  # pragma: no cover - env guard
        raise GmailProofError("jsonschema_unavailable") from error
    schema = json.loads(PUBLIC_SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(receipt),
        key=lambda err: list(err.absolute_path),
    )
    if errors:
        pointer = "/" + "/".join(str(part) for part in errors[0].absolute_path)
        raise GmailProofError(f"receipt_invalid at {pointer}: {errors[0].message}")


# ---------------------------------------------------------------------------
# Proof sequence (SPEC: ordered steps; live calls are OperatorTodo stubs).
# Each function documents its exact contract so the operator ports the GitHub
# equivalent into it rather than re-deriving the sequence.
# ---------------------------------------------------------------------------


def validate_prerequisites(
    artifacts_dir: Path, expected_commit: str, python_compat: Path, ts_compat: Path
) -> Any:
    """STEP 0. Verify release artifacts + both compatibility receipts.

    Port ``validate_prerequisites`` from live_github_proof.py: verify the wheel,
    sdist, and tarball hashes against a signed release manifest for
    ``expected_commit``, and validate the Python/TypeScript compatibility
    receipts share one workflow run. Gmail-specific: none -- this step is
    provider-agnostic, so it is a near-verbatim port.
    """
    raise OperatorTodo(
        "port validate_prerequisites from live_github_proof.py "
        f"(artifacts_dir={artifacts_dir}, commit={expected_commit})"
    )


def run_child_read_and_send(runtime: str, runner: Path) -> dict[str, Any]:
    """STEP 1-3 per SDK. Drive one installed-runtime child through the loop.

    The child (installed_gmail_live.py / installed-gmail-live.mts -- NOT written)
    must, from the installed artifact only:
      1. get_message on the owner fixture message (read passes),
      2. attempt an UNAPPROVED send and confirm it is rejected before transport
         (approvalRejectedBeforeTransport),
      3. perform exactly one APPROVED gmail.send_message (approvedSendPassed),
      4. return the sent message id so the parent can read it back and delete it.
    Return a child receipt the parent validates (mirror validate_child_receipt).
    """
    raise OperatorTodo(
        f"write and invoke the {runtime} installed-runtime child runner at {runner}"
    )


def control_readback(sent_message_id: str) -> None:
    """STEP 4. Independently read the sent message back (controlReadbackPassed).

    Uses the owner OAuth grant directly (not the child), proving the send landed
    in the real mailbox. Port the GitHub control-readback path.
    """
    raise OperatorTodo(f"read back sent message {sent_message_id} via owner grant")


def cleanup_delete(sent_message_id: str) -> None:
    """STEP 5. Delete the proof message; cleanup must conclude 'passed'.

    GMAIL DIFFERENCE (flag): the Gmail *client* exposes no delete
    (registry/gmail/client.py has list_messages/get_message/send_message only).
    Cleanup must call the raw Gmail API (messages.delete or messages.trash) with
    the owner grant, then confirm absence -- do not add delete to the shipped
    client just for the proof. Port the exclusive owner-lock + pending-absence
    semantics from github_proof_cleanup.py so a concurrent run fails before
    transport and an unconfirmed delete stays pending for manual review.
    """
    raise OperatorTodo(
        f"delete proof message {sent_message_id} via raw Gmail API + confirm absence"
    )


def run_proof(
    *,
    artifacts_dir: Path,
    expected_commit: str,
    python_compatibility: Path,
    typescript_compatibility: Path,
    fixture_path: Path,
    state_path: Path,
    output_path: Path,
    environment: Any,
) -> None:
    """Full proof. Ordered exactly like the GitHub proof; live steps are stubs.

    A finished implementation writes the schema-valid receipt from build_receipt
    to output_path only after every step below has genuinely passed. The stubs
    guarantee this skeleton can never emit a passing receipt.
    """
    prerequisites = validate_prerequisites(
        artifacts_dir, expected_commit, python_compatibility, typescript_compatibility
    )
    children = {
        "python": run_child_read_and_send("python", PYTHON_RUNNER),
        "typescript": run_child_read_and_send("typescript", TYPESCRIPT_RUNNER),
    }
    # Each SDK sends its own proof message; read back and delete both.
    for runtime, child in children.items():
        sent_id = str(child.get("sentMessageId"))
        control_readback(sent_id)
        cleanup_delete(sent_id)
    receipt = build_receipt(
        commit=expected_commit,
        release_manifest_sha256=prerequisites.manifest_sha256,
        python_cell=build_cell(
            runtime="python", artifact_sha256="", package_proof_sha256=""
        ),
        typescript_cell=build_cell(
            runtime="typescript", artifact_sha256="", package_proof_sha256=""
        ),
    )
    validate_receipt(receipt)
    output_path.write_bytes(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )


# ---------------------------------------------------------------------------
# CLI (REAL: mirrors live_github_proof.py exactly so the runbook is identical).
# ---------------------------------------------------------------------------


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
    import os

    try:
        args = parse_args(argv)
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
    except OperatorTodo as todo:
        print(f"Gmail proof is a skeleton; unimplemented step: {todo}", file=sys.stderr)
        return 2
    except (GmailProofError, OSError):
        print("Gmail proof failed", file=sys.stderr)
        return 1
    print("Gmail exact-artifact proof passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
