from __future__ import annotations

import base64
from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any, cast

import pytest

from kaji.contracts.integration_recovery import recovery_for_reason
from kaji.integrations.errors import (
    IntegrationAuthRequiredError,
    IntegrationExecutionError,
    IntegrationPolicyError,
    IntegrationRateLimitedError,
    IntegrationTransientReadError,
    IntegrationTransportError,
)
from kaji.integrations.fixed_origin import IntegrationResponse
from kaji.integrations.registry.gmail.client import GmailClient
from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.context import ToolExecutionContext


def context() -> ToolExecutionContext:
    return ToolExecutionContext(
        principal_id="tester",
        session_id="session",
        turn_id="turn",
        request_id="request",
        trace_id="trace",
        tool_call_id="call",
        idempotency_key="session:call",
        cancellation_token=CancellationToken(),
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
        if response.get("transport_error") == "connection":
            raise OSError("private connection detail")
        if "body" in response:
            payload = response["body"].encode()
        else:
            payload = json.dumps(response["json"], separators=(",", ":")).encode()
        return IntegrationResponse(
            status=response["status"], headers=response.get("headers", {}), body=payload
        )


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _client(responses: list[dict[str, Any]]) -> tuple[GmailClient, ScriptedHttp]:
    http = ScriptedHttp(responses)

    async def token_for(_context: ToolExecutionContext) -> str:
        return "ya29.token"

    return GmailClient(token_for=token_for, http=http), http


@pytest.mark.asyncio
async def test_list_messages_normalizes_and_bounds() -> None:
    client, http = _client(
        [
            {
                "status": 200,
                "json": {
                    "messages": [
                        {"id": "abc123", "threadId": "thread1"},
                        {"id": "def456", "threadId": "thread2"},
                    ],
                    "resultSizeEstimate": 2,
                    "nextPageToken": "CURSOR_2",
                },
            }
        ]
    )
    result = await client.list_messages(context(), query="from:alice", max_results=5)
    assert result == {
        "messages": [
            {"id": "abc123", "thread_id": "thread1"},
            {"id": "def456", "thread_id": "thread2"},
        ],
        "result_size_estimate": 2,
        "next_page_token": "CURSOR_2",
    }
    # Query is sorted and url-encoded; both params present.
    assert http.requests[0]["path_and_query"] == (
        "/gmail/v1/users/me/messages?maxResults=5&q=from%3Aalice"
    )
    assert http.requests[0]["headers"]["authorization"] == "Bearer ya29.token"


@pytest.mark.asyncio
async def test_list_messages_pages_with_token() -> None:
    client, http = _client(
        [
            {
                "status": 200,
                "json": {
                    "messages": [{"id": "m1", "threadId": "t1"}],
                    "nextPageToken": "NEXT_PAGE_42",
                    "resultSizeEstimate": 50,
                },
            }
        ]
    )
    result = await client.list_messages(
        context(), max_results=1, page_token="PREV_CURSOR"
    )
    assert result == {
        "messages": [{"id": "m1", "thread_id": "t1"}],
        "result_size_estimate": 50,
        "next_page_token": "NEXT_PAGE_42",
    }
    assert http.requests[0]["path_and_query"] == (
        "/gmail/v1/users/me/messages?maxResults=1&pageToken=PREV_CURSOR"
    )


@pytest.mark.asyncio
async def test_list_messages_rejects_overlong_page_token() -> None:
    client, http = _client([])
    with pytest.raises(IntegrationPolicyError):
        await client.list_messages(context(), page_token="x" * 2049)
    assert http.requests == []


@pytest.mark.asyncio
async def test_get_message_decodes_text_plain_body() -> None:
    client, _ = _client(
        [
            {
                "status": 200,
                "json": {
                    "id": "abc123",
                    "threadId": "thread1",
                    "snippet": "hello there",
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "alice@example.com"},
                            {"name": "Subject", "value": "Hi"},
                            {"name": "X-Noise", "value": "dropped"},
                        ],
                        "mimeType": "multipart/alternative",
                        "parts": [
                            {
                                "mimeType": "text/html",
                                "body": {"data": _b64url("<p>ignored</p>")},
                            },
                            {
                                "mimeType": "text/plain",
                                "body": {"data": _b64url("plain body")},
                            },
                        ],
                    },
                },
            }
        ]
    )
    result = await client.get_message(context(), message_id="abc123")
    assert result == {
        "id": "abc123",
        "thread_id": "thread1",
        "snippet": "hello there",
        "headers": {"from": "alice@example.com", "subject": "Hi"},
        "body": "plain body",
        "body_truncated": False,
    }


@pytest.mark.asyncio
async def test_get_message_truncates_oversize_body() -> None:
    # > MAX_BODY_BYTES (48 KiB) must be capped, with body_truncated True.
    big = _b64url("x" * (50 * 1024))
    client, _ = _client(
        [
            {
                "status": 200,
                "json": {
                    "id": "bigbody0",
                    "threadId": "bigbody0",
                    "payload": {"mimeType": "text/plain", "body": {"data": big}},
                },
            }
        ]
    )
    result = await client.get_message(context(), message_id="bigbody0")
    assert result["body_truncated"] is True
    assert len(cast(str, result["body"]).encode("utf-8")) == 48 * 1024


@pytest.mark.asyncio
async def test_send_message_returns_ids_and_sends_raw() -> None:
    raw = _b64url("From: me@example.com\r\nTo: you@example.com\r\n\r\nHi")
    client, http = _client(
        [{"status": 200, "json": {"id": "sent1", "threadId": "thread9"}}]
    )
    result = await client.send_message(context(), raw=raw)
    assert result == {"id": "sent1", "thread_id": "thread9"}
    sent = http.requests[0]
    assert sent["method"] == "POST"
    assert sent["path_and_query"] == "/gmail/v1/users/me/messages/send"
    assert json.loads(sent["body"]) == {"raw": raw}


@pytest.mark.asyncio
async def test_send_message_transport_failure_is_unknown_mutation() -> None:
    raw = _b64url("From: me@example.com\r\n\r\nHi")
    client, _ = _client([{"transport_error": "connection"}])
    with pytest.raises(IntegrationTransportError) as excinfo:
        await client.send_message(context(), raw=raw)
    # Mutation whose outcome we can't confirm must surface the contracted reason.
    assert excinfo.value.reason_code == "gmail_mutation_unknown"


@pytest.mark.asyncio
async def test_send_message_5xx_is_unknown_mutation() -> None:
    raw = _b64url("From: me@example.com\r\n\r\nHi")
    client, _ = _client([{"status": 500, "json": {}}])
    with pytest.raises(IntegrationTransportError) as excinfo:
        await client.send_message(context(), raw=raw)
    assert excinfo.value.reason_code == "gmail_mutation_unknown"


@pytest.mark.asyncio
async def test_invalid_message_id_is_policy_rejected() -> None:
    client, _ = _client([])
    with pytest.raises(IntegrationPolicyError):
        await client.get_message(context(), message_id="not/a/valid/id")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        "!!! not base64 !!!",  # spaces + punctuation
        "!!!invalid!!!",  # non-alphabet punctuation, valid length
        "YWJj YWJj",  # embedded space
    ],
)
async def test_non_base64url_raw_is_policy_rejected(raw: str) -> None:
    # Strict alphabet check: urlsafe_b64decode would silently drop these.
    client, _ = _client([])
    with pytest.raises(IntegrationPolicyError):
        await client.send_message(context(), raw=raw)


@pytest.mark.asyncio
async def test_401_surfaces_auth_required() -> None:
    client, _ = _client([{"status": 401, "json": {}}])
    with pytest.raises(IntegrationAuthRequiredError) as excinfo:
        await client.list_messages(context())
    assert excinfo.value.reason_code == "gmail_grant_missing"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token",
    ["", "   ", "a\r\nb", "x" * 4097, "\udc00", "\ud800a", 7],
)
async def test_invalid_tokens_rejected_before_http(token: object) -> None:
    # Header-injection, empty/whitespace, overlong, lone-surrogate, and
    # non-string tokens must fail as auth-required before any HTTP call.
    http = ScriptedHttp([])

    async def token_for(_context: ToolExecutionContext) -> str:
        return cast(str, token)

    client = GmailClient(token_for=token_for, http=http)
    with pytest.raises(IntegrationAuthRequiredError):
        await client.list_messages(context())
    assert http.requests == []


_FIXTURE = json.loads(
    (
        Path(__file__).resolve().parents[3]
        / "contracts"
        / "integrations"
        / "gmail-api-conformance-v1.json"
    ).read_text()
)
_CASES = cast(list[dict[str, Any]], _FIXTURE["cases"])
_TOKEN = cast(str, _FIXTURE["token"])


async def _invoke(
    client: GmailClient,
    execution_context: ToolExecutionContext,
    operation: str,
    values: dict[str, Any],
) -> object:
    if operation == "list_messages":
        kwargs: dict[str, Any] = {}
        if values.get("query") is not None:
            kwargs["query"] = values["query"]
        if values.get("maxResults") is not None:
            kwargs["max_results"] = values["maxResults"]
        if values.get("pageToken") is not None:
            kwargs["page_token"] = values["pageToken"]
        return await client.list_messages(execution_context, **kwargs)
    if operation == "get_message":
        return await client.get_message(
            execution_context, message_id=values["messageId"]
        )
    if operation == "send_message":
        return await client.send_message(execution_context, raw=values["raw"])
    raise AssertionError(f"unknown fixture operation: {operation}")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", _CASES, ids=[case["name"] for case in _CASES])
async def test_shared_gmail_conformance(case: dict[str, Any]) -> None:
    """The same fixture drives kaji/packages/typescript/tests/gmail-client.test.ts; both SDKs
    must normalize identically. This is the cross-language parity gate that
    keeps the Python and TypeScript Gmail clients behaviorally in sync."""
    http = ScriptedHttp(case["responses"])
    token_contexts: list[ToolExecutionContext] = []
    sleeps: list[float] = []

    async def token_for(execution_context: ToolExecutionContext) -> str:
        token_contexts.append(execution_context)
        return _TOKEN

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    client = GmailClient(
        token_for=token_for, http=http, _sleep=sleep, _monotonic=lambda: 0.0
    )
    execution_context = context()

    try:
        result = await _invoke(
            client, execution_context, case["operation"], case["input"]
        )
        actual: dict[str, object] = {"result": result}
    except IntegrationTransportError as error:
        assert "private" not in str(error).lower()
        recovery = recovery_for_reason("gmail_mutation_unknown")
        assert error.error_code == recovery.error_code
        assert error.reason_code == "gmail_mutation_unknown"
        assert error.recovery_code == recovery.recovery_code
        assert error.doc_url == recovery.doc_url
        actual = {"exception": "unknown"}
    except IntegrationRateLimitedError as error:
        actual = {
            "error": {
                "code": error.error_code,
                "outcome": error.outcome,
                "retryable": error.retryable,
            }
        }
    except (IntegrationTransientReadError, IntegrationExecutionError) as error:
        assert "private" not in str(error).lower()
        actual = {
            "error": {
                "code": error.error_code,
                "outcome": error.outcome,
                "retryable": error.retryable,
            }
        }

    assert actual == case["expected"]
    seen_requests = [
        {
            "method": r["method"],
            "path_and_query": r["path_and_query"],
            "body": r["body"],
        }
        for r in http.requests
    ]
    assert seen_requests == case["expected_requests"]
    # Python sleeps in seconds; the fixture records milliseconds (TS units).
    assert [s * 1000 for s in sleeps] == case.get("expected_sleeps", [])
    assert http.responses == []
