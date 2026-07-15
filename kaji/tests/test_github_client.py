from __future__ import annotations

import asyncio
from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any, cast

import pytest

from kaji.infra.events.errors import DurableJsonLimitError
from kaji.infra.events.json import canonical_json, durable_json_snapshot
from kaji.infra.events.schemas import MAX_DURABLE_TOOL_RESULT_BYTES
from kaji.integrations.errors import (
    IntegrationAuthRequiredError,
    IntegrationPolicyError,
    IntegrationTransportError,
)
from kaji.integrations.fixed_origin import IntegrationResponse
from kaji.contracts.integration_recovery import recovery_for_reason
from kaji.integrations.registry.github.client import GitHubClient
from kaji.runtime.agents.cancellation import CancellationToken, CancelledError
from kaji.runtime.context import ToolExecutionContext
from kaji.runtime.tools.execution import ToolExecutionError


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = cast(
    dict[str, Any],
    json.loads(
        (
            ROOT
            / "kaji"
            / "contracts"
            / "integrations"
            / "github-api-conformance-v1.json"
        ).read_text()
    ),
)
CASES = cast(list[dict[str, Any]], FIXTURE["cases"])
REPOSITORY = cast(str, FIXTURE["repository"])
TOKEN = cast(str, FIXTURE["token"])


def context(*, token: CancellationToken | None = None) -> ToolExecutionContext:
    return ToolExecutionContext(
        principal_id="tester",
        session_id="session",
        turn_id="turn",
        request_id="request",
        trace_id="trace",
        tool_call_id="call",
        idempotency_key="session:call",
        cancellation_token=token or CancellationToken(),
        deadline_monotonic=None,
        db=None,
        metadata={},
    )


class ScriptedHttp:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.contexts: list[ToolExecutionContext] = []

    async def request(
        self,
        path_and_query: str,
        *,
        method: str,
        headers: Mapping[str, str],
        body: bytes | None,
        context: ToolExecutionContext,
    ) -> IntegrationResponse:
        self.requests.append(
            {
                "method": method,
                "path_and_query": path_and_query,
                "headers": dict(headers),
                "body": None if body is None else body.decode("utf-8"),
            }
        )
        self.contexts.append(context)
        response = self.responses.pop(0)
        transport_error = response.get("transport_error")
        if transport_error == "response_limit":
            raise IntegrationTransportError(
                "INTEGRATION_RESPONSE_LIMIT", "response_limit_exceeded"
            )
        if transport_error == "cancelled":
            raise CancelledError("private cancellation detail")
        if transport_error == "connection":
            raise OSError("private connection detail")
        if "json" in response:
            payload = json.dumps(
                response["json"], ensure_ascii=False, separators=(",", ":")
            ).encode()
        else:
            payload = response.get("body", "").encode()
        return IntegrationResponse(
            status=response["status"],
            headers=response.get("headers", {}),
            body=payload,
        )


async def invoke(
    client: GitHubClient,
    execution_context: ToolExecutionContext,
    operation: str,
    values: dict[str, Any],
) -> object:
    if operation == "search_code":
        return await client.search_code(
            execution_context, repository=REPOSITORY, **values
        )
    if operation == "get_file":
        return await client.get_file(execution_context, repository=REPOSITORY, **values)
    if operation == "list_issues":
        return await client.list_issues(
            execution_context, repository=REPOSITORY, **values
        )
    if operation == "get_issue":
        return await client.get_issue(
            execution_context, repository=REPOSITORY, **values
        )
    if operation == "create_issue":
        return await client.create_issue(
            execution_context, repository=REPOSITORY, **values
        )
    if operation == "add_comment":
        return await client.add_comment(
            execution_context, repository=REPOSITORY, **values
        )
    raise AssertionError(f"unknown fixture operation: {operation}")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
async def test_shared_github_conformance(case: dict[str, Any]) -> None:
    http = ScriptedHttp(case["responses"])
    token_contexts: list[ToolExecutionContext] = []
    sleeps: list[float] = []

    async def token_for(execution_context: ToolExecutionContext) -> str:
        token_contexts.append(execution_context)
        return TOKEN

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    client = GitHubClient(
        token_for=token_for,
        repositories=[REPOSITORY],
        http=http,
        _sleep=sleep,
        _monotonic=lambda: 0.0,
    )
    execution_context = context()

    try:
        result = await invoke(
            client, execution_context, case["operation"], case["input"]
        )
        actual: dict[str, object] = {"result": result}
    except ToolExecutionError as error:
        actual = {
            "error": {
                "code": error.error_code,
                "outcome": error.outcome,
                "retryable": error.retryable,
            }
        }
    except asyncio.CancelledError:
        actual = {"exception": "cancelled"}
    except Exception as error:
        assert "private" not in str(error).lower()
        if case["expected"] == {"exception": "unknown"}:
            recovery = recovery_for_reason("github_mutation_unknown")
            assert isinstance(error, IntegrationTransportError)
            assert error.error_code == recovery.error_code
            assert error.reason_code == "github_mutation_unknown"
            assert error.recovery_code == recovery.recovery_code
            assert error.doc_url == recovery.doc_url
        actual = {"exception": "unknown"}

    assert actual == case["expected"]
    assert http.requests == case["expected_requests"]
    assert sleeps == case.get("expected_sleeps", [])
    assert len(token_contexts) == case.get("expected_token_calls", 1)
    assert all(seen is execution_context for seen in token_contexts)
    assert all(seen is execution_context for seen in http.contexts)
    assert http.responses == []


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["", "   ", "a\r\nb", "x" * 4097, 7])
async def test_rejects_invalid_tokens_before_http(value: object) -> None:
    http = ScriptedHttp([])

    async def token_for(_context: ToolExecutionContext) -> str:
        return cast(str, value)

    client = GitHubClient(
        token_for=token_for,
        repositories=[REPOSITORY],
        http=http,
    )
    with pytest.raises(IntegrationAuthRequiredError):
        await client.get_issue(context(), repository=REPOSITORY, issue_number=1)
    assert http.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["", ".", "..", "src//secret", "src/../secret"])
async def test_rejects_content_path_before_token_or_http(path: str) -> None:
    token_calls = 0
    http = ScriptedHttp([])

    async def token_for(_context: ToolExecutionContext) -> str:
        nonlocal token_calls
        token_calls += 1
        return TOKEN

    client = GitHubClient(
        token_for=token_for,
        repositories=[REPOSITORY],
        http=http,
    )
    with pytest.raises(IntegrationPolicyError):
        await client.get_file(context(), repository=REPOSITORY, path=path)
    assert token_calls == 0
    assert http.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["../secret", "%2E%2E/secret", "src/%2Fsecret"])
async def test_request_core_cannot_bypass_content_path_policy(path: str) -> None:
    token_calls = 0
    http = ScriptedHttp([])

    async def token_for(_context: ToolExecutionContext) -> str:
        nonlocal token_calls
        token_calls += 1
        return TOKEN

    client = GitHubClient(
        token_for=token_for,
        repositories=[REPOSITORY],
        http=http,
    )
    with pytest.raises(IntegrationPolicyError):
        await client.request_json(
            context(),
            method="GET",
            repository=REPOSITORY,
            path=f"/repos/{REPOSITORY}/contents/{path}",
        )
    assert token_calls == 0
    assert http.requests == []


@pytest.mark.asyncio
async def test_repository_allowlist_is_validated_and_snapshotted() -> None:
    repositories = [REPOSITORY]
    http = ScriptedHttp([])

    async def token_for(_context: ToolExecutionContext) -> str:
        return TOKEN

    client = GitHubClient(
        token_for=token_for,
        repositories=repositories,
        http=http,
    )
    repositories.append("other/private")
    with pytest.raises(IntegrationPolicyError):
        await client.get_issue(context(), repository="other/private", issue_number=1)
    assert http.requests == []

    with pytest.raises(IntegrationPolicyError):
        GitHubClient(
            token_for=token_for,
            repositories=["invalid"],
            http=http,
        )


@pytest.mark.asyncio
async def test_search_validates_every_repository_before_row_cap() -> None:
    items = [
        {
            "path": f"src/{index}.py",
            "sha": str(index),
            "repository": {"full_name": REPOSITORY},
            "text_matches": [],
        }
        for index in range(20)
    ]
    items.append(
        {
            "path": "private.txt",
            "sha": "bad",
            "repository": {"full_name": "other/private"},
            "text_matches": [],
        }
    )
    http = ScriptedHttp(
        [{"status": 200, "headers": {}, "json": {"total_count": 21, "items": items}}]
    )
    client = GitHubClient(
        token_for=lambda _context: asyncio.sleep(0, result=TOKEN),
        repositories=[REPOSITORY],
        http=http,
    )
    with pytest.raises(ToolExecutionError):
        await client.search_code(context(), repository=REPOSITORY, query="needle")


@pytest.mark.asyncio
@pytest.mark.parametrize(("field", "maximum"), [("path", 512), ("title", 256)])
async def test_provider_identifiers_use_unicode_character_limits(
    field: str, maximum: int
) -> None:
    async def call(value: str) -> Mapping[str, object]:
        if field == "path":
            response: object = {
                "total_count": 1,
                "items": [
                    {
                        "path": value,
                        "sha": "abc123",
                        "repository": {"full_name": REPOSITORY},
                        "text_matches": [],
                    }
                ],
            }
        else:
            response = {
                "number": 1,
                "state": "open",
                "title": value,
                "body": "",
                "html_url": "https://github.com/octo/widgets/issues/1",
            }
        client = GitHubClient(
            token_for=lambda _context: asyncio.sleep(0, result=TOKEN),
            repositories=[REPOSITORY],
            http=ScriptedHttp([{"status": 200, "headers": {}, "json": response}]),
        )
        if field == "path":
            return await client.search_code(
                context(), repository=REPOSITORY, query="needle"
            )
        return await client.get_issue(context(), repository=REPOSITORY, issue_number=1)

    valid = "é" * maximum
    result = await call(valid)
    if field == "path":
        items = result["items"]
        assert isinstance(items, list)
        first = items[0]
        assert isinstance(first, Mapping)
        first_row = cast(Mapping[str, object], first)
        assert first_row["path"] == valid
    else:
        assert result["title"] == valid
    with pytest.raises(ToolExecutionError):
        await call("é" * (maximum + 1))


@pytest.mark.asyncio
async def test_fragment_preview_uses_utf8_byte_limit() -> None:
    fragment = "é" * 513
    response = {
        "total_count": 1,
        "items": [
            {
                "path": "src/lib.py",
                "sha": "abc123",
                "repository": {"full_name": REPOSITORY},
                "text_matches": [{"fragment": fragment}],
            }
        ],
    }
    client = GitHubClient(
        token_for=lambda _context: asyncio.sleep(0, result=TOKEN),
        repositories=[REPOSITORY],
        http=ScriptedHttp([{"status": 200, "headers": {}, "json": response}]),
    )
    result = await client.search_code(context(), repository=REPOSITORY, query="needle")
    items = result["items"]
    assert isinstance(items, list)
    first = items[0]
    assert isinstance(first, Mapping)
    first_row = cast(Mapping[str, object], first)
    preview = first_row["fragment"]
    assert isinstance(preview, str)
    assert preview == "é" * 512
    assert len(preview.encode()) == 1_024


@pytest.mark.asyncio
async def test_issue_body_uses_utf8_byte_limit() -> None:
    async def call(body: str) -> Mapping[str, object]:
        response = {
            "number": 1,
            "state": "open",
            "title": "Title",
            "body": body,
            "html_url": "https://github.com/octo/widgets/issues/1",
        }
        client = GitHubClient(
            token_for=lambda _context: asyncio.sleep(0, result=TOKEN),
            repositories=[REPOSITORY],
            http=ScriptedHttp([{"status": 200, "headers": {}, "json": response}]),
        )
        return await client.get_issue(context(), repository=REPOSITORY, issue_number=1)

    assert (await call("é" * 8_192))["body"] == "é" * 8_192
    with pytest.raises(ToolExecutionError):
        await call("é" * 8_193)


@pytest.mark.parametrize(
    "boundary", FIXTURE["durable_result_boundaries"], ids=lambda row: row["name"]
)
def test_exact_durable_result_boundary(boundary: dict[str, Any]) -> None:
    empty_size = len(canonical_json({"padding": ""}).encode())
    value = {"padding": "x" * (boundary["serialized_bytes"] - empty_size)}
    assert len(canonical_json(value).encode()) == boundary["serialized_bytes"]
    if boundary["accepted"]:
        assert (
            durable_json_snapshot(
                value,
                subject="tool_result",
                max_bytes=MAX_DURABLE_TOOL_RESULT_BYTES,
            )
            == value
        )
    else:
        with pytest.raises(DurableJsonLimitError):
            durable_json_snapshot(
                value,
                subject="tool_result",
                max_bytes=MAX_DURABLE_TOOL_RESULT_BYTES,
            )
