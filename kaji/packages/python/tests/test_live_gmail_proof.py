"""Self-check for the live_gmail_proof.py skeleton.

Proves the parts that ARE real today: the receipt shape validates against the
shipped public schema, a tampered receipt is rejected, and the skeleton fails
closed (never emits a passing receipt) because every live step is stubbed.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "kaji" / "scripts"


def _load_proof():
    spec = importlib.util.spec_from_file_location(
        "live_gmail_proof", SCRIPTS / "live_gmail_proof.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["live_gmail_proof"] = module
    spec.loader.exec_module(module)
    return module


proof = _load_proof()


def _good_receipt() -> dict:
    return proof.build_receipt(
        commit="0" * 40,
        release_manifest_sha256="a" * 64,
        python_cell=proof.build_cell(
            runtime="python", artifact_sha256="b" * 64, package_proof_sha256="c" * 64
        ),
        typescript_cell=proof.build_cell(
            runtime="typescript",
            artifact_sha256="d" * 64,
            package_proof_sha256="e" * 64,
        ),
    )


def test_wellformed_receipt_matches_shipped_schema() -> None:
    proof.validate_receipt(_good_receipt())  # must not raise


def test_tampered_receipt_is_rejected() -> None:
    bad = _good_receipt()
    bad["approvedSendPassed"] = False  # schema pins this const True
    try:
        proof.validate_receipt(bad)
    except proof.GmailProofError:
        return
    raise AssertionError("tampered receipt was not rejected")


def test_wrong_cell_order_is_rejected() -> None:
    receipt = _good_receipt()
    receipt["cells"] = list(reversed(receipt["cells"]))  # schema pins py then ts
    try:
        proof.validate_receipt(receipt)
    except proof.GmailProofError:
        return
    raise AssertionError("reversed cells were not rejected")


def test_bad_cell_runtime_raises() -> None:
    try:
        proof.build_cell(runtime="ruby", artifact_sha256="", package_proof_sha256="")
    except proof.GmailProofError:
        return
    raise AssertionError("invalid cell runtime was accepted")


def test_skeleton_fails_closed() -> None:
    # main() must exit 2 (OperatorTodo), proving it never reports a pass.
    code = proof.main(
        [
            "--artifacts-dir",
            "/nonexistent",
            "--expected-commit",
            "0" * 40,
            "--python-compat",
            "/nonexistent/py.json",
            "--typescript-compat",
            "/nonexistent/ts.json",
            "--fixture",
            "/nonexistent/fixture.json",
            "--state",
            "/nonexistent/state.json",
            "--output",
            "/nonexistent/out.json",
        ]
    )
    assert code == 2, f"expected fail-closed exit 2, got {code}"
