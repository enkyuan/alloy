# apps/docs — better-auth rework (round 2: tokens + components + chrome)

date: 2026-06-08
status: approved

## summary

A second pass to make `apps/docs` more closely resemble the better-auth docs
site. Round 1 swapped the fumadocs theme to `black.css` and the fonts to Geist.
This round adds the parts that still differ: the design-token layer (full
shadcn-style token set), layout chrome (richer nav, density, textured
background), original MDX/UI components, and a real home page.

Scope decisions (from brainstorming):
- Depth: layout config + density tuning. Keep fumadocs' `DocsLayout`; do NOT
  rebuild a fully custom sidebar with `enabled:false`.
- Tokens: full shadcn token set (colors, charts, sidebar tokens, radius,
  spacing, shadows) via `@theme inline`, layered onto `black.css`.
- Components: write ORIGINAL kaji components, using better-auth's structure
  only as reference.

## IP / licensing boundary (important)

better-auth is MIT-licensed. This rework ADAPTS design-token *values* (color,
radius, spacing, shadow numbers — factual design configuration) and layout
*structure/config*. It does NOT copy better-auth's component source files
(`custom-sidebar.tsx`, `docs-sidebar.tsx`, `features.tsx`, etc.) verbatim. All
React components are written fresh for kaji. The better-auth checkout stays
a read-only /tmp reference; nothing of theirs is committed verbatim.

## context / current state

- `apps/docs/app/global.css`: imports `tailwindcss`, `fumadocs-ui/css/black.css`,
  `preset.css`, plus a `:root` mapping `--font-sans`/`--font-mono` to Geist.
- `apps/docs/lib/layout.shared.tsx`: `baseOptions()` returns only
  `{ nav: { title: appName }, githubUrl }`.
- `apps/docs/app/docs/layout.tsx`: plain `DocsLayout` with `baseOptions()`.
- `apps/docs/app/(home)/page.tsx`: a "Hello World" placeholder.
- `apps/docs/components/mdx.tsx`: passes through fumadocs default MDX components
  (content uses no custom components).

better-auth's distinctive feel (from their globals.css, MIT) comes from:
`--radius: 0.2rem` (crisp near-square corners), `--fd-nav-height: 56px`,
`--fd-page-width: 900px`, `--fd-toc-width: 280px`, `--spacing: 0.25rem`, a full
shadcn color-token set mapped via `@theme inline`, a low-opacity shadow scale,
and a subtle grid/noise textured background.

## goals

- The site visibly resembles better-auth: crisp corners, denser narrower reading
  column, enriched top nav, subtle textured background, consistent token-driven
  components.
- A full shadcn token layer is available so components use `bg-card`,
  `border-border`, `rounded-md`, etc.
- A real (small) kaji home page replaces "Hello World".
- No framework change, no AI chat, no Typesense, no Framer Motion, no marketing
  pages beyond the single home page. Stays on Next.js + fumadocs.

## non-goals (YAGNI)

- No fully custom sidebar component (keep fumadocs' `DocsLayout` sidebar).
- No AI chat / command menu / version switcher / Typesense.
- No Framer Motion animations or better-auth's noise-filter logo animations.
- No marketing pages (pricing, blog, careers).
- No content rewrites (round 1 already did Title Case + frontmatter). Content
  `.mdx` under `content/docs/` is untouched except where a new MDX component is
  demonstrably needed (none expected).
- Do NOT copy better-auth component source verbatim.
- Do NOT commit the /tmp better-auth reference.

## file changes

### 1. Design tokens — `apps/docs/app/global.css`

Apply the COMPLETE better-auth design-token set (user requirement: the full set,
not a subset). Keep the existing `@import` lines (tailwindcss, black.css,
preset.css) and the Geist `:root` font mapping. The token VALUES are copied
verbatim-accurate from better-auth's `globals.css` (these are CSS configuration
values, not component code). Add all of:

- A `:root` block with the FULL light-theme token set: `--background`,
  `--foreground`, `--card`(+`-foreground`), `--popover`(+`-foreground`),
  `--primary`(+`-foreground`), `--secondary`(+`-foreground`),
  `--muted`(+`-foreground`), `--accent`(+`-foreground`),
  `--destructive`(+`-foreground`), `--border`, `--input`, `--ring`,
  `--chart-1..5`, the full `--sidebar*` set (sidebar, -foreground, -primary,
  -primary-foreground, -accent, -accent-foreground, -border, -ring),
  `--scrollbar-thumb`/`-hover`/`-track`, `--radius: 0.2rem`, the full shadow
  scale (`--shadow-2xs` through `--shadow-2xl`), `--tracking-normal: 0em`,
  `--spacing: 0.25rem`, and the layout vars `--landing-topbar-height`,
  `--fd-nav-height: 56px`, `--fd-banner-height`, `--fd-tocnav-height`. Use the
  exact oklch/hsl values from better-auth's `:root`.
- A `.dark` block with the FULL dark-theme token set: every token above that
  better-auth overrides in `.dark` (background, foreground, card, popover,
  primary, secondary, muted, accent, destructive, border, input, ring,
  chart-1..5, the sidebar set, scrollbar vars, and the shadow scale), using
  better-auth's exact `.dark` values.
- An `@theme inline` block mapping ALL `--color-*` to the tokens (background,
  foreground, card, popover, primary, secondary, muted, accent, destructive,
  border, input, ring, chart-1..5, the full sidebar set), the
  `--radius-sm/md/lg/xl` scale derived from `--radius`, the full `--shadow-*`
  passthrough, `--breakpoint-navbar: 64rem`, and the accordion animation tokens
  (`--animate-accordion-down/up` + the `@keyframes accordion-down/up`).
- The narrower content/toc dimensions to match better-auth's density (page width
  and `--fd-toc-width`).
- A subtle grid/texture background utility applied to the body or layout
  container (low opacity, theme-aware), recreating better-auth's textured feel
  with an ORIGINAL small SVG/CSS (not their exact asset).

Completeness gate: the verification dogfood must confirm the token block is the
full set (spot-check that `--card`, `--primary`, `--muted`, `--chart-1`, the
`--sidebar*` set, `--radius: 0.2rem`, and the shadow scale are all present in
both `:root` and `.dark`, and resolvable as Tailwind utilities `bg-card`,
`bg-primary`, `text-muted-foreground`, `rounded-md`).

Reconciliation note: `black.css` already sets fumadocs `--color-fd-*` tokens.
The new shadcn `--color-*` tokens are ADDITIVE (different namespace). Where they
overlap conceptually (background/foreground), ensure the shadcn values are
visually consistent with black.css so the page does not look two-toned. Verify
in the dogfood; adjust token values minimally if there is a clash.

### 2. Nav chrome — `apps/docs/lib/layout.shared.tsx`

Enrich `baseOptions()`:
- `nav.title`: a small logo mark + `appName` (use a new `components/icons.tsx`
  brand mark, or text if simpler).
- `links`: top-nav links (e.g. Docs -> /docs; optionally an external link).
- Keep `githubUrl`. Ensure search and theme toggle remain enabled (fumadocs
  defaults) so the nav has the better-auth-style control cluster.

### 3. Docs layout density — `apps/docs/app/docs/layout.tsx`

Pass `containerProps`/sidebar options to tighten spacing to match the token
dimensions. Keep `tree={source.getPageTree()}` and `baseOptions()`. Do NOT set
`sidebar.enabled:false` (we keep fumadocs' sidebar).

### 4. MDX components — `apps/docs/components/mdx.tsx` (+ new files as needed)

Extend the MDX component map beyond pass-through with ORIGINAL components styled
via the new tokens: callout/note, card + cards grid, styled tables/links/inline
code. Only add components the content can actually use; do not over-build. If a
component is added, it may be lightly demonstrated on the home page rather than
forcing it into existing content pages.

### 5. Home page — `apps/docs/app/(home)/page.tsx`

Replace "Hello World" with a small, original kaji front door: a hero line
(what kaji is), a couple of feature cards using the new card component, and a
clear CTA to `/docs`. Token-driven styling. NOT a full marketing landing.

### 6. New component files (original)
- `apps/docs/components/icons.tsx` — brand/logo mark (simple original SVG).
- Possibly `apps/docs/components/mdx/*` — callout, card, etc. Keep small and
  focused; one responsibility per file.

## prose / brand

Brand `kaji` stays lowercase. No em-dashes in any prose added (home page
copy). Terse, technical.

## branch / process

- New branch `feat/docs-restyle-2` off `main`.
- Use bun for all package ops (none expected; no new deps planned — if a tiny
  utility is needed, prefer existing deps like `clsx`/`tailwind-merge` already in
  the tree, added via `bun add` only if truly required).
- Commit in logical units: tokens, then chrome/layout, then components, then home
  page.

## verification

1. `bun --filter @kaji/docs build` passes (all pages compile).
2. `bun --filter @kaji/docs typecheck` passes.
3. `turbo run lint --filter=@kaji/docs` and `format:check` do not regress.
4. Clean-clone build: `git archive HEAD apps/docs | tar -x` into a temp dir,
   `bun install && bun run build` -> exit 0 (catch untracked files, esp. new
   components/ files and any lib/ files vs the Python lib/ gitignore rule).
5. `/browse` dogfood in BOTH light and dark mode: confirm crisp `0.2rem` corners,
   denser/narrower reading column, enriched nav (logo, links, GitHub, search,
   theme), subtle textured background, the new home page, and that code blocks +
   sidebar still render. Compare side by side with the live better-auth docs.
   Confirm no two-toned color clash between shadcn tokens and black.css. Fix
   issues, rebuild, reload.

Do not auto-ship. Build + clean-clone + browse dogfood only.

## components / boundaries

- Tokens live in `global.css`. Nav config in `layout.shared.tsx`. Layout density
  in `docs/layout.tsx`. UI components in `components/`. Each file one
  responsibility. Content is untouched data.
- New components depend only on tokens + existing deps (clsx/tailwind-merge,
  fumadocs-ui). No new heavy dependencies.

## open risks

- shadcn tokens vs black.css clash (two-toned look). Mitigation: keep shadcn
  background/foreground visually consistent with black.css; verify in dogfood;
  adjust token values minimally, do not rip out black.css.
- New files under `apps/docs/components/` are fine, but watch the root
  `.gitignore` Python `lib/` rule if any file lands under a `lib/` dir (the docs
  app's lib/ is already negated/tracked; new lib/ files should be fine, but the
  clean-clone build in verification will catch a regression).
- oxfmt over `.ts`/`.tsx` only; MDX/CSS not formatter-touched. Keep new TSX
  formatted.
