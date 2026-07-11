"""Surfacing tool-arg JSON parse failures in OpenAI streaming.

Raw model output may carry user PII; it goes neither to logs nor into the event
payload (which is persisted, replayed, and surfaced to UI).
The payload signals the failure via ``__parse_error`` so the planner can fail
the call closed.
"""

from __future__ import annotations

import logging

from kaji.runtime.providers.openai import OpenAIProvider


def test_finalize_redacts_raw_and_surfaces_parse_error_in_payload(caplog):
    caplog.set_level(logging.WARNING, logger="kaji.runtime.providers.openai")

    pending = {
        0: {"id": "call_1", "name": "lookup", "arguments": "{not json"},
    }
    calls = OpenAIProvider._finalize_stream_tool_calls(pending)

    assert len(calls) == 1
    assert calls[0]["name"] == "lookup"
    assert calls[0]["id"] == "call_1"
    # Payload signals the failure but does NOT carry the raw model output.
    assert "__parse_error" in calls[0]["arguments"]
    assert isinstance(calls[0]["arguments"]["__parse_error"], str)
    assert "__raw" not in calls[0]["arguments"]

    log_text = " ".join(rec.message for rec in caplog.records)
    assert "failed to parse" in log_text.lower()
    assert "arguments redacted" in log_text
    assert "{not json" not in log_text
    assert "lookup" in log_text


def test_finalize_reports_size_without_logging_oversize_raw(caplog):
    caplog.set_level(logging.WARNING, logger="kaji.runtime.providers.openai")

    # 1KB of malformed JSON; the log should carry only its size.
    payload = "{" + ("a" * 1024)
    pending = {0: {"id": "call_big", "name": "lookup", "arguments": payload}}
    calls = OpenAIProvider._finalize_stream_tool_calls(pending)

    assert "__parse_error" in calls[0]["arguments"]
    log_text = " ".join(rec.message for rec in caplog.records)
    assert "arguments redacted" in log_text
    assert "1025 characters" in log_text
    assert payload not in log_text


def test_finalize_passes_through_valid_json():
    pending = {
        0: {"id": "call_2", "name": "lookup", "arguments": '{"city": "NYC"}'},
    }
    calls = OpenAIProvider._finalize_stream_tool_calls(pending)
    assert calls[0]["arguments"] == {"city": "NYC"}


def test_finalize_treats_empty_arguments_as_empty_object():
    pending = {
        0: {"id": "call_3", "name": "ping", "arguments": ""},
    }
    calls = OpenAIProvider._finalize_stream_tool_calls(pending)
    assert calls[0]["arguments"] == {}


def test_finalize_skips_entries_without_a_name():
    pending = {
        0: {"id": "", "name": "", "arguments": '{"foo": 1}'},
        1: {"id": "call_4", "name": "real", "arguments": "{}"},
    }
    calls = OpenAIProvider._finalize_stream_tool_calls(pending)
    assert [c["name"] for c in calls] == ["real"]


def test_finalize_preserves_order_by_index():
    pending = {
        2: {"id": "c", "name": "third", "arguments": "{}"},
        0: {"id": "a", "name": "first", "arguments": "{}"},
        1: {"id": "b", "name": "second", "arguments": "{}"},
    }
    calls = OpenAIProvider._finalize_stream_tool_calls(pending)
    assert [c["name"] for c in calls] == ["first", "second", "third"]
