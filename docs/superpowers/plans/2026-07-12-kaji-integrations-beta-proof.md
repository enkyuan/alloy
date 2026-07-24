# Kaji GitHub/Gmail Integration and macOS Beta-Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` to implement this plan task-by-task. Each task requires a fresh implementer, spec review, code-quality review, and GitButler checkpoint before the next dependent task starts.

**Goal:** Add production-hardened GitHub and Gmail tools to both Kaji SDKs, prove their schemas and live behavior on macOS, and close the remaining evidence-only gates for a defensible Python/TypeScript beta release.

**Architecture:** Keep integrations copyable and host-owned, but make their contracts canonical: one manifest/auth schema, one executable ABI per integration, fixed-origin bounded HTTP clients, and identical Python/TypeScript tool semantics. GitHub ships first with environment-token auth; Gmail follows only after explicit Google PKCE authorization, per-principal macOS Keychain storage, and a pre-execution approval boundary for sending. Both integrations begin `experimental` and promote independently after exact-commit offline and live proofs; neither silently expands the stable core.

**Tech Stack:** Python 3.11-3.14, asyncio, httpx, Pydantic 2, jsonschema Draft 2020-12, pytest, Ruff, ty, uv; TypeScript 5.7-6.x, Node 22/24, Bun, Zod 4, Ajv 2020, Vitest, provider-owned `node:https` agents/requests; killable bounded argument-array calls to macOS `/usr/bin/security` in both beta paths; ast-grep 0.44.1; existing Kaji benchmark, soak, provider-proof, release, SBOM, and provenance tooling.

**Status:** Reviewed and implementation-ready; CEO, engineering, developer-experience, and independent-review findings are folded in, with no unresolved decisions. Publication remains blocked by exhausted hosted-CI minutes.

**Supersedes:** This is the integration and remaining operator-evidence delta to `docs/superpowers/plans/2026-07-11-kaji-sdk-production-beta-gap-closure.md`. It does not reopen core runtime work already implemented and verified there.

## Global Constraints

- At implementation decision points, use this plan's recommended path by default. Deviate only when a materially safer, simpler, or more verifiable option is demonstrated, and record the rationale in the task checkpoint.
- Beta evidence and the first supported operator path target macOS only. The required first operator cells are arm64 and record the exact macOS version; x86_64 and untested macOS versions are not implied. Existing Linux-capable runtime/process code remains supported but is not part of the beta claim.
- GitHub and Gmail enter both registry indexes as `experimental`; `kaji/contracts/beta-core-v1.json` continues to list only Echo until an integration-specific promotion checkpoint passes.
- Hosted GitHub Actions cannot run while CI minutes are exhausted. Exact local commands must emit retained, hash-bound evidence and may establish `beta-ready` engineering status, but no signed beta tag, trusted publication, provenance claim, or registry release occurs until the existing protected workflow can run after minutes reset. Missing minutes are documented as an infrastructure block, never misreported as product failure or success.
- Shared contracts, their Python consumer, their TypeScript consumer, conformance fixtures, and package copies land in the same GitButler checkpoint.
- Registry modules never accept an arbitrary origin, redirect target, filesystem credential path, or shell command. GitHub is fixed to `https://api.github.com`; Gmail is fixed to `https://gmail.googleapis.com`; Google authorization is fixed to `https://accounts.google.com/o/oauth2/v2/auth`, token exchange/refresh to `https://oauth2.googleapis.com/token`, and revocation to `https://oauth2.googleapis.com/revoke`. Manifests and host configuration cannot override them; private tests inject transports rather than URLs.
- Provider clients disable ambient proxy discovery by default. A host may inject an explicitly reviewed transport, but it cannot relax origin, redirect, timeout, cancellation, or response-size policy.
- TypeScript registry source never calls `fetch`, `exec`, `spawn`, or a shell directly. Network calls go through the SDK fixed-origin client; Keychain calls go through an injected argument-array process runner in `src/auth/keychain.ts` with `shell: false`.
- Host-owned copies use provider-scoped destinations (`./integrations/github`, `./integrations/gmail`). Each CLI stages and validates the whole bundle before an atomic directory swap; `--force` may replace only an unmodified prior bundle whose provenance names the same provider, never a different provider or locally modified files.
- Every copied provider bundle includes the applicable Kaji license text/URL and binds its digest in provenance; “host-owned” means operationally copied and modifiable, not relicensed or open-source.
- `kaji add <provider> --check --out <provider-dir>` is read-only and reports `current|absent|outdated|modified|demoted` from canonical registry state plus the provenance sidecar; it never repairs implicitly.
- Python shared/release automation stays Python; TypeScript package-local automation stays TypeScript. Add no Bash scripts and keep new script names to two or three functional words.
- Tool arguments and results remain within the frozen 64 KiB durable boundary. Gmail outbound attachments and arbitrary binary bodies are excluded from this release.
- `read` tools may be `parallel_safe: true`; mutations are never parallel-safe. Remote communication that affects people or external systems is `external_effect`, not `write`.
- Host policy examples require approval for `external_effect`. `send_draft`, `create_issue`, and `add_comment` must prove transport is untouched when approval is rejected.
- No mutation tool automatically retries after a request may have reached the provider. Connection loss or timeout after dispatch remains `outcome=unknown` and retains the runtime idempotency tombstone.
- OAuth consent is an explicit CLI/host action. A tool call may refresh an existing grant, but it may never open a browser or start a consent listener unexpectedly.
- Google uses a bring-your-own Desktop OAuth client. Kaji does not ship a centralized OAuth client secret or claim Google verification for a hosted multi-user application.
- Secrets, authorization headers, raw provider response bodies, OAuth tokens, and Gmail/GitHub content never appear in operational logs, exceptions, retained proof evidence, or test failure diffs. Canonical tool-call/result events necessarily retain validated arguments/results; hosts must classify their event store as sensitive application data and apply their own retention/access controls. Gmail live proof uses synthetic data and a fresh bounded process-local in-memory store per runtime cell, asserts no disk persistence, clears it in `finally`, and drops the process before attestation. Do not claim encryption. Gmail cannot promote until its production durable-data contract is explicitly approved.
- Use `/usr/local/bin/but` for all version-control inspection and writes. Commit only file/hunk IDs belonging to the current task; do not stage or absorb ambient work from another agent.
- Implementation preflight must make `/usr/local/bin/but status` succeed and create the dedicated session branch through GitButler. The current checkout reports “Setup required”; repository setup is an operator prerequisite, not permission to fall back to Git writes or mix another agent's work.
- Do not push, publish, tag, or create a pull request during implementation unless the user separately authorizes that external change.

---

## Release Outcome and Independent Promotion Gates

The work has three distinct outcomes; conflating them would create false beta confidence.

1. **SDK core beta:** local gates first establish `beta-ready` on one exact commit/artifact set: existing core contract plus calibrated benchmark, full performance gate, 30-minute soak, four keyed provider proofs, and five fresh-user macOS TTHW runs. Published beta additionally requires restored hosted minutes, the protected workflow, signed tag, exact artifacts, SBOM, trusted provenance, and byte-verified publication.
2. **GitHub integration beta:** both executable adapters, ABI/conformance parity, bounded live read/write proof against one private fixture repository, package smoke, and approval/no-retry evidence.
3. **Gmail integration beta:** both executable adapters, OAuth/Keychain parity, ABI/conformance parity, bounded live read/draft/send-to-self proof against one disposable account per runtime cell, event-store/account cleanup attestations, package smoke, and approval/no-retry evidence.

Core beta is not blocked by an integration remaining experimental. An integration is not promoted merely because its unit tests pass.

## What Already Exists

| Existing capability | Evidence | Plan treatment |
|---|---|---|
| Closed manifest and index schemas | `kaji/contracts/integrations/manifest.schema.json:1-109`, `index.schema.json` | Extend the OAuth arm; preserve closed unions and pointer-normalized failures. |
| Byte-synced package schema copies | `kaji/scripts/sync_integration_contracts.py:17-31` | Generalize the same synchronizer; do not add a second copy mechanism. |
| Echo executable ABI gate | `kaji/scripts/check_integration_abi.py:18-26,291-320`, `kaji/ts/scripts/integration-abi.ts:223-244` | Replace Echo constants with a canonical cross-runtime ABI index. |
| Safe arbitrary-URL TypeScript request boundary | `kaji/ts/src/integrations/safe-fetch.ts:36-58,441-535` | Keep it for HTTP/Web; add a simpler fixed-origin client for provider-owned origins. |
| Full execution identity/cancellation/deadline context | `kaji/sdk/src/runtime/context.py:212-282`, `kaji/ts/src/runtime/context.ts:178-209` | Pass it through every integration request and token lookup. |
| Risk-driven approvals and bounded execution | `kaji/sdk/src/runtime/tools/policies.py:73-89`, `kaji/ts/src/tools/policy.ts:72-90` | Reuse; do not create integration-specific approval machinery. |
| Python Google installed-app helper | `kaji/sdk/src/integrations/oauth.py:64-467` | Harden and separate consent from access-token lookup; do not replace with another parallel helper. |
| Python Keyring storage | `kaji/sdk/src/integrations/oauth.py:107-160` | Preserve only as non-beta compatibility if needed; route the macOS beta factory through the same killable `/usr/bin/security` contract as TypeScript. |
| Environment secret sources | `kaji/ts/src/auth/source.ts:1-14` and Python provider patterns | Reuse for GitHub and Google client metadata; never accept secrets on the command line. |
| Stable release evidence machinery | `kaji/scripts/beta_benchmark_gate.py`, `run_beta_soak.py`, `live_provider_proof.py`, `beta_release_check.py` | Run and retain it; do not duplicate benchmark/provider/release orchestration. |

## NOT in Scope

- Notion, Google Calendar, and Slack are sequenced follow-ups. Calendar is the next Google OAuth reuse test; Notion tests structured CRUD; Slack waits until rate-limit and bot-install semantics are justified.
- GitHub Apps, organization installations, webhooks, GraphQL, Projects, pull-request mutation, checks, workflow dispatch, repository deletion, and arbitrary GitHub Enterprise base URLs are excluded.
- Gmail delete, trash, modify-label, settings, forwarding, delegation, bulk send, HTML composition, multiple recipients, CC/BCC, and outbound attachments are excluded.
- A Kaji-hosted OAuth redirect service, centralized credential vault, browser UI, web control plane, and multi-tenant SaaS account linking are excluded.
- General-purpose Node DNS-pinning transport remains the application-owned boundary for arbitrary URLs. The new client handles fixed HTTPS origins only and cannot be configured by tool arguments.
- Cross-platform Keychain parity is excluded from the beta claim. TypeScript fails clearly outside macOS; Python may keep existing cross-platform `keyring` compatibility without promising it.
- Exactly-once remote effects are not claimed. GitHub and Gmail do not provide a universal idempotency key for these operations; Kaji records unknown outcomes and requires reconciliation.
- Gmail attachment streaming waits for an explicit file-reference capability because base64 in tool arguments conflicts with the 64 KiB durable contract.
- Integration promotion uses a two-person exact-docs usability smoke, not an adoption/TTHW claim; the release-critical five-user cohort continues to test artifact install, no-key run, and Echo. A post-beta integration adoption cohort is a measured follow-up.
- A statistically meaningful integration-adoption claim is deferred until at least five fresh runs per promoted integration, with median/all-run thresholds and a 30-day repeat; it does not block this beta's two-person docs-usability gate.

## Target Architecture

```text
Canonical contracts
  manifest.schema.json + abi-index-v1.json + *-tool-abi-v1.json
               |
               +---- sync/check ----> Python registry package copies
               |                         | inspect_integration()
               |                         v
               |                     ToolSpec metadata
               |
               +---- sync/check ----> TypeScript registry sources
                                         | inspectIntegration()
                                         v
                                     ToolSpec metadata
               |
               +---- exact comparison: schema + manifest + Python + TypeScript

Host AgentBuilder
  -> scoped Integration
  -> validated ToolSpec
  -> ToolPolicy approval
  -> ToolExecutionController (deadline, cancellation, idempotency)
  -> integration handler
       -> principal-bound token provider
       -> FixedOriginClient(relative path only)
       -> GitHub or Gmail HTTPS origin
  -> bounded, detached JSON result
  -> durable event + replay
```

### Fixed-origin request flow and shadow paths

```text
relative path -> reject scheme/host/hash/credentials/"//" -> fixed HTTPS origin
      | nil/missing: type/schema failure before approval
      | empty: reject before network
      | malformed traversal: reject before network
      v
validated headers -> remove host/content-length/hop-by-hop -> link context signal + timeout
      | ambient proxy: disabled; reviewed injected transport cannot alter origin policy
      | missing token: INTEGRATION_AUTH_REQUIRED, failed, no network
      | cancelled: TOOL_CANCELLED with runtime-owned outcome
      v
manual-redirect fetch/httpx stream -> cap headers/body -> parse closed response shape
      | 3xx: reject; never follow
      | 401/403 auth: typed failed response when provider confirms rejection
      | 429/rate limit: bounded retry-after metadata; reads may be retried by host
      | timeout/connection loss after write dispatch: generic unknown outcome; no retry
      | malformed/oversize JSON: typed failed response for reads, unknown for uncertain writes
      v
bounded provider DTO -> bounded tool DTO -> durable JSON snapshot
```

### OAuth state machine

```text
DISCONNECTED -- explicit `kaji connect gmail --principal P` --> CONSENT_PENDING
      | authorization endpoint fixed: https://accounts.google.com/o/oauth2/v2/auth
CONSENT_PENDING -- state + PKCE callback --> EXCHANGING --> CONNECTED
      | token endpoint fixed: https://oauth2.googleapis.com/token
CONSENT_PENDING -- deny/state mismatch/5m timeout/cancel --> DISCONNECTED
CONNECTED -- access token valid --> CONNECTED
CONNECTED -- expiring --> REFRESHING(single-flight per principal)
REFRESHING -- success + required scopes granted --> CONNECTED
REFRESHING -- invalid_grant/scope drift --> AUTH_REQUIRED (no browser from tool)
CONNECTED/AUTH_REQUIRED -- `kaji disconnect` --> REVOKING --> DISCONNECTED
      | revocation endpoint fixed: https://oauth2.googleapis.com/revoke
REVOKING -- timeout/ambiguous failure --> REVOCATION_PENDING (token use blocked)
REVOCATION_PENDING -- `kaji disconnect` retry confirms revoke --> DISCONNECTED
REVOCATION_PENDING -- explicit `--force-local` --> DISCONNECTED + manual-revoke warning

Invalid transitions:
  tool call -> CONSENT_PENDING      prevented by accessToken() never invoking connect()
  principal A -> principal B token prevented by Keychain service+account key and lookup argument
  two refreshes for same principal prevented by per-principal in-flight map
  refresh for A blocks B           prevented by keyed, not global, single-flight entries
```

### Gmail draft/send flow

```text
create_draft(to, subject, body)
  -> strict email/header/body validation
  -> allowed-recipient check
  -> MIME text/plain + X-Kaji-Draft-Key=sha256(idempotency_key)
  -> Gmail drafts.create
  -> {draft_id, draft_key, to, subject}

send_draft(draft_id, draft_key, to, subject, body) -- approval binds full canonical payload
  -> approval rejected: handler and transport untouched
  -> fetch draft raw only to verify draft ownership + X-Kaji-Draft-Key
  -> deterministically rebuild MIME from the exact approved to/subject/body
  -> Gmail drafts.send once with {id: draft_id, message: {raw: approved_raw}}
  -> provider atomically replaces mutable draft content with approved MIME and sends
  -> success result OR unknown outcome after ambiguous transport failure
```

### Deployment and rollback

```text
contracts -> offline conformance -> GitHub/Gmail experimental implementation
         -> checkpoint evidence tooling + baseline + docs + protected workflow
         -> candidate artifacts -> artifact-executed candidate proof per provider
         -> machine promotion decision -> beta-marker checkpoint (or hold experimental)
         -> FINAL clean commit -> two-clone byte-identical freeze
         -> consume-only smokes + performance/soak/provider/TTHW + final integration proofs
         -> local immutable readiness: beta_ready/publication_blocked(ci_minutes)
         -> protected arm64 macOS candidate ingestion after minutes reset
         -> explicit authorization -> signed tag selects run/artifact ID + digests
         -> provenance + OIDC publication of selected bytes -> registry byte verification

Rollback before publication:
  change registry stability beta -> experimental; retain code and evidence for diagnosis
  copied host files remain deployed; publish checksum/ABI advisory + locate/remove/replace steps
Rollback after immutable publication:
  deprecate/yank affected beta, increment both beta versions, rebuild all evidence;
  never replace artifacts, retarget a signed tag, or reuse the published version
```

## File Responsibility Map

| File | Responsibility |
|---|---|
| `kaji/contracts/integrations/abi-index-v1.json` | Single list of cross-runtime integrations and canonical ABI files. |
| `github-tool-abi-v1.json`, `gmail-tool-abi-v1.json` | Exact namespace, descriptions, parameter schemas, risk, parallel safety, and timeout. |
| `github-api-conformance-v1.json`, `gmail-api-conformance-v1.json` | Provider request/response/error fixtures consumed by both runtimes. |
| `kaji/sdk/src/integrations/fixed_origin.py` | Pooled, bounded requests to constructor-fixed HTTPS origins. |
| `kaji/ts/src/integrations/fixed-origin.ts` | Native-fetch equivalent that accepts relative paths only. |
| `kaji/sdk/src/integrations/errors.py`, `kaji/ts/src/integrations/errors.ts` | Redaction-safe integration failure codes and safe pre-dispatch failures. |
| `kaji/sdk/src/integrations/oauth.py`, `kaji/ts/src/auth/oauth.ts` | Google PKCE consent, token validation, refresh single-flight, revoke, and access-token provider. |
| `kaji/ts/src/auth/keychain.ts` | Bounded macOS `/usr/bin/security` storage with no shell or token argv. |
| `kaji/sdk/src/cli/connect.py`, `disconnect.py`; TS equivalents | Explicit consent/revocation entry points. |
| `kaji/sdk/src/integrations/registry/github/*` | Python GitHub client/tools plus synchronized TS copies. |
| `kaji/ts/registry/github/*` | Canonical copyable TypeScript GitHub source. |
| `kaji/sdk/src/integrations/registry/gmail/*` | Python Gmail client/MIME/tools plus synchronized TS copies. |
| `kaji/ts/registry/gmail/*` | Canonical copyable TypeScript Gmail source. |
| `kaji/contracts/release/integration-proof-v1.schema.json` | Generic redacted two-runtime, one-provider evidence contract. |
| `gmail-reset-attestation-v1.schema.json` | Two-phase, per-runtime external account-reset binding with no account content. |
| `integration-docs-smoke-v1.schema.json` | Closed two-runtime exact-docs usability evidence with prerequisite time separated. |
| `integration-promotion-v1.schema.json` | Provider-specific candidate/final promote-or-hold decision bound to exact evidence. |
| `release-readiness-v1.schema.json` | Immutable pre-publication convergence record; publication outcome stays separate. |
| `kaji/scripts/integration_proof.py` | Bounded installed-artifact macOS live-proof orchestrator and validator. |
| `kaji/scripts/proof_cleanup.py` | Unpackaged GitHub proof reconciliation/cleanup requester with PATCH/DELETE. |
| `kaji/scripts/repro_artifacts.py` | Two-independent-clone byte-reproducibility gate and frozen candidate handoff. |

## Delivery Order and Parallel Lanes

| Lane | Tasks | Dependency |
|---|---|---|
| A — contracts | 1 | none |
| B — network | 2 | Task 1 error codes only |
| C — GitHub | 3 -> 4 | Tasks 1 and 2 |
| D — OAuth | 5 -> 6 | Task 1; may run parallel with Lane C after Task 2 |
| E — Gmail | 7 -> 8 | Tasks 2, 5, and 6 |
| F — deterministic gate | 9 | each implementation lane included in the candidate |
| G — evidence tooling | Task 10 | F; no live credentials/evidence yet |
| H — macOS/docs preparation | 11 -> 12 | G; all tracked inputs checkpoint before proof |
| I — candidate/final proof | Task 13 per provider | H; GitHub and Gmail remain independent |
| J — core evidence/release | Task 13 | H and the final clean commit; provider evidence only for promoted integrations |

Launch A first. After Task 1, run B and OAuth internals in parallel workspaces; GitHub waits for B, while OAuth CLI can proceed after OAuth internals. Join B/D only before Gmail. Tasks 10–12 must checkpoint all tooling/baseline/docs changes before Task 13 builds candidate bytes. GitHub proof may finish without Gmail; core evidence may finish with both integrations experimental. Shared registry indexes, contract synchronizer, public exports, docs, and release matrices are conflict zones and must be edited by one lane at a time.

## Implementation Tasks

### Task 1: Expand the Auth Contract and Generalize Executable ABI Verification

**Files:**

- Create `kaji/contracts/integrations/abi-index-v1.json`.
- Create `kaji/contracts/integrations/copy-provenance-v1.schema.json` for non-self-referential copied-bundle provenance.
- Modify `kaji/contracts/integrations/manifest.schema.json:25-64`.
- Modify `kaji/contracts/integrations/conformance-valid.json:73-83`.
- Modify `kaji/contracts/integrations/conformance-invalid.json:39-82`.
- Modify `kaji/sdk/src/integrations/__init__.py:49-55,194-206`.
- Modify `kaji/ts/src/integrations/registry-loader.ts:83-107`.
- Modify `kaji/scripts/sync_integration_contracts.py:17-112`.
- Modify `kaji/scripts/check_integration_abi.py:18-320`.
- Modify `kaji/ts/scripts/integration-abi.ts:11,193-244`.
- Modify `kaji/ts/scripts/check_integration_sources.ts:12-45`.
- Modify `kaji/scripts/check_beta_contract.py:31-52,1243-1276`.
- Test `kaji/sdk/tests/test_manifest_registry.py`.
- Test `kaji/ts/tests/manifest-validate.test.ts`.
- Test `kaji/ts/tests/integration-abi.test.ts`.

**Interfaces:**

- Produces Python `ManifestAuth(provider, client_id_env, client_secret_env)` and TypeScript `IntegrationAuth` with the same closed OAuth fields.
- Produces `inspect_integration()` in Python modules and `inspectIntegration()` in TypeScript modules as side-effect-free executable metadata entry points.
- Produces an ABI checker that takes an integration name rather than assuming Echo.

- [ ] **Step 1: Add failing closed-union tests**

```python
def test_oauth_manifest_requires_google_provider_and_client_id_env(tmp_path: Path) -> None:
    manifest = valid_manifest()
    manifest["auth"] = {
        "kind": "oauth",
        "provider": "google",
        "clientIdEnv": "GOOGLE_CLIENT_ID",
        "clientSecretEnv": "GOOGLE_CLIENT_SECRET",
        "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
    }
    loaded = validate_manifest_document(manifest, schema_root=CONTRACT_ROOT)
    assert loaded.auth.provider == "google"
    assert loaded.auth.client_id_env == "GOOGLE_CLIENT_ID"
    assert loaded.auth.client_secret_env == "GOOGLE_CLIENT_SECRET"


@pytest.mark.parametrize("field", ["provider", "clientIdEnv"])
def test_oauth_manifest_rejects_missing_required_metadata(field: str) -> None:
    auth = {
        "kind": "oauth",
        "provider": "google",
        "clientIdEnv": "GOOGLE_CLIENT_ID",
        "scopes": ["scope"],
    }
    del auth[field]
    with pytest.raises(ManifestValidationError) as caught:
        validate_manifest_document({**valid_manifest(), "auth": auth})
    assert caught.value.path.startswith("/auth")
```

Run: `UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync pytest kaji/sdk/tests/test_manifest_registry.py -q`

Expected: FAIL because the schema and immutable auth model do not expose provider/client environment metadata.

- [ ] **Step 2: Extend the canonical OAuth schema without runtime-controlled endpoints**

```json
{
  "type": "object",
  "required": ["kind", "provider", "clientIdEnv", "scopes"],
  "properties": {
    "kind": { "const": "oauth" },
    "provider": { "enum": ["google"] },
    "clientIdEnv": { "type": "string", "pattern": "^[A-Z][A-Z0-9_]*$" },
    "clientSecretEnv": { "type": "string", "pattern": "^[A-Z][A-Z0-9_]*$" },
    "scopes": {
      "type": "array",
      "minItems": 1,
      "uniqueItems": true,
      "items": { "type": "string", "minLength": 1, "maxLength": 512 }
    },
    "docs": { "type": "string", "format": "uri" }
  },
  "additionalProperties": false
}
```

Do not add auth URLs, token URLs, redirect URIs, Keychain paths, or principal IDs to the manifest. Those are executable/runtime policy, not catalog data.

- [ ] **Step 3: Parse identical immutable auth types**

```python
@dataclass(frozen=True, slots=True)
class ManifestAuth:
    kind: Literal["none", "env", "oauth"]
    env: str | None = None
    optional: bool = False
    docs: str | None = None
    provider: Literal["google"] | None = None
    client_id_env: str | None = None
    client_secret_env: str | None = None
    scopes: tuple[str, ...] = ()
```

```ts
export type IntegrationAuth =
  | Readonly<{ kind: "none" }>
  | Readonly<{ kind: "env"; env: string; optional?: boolean; docs?: string }>
  | Readonly<{
      kind: "oauth";
      provider: "google";
      clientIdEnv: string;
      clientSecretEnv?: string;
      scopes: readonly string[];
      docs?: string;
    }>;
```

- [ ] **Step 4: Replace Echo constants with a canonical ABI index**

```json
{
  "schemaVersion": "1.0.0",
  "integrations": {
    "echo": "echo-tool-abi-v1.json"
  }
}
```

The checker must reject absolute paths, `..`, missing files, duplicate manifest tool names, missing inspectors, top-level inspector errors, namespace drift, and any mismatch in description, complete parameter schema, risk, `parallel_safe`, or `timeout_ms`. It must print only JSON Pointer plus bounded type/length summaries, never rejected values.

- [ ] **Step 5: Add generic inspector fixtures**

```ts
it("fails when any indexed executable differs from its canonical ABI", async () => {
  const executable = {
    namespace: "github",
    tools: [{ ...canonicalGithub.tools[0]!, risk: "external_effect" as const }],
  };
  expect(() => compareExecutableIntegrationAbi(canonicalGithub, executable)).toThrow(
    /INTEGRATION_ABI_MISMATCH at \/tools\/0\/risk/,
  );
});
```

Run:

```bash
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/scripts/sync_integration_contracts.py --check
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/scripts/check_integration_abi.py --explain
cd kaji/ts && bun run test -- tests/manifest-validate.test.ts tests/integration-abi.test.ts
```

Expected after implementation: all commands PASS; the generalized ABI check names Echo and performs no network, browser, Keychain, or environment-secret read. Tasks 4 and 8 add GitHub and Gmail to the same index only when their executable inspectors exist.

- [ ] **Step 6: GitButler checkpoint**

Run `/usr/local/bin/but diff`, select only Task 1 file/hunk IDs, then create `codex/kaji-integrations` with commit message `feat(kaji): generalize integration auth and ABI contracts`. Preserve all unrelated workspace changes.

### Task 2: Add Bounded Fixed-Origin HTTP and Typed Integration Failures

**Files:**

- Create `kaji/sdk/src/integrations/fixed_origin.py`.
- Create `kaji/sdk/src/integrations/errors.py`.
- Create `kaji/ts/src/integrations/fixed-origin.ts`.
- Create `kaji/ts/src/integrations/errors.ts`.
- Modify `kaji/sdk/src/integrations/__init__.py` internal exports only; do not make origin-configurable client construction a stable public API.
- Modify `kaji/ts/src/integrations/index.ts`, `kaji/ts/package.json`, `kaji/ts/tsup.config.ts`, and `kaji/ts/tsconfig.json` to expose and build only a narrow `@kaji/sdk/integrations` subpath with provider-fixed requester factories; do not re-export raw policy, origin, client, or fetch injection from the root or subpath.
- Modify both Vitest configs to resolve the same `@kaji/sdk/integrations` self-import during source tests without widening the root export.
- Modify `kaji/contracts/errors/error-codes.json`.
- Create `kaji/contracts/errors/integration-recovery-v1.json` and synchronize its closed safe-remediation map into both packages.
- Modify `kaji/contracts/feature-tiers-v1.json` to classify these helpers experimental.
- Create `kaji/sdk/tests/test_fixed_origin.py`.
- Create `kaji/ts/tests/fixed-origin.test.ts`.
- Extend `kaji/sdk/tests/test_release_security.py:983-1011`.
- Extend `kaji/ts/tests/release-security.test.ts`.
- Modify Python/TypeScript durable tool-failure schemas, execution-error normalizers, CLI/replay renderers, and parity tests for closed recovery metadata.

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class _FixedOriginPolicy:
    origin: str
    timeout_seconds: float = 10.0
    max_response_bytes: int = 1_048_576
    allowed_methods: tuple[str, ...] = ("GET", "POST")


@dataclass(frozen=True, slots=True)
class IntegrationResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class FixedOriginClient:
    async def request(
        self,
        path_and_query: str,
        *,
        method: str,
        headers: Mapping[str, str],
        body: bytes | None,
        context: ToolExecutionContext,
    ) -> IntegrationResponse:
        raise NotImplementedError
```

```ts
interface FixedOriginPolicy {
  readonly origin: URL;
  readonly timeoutMs?: number;
  readonly maxResponseBytes?: number;
  readonly allowedMethods?: readonly ("GET" | "POST")[];
}

export interface FixedOriginRequester {
  request(
    pathAndQuery: string,
    init: Readonly<{ method: "GET" | "POST"; headers: HeadersInit; body?: Uint8Array }>,
    context: ToolExecutionContext,
  ): Promise<BoundedResponse>;
}

export function createGitHubRequester(): FixedOriginRequester;
export function createGmailRequester(): FixedOriginRequester;
```

Python mirrors the provider-specific production constructors (`for_github`, `for_gmail`) internally. In TypeScript, copied registry source imports only `FixedOriginRequester` plus `createGitHubRequester`/`createGmailRequester` from `@kaji/sdk/integrations`; those zero-argument factories accept no origin, fetch, proxy, headers, or policy override. Raw policy/client injection is module-private and used only by deterministic tests through relative imports. OAuth uses separate internal clients with the three hard-coded Google endpoints; it never accepts a host-supplied base URL.

Add `integrations: "src/integrations/index.ts"` as an explicit ESM/CJS/declaration tsup entry, a matching conditional `./integrations` package export, and a TypeScript self-path mapping for `@kaji/sdk/integrations`. Package tests import that subpath through both ESM and CJS from the packed tarball and assert that raw fixed-origin constructors are absent.

- [ ] **Step 1: Write adversarial URL/header/body tests**

Test empty paths, absolute URLs, protocol-relative URLs, backslashes, fragments, credentials, encoded authority changes, redirects, cross-origin `Location`, forbidden request headers, timeout, cancellation, one byte over the body limit, malformed `Content-Length`, and a response stream that never finishes. Assert the injected transport/fetch is untouched for every preflight rejection.

Poison `HTTP_PROXY`/`HTTPS_PROXY`/`NODE_USE_ENV_PROXY` and Node's process-wide global fetch dispatcher in a focused test. The zero-argument GitHub/Gmail production factories must use neither the proxy listener nor global dispatcher while the private direct test transport succeeds.

```ts
it.each([
  "",
  "https://evil.example/x",
  "//evil.example/x",
  "\\\\evil.example\\x",
  "/x#secret",
])("rejects unsafe path %s before fetch", async (pathAndQuery) => {
  const fetchImpl = vi.fn<typeof fetch>();
  const client = fixedOriginForTest("https://api.github.com", fetchImpl);
  await expect(client.request(pathAndQuery, { method: "GET", headers: {} }, context())).rejects.toThrow();
  expect(fetchImpl).not.toHaveBeenCalled();
});

it("keeps URL-looking query data on the fixed origin", async () => {
  const fetchImpl = boundedFetchStub();
  const client = fixedOriginForTest("https://api.github.com", fetchImpl);
  await client.request(
    "/search/code?q=https%3A%2F%2Fevil.example",
    { method: "GET", headers: {} },
    context(),
  );
  expect(fetchImpl.mock.calls[0]![0].toString()).toBe(
    "https://api.github.com/search/code?q=https%3A%2F%2Fevil.example",
  );
});
```

The query-value case remains valid because it cannot change the fixed origin; the test should assert it reaches the fixed host after URL encoding rather than reject it.

- [ ] **Step 2: Implement the strict request boundary**

The module-private constructor validates one HTTPS origin with `/`, no credentials, query, or hash; production callers reach it only through provider-specific constructors. `request` accepts only a leading single-slash relative path, resolves against the frozen origin, and asserts origin equality again. Python uses `httpx` with `trust_env=False`. TypeScript uses a private provider-owned `node:https.Agent`/`https.request` path (Bun-compatible), never native global fetch/dispatcher, with no proxy option or ambient environment discovery; raw agent/request injection stays test-private. Treat every 3xx as `INTEGRATION_REDIRECT_REJECTED`. Link context cancellation with the smaller of tool deadline and policy timeout. Stream at most the configured bytes and destroy/close the response and agent request when the cap is crossed.

- [ ] **Step 3: Add stable redaction-safe failure types**

```python
class IntegrationExecutionError(ToolExecutionError):
    error_code = "INTEGRATION_API_ERROR"
    retryable = False
    outcome: Literal["failed"] = "failed"
    reason_code: str
    recovery_code: str


class IntegrationAuthRequiredError(IntegrationExecutionError):
    error_code = "INTEGRATION_AUTH_REQUIRED"
    retryable = False


class IntegrationRateLimitedError(IntegrationExecutionError):
    error_code = "INTEGRATION_RATE_LIMITED"
    retryable = True


class IntegrationTransientReadError(IntegrationExecutionError):
    error_code = "INTEGRATION_API_ERROR"
    retryable = True


class IntegrationPolicyError(IntegrationExecutionError):
    error_code = "INTEGRATION_POLICY_REJECTED"
    retryable = False
```

Only raise these when the handler can certify no external side effect occurred: missing credential before dispatch, provider-confirmed auth rejection, provider-confirmed rate-limit/transient read rejection, a failed read, or local allowlist/schema policy rejection. Permanent validation/policy/auth failures are never retryable. Ambiguous mutation failures must remain ordinary exceptions so the execution controller records `unknown` and does not retry.

Do not let actionable guidance disappear at the generic tool-failure boundary. Extend both durable failure schemas/normalizers with closed optional `reason_code`, `recovery_code`, and versioned `doc_url` fields sourced only from `integration-recovery-v1.json`; never persist vendor text or arbitrary exception messages. Cover missing grant, missing/locked/corrupt/unsupported Keychain, scope drift, policy rejection, rate limit, and provider-specific unknown mutation reconciliation. CLI/replay/host renderers map codes to problem/cause/fix text such as `kaji connect gmail --principal <same-principal>` without echoing the real principal. Unknown GitHub/Gmail effects receive provider-specific reconciliation guidance while retaining generic safe event text.

- [ ] **Step 4: Verify focused and security suites**

```bash
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync pytest kaji/sdk/tests/test_fixed_origin.py kaji/sdk/tests/test_release_security.py -q
cd kaji/ts && bun run test -- tests/fixed-origin.test.ts tests/release-security.test.ts
```

Expected: PASS with no token, header value, body excerpt, URL query, email content, or provider payload reflected in failures.

- [ ] **Step 5: GitButler checkpoint**

Commit only Task 2 changes to `codex/kaji-integrations` with `feat(kaji): add bounded fixed-origin clients`.

### Task 3: Implement Canonical GitHub Clients in Both Runtimes

**Files:**

- Create `kaji/contracts/integrations/github-api-conformance-v1.json`.
- Create `kaji/sdk/src/integrations/registry/github/client.py`.
- Create `kaji/ts/registry/github/client.ts`.
- Create `kaji/sdk/tests/test_github_client.py`.
- Create `kaji/ts/tests/github-client.test.ts`.

**Interfaces:**

```python
class GitHubClient:
    def __init__(
        self,
        *,
        token_for: Callable[[ToolExecutionContext], Awaitable[str]],
        repositories: Collection[str],
        http: FixedOriginClient,
    ) -> None: ...

    async def request_json(
        self,
        context: ToolExecutionContext,
        *,
        method: Literal["GET", "POST"],
        repository: str,
        path: str,
        query: Mapping[str, str | int] | None = None,
        body: Mapping[str, object] | None = None,
        mutation: bool = False,
    ) -> Mapping[str, object] | Sequence[object]: ...
```

```ts
export interface GitHubClientOptions {
  readonly tokenFor: (context: ToolExecutionContext) => Promise<string>;
  readonly repositories: readonly string[];
  readonly http: FixedOriginRequester;
}
```

- [ ] **Step 1: Write one shared provider-conformance fixture**

The JSON fixture defines exact method/path/query/header/body and normalized result for: code search, content lookup, issue list/detail, issue creation, comment creation, empty result, 401, permission 403, secondary-rate-limit 403, 404, 422, 429, malformed JSON, oversize body, cancellation, and connection loss after a write dispatch. Include bounded headers only: `accept`, `content-type`, `link`, `retry-after`, `x-ratelimit-remaining`, and `x-ratelimit-reset`.

- [ ] **Step 2: Enforce repository and path authorization before token/network access**

```python
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")

def require_repository(value: str, allowed: frozenset[str]) -> str:
    if not REPOSITORY.fullmatch(value) or value not in allowed:
        raise IntegrationPolicyError()
    return value

def encode_content_path(value: str) -> str:
    parts = value.split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise IntegrationPolicyError()
    return "/".join(quote(part, safe="") for part in parts)
```

At construction, validate and snapshot repositories into an immutable `frozenset`/frozen copied array so later caller mutation cannot widen authorization. For `search_code`, reject case-insensitive scope-changing `repo:`, `org:`, or `user:` qualifiers anywhere in the user query before token/network access, append exactly one SDK-owned `repo:<validated-owner/name>` qualifier, and reject the whole provider response if any result's `repository.full_name` differs from that repository before copying a path/snippet. Token resolution occurs only after repository/path/query validation. Token strings are trimmed, bounded to 4,096 characters, rejected if blank/CR/LF-bearing, and inserted only into `Authorization: Bearer ...`.

- [ ] **Step 3: Implement response and retry semantics**

- Parse JSON only after a 1 MiB transport cap.
- Accept only documented object/array shapes and copy whitelisted fields into bounded DTOs. Snapshot/freeze all returned collections.
- `search_code`: at most 20 rows; path <=512 characters, SHA <=64, and text-match fragment <=1,024 UTF-8 bytes per row; normalized result <=32 KiB.
- `get_file`: path <=512, SHA <=64, and decoded content <=48 KiB. For larger files return metadata plus `content_omitted: true` and provider size; never return a partial ambiguous file.
- `list_issues`: at most 20 rows; number, state, title <=256 characters, and body preview <=1,024 UTF-8 bytes. `get_issue`/created issue retain body <=16,384 UTF-8 bytes. Comment creation returns identifiers/URL only, not an echoed body.
- Serialize the final DTO with the runtime's canonical JSON encoder before returning and enforce the exact 65,536-byte durable ceiling. Shared fixtures cover the last accepted byte and first rejected byte in both runtimes.
- For GET only, allow at most two attempts for provider-confirmed 429/secondary-limit responses with `Retry-After` in `0..2` seconds, injected sleeper, and remaining tool deadline sufficient for the delay.
- Never retry POST.
- A 401/403/429 response certifies no mutation only when GitHub returned it before success; map it to typed failed outcome. A timeout, reset, or parse failure after POST remains unknown.
- Ignore response body text when constructing errors.

- [ ] **Step 4: Run both conformance consumers**

```bash
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync pytest kaji/sdk/tests/test_github_client.py -q
cd kaji/ts && bun run test -- tests/github-client.test.ts
```

Expected: every fixture row has the same normalized method/path/body/result or error code in both runtimes.

- [ ] **Step 5: GitButler checkpoint**

Commit only Task 3 changes with `feat(kaji): add bounded GitHub clients`.

### Task 4: Expose the GitHub Tool Bundle, Registry, CLI, and Package Surface

**Files:**

- Create `kaji/sdk/src/integrations/registry/github/__init__.py`.
- Create `kaji/contracts/integrations/github-tool-abi-v1.json` and add GitHub to `abi-index-v1.json`.
- Create `kaji/sdk/src/integrations/registry/github/github.py`.
- Create `kaji/sdk/src/integrations/registry/github/manifest.json`.
- Create synchronized `kaji/sdk/src/integrations/registry/github/github.ts` and `client.ts`.
- Create copied no-network test helpers/templates and deterministic provider fixtures for Python and TypeScript; they expose scripted outcomes, never an origin/fetch override.
- Create `kaji/ts/registry/github/index.ts` and `manifest.json`.
- Modify both registry `index.json` files.
- Modify `kaji/sdk/pyproject.toml:49-129`.
- Modify `kaji/sdk/src/cli/add.py:23-78`.
- Modify `kaji/ts/src/cli/add.ts:132-216`.
- Modify package-boundary, list/add, registry, archive, copy-provenance, and package-smoke tests named in the File Responsibility Map.
- Create `kaji/sdk/tests/test_github_registry.py`.
- Create `kaji/ts/tests/github-registry.test.ts`.

**Tool ABI:**

| Tool | Required arguments | Optional bounded arguments | Risk | Parallel | Timeout |
|---|---|---|---|---|---|
| `search_code` | `repository`, `query` (1-256) | `page` 1-50 default 1; `per_page` 1-20 default 10 | read | true | 10,000 ms |
| `get_file` | `repository`, `path` (1-512) | `ref` (1-100), omitted = repository default branch | read | true | 10,000 ms |
| `list_issues` | `repository` | `state` default `open`; `page` 1-1000 default 1; `per_page` 1-20 default 10 | read | true | 10,000 ms |
| `get_issue` | `repository`, `issue_number` 1..9,007,199,254,740,991 | none | read | true | 10,000 ms |
| `create_issue` | `repository`, `title` (1-256), `body` (0-16,384) | none | external_effect | false | 15,000 ms |
| `add_comment` | `repository`, `issue_number` 1..9,007,199,254,740,991, `body` (1-16,384) | none | external_effect | false | 15,000 ms |

- [ ] **Step 1: Write failing schema/registration/approval tests**

```python
async def test_create_issue_rejection_never_resolves_token_or_calls_transport() -> None:
    token_for = AsyncMock(side_effect=AssertionError("token must not be read"))
    transport = AsyncMock(side_effect=AssertionError("network must not run"))
    integration = _create_github_integration_for_test(
        token_for=token_for,
        repositories={"kaji-fixtures/tools"},
        http=fixed_origin_stub(transport),
    )
    runtime = runtime_with(integration, approval=False)
    result = await runtime.run_turn(tool_call("github_create_issue", VALID_CREATE_ARGS))
    assert result.failure.error_code == "TOOL_APPROVAL_REJECTED"
    token_for.assert_not_awaited()
    transport.assert_not_awaited()
```

Also test every min/max boundary, `additionalProperties: false`, repository allowlist, catalog names, risk, parallel flags, timeouts, no module-global registration, and side-effect-free inspector.

- [ ] **Step 2: Implement class-based factories with dependency injection**

```python
def create_github_integration(
    *,
    token_for: Callable[[ToolExecutionContext], Awaitable[str]],
    repositories: Collection[str],
) -> GitHubIntegration:
    return _create_github_integration_for_test(
        token_for=token_for,
        repositories=repositories,
        http=FixedOriginClient.for_github(),
    )


def _create_github_integration_for_test(
    *,
    token_for: Callable[[ToolExecutionContext], Awaitable[str]],
    repositories: Collection[str],
    http: FixedOriginClient,
) -> GitHubIntegration:
    client = GitHubClient(
        token_for=token_for,
        repositories=repositories,
        http=http,
    )
    return GitHubIntegration(client)


def inspect_integration() -> GitHubIntegration:
    return _create_github_integration_for_test(
        token_for=_inspection_token,
        repositories={"owner/repository"},
        http=_inspection_http(),
    )
```

The TypeScript production factory mirrors `createGithubIntegration` without a client/origin override; a non-exported `createGithubIntegrationForTest` accepts the injected client. Inspector dependencies throw if invoked; ABI verification calls only `tools()`.

- [ ] **Step 3: Quarantine the registry entry and align CLI behavior**

Both indexes declare `stability: "experimental"` and runtimes `python`, `typescript`. Python gains `--allow-experimental` and must reject before creating `--out`, matching TypeScript. Docs/next-step output uses provider-scoped `--out ./integrations/github`; install-both-in-either-order, I/O rollback, sidecar mismatch, cross-provider `--force`, and locally modified target tests prove no mixed bundle. After opt-in, both CLIs print the exact credential step:

```text
next: set GITHUB_TOKEN to a fine-grained token limited to the configured repositories
docs: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens
```

Each successful copy writes `.kaji-integration-provenance.json` beside the bundle with integration name, SDK version, ABI digest, registry-manifest digest, license identifier/URL/digest, and a sorted map of relative copied-file body SHA-256 values. The sidecar never hashes itself; registry manifests/source stay byte-canonical. Collision/`--force` tests cover missing/tampered sidecars and locally modified files.

Add read-only `--check` with stable exits `0=current`, `3=absent`, `4=outdated`, `5=modified`, and `6=demoted`; human/JSON output names the state and safe next command. `--force` may atomically replace only `outdated` and byte-unmodified same-provider bundles. `modified`, `demoted`, cross-provider, or unknown provenance requires explicit inspect/reconcile/remove and cannot be bypassed by `--force`.

- [ ] **Step 4: Replace the obsolete third-party prohibition with an allowlist**

`kaji/sdk/tests/test_package_boundaries.py:133-150` must assert the only first-party copyable third-party directories are `github` and `gmail`; `gcal` remains absent. This is an intentional product-contract migration, not a deletion of the boundary test.

- [ ] **Step 5: Run focused package/ABI gates**

```bash
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync pytest kaji/sdk/tests/test_github_registry.py kaji/sdk/tests/test_manifest_registry.py kaji/sdk/tests/cli/test_add.py kaji/sdk/tests/test_package_boundaries.py -q
cd kaji/ts && bun run test -- tests/github-registry.test.ts tests/manifest-validate.test.ts tests/cli-add.test.ts tests/cli-list.test.ts tests/integration-abi.test.ts
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/scripts/check_integration_abi.py --explain
```

Expected: GitHub is listed as experimental in both SDKs, denied without opt-in, copied with opt-in, and byte/ABI equivalent.

- [ ] **Step 6: GitButler checkpoint**

Commit only Task 4 changes with `feat(kaji): add experimental GitHub tools`.

### Task 5: Harden Google OAuth and Add TypeScript/macOS Keychain Parity

**Files:**

- Modify `kaji/sdk/src/integrations/oauth.py:59-467`.
- Create `kaji/sdk/src/integrations/keychain.py` and `kaji/sdk/tests/test_integration_keychain.py` for the killable macOS beta adapter.
- Create `kaji/ts/src/auth/oauth.ts`.
- Create `kaji/ts/src/auth/keychain.ts`.
- Modify Python and TypeScript public exports and `feature-tiers-v1.json`.
- Extend `kaji/sdk/tests/test_integrations_oauth.py`.
- Create `kaji/ts/tests/oauth.test.ts`.
- Create `kaji/ts/tests/keychain.test.ts`.
- Extend both SDK release-security tests.

**Interfaces:**

```python
@runtime_checkable
class TokenStorage(Protocol):
    def load(self) -> dict[str, object] | None: ...
    def save(self, data: dict[str, object]) -> None: ...
    def delete(self) -> None: ...


TokenStorageFor = Callable[[str], TokenStorage]


@dataclass(frozen=True, slots=True)
class OAuthTokenSet:
    access_token: str
    refresh_token: str
    expires_at_epoch_ms: int
    granted_scopes: tuple[str, ...]
    token_type: Literal["Bearer"] = "Bearer"


@dataclass(frozen=True, slots=True)
class OAuthCredentialRecord:
    schema_version: Literal[1]
    state: Literal["active", "revocation_pending"]
    tokens: OAuthTokenSet


@dataclass(frozen=True, slots=True)
class DisconnectResult:
    local_state: Literal["deleted", "revocation_pending", "missing"]
    remote_revoked: bool


class GoogleOAuthClient:
    async def connect(self, principal_id: str, cancellation: CancellationToken) -> None: ...
    async def access_token(self, context: ToolExecutionContext) -> str: ...
    async def disconnect(self, principal_id: str, cancellation: CancellationToken, *, force_local: bool = False) -> DisconnectResult: ...
```

```ts
export interface OAuthCredentialRecord {
  readonly schemaVersion: 1;
  readonly state: "active" | "revocation_pending";
  readonly tokens: OAuthTokenSet;
}

export interface OAuthTokenStorage {
  load(principalId: string, signal: AbortSignal): Promise<OAuthCredentialRecord | undefined>;
  save(principalId: string, record: OAuthCredentialRecord, signal: AbortSignal): Promise<void>;
  delete(principalId: string, signal: AbortSignal): Promise<void>;
}

export interface OAuthAccessTokenProvider {
  accessToken(context: ToolExecutionContext): Promise<string>;
}

export class GoogleOAuthClient implements OAuthAccessTokenProvider {
  connect(principalId: string, signal: AbortSignal): Promise<void>;
  accessToken(context: ToolExecutionContext): Promise<string>;
  disconnect(
    principalId: string,
    signal: AbortSignal,
    options?: Readonly<{ forceLocal?: boolean }>,
  ): Promise<Readonly<{ localState: "deleted" | "revocation_pending" | "missing"; remoteRevoked: boolean }>>;
}
```

Both runtimes validate integration principal IDs as `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`; whitespace, controls, `@`, and non-ASCII are rejected before environment/Keychain/browser/network access. Derive the Keychain account as lowercase SHA-256 of `dev.kaji.oauth.<integration>\0<principal-id>` so raw principal values never enter `/usr/bin/security` arguments. CLI success/error output refers to “the requested principal” and never echoes it.

**Gmail stop/go prerequisite:** Do not start Gmail runtime work merely because GitHub landed. First require GitHub deterministic/package/live gates with no open P0/P1 in shared layers, confirm a Google Desktop OAuth project has the two restricted scopes and disposable test users, and run a macOS arm64 Keychain spike that proves save/load/delete, locked/missing/corrupt behavior, stdin token input, bounded stdout, cancellation/timeout, and no shell/native addon/secret leakage. If the spike or Google policy posture fails, leave Gmail deferred and do not introduce a native dependency without a new reviewed decision.

- [ ] **Step 1: Write the OAuth state-machine tests before changing behavior**

Cover:

- `access_token` with no stored grant raises `INTEGRATION_AUTH_REQUIRED` and never opens a browser/listener.
- `access_token(context)` uses `context.principal_id`, cancellation, and deadline in both runtimes; invalid principal or `revocation_pending` fails before token/network access.
- `connect` uses `127.0.0.1`, a random port, state, a 43-128 character verifier, and S256 challenge.
- authorization, token/refresh, and revocation calls use the three hard-coded production endpoints; manifests, public constructors, and host configuration cannot override them.
- wrong state, denied consent, missing code, callback timeout, cancellation, browser failure, token timeout, malformed JSON, missing token fields, unsupported token type, blank/oversize tokens, and scope omission each close the listener and emit no secret.
- two refreshes for one principal make one token request; different principals refresh concurrently.
- disconnect racing refresh/connect fences that principal first, cancels/awaits the old operation, and permits no post-disconnect token save or use; different principals remain independent.
- a short-deadline waiter may detach without cancelling a refresh still needed by another waiter; when every waiter detaches the shared refresh aborts.
- an existing unexpired token makes no request.
- stored scopes must be a superset of requested scopes; mismatch deletes the local grant and requires explicit reconnect.
- `invalid_grant` deletes local tokens and requires explicit reconnect.
- refresh responses that omit `refresh_token` preserve the stored refresh token; omitted `scope` preserves previously verified scopes, while a present scope must remain a superset.
- disconnect requires no client ID, confirms remote revocation before deletion, stores a blocked `revocation_pending` record on ambiguous failure, retries that state on the next disconnect, and supports explicit `--force-local` only with manual Google-account revocation guidance.

```ts
it("never starts consent from accessToken", async () => {
  const browser = vi.fn();
  const callback = vi.fn();
  const client = googleClient({ storage: emptyStorage(), browser, callback });
  await expect(client.accessToken(context({ principalId: "user-123" }))).rejects.toMatchObject({
    error_code: "INTEGRATION_AUTH_REQUIRED",
  });
  expect(browser).not.toHaveBeenCalled();
  expect(callback).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Make token storage atomic, principal-bound, and bounded**

Python file storage writes a versioned `OAuthCredentialRecord` to a same-directory mode-0600 temporary file, `fsync`s it, atomically replaces the target, and rejects symlinks/non-regular files. Preserve the existing no-argument `TokenStorage` API and inject `token_storage_for(principal_id)` into `GoogleOAuthClient`; the factory hashes the validated principal into the Keychain account or an explicitly principal-scoped file-store key. Reject unknown record versions/states and records over 16 KiB.

For the macOS beta factory, do not place Keychain reads/writes behind `asyncio.to_thread`: cancelling that await cannot stop a late blocking write. Python and TypeScript both use a killable `/usr/bin/security` argument-array subprocess adapter with `shell: false`, bounded stdin/stdout, a 10-second operation timeout, SIGTERM grace then SIGKILL, and awaited process reaping. A cancelled/timed-out save/delete cannot complete after the CLI reports failure. The old Python `keyring` adapter may remain explicitly non-beta compatibility, but live proof and documented production construction must select the subprocess adapter. Add deterministic late-completion tests.

TypeScript `MacOSKeychainTokenStorage` uses:

```ts
export interface KeychainProcess {
  run(
    args: readonly string[],
    options: Readonly<{ stdin?: string; signal: AbortSignal; timeoutMs: number; maxStdoutBytes: number }>,
  ): Promise<Readonly<{ code: number; stdout: string }>>;
}
```

Save invokes `/usr/bin/security add-generic-password -a <hashed-account> -s dev.kaji.oauth.gmail -U -w`, with `-w` last and record JSON supplied through stdin. Load invokes `find-generic-password ... -w` and caps stdout at 16 KiB. Delete invokes `delete-generic-password`. Never pass raw principal/token JSON as an argument, use `shell: true`, inherit stdio, or include stdout in an error.

- [ ] **Step 3: Add PKCE and optional desktop client secret**

```text
code_verifier  = base64url(random 64 bytes), no padding
code_challenge = base64url(SHA-256(ASCII(code_verifier))), no padding
method         = S256
redirect       = http://127.0.0.1:<ephemeral-port>/oauth/callback
authorization  = https://accounts.google.com/o/oauth2/v2/auth
token          = https://oauth2.googleapis.com/token
revocation     = https://oauth2.googleapis.com/revoke
consent        = explicit connect() only
token request  = code + verifier + client_id + redirect_uri + grant_type
client_secret  = included only when configured
```

Use a 5-minute callback deadline and 30-second, 64 KiB token/revocation request bounds. Validate `state` with constant-time equality. Do not render provider error descriptions; map only the documented error code.

- [ ] **Step 4: Implement keyed refresh single-flight**

The in-flight map key is the validated principal ID. Remove the entry in `finally` only if it still points at the same promise/task. The shared refresh owns a 30-second operation timeout independent of any one waiter and tracks active waiter count. Each `access_token(context)` waiter races its own cancellation/deadline and may detach without cancelling the shared operation; abort the shared request only when its operation timeout fires or every waiter has detached. A later shorter-deadline waiter never shortens an already-dispatched refresh. Persist a successful refresh atomically, preserving an omitted refresh token/scopes as described above.

Use one per-principal auth generation/operation gate across `connect`, `access_token`, and `disconnect`, not a refresh-only map. `disconnect` advances the generation and marks token use blocked before remote I/O, prevents new refreshes, cancels/awaits the captured in-flight operation, and writes `revocation_pending` or deletes only in its current generation. Refresh/connect capture the generation and may persist only while it is unchanged and `active`. Deterministic races pause at token response, refresh save, revoke response, pending-state save, and delete; none may resurrect a token or overwrite a later disconnect state.

- [ ] **Step 5: Run OAuth/security tests**

```bash
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync pytest kaji/sdk/tests/test_integrations_oauth.py kaji/sdk/tests/test_integration_keychain.py kaji/sdk/tests/test_release_security.py -q
cd kaji/ts && bun run test -- tests/oauth.test.ts tests/keychain.test.ts tests/release-security.test.ts
```

Expected: PASS without real browser, network, clock sleeps, or Keychain writes.

- [ ] **Step 6: GitButler checkpoint**

Commit only Task 5 changes with `feat(kaji): harden Google OAuth and Keychain storage`.

### Task 6: Add Explicit Connect/Disconnect CLI and Auth Setup Guidance

**Files:**

- Create `kaji/sdk/src/cli/connect.py` and `disconnect.py`.
- Create `kaji/sdk/src/cli/__main__.py` so `python -m kaji.cli` unambiguously selects the Python SDK binary.
- Modify `kaji/sdk/src/cli/__init__.py` command registration.
- Create `kaji/ts/src/cli/connect.ts` and `disconnect.ts`.
- Modify `kaji/ts/src/cli/index.ts:33-62`.
- Modify both `--help` banners to print the owning package and exact version.
- Modify `kaji/sdk/src/cli/add.py:61-77`.
- Modify `kaji/ts/src/cli/add.ts:215-216`.
- Modify Python `list_integrations.py` and TypeScript `list.ts` for identical structured discovery.
- Create `kaji/sdk/tests/cli/test_connect.py`.
- Create `kaji/ts/tests/cli-connect.test.ts`.
- Extend both add/list CLI tests.

**CLI contract:**

```text
python -m kaji.cli connect gmail --principal <stable-host-principal-id>
python -m kaji.cli disconnect gmail --principal <stable-host-principal-id>
bunx --package @kaji/sdk kaji connect gmail --principal <stable-host-principal-id>
bunx --package @kaji/sdk kaji disconnect gmail --principal <stable-host-principal-id> [--force-local]
```

- [ ] **Step 1: Add failing parser and side-effect-order tests**

Assert missing name/principal, unknown integration, non-OAuth integration, unsupported provider, invalid principal, missing client ID env for `connect`, missing/non-executable `/usr/bin/security`, non-macOS beta construction in either runtime, and cancellation return code 1 with problem + cause + exact fix. Assert `disconnect` does not require/read client ID or secret, can load a pending record, and validation completes before browser, callback listener, Keychain, or network access in the action-specific order. The legacy Python `oauth-keyring` extra is not a beta prerequisite or documented production path.

- [ ] **Step 2: Implement one manifest-driven OAuth command path**

`connect` loads the registry manifest, requires `auth.kind == oauth` and `provider == google`, reads the named client ID/optional secret environment variables, creates service `dev.kaji.oauth.<manifest.name>`, and calls `GoogleOAuthClient.connect`. `disconnect` derives only the hard-coded provider revocation endpoint plus manifest service identity, loads the hashed-account record without client metadata, and calls `disconnect`. Confirmed revocation deletes the record. Ambiguous revocation saves `revocation_pending`, blocks token use, returns exit 1, and prints retry/manual Google-account guidance. `--force-local` deletes that record only after an explicit operator command and warns that remote access may remain until manually revoked.

Every integration guide uses a package-qualified command because Python `kaji`, embedded `@kaji/sdk`, and standalone `@kaji/cli` install different binaries with the same name. Use `python -m kaji.cli ...` for Python and `bunx --package @kaji/sdk kaji ...` (or a project script pinned to `@kaji/sdk`) for TypeScript. Bare `kaji` appears only after an explicit `--help` ownership check. Package smoke installs conflicting binaries and proves the qualified path still selects the intended SDK/version.

Successful output is bounded and secret-free:

```text
Connected gmail for the requested principal.
Stored refresh credentials in macOS Keychain service dev.kaji.oauth.gmail.
```

Missing setup output is actionable:

```text
INTEGRATION_AUTH_REQUIRED: GOOGLE_CLIENT_ID is not set.
Create a Google Desktop OAuth client, load GOOGLE_CLIENT_ID, then rerun the package-qualified connect command shown above.
```

- [ ] **Step 3: Make `kaji add` print exact next steps in both runtimes**

Gmail output includes both credential environment names, scopes, and the package-qualified connect command; the legacy keyring extra is not advertised. GitHub output includes fine-grained PAT guidance. TypeScript gains parity with Python instead of stopping at `Wrote N file(s)`.

Both `list-integrations` commands accept identical `--json` and human modes. The closed JSON rows include name, version, stability, runtimes, auth kind/provider, experimental opt-in requirement, and package-qualified next command; no env value or secret is read. Canonical ABI schemas carry every optional tool default listed in Tasks 4/8, and executable inspectors plus docs must match those defaults exactly.

- [ ] **Step 4: Run focused CLI tests**

```bash
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync pytest kaji/sdk/tests/cli/test_add.py kaji/sdk/tests/cli/test_connect.py -q
cd kaji/ts && bun run test -- tests/cli-add.test.ts tests/cli-connect.test.ts
```

- [ ] **Step 5: GitButler checkpoint**

Commit only Task 6 changes with `feat(kaji): add explicit integration auth commands`.

### Task 7: Implement Canonical Gmail REST and MIME Clients in Both Runtimes

**Files:**

- Create `kaji/contracts/integrations/gmail-api-conformance-v1.json`.
- Create `kaji/sdk/src/integrations/registry/gmail/client.py` and `mime.py`.
- Create `kaji/ts/registry/gmail/client.ts` and `mime.ts`.
- Create `kaji/sdk/tests/test_gmail_client.py` and `test_gmail_mime.py`.
- Create `kaji/ts/tests/gmail-client.test.ts` and `gmail-mime.test.ts`.

**Interfaces:**

```python
class GmailClient:
    def __init__(
        self,
        *,
        access_token_for: Callable[[ToolExecutionContext], Awaitable[str]],
        allowed_recipients: Collection[str],
        http: FixedOriginClient,
    ) -> None: ...

    async def search_messages(self, context: ToolExecutionContext, query: str, max_results: int, page_token: str | None) -> dict[str, object]: ...
    async def get_thread(self, context: ToolExecutionContext, thread_id: str, max_messages: int) -> dict[str, object]: ...
    async def list_labels(self, context: ToolExecutionContext) -> dict[str, object]: ...
    async def create_draft(self, context: ToolExecutionContext, to: str, subject: str, body: str) -> dict[str, object]: ...
    async def send_draft(self, context: ToolExecutionContext, draft_id: str, draft_key: str, to: str, subject: str, body: str) -> dict[str, object]: ...
```

- [ ] **Step 1: Define shared Gmail provider fixtures**

Cover search/list pagination, empty mailbox, labels, metadata thread, ten-message cap, nested multipart, base64url padding variants, HTML-only fallback to bounded text, attachment metadata, malformed MIME, oversized body, 401, 403 insufficient scopes, 404, 429, 5xx, cancellation, create success, send success, and ambiguous POST failure.

- [ ] **Step 2: Implement one canonical MIME wire algorithm and parser**

Do not delegate outbound serialization to Python `EmailMessage` or a runtime mail library: their folding and transfer-encoding choices may differ. Both runtimes implement and fixture-test this byte-for-byte algorithm:

1. Before runtime approval, the closed tool schema accepts one canonical ASCII dot-atom addr-spec: no display name, comments, quoted local part, surrounding whitespace, control characters, or CR/LF; the domain is already lowercase and the local part is preserved exactly. The immutable recipient allowlist snapshots the same representation.
2. Subject/body are never trimmed or Unicode-normalized. Subject rejects CR/LF and is bounded to 998 Unicode scalar values and 4,096 UTF-8 bytes; body is bounded to 32,768 UTF-8 bytes.
3. Encode every subject, including ASCII, as RFC 2047 `=?UTF-8?B?...?=` words. Split only at Unicode scalar boundaries into chunks of at most 45 UTF-8 bytes; emit the first after `Subject: ` and every later word on its own single-space continuation line. This keeps each encoded word at or below 72 ASCII bytes and makes folding deterministic.
4. Emit headers in this exact case/order with CRLF: `To`, `Subject`, `MIME-Version: 1.0`, `Content-Type: text/plain; charset=UTF-8`, `Content-Transfer-Encoding: base64`, then `X-Kaji-Draft-Key` when creating/sending a draft. Emit one empty CRLF separator. Base64-encode the exact UTF-8 body, wrap at 76 ASCII characters, terminate non-empty bodies with CRLF, and emit no CC/BCC/attachments, Date, or Message-ID.
5. Base64url-encode the resulting message without padding for the Gmail API. Shared fixtures include ASCII, multi-byte Unicode at every chunk boundary, empty/max bodies, and header-injection attempts; Python and TypeScript must produce the identical raw bytes and request JSON.

`create_draft` derives:

```text
draft_key = lowercase_hex(SHA-256(UTF-8(context.idempotency_key)))
X-Kaji-Draft-Key: <64 hex characters>
```

Inbound parsing returns only From/To/Date/Subject, a bounded text body, message ID/thread ID, and attachment `{filename, mime_type, size}` metadata. It never returns attachment bytes. For HTML-only mail, both runtimes use the same bounded tokenizer contract: discard `head`/`script`/`style` elements and contents, map `br` and closing block elements to LF, decode the five XML entities plus bounded numeric entities, remove remaining tags, normalize CRLF/CR to LF, collapse ASCII spaces/tabs within a line, trim only the synthesized fallback, and then cap the UTF-8 result. The conformance fixture, not a provider/library-specific DOM serializer, is canonical. Bound MIME depth to 16, parts to 128, tokenizer input to 64 KiB, messages per thread to 10, each text body to 16 KiB, and the combined tool result below 64 KiB.

- [ ] **Step 3: Make thread retrieval bounded rather than one unbounded payload**

Call `threads.get?format=metadata` once, select at most `max_messages` IDs, then fetch those messages with a concurrency cap of four and preserve original order. Use `fields` to exclude attachment bodies. Abort remaining reads on cancellation or the first fatal provider error.

- [ ] **Step 4: Make send approval arguments verifiable**

Immediately after approval, fetch the draft only to verify that the ID exists for the authenticated account and its `X-Kaji-Draft-Key` matches the approved argument. Rebuild MIME from the exact already-approved canonical `to`, `subject`, and `body`, then call `drafts.send` once with both the draft ID and that exact `message.raw`; Gmail replaces any concurrently edited draft message in the same send operation. Reject ownership/key mismatch before send. A deterministic race test replaces the stored draft after pre-read and asserts the outgoing send body still equals the approved MIME, with empty CC/BCC and no attachments.

- [ ] **Step 5: Run cross-runtime client/MIME tests**

```bash
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync pytest kaji/sdk/tests/test_gmail_client.py kaji/sdk/tests/test_gmail_mime.py -q
cd kaji/ts && bun run test -- tests/gmail-client.test.ts tests/gmail-mime.test.ts
```

Expected: fixture-equivalent normalized output and no provider content in error snapshots.

- [ ] **Step 6: GitButler checkpoint**

Commit only Task 7 changes with `feat(kaji): add bounded Gmail clients and MIME handling`.

### Task 8: Expose Gmail Tools, Registry, Packaging, and Approval Semantics

**Files:**

- Create `kaji/sdk/src/integrations/registry/gmail/__init__.py`, `gmail.py`, and `manifest.json`.
- Create `kaji/contracts/integrations/gmail-tool-abi-v1.json` and add Gmail to `abi-index-v1.json`.
- Create synchronized `gmail.ts`, `client.ts`, and `mime.ts` copies under the Python registry.
- Create copied Gmail no-network test helpers/templates and deterministic provider fixtures for Python and TypeScript.
- Create `kaji/ts/registry/gmail/index.ts` and `manifest.json`.
- Modify both registry indexes and Python package mappings.
- Create `kaji/sdk/tests/test_gmail_registry.py`.
- Create `kaji/ts/tests/gmail-registry.test.ts`.
- Extend CLI, manifest, package-boundary, release-smoke, archive, npm-package, and stability tests.

**Tool ABI:**

| Tool | Required arguments | Optional bounded arguments | Risk | Parallel | Timeout |
|---|---|---|---|---|---|
| `search_messages` | `query` (1-512) | `max_results` 1-20 default 10; `page_token` 1-2048 omitted initially | read | true | 10,000 ms |
| `get_thread` | `thread_id` (1-256) | `max_messages` 1-10 default 10 | read | true | 15,000 ms |
| `list_labels` | none | none; strict empty object | read | true | 10,000 ms |
| `create_draft` | `to`, `subject`, `body` | none | write | false | 15,000 ms |
| `send_draft` | `draft_id`, `draft_key`, `to`, `subject`, `body` (<=32,768 UTF-8 bytes) | none | external_effect | false | 15,000 ms |

- [ ] **Step 1: Write failing full-runtime approval tests**

```ts
it("rejects send before auth or transport", async () => {
  const accessToken = vi.fn(async () => { throw new Error("token read"); });
  const request = vi.fn(async () => { throw new Error("transport called"); });
  const runtime = runtimeWithGmail({ approval: false, accessToken, request });
  const result = await runtime.runTurn(sendDraftCall(VALID_SEND_ARGS));
  expect(result.failure?.error_code).toBe("TOOL_APPROVAL_REJECTED");
  expect(accessToken).not.toHaveBeenCalled();
  expect(request).not.toHaveBeenCalled();
});
```

Also test missing principal, disconnected principal, scope drift, concurrent reads sharing refresh, different-principal isolation, recipient allowlist, non-canonical recipient forms rejected before approval, draft ownership/key mismatch, a concurrent draft replacement, deterministic exact MIME bytes, and mutation failure outcomes. Approval receives the complete canonical payload; no handler normalization changes it afterward.

- [ ] **Step 2: Implement scoped integration factories and inspectors**

```python
def create_gmail_integration(
    *,
    access_token_for: Callable[[ToolExecutionContext], Awaitable[str]],
    allowed_recipients: Collection[str],
) -> GmailIntegration:
    return _create_gmail_integration_for_test(
        access_token_for=access_token_for,
        allowed_recipients=allowed_recipients,
        http=FixedOriginClient.for_gmail(),
    )


def _create_gmail_integration_for_test(
    *,
    access_token_for: Callable[[ToolExecutionContext], Awaitable[str]],
    allowed_recipients: Collection[str],
    http: FixedOriginClient,
) -> GmailIntegration:
    recipients = frozenset(validate_canonical_recipient(value) for value in allowed_recipients)
    client = GmailClient(
        access_token_for=access_token_for,
        allowed_recipients=recipients,
        http=http,
    )
    return GmailIntegration(client)
```

No default global recipient list exists. A host must supply at least one recipient; construction validates and snapshots it so later caller mutation cannot widen authorization. Docs use the authenticated test account only.

- [ ] **Step 3: Declare least-privilege manifest auth**

```json
{
  "kind": "oauth",
  "provider": "google",
  "clientIdEnv": "GOOGLE_CLIENT_ID",
  "clientSecretEnv": "GOOGLE_CLIENT_SECRET",
  "scopes": [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose"
  ],
  "docs": "https://developers.google.com/workspace/gmail/api/auth/scopes"
}
```

The documentation must state both are restricted scopes and that BYO test-mode/client verification obligations belong to the application owner. Do not request `gmail.modify`, `gmail.send`, or full-mail scope.

- [ ] **Step 4: Register as experimental and synchronize source/ABI**

Both indexes declare both runtimes. Python `kaji add gmail` copies Python and synchronized TypeScript sources; TypeScript copies only `.ts`. Each add also writes the closed `.kaji-integration-provenance.json` sidecar defined in Task 1. Neither succeeds without `--allow-experimental`. The ABI check constructs inspectors without Keychain or network activity.

- [ ] **Step 5: Run focused tool/package gates**

```bash
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync pytest kaji/sdk/tests/test_gmail_registry.py kaji/sdk/tests/test_integrations_oauth.py kaji/sdk/tests/test_manifest_registry.py kaji/sdk/tests/cli/test_add.py kaji/sdk/tests/test_package_boundaries.py -q
cd kaji/ts && bun run test -- tests/gmail-registry.test.ts tests/oauth.test.ts tests/keychain.test.ts tests/manifest-validate.test.ts tests/cli-add.test.ts tests/integration-abi.test.ts
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/scripts/sync_integration_contracts.py --check
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/scripts/check_integration_abi.py --explain
```

- [ ] **Step 6: GitButler checkpoint**

Commit only Task 8 changes with `feat(kaji): add experimental Gmail tools`.

### Task 9: Add Cross-Runtime Structural, Security, and Deterministic Conformance Gates

**Files:**

- Create or modify ast-grep rules under `tools/ast-grep/rules/` for registry network/process boundaries.
- Add paired positive/negative fixtures under `tools/ast-grep/fixtures/`.
- Modify `tools/ast-grep/expected-rules.txt` and the repository audit command.
- Create `kaji/scripts/offline_gate.py`, a Python pytest autouse socket/DNS guard, and `kaji/ts/tests/offline-setup.ts`; wire them into `beta_release_check.py`, Vitest, and beta workflow contract tests.
- Extend both SDK security, conformance, docs-contract, API-parity, package, and full-runtime integration tests.
- Modify `kaji/ts/src/tools/execution.ts` idempotency transition and add Python/TypeScript parity tests for failed/unknown/completed claim reuse.
- Modify `kaji/sdk/src/infra/observability/protocols.py`, `kaji/sdk/src/runtime/tools/execution.py`, `kaji/sdk/src/runtime/agents/runtime.py`, `kaji/ts/src/observability.ts`, `kaji/ts/src/tools/execution.ts`, and `kaji/ts/src/runtime/runtime.ts` to remove `principal.id` from both tool- and turn-span vocabulary/emission; extend observability tests accordingly.
- Create `kaji/benchmarks/integration-budgets.json`, `kaji/scripts/integration_benchmark.py`, `kaji/ts/scripts/integration-benchmark.ts`, and deterministic benchmark tests in both SDKs.
- Modify `kaji/scripts/beta_release_check.py`, `.github/workflows/kaji.beta-pr.yml`, and workflow contract tests so `integration_benchmark.py --mode quick` is a pre-merge and offline-release gate, not a manual-only command.
- Modify `docs/kaji/api-parity.md` generated/checked stable and experimental surfaces.

- [ ] **Step 1: Add failing structural fixtures**

Rules must fail on:

- direct `fetch()` in any `kaji/ts/registry/**` source;
- `exec`, `execSync`, `spawn` with `shell: true`, or dynamic command strings in registry/auth source;
- module-top browser, callback listener, Keychain, environment-token, or network access;
- public GitHub/Gmail/OAuth production factories accepting `origin`, `baseUrl`, endpoint URLs, or injected clients; ambient-proxy enablement in provider clients;
- copied TypeScript registry source importing a private/root-unexported fixed-origin implementation instead of the provider-fixed `@kaji/sdk/integrations` subpath;
- `external_effect` tools marked parallel-safe;
- `send_draft`, `create_issue`, or `add_comment` declared with any risk other than `external_effect`, or `send_draft` omitting the canonical body from its closed argument schema;
- unbounded `response.text()`, `response.json()`, `read()`, or `aread()` in the new fixed-origin clients.

Positive fixtures prove non-exported internal injected transports, copied scripted no-network test helpers that accept outcomes but no origin/fetch, argument-array `/usr/bin/security`, provider-specific production constructors, side-effect-free inspectors, and bounded readers remain allowed.

Pin named rules rather than one broad matcher: `kaji-registry-no-direct-fetch`, `kaji-auth-no-shell-process`, `kaji-public-factory-no-origin-override`, `kaji-no-module-secret-read`, `kaji-external-effect-not-parallel`, `kaji-fixed-origin-no-unbounded-read`, and `kaji-copied-imports-public-subpath`. Use AST field/ancestor relationships so test-only relative factories are allowed only under test files and module-top calls are distinguished from function-body reads. Representative TypeScript fixture/rule shape:

```yaml
id: kaji-registry-no-direct-fetch
language: TypeScript
severity: error
files:
  - "kaji/ts/registry/**/*.ts"
  - "kaji/sdk/src/integrations/registry/**/*.ts"
rule:
  pattern: fetch($$$ARGS)
message: copied registry code must use the provider-fixed bounded requester
```

Each rule gets at least one violating fixture and one nearest-safe fixture. `tools/ast-grep/expected-rules.txt` must name the complete pinned set, and the audit fails if a rule, positive fixture, or negative fixture is missing—not merely when the current source happens to scan clean.

- [ ] **Step 2: Add hostile cross-runtime cases**

Consume each canonical API fixture from both runtimes and compare a normalized JSON record. Add fuzz/property rows for empty strings, Unicode, CR/LF, JSON-safe numeric boundaries, extra properties, over-limit lengths, encoded traversal, GitHub `repo:`/`org:`/`user:` query qualifiers, mismatched result repositories, caller mutation of repository/recipient collections, cancellation at every await, and concurrent principal/session calls. Seed randomness and print only the seed on failure.

- [ ] **Step 3: Prove failure outcomes and redaction through the real runtime**

For every mutation, cover approval rejection, provider-confirmed pre-effect rejection, timeout before handler start, cancellation before dispatch, connection loss after dispatch, and success-event persistence/replay. Assert:

```text
approval reject/pre-dispatch auth failure -> outcome=not_started or failed, no network
provider-confirmed no-effect response      -> outcome=failed, retryable only when safe
post-dispatch timeout/reset                -> outcome=unknown, retryable=false, tombstone retained
success                                    -> one completed event, replay returns same bounded DTO
```

Normalize idempotency-ledger transitions across runtimes: every certified `outcome=failed` releases the claim after persisting the failure, regardless of the advisory `retryable` flag; only `outcome=unknown` retains the tombstone, and success retains the completed result. Update the TypeScript execution condition that currently requires `failed && retryable`, and add parity tests that make a second claim after permanent auth/policy failure, transient read failure, unknown mutation failure, and success.

Treat the explicit CLI `--principal` value as an operator-supplied pseudonymous non-secret: it necessarily exists in that top-level CLI argv, but must never be echoed into turn/tool span attributes, CLI output, error text, logs, or retained evidence. Assert the raw principal never reaches any Keychain/helper subprocess argument; those receive only the hashed account. Correlation continues through existing trace/request/session/tool-call IDs.

- [ ] **Step 3.5: Make performance and observability claims executable**

Add closed metrics `kaji.integration.auth_ms` and `kaji.integration.request_ms` with only `integration=github|gmail`, `operation=read|mutation|token`, and `outcome=success|error|cancelled`; add spans `kaji.integration.auth` and `kaji.integration.request` with closed attributes `integration.name`, `integration.operation`, and `http.status_family`. Never add principal, repository, path, query, recipient, subject, body, token, or provider object ID. Both observability implementations reject unknown names/labels/attributes/values and have parity tests.

`integration_benchmark.py` orchestrates Python and TypeScript no-network cases using injected deterministic transports/clocks: fixed-origin preflight, 1 MiB cap rejection, GitHub DTO normalization at max row/field bounds, Gmail MIME encode/decode at max bounds, in-memory Keychain-process result parsing, and same-principal refresh single-flight. Compare results to `integration-budgets.json`, record machine fingerprint/sample distribution, and fail the exact local-work budgets in this plan. Benchmark output contains counts/durations only. Run:

```bash
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/scripts/integration_benchmark.py --mode quick
```

Tests use an injected clock for deterministic boundary behavior. Protected/calibration runs use the identical case corpus and exact artifact environment: 20 warmups, then three batches of 200 measured monotonic samples per runtime/case. Compute p99 by nearest rank `ceil(0.99 * 200)` independently per batch; every batch p99 must meet the budget. Reject a noisy case when p99 spread exceeds both 25% of the three-batch median and 2 ms; never average away a failing batch. Store raw samples in a separate bounded artifact, put its SHA-256 plus batch p50/p95/p99/max in the <=32-KiB evidence summary, and test the estimator at rank/variance boundaries. Task 11 rehearses and Task 13 runs protected/final with a recognized runner fingerprint.

Add the quick integration benchmark to `beta_release_check.py` common gates and `.github/workflows/kaji.beta-pr.yml` immediately after the existing core quick benchmark. Workflow contract tests assert both commands and their budgets remain present; either regression blocks merge even before provider credentials exist.

- [ ] **Step 4: Run the complete deterministic gate**

`offline_gate.py` constructs an explicit non-secret environment allowlist and deletes every OpenAI/Anthropic/GitHub/Google/Gmail credential plus proxy variables before launching tests. Python's autouse guard rejects real `socket.connect`, DNS resolution, and unstubbed HTTP transports; TypeScript's Vitest setup rejects global `fetch` plus real `node:net`, `node:dns`, `node:http`, and `node:https` dispatch. Injected in-memory transports remain usable. Guard self-tests attempt loopback and public endpoints and must fail before I/O. Use the same launcher from local Task 9, both `beta_release_check.py` modes, `.github/workflows/kaji.beta-pr.yml`, and protected offline rehearsal; a prose claim or empty credential set alone is insufficient.

```bash
bun run audit:ast-grep
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/scripts/integration_benchmark.py --mode quick
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/scripts/check_sdk_parity.py
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/scripts/offline_gate.py -- /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync pytest -m "not integration"
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/scripts/offline_gate.py -- /opt/homebrew/bin/bun --cwd kaji/ts run test
cd kaji/ts && bun run typecheck && bun run typecheck:registry && bun run validate:registry && bun run check:integrations && bun run lint && bun run format:check
```

Expected: all offline suites pass with network disabled and no credentials present.

- [ ] **Step 5: GitButler checkpoint**

Commit only Task 9 changes with `test(kaji): enforce integration safety and parity`.

### Task 10: Implement Exact-Artifact and Release-Evidence Tooling

**Files:**

- Create `kaji/contracts/release/integration-proof-v1.schema.json`, `gmail-reset-attestation-v1.schema.json`, `integration-docs-smoke-v1.schema.json`, `integration-promotion-v1.schema.json`, and `release-readiness-v1.schema.json`.
- Create `kaji/scripts/integration_proof.py`.
- Create `kaji/scripts/proof_cleanup.py`; this proof-only module is never packaged or exported.
- Create `kaji/scripts/repro_artifacts.py`.
- Create `kaji/scripts/release_readiness.py`.
- Create tracked `kaji/release-toolchain.json` and validate it from local/protected builders plus `verify_release_artifacts.py`.
- Create `kaji/sdk/tests/test_integration_proof.py`.
- Create `kaji/sdk/tests/test_proof_cleanup.py`.
- Create `kaji/sdk/tests/test_repro_artifacts.py`.
- Create `kaji/sdk/tests/test_release_readiness.py`.
- Modify `kaji/scripts/beta_release_check.py` to require deterministic release-build inputs/configurable output roots and to exclude credential-required integration tests in both quick and release modes.
- Create `kaji/sdk/tests/integration/test_github_live.py` and `test_gmail_live.py`.
- Create `kaji/ts/tests/integration/github-live.test.ts` and `gmail-live.test.ts`.
- Modify Python pytest marker configuration plus both TypeScript Vitest configs so default suites exclude `tests/integration/**` and dedicated integration targets include only those files.
- Modify `.gitignore` for `.artifacts/kaji-release/`, `.artifacts/kaji-evidence/`, and `.artifacts/kaji-integration-evidence/` if existing rules are insufficient.
- Modify `kaji/RELEASE_MATRIX.md` with separate GitHub/Gmail gate definitions and pre-freeze candidate-intent sections; final outcomes remain untracked evidence.

- [ ] **Step 0: Implement the fail-closed version preflight**

`release_readiness.py --check-versions` reads the exact Python/npm versions from package metadata, performs bounded unauthenticated lookups against fixed PyPI/npm registry endpoints, and classifies only authoritative not-found as available. Existing version, timeout, rate limit, malformed response, redirect, or registry ambiguity blocks the evidence run. Record status/duration but no registry body.

If either version exists, the eventual executor stops and performs one atomic version roll before building: update Python source/`pyproject.toml`/lock/changelog, TypeScript source/`package.json`/locks/changelog, TTHW schemas/validators, release metadata/verifiers, workflow tags/artifact names/registry URLs, docs, and all exact-version tests. Run an `rg` residual audit for both old version strings, rebuild contract/package copies, and invalidate every prior artifact/evidence digest. Task 10 adds/tests this command; Task 13 invokes it against the final candidate.

```bash
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/scripts/release_readiness.py --check-versions
```

- [ ] **Step 1: Implement two-clone reproducible building**

`repro_artifacts.py` takes an exact clean commit and creates two independent local clones with `--no-local --no-hardlinks`, each detached at that commit. This preserves `.git` for the existing `git rev-parse` provenance checks while excluding dirty/untracked caller files; do not use a plain export and do not mutate the caller's worktree. Run the release artifact builder in each clone with isolated uv/npm/Bun caches and exactly:

```text
SOURCE_DATE_EPOCH=<commit timestamp>
PYTHONHASHSEED=0
TZ=UTC
LC_ALL=C
LANG=C
KAJI_RELEASE_COMMIT=<40-hex commit>
```

Before either build, require the exact tracked toolchain—Python `3.14.6`, Node `24.18.0`, npm `11.16.0`, Bun `1.3.11`, uv `0.11.25`, setuptools `83.0.0`, and editables `0.6`—rather than floating `3.14`/`24` or whatever happens to be on PATH. Both setup actions and local bootstrap read `kaji/release-toolchain.json`; the manifest/receipt record the same complete map, and verification rejects any mismatch. Runtime support matrices still test the wider supported Python/Node lines separately; only release-byte production is single-toolchain.

The builder must not read untracked workspace files or wall-clock time into archives/manifests. Compare the exact five-file set enforced by `verify_release_artifacts.py`—wheel, sdist, npm tarball, `manifest.json`, and `SHA256SUMS`—by relative filename, size, and SHA-256. Any mismatch fails with filename plus hashes only. After equality, atomically copy the first set to `.artifacts/kaji-release/`, make it read-only, and write the receipt outside that exact directory at `.artifacts/kaji-evidence/reproducibility.json`. The receipt binds commit, deterministic variable names, build-tool versions, both artifact-set digests, and the final manifest digest without temp paths or wall-clock fields.

```bash
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/scripts/repro_artifacts.py \
  --commit "$(git rev-parse HEAD)" \
  --output .artifacts/kaji-release \
  --receipt .artifacts/kaji-evidence/reproducibility.json
```

This command is an interface specification in Task 10, not evidence execution. Tests cover changed timestamps/caches, one-byte mismatches, missing/extra files, dirty-source exclusion, detached-clone failure, atomic cleanup, and stable rerun receipts. The final invocation occurs only in Task 13 after every tracked change has been checkpointed.

**Evidence contracts:**

Use one generic closed schema but emit two independently valid documents:

```text
.artifacts/kaji-integration-evidence/github-proof.json
.artifacts/kaji-integration-evidence/gmail-proof.json
```

```json
{
  "schemaVersion": "1.0.0",
  "integration": "github",
  "commit": "40 lowercase hex characters",
  "generatedAt": "bounded RFC 3339 UTC timestamp",
  "runId": "bounded random non-secret identifier",
  "platform": "macos",
  "platformVersion": "recorded non-empty sw_vers product version",
  "architecture": "arm64",
  "manifestSha256": "64 lowercase hex characters",
  "proofs": [
    {
      "runtime": "python",
      "status": "passed",
      "durationMs": 1,
      "assertions": {
        "readBack": true,
        "writeApproval": true,
        "cleanup": true,
        "redacted": true
      }
    },
    {
      "runtime": "typescript",
      "status": "passed",
      "durationMs": 1,
      "assertions": {
        "readBack": true,
        "writeApproval": true,
        "cleanup": true,
        "redacted": true
      }
    }
  ]
}
```

For `integration: "gmail"`, the schema requires the same exact Python/TypeScript rows but replaces each row's assertion object with `readBack`, `draftVerified`, `sendApproval`, `selfRecipient`, `oauthLifecycle`, `eventStoreCleared`, `accountReset`, and `redacted`. Use schema `oneOf` branches so GitHub assertions cannot satisfy Gmail and one runtime cannot satisfy the other. Each document has exact two-runtime uniqueness, positive bounded durations, exact commit/manifest/platform-version/arm64 binding, `additionalProperties: false`, and no free-form provider/user content fields. A Gmail row remains pending until its own OAuth lifecycle, bounded in-memory clearing/process exit, and disposable-account reset/deletion are attested.

`integration-promotion-v1` is generic and machine-readable. It records `phase: candidate|final`, provider, decision `promote|hold`, exact commit/manifest/proof/ABI/source digests, applicable docs-smoke and Gmail-data-approval digests, a pseudonymous reviewer, reviewed-at timestamp, and one closed reason code. Emit `<provider>-candidate-promotion.json` before a registry-marker edit and `<provider>-promotion.json` after final exact-commit proof. Tracked `RELEASE_MATRIX.md` mirrors gate definitions and candidate marker intent only; it never records post-freeze final outcomes/digests. Those live solely in untracked machine-readable promotion/readiness/integration-status/publication artifacts, avoiding an evidence-invalidating documentation commit.

`integration-docs-smoke-v1` emits one document per provider and phase with exact commit/manifest/artifact digests, unique Python/TypeScript participants, clean-install/no-source booleans, artifact-install-to-first-safe-result duration, total provider-console-to-safe-result duration, success, separately measured credential-prerequisite duration, closed friction/remediation codes, and no provider identifiers/content/free text. Candidate promotion references candidate smoke; final promotion/readiness/protected ingestion require a fresh final-artifact document. It is explicitly a release docs-usability gate, not an adoption metric.

`release-readiness-v1` is immutable and pre-publication only. `engineeringStatus` is `beta_ready|blocked`; `publicationStatus` is `eligible|blocked`; `publicationBlock` is `null|ci_minutes|runner_unavailable|evidence_invalid`. It can never contain `published`; the existing post-registry `publication-status.json` remains the sole publication outcome.

- [ ] **Step 2: Write validator tests before the runner**

Reject an unknown integration, non-macOS or non-arm64 evidence, missing platform version/generatedAt/runId, missing/duplicate runtime rows, cross-provider assertion fields, `sk-`/Bearer/token-looking strings anywhere, email addresses, repository names, subjects, bodies, headers, future timestamps, wrong commit, wrong manifest hash, skipped/pending proofs, missing row-local cleanup/reset attestations, and zero/negative durations. Promotion/readiness validators additionally reject Markdown-only approvals, stale decision phase/digests, extra experimental-provider proof, and a `published` readiness state. The validator error reports only a JSON Pointer and rule name.

- [ ] **Step 3: Implement the GitHub live proofs**

Required environment:

```text
GITHUB_TOKEN             fine-grained PAT; one private fixture repository only
KAJI_GITHUB_TEST_REPO    owner/name; Contents read + Issues read/write
```

Each runtime must:

1. run a proof-only reconciliation sweep for stale `kaji-beta-<commit-prefix>-<runtime>` fixtures, then search/list/read the fixture repository;
2. run `create_issue` through a real approval handler using nonce `kaji-beta-<commit-prefix>-<runtime>`;
3. read the issue back;
4. run `add_comment` through approval and read it back;
5. return created numeric IDs only to the parent process, which cleans outside the tool surface through `proof_cleanup.py`; that module alone constructs a fixed-origin requester permitting PATCH/DELETE for the created/reconciled fixture IDs, and it is never exported, copied, registered, packaged, or available as a tool;
6. retain numeric IDs and durations in process memory only, then emit booleans/counts to evidence.

Missing credentials are a hard failure, never a skip. `proof_cleanup.py` owns startup reconciliation, close/delete, readback verification, idempotency, and tests; the normal integration requester remains GET/POST-only. Cleanup runs in `finally`; SIGINT/SIGTERM trigger cancellation followed by the bounded cleanup stack. An uncatchable crash is rescued by the next startup reconciliation sweep. Evidence fails unless deletion/closure is read back and verified. The token value and fixture repository never reach retained evidence.

- [ ] **Step 4: Implement the Gmail live proofs**

Required setup:

```text
GOOGLE_CLIENT_ID                Google Desktop OAuth client ID
GOOGLE_CLIENT_SECRET            optional when the registered desktop client supplies one
KAJI_GMAIL_PY_TEST_PRINCIPAL    Python cell pseudonymous Keychain account
KAJI_GMAIL_PY_TEST_ACCOUNT      Python cell disposable account; read only by the process
KAJI_GMAIL_TS_TEST_PRINCIPAL    TypeScript cell pseudonymous Keychain account
KAJI_GMAIL_TS_TEST_ACCOUNT      TypeScript cell disposable account; read only by the process
```

Each runtime independently runs `kaji connect gmail --principal <its-principal>`, searches its dedicated mailbox, lists labels, creates one synthetic plain-text draft to the same account, verifies ownership/key, approves the canonical send arguments, sends the deterministically rebuilt approved MIME atomically with the draft ID, retrieves the thread, and runs `kaji disconnect gmail --principal <its-principal>`. Each cell owns a fresh bounded in-memory event store, verifies no filesystem persistence path exists, clears all sessions/events in `finally`, and exits before `eventStoreCleared` may be true.

Because `gmail.readonly` plus `gmail.compose` cannot remove sent mail, use an explicit two-phase protocol. `--phase run` atomically writes redacted `gmail-pending.json` containing run ID, exact runtime/commit/manifest/artifact bindings, expiry, pending-receipt digest, and one random non-secret attestation nonce per runtime—never an address, subject, body, draft/thread ID, principal, token, or header. After child exit, the owner resets/deletes both disposable accounts outside Kaji and supplies exactly two closed `gmail-reset-attestation-v1` documents with run ID, runtime, commit, manifest/pending digests, matching nonce, `accountReset: true`, pseudonymous attester, and timestamp. `--phase finalize` rejects replay, duplicate runtime, expiry, or wrong run/cell/commit/manifest before producing `gmail-proof.json`. Machine validation proves binding; the reviewer is responsible for the truth of the external reset assertion.

- [ ] **Step 5: Orchestrate with bounded existing process infrastructure**

`integration_proof.py --integration github|gmail` uses `process_runner.py` argument arrays and budgets, runs only the selected provider's two runtime cells sequentially, scrubs child environments to an explicit allowlist, and captures bounded stdout/stderr. Each cell runs outside the checkout in a fresh environment that installs the exact manifest-selected wheel or npm tarball, invokes the installed CLI/public package and copied provider source, and proves loaded version/path/artifact digest. Clear `PYTHONPATH`, `NODE_PATH`, source aliases, and checkout cwd; any SDK resolution into the source tree fails. The orchestrator/validator may run from source, but provider runtime behavior may not.

Each child registers one idempotent cleanup stack for network fixtures, callback listener, refresh task, Keychain state, and in-memory event store; the orchestrator gives it a bounded termination grace and treats unverifiable cleanup as failure. The Gmail run holds only its document in a pending redacted state until two bound reset attestations finalize it. It writes a selected final proof through temporary file + atomic rename and validates before printing PASS:

```text
.artifacts/kaji-integration-evidence/<integration>-proof.json
```

- [ ] **Step 6: Test the runners without collecting release evidence**

```bash
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync pytest \
  kaji/sdk/tests/test_integration_proof.py \
  kaji/sdk/tests/test_proof_cleanup.py \
  kaji/sdk/tests/test_repro_artifacts.py \
  kaji/sdk/tests/test_release_readiness.py -q
cd kaji/ts && bun run test && bun run typecheck
```

Use fixture artifacts/transports only. Prove wrong wheel/tarball, source-tree import, package-manager timeout, attestation replay/duplication/wrong cell, cleanup failure, default-test inclusion, and cross-provider evidence all fail. Do not use GitHub/Gmail credentials or write release evidence in Task 10.

- [ ] **Step 7: Define the later independent review protocol**

Task 13 reviews each candidate/final proof separately: commit equals final HEAD for final proof, manifest digest matches the frozen set, installed-package assertions pass, platform is arm64 macOS, both runtime rows pass, and raw files contain no provider/user content. Gmail also requires both OAuth lifecycles, store clears/child exits, and bound reset attestations. Candidate review may authorize a marker edit; only a final machine-readable decision can satisfy release readiness.

- [ ] **Step 8: GitButler checkpoint**

Commit only code/schema/tests/docs from Task 10 with `test(kaji): add exact-artifact release evidence gates`. Do not commit generated `.artifacts` evidence. This checkpoint must precede every candidate/final artifact build and live call.

### Task 11: Bind macOS Evidence Contracts and Prepare Performance/Provider Gates

**Files:**

- Modify `kaji/contracts/release/tthw-evidence-v1.schema.json:145-150`.
- Modify `kaji/scripts/validate_tthw_evidence.py:89-96`.
- Modify `kaji/sdk/tests/test_tthw_evidence.py`.
- Modify `kaji/RELEASE_MATRIX.md:113-127`.
- Modify `docs/kaji/releasing.md:164-181` and `docs/kaji/testing.md:30-40`.
- Modify `kaji/scripts/beta_benchmark_gate.py`, `integration_benchmark.py`, `run_beta_soak.py`, and `live_provider_proof.py` plus tests so final modes consume/install an explicit frozen-artifact directory.
- Modify `kaji/ts/benchmarks/runtime-benchmark.ts` and `runtime-soak.ts` so protected runs import public `@kaji/sdk` from a temporary consumer rather than checkout-only `@/*` aliases.
- Modify `live_provider_proof.py` child environment handling to use an explicit allowlist; this is a verified secret-isolation defect, not feature expansion.

- [ ] **Step 1: Change the cohort contract atomically**

```json
"os": { "const": "macos" }
```

```python
if any(run["os"] != "macos" for run in runs):
    fail("/humanRuns", "every beta TTHW run must use macOS")
```

Keep exactly five distinct pseudonymous users and coverage of Python, npm, and Bun. Require recorded macOS version and arm64 architecture. The platform reduction does not reduce toolchain-path coverage, exact-artifact binding, clean/no-source attestations, timing thresholds, bounded redacted confusion/remediation codes, or 30-day follow-up.

- [ ] **Step 2: Make final evidence runners consume installed artifacts**

Add `--artifacts-dir` consume-only mode to protected benchmark, integration benchmark, soak, and keyed-provider proof. Each creates clean Python/TypeScript environments, installs the manifest-selected wheel/tarball, verifies resolved path/version/digest, and exercises shipped runtime code. The TypeScript benchmark/soak case files must replace `@/*` checkout aliases with public `@kaji/sdk` imports when invoked in protected mode and run from a generated temp consumer whose `node_modules/@kaji/sdk` is the exact tarball. Source-side orchestration and benchmark case definitions may run from the checkout; importing SDK runtime code from it may not. Fail if any resolved SDK module lies outside that consumer's `node_modules` or the Python temp venv. Evidence binds artifact and benchmark-source digests separately. Task 13 uses read-only `verify_release_artifacts.py` before these consumers; never call the mutating `verify_package_metadata.py` on the frozen directory.

- [ ] **Step 3: Rehearse calibration without updating the tracked baseline**

On the one approved pinned arm64 macOS benchmark runner, derive `KAJI_BENCHMARK_RUNNER_IMAGE_DIGEST` from its reviewed immutable runner/bootstrap manifest and use the same non-default digest for calibration, integration benchmarks, and full comparison. Set the exact commit once:

```bash
export KAJI_RELEASE_COMMIT="$(git rev-parse HEAD)"
export KAJI_BENCHMARK_CALIBRATION=1
export KAJI_BENCHMARK_PINNED_RUNNER=1
export KAJI_BENCHMARK_RUNNER_IMAGE_DIGEST='sha256:<approved-runner-manifest-digest>'
```

Do not substitute a host nickname or `local-unpinned`; capture the runner fingerprint in evidence.

```bash
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/scripts/beta_benchmark_gate.py \
  --mode calibrate \
  --output .artifacts/kaji-evidence/benchmark-calibration.json \
  --candidate-baseline .artifacts/kaji-evidence/beta-baseline.candidate.json
```

Review variance, machine fingerprint, sample counts, thresholds, dependency locks, and benchmark-source hash to validate the tooling/budgets. Do **not** replace `kaji/benchmarks/beta-baseline.json` here: Task 13 may still roll versions or edit promotion indexes that participate in the existing source hash. This rehearsal is not final release evidence; Task 13 repeats calibration after the last such edit, checkpoints only the accepted baseline, then freezes artifacts.

- [ ] **Step 4: Define the final 30-minute soak contract**

```bash
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/scripts/run_beta_soak.py --minutes 30 --protected --artifacts-dir .artifacts/kaji-release
```

Task 13 invokes this interface with `--artifacts-dir .artifacts/kaji-release`. Both installed runtimes must complete their full duration with bounded memory/store/fanout/tool metrics and validated exact-artifact evidence. Do not run/retain final soak evidence before the Task 13 freeze.

- [ ] **Step 5: Harden the four-cell keyed provider proof**

With `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` supplied through the operator environment, run:

```bash
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/scripts/live_provider_proof.py --artifacts-dir .artifacts/kaji-release
```

Task 13 runs real normalized tool loops for Python/OpenAI, TypeScript/OpenAI, Python/Anthropic, and TypeScript/Anthropic from installed artifacts. Missing-key hygiene or mock adapters do not count.

Before running, change `_child_environment()` to construct from an explicit non-secret allowlist (`PATH`, `HOME`, `TMPDIR`, locale, certificate variables, `UV_CACHE_DIR`, `KAJI_RELEASE_COMMIT`, and the selected provider's bounded model setting) plus only that child's provider key. Tests seed `GITHUB_TOKEN`, every `GOOGLE_*`/`KAJI_GMAIL_*` value, the other model-provider key, and sentinel secrets, then assert none reach stdout/stderr or the child environment.

- [ ] **Step 6: Define the final five-user macOS execution**

Task 13 has each pseudonymous participant install only the exact wheel/sdist/npm artifact under test, run ordered `artifact-install -> scaffold-init -> no-key-run -> echo-setup -> echo-run`, record toolchain versions and step milliseconds, redact confusion/remediation, and bind the document to the exact release manifest and artifact hashes. Validate there, not before the final freeze:

```bash
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/scripts/validate_tthw_evidence.py \
  .artifacts/kaji-evidence/tthw-evidence.json \
  --release-manifest .artifacts/kaji-release/manifest.json \
  --artifacts-dir .artifacts/kaji-release
```

Expected thresholds remain: no-key median under 5 minutes/every run under 10; Echo median under 10/every run under 20.

- [ ] **Step 7: GitButler checkpoint**

Commit the macOS contract/tests/docs and consume-only runner changes with `chore(kaji): bind beta evidence to macOS`. Do not commit the rehearsal baseline candidate, secrets, or generated evidence. The accepted tracked baseline lands only at Task 13's final-calibration checkpoint.

### Task 12: Complete Documentation, Consume-Only Smokes, and First-Use Assets

**Files:**

- Create `docs/kaji/github-integration.md`.
- Create `docs/kaji/gmail-integration.md`.
- Create `docs/kaji/gmail-data-handling.md`.
- Create `kaji/contracts/release/gmail-data-approval-v1.schema.json` and `kaji/sdk/tests/test_gmail_data_approval.py`.
- Create canonical runnable examples `kaji/sdk/examples/github_agent.py`, `gmail_agent.py`, `kaji/ts/examples/github-agent/index.ts`, and `gmail-agent/index.ts`, plus deterministic no-network smoke fixtures.
- Modify `docs/kaji/README.md`, `integration-manifests.md`, `tool-contracts.md`, `cli.md`, `troubleshooting.md`, `production-beta.md`, `testing.md`, and `releasing.md`.
- Modify `docs/MVP.md`, `apps/docs/content/install.mdx`, and `apps/docs/content/cli.mdx`.
- Modify the root/site open-source wording, `CONTRIBUTING.md`, and copied-bundle license assets to state the actual FSL permitted-purpose and competing-use terms, Apache-2.0 future-license transition, and integration contribution checklist.
- Create `apps/docs/content/integrations/github.mdx` and `gmail.mdx`; modify docs `meta.json`, sidebar config, and version-switcher data so both pages are publicly findable and labeled with the beta version.
- Modify `kaji/sdk/README.md` and `kaji/ts/README.md`.
- Modify both package metadata documentation/homepage links to the exact signed beta-tag docs path instead of mutable `main`; keep public-site latest pages as discovery aliases.
- Modify docs-contract and production-beta-doc tests in both SDKs.
- Create `.github/ISSUE_TEMPLATE/kaji-integration-onboarding.yml` with only redacted integration/runtime/failed-step/duration-bucket/friction/remediation fields.
- Modify `kaji/sdk/scripts/release_smoke.py`, `kaji/ts/scripts/smoke_package.mts`, archive verification, and npm package verification to include the new experimental assets/commands and explicit consume-only paths.

- [ ] **Step 1: Write docs-contract tests for exact commands and warnings**

Tests assert both languages document:

- install/add/opt-in commands;
- fixed origins and repository/recipient allowlists;
- GitHub fine-grained PAT minimum permissions and expiry;
- `kaji connect`/`disconnect`, Keychain service identity, PKCE, and principal binding;
- Gmail restricted-scope/BYO-client implications;
- event-store data classification: tool arguments/results may contain repository content, email addresses, subjects, and message bodies, so hosts must configure access control, encryption, retention, and deletion appropriate to restricted Gmail data;
- `ToolPolicy(require_approval_for={"external_effect"})` and TypeScript equivalent;
- mutation unknown-outcome/no-retry behavior;
- output and attachment limits;
- experimental status and exact promotion criteria.

Each provider page starts with a numbered provider-console-to-first-safe-result checklist and expected verification output. GitHub names exact repository selection, Contents read, Issues read/write, token expiry, organization-approval/pending behavior, secret-manager env name, qualified add/list command, and first read. Gmail names project creation, Gmail API enablement, branding/audience/test users, exact `gmail.readonly` + `gmail.compose` data-access scopes, Desktop client creation, client ID/optional secret env names, qualified connect, browser consent, Keychain confirmation, and first draft. Show SDK activation time and total prerequisite-inclusive time separately; never imply Google verification or GitHub organization approval is instant or controlled by Kaji.

`gmail-data-handling.md` is normative for promotion and contains a closed field-by-field classification of tool arguments/results/events, the bounded in-memory SDK default, the explicit absence of encrypted durable storage, host obligations for encryption/access/tenant isolation/retention/deletion/backups/incidents, and a deletion/revocation runbook. The approval schema records exact commit, Gmail ABI digest, policy-document digest, classification version, phase `provisional|final`, pseudonymous approver ID, approval timestamp, and booleans confirming every required control/host-responsibility section. It permits no free-form provider/user content. A validator rejects stale digests or incomplete controls; Task 13 uses a provisional approval for candidate proof and regenerates a final `.artifacts/kaji-evidence/gmail-data-approval.json` only after the final marker/docs commit.

Docs IA tests assert GitHub/Gmail appear in site metadata/sidebar, the version switcher does not advertise mutable `Latest 0.0`, and each installed package version maps to commands/examples under its exact future signed-tag docs URL. A version roll updates package metadata, docs labels, and these contract fixtures atomically before any evidence.

- [ ] **Step 2: Publish copy-paste first-use paths**

The docs embed code mechanically synchronized with all four example files. They tell installed-package users to save the shown file locally instead of calling a repository-only/nonexistent `examples/...` path. GitHub Python target path, after the user already owns a fixture token/repository:

```bash
python -m kaji.cli add github --allow-experimental --out ./integrations/github
# Load GITHUB_TOKEN from the documented secret-manager/environment-file path.
python github_agent.py
```

Gmail Python target path:

```bash
pip install kaji
python -m kaji.cli add gmail --allow-experimental --out ./integrations/gmail
# Load GOOGLE_CLIENT_ID from the documented environment file.
python -m kaji.cli connect gmail --principal local-user
python gmail_agent.py
```

TypeScript has parallel `bun github-agent.ts` and `bun gmail-agent.ts` paths using the same copied-source ABI and provider-fixed `@kaji/sdk/integrations` subpath. Each example supplies a principal, immutable repository/recipient allowlist, approval handler, and expected first output. Docs-contract tests compare the embedded code to canonical example files and smoke them with injected no-network transports.

Every copied provider directory also contains a pytest/Vitest template plus deterministic fixture data. Its test-only scripted requester can produce success, missing auth, rate limit, approval rejection-before-transport, and connection loss after mutation dispatch, but cannot select an origin or make network calls. `docs/kaji/testing.md` shows how owners keep/extend these tests after modifying a copy; package smoke proves the templates pass from installed artifacts with credentials cleared and network denied.

- [ ] **Step 3: Add genuinely consume-only package smoke**

Python `release_smoke.py --consume-only --wheel <path> --sdist <path>` must never clean/build/copy the dist directory. TypeScript `smoke_package.mts --consume-only <tarball>` must never run `npm pack` or build. From supplied artifacts only, verify registry list, experimental denial, opt-in copy, side-effect-free import/inspection, schema/ABI assets, the public provider-fixed TypeScript integration subpath, CLI auth-required output, ESM/CJS declarations, and no network/browser/Keychain access. Smoke validates each bundle's non-self-referential `.kaji-integration-provenance.json` sidecar against canonical source bodies, ABI, manifest, SDK version, and copied Kaji license digest; source files/manifests contain no self-digest header. `verify_release_artifacts.py` remains the only frozen-set verifier; never invoke mutating `verify_package_metadata.py` on that directory.

Document that registry demotion/yanking cannot retract host-owned copied files. Provide exact digest-based locate, inspect, remove, and replace instructions for Python and TypeScript projects, including how to reconcile locally modified copies rather than overwrite them. Release advisories name affected ABI/source digests; do not imply an SDK upgrade disables deployed copies.

- [ ] **Step 4: Run documentation and package gates**

```bash
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync pytest kaji/sdk/tests/test_production_beta_docs.py kaji/sdk/tests/test_docs_contract.py -q
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/sdk/scripts/release_smoke.py
cd kaji/ts && bun run build && bun run package:smoke && bun run test -- tests/docs-contract.test.ts
```

- [ ] **Step 5: Define the two-person exact-docs usability smoke**

Task 13 has one fresh Python user and one fresh TypeScript user follow only the committed docs on clean macOS accounts and exact frozen artifacts, with isolated GitHub fixture access and distinct disposable Gmail rehearsal principals. Emit validated `integration-docs-smoke-v1` documents, not free-form notes. Measure credential setup separately from SDK time and also record total start-to-safe-result: GitHub PAT/repository approval and Google project/API/consent/Desktop-client setup have their own `credentialPrerequisiteMs`; GitHub artifact-install-to-first-read targets under 10 minutes after credentials, and Gmail artifact-install-to-created-draft targets under 15 minutes after a desktop client. Both rows must succeed. Record only closed redacted friction/remediation codes. This is not a substitute for the five-user core TTHW gate or machine live-proof principals.

The onboarding issue form uses the same closed codes without repository/account/message data. `docs/kaji/testing.md` defines the non-blocking post-beta cohort: at least five new runs per promoted integration, report activation and total medians plus every-run maximum/success rate, and repeat after 30 days before making an adoption-speed claim.

- [ ] **Step 6: GitButler checkpoint**

Commit only Task 12 changes with `docs(kaji): document GitHub and Gmail beta paths`. Source-build smokes validate implementation; Task 13's consume-only runs establish final-artifact evidence.

### Task 13: Decide Promotion, Freeze the Final Commit, and Execute Protected Release

**Files:**

- Modify registry stability and `kaji/contracts/beta-core-v1.json` only for integrations whose candidate promotion gates passed.
- Modify `kaji/benchmarks/beta-baseline.json` only at the final-calibration checkpoint after all source-hash-changing edits.
- Modify `kaji/RELEASE_MATRIX.md`/`docs/kaji/production-beta.md` only for pre-freeze candidate marker intent; modify package versions/changelog only if the version preflight requires it. Never edit tracked status after final evidence.
- Modify `.github/workflows/kaji.beta.yml` and `.github/workflows/kaji.beta-publish.yml` to ingest a protected candidate bundle and publish its exact selected bytes.
- Modify `kaji/scripts/attach_release_assets.py` and its tests to attach the validated integration-evidence directory without requiring files for experimental providers.
- Extend release-workflow/security contract tests in both SDKs for required, not-required, missing, mismatched, attested, and attached integration evidence.
- No tracked change is allowed after the final marker checkpoint without discarding and rerunning every final artifact/evidence item.

- [ ] **Step 0: Implement and checkpoint protected ingestion before evidence**

Add a protected `workflow_dispatch` candidate-ingest path, unavailable while hosted minutes are exhausted. Its build/validation job runs on the standard GitHub-hosted arm64 `macos-15` label, asserts `uname -m=arm64`, records `sw_vers`, and has no larger-runner/Linux/self-hosted/manual fallback. This avoids the `macos-14` image's 2026 deprecation while remaining available to personal repositories. Add a preflight smoke proving the build stays within the standard runner's published CPU/memory/disk/job-time budgets. It receives bounded evidence documents through separately named environment-protected secrets/variables, validates each against the checked-out commit and rebuilt manifest, and uploads one retention-bounded candidate bundle with Actions run ID, artifact ID, and archive SHA-256. Transport-only OIDC publisher jobs may remain Ubuntu because they execute no SDK/benchmark and publish only verified bundle bytes.

Remove the current Linux/x64 performance evidence job from the beta claim. Protected ingestion validates the signed/digest-bound local arm64 macOS core performance evidence and re-executes deterministic artifact/package checks plus the absolute-budget integration microbenchmark on standard `macos-15`; it must not generate or attest a second incompatible Linux baseline.

Workflow tests cover missing/extra/stale evidence, wrong runner/architecture, marker/evidence disagreement, artifact expiry, digest mismatch, and experimental integrations not requiring provider secrets. The tag workflow grants explicit least-privilege `actions: read` in addition to `contents: read`; cross-run download supplies a pinned `github-token`, exact `run-id`, and numeric artifact ID—never a mutable artifact name alone. Commit these workflow/script/test changes with `ci(kaji): add protected beta candidate ingestion` before any candidate build.

- [ ] **Precondition: Check versions and the clean implementation commit**

Run the bounded fixed-endpoint version preflight from Task 10. Accept only authoritative not-found. If either version exists, perform one atomic cross-package version roll, run the residual audit, and checkpoint it. Require clean HEAD after Tasks 1–12 and Step 0; no candidate live call precedes this point.

- [ ] **Step 1: Run candidate proof and decide GitHub promotion**

Build a temporary two-clone artifact set from the clean implementation commit. Require offline suites, executable ABI, installed-package smoke, both artifact-executed GitHub runtime cells, approval rejection before transport, read/write/readback, cleanup, redaction review, and the exact-docs usability smoke. Emit `github-candidate-promotion.json`. A `hold` leaves GitHub experimental; a `promote` authorizes changing both indexes and `beta-core-v1.json` together, followed by a GitButler marker checkpoint. Candidate artifacts/proofs become invalid immediately after that edit.

- [ ] **Step 2: Run candidate proof and decide Gmail promotion separately**

First validate a **provisional** Gmail data approval bound to the candidate commit/ABI/policy. Then require all applicable offline/package gates plus both artifact-executed Gmail cells, PKCE/state/callback tests, Keychain parity, per-principal refresh isolation, restricted-scope documentation, independent connect/disconnect/revoke, canonical send bytes, send-to-self, process-local store clear/child exit, two-phase disposable-account reset attestations, redaction review, and exact-docs usability smoke. Emit `gmail-candidate-promotion.json`. If Google policy/verification or data lifecycle is unacceptable, hold Gmail without invalidating GitHub/core; otherwise checkpoint both registry/beta-contract markers. Never reuse provisional approval or candidate evidence as final release evidence.

- [ ] **Step 3: Recalibrate after the last source-hash change**

After every version and promotion-marker checkpoint, run protected calibration again on the approved pinned arm64 macOS benchmark runner. Require the candidate source hash to include the final Python/TypeScript sources and package metadata. Review it, replace only `kaji/benchmarks/beta-baseline.json`, then checkpoint that baseline; because the existing source hash excludes the baseline file, the baseline-only commit must preserve the measured source hash. Any later source/package/marker edit invalidates calibration and returns here.

- [ ] **Step 4: Freeze the final tracked commit exactly once**

Only after all code, workflow, baseline, docs, examples, versions, and promotion markers are checkpointed, run the two-clone build and read-only verifier:

```bash
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/scripts/repro_artifacts.py \
  --commit "$(git rev-parse HEAD)" \
  --output .artifacts/kaji-release \
  --receipt .artifacts/kaji-evidence/reproducibility.json
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/scripts/verify_release_artifacts.py \
  --artifacts-dir .artifacts/kaji-release \
  --expected-commit "$(git rev-parse HEAD)"
```

Record directory hashes before/after every consumer. Run Python `release_smoke.py --consume-only --wheel <frozen-wheel> --sdist <frozen-sdist>` and TypeScript `smoke_package.mts --consume-only <frozen-tarball>`; neither may build, pack, copy, or rewrite. Then run Task 9's offline parity/contracts/ast-grep/lint/typecheck/dependency/archive gates with credential-required live tests excluded. Never call `verify_package_metadata.py` on `.artifacts/kaji-release`.

```bash
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/sdk/scripts/release_smoke.py --consume-only --wheel .artifacts/kaji-release/kaji-0.2.0b1-py3-none-any.whl --sdist .artifacts/kaji-release/kaji-0.2.0b1.tar.gz
cd kaji/ts && bun scripts/smoke_package.mts --consume-only ../../.artifacts/kaji-release/kaji-sdk-0.2.0-beta.1.tgz
```

- [ ] **Step 5: Produce all final exact-artifact evidence**

On the approved pinned arm64 macOS runner, run the full calibrated benchmark, integration microbenchmark, 30-minute soak, and Python/TypeScript × OpenAI/Anthropic proof with `--artifacts-dir .artifacts/kaji-release`. Each runtime resolves only the installed frozen package. Conduct/validate the five-user macOS core TTHW cohort and per-provider `integration-docs-smoke-v1` evidence against those same bytes.

```bash
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/scripts/beta_benchmark_gate.py --mode full --protected --artifacts-dir .artifacts/kaji-release --output .artifacts/kaji-evidence/benchmark-results.json
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/scripts/integration_benchmark.py --mode protected --artifacts-dir .artifacts/kaji-release --output .artifacts/kaji-evidence/integration-benchmark.json
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/scripts/run_beta_soak.py --minutes 30 --protected --artifacts-dir .artifacts/kaji-release
UV_CACHE_DIR=/tmp/kaji-uv-cache /Users/Enkang.Yuan1/.local/bin/uv run --project kaji/sdk --no-sync python kaji/scripts/live_provider_proof.py --artifacts-dir .artifacts/kaji-release
```

First make `release_readiness.py --required-integrations` cross-check both indexes and `beta-core-v1.json` and emit the exact closed beta set. Run GitHub only when that set contains `github`; run Gmail `--phase run`/external reset/`--phase finalize` only when it contains `gmail`. Remove candidate/pending outputs before final collection and assert no proof, reset attestation, docs-smoke, data approval, or promotion input exists for an experimental provider. For each beta provider, create a **final** promotion decision bound to final proof/commit/manifest. Gmail additionally requires a fresh **final** data approval after the marker/docs commit. If a beta-marked provider fails, demote it, checkpoint, and restart Steps 3–5 from recalibration.

```text
required beta set = release_readiness.py --required-integrations
if github required: integration_proof.py --integration github --phase run --artifacts-dir <frozen>
if gmail required:  integration_proof.py --integration gmail --phase run --artifacts-dir <frozen>
                    reset both accounts after child exit
                    integration_proof.py --integration gmail --phase finalize --pending <pending> --attestation <python> --attestation <typescript> --artifacts-dir <frozen>
```

- [ ] **Step 6: Emit immutable local readiness**

Generate `.artifacts/kaji-evidence/release-readiness.json` through `release_readiness.py`. Its closed schema binds exact commit, release-manifest/reproducibility-receipt digests, offline/package status, benchmark/integration-benchmark/soak/provider/TTHW digests, final registry marker set, and each required integration proof/docs-smoke/data-approval/**final promotion-decision** digest. It rejects extra/missing/stale evidence, dirty commit, reused version, mismatched artifact set, or Markdown-only approval. While minutes are exhausted it emits only `engineeringStatus: beta_ready`, `publicationStatus: blocked`, `publicationBlock: ci_minutes`. It is immutable and can never report publication.

Confirm both beta versions remain unused, the commit is clean, all required local evidence binds the frozen set, and publisher identities are configured. Core may reach `beta-ready` with both integrations experimental. Record exhausted hosted minutes as `publication_blocked: ci_minutes`; wait for reset instead of bypassing protection.

- [ ] **Step 7: After minutes reset, create the protected candidate bundle**

Provide each bounded local evidence JSON (maximum 32 KiB, no provider/user content) through a separately named environment-protected secret: benchmark, integration benchmark, soak, keyed-provider proof, TTHW, final promotion/proof/**docs-smoke** documents for beta integrations, final Gmail data approval when required, and expected local manifest/reproducibility digests. The standard arm64 `macos-15` job rebuilds twice, byte-compares to the expected manifest, revalidates every ingested document, regenerates readiness with `publicationStatus: eligible`, and uploads exact artifacts/evidence as one candidate bundle. If the runner is unavailable, a document is too large/stale, or any byte differs, remain blocked; do not fall back.

- [ ] **Step 8: Sign the candidate selection only with explicit authorization**

After reviewing the protected run, create a signed annotated tag whose closed message names commit, Actions run ID, artifact ID, candidate-archive SHA-256, manifest SHA-256, reproducibility digest, and eligible-readiness SHA-256. This authenticates the selected protected bytes instead of asking a later tag workflow to guess/rebuild them. The implementation agent stops and requests explicit user authorization immediately before creating or pushing the immutable tag.

- [ ] **Step 9: Publish and byte-verify only the selected bundle**

The tag workflow verifies the trusted tag signature/message, uses explicit `actions: read` plus the pinned cross-run token/run/artifact IDs to download the exact candidate, and rejects an expired/replaced/missing bundle or any archive/manifest/readiness mismatch. Derive required integrations from both indexes and `beta-core-v1.json`; disagreement fails. Supply-chain provenance includes eligible readiness, integration status, required proof/promotion/docs-smoke/data documents, SBOM, and exact package bytes. Python/npm OIDC jobs publish only those bytes; registry polling compares filename, size, SHA-256, and integrity. Only after both registries byte-verify does existing `publication-status.json` become `published` and the prerelease complete. Follow the partial-publication incident runbook on ambiguity; never rerun a publisher, reuse a version, retarget a tag, or substitute local publication.

## Error and Rescue Registry

| Method/codepath | Failure | Public code/outcome | Rescue action | User sees |
|---|---|---|---|---|
| Manifest load | missing/unknown OAuth field | `INTEGRATION_SCHEMA_INVALID`, not started | reject with pointer | exact field path and docs |
| `kaji add --check`/copy | absent/outdated/modified/demoted/cross-provider or I/O failure | stable check exit / copy abort | inspect sidecar; atomic same-provider swap or manual reconcile | state + package-qualified safe command |
| Fixed-origin/policy preflight | origin/header/allowlist/query violation | `INTEGRATION_POLICY_REJECTED`, failed/non-retryable | reject before token/network | safe configuration error |
| Token lookup | no principal grant | `INTEGRATION_AUTH_REQUIRED`, failed | no browser; instruct connect | exact connect command |
| OAuth consent | deny/state mismatch/timeout/cancel | `INTEGRATION_AUTH_ERROR`, not started | close listener; keep disconnected | bounded cause and retry step |
| OAuth token exchange | timeout/malformed/missing scope | `INTEGRATION_AUTH_ERROR`, not started | discard response; no storage write | reconnect guidance |
| OAuth refresh | transient confirmed failure | `INTEGRATION_AUTH_ERROR`, failed | shared single-flight ends; preserve grant when valid | retry guidance |
| OAuth refresh | `invalid_grant`/scope drift | `INTEGRATION_AUTH_REQUIRED`, failed | delete local grant | reconnect guidance |
| OAuth disconnect | ambiguous revocation | `INTEGRATION_AUTH_ERROR`, failed | persist blocked `revocation_pending`; retry or force-local/manual revoke | exact remote/local state |
| Keychain | missing binary/non-macOS/locked/corrupt | `INTEGRATION_AUTH_ERROR`, failed | no fallback plaintext storage | exact Keychain fix |
| GitHub/Gmail read | 401/403 | `INTEGRATION_AUTH_REQUIRED` or API error, failed | no retry without corrected auth | connect/token guidance |
| GitHub/Gmail read | bounded 429 | `INTEGRATION_RATE_LIMITED`, failed | at most two bounded read retries | retry-after summary |
| GitHub/Gmail read | malformed/oversize response | `INTEGRATION_API_ERROR`, failed | cancel body; no reflected payload | provider response invalid |
| Mutation preflight | disallowed repo/recipient/draft mismatch | `INTEGRATION_POLICY_REJECTED`, failed | reject before dispatch | policy mismatch + safe recovery code |
| Mutation provider response | confirmed 4xx/429 no effect | typed failed outcome | no blind retry | safe provider status summary |
| Mutation transport | timeout/reset after dispatch | `TOOL_EXECUTION_FAILED`, unknown | tombstone; reconcile provider | unknown-outcome guidance |
| Live proof | missing credential/cell/failure | hard failed evidence | retain no success claim | failing cell only |
| Gmail proof cleanup | in-memory store not cleared/process not exited or account not reset/deleted | pending/failed evidence | complete cleanup; attest with no identifiers | cleanup gate only |
| Release readiness | missing/stale/extra evidence or used version | blocked, no tag | rebuild/recollect only affected exact-commit evidence | failing JSON Pointer/rule |
| Release publication | partial/ambiguous registry state | release incident | preserve evidence; inspect/yank/deprecate/new version | explicit incident state |

No row is permitted to be unrescued, untested, silent, and user-invisible. Catch-all handlers may log privately through the existing redaction helper only, then rethrow a typed safe failure or preserve unknown outcome.

## Failure Modes Registry

| Codepath | Realistic failure | Rescued? | Test? | User-visible? | Logged safely? |
|---|---|---:|---:|---:|---:|
| GitHub search | secondary limit under parallel reads | yes | yes | yes | yes |
| GitHub create | socket closes after issue creation | reconciled as unknown | yes | yes | yes |
| Gmail thread | large multipart exceeds response cap | yes | yes | yes | yes |
| Gmail draft | CRLF injection in subject | yes, preflight | yes | yes | yes |
| Gmail send | draft replaced between pre-read and send | yes, supplied send MIME overwrites with approved bytes | race test | yes | yes |
| Gmail proof | runtime OAuth lifecycle/store/account cleanup incomplete | yes, pending/fail closed | yes | yes | yes |
| OAuth callback | attacker races wrong state | yes | yes | yes | yes |
| OAuth refresh | two callers rotate refresh token concurrently | single-flight | yes | yes | yes |
| OAuth refresh/disconnect | late refresh tries to save after revoke/delete | generation-fenced; late save rejected | deterministic race | yes | yes |
| Keychain save/delete | cancellation/timeout during blocking OS operation | subprocess terminated/reaped; no late completion | yes | yes | yes |
| Copied bundle | second provider, partial I/O, modified local file, or demoted source | staged atomic swap/refusal | either-order + rollback | yes | yes |
| Keychain write | process times out after prompt | yes | yes | yes | yes |
| ABI import | inspector performs top-level side effect | hard gate | yes + ast-grep | yes | yes |
| Local release | CI minutes unavailable | documented local evidence only | procedural | yes | n/a |
| Publication | one registry succeeds, one is ambiguous | incident procedure | workflow tests | yes | yes |

## Test Coverage Map

```text
CONTRACTS
  auth union: valid + every missing/extra/mixed field
  ABI index: containment + missing file + all metadata fields
  API conformance: happy/empty/error/boundary rows in Python and TS

NETWORK
  fixed origin: unsafe URL/header/redirect/body/timeout/cancel
  provider parsing: status + malformed + oversize + redaction
  mutation certainty: failed vs unknown + no retry

AUTH
  consent: PKCE/state/callback/deny/timeout/cancel
  storage: file atomicity + Keychain load/save/delete/corruption
  refresh: valid/scope drift/invalid_grant/single-flight/principal isolation
  CLI: connect/disconnect/actionable errors/no secret output

TOOLS
  every schema boundary + extra fields
  registration/namespace/risk/parallel/timeout ABI
  approval reject before handler/token/network
  durable result/replay and unknown-outcome tombstone

LIVE/RELEASE
  GitHub Python + TS read/create/comment/readback/cleanup
  Gmail Python + TS independent connect/read/draft/full-payload-verify/send-to-self/readback/disconnect/store-destroy/account-reset
  benchmark full + 30m soak + four keyed provider cells
  five macOS users across Python/npm/Bun
  exact artifact/tag/SBOM/provenance/publication verification
```

The 2 a.m. confidence test is the exact-commit protected release rehearsal plus each promoted integration's independent two-runtime proof with network faults injected before its real live pass. The hostile QA test injects cancellation at every await and content at every maximum+1 boundary. The chaos test races same-principal refresh, cross-principal reads, mutation timeout, callback spoofing, and response-stream overflow while asserting no secret/body leak and deterministic terminal events.

## Performance Budgets

| Path | Bound | Expected p99 on healthy provider, excluding provider latency |
|---|---|---|
| Fixed-origin preflight | O(path + headers), <=1 MiB response | <5 ms local work |
| GitHub single read | one request, <=20 results, <=1 MiB | <25 ms parsing |
| GitHub mutation | one POST, no automatic retry | <10 ms local work |
| Gmail search/labels | one request, <=20 IDs/labels | <20 ms parsing |
| Gmail thread | one metadata + <=10 message reads, concurrency 4 | <50 ms local work |
| OAuth access token | Keychain load or one keyed refresh | <20 ms storage; provider excluded |
| MIME parse | depth 16, parts 128, result <64 KiB | <20 ms |

At 10x, provider rate limits and Gmail thread fan-out fail first; caps, keyed single-flight, concurrency four, and bounded retry contain them. At 100x, local Keychain/process churn and provider quotas dominate; hosts should reuse one integration/client per principal/runtime and apply their own admission control. No unbounded cache, response accumulator, retry queue, or global OAuth lock is introduced.

## Observability and Operational Runbook

Emit existing metrics/traces with only low-cardinality labels: integration, tool, outcome, error code, attempt, and status family. Never label principal, repository, recipient, query, subject, path, provider ID, or token. Add spans for auth load/refresh and integration request; propagate existing trace/request/tool-call IDs. A three-week-later incident must be reconstructable from event sequence, tool code/outcome, attempt count, duration, provider status family, and exact ABI/version without provider content.

Runbooks:

- `INTEGRATION_AUTH_REQUIRED`: verify principal, manifest env names, Keychain service, and rerun the renderer's package-qualified `connect` command.
- `INTEGRATION_RATE_LIMITED`: inspect bounded retry metadata; reduce parallelism; never rotate credentials automatically.
- mutation `unknown`: reconcile by fixture marker/draft metadata before any manual retry.
- OAuth scope drift: disconnect, review least-privilege scopes, reconnect explicitly.
- live-proof failure: preserve only redacted evidence and local bounded logs; rerun the failed provider's cells after fixing state, then regenerate only that provider's exact-commit document.
- partial publication: follow `docs/kaji/releasing.md:106-162`; never rerun publisher jobs or reuse versions.

## Official Provider Constraints Used by This Plan

- Google desktop apps use the system browser, loopback `127.0.0.1`, state, and PKCE S256: <https://developers.google.com/identity/protocols/oauth2/native-app>.
- Gmail requests the narrowest applicable scopes; `gmail.readonly` and `gmail.compose` are restricted and may trigger verification/security-assessment obligations: <https://developers.google.com/workspace/gmail/api/auth/scopes>.
- Gmail drafts are stable containers whose messages can be replaced; `drafts.send` accepts both the draft ID and updated `message.raw`, which is the required atomic approved-send path: <https://developers.google.com/workspace/gmail/api/guides/drafts#send-drafts>.
- GitHub recommends fine-grained PATs for personal use and GitHub Apps for organization/long-lived installs: <https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens>.
- GitHub clients must honor primary/secondary limits, pagination, and rate-limit response headers: <https://docs.github.com/en/rest/using-the-rest-api>.

## Dream State Delta

This plan reaches a defensible two-runtime, two-provider macOS beta wedge: canonical copied-source contracts, fixed provider boundaries, explicit OAuth, exact-artifact execution, and a protected byte-selected release. It intentionally stops short of the 12-month ideal in five places:

1. Integration breadth remains GitHub/Gmail; Calendar, Notion, and Slack must prove the same ABI/transport discipline before the registry becomes an ecosystem claim.
2. Authentication remains host-owned PAT/Desktop OAuth plus macOS Keychain; there is no hosted account-linking service, organization GitHub App, enterprise vault adapter, or cross-platform credential guarantee.
3. Gmail's default event store is process-local and bounded; production hosts still own durable encryption, tenant isolation, retention, deletion, and incident controls.
4. The release claim is arm64 macOS only. Cross-platform performance/TTHW matrices and non-macOS secure storage remain future validation, not hidden beta promises.
5. Provider effects remain at-least-once/unknown-outcome with reconciliation. Webhooks, remote idempotency coordination, and exactly-once effect claims are outside this wedge.

These are explicit product boundaries, not reasons to broaden the current implementation. The next highest-information follow-up is Calendar because it reuses Google OAuth while testing time-zone and recurrence schemas without adding another auth family.

## Stale Diagram Audit

| Existing diagram/grammar | Current status | Required plan action |
|---|---|---|
| `docs/MVP.md:435-442` runtime pipeline | Still accurate; integrations enter through scoped `ToolRegistry` and do not replace core runtime nodes. | Preserve and add only a link to integration architecture if docs need it. |
| `docs/kaji/tool-contracts.md:53-55` external idempotency-key shape | Still accurate; new mutations use the same runtime key and unknown-outcome semantics. | Keep byte-identical and reference it from GitHub/Gmail docs. |
| `docs/kaji/cli.md:5-7` init-only CLI grammar | Becomes stale when `list-integrations`, `add`, `connect`, and `disconnect` gain documented parity. | Task 6/12 must replace it with the full command tree and exact exit/auth states in both runtimes. |
| Six ASCII diagrams in this plan (architecture, request/error shadow paths, OAuth state, Gmail send, deployment, rollback) | Authoritative design target; none describe removed runtime nodes. | Docs-contract review must compare final docs/code against them before promotion. |

No other touched documentation file currently contains an ASCII/Mermaid system diagram; code examples and fenced command syntax are covered by docs-contract tests rather than this diagram audit.

## CEO Review Implementation Tasks

- [ ] **CEO-T1 (P1, human: ~4h / CC: ~45min)** — release evidence — checkpoint every tracked tool/workflow/baseline/docs/marker change before final two-clone artifact freeze.
  - Surfaced by: Architecture/deployment convergence — Tasks 10–13 previously proved an earlier commit.
  - Files: Task 10–13 file lists and GitButler checkpoints.
  - Verify: final manifest commit equals clean HEAD and no evidence predates the last marker checkpoint.
- [ ] **CEO-T2 (P1, human: ~1d / CC: ~2h)** — live proof — install and execute the frozen wheel/tarball in every provider/runtime cell with source-path rejection.
  - Surfaced by: Architecture and release proof — hash-binding alone did not prove shipped code ran.
  - Files: `kaji/scripts/integration_proof.py`, live proof tests, package smokes.
  - Verify: wrong artifact/source import fixtures fail; exact installed path/version/digest passes.
- [ ] **CEO-T3 (P1, human: ~4h / CC: ~45min)** — release handoff — ingest a protected macOS candidate bundle and authenticate its artifact ID/digests in the signed tag.
  - Surfaced by: Deployment/reversibility — the tag workflow had no producer for locally approved bytes/readiness.
  - Files: `.github/workflows/kaji.beta.yml`, `.github/workflows/kaji.beta-publish.yml`, workflow contract tests.
  - Verify: expired/replaced/mismatched candidate bundle blocks publishers.
- [ ] **CEO-T4 (P1, human: ~3h / CC: ~30min)** — evidence lifecycle — keep readiness pre-publication and use machine-readable per-provider promotion/finalization artifacts.
  - Surfaced by: State/error audit — publication and Gmail reset states were cyclic or unverifiable.
  - Files: release schemas, `release_readiness.py`, `integration_proof.py`.
  - Verify: `published` readiness, stale approvals, duplicate/wrong reset attestations, and Markdown-only promotion all fail.
- [ ] **CEO-T5 (P1, human: ~4h / CC: ~45min)** — package/DX — add TypeScript subpath build mapping, consume-only smokes, and real Python/TypeScript examples.
  - Surfaced by: Feasibility/DX — declared imports/examples were not executable from packaged bytes.
  - Files: `kaji/ts/tsup.config.ts`, `tsconfig.json`, `package.json`, smoke scripts, four examples/docs.
  - Verify: packed ESM/CJS imports and synchronized docs examples pass with network disabled.

## Engineering Review Implementation Tasks

- [ ] **ENG-T1 (P1, human: ~1d / CC: ~2h)** — auth lifecycle — generation-fence connect/refresh/disconnect and replace macOS beta keyring threads with killable Keychain subprocesses.
  - Surfaced by: concurrency/cancellation review — late refresh or blocking keyring work could outlive disconnect/cancellation.
  - Files: Python/TypeScript OAuth and Keychain modules/tests.
  - Verify: deterministic races at every token/revoke/storage await produce no post-disconnect save or late Keychain completion.
- [ ] **ENG-T2 (P1, human: ~4h / CC: ~45min)** — runtime parity — align failed/unknown idempotency transitions and remove principal IDs from turn/tool observability.
  - Surfaced by: code-quality/security review — Python/TS reused claims differently and turn spans still emitted principal IDs.
  - Files: both execution/idempotency paths, both runtime span emitters, closed vocabularies/tests.
  - Verify: second-claim parity matrix and sentinel-principal scan pass.
- [ ] **ENG-T3 (P1, human: ~1d / CC: ~2h)** — exact-artifact performance — run Python/TS benchmark/soak/provider cells from installed frozen packages, never checkout aliases.
  - Surfaced by: architecture/test review — TS benchmarks imported `@/*` source despite artifact claims.
  - Files: benchmark/soak scripts, orchestrators, temp-consumer tests.
  - Verify: module resolution outside temp venv/node_modules fails.
- [ ] **ENG-T4 (P1, human: ~4h / CC: ~45min)** — deterministic gates — enforce offline execution, pre-merge integration microbench, and executable p99 sampling/noise rules.
  - Surfaced by: test/performance review — network denial and p99 were prose-only; quick integration regression was manual.
  - Files: offline guards, beta release/PR workflows, integration budgets/benchmarks/tests.
  - Verify: real socket/fetch probes fail; 20-warmup/3x200 nearest-rank p99 fixtures and workflow contracts pass.
- [ ] **ENG-T5 (P1, human: ~4h / CC: ~45min)** — release determinism — pin the complete build toolchain and calibrate only after final version/marker edits.
  - Surfaced by: release review — floating Node/Python/npm and pre-marker calibration made later byte/performance proof stale.
  - Files: `kaji/release-toolchain.json`, build/verify scripts/actions, baseline gate.
  - Verify: any tool version/source-hash drift blocks before build/full benchmark.
- [ ] **ENG-T6 (P1, human: ~4h / CC: ~45min)** — provider transport — bypass Node global proxy/dispatcher state with a private direct HTTPS agent.
  - Surfaced by: security architecture review — native global fetch could route bearer traffic through ambient proxy state.
  - Files: TypeScript fixed-origin requester and poisoned-proxy tests.
  - Verify: proxy/global dispatcher remain untouched while fixed-origin request succeeds.

## Developer Experience Review

**Mode:** DX POLISH — hold feature scope; make the existing GitHub/Gmail path reliable, discoverable, testable, and accurately licensed.

| Dimension | Before refinement | Planned result | Gate |
|---|---:|---:|---|
| Getting started | 5/10 | 8/10 | package-qualified commands, provider-console checklist, exact-docs smoke |
| API/CLI | 6/10 | 9/10 | canonical defaults, structured discovery, safe `add --check` |
| Errors/debugging | 4/10 | 9/10 | closed reason/recovery/doc metadata survives runtime/replay |
| Documentation | 6/10 | 9/10 | public integration IA plus exact-version/tag links |
| Upgrade/demotion | 5/10 | 9/10 | provenance, read-only status, atomic same-provider replacement |
| Tooling/testing | 6/10 | 9/10 | copied no-network pytest/Vitest templates and fixtures |
| Ecosystem/legal | 3/10 | 8/10 | accurate source-available terms, copied license, contribution path |
| Measurement | 4/10 | 8/10 | exact-docs smoke now; closed feedback and five-run post-beta cohort |

### Developer Experience Implementation Tasks

- [ ] **DX-T1 (P1, human: ~4h / CC: ~45min)** — CLI/errors — make commands package-qualified and preserve closed actionable recovery metadata through durable failures.
  - Files: Python/TS CLI entrypoints/help/list/renderers, error schemas/mappings, docs/tests.
  - Verify: conflicting binaries still select the right SDK; three auth/Keychain/unknown-effect errors show safe exact recovery.
- [ ] **DX-T2 (P1, human: ~4h / CC: ~45min)** — discovery/docs — publish GitHub/Gmail site pages, exact-version links, canonical optional defaults, and full structured list parity.
  - Files: docs content/meta/sidebar/version data, package metadata, ABI fixtures, list CLIs.
  - Verify: installed version resolves matching examples/commands and Python/TS JSON output is byte-shape equivalent.
- [ ] **DX-T3 (P1, human: ~1d / CC: ~2h)** — copied bundles — add provider-scoped atomic copying, provenance/license sidecars, `add --check`, and no-network owner tests.
  - Files: both add implementations, registry bundles/manifests/fixtures, package smokes, testing docs.
  - Verify: install both orders, partial-I/O rollback, modified/demoted/cross-provider refusal, license/provenance checks, downstream failure fixtures.
- [ ] **DX-T4 (P1, human: ~3h / CC: ~30min)** — credential onboarding — document exact GitHub/Google console prerequisites and measure prerequisite/activation/total time separately.
  - Files: provider docs/examples, `integration-docs-smoke-v1`, docs contracts.
  - Verify: fresh Python/TS users reach the safe result using only the committed page and emit valid closed evidence.
- [ ] **DX-T5 (P2, human: ~2h / CC: ~20min)** — feedback loop — add redacted onboarding feedback and define the post-beta adoption cohort.
  - Files: onboarding issue form, testing/releasing docs.
  - Verify: form/schema accept only closed non-content fields; five-run/30-day protocol is explicit and non-blocking for beta.

## Self-Review Checklist

- [ ] Every requested beta concern maps to a task: production hardening (Tasks 1-9), feature/schema proof (Tasks 1, 3-8), architecture/performance (Tasks 2, 5, 7, 9, 11), release evidence (Tasks 10-13), and macOS-only cohort (Task 11).
- [ ] GitHub, Gmail, Calendar, Notion, and Slack sequencing is explicit; only the first two enter implementation.
- [ ] Shared contract changes include both runtimes and package copies in one checkpoint.
- [ ] All new interfaces used by later tasks are named in earlier tasks.
- [ ] No tool can choose its origin, credential path, shell command, repository outside a host allowlist, or Gmail recipient outside a host allowlist.
- [ ] No mutation retries after ambiguous dispatch; approval denial proves zero handler/token/network calls.
- [ ] OAuth consent is explicit and principal-bound; tools only load/refresh.
- [ ] Deterministic offline tests precede live provider calls.
- [ ] Integration promotion is independent of the SDK core beta and independent between GitHub/Gmail.
- [ ] All tracked tooling, workflow, baseline, docs, version, and marker edits are checkpointed before the final two-clone freeze; generated evidence remains uncommitted.
- [ ] Every final live/performance/soak/provider cell installs and resolves the frozen wheel/tarball; source is limited to orchestration and case definitions.
- [ ] Frozen artifacts are verified/consumed read-only; no metadata or smoke command rebuilds or rewrites them.
- [ ] Gmail reset finalization and provider promotion decisions are closed machine-readable artifacts bound to the final run/commit/manifest.
- [ ] Readiness is immutable and pre-publication; only `publication-status.json` can record `published`.
- [ ] Hosted CI exhaustion is handled as an evidence limitation, not bypass authorization.
- [ ] Tagging, pushing, publishing, and immutable external writes require a fresh user authorization.
- [ ] The plan contains no `TBD`, deferred implementation placeholder, vague “add tests,” or unnamed error-handling step.
- [ ] GitButler checkpoints require selecting only task-owned file/hunk IDs.

## Implementation Completion Definition

The plan has three independently reportable completion outcomes:

1. **Shared implementation complete:** all offline Python/TypeScript/contract/ast-grep/package gates pass, and GitHub/Gmail are present as opt-in experimental integrations with synchronized ABI assets. No live provider or promotion claim is implied.
2. **Core beta-ready:** two independent detached clones produce byte-identical frozen candidate artifacts from the final clean commit; consume-only smokes, macOS-only five-user TTHW, calibrated full benchmark, 30-minute soak, and four keyed model-provider proofs execute/bind those bytes. GitHub/Gmail may both remain experimental. While hosted minutes are exhausted, report `beta-ready / publication blocked`, not published beta.
3. **Published core beta:** after minutes reset, protected arm64 macOS ingestion rebuilds and selects the approved bytes, a signed tag authenticates the exact candidate artifact ID/digests, and protected jobs attach SBOM/provenance then byte-verify both registries after explicit authorization.
4. **Integration promotion complete, independently per provider:** its two-runtime macOS proof validates on the final marker commit, every provider-specific gate/rehearsal passes, and its reviewed decision is recorded. GitHub failure cannot invalidate Gmail/core; Gmail failure or deferral cannot invalidate GitHub/core.

All applicable review decisions below must also be resolved and the final `GSTACK REVIEW REPORT` must state which of these outcomes are clear, pending, or blocked.

## GSTACK REVIEW REPORT

| Review | Result | Resolution |
|---|---|---|
| CEO | **CLEAR — HOLD_SCOPE** | GitHub then Gmail remains the release wedge; all five scope/release findings are represented by CEO-T1 through CEO-T5. No additional provider enters this implementation. |
| Engineering | **CLEAR — FULL_REVIEW** | Auth races, idempotency parity, private transport, exact-artifact execution, deterministic performance/offline gates, and full toolchain pinning are locked by ENG-T1 through ENG-T6. No P0/P1 architecture gap remains. |
| Developer experience | **CLEAR — DX_POLISH (planned 8/10)** | Package-qualified commands, actionable errors, public docs, safe copied-bundle lifecycle, downstream tests, accurate licensing, and measurable onboarding are locked by DX-T1 through DX-T5. |
| Independent outside voice | **CLEAR AFTER FIXES** | Claude CLI reported `loggedIn: false`, so an independent fresh-subagent fallback reviewed the plan. Its runner, artifact, toolchain, first-use, permission, and proof-selection findings are folded in. |
| Design | **NOT APPLICABLE** | This plan changes SDK, CLI, schemas, docs, release automation, and evidence contracts; it adds no product UI. |

**Current structural evidence:** the existing ast-grep audit passes all 27 rule fixtures and scans `kaji/` clean. Implementation must retain those gates and add the named integration rules/fixtures before promotion.

**Outcome disposition:** the plan is clear to implement. Shared implementation, core beta-ready proof, protected publication, and per-provider promotion remain pending execution. Protected publication alone is externally blocked until hosted-CI minutes reset; local evidence must not be represented as a published beta.

**Execution prerequisite:** GitButler must be initialized for this workspace before the first task checkpoint. No implementation, checkpoint, tag, push, or publication action is authorized by this planning review.

**NO UNRESOLVED DECISIONS.**
