<p align="center">
  <img src="docs/assets/banner.svg" alt="Modal Banner" width="100%" style="border-radius: 16px;" />
</p>

## Overview

Modal decouples conversational speed from heavy-duty task execution to deliver a voice-first experience that feels instantaneous. It leverages a split-pipeline architecture using Redis streams for real-time voice processing and distributed queues for agentic tools.

**Core Capabilities:**
- **Ultra-low latency** voice interactions (<500ms).
- **Agentic workflow execution** (Calendar, Spotify, Email).
- **Event-driven architecture** for scalable microservices.

## Tech Stack

- **Client:** Swift 5 (SwiftUI, MVVM, Soniox STT).
- **Backend:** Python 3.11 (FastAPI, TaskIQ).
- **Infrastructure:** Redis (Streams/PubSub), Supabase (Auth/PostgreSQL), Docker.

## Quick Start

> **Prerequisites:** Docker Desktop, Python 3.11+, Xcode 15+, [Bun](https://bun.sh)

### Desktop App Setup

1. Install workspace dependencies from the repository root:
   ```bash
   bun i
   ```

2. Start the desktop app:
   ```bash
   bun --filter @milo/desktop dev
   ```

3. Build the desktop app:
   ```bash
   bun --filter @milo/desktop build
   ```

For detailed manual configuration, please refer to the **[Setup Guide](docs/SETUP.md)**.
