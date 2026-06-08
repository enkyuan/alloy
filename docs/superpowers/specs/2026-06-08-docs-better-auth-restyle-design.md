# apps/docs — better-auth restyle + content polish

date: 2026-06-08
status: approved

## summary

Restyle the existing `apps/docs` Fumadocs site to resemble the better-auth docs
site, and polish the agentkit content using better-auth's writing patterns. Stay
on Next.js + Fumadocs (no framework migration). This is an in-place reskin of the
app built on `feat/apps-docs-fumadocs`, not a re-clone.

Two independent workstreams:
1. **Styling**: adopt better-auth's docs look (fumadocs-ui `black` theme preset +
   Geist Sans/Mono fonts).
2. **Content**: convert all-lowercase prose to proper Title Case / sentence case,
   and rewrite thin `description:` frontmatter into rich better-auth-style
   sentences. Keep the 9 pages, structure, code samples, and facts as-is.

## context / findings

better-auth's `docs/` directory (sparse-cloned to /tmp for reference) is a
416-file, 123-dependency product: marketing landing, pricing, careers, blog,
changelog, community pages, AI chat, command menu, Typesense search, version
switcher. The docs section is one slice. Per the scope decision, we take ONLY the
docs-relevant styling, not the marketing/blog/search machinery.

The better-auth docs "look" decomposes to a small set of essentials:
- `app/globals.css` imports `fumadocs-ui/css/black.css` + `preset.css` (the
  monochrome high-contrast theme). The rest of their globals.css is landing-page
  animation/noise/grid utilities we are NOT bringing over.
- `app/layout.tsx` uses Geist Sans + Geist Mono (via the `geist` package), wired
  as `--font-sans` / `--font-mono` CSS variables.

Our current app uses `fumadocs-ui/css/neutral.css` and Inter. The visual delta is
almost entirely: theme preset (neutral -> black) + fonts (Inter -> Geist).

Our content uses ZERO custom MDX components (verified: no JSX tags in content/),
only markdown, tables, and fenced code. So no custom MDX components need porting;
fumadocs-ui defaults already render everything.

better-auth writing patterns worth adopting (the parts in scope):
- Title Case in `title:` frontmatter and section headings.
- Rich, specific `description:` frontmatter (full sentences listing what the page
  covers).
- Proper sentence case in body prose.

## goals

- The site visually resembles better-auth's docs: black theme, Geist typography.
- Content reads professionally: Title Case headings, sentence-case prose, rich
  descriptions.
- No framework change, no marketing pages, no new search backend, no blog.
- Builds clean from a fresh clone; all monorepo gates stay green.

## non-goals (YAGNI)

- No framework migration (stays Next.js + Fumadocs). The earlier TanStack idea is
  dropped.
- No marketing landing page, pricing, careers, blog, changelog, community pages.
- No AI chat, command menu, version switcher.
- No Typesense or Algolia; keep fumadocs' built-in Orama search.
- No custom MDX components (content doesn't use any).
- No landing-page animation utilities (noise texture, grid backgrounds, logo
  animations) from better-auth's globals.css.
- No content restructure or page expansion (that was the rejected option). This
  is casing + frontmatter polish only.
- Do NOT commit the sparse-cloned better-auth reference (stays in /tmp).

## file changes

### Styling

1. `apps/docs/app/global.css`
   - Change `@import 'fumadocs-ui/css/neutral.css';` to
     `@import 'fumadocs-ui/css/black.css';`. Keep the `preset.css` import and the
     existing scrollbar-gutter / body-scroll-lock rules.
   - Optionally add the `--font-sans` / `--font-mono` family wiring if not handled
     entirely in layout (see step 2). Keep this minimal.

2. `apps/docs/app/layout.tsx`
   - Replace the Inter font with Geist Sans + Geist Mono from the `geist` package
     (`geist/font/sans`, `geist/font/mono`), matching better-auth. Apply the font
     CSS variables to `<html>` / `<body>` so fumadocs-ui picks them up
     (`--font-sans`, `--font-mono`).
   - Keep the existing `metadata` export (title template + description) and
     `RootProvider`.

3. `apps/docs/package.json`
   - Add `geist` to dependencies via `bun add geist` (run inside the workspace).
     USE BUN, not npm.

### Content (9 MDX files under `apps/docs/content/docs/`)

For each of: `index.mdx`, `getting-started.mdx`, `architecture.mdx`,
`reference-service.mdx`, `concepts/events.mdx`, `concepts/session-state.mdx`,
`concepts/tool-registry.mdx`, `concepts/event-bus.mdx`, `concepts/providers.mdx`:

4. **Title Case** the `title:` frontmatter and all section headings
   (`## ...`, `### ...`). Capitalize major words.
5. **Sentence case** the body prose: capitalize the start of each sentence and
   proper nouns. The body is currently all-lowercase; make it read normally.
6. **Rich `description:` frontmatter**: rewrite each thin description into a
   specific better-auth-style sentence describing what the page covers.

PRESERVE verbatim (do NOT case-change): the brand `agentkit`, package names
(`agentkit-serve`, `@agentkit/sdk`), code identifiers (`replaySession`,
`InMemoryEventBus`, `ModelProvider`, `ToolContext`, etc.), env vars
(`AGENTKIT_MODEL_PROVIDER`), event type strings (`user.message`,
`tool.call.completed`), file paths, and everything inside code fences.

Keep: the 9 pages, their structure, code samples, language-neutral framing, the
`gemini` provider entry, no em-dashes, all internal links and meta.json nav.

## prose style

No em-dashes (use periods, commas, or spaced hyphens). Title Case headings,
sentence-case prose. Terse and technical. The all-lowercase house style used
before is REPLACED by proper casing per the user's explicit request.

## branch / process

- New branch `feat/docs` off the current `feat/apps-docs-fumadocs`.
- Use bun for all package operations (`bun add geist`, `bun install`,
  `bun --filter @agentkit/docs <script>`). Never npm.
- Commit styling and content as separate logical commits.

## verification

1. `bun add geist` succeeds in the workspace; `bun install` at root clean.
2. `bun --filter @agentkit/docs build` passes (next build, all pages compile).
3. `bun --filter @agentkit/docs typecheck` passes.
4. `turbo run lint --filter=@agentkit/docs` and `format:check` do not regress.
5. Clean-clone build: `git archive HEAD apps/docs | tar -x` into a temp dir,
   `bun install && bun run build` -> exit 0 (catches any untracked file).
6. `/browse` dogfood: load the running dev site, confirm the black theme and
   Geist fonts render, the sidebar/nav still work, code blocks render, and the
   look broadly resembles the live better-auth docs (compare side by side). Fix
   render issues. Confirm headings now read in Title Case.

Do not auto-ship. Build + clean-clone + browse dogfood only.

## components / boundaries

- Styling is isolated to `global.css` + `layout.tsx` + `package.json`. Content is
  data under `content/docs/`. Changing one does not touch the other.
- No new coupling to the monorepo. The app remains a self-contained `apps/*`
  workspace.
- The better-auth source stays a read-only /tmp reference; nothing from it is
  committed verbatim except the two specific styling choices (black theme, Geist).

## open risks

- `geist` package version / Next 16 compatibility: if `geist/font` has issues with
  Next 16, fall back to `next/font/google` Geist (same fonts, different import).
  Note in the plan as a fallback.
- The `black` theme may need a token tweak if contrast is too aggressive against
  fumadocs-ui 16.9 defaults; adjust minimally in global.css if the dogfood shows
  a problem. Do not rebuild the theme.
- oxfmt over `.ts`/`.tsx` only (unchanged from prior scope); MDX content is not
  formatter-touched.
