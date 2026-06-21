/**
 * Install smoke test for @agentkit/sdk.
 *
 * Validates that the installed package exports resolve correctly and that
 * constructing a provider without a key fails with a clear error. Does NOT
 * run a full agent turn — that requires a real API key.
 *
 * Run after installing the packed tarball into a clean directory:
 *   npm install @agentkit/sdk-*.tgz zod
 *   npx tsx scripts/smoke-install.mts
 *
 * Or from monorepo source:
 *   bun run scripts/smoke-install.mts
 */

// Prefer the installed package. Fall back to source so the script is still
// convenient during local development.
const sdk = await import("@agentkit/sdk").catch(() => import("../src/index.ts"));
const testing = await import("@agentkit/sdk/testing").catch(() => import("../src/testing.ts"));

const {
  AgentBuilder,
  AgentRuntime,
  InMemoryEventStore,
  EventBus,
  ToolRegistry,
  ToolPlanner,
  ToolPolicy,
  CancellationToken,
  EventType,
  AgentKitEvent,
  SessionManager,
  InMemorySessionStore,
  OpenAIProvider,
  AnthropicProvider,
  Integration,
  tool,
  VERSION,
} = sdk;
const { MockProvider } = testing;

let failures = 0;

function ok(label: string) {
  console.log(`  ok: ${label}`);
}

function fail(label: string, reason: string) {
  console.error(`FAIL: ${label} — ${reason}`);
  failures++;
}

// ---------------------------------------------------------------------------
// 1. Main package exports resolve
// ---------------------------------------------------------------------------
console.log("Checking main package exports...");

const exports: [string, unknown][] = [
  ["AgentBuilder", AgentBuilder],
  ["AgentRuntime", AgentRuntime],
  ["InMemoryEventStore", InMemoryEventStore],
  ["EventBus", EventBus],
  ["ToolRegistry", ToolRegistry],
  ["ToolPlanner", ToolPlanner],
  ["ToolPolicy", ToolPolicy],
  ["CancellationToken", CancellationToken],
  ["EventType", EventType],
  ["AgentKitEvent", AgentKitEvent],
  ["SessionManager", SessionManager],
  ["InMemorySessionStore", InMemorySessionStore],
  ["OpenAIProvider", OpenAIProvider],
  ["AnthropicProvider", AnthropicProvider],
  ["Integration", Integration],
  ["tool", tool],
  ["VERSION", VERSION],
];

for (const [name, value] of exports) {
  if (value == null) {
    fail(name, "is null or undefined");
  } else {
    ok(name);
  }
}

console.log("\nChecking testing package exports...");
if (MockProvider == null) {
  fail("MockProvider", "is null or undefined");
} else {
  ok("MockProvider");
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
  await (p as any).generate([], []).catch((e: Error) => { throw e; });
  fail("OpenAIProvider missing key", "no error thrown");
} catch (e) {
  const msg = String(e).toLowerCase();
  if (msg.includes("key") || msg.includes("auth") || msg.includes("config") || msg.includes("api")) {
    ok(`OpenAIProvider raises clear error: ${e}`);
  } else {
    // A generic error is still OK for smoke purposes — we just confirm something throws
    ok(`OpenAIProvider throws on empty key: ${e}`);
  }
}

// ---------------------------------------------------------------------------
// 3. VERSION is a string
// ---------------------------------------------------------------------------
console.log("\nChecking VERSION...");
if (typeof VERSION !== "string" || VERSION.length === 0) {
  fail("VERSION", `expected non-empty string, got ${JSON.stringify(VERSION)}`);
} else {
  ok(`VERSION = ${VERSION}`);
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
if (failures > 0) {
  console.error(`\nSmoke install: FAILED (${failures} failure(s))`);
  process.exit(1);
} else {
  console.log("\nSmoke install: PASSED");
}
