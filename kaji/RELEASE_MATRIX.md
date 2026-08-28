# Kaji SDK Release Matrix

## Release Promise

Kaji is in pre-beta release implementation. Promotion is blocked pending
same-commit protected release evidence: floor/latest runtime matrices, the
required automated TypeScript onboarding aggregate, keyed OpenAI proof, the
paired A/B benchmark, a
30-minute soak, a real signed tag, provenance, and publication verification.
The sole beta-supported external provider must complete a real model-requested
tool loop in Python and TypeScript on that exact release commit. It does not
mean every Python-only modality or infrastructure adapter is beta-ready.

The exact runtime defaults and operating boundaries are documented in
[`docs/kaji/production-beta.md`](../docs/kaji/production-beta.md). This matrix
is checked against the machine feature contract and both registry indexes by
`kaji/scripts/check_beta_contract.py`.

## Stable Core

<!-- beta-stable: agent-builder,runtime-turn-loop,cancellation,sessions,in-memory-event-store-journal,event-replay,tool-registry-planner-policy,openai-adapter,echo-integration -->

| Surface | Python | TypeScript | Release gate |
| --- | --- | --- | --- |
| Agent builder | Stable core | Stable core | unit tests |
| Runtime turn loop | Stable core | Stable core | unit tests + mandatory live OpenAI tool loops |
| Cancellation | Stable core | Stable core | cancellation lifecycle tests |
| Sessions | Stable core | Stable core | session isolation tests |
| In-memory event store/journal | Stable core | Stable core | journal/store tests |
| Event replay | Stable core | Stable core | replay tests |
| Tool registry/planner/policy | Stable core | Stable core | unit tests + echo integration |
| OpenAI adapter | Stable core | Stable core | unit tests + mandatory live tool loop in both SDKs |
| Echo integration | Stable core | Stable core | integration tests |

OpenAI is Kaji's sole beta-supported primary provider. Anthropic remains
implemented but experimental/WIP, with no beta compatibility or
publication-proof commitment.

The echo and GitHub integrations are catalog entries inside the first beta
promise.
`kaji-serve`, its REST/STT surface, and its Postgres/Supabase adapters are also
excluded from the 0.2 SDK beta promise. It has no hosted agent worker.

## Catalog Stability

<!-- beta-integrations: echo,github,gmail -->
<!-- experimental-integrations:  -->

| Integration | Stability | Runtimes |
| --- | --- | --- |
| echo | beta | python, typescript |
| github | beta | python, typescript |
| gmail | beta | python, typescript |

<!-- beta-experimental: python-redis-event-history,voice-tts,rag-retrieval,native-gemini-kimi,anthropic-adapter,retriever-selection,distributed-session-serialization,exactly-once-external-side-effects,unbounded-cross-process-replay,durable-snapshotting -->

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
| Anthropic adapter                      | Experimental cross-SDK | implemented and test-covered, but outside the beta support and publication-proof promise |
| Distributed same-session serialization | Deferred     | the beta coordinator is process-local   |
| Exactly-once external side effects     | Deferred     | external systems must honor idempotency |
| Unbounded or cross-process replay      | Deferred     | the beta replay is capacity-limited     |
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
| voice/TTS              | Configured TTS adapter smoke tests, interruption/cancellation tests, and explicit fallback behavior for unconfigured adapters.                        |
| DocumentRAG            | Deterministic retrieval tests, fixture-based indexing tests, eval set for answer grounding, and documented storage requirements.                     |
| native Gemini/Kimi     | Native keyed provider smoke tests, tool-call tests where supported, error mapping tests, and cost metadata tests.                                    |
| Anthropic adapter      | Explicit product promotion plus protected Python and TypeScript tool-loop evidence on one exact candidate.                                           |
| tool retrieval         | Ranking fixture tests, policy interaction tests, and runtime integration tests proving retrieved tools are callable.                                 |

## Release Gates

Run `bun run ci:local` before pushing. It validates the GitHub Actions
documents and executable workflow contracts, then runs the same Kaji gate used
by `gate / kaji`. A passing local run proves repository-owned logic on the
current macOS host only; it does not replace protected evidence below.

Use the root wrapper as the default local gate before a beta checkpoint:

```bash
uv run --project kaji/packages/py python kaji/scripts/beta_release_check.py
```

The wrapper runs the non-keyed local checks below and fails clearly when
required local tooling such as `bun` or `uv` is missing. This is an offline
rehearsal, not provider-readiness evidence. The protected rehearsal and
publish workflows are authoritative. `kaji-onboarding` protects the
deterministic TypeScript onboarding aggregate, `kaji-release` protects the keyed
OpenAI tool loop in both SDKs, and `kaji-publish` protects publisher
identity and the sole npm write. A missing OpenAI credential blocks the
release.

The pinned ast-grep step is mandatory. It guards the Python SDK/service
boundary, core package dependency direction, legacy tool-model imports,
TypeScript optional provider imports, and cancellation error shape.

| Gate                      | Command or workflow                                                             | Required for beta                                                   | Current evidence                       |
| ------------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------- | -------------------------------------- |
| Offline release rehearsal | `uv run --project kaji/packages/py python kaji/scripts/beta_release_check.py --release` | Yes; exact artifacts, tests, metadata, and locked dependency audits | Locally proven; not protected evidence |

<!-- beta-parity-scenarios: 67 -->

| Cross-SDK behavioral parity | `uv run --project kaji/packages/py python kaji/scripts/check_sdk_parity.py` | Yes; 67 deterministic scenarios | Locally proven |
| Shared schemas and registry | `gate / kaji` / `beta release gate` | Yes | locally proven; protected PR run pending |
| Pinned structural audit | `bun run audit:ast-grep` | Yes | Locally proven |
| Python floor/latest artifacts | `kaji.rehearsal.yml` and `kaji.publish.yml` on Python 3.11/3.14 | Yes | Pending protected run |
| Node floor/latest artifacts | the same workflows on Node 22/24 | Yes | Pending protected run |
| TypeScript onboarding evidence | exact current-run tarball and raw `kaji-artifacts`, `kaji-node-compat-22`, and `kaji-node-compat-24` REST ZIPs, independently recomputed by calibration and the protected aggregate | Yes; npm and Bun install, scaffold, no-key, Echo lifecycle, cold, and warm phases on GitHub-hosted Linux/x64 Node 22 `ubuntu-22.04` and Node 24 `ubuntu-24.04`; no human, macOS/arm64, Windows, or fully offline onboarding claim | Pending protected run |
| Paired A/B benchmark | `kaji.performance.yml`: immutable reference artifacts and the exact candidate on three numbered GitHub-hosted `macos-15` matrix replicas in one run attempt; five adjacent matched pairs after two warmups per case, with retained raw runner/image receipts; diagnostic runner names may repeat | Yes; timing must pass unanimously at ≤1.20 across all three replicas, mixed timing is inconclusive, and any per-pair RSS ratio >1.20 is a hard failure | Pending protected run |
| Thirty-minute soak | `run_beta_soak.py --minutes 30 --protected` on the exact candidate, with retained `macos-15` image provenance | Yes; independent of the paired benchmark | Pending protected run |
| Keyed OpenAI proof | `live_provider_proof.py` in `kaji-release` | Yes; OpenAI in Python and TypeScript, missing key blocks | Pending protected run |
| Exact-artifact GitHub proof | `live_github_proof.py` against the retained Python 3.11 and Node 22 compatibility receipts | Required before GitHub can move from experimental to beta; both installed artifacts must read, make one exactly approved comment, verify it, and clean it up | Pending protected private-repository run |
| Immutable signed tag | `kaji.publish.yml` tag verification | Yes; annotated, signed, approved tagger, direct commit | Pending real tag |
| SBOM, provenance, attestation | publish workflow supply-chain job | Yes | Pending real tag |
| Registry publication proof | protected npm publication plus exact npm byte, integrity, signature, provenance, and attestation verification; PyPI remains absent/deferred | Yes for the TypeScript beta; Python registry promotion is deferred | Pending approval/publication |

No-key provider hygiene proves only that missing credentials fail safely. It is
not provider-readiness evidence. Every protected row must come
from the exact release commit; a prior run cannot be substituted.
