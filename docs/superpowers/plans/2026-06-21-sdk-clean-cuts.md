# SDK Clean Cuts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove vertical / dead / opinionated modules from both kaji SDKs so the core ships only primitives. Specifically: drop `payment` (vertical -- agentpay), `system_tools` (legacy voice), `manifest.py` and `runner.py` (dead shims), and flip the Python default LLM provider from `kimi` to `mock` so the SDK does not silently route requests to OpenRouter.

**Architecture:** Pure deletion + small consequential edits. No new code lands. Each cut is one file plus the lazy-map / surface-pin / smoke-test references that pointed at it. Tasks are sequenced so each leaves the test suites green; nothing runs in parallel because they all touch overlapping registries (`__init__.py`, `test_public_surface.py`, `smoke_install.py`).

**Tech Stack:** Python 3.11+ (poetry, pytest, ruff, pyrefly), TypeScript 6 (bun, tsup, vitest, tsc).

## Global Constraints

- **Branch:** all work on a new branch `chore/sdk-clean-cuts`, never on `main` or `feat/sdk-dx-and-docs`.
- **No new heavy dependencies** in either SDK.
- **No em-dashes** in source, docs, or commit messages. Use `--`, `-`, or a comma.
- **Bun** for TS package ops. **Poetry** for Python.
- **TS sources / tests:** `kaji/ts/src/**`, `kaji/ts/tests/**`.
- **Python SDK sources / tests:** `kaji/sdk/kaji/**`, `kaji/sdk/tests/**`.
- **Public-surface contract:** after this plan, `dir(kaji)` is 25 names (drops `RequestPaymentTool`). The TS `index.ts` drops the `requestPayment` + `RequestPaymentOptions` + `RequestPaymentTool` exports.
- **Tests required:** each task ends with the relevant suite green. Final task re-runs everything.
- **Scope: NOT TOUCHED** by this plan -- `modalities/voice/`, `knowledge/`, `infra/observability/`, `cli/`, `idempotency.py`, `function_calls.py`. They are kept on purpose; the user explicitly excluded them.

---

## File Structure

### Python SDK -- files DELETED

- `kaji/sdk/kaji/runtime/tools/payment.py`
- `kaji/sdk/kaji/runtime/tools/system_tools.py`
- `kaji/sdk/kaji/runtime/tools/manifest.py`
- `kaji/sdk/kaji/runtime/tools/runner.py`
- `kaji/sdk/tests/test_tools_payment.py`

### Python SDK -- files MODIFIED

- `kaji/sdk/kaji/__init__.py` -- drop the `RequestPaymentTool` entry from `_LAZY`.
- `kaji/sdk/kaji/runtime/tools/__init__.py` -- drop the `RequestPaymentTool` re-export.
- `kaji/sdk/kaji/core/config.py:53` -- change `KAJI_MODEL_PROVIDER: str = "kimi"` to `KAJI_MODEL_PROVIDER: str = "mock"`.
- `kaji/sdk/tests/test_public_surface.py` -- drop `"RequestPaymentTool"` from `EXPECTED_PUBLIC`.
- `kaji/sdk/tests/test_package_boundaries.py:120-135` -- drop the `system_tools.py` exception block.
- `kaji/sdk/scripts/smoke_install.py` -- drop `"RequestPaymentTool"` from `required_names`.

### TS SDK -- files DELETED

- `kaji/ts/src/tools/payment.ts`
- `kaji/ts/tests/tools/payment.test.ts`

### TS SDK -- files MODIFIED

- `kaji/ts/src/index.ts` -- drop the two `payment` export lines.

### Docs -- files MODIFIED

- `apps/docs/content/index.mdx` -- add a one-paragraph composition note.

---

### Task 1: Branch + baseline

**Files:** none modified.

**Interfaces:**
- Consumes: nothing.
- Produces: branch `chore/sdk-clean-cuts` checked out from `origin/main`. A recorded `BASE_SHA` for downstream review-package generation.

- [ ] **Step 1: Sync main, branch off, push**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy
git checkout main
git pull --ff-only origin main
git checkout -b chore/sdk-clean-cuts
git push -u origin chore/sdk-clean-cuts
```

- [ ] **Step 2: Confirm baseline is green**

```bash
bun --filter @kaji/sdk test 2>&1 | tail -3
cd kaji/sdk && poetry run pytest -q --ignore=tests/integration 2>&1 | tail -3
```

Expected: both green. The Python suite should report 298 passed (matches the count at the tip of `feat/sdk-dx-and-docs` which has already merged or is in flight). If lower, you may be branching off a stale `main` -- re-run Step 1.

Do not commit anything in this task.

---

### Task 2: Delete TS `payment.ts` + test + exports

**Files:**
- Delete: `kaji/ts/src/tools/payment.ts`
- Delete: `kaji/ts/tests/tools/payment.test.ts`
- Modify: `kaji/ts/src/index.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `@kaji/sdk` no longer exports `requestPayment`, `RequestPaymentOptions`, or `RequestPaymentTool`. The test suite drops 4 tests (was 147 passing, becomes 143 + 4 = same 143 as pre-T5 of the previous plan).

- [ ] **Step 1: Delete the source file**

```bash
git rm kaji/ts/src/tools/payment.ts
```

- [ ] **Step 2: Delete the test file**

```bash
git rm kaji/ts/tests/tools/payment.test.ts
```

- [ ] **Step 3: Remove the exports from `index.ts`**

In `kaji/ts/src/index.ts`, find the block:

```ts
export { requestPayment } from "./tools/payment";
export type { RequestPaymentOptions, RequestPaymentTool } from "./tools/payment";
```

Delete both lines. Leave the rest of the file untouched.

- [ ] **Step 4: Typecheck + tests**

```bash
cd kaji/ts && bun run typecheck && cd ../..
bun --filter @kaji/sdk test 2>&1 | tail -3
```

Expected: typecheck exits 0 (no unresolved imports anywhere), tests show 143 pass / 6 skipped. If any test imports `requestPayment`, you missed something -- grep the tree:

```bash
grep -rn "requestPayment\|RequestPayment" kaji/ts/ --include="*.ts"
```

Expected: zero matches.

- [ ] **Step 5: Commit**

```bash
git commit -m "refactor(ts-sdk): drop requestPayment -- vertical does not belong in core"
```

---

### Task 3: Delete Python `payment.py` + test + lazy map entry

**Files:**
- Delete: `kaji/sdk/kaji/runtime/tools/payment.py`
- Delete: `kaji/sdk/tests/test_tools_payment.py`
- Modify: `kaji/sdk/kaji/runtime/tools/__init__.py`
- Modify: `kaji/sdk/kaji/__init__.py`
- Modify: `kaji/sdk/tests/test_public_surface.py`
- Modify: `kaji/sdk/scripts/smoke_install.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `dir(kaji)` no longer includes `RequestPaymentTool`. `EXPECTED_PUBLIC` set shrinks from 26 to 25 names. The install-smoke script no longer requires `RequestPaymentTool`.

- [ ] **Step 1: Delete the source file**

```bash
git rm kaji/sdk/kaji/runtime/tools/payment.py
```

- [ ] **Step 2: Delete the test file**

```bash
git rm kaji/sdk/tests/test_tools_payment.py
```

- [ ] **Step 3: Strip the re-export from `runtime/tools/__init__.py`**

In `kaji/sdk/kaji/runtime/tools/__init__.py`, find the single line:

```python
from kaji.runtime.tools.payment import RequestPaymentTool  # noqa: F401
```

Delete the entire line. If the file becomes empty, replace its body with a one-line docstring:

```python
"""kaji runtime tools subpackage."""
```

If there is an `__all__` list that contained `"RequestPaymentTool"`, remove that entry too.

- [ ] **Step 4: Strip the entry from the lazy map**

In `kaji/sdk/kaji/__init__.py`, find the line:

```python
    "RequestPaymentTool": "kaji.runtime.tools.payment",
```

Delete it. Leave alphabetical ordering of the surrounding entries intact (the entries before and after are `ReplaySession` and `SessionManager`).

- [ ] **Step 5: Update the surface-pinning test**

In `kaji/sdk/tests/test_public_surface.py`, find `"RequestPaymentTool",` inside the `EXPECTED_PUBLIC = {...}` set literal and delete that line.

- [ ] **Step 6: Update the smoke-install script**

In `kaji/sdk/scripts/smoke_install.py`, find `"RequestPaymentTool",` inside the `required_names = [...]` list and delete that line.

- [ ] **Step 7: Run the focused tests**

```bash
cd kaji/sdk && poetry run pytest tests/test_public_surface.py -v 2>&1 | tail -5
```

Expected: 3 tests passing. The `test_public_surface_is_pinned` set equality now holds with 25 names; `test_each_public_name_resolves` no longer attempts to import the deleted module; `test_internal_names_still_importable_from_subpackages` is untouched and still passes.

- [ ] **Step 8: Run the smoke-install script**

```bash
cd kaji/sdk && poetry run python scripts/smoke_install.py 2>&1 | tail -15
```

Expected: "Smoke install: PASSED".

- [ ] **Step 9: Run the whole Python suite**

```bash
cd kaji/sdk && poetry run pytest -q --ignore=tests/integration 2>&1 | tail -3
```

Expected: 294 passed (298 baseline minus the 4 payment tests). If you see import errors anywhere mentioning `payment`, run:

```bash
grep -rn "payment" kaji/sdk/kaji/ tests/ --include="*.py" 2>&1 | grep -vE "__pycache__|payment_intent\.|\.py\.typed" | head
```

Expected: only documentation strings (e.g., a docstring mentioning "no payment example here") or unrelated agentpay-string mentions. Anything that looks like a live import is a leak; remove it.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "refactor(py-sdk): drop request_payment -- vertical does not belong in core"
```

---

### Task 4: Delete Python `system_tools.py` + boundary-test exception

**Files:**
- Delete: `kaji/sdk/kaji/runtime/tools/system_tools.py`
- Modify: `kaji/sdk/tests/test_package_boundaries.py:120-135`

**Interfaces:**
- Consumes: nothing.
- Produces: the boundary test no longer carries a deliberate exception for legacy voice tools. If a hidden importer points at `runtime/tools/system_tools`, the next test run will surface it.

The module's own docstring marks it deprecated and points at `modalities/voice/legacy/system_tools` as the canonical home. We verified zero imports across the codebase before planning (only test_package_boundaries.py mentions it by path).

- [ ] **Step 1: Grep one more time to be sure**

```bash
grep -rn "kaji.runtime.tools.system_tools\|runtime\.tools\.system_tools" \
    /Users/Enkang.Yuan1/Desktop/Projects/alloy/kaji/sdk --include="*.py" 2>&1 | \
    grep -v __pycache__ | grep -v "system_tools.py:" | grep -v test_package_boundaries
```

Expected: zero results. If any module imports `system_tools`, STOP -- escalate. The plan assumed no live consumers and that assumption is now wrong.

- [ ] **Step 2: Delete the source file**

```bash
git rm kaji/sdk/kaji/runtime/tools/system_tools.py
```

- [ ] **Step 3: Strip the exception from the boundary test**

Open `kaji/sdk/tests/test_package_boundaries.py`. Find the block that looks like:

```python
    The legacy ToolDefinition ABC lives in kaji/types/tool.py. The current
    runtime tool model uses kaji.runtime.tools.registry.ToolSpec. The one
    deliberate exception is system_tools.py, which is itself the legacy shim and
    is documented as deprecated.
    """
    runtime_tools_dir = PACKAGE_ROOT / "runtime" / "tools"
    allowed_exception = Path("kaji/runtime/tools/system_tools.py")
    violations: list[str] = []

    for path in _python_files(runtime_tools_dir):
        rel = path.relative_to(SDK_ROOT)
        if rel == allowed_exception:
            continue
        if any(_matches(imp, "kaji.types.tool") for imp in _imports(path)):
            violations.append(str(rel))
```

Replace the docstring tail (from "The one deliberate exception..." through "documented as deprecated.") so it reads:

```python
    The legacy ToolDefinition ABC lives in kaji/types/tool.py. The current
    runtime tool model uses kaji.runtime.tools.registry.ToolSpec. No file
    under runtime/tools/ may still import the legacy ABC.
    """
```

Then remove these two lines from the body:

```python
    allowed_exception = Path("kaji/runtime/tools/system_tools.py")
```

and:

```python
        if rel == allowed_exception:
            continue
```

The resulting loop is:

```python
    for path in _python_files(runtime_tools_dir):
        rel = path.relative_to(SDK_ROOT)
        if any(_matches(imp, "kaji.types.tool") for imp in _imports(path)):
            violations.append(str(rel))
```

- [ ] **Step 4: Run the boundary test**

```bash
cd kaji/sdk && poetry run pytest tests/test_package_boundaries.py -v 2>&1 | tail -10
```

Expected: all tests pass, including the now-stricter `test_runtime_tools_do_not_use_legacy_tool_abc` (the function name may differ slightly -- adapt to whatever the actual test is called). If a violation is reported, an undiscovered importer of `kaji.types.tool` is hiding under `runtime/tools/` -- escalate.

- [ ] **Step 5: Run the whole Python suite**

```bash
cd kaji/sdk && poetry run pytest -q --ignore=tests/integration 2>&1 | tail -3
```

Expected: 294 passed (carried over from Task 3; system_tools wasn't imported by anything so the count holds).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(py-sdk): drop legacy system_tools.py shim from runtime/tools"
```

---

### Task 5: Delete Python `manifest.py` and `runner.py` (dead shims)

**Files:**
- Delete: `kaji/sdk/kaji/runtime/tools/manifest.py`
- Delete: `kaji/sdk/kaji/runtime/tools/runner.py`

**Interfaces:**
- Consumes: nothing.
- Produces: smaller `runtime/tools/` package. Both files only re-exported names from `runtime.tools.registry`; callers should already be using the registry directly.

Both files were verified to have zero external consumers in the planning phase.

- [ ] **Step 1: Grep one more time**

```bash
grep -rn "kaji.runtime.tools.manifest\|kaji.runtime.tools.runner" \
    /Users/Enkang.Yuan1/Desktop/Projects/alloy --include="*.py" 2>&1 | \
    grep -v __pycache__ | grep -v "manifest.py:" | grep -v "runner.py:" | head
```

Expected: zero results. If any consumer turns up, the right fix is to point it at `kaji.runtime.tools.registry` (which exposes the same names) before the delete; STOP and report it as a finding.

- [ ] **Step 2: Delete both files**

```bash
git rm kaji/sdk/kaji/runtime/tools/manifest.py
git rm kaji/sdk/kaji/runtime/tools/runner.py
```

- [ ] **Step 3: Run the Python suite**

```bash
cd kaji/sdk && poetry run pytest -q --ignore=tests/integration 2>&1 | tail -3
```

Expected: still 294 passed.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(py-sdk): drop dead manifest.py and runner.py shims"
```

---

### Task 6: Flip Python default provider from `kimi` to `mock`

**Files:**
- Modify: `kaji/sdk/kaji/core/config.py:53`

**Interfaces:**
- Consumes: nothing.
- Produces: a fresh `import kaji; kaji.GetProvider("openai")` call still works the same. Out of the box, with no `KAJI_MODEL_PROVIDER` env var set, the SDK now returns the in-memory `MockProvider` instead of routing to OpenRouter's `kimi`.

Why this matters: a user who pip-installs `kaji[openai]`, sets `OPENAI_API_KEY`, and writes `runtime = AgentBuilder().provider(GetProvider("openai")).build()` is fine either way -- they explicitly named openai. But a user who writes `GetProvider()` with no name silently hits the default. Today that default sends their tokens to `https://openrouter.ai/api/v1`. That is a vendor opinion baked into the SDK. After this change, the default goes to a mock that never makes a network call, which is the safe + neutral choice. Users can opt back into `kimi` with one env var.

- [ ] **Step 1: Inspect the existing line**

Open `kaji/sdk/kaji/core/config.py` and find:

```python
    KAJI_MODEL_PROVIDER: str = "kimi"
```

at approximately line 53.

- [ ] **Step 2: Change the default**

Edit the line to read:

```python
    KAJI_MODEL_PROVIDER: str = "mock"
```

Do not touch the `KIMI_API_KEY`, `KIMI_MODEL`, or `CLOUDFLARE_KIMI_MODEL` lines -- they remain so users who set `KAJI_MODEL_PROVIDER=kimi` still work.

- [ ] **Step 3: Add a regression test pinning the default**

Create `kaji/sdk/tests/test_default_provider.py`:

```python
"""Pin the SDK's out-of-the-box default LLM provider."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest


def test_default_provider_is_mock() -> None:
    """A fresh import with no env var must default to the in-memory mock.

    Routing to a real vendor (kimi/openrouter, openai, anthropic) by default
    would silently send the user's tokens to a third party they did not pick.
    """
    # Strip any KAJI_* env vars that pydantic-settings would read.
    fake_env = {k: v for k, v in os.environ.items() if not k.startswith("KAJI_")}
    with patch.dict(os.environ, fake_env, clear=True):
        # Re-import settings to pick up the cleaned env.
        from kaji.core.config import Settings

        settings = Settings()
        assert settings.KAJI_MODEL_PROVIDER == "mock"


def test_explicit_provider_env_still_wins() -> None:
    """Setting KAJI_MODEL_PROVIDER=kimi must still route to kimi."""
    with patch.dict(os.environ, {"KAJI_MODEL_PROVIDER": "kimi"}):
        from kaji.core.config import Settings

        settings = Settings()
        assert settings.KAJI_MODEL_PROVIDER == "kimi"
```

- [ ] **Step 4: Run the test**

```bash
cd kaji/sdk && poetry run pytest tests/test_default_provider.py -v 2>&1 | tail -10
```

Expected: 2/2 pass. If the first test fails because `Settings()` is cached as a singleton or the env-var patch is not respected, you may need `Settings.model_config.env_file = None` overrides or to reload the module. Inspect `kaji/core/config.py` for caching before assuming the change is broken.

- [ ] **Step 5: Run the whole Python suite to catch any test that depended on `kimi` being default**

```bash
cd kaji/sdk && poetry run pytest -q --ignore=tests/integration 2>&1 | tail -5
```

Expected: 296 passed (294 + 2 new). If any test fails because it expected `kimi` to be the default, that test had a hidden assumption -- update it to either pin the new mock default or set `KAJI_MODEL_PROVIDER=kimi` explicitly in its env. Note the change in the commit.

- [ ] **Step 6: Commit**

```bash
git add kaji/sdk/kaji/core/config.py kaji/sdk/tests/test_default_provider.py
git commit -m "$(cat <<'EOF'
chore(py-sdk): default KAJI_MODEL_PROVIDER to mock, not kimi

The SDK's out-of-the-box behavior should not silently route a user's
tokens to OpenRouter (the kimi backend). Switch the default to the
infra-free mock provider. Users who want kimi explicitly opt in via
KAJI_MODEL_PROVIDER=kimi.
EOF
)"
```

---

### Task 7: Docs composition note

**Files:**
- Modify: `apps/docs/content/index.mdx`

**Interfaces:** none.

The user's stated goal is "keep the SDK clean and let the user decide what they want to build." This PR removes the easy violations; the harder ones (CLI bundling, voice in core, knowledge / observability in core) remain on purpose for v0.1.0. A short paragraph on the index page makes that policy visible to readers so they don't trip on it later.

- [ ] **Step 1: Read the current index**

Read `apps/docs/content/index.mdx`. It currently ends with a `## Next` section listing other pages.

- [ ] **Step 2: Insert a composition section before `## Next`**

Find the `## Next` heading and insert this block immediately before it:

```mdx
## Composition

kaji's core is a set of primitives -- events, sessions, tools,
providers, runtime. By design the core does not ship verticals (no
built-in payment, calendar, or email tools), and it does not pick a
vendor for you -- `GetProvider()` with no name returns an in-memory mock,
not a third-party service.

For v0.1.0 the Python SDK still bundles a few opinionated modules at the
top level for convenience: `kaji.cli` (project scaffolding),
`kaji.knowledge` (RAG building blocks), `kaji.modalities.voice`
(STT / TTS edges), and `kaji.infra.observability` (metrics, tracing).
These are slated to split into their own packages (`@kaji/cli`,
`@kaji/knowledge`, etc.) in a future release. Treat them as optional
add-ons today and avoid relying on their top-level imports if you want a
smaller v1.0 upgrade path.

The TypeScript SDK ships only the core primitives.
```

- [ ] **Step 3: Em-dash sweep**

```bash
grep -n '—' apps/docs/content/index.mdx
```

Expected: zero matches.

- [ ] **Step 4: Build the docs**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && bun --filter @kaji/docs build 2>&1 | tail -5
```

Expected: exit code 0.

- [ ] **Step 5: Commit**

```bash
git add apps/docs/content/index.mdx
git commit -m "docs: note core-vs-add-on composition policy on index page"
```

---

### Task 8: Final sweep, push, PR

**Files:** none modified.

**Interfaces:** none.

- [ ] **Step 1: Em-dash sweep across all touched files**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy
grep -rn '—' apps/docs/content/index.mdx kaji/sdk/kaji/ kaji/sdk/tests/ kaji/sdk/scripts/ kaji/ts/src/ kaji/ts/tests/ 2>&1 | head
```

Expected: zero matches in any file the plan modified. If you find matches in files this plan touched, replace `—` with `--` or a comma; commit the cleanup.

- [ ] **Step 2: Final test sweep**

```bash
bun --filter @kaji/sdk test 2>&1 | tail -3
cd kaji/sdk && poetry run pytest -q --ignore=tests/integration 2>&1 | tail -3 && cd ../..
cd kaji/sdk && poetry run pyrefly check 2>&1 | tail -3 && cd ../..
cd kaji/sdk && poetry run ruff check . 2>&1 | tail -3 && cd ../..
cd kaji/sdk && poetry run ruff format --check . 2>&1 | tail -3 && cd ../..
bun --filter @kaji/docs build 2>&1 | tail -5
```

Expected: every line green. Counts:

- TS SDK: 143 pass / 6 skipped (was 147 -- minus the 4 payment tests).
- Python SDK: 296 pass (was 298 -- minus 4 payment tests + 2 new default-provider tests = net 296).
- pyrefly: 0 errors.
- ruff check: All checks passed.
- ruff format: every file already formatted.
- docs build: exit 0.

- [ ] **Step 3: Confirm history**

```bash
git log --oneline origin/main..HEAD
```

Expected: 6 commits, in this order (one per task with code):

```
refactor(ts-sdk): drop requestPayment -- vertical does not belong in core
refactor(py-sdk): drop request_payment -- vertical does not belong in core
refactor(py-sdk): drop legacy system_tools.py shim from runtime/tools
refactor(py-sdk): drop dead manifest.py and runner.py shims
chore(py-sdk): default KAJI_MODEL_PROVIDER to mock, not kimi
docs: note core-vs-add-on composition policy on index page
```

- [ ] **Step 4: Push**

```bash
git push origin chore/sdk-clean-cuts
```

- [ ] **Step 5: Open the PR**

```bash
gh pr create --title "chore(sdk): drop verticals and dead modules from core" --body "$(cat <<'EOF'
## Summary

Removes modules that violated the SDK's stated goal of "primitives only,
let the user decide what to build." Specifically:

- TS + Py: drop the request_payment tool -- it bridges to agentpay, which
  is a vertical. Belongs in @kaji/agentpay once that exists.
- Py: drop legacy system_tools.py -- documented as deprecated voice shim,
  no live consumers.
- Py: drop manifest.py and runner.py -- dead pass-through shims, zero
  consumers, all real users go straight to runtime.tools.registry.
- Py: flip the default LLM provider from kimi to mock. The SDK should
  not silently route a user's tokens to OpenRouter just because no
  provider was named. Users who want kimi opt in via
  KAJI_MODEL_PROVIDER=kimi.
- Docs: add a composition policy note on the index page so the
  "core-vs-add-on" intent is visible.

Voice, knowledge, observability, and the bundled CLI remain in the
Python SDK for v0.1.0 and are flagged in the new docs note as
add-on candidates for a future split.

## Test plan

- [x] bun --filter @kaji/sdk test (was 147, now 143)
- [x] cd kaji/sdk && poetry run pytest -q --ignore=tests/integration (was 298, now 296)
- [x] cd kaji/sdk && poetry run pyrefly check (0 errors)
- [x] cd kaji/sdk && poetry run ruff check . && ruff format --check .
- [x] bun --filter @kaji/docs build (exit 0)
EOF
)"
```

Capture the PR URL from the gh output.

---

## Self-Review

**Spec coverage:** the user asked for the payment tool removed, the kimi default removed, and any other unnecessary tools removed. Tasks:

| Ask | Task |
|---|---|
| Remove TS payment tool | 2 |
| Remove Python payment tool + lazy map / smoke / surface entries | 3 |
| Remove other unnecessary tools (`system_tools`, `manifest`, `runner`) | 4, 5 |
| Drop the `kimi` default provider | 6 |
| Make the composition policy visible | 7 |
| Sweep + push + PR | 8 |

Intentionally NOT in scope (per the prior conversation):
- Voice modality (user previously excluded).
- Knowledge / RAG and observability extraction (large; deserves its own plan).
- CLI extraction (the CLI is already a separate distribution via `[tool.poetry.scripts]`).
- `idempotency.py` (used by `tests/test_tools_policies.py`).
- `function_calls.py` (live consumer: `providers/gemini.py`).

**Placeholder scan:** every step ships exact commands, exact diff snippets, exact expected output. The only conditional-on-discovery step is Task 6 Step 5 (re-running the full suite to catch hidden assumptions about the `kimi` default) -- and the plan tells the implementer what to do if a failure surfaces.

**Type consistency:** no new public types created; only deletions and a single string literal change.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-21-sdk-clean-cuts.md`. Two execution options:

**1. Subagent-Driven (recommended)** -- dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** -- batch execution with checkpoints in this session.

Which approach?
