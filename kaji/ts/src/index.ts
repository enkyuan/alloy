/**
 * Kaji: build agents in TypeScript.
 *
 * Infra-free core, mirroring the Python `kaji` SDK's public surface:
 * event-sourced building blocks (events, bus, store, replay) and a tool
 * registry. Import what you need and compose it; nothing here requires a
 * database, server, or any environment configured.
 *
 * Implementation helpers (test resets, internal symbols, low-level Zod/JSON
 * Schema converters, the planner's `EmitFn`/`buildMessages`) deliberately are
 * not re-exported here; reach into the submodule path when you need them.
 */

export const VERSION = "0.1.0";

// Events
export { EventType } from "@/events/types";
export { KajiEvent, type KajiEventInput, type BaseEvent } from "@/events/schemas";
export { EventBus } from "@/events/bus";
export { type EventBusProtocol } from "@/events/protocols";
export { type EventStore, InMemoryEventStore } from "@/events/store";
export { ProviderRateLimited } from "@/events/schemas";

// Sessions
export {
  replaySession,
  type SessionState,
  type Message,
  type SessionTokens,
} from "@/sessions/replay";
export { SessionManager } from "@/sessions/manager";
export { type SessionRecord, type SessionStore, InMemorySessionStore } from "@/sessions/store";

// Tools
export {
  type ToolSpec,
  type ToolContext,
  type ToolHandler,
  type JSONSchema,
  type ToolParameters,
  type ListToolSpecsOptions,
  ToolRegistry,
  UnknownToolError,
  registerTool,
  listToolSpecs,
  toolSpecFromSchema,
  executeTool,
} from "@/tools/registry";
export {
  ToolPolicy,
  ToolPolicyViolation,
  type ToolPolicyOptions,
  type ToolRisk,
} from "@/tools/policy";
export {
  ToolPlanner,
  type ToolPlannerOptions,
  type ToolCallInstruction,
  type ToolCallResult,
  type ToolExecutor,
  type ApprovalHandler,
  type AnyApprovalHandler,
} from "@/tools/planner";
export { cliApprovalHandler, type CliApprovalOptions } from "@/tools/cli_approval_handler";

// Providers
export type {
  ModelProvider,
  ModelProviderOptions,
  ModelResponse,
  ModelResponseChunk,
  ProviderMessage,
  ToolCall,
  TokenUsage,
} from "@/providers/base";
export { OpenAIProvider } from "@/providers/openai";
export type { OpenAIProviderOptions, RetryOptions } from "@/providers/openai";
export { AnthropicProvider } from "@/providers/anthropic";
export type { AnthropicProviderOptions } from "@/providers/anthropic";
export {
  ProviderAPIError,
  ProviderConfigError,
  ProviderConnectionError,
  ProviderError,
  ProviderRateLimitedError,
} from "@/providers/errors";
export { lookupCost, calculateCostUsd } from "@/providers/_cost_table";
export type { ModelCostEntry } from "@/providers/_cost_table";
export { getProvider, registerProvider } from "@/providers/registry";
export {
  openai,
  anthropic,
  openrouter,
  kimi,
  gemini,
  type OpenRouterFactoryOptions,
  type GeminiFactoryOptions,
} from "@/providers/factory";

// Auth
export { type SecretSource, EnvSecretSource } from "@/auth/secret_source";

// Integrations
export {
  BoundTool,
  functionTool,
  type FunctionToolHandler,
  type FunctionToolMeta,
  Integration,
  tool,
} from "@/integrations";

// Runtime
export {
  AgentRuntime,
  type AgentRuntimeOptions,
  type AgentStrategy,
  type RunTurnOptions,
} from "@/runtime/runtime";
export { CancellationToken } from "@/runtime/cancellation";
export { AgentBuilder, type Integrable, type AgentBuilderBuildOptions } from "@/runtime/builder";
export {
  generateText,
  streamText,
  type GenerateTextOptions,
  type StreamTextResult,
} from "@/runtime/oneshot";

// Approval handlers
export type {
  TypedApprovalHandler,
  ApprovalDecision,
  ToolContext as ApprovalContext,
  ApprovalRequest,
} from "@/runtime/approval/types";
export { EventApprovalHandler } from "@/runtime/approval/event_handler";
export { AutoApprovalHandler, type AutoApprovalPolicy } from "@/runtime/approval/auto";
