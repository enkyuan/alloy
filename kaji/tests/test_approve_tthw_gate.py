from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "kaji" / "scripts"
APPROVER = SCRIPTS / "approve_tthw_gate.py"
RUN_ID = 123
COMMIT = "a" * 40
TAG = "kaji-v0.2.0-beta.6"
ENVIRONMENT_ID = 777
EVIDENCE_BYTES = b'{"opaque":"exact evidence bytes"}'


def _load_script() -> ModuleType:
    scripts = str(SCRIPTS)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("test_approve_tthw_gate", APPROVER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_tthw_support() -> ModuleType:
    path = Path(__file__).with_name("test_tthw_evidence.py")
    spec = importlib.util.spec_from_file_location("_approve_tthw_support", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeGitHub:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, tuple[str, ...], bytes | None]] = []

    def json(self, arguments: list[str], *, input_bytes: bytes | None = None) -> Any:
        self.calls.append(("json", tuple(arguments), input_bytes))
        assert self.responses, f"unexpected GitHub JSON call: {arguments}"
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)

    def set_secret(self, encoded: bytes) -> None:
        self.calls.append(("set_secret", (), encoded))


def _run() -> dict[str, Any]:
    return {
        "id": RUN_ID,
        "run_attempt": 1,
        "event": "push",
        "path": ".github/workflows/kaji.publish.yml",
        "head_sha": COMMIT,
        "head_branch": TAG,
        "created_at": "2026-07-26T12:00:00Z",
    }


def _jobs() -> dict[str, Any]:
    jobs = [
        {
            "id": 11,
            "run_id": RUN_ID,
            "name": "time-to-hello-world evidence",
            "head_sha": COMMIT,
            "head_branch": TAG,
            "status": "waiting",
            "conclusion": None,
            "run_attempt": 1,
        },
        {
            "id": 12,
            "name": "offline release",
            "status": "completed",
            "conclusion": "success",
            "run_attempt": 1,
        },
    ]
    return {"total_count": len(jobs), "jobs": jobs}


def _environment() -> dict[str, Any]:
    return {
        "id": ENVIRONMENT_ID,
        "name": "kaji-beta",
        "can_admins_bypass": True,
        "deployment_branch_policy": {
            "protected_branches": False,
            "custom_branch_policies": True,
        },
        "protection_rules": [
            {
                "id": 1,
                "type": "required_reviewers",
                "prevent_self_review": False,
                "reviewers": [
                    {
                        "type": "User",
                        "reviewer": {"id": 31, "login": "reviewer"},
                    }
                ],
            },
            {"id": 2, "type": "branch_policy"},
        ],
    }


def _branch_policies() -> dict[str, Any]:
    policies = [
        {"id": 21, "name": "kaji-v*-beta.*", "type": "tag"},
        {"id": 22, "name": "main", "type": "branch"},
    ]
    return {"total_count": len(policies), "branch_policies": policies}


def _pending() -> list[dict[str, Any]]:
    return [
        {
            "environment": {"id": ENVIRONMENT_ID, "name": "kaji-beta"},
            "current_user_can_approve": True,
            "wait_timer": 0,
            "reviewers": [],
        }
    ]


def _preflight() -> list[Any]:
    return [_run(), _jobs(), _environment(), _branch_policies(), _pending()]


def _secret(updated_at: str) -> dict[str, Any]:
    secret = {
        "name": "KAJI_TTHW_EVIDENCE_JSON",
        "created_at": "2026-07-26T11:00:00Z",
        "updated_at": updated_at,
    }
    return {"total_count": 1, "secrets": [secret]}


def _approval(
    *,
    sha: str = COMMIT,
    ref: str = TAG,
    environment: str = "kaji-beta",
) -> list[dict[str, Any]]:
    return [
        {
            "id": 901,
            "sha": sha,
            "ref": ref,
            "environment": environment,
        }
    ]


def _args(evidence: Path, *, approve: bool) -> SimpleNamespace:
    return SimpleNamespace(
        run_id=RUN_ID,
        evidence=evidence,
        release_manifest=Path("manifest.json"),
        artifacts_dir=Path("artifacts"),
        python_compatibility_receipt=Path("python.json"),
        node_compatibility_receipt=Path("node.json"),
        approve=approve,
    )


def _stub_local_validation(module: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        module,
        "validate_evidence",
        lambda _args, _encoded: module.Candidate(
            commit=COMMIT,
            typescript_version="0.2.0-beta.6",
            tag=TAG,
        ),
    )
    monkeypatch.setattr(
        module,
        "_utc_now",
        lambda: datetime(2026, 7, 26, 12, 0, 30, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize("unsafe", ["empty", "oversize", "symlink", "changed"])
def test_unsafe_evidence_never_calls_github(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe: str,
) -> None:
    module = _load_script()
    _stub_local_validation(module, monkeypatch)
    evidence = tmp_path / "evidence.json"
    if unsafe == "empty":
        evidence.write_bytes(b"")
    elif unsafe == "oversize":
        evidence.write_bytes(b"x" * (module.MAX_EVIDENCE_BYTES + 1))
    else:
        evidence.write_bytes(EVIDENCE_BYTES)
        if unsafe == "symlink":
            target = tmp_path / "target.json"
            evidence.replace(target)
            evidence.symlink_to(target)
        else:
            original_same_file = module._same_file
            comparisons = 0

            def unstable_on_final_comparison(before: Any, after: Any) -> bool:
                nonlocal comparisons
                comparisons += 1
                return comparisons < 3 and original_same_file(before, after)

            monkeypatch.setattr(module, "_same_file", unstable_on_final_comparison)
    github = FakeGitHub([])

    with pytest.raises(module.ApprovalError, match="empty, oversized"):
        module.approve(_args(evidence, approve=True), github)

    assert github.calls == []


@pytest.mark.parametrize("suffix", [b"\n", b"\r", b"\r\n", b"\n\r\r\n"])
def test_cli_transformable_evidence_never_calls_github(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: bytes,
) -> None:
    module = _load_script()
    _stub_local_validation(module, monkeypatch)
    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(EVIDENCE_BYTES + suffix)
    github = FakeGitHub([])

    with pytest.raises(module.ApprovalError, match="ends in CR or LF"):
        module.approve(_args(evidence, approve=True), github)

    assert github.calls == []


def test_local_validation_reuses_the_protected_tthw_contract(tmp_path: Path) -> None:
    module = _load_script()
    support = _load_tthw_support()
    document, manifest, artifacts = support._fixture(tmp_path)
    python, node = support._compatibility_receipts(document, artifacts)
    evidence = tmp_path / "evidence.json"
    python_path = tmp_path / "python.json"
    node_path = tmp_path / "node.json"
    encoded = json.dumps(document, separators=(",", ":")).encode()
    evidence.write_bytes(encoded)
    python_path.write_text(json.dumps(python))
    node_path.write_text(json.dumps(node))
    args = SimpleNamespace(
        run_id=RUN_ID,
        evidence=evidence,
        release_manifest=manifest,
        artifacts_dir=artifacts,
        python_compatibility_receipt=python_path,
        node_compatibility_receipt=node_path,
        approve=False,
    )

    candidate = module.validate_evidence(args, module.read_evidence(evidence))

    assert candidate == module.Candidate(
        commit=COMMIT,
        typescript_version="0.2.0-beta.6",
        tag=TAG,
    )


def test_github_adapter_sets_only_the_exact_environment_secret_via_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    observed: dict[str, Any] = {}

    def run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        observed["command"] = command
        observed["options"] = kwargs
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(module, "run_checked", run)

    module.GitHub().set_secret(EVIDENCE_BYTES)

    assert observed == {
        "command": [
            "gh",
            "secret",
            "set",
            "KAJI_TTHW_EVIDENCE_JSON",
            "--repo",
            "enkyuan/alloy",
            "--env",
            "kaji-beta",
        ],
        "options": {
            "cwd": Path.cwd(),
            "budget": module.METADATA_BUDGET,
            "capture": True,
            "check": False,
            "input_bytes": EVIDENCE_BYTES,
        },
    }


@pytest.mark.parametrize(
    ("returncode", "stdout", "message"),
    [
        (1, b"", "GitHub command failed"),
        (0, b"not-json", "GitHub returned malformed JSON"),
    ],
)
def test_github_adapter_fails_closed_without_exposing_output(
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stdout: bytes,
    message: str,
) -> None:
    module = _load_script()
    secret_output = b"token-that-must-not-appear"

    monkeypatch.setattr(
        module,
        "run_checked",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=returncode,
            stdout=stdout,
            stderr=secret_output,
        ),
    )

    with pytest.raises(module.ApprovalError, match=message) as captured:
        module.GitHub().json(["api", "repos/enkyuan/alloy/actions/runs/123"])

    assert secret_output.decode() not in str(captured.value)


def test_github_adapter_maps_runner_failure_without_exposing_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    secret = b"opaque-evidence-that-must-not-appear"

    def fail_run(*_args: Any, **_kwargs: Any) -> None:
        raise module.CommandError("runner detail that must not escape")

    monkeypatch.setattr(module, "run_checked", fail_run)

    with pytest.raises(
        module.ApprovalError, match="GitHub command could not be completed"
    ) as captured:
        module.GitHub().set_secret(secret)

    rendered = f"{captured.value!s} {captured.value!r}"
    assert secret.decode() not in rendered
    assert "runner detail" not in rendered


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", RUN_ID + 1),
        ("run_attempt", 2),
        ("head_branch", "kaji-v0.2.0-beta.4"),
    ],
)
def test_current_run_tag_and_attempt_mismatch_blocks_secret_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
) -> None:
    module = _load_script()
    _stub_local_validation(module, monkeypatch)
    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(EVIDENCE_BYTES)
    run = _run()
    run[field] = value
    github = FakeGitHub([run])

    with pytest.raises(module.ApprovalError, match="workflow run binding differs"):
        module.approve(_args(evidence, approve=True), github)

    assert all(call[0] != "set_secret" for call in github.calls)


@pytest.mark.parametrize("ambiguity", ["job", "other-waiting-job", "pending"])
def test_job_or_pending_ambiguity_blocks_secret_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ambiguity: str,
) -> None:
    module = _load_script()
    _stub_local_validation(module, monkeypatch)
    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(EVIDENCE_BYTES)
    jobs = _jobs()
    pending = _pending()
    if ambiguity == "job":
        jobs["jobs"].append(deepcopy(jobs["jobs"][0]))
        jobs["total_count"] += 1
    elif ambiguity == "other-waiting-job":
        other = deepcopy(jobs["jobs"][1])
        other.update(
            {
                "id": 13,
                "name": "provider proof",
                "status": "waiting",
                "conclusion": None,
            }
        )
        jobs["jobs"].append(other)
        jobs["total_count"] += 1
    else:
        pending.append(
            {
                "environment": {"id": 999, "name": "other"},
                "current_user_can_approve": True,
            }
        )
    github = FakeGitHub([_run(), jobs, _environment(), _branch_policies(), pending])

    with pytest.raises(module.ApprovalError):
        module.approve(_args(evidence, approve=True), github)

    assert all(call[0] != "set_secret" for call in github.calls)


@pytest.mark.parametrize(
    "drift",
    ["reviewers", "tag-policy", "environment-id", "custom-policies"],
)
def test_environment_protection_drift_blocks_secret_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    module = _load_script()
    _stub_local_validation(module, monkeypatch)
    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(EVIDENCE_BYTES)
    environment = _environment()
    policies = _branch_policies()
    pending = _pending()
    if drift == "reviewers":
        environment["protection_rules"][0]["reviewers"] = []
    elif drift == "tag-policy":
        policies["branch_policies"][0]["name"] = "kaji-v0.2.0-beta.5"
    elif drift == "environment-id":
        pending[0]["environment"]["id"] = ENVIRONMENT_ID + 1
    else:
        environment["deployment_branch_policy"]["custom_branch_policies"] = False
    github = FakeGitHub([_run(), _jobs(), environment, policies, pending])

    with pytest.raises(module.ApprovalError):
        module.approve(_args(evidence, approve=True), github)

    assert all(call[0] != "set_secret" for call in github.calls)


def test_dry_run_performs_full_preflight_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script()
    _stub_local_validation(module, monkeypatch)
    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(EVIDENCE_BYTES)
    github = FakeGitHub(_preflight())

    module.approve(_args(evidence, approve=False), github)

    assert not github.responses
    assert all(call[0] != "set_secret" for call in github.calls)
    assert "no state changed" in capsys.readouterr().out


def test_success_uses_exact_order_identical_secret_bytes_and_one_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    _stub_local_validation(module, monkeypatch)
    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(EVIDENCE_BYTES)
    responses = [
        *_preflight(),
        _secret("2026-07-26T11:30:00Z"),
        _secret("2026-07-26T12:01:00Z"),
        *_preflight(),
        _secret("2026-07-26T12:01:00Z"),
        _approval(),
    ]
    github = FakeGitHub(responses)

    module.approve(_args(evidence, approve=True), github)

    expected_preflight = [
        (
            "api",
            f"repos/enkyuan/alloy/actions/runs/{RUN_ID}",
        ),
        (
            "api",
            (f"repos/enkyuan/alloy/actions/runs/{RUN_ID}/attempts/1/jobs?per_page=100"),
        ),
        ("api", "repos/enkyuan/alloy/environments/kaji-beta"),
        (
            "api",
            (
                "repos/enkyuan/alloy/environments/kaji-beta/"
                "deployment-branch-policies?per_page=100"
            ),
        ),
        (
            "api",
            f"repos/enkyuan/alloy/actions/runs/{RUN_ID}/pending_deployments",
        ),
    ]
    secrets_command = (
        "api",
        "repos/enkyuan/alloy/environments/kaji-beta/secrets?per_page=100",
    )
    approval_command = (
        "api",
        "--method",
        "POST",
        f"repos/enkyuan/alloy/actions/runs/{RUN_ID}/pending_deployments",
        "--input",
        "-",
    )
    assert [(call[0], call[1]) for call in github.calls] == [
        *(("json", command) for command in expected_preflight),
        ("json", secrets_command),
        ("set_secret", ()),
        ("json", secrets_command),
        *(("json", command) for command in expected_preflight),
        ("json", secrets_command),
        ("json", approval_command),
    ]
    secret_call = next(call for call in github.calls if call[0] == "set_secret")
    assert secret_call[2] == EVIDENCE_BYTES
    approval_call = github.calls[-1]
    approval_body = approval_call[2]
    assert approval_body is not None
    assert json.loads(approval_body) == {
        "environment_ids": [ENVIRONMENT_ID],
        "state": "approved",
        "comment": "Approve exact-run TTHW evidence.",
    }
    assert not github.responses


def test_stale_post_set_secret_metadata_blocks_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    _stub_local_validation(module, monkeypatch)
    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(EVIDENCE_BYTES)
    github = FakeGitHub(
        [
            *_preflight(),
            _secret("2026-07-26T10:00:00Z"),
            _secret("2026-07-26T11:59:59Z"),
        ]
    )

    with pytest.raises(module.ApprovalError, match="predates"):
        module.approve(_args(evidence, approve=True), github)

    assert any(call[0] == "set_secret" for call in github.calls)
    assert not any(call[0] == "json" and "--method" in call[1] for call in github.calls)


def test_post_secret_remote_race_blocks_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    _stub_local_validation(module, monkeypatch)
    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(EVIDENCE_BYTES)
    raced_run = _run()
    raced_run["head_sha"] = "b" * 40
    github = FakeGitHub(
        [
            *_preflight(),
            _secret("2026-07-26T11:30:00Z"),
            _secret("2026-07-26T12:01:00Z"),
            raced_run,
        ]
    )

    with pytest.raises(module.ApprovalError, match="workflow run binding differs"):
        module.approve(_args(evidence, approve=True), github)

    assert any(call[0] == "set_secret" for call in github.calls)
    assert not any(call[0] == "json" and "--method" in call[1] for call in github.calls)


def test_post_secret_second_waiting_job_blocks_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    _stub_local_validation(module, monkeypatch)
    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(EVIDENCE_BYTES)
    raced_jobs = _jobs()
    other = deepcopy(raced_jobs["jobs"][1])
    other.update(
        {
            "id": 13,
            "name": "provider proof",
            "status": "waiting",
            "conclusion": None,
        }
    )
    raced_jobs["jobs"].append(other)
    raced_jobs["total_count"] += 1
    github = FakeGitHub(
        [
            *_preflight(),
            _secret("2026-07-26T11:30:00Z"),
            _secret("2026-07-26T12:01:00Z"),
            _run(),
            raced_jobs,
        ]
    )

    with pytest.raises(module.ApprovalError, match="sole waiting job"):
        module.approve(_args(evidence, approve=True), github)

    assert any(call[0] == "set_secret" for call in github.calls)
    assert not any(call[0] == "json" and "--method" in call[1] for call in github.calls)


def test_post_secret_environment_recreation_blocks_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    _stub_local_validation(module, monkeypatch)
    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(EVIDENCE_BYTES)
    changed_environment = _environment()
    changed_environment["id"] = ENVIRONMENT_ID + 1
    changed_pending = _pending()
    changed_pending[0]["environment"]["id"] = ENVIRONMENT_ID + 1
    github = FakeGitHub(
        [
            *_preflight(),
            _secret("2026-07-26T11:30:00Z"),
            _secret("2026-07-26T12:01:00Z"),
            _run(),
            _jobs(),
            changed_environment,
            _branch_policies(),
            changed_pending,
        ]
    )

    with pytest.raises(module.ApprovalError, match="approval state changed"):
        module.approve(_args(evidence, approve=True), github)

    assert any(call[0] == "set_secret" for call in github.calls)
    assert not any(call[0] == "json" and "--method" in call[1] for call in github.calls)


@pytest.mark.parametrize(
    "drift",
    ["job-id", "pending-metadata", "reviewer-identity", "tag-policy-identity"],
)
def test_valid_shape_security_identity_drift_blocks_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    module = _load_script()
    _stub_local_validation(module, monkeypatch)
    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(EVIDENCE_BYTES)
    jobs = _jobs()
    environment = _environment()
    policies = _branch_policies()
    pending = _pending()
    if drift == "job-id":
        jobs["jobs"][0]["id"] = 99
    elif drift == "pending-metadata":
        pending[0]["wait_timer"] = 30
    elif drift == "reviewer-identity":
        environment["protection_rules"][0]["reviewers"][0]["reviewer"]["login"] = (
            "other-reviewer"
        )
    else:
        policies["branch_policies"][0]["id"] = 99
    github = FakeGitHub(
        [
            *_preflight(),
            _secret("2026-07-26T11:30:00Z"),
            _secret("2026-07-26T12:01:00Z"),
            _run(),
            jobs,
            environment,
            policies,
            pending,
        ]
    )

    with pytest.raises(module.ApprovalError, match="approval state changed"):
        module.approve(_args(evidence, approve=True), github)

    assert any(call[0] == "set_secret" for call in github.calls)
    assert not any(call[0] == "json" and "--method" in call[1] for call in github.calls)


def test_secret_metadata_must_be_fresh_for_this_set_operation() -> None:
    module = _load_script()
    before = _secret("2026-07-26T12:00:28Z")["secrets"][0]
    after = _secret("2026-07-26T12:00:29Z")["secrets"][0]

    with pytest.raises(module.ApprovalError, match="this secret update operation"):
        module.assert_fresh_secret(
            before,
            after,
            run_created_at=datetime(
                2026,
                7,
                26,
                12,
                0,
                tzinfo=timezone.utc,
            ),
            set_started_at=datetime(
                2026,
                7,
                26,
                12,
                0,
                30,
                999_999,
                tzinfo=timezone.utc,
            ),
        )


def test_secret_freshness_allows_api_second_precision() -> None:
    module = _load_script()
    before = _secret("2026-07-26T12:00:29Z")["secrets"][0]
    after = _secret("2026-07-26T12:00:30Z")["secrets"][0]

    module.assert_fresh_secret(
        before,
        after,
        run_created_at=datetime(
            2026,
            7,
            26,
            12,
            0,
            tzinfo=timezone.utc,
        ),
        set_started_at=datetime(
            2026,
            7,
            26,
            12,
            0,
            30,
            999_999,
            tzinfo=timezone.utc,
        ),
    )


def test_unchanged_secret_timestamp_blocks_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    _stub_local_validation(module, monkeypatch)
    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(EVIDENCE_BYTES)
    github = FakeGitHub(
        [
            *_preflight(),
            _secret("2026-07-26T12:01:00Z"),
            _secret("2026-07-26T12:01:00Z"),
        ]
    )

    with pytest.raises(module.ApprovalError, match="timestamp did not change"):
        module.approve(_args(evidence, approve=True), github)

    assert not any(call[0] == "json" and "--method" in call[1] for call in github.calls)


def test_concurrent_secret_overwrite_blocks_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    _stub_local_validation(module, monkeypatch)
    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(EVIDENCE_BYTES)
    github = FakeGitHub(
        [
            *_preflight(),
            _secret("2026-07-26T11:30:00Z"),
            _secret("2026-07-26T12:01:00Z"),
            *_preflight(),
            _secret("2026-07-26T12:02:00Z"),
        ]
    )

    with pytest.raises(
        module.ApprovalError, match="changed before deployment approval"
    ):
        module.approve(_args(evidence, approve=True), github)

    assert not any(call[0] == "json" and "--method" in call[1] for call in github.calls)


def test_any_post_set_secret_metadata_drift_blocks_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    _stub_local_validation(module, monkeypatch)
    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(EVIDENCE_BYTES)
    changed_metadata = _secret("2026-07-26T12:01:00Z")
    changed_metadata["secrets"][0]["created_at"] = "2026-07-26T11:00:01Z"
    github = FakeGitHub(
        [
            *_preflight(),
            _secret("2026-07-26T11:30:00Z"),
            _secret("2026-07-26T12:01:00Z"),
            *_preflight(),
            changed_metadata,
        ]
    )

    with pytest.raises(
        module.ApprovalError, match="changed before deployment approval"
    ):
        module.approve(_args(evidence, approve=True), github)

    assert not any(call[0] == "json" and "--method" in call[1] for call in github.calls)


@pytest.mark.parametrize(
    "response",
    [
        [],
        [*_approval(), *_approval()],
        _approval(sha="b" * 40),
        _approval(ref="kaji-v0.2.0-beta.4"),
        _approval(environment="other"),
    ],
)
def test_approval_response_must_bind_one_exact_deployment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response: list[dict[str, Any]],
) -> None:
    module = _load_script()
    _stub_local_validation(module, monkeypatch)
    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(EVIDENCE_BYTES)
    github = FakeGitHub(
        [
            *_preflight(),
            _secret("2026-07-26T11:30:00Z"),
            _secret("2026-07-26T12:01:00Z"),
            *_preflight(),
            _secret("2026-07-26T12:01:00Z"),
            response,
        ]
    )

    with pytest.raises(module.ApprovalError, match="deployment"):
        module.approve(_args(evidence, approve=True), github)

    approval_calls = [
        call for call in github.calls if call[0] == "json" and "--method" in call[1]
    ]
    assert len(approval_calls) == 1
