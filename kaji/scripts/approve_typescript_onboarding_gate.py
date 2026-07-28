#!/usr/bin/env python3
"""Validate and approve the exact Kaji TypeScript onboarding deployment gate."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Literal, NoReturn

from process_runner import METADATA_BUDGET, CommandError, run_checked
import validate_typescript_onboarding_evidence as onboarding


REPOSITORY = "enkyuan/alloy"
API_VERSION = "2026-03-10"
RUN_ATTEMPT = 1
TAG = "kaji-v0.2.0-beta.9"

ONBOARDING_ENVIRONMENT = "kaji-beta-onboarding"
PROVIDER_ENVIRONMENT = "kaji-beta"
PUBLISH_ENVIRONMENT = "kaji-beta-publish"
REVIEWER_TYPE = "User"
REVIEWER_LOGIN = "enkyuan"
REVIEWER_ID = 90286412

ONBOARDING_JOB_NAME = "TypeScript onboarding evidence"
ARCHIVE_CALIBRATION_JOB_NAME = "TypeScript onboarding archive calibration"

PRODUCER_ARTIFACT_NAME = "kaji-beta-artifacts"
NODE22_ARTIFACT_NAME = "kaji-node-compat-22"
NODE24_ARTIFACT_NAME = "kaji-node-compat-24"

REHEARSAL_WORKFLOW_PATH = ".github/workflows/kaji.rehearsal.yml"
REHEARSAL_WORKFLOW_REF = (
    "enkyuan/alloy/.github/workflows/kaji.rehearsal.yml@refs/heads/main"
)
PUBLISH_WORKFLOW_PATH = ".github/workflows/kaji.publish.yml"
PUBLISH_WORKFLOW_REF = (
    "enkyuan/alloy/.github/workflows/kaji.publish.yml@refs/tags/kaji-v0.2.0-beta.9"
)

APPROVAL_COMMENT = "Approve exact-run TypeScript onboarding evidence."
MAX_SAFE_INTEGER = 9_007_199_254_740_991
COMMIT = re.compile(r"[0-9a-f]{40}")
ARTIFACT_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
AMBIGUOUS_MESSAGE = (
    "the onboarding approval request was issued; inspect the exact workflow "
    "run manually and do not retry this command automatically"
)


class ApprovalError(RuntimeError):
    """A pre-issuance validation or transaction error."""


class ApprovalOutcomeAmbiguous(RuntimeError):
    """The sole approval request may have changed remote state."""

    def __init__(self) -> None:
        super().__init__(AMBIGUOUS_MESSAGE)


def fail(message: str) -> NoReturn:
    raise ApprovalError(message)


@dataclass(frozen=True, slots=True)
class ModePolicy:
    name: Literal["rehearsal", "publish"]
    event: str
    head_branch: str
    workflow_path: str
    workflow_ref: str
    anchor_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LocalState:
    mode: Literal["rehearsal", "publish"]
    run_id: int
    commit: str
    aggregate: Mapping[str, Any]
    producer_artifact_id: int
    node22_artifact_id: int
    node24_artifact_id: int
    producer_observed_digest: str
    node22_observed_digest: str
    node24_observed_digest: str
    semantic_snapshot: str


@dataclass(frozen=True, slots=True)
class ProtectedEnvironmentState:
    name: str
    environment_id: int
    node_id: str
    rule_ids: tuple[int, int]
    rule_node_ids: tuple[str, str]
    policy_ids: tuple[int, ...]
    policy_node_ids: tuple[str, ...]
    security_snapshot: str


@dataclass(frozen=True, slots=True)
class EnvironmentAuditState:
    onboarding: ProtectedEnvironmentState
    provider: ProtectedEnvironmentState
    publisher: ProtectedEnvironmentState
    security_snapshot: str


@dataclass(frozen=True, slots=True)
class ArtifactState:
    name: str
    artifact_id: int
    digest: str
    run_id: int
    head_branch: str
    head_sha: str
    expired: Literal[False]
    archive_download_url: str
    security_snapshot: str


@dataclass(frozen=True, slots=True)
class HostedCalibrationState:
    run_id: int
    commit: str
    workflow_ref: str
    calibration_job_id: int
    producer_id: int
    producer_digest: str
    node22_id: int
    node22_digest: str
    node24_id: int
    node24_digest: str
    aggregate_sha256: str
    security_snapshot: str


@dataclass(frozen=True, slots=True)
class RemoteState:
    mode: Literal["rehearsal", "publish"]
    run_id: int
    commit: str
    head_branch: str
    workflow_ref: str
    onboarding_environment_id: int
    calibration_job_id: int
    environment_audit: EnvironmentAuditState
    run_snapshot: str
    anchor_jobs_snapshot: str
    calibration_job_snapshot: str
    waiting_job_snapshot: str
    artifact_collection_snapshot: str
    artifacts: tuple[ArtifactState, ArtifactState, ArtifactState]
    pending_deployment_snapshot: str
    security_snapshot: str


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive safe integer") from error
    if parsed < 1 or parsed > MAX_SAFE_INTEGER:
        raise argparse.ArgumentTypeError("must be a positive safe integer")
    return parsed


def _commit_argument(value: str) -> str:
    if COMMIT.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("must be 40 lowercase hexadecimal characters")
    return value


def _digest_argument(value: str) -> str:
    if ARTIFACT_DIGEST.fullmatch(value) is None:
        raise argparse.ArgumentTypeError(
            "must be sha256: followed by 64 lowercase hexadecimal characters"
        )
    return value


def _positive_id(value: Any, label: str) -> int:
    if type(value) is not int or value < 1 or value > MAX_SAFE_INTEGER:
        fail(f"{label} ID is invalid")
    return value


def _exact_id(value: Any, expected: int, label: str) -> int:
    observed = _positive_id(value, label)
    if observed != expected:
        fail(f"{label} differs")
    return observed


def _exact_attempt(value: Any, label: str) -> None:
    if type(value) is not int or value != RUN_ATTEMPT:
        fail(f"{label} differs")


def _node_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1_024 or "\0" in value:
        fail(f"{label} node ID is invalid")
    return value


def _reject_unreviewed_bypass(
    value: Any,
    label: str,
    *,
    allow_admin_field: bool = False,
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                fail(f"{label} response is malformed")
            if "bypass" in key.lower() and not (
                allow_admin_field and key == "can_admins_bypass"
            ):
                fail(f"{label} contains an unreviewed bypass field")
            _reject_unreviewed_bypass(item, label)
    elif isinstance(value, list):
        for item in value:
            _reject_unreviewed_bypass(item, label)


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        fail(f"{label} response is malformed")
    return value


def _complete_collection(
    response: Any,
    *,
    collection_key: str,
    label: str,
) -> list[Any]:
    document = _object(response, label)
    _reject_unreviewed_bypass(document, label)
    if set(document) != {"total_count", collection_key}:
        fail(f"{label} response contains an unreviewed field")
    values = document.get(collection_key)
    if not isinstance(values, list):
        fail(f"{label} response is malformed")
    total = document.get("total_count")
    if type(total) is not int or total != len(values) or total > 100:
        fail(f"{label} response is incomplete")
    return values


def _normalized_json(value: Any) -> Any:
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            fail("remote response has a non-string object key")
        return {key: _normalized_json(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        items = [_normalized_json(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
        )
    if isinstance(value, float) and not math.isfinite(value):
        fail("remote response contains a non-finite number")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    fail("remote response contains an unsupported value")


def _snapshot(value: Any) -> str:
    return json.dumps(
        _normalized_json(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _mode_policy(mode: str) -> ModePolicy:
    if mode == "rehearsal":
        return ModePolicy(
            name="rehearsal",
            event="workflow_dispatch",
            head_branch="main",
            workflow_path=REHEARSAL_WORKFLOW_PATH,
            workflow_ref=REHEARSAL_WORKFLOW_REF,
            anchor_names=("offline release",),
        )
    if mode == "publish":
        return ModePolicy(
            name="publish",
            event="push",
            head_branch=TAG,
            workflow_path=PUBLISH_WORKFLOW_PATH,
            workflow_ref=PUBLISH_WORKFLOW_REF,
            anchor_names=("verify release tag", "offline release gates"),
        )
    fail("release mode is invalid")


def _validate_gate_inputs(args: argparse.Namespace) -> ModePolicy:
    policy = _mode_policy(args.mode)
    _positive_id(args.run_id, "workflow run")
    if (
        not isinstance(args.expected_commit, str)
        or COMMIT.fullmatch(args.expected_commit) is None
    ):
        fail("expected commit identity is invalid")
    identities = (
        ("producer artifact", args.producer_artifact_id),
        ("Node 22 artifact", args.node22_artifact_id),
        ("Node 24 artifact", args.node24_artifact_id),
    )
    for label, value in identities:
        _positive_id(value, label)
    if len({value for _, value in identities}) != 3:
        fail("artifact IDs are not distinct")
    for label, value in (
        ("producer artifact", args.producer_artifact_digest),
        ("Node 22 artifact", args.node22_artifact_digest),
        ("Node 24 artifact", args.node24_artifact_digest),
    ):
        if not isinstance(value, str) or ARTIFACT_DIGEST.fullmatch(value) is None:
            fail(f"{label} digest is invalid")
    return policy


class GitHub:
    """Bounded, redacted GitHub REST adapter."""

    @staticmethod
    def _arguments(
        endpoint: str,
        *,
        method: Literal["GET", "POST"],
    ) -> list[str]:
        if not endpoint.startswith(f"repos/{REPOSITORY}/") or "\0" in endpoint:
            fail("GitHub endpoint is outside the reviewed release surface")
        arguments = [
            "api",
            "--hostname",
            "github.com",
            "--header",
            "Accept: application/vnd.github+json",
            "--header",
            f"X-GitHub-Api-Version: {API_VERSION}",
        ]
        if method == "POST":
            arguments.extend(["--method", "POST"])
        arguments.append(endpoint)
        if method == "POST":
            arguments.extend(["--input", "-"])
        return arguments

    def _json(
        self,
        endpoint: str,
        *,
        method: Literal["GET", "POST"],
        input_bytes: bytes | None = None,
    ) -> Any:
        try:
            completed = run_checked(
                ["gh", *self._arguments(endpoint, method=method)],
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
        if len(completed.stdout) > METADATA_BUDGET.max_output_bytes:
            fail("GitHub response exceeded the reviewed output bound")

        def reject_constant(_value: str) -> NoReturn:
            fail("GitHub returned malformed JSON")

        def parse_finite_float(value: str) -> float:
            parsed = float(value)
            if not math.isfinite(parsed):
                fail("GitHub returned malformed JSON")
            return parsed

        def reject_duplicate_keys(
            pairs: list[tuple[str, Any]],
        ) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    fail("GitHub returned malformed JSON")
                result[key] = value
            return result

        try:
            return json.loads(
                completed.stdout,
                parse_constant=reject_constant,
                parse_float=parse_finite_float,
                object_pairs_hook=reject_duplicate_keys,
            )
        except (UnicodeError, json.JSONDecodeError):
            fail("GitHub returned malformed JSON")

    def get(self, endpoint: str) -> Any:
        return self._json(endpoint, method="GET")

    def post(self, endpoint: str, *, input_bytes: bytes) -> Any:
        return self._json(endpoint, method="POST", input_bytes=input_bytes)


def _expected_policies(name: str) -> set[tuple[str, str]]:
    if name in {ONBOARDING_ENVIRONMENT, PROVIDER_ENVIRONMENT}:
        return {("branch", "main"), ("tag", TAG)}
    if name == PUBLISH_ENVIRONMENT:
        return {("tag", TAG)}
    fail("protected environment name is invalid")


def _environment_state(github: GitHub, name: str) -> ProtectedEnvironmentState:
    environment = _object(
        github.get(f"repos/{REPOSITORY}/environments/{name}"),
        f"{name} environment",
    )
    _reject_unreviewed_bypass(
        environment,
        f"{name} environment",
        allow_admin_field=True,
    )
    if environment.get("name") != name:
        fail(f"{name} environment name differs")
    if set(environment) != {
        "id",
        "node_id",
        "name",
        "url",
        "html_url",
        "created_at",
        "updated_at",
        "can_admins_bypass",
        "protection_rules",
        "deployment_branch_policy",
    }:
        fail(f"{name} environment contains an unreviewed field")
    environment_id = _positive_id(environment.get("id"), f"{name} environment")
    environment_node_id = _node_id(
        environment.get("node_id"),
        f"{name} environment",
    )
    expected_url = f"https://api.github.com/repos/{REPOSITORY}/environments/{name}"
    expected_html_url = (
        f"https://github.com/{REPOSITORY}/deployments/activity_log"
        f"?environments_filter={name}"
    )
    if (
        environment.get("url") != expected_url
        or environment.get("html_url") != expected_html_url
        or not isinstance(environment.get("created_at"), str)
        or not environment["created_at"]
        or not isinstance(environment.get("updated_at"), str)
        or not environment["updated_at"]
    ):
        fail(f"{name} environment metadata differs")
    if environment.get("can_admins_bypass") is not False:
        fail(f"{name} administrator bypass must be disabled")
    deployment_policy = _object(
        environment.get("deployment_branch_policy"),
        f"{name} deployment branch policy configuration",
    )
    if (
        set(deployment_policy) != {"custom_branch_policies", "protected_branches"}
        or deployment_policy.get("custom_branch_policies") is not True
        or deployment_policy.get("protected_branches") is not False
    ):
        fail(f"{name} environment does not use exact custom deployment policies")
    rules = environment.get("protection_rules")
    if (
        not isinstance(rules, list)
        or len(rules) != 2
        or not all(isinstance(rule, dict) for rule in rules)
    ):
        fail(f"{name} protection rules differ")
    for rule in rules:
        _object(rule, f"{name} protection rule")
    reviewer_rules = [
        rule for rule in rules if rule.get("type") == "required_reviewers"
    ]
    branch_rules = [rule for rule in rules if rule.get("type") == "branch_policy"]
    if len(reviewer_rules) != 1 or len(branch_rules) != 1:
        fail(f"{name} protection rules differ")
    reviewer_rule = reviewer_rules[0]
    branch_rule = branch_rules[0]
    reviewer_rule_id = _positive_id(
        reviewer_rule.get("id"),
        f"{name} required reviewers rule",
    )
    branch_rule_id = _positive_id(
        branch_rule.get("id"),
        f"{name} branch policy rule",
    )
    if reviewer_rule_id == branch_rule_id:
        fail(f"{name} protection rule IDs are not distinct")
    if set(reviewer_rule) != {
        "id",
        "node_id",
        "type",
        "prevent_self_review",
        "reviewers",
    } or set(branch_rule) != {"id", "node_id", "type"}:
        fail(f"{name} protection rules contain an unreviewed field")
    reviewer_rule_node = _node_id(
        reviewer_rule.get("node_id"),
        f"{name} required reviewers rule",
    )
    branch_rule_node = _node_id(
        branch_rule.get("node_id"),
        f"{name} branch policy rule",
    )
    if reviewer_rule_node == branch_rule_node:
        fail(f"{name} protection rule node IDs are not distinct")
    reviewers = reviewer_rule.get("reviewers")
    if (
        reviewer_rule.get("prevent_self_review") is not False
        or not isinstance(reviewers, list)
        or len(reviewers) != 1
    ):
        fail(f"{name} required reviewer policy differs")
    reviewer = _object(reviewers[0], f"{name} required reviewer")
    identity = _object(reviewer.get("reviewer"), f"{name} required reviewer identity")
    identity_id = _positive_id(
        identity.get("id"),
        f"{name} required reviewer",
    )
    _node_id(identity.get("node_id"), f"{name} required reviewer")
    if (
        set(reviewer) != {"type", "reviewer"}
        or reviewer.get("type") != REVIEWER_TYPE
        or set(identity)
        != {
            "id",
            "node_id",
            "login",
            "type",
            "user_view_type",
            "site_admin",
            "url",
        }
        or identity.get("login") != REVIEWER_LOGIN
        or identity_id != REVIEWER_ID
        or identity.get("type") != REVIEWER_TYPE
        or identity.get("user_view_type") != "public"
        or identity.get("site_admin") is not False
        or identity.get("url") != f"https://api.github.com/users/{REVIEWER_LOGIN}"
    ):
        fail(f"{name} required reviewer identity differs")
    policies = _complete_collection(
        github.get(
            f"repos/{REPOSITORY}/environments/{name}/"
            "deployment-branch-policies?per_page=100"
        ),
        collection_key="branch_policies",
        label=f"{name} deployment branch policies",
    )
    if not all(isinstance(policy, dict) for policy in policies):
        fail(f"{name} deployment branch policies are malformed")
    _reject_unreviewed_bypass(policies, f"{name} deployment branch policies")
    observed: set[tuple[str, str]] = set()
    policy_ids: set[int] = set()
    policy_node_ids: set[str] = set()
    for policy in policies:
        if set(policy) != {"id", "node_id", "name", "type"}:
            fail(f"{name} deployment branch policy contains an unreviewed field")
        policy_id = _positive_id(
            policy.get("id"),
            f"{name} deployment branch policy",
        )
        if policy_id in policy_ids:
            fail(f"{name} deployment branch policy IDs are not distinct")
        policy_ids.add(policy_id)
        policy_node_id = _node_id(
            policy.get("node_id"),
            f"{name} deployment branch policy",
        )
        if policy_node_id in policy_node_ids:
            fail(f"{name} deployment branch policy node IDs are not distinct")
        policy_node_ids.add(policy_node_id)
        kind = policy.get("type")
        policy_name = policy.get("name")
        if (
            not isinstance(kind, str)
            or kind not in {"branch", "tag"}
            or not isinstance(policy_name, str)
            or not policy_name
        ):
            fail(f"{name} deployment branch policy is malformed")
        identity_pair = (kind, policy_name)
        if identity_pair in observed:
            fail(f"{name} deployment branch policies are duplicated")
        observed.add(identity_pair)
    if observed != _expected_policies(name):
        fail(f"{name} deployment branch policies differ")
    return ProtectedEnvironmentState(
        name=name,
        environment_id=environment_id,
        node_id=environment_node_id,
        rule_ids=(reviewer_rule_id, branch_rule_id),
        rule_node_ids=(reviewer_rule_node, branch_rule_node),
        policy_ids=tuple(sorted(policy_ids)),
        policy_node_ids=tuple(sorted(policy_node_ids)),
        security_snapshot=_snapshot(
            {
                "environment": {
                    "id": environment_id,
                    "node_id": environment_node_id,
                    "name": name,
                    "url": expected_url,
                    "html_url": expected_html_url,
                    "created_at": environment["created_at"],
                    "updated_at": environment["updated_at"],
                    "can_admins_bypass": False,
                    "deployment_branch_policy": deployment_policy,
                    "protection_rules": rules,
                },
                "deployment_branch_policies": policies,
            }
        ),
    )


def audit_environments(github: GitHub | None = None) -> EnvironmentAuditState:
    client = github or GitHub()
    onboarding_state = _environment_state(client, ONBOARDING_ENVIRONMENT)
    provider_state = _environment_state(client, PROVIDER_ENVIRONMENT)
    publisher_state = _environment_state(client, PUBLISH_ENVIRONMENT)
    states = (onboarding_state, provider_state, publisher_state)
    if len({state.environment_id for state in states}) != 3:
        fail("protected environment IDs are not distinct")
    if len({state.node_id for state in states}) != 3:
        fail("protected environment node IDs are not distinct")
    all_rule_ids = [identity for state in states for identity in state.rule_ids]
    all_rule_nodes = [identity for state in states for identity in state.rule_node_ids]
    all_policy_ids = [identity for state in states for identity in state.policy_ids]
    all_policy_nodes = [
        identity for state in states for identity in state.policy_node_ids
    ]
    if len(set(all_rule_ids)) != len(all_rule_ids):
        fail("protected environment rule IDs are not globally distinct")
    if len(set(all_rule_nodes)) != len(all_rule_nodes):
        fail("protected environment rule node IDs are not globally distinct")
    if len(set(all_policy_ids)) != len(all_policy_ids):
        fail("deployment policy IDs are not globally distinct")
    if len(set(all_policy_nodes)) != len(all_policy_nodes):
        fail("deployment policy node IDs are not globally distinct")
    return EnvironmentAuditState(
        onboarding=onboarding_state,
        provider=provider_state,
        publisher=publisher_state,
        security_snapshot=_snapshot(
            {
                onboarding_state.name: onboarding_state.security_snapshot,
                provider_state.name: provider_state.security_snapshot,
                publisher_state.name: publisher_state.security_snapshot,
            }
        ),
    )


def _observed_digest(archive: onboarding.AuthenticatedArtifactArchive) -> str:
    return "sha256:" + hashlib.sha256(archive.archive_bytes).hexdigest()


def validate_local(args: argparse.Namespace) -> LocalState:
    policy = _validate_gate_inputs(args)
    producer = onboarding.load_authenticated_archive(
        args.producer_archive,
        name=PRODUCER_ARTIFACT_NAME,
        artifact_id=args.producer_artifact_id,
        digest=args.producer_artifact_digest,
        run_id=args.run_id,
        run_attempt=1,
        head_sha=args.expected_commit,
        expired=False,
    )
    node22 = onboarding.load_authenticated_archive(
        args.node22_archive,
        name=NODE22_ARTIFACT_NAME,
        artifact_id=args.node22_artifact_id,
        digest=args.node22_artifact_digest,
        run_id=args.run_id,
        run_attempt=1,
        head_sha=args.expected_commit,
        expired=False,
    )
    node24 = onboarding.load_authenticated_archive(
        args.node24_archive,
        name=NODE24_ARTIFACT_NAME,
        artifact_id=args.node24_artifact_id,
        digest=args.node24_artifact_digest,
        run_id=args.run_id,
        run_attempt=1,
        head_sha=args.expected_commit,
        expired=False,
    )
    producer_observed = _observed_digest(producer)
    node22_observed = _observed_digest(node22)
    node24_observed = _observed_digest(node24)
    for label, observed, expected in (
        ("producer", producer_observed, args.producer_artifact_digest),
        ("Node 22", node22_observed, args.node22_artifact_digest),
        ("Node 24", node24_observed, args.node24_artifact_digest),
    ):
        if observed != expected:
            fail(f"{label} raw archive digest differs")
    workflow_run = f"https://github.com/{REPOSITORY}/actions/runs/{args.run_id}"
    compose_inputs = {
        "producer_archive": producer,
        "node22_archive": node22,
        "node24_archive": node24,
        "expected_workflow_run": workflow_run,
        "expected_workflow_ref": policy.workflow_ref,
        "expected_workflow_sha": args.expected_commit,
    }
    aggregate = onboarding.compose_document(**compose_inputs)
    onboarding.validate_document(aggregate)
    onboarding.recompute_and_compare(aggregate, **compose_inputs)
    semantic = {
        "mode": policy.name,
        "runId": args.run_id,
        "runAttempt": RUN_ATTEMPT,
        "commit": args.expected_commit,
        "event": policy.event,
        "workflowPath": policy.workflow_path,
        "workflowRef": policy.workflow_ref,
        "aggregate": aggregate,
        "archives": [
            {
                "name": PRODUCER_ARTIFACT_NAME,
                "id": args.producer_artifact_id,
                "digest": args.producer_artifact_digest,
                "observedDigest": producer_observed,
            },
            {
                "name": NODE22_ARTIFACT_NAME,
                "id": args.node22_artifact_id,
                "digest": args.node22_artifact_digest,
                "observedDigest": node22_observed,
            },
            {
                "name": NODE24_ARTIFACT_NAME,
                "id": args.node24_artifact_id,
                "digest": args.node24_artifact_digest,
                "observedDigest": node24_observed,
            },
        ],
    }
    return LocalState(
        mode=policy.name,
        run_id=args.run_id,
        commit=args.expected_commit,
        aggregate=aggregate,
        producer_artifact_id=args.producer_artifact_id,
        node22_artifact_id=args.node22_artifact_id,
        node24_artifact_id=args.node24_artifact_id,
        producer_observed_digest=producer_observed,
        node22_observed_digest=node22_observed,
        node24_observed_digest=node24_observed,
        semantic_snapshot=_snapshot(semantic),
    )


def _selected_job(
    jobs: list[dict[str, Any]],
    name: str,
    *,
    run_id: int,
    commit: str,
    head_branch: str,
    status: str,
    conclusion: str | None,
) -> dict[str, Any]:
    matches = [job for job in jobs if job.get("name") == name]
    if len(matches) != 1:
        fail(f"{name} job is missing or ambiguous")
    job = matches[0]
    _exact_id(job.get("run_id"), run_id, f"{name} job run")
    _exact_attempt(job.get("run_attempt"), f"{name} job run attempt")
    expected = {
        "head_sha": commit,
        "head_branch": head_branch,
        "status": status,
        "conclusion": conclusion,
    }
    if any(job.get(field) != value for field, value in expected.items()):
        fail(f"{name} job binding differs")
    _positive_id(job.get("id"), f"{name} job")
    return job


def _artifact_state(
    document: Any,
    *,
    expected_name: str,
    expected_id: int,
    expected_digest: str,
    run_id: int,
    head_branch: str,
    commit: str,
) -> ArtifactState:
    artifact = _object(document, f"{expected_name} artifact")
    _reject_unreviewed_bypass(artifact, f"{expected_name} artifact")
    workflow_run = _object(
        artifact.get("workflow_run"),
        f"{expected_name} artifact workflow run",
    )
    expected_url = (
        f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{expected_id}/zip"
    )
    _exact_id(artifact.get("id"), expected_id, f"{expected_name} artifact")
    _exact_id(
        workflow_run.get("id"),
        run_id,
        f"{expected_name} artifact workflow run",
    )
    if (
        artifact.get("name") != expected_name
        or artifact.get("digest") != expected_digest
        or artifact.get("expired") is not False
        or artifact.get("archive_download_url") != expected_url
        or workflow_run.get("head_branch") != head_branch
        or workflow_run.get("head_sha") != commit
    ):
        fail(f"{expected_name} artifact binding differs")
    return ArtifactState(
        name=expected_name,
        artifact_id=expected_id,
        digest=expected_digest,
        run_id=run_id,
        head_branch=head_branch,
        head_sha=commit,
        expired=False,
        archive_download_url=expected_url,
        security_snapshot=_snapshot(
            {
                "id": expected_id,
                "name": expected_name,
                "digest": expected_digest,
                "expired": False,
                "archive_download_url": expected_url,
                "workflow_run": {
                    "id": run_id,
                    "head_branch": head_branch,
                    "head_sha": commit,
                },
            }
        ),
    )


def remote_preflight(
    github: GitHub,
    *,
    args: argparse.Namespace,
    local: LocalState,
) -> RemoteState:
    policy = _validate_gate_inputs(args)
    environments = audit_environments(github)
    run = _object(
        github.get(f"repos/{REPOSITORY}/actions/runs/{args.run_id}"),
        "workflow run",
    )
    _reject_unreviewed_bypass(run, "workflow run")
    expected_run = {
        "event": policy.event,
        "path": policy.workflow_path,
        "head_sha": args.expected_commit,
        "head_branch": policy.head_branch,
        "status": "waiting",
        "conclusion": None,
    }
    _exact_id(run.get("id"), args.run_id, "workflow run")
    _exact_attempt(run.get("run_attempt"), "workflow run attempt")
    if any(run.get(field) != value for field, value in expected_run.items()):
        fail("workflow run binding differs")
    jobs_values = _complete_collection(
        github.get(
            f"repos/{REPOSITORY}/actions/runs/{args.run_id}/attempts/"
            f"{RUN_ATTEMPT}/jobs?per_page=100"
        ),
        collection_key="jobs",
        label="workflow jobs",
    )
    if not all(isinstance(job, dict) for job in jobs_values):
        fail("workflow jobs response is malformed")
    jobs = list(jobs_values)
    all_job_ids = [_positive_id(job.get("id"), "workflow job") for job in jobs]
    if len(set(all_job_ids)) != len(all_job_ids):
        fail("workflow job IDs are not distinct")
    calibration = _selected_job(
        jobs,
        ARCHIVE_CALIBRATION_JOB_NAME,
        run_id=args.run_id,
        commit=args.expected_commit,
        head_branch=policy.head_branch,
        status="completed",
        conclusion="success",
    )
    calibration_environment = calibration.get("environment")
    if calibration_environment is not None and calibration_environment != "":
        fail("archive calibration job must not use a protected environment")
    waiting = _selected_job(
        jobs,
        ONBOARDING_JOB_NAME,
        run_id=args.run_id,
        commit=args.expected_commit,
        head_branch=policy.head_branch,
        status="waiting",
        conclusion=None,
    )
    waiting_jobs = [job for job in jobs if job.get("status") == "waiting"]
    if len(waiting_jobs) != 1 or waiting_jobs[0] is not waiting:
        fail("onboarding job is not the run's sole waiting job")
    anchors = [
        _selected_job(
            jobs,
            name,
            run_id=args.run_id,
            commit=args.expected_commit,
            head_branch=policy.head_branch,
            status="completed",
            conclusion="success",
        )
        for name in policy.anchor_names
    ]
    selected_job_ids = [
        _positive_id(calibration.get("id"), "archive calibration job"),
        _positive_id(waiting.get("id"), "onboarding job"),
        *[
            _positive_id(anchor.get("id"), f"{anchor['name']} job")
            for anchor in anchors
        ],
    ]
    if len(set(selected_job_ids)) != len(selected_job_ids):
        fail("selected release job IDs are not distinct")
    artifact_values = _complete_collection(
        github.get(
            f"repos/{REPOSITORY}/actions/runs/{args.run_id}/artifacts?per_page=100"
        ),
        collection_key="artifacts",
        label="workflow artifacts",
    )
    if not all(isinstance(artifact, dict) for artifact in artifact_values):
        fail("workflow artifacts response is malformed")
    all_artifact_ids = [
        _positive_id(artifact.get("id"), "workflow artifact")
        for artifact in artifact_values
    ]
    if len(set(all_artifact_ids)) != len(all_artifact_ids):
        fail("workflow artifact IDs are not distinct")
    names = (PRODUCER_ARTIFACT_NAME, NODE22_ARTIFACT_NAME, NODE24_ARTIFACT_NAME)
    selected_documents: list[dict[str, Any]] = []
    for name in names:
        matches = [
            artifact
            for artifact in artifact_values
            if isinstance(artifact, dict) and artifact.get("name") == name
        ]
        if len(matches) != 1:
            fail(f"{name} artifact is missing or ambiguous")
        selected_documents.append(matches[0])
    slots = (
        (
            PRODUCER_ARTIFACT_NAME,
            local.producer_artifact_id,
            local.producer_observed_digest,
        ),
        (
            NODE22_ARTIFACT_NAME,
            local.node22_artifact_id,
            local.node22_observed_digest,
        ),
        (
            NODE24_ARTIFACT_NAME,
            local.node24_artifact_id,
            local.node24_observed_digest,
        ),
    )
    collection_states = tuple(
        _artifact_state(
            document,
            expected_name=name,
            expected_id=artifact_id,
            expected_digest=digest,
            run_id=args.run_id,
            head_branch=policy.head_branch,
            commit=args.expected_commit,
        )
        for document, (name, artifact_id, digest) in zip(
            selected_documents,
            slots,
            strict=True,
        )
    )
    by_id_values = tuple(
        _artifact_state(
            github.get(f"repos/{REPOSITORY}/actions/artifacts/{artifact_id}"),
            expected_name=name,
            expected_id=artifact_id,
            expected_digest=digest,
            run_id=args.run_id,
            head_branch=policy.head_branch,
            commit=args.expected_commit,
        )
        for name, artifact_id, digest in slots
    )
    by_id_states = (
        by_id_values[0],
        by_id_values[1],
        by_id_values[2],
    )
    if by_id_states != collection_states:
        fail("by-ID artifact metadata differs from the run artifact collection")
    pending = github.get(
        f"repos/{REPOSITORY}/actions/runs/{args.run_id}/pending_deployments"
    )
    _reject_unreviewed_bypass(pending, "pending deployments")
    if not isinstance(pending, list) or len(pending) != 1:
        fail("expected exactly one pending deployment")
    deployment = _object(pending[0], "pending deployment")
    pending_environment = _object(
        deployment.get("environment"),
        "pending deployment environment",
    )
    if (
        pending_environment.get("name") != ONBOARDING_ENVIRONMENT
        or _positive_id(
            pending_environment.get("id"),
            "pending deployment environment",
        )
        != environments.onboarding.environment_id
        or deployment.get("current_user_can_approve") is not True
    ):
        fail("pending onboarding deployment is not bound and approvable")
    run_snapshot = _snapshot(expected_run)
    anchors_snapshot = _snapshot(
        [
            {
                field: anchor.get(field)
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
            for anchor in anchors
        ]
    )
    calibration_snapshot = _snapshot(
        {
            field: calibration.get(field)
            for field in (
                "id",
                "run_id",
                "run_attempt",
                "name",
                "head_sha",
                "head_branch",
                "status",
                "conclusion",
                "environment",
            )
        }
    )
    waiting_snapshot = _snapshot(
        {
            field: waiting.get(field)
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
    collection_snapshot = _snapshot(artifact_values)
    pending_snapshot = _snapshot(deployment)
    security_snapshot = _snapshot(
        {
            "environments": environments.security_snapshot,
            "run": run_snapshot,
            "anchors": anchors_snapshot,
            "calibration": calibration_snapshot,
            "waiting": waiting_snapshot,
            "artifactCollection": collection_snapshot,
            "artifacts": [artifact.security_snapshot for artifact in by_id_states],
            "pending": pending_snapshot,
        }
    )
    return RemoteState(
        mode=policy.name,
        run_id=args.run_id,
        commit=args.expected_commit,
        head_branch=policy.head_branch,
        workflow_ref=policy.workflow_ref,
        onboarding_environment_id=environments.onboarding.environment_id,
        calibration_job_id=_positive_id(
            calibration.get("id"),
            "archive calibration job",
        ),
        environment_audit=environments,
        run_snapshot=run_snapshot,
        anchor_jobs_snapshot=anchors_snapshot,
        calibration_job_snapshot=calibration_snapshot,
        waiting_job_snapshot=waiting_snapshot,
        artifact_collection_snapshot=collection_snapshot,
        artifacts=by_id_states,
        pending_deployment_snapshot=pending_snapshot,
        security_snapshot=security_snapshot,
    )


def validate_hosted_calibration(
    local: LocalState,
    remote: RemoteState,
) -> HostedCalibrationState:
    if (
        local.mode != remote.mode
        or local.run_id != remote.run_id
        or local.commit != remote.commit
    ):
        fail("hosted calibration run identity differs")
    producer, node22, node24 = remote.artifacts
    expected = (
        (
            PRODUCER_ARTIFACT_NAME,
            local.producer_artifact_id,
            local.producer_observed_digest,
        ),
        (
            NODE22_ARTIFACT_NAME,
            local.node22_artifact_id,
            local.node22_observed_digest,
        ),
        (
            NODE24_ARTIFACT_NAME,
            local.node24_artifact_id,
            local.node24_observed_digest,
        ),
    )
    observed = tuple(
        (artifact.name, artifact.artifact_id, artifact.digest)
        for artifact in remote.artifacts
    )
    if observed != expected:
        fail("hosted calibration artifact identity differs")
    aggregate_sha256 = hashlib.sha256(_snapshot(local.aggregate).encode()).hexdigest()
    security_snapshot = _snapshot(
        {
            "local": local.semantic_snapshot,
            "remote": remote.security_snapshot,
            "calibrationJob": remote.calibration_job_snapshot,
            "artifactIdentities": [list(identity) for identity in observed],
            "aggregateSha256": aggregate_sha256,
        }
    )
    return HostedCalibrationState(
        run_id=remote.run_id,
        commit=remote.commit,
        workflow_ref=remote.workflow_ref,
        calibration_job_id=remote.calibration_job_id,
        producer_id=producer.artifact_id,
        producer_digest=producer.digest,
        node22_id=node22.artifact_id,
        node22_digest=node22.digest,
        node24_id=node24.artifact_id,
        node24_digest=node24.digest,
        aggregate_sha256=aggregate_sha256,
        security_snapshot=security_snapshot,
    )


def _validate_approval_response(
    response: Any,
    *,
    commit: str,
    expected_ref: str,
) -> None:
    _reject_unreviewed_bypass(response, "approved deployment")
    if not isinstance(response, list) or len(response) != 1:
        fail("deployment approval did not return exactly one deployment")
    deployment = _object(response[0], "approved deployment")
    _positive_id(deployment.get("id"), "approved deployment")
    if (
        deployment.get("sha") != commit
        or deployment.get("ref") != expected_ref
        or deployment.get("environment") != ONBOARDING_ENVIRONMENT
    ):
        fail("approved deployment binding differs")


def gate(args: argparse.Namespace, github: GitHub | None = None) -> None:
    policy = _validate_gate_inputs(args)
    client = github or GitHub()
    local_1 = validate_local(args)
    remote_1 = remote_preflight(client, args=args, local=local_1)
    calibration_1 = validate_hosted_calibration(local_1, remote_1)
    if not args.approve:
        print(
            "PASS: exact raw-archive onboarding calibration and remote preflight "
            "succeeded; no state changed"
        )
        return
    local_2 = validate_local(args)
    remote_2 = remote_preflight(client, args=args, local=local_2)
    calibration_2 = validate_hosted_calibration(local_2, remote_2)
    if local_2 != local_1:
        fail("local archive evidence changed before deployment approval")
    if remote_2 != remote_1:
        fail("remote approval state changed before deployment approval")
    if calibration_2 != calibration_1:
        fail("hosted calibration state changed before deployment approval")
    payload = json.dumps(
        {
            "environment_ids": [remote_2.onboarding_environment_id],
            "state": "approved",
            "comment": APPROVAL_COMMENT,
        },
        separators=(",", ":"),
    ).encode()
    endpoint = f"repos/{REPOSITORY}/actions/runs/{args.run_id}/pending_deployments"
    post_issued = False
    try:
        post_issued = True
        response = client.post(endpoint, input_bytes=payload)
        _validate_approval_response(
            response,
            commit=args.expected_commit,
            expected_ref=policy.head_branch,
        )
        print("PASS: exact-run TypeScript onboarding deployment approved")
    except ApprovalOutcomeAmbiguous:
        raise
    except BaseException:
        if post_issued:
            raise ApprovalOutcomeAmbiguous from None
        raise


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "audit-environments",
        help="read-only audit of the three fixed protected environments",
    )
    gate_parser = commands.add_parser(
        "gate",
        help="validate one exact onboarding gate and optionally approve it",
    )
    gate_parser.add_argument("--mode", choices=("rehearsal", "publish"), required=True)
    gate_parser.add_argument("--run-id", type=_positive_integer, required=True)
    gate_parser.add_argument(
        "--expected-commit",
        type=_commit_argument,
        required=True,
    )
    for slot in ("producer", "node22", "node24"):
        gate_parser.add_argument(f"--{slot}-archive", type=Path, required=True)
        gate_parser.add_argument(
            f"--{slot}-artifact-id",
            type=_positive_integer,
            required=True,
        )
        gate_parser.add_argument(
            f"--{slot}-artifact-digest",
            type=_digest_argument,
            required=True,
        )
    gate_parser.add_argument("--approve", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        if args.command == "audit-environments":
            audit_environments()
            print("PASS: exact protected-environment audit succeeded; no state changed")
        else:
            gate(args)
    except ApprovalOutcomeAmbiguous as error:
        try:
            print(f"AMBIGUOUS: {error}")
        except BaseException:
            pass
        return 2
    except (ApprovalError, onboarding.EvidenceError) as error:
        print(f"FAIL: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
