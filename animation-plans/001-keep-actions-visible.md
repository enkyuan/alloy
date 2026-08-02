# 001 — Keep actions visible during first-visit motion

- **Status**: DONE
- **Commit**: 4dd04a1c
- **Severity**: MEDIUM
- **Category**: Purpose, frequency, and cohesion
- **Estimated scope**: 2 source files, 1 focused test

## Problem

The first-visit entrance targets `.heading-container`, which contains both the
decorative hero title and the actionable install link:

```astro
<!-- apps/docs/src/pages/index.astro:28 — current -->
<div class="heading-container">
  <h1 class="hero-title">...</h1>
  <a class="install-snippet" href="/docs/install">...</a>
</div>
```

```css
/* apps/docs/src/styles/global.css:1204 — current */
html[data-kaji-first-visit] .overview-article .heading-container,
html[data-kaji-first-visit] .overview-article > header .tagline {
  animation: home-enter 360ms var(--ease-out) both;
}
```

This makes the install link visually unavailable during decorative motion.
The wordmark animation also applies to both the non-interactive current-page
mark and the linked wordmark shown on other documentation routes.

## Target

Keep every action visible immediately:

```css
html[data-kaji-first-visit] span.kaji-wordmark .wordmark-glyph {
  animation: wordmark-write 620ms var(--ease-out) both;
}

html[data-kaji-first-visit] .overview-article .hero-title,
html[data-kaji-first-visit] .overview-article > header .tagline {
  animation: home-enter 360ms var(--ease-out) both;
}
```

- Animate the wordmark only when it is the non-interactive current-page
  `<span>`.
- Leave `.install-snippet` and linked wordmarks visible immediately.
- Use an 80ms cadence: wordmark glyph delays of 60ms and 140ms; hero title and
  tagline delays of 120ms and 200ms.
- Preserve `--ease-out: cubic-bezier(0.23, 1, 0.32, 1)`.
- Preserve the existing 160ms, zero-delay, opacity-only reduced-motion
  fallback.

## Repo conventions to follow

- First-visit state is owned by
  `apps/docs/src/layouts/base.astro:42-69`.
- Motion tokens and reduced-motion handling live in
  `apps/docs/src/styles/global.css`.
- One-shot entrance sequences use CSS keyframes; route preparation removes
  `data-kaji-first-visit` to interrupt them.

## Steps

1. In `apps/docs/src/styles/global.css`, scope wordmark entrance and its
   reduced-motion selector to `span.kaji-wordmark`.
2. Change the hero entrance selector from `.heading-container` to
   `.hero-title`, including the reduced-motion selector.
3. Tighten the second glyph delay from 180ms to 140ms and the tagline delay
   from 220ms to 200ms.
4. Add a focused contract test proving actions remain outside first-visit
   selectors and broad navigation/content stagger remains absent.

## Boundaries

- Do NOT animate sidebar navigation items or lower root sections.
- Do NOT change `base.astro`, Astro routing, Agentation, or runtime-demo
  lifecycle behavior.
- Do NOT add dependencies.
- Do NOT alter layout, typography, color, or content.
- If the cited selectors have drifted, stop instead of improvising.

## Verification

- **Mechanical**:
  - `bun run --cwd apps/docs format:check`
  - `bun run --cwd apps/docs lint`
  - `bun run --cwd apps/docs typecheck`
  - `bun run --cwd apps/docs build`
  - Run the focused docs-motion contract test.
- **Feel check**:
  - In a fresh browser session on `/`, confirm the install link is fully
    visible while the title and non-linked wordmark enter.
  - On a fresh session landing on `/docs`, confirm the linked wordmark is
    static and visible.
  - Navigate before entrance completion and confirm Astro navigation starts
    immediately.
  - Emulate `prefers-reduced-motion: reduce`; confirm a 160ms opacity-only
    entrance with no translation.
  - At 10% playback speed, confirm the two decorative stagger gaps are 80ms.
- **Done when**: all actions are visible from the first rendered frame,
  decorative first-visit motion remains one-shot and interruptible, reduced
  motion is spatially static, and the docs gates pass.
