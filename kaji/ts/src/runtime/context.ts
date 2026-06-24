/**
 * Build the provider message list from replayed session state. Mirrors the
 * message construction in `kaji.runtime.agents.runtime`.
 */
import type { ProviderMessage } from "../providers/base";
import type { Message } from "../sessions/replay";

export function buildMessages(messages: Message[], systemPrompt?: string): ProviderMessage[] {
  const result: ProviderMessage[] = [];
  if (systemPrompt) {
    result.push({ role: "system", content: systemPrompt });
  }
  for (const m of messages) {
    if (m.role === "tool") {
      result.push({
        role: "tool",
        content: m.content,
        name: m.name,
        // H3: use the real tool_call_id threaded through replay. Fall back to
        // the name only if an older event lacks it.
        tool_call_id: m.toolCallId ?? m.name ?? "unknown",
      });
    } else {
      result.push({ role: m.role, content: m.content });
    }
  }
  return result;
}
