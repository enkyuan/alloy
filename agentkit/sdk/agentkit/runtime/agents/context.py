from typing import Any, Dict, List, Optional

from agentkit.runtime.agents.prompts import SystemPrompt
from agentkit.infra.events.replay import SessionState


class ContextBuilder:
    """Converts the internal AgentKit SessionState into generic LLM provider messages."""

    @staticmethod
    def build_messages(
        state: SessionState,
        prompt: SystemPrompt,
        variables: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Construct the message array for the model."""
        return [
            {"role": "system", "content": prompt.render(variables)},
            *state.messages,
        ]
