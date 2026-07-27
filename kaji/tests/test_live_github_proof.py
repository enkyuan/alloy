from __future__ import annotations

import asyncio
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import textwrap
from types import SimpleNamespace
from typing import Any

import httpx
from jsonschema import Draft202012Validator
import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "kaji" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import github_proof_control as proof_control  # noqa: E402  # ty: ignore[unresolved-import]
from github_proof_control import (  # noqa: E402  # ty: ignore[unresolved-import]
    GitHubProofControl,
    GitHubProofError,
    new_proof_state,
    private_state_lock,
    read_private_json,
    update_proof_cell,
    write_private_json,
)
from live_github_proof import (  # noqa: E402  # ty: ignore[unresolved-import]
    ProofPrerequisites,
    run_proof,
    validate_child_receipt,
    validate_prerequisites,
)
from verify_release_artifacts import (  # noqa: E402  # ty: ignore[unresolved-import]
    VerifiedReleaseArtifacts,
)


COMMIT = "a" * 40
MANIFEST = "b" * 64
ARTIFACT = "c" * 64
PROOF = "d" * 64
ISSUE_URL = "https://api.github.com/repos/octo/widgets/issues/7"


def _public_receipt() -> dict[str, Any]:
    return {
        "schemaVersion": "1.0.0",
        "commit": COMMIT,
        "releaseManifestSha256": MANIFEST,
        "cells": [
            {
                "runtime": "python",
                "artifactSha256": ARTIFACT,
                "packageProofSha256": PROOF,
                "conclusion": "passed",
            },
            {
                "runtime": "typescript",
                "artifactSha256": ARTIFACT,
                "packageProofSha256": PROOF,
                "conclusion": "passed",
            },
        ],
        "approvalRejectedBeforeTransport": True,
        "readPassed": True,
        "approvedCommentPassed": True,
        "controlReadbackPassed": True,
        "ambiguousMutationRetried": False,
        "cleanup": {"required": True, "conclusion": "passed"},
        "redacted": True,
    }


def _private_path(tmp_path: Path, name: str = "fixture.json") -> Path:
    directory = tmp_path / ".artifacts" / "private"
    directory.mkdir(parents=True, mode=0o700)
    os.chmod(directory, 0o700)
    return directory / name


def _compatibility_receipt(
    runtime: str,
    *,
    workflow_run: str = "https://github.com/enkyuan/alloy/actions/runs/71",
    workflow_attempt: int = 2,
) -> dict[str, Any]:
    common = {
        "schemaVersion": 1,
        "commit": COMMIT,
        "releaseManifestSha256": MANIFEST,
        "workflowRun": workflow_run,
        "workflowRunAttempt": workflow_attempt,
        "githubPackageProofs": {},
        "conclusion": "passed",
        "failureCode": None,
    }
    if runtime == "python":
        return {
            **common,
            "artifactSha256": {
                "kaji_sdk-0.2.0b1-py3-none-any.whl": "1" * 64,
                "kaji_sdk-0.2.0b1.tar.gz": "2" * 64,
            },
            "runtime": {
                "implementation": "CPython",
                "version": "3.11.9",
                "executable": "/opt/python/3.11/bin/python",
            },
            "artifacts": {
                "wheel": "/artifacts/kaji_sdk-0.2.0b1-py3-none-any.whl",
                "sdist": "/artifacts/kaji_sdk-0.2.0b1.tar.gz",
            },
        }
    return {
        **common,
        "artifactSha256": {
            "kaji-sdk-0.2.0-beta.7.tgz": "3" * 64,
        },
        "runtime": {"version": "v22.14.0"},
        "artifacts": {
            "tarball": "/artifacts/kaji-sdk-0.2.0-beta.7.tgz",
            "package": "/tmp/installed/node_modules/kaji-sdk",
        },
    }


def _prerequisite_files(tmp_path: Path) -> tuple[Path, Path]:
    python = tmp_path / "python-compat.json"
    typescript = tmp_path / "typescript-compat.json"
    python.write_text(json.dumps(_compatibility_receipt("python"), indent=2) + "\n")
    typescript.write_text(
        json.dumps(_compatibility_receipt("typescript"), indent=2) + "\n"
    )
    return python, typescript


def _release(tmp_path: Path) -> VerifiedReleaseArtifacts:
    return VerifiedReleaseArtifacts(
        root=tmp_path / "artifacts",
        commit=COMMIT,
        manifest_sha256=MANIFEST,
        python_wheel=tmp_path / "artifacts/kaji_sdk-0.2.0b1-py3-none-any.whl",
        python_sdist=tmp_path / "artifacts/kaji_sdk-0.2.0b1.tar.gz",
        npm_tarball=tmp_path / "artifacts/kaji-sdk-0.2.0-beta.7.tgz",
        artifact_sha256={
            "kaji_sdk-0.2.0b1-py3-none-any.whl": "1" * 64,
            "kaji_sdk-0.2.0b1.tar.gz": "2" * 64,
            "kaji-sdk-0.2.0-beta.7.tgz": "3" * 64,
        },
    )


def _load_script(name: str) -> Any:
    path = SCRIPTS / name
    spec = importlib.util.spec_from_file_location(f"task9_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_github_proof_contract_is_closed_and_orders_two_cells() -> None:
    schema = json.loads(
        (
            ROOT / "kaji" / "contracts" / "release" / "github-proof-v1.schema.json"
        ).read_text()
    )
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    receipt = _public_receipt()

    assert list(validator.iter_errors(receipt)) == []
    for hostile in (
        {**receipt, "repository": "private/repository"},
        {**receipt, "token": "ghp_secret"},
        {**receipt, "provider": "gmail"},
        {**receipt, "extra": True},
        {**receipt, "cells": receipt["cells"][:1]},
        {
            **receipt,
            "cells": [receipt["cells"][1], receipt["cells"][0]],
        },
    ):
        assert list(validator.iter_errors(hostile))


def test_prerequisites_bind_raw_receipts_to_one_exact_candidate(
    tmp_path: Path,
) -> None:
    python, typescript = _prerequisite_files(tmp_path)
    validated: list[tuple[str, str]] = []

    def compatibility_validator(
        document: dict[str, Any], runtime: str, version: str, *_args: Any
    ) -> None:
        assert document["runtime"]
        validated.append((runtime, version))

    result = validate_prerequisites(
        tmp_path / "artifacts",
        COMMIT,
        python,
        typescript,
        verifier=lambda *_args: _release(tmp_path),
        compatibility_validator=compatibility_validator,
        workspace=ROOT,
    )

    assert validated == [("python", "3.11"), ("typescript", "22")]
    assert result.commit == COMMIT
    assert result.release_manifest_sha256 == MANIFEST
    assert result.workflow_run.endswith("/71")
    assert result.workflow_run_attempt == 2
    assert result.artifact_sha256 == {
        "python": "1" * 64,
        "typescript": "3" * 64,
    }
    assert result.package_proof_sha256 == {
        "python": hashlib.sha256(python.read_bytes()).hexdigest(),
        "typescript": hashlib.sha256(typescript.read_bytes()).hexdigest(),
    }


@pytest.mark.parametrize(
    ("label", "mutate"),
    (
        (
            "wrong-commit",
            lambda value: value.update(commit="f" * 40),
        ),
        (
            "wrong-manifest",
            lambda value: value.update(releaseManifestSha256="f" * 64),
        ),
        (
            "stale-run",
            lambda value: value.update(
                workflowRun="https://github.com/enkyuan/alloy/actions/runs/72"
            ),
        ),
        (
            "run-attempt",
            lambda value: value.update(workflowRunAttempt=3),
        ),
        (
            "nonterminal",
            lambda value: value.update(
                conclusion="failed", failureCode="compatibility_failed"
            ),
        ),
        (
            "wrong-node",
            lambda value: value["runtime"].update(version="v24.4.0"),
        ),
        (
            "source-path",
            lambda value: value["artifacts"].update(
                package=str(ROOT / "kaji/ts/src/node_modules/kaji-sdk")
            ),
        ),
    ),
)
def test_prerequisite_identity_rejections_precede_compatibility_execution(
    tmp_path: Path, label: str, mutate: Any
) -> None:
    python, typescript = _prerequisite_files(tmp_path)
    target = (
        python
        if label in {"wrong-commit", "wrong-manifest", "nonterminal"}
        else typescript
    )
    document = json.loads(target.read_text())
    mutate(document)
    target.write_text(json.dumps(document))
    validations = 0

    def compatibility_validator(*_args: Any) -> None:
        nonlocal validations
        validations += 1

    with pytest.raises(GitHubProofError, match="prerequisite_invalid"):
        validate_prerequisites(
            tmp_path / "artifacts",
            COMMIT,
            python,
            typescript,
            verifier=lambda *_args: _release(tmp_path),
            compatibility_validator=compatibility_validator,
            workspace=ROOT,
        )
    assert validations == 0


def test_prerequisites_delegate_exact_task8_shape_before_any_live_work(
    tmp_path: Path,
) -> None:
    python, typescript = _prerequisite_files(tmp_path)
    document = json.loads(typescript.read_text())
    document["githubPackageProofs"] = {
        "npm": {
            "schemaVersion": 4,
            "publicScenarioCount": 14,
            "unknownMutationPreserved": False,
            "mutationRetries": 1,
        },
        "bun": {"divergent": True},
    }
    typescript.write_text(json.dumps(document))
    calls: list[str] = []

    def compatibility_validator(
        _document: dict[str, Any], runtime: str, _version: str, *_args: Any
    ) -> None:
        calls.append(runtime)
        if runtime == "typescript":
            raise RuntimeError("github_package_proof_invalid")

    with pytest.raises(GitHubProofError, match="prerequisite_invalid"):
        validate_prerequisites(
            tmp_path / "artifacts",
            COMMIT,
            python,
            typescript,
            verifier=lambda *_args: _release(tmp_path),
            compatibility_validator=compatibility_validator,
            workspace=ROOT,
        )
    assert calls == ["python", "typescript"]


@pytest.mark.parametrize(
    "payload",
    (
        b'{"schemaVersion":1,"schemaVersion":1}',
        b'{"schemaVersion":NaN}',
        b" " * (1024 * 1024 + 1),
    ),
)
def test_prerequisites_reject_unsafe_receipt_bytes(
    tmp_path: Path, payload: bytes
) -> None:
    python, typescript = _prerequisite_files(tmp_path)
    python.write_bytes(payload)
    with pytest.raises(GitHubProofError, match="prerequisite_invalid"):
        validate_prerequisites(
            tmp_path / "artifacts",
            COMMIT,
            python,
            typescript,
            verifier=lambda *_args: _release(tmp_path),
            compatibility_validator=lambda *_args: None,
            workspace=ROOT,
        )


@pytest.mark.parametrize("runtime", ("python", "typescript"))
def test_installed_child_receipt_is_closed_and_bounded(runtime: str) -> None:
    receipt = {
        "runtime": runtime,
        "readPassed": True,
        "approvedCommentPassed": True,
        "commentId": 91,
    }
    assert (
        validate_child_receipt(
            json.dumps(receipt, separators=(",", ":")).encode(), runtime
        )
        == receipt
    )
    for hostile in (
        {**receipt, "repository": "private/repository"},
        {**receipt, "body": "private marker"},
        {**receipt, "extra": True},
        {**receipt, "runtime": "python" if runtime == "typescript" else "typescript"},
        {**receipt, "readPassed": False},
        {**receipt, "commentId": 0},
    ):
        with pytest.raises(GitHubProofError, match="child_receipt_invalid"):
            validate_child_receipt(json.dumps(hostile).encode(), runtime)
    with pytest.raises(GitHubProofError, match="child_receipt_invalid"):
        validate_child_receipt(b"x" * 65_537, runtime)


@pytest.mark.asyncio
async def test_python_installed_cell_reads_then_approves_one_exact_comment() -> None:
    runner = _load_script("installed_github_live.py")
    calls: list[tuple[str, dict[str, Any]]] = []

    class Client:
        async def get_issue(self, context: object, **arguments: Any) -> dict[str, Any]:
            del context
            calls.append(("get_issue", arguments))
            return {
                "number": arguments["issue_number"],
                "state": "open",
                "title": "Proof fixture",
                "body": "",
                "url": "https://github.com/octo/widgets/issues/7",
            }

        async def add_comment(
            self, context: object, **arguments: Any
        ) -> dict[str, Any]:
            del context
            calls.append(("add_comment", arguments))
            return {
                "id": 91,
                "url": "https://github.com/octo/widgets/issues/7#issuecomment-91",
            }

        async def create_issue(
            self, context: object, **_kwargs: object
        ) -> dict[str, Any]:
            del context
            raise AssertionError("create_issue must never execute")

        async def get_file(self, context: object, **_kwargs: object) -> dict[str, Any]:
            del context
            raise AssertionError("unexpected tool")

        async def list_issues(
            self, context: object, **_kwargs: object
        ) -> dict[str, Any]:
            del context
            raise AssertionError("unexpected tool")

        async def search_code(
            self, context: object, **_kwargs: object
        ) -> dict[str, Any]:
            del context
            raise AssertionError("unexpected tool")

    from kaji.integrations.registry.github.github import GitHubIntegration

    integration = GitHubIntegration(Client())
    module = SimpleNamespace(create_github_integration=lambda **_kwargs: integration)
    marker = f"kaji-proof/{COMMIT}/python/{'1' * 32}"

    receipt = await runner._execute(
        module,
        repository="octo/widgets",
        issue_number=7,
        marker=marker,
        token="token",
    )

    assert receipt == {
        "runtime": "python",
        "readPassed": True,
        "approvedCommentPassed": True,
        "commentId": 91,
    }
    assert calls == [
        ("get_issue", {"repository": "octo/widgets", "issue_number": 7}),
        (
            "add_comment",
            {
                "repository": "octo/widgets",
                "issue_number": 7,
                "body": marker,
            },
        ),
    ]


def test_installed_children_have_no_source_fallback_or_issue_creation_call() -> None:
    python = (SCRIPTS / "installed_github_live.py").read_text()
    typescript = (
        ROOT / "kaji" / "ts" / "scripts" / "installed-github-live.mts"
    ).read_text()
    for source in (python, typescript):
        assert "source fallback" not in source.lower()
        assert "create_issue(" not in source
        assert 'github_create_issue",' in source
        assert "github_get_issue" in source
        assert "github_add_comment" in source
        assert "KAJI_GITHUB_PROOF_TOKEN" in source
    assert 'Path(kaji.__file__ or "").resolve().parent != package_root' in python
    assert 'import.meta.resolve("kaji-sdk")' in typescript
    assert "KAJI_GITHUB_PROOF_INPUT" in typescript
    assert "readFileSync" not in typescript
    assert "/.artifacts/private/" not in typescript

    abi = json.loads(
        (
            ROOT
            / "kaji"
            / "contracts"
            / "integrations"
            / "github-tool-abi-typescript-v1.json"
        ).read_text()
    )
    expected = {f"github_{tool['name']}" for tool in abi["tools"]}
    catalog_block = typescript.split("const EXPECTED_TOOLS", 1)[1].split("]);", 1)[0]
    actual = {
        line.strip().removesuffix(",").strip('"')
        for line in catalog_block.splitlines()
        if '"github_' in line
    }
    assert actual == expected


def test_typescript_child_receives_parent_snapshot_without_a_private_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = _load_script("live_github_proof.py")
    input_path = _private_path(tmp_path, "typescript-input.json")
    document = {
        "runtime": "typescript",
        "owner": "octo",
        "repository": "widgets",
        "issueNumber": 7,
        "marker": f"kaji-proof/{COMMIT}/typescript/{'1' * 32}",
    }
    write_private_json(input_path, document)
    captured: dict[str, Any] = {}

    def run_checked(command: list[str], **kwargs: Any) -> Any:
        captured["command"] = command
        captured["environment"] = kwargs["env"]
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "runtime": "typescript",
                    "readPassed": True,
                    "approvedCommentPassed": True,
                    "commentId": 91,
                }
            ).encode(),
            stderr=b"",
        )

    monkeypatch.setattr(live, "run_checked", run_checked)
    monkeypatch.setattr(live.shutil, "which", lambda *_args, **_kwargs: "/bun")
    runtime = SimpleNamespace(
        environment={"PATH": "/bin"},
        root=tmp_path,
        typescript_workdir=tmp_path,
        resolved_typescript_package=tmp_path / "node_modules" / "kaji-sdk",
    )

    assert live._default_child_runner(runtime, "typescript", input_path, "token") == {
        "runtime": "typescript",
        "readPassed": True,
        "approvedCommentPassed": True,
        "commentId": 91,
    }
    assert "--input" not in captured["command"]
    assert str(input_path) not in captured["command"]
    assert json.loads(captured["environment"]["KAJI_GITHUB_PROOF_INPUT"]) == document


def _write_fake_installed_kaji(package: Path) -> None:
    package.mkdir()
    (package / "__init__.py").write_text(
        textwrap.dedent(
            """
            import sys
            import types
            from types import SimpleNamespace

            def package(name):
                value = types.ModuleType(name)
                value.__path__ = []
                sys.modules[name] = value

            def module(name, **values):
                value = types.ModuleType(name)
                value.__dict__.update(values)
                sys.modules[name] = value

            for name in (
                "kaji.infra",
                "kaji.infra.events",
                "kaji.runtime",
                "kaji.runtime.agents",
                "kaji.runtime.tools",
            ):
                package(name)

            class Box:
                def __init__(self, *args, **kwargs):
                    self.args = args
                    self.__dict__.update(kwargs)

            class ApprovalDecision:
                def __init__(self, granted, code):
                    self.granted = granted
                    self.code = code

            class ToolInvocation:
                def __init__(self, identifier, name, arguments, context):
                    self.id = identifier
                    self.name = name
                    self.arguments = arguments
                    self.context = context

            class ToolRegistry:
                def __init__(self):
                    self.specs = {}
                    self.handlers = {}

                def add(self, name, risk, handler):
                    self.specs[name] = SimpleNamespace(name=name, risk=risk)
                    self.handlers[name] = handler

                def list_specs(self):
                    return list(self.specs.values())

                async def execute(self, invocation):
                    return await self.handlers[invocation.name](
                        invocation.context, dict(invocation.arguments)
                    )

            class ToolPlanner:
                def __init__(
                    self,
                    executor,
                    *,
                    policy,
                    approval_handler,
                    specs,
                ):
                    self.executor = executor
                    self.approval_handler = approval_handler
                    self.specs = specs

                async def execute_batch(self, _session, calls, _emitter, **_kwargs):
                    results = []
                    for call in calls:
                        invocation = ToolInvocation(
                            call["id"],
                            call["name"],
                            call["arguments"],
                            SimpleNamespace(),
                        )
                        if self.specs[call["name"]].risk == "external_effect":
                            decision = await self.approval_handler.request(
                                invocation, SimpleNamespace()
                            )
                            if not decision.granted:
                                raise RuntimeError("approval rejected")
                        results.append({"result": await self.executor(invocation)})
                    return results

            class JournalEventEmitter:
                def __init__(self, _journal):
                    pass

            module(
                "kaji.infra.events.journal",
                InMemoryEventJournal=Box,
            )
            module(
                "kaji.infra.events.store",
                InMemoryEventStore=Box,
            )
            module(
                "kaji.runtime.agents.approval",
                ApprovalDecision=ApprovalDecision,
                ApprovalRequestContext=Box,
            )
            module(
                "kaji.runtime.agents.cancellation",
                CancellationToken=Box,
            )
            module(
                "kaji.runtime.agents.context",
                TurnContext=Box,
            )
            module(
                "kaji.runtime.agents.planner",
                JournalEventEmitter=JournalEventEmitter,
                ToolPlanner=ToolPlanner,
            )
            module(
                "kaji.runtime.context",
                ToolInvocation=ToolInvocation,
            )
            module(
                "kaji.runtime.tools.policies",
                ToolPolicy=Box,
            )
            module(
                "kaji.runtime.tools.registry",
                ToolRegistry=ToolRegistry,
            )
            """
        ).lstrip()
    )


def _write_fake_github_bundle(bundle: Path) -> None:
    bundle.mkdir(parents=True)
    (bundle / "client.py").write_text("# installed fake client\n")
    (bundle / "github.py").write_text(
        textwrap.dedent(
            """
            TOOL_RISKS = {
                "github_add_comment": "external_effect",
                "github_create_issue": "external_effect",
                "github_get_file": "read",
                "github_get_issue": "read",
                "github_list_issues": "read",
                "github_search_code": "read",
            }

            class Integration:
                def register(self, registry):
                    for name, risk in TOOL_RISKS.items():
                        async def handler(_context, arguments, *, selected=name):
                            if selected == "github_get_issue":
                                return {"number": arguments["issue_number"]}
                            if selected == "github_add_comment":
                                return {"id": 91}
                            raise RuntimeError("unexpected fake tool")
                        registry.add(name, risk, handler)

                async def aclose(self):
                    return None

            def create_github_integration(**_kwargs):
                return Integration()
            """
        ).lstrip()
    )


def test_python_installed_child_bootstrap_runs_isolated_help_and_fake_package(
    tmp_path: Path,
) -> None:
    live = _load_script("live_github_proof.py")
    root = tmp_path / "installed"
    root.mkdir()
    helper = root / "github_proof_control.py"
    runner = root / "installed_github_live.py"
    shutil.copy2(SCRIPTS / helper.name, helper)
    shutil.copy2(SCRIPTS / runner.name, runner)
    package = root / "kaji"
    _write_fake_installed_kaji(package)
    bundle = root / "owner_integrations" / "github"
    _write_fake_github_bundle(bundle)
    input_path = root / ".artifacts" / "private" / "input.json"
    input_path.parent.mkdir(parents=True, mode=0o700)
    os.chmod(input_path.parent, 0o700)
    write_private_json(
        input_path,
        {
            "runtime": "python",
            "owner": "octo",
            "repository": "widgets",
            "issueNumber": 7,
            "marker": f"kaji-proof/{COMMIT}/python/{'1' * 32}",
        },
    )
    prefix = [
        sys.executable,
        "-I",
        "-c",
        live.PYTHON_CHILD_BOOTSTRAP,
        str(root),
        str(helper),
        str(runner),
    ]
    environment = {
        "PATH": os.environ["PATH"],
        "KAJI_GITHUB_PROOF_TOKEN": "token",
    }

    help_result = subprocess.run(
        [*prefix, "--help"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "--package-root" in help_result.stdout

    command = [
        *prefix,
        "--sandbox-root",
        str(root),
        "--bundle-root",
        str(bundle),
        "--package-root",
        str(package),
        "--input",
        str(input_path),
    ]
    result = subprocess.run(
        command,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "runtime": "python",
        "readPassed": True,
        "approvedCommentPassed": True,
        "commentId": 91,
    }

    wrong = list(command)
    wrong[wrong.index(str(package))] = str(ROOT / "kaji" / "src" / "kaji")
    rejected = subprocess.run(
        wrong,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode == 1
    assert rejected.stderr == "installed GitHub proof failed\n"


class _ProofServer:
    def __init__(self) -> None:
        self.comments: list[dict[str, Any]] = []
        self.calls: list[tuple[Any, ...]] = []


class _ProofControl:
    def __init__(self, server: _ProofServer) -> None:
        self.server = server

    async def __aenter__(self) -> _ProofControl:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def list_issue_comments(
        self, owner: str, repository: str, issue_number: int
    ) -> list[dict[str, Any]]:
        self.server.calls.append(("list", owner, repository, issue_number))
        expected = (
            f"https://api.github.com/repos/{owner}/{repository}/issues/{issue_number}"
        )
        return [
            comment
            for comment in self.server.comments
            if comment.get("issueUrl") == expected
        ]

    async def get_comment(
        self, owner: str, repository: str, comment_id: int
    ) -> dict[str, Any] | None:
        self.server.calls.append(("get", owner, repository, comment_id))
        return next(
            (
                comment
                for comment in self.server.comments
                if comment["id"] == comment_id
            ),
            None,
        )

    async def delete_comment(
        self, owner: str, repository: str, comment_id: int
    ) -> None:
        self.server.calls.append(("delete", owner, repository, comment_id))
        self.server.comments = [
            comment for comment in self.server.comments if comment["id"] != comment_id
        ]


def _proof_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    private = tmp_path / ".artifacts" / "private"
    private.mkdir(parents=True, mode=0o700)
    os.chmod(private, 0o700)
    fixture = private / "fixture.json"
    fixture.write_text('{"owner":"octo","repository":"widgets","issueNumber":7}\n')
    os.chmod(fixture, 0o600)
    return (
        fixture,
        private / "state.json",
        tmp_path / ".artifacts" / "evidence" / "github-proof.json",
    )


def _proof_prerequisites(tmp_path: Path) -> ProofPrerequisites:
    release = _release(tmp_path)
    return ProofPrerequisites(
        commit=COMMIT,
        release_manifest_sha256=MANIFEST,
        workflow_run="https://github.com/enkyuan/alloy/actions/runs/71",
        workflow_run_attempt=2,
        artifact_sha256={"python": "1" * 64, "typescript": "3" * 64},
        package_proof_sha256={"python": "4" * 64, "typescript": "5" * 64},
        release=release,
    )


def _runtime_identity() -> dict[str, Any]:
    return {
        "commit": COMMIT,
        "releaseManifestSha256": MANIFEST,
        "artifacts": {
            "python": {
                "file": "kaji_sdk-0.2.0b1-py3-none-any.whl",
                "sha256": "1" * 64,
            },
            "typescript": {
                "file": "kaji-sdk-0.2.0-beta.7.tgz",
                "sha256": "3" * 64,
            },
        },
    }


@pytest.mark.asyncio
async def test_parent_orchestrator_cleans_both_cells_before_public_success(
    tmp_path: Path,
) -> None:
    fixture, state, output = _proof_fixture(tmp_path)
    server = _ProofServer()
    child_calls: list[str] = []
    lifecycle: list[str] = []

    @contextmanager
    def runtime_factory(*_args: Any, **_kwargs: Any) -> Any:
        lifecycle.append("runtime")
        yield SimpleNamespace(identity=_runtime_identity)

    def child_runner(
        _runtime: object,
        runtime: str,
        input_path: Path,
        _token: str,
    ) -> dict[str, Any]:
        assert input_path.name.startswith(f".{runtime}-github-input-")
        assert input_path != state
        private_input = read_private_json(input_path)
        assert (
            read_private_json(state)["cells"][len(child_calls)]["phase"] == "dispatched"
        )
        comment_id = 91 + len(child_calls)
        server.comments.append(
            {
                "id": comment_id,
                "body": private_input["marker"],
                "issueUrl": ISSUE_URL,
            }
        )
        child_calls.append(runtime)
        return {
            "runtime": runtime,
            "readPassed": True,
            "approvedCommentPassed": True,
            "commentId": comment_id,
        }

    receipt = await run_proof(
        artifacts_dir=tmp_path / "artifacts",
        expected_commit=COMMIT,
        python_compatibility=tmp_path / "python.json",
        typescript_compatibility=tmp_path / "typescript.json",
        fixture_path=fixture,
        state_path=state,
        output_path=output,
        environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
        prerequisite_loader=lambda *_args, **_kwargs: _proof_prerequisites(tmp_path),
        runtime_factory=runtime_factory,
        runtime_preparer=lambda _runtime: None,
        child_runner=child_runner,
        control_factory=lambda _token: _ProofControl(server),
    )

    assert child_calls == ["python", "typescript"]
    assert lifecycle == ["runtime"]
    assert server.comments == []
    private_state = read_private_json(state)
    assert [cell["phase"] for cell in private_state["cells"]] == [
        "cleaned",
        "cleaned",
    ]
    assert receipt == json.loads(output.read_text())
    assert receipt["cells"] == [
        {
            "runtime": "python",
            "artifactSha256": "1" * 64,
            "packageProofSha256": "4" * 64,
            "conclusion": "passed",
        },
        {
            "runtime": "typescript",
            "artifactSha256": "3" * 64,
            "packageProofSha256": "5" * 64,
            "conclusion": "passed",
        },
    ]
    retained = output.read_text()
    for private_value in ("octo", "widgets", "kaji-proof/", "91", "92", "token"):
        assert private_value not in retained


@pytest.mark.asyncio
async def test_parent_reconciles_unknown_child_dispatch_without_public_pass(
    tmp_path: Path,
) -> None:
    fixture, state, output = _proof_fixture(tmp_path)
    server = _ProofServer()

    @contextmanager
    def runtime_factory(*_args: Any, **_kwargs: Any) -> Any:
        yield SimpleNamespace(identity=_runtime_identity)

    def interrupted_child(
        _runtime: object,
        _runtime_name: str,
        input_path: Path,
        _token: str,
    ) -> dict[str, Any]:
        private_input = read_private_json(input_path)
        server.comments.append(
            {
                "id": 91,
                "body": private_input["marker"],
                "issueUrl": ISSUE_URL,
            }
        )
        raise RuntimeError("private child detail")

    with pytest.raises(GitHubProofError, match="cleanup_incomplete"):
        await run_proof(
            artifacts_dir=tmp_path / "artifacts",
            expected_commit=COMMIT,
            python_compatibility=tmp_path / "python.json",
            typescript_compatibility=tmp_path / "typescript.json",
            fixture_path=fixture,
            state_path=state,
            output_path=output,
            environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
            prerequisite_loader=lambda *_args, **_kwargs: _proof_prerequisites(
                tmp_path
            ),
            runtime_factory=runtime_factory,
            runtime_preparer=lambda _runtime: None,
            child_runner=interrupted_child,
            control_factory=lambda _token: _ProofControl(server),
        )
    assert server.comments == []
    cell = read_private_json(state)["cells"][0]
    assert cell["phase"] == "failed"
    assert cell["failureOrigin"] == "child"
    assert cell["reconciliationRequired"] is False
    assert not output.exists()


@pytest.mark.asyncio
async def test_parent_keeps_wrong_issue_marker_pending_for_manual_review(
    tmp_path: Path,
) -> None:
    fixture, state, output = _proof_fixture(tmp_path)
    server = _ProofServer()

    @contextmanager
    def runtime_factory(*_args: Any, **_kwargs: Any) -> Any:
        yield SimpleNamespace(identity=_runtime_identity)

    def wrong_id_child(
        _runtime: object,
        runtime_name: str,
        input_path: Path,
        _token: str,
    ) -> dict[str, Any]:
        private_input = read_private_json(input_path)
        assert runtime_name == "python"
        server.comments.extend(
            (
                {
                    "id": 91,
                    "body": private_input["marker"],
                    "issueUrl": (
                        "https://api.github.com/repos/octo/widgets/issues/999"
                    ),
                },
                {
                    "id": 92,
                    "body": private_input["marker"],
                    "issueUrl": ISSUE_URL,
                },
            )
        )
        return {
            "runtime": runtime_name,
            "readPassed": True,
            "approvedCommentPassed": True,
            "commentId": 91,
        }

    with pytest.raises(GitHubProofError, match="cleanup_issue_mismatch"):
        await run_proof(
            artifacts_dir=tmp_path / "artifacts",
            expected_commit=COMMIT,
            python_compatibility=tmp_path / "python.json",
            typescript_compatibility=tmp_path / "typescript.json",
            fixture_path=fixture,
            state_path=state,
            output_path=output,
            environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
            prerequisite_loader=lambda *_args, **_kwargs: _proof_prerequisites(
                tmp_path
            ),
            runtime_factory=runtime_factory,
            runtime_preparer=lambda _runtime: None,
            child_runner=wrong_id_child,
            control_factory=lambda _token: _ProofControl(server),
        )

    assert not output.exists()
    assert [comment["id"] for comment in server.comments] == [91, 92]
    cell = read_private_json(state)["cells"][0]
    assert cell["phase"] == "failed"
    assert cell["commentId"] == 91
    assert cell["reconciliationRequired"] is True
    assert cell["absenceObserved"] is False


@pytest.mark.asyncio
async def test_legacy_input_filename_cannot_delete_state_after_unknown_dispatch(
    tmp_path: Path,
) -> None:
    fixture, _state, output = _proof_fixture(tmp_path)
    state = fixture.with_name(".python-github-input.json")
    server = _ProofServer()

    @contextmanager
    def runtime_factory(*_args: Any, **_kwargs: Any) -> Any:
        yield SimpleNamespace(identity=_runtime_identity)

    def interrupted_child(
        _runtime: object,
        _runtime_name: str,
        input_path: Path,
        _token: str,
    ) -> dict[str, Any]:
        private_input = read_private_json(input_path)
        server.comments.append(
            {
                "id": 91,
                "body": private_input["marker"],
                "issueUrl": ISSUE_URL,
            }
        )
        raise RuntimeError("ambiguous child result")

    with pytest.raises(GitHubProofError):
        await run_proof(
            artifacts_dir=tmp_path / "artifacts",
            expected_commit=COMMIT,
            python_compatibility=tmp_path / "python.json",
            typescript_compatibility=tmp_path / "typescript.json",
            fixture_path=fixture,
            state_path=state,
            output_path=output,
            environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
            prerequisite_loader=lambda *_args, **_kwargs: _proof_prerequisites(
                tmp_path
            ),
            runtime_factory=runtime_factory,
            runtime_preparer=lambda _runtime: None,
            child_runner=interrupted_child,
            control_factory=lambda _token: _ProofControl(server),
        )

    assert state.exists()
    assert server.comments == []
    cell = read_private_json(state)["cells"][0]
    assert cell["phase"] == "failed"
    assert cell["reconciliationRequired"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", ("fixture", "output"))
async def test_private_path_aliases_fail_before_prerequisites_or_state_creation(
    tmp_path: Path,
    alias: str,
) -> None:
    fixture, state, output = _proof_fixture(tmp_path)
    prerequisite_calls = 0

    def prerequisites(*_args: Any, **_kwargs: Any) -> ProofPrerequisites:
        nonlocal prerequisite_calls
        prerequisite_calls += 1
        return _proof_prerequisites(tmp_path)

    requested_state = fixture if alias == "fixture" else state
    requested_output = state if alias == "output" else output
    fixture_before = fixture.read_bytes()
    with pytest.raises(GitHubProofError, match="path_collision"):
        await run_proof(
            artifacts_dir=tmp_path / "artifacts",
            expected_commit=COMMIT,
            python_compatibility=tmp_path / "python.json",
            typescript_compatibility=tmp_path / "typescript.json",
            fixture_path=fixture,
            state_path=requested_state,
            output_path=requested_output,
            environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
            prerequisite_loader=prerequisites,
        )

    assert prerequisite_calls == 0
    assert fixture.read_bytes() == fixture_before
    if alias == "output":
        assert not state.exists()


@pytest.mark.asyncio
async def test_casefold_path_alias_fails_before_prerequisites(
    tmp_path: Path,
) -> None:
    fixture, state, _output = _proof_fixture(tmp_path)
    prerequisite_calls = 0

    def prerequisites(*_args: Any, **_kwargs: Any) -> ProofPrerequisites:
        nonlocal prerequisite_calls
        prerequisite_calls += 1
        return _proof_prerequisites(tmp_path)

    with pytest.raises(GitHubProofError, match="path_collision"):
        await run_proof(
            artifacts_dir=tmp_path / "artifacts",
            expected_commit=COMMIT,
            python_compatibility=tmp_path / "python.json",
            typescript_compatibility=tmp_path / "typescript.json",
            fixture_path=fixture,
            state_path=state,
            output_path=state.with_name(state.name.upper()),
            environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
            prerequisite_loader=prerequisites,
        )

    assert prerequisite_calls == 0
    assert not state.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "protected_output",
    ("python-compat", "typescript-compat", "manifest", "wheel", "artifact-descendant"),
)
async def test_output_cannot_alias_retained_prerequisites_or_artifacts(
    tmp_path: Path,
    protected_output: str,
) -> None:
    fixture, state, _output = _proof_fixture(tmp_path)
    artifacts = tmp_path / "artifacts"
    python_compatibility = tmp_path / "python.json"
    typescript_compatibility = tmp_path / "typescript.json"
    paths = {
        "python-compat": python_compatibility,
        "typescript-compat": typescript_compatibility,
        "manifest": artifacts / "manifest.json",
        "wheel": artifacts / "kaji_sdk-0.2.0b1-py3-none-any.whl",
        "artifact-descendant": artifacts / "github-proof.json",
    }
    prerequisite_calls = 0

    def prerequisites(*_args: Any, **_kwargs: Any) -> ProofPrerequisites:
        nonlocal prerequisite_calls
        prerequisite_calls += 1
        return _proof_prerequisites(tmp_path)

    with pytest.raises(GitHubProofError, match="path_collision"):
        await run_proof(
            artifacts_dir=artifacts,
            expected_commit=COMMIT,
            python_compatibility=python_compatibility,
            typescript_compatibility=typescript_compatibility,
            fixture_path=fixture,
            state_path=state,
            output_path=paths[protected_output],
            environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
            prerequisite_loader=prerequisites,
        )

    assert prerequisite_calls == 0
    assert not state.exists()


@pytest.mark.asyncio
async def test_state_lock_contention_fails_before_prerequisites_or_transport(
    tmp_path: Path,
) -> None:
    fixture, state, output = _proof_fixture(tmp_path)
    prerequisite_calls = 0

    def prerequisites(*_args: Any, **_kwargs: Any) -> ProofPrerequisites:
        nonlocal prerequisite_calls
        prerequisite_calls += 1
        return _proof_prerequisites(tmp_path)

    with private_state_lock(state):
        with pytest.raises(GitHubProofError, match="state_lock_busy"):
            await run_proof(
                artifacts_dir=tmp_path / "artifacts",
                expected_commit=COMMIT,
                python_compatibility=tmp_path / "python.json",
                typescript_compatibility=tmp_path / "typescript.json",
                fixture_path=fixture,
                state_path=state,
                output_path=output,
                environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
                prerequisite_loader=prerequisites,
            )

    assert prerequisite_calls == 0
    assert not state.exists()


@pytest.mark.asyncio
async def test_cleaned_rerun_is_runtime_token_and_network_free(
    tmp_path: Path,
) -> None:
    fixture, state, output = _proof_fixture(tmp_path)
    proof_state = new_proof_state(
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
    for index, runtime in enumerate(("python", "typescript")):
        update_proof_cell(
            proof_state,
            runtime,
            phase="cleaned",
            dispatchAttempted=True,
            reconciliationRequired=False,
            commentId=91 + index,
            readPassed=True,
            approvedCommentPassed=True,
            controlReadbackPassed=True,
        )
    write_private_json(state, proof_state)

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("cleaned rerun must not construct runtime or transport")

    receipt = await run_proof(
        artifacts_dir=tmp_path / "artifacts",
        expected_commit=COMMIT,
        python_compatibility=tmp_path / "python.json",
        typescript_compatibility=tmp_path / "typescript.json",
        fixture_path=fixture,
        state_path=state,
        output_path=output,
        environment={},
        prerequisite_loader=lambda *_args, **_kwargs: _proof_prerequisites(tmp_path),
        runtime_factory=forbidden,
        runtime_preparer=forbidden,
        child_runner=forbidden,
        control_factory=forbidden,
    )
    assert receipt["cleanup"] == {"required": True, "conclusion": "passed"}


@pytest.mark.asyncio
async def test_prerequisites_fail_before_token_transport_or_runtime(
    tmp_path: Path,
) -> None:
    fixture, state, output = _proof_fixture(tmp_path)
    events: list[str] = []

    def prerequisites(*_args: Any, **_kwargs: Any) -> ProofPrerequisites:
        events.append("prerequisite")
        raise GitHubProofError("prerequisite_invalid")

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        events.append("forbidden")
        raise AssertionError

    with pytest.raises(GitHubProofError, match="prerequisite_invalid"):
        await run_proof(
            artifacts_dir=tmp_path / "artifacts",
            expected_commit=COMMIT,
            python_compatibility=tmp_path / "python.json",
            typescript_compatibility=tmp_path / "typescript.json",
            fixture_path=fixture,
            state_path=state,
            output_path=output,
            environment={"KAJI_GITHUB_PROOF_TOKEN": "token"},
            prerequisite_loader=prerequisites,
            runtime_factory=forbidden,
            runtime_preparer=forbidden,
            child_runner=forbidden,
            control_factory=forbidden,
        )
    assert events == ["prerequisite"]
    assert not state.exists()
    assert not output.exists()


@pytest.mark.asyncio
async def test_missing_token_fails_after_prerequisites_before_runtime(
    tmp_path: Path,
) -> None:
    fixture, state, output = _proof_fixture(tmp_path)
    runtime_calls = 0

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal runtime_calls
        runtime_calls += 1
        raise AssertionError

    with pytest.raises(GitHubProofError, match="proof_token_missing"):
        await run_proof(
            artifacts_dir=tmp_path / "artifacts",
            expected_commit=COMMIT,
            python_compatibility=tmp_path / "python.json",
            typescript_compatibility=tmp_path / "typescript.json",
            fixture_path=fixture,
            state_path=state,
            output_path=output,
            environment={},
            prerequisite_loader=lambda *_args, **_kwargs: _proof_prerequisites(
                tmp_path
            ),
            runtime_factory=forbidden,
            runtime_preparer=forbidden,
            child_runner=forbidden,
            control_factory=forbidden,
        )
    assert runtime_calls == 0
    assert not state.exists()


@pytest.mark.asyncio
async def test_unsafe_token_fails_before_state_transport_or_runtime(
    tmp_path: Path,
) -> None:
    fixture, state, output = _proof_fixture(tmp_path)
    runtime_calls = 0

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal runtime_calls
        runtime_calls += 1
        raise AssertionError

    with pytest.raises(GitHubProofError, match="control_token_invalid"):
        await run_proof(
            artifacts_dir=tmp_path / "artifacts",
            expected_commit=COMMIT,
            python_compatibility=tmp_path / "python.json",
            typescript_compatibility=tmp_path / "typescript.json",
            fixture_path=fixture,
            state_path=state,
            output_path=output,
            environment={"KAJI_GITHUB_PROOF_TOKEN": "non-ascii-\N{SNOWMAN}"},
            prerequisite_loader=lambda *_args, **_kwargs: _proof_prerequisites(
                tmp_path
            ),
            runtime_factory=forbidden,
            runtime_preparer=forbidden,
            child_runner=forbidden,
            control_factory=forbidden,
        )
    assert runtime_calls == 0
    assert not state.exists()


def test_private_json_requires_owner_only_regular_file(tmp_path: Path) -> None:
    path = _private_path(tmp_path)
    path.write_text('{"owner":"octo","repository":"widgets","issueNumber":1}\n')
    os.chmod(path, 0o600)
    assert read_private_json(path)["issueNumber"] == 1

    os.chmod(path, 0o640)
    with pytest.raises(GitHubProofError, match="private_input_invalid"):
        read_private_json(path)

    os.chmod(path, 0o600)
    link = path.with_name("fixture-link.json")
    link.symlink_to(path)
    with pytest.raises(GitHubProofError, match="private_input_invalid"):
        read_private_json(link)


def test_private_json_rejects_symlink_ancestors(tmp_path: Path) -> None:
    real = tmp_path / "real"
    private = real / ".artifacts" / "private"
    private.mkdir(parents=True)
    path = private / "fixture.json"
    path.write_text("{}")
    os.chmod(path, 0o600)
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)

    with pytest.raises(GitHubProofError, match="private_input_invalid"):
        read_private_json(alias / ".artifacts" / "private" / "fixture.json")


def test_private_json_rejects_lexical_traversal_without_touching_outside(
    tmp_path: Path,
) -> None:
    private = _private_path(tmp_path).parent
    outside = tmp_path / "outside.json"
    outside.write_text('{"outside":"unchanged"}\n')
    os.chmod(outside, 0o600)
    escaped = private / ".." / ".." / outside.name
    before = outside.read_bytes()

    with pytest.raises(GitHubProofError, match="private_input_invalid"):
        read_private_json(escaped)
    with pytest.raises(GitHubProofError, match="private_input_invalid"):
        write_private_json(escaped, {"outside": "overwritten"})

    assert outside.read_bytes() == before


def test_private_json_rejects_final_file_swap_to_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _private_path(tmp_path)
    path.write_text('{"owner":"octo","repository":"widgets","issueNumber":7}\n')
    os.chmod(path, 0o600)
    outside = tmp_path / "outside.json"
    outside.write_text('{"owner":"outside","repository":"secret","issueNumber":999}\n')
    os.chmod(outside, 0o600)
    real_read_bytes = Path.read_bytes
    real_open = os.open
    swapped = False

    def swap() -> None:
        nonlocal swapped
        if swapped:
            return
        path.unlink()
        path.symlink_to(outside)
        swapped = True

    def swapping_read_bytes(selected: Path) -> bytes:
        if selected == path:
            swap()
        return real_read_bytes(selected)

    def swapping_open(
        selected: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if dir_fd is not None and os.fspath(selected) == path.name:
            swap()
        return real_open(selected, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(Path, "read_bytes", swapping_read_bytes)
    monkeypatch.setattr(proof_control.os, "open", swapping_open)

    with pytest.raises(GitHubProofError, match="private_input_invalid"):
        read_private_json(path)
    assert swapped


@pytest.mark.parametrize(
    "payload",
    (
        b'{"owner":"first","owner":"second"}',
        b'{"issueNumber":NaN}',
        b'{"issueNumber":Infinity}',
        b'{"issueNumber":-Infinity}',
        b"[]",
    ),
)
def test_private_json_rejects_noncanonical_json(tmp_path: Path, payload: bytes) -> None:
    path = _private_path(tmp_path)
    path.write_bytes(payload)
    os.chmod(path, 0o600)
    with pytest.raises(GitHubProofError, match="private_input_invalid"):
        read_private_json(path)


def test_private_json_rejects_oversize_input(tmp_path: Path) -> None:
    path = _private_path(tmp_path)
    path.write_bytes(b" " * 65_537)
    os.chmod(path, 0o600)
    with pytest.raises(GitHubProofError, match="private_input_invalid"):
        read_private_json(path)


def test_private_json_write_is_atomic_owner_only_and_round_trips(
    tmp_path: Path,
) -> None:
    path = _private_path(tmp_path, "state.json")
    document = {
        "schemaVersion": "1.0.0",
        "commit": COMMIT,
        "releaseManifestSha256": MANIFEST,
    }

    write_private_json(path, document)

    assert read_private_json(path) == document
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(path.parent.glob(f".{path.name}.*.tmp")) == []


def _transport(handler: Any) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_control_transport_uses_only_fixed_routes_and_headers() -> None:
    requests: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, str(request.url)))
        assert request.headers["authorization"] == "Bearer proof-token"
        assert request.headers["accept"] == "application/vnd.github+json"
        assert request.headers["x-github-api-version"] == "2026-03-10"
        assert request.headers["user-agent"] == "kaji-github-proof/1.0"
        if request.method == "GET" and request.url.path.endswith("/comments/7"):
            return httpx.Response(
                200,
                json={"id": 7, "body": "marker", "issue_url": ISSUE_URL},
                headers={"content-type": "application/json"},
            )
        if request.method == "GET":
            return httpx.Response(
                200,
                json=[{"id": 7, "body": "marker", "issue_url": ISSUE_URL}],
                headers={"content-type": "application/json"},
            )
        return httpx.Response(204)

    async with GitHubProofControl(
        "proof-token", transport=_transport(handler)
    ) as control:
        assert await control.get_comment("octo", "widgets", 7) == {
            "id": 7,
            "body": "marker",
            "issueUrl": ISSUE_URL,
        }
        assert await control.list_issue_comments("octo", "widgets", 3) == [
            {
                "id": 7,
                "body": "marker",
                "issueUrl": ISSUE_URL,
            }
        ]
        await control.delete_comment("octo", "widgets", 7)

    assert requests == [
        (
            "GET",
            "https://api.github.com/repos/octo/widgets/issues/comments/7",
        ),
        (
            "GET",
            "https://api.github.com/repos/octo/widgets/issues/3/comments?per_page=100&page=1",
        ),
        (
            "DELETE",
            "https://api.github.com/repos/octo/widgets/issues/comments/7",
        ),
    ]


@pytest.mark.parametrize(
    "token",
    (
        "",
        "x" * 4_097,
        "secret\rheader",
        "secret\nheader",
        "non-ascii-\N{SNOWMAN}",
    ),
)
def test_control_transport_rejects_unsafe_tokens(token: str) -> None:
    with pytest.raises(GitHubProofError, match="control_token_invalid"):
        GitHubProofControl(token, transport=_transport(lambda _: httpx.Response(500)))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "code"),
    (
        (
            httpx.Response(302, headers={"location": "https://evil.invalid"}),
            "control_redirect",
        ),
        (httpx.Response(403), "control_forbidden"),
        (httpx.Response(429), "control_rate_limited"),
        (httpx.Response(500), "control_rejected"),
        (httpx.Response(200, content=b"{"), "control_response_invalid"),
    ),
)
async def test_control_transport_returns_only_static_redacted_errors(
    response: httpx.Response, code: str
) -> None:
    canary = "DO_NOT_LEAK_PRIVATE_REPOSITORY"

    async def handler(_request: httpx.Request) -> httpx.Response:
        if response.status_code == 500:
            return httpx.Response(500, content=canary.encode())
        return response

    async with GitHubProofControl(
        "proof-token", transport=_transport(handler)
    ) as control:
        with pytest.raises(GitHubProofError) as error:
            await control.get_comment("octo", "widgets", 7)
    assert str(error.value) == code
    assert canary not in repr(error.value)


@pytest.mark.asyncio
async def test_control_transport_bounds_headers_and_body() -> None:
    responses = iter(
        (
            httpx.Response(200, headers={f"x-{index}": "v" for index in range(65)}),
            httpx.Response(200, content=b"x" * (256 * 1024 + 1)),
        )
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        return next(responses)

    async with GitHubProofControl(
        "proof-token", transport=_transport(handler)
    ) as control:
        with pytest.raises(GitHubProofError, match="control_response_limit"):
            await control.get_comment("octo", "widgets", 7)
        with pytest.raises(GitHubProofError, match="control_response_limit"):
            await control.get_comment("octo", "widgets", 7)


@pytest.mark.asyncio
async def test_control_transport_preserves_cancellation() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    async with GitHubProofControl(
        "proof-token", transport=_transport(handler)
    ) as control:
        with pytest.raises(asyncio.CancelledError):
            await control.get_comment("octo", "widgets", 7)


@pytest.mark.asyncio
async def test_control_list_rejects_pagination_and_cap_ambiguity() -> None:
    responses = iter(
        (
            httpx.Response(
                200,
                json=[],
                headers={
                    "link": '<https://api.github.com/next>; rel="next"',
                },
            ),
            httpx.Response(
                200,
                json=[
                    {
                        "id": index + 1,
                        "body": "other",
                        "issue_url": ISSUE_URL,
                    }
                    for index in range(100)
                ],
            ),
        )
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        return next(responses)

    async with GitHubProofControl(
        "proof-token", transport=_transport(handler)
    ) as control:
        with pytest.raises(GitHubProofError, match="control_list_ambiguous"):
            await control.list_issue_comments("octo", "widgets", 3)
        with pytest.raises(GitHubProofError, match="control_list_ambiguous"):
            await control.list_issue_comments("octo", "widgets", 3)
