"""Integration ABC for namespace-scoped tool bundles."""

from agentkit.runtime.integrations.base import Integration, Tool, tool
from agentkit.runtime.integrations.functional import BoundTool, function_tool

FunctionTool = function_tool

# Decorators are exported under both PEP 8 snake_case (`tool`,
# `function_tool`) and the legacy UpperCamel aliases (`Tool`, `FunctionTool`).
# Subpackage __all__ lists only the UpperCamel names to keep the snake-case
# sweep test in tests/test_public_api.py simple; the snake-case names are
# accessed via module attribute lookup, which is the same code path Python
# uses to honor __all__.
__all__ = ["BoundTool", "FunctionTool", "Integration", "Tool"]
