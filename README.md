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

### CLI Setup & Usage

The project is managed via a CLI tool.

1. Navigate to the CLI directory:
   ```bash
   cd apps/cli
   ```

2. Install dependencies:
   ```bash
   bun i
   ```

3. Run the CLI (opens interactive menu for setup, startup, etc.):
   ```bash
   bun dev
   ```

For detailed manual configuration, please refer to the **[Setup Guide](docs/SETUP.md)**.
