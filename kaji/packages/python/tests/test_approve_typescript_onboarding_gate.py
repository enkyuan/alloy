from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import Any
import zipfile

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = REPO_ROOT / "kaji" / "scripts"
APPROVER = SCRIPTS / "approve_typescript_onboarding_gate.py"
RUN_ID = 123
COMMIT = "a" * 40
TAG = "kaji-v0.2.0-beta.11"
PRODUCER_ID = 456
NODE22_ID = 2201
NODE24_ID = 2401
ENVIRONMENT_IDS = {
    "kaji-beta-onboarding": 7001,
    "kaji-beta": 7002,
    "kaji-beta-publish": 7003,
}


def _load_script() -> ModuleType:
    scripts = str(SCRIPTS)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location(
        "test_approve_typescript_onboarding_gate",
        APPROVER,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_onboarding_support() -> ModuleType:
    path = Path(__file__).with_name("test_typescript_onboarding_evidence.py")
    spec = importlib.util.spec_from_file_location(
        "_approve_typescript_onboarding_support",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha256(encoded: bytes) -> str:
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _raw_args(
    tmp_path: Path,
    *,
    mode: str = "rehearsal",
    approve: bool = False,
) -> SimpleNamespace:
    support = _load_onboarding_support()
    validator = support._module()
    compatibility = support._support()
    producer_members = support._release_members(validator)
    producer_bytes = support._zip_bytes(producer_members)
    producer_path = tmp_path / f"{mode}-producer.zip"
    producer_path.write_bytes(producer_bytes)
    manifest_sha256 = hashlib.sha256(producer_members["manifest.json"]).hexdigest()
    tarball = producer_members[support.TARBALL]
    common = {
        "commit": COMMIT,
        "manifest_sha256": manifest_sha256,
        "tarball_sha256": hashlib.sha256(tarball).hexdigest(),
        "tarball_size": len(tarball),
        "workflow_run": (f"https://github.com/enkyuan/alloy/actions/runs/{RUN_ID}"),
        "workflow_run_attempt": 1,
        "producer_artifact_id": PRODUCER_ID,
        "producer_artifact_digest": _sha256(producer_bytes),
    }
    workflow_ref = (
        "enkyuan/alloy/.github/workflows/kaji.rehearsal.yml@refs/heads/main"
        if mode == "rehearsal"
        else (
            "enkyuan/alloy/.github/workflows/kaji.publish.yml"
            "@refs/tags/kaji-v0.2.0-beta.11"
        )
    )
    paths: dict[int, Path] = {}
    digests: dict[int, str] = {}
    for major in (22, 24):
        receipt = compatibility.node_v2_receipt(major, **common)
        receipt["invocation"]["workflowRef"] = workflow_ref
        encoded = support._zip_bytes(
            {
                "compatibility-receipt.json": json.dumps(
                    receipt,
                    sort_keys=True,
                ).encode()
            }
        )
        path = tmp_path / f"{mode}-node-{major}.zip"
        path.write_bytes(encoded)
        paths[major] = path
        digests[major] = _sha256(encoded)
    return SimpleNamespace(
        command="gate",
        mode=mode,
        run_id=RUN_ID,
        expected_commit=COMMIT,
        producer_archive=producer_path,
        producer_artifact_id=PRODUCER_ID,
        producer_artifact_digest=_sha256(producer_bytes),
        node22_archive=paths[22],
        node22_artifact_id=NODE22_ID,
        node22_artifact_digest=digests[22],
        node24_archive=paths[24],
        node24_artifact_id=NODE24_ID,
        node24_artifact_digest=digests[24],
        approve=approve,
    )


class FakeGitHub:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, bytes | None]] = []

    def _next(self, method: str, endpoint: str, body: bytes | None) -> Any:
        self.calls.append((method, endpoint, body))
        assert self.responses, f"unexpected {method}: {endpoint}"
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return deepcopy(response)

    def get(self, endpoint: str) -> Any:
        return self._next("GET", endpoint, None)

    def post(self, endpoint: str, *, input_bytes: bytes) -> Any:
        return self._next("POST", endpoint, input_bytes)


def _environment(name: str) -> dict[str, Any]:
    return {
        "id": ENVIRONMENT_IDS[name],
        "node_id": f"ENVIRONMENT_{ENVIRONMENT_IDS[name]}",
        "name": name,
        "url": f"https://api.github.com/repos/enkyuan/alloy/environments/{name}",
        "html_url": (
            "https://github.com/enkyuan/alloy/deployments/activity_log"
            f"?environments_filter={name}"
        ),
        "created_at": "2026-07-27T00:00:00Z",
        "updated_at": "2026-07-27T00:00:00Z",
        "can_admins_bypass": False,
        "deployment_branch_policy": {
            "protected_branches": False,
            "custom_branch_policies": True,
        },
        "protection_rules": [
            {
                "id": ENVIRONMENT_IDS[name] * 10 + 1,
                "node_id": f"ENVIRONMENT_REVIEW_RULE_{ENVIRONMENT_IDS[name]}",
                "type": "required_reviewers",
                "prevent_self_review": False,
                "reviewers": [
                    {
                        "type": "User",
                        "reviewer": {
                            "avatar_url": (
                                "https://avatars.githubusercontent.com/u/90286412?v=4"
                            ),
                            "events_url": (
                                "https://api.github.com/users/enkyuan/events{/privacy}"
                            ),
                            "followers_url": (
                                "https://api.github.com/users/enkyuan/followers"
                            ),
                            "following_url": (
                                "https://api.github.com/users/enkyuan/"
                                "following{/other_user}"
                            ),
                            "gists_url": (
                                "https://api.github.com/users/enkyuan/gists{/gist_id}"
                            ),
                            "gravatar_id": "",
                            "html_url": "https://github.com/enkyuan",
                            "id": 90286412,
                            "node_id": "USER_90286412",
                            "login": "enkyuan",
                            "organizations_url": (
                                "https://api.github.com/users/enkyuan/orgs"
                            ),
                            "received_events_url": (
                                "https://api.github.com/users/enkyuan/received_events"
                            ),
                            "repos_url": "https://api.github.com/users/enkyuan/repos",
                            "starred_url": (
                                "https://api.github.com/users/enkyuan/"
                                "starred{/owner}{/repo}"
                            ),
                            "subscriptions_url": (
                                "https://api.github.com/users/enkyuan/subscriptions"
                            ),
                            "type": "User",
                            "user_view_type": "public",
                            "site_admin": False,
                            "url": "https://api.github.com/users/enkyuan",
                        },
                    }
                ],
            },
            {
                "id": ENVIRONMENT_IDS[name] * 10 + 2,
                "node_id": f"ENVIRONMENT_BRANCH_RULE_{ENVIRONMENT_IDS[name]}",
                "type": "branch_policy",
            },
        ],
    }


def _policies(name: str) -> dict[str, Any]:
    values = [
        {
            "id": ENVIRONMENT_IDS[name] * 10 + 3,
            "node_id": f"ENVIRONMENT_TAG_POLICY_{ENVIRONMENT_IDS[name]}",
            "name": TAG,
            "type": "tag",
        }
    ]
    if name != "kaji-beta-publish":
        values.append(
            {
                "id": ENVIRONMENT_IDS[name] * 10 + 4,
                "node_id": f"ENVIRONMENT_BRANCH_POLICY_{ENVIRONMENT_IDS[name]}",
                "name": "main",
                "type": "branch",
            }
        )
    return {"total_count": len(values), "branch_policies": values}


def _environment_responses() -> list[Any]:
    responses: list[Any] = []
    for name in ("kaji-beta-onboarding", "kaji-beta", "kaji-beta-publish"):
        responses.extend([_environment(name), _policies(name)])
    return responses


def _run(mode: str) -> dict[str, Any]:
    return {
        "id": RUN_ID,
        "run_attempt": 1,
        "event": "workflow_dispatch" if mode == "rehearsal" else "push",
        "path": (
            ".github/workflows/kaji.rehearsal.yml"
            if mode == "rehearsal"
            else ".github/workflows/kaji.publish.yml"
        ),
        "head_sha": COMMIT,
        "head_branch": "main" if mode == "rehearsal" else TAG,
        "status": "waiting",
        "conclusion": None,
    }


def _job(
    name: str,
    *,
    mode: str,
    job_id: int,
    status: str,
    conclusion: str | None,
) -> dict[str, Any]:
    return {
        "id": job_id,
        "run_id": RUN_ID,
        "run_attempt": 1,
        "name": name,
        "head_sha": COMMIT,
        "head_branch": "main" if mode == "rehearsal" else TAG,
        "status": status,
        "conclusion": conclusion,
    }


def _jobs(mode: str) -> dict[str, Any]:
    values = [
        _job(
            "TypeScript onboarding archive calibration",
            mode=mode,
            job_id=101,
            status="completed",
            conclusion="success",
        ),
        _job(
            "TypeScript onboarding evidence",
            mode=mode,
            job_id=102,
            status="waiting",
            conclusion=None,
        ),
    ]
    anchors = (
        ("offline release",)
        if mode == "rehearsal"
        else ("verify release tag", "offline release gates")
    )
    for offset, name in enumerate(anchors, start=103):
        values.append(
            _job(
                name,
                mode=mode,
                job_id=offset,
                status="completed",
                conclusion="success",
            )
        )
    return {"total_count": len(values), "jobs": values}


def _artifact(
    name: str,
    artifact_id: int,
    digest: str,
    *,
    mode: str,
) -> dict[str, Any]:
    return {
        "id": artifact_id,
        "name": name,
        "digest": digest,
        "expired": False,
        "archive_download_url": (
            "https://api.github.com/repos/enkyuan/alloy/actions/artifacts/"
            f"{artifact_id}/zip"
        ),
        "workflow_run": {
            "id": RUN_ID,
            "head_branch": "main" if mode == "rehearsal" else TAG,
            "head_sha": COMMIT,
        },
    }


def _artifacts(args: SimpleNamespace) -> list[dict[str, Any]]:
    return [
        _artifact(
            "kaji-beta-artifacts",
            PRODUCER_ID,
            args.producer_artifact_digest,
            mode=args.mode,
        ),
        _artifact(
            "kaji-node-compat-22",
            NODE22_ID,
            args.node22_artifact_digest,
            mode=args.mode,
        ),
        _artifact(
            "kaji-node-compat-24",
            NODE24_ID,
            args.node24_artifact_digest,
            mode=args.mode,
        ),
    ]


def _pending() -> list[dict[str, Any]]:
    return [
        {
            "environment": {
                "id": ENVIRONMENT_IDS["kaji-beta-onboarding"],
                "name": "kaji-beta-onboarding",
            },
            "current_user_can_approve": True,
            "wait_timer": 0,
            "reviewers": [],
        }
    ]


def _remote_responses(args: SimpleNamespace) -> list[Any]:
    artifacts = _artifacts(args)
    return [
        *_environment_responses(),
        _run(args.mode),
        _jobs(args.mode),
        {"total_count": len(artifacts), "artifacts": artifacts},
        *artifacts,
        _pending(),
    ]


def _approval(mode: str) -> list[dict[str, Any]]:
    return [
        {
            "id": 9901,
            "sha": COMMIT,
            "ref": "main" if mode == "rehearsal" else TAG,
            "environment": "kaji-beta-onboarding",
        }
    ]


def test_policy_constants_are_fixed_to_the_reviewed_beta10_transaction() -> None:
    module = _load_script()

    assert module.REPOSITORY == "enkyuan/alloy"
    assert module.API_VERSION == "2026-03-10"
    assert module.RUN_ATTEMPT == 1
    assert module.TAG == "kaji-v0.2.0-beta.11"
    assert module.ONBOARDING_ENVIRONMENT == "kaji-beta-onboarding"
    assert module.PROVIDER_ENVIRONMENT == "kaji-beta"
    assert module.PUBLISH_ENVIRONMENT == "kaji-beta-publish"
    assert module.REVIEWER_TYPE == "User"
    assert module.REVIEWER_LOGIN == "enkyuan"
    assert module.REVIEWER_ID == 90286412
    assert module.ONBOARDING_JOB_NAME == "TypeScript onboarding evidence"
    assert (
        module.ARCHIVE_CALIBRATION_JOB_NAME
        == "TypeScript onboarding archive calibration"
    )
    assert module.PRODUCER_ARTIFACT_NAME == "kaji-beta-artifacts"
    assert module.NODE22_ARTIFACT_NAME == "kaji-node-compat-22"
    assert module.NODE24_ARTIFACT_NAME == "kaji-node-compat-24"


def test_cli_requires_exactly_three_raw_archive_slots() -> None:
    module = _load_script()
    args = module.parse_args(
        [
            "gate",
            "--mode",
            "rehearsal",
            "--run-id",
            "123",
            "--expected-commit",
            "a" * 40,
            "--producer-archive",
            "producer.zip",
            "--producer-artifact-id",
            "456",
            "--producer-artifact-digest",
            "sha256:" + "b" * 64,
            "--node22-archive",
            "node22.zip",
            "--node22-artifact-id",
            "2201",
            "--node22-artifact-digest",
            "sha256:" + "c" * 64,
            "--node24-archive",
            "node24.zip",
            "--node24-artifact-id",
            "2401",
            "--node24-artifact-digest",
            "sha256:" + "d" * 64,
        ]
    )

    assert args.command == "gate"
    assert args.mode == "rehearsal"
    assert args.approve is False
    assert args.producer_archive == Path("producer.zip")
    assert args.node22_archive == Path("node22.zip")
    assert args.node24_archive == Path("node24.zip")


@pytest.mark.parametrize(
    "option",
    [
        "--release-manifest",
        "--artifacts-dir",
        "--tarball",
        "--node22-receipt",
        "--node24-receipt",
        "--runner",
        "--image-version",
        "--repository",
        "--tag",
        "--environment",
        "--api-version",
        "--token",
    ],
)
def test_cli_rejects_every_forbidden_override(
    option: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script()

    with pytest.raises(SystemExit):
        module.parse_args(["audit-environments", option, "value"])

    assert "unrecognized arguments" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argument", "value"),
    [
        ("--run-id", "0"),
        ("--run-id", str(9_007_199_254_740_992)),
        ("--expected-commit", "A" * 40),
        ("--producer-artifact-id", "false"),
        ("--producer-artifact-digest", "sha256:" + "A" * 64),
    ],
)
def test_cli_rejects_noncanonical_identities(
    argument: str,
    value: str,
) -> None:
    module = _load_script()
    values = [
        "gate",
        "--mode",
        "rehearsal",
        "--run-id",
        "123",
        "--expected-commit",
        "a" * 40,
        "--producer-archive",
        "producer.zip",
        "--producer-artifact-id",
        "456",
        "--producer-artifact-digest",
        "sha256:" + "b" * 64,
        "--node22-archive",
        "node22.zip",
        "--node22-artifact-id",
        "2201",
        "--node22-artifact-digest",
        "sha256:" + "c" * 64,
        "--node24-archive",
        "node24.zip",
        "--node24-artifact-id",
        "2401",
        "--node24-artifact-digest",
        "sha256:" + "d" * 64,
    ]
    position = values.index(argument) + 1
    values[position] = value

    with pytest.raises(SystemExit):
        module.parse_args(values)


@pytest.mark.parametrize("mode", ["rehearsal", "publish"])
def test_local_validation_uses_exact_authenticated_archive_bytes(
    tmp_path: Path,
    mode: str,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path, mode=mode)

    local = module.validate_local(args)

    assert local.mode == mode
    assert local.commit == COMMIT
    assert local.producer_observed_digest == _sha256(args.producer_archive.read_bytes())
    assert local.node22_observed_digest == _sha256(args.node22_archive.read_bytes())
    assert local.node24_observed_digest == _sha256(args.node24_archive.read_bytes())
    assert local.aggregate["commit"] == COMMIT
    assert str(args.producer_archive) not in local.semantic_snapshot
    assert "compatibility-receipt.json" not in local.semantic_snapshot


@pytest.mark.parametrize(
    ("path_field", "digest_field"),
    [
        ("producer_archive", "producer_artifact_digest"),
        ("node22_archive", "node22_artifact_digest"),
        ("node24_archive", "node24_artifact_digest"),
    ],
)
def test_raw_archive_byte_mutation_blocks_before_github(
    tmp_path: Path,
    path_field: str,
    digest_field: str,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path, approve=True)
    path = getattr(args, path_field)
    path.write_bytes(path.read_bytes()[:-1] + bytes([path.read_bytes()[-1] ^ 1]))
    github = FakeGitHub([])

    with pytest.raises(module.onboarding.EvidenceError):
        module.gate(args, github)

    assert github.calls == []
    assert getattr(args, digest_field).startswith("sha256:")


def test_semantically_valid_repack_with_new_digest_still_requires_rest_binding(
    tmp_path: Path,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path, approve=True)
    original_remote = _remote_responses(args)
    with zipfile.ZipFile(BytesIO(args.node22_archive.read_bytes())) as archive:
        receipt = json.loads(archive.read("compatibility-receipt.json"))
    support = _load_onboarding_support()
    repacked = support._zip_bytes(
        {
            "compatibility-receipt.json": json.dumps(
                receipt,
                indent=2,
                sort_keys=True,
            ).encode()
        }
    )
    args.node22_archive.write_bytes(repacked)
    args.node22_artifact_digest = _sha256(repacked)
    github = FakeGitHub(original_remote)

    with pytest.raises(module.ApprovalError, match="artifact binding differs"):
        module.gate(args, github)

    assert len(github.calls) == 9
    assert not any(call[0] == "POST" for call in github.calls)


def test_local_validation_delegates_only_to_task3b_public_archive_surface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path)
    observed: list[str] = []
    for name in (
        "load_authenticated_archive",
        "compose_document",
        "validate_document",
        "recompute_and_compare",
    ):
        original = getattr(module.onboarding, name)

        def wrapped(
            *call_args: Any,
            _name: str = name,
            _original: Any = original,
            **call_kwargs: Any,
        ) -> Any:
            observed.append(_name)
            return _original(*call_args, **call_kwargs)

        monkeypatch.setattr(module.onboarding, name, wrapped)

    module.validate_local(args)

    assert observed.count("load_authenticated_archive") == 3
    assert observed.count("compose_document") == 1
    assert observed.count("recompute_and_compare") == 1
    assert observed.count("validate_document") >= 1


def test_duplicate_artifact_ids_block_before_file_or_github_access(
    tmp_path: Path,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path, approve=True)
    args.node22_artifact_id = args.producer_artifact_id
    args.producer_archive.unlink()
    github = FakeGitHub([])

    with pytest.raises(module.ApprovalError, match="not distinct"):
        module.gate(args, github)

    assert github.calls == []


def test_read_only_environment_audit_is_exactly_six_ordered_gets() -> None:
    module = _load_script()
    github = FakeGitHub(_environment_responses())

    state = module.audit_environments(github)

    assert state.onboarding.environment_id == 7001
    assert state.provider.environment_id == 7002
    assert state.publisher.environment_id == 7003
    assert [call[:2] for call in github.calls] == [
        (
            "GET",
            "repos/enkyuan/alloy/environments/kaji-beta-onboarding",
        ),
        (
            "GET",
            "repos/enkyuan/alloy/environments/kaji-beta-onboarding/"
            "deployment-branch-policies?per_page=100",
        ),
        ("GET", "repos/enkyuan/alloy/environments/kaji-beta"),
        (
            "GET",
            "repos/enkyuan/alloy/environments/kaji-beta/"
            "deployment-branch-policies?per_page=100",
        ),
        ("GET", "repos/enkyuan/alloy/environments/kaji-beta-publish"),
        (
            "GET",
            "repos/enkyuan/alloy/environments/kaji-beta-publish/"
            "deployment-branch-policies?per_page=100",
        ),
    ]
    assert all(
        method == "GET" and "/secrets" not in endpoint
        for method, endpoint, _ in github.calls
    )


@pytest.mark.parametrize(
    ("response_index", "mutation"),
    [
        (0, lambda value: value.update(can_admins_bypass=True)),
        (
            0,
            lambda value: value["protection_rules"][0].update(prevent_self_review=True),
        ),
        (
            2,
            lambda value: value["protection_rules"][0]["reviewers"][0][
                "reviewer"
            ].update(login="other"),
        ),
        (
            4,
            lambda value: value["protection_rules"].append(
                {"id": 999, "type": "wait_timer"}
            ),
        ),
        (
            1,
            lambda value: value["branch_policies"].append(
                {
                    "id": 999,
                    "node_id": "WILDCARD_POLICY",
                    "name": "*",
                    "type": "branch",
                }
            ),
        ),
        (
            1,
            lambda value: value["branch_policies"][0].update(type="branch"),
        ),
        (
            5,
            lambda value: value["branch_policies"].append(
                {
                    "id": 999,
                    "node_id": "EXTRA_MAIN_POLICY",
                    "name": "main",
                    "type": "branch",
                }
            ),
        ),
    ],
)
def test_environment_policy_drift_fails_closed(
    response_index: int,
    mutation: Any,
) -> None:
    module = _load_script()
    responses = _environment_responses()
    mutation(responses[response_index])
    if response_index % 2 == 1:
        responses[response_index]["total_count"] = len(
            responses[response_index]["branch_policies"]
        )
    github = FakeGitHub(responses)

    with pytest.raises(module.ApprovalError):
        module.audit_environments(github)

    assert all(call[0] == "GET" for call in github.calls)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda identity: identity.update(can_skip_required_review=True),
        lambda identity: identity.update(extra_field="unexpected"),
        lambda identity: identity.pop("avatar_url"),
        lambda identity: identity.pop("received_events_url"),
        lambda identity: identity.update(id=1),
        lambda identity: identity.update(login="other"),
        lambda identity: identity.update(node_id=""),
        lambda identity: identity.update(type="Organization"),
        lambda identity: identity.update(user_view_type="private"),
        lambda identity: identity.update(site_admin=True),
        lambda identity: identity.update(url="https://api.github.com/users/other"),
        lambda identity: identity.update(
            avatar_url="https://avatars.githubusercontent.com/u/1?v=4"
        ),
        lambda identity: identity.update(
            following_url="https://api.github.com/users/other/following{/other_user}"
        ),
        lambda identity: identity.update(gravatar_id="unexpected"),
        lambda identity: identity.update(html_url="https://github.com/other"),
        lambda identity: identity.update(
            followers_url="https://api.github.com/users/other/followers"
        ),
        lambda identity: identity.update(
            gists_url="https://api.github.com/users/other/gists{/gist_id}"
        ),
        lambda identity: identity.update(
            starred_url="https://api.github.com/users/other/starred{/owner}{/repo}"
        ),
        lambda identity: identity.update(
            subscriptions_url="https://api.github.com/users/other/subscriptions"
        ),
        lambda identity: identity.update(
            organizations_url="https://api.github.com/users/other/orgs"
        ),
        lambda identity: identity.update(
            repos_url="https://api.github.com/users/other/repos"
        ),
        lambda identity: identity.update(
            events_url="https://api.github.com/users/other/events{/privacy}"
        ),
        lambda identity: identity.update(
            received_events_url="https://api.github.com/users/other/received_events"
        ),
    ],
)
def test_required_reviewer_identity_shape_fails_closed(
    mutation: Any,
) -> None:
    module = _load_script()
    responses = _environment_responses()
    identity = responses[0]["protection_rules"][0]["reviewers"][0]["reviewer"]
    mutation(identity)
    github = FakeGitHub(responses)

    with pytest.raises(module.ApprovalError):
        module.audit_environments(github)

    assert all(call[0] == "GET" for call in github.calls)


@pytest.mark.parametrize("collection", ["policies", "jobs", "artifacts"])
def test_remote_collection_envelopes_reject_unreviewed_fields(
    tmp_path: Path,
    collection: str,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path)
    responses = _remote_responses(args)
    response_index = {"policies": 1, "jobs": 7, "artifacts": 8}[collection]
    responses[response_index]["security_controls"] = []
    github = FakeGitHub(responses)

    with pytest.raises(module.ApprovalError, match="unreviewed field"):
        module.gate(args, github)

    assert not any(call[0] == "POST" for call in github.calls)


@pytest.mark.parametrize("mode", ["rehearsal", "publish"])
def test_dry_run_performs_exact_thirteen_get_snapshot_without_post(
    tmp_path: Path,
    mode: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path, mode=mode)
    github = FakeGitHub(_remote_responses(args))

    module.gate(args, github)

    assert len(github.calls) == 13
    assert all(call[0] == "GET" for call in github.calls)
    assert not github.responses
    assert "no state changed" in capsys.readouterr().out
    assert github.calls[-7:] == [
        ("GET", f"repos/enkyuan/alloy/actions/runs/{RUN_ID}", None),
        (
            "GET",
            f"repos/enkyuan/alloy/actions/runs/{RUN_ID}/attempts/1/jobs?per_page=100",
            None,
        ),
        (
            "GET",
            f"repos/enkyuan/alloy/actions/runs/{RUN_ID}/artifacts?per_page=100",
            None,
        ),
        (
            "GET",
            f"repos/enkyuan/alloy/actions/artifacts/{PRODUCER_ID}",
            None,
        ),
        ("GET", f"repos/enkyuan/alloy/actions/artifacts/{NODE22_ID}", None),
        ("GET", f"repos/enkyuan/alloy/actions/artifacts/{NODE24_ID}", None),
        (
            "GET",
            f"repos/enkyuan/alloy/actions/runs/{RUN_ID}/pending_deployments",
            None,
        ),
    ]


@pytest.mark.parametrize("mode", ["rehearsal", "publish"])
def test_success_repeats_both_snapshots_then_posts_one_exact_body(
    tmp_path: Path,
    mode: str,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path, mode=mode, approve=True)
    github = FakeGitHub(
        [
            *_remote_responses(args),
            *_remote_responses(args),
            _approval(mode),
        ]
    )

    module.gate(args, github)

    assert [call[0] for call in github.calls] == [
        *(["GET"] * 13),
        *(["GET"] * 13),
        "POST",
    ]
    assert github.calls[-1][1] == (
        f"repos/enkyuan/alloy/actions/runs/{RUN_ID}/pending_deployments"
    )
    assert github.calls[-1][2] is not None
    assert json.loads(github.calls[-1][2]) == {
        "environment_ids": [ENVIRONMENT_IDS["kaji-beta-onboarding"]],
        "state": "approved",
        "comment": "Approve exact-run TypeScript onboarding evidence.",
    }
    assert not github.responses


def test_approval_transaction_order_is_local_remote_calibration_twice_then_post(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path, approve=True)
    events: list[str] = []
    for name, label in (
        ("validate_local", "local"),
        ("remote_preflight", "remote"),
        ("validate_hosted_calibration", "calibration"),
    ):
        original = getattr(module, name)

        def wrapped(
            *call_args: Any,
            _label: str = label,
            _original: Any = original,
            **call_kwargs: Any,
        ) -> Any:
            events.append(_label)
            return _original(*call_args, **call_kwargs)

        monkeypatch.setattr(module, name, wrapped)

    class OrderedFake(FakeGitHub):
        def post(self, endpoint: str, *, input_bytes: bytes) -> Any:
            events.append("POST")
            return super().post(endpoint, input_bytes=input_bytes)

    github = OrderedFake(
        [
            *_remote_responses(args),
            *_remote_responses(args),
            _approval("rehearsal"),
        ]
    )

    module.gate(args, github)

    assert events == [
        "local",
        "remote",
        "calibration",
        "local",
        "remote",
        "calibration",
        "POST",
    ]


@pytest.mark.parametrize(
    ("area", "field", "value"),
    [
        ("run", "event", "push"),
        ("run", "path", ".github/workflows/kaji.publish.yml"),
        ("run", "head_branch", TAG),
        ("run", "run_attempt", 2),
        ("run", "status", "completed"),
        ("run", "conclusion", "success"),
        ("calibration", "conclusion", "failure"),
        ("calibration", "run_attempt", 2),
        ("waiting", "head_sha", "b" * 40),
        ("anchor", "status", "waiting"),
    ],
)
def test_run_job_or_anchor_drift_blocks_before_post(
    tmp_path: Path,
    area: str,
    field: str,
    value: Any,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path, approve=True)
    responses = _remote_responses(args)
    if area == "run":
        responses[6][field] = value
    else:
        jobs = responses[7]["jobs"]
        name = {
            "calibration": "TypeScript onboarding archive calibration",
            "waiting": "TypeScript onboarding evidence",
            "anchor": "offline release",
        }[area]
        next(job for job in jobs if job["name"] == name)[field] = value
    github = FakeGitHub(responses)

    with pytest.raises(module.ApprovalError):
        module.gate(args, github)

    assert not any(call[0] == "POST" for call in github.calls)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda responses: responses[7]["jobs"].append(
            deepcopy(responses[7]["jobs"][0])
        ),
        lambda responses: responses[7]["jobs"].append(
            {
                **deepcopy(responses[7]["jobs"][0]),
                "id": 999,
                "name": "unrelated waiting",
                "status": "waiting",
                "conclusion": None,
            }
        ),
    ],
)
def test_duplicate_calibration_or_second_waiter_blocks(
    tmp_path: Path,
    mutation: Any,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path, approve=True)
    responses = _remote_responses(args)
    mutation(responses)
    responses[7]["total_count"] = len(responses[7]["jobs"])
    github = FakeGitHub(responses)

    with pytest.raises(module.ApprovalError):
        module.gate(args, github)

    assert not any(call[0] == "POST" for call in github.calls)


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("collection", "total_count", 2),
        ("producer", "id", 999),
        ("producer", "digest", "sha256:" + "f" * 64),
        ("node22", "name", "kaji-node-compat-24"),
        ("node22", "expired", True),
        ("node24", "archive_download_url", "https://example.test/signed"),
        ("node24-run", "head_sha", "b" * 40),
    ],
)
def test_artifact_collection_or_by_id_drift_blocks(
    tmp_path: Path,
    target: str,
    field: str,
    value: Any,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path, approve=True)
    responses = _remote_responses(args)
    indexes = {"producer": 9, "node22": 10, "node24": 11, "node24-run": 11}
    if target == "collection":
        responses[8][field] = value
    elif target == "node24-run":
        responses[indexes[target]]["workflow_run"][field] = value
    else:
        responses[indexes[target]][field] = value
    github = FakeGitHub(responses)

    with pytest.raises(module.ApprovalError):
        module.gate(args, github)

    assert not any(call[0] == "POST" for call in github.calls)


def test_duplicate_target_name_in_complete_collection_blocks(
    tmp_path: Path,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path, approve=True)
    responses = _remote_responses(args)
    duplicate_name = deepcopy(responses[8]["artifacts"][0])
    duplicate_name["id"] = 8802
    responses[8]["artifacts"].append(duplicate_name)
    responses[8]["total_count"] += 1
    github = FakeGitHub(responses)

    with pytest.raises(module.ApprovalError, match="missing or ambiguous"):
        module.gate(args, github)

    assert not any(call[0] == "POST" for call in github.calls)


@pytest.mark.parametrize("case", ["zero", "multiple", "wrong-id", "not-approvable"])
def test_pending_deployment_ambiguity_blocks(
    tmp_path: Path,
    case: str,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path, approve=True)
    responses = _remote_responses(args)
    if case == "zero":
        responses[12] = []
    elif case == "multiple":
        responses[12].append(deepcopy(responses[12][0]))
    elif case == "wrong-id":
        responses[12][0]["environment"]["id"] += 1
    else:
        responses[12][0]["current_user_can_approve"] = False
    github = FakeGitHub(responses)

    with pytest.raises(module.ApprovalError):
        module.gate(args, github)

    assert not any(call[0] == "POST" for call in github.calls)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda responses: responses[6].update(can_bypass_required_review=True),
        lambda responses: responses[7]["jobs"][0].update(
            can_bypass_required_review=True
        ),
        lambda responses: responses[8]["artifacts"][0].update(
            can_bypass_required_review=True
        ),
        lambda responses: responses[9]["workflow_run"].update(
            can_bypass_required_review=True
        ),
        lambda responses: responses[12][0].update(can_bypass_required_review=True),
    ],
)
def test_unreviewed_bypass_in_any_remote_approval_input_blocks(
    tmp_path: Path,
    mutation: Any,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path, approve=True)
    responses = _remote_responses(args)
    mutation(responses)
    github = FakeGitHub(responses)

    with pytest.raises(module.ApprovalError, match="unreviewed bypass"):
        module.gate(args, github)

    assert not any(call[0] == "POST" for call in github.calls)


@pytest.mark.parametrize("drift", ["environment", "artifact", "pending"])
def test_remote_security_drift_between_snapshots_blocks_post(
    tmp_path: Path,
    drift: str,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path, approve=True)
    second = _remote_responses(args)
    if drift == "environment":
        second[0]["id"] += 10
        second[12][0]["environment"]["id"] += 10
    elif drift == "artifact":
        second[8]["artifacts"].append(
            {
                "id": 8801,
                "name": "unrelated-evidence",
                "digest": "sha256:" + "e" * 64,
                "expired": False,
            }
        )
        second[8]["total_count"] += 1
    else:
        second[12][0]["wait_timer"] = 30
    github = FakeGitHub([*_remote_responses(args), *second])

    with pytest.raises(module.ApprovalError, match="changed"):
        module.gate(args, github)

    assert not any(call[0] == "POST" for call in github.calls)


def test_local_archive_replacement_between_snapshots_blocks_post(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path, approve=True)
    original = module.validate_local
    calls = 0

    def changed_local(arguments: Any) -> Any:
        nonlocal calls
        calls += 1
        state = original(arguments)
        if calls == 2:
            return module.LocalState(
                **{
                    **{
                        field: getattr(state, field)
                        for field in state.__dataclass_fields__
                    },
                    "semantic_snapshot": state.semantic_snapshot + "drift",
                }
            )
        return state

    monkeypatch.setattr(module, "validate_local", changed_local)
    github = FakeGitHub([*_remote_responses(args), *_remote_responses(args)])

    with pytest.raises(module.ApprovalError, match="local archive evidence changed"):
        module.gate(args, github)

    assert calls == 2
    assert not any(call[0] == "POST" for call in github.calls)


def test_calibration_state_drift_between_snapshots_blocks_post(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path, approve=True)
    original = module.validate_hosted_calibration
    calls = 0

    def changed_calibration(local: Any, remote: Any) -> Any:
        nonlocal calls
        calls += 1
        state = original(local, remote)
        if calls == 2:
            return module.HostedCalibrationState(
                **{
                    **{
                        field: getattr(state, field)
                        for field in state.__dataclass_fields__
                    },
                    "security_snapshot": state.security_snapshot + "drift",
                }
            )
        return state

    monkeypatch.setattr(
        module,
        "validate_hosted_calibration",
        changed_calibration,
    )
    github = FakeGitHub([*_remote_responses(args), *_remote_responses(args)])

    with pytest.raises(module.ApprovalError, match="calibration state changed"):
        module.gate(args, github)

    assert calls == 2
    assert not any(call[0] == "POST" for call in github.calls)


@pytest.mark.parametrize(
    "response",
    [
        RuntimeError("sensitive transport output"),
        [],
        [
            {
                "id": 1,
                "sha": COMMIT,
                "ref": "main",
                "environment": "other",
            }
        ],
        [
            {
                "id": 1,
                "sha": COMMIT,
                "ref": "main",
                "environment": "kaji-beta-onboarding",
                "can_bypass_required_review": True,
            }
        ],
        [
            {
                "id": 1,
                "sha": COMMIT,
                "ref": "main",
                "environment": "kaji-beta-onboarding",
            },
            {
                "id": 2,
                "sha": COMMIT,
                "ref": "main",
                "environment": "kaji-beta-onboarding",
            },
        ],
    ],
)
def test_every_post_issuance_failure_is_ambiguous_and_never_retried(
    tmp_path: Path,
    response: Any,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path, approve=True)
    github = FakeGitHub([*_remote_responses(args), *_remote_responses(args), response])

    with pytest.raises(module.ApprovalOutcomeAmbiguous) as captured:
        module.gate(args, github)

    assert str(captured.value) == module.AMBIGUOUS_MESSAGE
    assert "sensitive transport output" not in str(captured.value)
    assert len([call for call in github.calls if call[0] == "POST"]) == 1


def test_success_output_failure_after_post_is_ambiguous_and_never_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path, approve=True)
    github = FakeGitHub(
        [
            *_remote_responses(args),
            *_remote_responses(args),
            _approval("rehearsal"),
        ]
    )

    def fail_success_output(*_args: Any, **_kwargs: Any) -> None:
        raise BrokenPipeError("sensitive stdout diagnostic")

    monkeypatch.setattr("builtins.print", fail_success_output)

    with pytest.raises(module.ApprovalOutcomeAmbiguous) as captured:
        module.gate(args, github)

    assert str(captured.value) == module.AMBIGUOUS_MESSAGE
    assert "sensitive stdout diagnostic" not in str(captured.value)
    assert len([call for call in github.calls if call[0] == "POST"]) == 1


def test_dry_run_output_failure_remains_ordinary_without_post(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path)
    github = FakeGitHub(_remote_responses(args))

    def fail_output(*_args: Any, **_kwargs: Any) -> None:
        raise BrokenPipeError("dry-run stdout diagnostic")

    monkeypatch.setattr("builtins.print", fail_output)

    with pytest.raises(BrokenPipeError, match="dry-run stdout diagnostic"):
        module.gate(args, github)

    assert not any(call[0] == "POST" for call in github.calls)


@pytest.mark.parametrize(
    ("returncode", "stdout", "message"),
    [
        (1, b"sensitive stdout", "GitHub command failed"),
        (0, b"not-json", "GitHub returned malformed JSON"),
        (0, b"\xff", "GitHub returned malformed JSON"),
    ],
)
def test_github_adapter_is_versioned_and_redacts_failures(
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stdout: bytes,
    message: str,
) -> None:
    module = _load_script()
    observed: dict[str, Any] = {}

    def run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        observed["command"] = command
        observed["kwargs"] = kwargs
        return SimpleNamespace(
            returncode=returncode,
            stdout=stdout,
            stderr=b"sensitive stderr",
        )

    monkeypatch.setattr(module, "run_checked", run)

    with pytest.raises(module.ApprovalError, match=message) as captured:
        module.GitHub().get(f"repos/enkyuan/alloy/actions/runs/{RUN_ID}")

    assert "sensitive" not in str(captured.value)
    assert "Accept: application/vnd.github+json" in observed["command"]
    assert "X-GitHub-Api-Version: 2026-03-10" in observed["command"]
    assert observed["command"][2:4] == ["--hostname", "github.com"]
    assert observed["kwargs"]["input_bytes"] is None


def test_github_adapter_redacts_process_runner_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()

    def fail_run(*_args: Any, **_kwargs: Any) -> None:
        raise module.CommandError("sensitive runner diagnostic")

    monkeypatch.setattr(module, "run_checked", fail_run)

    with pytest.raises(
        module.ApprovalError,
        match="GitHub command could not be completed",
    ) as captured:
        module.GitHub().get(f"repos/enkyuan/alloy/actions/runs/{RUN_ID}")

    assert "sensitive runner diagnostic" not in str(captured.value)


@pytest.mark.parametrize(
    "stdout",
    [
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":1e999}',
        b'{"value":-1e999}',
        b'{"value":1,"value":2}',
    ],
)
def test_github_adapter_rejects_nonfinite_and_duplicate_json(
    monkeypatch: pytest.MonkeyPatch,
    stdout: bytes,
) -> None:
    module = _load_script()
    monkeypatch.setattr(
        module,
        "run_checked",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=stdout,
            stderr=b"",
        ),
    )

    with pytest.raises(module.ApprovalError, match="malformed JSON"):
        module.GitHub().get(f"repos/enkyuan/alloy/actions/runs/{RUN_ID}")


@pytest.mark.parametrize("literal", [b"1e999", b"-1e999"])
def test_github_adapter_rejects_exponent_overflow_in_ignored_run_field(
    monkeypatch: pytest.MonkeyPatch,
    literal: bytes,
) -> None:
    module = _load_script()
    encoded_run = json.dumps(_run("rehearsal"), separators=(",", ":")).encode()
    stdout = encoded_run[:-1] + b',"ignored_metric":' + literal + b"}"
    monkeypatch.setattr(
        module,
        "run_checked",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=stdout,
            stderr=b"",
        ),
    )

    with pytest.raises(module.ApprovalError, match="malformed JSON"):
        module.GitHub().get(f"repos/enkyuan/alloy/actions/runs/{RUN_ID}")


def test_nonfinite_fake_remote_value_is_mapped_to_approval_error(
    tmp_path: Path,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path)
    responses = _remote_responses(args)
    responses[12][0]["wait_timer"] = float("nan")
    github = FakeGitHub(responses)

    with pytest.raises(module.ApprovalError, match="non-finite"):
        module.gate(args, github)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda responses: responses[0]["deployment_branch_policy"].update(
            bypass_actors=[]
        ),
        lambda responses: responses[0]["protection_rules"][0]["reviewers"][0][
            "reviewer"
        ].update(bypass_actor=False),
        lambda responses: responses[0]["protection_rules"][1].update(
            id=responses[0]["protection_rules"][0]["id"]
        ),
        lambda responses: responses[0]["protection_rules"][1].update(
            node_id=responses[0]["protection_rules"][0]["node_id"]
        ),
        lambda responses: responses[1]["branch_policies"][1].update(
            id=responses[1]["branch_policies"][0]["id"]
        ),
        lambda responses: responses[1]["branch_policies"][1].update(
            node_id=responses[1]["branch_policies"][0]["node_id"]
        ),
        lambda responses: responses[0]["protection_rules"][0].pop("node_id"),
        lambda responses: responses[1]["branch_policies"][0].pop("node_id"),
        lambda responses: responses[2].update(id=7001),
        lambda responses: responses[2].update(node_id=responses[0]["node_id"]),
        lambda responses: responses[2]["protection_rules"][0].update(
            id=responses[0]["protection_rules"][0]["id"]
        ),
        lambda responses: responses[2]["protection_rules"][0].update(
            node_id=responses[0]["protection_rules"][0]["node_id"]
        ),
        lambda responses: responses[3]["branch_policies"][0].update(
            id=responses[1]["branch_policies"][0]["id"]
        ),
        lambda responses: responses[3]["branch_policies"][0].update(
            node_id=responses[1]["branch_policies"][0]["node_id"]
        ),
        lambda responses: responses[0].update(unreviewed_security_mode=False),
    ],
)
def test_aliasing_or_nested_bypass_environment_shapes_reject(
    mutation: Any,
) -> None:
    module = _load_script()
    responses = _environment_responses()
    mutation(responses)
    github = FakeGitHub(responses)

    with pytest.raises(module.ApprovalError):
        module.audit_environments(github)


@pytest.mark.parametrize("job_id", [101, 0, True, 9_007_199_254_740_992])
def test_all_complete_job_ids_must_be_positive_safe_and_distinct(
    tmp_path: Path,
    job_id: Any,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path)
    responses = _remote_responses(args)
    responses[7]["jobs"].append(
        _job(
            "unrelated completed",
            mode=args.mode,
            job_id=job_id,
            status="completed",
            conclusion="success",
        )
    )
    responses[7]["total_count"] += 1
    github = FakeGitHub(responses)

    with pytest.raises(module.ApprovalError, match="job ID"):
        module.gate(args, github)


@pytest.mark.parametrize("artifact_id", [PRODUCER_ID, 0, True, 9_007_199_254_740_992])
def test_all_complete_artifact_ids_must_be_positive_safe_and_distinct(
    tmp_path: Path,
    artifact_id: Any,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path)
    responses = _remote_responses(args)
    responses[8]["artifacts"].append(
        _artifact(
            "unrelated-evidence",
            artifact_id,
            "sha256:" + "e" * 64,
            mode=args.mode,
        )
    )
    responses[8]["total_count"] += 1
    github = FakeGitHub(responses)

    with pytest.raises(module.ApprovalError, match="artifact ID"):
        module.gate(args, github)


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("run", "id", True),
        ("run", "run_attempt", True),
        ("job", "run_id", True),
        ("job", "run_attempt", True),
        ("artifact", "id", True),
        ("artifact-run", "id", True),
    ],
)
def test_boolean_remote_identities_never_alias_integer_one(
    tmp_path: Path,
    target: str,
    field: str,
    value: Any,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path)
    responses = _remote_responses(args)
    if target == "run":
        responses[6][field] = value
    elif target == "job":
        responses[7]["jobs"][0][field] = value
    elif target == "artifact":
        responses[8]["artifacts"][0][field] = value
    else:
        responses[8]["artifacts"][0]["workflow_run"][field] = value
    github = FakeGitHub(responses)

    with pytest.raises(module.ApprovalError):
        module.gate(args, github)


def test_keyboard_interrupt_after_post_issuance_is_ambiguous(
    tmp_path: Path,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path, approve=True)
    github = FakeGitHub(
        [
            *_remote_responses(args),
            *_remote_responses(args),
            KeyboardInterrupt(),
        ]
    )

    with pytest.raises(module.ApprovalOutcomeAmbiguous):
        module.gate(args, github)

    assert len([call for call in github.calls if call[0] == "POST"]) == 1


def test_github_post_uses_stdin_and_no_environment_archive_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    body = b'{"environment_ids":[7001]}'
    observed: dict[str, Any] = {}

    def run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        observed["command"] = command
        observed["kwargs"] = kwargs
        return SimpleNamespace(
            returncode=0,
            stdout=b"[]",
            stderr=b"",
        )

    monkeypatch.setattr(module, "run_checked", run)

    module.GitHub().post(
        f"repos/enkyuan/alloy/actions/runs/{RUN_ID}/pending_deployments",
        input_bytes=body,
    )

    assert "--method" in observed["command"]
    assert "POST" in observed["command"]
    assert observed["command"][-2:] == ["--input", "-"]
    assert observed["kwargs"]["input_bytes"] == body
    assert "env" not in observed["kwargs"]


def test_main_reports_only_closed_ambiguous_instruction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script()
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda _argv=None: SimpleNamespace(command="gate"),
    )
    monkeypatch.setattr(
        module,
        "gate",
        lambda _args: (_ for _ in ()).throw(module.ApprovalOutcomeAmbiguous()),
    )

    assert module.main([]) == 2
    assert capsys.readouterr().out == (
        "AMBIGUOUS: the onboarding approval request was issued; inspect the exact "
        "workflow run manually and do not retry this command automatically\n"
    )


@pytest.mark.parametrize(
    "output_error",
    [
        BrokenPipeError("sensitive stdout diagnostic"),
        RuntimeError("sensitive custom stream diagnostic"),
        KeyboardInterrupt(),
    ],
)
def test_main_returns_ambiguous_exit_when_post_success_output_is_broken(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    output_error: BaseException,
) -> None:
    module = _load_script()
    args = _raw_args(tmp_path, approve=True)
    args.command = "gate"
    github = FakeGitHub(
        [
            *_remote_responses(args),
            *_remote_responses(args),
            _approval("rehearsal"),
        ]
    )
    monkeypatch.setattr(module, "parse_args", lambda _argv=None: args)
    monkeypatch.setattr(module, "GitHub", lambda: github)

    def fail_output(*_args: Any, **_kwargs: Any) -> None:
        raise output_error

    monkeypatch.setattr("builtins.print", fail_output)

    assert module.main([]) == 2
    assert len([call for call in github.calls if call[0] == "POST"]) == 1


def test_source_uses_only_public_archive_apis_and_contains_no_secret_route() -> None:
    source = APPROVER.read_text()

    for required in (
        "load_authenticated_archive",
        "compose_document",
        "validate_document",
        "recompute_and_compare",
    ):
        assert f"onboarding.{required}" in source
    for forbidden in (
        "KAJI_TTHW_EVIDENCE_JSON",
        "gh secret",
        "/secrets",
        "set_secret",
        "secret_metadata",
        "NPM_TOKEN",
        "TrustedRunner",
        "LoadedNodeReceipt",
        "_authenticate_archive",
        "_zip_members",
        "release-manifest",
        "artifacts-dir",
        "node22-receipt",
        "node24-receipt",
    ):
        assert forbidden not in source
