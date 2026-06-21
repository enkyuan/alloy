"""Integration ABC for namespace-scoped tool bundles."""

from agentkit.runtime.integrations.base import Integration, Tool
from agentkit.runtime.integrations.functional import BoundTool, function_tool

FunctionTool = function_tool

__all__ = ["BoundTool", "FunctionTool", "Integration", "Tool"]
