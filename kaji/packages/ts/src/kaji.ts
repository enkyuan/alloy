/**
 * Kaji.execute: stable one-shot entry point for product-capability execution.
 *
 * Composes the existing `ToolRegistry` + `ToolExecutionController` + `ToolPlanner`
 * triple (the same stack that `AgentBuilder.build()` constructs) to dispatch a
 * single `Capability` through `ToolPlanner.executeBatch()`. There is no second
 * execution path; policy and approval enforcement live exclusively in the
 * planner.
 */
import { InMemoryBackend } from "@/backends/in-memory";
import type { KajiBackend } from "@/backends/base";
import { Capability } from "@/capabilities/definition";
import { isCapabilityResult, capabilityResult, type CapabilityResult } from "@/capabilities/result";
import { systemClock, systemIdFactory, systemTimerScheduler } from "@/internal/uuid";
import { type JsonValue } from "@/events/json";
import type { ToolPolicy } from "@/tools/policy";
import { ToolPlanner, type ToolCallResult, bindEmitterToCommitter } from "@/tools/planner";
import { ToolExecutionController } from "@/tools/execution";
import { ToolExecutionError } from "@/tools/execution/errors";
import { assertAbortSignal, normalizePrincipalId } from "@/runtime/context";
import { ToolRegistry } from "@/tools/registry";
import type { TypedApprovalHandler } from "@/runtime/approval/types";
import type { CancellationToken } from "@/runtime/cancellation";

/** Arguments for the one-shot {@link Kaji.execute} entry point. */
export interface KajiExecuteArgs {
  /** A declared product capability (from `capability({...})`). */
  capability: Capability;
  /** Capability arguments, validated against the capability's Zod schema. */
  input: Record<string, unknown>;
  /**
   * Caller identity. A bare string is normalized to `{ id: <principalId> }`;
   * an object must include a non-empty `id`.
   */
  principal: string | { id: string; [k: string]: unknown };
  /** Durable seams; defaults to a fresh `InMemoryBackend`. */
  backend?: KajiBackend;
  /** Optional policy override; defaults to fail-closed (unknown risk blocked). */
  policy?: ToolPolicy;
  /**
   * Optional approval handler. If a capability requires approval and no
   * handler is supplied, the call rejects with `APPROVAL_UNAVAILABLE`.
   */
  approvalHandler?: TypedApprovalHandler;
  /** Cooperative cancellation token. */
  cancellationToken?: CancellationToken;
  /**
   * Optional session id for idempotency deduplication across retries.
   * When omitted a fresh id is generated.
   */
  sessionId?: string;
  /** Caller metadata forwarded to the execution context. */
  metadata?: Record<string, unknown>;
}

/**
 * Kaji one-shot execution surface. A static, stateless entry point: all
 * collaborators are supplied per-call so a single `Kaji.execute({ ... })`
 * call needs no prior wiring.
 */
export const Kaji: { execute: typeof execute } = {
  execute,
} as const;

/** {@link Kaji.execute} under a camelCase alias. */
export { execute as kajiExecute };

/**
 * Execute a single capability through the existing planner + controller stack.
 *
 * The method composes the same `ToolRegistry` + `ToolExecutionController` +
 * `ToolPlanner` triple that `AgentBuilder.build()` does, registers the
 * capability, and dispatches one tool call via `executeBatch`. `executeBatch`
 * assembles the full `ToolExecutionContext` internally from
 * `sessionId + turnContext.principalId + signal`; it throws
 * `MissingToolIdentityError` if `principalId` is absent (fail-closed).
 *
 * @returns `CapabilityResult<T>` — already-produced results are returned as-is;
 *   plain JSON returns are wrapped with `capabilityResult()`.
 * @throws {ToolExecutionError} with an `error_code` from the planner's failure
 *   taxonomy (`APPROVAL_UNAVAILABLE`, `APPROVAL_REJECTED`, `TOOL_NOT_ALLOWED`, …).
 */
async function execute<T extends JsonValue = JsonValue>(
  args: KajiExecuteArgs,
): Promise<CapabilityResult<T>> {
  const backend = args.backend ?? new InMemoryBackend();
  const idFactory = systemIdFactory;

  // (1) Same registry + capability registration path as AgentBuilder.build().
  const registry = new ToolRegistry();
  args.capability.register(registry);
  const specs = new Map(
    registry.listSpecs({ enabledOnly: false }).map((spec) => [spec.name, spec]),
  );

  // (2) Same controller+planner composition. Policy + approval live ONLY in
  // the planner; the controller handles idempotency claims and deadlines.
  // NOTE: executionController cannot be combined with idempotencyLedger or
  // executionLimits on ToolPlannerOptions (planner.ts:393).
  const executionController = new ToolExecutionController({
    ledger: backend.idempotencyLedger,
  });
  const planner = new ToolPlanner({
    executor: (name, argv, context) => registry.execute(name, argv, context),
    policy: args.policy,
    approvalHandler: args.approvalHandler,
    specs,
    executionController,
    approvalCommitter: backend.journal,
    idFactory,
    clock: systemClock,
    timerScheduler: systemTimerScheduler,
  });

  // (3) Emit through the same committer as approvals: journal first, then
  // acknowledge. The committer must be bound so approval waiters see the
  // correct store.
  const emit = bindEmitterToCommitter((event) => backend.journal.commit(event), backend.journal);

  // (4) executeBatch builds the full ToolExecutionContext (principalId,
  // requestId, traceId, turnId, toolCallId, idempotencyKey, signal, metadata)
  // internally; it throws MissingToolIdentityError if principalId is absent.
  const sessionId = args.sessionId ?? idFactory.next("session");
  const cancellationToken = args.cancellationToken;
  const signal = cancellationToken?.signal ?? new AbortController().signal;
  assertAbortSignal(signal);

  const results = await planner.executeBatch(
    sessionId,
    [{ name: args.capability.spec.name, arguments: args.input }],
    emit,
    /* turnId */ idFactory.next("turn"),
    {
      principalId: normalizePrincipalId(args.principal),
      metadata: args.metadata ?? {},
    },
    signal,
  );

  // (5) Single-call dispatch ⇒ exactly one result. Destructure with a guard
  //     because `noUncheckedIndexedAccess` makes `call` possibly undefined.
  const call = results[0];
  if (call === undefined) {
    throw new ToolExecutionError(
      "executeBatch returned no results",
      "TOOL_EXECUTION_ERROR",
      false,
      "failed",
    );
  }
  if ("result" in call) {
    return isCapabilityResult(call.result)
      ? (call.result as CapabilityResult<T>)
      : capabilityResult(call.result as T);
  }
  throw toolExecutionErrorFromResult(call);
}

function toolExecutionErrorFromResult(
  result: Extract<ToolCallResult, { error: string }>,
): ToolExecutionError {
  const code = result.error_code ?? "TOOL_EXECUTION_ERROR";
  const retryable = result.retryable ?? false;
  const outcome = result.outcome ?? "failed";
  return new ToolExecutionError(result.error, code, retryable, outcome);
}
