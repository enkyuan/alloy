# Kaji documentation

This is the canonical, versioned operating path for the Python `kaji` and
TypeScript `@kaji/sdk` packages. Package pages link here for scope and to the
[release matrix](../../kaji/RELEASE_MATRIX.md) for evidence. Package README
bytes do not change when release status changes.

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

Stable, experimental, and deprecated features and exports are classified by
[`feature-tiers-v1.json`](../../kaji/contracts/feature-tiers-v1.json).
OpenAI and Anthropic adapters are declared stable, so protected Python and
TypeScript tool-loop proof for both is mandatory release evidence. Missing
credentials block a release. Experimental surfaces remain available only with
their documented opt-in and carry no beta compatibility promise.
