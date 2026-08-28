from dataclasses import dataclass


@dataclass(frozen=True)
class AgentStrategy:
    """Configuration for how the agent executes its reasoning loop."""

    max_iterations: int = 5
    allow_tool_calls: bool = True
    temperature: float = 0.7

    def __post_init__(self) -> None:
        if isinstance(self.max_iterations, bool) or not isinstance(
            self.max_iterations, int
        ):
            raise TypeError("max_iterations must be a positive integer")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be a positive integer")
