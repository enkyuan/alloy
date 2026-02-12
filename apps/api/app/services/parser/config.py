"""Static configuration for the hybrid command parser service."""

from __future__ import annotations

# Candidate / consensus settings
MAX_ASR_ALTERNATIVES: int = 5
ASR_ALTERNATIVE_DECAY: float = 0.12
MIN_INTENT_SCORE: float = 0.28
COMMAND_LIKE_SIGNAL_MIN: float = 0.66
COMMAND_OVERRIDE_CONFIDENCE: float = 0.78

# Clarification policy tuned to reduce unnecessary clarifications
CLARIFY_MIN_CONFIDENCE: float = 0.42
CLARIFY_MIN_MARGIN: float = 0.04
STRONG_COMMAND_SIGNAL: float = 0.78

# Text normalization
FILLER_PATTERNS: tuple[str, ...] = (
    r"\b(um|uh|you know|actually|basically|literally)\b",
    r"\b(hey|hi|hello|haven)\b",
    r"\b(please|can you|could you|would you)\b",
)

QUERY_NOISE_PATTERNS: tuple[str, ...] = (
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
)

SYNONYMS: dict[str, str] = {
    "put on": "play",
    "start playing": "play",
    "can you play": "play",
    "please play": "play",
    "play list": "playlist",
    "song": "track",
    "tune": "track",
    "stop": "pause",
    "halt": "pause",
    "continue": "resume",
    "unpause": "resume",
    "skip": "next",
    "forward": "next",
    "back": "previous",
    "rewind": "previous",
    "louder": "volume up",
    "quieter": "volume down",
    "softer": "volume down",
}

# Intent schema and biasing
INTENT_REQUIRED_PARAMS: dict[str, tuple[str, ...]] = {
    "play_track": ("track",),
    "play_track_from_playlist": ("track", "playlist"),
    "play_playlist": ("playlist",),
    "add_to_queue": ("track",),
    "play_album": ("album",),
    "switch_device": ("device",),
    "set_volume": ("level",),
}

INTENT_BASE_WEIGHTS: dict[str, float] = {
    "play_track_from_playlist": 0.10,
    "add_to_queue": 0.08,
    "play_playlist": 0.08,
    "play_album": 0.07,
    "play_track": 0.06,
    "play_artist": -0.06,
    "pause": 0.05,
    "resume": 0.05,
    "next": 0.05,
    "previous": 0.05,
    "set_volume": 0.06,
    "volume_up": 0.05,
    "volume_down": 0.05,
    "switch_device": 0.06,
    "list_devices": 0.06,
    "play_another_by_artist": 0.06,
    "play_more_like_this": 0.06,
    "play_from_same_album": 0.06,
}

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "play_track": ("play", "track"),
    "play_track_from_playlist": ("play", "track", "playlist"),
    "play_playlist": ("playlist",),
    "add_to_queue": ("queue", "add"),
    "play_album": ("album",),
    "play_artist": ("play", "artist"),
    "pause": ("pause",),
    "resume": ("resume", "continue"),
    "next": ("next",),
    "previous": ("previous",),
    "set_volume": ("volume",),
    "volume_up": ("volume", "up"),
    "volume_down": ("volume", "down"),
    "switch_device": ("switch", "device"),
    "list_devices": ("devices",),
}

RAW_PATTERNS: dict[str, tuple[str, ...]] = {
    "play_another_by_artist": (
        r"play\s+another\s+(?:one|song|track)\s+by\s+them",
        r"play\s+another\s+(?:one|song|track)\s+by\s+(?:the\s+)?same\s+artist",
        r"play\s+(?:some\s+)?more\s+by\s+them",
        r"play\s+something\s+else\s+by\s+them",
        r"another\s+(?:one|song|track)\s+by\s+them",
    ),
    "play_more_like_this": (
        r"play\s+(?:something|more)\s+like\s+this",
        r"play\s+(?:something|more)\s+similar",
        r"more\s+like\s+this",
        r"similar\s+(?:songs|tracks|music)",
    ),
    "play_from_same_album": (
        r"play\s+(?:the\s+)?(?:next|another)\s+(?:song|track)\s+from\s+(?:this|the)\s+album",
        r"play\s+more\s+from\s+(?:this|the)\s+album",
        r"continue\s+(?:this|the)\s+album",
    ),
    "play_track_from_playlist": (
        r"play\s+(?P<track>.+?)\s+from\s+(?:my\s+)?playlist\s+(?P<playlist>.+)",
        r"play\s+(?P<track>.+?)\s+in\s+(?:my\s+)?playlist\s+(?P<playlist>.+)",
        r"play\s+(?P<track>.+?)\s+from\s+playlist\s+(?P<playlist>.+)",
    ),
    "play_playlist": (
        r"play\s+(?:my\s+)?playlist\s+(?P<playlist>.+)",
        r"play\s+the\s+playlist\s+(?P<playlist>.+)",
        r"put\s+on\s+(?:my\s+)?playlist\s+(?P<playlist>.+)",
        r"start\s+(?:my\s+)?playlist\s+(?P<playlist>.+)",
        r"play\s+my\s+(?P<playlist>liked\s+songs)",
        r"play\s+my\s+(?P<playlist>favorites)",
    ),
    "add_to_queue": (
        r"add\s+(?P<track>.+?)\s+by\s+(?P<artist>.+?)\s+to\s+(?:the\s+)?queue",
        r"add\s+(?P<track>.+?)\s+to\s+(?:the\s+)?queue",
        r"queue\s+(?P<track>.+?)\s+by\s+(?P<artist>.+)",
        r"queue\s+up\s+(?P<track>.+?)\s+by\s+(?P<artist>.+)",
        r"queue\s+(?P<track>.+)",
    ),
    "play_album": (
        r"play\s+(?:the\s+)?album\s+(?P<album>.+?)\s+by\s+(?P<artist>.+)",
        r"play\s+(?:the\s+)?album\s+(?P<album>.+)",
        r"put\s+on\s+(?:the\s+)?album\s+(?P<album>.+)",
    ),
    "play_track": (
        r"play\s+(?:the\s+)?track\s+(?P<track>.+?)\s+by\s+(?P<artist>.+)",
        r"play\s+(?:the\s+)?song\s+(?P<track>.+?)\s+by\s+(?P<artist>.+)",
        r"play\s+(?P<track>.+?)\s+by\s+(?P<artist>.+)",
        r"put\s+on\s+(?P<track>.+?)\s+by\s+(?P<artist>.+)",
        r"start\s+playing\s+(?P<track>.+?)\s+by\s+(?P<artist>.+)",
        r"play\s+(?:the\s+)?track\s+(?P<track>.+)",
        r"play\s+(?:the\s+)?song\s+(?P<track>.+)",
        r"put\s+on\s+(?P<track>.+)",
        r"start\s+playing\s+(?P<track>.+)",
    ),
    "play_artist": (
        r"play\s+(?:some\s+)?music\s+by\s+(?P<artist>.+)",
        r"play\s+(?:songs\s+from\s+)?artist\s+(?P<artist>.+)",
        r"play\s+artist\s+(?P<artist>.+)",
    ),
    "pause": (
        r"pause",
        r"pause\s+(?:the\s+)?music",
        r"stop\s+playing",
        r"stop\s+(?:the\s+)?music",
    ),
    "resume": (
        r"resume",
        r"continue",
        r"keep\s+playing",
        r"unpause",
        r"play$",
    ),
    "next": (
        r"next",
        r"skip",
        r"next\s+(?:song|track)",
        r"skip\s+(?:this\s+)?(?:song|track)",
        r"play\s+next",
    ),
    "previous": (
        r"previous",
        r"back",
        r"last\s+(?:song|track)",
        r"previous\s+(?:song|track)",
        r"go\s+back",
        r"play\s+previous",
    ),
    "set_volume": (
        r"volume\s+(?P<level>\d+)",
        r"set\s+volume\s+to\s+(?P<level>\d+)",
        r"change\s+volume\s+to\s+(?P<level>\d+)",
        r"turn\s+volume\s+to\s+(?P<level>\d+)",
    ),
    "volume_up": (
        r"volume\s+up",
        r"turn\s+(?:it\s+)?up",
        r"increase\s+volume",
    ),
    "volume_down": (
        r"volume\s+down",
        r"turn\s+(?:it\s+)?down",
        r"decrease\s+volume",
        r"lower\s+volume",
    ),
    "switch_device": (
        r"play\s+on\s+(?:my\s+)?(?P<device>.+)",
        r"switch\s+to\s+(?:my\s+)?(?P<device>.+)",
        r"use\s+(?:my\s+)?(?P<device>.+)",
        r"transfer\s+to\s+(?:my\s+)?(?P<device>.+)",
        r"move\s+to\s+(?:my\s+)?(?P<device>.+)",
        r"change\s+device\s+to\s+(?P<device>.+)",
    ),
    "list_devices": (
        r"list\s+(?:my\s+)?devices",
        r"show\s+(?:my\s+)?devices",
        r"what\s+devices",
        r"available\s+devices",
        r"which\s+devices",
        r"show\s+available\s+devices",
    ),
}

COMMAND_PREFIX_PATTERN: str = (
    r"^\s*(?:(?:hey|hi)\s+\w+[\s,]+|milo[\s,]+|haven[\s,]+)?"
    r"(?:please\s+)?(?:play|pause|resume|continue|unpause|skip|next|"
    r"previous|back|add|queue|switch|transfer|move|list|show|set|turn|"
    r"increase|decrease|lower)\b"
)

COMMAND_SIGNAL_PATTERNS: tuple[str, ...] = (
    r"\b(?:to\s+queue|in\s+my\s+playlist|from\s+my\s+playlist|set\s+volume)\b",
    r"\b(?:play\s+on\s+my|switch\s+to|transfer\s+to|move\s+to)\b",
)

NARRATIVE_PATTERNS: tuple[str, ...] = (
    r"\b(?:i\s+like\s+to|i\s+love\s+to|when\s+i|while\s+i)\b",
    r"\b(?:i\s+am|i'm|i\s+feel|we\s+)\b",
)

CONTROL_INTENTS: tuple[str, ...] = (
    "pause",
    "resume",
    "next",
    "previous",
    "volume_up",
    "volume_down",
    "list_devices",
)
