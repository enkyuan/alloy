# Kaji SDK Release Gaps Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining pre-beta trust gaps in `kaji/sdk` and `kaji/ts` without expanding SDK scope beyond the stable core agent loop.

**Architecture:** Keep the existing `AgentBuilder -> ToolRegistry -> ToolPlanner -> AgentRuntime -> ModelProvider` runtime shape. This plan only tightens release gates, packaging hygiene, provider test seams, and public stability contracts. Keyed live proof stays a real provider operation, not a mocked substitute.

**Tech Stack:** Python, Pydantic, pytest, ruff, ty, uv, setuptools, TypeScript, Vitest, tsc, Bun, tsup, OpenAI live integration tests, GitButler for checkpoint commits.

## Global Constraints

- Do not rewrite providers, runtime architecture, Redis, voice, RAG, or integration catalog.
- Keep `gpt-5.4-mini` as the default first live OpenAI model.
- Live tests must skip cleanly without `OPENAI_API_KEY`.
- `KAJI_REQUIRE_LIVE_KEYS=1` must fail loudly without `OPENAI_API_KEY`.
- Treat stable core as the beta promise: builder, runtime, tool registry/planner, replay, OpenAI/Anthropic, in-memory bus/store.
- Treat Redis realtime/history, voice/TTS, DocumentRAG, native Gemini/Kimi, and tool retrieval as experimental Python-only unless separately hardened.
- TS Gemini/Kimi remain OpenAI-compatible factories, not native provider implementations.
- Use GitButler (`but`) for version-control inspection and checkpoint commits. If `but` is unavailable, stop at the verification report and ask the user to restore GitButler before committing.

---

## File Structure

- `kaji/scripts/live-openai-tool-loop.sh`: existing root live readiness gate. Keep behavior; add tests around no-key and require-key modes.
- `kaji/sdk/tests/test_live_gate.py`: new Python subprocess tests for the root live gate's no-key behavior.
- `kaji/sdk/pyproject.toml`: declare registry namespace packages so setuptools stops warning while preserving the current `src/` remap.
- `kaji/sdk/src/integrations/registry/__init__.py`: new package marker for bundled registry data/modules.
- `kaji/sdk/src/integrations/registry/echo/__init__.py`: new package marker for the echo registry module.
- `kaji/sdk/tests/test_release_smoke.py`: extend release smoke script tests to assert registry package declarations.
- `kaji/sdk/scripts/verify_wheel.sh`: keep current wheel checks; add checks for registry `__init__.py` files if package markers are added.
- `kaji/ts/tests/cancellation.test.ts`: stop mutating private provider fields; use existing constructor hooks.
- `kaji/RELEASE_MATRIX.md`: new cross-SDK release matrix covering stable, experimental, not ported, release gates, and manual provider matrix.
- `kaji/sdk/README.md`, `kaji/ts/README.md`, `docs/MVP.md`: link to the release matrix and tighten release-gate wording.
- `kaji/sdk/tests/test_stability_contract.py`: assert docs and release matrix retain the stability contract.
- `kaji/ts/tests/docs-contract.test.ts`: assert TS docs and release matrix retain the cross-SDK parity contract.

## What Already Exists

- `kaji/scripts/live-openai-tool-loop.sh` already has correct skip/fail behavior and runs both live tool-loop tests.
- `kaji/sdk/tests/integration/test_openai_tools.py` already asserts requested tool, completed tool, final assistant text, and no exhausted turn.
- `kaji/ts/tests/integration/openai-tools.test.ts` already asserts the same live-readiness signal for TS.
- `OpenAIProvider` and `AnthropicProvider` already expose internal constructor hooks for test-only client injection.
- `kaji/sdk/scripts/release_smoke.sh` already builds, verifies, installs, and smoke-tests the wheel.
- `kaji/sdk/scripts/verify_wheel.sh` already rejects cache files and stale renamed modules in wheels.

## NOT In Scope

- No native TS Redis realtime, voice/TTS, RAG, Gemini, or Kimi implementation.
- No production hardening of Python Redis, voice/TTS, DocumentRAG, native Gemini/Kimi, or retrieval.
- No Python package layout migration from the current `src/` remap.
- No provider rewrites.
- No publishing to PyPI or npm.
- No repo change for local shell certificate warnings. That is a workstation configuration issue.
- No repo change for missing `ast-grep`. Use `rg` unless the project later standardizes ast-grep as a dev dependency.

## System Diagram

```text
Developer release command
  |
  v
kaji/scripts/live-openai-tool-loop.sh
  |
  +-- no OPENAI_API_KEY ---------------------> SKIP, exit 0
  |
  +-- no key + KAJI_REQUIRE_LIVE_KEYS=1 -----> FAIL, exit 2
  |
  +-- key present
        |
        +-- Python live tool loop
        |     AgentBuilder -> OpenAIProvider -> tool call -> ToolRegistry -> final text
        |
        +-- TS live tool loop
              AgentBuilder -> OpenAIProvider -> tool call -> ToolRegistry -> final text
```

### Task 1: Lock The Live Gate Contract

**Files:**
- Create: `kaji/sdk/tests/test_live_gate.py`
- Modify: `kaji/sdk/README.md`
- Modify: `kaji/ts/README.md`
- Modify: `docs/MVP.md`

**Interfaces:**
- Consumes: `kaji/scripts/live-openai-tool-loop.sh`
- Produces: test coverage for no-key skip and require-key failure semantics.

- [ ] **Step 1: Write failing tests for no-key script behavior**

Create `kaji/sdk/tests/test_live_gate.py`:

```python
from __future__ import annotations

import os
import subprocess
from pathlib import Path


SDK_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SDK_ROOT.parents[1]
LIVE_GATE = REPO_ROOT / "kaji" / "scripts" / "live-openai-tool-loop.sh"


def _env_without_openai_key(*, require: bool = False) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    env.pop("KAJI_LIVE_OPENAI_MODEL", None)
    if require:
        env["KAJI_REQUIRE_LIVE_KEYS"] = "1"
    else:
        env.pop("KAJI_REQUIRE_LIVE_KEYS", None)
    return env


def test_live_gate_skips_cleanly_without_openai_key() -> None:
    proc = subprocess.run(
        ["bash", str(LIVE_GATE)],
        cwd=REPO_ROOT,
        env=_env_without_openai_key(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0
    assert "SKIP: OPENAI_API_KEY not set" in proc.stdout
    assert "Running Python OpenAI live tool-loop" not in proc.stdout
    assert "Running TypeScript OpenAI live tool-loop" not in proc.stdout


def test_live_gate_fails_without_key_when_required() -> None:
    proc = subprocess.run(
        ["bash", str(LIVE_GATE)],
        cwd=REPO_ROOT,
        env=_env_without_openai_key(require=True),
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 2
    assert "FAIL: OPENAI_API_KEY required for live readiness" in proc.stderr
    assert "Running Python OpenAI live tool-loop" not in proc.stdout
    assert "Running TypeScript OpenAI live tool-loop" not in proc.stdout
```

- [ ] **Step 2: Run tests and verify they pass**

Run:

```bash
cd kaji/sdk
uv run pytest tests/test_live_gate.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 3: Tighten docs around keyed proof**

In `kaji/sdk/README.md`, `kaji/ts/README.md`, and `docs/MVP.md`, make the release-gate wording explicit:

````markdown
The no-key integration run proves import and skip hygiene only. It is not a
provider-readiness signal. A release cannot be called live-ready until this
command exits with `PASS: OpenAI live tool-loop readiness verified` while
`OPENAI_API_KEY` is set:

```bash
OPENAI_API_KEY=... KAJI_LIVE_OPENAI_MODEL=gpt-5.4-mini bash kaji/scripts/live-openai-tool-loop.sh
```
````

- [ ] **Step 4: Run docs/live-gate tests**

Run:

```bash
cd kaji/sdk
uv run pytest tests/test_live_gate.py tests/test_docs_sync.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Manual keyed release gate**

Run only when a real key is available:

```bash
OPENAI_API_KEY=... KAJI_LIVE_OPENAI_MODEL=gpt-5.4-mini bash kaji/scripts/live-openai-tool-loop.sh
```

Expected:

```text
PASS: OpenAI live tool-loop readiness verified
```

If no key is available, mark release readiness as blocked by missing external credential. Do not weaken the gate.

- [ ] **Step 6: GitButler checkpoint**

Run:

```bash
command -v but
but diff
but commit enkang/sdk-release-gaps-closure -c -m "test(kaji): lock live readiness gate contract" --changes <file-or-hunk-ids-from-but-diff>
```

Expected: GitButler records only Task 1 files. If `but` is unavailable, stop and report the missing CLI.

### Task 2: Remove Python Registry Packaging Warnings

**Files:**
- Create: `kaji/sdk/src/integrations/registry/__init__.py`
- Create: `kaji/sdk/src/integrations/registry/echo/__init__.py`
- Modify: `kaji/sdk/pyproject.toml`
- Modify: `kaji/sdk/scripts/verify_wheel.sh`
- Modify: `kaji/sdk/tests/test_release_smoke.py`

**Interfaces:**
- Consumes: existing `src/` remap and registry data layout.
- Produces: explicit registry namespace package declarations and wheel verification for package markers.

- [ ] **Step 1: Write failing package-declaration test**

Append to `kaji/sdk/tests/test_release_smoke.py`:

```python
import tomllib


def test_registry_namespace_packages_are_declared() -> None:
    pyproject = tomllib.loads((SDK_ROOT / "pyproject.toml").read_text())
    packages = set(pyproject["tool"]["setuptools"]["packages"])
    package_dir = pyproject["tool"]["setuptools"]["package-dir"]

    assert "kaji.integrations.registry" in packages
    assert "kaji.integrations.registry.echo" in packages
    assert package_dir["kaji.integrations.registry"] == "src/integrations/registry"
    assert package_dir["kaji.integrations.registry.echo"] == "src/integrations/registry/echo"
```

Run:

```bash
cd kaji/sdk
uv run pytest tests/test_release_smoke.py::test_registry_namespace_packages_are_declared -q
```

Expected before implementation: failure because registry packages are not declared.

- [ ] **Step 2: Add package marker files**

Create `kaji/sdk/src/integrations/registry/__init__.py`:

```python
"""Bundled Kaji integration registry assets."""
```

Create `kaji/sdk/src/integrations/registry/echo/__init__.py`:

```python
"""Echo integration registry entry."""
```

- [ ] **Step 3: Declare registry packages in `pyproject.toml`**

Modify `[tool.setuptools].packages`:

```toml
    "kaji.integrations.registry",
    "kaji.integrations.registry.echo",
```

Insert those after `"kaji.integrations",`.

Modify `[tool.setuptools.package-dir]`:

```toml
"kaji.integrations.registry" = "src/integrations/registry"
"kaji.integrations.registry.echo" = "src/integrations/registry/echo"
```

Insert those after `"kaji.integrations" = "src/integrations"`.

- [ ] **Step 4: Extend wheel verification for registry package markers**

In `kaji/sdk/scripts/verify_wheel.sh`, inside the Python wheel inspection block after `schema_path`, add:

```python
    package_markers = [
        f"{registry_root}/__init__.py",
        f"{registry_root}/echo/__init__.py",
    ]
```

Then verify them with the existing path loop:

```python
    for path in (index_path, schema_path, *package_markers):
        if path not in names:
            fail(f"{path} missing from wheel")
        print(f"  ok: {path}")
```

- [ ] **Step 5: Run focused packaging tests**

Run:

```bash
cd kaji/sdk
uv run pytest tests/test_release_smoke.py tests/test_echo_registry.py tests/test_package_boundaries.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Run release smoke and confirm warning is gone**

Run:

```bash
cd kaji/sdk
bash scripts/release_smoke.sh
```

Expected:

```text
PASS: wheel contents verified
PASS: release smoke verified
```

Also inspect the build output. It must not contain:

```text
Package 'kaji.integrations.registry' is absent from the `packages` configuration.
Package 'kaji.integrations.registry.echo' is absent from the `packages` configuration.
```

- [ ] **Step 7: GitButler checkpoint**

Run:

```bash
command -v but
but diff
but commit enkang/sdk-release-gaps-closure -m "fix(sdk): declare registry packages for wheel builds" --changes <file-or-hunk-ids-from-but-diff>
```

Expected: GitButler records only Task 2 files.

### Task 3: Remove Private Client Mutation From TS Cancellation Tests

**Files:**
- Modify: `kaji/ts/tests/cancellation.test.ts`
- No production files should change unless the provider hook types fail to export.

**Interfaces:**
- Consumes: `OpenAIProviderTestHooks` and `AnthropicProviderTestHooks`.
- Produces: cancellation tests that use constructor injection instead of `(provider as unknown as { client: unknown }).client`.

- [ ] **Step 1: Write the target helper shape**

Modify imports in `kaji/ts/tests/cancellation.test.ts`:

```ts
import { OpenAIProvider, type OpenAIProviderTestHooks } from "@/providers/openai";
import { AnthropicProvider, type AnthropicProviderTestHooks } from "@/providers/anthropic";
```

Add helpers below the imports:

```ts
function openAIHooks(create: ReturnType<typeof vi.fn>): OpenAIProviderTestHooks {
  return {
    client: {
      chat: { completions: { create } },
    } as unknown as NonNullable<OpenAIProviderTestHooks["client"]>,
  };
}

function anthropicHooks(create: ReturnType<typeof vi.fn>): AnthropicProviderTestHooks {
  return {
    client: {
      messages: { create },
    } as unknown as NonNullable<AnthropicProviderTestHooks["client"]>,
  };
}
```

- [ ] **Step 2: Replace OpenAI generate test setup**

Change:

```ts
const provider = new OpenAIProvider({ apiKey: "test-key" });
...
(provider as unknown as { client: unknown }).client = {
  chat: { completions: { create } },
};
```

to:

```ts
const create = vi.fn().mockResolvedValue({
  choices: [{ message: { content: "ok", tool_calls: null } }],
});
const provider = new OpenAIProvider({ apiKey: "test-key" }, openAIHooks(create));
```

- [ ] **Step 3: Replace OpenAI stream test setup**

Change:

```ts
const provider = new OpenAIProvider({ apiKey: "test-key" });
...
(provider as unknown as { client: unknown }).client = {
  chat: { completions: { create } },
};
```

to:

```ts
const create = vi.fn().mockResolvedValue(empty());
const provider = new OpenAIProvider({ apiKey: "test-key" }, openAIHooks(create));
```

- [ ] **Step 4: Replace Anthropic generate test setup**

Change:

```ts
const provider = new AnthropicProvider({ apiKey: "test-key" });
...
(provider as unknown as { client: unknown }).client = {
  messages: { create },
};
```

to:

```ts
const create = vi.fn().mockResolvedValue({ content: [{ type: "text", text: "ok" }] });
const provider = new AnthropicProvider({ apiKey: "test-key" }, anthropicHooks(create));
```

- [ ] **Step 5: Run focused TS tests**

Run:

```bash
cd kaji/ts
bun run test tests/cancellation.test.ts tests/openai-provider.test.ts tests/anthropic-provider.test.ts
node_modules/.bin/tsc --noEmit
```

Expected: all selected tests pass and `tsc` exits 0.

- [ ] **Step 6: Verify no private client mutation remains**

Run:

```bash
rg -n "\\(provider as unknown as \\{ client: unknown \\}\\)\\.client|as unknown as \\{ client" kaji/ts/tests kaji/ts/src
```

Expected: no output.

- [ ] **Step 7: GitButler checkpoint**

Run:

```bash
command -v but
but diff
but commit enkang/sdk-release-gaps-closure -m "test(ts-sdk): use provider hooks in cancellation tests" --changes <file-or-hunk-ids-from-but-diff>
```

Expected: GitButler records only Task 3 files.

### Task 4: Add A Formal Cross-SDK Release Matrix

**Files:**
- Create: `kaji/RELEASE_MATRIX.md`
- Modify: `kaji/sdk/README.md`
- Modify: `kaji/ts/README.md`
- Modify: `docs/MVP.md`
- Modify: `kaji/sdk/tests/test_stability_contract.py`
- Create: `kaji/ts/tests/docs-contract.test.ts`

**Interfaces:**
- Consumes: existing stability tier text in both READMEs.
- Produces: one release matrix that makes stable, experimental, not ported, and release-gated surfaces explicit.

- [ ] **Step 1: Create `kaji/RELEASE_MATRIX.md`**

Create:

```markdown
# Kaji SDK Release Matrix

## Release Promise

Kaji pre-beta readiness means the stable core agent loop works in both Python
and TypeScript with one real OpenAI model and one real model-requested tool call.
It does not mean every Python-only modality or infrastructure adapter is beta-ready.

## Stable Core

| Surface | Python | TypeScript | Release gate |
| --- | --- | --- | --- |
| AgentBuilder | Stable core | Stable core | unit tests |
| AgentRuntime turn loop | Stable core | Stable core | unit tests + live OpenAI tool loop |
| ToolRegistry and ToolPlanner | Stable core | Stable core | unit tests + echo integration |
| Session replay | Stable core | Stable core | replay tests |
| OpenAI provider | Stable core | Stable core | unit tests + live OpenAI tool loop |
| Anthropic provider | Stable core | Stable core | unit tests + live smoke when keyed |
| In-memory event bus/store | Stable core | Stable core | bus/store tests |

## Experimental Python-Only

| Surface | Status | Why |
| --- | --- | --- |
| Redis realtime/history | Experimental Python-only | present, but not a beta release gate |
| voice/TTS | Experimental Python-only | provider adapters exist, placeholder TTS remains valid for unconfigured use |
| DocumentRAG | Experimental Python-only | useful primitives, not cross-SDK parity |
| native Gemini/Kimi | Experimental Python-only | not part of first live readiness gate |
| tool retrieval | Experimental Python-only | not part of first live readiness gate |

## TypeScript Not Ported

| Surface | TS status |
| --- | --- |
| Redis realtime/history | Not ported |
| voice/TTS | Not ported |
| RAG | Not ported |
| native Gemini/Kimi | Not ported; Gemini/Kimi are OpenAI-compatible factories |

## Release Gates

| Gate | Command | Required for beta |
| --- | --- | --- |
| Python unit/static | `cd kaji/sdk && uv run pytest -m "not integration" && uv run python scripts/typecheck_ty.py --output-format concise && uv run ruff check src tests` | Yes |
| Python wheel smoke | `cd kaji/sdk && bash scripts/release_smoke.sh` | Yes |
| TS unit/static/build | `cd kaji/ts && bun run test && node_modules/.bin/tsc --noEmit && bun run build` | Yes |
| TS package smoke | `cd kaji/ts && bun run scripts/smoke.mts` | Yes |
| No-key integration hygiene | `bash kaji/scripts/live-openai-tool-loop.sh` | Yes, proves skip hygiene only |
| Keyed OpenAI live proof | `OPENAI_API_KEY=... KAJI_LIVE_OPENAI_MODEL=gpt-5.4-mini bash kaji/scripts/live-openai-tool-loop.sh` | Yes, proves live readiness |
```

- [ ] **Step 2: Link the matrix from docs**

In both READMEs and `docs/MVP.md`, add:

```markdown
See [`kaji/RELEASE_MATRIX.md`](../RELEASE_MATRIX.md) for the cross-SDK release
matrix and the exact distinction between stable core, experimental Python-only
surfaces, and TypeScript surfaces that are not ported.
```

Use the correct relative link per file:

- From `kaji/sdk/README.md`: `../RELEASE_MATRIX.md`
- From `kaji/ts/README.md`: `../RELEASE_MATRIX.md`
- From `docs/MVP.md`: `../kaji/RELEASE_MATRIX.md`

- [ ] **Step 3: Extend Python stability contract tests**

In `kaji/sdk/tests/test_stability_contract.py`, add a test that reads all four docs:

```python
def test_release_matrix_preserves_cross_sdk_contract() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    combined = "\n".join(
        [
            (repo_root / "kaji" / "RELEASE_MATRIX.md").read_text(),
            (repo_root / "kaji" / "sdk" / "README.md").read_text(),
            (repo_root / "kaji" / "ts" / "README.md").read_text(),
            (repo_root / "docs" / "MVP.md").read_text(),
        ]
    )

    for phrase in [
        "Stable core",
        "Experimental Python-only",
        "TypeScript Not Ported",
        "OpenAI-compatible factories",
        "Redis realtime/history",
        "voice/TTS",
        "DocumentRAG",
        "Keyed OpenAI live proof",
        "gpt-5.4-mini",
    ]:
        assert phrase in combined
```

If `Path` is not already imported, add:

```python
from pathlib import Path
```

- [ ] **Step 4: Add TS docs contract test**

Create `kaji/ts/tests/docs-contract.test.ts`:

```ts
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const repoRoot = resolve(__dirname, "../../..");

function read(path: string): string {
  return readFileSync(resolve(repoRoot, path), "utf8");
}

describe("cross-SDK release matrix docs", () => {
  it("keeps stable core, experimental, and not-ported surfaces explicit", () => {
    const combined = [
      read("kaji/RELEASE_MATRIX.md"),
      read("kaji/sdk/README.md"),
      read("kaji/ts/README.md"),
      read("docs/MVP.md"),
    ].join("\n");

    for (const phrase of [
      "Stable core",
      "Experimental Python-only",
      "TypeScript Not Ported",
      "OpenAI-compatible factories",
      "Redis realtime/history",
      "voice/TTS",
      "DocumentRAG",
      "Keyed OpenAI live proof",
      "gpt-5.4-mini",
    ]) {
      expect(combined).toContain(phrase);
    }
  });
});
```

- [ ] **Step 5: Run docs contract tests**

Run:

```bash
cd kaji/sdk
uv run pytest tests/test_stability_contract.py tests/test_docs_sync.py -q

cd ../ts
bun run test tests/docs-contract.test.ts
node_modules/.bin/tsc --noEmit
```

Expected: all selected checks pass.

- [ ] **Step 6: GitButler checkpoint**

Run:

```bash
command -v but
but diff
but commit enkang/sdk-release-gaps-closure -m "docs(kaji): add cross-sdk release matrix" --changes <file-or-hunk-ids-from-but-diff>
```

Expected: GitButler records only Task 4 files.

### Task 5: Final Verification And Release Decision

**Files:**
- No source edits expected.
- Commands operate across `kaji/sdk`, `kaji/ts`, and `kaji/scripts`.

**Interfaces:**
- Consumes: all prior task outputs.
- Produces: final release-readiness verdict.

- [ ] **Step 1: Run TS verification**

Run:

```bash
cd kaji/ts
bun run test
node_modules/.bin/tsc --noEmit
bun run build
bun run validate:registry
bun run scripts/smoke.mts
bun run test:integration
```

Expected:

- Unit tests pass.
- `tsc` exits 0.
- Build exits 0.
- Registry validation passes.
- Smoke install passes.
- Integration suite skips cleanly without keys.

- [ ] **Step 2: Run Python verification**

Run:

```bash
cd kaji/sdk
uv run pytest -m "not integration"
uv run python scripts/typecheck_ty.py --output-format concise
uv run ruff check src tests
bash scripts/release_smoke.sh
uv run pytest -m integration
```

Expected:

- Non-integration tests pass.
- `ty` passes.
- `ruff` passes.
- Release smoke passes with no setuptools registry warnings.
- Integration suite skips cleanly without keys.

- [ ] **Step 3: Run root live gate no-key modes**

Run:

```bash
bash kaji/scripts/live-openai-tool-loop.sh
KAJI_REQUIRE_LIVE_KEYS=1 bash kaji/scripts/live-openai-tool-loop.sh
```

Expected:

- First command exits 0 with `SKIP: OPENAI_API_KEY not set`.
- Second command exits 2 with `FAIL: OPENAI_API_KEY required for live readiness`.

- [ ] **Step 4: Run keyed live proof**

Run only with a real key:

```bash
OPENAI_API_KEY=... KAJI_LIVE_OPENAI_MODEL=gpt-5.4-mini bash kaji/scripts/live-openai-tool-loop.sh
```

Expected:

```text
PASS: OpenAI live tool-loop readiness verified
```

If this cannot run, final status is `DONE_WITH_CONCERNS`: code checks can be green, but release readiness remains blocked by missing keyed proof.

- [ ] **Step 5: Confirm generated debris is gone**

Run:

```bash
find kaji/sdk/src kaji/sdk/tests -type d -name __pycache__
```

Expected: no output.

- [ ] **Step 6: Final GitButler checkpoint**

Run:

```bash
command -v but
but diff
but commit enkang/sdk-release-gaps-closure -m "chore(kaji): close sdk release trust gaps" --changes <file-or-hunk-ids-from-but-diff>
```

Expected: GitButler records only remaining coherent files from this plan. If prior task commits already captured all changes, this step can be skipped after `but diff` confirms no remaining plan changes.

## Failure Modes Registry

| Codepath | Failure mode | Mitigation | Test/check |
| --- | --- | --- | --- |
| Live readiness gate | No key creates false confidence | No-key exits 0 with explicit skip; require-key exits 2 | `test_live_gate.py` |
| Live readiness gate | Model never actually tested | Keyed command remains required release gate | manual keyed run |
| Python wheel build | setuptools registry warning hides package drift | Declare registry packages and package dirs | `release_smoke.sh` output |
| Python wheel contents | Registry files missing after package config change | Verify index, schema, manifests, files, and package markers | `verify_wheel.sh` |
| TS cancellation tests | Tests mutate private provider fields | Use constructor hooks only | `rg` no private mutation |
| Public docs | Beta promise drifts into experimental surfaces | Formal release matrix and docs contract tests | Python + TS docs tests |
| Worktree process | Changes pass locally but are not checkpointed | GitButler checkpoint after each task | `but diff`, `but commit` |

## Test Coverage Diagram

```text
CODE PATHS                                           COVERAGE TARGET
kaji/scripts/live-openai-tool-loop.sh
  +-- no key, require off -------------------------- pytest subprocess
  +-- no key, require on --------------------------- pytest subprocess
  +-- key present, Python + TS live ---------------- manual keyed release gate

kaji/sdk packaging
  +-- pyproject package list ----------------------- pytest static contract
  +-- wheel registry files ------------------------- verify_wheel.sh
  +-- clean install smoke -------------------------- release_smoke.sh

kaji/ts cancellation tests
  +-- OpenAI generate signal ----------------------- vitest
  +-- OpenAI stream signal ------------------------- vitest
  +-- Anthropic generate signal -------------------- vitest
  +-- no private client mutation ------------------- rg check

docs contract
  +-- stable core wording -------------------------- pytest + vitest
  +-- experimental Python-only wording ------------- pytest + vitest
  +-- TS not ported wording ------------------------ pytest + vitest
```

## Parallelization Strategy

Sequential implementation is safest for docs because Tasks 1 and 4 both touch READMEs and `docs/MVP.md`.

After Task 1 lands, Task 2 and Task 3 can run in parallel:

| Step | Modules touched | Depends on |
| --- | --- | --- |
| Task 1 live gate contract | `kaji/scripts`, `kaji/sdk/tests`, docs | none |
| Task 2 packaging warnings | `kaji/sdk` packaging and registry | none |
| Task 3 TS test seam | `kaji/ts/tests` | none |
| Task 4 release matrix | docs and docs tests | Task 1 wording |
| Task 5 final verification | all | Tasks 1-4 |

Lanes:

- Lane A: Task 1 -> Task 4 -> Task 5.
- Lane B: Task 2 after Task 1 starts, independent except final verification.
- Lane C: Task 3 after Task 1 starts, independent except final verification.

Conflict flags:

- Task 1 and Task 4 both touch README/MVP docs. Keep them sequential.
- Task 2 and Task 3 touch different SDKs and can run in parallel worktrees.

## Review Fold-In

### Plan-Tune Review

- User preference is complete edge coverage with low question overhead.
- The plan defaults to the complete release closure path and avoids asking for scope choices that have an obvious answer.
- The only unresolved external decision is availability of `OPENAI_API_KEY`; the plan treats missing keys as a release blocker, not a prompt for weaker proof.

### CEO Review

- Hold scope. The product move is trust, not broader SDK parity.
- Do not expand into Redis, voice, RAG, Gemini/Kimi, or publishing pipelines.
- The release story should be simple: green local checks, clean wheel/package smoke, no-key skip hygiene, and one keyed OpenAI tool loop.

### Engineering Review

- The plan uses existing hooks, scripts, and tests instead of introducing new architecture.
- Packaging warning cleanup is explicit and testable.
- TS cancellation cleanup removes private field mutation without weakening production encapsulation.
- Docs get executable contract tests so the stability promise does not drift.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
| --- | --- | --- | --- | --- | --- |
| Plan Tune | `/plan-tune` | Question sensitivity and scope posture | 1 | CLEAR | Complete edge coverage, low question overhead |
| CEO Review | `/plan-ceo-review` | Scope and product trust | 1 | CLEAR | Hold scope; trust closure beats new features |
| Eng Review | `/plan-eng-review` | Architecture and tests | 1 | CLEAR | Use existing scripts/hooks; add exact tests and release matrix |

- **VERDICT:** PLAN READY - implement Tasks 1-5 sequentially, with Task 2 and Task 3 parallelizable after Task 1 starts.

NO UNRESOLVED DECISIONS
