# Kaji Registry Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the four P1 registry defects surfaced by `/code-review` on the untracked files in `kaji/ts/registry/`: delete stale Python/duplicate sources, track the JSON Schema, align the schema with the manifests it validates.

**Architecture:** Four surgical fixes, no new abstractions, no new code paths. Two file deletions, one schema edit, one git-add. Each task is independently testable: a `node -e ajv.validate(...)` check against every manifest after the schema fix. No runtime SDK code is touched, so existing Vitest suites are unaffected.

**Tech Stack:** JSON Schema draft 2020-12, ajv 8 (added as dev dep in Task 5 — confirmed NOT yet present in `kaji/ts/package.json`), bun. **`kaji/ts/package.json` has `"type": "module"`** — ESM. `__dirname` is not defined; use `import.meta.dirname` (Node 20+) or `fileURLToPath(import.meta.url)`.

## Global Constraints

- **Branch discipline:** all work on `fix/registry-schema-and-cleanup`. Squash-merge with `gh pr merge --squash --delete-branch`.
- **Package manager:** `bun` exclusively. Never `npm`, `yarn`, `pnpm`.
- **No back-compat shims:** pre-1.0. Remove cleanly. No aliased fields, no `extras` and `peerDeps` both.
- **No em-dashes in prose/docs.** Terse technical sentences.
- **Verify branch content before push:** `git diff --stat main...HEAD` before opening a PR.
- **Schema is the contract:** after this plan, every manifest under `kaji/ts/registry/<name>/manifest.json` and `kaji/ts/registry/_template/manifest.json` MUST validate against `kaji/ts/registry/schema.json`. CI gate added in Task 5.
- **Out of scope:** P2 findings (HTTP SSRF doc, fs walkDir error handling, sqlite connection caching, web reader-mode swap). These are real, but they're tool-code changes that belong inside Sub-Plan 2 of the master plan. This plan is **registry-shape only**.
- **Out of scope:** `gcal/`, `github/`, `gmail/` Python-era directories. They're orthogonal to the schema fix and get their own decision (delete vs archive vs `.gitignore`) in a follow-up.

---

### Task 1: Delete the stale `echo/echo.py` and `echo/echo.ts` duplicates

**Files:**
- Delete: `kaji/ts/registry/echo/echo.py`
- Delete: `kaji/ts/registry/echo/echo.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: a registry tree where `echo/` matches every other integration directory (only `index.ts` + `manifest.json` + tests when present). `echo/manifest.json`'s `files: ["index.ts"]` already documents `index.ts` as canonical.

**Why these specific deletions:**
- `echo.py` is a Python predecessor. Commit `dc0bf75` ("feat(sp2): add TS-native registry... drop generated copy") was meant to remove it; it escaped cleanup.
- `echo.ts` is byte-equivalent to `index.ts` minus the integration-template header comment. `git diff --no-index kaji/ts/registry/echo/echo.ts kaji/ts/registry/echo/index.ts` will show only the header delta. Confirmed by reading both files at lines 11-29 of each.

- [ ] **Step 1: Confirm the duplicate before deleting**

Run from repo root:
```bash
diff <(tail -n +9 kaji/ts/registry/echo/echo.ts) <(tail -n +8 kaji/ts/registry/echo/index.ts)
```
Expected output: empty (the bodies are identical after the header comment is skipped on each side; `echo.ts` has 8 lines of `/** ... */` JSDoc header, `index.ts` has 7 lines of `// ...` template-header comments).

If the diff is non-empty, STOP. The files are not byte-equivalent; investigate before deleting.

- [ ] **Step 2: Delete the duplicates**

```bash
rm kaji/ts/registry/echo/echo.py
rm kaji/ts/registry/echo/echo.ts
```

- [ ] **Step 3: Verify the echo integration still imports**

The registry uses `echo/index.ts` as the canonical export (per `echo/manifest.json:7` `"files": ["index.ts"]`). Run:
```bash
cd kaji/ts && bun run --bun -e 'import("./registry/echo/index.ts").then(m => console.log(Object.keys(m)))'
```
Expected output: `[ "say", "shout" ]` (the two `functionTool` exports from `index.ts`).

If this fails because `bun run -e` doesn't accept `.ts` imports, fall back to:
```bash
cd kaji/ts && bunx tsc --noEmit registry/echo/index.ts
```
Expected: exit 0, no type errors.

- [ ] **Step 4: Commit**

```bash
git checkout -b fix/registry-schema-and-cleanup
git add kaji/ts/registry/echo/
git commit -m "fix(registry): drop stale echo.py and echo.ts duplicates

echo.py was a Python predecessor that escaped the dc0bf75 cleanup.
echo.ts was byte-equivalent to index.ts (the manifest's canonical file).
Both confirmed dead via manifest.files = [\"index.ts\"]."
```

---

### Task 1.5: Track `schema.json` BEFORE editing it (reorder gate)

**Files:**
- `kaji/ts/registry/schema.json` — already on disk, untracked.

**Why this happens first, not last:**
- Tasks 2+3 will edit `schema.json`. If the file is untracked when Tasks 2+3 run, `git diff` shows nothing — the edits look like "changes to an untracked file" rather than diffs in git history.
- Stage the file FIRST so Tasks 2+3 land as readable diffs.
- (Original eng review pass-1 finding A5: task-ordering risk. Original plan had this as Task 4; moving to Task 1.5 makes the schema edits land as proper diffs against an initial-tracked baseline.)

- [ ] **Step 1: Confirm `schema.json` is untracked, not gitignored**

```bash
git status kaji/ts/registry/schema.json
git check-ignore kaji/ts/registry/schema.json
```
Expected: `git status` shows it under "Untracked files"; `git check-ignore` exits 1 with no output (not ignored).

- [ ] **Step 2: Stage and commit the pre-edit baseline**

```bash
git add kaji/ts/registry/schema.json
git commit -m "fix(registry): track schema.json so index.json \$schema resolves

Baseline commit. The file was on disk but untracked, breaking the
'./schema.json' reference at registry/index.json:2 for anyone cloning the
repo. Schema edits (extras → peerDeps, drop tools.minItems) land in the
next commit so they show as proper diffs against this baseline."
```

- [ ] **Step 3: Verify the `$schema` reference now resolves from a fresh checkout**

```bash
git archive HEAD kaji/ts/registry/ | tar -tf - | grep -E "(schema\.json|index\.json)$"
```
Expected: both `schema.json` and `index.json` listed.

---

### Task 2: Fix `schema.json` peerDeps field name and shape

**Files:**
- Modify: `kaji/ts/registry/schema.json`

**Interfaces:**
- Consumes: actual manifests on disk (`echo/`, `fs/`, `http/`, `sqlite/`, `web/`, `_template/`) — all use `peerDeps: object<string, string>`.
- Produces: schema that validates every existing manifest. The downstream consumer is `scripts/check-integration.ts` (planned in Sub-Plan 2 of the master plan) and any contributor's editor that follows the `$schema` reference.

**Why this change:**
- Schema currently declares `extras` (array of strings) at `properties.extras`. This is a Python-era carryover (pip extras like `httpx`).
- Every manifest on disk uses `peerDeps` (object of npm-package-name → semver-range), e.g., `sqlite/manifest.json:14` has `"peerDeps": { "better-sqlite3": "^9" }`.
- Schema's root has `additionalProperties: false`, so every manifest **fails strict validation** today.

- [ ] **Step 1: Read the current schema's `extras` block**

```bash
grep -n -A 5 '"extras"' kaji/ts/registry/schema.json
```
Expected: shows lines 74-78 with the `extras` array-of-strings definition.

- [ ] **Step 2: Edit the schema — rename `extras` → `peerDeps`, change shape**

Open `kaji/ts/registry/schema.json` and replace the `extras` block with:
```json
    "peerDeps": {
      "type": "object",
      "additionalProperties": {"type": "string"},
      "description": "npm peer/optional dependencies the integration requires, keyed by package name to semver range (e.g. {\"better-sqlite3\": \"^9\"})."
    }
```

The exact `Edit` operation: `old_string` is the existing `extras` block (with leading whitespace exactly as in the file); `new_string` is the block above.

- [ ] **Step 3: Verify the schema still parses as JSON**

```bash
jq . kaji/ts/registry/schema.json > /dev/null && echo OK
```
Expected: `OK`. If `jq` errors, the edit broke JSON syntax.

- [ ] **Commit deferred — combine with Task 3 below.**

---

### Task 3: Remove `tools.minItems: 1` from `schema.json`

**Files:**
- Modify: `kaji/ts/registry/schema.json`

**Interfaces:**
- Consumes: the current schema after Task 2.
- Produces: schema where `_template/manifest.json` (`tools: []`) validates cleanly. Templates are the canonical shape contributors copy from and must be valid by definition.

**Why this change:**
- `_template/manifest.json:8` has `"tools": []`. Today the template fails its own schema because `tools.minItems: 1` forces at least one tool.
- A template legitimately has no tools yet. Forcing a placeholder tool is more code for the same outcome and Karpathy guideline 2 (simplicity) says don't.

- [ ] **Step 1: Locate the `minItems` line**

```bash
grep -n "minItems" kaji/ts/registry/schema.json
```
Expected: one line — the `tools` array's `minItems: 1`.

- [ ] **Step 2: Edit the schema — remove the `minItems` line**

In `kaji/ts/registry/schema.json`, in the `properties.tools` block, delete the `"minItems": 1` line. The line above it (the closing `}` of the inner items schema) must keep its comma.

Exact `Edit` operation:
- `old_string`:
```
      },
      "minItems": 1
    },
```
- `new_string`:
```
      }
    },
```

(Removes both the line and the now-unnecessary trailing comma on the preceding `}`.)

- [ ] **Step 3: Verify the schema still parses**

```bash
jq . kaji/ts/registry/schema.json > /dev/null && echo OK
```
Expected: `OK`.

- [ ] **Step 4: Commit Tasks 2 and 3 together**

The two schema edits are conceptually one change: "make the schema match the manifests it validates." Commit as one unit.

```bash
git add kaji/ts/registry/schema.json
git commit -m "fix(registry): align schema with manifests (peerDeps, no minItems)

Rename 'extras' (array<string>, Python-era pip-extras shape) to 'peerDeps'
(object<string,string>, npm semver-range map). Every manifest on disk already
uses peerDeps; the schema was stale.

Drop tools.minItems:1 so _template/manifest.json (tools: []) validates.
Templates legitimately have no tools yet."
```

---

### Task 5: Add a CI gate that validates every manifest against the schema

**Files:**
- Create: `kaji/ts/scripts/validate-manifests.ts`

**Interfaces:**
- Consumes: `kaji/ts/registry/schema.json`, every `kaji/ts/registry/*/manifest.json`, `kaji/ts/registry/_template/manifest.json`.
- Produces: a script exitable from CI with code 0 (all valid) or 1 (one or more invalid; prints which manifest and which Ajv error).

**Why this exists:**
- Without it, the schema is documentation. With it, the schema is enforced. Future contributors who add a manifest with a misspelled field name (e.g., `tols` instead of `tools`) get a CI failure with a clear message instead of a silent registry-load bug at runtime.
- This is the smallest possible enforcement: a `.ts` script, run from `package.json`, called by CI.

- [ ] **Step 1: Add `ajv` as a dev dep** (confirmed NOT yet present per `jq '.devDependencies.ajv'` returning null)

```bash
cd kaji/ts && bun add -D ajv
```
Verify:
```bash
cd kaji/ts && jq '.devDependencies.ajv' package.json
```
Expected: a version string like `"^8.x.x"`.

- [ ] **Step 2: Write the shared validator module** (DRY — script and test both import from here)

Create `kaji/ts/scripts/validate-manifests.ts`:
```ts
#!/usr/bin/env bun
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import Ajv from "ajv";

// ESM-safe __dirname (kaji/ts is "type": "module"). Don't use __dirname directly.
const __dirname = dirname(fileURLToPath(import.meta.url));
const REGISTRY_DIR = join(__dirname, "..", "registry");

export type ValidationResult = { dir: string; ok: true } | { dir: string; ok: false; errors: unknown };

export function validateAllManifests(): ValidationResult[] {
  const schema = JSON.parse(readFileSync(join(REGISTRY_DIR, "schema.json"), "utf8"));
  const ajv = new Ajv({ strict: false });
  const validate = ajv.compile(schema);

  const dirs = readdirSync(REGISTRY_DIR, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => e.name);

  const results: ValidationResult[] = [];
  for (const dir of dirs) {
    const path = join(REGISTRY_DIR, dir, "manifest.json");
    // T-G1 guard: skip directories without a manifest (e.g. future _archive/).
    // Don't fail the whole suite on a stray dir; the integration template lint
    // (separate concern) decides whether a missing manifest is itself an error.
    if (!existsSync(path)) {
      console.warn(`SKIP ${dir}/ — no manifest.json (intentional dir without integration?)`);
      continue;
    }
    const manifest = JSON.parse(readFileSync(path, "utf8"));
    if (validate(manifest)) {
      results.push({ dir, ok: true });
    } else {
      results.push({ dir, ok: false, errors: validate.errors });
    }
  }
  return results;
}

// T-G3 negative-test helper. Confirms the schema rejects shapes we expect to reject.
// Exported so the Vitest suite can assert "schema actually catches mistakes",
// not just "current manifests happen to pass."
export function validateOne(manifest: unknown): { ok: boolean; errors: unknown } {
  const schema = JSON.parse(readFileSync(join(REGISTRY_DIR, "schema.json"), "utf8"));
  const ajv = new Ajv({ strict: false });
  const validate = ajv.compile(schema);
  return { ok: !!validate(manifest), errors: validate.errors ?? null };
}

function main(): number {
  const results = validateAllManifests();
  let failures = 0;
  for (const r of results) {
    if (r.ok) {
      console.log(`OK   ${r.dir}/manifest.json`);
    } else {
      failures++;
      console.error(`FAIL ${r.dir}/manifest.json`);
      for (const err of (r.errors as { instancePath?: string; message?: string }[]) ?? []) {
        console.error(`  ${err.instancePath || "/"} ${err.message}`);
      }
    }
  }
  if (failures > 0) {
    console.error(`\n${failures} manifest(s) failed validation`);
    return 1;
  }
  return 0;
}

// Only run main() when invoked directly (not when imported by the test).
if (import.meta.url === `file://${process.argv[1]}`) {
  process.exit(main());
}
```

- [ ] **Step 3: Write the failing Vitest suite** (imports from the script — DRY)

Create `kaji/ts/tests/validate-manifests.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { validateAllManifests, validateOne } from "../scripts/validate-manifests";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REGISTRY_DIR = join(__dirname, "..", "registry");

describe("registry manifests validate against schema.json", () => {
  const results = validateAllManifests();
  for (const r of results) {
    it(`${r.dir}/manifest.json is valid`, () => {
      if (!r.ok) {
        throw new Error(`${r.dir} invalid: ${JSON.stringify(r.errors, null, 2)}`);
      }
      expect(r.ok).toBe(true);
    });
  }

  // T-G2 — named load-bearing case: sqlite's peerDeps is the only non-empty one.
  it("sqlite's peerDeps shape (object<string,string>) validates", () => {
    const manifest = JSON.parse(
      readFileSync(join(REGISTRY_DIR, "sqlite", "manifest.json"), "utf8"),
    );
    const { ok, errors } = validateOne(manifest);
    expect(ok, `errors: ${JSON.stringify(errors)}`).toBe(true);
  });
});

// T-G3 — negative tests. Schema must reject mistakes, not just accept current files.
describe("schema rejects malformed manifests", () => {
  const base = {
    name: "x",
    version: "0.1.0",
    namespace: "x",
    description: "x",
    auth: { kind: "none" },
    files: ["index.ts"],
    tools: [{ name: "y", description: "y" }],
  };

  it("rejects the Python-era 'extras' field (additionalProperties: false at root)", () => {
    const { ok } = validateOne({ ...base, extras: ["httpx"] });
    expect(ok).toBe(false);
  });

  it("rejects peerDeps as array instead of object", () => {
    const { ok } = validateOne({ ...base, peerDeps: ["better-sqlite3"] });
    expect(ok).toBe(false);
  });

  it("rejects peerDeps with non-string version", () => {
    const { ok } = validateOne({ ...base, peerDeps: { "better-sqlite3": 9 } });
    expect(ok).toBe(false);
  });
});
```

- [ ] **Step 4: Run the test — expect all positive cases PASS, negative cases PASS (i.e. schema rejects malformed)**

```bash
cd kaji/ts && bunx vitest run tests/validate-manifests.test.ts
```
Expected: 6+ positive tests (one per registry dir + sqlite-named) plus 3 negative tests all pass.

If any positive test fails, the schema doesn't actually match the manifests — re-read the Ajv error, go back to Task 2 or 3.
If any negative test fails, the schema is **too permissive** — it should reject those shapes. Tighten the schema before merging.

- [ ] **Step 5: Wire into `package.json`**

In `kaji/ts/package.json`'s `"scripts"` block, add:
```json
"validate:registry": "bun scripts/validate-manifests.ts"
```

Verify:
```bash
cd kaji/ts && bun run validate:registry
```
Expected output: 6 lines of `OK   <name>/manifest.json` (echo, fs, http, sqlite, web, _template), exit 0.

- [ ] **Step 6: Commit**

```bash
git add kaji/ts/scripts/validate-manifests.ts kaji/ts/tests/validate-manifests.test.ts kaji/ts/package.json kaji/ts/bun.lock
git commit -m "feat(registry): validate manifests against schema in CI

Adds tests/validate-manifests.test.ts (Vitest) and scripts/validate-manifests.ts
(CI runner). The test imports the script's validateAllManifests + validateOne
helpers — single source of truth, no DRY violation. Both compile schema.json
with ajv and validate every manifest in registry/*/manifest.json + _template/.
Wired as 'bun run validate:registry'.

Includes negative tests (T-G3): schema rejects the Python-era 'extras' field,
peerDeps-as-array, and peerDeps-with-non-string-version. Without these, the
positive loop only proves 'current manifests pass' — not 'schema catches
mistakes.'

Future contributors adding a misspelled or out-of-schema field get a clear
failure instead of a runtime registry-load bug.

ESM-safe: uses fileURLToPath(import.meta.url) for __dirname (kaji/ts is
\"type\": \"module\"; bare __dirname throws ReferenceError at module init)."
```

---

### Task 6: Open the PR

**Files:**
- None directly modified — this is the integration step.

**Interfaces:**
- Consumes: the four commits from Tasks 1+1.5+(2+3 combined)+5.
- Produces: a single squash-merged PR on `main` that fixes all four P1 findings.

- [ ] **Step 1: Verify the branch range**

```bash
git diff --stat main...HEAD
```
Expected: 6 paths changed:
- `kaji/ts/registry/echo/echo.py` deleted
- `kaji/ts/registry/echo/echo.ts` deleted
- `kaji/ts/registry/schema.json` added (Task 1.5) + modified (Tasks 2+3)
- `kaji/ts/scripts/validate-manifests.ts` created
- `kaji/ts/tests/validate-manifests.test.ts` created
- `kaji/ts/package.json` modified (devDeps + script)
- `kaji/ts/bun.lock` modified

If the stat is wildly different (extra files, missing files), STOP and investigate before pushing.

- [ ] **Step 2: Run the full test suite once locally**

```bash
cd kaji/ts && bun run validate:registry && bunx vitest run
```
Expected: validator exits 0; Vitest passes (including the new validate-manifests suite).

- [ ] **Step 3: Push and open PR**

```bash
git push -u origin fix/registry-schema-and-cleanup
gh pr create --title "fix(registry): align schema with manifests, drop stale echo duplicates" --body "$(cat <<'EOF'
## Summary

Fixes four P1 findings from `/code-review` on `kaji/ts/registry/`:

- **R1:** delete stale `echo/echo.py` (Python predecessor) and `echo/echo.ts` (byte-equivalent dup of `index.ts`)
- **R2:** track `schema.json` so `index.json`'s `\$schema: ./schema.json` reference resolves
- **R3:** rename schema's `extras` (array<string>, Python-era) to `peerDeps` (object<string,string>, npm semver map) so every manifest validates
- **R4:** remove `tools.minItems: 1` so `_template/manifest.json` (the canonical contributor template) validates against the schema

Adds a `bun run validate:registry` script + Vitest suite that enforces the schema in CI.

## Test plan

- [ ] `bun run validate:registry` exits 0 and prints `OK` for echo, fs, http, sqlite, web, _template
- [ ] `bunx vitest run tests/validate-manifests.test.ts` passes 6 tests
- [ ] `git archive HEAD kaji/ts/registry/ | tar -tvf - | grep schema.json` shows the file is tracked

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Squash-merge after review**

```bash
gh pr merge --squash --delete-branch
```

---

## Out of scope (deferred to follow-up plans)

These were flagged in the `/code-review` pass but are not registry-shape issues. Each gets its own scope decision:

| Finding | Why deferred |
|---|---|
| R5 — schema doesn't document `auth.optional` | Schema's `auth.additionalProperties: true` permits it; doc-only fix; bundle with the next schema iteration. |
| R6 — http SSRF only fires when allowedHosts is set | Sub-Plan 2.1 of the master plan owns the http integration's security posture. Documentation fix at minimum; deny-private-IP default is a future hardening pass. |
| R7 — http POST/PUT silently JSON.stringify any body | Description-text fix; bundle with Sub-Plan 2.1 polish. |
| R8 — fs walkDir swallows all errors | Sub-Plan 2.2; narrow catch to ENOENT only. |
| R9 — fs.glob walks the entire root per call | Documented as a sandbox-size tradeoff; user-edits-when-they-care per shadcn paradigm. |
| R10 — sqlite opens a new connection per tool call | Sub-Plan 2.4; lazy-init pattern, ~5 lines. |
| R11 — web uses regex strip instead of `@mozilla/readability` | Plan-vs-code mismatch; Sub-Plan 2.3 owns the resolution (plan-first: land readability). |
| R13 — `gcal/`, `github/`, `gmail/` untracked Python directories | Pre-existing carryover; needs explicit user decision (delete vs archive vs `.gitignore`). |

## What already exists (avoid rebuilding)

- `kaji/ts/registry/schema.json` is **on disk but untracked**. Task 4 stages it; we do not write a new schema.
- `kaji/ts/registry/{echo,fs,http,sqlite,web,_template}/manifest.json` already exist and are tracked. We don't touch them. The schema accommodates them.
- `ajv` is already a dep in most Vitest-using TS workspaces; Task 5 step 1 confirms before adding.
- Vitest is the existing test framework — no new test runner needed.

## Failure modes

| Codepath | Failure mode | Test? | Error handling? | User visibility |
|---|---|---|---|---|
| Task 2 schema edit | JSON syntax broken | YES (Task 2 step 3: `jq .` parse) | `jq` errors loudly | clear error in CI |
| Task 3 schema edit | dangling comma after deletion | YES (Task 3 step 3: `jq .` parse) | `jq` errors loudly | clear error in CI |
| Task 5 validator | manifest with extra unknown field | YES (Vitest positive + T-G3 negative) | Ajv error printed with path | clear failure |
| Task 5 validator | new integration dir added with no manifest | YES (T-G1 `existsSync` guard) | warn `SKIP <dir>/ — no manifest.json`; continue rest of suite | clear skip message, suite still passes |
| Task 5 validator | schema.json deleted accidentally | NO — minor | `readFileSync` throws `ENOENT` at suite-init; whole suite fails | confusing but loud; not a silent failure |

**Folded in pass-1 eng review:** the previous "single small gap" (missing-manifest case) is now covered by the T-G1 `existsSync` guard inside `validateAllManifests`. The only remaining minor gap is `schema.json` itself being deleted; that's loud, not silent, so acceptable.

## Worktree parallelization strategy

Sequential. Each task strictly depends on the prior task's commit:
- Task 1 has no prerequisites
- Tasks 2+3 modify the same file (`schema.json`); must run in sequence
- Task 4 commits the file that Tasks 2+3 edited; depends on both
- Task 5 depends on schema being correct (Task 4)
- Task 6 depends on all prior commits

Sequential implementation, no parallelization opportunity.

## Self-review

**Spec coverage check:**

- R1 (stale echo duplicates) → Task 1 ✓
- R2 (untracked schema.json) → Task 1.5 ✓ (reordered from old Task 4 — see eng-review pass 1 A5)
- R3 (extras vs peerDeps mismatch) → Task 2 ✓
- R4 (template fails minItems) → Task 3 ✓
- Schema enforcement (positive cases) → Task 5 ✓
- Schema enforcement (negative cases T-G3) → Task 5 step 3 ✓
- Missing-manifest guard T-G1 → Task 5 step 2 (`existsSync`) ✓
- Named load-bearing T-G2 (sqlite peerDeps) → Task 5 step 3 ✓
- ESM-safe `__dirname` (eng-review pass 1 A2+A3) → Task 5 step 2 (`fileURLToPath(import.meta.url)`) ✓
- DRY validator (eng-review pass 1 A1) → Task 5 step 2 (script exports; test imports) ✓
- PR + merge → Task 6 ✓

**Placeholder scan:** No "TBD", "implement later", or empty steps. Every step has either a command, a code block, or both with expected output.

**Type consistency:** Vitest test file path (`kaji/ts/tests/validate-manifests.test.ts`) and validator script path (`kaji/ts/scripts/validate-manifests.ts`) are used identically across Tasks 5 and 6. `bun run validate:registry` script name is used identically across Tasks 5 and 6. `ajv` import shape is the same in both the test file and the script.

**Schema-vs-manifest cross-check:** after Tasks 2+3, the manifests must validate. Walked through each:
- `echo/manifest.json`: has `name`, `version`, `namespace`, `description`, `auth.kind`, `files`, `tools`, `peerDeps: {}`. All required fields present. ✓
- `fs/manifest.json`: same shape. ✓
- `http/manifest.json`: same shape. ✓
- `sqlite/manifest.json`: has `peerDeps: { "better-sqlite3": "^9" }` — validates against new `object<string, string>` shape. ✓
- `web/manifest.json`: has `auth: { kind: "env", env: "BRAVE_API_KEY", optional: true }`. Schema's `auth.additionalProperties: true` accepts the extra `optional` field. ✓
- `_template/manifest.json`: has `tools: []`. After Task 3, the `minItems: 1` is gone — validates. ✓

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | clean | Pass 1: 5 architecture findings (A1 DRY validator/test, A2+A3 `__dirname` ESM bug — confirmed `kaji/ts` is `"type": "module"`, A4 deletion-history note, A5 task-ordering — schema must be tracked before edited) + 2 code-quality (Q1 ajv import, Q3 missing-manifest guard) + 3 test gaps (T-G1 missing-manifest guard, T-G2 named sqlite case, T-G3 negative tests) — **all folded**. Also confirmed ajv is NOT yet a dep; Task 5 step 1 now adds it explicitly. **No P1 findings; all P2/P3.** |
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | not run | Cleanup plan; no scope/strategy decisions at stake |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | not run | Plan is small enough that outside voice would be noise |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | n/a | No UI scope |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | n/a | Cleanup, not a new DX surface |

**VERDICT:** ENG CLEARED. Plan is execution-ready. 6 tasks, sequential. No P1 findings remain after pass 1. Folded pass-1 fixes: ESM-safe `__dirname` (was guaranteed-to-fail bug), ajv added as dep (was assumed-present bug), validator/test DRY (single source of truth), `existsSync` guard (future-stray-dir safety), named sqlite test + negative tests (schema-rejects-mistakes coverage), task reorder (schema tracked first so edits land as readable diffs). Ready to execute via `superpowers:subagent-driven-development` or `superpowers:executing-plans`.

NO UNRESOLVED DECISIONS
