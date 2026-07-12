/** Redaction-safe rendering for `kaji replay`. */
import { createHash } from "node:crypto";
import type { KajiEvent, StoredKajiEvent } from "@/events/schemas";
import { EventType } from "@/events/types";
import {
  closedRecoveryFields,
  recoveryForReason,
  type IntegrationRecoveryReason,
} from "@/integrations/recovery";

type RenderableEvent = KajiEvent | StoredKajiEvent;

export interface RenderOptions {
  color?: boolean;
}

export interface SafeReplayEvent {
  type: string;
  id: string;
  version: string;
  timestamp: number;
  session_id: string;
  turn_id?: string;
  sequence?: number;
  tool_name?: string;
  tool_call_id?: string;
  error_code?: string;
  error_path?: string;
  phase?: string;
  retryable?: boolean;
  outcome?: string;
  reason_code?: IntegrationRecoveryReason;
  recovery_code?: string;
  doc_url?: string;
}

const SAFE_EVENT_TYPES = new Set<string>(Object.values(EventType));
/** Kept byte-for-byte in order with contracts/errors/error-codes.json by tests. */
export const REPLAY_SAFE_ERROR_CODES = [
  "INVALID_TOOL_SCHEMA",
  "INVALID_TOOL_ARGUMENTS",
  "INVALID_DURABLE_VALUE",
  "INVALID_TOOL_RESULT",
  "UNCLASSIFIED_TOOL_RISK",
  "MISSING_TOOL_IDENTITY",
  "TOOL_NOT_ALLOWED",
  "APPROVAL_UNAVAILABLE",
  "APPROVAL_REJECTED",
  "APPROVAL_TIMEOUT",
  "TOOL_CANCELLED",
  "TOOL_TIMEOUT",
  "TOOL_EXECUTION_FAILED",
  "TOOL_START_RECORD_FAILED",
  "EVENT_APPEND_FAILED",
  "EVENT_PUBLISH_FAILED",
  "EVENT_ID_CONFLICT",
  "EVENT_BUFFER_OVERFLOW",
  "EVENT_PAYLOAD_TOO_LARGE",
  "EVENT_SCHEMA_INCOMPATIBLE",
  "EVENT_STORE_CAPACITY_EXCEEDED",
  "IDEMPOTENCY_CAPACITY_EXCEEDED",
  "IDEMPOTENCY_CONFLICT",
  "PROVIDER_API_ERROR",
  "PROVIDER_AUTH_ERROR",
  "PROVIDER_CONFIG_ERROR",
  "PROVIDER_NETWORK_ERROR",
  "PROVIDER_RATE_LIMITED",
  "PROVIDER_OUTPUT_LIMIT",
  "PROVIDER_CANCELLATION_CONTRACT_VIOLATION",
  "TURN_TIMEOUT",
  "INTEGRATION_SCHEMA_INVALID",
  "INTEGRATION_ABI_MISMATCH",
  "INTEGRATION_EXPERIMENTAL",
  "INTEGRATION_API_ERROR",
  "INTEGRATION_AUTH_REQUIRED",
  "INTEGRATION_AUTH_ERROR",
  "INTEGRATION_RATE_LIMITED",
  "INTEGRATION_POLICY_REJECTED",
  "INTEGRATION_REDIRECT_REJECTED",
  "INTEGRATION_RESPONSE_LIMIT",
] as const;
const SAFE_ERROR_CODES = new Set<string>(REPLAY_SAFE_ERROR_CODES);
const SAFE_PHASES = new Set(["queue", "provider_open", "provider_stream", "approval", "tool"]);
const SAFE_OUTCOMES = new Set(["not_started", "failed", "unknown"]);

function safeLiteral(value: string, allowed: ReadonlySet<string>, fallback: string): string {
  return allowed.has(value) ? value : fallback;
}

function pseudonym(kind: string, value: string): string {
  const digest = createHash("sha256").update(kind).update("\0").update(value).digest("hex");
  return `${kind}_${digest.slice(0, 16)}`;
}

function boundedTimestamp(value: number): number {
  return Number.isFinite(value) && value >= 0 && value <= Number.MAX_SAFE_INTEGER ? value : 0;
}

function boundedSequence(value: number): number {
  return Number.isSafeInteger(value) && value > 0 ? value : 0;
}

function palette(enabled: boolean) {
  const code = (value: string) => (enabled ? value : "");
  return {
    reset: code("\x1b[0m"),
    bold: code("\x1b[1m"),
    dim: code("\x1b[2m"),
    cyan: code("\x1b[36m"),
    green: code("\x1b[32m"),
    yellow: code("\x1b[33m"),
    red: code("\x1b[31m"),
    gray: code("\x1b[90m"),
  } as const;
}

/** Keep this allowlist closed. Never add prompt, payload, metadata, or raw-cause fields. */
export function safeReplayEvent(event: RenderableEvent): SafeReplayEvent {
  const safe: SafeReplayEvent = {
    type: safeLiteral(event.type, SAFE_EVENT_TYPES, "event.unknown"),
    id: pseudonym("event", event.id),
    version: event.version === "1.0" ? "1.0" : "unknown",
    timestamp: boundedTimestamp(event.timestamp),
    session_id: pseudonym("session", event.session_id),
  };
  if (event.turn_id !== undefined) safe.turn_id = pseudonym("turn", event.turn_id);
  if ("sequence" in event && event.sequence !== undefined) {
    safe.sequence = boundedSequence(event.sequence);
  }
  if ("tool_name" in event && typeof event.tool_name === "string") {
    safe.tool_name = pseudonym("tool", event.tool_name);
  }
  if ("tool_call_id" in event && typeof event.tool_call_id === "string") {
    safe.tool_call_id = pseudonym("call", event.tool_call_id);
  }
  if ("error_code" in event && typeof event.error_code === "string") {
    safe.error_code = safeLiteral(event.error_code, SAFE_ERROR_CODES, "OTHER");
  }
  if ("error_path" in event && typeof event.error_path === "string") {
    safe.error_path = pseudonym("path", event.error_path);
  }
  if ("phase" in event && typeof event.phase === "string") {
    safe.phase = safeLiteral(event.phase, SAFE_PHASES, "unknown");
  }
  if ("retryable" in event && typeof event.retryable === "boolean") {
    safe.retryable = event.retryable;
  }
  if ("outcome" in event && typeof event.outcome === "string") {
    safe.outcome = safeLiteral(event.outcome, SAFE_OUTCOMES, "unknown");
  }
  const recovery = closedRecoveryFields(event);
  if (recovery !== undefined) Object.assign(safe, recovery);
  return safe;
}

function sequenceRange(events: readonly SafeReplayEvent[]): string {
  const sequences = events.map((event) => event.sequence);
  if (sequences.some((sequence) => sequence === undefined)) return "";
  return `, seq=${sequences[0]}-${sequences[sequences.length - 1]}`;
}

function groupBySession(events: readonly SafeReplayEvent[]) {
  const groups = new Map<string, SafeReplayEvent[]>();
  for (const event of events) {
    const group = groups.get(event.session_id);
    if (group === undefined) groups.set(event.session_id, [event]);
    else group.push(event);
  }
  return [...groups.entries()];
}

function label(event: SafeReplayEvent): string {
  if (event.type === EventType.USER_MESSAGE) return "USER";
  if (
    event.type === EventType.AGENT_MESSAGE_DELTA ||
    event.type === EventType.AGENT_MESSAGE_COMPLETED
  ) {
    return "ASSISTANT";
  }
  if (event.type.startsWith("tool.")) return "TOOL";
  return "EVENT";
}

const RECOVERY_HINTS: Record<string, string> = {
  INVALID_TOOL_RESULT: "fix the durable tool result; do not automatically retry external effects",
  TURN_TIMEOUT: "inspect phase and outcome before deciding whether to retry",
  PROVIDER_CANCELLATION_CONTRACT_VIOLATION:
    "drain and replace the provider; restart if the operation never settles",
  PROVIDER_OUTPUT_LIMIT: "reduce provider output or schema size",
  INTEGRATION_ABI_MISMATCH: "update manifest/runtime metadata and rerun the ABI checker",
};

function diagnostic(event: SafeReplayEvent): string {
  if (event.error_code === undefined) return "";
  const fields = [
    `code=${event.error_code}`,
    ...(event.tool_name === undefined ? [] : [`tool=${event.tool_name}`]),
    ...(event.error_path === undefined ? [] : [`path=${event.error_path}`]),
    ...(event.phase === undefined ? [] : [`phase=${event.phase}`]),
    ...(event.retryable === undefined ? [] : [`retryable=${event.retryable}`]),
    ...(event.outcome === undefined ? [] : [`outcome=${event.outcome}`]),
  ];
  const hint = RECOVERY_HINTS[event.error_code];
  if (hint !== undefined) fields.push(`recovery=${hint}`);
  if (event.reason_code !== undefined) {
    const recovery = recoveryForReason(event.reason_code);
    fields.push(
      `reason=${event.reason_code}`,
      `recovery=${event.recovery_code}`,
      `doc=${event.doc_url}`,
      `problem=${JSON.stringify(recovery.problem)}`,
      `cause=${JSON.stringify(recovery.cause)}`,
      `fix=${JSON.stringify(recovery.fix)}`,
    );
  }
  return ` ${fields.join(" ")}`;
}

export function renderTree(
  events: readonly RenderableEvent[],
  options: RenderOptions = {},
): string {
  const safeEvents = events.map(safeReplayEvent);
  if (safeEvents.length === 0) return "";
  const color = options.color ?? true;
  const c = palette(color);
  const lines: string[] = [];
  for (const [sessionId, grouped] of groupBySession(safeEvents)) {
    lines.push(
      `${c.bold}${c.cyan}Session ${sessionId}${c.reset} ` +
        `${c.dim}(${grouped.length} events${sequenceRange(grouped)})${c.reset}`,
    );
    for (const event of grouped) {
      const tint = label(event) === "USER" ? c.green : label(event) === "TOOL" ? c.yellow : c.cyan;
      lines.push(
        `  ${tint}${label(event)}${c.reset} ${c.gray}[${event.type}]${c.reset}${diagnostic(event)}`,
      );
    }
  }
  return lines.join("\n");
}

export function renderSummary(
  events: readonly RenderableEvent[],
  options: RenderOptions = {},
): string {
  const safeEvents = events.map(safeReplayEvent);
  if (safeEvents.length === 0) return "";
  const c = palette(options.color ?? true);
  return groupBySession(safeEvents)
    .map(([sessionId, grouped]) => {
      const turns = grouped.filter((event) => event.type === EventType.USER_MESSAGE).length;
      const toolCalls = grouped.filter(
        (event) => event.type === EventType.TOOL_CALL_REQUESTED,
      ).length;
      const errors = grouped.filter(
        (event) =>
          event.type === EventType.AGENT_TURN_FAILED || event.type === EventType.TOOL_CALL_FAILED,
      ).length;
      return (
        `${c.bold}Session ${sessionId}${c.reset}  turns=${turns}  ` +
        `tool_calls=${toolCalls}  errors=${errors}${sequenceRange(grouped)}`
      );
    })
    .join("\n");
}

export function renderJson(events: readonly RenderableEvent[]): string {
  return JSON.stringify(events.map(safeReplayEvent), null, 2);
}
