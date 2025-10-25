# Voice-Activated Spotify Agent - Design Document

## Overview

This design extends the existing real-time voice assistant system to add intelligent Spotify control capabilities. The system will process natural language commands from the existing speech-to-text pipeline and execute Spotify operations through the existing SpotifyService API integration.

The architecture follows a layered approach:
- **Frontend Layer**: Swift iOS app with voice UI (existing AssistantView)
- **Backend Layer**: Python FastAPI service with WebSocket streaming (existing)
- **Agent Layer**: NEW - Command parsing and Spotify control logic
- **Integration Layer**: Existing Spotify API service

## Architecture

### High-Level Flow

```
User Voice → Microphone → StreamingAudioService → WebSocket → 
Soniox STT → Transcription Stream → Wake Word Detection → 
Command Parser → Intent Extraction → Spotify Controller → 
Spotify API → Audio Feedback → User
```

### Component Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    iOS Frontend                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │         AssistantViewModel (Extended)             │  │
│  │  - Wake word detection                            │  │
│  │  - Command mode state management                  │  │
│  │  - Audio feedback playback                        │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │         AssistantView (Extended)                  │  │
│  │  - Visual feedback for command mode               │  │
│  │  - Spotify playback status display                │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                          │
                    WebSocket (existing)
                          │
┌─────────────────────────────────────────────────────────┐
│                  Python Backend (FastAPI)                │
│  ┌──────────────────────────────────────────────────┐  │
│  │    STT Stream Router (existing)                   │  │
│  │    /stt/stream WebSocket endpoint                 │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │    Voice Agent Service (NEW)                      │  │
│  │  - Command parsing & intent extraction            │  │
│  │  - Context management                             │  │
│  │  - Response generation                            │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │    Spotify Controller (NEW)                       │  │
│  │  - Wraps existing SpotifyService                  │  │
│  │  - Search & playback orchestration                │  │
│  │  - Device management                              │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │    SpotifyService (existing)                      │  │
│  │  - Token management                               │  │
│  │  - Spotify API calls                              │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘

```

## Components and Interfaces

### 1. Wake Word Detector (Frontend - Swift)

**Location**: `apps/modal/modal/ViewModels/AssistantViewModel.swift` (extension)

**Responsibilities**:
- Monitor transcription stream for wake word patterns
- Trigger command listening mode
- Provide visual/audio feedback

**Interface**:
```swift
extension AssistantViewModel {
    // State
    @Published var isInCommandMode: Bool = false
    @Published var commandModeTimeout: Timer?
    
    // Methods
    func detectWakeWord(in transcription: String) -> Bool
    func enterCommandMode()
    func exitCommandMode()
    func resetCommandTimeout()
}
```

**Wake Word Patterns**:
- "Hey Modi"
- "Modi" (when at start of sentence)
- Case-insensitive matching
- Fuzzy matching for transcription errors

### 2. Voice Agent Service (Backend - Python)

**Location**: `apps/api/app/services/voice_agent.py` (NEW)

**Responsibilities**:
- Parse natural language commands
- Extract intent and parameters
- Maintain conversation context
- Generate response messages

**Interface**:
```python
class VoiceAgentService:
    def parse_command(self, text: str, context: dict) -> CommandIntent
    def extract_search_query(self, text: str, intent: str) -> dict
    def generate_response(self, result: dict, intent: str) -> str
    def handle_ambiguity(self, options: list) -> str
```

**Command Intent Types**:
```python
@dataclass
class CommandIntent:
    intent: str  # "play_track", "play_playlist", "play_album", "pause", "resume", etc.
    parameters: dict  # {"track": "xyz", "artist": "abc", "volume": 50}
    confidence: float
    requires_clarification: bool
```

**Intent Categories**:
- **Playback Control**: play, pause, resume, stop, next, previous
- **Search & Play**: play_track, play_album, play_playlist, play_artist
- **Volume Control**: set_volume, volume_up, volume_down
- **Library**: play_liked_songs, play_recent
- **Device**: switch_device, list_devices

### 3. Command Parser (Backend - Python)

**Location**: `apps/api/app/services/command_parser.py` (NEW)

**Responsibilities**:
- Pattern matching for command recognition
- Entity extraction (track names, artists, numbers)
- Handle natural language variations

**Interface**:
```python
class CommandParser:
    def __init__(self):
        self.patterns = self._load_patterns()
        self.synonyms = self._load_synonyms()
    
    def match_intent(self, text: str) -> tuple[str, float]
    def extract_entities(self, text: str, intent: str) -> dict
    def normalize_text(self, text: str) -> str
```

**Pattern Examples**:
```python
PATTERNS = {
    "play_track": [
        r"play (?P<track>.+?) by (?P<artist>.+)",
        r"play (?P<track>.+)",
        r"put on (?P<track>.+)",
        r"start playing (?P<track>.+)"
    ],
    "pause": [
        r"pause",
        r"stop",
        r"stop playing"
    ],
    "set_volume": [
        r"volume (?P<level>\d+)",
        r"set volume to (?P<level>\d+)",
        r"turn volume (?P<direction>up|down)"
    ]
}
```

### 4. Spotify Controller (Backend - Python)

**Location**: `apps/api/app/services/spotify_controller.py` (NEW)

**Responsibilities**:
- Orchestrate Spotify operations
- Handle search and selection logic
- Manage device state
- Error handling and fallbacks

**Interface**:
```python
class SpotifyController:
    def __init__(self, spotify_service: SpotifyService):
        self.spotify = spotify_service
    
    async def execute_command(
        self, 
        intent: CommandIntent, 
        access_token: str
    ) -> CommandResult
    
    async def search_and_play_track(
        self, 
        query: str, 
        access_token: str
    ) -> CommandResult
    
    async def search_and_play_playlist(
        self, 
        query: str, 
        access_token: str
    ) -> CommandResult
    
    async def control_playback(
        self, 
        action: str, 
        access_token: str
    ) -> CommandResult
    
    async def get_active_device(
        self, 
        access_token: str
    ) -> Optional[str]
```

**CommandResult**:
```python
@dataclass
class CommandResult:
    success: bool
    message: str  # User-friendly response
    data: dict  # Additional data (track info, etc.)
    error: Optional[str]
```

### 5. WebSocket Message Protocol Extension

**Location**: `apps/api/app/routers/speech_to_text_stream.py` (extend existing)

**New Message Types**:

Client → Server:
```json
{
  "type": "command",
  "text": "play xyz on spotify",
  "wake_word_detected": true
}
```

Server → Client:
```json
{
  "type": "command_result",
  "success": true,
  "message": "Now playing 'XYZ' by Artist Name",
  "data": {
    "track_name": "XYZ",
    "artist": "Artist Name",
    "album": "Album Name",
    "uri": "spotify:track:..."
  }
}
```

```json
{
  "type": "command_error",
  "message": "No matching track found. Did you mean 'ABC'?",
  "suggestions": ["ABC", "DEF"]
}
```

### 6. Frontend State Management (Swift)

**Location**: `apps/modal/modal/ViewModels/AssistantViewModel.swift` (extend)

**New State Properties**:
```swift
@Published var isInCommandMode: Bool = false
@Published var currentSpotifyTrack: SpotifyTrack?
@Published var commandFeedback: String?
@Published var isExecutingCommand: Bool = false
```

**New Methods**:
```swift
func handleTranscriptionForCommands(_ text: String)
func sendSpotifyCommand(_ command: String)
func handleCommandResult(_ result: CommandResult)
func playAudioFeedback(_ message: String)
```

### 7. UI Components (Swift)

**Location**: `apps/modal/modal/Views/Home/AssistantView.swift` (extend)

**New Visual Elements**:
- Command mode indicator (pulsing border or icon)
- Spotify playback status card
- Command feedback overlay

**Component Structure**:
```swift
struct CommandModeIndicator: View {
    let isActive: Bool
    // Pulsing animation when in command mode
}

struct SpotifyPlaybackCard: View {
    let track: SpotifyTrack?
    // Shows current track, artist, album art
}

struct CommandFeedbackOverlay: View {
    let message: String
    // Temporary overlay showing command result
}
```

## Data Models

### SpotifyTrack (Swift)
```swift
struct SpotifyTrack: Codable, Identifiable {
    let id: String
    let name: String
    let artist: String
    let album: String
    let uri: String
    let albumArtUrl: String?
    let durationMs: Int
}
```

### CommandContext (Python)
```python
@dataclass
class CommandContext:
    user_id: str
    last_command: Optional[str]
    last_intent: Optional[str]
    active_device_id: Optional[str]
    conversation_history: list[str]
    timestamp: datetime
```

## Error Handling

### Error Categories

1. **Authentication Errors**
   - No Spotify integration found
   - Token expired and refresh failed
   - User not premium (for certain features)

2. **Search Errors**
   - No results found
   - Ambiguous query
   - API rate limiting

3. **Playback Errors**
   - No active device
   - Device unavailable
   - Premium required

4. **Network Errors**
   - Spotify API timeout
   - WebSocket disconnection
   - Connection failures

### Error Handling Strategy

**Backend**:
```python
try:
    result = await spotify_controller.execute_command(intent, token)
    return {"type": "command_result", "success": True, "message": result.message}
except NoActiveDeviceError:
    return {
        "type": "command_error",
        "message": "No active Spotify device found. Please open Spotify on a device.",
        "error_code": "NO_DEVICE"
    }
except SearchNoResultsError as e:
    return {
        "type": "command_error",
        "message": f"Couldn't find '{e.query}'. Try being more specific.",
        "error_code": "NO_RESULTS"
    }
except SpotifyAPIError as e:
    logger.error(f"Spotify API error: {e}")
    return {
        "type": "command_error",
        "message": "Something went wrong with Spotify. Please try again.",
        "error_code": "API_ERROR"
    }
```

**Frontend**:
```swift
func handleCommandError(_ error: CommandError) {
    switch error.code {
    case "NO_DEVICE":
        showAlert("Open Spotify", message: error.message)
    case "NO_RESULTS":
        showFeedback(error.message, type: .warning)
    default:
        showFeedback("Command failed. Please try again.", type: .error)
    }
}
```

## Testing Strategy

### Unit Tests

**Backend Tests** (`tests/services/test_voice_agent.py`):
- Command parsing accuracy
- Intent extraction
- Entity recognition
- Pattern matching edge cases
- Context management

**Backend Tests** (`tests/services/test_spotify_controller.py`):
- Search result selection logic
- Device management
- Error handling
- Token refresh integration

**Backend Tests** (`tests/services/test_command_parser.py`):
- Pattern matching for all intent types
- Natural language variations
- Entity extraction accuracy
- Fuzzy matching

### Integration Tests

**WebSocket Flow** (`tests/integration/test_voice_command_flow.py`):
- End-to-end command execution
- Wake word detection → command → result
- Error scenarios
- Timeout handling

**Spotify Integration** (`tests/integration/test_spotify_integration.py`):
- Search and play flow
- Playback control
- Device switching
- Token refresh during command

### Frontend Tests (Swift)

**AssistantViewModel Tests**:
- Wake word detection logic
- Command mode state transitions
- Timeout handling
- Message parsing

**UI Tests**:
- Command mode visual feedback
- Playback status display
- Error message presentation

### Manual Testing Scenarios

1. **Happy Path**:
   - Say "Hey Modi, play Bohemian Rhapsody"
   - Verify track plays
   - Verify audio feedback

2. **Playback Control**:
   - Say "Hey Modi, pause"
   - Say "Hey Modi, next"
   - Say "Hey Modi, volume 50"

3. **Error Scenarios**:
   - Command with no active device
   - Search for non-existent track
   - Command timeout (no command after wake word)

4. **Natural Language Variations**:
   - "Hey Modi, can you play some Beatles?"
   - "Modi, put on my liked songs"
   - "Hey Modi, skip this track"

5. **Context Handling**:
   - "Hey Modi, play The Beatles"
   - "Play Yellow Submarine" (should maintain artist context)

## Performance Considerations

### Latency Targets
- Wake word detection: < 100ms
- Command parsing: < 200ms
- Spotify search: < 500ms
- Total command execution: < 1s

### Optimization Strategies
1. **Caching**: Cache user's playlists and recent searches
2. **Parallel Processing**: Search multiple types simultaneously
3. **Predictive Loading**: Preload user's top tracks/playlists
4. **Connection Pooling**: Reuse HTTP connections to Spotify API

### Resource Management
- Limit conversation context to last 10 commands
- Clear command mode after 10 seconds of inactivity
- Debounce wake word detection to avoid false positives

## Security Considerations

1. **Token Security**:
   - Never send Spotify tokens to frontend
   - Refresh tokens stored encrypted in database
   - Token validation on every command

2. **User Authorization**:
   - Verify user owns Spotify integration
   - Check token belongs to requesting user
   - Rate limiting per user

3. **Input Validation**:
   - Sanitize all voice command text
   - Validate extracted entities
   - Prevent injection attacks in search queries

## Deployment Considerations

### Backend Changes
- New service files: `voice_agent.py`, `command_parser.py`, `spotify_controller.py`
- Extended WebSocket router: `speech_to_text_stream.py`
- No database migrations required (uses existing Integration model)

### Frontend Changes
- Extended `AssistantViewModel.swift`
- Extended `AssistantView.swift`
- New UI components for command mode and playback status
- No new dependencies required

### Configuration
- No new environment variables needed
- Uses existing `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`
- Optional: Add `VOICE_COMMAND_TIMEOUT` (default: 10 seconds)

### Rollout Strategy
1. Deploy backend changes first
2. Test with internal users
3. Deploy frontend changes
4. Monitor error rates and latency
5. Gradual rollout to all users

## Future Enhancements

1. **Multi-language Support**: Extend command patterns for other languages
2. **Personalization**: Learn user's music preferences and command patterns
3. **Contextual Awareness**: Remember recent conversations and preferences
4. **Advanced NLU**: Use LLM for more sophisticated command understanding
5. **Playlist Management**: Create and modify playlists via voice
6. **Social Features**: Share tracks with friends via voice command
7. **Smart Recommendations**: "Play something like this" based on current track
