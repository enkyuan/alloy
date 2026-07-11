# Kaji Beta Structural Audit Guards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing non-keyed Kaji beta release gate fail on structural regressions that would blur the stable SDK boundary.

**Architecture:** Keep the beta gate wrapper exactly as the orchestrator. Expand the `sgconfig.yml` rule set so the existing `sg scan --config sgconfig.yml kaji` step guards SDK/service boundaries, legacy tool model imports, and TypeScript optional peer dependency boundaries. Add lightweight Python tests that pin the rule files and documentation so the audit cannot silently shrink again.

**Tech Stack:** ast-grep YAML rules, Bash release wrapper, Python pytest file-content tests, existing `bun` and `uv` release gates.

## Global Constraints

- Do not change SDK runtime behavior.
- Do not add new runtime dependencies.
- Keep ast-grep optional when `sg` is absent; the wrapper already skips clearly.
- Keep provider SDKs as optional peers/extras: type-only imports and dynamic imports are allowed, runtime value imports outside lazy provider construction are not.
- Keep service-only imports out of `kaji/sdk/src`.
- Ignore OpenAI API key usage until non-keyed hardening is complete.
- Use GitButler for checkpoint commits if available. If `but` is unavailable, report that instead of using raw git write operations.

## Review Fold-In

- **Plan tune:** Avoid interactive prompts in this Codex session because AskUserQuestion is unavailable. The scope is one two-way decision with a clear low-risk default: add structural guards without changing behavior.
- **CEO review:** Beta should mean "stable core verified end to end" and "release gate catches boundary drift." The 12-month ideal is a small, explicit SDK core with experimental Python-only surfaces documented and fenced by tests.
- **Eng review:** Prefer guardrails over refactors. The smallest reliable implementation is new ast-grep rules plus tests that pin their presence and docs wording. No runtime code should move.
- **Karpathy guidelines:** Surgical change only. Every edited line must trace to beta-release guard coverage. Verify with focused tests, ast-grep scan, and the root beta gate.

## File Structure

- Create: `tools/ast-grep/rules/python-sdk-no-service-imports.yml`
  - Responsibility: fail the structural audit if `kaji/sdk/src` imports service-only packages such as FastAPI, TaskIQ, SQLAlchemy, or `kaji_serve`.
- Create: `tools/ast-grep/rules/python-core-no-upward-imports.yml`
  - Responsibility: fail if `kaji/sdk/src/core` starts depending on infra, runtime, knowledge, modalities, Redis, or service packages.
- Create: `tools/ast-grep/rules/python-runtime-no-legacy-tooldefinition.yml`
  - Responsibility: fail if current runtime tools import the deleted legacy `kaji.types.tool` surface.
- Create: `tools/ast-grep/rules/ts-no-provider-value-imports.yml`
  - Responsibility: fail if TypeScript source uses static runtime value imports from optional provider SDK packages instead of type-only or dynamic imports.
- Modify: `kaji/sdk/tests/test_beta_release_check.py`
  - Responsibility: pin the structural audit rule IDs and ensure release docs explain what the ast-grep step guards.
- Modify: `kaji/RELEASE_MATRIX.md`, `kaji/sdk/README.md`, `kaji/ts/README.md`, `docs/MVP.md`
  - Responsibility: state that the ast-grep step guards SDK/service boundaries and optional provider imports, not just generic "when available" scanning.

---

### Task 1: Add Beta Structural Audit Rules

**Files:**
- Create: `tools/ast-grep/rules/python-sdk-no-service-imports.yml`
- Create: `tools/ast-grep/rules/python-core-no-upward-imports.yml`
- Create: `tools/ast-grep/rules/python-runtime-no-legacy-tooldefinition.yml`
- Create: `tools/ast-grep/rules/ts-no-provider-value-imports.yml`

**Interfaces:**
- Consumes: `sgconfig.yml` with `ruleDirs: tools/ast-grep/rules`
- Produces: rule IDs consumed by `kaji/sdk/tests/test_beta_release_check.py`

- [ ] **Step 1: Add `python-sdk-no-service-imports.yml`**

```yaml
id: python-sdk-no-service-imports
language: Python
message: Keep kaji/sdk/src independent from service-only runtime dependencies; service APIs belong under kaji/serve.
severity: error
files:
  - "kaji/sdk/src/**/*.py"
rule:
  any:
    - pattern: import kaji_serve
    - pattern: import kaji_serve.$M
    - pattern: from kaji_serve import $$$
    - pattern: from kaji_serve.$M import $$$
    - pattern: import fastapi
    - pattern: import fastapi.$M
    - pattern: from fastapi import $$$
    - pattern: from fastapi.$M import $$$
    - pattern: import sqlalchemy
    - pattern: import sqlalchemy.$M
    - pattern: from sqlalchemy import $$$
    - pattern: from sqlalchemy.$M import $$$
    - pattern: import taskiq
    - pattern: import taskiq.$M
    - pattern: from taskiq import $$$
    - pattern: from taskiq.$M import $$$
    - pattern: import taskiq_redis
    - pattern: import taskiq_redis.$M
    - pattern: from taskiq_redis import $$$
    - pattern: from taskiq_redis.$M import $$$
    - pattern: import websockets
    - pattern: import websockets.$M
    - pattern: from websockets import $$$
    - pattern: from websockets.$M import $$$
```

- [ ] **Step 2: Add `python-core-no-upward-imports.yml`**

```yaml
id: python-core-no-upward-imports
language: Python
message: kaji.core must stay foundational; do not import infra, runtime, knowledge, modalities, Redis, or service modules from core.
severity: error
files:
  - "kaji/sdk/src/core/**/*.py"
rule:
  any:
    - pattern: import kaji.infra
    - pattern: import kaji.infra.$M
    - pattern: from kaji.infra import $$$
    - pattern: from kaji.infra.$M import $$$
    - pattern: import kaji.runtime
    - pattern: import kaji.runtime.$M
    - pattern: from kaji.runtime import $$$
    - pattern: from kaji.runtime.$M import $$$
    - pattern: import kaji.knowledge
    - pattern: import kaji.knowledge.$M
    - pattern: from kaji.knowledge import $$$
    - pattern: from kaji.knowledge.$M import $$$
    - pattern: import kaji.modalities
    - pattern: import kaji.modalities.$M
    - pattern: from kaji.modalities import $$$
    - pattern: from kaji.modalities.$M import $$$
    - pattern: import kaji_serve
    - pattern: import kaji_serve.$M
    - pattern: from kaji_serve import $$$
    - pattern: from kaji_serve.$M import $$$
    - pattern: import redis
    - pattern: import redis.$M
    - pattern: from redis import $$$
    - pattern: from redis.$M import $$$
```

- [ ] **Step 3: Add `python-runtime-no-legacy-tooldefinition.yml`**

```yaml
id: python-runtime-no-legacy-tooldefinition
language: Python
message: Runtime tools must use ToolSpec from kaji.runtime.tools.registry, not the deleted legacy kaji.types.tool surface.
severity: error
files:
  - "kaji/sdk/src/runtime/tools/**/*.py"
rule:
  any:
    - pattern: import kaji.types.tool
    - pattern: import kaji.types.tool.$M
    - pattern: from kaji.types.tool import $$$
    - pattern: from kaji.types.tool.$M import $$$
```

- [ ] **Step 4: Add `ts-no-provider-value-imports.yml`**

```yaml
id: ts-no-provider-value-imports
language: TypeScript
message: Keep provider SDK packages optional; use import type at the top level and dynamic import() for runtime loading.
severity: error
files:
  - "kaji/ts/src/**/*.ts"
rule:
  any:
    - pattern: import $X from "openai"
    - pattern: import { $$$ } from "openai"
    - pattern: import * as $X from "openai"
    - pattern: import $X from "@anthropic-ai/sdk"
    - pattern: import { $$$ } from "@anthropic-ai/sdk"
    - pattern: import * as $X from "@anthropic-ai/sdk"
```

- [ ] **Step 5: Run the structural audit**

Run:

```bash
PATH="$HOME/.local/bin:$HOME/.bun/bin:/opt/homebrew/bin:/usr/local/bin:$PATH" sg scan --config sgconfig.yml kaji
```

Expected: PASS with no findings.

### Task 2: Pin The Audit In Tests And Docs

**Files:**
- Modify: `kaji/sdk/tests/test_beta_release_check.py`
- Modify: `kaji/RELEASE_MATRIX.md`
- Modify: `kaji/sdk/README.md`
- Modify: `kaji/ts/README.md`
- Modify: `docs/MVP.md`

**Interfaces:**
- Consumes: rule IDs from Task 1.
- Produces: tests that fail if the release audit silently loses boundary coverage.

- [ ] **Step 1: Add test assertions for required rule IDs**

Add this helper and test to `kaji/sdk/tests/test_beta_release_check.py`:

```python
RULE_DIR = REPO_ROOT / "tools" / "ast-grep" / "rules"


def test_beta_structural_audit_rules_cover_sdk_boundaries() -> None:
    rule_text = "\n".join(path.read_text() for path in sorted(RULE_DIR.glob("*.yml")))

    for expected in [
        "python-sdk-no-service-imports",
        "python-core-no-upward-imports",
        "python-runtime-no-legacy-tooldefinition",
        "ts-no-provider-value-imports",
        "no-generic-ts-cancelled-error",
    ]:
        assert f"id: {expected}" in rule_text
```

- [ ] **Step 2: Add doc assertions for the structural audit purpose**

Extend `test_release_docs_reference_beta_release_check()`:

```python
for expected in [
    "SDK/service boundary",
    "TypeScript optional provider imports",
]:
    assert expected in combined
```

- [ ] **Step 3: Update release docs wording**

In each release-gate paragraph, replace:

```markdown
ast-grep when available
```

with:

```markdown
ast-grep boundary checks when available
```

Then add one sentence near the wrapper description:

```markdown
The ast-grep step guards the Python SDK/service boundary, core package dependency direction, legacy tool-model imports, TypeScript optional provider imports, and cancellation error shape.
```

- [ ] **Step 4: Run the focused Python test**

Run:

```bash
cd kaji/sdk && PATH="$HOME/.local/bin:$HOME/.bun/bin:/opt/homebrew/bin:/usr/local/bin:$PATH" uv run pytest tests/test_beta_release_check.py -q
```

Expected: PASS.

### Task 3: Verify The Release Gate Still Passes

**Files:**
- No source files beyond Tasks 1-2.

**Interfaces:**
- Consumes: beta gate wrapper and new rules.
- Produces: verification evidence for the final report.

- [ ] **Step 1: Run ast-grep directly**

Run:

```bash
PATH="$HOME/.local/bin:$HOME/.bun/bin:/opt/homebrew/bin:/usr/local/bin:$PATH" sg scan --config sgconfig.yml kaji
```

Expected: PASS with no findings.

- [ ] **Step 2: Run the full non-keyed beta gate**

Run:

```bash
uv run --project kaji/sdk python kaji/scripts/beta_release_check.py
```

Expected: PASS, ending with:

```text
PASS: non-keyed beta release checks completed
```

- [ ] **Step 3: Check git state**

Run:

```bash
git status --short
```

Expected: only the intentional plan, rule, doc, and test changes are present.

## NOT In Scope

- Keyed OpenAI live proof: explicitly deferred by the user until non-keyed hardening is complete.
- Runtime provider refactors: the current non-keyed beta gate passes; this task adds guardrails only.
- Promoting Redis realtime, voice/TTS, DocumentRAG, native Gemini/Kimi, or tool retrieval: release docs already keep these outside the stable beta promise.
- Making ast-grep a required dependency: the wrapper still skips clearly when `sg` is missing.

## What Already Exists

- `kaji/scripts/beta_release_check.py` already runs `sg scan --config sgconfig.yml kaji` when `sg` exists.
- `kaji/sdk/tests/test_package_boundaries.py` already guards Python SDK package boundaries with Python AST tests.
- `tools/ast-grep/rules/no-generic-ts-cancelled-error.yml` already guards one TS cancellation regression.
- Release docs already define stable core, experimental Python-only surfaces, TS-not-ported surfaces, and keyed live proof requirements.

## Failure Modes

| Codepath | Failure mode | Rescued? | Test? | User sees? | Logged? |
| --- | --- | --- | --- | --- | --- |
| ast-grep release step | Rule set silently shrinks to one narrow check | Y after Task 2 | Y | Beta gate remains meaningful | N/A |
| Python SDK imports | SDK accidentally imports FastAPI/TaskIQ/SQLAlchemy | Y after Task 1 | Y | Release gate fails before ship | N/A |
| TS providers | Optional provider SDK is statically value-imported | Y after Task 1 | Y | Release gate fails before package publish | N/A |
| Runtime tools | Legacy `kaji.types.tool` import returns | Y after Task 1 | Y | Release gate fails before ship | N/A |

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | CLEAR | HOLD SCOPE: guard release-gate coverage, no runtime expansion |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | AskUserQuestion unavailable in this session |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | Minimal guardrail plan, focused tests, direct release-gate verification |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | SKIPPED | No UI scope |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | SKIPPED | Release command UX unchanged except clearer audit purpose |

- **VERDICT:** CEO + ENG CLEARED — ready to implement the structural-audit guard pass.

NO UNRESOLVED DECISIONS
