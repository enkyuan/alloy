"""Utterance classification helpers for routing chat vs command requests."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RouteDecision:
    """Routing decision for a user utterance."""

    should_parse_as_command: bool
    reason: str


class ConversationRouter:
    """Classifies whether an utterance is likely a command or casual conversation."""

    def __init__(self) -> None:
        self._explicit_command_patterns: tuple[re.Pattern[str], ...] = (
            re.compile(
                r"^\s*(?:(?:hey|hi)\s+\w+[,\s]+|milo[,\s]+|haven[,\s]+)?"
                r"(?:please\s+)?(?:play|pause|resume|continue|unpause|skip|next|"
                r"previous|back|add|queue|switch|transfer|move|list|show|set|turn)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?:can|could|would)\s+you\s+(?:please\s+)?"
                r"(?:play|pause|resume|skip|add|queue|switch|transfer|move|list|show|set)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?:to\s+queue|in\s+my\s+playlist|from\s+my\s+playlist|set\s+volume)\b",
                re.IGNORECASE,
            ),
        )

        self._conversation_patterns: tuple[re.Pattern[str], ...] = (
            re.compile(
                r"^\s*(?:hi|hello|hey|thanks|thank you|good morning|good evening)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"^\s*(?:how are you|who are you|what can you do|tell me about yourself)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?:just chatting|want to chat|i feel|i'm feeling|i am feeling)\b",
                re.IGNORECASE,
            ),
        )

    def decide(self, text: str) -> RouteDecision:
        """Decide whether a text should enter command fast-path parsing."""
        normalized = text.strip()
        if not normalized:
            return RouteDecision(
                should_parse_as_command=False, reason="empty_utterance_treated_as_chat"
            )

        for pattern in self._explicit_command_patterns:
            if pattern.search(normalized):
                return RouteDecision(
                    should_parse_as_command=True,
                    reason=f"matched_command_pattern:{pattern.pattern}",
                )

        for pattern in self._conversation_patterns:
            if pattern.search(normalized):
                return RouteDecision(
                    should_parse_as_command=False,
                    reason=f"matched_conversation_pattern:{pattern.pattern}",
                )

        # Default to conversation to avoid accidental command execution.
        return RouteDecision(
            should_parse_as_command=False, reason="no_explicit_command_signal"
        )


conversation_router = ConversationRouter()
