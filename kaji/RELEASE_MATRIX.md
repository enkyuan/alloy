# Kaji SDK Release Matrix

## Release Promise

Kaji is in pre-beta release implementation. Promotion is blocked pending
same-commit protected release evidence: floor/latest runtime matrices, the
required keyed OpenAI and Anthropic proofs, full benchmarks, a 30-minute soak,
a real signed tag, provenance, and publication verification. Both declared
stable provider adapters must complete a real model-requested tool loop in
Python and TypeScript on that exact release commit. It does not mean every
Python-only modality or infrastructure adapter is beta-ready.

The exact runtime defaults and operating boundaries are documented in
[`docs/kaji/production-beta.md`](../docs/kaji/production-beta.md). This matrix
is checked against the machine feature contract and both registry indexes by
`kaji/scripts/check_beta_contract.py`.

## Stable Core

<!-- beta-stable: agent-builder,runtime-turn-loop,cancellation,sessions,in-memory-event-store-journal,event-replay,tool-registry-planner-policy,openai-adapter,anthropic-adapter,echo-integration -->

| Surface | Python | TypeScript | Release gate |
| --- | --- | --- | --- |
| Agent builder | Stable core | Stable core | unit tests |
| Runtime turn loop | Stable core | Stable core | unit tests + mandatory live OpenAI and Anthropic tool loops |
| Cancellation | Stable core | Stable core | cancellation lifecycle tests |
| Sessions | Stable core | Stable core | session isolation tests |
| In-memory event store/journal | Stable core | Stable core | journal/store tests |
| Event replay | Stable core | Stable core | replay tests |
| Tool registry/planner/policy | Stable core | Stable core | unit tests + echo integration |
| OpenAI adapter | Stable core | Stable core | unit tests + mandatory live tool loop in both SDKs |
| Anthropic adapter | Stable core | Stable core | unit tests + mandatory live tool loop in both SDKs |
| Echo integration | Stable core | Stable core | integration tests |

The echo integration is the only catalog entry inside the first beta promise.
GitHub, HTTP, Web, filesystem, and SQLite remain explicit opt-in experiments.
`kaji-serve`, its legacy worker runtime, Redis transport, and voice path are
also excluded from the 0.2 SDK beta promise.

## Catalog Stability

<!-- beta-integrations: echo -->
<!-- experimental-integrations: fs,github,http,sqlite,web -->

| Integration | Stability | Runtimes |
| --- | --- | --- |
| echo | beta | python, typescript |
| fs | experimental | typescript |
| github | experimental | python, typescript |
| http | experimental | typescript |
| sqlite | experimental | typescript |
| web | experimental | typescript |

<!-- beta-experimental: python-redis-event-history,voice-tts,rag-retrieval,native-gemini-kimi,retriever-selection,typescript-http-integration,typescript-web-integration,typescript-filesystem-integration,typescript-sqlite-integration,distributed-session-serialization,exactly-once-external-side-effects,unbounded-cross-process-replay,durable-snapshotting -->

## Experimental Python-Only

| Surface                              | Status                   | Why                                                                         |
| ------------------------------------ | ------------------------ | --------------------------------------------------------------------------- |
| Redis realtime/history               | Experimental Python-only | present, but not a beta release gate                                        |
| voice/TTS                            | Experimental Python-only | provider adapters exist, placeholder TTS remains valid for unconfigured use |
| RAG/retrieval (DocumentRAG)          | Experimental Python-only | useful primitives, not cross-SDK parity                                     |
| native Gemini/Kimi                   | Experimental Python-only | not part of first live readiness gate                                       |
| Retriever selection (tool retrieval) | Experimental Python-only | not part of first live readiness gate                                       |

## Other Experimental or Deferred Surfaces

| Surface                                | Status       | Why                                     |
| -------------------------------------- | ------------ | --------------------------------------- |
| TypeScript HTTP integration            | Experimental | requires a bound transport              |
| TypeScript Web integration             | Experimental | requires a bound transport              |
| TypeScript filesystem integration      | Experimental | excluded from the first beta promise    |
| TypeScript SQLite integration          | Experimental | excluded from the first beta promise    |
| Distributed same-session serialization | Deferred     | the beta coordinator is process-local   |
| Exactly-once external side effects     | Deferred     | external systems must honor idempotency |
| Unbounded or cross-process replay      | Deferred     | beta replay is capacity-limited         |
| Durable snapshotting                   | Deferred     | promoted with a durable storage backend |

## TypeScript Not Ported

| Surface                | TS status                                               |
| ---------------------- | ------------------------------------------------------- |
| Redis realtime/history | Not ported                                              |
| voice/TTS              | Not ported                                              |
| RAG                    | Not ported                                              |
| native Gemini/Kimi     | Not ported; Gemini/Kimi are OpenAI-compatible factories |

## Promotion criteria

| Surface                | Promotion requirement before beta claim                                                                                                              |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| Redis realtime/history | Fake-Redis unit tests, keyed Redis integration tests, reconnect/backlog behavior tests, and documented durability limits.                            |
| voice/TTS              | Event registry tests, configured TTS adapter smoke tests, interruption/cancellation tests, and explicit fallback behavior for unconfigured adapters. |
| DocumentRAG            | Deterministic retrieval tests, fixture-based indexing tests, eval set for answer grounding, and documented storage requirements.                     |
| native Gemini/Kimi     | Native keyed provider smoke tests, tool-call tests where supported, error mapping tests, and cost metadata tests.                                    |
| tool retrieval         | Ranking fixture tests, policy interaction tests, and runtime integration tests proving retrieved tools are callable.                                 |

## Release Gates

Use the root wrapper as the default local gate before a beta checkpoint:

```bash
uv run --project kaji/sdk python kaji/scripts/beta_release_check.py
```

The wrapper runs the non-keyed local checks below and fails clearly when
required local tooling such as `bun` or `uv` is missing. This is an offline
rehearsal, not provider-readiness evidence. The protected `kaji-beta` workflow
requires OpenAI and Anthropic credentials and completes both provider tool
loops in both SDKs; a missing credential blocks the release.

The pinned ast-grep step is mandatory. It guards the Python SDK/service
boundary, core package dependency direction, legacy tool-model imports,
TypeScript optional provider imports, and cancellation error shape.

| Gate                      | Command or workflow                                                             | Required for beta                                                   | Current evidence                       |
| ------------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------- | -------------------------------------- |
| Offline release rehearsal | `uv run --project kaji/sdk python kaji/scripts/beta_release_check.py --release` | Yes; exact artifacts, tests, metadata, and locked dependency audits | Locally proven; not protected evidence |

<!-- beta-parity-scenarios: 67 -->

| Cross-SDK behavioral parity | `uv run --project kaji/sdk python kaji/scripts/check_sdk_parity.py` | Yes; 67 deterministic scenarios | Locally proven |
| Shared schemas and registry | `Kaji beta PR gate` / `Kaji beta PR gate` | Yes | locally proven; protected PR run pending |
| Pinned structural audit | `bun run audit:ast-grep` | Yes | Locally proven |
| Python floor/latest artifacts | `kaji.beta.yml` and `kaji.beta-publish.yml` on Python 3.11/3.14 | Yes | Pending protected run |
| Node floor/latest artifacts | the same workflows on Node 22/24 | Yes | Pending protected run |
| Full benchmark | `run_beta_benchmarks.py --full` on the pinned runner | Yes | Pending protected run |
| Thirty-minute soak | `run_beta_soak.py --minutes 30` on the pinned runner | Yes | Pending protected run |
| Keyed OpenAI + Anthropic proof | `live_provider_proof.py` in `kaji-beta` | Yes; both providers in Python and TypeScript, missing key blocks | Pending protected run |
| Five-user TTHW evidence | `validate_tthw_evidence.py` on exact-commit retained evidence | Yes; exactly five fresh users across macOS/Linux and Python/npm/Bun | Unmeasured |
| Immutable signed tag | `kaji.beta-publish.yml` tag verification | Yes; annotated, signed, approved tagger, direct commit | Pending real tag |
| SBOM, provenance, attestation | publish workflow supply-chain job | Yes | Pending real tag |
| Registry publication proof | protected PyPI/npm jobs plus byte verification | Yes | Pending approval/publication |

No-key provider hygiene proves only that missing credentials fail safely. It is
not provider-readiness evidence. Every protected row must come
from the exact release commit; a prior run cannot be substituted.
