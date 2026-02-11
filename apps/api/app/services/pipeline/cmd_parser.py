# TODO: FIX COMPUTED CONFIDENCE LEVELS

"""Command parser service for voice-activated Spotify agent."""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CommandIntent:
    """Represents a parsed command intent with extracted parameters."""

    intent: str  # Intent type (e.g., "play_track", "pause", "set_volume")
    parameters: dict  # Extracted parameters (e.g., {"track": "xyz", "artist": "abc"})
    confidence: float  # Confidence score (0.0 to 1.0)
    requires_clarification: bool  # Whether the command needs clarification
    raw_text: str  # Original command text


@dataclass
class CommandContext:
    """Maintains conversation context for command processing."""

    user_id: str
    last_command: Optional[str] = None
    last_intent: Optional[str] = None
    active_device_id: Optional[str] = None
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: Optional[datetime] = None
    last_track: Optional[str] = None
    last_artist: Optional[str] = None
    last_playlist: Optional[str] = None
    last_album: Optional[str] = None
    last_genre: Optional[str] = None

    # Context timeout in seconds (default: 5 minutes)
    CONTEXT_TIMEOUT_SECONDS: int = 300

    def __post_init__(self):
        """Initialize mutable defaults."""
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)

    def is_expired(self) -> bool:
        """Check if context has expired based on timeout.

        Returns:
            True if context is expired and should be reset
        """
        if not self.timestamp:
            return True

        elapsed = (datetime.now(timezone.utc) - self.timestamp).total_seconds()
        return elapsed > self.CONTEXT_TIMEOUT_SECONDS

    def reset(self) -> None:
        """Reset context to initial state."""
        self.last_command = None
        self.last_intent = None
        self.conversation_history = []
        self.timestamp = datetime.now(timezone.utc)
        self.last_track = None
        self.last_artist = None
        self.last_playlist = None
        self.last_album = None
        self.last_genre = None

    def update_timestamp(self) -> None:
        """Update timestamp to current time."""
        self.timestamp = datetime.now(timezone.utc)


class CommandParser:
    """Parses natural language commands for Spotify control."""

    def __init__(self):
        """Initialize command parser with patterns and synonyms."""
        self.patterns = self._load_patterns()
        self.synonyms = self._load_synonyms()
        self.intent_keywords = self._load_intent_keywords()
        self.query_noise_patterns = self._load_query_noise_patterns()

    def _load_query_noise_patterns(self) -> list[str]:
        """Load phrases to strip from extracted play queries."""
        return [
            r"\bhey\s+haven\b",
            r"\bhaven\b",
            r"\bhey\b",
            r"\bhi\b",
            r"\bcan you\b",
            r"\bcould you\b",
            r"\bwould you\b",
            r"\bplease\b",
            r"\bplay\b",
            r"\bon spotify\b",
            r"\bin spotify\b",
            r"\bwith spotify\b",
            r"\bspotify\b",
            r"\bfor me\b",
            r"\bthe song\b",
            r"\bthe track\b",
            r"\bthe album\b",
        ]

    def _clean_query_value(self, value: str) -> str:
        """Clean noise phrases from extracted entity values."""
        cleaned = value
        for pattern in self.query_noise_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

        cleaned = cleaned.replace("?", "").replace('"', "")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _load_patterns(self) -> dict:
        """Load regex patterns for intent matching.

        Returns:
            Dictionary mapping intent types to compiled regex patterns
        """
        # Note: Order matters! More specific patterns should come first
        patterns = {
            # Follow-up command patterns (must come first to catch context references)
            "play_another_by_artist": [
                r"play\s+another\s+(?:one|song|track)\s+by\s+them",
                r"play\s+another\s+(?:one|song|track)\s+by\s+(?:the\s+)?same\s+artist",
                r"play\s+(?:some\s+)?more\s+by\s+them",
                r"play\s+(?:some\s+)?more\s+from\s+them",
                r"play\s+something\s+else\s+by\s+them",
                r"another\s+(?:one|song|track)\s+by\s+them",
            ],
            "play_more_like_this": [
                r"play\s+(?:something|more)\s+like\s+this",
                r"play\s+(?:something|more)\s+similar",
                r"more\s+like\s+this",
                r"similar\s+(?:songs|tracks|music)",
            ],
            # ... (other patterns remain same, just compiling them below)
        }

        # Compile all patterns
        compiled_patterns = {}
        # We need to redefine the full dictionary here to ensure we have all patterns
        # Since I can't see the full file content in this tool call, I will use the previous view_file content
        # to reconstruct the dictionary and compile it.

        raw_patterns = {
            "play_another_by_artist": [
                r"play\s+another\s+(?:one|song|track)\s+by\s+them",
                r"play\s+another\s+(?:one|song|track)\s+by\s+(?:the\s+)?same\s+artist",
                r"play\s+(?:some\s+)?more\s+by\s+them",
                r"play\s+(?:some\s+)?more\s+from\s+them",
                r"play\s+something\s+else\s+by\s+them",
                r"another\s+(?:one|song|track)\s+by\s+them",
            ],
            "play_more_like_this": [
                r"play\s+(?:something|more)\s+like\s+this",
                r"play\s+(?:something|more)\s+similar",
                r"more\s+like\s+this",
                r"similar\s+(?:songs|tracks|music)",
            ],
            "play_from_same_album": [
                r"play\s+(?:the\s+)?(?:next|another)\s+(?:song|track)\s+from\s+(?:this|the)\s+album",
                r"play\s+more\s+from\s+(?:this|the)\s+album",
                r"continue\s+(?:this|the)\s+album",
            ],
            "play_track_from_playlist": [
                r"play\s+(?P<track>.+?)\s+from\s+(?:my\s+)?playlist\s+(?P<playlist>.+)",
                r"play\s+(?P<track>.+?)\s+in\s+(?:my\s+)?playlist\s+(?P<playlist>.+)",
                r"play\s+(?P<track>.+?)\s+from\s+playlist\s+(?P<playlist>.+)",
            ],
            "play_playlist": [
                r"play\s+(?:my\s+)?playlist\s+(?P<playlist>.+)",
                r"play\s+the\s+playlist\s+(?P<playlist>.+)",
                r"put\s+on\s+(?:my\s+)?playlist\s+(?P<playlist>.+)",
                r"start\s+(?:my\s+)?playlist\s+(?P<playlist>.+)",
                r"play\s+my\s+(?P<playlist>liked\s+songs)",
                r"play\s+my\s+(?P<playlist>favorites)",
            ],
            "add_to_queue": [
                r"add\s+(?P<track>.+?)\s+by\s+(?P<artist>.+?)\s+to\s+(?:the\s+)?queue",
                r"add\s+(?P<track>.+?)\s+to\s+(?:the\s+)?queue",
                r"queue\s+(?P<track>.+?)\s+by\s+(?P<artist>.+)",
                r"queue\s+(?P<track>.+)",
            ],
            "play_album": [
                r"play\s+(?:the\s+)?album\s+(?P<album>.+?)\s+by\s+(?P<artist>.+)",
                r"play\s+(?:the\s+)?album\s+(?P<album>.+)",
                r"put\s+on\s+(?:the\s+)?album\s+(?P<album>.+)",
            ],
            "play_track": [
                r"play\s+(?P<track>.+?)\s+by\s+(?P<artist>.+)",
                r"play\s+the\s+song\s+(?P<track>.+?)\s+by\s+(?P<artist>.+)",
                r"put\s+on\s+(?P<track>.+?)\s+by\s+(?P<artist>.+)",
                r"start\s+playing\s+(?P<track>.+?)\s+by\s+(?P<artist>.+)",
                r"can\s+you\s+play\s+(?P<track>.+?)\s+by\s+(?P<artist>.+)",
                r"play\s+(?P<track>.+)",
                r"play\s+the\s+song\s+(?P<track>.+)",
                r"put\s+on\s+(?P<track>.+)",
                r"start\s+playing\s+(?P<track>.+)",
            ],
            "play_artist": [
                r"play\s+(?:some\s+)?(?:music\s+by\s+)?(?P<artist>.+)",
                r"play\s+(?:songs\s+from\s+)?(?P<artist>.+)",
                r"put\s+on\s+(?:some\s+)?(?P<artist>.+)",
            ],
            "pause": [
                r"pause",
                r"stop",
                r"stop\s+playing",
                r"pause\s+(?:the\s+)?music",
                r"stop\s+(?:the\s+)?music",
            ],
            "resume": [
                r"resume",
                r"continue",
                r"keep\s+playing",
                r"unpause",
                r"play",
            ],
            "next": [
                r"next",
                r"skip",
                r"next\s+(?:song|track)",
                r"skip\s+(?:this\s+)?(?:song|track)",
                r"play\s+next",
            ],
            "previous": [
                r"previous",
                r"back",
                r"last\s+(?:song|track)",
                r"previous\s+(?:song|track)",
                r"go\s+back",
                r"play\s+previous",
            ],
            "set_volume": [
                r"volume\s+(?P<level>\d+)",
                r"set\s+volume\s+to\s+(?P<level>\d+)",
                r"change\s+volume\s+to\s+(?P<level>\d+)",
                r"turn\s+volume\s+to\s+(?P<level>\d+)",
            ],
            "volume_up": [
                r"volume\s+up",
                r"turn\s+(?:it\s+)?up",
                r"louder",
                r"increase\s+volume",
            ],
            "volume_down": [
                r"volume\s+down",
                r"turn\s+(?:it\s+)?down",
                r"quieter",
                r"decrease\s+volume",
                r"lower\s+volume",
            ],
            "switch_device": [
                r"play\s+on\s+(?:my\s+)?(?P<device>.+)",
                r"switch\s+to\s+(?:my\s+)?(?P<device>.+)",
                r"use\s+(?:my\s+)?(?P<device>.+)",
                r"transfer\s+to\s+(?:my\s+)?(?P<device>.+)",
                r"move\s+to\s+(?:my\s+)?(?P<device>.+)",
                r"change\s+device\s+to\s+(?P<device>.+)",
            ],
            "list_devices": [
                r"list\s+(?:my\s+)?devices",
                r"show\s+(?:my\s+)?devices",
                r"what\s+devices",
                r"available\s+devices",
                r"which\s+devices",
                r"show\s+available\s+devices",
            ],
        }

        for intent, patterns_list in raw_patterns.items():
            compiled_patterns[intent] = [
                re.compile(p, re.IGNORECASE) for p in patterns_list
            ]

        return compiled_patterns

    def _load_synonyms(self) -> dict:
        """Load synonym mappings for normalization.

        Returns:
            Dictionary mapping synonyms to canonical forms
        """
        return {
            # Action synonyms
            "put on": "play",
            "start playing": "play",
            "can you play": "play",
            "please play": "play",
            # Music type synonyms
            "song": "track",
            "tune": "track",
            # Control synonyms
            "stop": "pause",
            "halt": "pause",
            "continue": "resume",
            "unpause": "resume",
            "skip": "next",
            "forward": "next",
            "back": "previous",
            "rewind": "previous",
            # Volume synonyms
            "louder": "volume up",
            "quieter": "volume down",
            "softer": "volume down",
        }

    def _load_intent_keywords(self) -> dict:
        """Load keywords that help identify intent types.

        Returns:
            Dictionary mapping intent types to keyword lists
        """
        return {
            "play_track": ["play", "song", "track"],
            "play_track_from_playlist": ["play", "track", "playlist"],
            "play_playlist": ["playlist"],
            "add_to_queue": ["queue", "add"],
            "play_album": ["album"],
            "pause": ["pause", "stop"],
            "resume": ["resume", "continue", "unpause"],
            "next": ["next", "skip"],
            "previous": ["previous", "back"],
            "set_volume": ["volume"],
        }

    def normalize_text(self, text: str) -> str:
        """Normalize text for better pattern matching.

        Args:
            text: Raw command text

        Returns:
            Normalized text
        """
        # Convert to lowercase
        text = text.lower().strip()

        # Remove extra whitespace
        text = re.sub(r"\s+", " ", text)

        # Remove common filler words (but preserve "like" when used in "like this")
        filler_words = [
            r"\b(um|uh|you know|actually|basically|literally)\b",
            r"\b(hey|hi|hello|haven)\b",
            r"\b(please|can you|could you|would you)\b",
        ]
        for pattern in filler_words:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)

        # Remove "like" only when it's not part of "like this" or "like that"
        text = re.sub(r"\blike\b(?!\s+(?:this|that))", "", text, flags=re.IGNORECASE)

        # Clean up extra spaces after removal
        text = re.sub(r"\s+", " ", text).strip()

        # Apply synonym replacements
        for synonym, canonical in self.synonyms.items():
            text = re.sub(r"\b" + re.escape(synonym) + r"\b", canonical, text)

        return text

    def match_intent(self, text: str) -> tuple[str, float]:
        """Match text against intent patterns.

        Args:
            text: Normalized command text

        Returns:
            Tuple of (intent_type, confidence_score)
        """
        # Try to match against patterns in order (more specific first)
        # Return first match with high confidence
        for intent_type, patterns in self.patterns.items():
            for pattern in patterns:
                if isinstance(pattern, re.Pattern):
                    match = pattern.search(text)
                    pattern_text = pattern.pattern
                else:
                    match = re.search(pattern, text, re.IGNORECASE)
                    pattern_text = pattern
                if match:
                    # Calculate confidence based on match quality
                    confidence = self._calculate_confidence(text, pattern_text, match)
                    # Return immediately for high-confidence matches
                    if confidence >= 0.8:
                        return intent_type, confidence

        # If no high-confidence match, try all patterns and pick best
        best_match = None
        best_confidence = 0.0

        for intent_type, patterns in self.patterns.items():
            for pattern in patterns:
                if isinstance(pattern, re.Pattern):
                    match = pattern.search(text)
                    pattern_text = pattern.pattern
                else:
                    match = re.search(pattern, text, re.IGNORECASE)
                    pattern_text = pattern
                if match:
                    confidence = self._calculate_confidence(text, pattern_text, match)
                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_match = intent_type

        # If no pattern matched, try keyword-based matching
        if best_match is None:
            best_match, best_confidence = self._keyword_based_matching(text)

        return best_match or "unknown", best_confidence

    def _calculate_confidence(self, text: str, pattern: str, match: re.Match) -> float:
        """Calculate confidence score for a pattern match.

        Args:
            text: Original text
            pattern: Matched pattern
            match: Regex match object

        Returns:
            Confidence score (0.0 to 1.0)
        """
        # Base confidence for any match
        confidence = 0.7

        # Increase confidence if match covers most of the text
        match_length = len(match.group(0))
        text_length = len(text)
        coverage = match_length / text_length if text_length > 0 else 0
        confidence += coverage * 0.2

        # Increase confidence if pattern has named groups (more specific)
        if match.groupdict():
            confidence += 0.1

        return min(confidence, 1.0)

    def _keyword_based_matching(self, text: str) -> tuple[Optional[str], float]:
        """Fallback matching using keywords.

        Args:
            text: Normalized command text

        Returns:
            Tuple of (intent_type, confidence_score)
        """
        best_match = None
        best_score = 0

        for intent_type, keywords in self.intent_keywords.items():
            score = sum(1 for keyword in keywords if keyword in text)
            if score > best_score:
                best_score = score
                best_match = intent_type

        # Lower confidence for keyword-based matching
        confidence = min(0.5 + (best_score * 0.1), 0.7) if best_match else 0.0

        return best_match, confidence

    def extract_entities(self, text: str, intent: str) -> dict:
        """Extract entities (parameters) from text based on intent.

        Args:
            text: Normalized command text
            intent: Detected intent type

        Returns:
            Dictionary of extracted parameters
        """
        entities = {}

        # Get patterns for this intent
        patterns = self.patterns.get(intent, [])

        # Try each pattern to extract entities
        for pattern in patterns:
            if isinstance(pattern, re.Pattern):
                match = pattern.search(text)
            else:
                match = re.search(pattern, text, re.IGNORECASE)
            if match:
                # Extract named groups as entities
                entities.update(match.groupdict())
                break

        # Clean up extracted entities
        for key, value in entities.items():
            if value:
                cleaned = value.strip()
                if key in {"track", "artist", "album", "playlist"}:
                    cleaned = self._clean_query_value(cleaned)
                entities[key] = cleaned

        # Extract numbers for volume commands
        if intent in ["set_volume", "volume_up", "volume_down"]:
            numbers = re.findall(r"\d+", text)
            if numbers and "level" not in entities:
                entities["level"] = int(numbers[0])

        return entities

    def parse_command(
        self, text: str, context: Optional[CommandContext] = None
    ) -> CommandIntent:
        """Parse a natural language command into a structured intent.

        Args:
            text: Raw command text
            context: Optional conversation context

        Returns:
            CommandIntent with parsed information
        """
        # Normalize the text
        normalized_text = self.normalize_text(text)

        # Match intent
        intent, confidence = self.match_intent(normalized_text)

        # Extract entities
        parameters = self.extract_entities(normalized_text, intent)

        # Apply context if available
        if context:
            parameters = self._apply_context(parameters, intent, context)

        # Determine if clarification is needed
        requires_clarification = self._needs_clarification(
            intent, parameters, confidence
        )

        return CommandIntent(
            intent=intent,
            parameters=parameters,
            confidence=confidence,
            requires_clarification=requires_clarification,
            raw_text=text,
        )

    def _apply_context(
        self, parameters: dict, intent: str, context: CommandContext
    ) -> dict:
        """Apply conversation context to fill in missing parameters.

        Args:
            parameters: Extracted parameters
            intent: Command intent
            context: Conversation context

        Returns:
            Enhanced parameters with context
        """
        # Check if context has expired
        if context.is_expired():
            logger.info(f"Context expired for user {context.user_id}, resetting")
            context.reset()
            return parameters

        # Handle follow-up commands that reference previous context
        if intent == "play_another_by_artist":
            # Use artist from last command
            if context.last_artist:
                parameters["artist"] = context.last_artist
                # Convert to play_artist intent to play more by same artist
                parameters["_original_intent"] = intent
                parameters["_context_resolved"] = True
            else:
                # No artist in context, mark as needing clarification
                parameters["_needs_clarification"] = True

        elif intent == "play_more_like_this":
            # Use track and artist from last command for similarity search
            if context.last_track and context.last_artist:
                parameters["reference_track"] = context.last_track
                parameters["reference_artist"] = context.last_artist
                parameters["_original_intent"] = intent
                parameters["_context_resolved"] = True
            else:
                parameters["_needs_clarification"] = True

        elif intent == "play_from_same_album":
            # Use album from last command
            if context.last_album and context.last_artist:
                parameters["album"] = context.last_album
                parameters["artist"] = context.last_artist
                parameters["_original_intent"] = intent
                parameters["_context_resolved"] = True
            else:
                parameters["_needs_clarification"] = True

        # If playing a track without artist, use last artist from context
        elif intent == "play_track" and "artist" not in parameters:
            if context.last_artist:
                parameters["artist"] = context.last_artist
                parameters["_context_resolved"] = True

        # If playing an album without artist, use last artist from context
        elif intent == "play_album" and "artist" not in parameters:
            if context.last_artist:
                parameters["artist"] = context.last_artist
                parameters["_context_resolved"] = True

        # Use active device if available
        if context.active_device_id:
            parameters["device_id"] = context.active_device_id

        return parameters

    def _needs_clarification(
        self, intent: str, parameters: dict, confidence: float
    ) -> bool:
        """Determine if the command needs clarification.

        Args:
            intent: Command intent
            parameters: Extracted parameters
            confidence: Confidence score

        Returns:
            True if clarification is needed
        """
        # Low confidence commands need clarification
        if confidence < 0.5:
            return True

        # Unknown intent needs clarification
        if intent == "unknown":
            return True

        # Play commands without required parameters need clarification
        if intent == "play_track" and not parameters.get("track"):
            return True

        if intent == "play_track_from_playlist" and (
            not parameters.get("track") or not parameters.get("playlist")
        ):
            return True

        if intent == "play_playlist" and not parameters.get("playlist"):
            return True

        if intent == "add_to_queue" and not parameters.get("track"):
            return True

        if intent == "play_album" and not parameters.get("album"):
            return True

        return False


# Create singleton instance
command_parser = CommandParser()
