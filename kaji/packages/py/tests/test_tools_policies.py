import pytest

from kaji.runtime.tools.errors import (
    ToolSchemaValidationError,
    UnclassifiedToolRiskError,
)
from kaji.runtime.tools.policies import ToolPolicy, ToolPolicyViolation


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


# --- ToolPolicy risk-driven approval tests ---


def test_requires_approval_when_risk_in_set():
    policy = ToolPolicy(require_approval_for={"destructive", "admin"})
    assert policy.requires_approval("delete_all", "destructive") is True
    assert policy.requires_approval("manage_users", "admin") is True


def test_no_approval_required_for_lower_risk():
    policy = ToolPolicy(require_approval_for={"destructive", "admin"})
    assert policy.requires_approval("external", "external_effect") is False
    assert policy.requires_approval("search", "read") is False
    assert policy.requires_approval("write_doc", "write") is False


def test_unclassified_risk_fails_closed():
    policy = ToolPolicy(require_approval_for={"destructive"})
    with pytest.raises(UnclassifiedToolRiskError):
        policy.requires_approval("search", None)


def test_requires_approval_false_when_no_set_configured():
    policy = ToolPolicy()
    assert policy.requires_approval("delete_all", "destructive") is False


def test_existing_allow_deny_still_work_with_risk_fields():
    policy = ToolPolicy(
        allowed={"search"}, denied={"delete"}, require_approval_for={"destructive"}
    )
    assert policy.is_allowed("search") is True
    assert policy.is_allowed("delete") is False
    assert policy.requires_approval("charge", "destructive") is True


def test_approval_risks_are_validated_and_snapshotted() -> None:
    configured = {"destructive"}
    policy = ToolPolicy(require_approval_for=configured)
    configured.clear()
    configured.add("read")

    assert policy.requires_approval("search", "read") is False
    assert policy.requires_approval("delete", "destructive") is True

    with pytest.raises(ToolSchemaValidationError) as raised:
        ToolPolicy(require_approval_for={"typo"})
    assert raised.value.code == "INVALID_TOOL_SCHEMA"
