/**
 * AgentKit: build agents in TypeScript.
 *
 * Infra-free core, mirroring the Python `agentkit` SDK's public surface:
 * event-sourced building blocks (events, bus, store, replay) and a tool
 * registry. Import what you need and compose it; nothing here requires a
 * database, server, or any environment configured.
 */

export const VERSION = "0.1.0";

// Events
export { EventType } from "./events/types";
export {
  AgentKitEvent,
  type AgentKitEventInput,
  type BaseEvent,
} from "./events/schemas";
export { EventBus } from "./events/bus";
export {
  type EventStore,
  InMemoryEventStore,
} from "./events/store";

// Sessions
export {
  replaySession,
  ReplaySession,
  type SessionState,
  type Message,
} from "./sessions/replay";

// Tools
export {
  type ToolSpec,
  type ToolContext,
  type ToolHandler,
  type JSONSchema,
  registerTool,
  listToolSpecs,
  toolSpecFromSchema,
  executeTool,
  clearTools,
} from "./tools/registry";
