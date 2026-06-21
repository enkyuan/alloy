"""Tool execution policies — allowlists, denylists, and risk-driven approval."""

from __future__ import annotations

from typing import Iterable, Optional


# Ordered from least to most sensitive. Used for threshold comparisons.
RISK_LEVELS = ("read", "write", "external_effect", "financial", "destructive", "admin")
_RISK_RANK: dict[str, int] = {r: i for i, r in enumerate(RISK_LEVELS)}


class ToolPolicy:
    """Decides whether a tool may run and whether it needs human approval.

    Allow/deny lists work the same as before. The new ``require_approval_for``
    parameter accepts a set of risk-level strings; any tool whose ``ToolSpec.risk``
    is in that set (or whose risk rank >= the minimum rank in the set) will
    return ``True`` from ``requires_approval``.

    Example — approve anything destructive or higher::

        ToolPolicy(require_approval_for={"destructive", "admin"})

    Example — deny external_effect tools entirely::

        ToolPolicy(denied={"stripe.charge"})
    """

    def __init__(
        self,
        *,
        allowed: set[str] | None = None,
        denied: set[str] | None = None,
        require_approval_for: set[str] | None = None,
    ) -> None:
        self.allowed = allowed
        self.denied = denied or set()
        self.require_approval_for: set[str] = require_approval_for or set()

    def is_allowed(self, tool_name: str) -> bool:
        if tool_name in self.denied:
            return False
        if self.allowed is None:
            return True
        return tool_name in self.allowed

    def is_allowed_any(self, tool_names: Iterable[str]) -> bool:
        names = set(tool_names)
        if names.intersection(self.denied):
            return False
        if self.allowed is None:
            return True
        return bool(names.intersection(self.allowed))

    def enforce(self, tool_name: str) -> None:
        if not self.is_allowed(tool_name):
            raise ToolPolicyViolation(f"Tool not permitted: {tool_name}")

    def enforce_any(self, tool_name: str, aliases: Iterable[str] = ()) -> None:
        names = [tool_name, *aliases]
        if not self.is_allowed_any(names):
            raise ToolPolicyViolation(f"Tool not permitted: {tool_name}")

    def requires_approval(self, tool_name: str, risk: Optional[str]) -> bool:
        """Return True if this tool needs human approval before execution.

        ``require_approval_for`` acts as a *floor*: any tool whose risk is at
        or above the minimum rank in the set requires approval. So
        ``require_approval_for={"destructive"}`` also captures ``"admin"``
        because ``"admin"`` ranks higher. Unknown or unclassified risk
        (``None``) is treated as ``"read"`` (lowest rank) and will not trigger
        approval unless ``"read"`` is explicitly listed.
        """
        if not self.require_approval_for:
            return False
        effective_risk = risk or "read"
        # Unknown risk strings fall back to literal-membership semantics so we
        # don't silently fail-open on a typo.
        if effective_risk not in _RISK_RANK:
            return effective_risk in self.require_approval_for
        floor = (
            min(_RISK_RANK[r] for r in self.require_approval_for if r in _RISK_RANK)
            if any(r in _RISK_RANK for r in self.require_approval_for)
            else None
        )
        if floor is None:
            return effective_risk in self.require_approval_for
        return _RISK_RANK[effective_risk] >= floor


class ToolPolicyViolation(PermissionError):
    """Raised when a tool call violates the configured policy."""
