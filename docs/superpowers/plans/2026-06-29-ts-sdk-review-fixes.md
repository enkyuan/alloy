# TS SDK Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the four actionable review comments on `feat/ts-sdk` before landing the TypeScript SDK registry and approval-handler changes.

**Architecture:** Keep the fix narrow. Reuse existing `kaji add` realpath containment patterns for fs sandboxing, keep approval request events single-owner via a typed-handler capability flag, widen high-level runtime types to match `ToolPlanner`, and remove Python-only registry entries from the TS npm package.

**Tech Stack:** TypeScript, Bun, Vitest, Node `fs/promises`, JSON registry manifests, `@kaji/sdk` local source.

## Global Constraints

- Work only under `kaji/ts/` plus this plan file.
- Do not reintroduce third-party Python integrations into the TS SDK. The TS registry should ship TS-native integrations only.
- Preserve existing public behavior except where the review finding identifies a bug: fs symlink escapes, approval event duplication/race, typed approval handler API mismatch, and dead Python registry entries.
- Keep fixes DRY. If a helper already exists in spirit, mirror the pattern rather than inventing a parallel mechanism.
- Use Bun commands from `kaji/ts`.
- Do not modify root repo package-manager state unless dependency installation explicitly requires it.
- No TODO placeholders in code. Every branch added in these tasks gets a regression test.

---

## What Already Exists

- `kaji/ts/src/cli/add.ts` already contains a realpath-based parent containment guard for writes through symlinked output paths. Reuse this pattern for `registry/fs/index.ts` instead of creating a new policy model.
- `kaji/ts/src/tools/planner.ts` already accepts `AnyApprovalHandler = ApprovalHandler | TypedApprovalHandler` internally. The missing piece is public high-level type plumbing in `AgentRuntime` and `AgentBuilder`.
- `kaji/ts/tests/approval.handler.test.ts` already covers EventStore subscription and `EventApprovalHandler` grant/reject/timeout behavior. Add race and duplicate-event regressions there or in `tools.planner.test.ts`.
- `kaji/ts/tests/runtime.builder.test.ts` and `kaji/ts/tests/runtime.test.ts` already exercise high-level runtime wiring. Add typed approval handler acceptance tests there.
- `kaji/ts/tests/cli.add.test.ts` already proves Python-only fixtures are skipped when present in an artificial registry. The real shipped registry should not include those Python-only entries at all.

## NOT In Scope

- Building TS-native Google Calendar, GitHub, or Gmail integrations. That is product scope, not review cleanup.
- Changing `kaji add` to copy Python files. TS consumers should not receive Python sources.
- Rewriting the event store abstraction. The current store contract is enough once approval handlers subscribe before publishing request events.
- Adding new runtime approval concepts beyond a single typed-handler capability flag.
- Solving TOCTOU races against a malicious local filesystem attacker swapping symlinks between validation and `writeFile`. This plan closes the introduced symlink escape in normal SDK usage; kernel-level no-follow writes would be a separate hardening project.

## Review Findings To Resolve

1. `[P1] kaji/ts/registry/fs/index.ts:14-20` - `sandboxResolve` uses lexical containment only, so reads and writes can follow a symlink inside the sandbox to a path outside the sandbox.
2. `[P1] kaji/ts/src/runtime/approval/event_handler.ts:31-45` and `kaji/ts/src/tools/planner.ts:225-245` - approval request publishing is duplicated, and `EventApprovalHandler` subscribes after publishing so synchronous approvers can be missed.
3. `[P2] kaji/ts/src/index.ts:135-136` plus unchanged runtime/builder types - exported `EventApprovalHandler` cannot be passed to `AgentRuntime` or `AgentBuilder` without a TypeScript error.
4. `[P2] kaji/ts/registry/gcal/manifest.json:11`, `github/manifest.json:11`, `gmail/manifest.json:11` - Python-only registry entries ship in the npm package but are not indexed or usable by the TS CLI.

## Data Flow

```text
fs tool call
  |
  v
sandboxResolve(root, user path, mode)
  |-- lexical path escapes root? -> throw
  |-- read/list/glob target exists?
  |     |-- realpath target outside real root? -> throw or skip
  |     `-- inside root -> operate
  `-- write target missing?
        |-- realpath deepest existing parent outside real root? -> throw
        `-- inside root -> mkdir + write

approval-required tool call
  |
  v
ToolPlanner
  |-- handler publishes its own request event? -> do not emit request
  |-- otherwise emit TOOL_APPROVAL_REQUESTED
  v
approvalHandler.request(...)
  |-- EventApprovalHandler subscribes first
  |-- EventApprovalHandler appends request event
  |-- external approver appends approve/reject
  `-- handler resolves decision without timeout race
```

## Test Coverage Diagram

```text
CODE PATHS                                                   TEST TARGET
[+] fs sandbox
  |-- [GAP] read symlink to outside root is rejected          registry.fs.test.ts
  |-- [GAP] write through symlinked parent is rejected        registry.fs.test.ts
  |-- [GAP] glob does not expose outside-root symlink paths   registry.fs.test.ts
  `-- [TESTED] lexical ../../ escape is rejected              registry.fs.test.ts:140

[+] approval events
  |-- [GAP] synchronous approval after request is captured    approval.handler.test.ts
  |-- [GAP] planner + EventApprovalHandler emits one request  tools.planner.test.ts
  |-- [TESTED] grant/reject/timeout flows                     approval.handler.test.ts:84
  `-- [TESTED] function handler approval emits request        tools.planner.test.ts:82

[+] high-level typed approval API
  |-- [GAP] AgentRuntimeOptions accepts TypedApprovalHandler  runtime.test.ts
  |-- [GAP] AgentBuilder.approvalHandler accepts typed form   runtime.builder.test.ts
  `-- [TESTED] function approval handler still works          runtime.test.ts:442

[+] registry package hygiene
  |-- [GAP] real registry has no Python-only entries          cli.add.test.ts
  |-- [EXISTING] validate remaining manifests cleanly         validate-manifests.test.ts
  `-- [TESTED] real registry ships echo                       cli.add.test.ts:228

COVERAGE AFTER PLAN: 10/10 review-fix paths covered, with existing validate-manifests coverage reused.
```

## Failure Modes

- Fs read/write through symlink: without the fix, a sandboxed agent can read or write outside `opts.root`. Task 1 adds tests and realpath checks.
- Approval event race: without the fix, a UI or bot that approves immediately on `TOOL_APPROVAL_REQUESTED` can be missed, causing a timeout. Task 2 adds a synchronous-approver regression.
- Approval event duplication: without the fix, UIs can render two prompts for one tool call. Task 2 adds a single-request assertion.
- Typed handler API mismatch: without the fix, the exported handler compiles but cannot be used through normal runtime APIs. Task 3 adds compile-level usage tests.
- Python registry entries: without the fix, npm ships dead Python sources and manifests the TS CLI cannot use. Task 4 removes those directories and asserts the real registry stays TS-native.

---

### Task 1: Close symlink escapes in the fs registry integration

**Files:**
- Modify: `kaji/ts/registry/fs/index.ts`
- Modify: `kaji/ts/tests/registry.fs.test.ts`

**Interfaces:**
- Consumes: `createFsIntegration(opts: { root: string })`.
- Produces: the same `list`, `read`, `write`, and `glob` tools, with sandbox resolution that checks real filesystem targets.

- [ ] **Step 1: Write failing symlink regression tests**

Replace the imports at the top of `kaji/ts/tests/registry.fs.test.ts`:
```ts
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createFsIntegration } from "../registry/fs/index";
import type { ToolContext } from "../src/index";
```

Delete the inline `sandboxResolve`, `createFsList`, `createFsRead`, and `createFsWrite` helpers. Those copies are the old weakness: they can pass while the shipped registry template stays vulnerable. Keep this shared context:
```ts
const ctx: ToolContext = { userId: "_" };
```

Rewrite the existing list/read/write tests to call the real integration:
```ts
const { list, read, write, glob } = createFsIntegration({ root: tmpRoot });
```

Replace the direct `sandboxResolve` unit tests with behavior tests through `createFsIntegration`:
```ts
describe("fs integration: sandbox path handling", () => {
  let tmpRoot: string;

  beforeEach(async () => {
    tmpRoot = await mkdtemp(join(tmpdir(), "kaji-fs-test-"));
    await writeFile(join(tmpRoot, "inside.txt"), "inside");
  });

  afterEach(async () => {
    await rm(tmpRoot, { recursive: true, force: true });
  });

  it("allows ordinary paths within root", async () => {
    const { read } = createFsIntegration({ root: tmpRoot });
    await expect(read.handler(ctx, { path: "inside.txt" })).resolves.toEqual({ content: "inside" });
  });

  it("blocks lexical paths that escape the root", async () => {
    const { read } = createFsIntegration({ root: tmpRoot });
    await expect(read.handler(ctx, { path: "../../etc/passwd" })).rejects.toThrow(/escape.*sandbox/i);
  });
});
```

Add symlink regression tests to the existing read/write/glob describes:
```ts
it("rejects reads through a symlink that points outside the root", async () => {
  const outside = await mkdtemp(join(tmpdir(), "kaji-fs-outside-"));
  await writeFile(join(outside, "secret.txt"), "secret");
  await symlink(join(outside, "secret.txt"), join(tmpRoot, "secret-link.txt"));
  const { read } = createFsIntegration({ root: tmpRoot });

  await expect(read.handler(ctx, { path: "secret-link.txt" })).rejects.toThrow(/escape.*sandbox/i);

  await rm(outside, { recursive: true, force: true });
});

it("rejects writes through a symlinked parent directory", async () => {
  const outside = await mkdtemp(join(tmpdir(), "kaji-fs-outside-"));
  await symlink(outside, join(tmpRoot, "linkdir"));
  const { write } = createFsIntegration({ root: tmpRoot });

  await expect(write.handler(ctx, { path: "linkdir/evil.txt", content: "bad" })).rejects.toThrow(
    /escape.*sandbox/i,
  );
  await expect(readFile(join(outside, "evil.txt"), "utf8")).rejects.toThrow();

  await rm(outside, { recursive: true, force: true });
});

it("does not return symlinked outside-root paths from glob", async () => {
  const outside = await mkdtemp(join(tmpdir(), "kaji-fs-outside-"));
  await writeFile(join(outside, "secret.txt"), "secret");
  await symlink(join(outside, "secret.txt"), join(tmpRoot, "secret-link.txt"));
  const { glob } = createFsIntegration({ root: tmpRoot });

  const result = await glob.handler(ctx, { pattern: "**/*" });
  const matches = result["matches"] as string[];
  expect(matches).not.toContain("secret-link.txt");

  await rm(outside, { recursive: true, force: true });
});
```

- [ ] **Step 2: Run the fs tests and confirm they fail**

Run:
```bash
cd kaji/ts && bun test tests/registry.fs.test.ts
```
Expected: the symlink read/write/glob tests fail before `kaji/ts/registry/fs/index.ts` is updated, because the tests import the real shipped registry template.

- [ ] **Step 3: Implement the production sandbox helper**

In `kaji/ts/registry/fs/index.ts`, change imports:
```ts
import { mkdir, readdir, readFile, realpath, writeFile } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";
```

Replace `sandboxResolve` with:
```ts
async function deepestExisting(path: string): Promise<string> {
  let probe = path;
  while (probe !== dirname(probe)) {
    try {
      await realpath(probe);
      return probe;
    } catch {
      probe = dirname(probe);
    }
  }
  return probe;
}

function isInside(root: string, candidate: string): boolean {
  const rel = relative(root, candidate);
  return rel === "" || (!rel.startsWith("..") && resolve(root, rel) === candidate);
}

async function sandboxResolve(root: string, unsafePath: string, mode: "read" | "write"): Promise<string> {
  const rootPath = resolve(root);
  const rootReal = await realpath(rootPath);
  const resolved = resolve(rootPath, unsafePath);
  const rel = relative(rootPath, resolved);
  if (rel.startsWith("..") || resolve(rootPath, rel) !== resolved) {
    throw new Error(`Path escapes sandbox root: ${JSON.stringify(unsafePath)}`);
  }

  try {
    const targetReal = await realpath(resolved);
    if (!isInside(rootReal, targetReal)) {
      throw new Error(`Path escapes sandbox root: ${JSON.stringify(unsafePath)}`);
    }
    return targetReal;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT" || mode === "read") {
      throw error;
    }
  }

  const parent = await deepestExisting(dirname(resolved));
  const parentReal = await realpath(parent);
  if (!isInside(rootReal, parentReal)) {
    throw new Error(`Path escapes sandbox root: ${JSON.stringify(unsafePath)}`);
  }
  return resolved;
}
```

Update callers:
```ts
// fsList and fsRead
const safe = await sandboxResolve(root, path, "read");

// fsWrite
const safe = await sandboxResolve(root, path, "write");
```

Replace `walkDir` so `glob` skips symlinked entries and refuses traversal outside the real root:
```ts
async function walkDir(dir: string, rootReal: string): Promise<string[]> {
  const dirReal = await realpath(dir);
  if (!isInside(rootReal, dirReal)) {
    throw new Error(`Path escapes sandbox root: ${JSON.stringify(dir)}`);
  }

  const files: string[] = [];
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return files;
  }
  for (const entry of entries) {
    const full = join(dir, entry.name);
    if (entry.isSymbolicLink()) {
      continue;
    }
    if (entry.isDirectory()) {
      files.push(...(await walkDir(full, rootReal)));
    } else {
      files.push(full);
    }
  }
  return files;
}
```

Update `fsGlob` to pass the resolved root into `walkDir`:
```ts
const rootReal = await realpath(root);
const allFiles = await walkDir(root, rootReal);
```

- [ ] **Step 4: Run verification**

Run:
```bash
cd kaji/ts && bun test tests/registry.fs.test.ts
cd kaji/ts && bun run typecheck
```
Expected: both commands pass.

- [ ] **Step 5: Commit**

```bash
git add kaji/ts/registry/fs/index.ts kaji/ts/tests/registry.fs.test.ts
git commit -m "fix(ts-sdk): block fs sandbox symlink escapes"
```

---

### Task 2: Make approval request events single-owner and race-free

**Files:**
- Modify: `kaji/ts/src/runtime/approval/types.ts`
- Modify: `kaji/ts/src/runtime/approval/event_handler.ts`
- Modify: `kaji/ts/src/tools/planner.ts`
- Modify: `kaji/ts/tests/approval.handler.test.ts`
- Modify: `kaji/ts/tests/tools.planner.test.ts`

**Interfaces:**
- Consumes: `TypedApprovalHandler.request(call, ctx)`.
- Produces: typed handlers can declare `emitsApprovalRequest === true`; `ToolPlanner` emits the request only when the handler does not.

- [ ] **Step 1: Add failing approval tests**

In `kaji/ts/tests/approval.handler.test.ts`, add:
```ts
it("captures a synchronous approval appended by a request-event subscriber", async () => {
  const store = new InMemoryEventStore();
  const handler = new EventApprovalHandler(store);
  const call = makeCall({ id: "call-sync" });
  const ctx = { sessionId: "session-sync" };

  store.subscribe(ctx.sessionId, (event) => {
    if (event.type === EventType.TOOL_APPROVAL_REQUESTED && event.tool_call_id === call.id) {
      void store.append(
        KajiEvent.parse({
          type: EventType.TOOL_APPROVAL_APPROVED,
          session_id: ctx.sessionId,
          tool_name: call.name,
          tool_call_id: call.id,
        }),
      );
    }
  });

  await expect(handler.request(call, ctx)).resolves.toEqual({ granted: true });
});
```

In `kaji/ts/tests/tools.planner.test.ts`, add imports:
```ts
import { InMemoryEventStore } from "../src/events/store";
import { KajiEvent } from "../src/events/schemas";
import { EventApprovalHandler } from "../src/runtime/approval/event_handler";
```

Add a planner test that uses the real event handler and the same event store as the planner emit path:
```ts
it("emits exactly one approval request when EventApprovalHandler publishes request events", async () => {
  const store = new InMemoryEventStore();
  const sessionId = "sess-event-handler-approval";
  const executor = vi.fn().mockResolvedValue({ ok: true });
  const approvalHandler = new EventApprovalHandler(store, { timeoutMs: 250 });
  const policy = new ToolPolicy({ requireApprovalFor: new Set(["destructive"]) });
  const specs = new Map([
    ["nuke", { name: "nuke", description: "nuke", parameters: {}, risk: "destructive" as const }],
  ]);

  store.subscribe(sessionId, (event) => {
    if (event.type === EventType.TOOL_APPROVAL_REQUESTED && event.tool_call_id === "c-typed") {
      void store.append(
        KajiEvent.parse({
          type: EventType.TOOL_APPROVAL_APPROVED,
          session_id: sessionId,
          tool_name: "nuke",
          tool_call_id: "c-typed",
        }),
      );
    }
  });

  const planner = new ToolPlanner({ executor, policy, approvalHandler, specs });
  const results = await planner.executeScatterGather(sessionId, [{ id: "c-typed", name: "nuke", arguments: {} }], async (e) => {
    await store.append(e);
  });

  const events = await store.getEvents(sessionId);
  expect(events.filter((e) => e.type === EventType.TOOL_APPROVAL_REQUESTED)).toHaveLength(1);
  expect(events.map((e) => e.type)).toContain(EventType.TOOL_APPROVAL_APPROVED);
  expect(results[0]).toHaveProperty("result", { ok: true });
});
```

- [ ] **Step 2: Run approval tests and confirm they fail**

Run:
```bash
cd kaji/ts && bun test tests/approval.handler.test.ts tests/tools.planner.test.ts
```
Expected: the synchronous approval test times out or fails; the typed-handler capability field is not yet accepted by TypeScript.

- [ ] **Step 3: Extend the typed handler contract**

In `kaji/ts/src/runtime/approval/types.ts`, change:
```ts
export interface TypedApprovalHandler {
  readonly emitsApprovalRequest?: boolean;
  request(call: ToolCall, ctx: ToolContext): Promise<ApprovalDecision>;
}
```

In `kaji/ts/src/runtime/approval/event_handler.ts`, add the class property:
```ts
export class EventApprovalHandler implements TypedApprovalHandler {
  readonly emitsApprovalRequest = true;
```

- [ ] **Step 4: Subscribe before publishing in EventApprovalHandler**

Replace `request` in `kaji/ts/src/runtime/approval/event_handler.ts` with:
```ts
async request(call: ToolCall, ctx: ToolContext): Promise<ApprovalDecision> {
  const timeoutMs = this.opts.timeoutMs ?? DEFAULT_TIMEOUT_MS;

  return new Promise<ApprovalDecision>((resolve, reject) => {
    let settled = false;
    let unsubscribe: () => void = () => {};
    let timer: ReturnType<typeof setTimeout>;

    const finish = (decision: ApprovalDecision): void => {
      if (settled) return;
      settled = true;
      unsubscribe();
      clearTimeout(timer);
      resolve(decision);
    };

    unsubscribe = this.store.subscribe(ctx.sessionId, (event) => {
      if (event.type === EventType.TOOL_APPROVAL_APPROVED && event.tool_call_id === call.id) {
        finish({ granted: true });
        return;
      }

      if (event.type === EventType.TOOL_APPROVAL_REJECTED && event.tool_call_id === call.id) {
        finish({ granted: false, reason: event.reason ?? undefined });
      }
    });

    timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      unsubscribe();
      reject(new Error(`Tool approval timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    void this.store
      .append(
        KajiEvent.parse({
          type: EventType.TOOL_APPROVAL_REQUESTED,
          session_id: ctx.sessionId,
          tool_name: call.name,
          tool_call_id: call.id,
          tool_args: call.args,
          risk: ctx.risk ?? null,
        }),
      )
      .catch((error) => {
        if (settled) return;
        settled = true;
        unsubscribe();
        clearTimeout(timer);
        reject(error);
      });
  });
}
```

- [ ] **Step 5: Stop planner duplicate request emission**

In `kaji/ts/src/tools/planner.ts`, before emitting `TOOL_APPROVAL_REQUESTED`, compute:
```ts
const handlerPublishesApprovalRequest =
  this.approvalHandler !== undefined &&
  typeof this.approvalHandler !== "function" &&
  this.approvalHandler.emitsApprovalRequest === true;
```

Wrap the existing `await emit(KajiEvent.parse({ type: EventType.TOOL_APPROVAL_REQUESTED, ... }))` block:
```ts
if (!handlerPublishesApprovalRequest) {
  await emit(
    KajiEvent.parse({
      type: EventType.TOOL_APPROVAL_REQUESTED,
      session_id: sessionId,
      tool_name: toolName,
      tool_call_id: callId,
      tool_args: toolArgs,
      risk: risk ?? null,
      metadata,
    }),
  );
}
```

- [ ] **Step 6: Run verification**

Run:
```bash
cd kaji/ts && bun test tests/approval.handler.test.ts tests/tools.planner.test.ts
cd kaji/ts && bun run typecheck
```
Expected: both commands pass. Existing function-style approval tests still see planner-emitted request events.

- [ ] **Step 7: Commit**

```bash
git add kaji/ts/src/runtime/approval/types.ts kaji/ts/src/runtime/approval/event_handler.ts kaji/ts/src/tools/planner.ts kaji/ts/tests/approval.handler.test.ts kaji/ts/tests/tools.planner.test.ts
git commit -m "fix(ts-sdk): make approval request events single-owner"
```

---

### Task 3: Accept typed approval handlers through AgentRuntime and AgentBuilder

**Files:**
- Modify: `kaji/ts/src/tools/planner.ts`
- Modify: `kaji/ts/src/runtime/runtime.ts`
- Modify: `kaji/ts/src/runtime/builder.ts`
- Modify: `kaji/ts/tests/runtime.test.ts`
- Modify: `kaji/ts/tests/runtime.builder.test.ts`

**Interfaces:**
- Consumes: `AnyApprovalHandler`.
- Produces: `AgentRuntimeOptions.approvalHandler`, `AgentBuilder.approvalHandler`, and private fields accept both legacy function handlers and typed object handlers.

- [ ] **Step 1: Export `AnyApprovalHandler` from planner**

In `kaji/ts/src/tools/planner.ts`, change:
```ts
type AnyApprovalHandler = ApprovalHandler | TypedApprovalHandler;
```
to:
```ts
export type AnyApprovalHandler = ApprovalHandler | TypedApprovalHandler;
```

- [ ] **Step 2: Widen runtime types**

In `kaji/ts/src/runtime/runtime.ts`, change the import:
```ts
import { ToolPlanner, type AnyApprovalHandler } from "../tools/planner";
```

Change both type sites:
```ts
approvalHandler?: AnyApprovalHandler;
private readonly approvalHandler: AnyApprovalHandler | undefined;
```

- [ ] **Step 3: Widen builder types**

In `kaji/ts/src/runtime/builder.ts`, change the import:
```ts
import { ToolPlanner, type AnyApprovalHandler } from "../tools/planner";
```

Change the field and method:
```ts
private _approvalHandler: AnyApprovalHandler | undefined;

approvalHandler(handler: AnyApprovalHandler): this {
  this._approvalHandler = handler;
  return this;
}
```

- [ ] **Step 4: Add high-level usage tests**

In `kaji/ts/tests/runtime.test.ts`, add:
```ts
it("runs approval-required tools when a typed approval handler approves", async () => {
  const store = new InMemoryEventStore();
  const bus = new EventBus();
  const runtime = new AgentRuntime({
    provider: new MockProvider(),
    store,
    bus,
    policy: new ToolPolicy({ requireApprovalFor: new Set(["destructive"]) }),
    approvalHandler: {
      async request() {
        return { granted: true };
      },
    },
    tools: [
      {
        name: "get_weather",
        description: "weather",
        parameters: {},
        risk: "destructive",
      },
    ],
    toolExecutor: async () => ({ tempF: 68 }),
  });
  const s = "s-policy-typed-approve";
  await seed(store, s);

  await runtime.runTurn(s);

  const types = (await store.getEvents(s)).map((e) => e.type);
  expect(types).toContain(EventType.TOOL_APPROVAL_APPROVED);
  expect(types).toContain(EventType.TOOL_CALL_COMPLETED);
});
```

In `kaji/ts/tests/runtime.builder.test.ts`, add a compile/runtime smoke test:
```ts
it("accepts typed approval handlers in the fluent builder", () => {
  const { bus, store } = makeInfra();
  const runtime = new AgentBuilder()
    .provider(new MockProvider())
    .approvalHandler({
      async request() {
        return { granted: true };
      },
    })
    .build({ bus, store });

  expect(runtime).toBeInstanceOf(AgentRuntime);
});
```

- [ ] **Step 5: Run verification**

Run:
```bash
cd kaji/ts && bun test tests/runtime.test.ts tests/runtime.builder.test.ts
cd kaji/ts && bun run typecheck
```
Expected: both commands pass and legacy function handler tests still pass.

- [ ] **Step 6: Commit**

```bash
git add kaji/ts/src/tools/planner.ts kaji/ts/src/runtime/runtime.ts kaji/ts/src/runtime/builder.ts kaji/ts/tests/runtime.test.ts kaji/ts/tests/runtime.builder.test.ts
git commit -m "fix(ts-sdk): expose typed approval handlers through runtime APIs"
```

---

### Task 4: Remove Python-only third-party registry entries from the TS package

**Files:**
- Delete: `kaji/ts/registry/gcal/SETUP.md`
- Delete: `kaji/ts/registry/gcal/gcal.py`
- Delete: `kaji/ts/registry/gcal/manifest.json`
- Delete: `kaji/ts/registry/github/github.py`
- Delete: `kaji/ts/registry/github/manifest.json`
- Delete: `kaji/ts/registry/gmail/SETUP.md`
- Delete: `kaji/ts/registry/gmail/gmail.py`
- Delete: `kaji/ts/registry/gmail/manifest.json`
- Modify: `kaji/ts/tests/cli.add.test.ts`

**Interfaces:**
- Consumes: `kaji/ts/registry/index.json`, which only indexes `echo`, `http`, `fs`, `web`, and `sqlite`.
- Produces: an npm package registry tree that contains only TS-native, indexed registry entries plus `_template`.

- [ ] **Step 1: Add failing real-registry hygiene test**

In `kaji/ts/tests/cli.add.test.ts`, add:
```ts
it("does not ship unindexed Python-only integrations in the real TS registry", () => {
  const realRegistry = join(__dirname, "..", "registry");
  expect(existsSync(join(realRegistry, "gcal"))).toBe(false);
  expect(existsSync(join(realRegistry, "github"))).toBe(false);
  expect(existsSync(join(realRegistry, "gmail"))).toBe(false);
});
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:
```bash
cd kaji/ts && bun test tests/cli.add.test.ts
```
Expected: the new hygiene test fails because the directories still exist.

- [ ] **Step 3: Delete Python-only directories**

Run:
```bash
git rm -r kaji/ts/registry/gcal kaji/ts/registry/github kaji/ts/registry/gmail
```

- [ ] **Step 4: Verify registry validation still covers indexed entries**

Run:
```bash
cd kaji/ts && bun run validate:registry
cd kaji/ts && bun test tests/cli.add.test.ts tests/validate-manifests.test.ts
```
Expected: validation passes for `_template`, `echo`, `fs`, `http`, `sqlite`, and `web`; no references to `gcal`, `github`, or `gmail` remain.

- [ ] **Step 5: Search for stale references**

Run:
```bash
rg "gcal|gmail|github" kaji/ts/registry kaji/ts/tests kaji/ts/src
```
Expected: only the new real-registry hygiene test references these names; no Python source, manifest, registry index, or SDK runtime references remain.

- [ ] **Step 6: Commit**

```bash
git add kaji/ts/tests/cli.add.test.ts
git commit -m "fix(ts-sdk): remove Python-only registry entries from TS package"
```

---

### Task 5: Final verification and review handoff

**Files:**
- No source changes unless a previous verification failure requires a targeted fix.

**Interfaces:**
- Consumes: all prior task commits.
- Produces: a branch ready for a fresh diff review.

- [ ] **Step 1: Install dependencies if this checkout has no local toolchain**

Run:
```bash
cd kaji/ts && bun install
```
Expected: `node_modules/.bin/tsc`, `vitest`, and `ajv` are available.

- [ ] **Step 2: Run focused tests**

Run:
```bash
cd kaji/ts && bun test tests/registry.fs.test.ts tests/approval.handler.test.ts tests/tools.planner.test.ts tests/runtime.test.ts tests/runtime.builder.test.ts tests/cli.add.test.ts tests/validate-manifests.test.ts
```
Expected: all focused regression tests pass.

- [ ] **Step 3: Run package verification**

Run:
```bash
cd kaji/ts && bun run validate:registry
cd kaji/ts && bun run typecheck
cd kaji/ts && bun test
```
Expected: all commands pass.

- [ ] **Step 4: Inspect final diff**

Run:
```bash
git diff --stat fc4170a6abcce53828a3ee520388a0374b65e374
git diff fc4170a6abcce53828a3ee520388a0374b65e374 -- kaji/ts/registry/fs/index.ts kaji/ts/src/runtime/approval kaji/ts/src/tools/planner.ts kaji/ts/src/runtime/runtime.ts kaji/ts/src/runtime/builder.ts kaji/ts/registry
```
Expected: diff is limited to the four review fixes plus tests.

- [ ] **Step 5: Resolve verification failures at the owning task**

If Task 5 fails, return to the task that owns the failing file, patch that task's files, rerun that task's focused verification, and amend or add a commit with that task's exact `git add` command. Do not create a broad verification-only commit and do not use `git add -A`.

## Implementation Tasks

Synthesized from this review's findings. Each task derives from a specific finding above. Run with Claude Code or Codex; checkbox as you ship.

- [ ] **T1 (P1, human: ~2h / CC: ~20min)** - fs registry - Close symlink escapes in sandbox path resolution.
  - Surfaced by: Code review finding on `kaji/ts/registry/fs/index.ts:14-20`.
  - Files: `kaji/ts/registry/fs/index.ts`, `kaji/ts/tests/registry.fs.test.ts`.
  - Verify: `cd kaji/ts && bun test tests/registry.fs.test.ts && bun run typecheck`.
- [ ] **T2 (P1, human: ~2h / CC: ~25min)** - approval runtime - Make approval request events single-owner and subscribe before publishing.
  - Surfaced by: Code review finding on `kaji/ts/src/runtime/approval/event_handler.ts:31-45` and `kaji/ts/src/tools/planner.ts:225-245`.
  - Files: `kaji/ts/src/runtime/approval/types.ts`, `kaji/ts/src/runtime/approval/event_handler.ts`, `kaji/ts/src/tools/planner.ts`, `kaji/ts/tests/approval.handler.test.ts`, `kaji/ts/tests/tools.planner.test.ts`.
  - Verify: `cd kaji/ts && bun test tests/approval.handler.test.ts tests/tools.planner.test.ts && bun run typecheck`.
- [ ] **T3 (P2, human: ~45min / CC: ~10min)** - runtime API - Thread typed approval handler types through AgentRuntime and AgentBuilder.
  - Surfaced by: Code review finding on `kaji/ts/src/index.ts:135-136` exposing handlers that high-level APIs reject.
  - Files: `kaji/ts/src/tools/planner.ts`, `kaji/ts/src/runtime/runtime.ts`, `kaji/ts/src/runtime/builder.ts`, `kaji/ts/tests/runtime.test.ts`, `kaji/ts/tests/runtime.builder.test.ts`.
  - Verify: `cd kaji/ts && bun test tests/runtime.test.ts tests/runtime.builder.test.ts && bun run typecheck`.
- [ ] **T4 (P2, human: ~30min / CC: ~10min)** - TS registry - Remove unindexed Python-only registry directories from the shipped TS package.
  - Surfaced by: Code review finding on `kaji/ts/registry/gcal/manifest.json:11`, `github/manifest.json:11`, and `gmail/manifest.json:11`.
  - Files: `kaji/ts/registry/gcal`, `kaji/ts/registry/github`, `kaji/ts/registry/gmail`, `kaji/ts/tests/cli.add.test.ts`.
  - Verify: `cd kaji/ts && bun run validate:registry && bun test tests/cli.add.test.ts tests/validate-manifests.test.ts`.

## Worktree Parallelization Strategy

| Step | Modules touched | Depends on |
|------|-----------------|------------|
| T1 fs sandbox | `kaji/ts/registry/fs`, `kaji/ts/tests` | - |
| T2 approval events | `kaji/ts/src/runtime/approval`, `kaji/ts/src/tools`, `kaji/ts/tests` | - |
| T3 runtime API types | `kaji/ts/src/runtime`, `kaji/ts/src/tools`, `kaji/ts/tests` | T2 if `TypedApprovalHandler` adds `emitsApprovalRequest` |
| T4 registry cleanup | `kaji/ts/registry`, `kaji/ts/tests` | - |
| T5 verification | all changed modules | T1, T2, T3, T4 |

Lane A: T1 (fs sandbox).
Lane B: T2 -> T3 (approval/type plumbing, sequential because both touch planner approval types).
Lane C: T4 (registry cleanup).
Execution order: launch A + B + C in parallel worktrees, merge, then run T5 in the integration worktree.
Conflict flags: all lanes touch `kaji/ts/tests`, so expect small test-file merge conflicts if multiple workers add imports near the top.

## Plan-Tune Pass

Question tuning is effectively uncalibrated in this environment: declared profile is empty, inferred sample size is 0, and `EXPLAIN_LEVEL` is `default`. I therefore used the user's stated repo preferences as the tuning source: complete edge-case coverage, explicit over clever, right-sized diff, and avoid reintroducing third-party integrations.

## Engineering Review Summary

- Step 0 Scope Challenge: accepted as-is. Four review comments become four implementation tasks. No scope reduction needed.
- Architecture Review: 0 blocking architecture issues after adding the single-owner approval event capability flag.
- Code Quality Review: 2 plan-quality issues found and fixed. Task 1 now tests the shipped fs registry template instead of copied helpers, and Task 5 now routes verification failures back to the owning task instead of a broad placeholder commit.
- Test Review: 7 implementation gaps and 3 plan-test gaps identified and assigned to exact test files, with existing validate-manifests coverage reused.
- Performance Review: 0 issues. Added checks are filesystem-bound and only run during fs tool invocations or approval gating.
- NOT in scope: written.
- What already exists: written.
- TODOS.md updates: 0 items proposed. No `TODOS.md` found.
- Failure modes: 5 listed, 0 silent critical gaps after planned tests.
- Outside voice: skipped. The user requested local plan iteration with named skills, not cross-model review.
- Parallelization: 3 lanes, 3 parallel before final verification.
- Lake Score: 4/4 implementation recommendations choose the complete fix over a shortcut; 4/4 second-pass plan gaps are resolved.

## Plan-Eng Review Addendum

Second-pass findings folded into this plan:

- [P1] (confidence: 9/10) Task 1 test design - The earlier plan edited copied fs test helpers in `registry.fs.test.ts`, so production could stay vulnerable while tests passed. Fixed by making fs tests call `createFsIntegration` from the shipped registry template.
- [P2] (confidence: 8/10) Task 1 glob coverage - The earlier coverage diagram claimed glob protection without specifying a real glob test or `walkDir` hardening. Fixed with a glob symlink regression and a `walkDir(dir, rootReal)` implementation that skips symlinks.
- [P2] (confidence: 8/10) Task 2 TypeScript snippet - The approval handler snippet could trip block-scoped variable checks around `unsubscribe` and `timer`. Fixed with explicit `let` bindings before subscribing and scheduling the timeout.
- [P3] (confidence: 9/10) Task 4/5 execution hygiene - The earlier plan had a conditional `validate-manifests.test.ts` edit and a placeholder git command. Fixed by removing both and keeping git staging scoped to exact owner files.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | - | Not needed for review-comment cleanup |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | ISSUES FOUND | 4 actionable findings converted into tasks |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 2 | CLEAR | 4 implementation tasks, 4 plan gaps fixed, 0 unresolved decisions, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | - | Not applicable, no UI scope |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | - | Not applicable, no developer-facing flow change beyond bug fixes |

- **VERDICT:** ENG CLEARED after second pass - ready to implement the four review-fix tasks.

NO UNRESOLVED DECISIONS
