/** A message shape used by session projections and tool approvals. */
export interface ProviderMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  /** Set only for tool-result messages. */
  name?: string;
  /** Set only for tool-result messages: id from the originating tool call. */
  tool_call_id?: string;
  /** Set only for assistant messages that requested tools. */
  toolCalls?: ToolCall[];
}

/** A tool call requested by an assistant message. */
export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
}
