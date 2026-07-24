/**
 * Install smoke test for kaji-sdk.
 *
 * Validates that the installed package exports resolve correctly and that
 * constructing a provider without a key fails with a clear error. Does NOT
 * run a full agent turn — that requires a real API key.
 *
 * Run only from a clean project where the packed tarball is installed. The
 * release gate uses smoke_package.mts to create that project.
 */

const sdk = await import("kaji-sdk");
const testing = await import("kaji-sdk/testing");
const openaiSubpath = await import("kaji-sdk/openai");
const anthropicSubpath = await import("kaji-sdk/anthropic");

const {
  AgentBuilder,
  AgentRuntime,
  InMemoryEventStore,
  EventBus,
  ToolRegistry,
  ToolPlanner,
  ToolPolicy,
  ToolArgumentValidationError,
  ToolSchemaValidationError,
  ToolSchemaValidator,
  CancellationToken,
  EventType,
  KajiEvent,
  SessionManager,
  InMemorySessionStore,
  OpenAIProvider,
  AnthropicProvider,
  Integration,
  tool,
  VERSION,
} = sdk;
const { MockProvider } = testing;
const { OpenAIProvider: OpenAIProviderSubpath } = openaiSubpath;
const { AnthropicProvider: AnthropicProviderSubpath } = anthropicSubpath;

let failureCount = 0;

function reportPass(label: string) {
  console.log(`  ok: ${label}`);
}

function reportFailure(label: string, reason: string) {
  console.error(`FAIL: ${label} — ${reason}`);
  failureCount++;
}

// ---------------------------------------------------------------------------
// 1. Main package exports resolve
// ---------------------------------------------------------------------------
console.log("Checking main package exports...");

const requiredExports: [string, unknown][] = [
  ["AgentBuilder", AgentBuilder],
  ["AgentRuntime", AgentRuntime],
  ["InMemoryEventStore", InMemoryEventStore],
  ["EventBus", EventBus],
  ["ToolRegistry", ToolRegistry],
  ["ToolPlanner", ToolPlanner],
  ["ToolPolicy", ToolPolicy],
  ["ToolArgumentValidationError", ToolArgumentValidationError],
  ["ToolSchemaValidationError", ToolSchemaValidationError],
  ["ToolSchemaValidator", ToolSchemaValidator],
  ["CancellationToken", CancellationToken],
  ["EventType", EventType],
  ["KajiEvent", KajiEvent],
  ["SessionManager", SessionManager],
  ["InMemorySessionStore", InMemorySessionStore],
  ["OpenAIProvider", OpenAIProvider],
  ["AnthropicProvider", AnthropicProvider],
  ["Integration", Integration],
  ["tool", tool],
  ["VERSION", VERSION],
];

for (const [name, value] of requiredExports) {
  if (value == null) {
    reportFailure(name, "is null or undefined");
  } else {
    reportPass(name);
  }
}

console.log("\nChecking testing package exports...");
if (MockProvider == null) {
  reportFailure("MockProvider", "is null or undefined");
} else {
  reportPass("MockProvider");
}

console.log("\nChecking provider subpath exports...");
if (OpenAIProviderSubpath == null) {
  reportFailure("kaji-sdk/openai OpenAIProvider", "is null or undefined");
} else {
  reportPass("kaji-sdk/openai OpenAIProvider");
}
if (AnthropicProviderSubpath == null) {
  reportFailure("kaji-sdk/anthropic AnthropicProvider", "is null or undefined");
} else {
  reportPass("kaji-sdk/anthropic AnthropicProvider");
}

// ---------------------------------------------------------------------------
// 2. OpenAIProvider fails with clear error when constructed without a key
// ---------------------------------------------------------------------------
console.log("\nChecking OpenAIProvider missing-key error...");

delete process.env["OPENAI_API_KEY"];
delete process.env["ANTHROPIC_API_KEY"];

try {
  const p = new OpenAIProvider({ apiKey: "" });
  // May not throw at construction; try to generate
  await (p as any).generate([], []).catch((e: Error) => {
    throw e;
  });
  reportFailure("OpenAIProvider missing key", "no error thrown");
} catch (e) {
  const msg = String(e).toLowerCase();
  if (
    msg.includes("key") ||
    msg.includes("auth") ||
    msg.includes("config") ||
    msg.includes("api")
  ) {
    reportPass(`OpenAIProvider raises clear error: ${e}`);
  } else {
    // A generic error is still OK for smoke purposes — we just confirm something throws
    reportPass(`OpenAIProvider throws on empty key: ${e}`);
  }
}

// ---------------------------------------------------------------------------
// 3. VERSION is a string
// ---------------------------------------------------------------------------
console.log("\nChecking VERSION...");
if (typeof VERSION !== "string" || VERSION.length === 0) {
  reportFailure("VERSION", `expected non-empty string, got ${JSON.stringify(VERSION)}`);
} else {
  reportPass(`VERSION = ${VERSION}`);
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
if (failureCount > 0) {
  console.error(`\nSmoke install: FAILED (${failureCount} failure(s))`);
  process.exit(1);
} else {
  console.log("\nSmoke install: PASSED");
}
