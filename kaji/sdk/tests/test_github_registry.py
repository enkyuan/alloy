"""GitHub registry bundle metadata and wrapper behavior."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from kaji.runtime.context import ToolExecutionContext
from kaji.runtime.integrations.base import Integration
from kaji.runtime.tools.registry import list_tool_specs


ROOT = Path(__file__).resolve().parents[3]
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


def test_github_manifest_is_experimental_and_declares_the_owner_bundle() -> None:
    python = json.loads(
        (ROOT / "kaji/sdk/src/integrations/registry/github/manifest.json").read_text()
    )
    typescript = json.loads(
        (ROOT / "kaji/ts/registry/github/manifest.json").read_text()
    )
    python_index = json.loads(
        (ROOT / "kaji/sdk/src/integrations/registry/index.json").read_text()
    )
    typescript_index = json.loads((ROOT / "kaji/ts/registry/index.json").read_text())

    for index in (python_index, typescript_index):
        assert index["integrations"]["github"] == {
            "manifest": "github/manifest.json",
            "stability": "experimental",
            "runtimes": ["python", "typescript"],
        }
    assert python["tools"] == ABI["tools"]
    assert typescript["tools"] == ABI["tools"]
    assert python["files"] == [
        "github.py",
        "client.py",
        "github.ts",
        "client.ts",
        "github_pytest.py",
        "github_vitest.ts",
        "owner-fixtures.json",
        "LICENSE",
    ]
    assert typescript["files"] == [
        "index.ts",
        "client.ts",
        "github_vitest.ts",
        "owner-fixtures.json",
        "LICENSE",
    ]


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
        approval_handler=AsyncMock(return_value=False),
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
