"""Surfacing tool-arg JSON parse failures in Anthropic streaming.

Raw model output may carry user PII; it goes only to the privileged log sink,
NOT into the event payload (which is persisted, replayed, and surfaced to UI).
The payload signals the failure via ``__parse_error`` so the planner can fail
the call closed.
"""

from __future__ import annotations

import logging

from kaji.runtime.providers.anthropic import AnthropicProvider


def test_parse_tool_args_logs_raw_and_surfaces_parse_error_in_payload(caplog):
    caplog.set_level(logging.WARNING, logger="kaji.runtime.providers.anthropic")

    args = AnthropicProvider._parse_tool_args(
        raw="{not json", name="lookup", tool_id="toolu_1"
    )

    # Payload signals the failure but does NOT carry the raw model output.
    assert "__parse_error" in args
    assert isinstance(args["__parse_error"], str)
    assert "__raw" not in args

    # Raw input is logged at WARNING. Privileged sink only.
    log_text = " ".join(rec.message for rec in caplog.records)
    assert "failed to parse" in log_text.lower()
    assert "{not json" in log_text
    assert "lookup" in log_text


def test_parse_tool_args_truncates_oversize_raw_in_log(caplog):
    caplog.set_level(logging.WARNING, logger="kaji.runtime.providers.anthropic")

    payload = "{" + ("a" * 1024)
    args = AnthropicProvider._parse_tool_args(
        raw=payload, name="lookup", tool_id="toolu_big"
    )

    assert "__parse_error" in args
    log_text = " ".join(rec.message for rec in caplog.records)
    assert "..." in log_text
    assert payload not in log_text


def test_parse_tool_args_passes_through_valid_json():
    args = AnthropicProvider._parse_tool_args(
        raw='{"city": "NYC"}', name="lookup", tool_id="toolu_2"
    )
    assert args == {"city": "NYC"}


def test_parse_tool_args_treats_empty_string_as_empty_object():
    args = AnthropicProvider._parse_tool_args(raw="", name="ping", tool_id="toolu_3")
    assert args == {}
