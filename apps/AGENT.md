## Project Context
**Modal** is an agentic voice assistant engineered for ultra-low latency interaction and complex task execution.
* **Core Philosophy:** Voice-first design that decouples conversational speed ("Fast Path") from heavy-duty task execution ("Slow Path").
* **Architecture:** Event-driven microservices utilizing **Redis** to stream voice data and manage distributed tasks.

---

## 1. Tech Stack & Standards

### **Client**
* **Language:** Swift 5+
* **Frameworks:**
    * **SwiftUI:** Primary driver for UI composition, navigation, and reactive state management.
    * **UIKit:** Used via `UIViewRepresentable` / `UIViewControllerRepresentable` for low-level audio visualization, gesture handling, or legacy integrations.
    * **AVFoundation:** Core audio engine for recording and playback.
* **STT Provider:** **Soniox** (via WebSocket).
* **Architecture:** MVVM (Model-View-ViewModel).

### **Backend & Infrastructure**
* **API Framework:** **FastAPI**
* **Task Queue:** **Taskiq**
* **Message Broker:** **Redis**.
* **Database:** **Supabase*** 
* **Migrations:** **Alembic** 

---

## 2. Documentation & Tooling Strategy

### **Swift Documentation**
Refer to these official sources for implementation details:
* **SwiftUI:** [Apple SwiftUI Documentation](https://developer.apple.com/documentation/swiftui)
* **UIKit:** [Apple UIKit Documentation](https://developer.apple.com/documentation/uikit)
* **AVFoundation:** [Apple AVFoundation Documentation](https://developer.apple.com/documentation/avfoundation) (Essential for the Audio Engine).
* **Concurrency:** Use Swift `async/await` and `Actors` for thread-safe state updates.

### **Supabase & Schema Management**
* **Inspection:** Use the **Supabase MCP Server** tools (`get_tables`, `describe_table`) to verify schema state before writing queries. **Do not hallucinate table names.**
* **Migrations:** **Do not** create tables in the Supabase Dashboard. Use **Alembic**.
    * *Workflow:* Define Python model -> `alembic revision --autogenerate` -> `alembic upgrade head`.

### **Soniox STT Integration**
* **Protocol:** WebSocket (`wss://stt-rt.soniox.com/transcribe-websocket`).
* [cite_start]**Handling:** Manage `final` vs `non_final` tokens to update the UI instantly while waiting for confirmed text[cite: 8].

---

## 3. System Architecture

The system follows a split-pipeline approach (Ref: `pipeline.txt`).

### **The Event Backbone (Redis)**
Redis replaces Kafka to serve as the unified bus.

1.  **Streams (`stream:voice_input`)**
    * **Source:** Client (via FastAPI Ingestion) or STT Service.
    * **Payload:** `{ user_id: string, text: string, timestamp: float, is_final: bool }`
    * **Consumer:** LLM Service (FastAPI).
2.  **Work Queues (Taskiq)**
    * **`queue:high_priority`:** Urgent commands (Stop audio, Music control, System alerts).
    * **`queue:background`:** Summarization, Vector embeddings, Analytics.

### **Data Persistence (Supabase)**
* **Vector Store:** `pgvector` extension for RAG (Retrieval Augmented Generation).
* **User State:** Conversation history, user preferences, and session metadata.

---

## 4. Frontend Architecture (Inspired by Vercel v0)
*Reference: [How we built the v0 iOS app](https://vercel.com/blog/how-we-built-the-v0-ios-app)*

To achieve a "native" fluid feel, adopt these composable architecture patterns in Swift:

### **1. Composable State Providers**
Avoid a monolithic `AssistantViewModel`. Instead, inject granular providers via `.environmentObject()`:
* `InputState`: Manages the floating composer height and text content.
* `KeyboardState`: Dedicated observer for keyboard height and layout adjustments.
* `MessageStream`: Handles the WebSocket connection and token appending.

### **2. Optimistic UI & Staggered Streaming**
* **Immediate Feedback:** When a user speaks/types, render the bubble immediately (Optimistic UI) before the server confirms receipt.
* **Token Streaming:** Use `AsyncThrowingStream` to append tokens. Do not re-render the entire list on every token. Use `id`-based updates on specific message cells.
* **Staggered Fade-In:** Assistant messages should not "pop" in. Use `.transition(.opacity.animation(.easeIn))` on new tokens to create a smooth "reading" flow.

### **3. The Floating Composer ("Liquid Glass")**
* **Design:** The input bar should float above the content with a blur material (`.regularMaterial`), distinct from the scroll view.
* **Keyboard Avoidance:** Use `GeometryReader` or specific `ignoresSafeArea(.keyboard)` configurations to ensure the composer sticks to the keyboard top smoothly without jitter.

---

## 5. Deliverables & Implementation Plan

### **Phase 1: Infrastructure & Core Backend**
*Goal: Establish the event loop and storage layer.*

1.  **Redis Configuration:**
    * Provision Redis.
    * Define consumer groups for `stream:voice_input`.
2.  **Supabase & Alembic:**
    * Initialize Alembic in the Python backend.
    * Define models: `User`, `Conversation`, `VectorEmbedding`.
    * Generate and apply initial migrations.
3.  **FastAPI Skeleton:**
    * Setup `Taskiq` with Redis broker.
    * Implement `Lifespan` context to manage Redis/DB connections.

### **Phase 2: The Fast Path (Voice Loop)**
*Goal: Latency < 500ms from Speech to Audio Response.*

1.  **Soniox Service (Swift/Python):**
    * Implement WebSocket client for Soniox.
    * [cite_start]Handle `final` and `non_final` token streams[cite: 8].
    * Push transcribed text to Redis `stream:voice_input`.
2.  **LLM Consumer (Python):**
    * Worker subscribes to Redis Stream.
    * Fetches brief context (last 3 turns) from Supabase.
    * Streams LLM tokens to TTS Service.
3.  **Audio Output:**
    * Stream TTS bytes back to the client via WebSocket or HTTP Chunked Transfer.

### **Phase 3: The Slow Path (Agentic Tasks)**
*Goal: Tool execution and complex reasoning.*

1.  **Intent Router:**
    * LLM Service identifies intent (e.g., "Play music").
    * If intent matches a tool, push payload to `queue:high_priority` via Taskiq.
2.  **Taskiq Workers:**
    * Implement workers for external APIs (Spotify, Calendar).
    * Update Client UI state via Redis Pub/Sub (`channel:user_updates`) upon task completion.
3.  **RAG Implementation:**
    * On `queue:background`, generate embeddings for user queries and store in Supabase.

### **Phase 4: Client Implementation (Swift)**
*Goal: A fluid, reactive native iOS interface.*

1.  **Audio Engine (`AudioRecordingService.swift`):**
    * Use **AVFoundation** to capture raw PCM audio.
    * [cite_start]Convert to Soniox-compatible format (`pcm_s16le`, 16kHz)[cite: 8].
2.  **WebSocket Manager (`WebSocketSTTService.swift`):**
    * Manage the connection lifecycle with Soniox.
    * Publish `final` text to the local `MessageModel`.
3.  **UI Layer (`Views/`):**
    * **SwiftUI:** Build `AssistantView` and `TranscriptionBubble` for the chat interface.
    * **UIKit Integration:** Use `UIViewRepresentable` for a high-performance audio waveform visualizer (if `Canvas` is insufficient).
4.  **Live Activities:**
    * Implement Dynamic Island support (`ModalActivityAttributes.swift`) to show active listening state when the app is backgrounded.

---

## 6. Coding Standards

* **Swift:**
    * Use `struct` for data models (`Models/MessageModel.swift`).
    * Isolate logic in `ViewModels` (`AssistantViewModel.swift`).
    * Use `EnvironmentObject` for global state (Auth, AudioState).
* **Python:**
    * **Type Checking:** Use **pyrefly** for strict type checking. **Resolve all reported issues.**
    * Strict Type Hinting (Pydantic models for all API payloads).
    * Use `async/await` for all Redis and Database I/O.
    * **Taskiq:** Define tasks with clear retry policies.
  * **Comments:**
    * **Rule of Thumb:** Add comments for functions and keep them concise but detailed enough for any developer to understand. No emojis - this is applicable to both logs in Go and Python and in comments
    * **Notes:** Use comments to keep track of remaining tasks, i.e, 
    ```text
    // TODO: ...
    // FIX: ...
    ```
  * **Logging:**
    * Add logs wherever possible in both the api and swift app. Use these to help debug issues and obtain the stack trace of and issues.
