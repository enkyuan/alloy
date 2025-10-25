# Implementation Plan

- [x] 1. Create backend command parsing infrastructure
  - Implement CommandParser service with pattern matching for intent recognition
  - Create CommandIntent and CommandContext data models
  - Implement entity extraction for track names, artists, playlists, and numbers
  - Add natural language pattern definitions for all command types (play, pause, volume, etc.)
  - _Requirements: 5.1, 5.2, 5.3, 8.1, 8.5_

- [x] 2. Implement VoiceAgentService for command orchestration
  - Create VoiceAgentService class with command parsing and response generation
  - Implement context management for maintaining conversation state
  - Add ambiguity detection and clarification request logic
  - Implement response message generation for success and error cases
  - _Requirements: 5.4, 5.5, 6.1, 6.2, 8.3_

- [x] 3. Build SpotifyController for command execution
  - Create SpotifyController class wrapping existing SpotifyService
  - Implement search_and_play_track with result selection logic (most popular)
  - Implement search_and_play_playlist with user playlist support
  - Implement search_and_play_album functionality
  - Add playback control methods (pause, resume, next, previous, volume)
  - Implement get_active_device with fallback handling
  - Add comprehensive error handling for all Spotify operations
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 4.5, 7.1, 7.2, 7.4, 7.5_

- [x] 4. Extend WebSocket endpoint for voice commands
  - Modify speech_to_text_stream.py to handle command messages
  - Integrate VoiceAgentService and SpotifyController into WebSocket flow
  - Add command message type handling (client → server)
  - Implement command_result and command_error response messages (server → client)
  - Add user authentication and Spotify integration validation
  - Implement proper error handling and logging for command execution
  - _Requirements: 7.1, 8.1, 8.2, 8.4_

- [x] 5. Implement wake word detection in iOS frontend
  - Extend AssistantViewModel with wake word detection logic
  - Add isInCommandMode state property and command mode management
  - Implement detectWakeWord method with pattern matching for "Hey Modi"
  - Add enterCommandMode and exitCommandMode methods
  - Implement 10-second timeout for command mode with automatic exit
  - Add command mode state change notifications
  - _Requirements: 1.1, 1.3, 1.4_

- [x] 6. Add command execution flow to iOS frontend
  - Extend AssistantViewModel to send command messages via WebSocket
  - Implement handleTranscriptionForCommands to process transcriptions in command mode
  - Add sendSpotifyCommand method to send commands to backend
  - Implement handleCommandResult to process command responses
  - Add error handling for command failures
  - Create SpotifyTrack model for playback state
  - _Requirements: 2.1, 2.2, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 8.2_

- [x] 7. Build UI components for command mode feedback
  - Create CommandModeIndicator view with pulsing animation
  - Implement SpotifyPlaybackCard to display current track info
  - Add CommandFeedbackOverlay for temporary command result messages
  - Extend AssistantView to show command mode indicator
  - Add visual feedback for command execution states (processing, success, error)
  - Integrate playback status display into main view
  - _Requirements: 1.2, 1.5, 6.1, 6.2, 6.5_

- [x] 8. Implement audio feedback system
  - Add text-to-speech or audio playback capability to AssistantViewModel
  - Implement playAudioFeedback method for command confirmations
  - Create audio feedback messages for common command results
  - Add audio indicators for command processing states
  - Implement configurable verbosity levels for feedback
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [x] 9. Add device management capabilities
- [x] 9.1 Implement device listing and selection in SpotifyController
  - Add get_available_devices wrapper method
  - Implement device selection command parsing
  - Add device switching functionality
  - _Requirements: 7.2, 7.3_

- [x] 9.2 Create device management UI components
  - Build device selection view
  - Add device status indicators
  - _Requirements: 7.2, 7.3_

- [ ] 10. Implement context-aware command handling
  - Add conversation history tracking to CommandContext
  - Implement context extraction from previous commands
  - Add follow-up command support (e.g., "play another one by them")
  - Implement context timeout and reset logic
  - _Requirements: 5.5_

- [ ] 11. Add comprehensive error handling and user feedback
  - Implement NoActiveDeviceError with user-friendly messaging
  - Add SearchNoResultsError with suggestion support
  - Implement SpotifyAPIError handling with retry logic
  - Add authentication error handling (token expired, no integration)
  - Implement premium limitation detection and messaging
  - Create user-facing error messages for all error scenarios
  - _Requirements: 2.5, 4.4, 6.2, 7.4, 7.5, 8.3_