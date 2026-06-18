"""Re-export of the legacy ToolDefinition ABC.

Prefer ``agentkit.runtime.tools.registry.ToolSpec`` for new voice tools.
"""
from agentkit.types.tool import ToolDefinition  # noqa: F401

__all__ = ["ToolDefinition"]
