import type { AgentRuntime, StoredKajiEvent } from "kaji";

type HistoryReader = Pick<AgentRuntime, "history">;

const SAFE_EVIDENCE_FIELDS = [
  "tool_name",
  "tool_call_id",
  "error_code",
  "phase",
  "retryable",
  "outcome",
  "reason_code",
  "recovery_code",
  "doc_url",
] as const;

/** Page an exclusive sequence cursor until the reader returns an empty page. */
export async function pageHistory(
  reader: HistoryReader,
  sessionId: string,
  limit = 2,
): Promise<StoredKajiEvent[]> {
  const events: StoredKajiEvent[] = [];
  let afterSequence = 0;
  for (;;) {
    const page = await reader.history(sessionId, { afterSequence, limit });
    if (page.length === 0) return events;
    const nextSequence = page.at(-1)!.sequence;
    if (nextSequence <= afterSequence) {
      throw new Error("history cursor did not advance");
    }
    events.push(...page);
    afterSequence = nextSequence;
  }
}

/** Test-only example of the allowlist applications should derive before export. */
export function safeJournalEvidence(event: StoredKajiEvent): Readonly<Record<string, unknown>> {
  const evidence: Record<string, unknown> = {
    sequence: event.sequence,
    type: event.type,
  };
  if (event.turn_id !== undefined) evidence.turn_id = event.turn_id;
  for (const field of SAFE_EVIDENCE_FIELDS) {
    const value = Reflect.get(event, field);
    if (value !== undefined) evidence[field] = value;
  }
  return Object.freeze(evidence);
}
