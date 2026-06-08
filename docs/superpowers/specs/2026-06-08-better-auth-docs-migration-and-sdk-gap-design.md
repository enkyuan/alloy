# Better-Auth Docs Migration + SDK Gap Review — Design

Date: 2026-06-08
Status: Approved pending spec review

## Summary

Two deliverables:

- **Part A — Docs migration.** Migrate the better-auth docs app's design system
  (tokens, full `globals.css`, fonts, UI component library, MDX component specs,
  docs layout + custom sidebar) and a rebranded landing page into alloy's
  `apps/docs`, 1:1, branded to agentkit using the `shape-40.svg` logo.
- **Part B — SDK gap review.** A written gap analysis of the TypeScript SDK
  (`agentkit/ts`) vs the Python SDK (`agentkit/sdk/agentkit`), excluding serve,
  plus a prioritized plan to close the top gaps. No SDK code changes in this pass.

## Source / target

| | better-auth (source) | alloy (target) |
|---|---|---|
| Docs app | `/Users/Enkang.Yuan1/Desktop/Projects/better-auth/docs` | `apps/docs` |
| Framework | fumadocs 16.7.9 + Tailwind 4 + Next 16.2.6 | fumadocs 16.9.3 + Tailwind 4 + Next 16.2.7 |
| Styling source of truth | `app/globals.css` (954 lines) | `app/global.css` (184 lines) |
| Logo | 3D logo images + marks | `shape-40.svg` (agentkit mark) |

Both are fumadocs + Tailwind 4 apps, so the design layer is portable. alloy keeps
its own working content pipeline (`collections/server`, `source.config.ts`,
`proxy.ts`, `app/llms.txt`, `app/og`) — the migration swaps the *design* layer,
not the content/MDX wiring.

## Decisions (locked with user)

- **Scope:** design system + landing (not the full marketing site: no
  blog/pricing/products/enterprise/legal).
- **Dependencies:** match better-auth exactly (full radix/cva/framer/etc. set).
- **Landing:** same structure, rebranded to agentkit; placeholder data where
  agentkit specifics are unknown.
- **Sidebar:** literal 1:1 — copy `sidebar-content.tsx` + custom `docs-sidebar.tsx`,
  hand-author an agentkit nav tree mirroring `content/docs`, disable fumadocs'
  built-in DocsLayout sidebar.
- **Favicon:** remove text-based favicon/icon generation; user supplies favicon
  images manually. Keep `%s | agentkit` title metadata.
- **SDK:** report + propose plan, no code changes.
- **Execution:** spec → plan → phased execution with browse QA checkpoints.

## Part A — Docs migration

### A1. CSS / design tokens (full port)

Replace `apps/docs/app/global.css` with better-auth's `globals.css` content
verbatim:

- All `:root` OKLCH tokens + `.dark` overrides.
- `@theme inline` mapping (colors, radius scale, shadows, accordion keyframes).
- 20+ `@keyframes` (logo-snap, border-sparkle w/ `@property`, marquee variants,
  fadeInUp, shimmer, etc.).
- `@utility` blocks (`no-scrollbar`, `bg-grid`, `bg-grid-small`, `bg-dot`),
  `@layer utilities` (`.bg-noise-pattern`, `.bg-grid-black/white`, `.animate-fade-in`),
  npm-card gradient-border styles.
- Global scrollbar styling, `@layer base` overrides.
- `.docs-layout` / blog-layout fumadocs `--fd-*` overrides.
- Code-block flat treatment (`#050505` bg, no radius, subtle border).
- `prefers-reduced-motion` block.

Keep at top: alloy's `@import 'fumadocs-ui/css/black.css'` and
`@import 'fumadocs-ui/css/preset.css'` (better-auth uses the same presets).
Filename: keep alloy's `global.css` (layout.tsx imports `./global.css`), or rename
to `globals.css` and update the import — pick `global.css` to minimize churn.

### A2. Fonts (full port)

In `app/layout.tsx`: load `Geist` + `Geist_Mono` from `next/font/google` as
`--font-sans` / `--font-mono`, and `GeistPixelSquare` from `geist/font/pixel`.
Apply all three variables + `font-sans antialiased` to `<body>`. (alloy currently
uses `geist/font/sans` + `geist/font/mono` static imports — switch to the
`next/font/google` form to match better-auth and gain the pixel font.)

### A3. UI component library (full port)

Copy into `apps/docs/components/ui/` (all 22):
accordion, alert, badge, button, callout, card, checkbox, code-block, command,
drawer, dynamic-code-block, form, input, label, popover, scroll-area, select,
table, tabs, textarea, tooltip, use-copy-button.

- Replace `apps/docs/lib/cn.ts` (currently `export { twMerge as cn }`) with
  better-auth's `lib/utils.ts` (`cn` = `twMerge(clsx(...))` + `mergeRefs`). Update
  any importers (`@/lib/cn` → `@/lib/utils`).
- Copy `components.json` (shadcn config, baseColor stone, aliases).
- The existing minimal `components/ui/card.tsx` and `components/ui/callout.tsx`
  are replaced by the better-auth versions.

### A4. MDX components (port design, keep alloy wiring)

- Port better-auth's `components/docs/mdx-components.tsx` component set
  (`APIMethod`, `Endpoint`, `DatabaseTable`, `ForkButton`, `DividerText`,
  `GenerateSecret`, `GenerateAppleJwt`, `AddToCursor`, `Features`, plus the
  type-icon / schema-gen helpers) and `components/mdx/mermaid.tsx`.
- Wire them through alloy's existing `components/mdx.tsx` `getMDXComponents()`
  registration (merge into the returned map alongside fumadocs defaults), keeping
  alloy's `collections/server` + `source.config.ts` pipeline untouched.
- Auth-specific components (`GenerateSecret`, `GenerateAppleJwt`, `AddToCursor`)
  are ported for 1:1 fidelity but won't be referenced by agentkit content; that's
  acceptable.

### A5. Docs layout + custom sidebar (literal 1:1)

- Copy `components/sidebar-content.tsx` and author an **agentkit nav tree**
  mirroring `content/docs`: index, getting-started, architecture,
  reference-service, and the `concepts/` group (events, session-state,
  tool-registry, event-bus, providers). Assign lucide icons per section.
- Copy `components/docs/docs-sidebar.tsx`, `components/docs/custom-sidebar.tsx`,
  `components/docs/icons.tsx`, `components/version-switcher.tsx`,
  `components/theme-toggle.tsx`, `components/providers.tsx`,
  `components/search-dialog.tsx` (+ deps they pull: `lib/docs-versions.ts`).
- Rewire `app/docs/layout.tsx` to better-auth's shape: render the custom
  `<DocsSidebar />`, wrap children in `<DocsLayout>` with
  `nav/searchToggle/themeSwitch/sidebar` all `enabled: false` and
  `containerProps={{ className: "docs-layout" }}`.
- AI-chat components (`ai-chat.tsx`) are **out of scope** for the sidebar port
  (depend on ai-sdk keys + typesense). The "Ask AI" trigger may be omitted or
  rendered inert.

### A6. Landing page (rebranded structure)

- Port `app/page.tsx` (hero split layout) and `components/landing/*`:
  `hero-title`, `hero-readme`, `line-field-bg`, `signature-mark`,
  `staggered-nav-files`, `footer`, `trusted-by`, `framework-sections`,
  `halftone-bg`, `logo-context-menu`.
- Replace alloy's `app/(home)/page.tsx` "Hello World" with the ported hero.
  Decide: keep the `(home)` route group or move to `app/page.tsx` (better-auth
  uses `app/page.tsx`). Recommend `app/page.tsx` for 1:1; remove `(home)`.
- Rebrand all copy: "Better Auth" → "agentkit"; hero tagline → agentkit
  positioning ("Embeddable SDK for building agents…"); footer "© 2026 Better
  Auth Inc." → agentkit; links → alloy GitHub + `/docs`.
- **Live-data caveat (explicit):** `hero-readme.tsx` (2190 lines) and
  `trusted-by.tsx` embed better-auth npm download charts, GitHub contributor
  avatars, and partner logos. For visual 1:1: port the layout, wire agentkit's
  GitHub repo where applicable, and use static/placeholder data for npm-downloads
  chart and the partner marquee. These are visually identical but not live.

### A7. Logo / favicon

- Save `shape-40.svg` as the agentkit mark (e.g. `components/icons.tsx`
  `AgentkitMark`, or `public/logo.svg`). The mark uses `#FF6E3C` fills; provide a
  `currentColor` variant for nav/theming where better-auth used `currentColor`,
  and the brand-orange variant for the hero.
- Replace `AgentkitMark` usages (nav title) with the shape-40 mark.
- **Remove text-based favicon/icon generation.** Search for and remove any
  `app/icon.tsx`/`app/apple-icon.tsx`/favicon text routes (alloy currently has
  none — confirm and leave a clean slot). Keep `app/og` route (page OG images)
  unless it renders the brand text-favicon; user adds favicon image files manually.

### A8. Config

- `next.config.mjs`: keep alloy's `createMDX()` + `reactStrictMode`; merge in
  better-auth's `experimental.optimizePackageImports` (lucide, framer-motion,
  radix tabs/scroll-area/popover/select/checkbox) and `images.remotePatterns`.
  Do **not** copy better-auth's auth-specific `redirects()`.
- Adopt `components.json`.
- Keep alloy's `tsconfig.json` paths (`@/*`, `collections/*`), `proxy.ts`,
  `source.config.ts`.

### A9. Dependencies (match better-auth exactly)

Add to `apps/docs/package.json` the better-auth dependency set: full `@radix-ui/*`
suite, `class-variance-authority`, `clsx`, `cmdk`, `framer-motion`, `next-themes`,
`sonner`, `vaul`, `tw-animate-css`, `tailwindcss-animate`, `recharts`, `mermaid`,
`shiki`, `react-hook-form` + `@hookform/resolvers` + `zod`, `embla-carousel-react`,
`lucide-react`, `@vercel/analytics`, etc. Install with **bun** (per repo
convention). Reconcile versions with alloy's newer fumadocs (16.9.3) / Next
(16.2.7) — keep alloy's newer pins where they conflict.

### A10. Verification (per-phase checkpoints)

After each phase: `bun run typecheck` + `bun run lint` in `apps/docs`, then
`bun run dev` and browse QA via the `/browse` skill (gstack) on `/` and `/docs`.
Final: `bun run build` clean, visual diff of `/docs` and `/` against better-auth
running locally.

## Part B — SDK gap review

### B1. Deliverable

A written report at `docs/sdk-gap-analysis.md` (repo docs, not the spec dir) plus
a prioritized closure plan. No code changes to either SDK in this pass.

### B2. Findings (from triage — to be written up)

Surface mapping done. TS (`agentkit/ts/src`) mirrors the Python event-sourced core
(events, store, bus, replay, tools, runtime loop, mock provider, cancellation) but:

**Missing in TS:** real LLM providers (openai/kimi/gemini), voice/STT/TTS
modalities, knowledge/RAG, core infra (config/redis/db/auth/observability),
SessionManager/SessionStore, AgentStrategy config, ToolPlanner, Swarm, neutral
tool-payload translators (`to_openai`/`to_gemini`).

**Alignment issues (18 total)** — key ones:

1. `ToolContext` field `userId` (TS) vs `user_id` (Python).
2. Provider tool-call shape `{id,name,args}` (TS) vs `{name,arguments,id}` (Python).
3. Replay carries `toolCallId` onto messages (TS) but Python drops it.
4. TS replay intentionally skips `TOOL_CALL_FAILED`; Python projects it as an
   error tool message.
5. `EventBus.publish()` returns `void` (TS) vs message/stream id (Python);
   `subscribe()` lacks `last_id`/`block_ms`.
6. Provider `generate()` lacks temperature/max_tokens/response_format/metrics (TS).
7. Tool-result stringification: `JSON.stringify` (TS) vs `str()` repr (Python).
8. TOOL_CALL_REQUESTED emit ordering differs (batch-after-stream vs per-tool).
9. CancellationToken: boolean + `throwIfCancelled()` (TS) vs asyncio.Event poll.
10. No `send()` convenience in TS; hardcoded MAX_TOOL_ITERATIONS=10 vs AgentStrategy.

**Critical cross-SDK divergences:** event default generation, tool-call field
names, replay tool_call_id threading, failure-event projection, and emit ordering
mean event logs are **not byte-for-byte replayable across SDKs** today.

### B3. Proposed closure plan (prioritized, to be detailed in report)

- **P0 (wire compat):** align tool-call shape (`args`↔`arguments`), decide a single
  `tool_call_id` threading + `TOOL_CALL_FAILED` projection policy, align replay
  stringification. These break cross-SDK replay.
- **P1 (capability parity):** port a real provider to TS (OpenAI first) + the
  neutral tool-payload translators; add provider `generate` params + metrics.
- **P2 (API ergonomics):** `userId`/`user_id` convention decision, AgentStrategy
  config in TS, `send()` convenience, EventBus return-value parity.
- **P3 (larger ports):** voice/STT/TTS, knowledge/RAG, SessionManager/Store, Swarm,
  durable (Redis) bus — scoped as follow-on projects.

## Out of scope

- Full marketing site (blog, pricing, products, enterprise, legal pages).
- AI-chat / command-menu functional wiring (typesense, ai-sdk keys).
- Live npm/GitHub stats on the landing (static/placeholder data instead).
- Any SDK code change (Part B is report + plan only).
- Adding favicon image files (user does this manually).

## Risks

- **Version skew:** alloy is on newer fumadocs/Next than better-auth; ported
  components may reference fumadocs internals that shifted between 16.7.9 and
  16.9.3. Mitigation: typecheck after the UI-lib phase, before the layout phase.
- **Tailwind 4 token collisions:** both define `@theme inline`; the full replace
  avoids merge conflicts but must be verified against fumadocs preset cascade.
- **Landing size:** `hero-readme.tsx` (2190 lines) is large and better-auth-coupled;
  rebranding may need section-level edits, not just string swaps.
