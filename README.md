<p align="center">
  <img src="docs/assets/banner.svg" alt="Modal Banner" width="100%" style="border-radius: 16px;" />
</p>

<p align="center">
  <b>Modal</b> is an agentic voice assistant engineered for ultra-low latency interaction and complex task execution.
</p>

---

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

> **Prerequisites:** Docker Desktop, Python 3.11+, Xcode 15+

### Environment Setup

Initialize configuration and sync environment variables:

```bash
./scripts/setup.sh
```

### Start Services

Launch the Docker stack and build the iOS client:

```bash
modal-cli startup
```

Or if running from the CLI directory:

```bash
cd apps/cli && bun run src/index.ts startup
```

For detailed manual configuration, please refer to the **[Setup Guide](docs/SETUP.md)**.