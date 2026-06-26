"""Re-export of the legacy ToolDefinition ABC.

Prefer ``kaji.runtime.tools.registry.ToolSpec`` for new voice tools.
"""

from kaji.types.tool import ToolDefinition  # noqa: F401

__all__ = ["ToolDefinition"]
