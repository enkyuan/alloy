# Landing page rebrand + content accuracy — design

Date: 2026-06-09
Branch: feat/docs-restyle-2

## Problem

The agentkit docs landing page (`apps/docs/app/page.tsx` + `components/landing/*`)
is a port of the better-auth landing page. The visual shell was rebranded, but
large amounts of better-auth *content* remain: the README intro paragraph, the
entire Features grid (Email & Password, SSO, Passkeys, Organizations…), the
"Framework — most comprehensive authentication framework for TypeScript"
section, the footer CTA ("Roll your own auth…"), a "Trusted By" logo strip, a
better-auth watermark logo in the footer, and a CLI tab advertising a
nonexistent `npx auth init`.

A round of page feedback (8 items, captured via the agentation toolbar) calls
these out. This spec covers those 8 items plus the directly-adjacent residue
they imply.

## Ground truth: what agentkit actually is

From `README.md` and `docs/ROADMAP.md`:

- agentkit = an **embeddable agent SDK** (Python `agentkit` + TypeScript
  `@agentkit/sdk`), powering agentpay's runtime but usable standalone.
- Real, shipped capabilities: event-sourced agent loop (`AgentRuntime`),
  tool registry + provider-neutral tool payloads, pluggable LLM providers
  (OpenAI, Kimi, Gemini — Anthropic is MISSING/roadmap), STT/TTS voice
  modalities, RAG tool retriever, replay/projection, in-memory + Redis event
  bus.
- There is **no CLI yet**. Install is `pip install agentkit` /
  `bun add @agentkit/sdk`.
- The existing `aiPromptText` constant (hero-readme.tsx:25–40) is already
  correct agentkit copy and is the tone reference.

## Decisions (confirmed with user)

1. Features grid → **SDK capabilities** drawn from the ground-truth list above.
2. CLI tab → show the **real install command** (`pip install agentkit` /
   `bun add @agentkit/sdk`), and add a "CLI / scaffold `init`" item to
   `docs/ROADMAP.md` as future work.
3. Workflow → spec then implement.

## better-auth setup pattern (research, for the CLI tab — item 3)

better-auth's pattern: one root binary (`npx auth@latest <cmd>`) with
`init` / `generate` / `migrate` / `secret` subcommands; the install step is a
single copy-paste command shown in package-manager tabs (npm/pnpm/yarn/bun);
canonical sequence is install → env (`BETTER_AUTH_SECRET`) → create instance →
mount handler → generate/migrate schema. agentkit has no schema/migration step
and no CLI, so we collapse this to: **install command now**, with the
`init`-style scaffold deferred to the roadmap.

## Scope — the 8 feedback items

All in `apps/docs`.

| # | Element | File | Action |
|---|---------|------|--------|
| 1 | `cursor-pointer` 68×52 element top-left of left column | (agentation toolbar anchor — NOT our code) | **Flag to user, no change.** The `<Popper><PopoverAnchor>` React stack is agentation's own toolbar trigger, not a landing element. "Flex horizontally" has no clear target in our source. Confirm before touching. |
| 2 | "Trusted By" divider + `<TrustedBy />` logo strip | `hero-readme.tsx` ~966–973 | **Remove** the divider block and the `<TrustedBy />` render. Leave the `trusted-by.tsx` component file in place (unused) unless user wants it deleted. |
| 3 | InstallBlock CLI tab (`npx auth init`) + Skills tab | `hero-readme.tsx` 143–647 | CLI tab → real install command. **Remove the Skills tab** entirely (button + `mode` union member + `skills` branches). Add CLI scaffold item to ROADMAP. |
| 4 | README intro paragraph ("Auth that lives inside your app…") | `hero-readme.tsx` 951–962 | **Rewrite** to describe agentkit accurately. |
| 5 | "Features" grid (auth features) | `hero-readme.tsx` 982–1049 (data) | **Rewrite the 9 feature cards** to SDK capabilities. Preserve the grid layout, hover/animation chrome, and per-card illustration *slots* — remap illustrations where one fits, drop illustration where none fits (text-only card). |
| 6 | Footer watermark = better-auth "B" logo SVG | `hero-readme.tsx` 815–828 | **Swap** the inline path for the agentkit logomark SVG, same size/opacity/positioning. Source the agentkit mark from `components/icons/logo.tsx`. |
| 7 | Footer CTA copy ("Roll your own auth…") | `hero-readme.tsx` 844–846 | **Rewrite** to agentkit copy. |
| 8 | `/logo.svg` hero mark behind the big title | `app/page.tsx` 19–30 | **Remove** the hero-mark `<div>` (the centered watermark behind "The embeddable SDK for building agents"). |

## Adjacent residue (NOT in the 8 items) — flag, don't auto-fix

These are more better-auth content the feedback did not flag. I will list them
for the user and only act if asked, to keep this change scoped:

- `hero-readme.tsx` ~1592–1602: "Framework — The most comprehensive
  authentication framework for TypeScript." section.
- `hero-readme.tsx` ~1604–1715+: framework tabs pulling in `DatabaseSection`,
  `SocialProvidersSection`, `IntegrationsSection`, `PluginEcosystem` from
  `framework-sections.tsx` — all auth-themed.
- The `frameworkTab` union (`declarative | database | oauth | integrations`)
  and `socialHovered` state.
- `mcpCommands` (hero-readme.tsx:18–23) still uses `npx auth mcp …`.

The MCP tab (`npx auth mcp`) — item 3 only named CLI + Skills, but `auth mcp`
is the same residue; I'll rebrand the command strings to `npx agentkit mcp`
style as part of item 3 since it's the same InstallBlock and leaving it
half-rebranded would be incoherent.

## Components / data flow

No architectural change. `HeroReadMe` stays one (large) client component;
`InstallBlock` loses one tab (`skills`) shrinking its `mode` union to
`"cli" | "prompt" | "mcp"`. The Features grid stays a `.map()` over a data
array — only the array contents and per-card illustration flags change.

The footer watermark becomes a shared mark: rather than inline-duplicating the
SVG, reuse the logomark already defined in `components/icons/logo.tsx`
(confirm an icon-only mark export exists; if only `AgentkitWordmark` exists,
extract the glyph `<path>` into the watermark inline, matching current
`viewBox`/sizing).

## Testing / verification

- `cd apps/docs && ~/.bun/bin/bun run typecheck` must stay green (the existing
  `apps/web` input.tsx error is unrelated and not in this app).
- `grep -rin "better.\?auth\|Roll your own\|Trusted By\|npx auth"
  apps/docs/components apps/docs/app` returns no user-visible auth residue
  within scoped files.
- Visual check via `bun run dev` (left to user / a follow-up `/qa` pass):
  README panel reads as agentkit, no Trusted By strip, no Skills tab, footer
  CTA + watermark rebranded, no logo behind hero title.

## Out of scope

- Item 1 (agentation toolbar) — flagged, no change without confirmation.
- The deeper Framework/framework-sections residue — flagged, no change without
  confirmation.
- Deleting now-unused component files (`trusted-by.tsx`) — leave in place.
- Building an actual agentkit CLI — roadmap entry only.
