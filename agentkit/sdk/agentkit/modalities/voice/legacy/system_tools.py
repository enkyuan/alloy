"""Re-export of legacy voice system tools.

These tools use the older ``ToolDefinition`` model.  Prefer implementing new
voice tools via ``agentkit.runtime.tools.registry.ToolSpec``.
"""
from agentkit.runtime.tools.system_tools import (  # noqa: F401
    EndCallTool,
    TransferCallTool,
)

__all__ = ["EndCallTool", "TransferCallTool"]
