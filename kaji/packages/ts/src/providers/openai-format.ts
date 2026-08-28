import type OpenAI from "openai";
import type { ProviderMessage } from "@/providers/base";

export type OpenAIChatMessage = OpenAI.Chat.Completions.ChatCompletionMessageParam;

/** @internal */
export function toOpenAIChatMessages(messages: ProviderMessage[]): OpenAIChatMessage[] {
  return messages.map<OpenAIChatMessage>((m) => {
    if (m.role === "tool") {
      return {
        role: "tool",
        content: m.content,
        tool_call_id: m.tool_call_id ?? "",
      };
    }
    if (m.role === "assistant" && m.toolCalls?.length) {
      return {
        role: "assistant",
        content: m.content,
        tool_calls: m.toolCalls.map((tc) => ({
          id: tc.id,
          type: "function" as const,
          function: {
            name: tc.name,
            arguments: JSON.stringify(tc.args ?? {}),
          },
        })),
      };
    }
    return { role: m.role, content: m.content };
  });
}
