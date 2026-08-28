"""Tests for MockProvider's reply / tool_call options."""

from __future__ import annotations

import pytest

from kaji.runtime.providers.mock import MockProvider


@pytest.mark.asyncio
async def test_mock_reply_returns_literal_text():
    p = MockProvider(reply="hello world")
    r = await p.generate([{"role": "user", "content": "hi"}])
    assert r.text == "hello world"
    assert r.tool_calls == []


@pytest.mark.asyncio
async def test_mock_tool_call_returns_named_call():
    p = MockProvider(tool_call={"name": "ping", "args": {"x": 1}})
    r = await p.generate([{"role": "user", "content": "hi"}])
    assert r.text == ""
    assert len(r.tool_calls) == 1
    assert r.tool_calls[0]["name"] == "ping"
    assert r.tool_calls[0]["arguments"] == {"x": 1}


@pytest.mark.asyncio
async def test_mock_tool_call_falls_through_to_terminal_text():
    p = MockProvider(tool_call={"name": "ping", "args": {}})
    r = await p.generate(
        [
            {"role": "user", "content": "hi"},
            {"role": "tool", "content": "{}", "name": "ping"},
        ]
    )
    assert r.text == "mock response"
    assert r.tool_calls == []


def test_mock_reply_and_tool_call_mutually_exclusive():
    with pytest.raises(ValueError):
        MockProvider(reply="x", tool_call={"name": "y", "args": {}})


@pytest.mark.asyncio
async def test_mock_default_behavior_unchanged():
    p = MockProvider()
    r = await p.generate([{"role": "user", "content": "hi"}], tools=None)
    assert r.text == "mock response"
    assert r.tool_calls == []


@pytest.mark.asyncio
async def test_mock_reply_stream_yields_single_chunk():
    p = MockProvider(reply="hello world")
    chunks = []
    async for c in p.generate_stream([{"role": "user", "content": "hi"}]):
        chunks.append(c)
    assert len(chunks) == 1
    assert chunks[0].delta == "hello world"
    assert chunks[0].tool_calls == []


@pytest.mark.asyncio
async def test_mock_tool_call_stream_yields_call_then_returns():
    p = MockProvider(tool_call={"name": "ping", "args": {"x": 1}})
    chunks = []
    async for c in p.generate_stream([{"role": "user", "content": "hi"}]):
        chunks.append(c)
    assert len(chunks) == 1
    assert chunks[0].delta == ""
    assert chunks[0].tool_calls[0]["name"] == "ping"
