"""Contract tests for the trusted TypeScript handoff source verifier."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from types import ModuleType
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
VERIFIER = REPO_ROOT / "kaji" / "scripts" / "verify_ts_handoff_source.py"
SCRIPTS = VERIFIER.parent
BASE_REF = "refs/remotes/origin/main"
REPOSITORY = "enkyuan/alloy"
REPOSITORY_URL = "https://github.com/enkyuan/alloy.git"
SIGNER = "release.signer@example.com"
TOKEN = "ghp_source_verifier_secret"
HEX40 = "a" * 40


def _git(
    root: Path, *arguments: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull},
    )


def _git_output(root: Path, *arguments: str) -> str:
    return _git(root, *arguments).stdout.strip()


def _commit(root: Path, message: str, content: str) -> str:
    (root / "tracked.txt").write_text(content)
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-q", "-m", message)
    return _git_output(root, "rev-parse", "HEAD")


def _commit_file(root: Path, name: str, message: str, content: str) -> str:
    (root / name).write_text(content)
    _git(root, "add", name)
    _git(root, "commit", "-q", "-m", message)
    return _git_output(root, "rev-parse", "HEAD")


def _repository(root: Path) -> str:
    root.mkdir(parents=True)
    _git(root, "init", "-q", "--initial-branch=main")
    _git(root, "config", "user.name", "Release Signer")
    _git(root, "config", "user.email", SIGNER)
    _git(root, "config", "commit.gpgsign", "false")
    (root / ".gitignore").write_text("__pycache__/\n")
    (root / "tracked.txt").write_text("base\n")
    _git(root, "add", ".gitignore", "tracked.txt")
    _git(root, "commit", "-q", "-m", "base")
    head = _git_output(root, "rev-parse", "HEAD")
    _git(root, "update-ref", BASE_REF, head)
    return head


def _load_verifier(path: Path = VERIFIER) -> ModuleType:
    scripts = str(SCRIPTS)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    name = f"test_ts_handoff_source_{hash(path)}_{len(sys.modules)}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _payload(email: str = SIGNER) -> str:
    return (
        f"tree {'1' * 40}\n"
        f"author Release Signer <{email}> 1 +0000\n"
        f"committer Release Signer <{email}> 1 +0000\n"
        "\nsource checkpoint\n"
    )


def _commit_document(
    sha: str,
    *,
    response_email: str = SIGNER,
    payload: str | None = None,
    verified: bool = True,
    reason: str = "valid",
) -> dict[str, Any]:
    return {
        "sha": sha,
        "committer": {"email": response_email},
        "verification": {
            "verified": verified,
            "reason": reason,
            "payload": _payload(response_email) if payload is None else payload,
        },
    }


class RestStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.commits: dict[str, dict[str, Any]] = {}
        self.tag_ref: dict[str, Any] | None = None
        self.tag_object: dict[str, Any] | None = None
        self.error: BaseException | None = None
        self.before_response: Any = None

    def __call__(self, path: str, token: str) -> dict[str, Any]:
        self.calls.append((path, token))
        if self.before_response is not None:
            callback, self.before_response = self.before_response, None
            callback()
        if self.error is not None:
            raise self.error
        commit_prefix = f"/repos/{REPOSITORY}/git/commits/"
        if path.startswith(commit_prefix):
            sha = path.removeprefix(commit_prefix)
            return self.commits.get(sha, _commit_document(sha))
        if path.startswith(f"/repos/{REPOSITORY}/git/ref/tags/"):
            assert self.tag_ref is not None
            return self.tag_ref
        if path.startswith(f"/repos/{REPOSITORY}/git/tags/"):
            assert self.tag_object is not None
            return self.tag_object
        raise AssertionError(f"unexpected REST path: {path}")


@dataclass(slots=True)
class Case:
    verifier: ModuleType
    trusted: Path
    candidate: Path
    output: Path
    rest: RestStub


def _case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Case:
    trusted = tmp_path / "trusted"
    candidate = tmp_path / "candidate"
    _repository(trusted)
    _repository(candidate)

    trusted_script = trusted / "kaji" / "scripts" / VERIFIER.name
    trusted_script.parent.mkdir(parents=True)
    shutil.copyfile(VERIFIER, trusted_script)
    _git(trusted, "add", trusted_script.relative_to(trusted).as_posix())
    _git(trusted, "commit", "-q", "-m", "trusted verifier")
    trusted_head = _git_output(trusted, "rev-parse", "HEAD")
    _git(trusted, "update-ref", BASE_REF, trusted_head)

    monkeypatch.setenv("KAJI_RELEASE_SIGNER_EMAIL", SIGNER)
    monkeypatch.setenv("GH_TOKEN", TOKEN)
    output_parent = tmp_path / "outputs"
    output_parent.mkdir()
    return Case(
        verifier=_load_verifier(trusted_script),
        trusted=trusted,
        candidate=candidate,
        output=output_parent / "source",
        rest=RestStub(),
    )


def _invoke(
    case: Case,
    *,
    mode: str = "commit",
    tag_name: str | None = None,
    rest: RestStub | None = None,
) -> None:
    case.verifier.verify_source(
        candidate_root=case.candidate,
        base_ref=BASE_REF,
        mode=mode,
        tag_name=tag_name,
        output_dir=case.output,
        rest_get=case.rest if rest is None else rest,
    )


def _failure(case: Case, code: str, **options: Any) -> None:
    with pytest.raises(case.verifier.VerificationError) as captured:
        _invoke(case, **options)
    assert captured.value.code == code
    assert captured.value.__cause__ is None


def _read_outputs(case: Case) -> tuple[dict[str, Any], dict[str, Any]]:
    source = json.loads((case.output / "source-equivalence.raw.json").read_bytes())
    signature_document = json.loads(
        (case.output / "signature-verification.raw.json").read_bytes()
    )
    assert isinstance(source, dict)
    assert isinstance(signature_document, dict)
    return source, signature_document


def _assert_canonical(path: Path, document: dict[str, Any]) -> None:
    expected = (
        json.dumps(document, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()
    assert path.read_bytes() == expected


def _configure_tag(
    case: Case,
    name: str,
    *,
    object_type: str = "tag",
    tag_name: str | None = None,
    tag_verified: bool = True,
    tag_reason: str = "valid",
    tagger_email: str = SIGNER,
    target_type: str = "commit",
    target_sha: str | None = None,
) -> str:
    object_sha = "b" * 40
    head = _git_output(case.candidate, "rev-parse", "HEAD")
    case.rest.tag_ref = {
        "ref": f"refs/tags/{name}",
        "object": {"type": object_type, "sha": object_sha},
    }
    case.rest.tag_object = {
        "sha": object_sha,
        "tag": name if tag_name is None else tag_name,
        "tagger": {"email": tagger_email},
        "object": {
            "type": target_type,
            "sha": head if target_sha is None else target_sha,
        },
        "verification": {"verified": tag_verified, "reason": tag_reason},
    }
    return object_sha


def test_verifier_entrypoint_freezes_identity_and_uses_bounded_process_runner() -> None:
    verifier = _load_verifier()
    source = VERIFIER.read_text()

    assert verifier.REPOSITORY == REPOSITORY
    assert verifier.REPOSITORY_URL == REPOSITORY_URL
    assert verifier.BASE_REF == BASE_REF
    assert "from process_runner import" in source
    assert "run_checked" in source
    assert "subprocess." not in source


def test_git_children_receive_no_rest_token_or_ambient_git_redirection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _load_verifier()
    monkeypatch.setenv("GH_TOKEN", TOKEN)
    monkeypatch.setenv("GIT_DIR", "/attacker/repository")
    monkeypatch.setenv("GIT_INDEX_FILE", "/attacker/index")
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'alias.status=!env'")

    environment = verifier._git_environment()

    assert TOKEN not in environment.values()
    assert "GH_TOKEN" not in environment
    assert "GIT_DIR" not in environment
    assert "GIT_INDEX_FILE" not in environment
    assert "GIT_CONFIG_PARAMETERS" not in environment
    assert environment["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert environment["GIT_OPTIONAL_LOCKS"] == "0"


def test_empty_range_verifies_singleton_head_and_writes_exact_closed_raw_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    head = _git_output(case.candidate, "rev-parse", "HEAD")
    tree = _git_output(case.candidate, "rev-parse", "HEAD^{tree}")
    trusted_head = _git_output(case.trusted, "rev-parse", "HEAD")

    _invoke(case)

    source, signature_document = _read_outputs(case)
    assert set(source) == {
        "repository",
        "headCommit",
        "treeSha",
        "mergeBase",
        "revisionCommand",
        "range",
        "checkout",
        "clean",
        "trustedVerifierCommit",
    }
    assert source == {
        "repository": REPOSITORY_URL,
        "headCommit": head,
        "treeSha": tree,
        "mergeBase": head,
        "revisionCommand": [
            "git",
            "rev-list",
            "--reverse",
            "--topo-order",
            f"{head}..{head}",
        ],
        "range": [],
        "checkout": "separate-fetch-depth-0",
        "clean": True,
        "trustedVerifierCommit": trusted_head,
    }
    assert set(signature_document) == {
        "identityField",
        "approvedSignerEmail",
        "verifierSource",
        "headCommit",
        "treeSha",
        "verifierCommit",
        "verifierScriptSha256",
        "mergeBase",
        "range",
        "commits",
        "mechanism",
    }
    assert signature_document["range"] == []
    assert [item["sha"] for item in signature_document["commits"]] == [head]
    assert signature_document["commits"][0] == {
        "sha": head,
        "verified": True,
        "reason": "valid",
        "signerEmail": SIGNER,
        "payloadSha256": hashlib.sha256(_payload().encode()).hexdigest(),
    }
    assert signature_document["verifierCommit"] == trusted_head
    assert (
        signature_document["verifierScriptSha256"]
        == hashlib.sha256(
            (case.trusted / "kaji" / "scripts" / VERIFIER.name).read_bytes()
        ).hexdigest()
    )
    assert signature_document["mechanism"] == "github-rest-commit-verification"
    assert "rawResultSha256" not in source
    assert "rawResultSha256" not in signature_document
    assert case.rest.calls == [(f"/repos/{REPOSITORY}/git/commits/{head}", TOKEN)]
    _assert_canonical(case.output / "source-equivalence.raw.json", source)
    _assert_canonical(
        case.output / "signature-verification.raw.json", signature_document
    )


def test_nonempty_range_is_exact_reverse_topological_order_with_merge_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    base = _git_output(case.candidate, "rev-parse", "HEAD")
    _git(case.candidate, "switch", "-q", "-c", "side")
    side = _commit_file(case.candidate, "side.txt", "side", "side\n")
    _git(case.candidate, "switch", "-q", "main")
    main = _commit_file(case.candidate, "main.txt", "main", "main\n")
    _git(case.candidate, "merge", "-q", "--no-ff", "side", "-m", "merge")
    head = _git_output(case.candidate, "rev-parse", "HEAD")
    expected = _git_output(
        case.candidate,
        "rev-list",
        "--reverse",
        "--topo-order",
        f"{base}..{head}",
    ).splitlines()

    _invoke(case)

    source, signature_document = _read_outputs(case)
    assert source["range"] == expected
    assert signature_document["range"] == expected
    assert head == expected[-1]
    assert expected.count(head) == 1
    assert {side, main, head}.issubset(expected)
    assert [item["sha"] for item in signature_document["commits"]] == expected
    assert [path.rsplit("/", 1)[-1] for path, _token in case.rest.calls] == expected


@pytest.mark.parametrize("state", ["tracked", "staged", "untracked"])
def test_candidate_must_have_no_tracked_staged_or_untracked_change(
    state: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    if state == "untracked":
        (case.candidate / "unexpected.txt").write_text("secret\n")
    else:
        (case.candidate / "tracked.txt").write_text("changed\n")
        if state == "staged":
            _git(case.candidate, "add", "tracked.txt")

    _failure(case, "SOURCE_DIRTY")
    assert case.rest.calls == []
    assert not case.output.exists()


def test_trusted_checkout_must_be_clean_and_on_fetched_default_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirty = _case(tmp_path / "dirty", monkeypatch)
    (dirty.trusted / "tracked.txt").write_text("dirty\n")
    _failure(dirty, "SOURCE_DIRTY")

    unreachable = _case(tmp_path / "unreachable", monkeypatch)
    _commit(unreachable.trusted, "not on default", "different\n")
    _failure(unreachable, "TRUSTED_VERIFIER_NOT_ON_DEFAULT")


@pytest.mark.parametrize("which", ["candidate", "trusted"])
def test_both_checkouts_must_be_full_history(
    which: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    root = case.candidate if which == "candidate" else case.trusted
    (root / ".git" / "shallow").write_text(
        _git_output(root, "rev-parse", "HEAD") + "\n"
    )

    _failure(case, "SOURCE_NOT_ISOLATED")


def test_candidate_cannot_be_the_trusted_root_or_a_non_root_subdirectory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    same = _case(tmp_path / "same", monkeypatch)
    same.candidate = same.trusted
    _failure(same, "SOURCE_NOT_ISOLATED")

    nested = _case(tmp_path / "nested", monkeypatch)
    child = nested.candidate / "child"
    child.mkdir()
    nested.candidate = child
    _failure(nested, "SOURCE_NOT_ISOLATED")


def test_candidate_local_verifier_copy_cannot_substitute_for_trusted_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    candidate_script = case.candidate / "kaji" / "scripts" / VERIFIER.name
    candidate_script.parent.mkdir(parents=True)
    shutil.copyfile(VERIFIER, candidate_script)
    case.verifier = _load_verifier(candidate_script)

    _failure(case, "SOURCE_NOT_ISOLATED")


def test_empty_range_requires_head_to_be_ancestor_of_fetched_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    original = case.verifier._is_ancestor

    def ancestor(root: Path, first: str, second: str) -> bool:
        if root == case.candidate.resolve():
            return False
        return original(root, first, second)

    monkeypatch.setattr(case.verifier, "_is_ancestor", ancestor)

    _failure(case, "SIGNATURE_RANGE_EMPTY")
    assert case.rest.calls == []


@pytest.mark.parametrize(
    ("document", "code"),
    [
        (_commit_document("f" * 40), "SIGNATURE_INVALID"),
        (_commit_document(HEX40, verified=False), "SIGNATURE_INVALID"),
        (_commit_document(HEX40, reason="expired_key"), "SIGNATURE_INVALID"),
        (
            _commit_document(
                HEX40,
                response_email="attacker@example.com",
                payload=_payload("attacker@example.com"),
            ),
            "SIGNER_NOT_APPROVED",
        ),
        (
            _commit_document(HEX40, payload=_payload("attacker@example.com")),
            "SIGNATURE_INVALID",
        ),
        (
            _commit_document(HEX40, payload="tree " + "1" * 40 + "\n\nmessage"),
            "SIGNATURE_INVALID",
        ),
        (
            _commit_document(
                HEX40,
                payload=_payload().replace(
                    "\n\n",
                    "\ncommitter Duplicate <release.signer@example.com> 2 +0000\n\n",
                    1,
                ),
            ),
            "SIGNATURE_INVALID",
        ),
    ],
    ids=[
        "response-sha",
        "unverified",
        "reason",
        "unapproved-response-and-payload",
        "payload-email-mismatch",
        "missing-payload-committer",
        "duplicate-payload-committer",
    ],
)
def test_commit_rest_response_and_signed_payload_fail_closed(
    document: dict[str, Any],
    code: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case(tmp_path, monkeypatch)
    head = _git_output(case.candidate, "rev-parse", "HEAD")
    replacement = json.loads(json.dumps(document))
    if replacement.get("sha") == HEX40:
        replacement["sha"] = head
    case.rest.commits[head] = replacement

    _failure(case, code)
    assert not case.output.exists()


@pytest.mark.parametrize("variable", ["KAJI_RELEASE_SIGNER_EMAIL", "GH_TOKEN"])
def test_signer_and_token_exist_only_in_protected_environment(
    variable: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    monkeypatch.delenv(variable)
    expected = (
        "SIGNER_NOT_APPROVED" if variable.startswith("KAJI") else "SIGNATURE_INVALID"
    )

    _failure(case, expected)
    assert case.rest.calls == []


def test_signed_tag_verifies_annotated_object_and_direct_head_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    tag_name = "kaji-release_1.alpha"
    object_sha = _configure_tag(case, tag_name)
    head = _git_output(case.candidate, "rev-parse", "HEAD")

    _invoke(case, mode="signed-tag", tag_name=tag_name)

    _source, signature_document = _read_outputs(case)
    assert signature_document["mechanism"] == (
        "github-rest-commit-and-annotated-tag-verification"
    )
    assert signature_document["tag"] == {
        "name": tag_name,
        "objectSha": object_sha,
        "targetCommit": head,
        "taggerEmail": SIGNER,
        "verified": True,
        "reason": "valid",
    }
    assert [path for path, _token in case.rest.calls] == [
        f"/repos/{REPOSITORY}/git/commits/{head}",
        f"/repos/{REPOSITORY}/git/ref/tags/{tag_name}",
        f"/repos/{REPOSITORY}/git/tags/{object_sha}",
    ]


@pytest.mark.parametrize(
    ("options", "code"),
    [
        ({"object_type": "commit"}, "TAG_INVALID"),
        ({"tag_name": "kaji-other"}, "TAG_INVALID"),
        ({"tag_verified": False}, "TAG_INVALID"),
        ({"tag_reason": "unsigned"}, "TAG_INVALID"),
        ({"tagger_email": "attacker@example.com"}, "SIGNER_NOT_APPROVED"),
        ({"target_type": "tag"}, "TAG_INVALID"),
        ({"target_type": "tree"}, "TAG_INVALID"),
        ({"target_sha": "c" * 40}, "TAG_INVALID"),
    ],
    ids=[
        "lightweight",
        "wrong-name",
        "unverified",
        "wrong-reason",
        "wrong-tagger",
        "tag-chain",
        "tree-target",
        "wrong-head",
    ],
)
def test_signed_tag_rejects_every_indirect_or_untrusted_shape(
    options: dict[str, Any],
    code: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case(tmp_path, monkeypatch)
    tag_name = "kaji-release_1.alpha"
    _configure_tag(case, tag_name, **options)

    _failure(case, code, mode="signed-tag", tag_name=tag_name)
    assert not case.output.exists()


def test_output_collision_fails_before_git_or_rest_and_never_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    case.output.mkdir()
    marker = case.output / "owned-by-caller"
    marker.write_text("preserve\n")

    _failure(case, "OUTPUT_EXISTS")

    assert marker.read_text() == "preserve\n"
    assert case.rest.calls == []


def test_source_mutation_during_rest_verification_prevents_raw_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    case.rest.before_response = lambda: (case.candidate / "tracked.txt").write_text(
        "mutated\n"
    )

    _failure(case, "SOURCE_DIRTY")

    assert not case.output.exists()


def test_signal_during_atomic_write_cleans_only_owned_temp_and_is_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, monkeypatch)
    original_write = case.verifier._write_json
    old_term = signal.getsignal(signal.SIGTERM)

    def interrupt_after_first(path: Path, document: dict[str, Any]) -> None:
        original_write(path, document)
        if path.name == "source-equivalence.raw.json":
            os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(case.verifier, "_write_json", interrupt_after_first)
    with pytest.raises(case.verifier.VerifierInterrupted):
        _invoke(case)

    assert signal.getsignal(signal.SIGTERM) == old_term
    assert not case.output.exists()
    assert list(case.output.parent.iterdir()) == []

    monkeypatch.setattr(case.verifier, "_write_json", original_write)
    case.rest.calls.clear()
    _invoke(case)
    assert sorted(path.name for path in case.output.iterdir()) == [
        "signature-verification.raw.json",
        "source-equivalence.raw.json",
    ]


def test_production_rest_client_freezes_origin_headers_timeout_and_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _load_verifier()
    path = f"/repos/{REPOSITORY}/git/commits/{HEX40}"
    encoded = json.dumps({"sha": HEX40}).encode()
    observed: dict[str, Any] = {}

    class Response:
        status = 200

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_arguments: object) -> None:
            return None

        def geturl(self) -> str:
            return f"{verifier.API_ROOT}{path}"

        def read(self, amount: int) -> bytes:
            observed["amount"] = amount
            return encoded

    def open_github(github_request: Any, *, timeout: float) -> Response:
        observed["url"] = github_request.full_url
        observed["headers"] = {
            key.lower(): value for key, value in github_request.header_items()
        }
        observed["timeout"] = timeout
        return Response()

    monkeypatch.setattr(verifier, "_open_github", open_github)

    assert verifier._github_rest_get(path, TOKEN) == {"sha": HEX40}
    assert 0 < observed.pop("timeout") <= 30.0
    assert observed == {
        "url": f"https://api.github.com{path}",
        "headers": {
            "accept": "application/vnd.github+json",
            "authorization": f"Bearer {TOKEN}",
            "user-agent": "kaji-ts-handoff-source-verifier/1",
            "x-github-api-version": "2026-03-10",
        },
        "amount": verifier.MAX_REST_BYTES + 1,
    }


def test_rest_absolute_deadline_stops_fast_trickle_and_restores_alarm_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _load_verifier()
    path = f"/repos/{REPOSITORY}/git/commits/{HEX40}"
    original_handler = signal.getsignal(signal.SIGALRM)
    original_timer = signal.getitimer(signal.ITIMER_REAL)
    original_started = time.monotonic()
    prior_calls: list[int] = []
    response_state = {"closed": False, "ticks": 0}

    class Response:
        status = 200

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_arguments: object) -> None:
            response_state["closed"] = True

        def geturl(self) -> str:
            return f"{verifier.API_ROOT}{path}"

        def read(self, _amount: int) -> bytes:
            for _index in range(50):
                response_state["ticks"] += 1
                time.sleep(0.01)
            return b"{}"

    def prior_alarm(signum: int, _frame: object) -> None:
        prior_calls.append(signum)

    monkeypatch.setattr(verifier, "REST_DEADLINE_SECONDS", 0.05)
    monkeypatch.setattr(
        verifier, "_open_github", lambda *_arguments, **_options: Response()
    )
    signal.signal(signal.SIGALRM, prior_alarm)
    signal.setitimer(signal.ITIMER_REAL, 5.0)
    started = time.monotonic()
    try:
        with pytest.raises(verifier.VerificationError) as captured:
            verifier._verify_commit(
                HEX40,
                signer=SIGNER,
                token=TOKEN,
                rest_get=verifier._github_rest_get,
            )
        elapsed = time.monotonic() - started
        restored_delay, restored_interval = signal.getitimer(signal.ITIMER_REAL)

        assert captured.value.code == "SIGNATURE_INVALID"
        assert captured.value.__cause__ is None
        assert 0.03 <= elapsed < 0.25
        assert response_state["closed"] is True
        assert 2 <= response_state["ticks"] < 25
        assert signal.getsignal(signal.SIGALRM) is prior_alarm
        assert 4.5 < restored_delay <= 5.0
        assert restored_interval == 0.0
        assert prior_calls == []
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, original_handler)
        original_delay, original_interval = original_timer
        if original_delay > 0:
            elapsed = time.monotonic() - original_started
            signal.setitimer(
                signal.ITIMER_REAL,
                max(original_delay - elapsed, 1e-6),
                original_interval,
            )


@pytest.mark.parametrize("kind", ["redirect", "oversize", "non-object"])
def test_production_rest_client_rejects_redirect_oversize_and_open_shape(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    verifier = _load_verifier()
    path = f"/repos/{REPOSITORY}/git/commits/{HEX40}"

    class Response:
        status = 200

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_arguments: object) -> None:
            return None

        def geturl(self) -> str:
            return (
                "https://example.com/redirect"
                if kind == "redirect"
                else f"{verifier.API_ROOT}{path}"
            )

        def read(self, _amount: int) -> bytes:
            if kind == "oversize":
                return b"x" * (verifier.MAX_REST_BYTES + 1)
            return b"[]"

    monkeypatch.setattr(
        verifier, "_open_github", lambda *_arguments, **_options: Response()
    )

    with pytest.raises(RuntimeError):
        verifier._github_rest_get(path, TOKEN)


def test_cli_is_frozen_and_has_no_trust_or_verification_bypass() -> None:
    completed = subprocess.run(
        [sys.executable, str(VERIFIER), "--help"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert completed.returncode == 0
    assert {
        "--candidate-root",
        "--base-ref",
        "--mode",
        "--tag-name",
        "--output-dir",
    }.issubset(completed.stdout.split())
    for forbidden in (
        "--repository",
        "--signer-email",
        "--trusted-root",
        "--head",
        "--verifier-commit",
        "--skip-signature",
        "--fake-rest",
    ):
        assert forbidden not in completed.stdout


@pytest.mark.parametrize(
    "arguments",
    [
        ["--base-ref", "refs/remotes/origin/other"],
        ["--mode", "commit", "--tag-name", "kaji-a"],
        ["--mode", "signed-tag"],
        ["--mode", "signed-tag", "--tag-name", "release-1"],
        ["--repository", REPOSITORY],
    ],
)
def test_cli_rejects_base_override_mode_mismatch_and_unknown_options(
    arguments: list[str],
) -> None:
    command = [
        sys.executable,
        str(VERIFIER),
        "--candidate-root",
        "candidate",
        "--base-ref",
        BASE_REF,
        "--mode",
        "commit",
        "--output-dir",
        "output",
        *arguments,
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert completed.returncode == 2


def test_operational_failure_is_one_closed_redacted_json_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = _case(tmp_path, monkeypatch)
    case.rest.error = RuntimeError(f"Authorization: Bearer {TOKEN}")
    arguments = [
        "--candidate-root",
        str(case.candidate),
        "--base-ref",
        BASE_REF,
        "--mode",
        "commit",
        "--output-dir",
        str(case.output),
    ]

    status = case.verifier._run(arguments, rest_get=case.rest)

    captured = capsys.readouterr()
    assert status == 1
    assert captured.out == ""
    assert TOKEN not in captured.err
    assert "Authorization" not in captured.err
    failure = json.loads(captured.err)
    assert set(failure) == {
        "schemaVersion",
        "command",
        "result",
        "failureCode",
        "sourceCommit",
        "artifactSha256",
    }
    assert failure == {
        "schemaVersion": 1,
        "command": "source-verify",
        "result": "failed",
        "failureCode": "SIGNATURE_INVALID",
        "sourceCommit": _git_output(case.candidate, "rev-parse", "HEAD"),
        "artifactSha256": None,
    }
    assert not case.output.exists()
