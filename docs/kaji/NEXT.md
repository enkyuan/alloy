# Kaji: what's next

> Forward-looking plan. For current beta-readiness authority use
> [`kaji/README.md`](../../kaji/README.md) and
> [`kaji/RELEASE_MATRIX.md`](../../kaji/RELEASE_MATRIX.md). This document sets
> direction; those set truth.

## Thesis

Kaji is general agent infrastructure: any app that needs agents can be built on
top of it. Ryo is the first such app, not the reason Kaji exists. That framing
decides scope:

- The Ryo bridge (a `request_payment` tool hitting the Ryo API) is Ryo's
  concern, not Kaji's. Putting a service call inside the SDK would break the
  `python-sdk-no-service-imports` boundary the ast-grep rules enforce. It is
  out of scope for the SDK roadmap and belongs in the Ryo codebase, written
  against Kaji's public `Integration` seam like any other third-party tool.
- The work that makes the generality claim true is three surfaces: prove and
  document the third-party integration path, sharpen the build-an-agent
  on-ramp, and ship an actually-installable beta.

---

## Surface A -- third-party integration path (the generality proof)

The path already exists and works today. An out-of-tree integration reaches an
`AgentRuntime` by subclassing `Integration` and passing it to
`AgentBuilder.integration()`. This path has no allowlist, no manifest, and no
registry directory; it is duck-typed on a `register()` method
([`builder.py`](../../kaji/packages/python/src/kaji/runtime/agents/builder.py),
[`builder.ts`](../../kaji/packages/typescript/src/runtime/builder.ts)). The
`agentos` example uses exactly this path
([`agentos-integration.ts`](../../kaji/packages/typescript/examples/agentos/agentos-integration.ts)).

The manifest/registry loader (`load_manifest` / `loadManifest`) is a separate
source-copy mechanism used only by `kaji add`; it never constructs a runtime
object. The closed allowlist test gates packaging, not loading. So the work
here is to prove, document, and exhibit the path -- not to build a loader.

1. **Prove it.** Add an out-of-tree fixture: a tiny package outside the SDK
   tree that subclasses `Integration`, installs into a clean environment, and
   asserts it drives an `AgentRuntime` via `AgentBuilder.integration()`. This
   is the missing evidence that the generality claim holds for a stranger, not
   just for first-party code.
2. **Document it.** A public docs-site page ("Build your own integration") on
   the direct-subclass path, the API a third-party author actually uses today:
   `Integration`, `tool`, `function_tool`, `AgentBuilder`. Explicitly
   distinguish it from `kaji add`, which today is easy to misread as "the
   extension mechanism" when it is really a source-copy of curated first-party
   bundles.
3. **Graduate agentOS.** Promote the `agentos` example to the
   separately-versioned `@kaji/agentos` package the example README already
   promises, as the worked example of an arm's-length, out-of-tree integration.
   Keep it outside the `kaji-sdk` tarball; its native, ESM-only, preview nature
   is exactly why it must not be a core subpath.

**Deliberately not doing (yet): a manifest-to-runtime bridge.** Making external
packages plug into `kaji add` would be net-new code in both SDKs (the Python
loader is path-locked and no manifest-to-`Integrable` bridge exists anywhere).
The subclass path already satisfies the thesis, so the bridge is speculative.
Flag it; do not build it until real demand appears.

---

## Surface B -- core SDK ergonomics + docs (the on-ramp)

A stranger should reach a working agent without reading the source.

- **TypeScript quickstart friction.** The no-key hello agent only runs if saved
  as `.mts` (top-level await / ESM). Add a CommonJS-safe variant or an
  `async main()` wrapper so a paste into `index.js` works from a default npm
  project.
- **No Python `pip install` path.** PyPI publication is deferred, so the docs
  route Python users to a source checkout. Either surface that honestly on the
  getting-started page (which is currently TypeScript-first with Python as an
  aside) or prioritize the PyPI publish. This is a sequencing decision, not a
  code change in isolation.
- **Missing docs-site pages.** There is no public API reference, and no concept
  pages for RAG / DocumentRAG, sessions and replay, approvals, cancellation, or
  observability. These surfaces live only in the READMEs and
  [`production-beta.md`](production-beta.md). Add the high-traffic ones.
- **Parity is already covered.** API parity is tracked in
  [`api-parity.md`](api-parity.md) and enforced by the 67-scenario
  `check_sdk_parity.py` gate. No work needed there.

---

## Surface C -- ship the 0.2 beta (the mechanical checklist)

From the [`RELEASE_MATRIX.md`](../../kaji/RELEASE_MATRIX.md) gate table. Ordered;
each item tagged by the kind of work it is.

1. **[ops]** Make `enkyuan/alloy` public (audit history and Actions logs for
   secrets first). npm provenance requires a public source repo.
2. **[code]** Reconcile or consciously document the Python version pin. TS is
   `0.2.0-beta.11`; Python is `0.2.0b1`. The skew is currently intentional and
   test-pinned (`test_release_task15.py` asserts both literals), so document it
   rather than "fixing" it blindly.
3. **[code/CI]** Land the reviewed release commit on `main`; confirm license
   byte-identity and changelog dates.
4. **[ops]** Configure the three protected environments in order
   (`kaji-beta-onboarding` then `kaji-beta` then `kaji-beta-publish`) and the
   reviewer.
5. **[credential]** Store `OPENAI_API_KEY` in `kaji-beta` only, a fresh
   `NPM_TOKEN` in `kaji-beta-publish` only, and set `KAJI_RELEASE_SIGNER_EMAIL`.
6. **[CI/evidence]** Confirm registry-absence (npm and PyPI 404 for beta.11).
7. **[CI/evidence]** Dispatch `kaji.rehearsal.yml`: offline gates, Python
   3.11/3.14 and Node 22/24 compatibility, the 3x paired benchmark, and the
   30-minute soak.
8. **[CI/evidence]** Approve the `kaji-beta-onboarding` aggregate.
9. **[credential]** Approve `kaji-beta`. `live_provider_proof.py` completes the
   OpenAI tool loop in both SDKs. This is the single highest-leverage blocker:
   it cannot be rehearsed offline and is the literal content of the release
   promise. Run the Gmail live proof (see runbook below) in the same protected
   window.
10. **[ops]** Bind and push the canonical-JSON signed annotated tag
    `kaji-v0.2.0-beta.11`.
11. **[CI/evidence]** Publish workflow: SBOM, provenance, attestation.
12. **[credential/ops]** Approve `kaji-beta-publish`, publish once, and require
    `npm_byte_verified` plus `verify_published_packages.py`.

---

## Recommended sequencing

**Ship C first, then A, with B running continuously.**

"Any app builds on Kaji" means nothing until `npm i kaji-sdk` is a real
published thing. The beta is one credential and one repo-visibility flip from
done, so it is the cheapest high-value unlock. The third-party path (A) is what
makes the generality real, but it has no audience until there is a published SDK
to build on. Ergonomics and docs (B) run alongside both, not as a discrete
phase.

This sequencing was the contested call sent through `/autoplan` review. The
review revised it: an **A0-lite gate runs before the beta tag** (a cross-SDK
parity assertion on the `Integration` surface), and the F2/F4 findings were
accepted. See the "Revised recommendation" under GSTACK REVIEW REPORT below,
which supersedes this section.

---

## Manual runbook (credential-gated; cannot run in a normal dev session)

These steps need real credentials and a tagged release commit. They are listed
here so the operator who has them can execute in order.

- **Gmail live proof.** Gmail is now catalog-beta, but its live send path is
  unproven until a protected operator run retains a valid
  `gmail-proof-v1.schema.json` receipt. The receipt schema ships in all three
  contract locations. `kaji/scripts/live_gmail_proof.py` ships as an
  **executable skeleton**: the CLI (mirrors `live_github_proof.py`'s flags), the
  receipt builder + schema validation, and the ordered
  `get_message -> approved send_message -> readback -> delete -> redacted receipt`
  sequence are real and self-checked (`test_live_gmail_proof.py`); every live
  step is a `OperatorTodo` stub so the skeleton fails closed (exit 2) and can
  never emit a passing receipt. The operator fills the stubs in the `kaji-beta`
  window (step 9 above): port prerequisite validation from the GitHub proof,
  write the `installed_gmail_live.py` / `installed-gmail-live.mts` child runners,
  and wire the credentialed Gmail API calls. Note: the Gmail client exposes no
  delete, so cleanup deletes the proof message via a raw authorized Gmail API
  call, not through the shipped client.
- **OpenAI tool-loop proof, tag, and publish.** Steps 9 through 12 above are all
  credential- or ops-gated and run only in the protected workflows.

---

## GSTACK REVIEW REPORT

`/autoplan` reviewed the two contested surfaces (Surface A and the sequencing
call) with dual voices: an independent Claude engineering/strategy subagent and
Codex (both read the actual code). Surface C and the gmail work were out of
review scope by request (mechanical, gate-driven).

### Consensus table (CEO/strategy + DX dimensions)

```
Dimension                                        Claude   Codex   Consensus
------------------------------------------------ -------- ------- ---------
1. No manifest-to-runtime bridge (YAGNI)         endorse  endorse CONFIRMED
2. Subclass path works today (verified in code)  yes      yes     CONFIRMED
3. Subclass path alone PROVES generality         no       no      CONFIRMED (plan overclaims)
4. Beta-first is correct AS WRITTEN              no       no      CONFIRMED (revise: A0 gate before tag)
5. agentOS graduation is well-gated now          no       no      CONFIRMED (violates its own demand+stability gate)
6. PyPI-deferred undercuts dual-language thesis  yes      yes     CONFIRMED
```

Both voices converged, so finding 4 is treated as a **User Challenge** (both
models recommend changing the user's stated "ship C first, then A" sequencing),
not an auto-decided taste call. It is surfaced to the user, whose original
direction stands unless explicitly changed.

### Findings

**F1 (medium). Surface A overclaims "already works"; the real deliverable is a
package-authoring contract, not another subclass tutorial.** Verified: the
subclass + `AgentBuilder.integration()` path works today with zero SDK changes
(`builder.ts:66`, `builder.py:85`, duck-typed on `register()`). But both READMEs
already ship a `WeatherIntegration` subclass example
([python](../../kaji/packages/python/README.md), TS README), so the missing piece
is not a tutorial. What is missing for a stranger: package naming, peer-dependency
ranges, factory-export convention, cross-SDK parity of the authored surface, and
ESM/CJS consumption guidance. Reframe A as *closing* that gap, and make the
out-of-tree fixture depend on the **packed tarball** (not a workspace path), or it
proves nothing about the real import surface.

**F2 (high). Beta ships an installable SDK for only one of two languages.**
`kaji.publish.yml` runs `npm publish` only; PyPI is `skipped`. At the beta, the
pitch to a Python shop is "clone the monorepo and run from source," which is a
vendored dependency, not an installable SDK. The dual-language thesis is half-true
at the moment of the beta the plan prioritizes. Fix additively: make "Python is
source-install at beta" an above-the-fold release gate on the getting-started
page, and add an explicit post-beta/pre-1.0 PyPI-publish line item (the wheel and
sdist are already built and attested; the missing piece is the trusted-publish
step).

**F3 (medium-high, the 6-month regret). Publishing the `Integration` ABI as
stable before the package boundary is proven or specified.** Both voices name the
same regret: early integrations discover they need async initialization, managed
disposal, host-provided credential resolution, and compatibility metadata; Kaji
then either breaks the stable `register()` contract or carries a second lifecycle
interface forever. Meanwhile users read `kaji add` as the official mechanism and
fork security-sensitive HTTP/auth code. Insurance: a cross-SDK parity assertion on
the third-party-facing surface (`Integration.tools()` shape, `register()`
signature, `tool`/`function_tool` metadata keys) gated in the existing
`check_sdk_parity.py` before the tag.

**F4 (low). agentOS graduation is sequenced too eagerly.** The example README
gates `@kaji/agentos` on "demand appears and agentOS stabilizes," but the pin is a
churning `0.2.15` preview. Publishing it now, while rejecting the bridge on YAGNI
grounds, is inconsistent. Keep the docs value (link the example file); gate the
package publish on the README's own two conditions.

### Revised recommendation (supersedes the "Recommended sequencing" section above)

Decided at the `/autoplan` gate: **A0-lite before the tag** (user chose the middle
path over the models' full-A0 recommendation), F2 and F4 accepted.

Ship C first **with an A0-lite gate before the tag**, then the rest of A, with B
continuous:

- **A0-lite (before the beta tag): LANDED.** The cross-SDK parity assertion (F3)
  on the third-party-facing surface is built and green. Both parity exporters
  (`export_parity.py`, `export_parity.ts`) emit a `thirdPartyIntegrationSurface`
  descriptor by exercising the real path -- a two-tool sample `Integration`
  observed via `tools()` and via `register()` into a real `ToolRegistry` -- and
  `check_sdk_parity.py`'s three-way compare gates it (byte-identical across SDKs;
  verified to catch injected drift). The descriptor captures the drift-sensitive
  fields (surfaced `ToolSpec` key set, `parallel_safe`, `timeout_ms`,
  namespace-prefixed catalog names), with a `full` tool that sets every field and
  a `minimal` tool that sets only the required ones -- so the known
  TS-omits-defaults vs Python-carries-defaults divergence is caught. This is the
  one A item that gates the tag. The full out-of-tree fixture + package-author
  contract remain deferred to post-beta (below).
- **C (rest):** the beta checklist as written, plus the F2 line items (Python
  source-install gate on getting-started; explicit post-beta PyPI line).
- **A (rest, post-beta):** the out-of-tree fixture against the packed tarball, and
  the BYO-integration docs as a package-authoring/operations contract (not another
  subclass tutorial -- the READMEs already have one).
- **agentOS graduation:** deferred behind its own demand + stability gate (F4);
  keep the example file as the linked worked example until then.
- **No manifest-to-runtime bridge, no marketplace/discovery loader** (both voices
  endorse; unchanged).

**Note on the User Challenge:** both models recommended full A0 (the complete
out-of-tree fixture) as a pre-tag gate. The user chose A0-lite -- only the parity
assertion gates the tag -- accepting that the full fixture proof lands post-beta.
The parity assertion has landed (see A0-lite above); the named 6-month regret
(stable `Integration` ABI calcifying before the package boundary is externally
proven) is mitigated by it but not fully closed until the post-beta fixture
lands. That is the accepted tradeoff.

### Decision audit trail

| # | Phase | Decision | Classification | Principle | Rationale |
|---|-------|----------|----------------|-----------|-----------|
| 1 | strategy | Keep "no manifest-to-runtime bridge" | Mechanical | P4 DRY / YAGNI | Both voices endorse; subclass seam already covers it |
| 2 | strategy | Reframe A as closing the generality gap, deliverable = package-author contract | Mechanical | P1 completeness | READMEs already have subclass tutorials; the gap is packaging/ops |
| 3 | eng | A0-lite: cross-SDK parity assertion gates the tag (LANDED); full out-of-tree fixture deferred post-beta | User Challenge (user chose A0-lite over models' full-A0) | P1 + P2 | Both voices: beta marks Integration stable. User accepted the parity assertion as pre-tag insurance; assertion built + green, full fixture deferred |
| 4 | strategy | Add Python source-install gate + post-beta PyPI line item | Mechanical | P1 completeness | Beta publishes npm only; dual-language thesis half-true without it |
| 5 | eng | Defer agentOS graduation behind its README's demand+stability gate | Mechanical | P5 explicit / YAGNI | Preview-pinned publish contradicts the no-bridge YAGNI call |

