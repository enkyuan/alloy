import { StoredKajiEvent } from "../src/events/schemas";
import { EventType } from "../src/events/types";
import { SessionProjector } from "../src/sessions/projector";
import { applyEvent, createSessionState } from "../src/sessions/replay";

const mode = process.argv[2];
const projector = mode === "indexed" ? new SessionProjector("rss") : undefined;
const state = projector === undefined ? createSessionState("rss") : undefined;
let sequence = 0;

function apply(input: Record<string, unknown>): void {
  const event = StoredKajiEvent.parse({
    id: `rss-${++sequence}`,
    version: "1.0",
    timestamp: sequence,
    session_id: "rss",
    sequence,
    ...input,
  });
  if (projector === undefined) applyEvent(state!, event);
  else projector.apply(event);
}

for (let batch = 0; batch < 2_000; batch++) {
  const callId = `call-${batch}`;
  apply({ type: EventType.USER_MESSAGE, content: String(batch) });
  apply({ type: EventType.AGENT_REASONING_STARTED });
  apply({
    type: EventType.TOOL_CALL_REQUESTED,
    turn_id: `turn-${batch}`,
    tool_name: "lookup",
    tool_call_id: callId,
    tool_args: { batch },
  });
  apply({
    type: EventType.TOOL_CALL_COMPLETED,
    turn_id: `turn-${batch}`,
    tool_name: "lookup",
    tool_call_id: callId,
    result: { ok: true },
  });
  apply({ type: EventType.AGENT_MESSAGE_COMPLETED, content: `done-${batch}` });
}

if (typeof Bun !== "undefined") Bun.gc(true);
const projected = projector?.state ?? state!;
const rawMaxRss = process.resourceUsage().maxRSS;
const currentRssBytes = process.memoryUsage().rss;
const maxRssBytes = rawMaxRss >= currentRssBytes / 8 ? rawMaxRss : rawMaxRss * 1_024;
console.log(
  JSON.stringify({
    rss: maxRssBytes,
    rawMaxRss,
    currentRssBytes,
    messages: projected.messages.length,
  }),
);
