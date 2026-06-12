"""Integration abstract base class."""
from __future__ import annotations

import abc
from dataclasses import replace
from typing import List, Tuple

from agentkit.runtime.tools.registry import ToolHandler, ToolRegistry, ToolSpec


class Integration(abc.ABC):
    """Abstract base for a namespace-scoped collection of tools.

    Subclasses declare a `namespace` string and implement `tools()` returning
    a list of (ToolSpec, handler) pairs. The Integration prefixes each tool
    name as `{namespace}.{tool_name}` when registering into a ToolRegistry.
    """

    @property
    @abc.abstractmethod
    def namespace(self) -> str:
        """The namespace prefix for all tools in this integration."""
        ...

    @abc.abstractmethod
    def tools(self) -> List[Tuple[ToolSpec, ToolHandler]]:
        """Return all (spec, handler) pairs for this integration."""
        ...

    def register(self, registry: ToolRegistry) -> None:
        """Register all tools into the given registry, namespace-prefixed."""
        for spec, handler in self.tools():
            prefixed = replace(spec, name=f"{self.namespace}.{spec.name}")
            registry.register(prefixed)(handler)
