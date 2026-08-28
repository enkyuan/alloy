from typing import Any, Dict, Optional

ASSISTANT_SYSTEM_INSTRUCTION = (
    "You are a helpful and precise voice assistant.\n"
    "CRITICAL CONSTRAINTS FOR TOOL USAGE:\n"
    "1. ONLY use the provided tools. Do not hallucinate tools or make up arguments.\n"
    "2. If an argument is missing from the user's request (e.g., requesting to play a song without naming it), DO NOT guess. Explicitly ask the user to provide the missing information.\n"
    "3. Adhere strictly to the parameter schemas. If a query requires a non-empty string, ensure you provide one.\n"
    "4. If a tool result is successfully provided inside the conversation history, acknowledge it and respond succinctly to the user without calling the tool again.\n"
    "5. If a tool fails to execute or returns an error, inform the user directly instead of repeatedly trying the same flawed arguments."
)


class SystemPrompt:
    """Manages the agent's core instructions and variable interpolation."""

    def __init__(self, template: str):
        self.template = template

    def render(self, variables: Optional[Dict[str, Any]] = None) -> str:
        """Render the prompt with the given state variables."""
        if variables is None:
            variables = {}
        # Allows for basic formatting. In a real system, you might use Jinja2/Mako here.
        try:
            return self.template.format(**variables)
        except KeyError:
            return self.template  # Fallback if strict formatting fails
