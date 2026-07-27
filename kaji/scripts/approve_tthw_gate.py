#!/usr/bin/env python3
"""Validate and approve the exact Kaji TTHW gate through a fail-closed transaction."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
from typing import Any, NoReturn

from process_runner import METADATA_BUDGET, CommandError, run_checked
import validate_tthw_evidence as validation


REPOSITORY = "enkyuan/alloy"
ENVIRONMENT = "kaji-beta"
WORKFLOW_PATH = ".github/workflows/kaji.publish.yml"
JOB_NAME = "time-to-hello-world evidence"
SECRET_NAME = "KAJI_TTHW_EVIDENCE_JSON"
RUN_ATTEMPT = 1
MAX_EVIDENCE_BYTES = 49_152
TAG_POLICY = "kaji-v*-beta.*"
APPROVAL_COMMENT = "Approve exact-run TTHW evidence."


class ApprovalError(RuntimeError):
    """An unsafe or ambiguous approval transaction."""


def fail(message: str) -> NoReturn:
    raise ApprovalError(message)


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _same_file(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
        before.st_mode,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
        after.st_mode,
    )


def read_evidence(path: Path) -> bytes:
    """Read one stable, nonempty, regular evidence-file snapshot."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        before_path = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISREG(before_path.st_mode)
            or before_path.st_size < 1
            or before_path.st_size > MAX_EVIDENCE_BYTES
        ):
            raise OSError
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_size < 1
                or before.st_size > MAX_EVIDENCE_BYTES
                or not _same_file(before_path, before)
            ):
                raise OSError
            encoded = stream.read(MAX_EVIDENCE_BYTES + 1)
            after = os.fstat(stream.fileno())
        after_path = os.stat(path, follow_symlinks=False)
        if (
            len(encoded) < 1
            or len(encoded) > MAX_EVIDENCE_BYTES
            or len(encoded) != before.st_size
            or not _same_file(before, after)
            or not _same_file(after, after_path)
        ):
            raise OSError
        if encoded.endswith((b"\r", b"\n")):
            fail("evidence file ends in CR or LF bytes that GitHub CLI would remove")
        return encoded
    except OSError:
        fail("evidence file is empty, oversized, non-regular, symlinked, or unstable")


@dataclass(frozen=True)
class Candidate:
    commit: str
    typescript_version: str
    tag: str


@dataclass(frozen=True)
class ProtectedEnvironmentState:
    environment_id: int
    security_snapshot: str


@dataclass(frozen=True)
class RemoteState:
    run_created_at: datetime
    waiting_job_snapshot: str
    protected_environment: ProtectedEnvironmentState
    pending_deployment_snapshot: str


def validate_evidence(args: argparse.Namespace, encoded: bytes) -> Candidate:
    document = validation._json_object(encoded, "TTHW evidence")
    validation.validate_document(document)
    validation.validate_release_freshness(document)
    validation.validate_bindings(
        document,
        args.release_manifest,
        args.artifacts_dir,
    )
    expected_run = f"https://github.com/{REPOSITORY}/actions/runs/{args.run_id}"
    validation.validate_compatibility_receipts(
        document,
        validation.load_json(
            args.python_compatibility_receipt,
            "Python 3.14 compatibility receipt",
        ),
        validation.load_json(
            args.node_compatibility_receipt,
            "Node 24 compatibility receipt",
        ),
        expected_workflow_run=expected_run,
        expected_workflow_run_attempt=RUN_ATTEMPT,
    )
    typescript = [
        entry for entry in document["artifacts"] if entry.get("package") == "typescript"
    ]
    if len(typescript) != 1:
        fail("validated evidence does not contain one TypeScript artifact")
    version = typescript[0].get("version")
    if not isinstance(version, str) or not version:
        fail("validated evidence TypeScript version is invalid")
    return Candidate(
        commit=document["commit"],
        typescript_version=version,
        tag=f"kaji-v{version}",
    )


class GitHub:
    """Small subprocess adapter so the transaction can be fully faked."""

    def _run(self, arguments: list[str], *, input_bytes: bytes | None = None) -> bytes:
        try:
            completed = run_checked(
                ["gh", *arguments],
                cwd=Path.cwd(),
                budget=METADATA_BUDGET,
                capture=True,
                check=False,
                input_bytes=input_bytes,
            )
        except CommandError:
            fail("GitHub command could not be completed")
        if completed.returncode != 0:
            fail("GitHub command failed")
        return completed.stdout

    def json(self, arguments: list[str], *, input_bytes: bytes | None = None) -> Any:
        encoded = self._run(arguments, input_bytes=input_bytes)
        try:
            return json.loads(encoded)
        except (UnicodeError, json.JSONDecodeError):
            fail("GitHub returned malformed JSON")

    def set_secret(self, encoded: bytes) -> None:
        self._run(
            [
                "secret",
                "set",
                SECRET_NAME,
                "--repo",
                REPOSITORY,
                "--env",
                ENVIRONMENT,
            ],
            input_bytes=encoded,
        )


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{label} response is malformed")
    return value


def _positive_id(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        fail(f"{label} ID is invalid")
    return value


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        fail(f"{label} timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail(f"{label} timestamp is invalid")
    if parsed.tzinfo is None:
        fail(f"{label} timestamp is invalid")
    return parsed


def _complete_collection(
    response: Any,
    *,
    collection_key: str,
    label: str,
) -> list[Any]:
    document = _object(response, label)
    values = document.get(collection_key)
    if not isinstance(values, list):
        fail(f"{label} response is malformed")
    total = document.get("total_count")
    if type(total) is not int or total != len(values):
        fail(f"{label} response is incomplete")
    return values


def _normalized_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _normalized_json(item)
            for key, item in sorted(value.items())
            if isinstance(key, str)
        }
    if isinstance(value, list):
        items = [_normalized_json(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
        )
    return value


def _snapshot(value: Any) -> str:
    return json.dumps(
        _normalized_json(value),
        sort_keys=True,
        separators=(",", ":"),
    )


def _environment_state(github: GitHub) -> ProtectedEnvironmentState:
    environment = _object(
        github.json(["api", f"repos/{REPOSITORY}/environments/{ENVIRONMENT}"]),
        "environment",
    )
    if environment.get("name") != ENVIRONMENT:
        fail("protected environment name differs")
    environment_id = _positive_id(environment.get("id"), "environment")
    rules = environment.get("protection_rules")
    if not isinstance(rules, list) or not all(isinstance(rule, dict) for rule in rules):
        fail("protected environment rules are malformed")
    reviewer_rules = [
        rule
        for rule in rules
        if isinstance(rule, dict) and rule.get("type") == "required_reviewers"
    ]
    branch_rules = [
        rule
        for rule in rules
        if isinstance(rule, dict) and rule.get("type") == "branch_policy"
    ]
    if (
        len(reviewer_rules) != 1
        or not isinstance(reviewer_rules[0].get("reviewers"), list)
        or not reviewer_rules[0]["reviewers"]
        or type(reviewer_rules[0].get("prevent_self_review")) is not bool
    ):
        fail("protected environment requires nonempty required reviewers")
    if len(branch_rules) != 1:
        fail("protected environment branch policy is missing or ambiguous")
    _positive_id(reviewer_rules[0].get("id"), "required reviewers rule")
    _positive_id(branch_rules[0].get("id"), "branch policy rule")
    for reviewer in reviewer_rules[0]["reviewers"]:
        reviewer_entry = _object(reviewer, "required reviewer")
        reviewer_type = reviewer_entry.get("type")
        identity = _object(reviewer_entry.get("reviewer"), "required reviewer identity")
        identity_field = "login" if reviewer_type == "User" else "slug"
        if (
            reviewer_type not in {"User", "Team"}
            or not isinstance(identity.get(identity_field), str)
            or not identity[identity_field]
        ):
            fail("required reviewer identity is invalid")
        _positive_id(identity.get("id"), "required reviewer")

    deployment_branch_policy = _object(
        environment.get("deployment_branch_policy"),
        "deployment branch policy configuration",
    )
    if (
        deployment_branch_policy.get("custom_branch_policies") is not True
        or deployment_branch_policy.get("protected_branches") is not False
    ):
        fail("protected environment does not use custom deployment branch policies")
    if type(environment.get("can_admins_bypass")) is not bool:
        fail("protected environment administrator bypass setting is malformed")

    policies = _complete_collection(
        github.json(
            [
                "api",
                (
                    f"repos/{REPOSITORY}/environments/{ENVIRONMENT}"
                    "/deployment-branch-policies?per_page=100"
                ),
            ]
        ),
        collection_key="branch_policies",
        label="deployment branch policies",
    )
    if not all(isinstance(policy, dict) for policy in policies):
        fail("deployment branch policies response is malformed")
    for policy in policies:
        _positive_id(policy.get("id"), "deployment branch policy")
        if (
            policy.get("type") not in {"branch", "tag"}
            or not isinstance(policy.get("name"), str)
            or not policy["name"]
        ):
            fail("deployment branch policy is malformed")
    tag_policies = [
        policy
        for policy in policies
        if isinstance(policy, dict)
        and policy.get("type") == "tag"
        and policy.get("name") == TAG_POLICY
    ]
    if len(tag_policies) != 1:
        fail("protected environment exact beta tag policy is missing or ambiguous")
    return ProtectedEnvironmentState(
        environment_id=environment_id,
        security_snapshot=_snapshot(
            {
                "environment": {
                    "id": environment_id,
                    "name": environment["name"],
                    "can_admins_bypass": environment["can_admins_bypass"],
                    "deployment_branch_policy": deployment_branch_policy,
                    "protection_rules": rules,
                },
                "deployment_branch_policies": policies,
                "exact_tag_policy": tag_policies[0],
            }
        ),
    )


def remote_preflight(
    github: GitHub,
    *,
    run_id: int,
    candidate: Candidate,
) -> RemoteState:
    run = _object(
        github.json(["api", f"repos/{REPOSITORY}/actions/runs/{run_id}"]),
        "workflow run",
    )
    expected_run = {
        "id": run_id,
        "run_attempt": RUN_ATTEMPT,
        "event": "push",
        "path": WORKFLOW_PATH,
        "head_sha": candidate.commit,
        "head_branch": candidate.tag,
    }
    if any(run.get(field) != value for field, value in expected_run.items()):
        fail("workflow run binding differs")
    run_created_at = _timestamp(run.get("created_at"), "workflow run created_at")

    jobs = _complete_collection(
        github.json(
            [
                "api",
                (
                    f"repos/{REPOSITORY}/actions/runs/{run_id}/attempts/"
                    f"{RUN_ATTEMPT}/jobs?per_page=100"
                ),
            ]
        ),
        collection_key="jobs",
        label="workflow jobs",
    )
    if not all(isinstance(job, dict) for job in jobs):
        fail("workflow jobs response is malformed")
    tthw_jobs = [job for job in jobs if job.get("name") == JOB_NAME]
    waiting_jobs = [job for job in jobs if job.get("status") == "waiting"]
    if (
        len(tthw_jobs) != 1
        or len(waiting_jobs) != 1
        or waiting_jobs[0] is not tthw_jobs[0]
        or type(tthw_jobs[0].get("id")) is not int
        or tthw_jobs[0]["id"] < 1
        or tthw_jobs[0].get("run_id") != run_id
        or tthw_jobs[0].get("head_sha") != candidate.commit
        or tthw_jobs[0].get("head_branch") != candidate.tag
        or tthw_jobs[0].get("status") != "waiting"
        or tthw_jobs[0].get("conclusion") is not None
        or tthw_jobs[0].get("run_attempt") != RUN_ATTEMPT
    ):
        fail("expected the attempt-1 TTHW job to be the run's sole waiting job")

    waiting_job_snapshot = _snapshot(
        {
            field: tthw_jobs[0].get(field)
            for field in (
                "id",
                "run_id",
                "run_attempt",
                "name",
                "head_sha",
                "head_branch",
                "status",
                "conclusion",
            )
        }
    )
    protected_environment = _environment_state(github)
    pending = github.json(
        [
            "api",
            f"repos/{REPOSITORY}/actions/runs/{run_id}/pending_deployments",
        ]
    )
    if not isinstance(pending, list) or len(pending) != 1:
        fail("expected exactly one pending deployment")
    deployment = _object(pending[0], "pending deployment")
    environment = _object(deployment.get("environment"), "pending environment")
    if (
        environment.get("name") != ENVIRONMENT
        or _positive_id(environment.get("id"), "pending environment")
        != protected_environment.environment_id
        or deployment.get("current_user_can_approve") is not True
    ):
        fail("pending kaji-beta deployment is not bound and approvable")
    return RemoteState(
        run_created_at=run_created_at,
        waiting_job_snapshot=waiting_job_snapshot,
        protected_environment=protected_environment,
        pending_deployment_snapshot=_snapshot(deployment),
    )


def secret_metadata(github: GitHub) -> dict[str, Any] | None:
    secrets = _complete_collection(
        github.json(
            [
                "api",
                (f"repos/{REPOSITORY}/environments/{ENVIRONMENT}/secrets?per_page=100"),
            ]
        ),
        collection_key="secrets",
        label="environment secrets",
    )
    matches = [
        secret
        for secret in secrets
        if isinstance(secret, dict) and secret.get("name") == SECRET_NAME
    ]
    if len(matches) > 1:
        fail("TTHW secret metadata is ambiguous")
    return matches[0] if matches else None


def assert_fresh_secret(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    *,
    run_created_at: datetime,
    set_started_at: datetime,
) -> None:
    if after is None:
        fail("TTHW secret metadata is missing after update")
    updated_at = _timestamp(after.get("updated_at"), "TTHW secret updated_at")
    if updated_at < run_created_at:
        fail("TTHW secret predates the authoritative workflow run")
    if set_started_at.tzinfo is None:
        fail("secret update start timestamp is invalid")
    api_precision_floor = set_started_at.astimezone(timezone.utc).replace(microsecond=0)
    if updated_at < api_precision_floor:
        fail("TTHW secret metadata predates this secret update operation")
    if before is not None:
        before_updated_at = _timestamp(
            before.get("updated_at"),
            "previous TTHW secret updated_at",
        )
        if before_updated_at == updated_at:
            fail("TTHW secret metadata timestamp did not change")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def validate_approval_response(response: Any, candidate: Candidate) -> None:
    if not isinstance(response, list) or len(response) != 1:
        fail("deployment approval did not return exactly one deployment")
    deployment = _object(response[0], "approved deployment")
    _positive_id(deployment.get("id"), "approved deployment")
    if (
        deployment.get("sha") != candidate.commit
        or deployment.get("ref") != candidate.tag
        or deployment.get("environment") != ENVIRONMENT
    ):
        fail("approved deployment binding differs")


def approve(args: argparse.Namespace, github: GitHub | None = None) -> None:
    client = github or GitHub()
    encoded = read_evidence(args.evidence)
    candidate = validate_evidence(args, encoded)
    initial = remote_preflight(
        client,
        run_id=args.run_id,
        candidate=candidate,
    )
    if not args.approve:
        print(
            "PASS: local evidence and remote TTHW approval preflight succeeded; "
            "no state changed"
        )
        return

    before = secret_metadata(client)
    set_started_at = _utc_now()
    client.set_secret(encoded)
    after = secret_metadata(client)
    assert_fresh_secret(
        before,
        after,
        run_created_at=initial.run_created_at,
        set_started_at=set_started_at,
    )
    refreshed = remote_preflight(
        client,
        run_id=args.run_id,
        candidate=candidate,
    )
    if refreshed != initial:
        fail("authoritative approval state changed after secret update")
    latest = secret_metadata(client)
    if latest is None or _snapshot(latest) != _snapshot(after):
        fail("TTHW secret metadata changed before deployment approval")
    payload = json.dumps(
        {
            "environment_ids": [refreshed.protected_environment.environment_id],
            "state": "approved",
            "comment": APPROVAL_COMMENT,
        },
        separators=(",", ":"),
    ).encode()
    response = client.json(
        [
            "api",
            "--method",
            "POST",
            (f"repos/{REPOSITORY}/actions/runs/{args.run_id}/pending_deployments"),
            "--input",
            "-",
        ],
        input_bytes=payload,
    )
    validate_approval_response(response, candidate)
    print("PASS: exact-run TTHW evidence secret set and deployment approved")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", type=_positive_integer, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--python-compatibility-receipt", type=Path, required=True)
    parser.add_argument("--node-compatibility-receipt", type=Path, required=True)
    parser.add_argument("--approve", action="store_true")
    return parser.parse_args()


def main() -> int:
    try:
        approve(parse_args())
    except (ApprovalError, validation.EvidenceError) as error:
        print(f"FAIL: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
