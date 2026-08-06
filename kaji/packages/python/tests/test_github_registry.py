"""GitHub registry bundle metadata and wrapper behavior."""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
import sys
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from kaji.runtime.agents.approval import ApprovalDecision
from kaji.runtime.context import ToolExecutionContext
from kaji.runtime.integrations.base import Integration
from kaji.runtime.tools.registry import list_tool_specs
from tests.helpers.approval import StaticApprovalHandler


ROOT = Path(__file__).resolve().parents[4]
ABI = json.loads(
    (ROOT / "kaji/contracts/integrations/github-tool-abi-v1.json").read_text()
)


def _document(integration: Integration) -> dict[str, object]:
    tools = integration.tools()
    return {
        "namespace": integration.namespace,
        "tools": [
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
                "risk": spec.risk,
                "parallel_safe": spec.parallel_safe,
                "timeout_ms": spec.timeout_ms,
            }
            for spec, _handler in tools
        ],
    }


def test_github_inspector_matches_canonical_abi_without_global_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kaji.integrations import fixed_origin
    from kaji.integrations.registry.github.github import inspect_integration

    monkeypatch.setattr(
        fixed_origin.FixedOriginClient,
        "for_github",
        lambda: pytest.fail("inspector constructed production HTTP"),
    )
    before = list_tool_specs()
    inspected = inspect_integration()

    assert _document(inspected) == {
        "namespace": ABI["namespace"],
        "tools": [
            {
                **tool,
                "timeout_ms": tool["timeout_ms"],
            }
            for tool in ABI["tools"]
        ],
    }
    assert list_tool_specs() == before


@pytest.mark.asyncio
async def test_each_wrapper_delegates_once_with_the_execution_context() -> None:
    from kaji.integrations.registry.github.github import GitHubIntegration

    client = type("Client", (), {})()
    calls = {
        "add_comment": {
            "repository": "owner/repo",
            "issue_number": 1,
            "body": "comment",
        },
        "create_issue": {
            "repository": "owner/repo",
            "title": "title",
            "body": "body",
        },
        "get_file": {"repository": "owner/repo", "path": "README.md"},
        "get_issue": {"repository": "owner/repo", "issue_number": 1},
        "list_issues": {"repository": "owner/repo"},
        "search_code": {"repository": "owner/repo", "query": "needle"},
    }
    for name in calls:
        setattr(client, name, AsyncMock(return_value={"operation": name}))
    integration = GitHubIntegration(cast(Any, client))
    context = cast(ToolExecutionContext, object())

    for spec, handler in integration.tools():
        assert await handler(context, calls[spec.name]) == {"operation": spec.name}
        getattr(client, spec.name).assert_awaited_once_with(context, **calls[spec.name])


@pytest.mark.asyncio
async def test_production_integration_closes_its_owned_http_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kaji.integrations import fixed_origin
    from kaji.integrations.registry.github.github import create_github_integration

    http = type(
        "Http",
        (),
        {
            "request": AsyncMock(side_effect=AssertionError("HTTP must not run")),
            "aclose": AsyncMock(),
        },
    )()
    monkeypatch.setattr(
        fixed_origin.FixedOriginClient,
        "for_github",
        lambda **_kwargs: http,
    )
    integration = create_github_integration(
        token_for=AsyncMock(side_effect=AssertionError("token must not be read")),
        repositories={"owner/repo"},
    )

    await asyncio.gather(integration.aclose(), integration.aclose())
    await integration.aclose()

    http.aclose.assert_awaited_once_with()


def test_github_manifest_is_beta_and_declares_native_owner_bundles() -> None:
    python = json.loads(
        (
            ROOT
            / "kaji/packages/python/src/kaji/integrations/registry/github/manifest.json"
        ).read_text()
    )
    typescript = json.loads(
        (ROOT / "kaji/packages/typescript/registry/github/manifest.json").read_text()
    )
    python_index = json.loads(
        (
            ROOT / "kaji/packages/python/src/kaji/integrations/registry/index.json"
        ).read_text()
    )
    typescript_index = json.loads(
        (ROOT / "kaji/packages/typescript/registry/index.json").read_text()
    )

    for index in (python_index, typescript_index):
        assert index["integrations"]["github"] == {
            "manifest": "github/manifest.json",
            "stability": "beta",
            "runtimes": ["python", "typescript"],
        }
    assert python["tools"] == ABI["tools"]
    assert typescript["tools"] == ABI["tools"]
    assert python["files"] == [
        "github.py",
        "client.py",
        "tests/test_github.py",
        "owner-fixtures.json",
        "LICENSE",
    ]
    assert typescript["files"] == [
        "index.ts",
        "client.ts",
        "tests/github.test.ts",
        "owner-fixtures.json",
        "LICENSE",
    ]


def test_github_owner_fixture_has_one_closed_cross_runtime_shape() -> None:
    python_path = (
        ROOT
        / "kaji/packages/python/src/kaji/integrations/registry/github/owner-fixtures.json"
    )
    typescript_path = (
        ROOT / "kaji/packages/typescript/registry/github/owner-fixtures.json"
    )

    assert python_path.read_bytes() == typescript_path.read_bytes()
    assert json.loads(python_path.read_text()) == {
        "schemaVersion": "1.0.0",
        "outcomes": [
            {"name": "success", "expected": "success"},
            {
                "name": "missing_auth",
                "expected": "INTEGRATION_AUTH_REQUIRED",
            },
            {
                "name": "rate_limit",
                "expected": "INTEGRATION_RATE_LIMITED",
            },
            {
                "name": "approval_rejected",
                "expected": "APPROVAL_REJECTED",
            },
            {
                "name": "connection_lost_after_dispatch",
                "expected": "unknown",
            },
        ],
    }


def test_copied_python_bundle_uses_its_owner_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kaji.integrations import load_manifest
    from kaji.integrations.copy import install_integration_bundle

    destination = tmp_path / "owner_integrations" / "github"
    install_integration_bundle(
        load_manifest("github"),
        destination,
        runtime="python",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    imported = (
        "owner_integrations",
        "owner_integrations.github",
        "owner_integrations.github.client",
        "owner_integrations.github.github",
    )
    try:
        module = importlib.import_module("owner_integrations.github.github")
        assert module.GitHubClient.__module__ == "owner_integrations.github.client"
        assert len(module.inspect_integration().tools()) == 6
    finally:
        for name in reversed(imported):
            sys.modules.pop(name, None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        (
            "github_create_issue",
            {"repository": "owner/repo", "title": "title", "body": "body"},
        ),
        (
            "github_add_comment",
            {"repository": "owner/repo", "issue_number": 1, "body": "body"},
        ),
    ],
)
async def test_mutation_approval_rejection_never_reads_token_or_runs_http(
    name: str, arguments: dict[str, object]
) -> None:
    from kaji.infra.events.journal import InMemoryEventJournal
    from kaji.infra.events.store import InMemoryEventStore
    from kaji.infra.events.types import EventType
    from kaji.integrations.registry.github.github import (
        _create_github_integration_for_test,
    )
    from kaji.runtime.agents.cancellation import CancellationToken
    from kaji.runtime.agents.context import TurnContext
    from kaji.runtime.agents.planner import JournalEventEmitter, ToolPlanner
    from kaji.runtime.tools.policies import ToolPolicy
    from kaji.runtime.tools.registry import ToolRegistry

    token_for = AsyncMock(side_effect=AssertionError("token must not be read"))
    http = type(
        "Http",
        (),
        {"request": AsyncMock(side_effect=AssertionError("HTTP must not run"))},
    )()
    integration = _create_github_integration_for_test(
        token_for=token_for,
        repositories={"owner/repo"},
        http=cast(Any, http),
    )
    registry = ToolRegistry()
    integration.register(registry)
    specs = {spec.name: spec for spec in registry.list_specs()}
    journal = InMemoryEventJournal(InMemoryEventStore())
    events: list[object] = []

    async def observe(event: object) -> None:
        events.append(event)

    async def execute(invocation: object) -> dict[str, object]:
        return await registry.execute(cast(Any, invocation))

    planner = ToolPlanner(
        execute,
        policy=ToolPolicy(require_approval_for={"external_effect"}),
        approval_handler=StaticApprovalHandler(
            ApprovalDecision(False, "rejected", "Rejected by test")
        ),
        specs=specs,
    )
    result = await planner.execute_batch(
        "session",
        [{"id": "call", "name": name, "arguments": arguments}],
        JournalEventEmitter(journal, before_commit=observe),
        turn_id="turn",
        turn_context=TurnContext(principal_id="principal"),
        cancellation_token=CancellationToken(),
        approval_journal=journal,
    )

    assert result[0]["error_code"] == "APPROVAL_REJECTED"
    assert EventType.TOOL_CALL_STARTED not in [
        getattr(event, "type") for event in events
    ]
    token_for.assert_not_awaited()
    http.request.assert_not_awaited()
