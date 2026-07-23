from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "kaji" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from github_proof_cleanup import (  # noqa: E402  # ty: ignore[unresolved-import]
    main as cleanup_main,
    parse_args,
    reconcile_state,
)
from github_proof_control import (  # noqa: E402  # ty: ignore[unresolved-import]
    GitHubProofError,
    new_proof_state,
    private_state_lock,
    read_private_json,
    update_proof_cell,
    write_private_json,
)


COMMIT = "a" * 40
MANIFEST = "b" * 64
ISSUE_URL = "https://api.github.com/repos/octo/widgets/issues/7"


def _comment(
    comment_id: int,
    body: str,
    *,
    issue_number: int = 7,
) -> dict[str, Any]:
    return {
        "id": comment_id,
        "body": body,
        "issueUrl": (
            f"https://api.github.com/repos/octo/widgets/issues/{issue_number}"
        ),
    }


def _state_path(tmp_path: Path) -> Path:
    directory = tmp_path / ".artifacts" / "private"
    directory.mkdir(parents=True, mode=0o700)
    os.chmod(directory, 0o700)
    return directory / "github-state.json"


def _state(tmp_path: Path) -> Path:
    path = _state_path(tmp_path)
    state = new_proof_state(
        commit=COMMIT,
        release_manifest_sha256=MANIFEST,
        owner="octo",
        repository="widgets",
        issue_number=7,
        markers={
            "python": f"kaji-proof/{COMMIT}/python/{'1' * 32}",
            "typescript": f"kaji-proof/{COMMIT}/typescript/{'2' * 32}",
        },
    )
    write_private_json(path, state)
    return path


def _transition(path: Path, runtime: str, **changes: Any) -> None:
    state = read_private_json(path)
    update_proof_cell(state, runtime, **changes)
    write_private_json(path, state)


class FakeControl:
    def __init__(
        self,
        comments: list[dict[str, Any]],
        *,
        listed_comments: list[dict[str, Any]] | None = None,
        delete_error: GitHubProofError | None = None,
        list_error: GitHubProofError | None = None,
    ) -> None:
        self.comments = list(comments)
        self.listed_comments = (
            self.comments if listed_comments is None else list(listed_comments)
        )
        self.delete_error = delete_error
        self.list_error = list_error
        self.calls: list[tuple[Any, ...]] = []

    async def __aenter__(self) -> FakeControl:
        return self

    async def __aexit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: object,
    ) -> None:
        return None

    async def list_issue_comments(
        self, owner: str, repository: str, issue_number: int
    ) -> list[dict[str, Any]]:
        self.calls.append(("list", owner, repository, issue_number))
        if self.list_error is not None:
            raise self.list_error
        return list(self.listed_comments)

    async def get_comment(
        self, owner: str, repository: str, comment_id: int
    ) -> dict[str, Any] | None:
        self.calls.append(("get", owner, repository, comment_id))
        return next(
            (comment for comment in self.comments if comment["id"] == comment_id),
            None,
        )

    async def delete_comment(
        self, owner: str, repository: str, comment_id: int
    ) -> None:
        self.calls.append(("delete", owner, repository, comment_id))
        if self.delete_error is not None:
            raise self.delete_error
        self.comments = [
            comment for comment in self.comments if comment["id"] != comment_id
        ]
        self.listed_comments = [
            comment for comment in self.listed_comments if comment["id"] != comment_id
        ]


@pytest.mark.asyncio
async def test_cleaned_state_is_token_and_network_free_noop(tmp_path: Path) -> None:
    path = _state(tmp_path)
    for runtime in ("python", "typescript"):
        _transition(
            path,
            runtime,
            phase="cleaned",
            dispatchAttempted=True,
            reconciliationRequired=False,
            commentId=7 if runtime == "python" else 8,
            readPassed=True,
            approvedCommentPassed=True,
            controlReadbackPassed=True,
        )
    factories = 0

    def factory(_token: str) -> FakeControl:
        nonlocal factories
        factories += 1
        return FakeControl([])

    assert await reconcile_state(
        path,
        COMMIT,
        environment={},
        control_factory=factory,
    )
    assert factories == 0


@pytest.mark.asyncio
async def test_cleanup_without_id_keeps_zero_match_pending_for_confirmation(
    tmp_path: Path,
) -> None:
    path = _state(tmp_path)
    _transition(
        path,
        "python",
        phase="dispatched",
        dispatchAttempted=True,
        reconciliationRequired=True,
    )
    control = FakeControl([])

    assert not await reconcile_state(
        path,
        COMMIT,
        environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
        control_factory=lambda _token: control,
    )
    state = read_private_json(path)
    cell = state["cells"][0]
    assert cell["phase"] == "failed"
    assert cell["failureOrigin"] == "interrupted"
    assert cell["reconciliationRequired"] is True
    assert cell["absenceObserved"] is True
    assert control.calls == [("list", "octo", "widgets", 7)]


@pytest.mark.asyncio
async def test_cleanup_rechecks_delayed_visibility_without_retrying_mutation(
    tmp_path: Path,
) -> None:
    path = _state(tmp_path)
    _transition(
        path,
        "python",
        phase="dispatched",
        dispatchAttempted=True,
        reconciliationRequired=True,
    )
    first = FakeControl([])
    assert not await reconcile_state(
        path,
        COMMIT,
        environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
        control_factory=lambda _token: first,
    )
    marker = read_private_json(path)["cells"][0]["marker"]
    delayed = FakeControl([_comment(91, marker)])

    assert not await reconcile_state(
        path,
        COMMIT,
        environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
        control_factory=lambda _token: delayed,
    )
    cell = read_private_json(path)["cells"][0]
    assert cell["phase"] == "failed"
    assert cell["commentId"] == 91
    assert cell["reconciliationRequired"] is False
    assert delayed.comments == []
    assert all(call[0] != "post" for call in [*first.calls, *delayed.calls])


@pytest.mark.asyncio
async def test_repeated_zero_without_confirmation_stays_pending(
    tmp_path: Path,
) -> None:
    path = _state(tmp_path)
    _transition(
        path,
        "python",
        phase="dispatched",
        dispatchAttempted=True,
        reconciliationRequired=True,
    )
    for _attempt in range(2):
        control = FakeControl([])
        assert not await reconcile_state(
            path,
            COMMIT,
            environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
            control_factory=lambda _token, selected=control: selected,
        )
        assert control.calls == [("list", "octo", "widgets", 7)]
        cell = read_private_json(path)["cells"][0]
        assert cell["reconciliationRequired"] is True
        assert cell["absenceObserved"] is True


@pytest.mark.asyncio
async def test_explicit_confirmed_second_absence_clears_reconciliation(
    tmp_path: Path,
) -> None:
    path = _state(tmp_path)
    _transition(
        path,
        "python",
        phase="dispatched",
        dispatchAttempted=True,
        reconciliationRequired=True,
    )
    first = FakeControl([])
    assert not await reconcile_state(
        path,
        COMMIT,
        environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
        control_factory=lambda _token: first,
    )
    confirmation = FakeControl([])
    assert not await reconcile_state(
        path,
        COMMIT,
        environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
        control_factory=lambda _token: confirmation,
        confirm_absence=True,
    )
    cell = read_private_json(path)["cells"][0]
    assert cell["phase"] == "failed"
    assert cell["reconciliationRequired"] is False
    assert cell["absenceObserved"] is True
    assert confirmation.calls == [("list", "octo", "widgets", 7)]


@pytest.mark.asyncio
async def test_absence_confirmation_requires_a_prior_zero_without_network(
    tmp_path: Path,
) -> None:
    path = _state(tmp_path)
    _transition(
        path,
        "python",
        phase="dispatched",
        dispatchAttempted=True,
        reconciliationRequired=True,
    )
    factories = 0

    def factory(_token: str) -> FakeControl:
        nonlocal factories
        factories += 1
        return FakeControl([])

    with pytest.raises(GitHubProofError, match="absence_confirmation_unavailable"):
        await reconcile_state(
            path,
            COMMIT,
            environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
            control_factory=factory,
            confirm_absence=True,
        )
    assert factories == 0


@pytest.mark.asyncio
async def test_cleanup_without_id_persists_single_match_before_delete(
    tmp_path: Path,
) -> None:
    path = _state(tmp_path)
    _transition(
        path,
        "python",
        phase="dispatched",
        dispatchAttempted=True,
        reconciliationRequired=True,
    )
    marker = read_private_json(path)["cells"][0]["marker"]
    control = FakeControl([_comment(91, marker)])

    assert not await reconcile_state(
        path,
        COMMIT,
        environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
        control_factory=lambda _token: control,
    )
    cell = read_private_json(path)["cells"][0]
    assert cell["commentId"] == 91
    assert cell["phase"] == "failed"
    assert cell["failureOrigin"] == "interrupted"
    assert cell["reconciliationRequired"] is False
    assert control.calls == [
        ("list", "octo", "widgets", 7),
        ("get", "octo", "widgets", 91),
        ("delete", "octo", "widgets", 91),
        ("get", "octo", "widgets", 91),
        ("list", "octo", "widgets", 7),
    ]


@pytest.mark.asyncio
async def test_cleanup_fails_closed_on_duplicate_or_ambiguous_enumeration(
    tmp_path: Path,
) -> None:
    for label, control in (
        (
            "duplicate",
            FakeControl(
                [
                    _comment(91, "placeholder"),
                    _comment(92, "placeholder"),
                ]
            ),
        ),
        (
            "pagination",
            FakeControl([], list_error=GitHubProofError("control_list_ambiguous")),
        ),
    ):
        path = _state(tmp_path / label)
        _transition(
            path,
            "python",
            phase="dispatched",
            dispatchAttempted=True,
            reconciliationRequired=True,
        )
        if label == "duplicate":
            marker = read_private_json(path)["cells"][0]["marker"]
            for comment in control.comments:
                comment["body"] = marker
        with pytest.raises(GitHubProofError):
            await reconcile_state(
                path,
                COMMIT,
                environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
                control_factory=lambda _token, selected=control: selected,
            )
        cell = read_private_json(path)["cells"][0]
        assert cell["phase"] == "failed"
        assert cell["failureOrigin"] == "cleanup"
        assert cell["reconciliationRequired"] is True


@pytest.mark.asyncio
async def test_cleanup_with_id_requires_exact_marker_then_verifies_absence(
    tmp_path: Path,
) -> None:
    path = _state(tmp_path)
    marker = read_private_json(path)["cells"][0]["marker"]
    _transition(
        path,
        "python",
        phase="cleanup_required",
        dispatchAttempted=True,
        reconciliationRequired=True,
        commentId=91,
        readPassed=True,
        approvedCommentPassed=True,
        controlReadbackPassed=True,
    )
    control = FakeControl([_comment(91, marker)])

    assert await reconcile_state(
        path,
        COMMIT,
        environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
        control_factory=lambda _token: control,
    )
    cell = read_private_json(path)["cells"][0]
    assert cell["phase"] == "cleaned"
    assert cell["reconciliationRequired"] is False
    assert control.calls == [
        ("get", "octo", "widgets", 91),
        ("list", "octo", "widgets", 7),
        ("delete", "octo", "widgets", 91),
        ("get", "octo", "widgets", 91),
        ("list", "octo", "widgets", 7),
    ]


@pytest.mark.asyncio
async def test_cleanup_verified_id_dominates_a_stale_empty_issue_list(
    tmp_path: Path,
) -> None:
    path = _state(tmp_path)
    marker = read_private_json(path)["cells"][0]["marker"]
    _transition(
        path,
        "python",
        phase="cleanup_required",
        dispatchAttempted=True,
        reconciliationRequired=True,
        commentId=91,
        readPassed=True,
        approvedCommentPassed=True,
        controlReadbackPassed=True,
    )
    control = FakeControl(
        [_comment(91, marker)],
        listed_comments=[],
    )

    assert await reconcile_state(
        path,
        COMMIT,
        environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
        control_factory=lambda _token: control,
    )
    cell = read_private_json(path)["cells"][0]
    assert cell["phase"] == "cleaned"
    assert cell["commentId"] == 91
    assert cell["reconciliationRequired"] is False
    assert cell["absenceObserved"] is False
    assert control.comments == []
    assert control.calls == [
        ("get", "octo", "widgets", 91),
        ("list", "octo", "widgets", 7),
        ("delete", "octo", "widgets", 91),
        ("get", "octo", "widgets", 91),
        ("list", "octo", "widgets", 7),
    ]


@pytest.mark.asyncio
async def test_cleanup_with_id_rejects_duplicate_marker_before_delete(
    tmp_path: Path,
) -> None:
    path = _state(tmp_path)
    marker = read_private_json(path)["cells"][0]["marker"]
    _transition(
        path,
        "python",
        phase="cleanup_required",
        dispatchAttempted=True,
        reconciliationRequired=True,
        commentId=91,
        readPassed=True,
        approvedCommentPassed=True,
        controlReadbackPassed=True,
    )
    control = FakeControl([_comment(91, marker), _comment(92, marker)])

    with pytest.raises(GitHubProofError, match="cleanup_ambiguous"):
        await reconcile_state(
            path,
            COMMIT,
            environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
            control_factory=lambda _token: control,
        )

    assert all(call[0] != "delete" for call in control.calls)
    assert read_private_json(path)["cells"][0]["reconciliationRequired"] is True


@pytest.mark.asyncio
async def test_cleanup_verified_id_rejects_a_conflicting_listed_marker(
    tmp_path: Path,
) -> None:
    path = _state(tmp_path)
    marker = read_private_json(path)["cells"][0]["marker"]
    _transition(
        path,
        "python",
        phase="cleanup_required",
        dispatchAttempted=True,
        reconciliationRequired=True,
        commentId=91,
        readPassed=True,
        approvedCommentPassed=True,
        controlReadbackPassed=True,
    )
    exact = _comment(91, marker)
    listed = _comment(92, marker)
    control = FakeControl([exact, listed], listed_comments=[listed])

    with pytest.raises(GitHubProofError, match="cleanup_ambiguous"):
        await reconcile_state(
            path,
            COMMIT,
            environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
            control_factory=lambda _token: control,
        )

    cell = read_private_json(path)["cells"][0]
    assert cell["commentId"] == 91
    assert cell["reconciliationRequired"] is True
    assert all(call[0] != "delete" for call in control.calls)
    assert control.comments == [exact, listed]


@pytest.mark.asyncio
async def test_cleanup_verifies_marker_wide_absence_after_delete(
    tmp_path: Path,
) -> None:
    path = _state(tmp_path)
    marker = read_private_json(path)["cells"][0]["marker"]
    _transition(
        path,
        "python",
        phase="cleanup_required",
        dispatchAttempted=True,
        reconciliationRequired=True,
        commentId=91,
        readPassed=True,
        approvedCommentPassed=True,
        controlReadbackPassed=True,
    )

    class ConcurrentControl(FakeControl):
        async def delete_comment(
            self, owner: str, repository: str, comment_id: int
        ) -> None:
            await super().delete_comment(owner, repository, comment_id)
            self.comments.append(_comment(92, marker))
            self.listed_comments.append(_comment(92, marker))

    control = ConcurrentControl([_comment(91, marker)])
    with pytest.raises(GitHubProofError, match="cleanup_verification_failed"):
        await reconcile_state(
            path,
            COMMIT,
            environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
            control_factory=lambda _token: control,
        )

    assert [comment["id"] for comment in control.comments] == [92]
    assert read_private_json(path)["cells"][0]["reconciliationRequired"] is True


@pytest.mark.asyncio
async def test_cleanup_known_marker_on_wrong_issue_stays_pending_for_manual_review(
    tmp_path: Path,
) -> None:
    path = _state(tmp_path)
    marker = read_private_json(path)["cells"][0]["marker"]
    _transition(
        path,
        "python",
        phase="cleanup_required",
        dispatchAttempted=True,
        reconciliationRequired=True,
        commentId=999,
        readPassed=True,
        approvedCommentPassed=True,
        controlReadbackPassed=True,
    )
    wrong_issue = _comment(999, marker, issue_number=999)
    designated = _comment(91, marker)
    control = FakeControl(
        [wrong_issue, designated],
        listed_comments=[designated],
    )

    with pytest.raises(GitHubProofError, match="cleanup_issue_mismatch"):
        await reconcile_state(
            path,
            COMMIT,
            environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
            control_factory=lambda _token: control,
        )
    cell = read_private_json(path)["cells"][0]
    assert cell["phase"] == "failed"
    assert cell["commentId"] == 999
    assert cell["reconciliationRequired"] is True
    assert cell["absenceObserved"] is False
    assert control.comments == [wrong_issue, designated]
    assert control.calls == [("get", "octo", "widgets", 999)]

    with pytest.raises(GitHubProofError, match="absence_confirmation_unavailable"):
        await reconcile_state(
            path,
            COMMIT,
            environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
            control_factory=lambda _token: control,
            confirm_absence=True,
        )
    assert control.calls == [("get", "octo", "widgets", 999)]


@pytest.mark.asyncio
async def test_cleanup_rejects_issue_mismatch_in_designated_list(
    tmp_path: Path,
) -> None:
    path = _state(tmp_path)
    marker = read_private_json(path)["cells"][0]["marker"]
    _transition(
        path,
        "python",
        phase="dispatched",
        dispatchAttempted=True,
        reconciliationRequired=True,
    )
    control = FakeControl(
        [_comment(91, marker, issue_number=999)],
        listed_comments=[_comment(91, marker, issue_number=999)],
    )

    with pytest.raises(GitHubProofError, match="cleanup_issue_mismatch"):
        await reconcile_state(
            path,
            COMMIT,
            environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
            control_factory=lambda _token: control,
        )
    cell = read_private_json(path)["cells"][0]
    assert cell["phase"] == "failed"
    assert cell["reconciliationRequired"] is True


@pytest.mark.asyncio
async def test_cleanup_marker_mismatch_finds_actual_designated_comment(
    tmp_path: Path,
) -> None:
    path = _state(tmp_path)
    marker = read_private_json(path)["cells"][0]["marker"]
    _transition(
        path,
        "python",
        phase="cleanup_required",
        dispatchAttempted=True,
        reconciliationRequired=True,
        commentId=91,
        readPassed=True,
        approvedCommentPassed=True,
        controlReadbackPassed=True,
    )
    wrong = _comment(91, "different")
    actual = _comment(92, marker)
    control = FakeControl([wrong, actual])

    assert await reconcile_state(
        path,
        COMMIT,
        environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
        control_factory=lambda _token: control,
    )
    cell = read_private_json(path)["cells"][0]
    assert cell["phase"] == "cleaned"
    assert cell["commentId"] == 92
    assert control.comments == [wrong]


@pytest.mark.asyncio
async def test_cleanup_delete_ambiguity_remains_pending(tmp_path: Path) -> None:
    path = _state(tmp_path)
    marker = read_private_json(path)["cells"][0]["marker"]
    _transition(
        path,
        "python",
        phase="cleanup_required",
        dispatchAttempted=True,
        reconciliationRequired=True,
        commentId=91,
        readPassed=True,
        approvedCommentPassed=True,
        controlReadbackPassed=True,
    )
    control = FakeControl(
        [_comment(91, marker)],
        delete_error=GitHubProofError("control_unavailable"),
    )

    with pytest.raises(GitHubProofError):
        await reconcile_state(
            path,
            COMMIT,
            environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
            control_factory=lambda _token: control,
        )
    cell = read_private_json(path)["cells"][0]
    assert cell["phase"] == "failed"
    assert cell["failureOrigin"] == "cleanup"
    assert cell["reconciliationRequired"] is True


@pytest.mark.asyncio
async def test_cleanup_missing_identified_comment_requires_confirmation(
    tmp_path: Path,
) -> None:
    path = _state(tmp_path)
    _transition(
        path,
        "python",
        phase="cleanup_required",
        dispatchAttempted=True,
        reconciliationRequired=True,
        commentId=91,
        readPassed=True,
        approvedCommentPassed=True,
        controlReadbackPassed=True,
    )
    control = FakeControl([])

    assert not await reconcile_state(
        path,
        COMMIT,
        environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
        control_factory=lambda _token: control,
    )
    cell = read_private_json(path)["cells"][0]
    assert cell["phase"] == "failed"
    assert cell["reconciliationRequired"] is True
    assert cell["absenceObserved"] is True
    assert control.calls == [
        ("get", "octo", "widgets", 91),
        ("list", "octo", "widgets", 7),
    ]


@pytest.mark.asyncio
async def test_cleanup_validates_commit_before_token_or_transport(
    tmp_path: Path,
) -> None:
    path = _state(tmp_path)
    _transition(
        path,
        "python",
        phase="dispatched",
        dispatchAttempted=True,
        reconciliationRequired=True,
    )
    factories = 0

    def factory(_token: str) -> FakeControl:
        nonlocal factories
        factories += 1
        return FakeControl([])

    with pytest.raises(GitHubProofError, match="state_binding_invalid"):
        await reconcile_state(
            path,
            "f" * 40,
            environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
            control_factory=factory,
        )
    assert factories == 0


@pytest.mark.asyncio
async def test_cleanup_requires_token_only_when_reconciliation_is_pending(
    tmp_path: Path,
) -> None:
    path = _state(tmp_path)
    _transition(
        path,
        "python",
        phase="dispatched",
        dispatchAttempted=True,
        reconciliationRequired=True,
    )
    with pytest.raises(GitHubProofError, match="proof_token_missing"):
        await reconcile_state(path, COMMIT, environment={})


@pytest.mark.asyncio
async def test_cleanup_wholly_planned_state_is_not_success(tmp_path: Path) -> None:
    path = _state(tmp_path)
    assert not await reconcile_state(path, COMMIT, environment={})


def test_cleanup_cli_exposes_explicit_absence_confirmation() -> None:
    args = parse_args(
        [
            "--state",
            "/tmp/state.json",
            "--expected-commit",
            COMMIT,
            "--confirm-absence",
        ]
    )
    assert args.confirm_absence is True


def test_cleanup_cli_lock_contention_fails_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _state(tmp_path)
    with private_state_lock(path):
        assert cleanup_main(["--state", str(path), "--expected-commit", COMMIT]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "GitHub proof cleanup failed\n"
