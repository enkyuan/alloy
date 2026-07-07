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

## Promotion criteria

| Surface | Promotion requirement before beta claim |
| --- | --- |
| Redis realtime/history | Fake-Redis unit tests, keyed Redis integration tests, reconnect/backlog behavior tests, and documented durability limits. |
| voice/TTS | Event registry tests, configured TTS adapter smoke tests, interruption/cancellation tests, and explicit fallback behavior for unconfigured adapters. |
| DocumentRAG | Deterministic retrieval tests, fixture-based indexing tests, eval set for answer grounding, and documented storage requirements. |
| native Gemini/Kimi | Native keyed provider smoke tests, tool-call tests where supported, error mapping tests, and cost metadata tests. |
| tool retrieval | Ranking fixture tests, policy interaction tests, and runtime integration tests proving retrieved tools are callable. |

## Release Gates

Use the root wrapper as the default local gate before a beta checkpoint:

```bash
bash kaji/scripts/beta-release-check.sh
```

The wrapper runs all non-keyed checks below, fails clearly when required local
tooling such as `bun` or `uv` is missing, and does not spend provider credits by
default. To include the keyed OpenAI live proof in the same run, set
`KAJI_RUN_KEYED_LIVE=1` with `OPENAI_API_KEY`.

When available, the ast-grep step guards the Python SDK/service boundary, core package dependency direction, legacy tool-model imports, TypeScript optional provider imports, and cancellation error shape.

| Gate | Command | Required for beta |
| --- | --- | --- |
| Non-keyed beta gate bundle | `bash kaji/scripts/beta-release-check.sh` | Yes, aggregates non-keyed gates |
| Python unit/static | `cd kaji/sdk && uv run pytest -m "not integration" && uv run python scripts/typecheck_ty.py --output-format concise && uv run ruff check src tests` | Yes |
| Python wheel smoke | `cd kaji/sdk && bash scripts/release_smoke.sh` | Yes |
| TS unit/static/build | `cd kaji/ts && bun run test && node_modules/.bin/tsc --noEmit && bun run build` | Yes |
| TS package smoke | `cd kaji/ts && bun run scripts/smoke.mts` | Yes |
| No-key integration hygiene | `bash kaji/scripts/live-openai-tool-loop.sh` | Yes, proves skip hygiene only |
| Keyed OpenAI live proof | `OPENAI_API_KEY=... KAJI_LIVE_OPENAI_MODEL=gpt-5.4-mini bash kaji/scripts/live-openai-tool-loop.sh` | Yes, proves live readiness |
