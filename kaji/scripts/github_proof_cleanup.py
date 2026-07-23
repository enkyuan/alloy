#!/usr/bin/env python3
"""Idempotently reconcile private GitHub proof comment state."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Mapping
import os
from pathlib import Path
import sys
from typing import Any, Protocol

from github_proof_control import (
    GitHubProofControl,
    GitHubProofError,
    canonical_issue_url,
    normalize_private_path,
    private_state_lock,
    read_private_json,
    update_proof_cell,
    validate_proof_token,
    validate_proof_state,
    write_private_json,
)


class _Control(Protocol):
    async def __aenter__(self) -> _Control: ...
    async def __aexit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: object,
    ) -> None: ...
    async def list_issue_comments(
        self, owner: str, repository: str, issue_number: int
    ) -> list[dict[str, Any]]: ...
    async def get_comment(
        self, owner: str, repository: str, comment_id: int
    ) -> dict[str, Any] | None: ...
    async def delete_comment(
        self, owner: str, repository: str, comment_id: int
    ) -> None: ...


_ControlFactory = Callable[[str], _Control]


def _control_factory(token: str) -> _Control:
    return GitHubProofControl(token)


def _write(path: Path, state: dict[str, Any], expected_commit: str) -> None:
    validate_proof_state(state, expected_commit=expected_commit)
    write_private_json(path, state)


def _mark_cleanup_failure(
    path: Path,
    state: dict[str, Any],
    runtime: str,
    expected_commit: str,
) -> None:
    cell = update_proof_cell(
        state,
        runtime,
        phase="failed",
        reconciliationRequired=True,
        failureOrigin="cleanup",
    )
    if not cell["dispatchAttempted"]:
        cell["reconciliationRequired"] = False
    _write(path, state, expected_commit)


def _marker_matches(
    comments: list[dict[str, Any]],
    marker: str,
    issue_url: str,
) -> list[dict[str, Any]]:
    if any(comment.get("issueUrl") != issue_url for comment in comments):
        raise GitHubProofError("cleanup_issue_mismatch")
    matches = [comment for comment in comments if comment.get("body") == marker]
    if len(matches) > 1:
        raise GitHubProofError("cleanup_ambiguous")
    return matches


async def _cleanup_cell(
    path: Path,
    state: dict[str, Any],
    cell: dict[str, Any],
    control: _Control,
    expected_commit: str,
    *,
    confirm_absence: bool,
) -> bool:
    runtime = cell["runtime"]
    owner = state["owner"]
    repository = state["repository"]
    issue_number = state["issueNumber"]
    marker = cell["marker"]
    issue_url = canonical_issue_url(owner, repository, issue_number)
    was_successful = cell["failureOrigin"] is None and cell["phase"] in {
        "identified",
        "cleanup_required",
    }
    comment_id = cell["commentId"]
    comment: dict[str, Any] | None = None

    if comment_id is not None:
        candidate = await control.get_comment(owner, repository, comment_id)
        if candidate is not None and candidate.get("body") == marker:
            if candidate.get("issueUrl") != issue_url:
                raise GitHubProofError("cleanup_issue_mismatch")
            comment = candidate

    comments = await control.list_issue_comments(owner, repository, issue_number)
    matches = _marker_matches(comments, marker, issue_url)
    if comment is not None and matches and matches[0]["id"] != comment_id:
        raise GitHubProofError("cleanup_ambiguous")
    if not matches:
        if comment is None:
            update_proof_cell(
                state,
                runtime,
                phase="failed",
                reconciliationRequired=not confirm_absence,
                commentId=None,
                failureOrigin=cell["failureOrigin"] or "interrupted",
                absenceObserved=True,
            )
            _write(path, state, expected_commit)
            return False
    elif comment is None:
        selected_id = matches[0]["id"]
        if selected_id != comment_id:
            comment_id = selected_id
            update_proof_cell(
                state,
                runtime,
                phase="identified" if cell["failureOrigin"] is None else "failed",
                commentId=comment_id,
                absenceObserved=False,
            )
            _write(path, state, expected_commit)
            comment = None
    if comment is None:
        comment = await control.get_comment(owner, repository, comment_id)

    if (
        comment is None
        or comment.get("body") != marker
        or comment.get("issueUrl") != issue_url
    ):
        raise GitHubProofError("cleanup_verification_failed")
    await control.delete_comment(owner, repository, comment_id)
    if await control.get_comment(owner, repository, comment_id) is not None:
        raise GitHubProofError("cleanup_verification_failed")
    remaining = await control.list_issue_comments(owner, repository, issue_number)
    if _marker_matches(remaining, marker, issue_url):
        raise GitHubProofError("cleanup_verification_failed")

    if was_successful:
        update_proof_cell(
            state,
            runtime,
            phase="cleaned",
            reconciliationRequired=False,
            absenceObserved=False,
        )
        _write(path, state, expected_commit)
        return True
    update_proof_cell(
        state,
        runtime,
        phase="failed",
        reconciliationRequired=False,
        failureOrigin=cell["failureOrigin"] or "interrupted",
        absenceObserved=False,
    )
    _write(path, state, expected_commit)
    return False


async def reconcile_state(
    state_path: Path,
    expected_commit: str,
    *,
    environment: Mapping[str, str] | None = None,
    control_factory: _ControlFactory = _control_factory,
    confirm_absence: bool = False,
) -> bool:
    state_path = normalize_private_path(state_path)
    state = validate_proof_state(
        read_private_json(state_path), expected_commit=expected_commit
    )
    pending = [cell for cell in state["cells"] if cell["reconciliationRequired"]]
    if not pending:
        return all(cell["phase"] == "cleaned" for cell in state["cells"])
    if confirm_absence and any(not cell["absenceObserved"] for cell in pending):
        raise GitHubProofError("absence_confirmation_unavailable")
    source = os.environ if environment is None else environment
    token = source.get("KAJI_GITHUB_PROOF_TOKEN", "")
    if not token:
        raise GitHubProofError("proof_token_missing")
    token = validate_proof_token(token)

    successful = True
    async with control_factory(token) as control:
        for cell in pending:
            try:
                successful = (
                    await _cleanup_cell(
                        state_path,
                        state,
                        cell,
                        control,
                        expected_commit,
                        confirm_absence=confirm_absence,
                    )
                    and successful
                )
            except asyncio.CancelledError:
                _mark_cleanup_failure(
                    state_path, state, cell["runtime"], expected_commit
                )
                raise
            except GitHubProofError:
                _mark_cleanup_failure(
                    state_path, state, cell["runtime"], expected_commit
                )
                raise
    return successful


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--confirm-absence", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        with private_state_lock(args.state):
            successful = asyncio.run(
                reconcile_state(
                    args.state,
                    args.expected_commit,
                    confirm_absence=args.confirm_absence,
                )
            )
    except (GitHubProofError, OSError):
        print("GitHub proof cleanup failed", file=sys.stderr)
        return 1
    if not successful:
        print("GitHub proof cleanup completed after a failed proof", file=sys.stderr)
        return 1
    print("GitHub proof cleanup completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
