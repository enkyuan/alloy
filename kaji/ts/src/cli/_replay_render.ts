/**
 * Pure rendering functions for `kaji replay`. No file I/O here —
 * all renderers accept parsed KajiEvent[] and return a string.
 */
import type { KajiEvent } from "../events/schemas";
import { EventType } from "../events/types";

const C = {
  reset: "\x1b[0m",
  bold: "\x1b[1m",
  dim: "\x1b[2m",
  cyan: "\x1b[36m",
  green: "\x1b[32m",
  yellow: "\x1b[33m",
  red: "\x1b[31m",
  magenta: "\x1b[35m",
  blue: "\x1b[34m",
  gray: "\x1b[90m",
} as const;

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

function fmtTimestamp(ts: number): string {
  return new Date(ts * 1000).toISOString();
}

function failureColor(errorMsg: string): string {
  const lc = errorMsg.toLowerCase();
  if (lc.includes("validation_error") || lc.includes("validation error"))
    return C.yellow;
  if (lc.includes("policy_denied") || lc.includes("policy denied"))
    return C.magenta;
  if (lc.includes("approval_rejected") || lc.includes("approval rejected"))
    return C.blue;
  return C.red;
}

interface SessionGroup {
  sessionId: string;
  events: KajiEvent[];
}

function groupBySessions(events: KajiEvent[]): SessionGroup[] {
  const map = new Map<string, KajiEvent[]>();
  for (const e of events) {
    const list = map.get(e.session_id) ?? [];
    list.push(e);
    map.set(e.session_id, list);
  }
  const groups: SessionGroup[] = [];
  for (const [sessionId, evts] of map) {
    groups.push({ sessionId, events: evts });
  }
  return groups;
}

interface ToolCallInfo {
  toolName: string;
  toolArgs: Record<string, unknown>;
  requestTs: number;
  completionTs: number | undefined;
  result: unknown;
  error: string | undefined;
  status: "pending" | "completed" | "failed";
}

/**
 * Render events as a human-readable turn tree grouped by session.
 * Events in a session are grouped into turns starting at each USER_MESSAGE.
 */
export function renderTree(events: KajiEvent[]): string {
  if (events.length === 0) return "";
  const groups = groupBySessions(events);
  const lines: string[] = [];

  for (const { sessionId, events: sevents } of groups) {
    const firstTs = sevents[0]!.timestamp;
    const lastTs = sevents[sevents.length - 1]!.timestamp;
    const durationS = (lastTs - firstTs).toFixed(3);
    lines.push(
      `${C.bold}${C.cyan}Session ${sessionId}${C.reset} ` +
        `${C.dim}(${durationS}s, ${sevents.length} events)${C.reset}`,
    );

    // Group into turns starting at each USER_MESSAGE
    const turns: Array<{ startTs: number; events: KajiEvent[] }> = [];
    let currentTurn: { startTs: number; events: KajiEvent[] } | null = null;

    for (const e of sevents) {
      if (e.type === EventType.USER_MESSAGE) {
        currentTurn = { startTs: e.timestamp, events: [e] };
        turns.push(currentTurn);
      } else if (currentTurn !== null) {
        currentTurn.events.push(e);
      }
    }

    if (turns.length === 0) {
      // Session with no user messages — show all events as [type]
      for (const e of sevents) {
        lines.push(`  ${C.gray}[${e.type}]${C.reset}`);
      }
      continue;
    }

    for (let ti = 0; ti < turns.length; ti++) {
      const turn = turns[ti]!;
      lines.push(
        `  ${C.bold}Turn ${ti + 1}${C.reset} ` +
          `${C.gray}[${fmtTimestamp(turn.startTs)}]${C.reset}`,
      );

      // Pre-collect tool call info so TOOL_CALL_REQUESTED can render result inline
      const toolCalls = new Map<string, ToolCallInfo>();
      for (const e of turn.events) {
        if (e.type === EventType.TOOL_CALL_REQUESTED) {
          toolCalls.set(e.tool_call_id, {
            toolName: e.tool_name,
            toolArgs: e.tool_args,
            requestTs: e.timestamp,
            completionTs: undefined,
            result: undefined,
            error: undefined,
            status: "pending",
          });
        } else if (e.type === EventType.TOOL_CALL_COMPLETED) {
          const info = toolCalls.get(e.tool_call_id);
          if (info !== undefined) {
            info.completionTs = e.timestamp;
            info.result = e.result;
            info.status = "completed";
          }
        } else if (e.type === EventType.TOOL_CALL_FAILED) {
          const info = toolCalls.get(e.tool_call_id);
          if (info !== undefined) {
            info.completionTs = e.timestamp;
            info.error = e.error;
            info.status = "failed";
          }
        }
      }

      let deltaBuffer = "";
      let assistantShown = false;

      const flushDelta = (): void => {
        if (deltaBuffer && !assistantShown) {
          lines.push(`    ${C.cyan}ASSISTANT${C.reset}: ${deltaBuffer}`);
          assistantShown = true;
          deltaBuffer = "";
        }
      };

      for (const e of turn.events) {
        switch (e.type) {
          // Structural / transient events — no output
          case EventType.SESSION_CREATED:
          case EventType.SESSION_CLOSED:
          case EventType.AGENT_REASONING_STARTED:
          case EventType.TOOL_CALL_STARTED:
          case EventType.TOOL_CALL_COMPLETED: // rendered via TOOL_CALL_REQUESTED
          case EventType.TOOL_CALL_FAILED: // rendered via TOOL_CALL_REQUESTED
          case EventType.TOOL_APPROVAL_APPROVED:
          case EventType.TOOL_APPROVAL_REJECTED:
            break;

          case EventType.USER_MESSAGE:
            lines.push(`    ${C.green}USER${C.reset}: ${e.content}`);
            break;

          case EventType.AGENT_MESSAGE_DELTA:
            deltaBuffer += e.delta;
            break;

          case EventType.AGENT_MESSAGE_COMPLETED:
            deltaBuffer = "";
            if (!assistantShown) {
              lines.push(`    ${C.cyan}ASSISTANT${C.reset}: ${e.content}`);
              assistantShown = true;
            }
            break;

          case EventType.TOOL_CALL_REQUESTED: {
            flushDelta();
            const info = toolCalls.get(e.tool_call_id);
            const argsJson = truncate(JSON.stringify(e.tool_args), 80);

            if (info?.status === "completed") {
              const resultStr = truncate(JSON.stringify(info.result), 60);
              const durMs =
                info.completionTs !== undefined
                  ? Math.round((info.completionTs - e.timestamp) * 1000)
                  : null;
              const durStr = durMs !== null ? ` in ${durMs}ms` : "";
              lines.push(
                `    ${C.yellow}TOOL${C.reset}: ${C.bold}${e.tool_name}${C.reset}` +
                  `(${C.dim}${argsJson}${C.reset}) → ${C.dim}${resultStr}${C.reset}`,
              );
              lines.push(`      ${C.green}✓ completed${durStr}${C.reset}`);
            } else if (info?.status === "failed" && info.error !== undefined) {
              const fColor = failureColor(info.error);
              const durMs =
                info.completionTs !== undefined
                  ? Math.round((info.completionTs - e.timestamp) * 1000)
                  : null;
              const durStr = durMs !== null ? ` (${durMs}ms)` : "";
              lines.push(
                `    ${C.yellow}TOOL${C.reset}: ${C.bold}${e.tool_name}${C.reset}` +
                  `(${C.dim}${argsJson}${C.reset})`,
              );
              lines.push(
                `      ${fColor}✗ failed${durStr}: ${info.error}${C.reset}`,
              );
            } else {
              // Still pending or no completion tracked
              lines.push(
                `    ${C.yellow}TOOL${C.reset}: ${C.bold}${e.tool_name}${C.reset}` +
                  `(${C.dim}${argsJson}${C.reset})`,
              );
            }
            break;
          }

          case EventType.TOOL_APPROVAL_REQUESTED: {
            flushDelta();
            lines.push(
              `    ${C.magenta}TOOL_APPROVAL_REQUESTED${C.reset}: ` +
                `${e.tool_name} ${C.dim}(awaiting approval)${C.reset}`,
            );
            break;
          }

          // Less-common events — show as [type] in gray
          case EventType.USER_AUDIO_CHUNK:
          case EventType.TRANSCRIPT_PARTIAL:
          case EventType.TRANSCRIPT_FINAL:
          case EventType.MEMORY_RETRIEVAL_STARTED:
          case EventType.MEMORY_RETRIEVAL_COMPLETED:
          case EventType.WORKFLOW_STARTED:
          case EventType.WORKFLOW_COMPLETED:
          case EventType.WORKFLOW_FAILED:
          case EventType.CANCELLATION_REQUESTED:
          case EventType.CANCELLATION_COMPLETED:
            lines.push(`    ${C.gray}[${e.type}]${C.reset}`);
            break;

          case EventType.PROVIDER_RATE_LIMITED:
            lines.push(
              `    ${C.yellow}[rate-limited] provider=${e.provider} ` +
                `retry=${e.retry_after_ms}ms attempt=${e.attempt}${C.reset}`,
            );
            break;

          default: {
            // Exhaustive guard — fails at compile time if a new EventType is added
            const _: never = e;
            void _;
            break;
          }
        }
      }

      flushDelta();
    }
  }

  return lines.join("\n");
}

/**
 * One-liner summary per session: turns, tool calls, errors, duration.
 */
export function renderSummary(events: KajiEvent[]): string {
  if (events.length === 0) return "";
  const groups = groupBySessions(events);
  const lines: string[] = [];

  for (const { sessionId, events: sevents } of groups) {
    const turns = sevents.filter((e) => e.type === EventType.USER_MESSAGE).length;
    const toolCalls = sevents.filter(
      (e) => e.type === EventType.TOOL_CALL_REQUESTED,
    ).length;
    const errors = sevents.filter(
      (e) => e.type === EventType.TOOL_CALL_FAILED,
    ).length;
    const firstTs = sevents[0]!.timestamp;
    const lastTs = sevents[sevents.length - 1]!.timestamp;
    const durationS = (lastTs - firstTs).toFixed(3);
    lines.push(
      `${C.bold}Session ${sessionId}${C.reset}  ` +
        `turns=${turns}  tool_calls=${toolCalls}  errors=${errors}  duration=${durationS}s`,
    );
  }

  return lines.join("\n");
}

/** Raw JSON dump of the event array, indented for readability. */
export function renderJson(events: KajiEvent[]): string {
  return JSON.stringify(events, null, 2);
}
