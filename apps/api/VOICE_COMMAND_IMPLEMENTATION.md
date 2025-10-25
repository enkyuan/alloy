# Voice Command WebSocket Implementation

## Overview
Extended the WebSocket endpoint at `/stt/stream` to handle voice commands for Spotify control.

## Changes Made

### 1. Modified `apps/api/app/routers/speech_to_text_stream.py`

#### Added Imports
- `SessionLocal` from `app.database` - For database session management
- `Integration` model from `app.models.integration` - For Spotify integration queries
- `spotify_service` from `app.services.spotify` - For token management
- `spotify_controller` and exceptions from `app.services.spotify_controller` - For command execution
- `voice_agent_service` from `app.services.voice_agent` - For command parsing

#### New Helper Functions

**`get_spotify_integration(user_id: str, db: Session)`**
- Queries database for user's active Spotify integration
- Returns Integration object or None

**`execute_spotify_command(command_text: str, user_id: str, db: Session)`**
- Main command execution function
- Validates Spotify integration exists
- Refreshes access token if needed
- Parses command using voice_agent_service
- Executes appropriate Spotify controller method based on intent
- Handles all error cases with specific error codes
- Returns structured response dictionary

#### WebSocket Handler Updates

**Authentication & Setup**
- Added `user_id` extraction from authenticated user
- Created database session for integration queries
- Session properly closed in finally block

**Message Handling**
- Extended text message handling to parse JSON command messages
- Added command message type detection: `{"type": "command", "text": "..."}`
- Executes Spotify commands when command messages received
- Sends command results back to client

**Supported Command Intents**
- `play_track` - Search and play tracks
- `play_playlist` - Search and play playlists
- `play_album` - Search and play albums
- `pause` - Pause playback
- `resume` - Resume playback
- `next` - Skip to next track
- `previous` - Skip to previous track
- `set_volume` - Set volume level
- `list_devices` - List available devices

#### Error Handling

**Error Types with Specific Codes**
- `NO_INTEGRATION` - User hasn't connected Spotify
- `AUTH_FAILED` - Token refresh failed
- `NO_DEVICE` - No active Spotify device found
- `NO_RESULTS` - Search returned no results
- `PREMIUM_REQUIRED` - Feature requires Spotify Premium
- `API_ERROR` - Spotify API error
- `UNKNOWN_INTENT` - Command not understood
- `INTERNAL_ERROR` - Unexpected error

**Response Message Types**
- `command_result` - Successful command execution
- `command_error` - Command execution failed
- `command_clarification` - Command needs clarification

## Message Protocol

### Client → Server

**Command Message**
```json
{
  "type": "command",
  "text": "play bohemian rhapsody by queen"
}
```

### Server → Client

**Success Response**
```json
{
  "type": "command_result",
  "success": true,
  "message": "Now playing 'Bohemian Rhapsody' by Queen",
  "data": {
    "track_name": "Bohemian Rhapsody",
    "artist": "Queen",
    "album": "A Night at the Opera",
    "uri": "spotify:track:...",
    "track_id": "...",
    "album_art": "https://..."
  },
  "intent": "play_track"
}
```

**Error Response**
```json
{
  "type": "command_error",
  "message": "No active Spotify device found. Please open Spotify on a device.",
  "error_code": "NO_DEVICE"
}
```

**Clarification Response**
```json
{
  "type": "command_clarification",
  "message": "What track would you like to play?",
  "intent": "play_track",
  "confidence": 0.3
}
```

## Integration with Existing Services

### VoiceAgentService
- Parses natural language commands
- Extracts intent and parameters
- Maintains conversation context per user
- Generates user-friendly response messages

### SpotifyController
- Executes Spotify API operations
- Handles device management
- Implements search and playback logic
- Provides comprehensive error handling

### CommandParser
- Pattern matching for intent recognition
- Entity extraction (track names, artists, etc.)
- Natural language normalization
- Context-aware parsing

## Requirements Satisfied

✅ **Requirement 7.1** - Uses existing Spotify authentication and token management
✅ **Requirement 8.1** - Works with transcribed text from WebSocketSTTService
✅ **Requirement 8.2** - Handles partial and final transcriptions appropriately
✅ **Requirement 8.4** - Provides timeout handling for incomplete commands

## Testing

To test the implementation:

1. Ensure API server is running
2. Connect to WebSocket: `ws://localhost:8000/api/v1/stt/stream?token=<auth_token>`
3. Send command message:
   ```json
   {"type": "command", "text": "play bohemian rhapsody"}
   ```
4. Verify response is received with command result or error

## Next Steps

The following tasks remain to complete the voice-activated Spotify agent:

- Task 5: Implement wake word detection in iOS frontend
- Task 6: Add command execution flow to iOS frontend
- Task 7: Build UI components for command mode feedback
- Task 8: Implement audio feedback system
- Task 9: Add device management capabilities
- Task 10: Implement context-aware command handling
- Task 11: Add comprehensive error handling and user feedback
