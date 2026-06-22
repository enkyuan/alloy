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
export { AgentKitEvent, type AgentKitEventInput, type BaseEvent } from "./events/schemas";
export { EventBus } from "./events/bus";
export { type EventStore, InMemoryEventStore } from "./events/store";

// Sessions
export { replaySession, ReplaySession, type SessionState, type Message } from "./sessions/replay";
export { SessionManager } from "./sessions/manager";
export { type SessionRecord, type SessionStore, InMemorySessionStore } from "./sessions/store";

// Tools
export {
  type ToolSpec,
  type ToolContext,
  type ToolHandler,
  type JSONSchema,
  type ToolParameters,
  type ListToolSpecsOptions,
  type ToolMeta,
  type TaggedHandler,
  TOOL_META,
  ToolRegistry,
  registerTool,
  listToolSpecs,
  toolSpecFromSchema,
  providerSafeToolName,
  toolParametersToJSONSchema,
  executeTool,
  clearTools,
} from "./tools/registry";
export { requestPayment } from "./tools/payment";
export type { RequestPaymentOptions, RequestPaymentTool } from "./tools/payment";
export {
  ToolPolicy,
  ToolPolicyViolation,
  type ToolPolicyOptions,
  type ToolRisk,
} from "./tools/policy";
export {
  ToolPlanner,
  type ToolPlannerOptions,
  type ToolCallInstruction,
  type ToolCallResult,
  type ToolExecutor,
  type ApprovalHandler,
  type EmitFn,
} from "./tools/planner";

// Providers
export type {
  ModelProvider,
  ModelProviderOptions,
  ModelResponse,
  ModelResponseChunk,
  ProviderMessage,
  ToolCall,
} from "./providers/base";
export { OpenAIProvider } from "./providers/openai";
export type { OpenAIProviderOptions } from "./providers/openai";
export { AnthropicProvider } from "./providers/anthropic";
export type { AnthropicProviderOptions } from "./providers/anthropic";
export {
  ProviderAPIError,
  ProviderConfigError,
  ProviderConnectionError,
  ProviderError,
} from "./providers/errors";
export { clearProviders, getProvider, registerProvider } from "./providers/registry";

// Integrations
export {
  BoundTool,
  FunctionTool,
  type FunctionToolHandler,
  type FunctionToolMeta,
  Integration,
  tool,
} from "./integrations";

// Runtime
export {
  AgentRuntime,
  type AgentRuntimeOptions,
  type AgentStrategy,
  type RunTurnOptions,
} from "./runtime/runtime";
export { CancellationToken } from "./runtime/cancellation";
export { buildMessages } from "./runtime/context";
export { AgentBuilder, type Integrable, type AgentBuilderBuildOptions } from "./runtime/builder";
