This document is written **for LLMs and human contributors**. It explains *how this Swift 6+ iOS app is structured, why it is structured this way, and how new features should be implemented*.

If a task is clear but the implementation details are uncertain, **default to Apple’s official documentation** (AVFoundation, Swift Concurrency, Network, SwiftUI, XCTest). If the LLM lacks certainty, it should explicitly say *which Apple doc section is needed* rather than guessing.

---

## 1. Core Principles (Read First)

### 1.1 Swift Version & Language Model

* Target **Swift 6+**
* Use **strict concurrency checking** (`Sendable`, `@MainActor`, `nonisolated` where appropriate)
* Prefer **async/await** over callbacks
* Avoid Combine unless strictly necessary (Swift Concurrency is the default)

### 1.2 File Size & Modularity

* **Hard limit:** 400–500 LOC per file
* If logic is reused more than twice → **refactor into a helper/service**
* Prefer *composition* over inheritance

### 1.3 Error Handling (Non‑Optional)

* Never swallow errors
* Prefer `enum AppError: Error` with associated values
* Errors must:

  * Be loggable
  * Be user-presentable *when appropriate*
  * Carry enough context for debugging

### 1.4 Testing Expectations

* Complex flows require **unit tests**
* UI rendering requires **snapshot tests**
* Network/audio edge cases require **mocked dependencies**

---

## 2. High-Level Architecture

The app follows a **Service-Oriented + SwiftUI MVVM** architecture.

```
Views (SwiftUI)
  ↓
ViewModels (@MainActor)
  ↓
Services (Audio, Network, Auth, Tools)
  ↓
System APIs / Backend
```

### Why this matters

* SwiftUI views stay declarative and testable
* Side effects are isolated
* Audio + networking can be stress-tested independently

---

## 3. Directory Responsibilities

### `/Config`

**Purpose:** Environment & infrastructure separation

* `Environment.swift`

  * Defines `.staging` vs `.production`
  * No secrets hardcoded
* `Supabase.swift`

  * Centralized backend client configuration

> Tokens must be injected via build settings or CI secrets

---

### `/Helpers`

**Purpose:** Stateless utilities

* `AudioFormatConverter`

  * PCM ↔ Opus
  * Must be deterministic and unit-tested
* `ThemeManager`

  * Central source of colors, spacing, haptics

No side effects. No networking. No singletons.

---

### `/Models`

**Purpose:** Data contracts

* Codable-first
* Matches backend schema exactly
* No business logic

Examples:

* `MessageModel`
* `SpotifyTrackModel`
* `ToolModel`

If decoding fails → surface a typed error.

---

### `/Services` (Critical)

Services are **long-lived**, testable, and injected.

#### Audio Services

* `AudioRecordingService`
* `AudioStreamingService`
* `AudioFeedbackService`

Use **AVAudioEngine** and **AVAudioSession** directly.

> Always reference Apple docs:
>
> * *Audio Engine Programming Guide*
> * *AVAudioSession Category Options*

#### Networking

* `WebSocketSTTService`
* `MCPService`

Must handle:

* Reconnection
* Backpressure
* Partial payloads

#### Auth & Integrations

* `AuthService`
* `IntegrationService`

Auth state changes must be observable and testable.

---

## 4. Core Engineering Deliverables

### 4.1 VoiceManager (Singleton)

**Purpose:** Owns microphone input lifecycle

Responsibilities:

* Audio input buffer
* Voice Activity Detection (VAD)
* Silence detection
* Interrupt signaling

Design rules:

* Thread-safe
* Minimal public API
* No UI logic

If using VAD:

* Document algorithm
* Provide tunable thresholds

### 4.2 WebSocketClient

**Purpose:** Bidirectional streaming with Python backend

Must support:

* Binary audio frames
* JSON control messages
* Immediate interrupt messages

Failure modes to handle:

* Network drops mid-utterance
* Partial frames
* Server backpressure

### 4.3 AudioPlayerEngine

**Purpose:** Play raw PCM or Opus chunks

Requirements:

* No full-file buffering
* Low-latency playback
* Queue-based scheduling

Use:

* `AVAudioPlayerNode`
* Manual buffer scheduling

---

## 5. Feature Implementation Notes

### Latency UI (<200ms)

* Visual feedback must react **before audio playback**
* Use lightweight SwiftUI animations
* State driven from ViewModel

### Interruption Handling

* If user speaks while AI speaks:

  1. Stop local playback immediately
  2. Clear audio buffers
  3. Send interrupt signal to backend

No debounce delays allowed.

### Background Audio

* Configure `AVAudioSession` correctly
* Add background audio capability
* Test screen-lock behavior

### Bluetooth & CarPlay

* Handle route changes via notifications
* Never assume default output

---

## 6. Testing Strategy

### Unit Tests

* Mock WebSocket responses
* Simulate dropped connections
* Validate recovery behavior

### UI Tests

* Snapshot tests for chat UI
* State-driven rendering only

### End-to-End

* Audio → WebSocket → Audio loop
* Latency measurements

---

## 7. App Store & Compliance

### Info.plist (Required)

* `NSMicrophoneUsageDescription`
* `NSSpeechRecognitionUsageDescription`

Text must clearly explain **why audio is recorded**.

### Assets

* App icons:

  * 1024×1024
  * 180×180
  * 120×120
* SVG/PDF vectors for in-app icons

---

## 8. Technical Documentation Deliverables

### API Contract

* Define JSON / Protobuf schemas
* Versioned
* Backward compatible

### Latency Budget

* Measure round-trip on:

  * WiFi
  * 4G
  * 5G

Breakdown:

* Capture
* Encode
* Network
* Decode
* Playback

---

## 9. Design & UX

### Haptics

* Centralized map
* No random vibration usage

### Waiting State Animation

* SwiftUI animation or Lottie
* Loop until first token received

---

## 10. LLM Operating Instructions (Important)

When modifying or adding code:

1. Do **not** invent APIs
2. Prefer Apple documentation
3. Keep files small
4. Add tests when logic branches
5. Ask for docs if unsure

If something feels unclear, **stop and request clarification** instead of guessing.

---

**This document is the source of truth.**
