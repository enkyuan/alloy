"""Copied no-network owner fixtures for the GitHub bundle."""

from __future__ import annotations

import json
from pathlib import Path


_CLOSED_OUTCOMES = frozenset(
    {
        "success",
        "missing_auth",
        "rate_limit",
        "approval_rejected",
        "connection_lost_after_dispatch",
    }
)


def scripted_outcome(name: str) -> str:
    if name not in _CLOSED_OUTCOMES:
        raise ValueError("unknown scripted GitHub outcome")
    fixture = json.loads(
        (Path(__file__).parents[1] / "owner-fixtures.json").read_text()
    )
    rows = {row["name"]: row["expected"] for row in fixture["outcomes"]}
    return rows[name]


def test_github_owner_fixture_contract() -> None:
    assert {name: scripted_outcome(name) for name in _CLOSED_OUTCOMES} == {
        "success": "success",
        "missing_auth": "INTEGRATION_AUTH_REQUIRED",
        "rate_limit": "INTEGRATION_RATE_LIMITED",
        "approval_rejected": "APPROVAL_REJECTED",
        "connection_lost_after_dispatch": "unknown",
    }
