"""Legacy tool abstraction — use ``agentkit.runtime.tools.registry.ToolSpec`` instead.

.. deprecated::
   ``ToolDefinition`` predates the provider-neutral ``ToolSpec`` / ``ToolRegistry``
   model.  It is retained for voice-agent serve-side compatibility and will be
   removed in a future release.  New code should use ``ToolSpec``.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, cast

try:
    from google.genai import types as gemini_types
except ImportError:
    gemini_types = None

gemini_types = cast(Any, gemini_types)


class ToolDefinition(ABC):
    """Abstract base class for static tool definitions.

    This class should be implemented by all system tools. Each tool should define
    its name, description, and return type as class methods.
    """

    @classmethod
    @abstractmethod
    def name(cls) -> str:
        """Tool name for LLM usage."""
        pass

    @classmethod
    @abstractmethod
    def description(cls) -> str:
        """Tool description for LLM understanding."""
        pass

    @classmethod
    @abstractmethod
    def to_gemini_tool(cls) -> Any:
        """Map to Gemini tool format. https://ai.google.dev/gemini-api/docs/function-calling"""
        pass

    @classmethod
    @abstractmethod
    def to_openai_tool(cls) -> Dict[str, object]:
        """Map to OpenAI tool format. https://platform.openai.com/docs/guides/tools?tool-type=function-calling"""
        pass
