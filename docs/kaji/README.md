# Kaji documentation

This is the canonical, versioned operating path for the Python `kaji` and
TypeScript `kaji` packages. Package pages link here for scope and to the
[release matrix](../../kaji/RELEASE_MATRIX.md) for evidence. Package README
canonical-status-link blocks do not change when release status changes.

Automated TypeScript onboarding evidence is defined in
[testing](testing.md), the
[evidence contract](typescript-onboarding-evidence.md), and the
[release runbook](releasing.md). It proves only the exact npm/Bun artifact
phases on the two declared GitHub-hosted Linux/x64 cells; it does not imply a
human, macOS/arm64, Windows, or fully offline onboarding result.

## Start here

- [Production-beta scope and installed quickstart](production-beta.md)
- [Python/TypeScript API parity](api-parity.md)
- [CLI grammar, streams, and exit codes](cli.md)
- [Deterministic and artifact testing](testing.md)
- [Protected TypeScript onboarding evidence](typescript-onboarding-evidence.md)
- [Concurrency and ordering](concurrency-and-ordering.md)
- [Tool and durable-result contracts](tool-contracts.md)
- [Integration manifests](integration-manifests.md)
- [Migration preflight](migrating-to-beta.md)
- [Troubleshooting](troubleshooting.md)
- [Release operator runbook](releasing.md)

## Three paths

**Kaji is an embedded execution runtime for safely connecting AI agents to real
product actions.** Agent frameworks decide what to do; Kaji provides the
execution boundary for identity, policy, approvals, durable events,
idempotency, failures, artifacts, and replay.

- **Build an agent:** compose a provider, tools, and a runtime for ordinary
  conversational or tool-using agents.
- **Expose a product capability:** wrap an existing product function as a
  risk-classified `Capability`; Kaji executes it through the same tool policy
  and approval boundary.
- **Run durable agent tasks:** use `TaskRuntime` and `TaskHandle` to create a
  task, inspect its journal-derived state and artifacts, and control its
  lifecycle. `Task.events()` is privileged raw journal data, not a safe log.

See [`examples/refund-agent`](../../examples/refund-agent) for a Stripe
test-mode product action using only package APIs.

## Support boundaries

Stable and experimental features and exports are classified by
[`feature-tiers-v1.json`](../../kaji/contracts/tiers/v1/features.json).
OpenAI is Kaji's sole beta-supported primary provider. Keyed OpenAI proof in
both Python and TypeScript is mandatory release evidence, and a missing
`OPENAI_API_KEY` blocks release.
Anthropic remains implemented but experimental/WIP.
Anthropic, Gemini, Kimi, and OpenRouter are opt-in and carry no beta
compatibility or publication-proof commitment. `MockProvider` remains the
deterministic local/test default.
