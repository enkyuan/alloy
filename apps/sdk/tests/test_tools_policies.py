import pytest

from agentkit.tools.idempotency import ToolIdempotencyGuard, build_tool_idempotency_key
from agentkit.tools.policies import ToolPolicy, ToolPolicyViolation


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
