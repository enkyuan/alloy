"""Working memory buffer for in-session context windows."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkingMemory:
    """Bounded FIFO buffer of recent conversation turns."""

    max_messages: int = 20
    _messages: deque[dict[str, Any]] = field(default_factory=deque)

    def append(self, role: str, content: str) -> None:
        self._messages.append({"role": role, "content": content})
        while len(self._messages) > self.max_messages:
            self._messages.popleft()

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self._messages)

    def clear(self) -> None:
        self._messages.clear()
