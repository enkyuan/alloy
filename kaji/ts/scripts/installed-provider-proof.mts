#!/usr/bin/env bun
/** Run one redacted provider tool-loop proof from an installed @kaji/sdk tarball. */

import { realpathSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { AgentBuilder, EventType, InMemoryEventStore, ToolRegistry } from "@kaji/sdk";
import { AnthropicProvider } from "@kaji/sdk/anthropic";
import { OpenAIProvider } from "@kaji/sdk/openai";

const MARKER = "kaji-installed-provider-proof-marker";
const PROVIDER_KEYS = {
  openai: "OPENAI_API_KEY",
  anthropic: "ANTHROPIC_API_KEY",
} as const;
const FORBIDDEN_TERMINALS = new Set<string>([
  EventType.AGENT_TURN_EXHAUSTED,
  EventType.AGENT_TURN_FAILED,
  EventType.TOOL_CALL_FAILED,
  EventType.CANCELLATION_REQUESTED,
  EventType.CANCELLATION_COMPLETED,
]);

type ProviderName = keyof typeof PROVIDER_KEYS;

class EchoProofIntegration {
  register(registry: ToolRegistry): void {
    registry.register(
      {
        name: "proof_echo",
        catalogName: "proof.echo",
        description: "Echo the supplied marker back to the caller.",
        parameters: {
          type: "object",
          properties: { marker: { type: "string" } },
          required: ["marker"],
          additionalProperties: false,
        },
        risk: "read",
      },
      async (args) => ({
        marker: String(args.marker),
        source: "kaji-installed-provider-proof",
      }),
    );
  }
}

function resolvedPackage(): string {
  const entry = fileURLToPath(import.meta.resolve("@kaji/sdk"));
  return realpathSync(join(dirname(entry), ".."));
}

function baseReceipt(provider: ProviderName, model: string) {
  return {
    sdk: "typescript",
    provider,
    proof: "real_normalized_tool_loop",
    status: "failed",
    model,
    resolvedPackage: resolvedPackage(),
    requestedToolCalls: 0,
    completedToolCalls: 0,
    requestedToolCallIds: [] as string[],
    completedToolCallIds: [] as string[],
    echoResultMatched: false,
    finalTextPresent: false,
    forbiddenTerminalEvents: [] as string[],
  };
}

function parseArguments(argv: string[]): { provider: ProviderName; model: string } {
  let provider: string | undefined;
  let model: string | undefined;
  for (let index = 0; index < argv.length; index += 2) {
    const value = argv[index + 1];
    if (argv[index] === "--provider") provider = value;
    else if (argv[index] === "--model") model = value;
    else throw new Error("invalid provider proof argument");
  }
  if ((provider !== "openai" && provider !== "anthropic") || !model?.trim()) {
    throw new Error("invalid provider proof configuration");
  }
  return { provider, model: model.trim() };
}

function echoMatches(value: unknown): boolean {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as Record<string, unknown>).marker === MARKER &&
    (value as Record<string, unknown>).source === "kaji-installed-provider-proof"
  );
}

async function runProof(providerName: ProviderName, model: string, apiKey: string) {
  const provider =
    providerName === "openai"
      ? new OpenAIProvider({ apiKey, model, temperature: 0 })
      : new AnthropicProvider({ apiKey, model, temperature: 0 });
  const runtime = new AgentBuilder()
    .provider(provider)
    .integration(new EchoProofIntegration())
    .defaultContext({ principalId: `${providerName}-installed-proof` })
    .systemPrompt(
      "You are validating installed SDK tool execution. Call the `proof_echo` tool " +
        "exactly once with the marker from the user message, then give a short final answer.",
    )
    .build({ store: new InMemoryEventStore() });
  const result = await runtime.turn(
    `Call \`proof_echo\` exactly once with marker \`${MARKER}\`, then finish.`,
    { sessionId: `${providerName}-installed-provider-proof` },
  );
  const requestedIds = result.events.flatMap((event) =>
    event.type === EventType.TOOL_CALL_REQUESTED ? [event.tool_call_id] : [],
  );
  const completed = result.events.flatMap((event) =>
    event.type === EventType.TOOL_CALL_COMPLETED ? [event] : [],
  );
  const completedIds = completed.map((event) => event.tool_call_id);
  const forbidden = [
    ...new Set(
      result.events
        .map((event) => event.type)
        .filter((eventType) => FORBIDDEN_TERMINALS.has(eventType)),
    ),
  ].sort();
  const receipt = {
    ...baseReceipt(providerName, model),
    requestedToolCalls: requestedIds.length,
    completedToolCalls: completedIds.length,
    requestedToolCallIds: requestedIds,
    completedToolCallIds: completedIds,
    echoResultMatched: completed.length === 1 && echoMatches(completed[0]!.result),
    finalTextPresent: result.text.trim().length > 0,
    forbiddenTerminalEvents: forbidden,
  };
  receipt.status =
    receipt.requestedToolCalls === 1 &&
    receipt.completedToolCalls === 1 &&
    receipt.requestedToolCallIds[0] === receipt.completedToolCallIds[0] &&
    receipt.echoResultMatched &&
    receipt.finalTextPresent &&
    receipt.forbiddenTerminalEvents.length === 0
      ? "passed"
      : "failed";
  return receipt;
}

async function main(): Promise<number> {
  let args: { provider: ProviderName; model: string };
  try {
    args = parseArguments(process.argv.slice(2));
  } catch {
    console.error("provider proof configuration is incomplete");
    return 2;
  }
  const apiKey = process.env[PROVIDER_KEYS[args.provider]]?.trim() ?? "";
  if (!apiKey) {
    console.log(JSON.stringify(baseReceipt(args.provider, args.model)));
    console.error("provider proof configuration is incomplete");
    return 2;
  }
  try {
    const receipt = await runProof(args.provider, args.model, apiKey);
    console.log(JSON.stringify(receipt));
    return receipt.status === "passed" ? 0 : 1;
  } catch {
    console.log(JSON.stringify(baseReceipt(args.provider, args.model)));
    console.error("provider proof execution failed");
    return 1;
  }
}

process.exitCode = await main();
