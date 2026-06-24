# apps/docs — kaji documentation site (Fumadocs)

date: 2026-06-07
status: approved

## summary

Stand up a Fumadocs documentation site at `apps/docs`, scoped to the kaji
SDK and written language-agnostically (concepts first, Python/TypeScript code as
illustration). Seed initial content from the existing `docs/KAJI.md`. Wire
the app into the existing Bun + Turbo monorepo so it behaves like the other
workspaces (`@ryo/web`, `@kaji/sdk`).

This is a documentation *site* for external developers consuming kaji
standalone. It is not ryo product docs, and it does not replace the loose
markdown under `docs/`.

## goals

- A navigable, non-empty Fumadocs site that builds and runs locally.
- Content grounded in what already exists (`docs/KAJI.md`), not invented.
- Repo-native: same package-name scheme, scripts, formatter, and Turbo wiring as
  sibling workspaces; one `bun install` at root pulls it in.
- Concepts documented language-neutrally so they stay true while the Python SDK
  and the TypeScript port (`@kaji/sdk`) continue to diverge in maturity.

## non-goals (YAGNI)

- No ryo documentation.
- No search backend beyond Fumadocs' built-in default (Orama). No Algolia.
- No deploy configuration (Vercel etc.). Local `dev` / `build` only.
- Do not move, edit, or delete the existing `docs/*.md` files. The site *seeds
  from* `docs/KAJI.md`; the original stays in place untouched.
- No dual-language code-sample parity guarantee. Use a tabbed code block only
  where a sample genuinely exists for both languages; otherwise show one and
  state the concept neutrally.

## scaffold approach

Use the official `create-fumadocs-app` scaffolder to generate `apps/docs`
(Next.js App Router + `fumadocs-core` + `fumadocs-ui` + `fumadocs-mdx`, MDX
content), then adapt it to repo conventions. The scaffolder is the source of
truth for the current known-good Fumadocs file layout; do not hand-roll the
Next.js + fumadocs wiring from memory.

Adaptations after scaffolding:

- `package.json`:
  - `name` → `@kaji/docs`
  - `private: true`, `version: 0.0.0`
  - scripts aligned to sibling workspaces:
    - `dev` — next dev
    - `build` — next build
    - `lint` — whatever the scaffold ships (Next lint / eslint); acceptable to
      leave as-is so long as `turbo run lint` does not error
    - `typecheck` — `tsc --noEmit` (add if the scaffold lacks it)
    - `format` — `oxfmt --write .`
    - `format:check` — `oxfmt --check .`
    - `clean` — `rm -rf .next .source node_modules/.tmp`
- `.gitignore` (app-local): `.next/`, `.source/` (Fumadocs generated), `out/`,
  and standard Next artifacts.
- `turbo.json` (root): add `.next/**` to the `build` task `outputs` if not
  already covered, or a `@kaji/docs#build` override mirroring the existing
  per-package override style. Keep `dev` non-cached + persistent (already the
  default `dev` task).
- The app joins the root `apps/*` workspace glob automatically. After scaffold,
  run one `bun install` at the repo root.

### scaffold risk / fallback

If `create-fumadocs-app` cannot run non-interactively or pulls an unexpected
layout, fall back to a minimal hand-built Next.js App Router app with
`fumadocs-core` / `fumadocs-ui` / `fumadocs-mdx` added manually, following the
current Fumadocs "manual installation" docs. Prefer the scaffolder.

## content structure

Seeded from `docs/KAJI.md`. Layout under the Fumadocs content root
(exact directory name follows whatever the scaffold uses, e.g.
`content/docs/`):

```
index.mdx              what kaji is; infra-free core; embed vs serve
getting-started.mdx    install (py + ts); minimal agent loop
concepts/
  events.mdx           append-only event log; wire-format type strings
  session-state.mdx    replay -> SessionState (isActive, messages)
  tool-registry.mdx    register spec + handler; scatter-gather concurrency
  event-bus.mdx        per-session fan-out; in-memory vs Redis
  providers.mdx        ModelProvider / TTSProvider protocols; STT
architecture.mdx       runtime (ReAct) loop diagram; modality edge diagram
reference-service.mdx  kaji-serve: api / bus-worker / worker over Redis
meta.json              nav order for the above
```

Content mapping from `docs/KAJI.md`:

- intro paragraph + "packages" table -> `index.mdx`
- "architecture" (both ASCII diagrams) -> `architecture.mdx`
- "core concepts" subsections -> one page each under `concepts/`
- "the reference service (kaji-serve)" -> `reference-service.mdx`
- "typescript SDK" notes folded into `index.mdx` / per-concept neutral phrasing,
  NOT a standalone "TS is missing X" page (that content goes stale fast)

### content correctness note

`docs/KAJI.md` line ~150 currently says the TypeScript reasoning loop and
LLM providers are "not yet ported." Recent commits and the current branch
(`feat/kaji-rag-persistence-ts-runtime`, plus
`feat(ts): add ModelProvider interface, registry, and MockProvider`) indicate
the TS runtime/providers are now in progress. To avoid shipping a claim that is
already stale, the site states concepts language-neutrally and does not assert a
fixed TS parity matrix. Do not copy the "not yet ported" sentence verbatim.

## prose style

Terse, technical, no em-dashes, no marketing slop (per saved user preference).
Lowercase headings are acceptable to match `docs/KAJI.md` voice, but follow
whatever the scaffold's example pages establish if it conflicts; consistency
within the site wins.

## branch / process

- Do the work on a dedicated branch (e.g. `feat/apps-docs-fumadocs`), not the
  current `feat/kaji-rag-persistence-ts-runtime` branch and not `main`
  (saved preference: never commit directly to main; always a named feat/ branch).
- The spec commit and all implementation commits land on that branch.

## verification

1. `bun install` at root succeeds with the new workspace present.
2. `bun --filter @kaji/docs dev` starts the dev server.
3. `bun --filter @kaji/docs build` (next build) passes.
4. `turbo run typecheck` and `turbo run lint` do not regress the workspace.
5. Dogfood with the gstack `/browse` skill: load the running dev site, click
   through the nav, open `index`, one `concepts/*` page, and `architecture`;
   confirm pages render and code blocks display. Fix render issues found.

Do not auto-ship. Building + local verification + browse dogfood only. A `/ship`
or `/review` pass happens only if explicitly requested.

## components / boundaries

- `apps/docs` is a self-contained workspace. It has no code dependency on
  `@kaji/sdk`, `@ryo/*`, or the Python packages. Its only coupling to
  the repo is: the `apps/*` workspace glob, root Turbo tasks, and the root
  formatter config it opts into.
- Content (MDX) is data, isolated under the content root. Swapping or extending
  pages does not touch app wiring.
- Source of truth for concepts remains the SDK source and `docs/KAJI.md`;
  this site is a presentation layer seeded from them, not a second authority.

## open risks

- Fumadocs/Next version drift vs. any remembered layout: mitigated by using the
  live scaffolder and the fallback path above.
- `oxfmt` may not understand MDX/Next idioms cleanly; if `format:check` fights
  the scaffold output, scope the formatter to the app's `.ts`/`.tsx` and leave
  MDX to Fumadocs/Prettier defaults rather than forcing oxfmt over everything.
- Next.js build output (`.next/`) and Fumadocs generated (`.source/`) must be
  gitignored and Turbo-aware to keep caching correct.
