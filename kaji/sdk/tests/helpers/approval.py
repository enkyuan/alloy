"""Typed approval handlers shared by runtime tests."""

from __future__ import annotations

from kaji.runtime.agents.approval import ApprovalDecision, ApprovalRequestContext
from kaji.runtime.context import ToolInvocation


class StaticApprovalHandler:
    def __init__(self, decision: ApprovalDecision) -> None:
        self._decision = decision

    async def request(
        self, call: ToolInvocation, context: ApprovalRequestContext
    ) -> ApprovalDecision:
        _ = (call, context)
        return self._decision


class RaisingApprovalHandler:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def request(
        self, call: ToolInvocation, context: ApprovalRequestContext
    ) -> ApprovalDecision:
        _ = (call, context)
        raise self._error
