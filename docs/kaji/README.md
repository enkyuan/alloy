# Kaji documentation

This is the canonical, versioned operating path for the Python `kaji` and
TypeScript `kaji-sdk` packages. Package pages link here for scope and to the
[release matrix](../../kaji/RELEASE_MATRIX.md) for evidence. Package README
canonical-status-link blocks do not change when release status changes.

Human time-to-hello-world evidence is **unmeasured**. The target protocol is
defined in [testing](testing.md) and [releasing](releasing.md); no cohort result
is inferred from automated smoke tests.

## Start here

- [Production-beta scope and installed quickstart](production-beta.md)
- [Python/TypeScript API parity](api-parity.md)
- [CLI grammar, streams, and exit codes](cli.md)
- [Deterministic and artifact testing](testing.md)
- [Concurrency and ordering](concurrency-and-ordering.md)
- [Tool and durable-result contracts](tool-contracts.md)
- [Integration manifests](integration-manifests.md)
- [Migration preflight](migrating-to-beta.md)
- [Troubleshooting](troubleshooting.md)
- [Release operator runbook](releasing.md)

## Support boundaries

Stable and experimental features and exports are classified by
[`feature-tiers-v1.json`](../../kaji/contracts/feature-tiers-v1.json).
OpenAI is Kaji's sole beta-supported primary provider. Keyed OpenAI proof in
both Python and TypeScript is mandatory release evidence, and a missing
`OPENAI_API_KEY` blocks release.
Anthropic remains implemented but experimental/WIP.
Anthropic, Gemini, Kimi, and OpenRouter are opt-in and carry no beta
compatibility or publication-proof commitment. `MockProvider` remains the
deterministic local/test default.
