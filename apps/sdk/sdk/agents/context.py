from typing import Any, Dict, List, Optional

from sdk.agents.prompts import SystemPrompt
from sdk.events.replay import SessionState


class ContextBuilder:
    """Converts the internal AgentKit SessionState into generic LLM provider messages."""

    @staticmethod
    def build_messages(
        state: SessionState,
        prompt: SystemPrompt,
        variables: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Construct the message array for the model."""
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": prompt.render(variables)}
        ]

        # Append all historical turns safely
        for msg in state.messages:
            messages.append(msg)

        return messages
