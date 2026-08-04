from __future__ import annotations

import base64
from collections.abc import Mapping
import json
from typing import Any

import pytest

from kaji.integrations.errors import (
    IntegrationAuthRequiredError,
    IntegrationPolicyError,
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
        response = self.responses.pop(0)
        if response.get("transport_error") == "connection":
            raise OSError("private connection detail")
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
                    "nextPageToken": "should-be-dropped",
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
    }
    # Query is sorted and url-encoded; both params present.
    assert http.requests[0]["path_and_query"] == (
        "/gmail/v1/users/me/messages?maxResults=5&q=from%3Aalice"
    )
    assert http.requests[0]["headers"]["authorization"] == "Bearer ya29.token"


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
