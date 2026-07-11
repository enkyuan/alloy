/** Dependency-free, low-cardinality observability contracts for the stable runtime. */

export type ProviderFamily = "openai" | "anthropic" | "custom";
export type SpanName = "kaji.turn" | "kaji.provider" | "kaji.tool";
export type ProviderStatus = "success" | "error" | "cancelled";
export type TurnOutcome = "completed" | "failed" | "cancelled";
export type ToolMetricOutcome =
  | "acquired"
  | "completed"
  | "failed"
  | "cancelled"
  | "timeout"
  | "not_started"
  | "unknown";
export type JournalStage = "append" | "publish";
export type SubscriberStage = "lag" | "overflow";

interface MetricLabelsByName {
  "kaji.turn.queue_wait_ms": Record<never, never>;
  "kaji.turn.duration_ms": { outcome: TurnOutcome };
  "kaji.turn.iterations": { outcome: TurnOutcome };
  "kaji.provider.duration_ms": { provider_family: ProviderFamily; status: ProviderStatus };
  "kaji.provider.retries": { provider_family: ProviderFamily };
  "kaji.replay.input_events": Record<never, never>;
  "kaji.context.messages": Record<never, never>;
  "kaji.context.characters": Record<never, never>;
  "kaji.tool.queue_wait_ms": { outcome: ToolMetricOutcome };
  "kaji.tool.active": Record<never, never>;
  "kaji.tool.duration_ms": { outcome: ToolMetricOutcome; error_code: string };
  "kaji.journal.failures": { stage: JournalStage };
  "kaji.subscriber.lag_events": Record<never, never>;
  "kaji.subscriber.overflow": { stage: SubscriberStage };
}

interface MetricUnitByName {
  "kaji.turn.queue_wait_ms": "ms";
  "kaji.turn.duration_ms": "ms";
  "kaji.turn.iterations": "count";
  "kaji.provider.duration_ms": "ms";
  "kaji.provider.retries": "count";
  "kaji.replay.input_events": "count";
  "kaji.context.messages": "count";
  "kaji.context.characters": "count";
  "kaji.tool.queue_wait_ms": "ms";
  "kaji.tool.active": "gauge";
  "kaji.tool.duration_ms": "ms";
  "kaji.journal.failures": "count";
  "kaji.subscriber.lag_events": "count";
  "kaji.subscriber.overflow": "count";
}

export type MetricName = keyof MetricLabelsByName;
export type MetricLabels<TName extends MetricName> = Readonly<MetricLabelsByName[TName]>;
export type MetricMeasurement = {
  [TName in MetricName]: Readonly<{
    name: TName;
    value: number;
    unit: MetricUnitByName[TName];
    labels: MetricLabels<TName>;
  }>;
}[MetricName];

export interface MetricsSink {
  record(measurement: MetricMeasurement): void | Promise<void>;
}

export type TraceAttributeName =
  | "principal.id"
  | "session.id"
  | "turn.id"
  | "request.id"
  | "trace.id"
  | "tool.call_id"
  | "provider.family";
export type TraceAttributeValue = string;
export type TraceAttributes = Readonly<Partial<Record<TraceAttributeName, TraceAttributeValue>>>;

export interface TraceSpan {
  setAttribute(name: TraceAttributeName, value: TraceAttributeValue): void;
  recordError(error: unknown): void;
  end(): void;
}

export interface TraceSink {
  startSpan(name: SpanName, attributes?: TraceAttributes): TraceSpan;
}

const SPAN_NAMES = new Set<SpanName>(["kaji.turn", "kaji.provider", "kaji.tool"]);
const TRACE_ATTRIBUTES = new Set<TraceAttributeName>([
  "principal.id",
  "session.id",
  "turn.id",
  "request.id",
  "trace.id",
  "tool.call_id",
  "provider.family",
]);

const METRIC_UNITS: Readonly<{ [TName in MetricName]: MetricUnitByName[TName] }> = Object.freeze({
  "kaji.turn.queue_wait_ms": "ms",
  "kaji.turn.duration_ms": "ms",
  "kaji.turn.iterations": "count",
  "kaji.provider.duration_ms": "ms",
  "kaji.provider.retries": "count",
  "kaji.replay.input_events": "count",
  "kaji.context.messages": "count",
  "kaji.context.characters": "count",
  "kaji.tool.queue_wait_ms": "ms",
  "kaji.tool.active": "gauge",
  "kaji.tool.duration_ms": "ms",
  "kaji.journal.failures": "count",
  "kaji.subscriber.lag_events": "count",
  "kaji.subscriber.overflow": "count",
});

export const METRIC_NAMES: readonly MetricName[] = Object.freeze(
  Object.keys(METRIC_UNITS) as MetricName[],
);

const ALLOWED_LABELS: Readonly<Record<MetricName, readonly string[]>> = Object.freeze({
  "kaji.turn.queue_wait_ms": [],
  "kaji.turn.duration_ms": ["outcome"],
  "kaji.turn.iterations": ["outcome"],
  "kaji.provider.duration_ms": ["provider_family", "status"],
  "kaji.provider.retries": ["provider_family"],
  "kaji.replay.input_events": [],
  "kaji.context.messages": [],
  "kaji.context.characters": [],
  "kaji.tool.queue_wait_ms": ["outcome"],
  "kaji.tool.active": [],
  "kaji.tool.duration_ms": ["outcome", "error_code"],
  "kaji.journal.failures": ["stage"],
  "kaji.subscriber.lag_events": [],
  "kaji.subscriber.overflow": ["stage"],
});

const STABLE_ERROR_CODES = new Set([
  "NONE",
  "OTHER",
  "INVALID_TOOL_SCHEMA",
  "INVALID_TOOL_ARGUMENTS",
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
  "IDEMPOTENCY_CAPACITY_EXCEEDED",
  "IDEMPOTENCY_CONFLICT",
]);

function normalizeLabel(key: string, value: unknown): string {
  const text = typeof value === "string" ? value : "";
  if (key === "provider_family") {
    return text === "openai" || text === "anthropic" ? text : "custom";
  }
  if (key === "status") {
    return text === "success" || text === "cancelled" ? text : "error";
  }
  if (key === "stage") {
    return ["append", "publish", "lag", "overflow"].includes(text) ? text : "overflow";
  }
  if (key === "error_code") return STABLE_ERROR_CODES.has(text) ? text : "OTHER";
  if (key === "outcome") {
    return [
      "acquired",
      "completed",
      "failed",
      "cancelled",
      "timeout",
      "not_started",
      "unknown",
    ].includes(text)
      ? text
      : "failed";
  }
  return "";
}

/** Record a sanitized measurement. Sink failures never affect runtime behavior. */
export function recordMetric<TName extends MetricName>(
  sink: MetricsSink,
  name: TName,
  value: number,
  labels: MetricLabels<TName>,
): void {
  if (!Number.isFinite(value)) return;
  if (sink === NOOP_METRICS) return;
  const sanitized: Record<string, string> = {};
  const allowed = ALLOWED_LABELS[name];
  for (const key of allowed) {
    const raw = (labels as Record<string, unknown>)[key];
    sanitized[key] = normalizeLabel(key, raw);
  }
  const measurement = Object.freeze({
    name,
    value,
    unit: METRIC_UNITS[name],
    labels: Object.freeze(sanitized),
  }) as MetricMeasurement;
  try {
    const pending = sink.record(measurement);
    if (pending !== undefined) void Promise.resolve(pending).catch(() => undefined);
  } catch {
    // Observability is best-effort by contract.
  }
}

const NOOP_SPAN: TraceSpan = Object.freeze({
  setAttribute: () => {},
  recordError: () => {},
  end: () => {},
});

export const NOOP_METRICS: MetricsSink = Object.freeze({ record: () => {} });
export const NOOP_TRACE: TraceSink = Object.freeze({ startSpan: () => NOOP_SPAN });

/** Start a span protected from throwing third-party sinks and span handles. */
export function startSpan(
  sink: TraceSink,
  name: SpanName,
  attributes: TraceAttributes = {},
): TraceSpan {
  if (sink === NOOP_TRACE) return NOOP_SPAN;
  if (!SPAN_NAMES.has(name)) return NOOP_SPAN;
  let safeAttributes: TraceAttributes;
  try {
    const entries = Object.entries(attributes);
    if (
      entries.some(
        ([key, value]) =>
          !TRACE_ATTRIBUTES.has(key as TraceAttributeName) || typeof value !== "string",
      )
    ) {
      return NOOP_SPAN;
    }
    safeAttributes = Object.freeze(Object.fromEntries(entries)) as TraceAttributes;
  } catch {
    return NOOP_SPAN;
  }
  let inner: TraceSpan;
  try {
    inner = sink.startSpan(name, safeAttributes);
  } catch {
    return NOOP_SPAN;
  }
  let ended = false;
  return {
    setAttribute(attributeName, value) {
      if (ended) return;
      if (!TRACE_ATTRIBUTES.has(attributeName) || typeof value !== "string") return;
      try {
        inner.setAttribute(attributeName, value);
      } catch {
        // Best-effort.
      }
    },
    recordError(error) {
      if (ended) return;
      try {
        inner.recordError(error);
      } catch {
        // Best-effort.
      }
    },
    end() {
      if (ended) return;
      ended = true;
      try {
        inner.end();
      } catch {
        // Best-effort.
      }
    },
  };
}

export function providerFamily(provider: object): ProviderFamily {
  try {
    const declared = (provider as { readonly providerFamily?: unknown }).providerFamily;
    if (declared === "openai" || declared === "anthropic" || declared === "custom") {
      return declared;
    }
    const name = provider.constructor?.name.toLowerCase() ?? "";
    if (name.includes("openai")) return "openai";
    if (name.includes("anthropic")) return "anthropic";
  } catch {
    // Observability metadata must not affect provider behavior.
  }
  return "custom";
}
