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

export const VERSION = "0.2.0-beta.1";

// Events
export { EventType } from "@/events/types";
export {
  AgentTurnFailed,
  KajiEvent,
  NewKajiEvent,
  SessionCreated,
  StoredKajiEvent,
  validateNewEvent,
  validateStoredEvent,
  type KajiEventInput,
  type BaseEvent,
} from "@/events/schemas";
export { EventBus } from "@/events/bus";
export { type EventBusProtocol, type EventCommitter } from "@/events/protocols";
export {
  InMemoryEventCommitter,
  SplitEventCommitter,
  type InMemoryEventCommitterOptions,
  type SplitEventCommitterOptions,
} from "@/events/committer";
export {
  DurableJsonLimitError,
  EventBufferOverflowError,
  EventDeliveryError,
  EventIdConflictError,
  EventSchemaIncompatibleError,
  EventStoreCapacityError,
  InvalidDurableValueError,
} from "@/events/errors";
export { type EventStore, InMemoryEventStore } from "@/events/store";

// Sessions
export {
  replayLegacySession,
  replaySession,
  applyEvent,
  approvalKey,
  type ApprovalFailureCode,
  type ApprovalKey,
  type SessionState,
  type Message,
  type SessionTokens,
} from "@/sessions/replay";
export { SessionProjector } from "@/sessions/projector";
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
  UnclassifiedToolRiskError,
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
export {
  ToolArgumentValidationError,
  ToolSchemaValidationError,
  ToolSchemaValidator,
  ToolValidationError,
  type ToolExecutionOutcome,
  type ToolValidationCode,
} from "@/tools/validation";
export { cliApprovalHandler, type CliApprovalOptions } from "@/tools/approval";
export {
  DEFAULT_TOOL_EXECUTION_LIMITS,
  ToolExecutionController,
  type ToolExecutionControllerOptions,
  type ToolExecutionControllerOutcome,
  type ToolExecutionLimits,
  type ToolExecutionRequest,
} from "@/tools/execution";
export {
  IdempotencyCapacityError,
  IdempotencyConflictError,
  ToolExecutionError,
  type ToolFailureFields,
  type ToolFailureOutcome,
} from "@/tools/execution-errors";
export {
  InMemoryToolIdempotencyLedger,
  type InMemoryToolIdempotencyLedgerOptions,
  type ToolClaimResult,
  type ToolIdempotencyClaim,
  type ToolIdempotencyLedger,
  type ToolLedgerOutcome,
} from "@/tools/idempotency";

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
  normalizeProviderError,
  ProviderAPIError,
  ProviderConfigError,
  ProviderConnectionError,
  ProviderError,
  ProviderRateLimitedError,
} from "@/providers/errors";
export type { NormalizedProviderError } from "@/providers/errors";
export { lookupCost, calculateCostUsd } from "@/providers/costs";
export type { ModelCostEntry } from "@/providers/costs";
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
export { type SecretSource, EnvSecretSource } from "@/auth/source";

// Integrations
export {
  BoundTool,
  functionTool,
  type FunctionToolHandler,
  type FunctionToolMeta,
  Integration,
  tool,
  formatIntegrationError,
  IndexValidationError,
  IntegrationExperimentalError,
  IntegrationNotFoundError,
  IntegrationValidationError,
  loadManifest,
  loadRegistryIndex,
  ManifestValidationError,
  validateIndexDocument,
  validateManifestDocument,
  type IntegrationAuth,
  type IntegrationManifestDocument,
  type IntegrationManifestTool,
  type IntegrationRuntime,
  type IntegrationStability,
  type IntegrationToolRisk,
  type IntegrationValidationCode,
  type LoadedIntegrationManifest,
  type NormalizedIntegrationValidationError,
  type RegistryIndexDocument,
  type RegistryIndexEntry,
  type RegistryLoaderOptions,
  safeRequest,
  type BoundedResponse,
  type BoundNetworkTransport,
  type SafeFetchPolicy,
} from "@/integrations";

// Runtime
export {
  AgentRuntime,
  type EffectiveRuntimeLimits,
  type AgentRuntimeOptions,
  type AgentStrategy,
  type RunTurnOptions,
  type TurnOptions,
  type TurnResult,
} from "@/runtime/runtime";
export {
  ContextIntegrityError,
  ContextWindowOverflowError,
  DEFAULT_CONTEXT_WINDOW,
  MissingToolIdentityError,
  type ContextDiagnostics,
  type ContextWindow,
  type ToolExecutionContext,
  type TurnContext,
} from "@/runtime/context";
export {
  CancellationError,
  CancellationToken,
  throwIfCancellationRequested,
  type CancellationTokenLike,
} from "@/runtime/cancellation";
export { AgentBuilder, type Integrable, type AgentBuilderBuildOptions } from "@/runtime/builder";
export type { Clock, IdFactory, IdScope, UuidFactory } from "@/internal/uuid";
export {
  InMemorySessionTurnCoordinator,
  type ObservableCancellationToken,
  type SessionTurnCoordinator,
} from "@/runtime/session-turn-coordinator";
export {
  generateText,
  streamText,
  type GenerateTextOptions,
  type StreamTextResult,
} from "@/runtime/oneshot";

// Approval handlers
export type {
  TypedApprovalHandler,
  EventBackedApprovalHandler,
  ApprovalRequest,
  ApprovalRequestContext,
  ApprovalRejectionCode,
  EventApprovalContext,
  ApprovalRequestContext as ApprovalContext,
  ApprovalDecision,
  LegacyApprovalHandler,
  ToolContext as TypedApprovalContext,
} from "@/runtime/approval/types";
export { adaptLegacyApprovalHandler } from "@/runtime/approval/types";
export { EventApprovalHandler, type EventApprovalHandlerOptions } from "@/runtime/approval/handler";
export { AutoApprovalHandler, type AutoApprovalPolicy } from "@/runtime/approval/auto";

// Observability
export {
  NOOP_METRICS,
  NOOP_TRACE,
  METRIC_NAMES,
  providerFamily,
  recordMetric,
  startSpan,
  type JournalStage,
  type MetricLabels,
  type MetricMeasurement,
  type MetricName,
  type MetricsSink,
  type ProviderFamily,
  type ProviderStatus,
  type SpanName,
  type SubscriberStage,
  type ToolMetricOutcome,
  type TraceAttributeName,
  type TraceAttributeValue,
  type TraceAttributes,
  type TraceSink,
  type TraceSpan,
  type TurnOutcome,
} from "@/observability";
