# Python and TypeScript API parity

Wire objects use `snake_case` in both SDKs. Host-language APIs keep Python
snake case and TypeScript camel case. Duration values end in timeout units;
absolute deadlines are named explicitly.

| Concept                | Python                                                  | TypeScript                                              | Unit/wire note                                                      |
| ---------------------- | ------------------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------- |
| Builder                | `AgentBuilder`                                          | Removed with the capability cut                         | Fluent, scoped runtime (Python)                                     |
| Turn                   | `runtime.turn()`                                        | Removed with the capability cut                         | Returns text, turn, and stored events (Python)                      |
| Capability execution    | `Kaji.execute` planned (v0.4 gate)                       | `Kaji.execute` / `kajiExecute`                          | one-shot `Capability` dispatch through the planner                   |
| Caller context         | `TurnContext`                                           | `TurnContext`                                           | Wire fields remain snake case                                       |
| Absolute deadline      | `deadline_monotonic`                                    | `deadlineAtMs`                                          | monotonic seconds vs epoch milliseconds                             |
| Duration helper        | add seconds to `time.monotonic()`                       | `deadlineAfter(timeoutMs)`                              | never use removed `deadlineMs`                                      |
| Effective limits       | `runtime.effective_limits()`                            | Removed with the capability cut                         | configured 120-second work timeout plus 5-second cancellation grace |
| Tool context           | `ToolExecutionContext`                                  | `ToolExecutionContext`                                  | immutable identity/deadline context                                 |
| Provider error         | `normalize_provider_error`                              | Removed with the capability cut                         | closed code/retry/outcome fields (Python)                           |
| Drain                  | `drain_providers()`                                     | Removed with the capability cut                         | required after provider quarantine (Python)                         |
| Purge                  | `runtime.purge_session()`                               | `PurgeableEventStore`, `supportsSessionPurge()`         | explicit, session-scoped generation teardown                        |
| Store purge capability | `PurgeableEventStore`, `supports_session_purge()`       | `PurgeableEventStore`, `supportsSessionPurge()`         | public one-argument capability; runtime coordination stays internal |
| Purge failures         | `SessionPurgeBusyError`, `SessionPurgeUnsupportedError` | `SessionPurgeBusyError`, `SessionPurgeUnsupportedError` | same closed busy/unsupported boundary                               |
| Close                  | `close()`                                               | `close()`                                               | rejects new work; cannot kill hostile in-process code               |

The supported in-memory lifecycle is identical across SDKs: capacity fails
closed until explicit purge; shared owners and direct store operations are
fenced; old subscribers terminate; successful reuse resets the cursor to `0`
and begins again at sequence `1`; failed post-delete cleanup retains a tombstone
until a runtime retry converges. Split delivery and public-only custom stores
are purge-unsupported at the coordinated runtime boundary. `TurnAccounting` was
removed with the TypeScript capability cut and is not part of purge parity.

The executable Echo lifecycle is maintained once in the marked Python and
TypeScript quickstarts in [production-beta.md](production-beta.md). Both use
stored events, tool execution, stored sequence, and terminal-result lifecycle
semantics. Protected OpenAI proof must exercise that lifecycle in Python before
release. Anthropic, Gemini, and Kimi remain available on the Python side as
opt-in experimental/WIP adapters without a beta compatibility or
publication-proof commitment; OpenRouter is Python-only catalog metadata.

The lists below are generated from the machine contract and checked against
Python `kaji.__all__` and fresh built TypeScript declarations.

<!-- public-exports:python:start -->
### Python public exports
- Stable: `AgentBuilder`, `AgentRuntime`, `ApprovalDecision`, `ApprovalHandler`, `ApprovalRequestContext`, `ArtifactEmitted`, `ArtifactRef`, `CancellationToken`, `Capability`, `CapabilityResult`, `Clock`, `DurableJsonLimitError`, `EffectiveRuntimeLimits`, `EventApprovalHandler`, `EventBackedApprovalHandler`, `EventBufferOverflowError`, `EventDeliveryError`, `EventIdConflictError`, `EventJournal`, `EventStore`, `EventStoreCapacityError`, `IdFactory`, `IdempotencyCapacityExceeded`, `IdempotencyConflictError`, `InMemoryEventJournal`, `InMemoryEventStore`, `InMemorySessionStore`, `InMemoryToolIdempotencyLedger`, `InMemoryTurnCoordinator`, `Integration`, `InvalidDurableValueError`, `Measurement`, `MetricsSink`, `MissingToolIdentityError`, `ModelProvider`, `NOOP_METRICS`, `NOOP_TRACE`, `NewKajiEvent`, `NormalizedProviderError`, `ProviderAPIError`, `ProviderCancellationContractViolation`, `ProviderConfigError`, `ProviderConnectionError`, `ProviderError`, `ProviderOutputLimitError`, `ProviderRateLimitedError`, `ProviderResponseLimits`, `PurgeableEventStore`, `SessionManager`, `SessionPurgeBusyError`, `SessionPurgeUnsupportedError`, `SessionRecord`, `SessionState`, `SessionStore`, `SpanHandle`, `StoredKajiEvent`, `SystemClock`, `SystemIdFactory`, `ToolArgumentValidationError`, `ToolExecutionContext`, `ToolExecutionController`, `ToolExecutionError`, `ToolExecutionLimits`, `ToolIdempotencyLedger`, `ToolInvocation`, `ToolPolicy`, `ToolPolicyViolation`, `ToolRegistry`, `ToolSchemaValidationError`, `ToolSchemaValidator`, `ToolSpec`, `TraceSink`, `TurnContext`, `TurnCoordinator`, `TurnExecutionLimits`, `TurnResult`, `TurnTimeoutError`, `UnclassifiedToolRiskError`, `UnknownToolError`, `UserMessage`, `__version__`, `artifact`, `build_tools_payload`, `capability`, `capability_result`, `function_tool`, `get_provider`, `list_tool_specs`, `normalize_provider_error`, `register_provider`, `register_tool`, `replay_session`, `spec_to_neutral`, `supports_session_purge`, `to_openai`, `tool`
- Experimental: `AppendResult`, `Chunk`, `CredentialStore`, `DisconnectResult`, `Document`, `DocumentRAG`, `Embedder`, `EmbeddingCache`, `EventBus`, `GoogleOAuthClient`, `HistoryStore`, `InMemoryEventBus`, `InMemoryHistoryStore`, `InMemoryVectorStore`, `JournalEventEmitter`, `MacOSKeychainTokenStorage`, `OAuthCredentialRecord`, `OAuthTokenSet`, `SplitEventJournal`, `ToolRetriever`, `VectorStore`, `to_anthropic`, `to_gemini`
- Deprecated: none
<!-- public-exports:python:end -->

<!-- public-exports:typescript:start -->
### TypeScript public exports
- Stable: `AgentTurnFailed`, `ApprovalDeadlineSource`, `ApprovalDecision`, `ApprovalFailureCode`, `ApprovalKey`, `ApprovalRejectionCode`, `ApprovalRequestContext`, `ArtifactEmitted`, `ArtifactRef`, `AutoApprovalHandler`, `AutoApprovalPolicy`, `BaseEvent`, `CancellationError`, `CancellationToken`, `CancellationTokenLike`, `Capability`, `CapabilityDefinition`, `CapabilityResult`, `CliApprovalInput`, `CliApprovalOptions`, `CliApprovalOutput`, `Clock`, `ContextDiagnostics`, `ContextIntegrityError`, `ContextWindow`, `ContextWindowOverflowError`, `DEFAULT_CONTEXT_WINDOW`, `DEFAULT_TOOL_EXECUTION_LIMITS`, `DEFAULT_TURN_EXECUTION_LIMITS`, `DurableJsonLimitError`, `EventApprovalHandler`, `EventApprovalHandlerOptions`, `EventBackedApprovalHandler`, `EventBufferOverflowError`, `EventBusProtocol`, `EventCommitter`, `EventDeliveryError`, `EventIdConflictError`, `EventSchemaIncompatibleError`, `EventStore`, `EventStoreCapacityError`, `EventType`, `IdFactory`, `IdScope`, `IdempotencyCapacityError`, `IdempotencyConflictError`, `InMemoryBackend`, `InMemoryEventCommitter`, `InMemoryEventCommitterOptions`, `InMemoryEventStore`, `InMemorySessionStore`, `InMemorySessionTurnCoordinator`, `InMemoryToolIdempotencyLedger`, `InMemoryToolIdempotencyLedgerOptions`, `InvalidDurableValueError`, `JSONSchema`, `JournalStage`, `Kaji`, `KajiBackend`, `KajiEvent`, `KajiEventInput`, `KajiExecuteArgs`, `ListToolSpecsOptions`, `METRIC_NAMES`, `Message`, `MetricLabels`, `MetricMeasurement`, `MetricName`, `MetricsSink`, `MissingToolIdentityError`, `NOOP_METRICS`, `NOOP_TRACE`, `NewKajiEvent`, `ObservableCancellationToken`, `ProviderCancellationContractViolation`, `PurgeableEventStore`, `SessionCreated`, `SessionManager`, `SessionProjector`, `SessionPurgeBusyError`, `SessionPurgeUnsupportedError`, `SessionRecord`, `SessionState`, `SessionStore`, `SessionTokens`, `SessionTurnCoordinator`, `SessionTurnLease`, `SpanName`, `StoredKajiEvent`, `SubscriberStage`, `TimerHandle`, `TimerScheduler`, `ToolArgumentValidationError`, `ToolCallInstruction`, `ToolCallResult`, `ToolClaimResult`, `ToolExecutionContext`, `ToolExecutionController`, `ToolExecutionControllerOptions`, `ToolExecutionControllerOutcome`, `ToolExecutionError`, `ToolExecutionLimits`, `ToolExecutionOutcome`, `ToolExecutionRequest`, `ToolExecutor`, `ToolFailureFields`, `ToolFailureOutcome`, `ToolHandler`, `ToolIdempotencyClaim`, `ToolIdempotencyLedger`, `ToolLedgerOutcome`, `ToolMetricOutcome`, `ToolParameters`, `ToolPlanner`, `ToolPlannerOptions`, `ToolPolicy`, `ToolPolicyOptions`, `ToolPolicyViolation`, `ToolRegistry`, `ToolRisk`, `ToolSchemaValidationError`, `ToolSchemaValidator`, `ToolSpec`, `ToolValidationCode`, `ToolValidationError`, `TraceAttributeName`, `TraceAttributeValue`, `TraceAttributes`, `TraceSink`, `TraceSpan`, `TurnContext`, `TurnDeadlineOutcome`, `TurnExecutionLimits`, `TurnLeaseOptions`, `TurnOutcome`, `TurnPhase`, `TurnTimeoutError`, `TypedApprovalHandler`, `UnclassifiedToolRiskError`, `UnknownToolError`, `UuidFactory`, `VERSION`, `applyEvent`, `approvalKey`, `artifact`, `capability`, `capabilityResult`, `cliApprovalHandler`, `deadlineAfter`, `executeTool`, `kajiExecute`, `listToolSpecs`, `recordMetric`, `registerTool`, `replaySession`, `startSpan`, `supportsSessionPurge`, `throwIfCancellationRequested`, `toolSpecFromSchema`, `validateArtifactRef`, `validateNewEvent`, `validateStoredEvent`
- Experimental: `EventBus`, `SplitEventCommitter`, `SplitEventCommitterOptions`
- Deprecated: none
<!-- public-exports:typescript:end -->
