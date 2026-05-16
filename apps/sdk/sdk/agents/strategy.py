from dataclasses import dataclass


@dataclass
class AgentStrategy:
    """Configuration for how the agent executes its reasoning loop."""

    max_iterations: int = 5
    allow_tool_calls: bool = True
    temperature: float = 0.7
