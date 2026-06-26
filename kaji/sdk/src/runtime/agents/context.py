from typing import Any, Dict, List, Optional

from kaji.runtime.agents.prompts import SystemPrompt
from kaji.infra.events.replay import SessionState


class ContextBuilder:
    """Converts the internal Kaji SessionState into generic LLM provider messages."""

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
