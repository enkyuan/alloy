import pytest

from agentkit.runtime.tools.idempotency import (
    ToolIdempotencyGuard,
    build_tool_idempotency_key,
)
from agentkit.runtime.tools.policies import ToolPolicy, ToolPolicyViolation


def test_tool_policy_allowlist():
    policy = ToolPolicy(allowed={"search", "calendar"})
    assert policy.is_allowed("search") is True
    assert policy.is_allowed("delete") is False


def test_tool_policy_denylist_wins_over_allowlist():
    policy = ToolPolicy(allowed={"search"}, denied={"search"})
    assert policy.is_allowed("search") is False


def test_tool_policy_enforce_raises():
    policy = ToolPolicy(allowed={"search"})
    with pytest.raises(ToolPolicyViolation, match="not permitted"):
        policy.enforce("delete")


def test_tool_idempotency_guard_skips_duplicates():
    guard = ToolIdempotencyGuard()
    args = {"q": "hello"}
    assert guard.should_execute(session_id="s1", tool_name="search", tool_args=args)
    assert not guard.should_execute(session_id="s1", tool_name="search", tool_args=args)


def test_build_tool_idempotency_key_includes_session():
    key_a = build_tool_idempotency_key(
        session_id="s1", tool_name="search", tool_args={"q": "x"}
    )
    key_b = build_tool_idempotency_key(
        session_id="s2", tool_name="search", tool_args={"q": "x"}
    )
    assert key_a != key_b


# --- ToolPolicy risk-driven approval tests ---


def test_requires_approval_when_risk_in_set():
    policy = ToolPolicy(require_approval_for={"destructive", "admin"})
    assert policy.requires_approval("delete_all", "destructive") is True
    assert policy.requires_approval("manage_users", "admin") is True


def test_no_approval_required_for_lower_risk():
    policy = ToolPolicy(require_approval_for={"destructive", "admin"})
    assert policy.requires_approval("search", "read") is False
    assert policy.requires_approval("write_doc", "write") is False


def test_unclassified_risk_treated_as_read():
    policy = ToolPolicy(require_approval_for={"destructive"})
    # None risk → treated as "read" → not in approval set
    assert policy.requires_approval("search", None) is False


def test_requires_approval_false_when_no_set_configured():
    policy = ToolPolicy()
    assert policy.requires_approval("delete_all", "destructive") is False


def test_existing_allow_deny_still_work_with_risk_fields():
    policy = ToolPolicy(
        allowed={"search"}, denied={"delete"}, require_approval_for={"financial"}
    )
    assert policy.is_allowed("search") is True
    assert policy.is_allowed("delete") is False
    assert policy.requires_approval("charge", "financial") is True
