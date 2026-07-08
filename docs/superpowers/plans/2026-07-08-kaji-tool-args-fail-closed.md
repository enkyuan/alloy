# Kaji Tool Argument Fail-Closed Hardening

## Objective

Close the remaining beta-readiness gap found after the SDK/TS beta gate passed: tool-call arguments must be object-shaped before a user executor, approval handler, or tool implementation sees them.

This is a stable-core reliability hardening task for `kaji/sdk` and `kaji/ts`. It intentionally does not expand the beta surface, add provider features, or address keyed OpenAI live usage, which remains deferred until the rest of the non-keyed release gate is stable.

## Assessment

The existing beta release gate passes for non-keyed checks:

- TS unit tests, typecheck, build, package smoke.
- Python non-integration tests, typecheck, lint, wheel smoke.
- `sg scan --config sgconfig.yml kaji`.
- Keyed OpenAI proof is intentionally skipped unless explicitly requested.

Investigation found no current stable-core blocker in the package boundary, public surface, provider import laziness, replay, policy gates, approval gates, or event contracts. The concrete gap is narrower:

- Python `ToolPlanner` only rejects non-object arguments when a `ToolSpec` exists and declares `type: object`.
- TS `parseToolArgsJSON` returns any valid JSON value, even arrays, strings, numbers, booleans, or `null`, while its public type says `Record<string, unknown>`.
- TS `ToolPlanner` assumes `call.arguments` is an object before reading `__parse_error`.

For beta, a model/provider payload like `[]` or `"x"` should fail closed as invalid tool arguments and should never reach the executor.

## Review Fold-In

### Plan Tune

Question sensitivity is low. The user asked for implementation, and the beta contract already implies object-shaped tool args. No user choice is needed.

### CEO Review

The highest-leverage fix is a small invariant at the stable-core boundary, not a broader architecture rewrite. This avoids moving experimental Python-only surfaces into beta and keeps the release claim clear.

### Engineering Review

The implementation should be symmetric across Python and TS:

- Validate runtime `arguments` shape before parse-sentinel, schema, policy, approval, or execution logic that assumes object access.
- Keep empty/missing streamed args as `{}`.
- Treat valid but non-object JSON as a provider parse sentinel in TS so model-visible tool failure behavior stays consistent.
- Add focused regression tests that assert the executor is not called.

## Implementation Plan

1. Add Python planner tests in `kaji/sdk/tests/test_tool_planner.py`.
   - Pass list, string, and `None` arguments into `ToolPlanner`.
   - Assert emitted events are `TOOL_CALL_REQUESTED` then `TOOL_CALL_FAILED`.
   - Assert the executor is not called.
   - Assert the result contains `Invalid tool arguments`.

2. Add TS parser tests in `kaji/ts/tests/provider-args.test.ts`.
   - Keep existing `{}` behavior for `null`, `undefined`, and `""`.
   - Assert valid object JSON still parses.
   - Assert valid non-object JSON (`[]`, `"x"`, `1`, `true`) returns a labeled `__parse_error` sentinel.

3. Add TS planner tests in `kaji/ts/tests/tool-planner.test.ts`.
   - Pass list, string, and `null` arguments via runtime casts.
   - Assert planner emits request then failure.
   - Assert executor is not called.

4. Harden Python `ToolPlanner`.
   - Add a small JSON type-name helper.
   - Immediately reject `tool_args` when it is not a `dict`.
   - Return the same `Invalid tool arguments: ...` failure shape used by parse and schema validation.

5. Harden TS provider/parser and planner.
   - Add `jsonTypeName` and `isJsonObjectRecord` helpers where appropriate.
   - In `parseToolArgsJSON`, reject valid JSON that is not a non-array object with a provider-labeled `__parse_error`.
   - In `ToolPlanner`, guard `call.arguments` before `__parse_error`, schema validation, approval, or execution.

6. Verify.
   - `cd kaji/sdk && uv run pytest tests/test_tool_planner.py -q`
   - `cd kaji/ts && bun run test tests/provider-args.test.ts tests/tool-planner.test.ts`
   - `sg scan --config sgconfig.yml kaji`
   - `bash kaji/scripts/beta-release-check.sh`

## Completion Criteria

- Non-object tool arguments fail before executors in both SDKs.
- Provider JSON parsing in TS never returns non-object values as `Record<string, unknown>`.
- Existing zero-arg streamed-tool behavior remains unchanged.
- Focused tests and the full non-keyed beta gate pass.
- Any remaining beta caveat is documented as intentional: keyed live proof is deferred, and experimental Python-only surfaces remain outside the beta promise.
