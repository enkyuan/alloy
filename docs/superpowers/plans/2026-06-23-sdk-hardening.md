# SDK Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the correctness gaps and one specific security gap (OAuth at-rest) in `kaji/ts` and `kaji/sdk` surfaced by the 2026-06-23 deep review, then ship the first installable releases on npm and PyPI. After this plan lands, the SDK is safe to recommend to external developers. Broader security work (SSRF tool-URL allowlist, tool middleware, structured-output validation) is tracked separately.

**Architecture:** Each task is a surgical change to one or two files with its own test. No new subsystems, no redesigns. Five buckets: (1) provider correctness (NaN, JSON parse silence, symmetric cancellation), (2) DX-blocking runtime bugs (UUID portability, streamText unhandled rejection), (3) OAuth token storage as a pluggable protocol with an opt-in OS-keyring backend, (4) architecture cleanup (`EventBusProtocol` in TS, collapse planner-construction paths, opt-in tool-name sanitization warning), (5) publish pipeline (npm + PyPI workflows, 0.1.1 release).

**Tech Stack:** TypeScript (`@kaji/sdk`, vitest), Python (`kaji`, pytest, pytest-asyncio).

## Global Constraints

- Pre-1.0 SDKs: no back-compat shims, no aliases, no deprecation wrappers. Rename/replace cleanly. (Per repo memory `feedback-no-back-compat`.)
- All package operations use `bun`, not `npm`/`yarn`/`pnpm`. (Per repo memory `use-bun-not-npm`.)
- No em-dashes in user-facing strings, error messages, or docstrings touched by this plan. (Per repo memory `writing-style-no-emdash`.)
- Branch name: `fix/sdk-hardening`. Commit directly to that branch; do not push to `main`.
- Python tests run via `cd kaji/sdk && pytest`; TS tests via `cd kaji/ts && bun run test` (vitest).
- Each task ends with a single commit on the same branch. No squashing within the plan.

## Coordination with other plans

- **Lands before `2026-06-23-sdk-deficiencies.md`.** The deficiencies plan also touches `kaji/sdk/kaji/runtime/agents/runtime.py` (its task collapses the planner constructor branch more aggressively, requiring a planner argument). If the deficiencies plan ships first, drop Task 9 from this plan and add a note. If this plan ships first, reduce the deficiencies-plan runtime task to "require planner, expose `build_planner()` helper" (Task 9 already did the attribute collapse).
- **No conflict with `2026-06-21-sdk-dx-and-docs.md`.** That plan touches `py.typed`, peer-dep ranges, and docs pages — disjoint from this plan's surfaces.

## Success criteria

- All 11 tasks committed on `fix/sdk-hardening`.
- Existing test suites pass: ~23 TS, ~73 Python.
- One manual end-to-end demo against OpenAI succeeds with the new error messages and cancellation behavior visible.
- `@kaji/sdk@0.1.1` published to npm; `kaji==0.1.1` published to PyPI.
- `streamText` semantics change in Task 5 is intentional and has no existing external consumers (verified via `grep -r streamText apps kaji/ts/examples`).

## Execution Order

The previous "parallel groups" formulation hid file-level collisions. Use lanes instead.

```
TS lane:     Task 1  ->  Task 4  ->  Task 5  ->  Task 6  ->  Task 7-ts
Python lane: Task 2  ->  Task 3  ->  Task 7-py ->  Task 8  ->  Task 9
Publish lane (last, blocks on both): Task 10  ->  Task 11
```

The TS and Python lanes are independent and can run in parallel (two subagents).
Task 7 (sanitizer onMutate) is split across lanes because it touches files in both languages; commit as one combined commit at the end of whichever lane finishes Task 7's slice last. Task 10 (npm publish) and Task 11 (PyPI publish) only after both lanes land on the branch.

---

## File Structure

**TypeScript (`kaji/ts/src/`)**
- `tools/planner.ts` — fix NaN/Infinity acceptance in `JSON_TYPE_CHECK.number`; replace `crypto.randomUUID()` with injectable factory.
- `runtime/oneshot.ts` — fix unhandled rejection on `text`/`toolCalls` promises when consumer awaits only one.
- `events/protocols.ts` — new file, defines `EventBusProtocol` mirroring Python's `EventBusProtocol`.
- `events/bus.ts` — `EventBus` declares `implements EventBusProtocol`.
- `runtime/runtime.ts` — `AgentRuntimeOptions.bus` accepts `EventBusProtocol` instead of concrete `EventBus`.
- `index.ts` — export `EventBusProtocol`.
- `tools/registry.ts` — `providerSafeToolName` takes optional `onMutate` callback; no default side-effects.

**Python (`kaji/sdk/kaji/`)**
- `runtime/providers/openai.py` — log + structured-error signal on `JSONDecodeError` in `_finalize_stream_tool_calls` (raw input goes to log, NOT to event payload); raise `asyncio.CancelledError` in both `generate()` and `generate_stream()` when the token is set.
- `integrations/oauth.py` — pluggable `TokenStorage` with `FileTokenStorage` (default) and `KeyringTokenStorage` (optional).
- `runtime/agents/runtime.py` — collapse two-path planner resolution: delete `@property def planner`, set `self.planner` directly in `__init__`.
- `runtime/tools/registry.py` — `provider_safe_tool_name` takes optional `on_mutate` callback; no default side-effects.

**Tests**
- `kaji/ts/tests/planner.validate.test.ts` — NaN, Infinity, valid number.
- `kaji/ts/tests/planner.callid.test.ts` — UUID factory injection.
- `kaji/ts/tests/oneshot.unhandled.test.ts` — partial-consumer rejection observability.
- `kaji/ts/tests/events.protocol.test.ts` — runtime accepts a non-`EventBus` `EventBusProtocol`.
- `kaji/ts/tests/tools.sanitize.test.ts` — onMutate fires on mutation, silent on safe names.
- `kaji/sdk/tests/test_providers_openai_stream.py` — JSON-parse failure logs warning + emits `__parse_error` (no `__raw` in payload).
- `kaji/sdk/tests/test_providers_openai_cancel.py` — both `generate()` and `generate_stream()` raise on cancelled token.
- `kaji/sdk/tests/test_integrations_oauth.py` — extended with `TokenStorage` cases.
- `kaji/sdk/tests/test_agents_runtime.py` — extended with explicit-planner / built-planner symmetry.
- `kaji/sdk/tests/test_tools_registry_sanitize.py` — on_mutate fires on mutation, silent on safe names.

---

### Task 1: Reject NaN and Infinity in TS tool-arg validation

**Files:**
- Modify: `kaji/ts/src/tools/planner.ts` (`JSON_TYPE_CHECK` lines 10-18, `validateArgs` error message ~line 40)
- Test: `kaji/ts/tests/planner.validate.test.ts` (new)

**Interfaces:**
- Consumes: nothing.
- Produces: tightened `JSON_TYPE_CHECK.number` / `JSON_TYPE_CHECK.integer`. No public API change.

- [ ] **Step 1: Confirm the ToolPlanner.execute API shape**

Run:

```bash
grep -n "executeScatterGather\|class ToolPlanner\|ToolCallInstruction\|ToolCallResult" kaji/ts/src/tools/planner.ts
```

Expected: the public entry point is `executeScatterGather(sessionId, toolCalls, emit)` returning `Promise<ToolCallResult[]>`. The test in Step 2 uses this exact name. If the name has drifted, update the test before continuing.

- [ ] **Step 2: Write the failing test**

Create `kaji/ts/tests/planner.validate.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { ToolPlanner } from "../src/tools/planner";
import type { ToolSpec } from "../src/tools/registry";

const numericSpec: ToolSpec = {
  name: "price_check",
  description: "x",
  parameters: {
    type: "object",
    properties: { price: { type: "number" } },
    required: ["price"],
  },
};

describe("ToolPlanner argument validation", () => {
  const planner = new ToolPlanner({
    executor: async () => ({ ok: true }),
    specs: new Map([["price_check", numericSpec]]),
  });
  const noopEmit = async () => {};

  it("rejects NaN as a number argument", async () => {
    const out = await planner.executeScatterGather(
      "session-1",
      [{ id: "c1", name: "price_check", arguments: { price: Number.NaN } }],
      noopEmit,
    );
    expect(out[0].status).toBe("failed");
    expect(String((out[0] as { error?: string }).error ?? "")).toMatch(/finite/i);
  });

  it("rejects Infinity as a number argument", async () => {
    const out = await planner.executeScatterGather(
      "session-1",
      [{ id: "c2", name: "price_check", arguments: { price: Number.POSITIVE_INFINITY } }],
      noopEmit,
    );
    expect(out[0].status).toBe("failed");
    expect(String((out[0] as { error?: string }).error ?? "")).toMatch(/finite/i);
  });

  it("accepts a finite number", async () => {
    const out = await planner.executeScatterGather(
      "session-1",
      [{ id: "c3", name: "price_check", arguments: { price: 42 } }],
      noopEmit,
    );
    expect(out[0].status).toBe("succeeded");
  });
});
```

Re-read `kaji/ts/src/tools/planner.ts` around lines 60-130 to confirm `ToolCallResult`'s union shape and adjust the `.error` access if the failed variant nests differently. The test should compile against the existing types before you modify the source.

- [ ] **Step 3: Run test to verify it fails**

Run: `cd kaji/ts && bun run test -- tests/planner.validate.test.ts`
Expected: NaN and Infinity tests fail (the planner reports `succeeded`).

- [ ] **Step 4: Tighten the JSON_TYPE_CHECK numeric predicates**

In `kaji/ts/src/tools/planner.ts`, replace the existing `JSON_TYPE_CHECK` block:

```ts
const JSON_TYPE_CHECK: Record<string, (v: unknown) => boolean> = {
  object: (v) => typeof v === "object" && v !== null && !Array.isArray(v),
  array: Array.isArray,
  string: (v) => typeof v === "string",
  integer: (v) => typeof v === "number" && Number.isFinite(v) && Number.isInteger(v),
  number: (v) => typeof v === "number" && Number.isFinite(v),
  boolean: (v) => typeof v === "boolean",
  null: (v) => v === null,
};
```

In `validateArgs`, update the type-mismatch error message so callers can see WHY a number was rejected:

```ts
if (check && !check(args[key])) {
  const got =
    typeof args[key] === "number" && !Number.isFinite(args[key] as number)
      ? "non-finite number"
      : typeof args[key];
  return `argument '${key}': expected finite ${expected}, got ${got}`;
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd kaji/ts && bun run test -- tests/planner.validate.test.ts`
Expected: 3 PASS.

- [ ] **Step 6: Run full TS suite**

Run: `cd kaji/ts && bun run test`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add kaji/ts/src/tools/planner.ts kaji/ts/tests/planner.validate.test.ts
git commit -m "fix(ts): reject NaN and Infinity in tool-arg numeric validation"
```

---

### Task 2: Surface JSON parse failures in Python OpenAI streaming (log-only raw)

**Files:**
- Modify: `kaji/sdk/kaji/runtime/providers/openai.py` (`_finalize_stream_tool_calls`, lines 138-157)
- Test: `kaji/sdk/tests/test_providers_openai_stream.py` (new)

**Interfaces:**
- Consumes: nothing.
- Produces: `_finalize_stream_tool_calls` logs a warning containing the raw input AND the error, and marks the call args as `{"__parse_error": "<message>"}`. **Raw input does NOT appear in the event payload** (privacy: model output may contain user PII).

- [ ] **Step 1: Write the failing test**

Create `kaji/sdk/tests/test_providers_openai_stream.py`:

```python
import logging

from kaji.runtime.providers.openai import OpenAIProvider


def test_finalize_logs_raw_and_surfaces_parse_error_in_payload(caplog):
    caplog.set_level(logging.WARNING, logger="kaji.runtime.providers.openai")

    pending = {
        0: {"id": "call_1", "name": "lookup", "arguments": "{not json"},
    }
    calls = OpenAIProvider._finalize_stream_tool_calls(pending)

    assert calls and calls[0]["name"] == "lookup"
    # Payload signals the failure but does NOT carry the raw model output.
    assert "__parse_error" in calls[0]["arguments"]
    assert "__raw" not in calls[0]["arguments"]
    # The raw input appears in the privileged log only.
    log_text = " ".join(rec.message for rec in caplog.records)
    assert "tool_call arguments failed to parse" in log_text
    assert "{not json" in log_text


def test_finalize_passes_through_valid_json():
    pending = {
        0: {"id": "call_2", "name": "lookup", "arguments": '{"city": "NYC"}'},
    }
    calls = OpenAIProvider._finalize_stream_tool_calls(pending)
    assert calls[0]["arguments"] == {"city": "NYC"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd kaji/sdk && pytest tests/test_providers_openai_stream.py -v`
Expected: `__parse_error` absent and no warning logged.

- [ ] **Step 3: Replace the silent fallback**

In `kaji/sdk/kaji/runtime/providers/openai.py`, replace `_finalize_stream_tool_calls`:

```python
@staticmethod
def _finalize_stream_tool_calls(
    pending: Dict[int, Dict[str, str]],
) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []
    for _, item in sorted(pending.items()):
        if not item["name"]:
            continue
        raw = item["arguments"] or "{}"
        try:
            args: Dict[str, Any] = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            # Log carries the raw model output (privileged sink).
            # Event payload carries only the error string (may be persisted,
            # forwarded, or surfaced to UI; must not include raw model output
            # which may contain user PII).
            logger.warning(
                "OpenAI streaming tool_call arguments failed to parse "
                "for tool=%s id=%s raw=%r: %s",
                item["name"],
                item["id"] or "<unknown>",
                raw,
                exc,
            )
            args = {"__parse_error": str(exc)}
        calls.append(
            {
                "id": item["id"] or None,
                "name": item["name"],
                "arguments": args,
            }
        )
    return calls
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd kaji/sdk && pytest tests/test_providers_openai_stream.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Run full provider suite**

Run: `cd kaji/sdk && pytest tests/ -k provider -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add kaji/sdk/kaji/runtime/providers/openai.py kaji/sdk/tests/test_providers_openai_stream.py
git commit -m "fix(sdk): surface OpenAI stream tool-arg parse errors (log raw, signal in payload)"
```

---

### Task 3: Symmetric cancellation in Python OpenAI generate() and generate_stream()

**Files:**
- Modify: `kaji/sdk/kaji/runtime/providers/openai.py` (`generate()` 159-205; `generate_stream()` 207-253)
- Test: `kaji/sdk/tests/test_providers_openai_cancel.py` (new)

**Interfaces:**
- Consumes: nothing.
- Produces: both `generate()` and `generate_stream()` raise `asyncio.CancelledError` if the cancellation token is set on entry; `generate_stream()` also raises if the token fires mid-stream (replaces today's silent `break`). Symmetric semantics: callers always observe a cancellation.

- [ ] **Step 1: Write the failing tests**

Create `kaji/sdk/tests/test_providers_openai_cancel.py`:

```python
import asyncio
import pytest

from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.providers.openai import OpenAIProvider


@pytest.mark.asyncio
async def test_generate_raises_when_token_already_cancelled():
    provider = OpenAIProvider(model_name="gpt-4o-mini", api_key="dummy")
    token = CancellationToken()
    token.cancel()

    with pytest.raises(asyncio.CancelledError):
        await provider.generate(
            messages=[{"role": "user", "content": "hi"}],
            cancellation_token=token,
        )


@pytest.mark.asyncio
async def test_generate_stream_raises_when_token_already_cancelled():
    provider = OpenAIProvider(model_name="gpt-4o-mini", api_key="dummy")
    token = CancellationToken()
    token.cancel()

    with pytest.raises(asyncio.CancelledError):
        async for _ in provider.generate_stream(
            messages=[{"role": "user", "content": "hi"}],
            cancellation_token=token,
        ):
            pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd kaji/sdk && pytest tests/test_providers_openai_cancel.py -v`
Expected: FAIL. `generate()` attempts the API call (errors out for a different reason); `generate_stream` errors when constructing the client, not as `CancelledError`.

- [ ] **Step 3: Add the cancellation checks**

In `kaji/sdk/kaji/runtime/providers/openai.py`:

Add at the top, if not present:

```python
import asyncio
```

In `generate()`, immediately before `try:` at line ~181, insert:

```python
if cancellation_token is not None and getattr(
    cancellation_token, "is_cancelled", False
):
    raise asyncio.CancelledError(
        "OpenAIProvider.generate cancelled before request"
    )
```

In `generate_stream()`:

(a) Add the same pre-call check before `try:` at line ~227.

(b) Replace the in-loop `break` at lines ~236-239 with a `raise`:

```python
async for chunk in stream:
    if cancellation_token is not None and getattr(
        cancellation_token, "is_cancelled", False
    ):
        raise asyncio.CancelledError(
            "OpenAIProvider.generate_stream cancelled during streaming"
        )
    # ... rest of the loop unchanged ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd kaji/sdk && pytest tests/test_providers_openai_cancel.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Run full provider suite + agents runtime suite**

Run: `cd kaji/sdk && pytest tests/ -k "provider or agent_runtime or cancellation" -v`
Expected: all pass. If any existing test relied on the silent-break behavior of `generate_stream`, update it to expect `CancelledError`. Note the breakage in the commit message.

- [ ] **Step 6: Commit**

```bash
git add kaji/sdk/kaji/runtime/providers/openai.py kaji/sdk/tests/test_providers_openai_cancel.py
git commit -m "fix(sdk): symmetric CancelledError in OpenAI generate() and generate_stream()"
```

---

### Task 4: Inject UUID factory in TS planner

**Files:**
- Modify: `kaji/ts/src/tools/planner.ts` (`ToolPlannerOptions`, constructor, `callId` assignment ~line 129)
- Test: `kaji/ts/tests/planner.callid.test.ts` (new)

**Interfaces:**
- Consumes: nothing.
- Produces: `ToolPlannerOptions.uuid?: () => string`. Default factory uses `globalThis.crypto?.randomUUID?.()` if present; falls back to a `Math.random`-based UUID-shaped string for non-Web-Crypto runtimes (Workerd, restricted CSP). The fallback is NOT cryptographically secure; tool-call correlation does not require it.

- [ ] **Step 1: Write the failing test**

Create `kaji/ts/tests/planner.callid.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { ToolPlanner } from "../src/tools/planner";

describe("ToolPlanner uuid injection", () => {
  it("uses an injected uuid factory for missing call ids", async () => {
    let counter = 0;
    const planner = new ToolPlanner({
      executor: async () => ({ ok: true }),
      specs: new Map([
        ["noop", { name: "noop", description: "x", parameters: { type: "object" } }],
      ]),
      uuid: () => `fixed-${++counter}`,
    });

    const out = await planner.executeScatterGather(
      "s1",
      [{ name: "noop", arguments: {} }],
      async () => {},
    );

    expect((out[0] as { callId: string }).callId).toBe("fixed-1");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd kaji/ts && bun run test -- tests/planner.callid.test.ts`
Expected: TypeScript error (`uuid` is not a valid option) OR (if forgiving) `callId` is a real UUID and the assertion fails.

- [ ] **Step 3: Extend ToolPlannerOptions and use the injected factory**

In `kaji/ts/src/tools/planner.ts`:

Extend the existing `ToolPlannerOptions` interface (locate it; do not duplicate):

```ts
export interface ToolPlannerOptions {
  // ... existing fields unchanged ...
  /** Override the call-id generator. Defaults to globalThis.crypto.randomUUID with a Math.random fallback. */
  uuid?: () => string;
}
```

Add a `defaultUuid` helper near the top of the file:

```ts
function defaultUuid(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (c?.randomUUID) return c.randomUUID();
  // Fallback for runtimes without Web Crypto. Used only as a tool-call
  // correlation id, never as a security token.
  const hex = (bytes: number) =>
    Math.floor(Math.random() * 16 ** (bytes * 2))
      .toString(16)
      .padStart(bytes * 2, "0");
  return `${hex(4)}-${hex(2)}-${hex(2)}-${hex(2)}-${hex(6)}`;
}
```

In the constructor, capture the factory (add the field, assign in `__init__`):

```ts
private readonly uuid: () => string;

constructor(options: ToolPlannerOptions) {
  // ... existing assignments unchanged ...
  this.uuid = options.uuid ?? defaultUuid;
}
```

Replace `crypto.randomUUID()` at line ~129 with `this.uuid()`:

```ts
const callId = call.id ?? this.uuid();
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd kaji/ts && bun run test -- tests/planner.callid.test.ts`
Expected: PASS.

- [ ] **Step 5: Run full TS suite**

Run: `cd kaji/ts && bun run test`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add kaji/ts/src/tools/planner.ts kaji/ts/tests/planner.callid.test.ts
git commit -m "feat(ts): inject uuid factory in ToolPlanner for non-WebCrypto envs"
```

---

### Task 5: Make streamText rejection observable without unhandled-rejection noise

**Files:**
- Modify: `kaji/ts/src/runtime/oneshot.ts` (around line 113, before the `return`)
- Test: `kaji/ts/tests/oneshot.unhandled.test.ts` (new)

**Interfaces:**
- Consumes: nothing.
- Produces: when the source stream errors, both the `text` and `toolCalls` promises reject with the same error. The caller observes whichever they `await`; the other does NOT produce a `process.on('unhandledRejection')` warning because both promises have an attached noop catch.

**Test approach.** We do NOT use `process.on('unhandledRejection')` — that's process-global, vitest-fragile, and timing-dependent. We assert the actual user-visible contract: a consumer can await either promise and observe the rejection.

- [ ] **Step 1: Write the failing test**

Create `kaji/ts/tests/oneshot.unhandled.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { streamText } from "../src/runtime/oneshot";
import type { ModelProvider, ModelResponseChunk, ProviderMessage } from "../src/providers/base";

function makeFlakyProvider(): ModelProvider {
  return {
    async generate() {
      throw new Error("unused");
    },
    async *generateStream(
      _messages: ProviderMessage[],
    ): AsyncGenerator<ModelResponseChunk> {
      yield { delta: "hi", toolCalls: [] };
      throw new Error("upstream blew up");
    },
  };
}

describe("streamText rejection observability", () => {
  it("rejects toolCalls when the source stream errors, even if textStream is not iterated", async () => {
    const result = streamText({
      provider: makeFlakyProvider(),
      messages: [{ role: "user", content: "go" }],
    });
    await expect(result.toolCalls).rejects.toThrow("upstream blew up");
  });

  it("rejects text when the source stream errors, even if toolCalls is not awaited", async () => {
    const result = streamText({
      provider: makeFlakyProvider(),
      messages: [{ role: "user", content: "go" }],
    });
    await expect(result.text).rejects.toThrow("upstream blew up");
  });

  it("iterating textStream yields the delta then throws", async () => {
    const result = streamText({
      provider: makeFlakyProvider(),
      messages: [{ role: "user", content: "go" }],
    });
    const seen: string[] = [];
    await expect(async () => {
      for await (const chunk of result.textStream) {
        seen.push(chunk);
      }
    }).rejects.toThrow("upstream blew up");
    expect(seen).toEqual(["hi"]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd kaji/ts && bun run test -- tests/oneshot.unhandled.test.ts`
Expected: tests 1 and 2 hang or fail with timeout. The current `streamText` only resolves/rejects `text`/`toolCalls` after `textStream` is iterated to completion (see the docstring at oneshot.ts:42-46).

This task changes that contract: rejection is observable without iterating `textStream`. **This is a deliberate behavior change** to fix the unhandled-rejection class of bugs. The docstring on `streamText` must be updated to match (Step 3).

- [ ] **Step 3: Update streamText so rejection propagates to all three handles**

In `kaji/ts/src/runtime/oneshot.ts`, locate the `streamText` function. The existing pattern uses a single source generator and resolves the `text`/`toolCalls` promises inside the `textStream` generator's body. We change it so the source is drained eagerly when the caller awaits any of the three handles.

Find the existing structure (`function* textStream()` calling `rejectAll`/`resolveText` inside its try/catch), and replace it with this shape:

```ts
export function streamText(options: GenerateTextOptions): StreamTextResult {
  const { provider, messages, tools, ...providerOptions } = options;
  const source = provider.generateStream(messages, tools ?? [], providerOptions);

  let resolveText: (s: string) => void;
  let rejectText: (err: unknown) => void;
  let resolveCalls: (c: ModelResponse["toolCalls"]) => void;
  let rejectCalls: (err: unknown) => void;
  const text = new Promise<string>((res, rej) => {
    resolveText = res;
    rejectText = rej;
  });
  const toolCalls = new Promise<ModelResponse["toolCalls"]>((res, rej) => {
    resolveCalls = res;
    rejectCalls = rej;
  });

  // Buffer text deltas and tool calls; surface via the iterable below.
  const collected: string[] = [];
  const calls: ModelResponse["toolCalls"] = [];
  const queue: string[] = [];
  let queueWaiter: ((r: IteratorResult<string>) => void) | null = null;
  let drained = false;
  let drainError: unknown = null;

  async function drain(): Promise<void> {
    try {
      for await (const chunk of source) {
        if (chunk.delta) {
          collected.push(chunk.delta);
          if (queueWaiter) {
            const w = queueWaiter;
            queueWaiter = null;
            w({ value: chunk.delta, done: false });
          } else {
            queue.push(chunk.delta);
          }
        }
        if (chunk.toolCalls?.length) calls.push(...chunk.toolCalls);
      }
      drained = true;
      resolveText(collected.join(""));
      resolveCalls(calls);
      if (queueWaiter) {
        const w = queueWaiter;
        queueWaiter = null;
        w({ value: undefined, done: true });
      }
    } catch (err) {
      drained = true;
      drainError = err;
      rejectText(err);
      rejectCalls(err);
      if (queueWaiter) {
        const w = queueWaiter;
        queueWaiter = null;
        w({ value: undefined, done: true });
      }
    }
  }

  // Start draining immediately. Suppress unhandled-rejection if the caller
  // awaits only one of (text, toolCalls); the rejection is still delivered
  // to whichever they await.
  const drainPromise = drain();
  drainPromise.catch(() => {});
  text.catch(() => {});
  toolCalls.catch(() => {});

  const textStream: AsyncIterable<string> = {
    [Symbol.asyncIterator](): AsyncIterator<string> {
      return {
        async next(): Promise<IteratorResult<string>> {
          const buffered = queue.shift();
          if (buffered !== undefined) return { value: buffered, done: false };
          if (drained) {
            if (drainError) throw drainError;
            return { value: undefined, done: true };
          }
          return new Promise((res) => {
            queueWaiter = res;
          });
        },
      };
    },
  };

  return { textStream, text, toolCalls };
}
```

Also update the JSDoc on `StreamTextResult` (lines 38-63 of the current file) to reflect the new contract: "Each of `textStream`, `text`, and `toolCalls` is independently consumable; awaiting any one of them does not require iterating any of the others. All three reject if the source stream errors."

- [ ] **Step 4: Run test to verify it passes**

Run: `cd kaji/ts && bun run test -- tests/oneshot.unhandled.test.ts`
Expected: 3 PASS.

- [ ] **Step 5: Run full TS suite (especially existing oneshot tests)**

Run: `cd kaji/ts && bun run test`
Expected: all pass. If existing tests assumed "await `text` hangs until `textStream` is drained," update them to reflect the new "drain is automatic" contract. Note any updated tests in the commit message.

- [ ] **Step 6: Commit**

```bash
git add kaji/ts/src/runtime/oneshot.ts kaji/ts/tests/oneshot.unhandled.test.ts
git commit -m "fix(ts): streamText rejection observable from text and toolCalls independently"
```

---

### Task 6: Define EventBusProtocol in TypeScript

```
            +--------------------+
            | EventBusProtocol   |  kaji/ts/src/events/protocols.ts
            |  publish(event)    |
            |  subscribe(sid)    |
            |  close()           |
            +---------+----------+
                      ^
                      | implements
            +---------+----------+
            |     EventBus       |  kaji/ts/src/events/bus.ts
            |   (in-memory)      |
            +--------------------+
                      ^
                      | options.bus: EventBusProtocol
            +---------+----------+
            |   AgentRuntime     |  kaji/ts/src/runtime/runtime.ts
            +--------------------+
```

**Files:**
- Create: `kaji/ts/src/events/protocols.ts`
- Modify: `kaji/ts/src/events/bus.ts` (`implements` clause)
- Modify: `kaji/ts/src/runtime/runtime.ts` (import + options.bus + field type)
- Modify: `kaji/ts/src/index.ts` (export protocol)
- Test: `kaji/ts/tests/events.protocol.test.ts` (new)

**Interfaces:**
- Consumes: nothing.
- Produces: `EventBusProtocol` exported from `@kaji/sdk`. Any object with `publish(event): Promise<void>`, `subscribe(sessionId): AsyncIterableIterator<KajiEvent>`, `close(): void` is accepted by `AgentRuntime`.

- [ ] **Step 1: Write the failing test**

Create `kaji/ts/tests/events.protocol.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { AgentRuntime } from "../src/runtime/runtime";
import { InMemoryEventStore } from "../src/events/store";
import type { KajiEvent } from "../src/events/schemas";
import type { EventBusProtocol } from "../src/events/protocols";
import type {
  ModelProvider,
  ModelResponseChunk,
  ProviderMessage,
} from "../src/providers/base";

class RecordingBus implements EventBusProtocol {
  readonly published: KajiEvent[] = [];
  async publish(event: KajiEvent): Promise<void> {
    this.published.push(event);
  }
  subscribe(): AsyncIterableIterator<KajiEvent> {
    return (async function* () {})();
  }
  close(): void {}
}

const stubProvider: ModelProvider = {
  async generate() {
    return { text: "ok", toolCalls: [] };
  },
  async *generateStream(
    _m: ProviderMessage[],
  ): AsyncGenerator<ModelResponseChunk> {
    yield { delta: "ok", toolCalls: [] };
  },
};

describe("AgentRuntime accepts EventBusProtocol", () => {
  it("publishes events through a non-EventBus implementation", async () => {
    const bus = new RecordingBus();
    const runtime = new AgentRuntime({
      provider: stubProvider,
      store: new InMemoryEventStore(),
      bus,
    });
    await runtime.send("s1", "hello");
    expect(bus.published.length).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd kaji/ts && bun run test -- tests/events.protocol.test.ts`
Expected: TypeScript compile error — `EventBusProtocol` does not exist; `AgentRuntime` requires concrete `EventBus`.

- [ ] **Step 3: Create the protocol file**

Create `kaji/ts/src/events/protocols.ts`:

```ts
import type { KajiEvent } from "./schemas";

/**
 * Structural contract for an event bus. The shipped in-memory `EventBus`
 * implements this; users may pass a Redis-, Kafka-, or test-backed
 * implementation that satisfies the same shape.
 *
 * Mirrors `kaji.infra.events.protocols.EventBusProtocol` from the
 * Python SDK.
 */
export interface EventBusProtocol {
  publish(event: KajiEvent): Promise<void>;
  subscribe(sessionId: string): AsyncIterableIterator<KajiEvent>;
  close(): void;
}
```

- [ ] **Step 4: Mark EventBus as implementing the protocol**

In `kaji/ts/src/events/bus.ts`, add the import and the `implements` clause:

```ts
import type { EventBusProtocol } from "./protocols";

export class EventBus implements EventBusProtocol {
  // existing body unchanged
}
```

- [ ] **Step 5: Loosen AgentRuntimeOptions.bus**

In `kaji/ts/src/runtime/runtime.ts`:

Replace the value import of `EventBus` at line 9 with a type import of `EventBusProtocol`:

```ts
import type { EventBusProtocol } from "../events/protocols";
```

(If `EventBus` value is still referenced anywhere in `runtime.ts`, keep `import { EventBus }` alongside. From my read, it is only used as a type. Confirm with `grep -n "EventBus" kaji/ts/src/runtime/runtime.ts` before deleting.)

Update the option type around line 30:

```ts
bus: EventBusProtocol;
```

Update the field declaration around line 80:

```ts
private readonly bus: EventBusProtocol;
```

- [ ] **Step 6: Export from public surface**

In `kaji/ts/src/index.ts`, replace the events block (around lines 17-20):

```ts
// Events
export { EventType } from "./events/types";
export { KajiEvent, type KajiEventInput, type BaseEvent } from "./events/schemas";
export { EventBus } from "./events/bus";
export { type EventBusProtocol } from "./events/protocols";
export { type EventStore, InMemoryEventStore } from "./events/store";
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd kaji/ts && bun run test -- tests/events.protocol.test.ts`
Expected: PASS.

- [ ] **Step 8: Run full TS suite**

Run: `cd kaji/ts && bun run test`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add kaji/ts/src/events/protocols.ts kaji/ts/src/events/bus.ts kaji/ts/src/runtime/runtime.ts kaji/ts/src/index.ts kaji/ts/tests/events.protocol.test.ts
git commit -m "feat(ts): EventBusProtocol decouples AgentRuntime from concrete bus"
```

---

### Task 7: Add `onMutate` callback to tool-name sanitizer (no default side-effect)

**Files:**
- Modify: `kaji/ts/src/tools/registry.ts` (`providerSafeToolName`, line 61)
- Modify: `kaji/sdk/kaji/runtime/tools/registry.py` (`provider_safe_tool_name`, line 44)
- Test: `kaji/ts/tests/tools.sanitize.test.ts` (new)
- Test: `kaji/sdk/tests/test_tools_registry_sanitize.py` (new)

**Interfaces:**
- Consumes: nothing.
- Produces: `providerSafeToolName(name, opts?: { onMutate?: (original, sanitized) => void })`. **No default side-effect**: if the caller does not pass `onMutate`, no warning is emitted, no global state is mutated, no console output. Integration code (`integrations/base.ts:67`, `integrations/functional.ts:46`, Python equivalents) will be updated in this task to pass an `onMutate` that wires the warning to the registry's optional logger.

Why no default side-effect: the existing call sites run at tool-registration time (every `builder.tool(...)` call), so a default `console.warn` would produce one stderr line per sanitized name on every startup — noisy for any non-trivial integration set. Explicit opt-in via callback keeps the API silent unless the caller wants the signal.

- [ ] **Step 1: Audit call sites**

Run:

```bash
grep -rn "providerSafeToolName\|provider_safe_tool_name" kaji/ts/src kaji/sdk/kaji
```

Expected call sites (confirm against actual output):

```
kaji/ts/src/integrations/base.ts:67       (Integration.register)
kaji/ts/src/integrations/functional.ts:46 (BoundTool.register)
kaji/sdk/kaji/runtime/integrations/base.py:100
kaji/sdk/kaji/runtime/integrations/functional.py:53
```

These are the four sites where the callback will be threaded in.

- [ ] **Step 2: Write the failing TS test**

Create `kaji/ts/tests/tools.sanitize.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";
import { providerSafeToolName } from "../src/tools/registry";

describe("providerSafeToolName", () => {
  it("invokes onMutate when the name is changed", () => {
    const onMutate = vi.fn();
    const out = providerSafeToolName("weather-api", { onMutate });
    expect(out).not.toBe("weather-api");
    expect(onMutate).toHaveBeenCalledTimes(1);
    expect(onMutate).toHaveBeenCalledWith("weather-api", out);
  });

  it("does not invoke onMutate when the name is already safe", () => {
    const onMutate = vi.fn();
    const out = providerSafeToolName("weather_api", { onMutate });
    expect(out).toBe("weather_api");
    expect(onMutate).not.toHaveBeenCalled();
  });

  it("emits no side effect when onMutate is omitted", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    try {
      const out = providerSafeToolName("weather-api");
      expect(out).toBe("weather_api");
      expect(warn).not.toHaveBeenCalled();
    } finally {
      warn.mockRestore();
    }
  });
});
```

- [ ] **Step 3: Run TS test to verify it fails**

Run: `cd kaji/ts && bun run test -- tests/tools.sanitize.test.ts`
Expected: FAIL (function rejects the options arg).

- [ ] **Step 4: Implement TS sanitizer + thread the callback through integrations**

In `kaji/ts/src/tools/registry.ts`, replace the existing `providerSafeToolName`:

```ts
export interface ProviderSafeToolNameOptions {
  /** Called once with (original, sanitized) when the name is mutated. */
  onMutate?: (original: string, sanitized: string) => void;
}

export function providerSafeToolName(
  name: string,
  opts: ProviderSafeToolNameOptions = {},
): string {
  const safe = name.replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "") || "tool";
  if (safe !== name && opts.onMutate) {
    opts.onMutate(name, safe);
  }
  return safe;
}
```

(Preserve the existing transform — copy the regex/fallback from the current line 61 implementation; only add the `opts` and `onMutate` logic.)

In `kaji/ts/src/integrations/base.ts` line 67 and `kaji/ts/src/integrations/functional.ts` line 46, thread the callback. Example for `functional.ts:46`:

```ts
registry.register(
  {
    ...this.spec,
    name: providerSafeToolName(catalogName, {
      onMutate: (orig, safe) => {
        // eslint-disable-next-line no-console
        console.warn(
          `[kaji] tool name "${orig}" sanitized to "${safe}" for provider compatibility`,
        );
      },
    }),
    catalogName,
  },
  this.handler,
);
```

Do the same in `base.ts:67`.

- [ ] **Step 5: Run TS test to verify it passes**

Run: `cd kaji/ts && bun run test -- tests/tools.sanitize.test.ts`
Expected: 3 PASS.

- [ ] **Step 6: Write the failing Python test**

Create `kaji/sdk/tests/test_tools_registry_sanitize.py`:

```python
import logging

from kaji.runtime.tools.registry import provider_safe_tool_name


def test_on_mutate_callback_fires():
    seen: list[tuple[str, str]] = []
    out = provider_safe_tool_name("weather-api", on_mutate=lambda o, n: seen.append((o, n)))
    assert out != "weather-api"
    assert seen == [("weather-api", out)]


def test_no_side_effect_without_on_mutate(caplog):
    caplog.set_level(logging.WARNING, logger="kaji.runtime.tools.registry")
    out = provider_safe_tool_name("weather-api")
    assert out == "weather_api"
    assert [r for r in caplog.records if "sanitized" in r.message] == []


def test_no_callback_when_name_is_safe():
    seen: list[tuple[str, str]] = []
    out = provider_safe_tool_name("weather_api", on_mutate=lambda o, n: seen.append((o, n)))
    assert out == "weather_api"
    assert seen == []
```

- [ ] **Step 7: Run Python test to verify it fails**

Run: `cd kaji/sdk && pytest tests/test_tools_registry_sanitize.py -v`
Expected: FAIL — keyword arg unknown.

- [ ] **Step 8: Implement Python sanitizer + thread callback**

In `kaji/sdk/kaji/runtime/tools/registry.py`, replace `provider_safe_tool_name`:

```python
def provider_safe_tool_name(
    name: str,
    *,
    on_mutate: Optional[Callable[[str, str], None]] = None,
) -> str:
    """Return a provider-safe tool name using only letters, digits, "_", and "-".

    If ``on_mutate`` is given and the name is changed, the callback is invoked
    once with ``(original, sanitized)``. With no callback, no side effects.
    """
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "tool"
    if safe != name and on_mutate is not None:
        on_mutate(name, safe)
    return safe
```

In `kaji/sdk/kaji/runtime/integrations/base.py` (line 100) and `kaji/sdk/kaji/runtime/integrations/functional.py` (line 53), thread the callback. Add at the top of each (if not present):

```python
import logging
logger = logging.getLogger(__name__)
```

Then change the sanitizer call:

```python
def _warn_on_sanitize(original: str, sanitized: str) -> None:
    logger.warning(
        "tool name %r sanitized to %r for provider compatibility",
        original,
        sanitized,
    )

# ...

name=provider_safe_tool_name(catalog_name, on_mutate=_warn_on_sanitize),
```

(Or define `_warn_on_sanitize` once at module scope in a shared util; one-per-file is fine for this plan.)

- [ ] **Step 9: Run Python test to verify it passes**

Run: `cd kaji/sdk && pytest tests/test_tools_registry_sanitize.py -v`
Expected: 3 PASS.

- [ ] **Step 10: Run both suites for regressions**

Run: `cd kaji/ts && bun run test && cd ../sdk && pytest tests/`
Expected: all pass.

- [ ] **Step 11: Commit**

```bash
git add kaji/ts/src/tools/registry.ts kaji/ts/src/integrations/base.ts kaji/ts/src/integrations/functional.ts kaji/ts/tests/tools.sanitize.test.ts kaji/sdk/kaji/runtime/tools/registry.py kaji/sdk/kaji/runtime/integrations/base.py kaji/sdk/kaji/runtime/integrations/functional.py kaji/sdk/tests/test_tools_registry_sanitize.py
git commit -m "feat(sdk,ts): opt-in onMutate callback on tool-name sanitizer"
```

---

### Task 8: Pluggable OAuth token storage with optional OS keyring backend

**Files:**
- Modify: `kaji/sdk/kaji/integrations/oauth.py`
- Modify: `kaji/sdk/pyproject.toml` (add `oauth-keyring` extra)
- Test: extend `kaji/sdk/tests/test_integrations_oauth.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `TokenStorage` runtime-checkable `Protocol` with `load() -> Optional[dict]` and `save(dict) -> None`.
  - `FileTokenStorage(path)` — current behavior (JSON at chmod 0600).
  - `KeyringTokenStorage(service_name, account)` — uses `keyring` package; raises `OAuthError` with install instructions if `keyring` not installed.
  - `GoogleOAuthClient(..., token_storage: Optional[TokenStorage] = None)` — defaults to `FileTokenStorage(self.token_path)`.

- [ ] **Step 1: Write the failing test**

Append to `kaji/sdk/tests/test_integrations_oauth.py`:

```python
import json
import pytest

from kaji.integrations.oauth import (
    GoogleOAuthClient,
    FileTokenStorage,
    KeyringTokenStorage,
    TokenStorage,
)


def test_file_token_storage_roundtrips(tmp_path):
    storage = FileTokenStorage(tmp_path / "tokens.json")
    payload = {"access_token": "a", "refresh_token": "r", "expires_at": 1.0, "scopes": []}
    storage.save(payload)
    assert storage.load() == payload


def test_keyring_token_storage_uses_keyring(monkeypatch):
    fake_store: dict[tuple[str, str], str] = {}

    class FakeKeyring:
        @staticmethod
        def set_password(service: str, account: str, secret: str) -> None:
            fake_store[(service, account)] = secret

        @staticmethod
        def get_password(service: str, account: str):
            return fake_store.get((service, account))

    monkeypatch.setattr("kaji.integrations.oauth.keyring", FakeKeyring, raising=False)

    storage = KeyringTokenStorage(service_name="kaji-test", account="gmail")
    payload = {"access_token": "a", "refresh_token": "r", "expires_at": 1.0, "scopes": []}
    storage.save(payload)
    assert storage.load() == payload


def test_keyring_token_storage_raises_without_keyring(monkeypatch):
    monkeypatch.setattr("kaji.integrations.oauth.keyring", None, raising=False)
    storage = KeyringTokenStorage(service_name="kaji-test", account="gmail")
    with pytest.raises(Exception, match=r"oauth-keyring"):
        storage.save({"a": 1})


def test_client_accepts_custom_token_storage(tmp_path):
    storage = FileTokenStorage(tmp_path / "tok.json")
    client = GoogleOAuthClient(
        client_id="id",
        client_secret="sec",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        token_path=tmp_path / "ignored.json",
        token_storage=storage,
    )
    assert isinstance(client._token_storage, FileTokenStorage)
    assert client._token_storage is storage


def test_token_storage_is_runtime_checkable():
    # Sanity-check the protocol decoration.
    assert isinstance(FileTokenStorage("/tmp/x"), TokenStorage)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd kaji/sdk && pytest tests/test_integrations_oauth.py -v -k "storage or keyring"`
Expected: FAIL — `FileTokenStorage` etc. not exported.

- [ ] **Step 3: Add TokenStorage protocol and implementations to oauth.py**

In `kaji/sdk/kaji/integrations/oauth.py`, add the imports near the top of the file (extend the existing typing imports):

```python
from typing import Any, Optional, Protocol, runtime_checkable
```

Add the optional-import block after `_REFRESH_BUFFER_SECONDS`:

```python
try:
    import keyring as _keyring_module  # type: ignore
    keyring: Any = _keyring_module
except ImportError:  # pragma: no cover - optional dep
    keyring = None
```

Add the protocol and implementations:

```python
@runtime_checkable
class TokenStorage(Protocol):
    """Persist OAuth tokens. Implementations round-trip a JSON-serialisable dict."""

    def load(self) -> Optional[dict[str, Any]]: ...
    def save(self, data: dict[str, Any]) -> None: ...


class FileTokenStorage:
    """Tokens stored as JSON at a user-controlled path, chmod 0600.

    Suitable for single-user developer machines. On shared hosts prefer
    ``KeyringTokenStorage``.
    """

    def __init__(self, path: "str | Path") -> None:
        self.path = Path(path).expanduser()

    def load(self) -> Optional[dict[str, Any]]:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to load tokens from %s: %s", self.path, exc)
            return None

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2))
        try:
            self.path.chmod(0o600)
        except OSError:
            pass


class KeyringTokenStorage:
    """Tokens stored in the OS keyring (Keychain, libsecret, Credential Manager).

    Requires the optional ``keyring`` extra: ``pip install 'kaji[oauth-keyring]'``.
    Recommended over ``FileTokenStorage`` on shared machines.

    Stores the token dict as a single JSON string. Total payload should stay
    under 100KB for cross-platform compatibility (macOS Keychain caps secrets
    around 512KB; libsecret and Credential Manager are similar). The current
    Google OAuth token payload is well under 1KB; this is a forward warning.
    """

    def __init__(self, *, service_name: str, account: str) -> None:
        self.service_name = service_name
        self.account = account

    def _require_keyring(self) -> None:
        if keyring is None:
            raise OAuthError(
                "KeyringTokenStorage requires the 'keyring' package. "
                "Install with: pip install 'kaji[oauth-keyring]'"
            )

    def load(self) -> Optional[dict[str, Any]]:
        self._require_keyring()
        secret = keyring.get_password(self.service_name, self.account)
        if secret is None:
            return None
        return json.loads(secret)

    def save(self, data: dict[str, Any]) -> None:
        self._require_keyring()
        keyring.set_password(self.service_name, self.account, json.dumps(data))
```

- [ ] **Step 4: Wire TokenStorage into GoogleOAuthClient**

In the same file, modify `__init__`:

```python
def __init__(
    self,
    *,
    client_id: str,
    client_secret: str,
    scopes: list[str] | tuple[str, ...],
    token_path: str | Path,
    callback_port: int = 0,
    open_browser: bool = True,
    token_storage: Optional[TokenStorage] = None,
) -> None:
    if not client_id or not client_secret:
        raise OAuthError(
            "GoogleOAuthClient requires client_id and client_secret. "
            "See the integration's SETUP.md for the Google Cloud step."
        )
    self.client_id = client_id
    self.client_secret = client_secret
    self.scopes = tuple(scopes)
    self.token_path = Path(token_path).expanduser()
    self.callback_port = callback_port
    self.open_browser = open_browser
    self._token_storage: TokenStorage = token_storage or FileTokenStorage(self.token_path)
    self._tokens: Optional[_Tokens] = None
    self._http: Optional[httpx.AsyncClient] = None
```

Replace `_load_tokens` and `_save_tokens`:

```python
def _load_tokens(self) -> Optional[_Tokens]:
    data = self._token_storage.load()
    if data is None:
        return None
    try:
        return _Tokens.from_dict(data)
    except (KeyError, ValueError) as exc:
        logger.warning("Stored tokens malformed: %s", exc)
        return None

def _save_tokens(self, tokens: _Tokens) -> None:
    self._token_storage.save(tokens.to_dict())
```

- [ ] **Step 5: Add the optional extra**

In `kaji/sdk/pyproject.toml`, add to `[project.optional-dependencies]`:

```toml
oauth-keyring = ["keyring>=24"]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd kaji/sdk && pytest tests/test_integrations_oauth.py -v`
Expected: all OAuth tests PASS.

- [ ] **Step 7: Commit**

```bash
git add kaji/sdk/kaji/integrations/oauth.py kaji/sdk/tests/test_integrations_oauth.py kaji/sdk/pyproject.toml
git commit -m "feat(sdk): pluggable OAuth token storage with optional OS keyring backend"
```

---

### Task 9: Collapse Python planner-construction paths

**Files:**
- Modify: `kaji/sdk/kaji/runtime/agents/runtime.py` (lines 80-113: delete `@property def planner`, set `self.planner` directly in `__init__`)
- Test: extend `kaji/sdk/tests/test_agents_runtime.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `AgentRuntime.planner` is a plain attribute set once in `__init__`. The `@property def planner` is deleted; `_explicit_planner` is gone; `_build_planner()` remains as a helper called from `__init__` when no explicit planner is passed. Constructor public signature unchanged.

- [ ] **Step 1: Append the test**

Append to `kaji/sdk/tests/test_agents_runtime.py` (reuse the existing `MockProvider` and `MockEventBus` defined at the top of the file; do NOT introduce new helpers):

```python
@pytest.mark.asyncio
async def test_runtime_uses_explicit_planner_when_provided():
    store = InMemoryEventStore()
    bus = MockEventBus()
    provider = MockProvider()
    sentinel = ToolPlanner(executor=mock_executor)
    runtime = AgentRuntime(bus=bus, store=store, provider=provider, planner=sentinel)
    assert runtime.planner is sentinel


@pytest.mark.asyncio
async def test_runtime_builds_default_planner_when_omitted():
    store = InMemoryEventStore()
    bus = MockEventBus()
    provider = MockProvider()
    runtime = AgentRuntime(bus=bus, store=store, provider=provider, tools=[])
    # Built default planner exists and has the expected interface.
    assert runtime.planner is not None
    assert hasattr(runtime.planner, "execute_scatter_gather") or hasattr(
        runtime.planner, "executeScatterGather"
    )
```

The second assert is defensive: the Python `ToolPlanner` exposes its tool-execution entrypoint under one of those names; pick the one that matches the current source by running `grep -n "def execute" kaji/sdk/kaji/runtime/agents/planner.py`.

- [ ] **Step 2: Run test to confirm it passes against current code (characterization)**

Run: `cd kaji/sdk && pytest tests/test_agents_runtime.py::test_runtime_uses_explicit_planner_when_provided tests/test_agents_runtime.py::test_runtime_builds_default_planner_when_omitted -v`
Expected: PASS. The test pins the current behavior before we refactor.

- [ ] **Step 3: Refactor to a single resolved planner**

In `kaji/sdk/kaji/runtime/agents/runtime.py`:

**Delete first, assign second.** Order matters because the current code has BOTH `@property def planner` (line 111) AND a `_planner` field. If we assign `self.planner` in `__init__` before deleting the property, Python will raise `AttributeError: can't set attribute` (the property has no setter).

Step 3a: Delete the existing `@property def planner` (currently at lines 110-113).

Step 3b: Delete the `_explicit_planner` attribute and any reference to it.

Step 3c: Replace the existing `__init__` body so `self.planner` is the single source of truth. The new `__init__`:

```python
def __init__(
    self,
    bus: EventBusProtocol,
    store: EventStore,
    provider: ModelProvider,
    planner: Optional[ToolPlanner] = None,
    system_prompt: str = "You are a helpful assistant.",
    strategy: Optional[AgentStrategy] = None,
    tools: Optional[List[ToolSpec]] = None,
    rag: Optional[Any] = None,
    rag_top_k: int = 5,
    tool_executor: Optional[ToolExecutor] = None,
    policy: Optional[Any] = None,
    approval_handler: Optional[ApprovalHandler] = None,
    user_id: str = "agent",
):
    self.bus = bus
    self.store = store
    self.provider = provider
    self.tools = tools or []
    self.strategy = strategy or AgentStrategy()
    self._rag = rag
    self._rag_top_k = rag_top_k
    self._user_id = user_id
    self._tool_executor = tool_executor
    self._policy = policy
    self._approval_handler = approval_handler
    self.system_prompt = SystemPrompt(system_prompt)
    self.state_manager = SessionStateManager(self.store)
    self.context_builder = ContextBuilder(self.system_prompt, self.state_manager)
    self.planner: ToolPlanner = planner or self._build_planner()
```

Keep `_build_planner` as-is (it already builds the default planner from `_tool_executor`/`_policy`/`_approval_handler`/`self.tools`); it's now called only from `__init__`, never lazily.

- [ ] **Step 4: Run the new tests + the existing suite**

Run: `cd kaji/sdk && pytest tests/test_agents_runtime.py -v`
Expected: all pass.

- [ ] **Step 5: Run full Python suite**

Run: `cd kaji/sdk && pytest tests/`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add kaji/sdk/kaji/runtime/agents/runtime.py kaji/sdk/tests/test_agents_runtime.py
git commit -m "refactor(sdk): collapse AgentRuntime planner to a single resolved attribute"
```

---

### Task 10: Publish `@kaji/sdk@0.1.1` to npm

**Files:**
- Create: `.github/workflows/ts.publish.yml`
- Modify: `kaji/ts/package.json` (bump version to `0.1.1`)
- Modify: `CHANGELOG.md` if present, else add at repo root

**Interfaces:**
- Consumes: all prior TS tasks merged.
- Produces: an npm-installable `@kaji/sdk@0.1.1`. Subsequent semver releases run via the same workflow on a git tag push.

**Prerequisite (manual, one-time):**
- An `NPM_TOKEN` (automation-grade, scoped to the `@kaji` org) added to the repo's GitHub Actions secrets. Confirm with the org owner before running this task. If the secret is not present, the workflow file still lands; the actual publish waits.

- [ ] **Step 1: Bump the TS package version**

In `kaji/ts/package.json`, change `"version": "0.1.0"` to `"version": "0.1.1"`.

- [ ] **Step 2: Create the publish workflow**

Create `.github/workflows/ts.publish.yml`:

```yaml
name: publish-ts

on:
  push:
    tags:
      - "ts-v*"
  workflow_dispatch:

jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: oven-sh/setup-bun@v2
        with:
          bun-version: latest
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          registry-url: "https://registry.npmjs.org"
      - name: Install dependencies
        run: bun --filter @kaji/sdk install
      - name: Test
        run: bun --filter @kaji/sdk run test
      - name: Build
        run: bun --filter @kaji/sdk run build
      - name: Publish
        working-directory: kaji/ts
        run: npm publish --access public --provenance
        env:
          NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
```

The workflow uses `npm publish` (not `bun publish`) for the `--provenance` flag, which signs the release via GitHub's OIDC. The build step still uses `bun`.

- [ ] **Step 3: Add a CHANGELOG entry**

If `CHANGELOG.md` exists at the repo root, prepend:

```markdown
## @kaji/sdk 0.1.1 — 2026-06-23

### Fixed
- Reject NaN/Infinity in tool-arg numeric validation.
- streamText: rejection observable from `text` and `toolCalls` without iterating `textStream`.
- crypto.randomUUID fallback for runtimes without Web Crypto.

### Changed
- AgentRuntime now accepts `EventBusProtocol` instead of concrete `EventBus`.
- providerSafeToolName takes optional `onMutate` callback (no default warning).

### Added
- Public export: `EventBusProtocol`.
```

If `CHANGELOG.md` does not exist, create it at the repo root with that section.

- [ ] **Step 4: Dry-run the publish locally**

From the repo root:

```bash
cd kaji/ts && bun run test && bun run build
cd dist && ls -la  # confirm artifacts exist
cd .. && npm publish --dry-run
```

Expected: `npm publish --dry-run` prints the file list and `+ @kaji/sdk@0.1.1`. No errors.

- [ ] **Step 5: Commit**

```bash
git add kaji/ts/package.json .github/workflows/ts.publish.yml CHANGELOG.md
git commit -m "chore(ts): publish @kaji/sdk@0.1.1 to npm"
```

- [ ] **Step 6: Tag and trigger the publish (after the PR merges)**

After this branch merges to `main`:

```bash
git checkout main && git pull
git tag ts-v0.1.1
git push origin ts-v0.1.1
```

The workflow runs, tests, builds, and publishes. Confirm at `https://www.npmjs.com/package/@kaji/sdk`.

---

### Task 11: Publish `kaji==0.1.1` to PyPI

**Files:**
- Create: `.github/workflows/python.publish.yml`
- Modify: `kaji/sdk/pyproject.toml` (bump version to `0.1.1`)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: all prior Python tasks merged.
- Produces: `pip install kaji==0.1.1` works from PyPI. Optional extras (`kaji[openai]`, `kaji[anthropic]`, `kaji[oauth-keyring]`) install correctly.

**Prerequisite (manual, one-time):**
- A PyPI "trusted publisher" configured for this repo + workflow. The trusted-publisher model uses OIDC and requires no API token. Confirm at `https://pypi.org/manage/project/kaji/settings/publishing/` before running this task. Alternative: `PYPI_API_TOKEN` in GitHub Actions secrets. Confirm which is set up with the org owner.

- [ ] **Step 1: Bump the Python package version**

In `kaji/sdk/pyproject.toml`, change `version = "0.1.0"` to `version = "0.1.1"`.

- [ ] **Step 2: Create the publish workflow**

Create `.github/workflows/python.publish.yml`:

```yaml
name: publish-python

on:
  push:
    tags:
      - "py-v*"
  workflow_dispatch:

jobs:
  publish:
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      contents: read
      id-token: write   # required for PyPI trusted publishing
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install poetry
        run: pipx install poetry
      - name: Install dependencies
        working-directory: kaji/sdk
        run: poetry install --with dev
      - name: Test
        working-directory: kaji/sdk
        run: poetry run pytest
      - name: Build
        working-directory: kaji/sdk
        run: poetry build
      - name: Publish to PyPI (trusted publisher)
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          packages-dir: kaji/sdk/dist/
```

If the team chose API-token publishing instead of trusted-publisher, replace the final step with:

```yaml
      - name: Publish to PyPI (token)
        working-directory: kaji/sdk
        env:
          POETRY_PYPI_TOKEN_PYPI: ${{ secrets.PYPI_API_TOKEN }}
        run: poetry publish
```

- [ ] **Step 3: Add CHANGELOG entry**

Prepend to `CHANGELOG.md`:

```markdown
## kaji 0.1.1 — 2026-06-23

### Fixed
- OpenAI streaming: surface JSON parse failures via `__parse_error` payload + log.
- OpenAI provider: `generate()` and `generate_stream()` both raise `CancelledError` on cancelled token.

### Added
- Pluggable OAuth `TokenStorage` protocol with `FileTokenStorage` (default) and `KeyringTokenStorage` (optional via `kaji[oauth-keyring]`).
- provider_safe_tool_name accepts optional `on_mutate` callback.

### Changed
- AgentRuntime.planner is now a single resolved attribute (was a property + dual-state field).
```

- [ ] **Step 4: Dry-run the build locally**

```bash
cd kaji/sdk
poetry build
ls -la dist/
# Expected: kaji-0.1.1-py3-none-any.whl and kaji-0.1.1.tar.gz
```

If `dist/` has wheel + sdist, the package is buildable. Run `poetry publish --dry-run` if available, or upload to TestPyPI first:

```bash
poetry config repositories.testpypi https://test.pypi.org/legacy/
poetry publish -r testpypi
# Then pip install -i https://test.pypi.org/simple/ kaji==0.1.1 in a fresh venv
```

- [ ] **Step 5: Commit**

```bash
git add kaji/sdk/pyproject.toml .github/workflows/python.publish.yml CHANGELOG.md
git commit -m "chore(sdk): publish kaji==0.1.1 to PyPI"
```

- [ ] **Step 6: Tag and trigger the publish (after the PR merges)**

After the branch merges:

```bash
git checkout main && git pull
git tag py-v0.1.1
git push origin py-v0.1.1
```

Confirm at `https://pypi.org/project/kaji/`.

---

## Self-Review Notes

**Spec coverage check.** The 2026-06-23 review's P0/P1 items addressed:

| Review finding | Task |
|---|---|
| NaN/Infinity acceptance (planner.ts:15) | Task 1 |
| Silent JSON parse fallback (openai.py:147) | Task 2 |
| Non-streaming cancellation ignored (openai.py:167) | Task 3 |
| Streaming cancellation silent-break asymmetry (openai.py:236) | Task 3 (folded in for symmetry) |
| `crypto.randomUUID` portability (planner.ts:129) | Task 4 |
| `streamText` unhandled rejection (oneshot.ts:106) | Task 5 |
| TS `EventBusProtocol` missing | Task 6 |
| Silent tool-name sanitization | Task 7 |
| OAuth tokens unencrypted on disk | Task 8 (pluggable storage; default still file with chmod 0600, opt-in keyring) |
| Three-way planner construction (Python side) | Task 9 |

**Out of scope** (separately tracked, need brainstorm/spec):
- Retry/backoff/error classification — net-new subsystem.
- Token-usage events / cost tracking — event-schema work.
- Tool middleware seam — design decision.
- SSRF tool-URL allowlist — policy design.
- Structured output / response schemas — net-new.
- `replaySession` event-ordering guarantee in `EventStore` contract — storage-backend audit.
- TS planner-construction simplification — current TS shape (lazy `null` sentinel + cached) is less complex than the Python pre-fix; defer.

**Eng-review fixes applied (from /plan-eng-review):**

- **F1.** Task 1 test now calls `executeScatterGather` (the actual method name) and adds a Step 0 to verify the API shape before writing the test.
- **F2.** Task 3 expanded to make `generate()` AND `generate_stream()` symmetrically raise `CancelledError`. The previous silent-break in `generate_stream` is replaced.
- **F3.** Task 5 test no longer uses `process.on('unhandledRejection')`. Asserts the user-facing contract: each of `text`/`toolCalls`/`textStream` independently observes the rejection. Required a structural change to `streamText` (eager drain) — also captured in Task 5.
- **F4.** Task 7 dropped the module-level `seenMutations`/`_seen_mutations` deduplication set. Default behavior is now no side effect at all; the caller wires `onMutate` to whatever logger they want.
- **F5.** Task 7 audits the four sanitizer call sites and threads `onMutate` through them with an explicit `console.warn` / `logger.warning`. No silent global-state mutation.
- **F6.** Task 8 `TokenStorage` is `@runtime_checkable`. `FileTokenStorage` is a plain class (no `@dataclass`/`__post_init__` ugliness).
- **F7.** Task 8 `KeyringTokenStorage` docstring notes the 100KB payload guideline.
- **F8.** Task 9 uses the existing `MockProvider`/`MockEventBus`/`mock_executor` helpers in `test_agents_runtime.py`. No phantom `make_test_bus`/`StubPlanner` references.
- **F9.** Task 9 explicitly orders the refactor: delete `@property` first, then assign attribute, to avoid `AttributeError: can't set attribute`.
- **F10.** Task 6 has an ASCII diagram showing the `EventBusProtocol` -> `EventBus` -> `AgentRuntime` wiring.
- **F11.** Task 2 keeps the raw input in the privileged log line only. Event payload carries `__parse_error` (no `__raw`). Test asserts both.
- **F12.** Execution-order groups documented at the top of the plan.

**Placeholder scan.** No TBDs, no "add appropriate," every code step has actual code. Test helpers are named against the real symbols in the existing tests.

**Type and symbol consistency.** `EventBusProtocol` is defined once in `protocols.ts` and consumed by `bus.ts`, `runtime.ts`, `index.ts`, and the test. `TokenStorage`/`FileTokenStorage`/`KeyringTokenStorage` are defined in `oauth.py` and used only there + the test. `ToolPlannerOptions.uuid` and `onMutate` are scoped to their immediate consumers.

## GSTACK REVIEW REPORT

| Run | Status | Key findings |
|---|---|---|
| Internal eng review (sonnet, 2026-06-23) | Applied | F1, F2, F3, F4, F5, F6, F7, F8, F9, F10, F11, F12 — all incorporated above |
| Internal CEO review (sonnet, 2026-06-23) | Applied | C1, C2, C3, C4, C5, C6, C8 + C7 (per user choice: keep Task 8 as written) |

CEO review fixes:
- **C1.** Task 9 (planner collapse) kept; documented as prerequisite for the deficiencies-plan runtime work.
- **C2.** Coordination block added: hardening lands BEFORE `2026-06-23-sdk-deficiencies.md`. If order reverses, drop Task 9 from this plan.
- **C3.** Tasks 10 and 11 added: npm + PyPI publish workflows, version bumps to 0.1.1, CHANGELOG entries. The plan now caps at "users can install it."
- **C4.** Goal statement softened: "Close correctness gaps and ONE specific security gap (OAuth at-rest). Broader security (SSRF, middleware) tracked separately." No overclaim.
- **C5.** Success criteria block added: 11 tasks shipped, existing test suites green, one E2E demo, both packages published. `streamText` semantics change flagged as intentional + no current external consumers.
- **C6.** Task 7 already named accurately after the eng-review F4 fix; no rename needed.
- **C7.** Task 8 (OAuth keyring) kept as written per user decision; Gmail/GCal demos justify shipping pluggable storage now.
- **C8.** Execution lanes replace the misleading "Groups" formulation: explicit TS-lane / Python-lane / publish-lane with intra-lane sequencing. Two-subagent parallelism is now safe.

VERDICT: Plan revised. 11 tasks, lane-sequenced. Coordination with sibling SDK plans documented. The cap on the "safe to recommend" thesis (publish to npm + PyPI) is now part of this plan. Task 8 (OAuth keyring) kept per user judgement on Gmail/GCal demo timing.

NO UNRESOLVED DECISIONS
