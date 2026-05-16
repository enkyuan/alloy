"""Tool execution policies — allowlists and denylists."""

from __future__ import annotations


class ToolPolicy:
    """Decides whether a tool may run for a given session."""

    def __init__(
        self,
        *,
        allowed: set[str] | None = None,
        denied: set[str] | None = None,
    ) -> None:
        self.allowed = allowed
        self.denied = denied or set()

    def is_allowed(self, tool_name: str) -> bool:
        if tool_name in self.denied:
            return False
        if self.allowed is None:
            return True
        return tool_name in self.allowed

    def enforce(self, tool_name: str) -> None:
        if not self.is_allowed(tool_name):
            raise ToolPolicyViolation(f"Tool not permitted: {tool_name}")


class ToolPolicyViolation(PermissionError):
    """Raised when a tool call violates the configured policy."""
