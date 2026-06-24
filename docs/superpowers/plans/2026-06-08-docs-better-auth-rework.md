# apps/docs better-auth Rework (round 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply better-auth's complete design-token set to `apps/docs`, enrich the layout chrome (nav, density, textured background), add original kaji UI/MDX components, and replace the placeholder home page.

**Architecture:** Layer a full shadcn-style token set (light `:root` + `.dark` + `@theme inline`) onto the existing `black.css` fumadocs theme, tune `DocsLayout` config for density, and add original React components. No framework change, no custom-sidebar rebuild, no AI-chat/Typesense/Framer.

**Tech Stack:** Next.js 16, fumadocs-ui 16.9 (`black.css` theme), Tailwind v4 (`@theme inline`), Geist fonts, Bun, Turbo.

## Testing note (read first)

Styling + components, no app logic. "Tests" are build / typecheck / lint / format / render gates, plus a token-completeness check and a `/browse` dogfood (light + dark). No hollow unit tests. Run the gate after each task, commit on green.

## Rules (read second)

- USE BUN for any package op (`bun --filter @kaji/docs <script>`). No new deps planned; if one is truly needed, prefer existing `clsx`/`tailwind-merge` (check first), add via `bun add` only if required. Never npm.
- A safety hook blocks standalone `rm -rf`; not needed here.
- The token VALUES below are CSS design configuration adapted from the MIT-licensed better-auth project. All React COMPONENTS are written fresh for kaji — do NOT copy better-auth component source.
- Branch is `feat/docs-restyle-2` (already created, spec committed there). Stay on it.
- Brand `kaji` stays lowercase. No em-dashes in added prose.

## Verified current state

`apps/docs/app/global.css` (full current content):
```css
@import 'tailwindcss';
@import 'fumadocs-ui/css/black.css';
@import 'fumadocs-ui/css/preset.css';

:root {
  --font-sans: var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif;
  --font-mono: var(--font-geist-mono), ui-monospace, monospace;
}

html {
  scrollbar-gutter: stable;
}

html > body[data-scroll-locked] {
  margin-right: 0px !important;
  --removed-body-scroll-bar-size: 0px !important;
}
```

`apps/docs/lib/shared.ts` exports `appName = "kaji"`, `docsRoute`, `gitConfig = { user: "enkyuan", repo: "alloy", branch: "main" }`.

`apps/docs/lib/layout.shared.tsx` `baseOptions()` returns `{ nav: { title: appName }, githubUrl }`.

`apps/docs/app/docs/layout.tsx` renders `<DocsLayout tree={source.getPageTree()} {...baseOptions()}>`.

`apps/docs/app/(home)/page.tsx` is a "Hello World" placeholder.

## File Structure

- Modify `apps/docs/app/global.css` — full token layer + texture utility (Task 1)
- Modify `apps/docs/lib/layout.shared.tsx` — nav links (Task 3)
- Create `apps/docs/components/icons.tsx` — brand mark (Task 3)
- Modify `apps/docs/app/docs/layout.tsx` — density containerProps (Task 4)
- Create `apps/docs/components/ui/callout.tsx`, `apps/docs/components/ui/card.tsx` — original components (Task 5)
- Modify `apps/docs/components/mdx.tsx` — register the new components (Task 5)
- Modify `apps/docs/app/(home)/page.tsx` — real home page (Task 6)

---

### Task 1: Apply the complete design-token layer

**Files:**
- Modify: `apps/docs/app/global.css`

- [ ] **Step 1: Replace global.css with the full token layer**

Overwrite `apps/docs/app/global.css` with the following. It keeps the three `@import`s and the Geist font mapping, and adds the complete light `:root`, `.dark`, and `@theme inline` token set (values from better-auth), the layout density vars, and a subtle original grid texture utility.

```css
@import 'tailwindcss';
@import 'fumadocs-ui/css/black.css';
@import 'fumadocs-ui/css/preset.css';

@custom-variant dark (&:is(.dark *));

:root {
  --font-sans: var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif;
  --font-mono: var(--font-geist-mono), ui-monospace, monospace;

  --background: oklch(1 0 0);
  --foreground: oklch(0.147 0.004 49.25);
  --card: oklch(1 0 0);
  --card-foreground: oklch(0.147 0.004 49.25);
  --popover: oklch(1 0 0);
  --popover-foreground: oklch(0.147 0.004 49.25);
  --primary: oklch(0.216 0.006 56.043);
  --primary-foreground: oklch(0.985 0.001 106.423);
  --secondary: oklch(0.97 0.001 106.424);
  --secondary-foreground: oklch(0.216 0.006 56.043);
  --muted: oklch(0.97 0.001 106.424);
  --muted-foreground: oklch(0.553 0.013 58.071);
  --accent: oklch(0.97 0.001 106.424);
  --accent-foreground: oklch(0.216 0.006 56.043);
  --destructive: oklch(0.577 0.245 27.325);
  --destructive-foreground: oklch(0.577 0.245 27.325);
  --border: oklch(0.923 0.003 48.717);
  --input: oklch(0.923 0.003 48.717);
  --ring: oklch(0.709 0.01 56.259);
  --chart-1: oklch(0.646 0.222 41.116);
  --chart-2: oklch(0.6 0.118 184.704);
  --chart-3: oklch(0.398 0.07 227.392);
  --chart-4: oklch(0.828 0.189 84.429);
  --chart-5: oklch(0.769 0.188 70.08);
  --sidebar: oklch(0.985 0.001 106.423);
  --sidebar-foreground: oklch(0.147 0.004 49.25);
  --sidebar-primary: oklch(0.216 0.006 56.043);
  --sidebar-primary-foreground: oklch(0.985 0.001 106.423);
  --sidebar-accent: oklch(0.97 0.001 106.424);
  --sidebar-accent-foreground: oklch(0.216 0.006 56.043);
  --sidebar-border: oklch(0.923 0.003 48.717);
  --sidebar-ring: oklch(0.709 0.01 56.259);
  --scrollbar-thumb: var(--border);
  --scrollbar-thumb-hover: var(--ring);
  --scrollbar-track: transparent;
  --radius: 0.2rem;
  --fd-nav-height: 56px;
  --shadow-2xs: 0px 1px 2px 0px hsl(0 0% 0% / 0.09);
  --shadow-xs: 0px 1px 2px 0px hsl(0 0% 0% / 0.09);
  --shadow-sm: 0px 1px 2px 0px hsl(0 0% 0% / 0.18), 0px 1px 2px -1px hsl(0 0% 0% / 0.18);
  --shadow: 0px 1px 2px 0px hsl(0 0% 0% / 0.18), 0px 1px 2px -1px hsl(0 0% 0% / 0.18);
  --shadow-md: 0px 1px 2px 0px hsl(0 0% 0% / 0.18), 0px 2px 4px -1px hsl(0 0% 0% / 0.18);
  --shadow-lg: 0px 1px 2px 0px hsl(0 0% 0% / 0.18), 0px 4px 6px -1px hsl(0 0% 0% / 0.18);
  --shadow-xl: 0px 1px 2px 0px hsl(0 0% 0% / 0.18), 0px 8px 10px -1px hsl(0 0% 0% / 0.18);
  --shadow-2xl: 0px 1px 2px 0px hsl(0 0% 0% / 0.45);
  --tracking-normal: 0em;
  --spacing: 0.25rem;
}

.dark {
  --background: hsl(0 0% 0%);
  --foreground: oklch(0.985 0.001 106.423);
  --card: oklch(0.147 0.004 49.25);
  --card-foreground: oklch(0.985 0.001 106.423);
  --popover: oklch(0.147 0.004 49.25);
  --popover-foreground: oklch(0.985 0.001 106.423);
  --primary: oklch(0.985 0.001 106.423);
  --primary-foreground: oklch(0.216 0.006 56.043);
  --secondary: oklch(0.268 0.007 34.298);
  --secondary-foreground: oklch(0.985 0.001 106.423);
  --muted: oklch(0.268 0.007 34.298);
  --muted-foreground: oklch(0.709 0.01 56.259);
  --accent: oklch(0.268 0.007 34.298);
  --accent-foreground: oklch(0.985 0.001 106.423);
  --destructive: oklch(0.396 0.141 25.723);
  --destructive-foreground: oklch(0.637 0.237 25.331);
  --border: oklch(0.268 0.007 34.298);
  --input: oklch(0.268 0.007 34.298);
  --ring: oklch(0.553 0.013 58.071);
  --chart-1: oklch(0.488 0.243 264.376);
  --chart-2: oklch(0.696 0.17 162.48);
  --chart-3: oklch(0.769 0.188 70.08);
  --chart-4: oklch(0.627 0.265 303.9);
  --chart-5: oklch(0.645 0.246 16.439);
  --sidebar: oklch(0.216 0.006 56.043);
  --sidebar-foreground: oklch(0.985 0.001 106.423);
  --sidebar-primary: oklch(0.488 0.243 264.376);
  --sidebar-primary-foreground: oklch(0.985 0.001 106.423);
  --sidebar-accent: oklch(0.268 0.007 34.298);
  --sidebar-accent-foreground: oklch(0.985 0.001 106.423);
  --sidebar-border: oklch(0.268 0.007 34.298);
  --sidebar-ring: oklch(0.553 0.013 58.071);
  --scrollbar-thumb: var(--border);
  --scrollbar-thumb-hover: var(--ring);
  --scrollbar-track: transparent;
  --shadow-2xs: 0px 1px 2px 0px hsl(0 0% 0% / 0.09);
  --shadow-xs: 0px 1px 2px 0px hsl(0 0% 0% / 0.09);
  --shadow-sm: 0px 1px 2px 0px hsl(0 0% 0% / 0.18), 0px 1px 2px -1px hsl(0 0% 0% / 0.18);
  --shadow: 0px 1px 2px 0px hsl(0 0% 0% / 0.18), 0px 1px 2px -1px hsl(0 0% 0% / 0.18);
  --shadow-md: 0px 1px 2px 0px hsl(0 0% 0% / 0.18), 0px 2px 4px -1px hsl(0 0% 0% / 0.18);
  --shadow-lg: 0px 1px 2px 0px hsl(0 0% 0% / 0.18), 0px 4px 6px -1px hsl(0 0% 0% / 0.18);
  --shadow-xl: 0px 1px 2px 0px hsl(0 0% 0% / 0.18), 0px 8px 10px -1px hsl(0 0% 0% / 0.18);
  --shadow-2xl: 0px 1px 2px 0px hsl(0 0% 0% / 0.45);
}

@theme inline {
  --breakpoint-navbar: 64rem;
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-destructive-foreground: var(--destructive-foreground);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --color-chart-1: var(--chart-1);
  --color-chart-2: var(--chart-2);
  --color-chart-3: var(--chart-3);
  --color-chart-4: var(--chart-4);
  --color-chart-5: var(--chart-5);
  --color-sidebar: var(--sidebar);
  --color-sidebar-foreground: var(--sidebar-foreground);
  --color-sidebar-primary: var(--sidebar-primary);
  --color-sidebar-primary-foreground: var(--sidebar-primary-foreground);
  --color-sidebar-accent: var(--sidebar-accent);
  --color-sidebar-accent-foreground: var(--sidebar-accent-foreground);
  --color-sidebar-border: var(--sidebar-border);
  --color-sidebar-ring: var(--sidebar-ring);

  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 4px);

  --shadow-2xs: var(--shadow-2xs);
  --shadow-xs: var(--shadow-xs);
  --shadow-sm: var(--shadow-sm);
  --shadow: var(--shadow);
  --shadow-md: var(--shadow-md);
  --shadow-lg: var(--shadow-lg);
  --shadow-xl: var(--shadow-xl);
  --shadow-2xl: var(--shadow-2xl);

  --animate-accordion-down: accordion-down 0.2s ease-out;
  --animate-accordion-up: accordion-up 0.2s ease-out;

  @keyframes accordion-down {
    from { height: 0; }
    to { height: var(--radix-accordion-content-height); }
  }
  @keyframes accordion-up {
    from { height: var(--radix-accordion-content-height); }
    to { height: 0; }
  }
}

/* subtle original grid texture, theme-aware, very low opacity */
@layer utilities {
  .bg-grid-texture {
    background-image: linear-gradient(to right, color-mix(in oklch, var(--color-fd-foreground) 4%, transparent) 1px, transparent 1px),
      linear-gradient(to bottom, color-mix(in oklch, var(--color-fd-foreground) 4%, transparent) 1px, transparent 1px);
    background-size: 56px 56px;
  }
}

html {
  scrollbar-gutter: stable;
}

html > body[data-scroll-locked] {
  margin-right: 0px !important;
  --removed-body-scroll-bar-size: 0px !important;
}
```

- [ ] **Step 2: Build gate**

Run: `cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && bun --filter @kaji/docs build`
Expected: `Exited with code 0`. Capture output. If Tailwind v4 errors on the `@theme inline` nested `@keyframes`, move the two `@keyframes` blocks OUT of `@theme inline` to top-level (keep the `--animate-*` lines inside) and rebuild.

- [ ] **Step 3: Typecheck gate**

Run: `cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && bun --filter @kaji/docs typecheck`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy
git add apps/docs/app/global.css
git commit -m "style(docs): apply full better-auth design-token set

Complete shadcn token layer (light + dark + @theme inline): colors,
charts, sidebar tokens, radius 0.2rem + scale, shadow scale, spacing,
accordion tokens, plus a subtle grid texture utility. Values adapted
from the MIT-licensed better-auth project.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Verify the token set is complete and resolvable

**Files:** none (verification only)

- [ ] **Step 1: Confirm all token groups present in global.css**

Run:
```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy/apps/docs/app
for t in --card --primary --muted --chart-1 --chart-5 --sidebar-ring --radius --shadow-lg --color-card --color-primary --radius-md; do
  grep -q -- "$t" global.css && echo "OK: $t" || echo "MISSING: $t";
done
echo "dark overrides:"; grep -c -- "--card:" global.css```
Expected: every token prints `OK`. `--card:` count should be 2 (one in `:root`, one in `.dark`).

- [ ] **Step 2: Confirm tokens resolve as Tailwind utilities at build**

The build in Task 1 already compiled. As a runtime check, this is verified in the Task 7 dogfood (`bg-card`, `bg-primary`, `text-muted-foreground`, `rounded-md` must apply). No commit (verification only).

---

### Task 3: Enrich the nav chrome + brand mark

**Files:**
- Create: `apps/docs/components/icons.tsx`
- Modify: `apps/docs/lib/layout.shared.tsx`

- [ ] **Step 1: Create an original brand mark**

Write `apps/docs/components/icons.tsx` (an original simple SVG, not copied from anywhere):

```tsx
import type { SVGProps } from "react";

export function AgentkitMark(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M8 12h8M12 8v8" />
    </svg>
  );
}
```

- [ ] **Step 2: Enrich baseOptions with a logo + nav links**

Replace `apps/docs/lib/layout.shared.tsx` with:

```tsx
import type { BaseLayoutProps } from "fumadocs-ui/layouts/shared";
import { appName, gitConfig } from "./shared";
import { AgentkitMark } from "@/components/icons";

export function baseOptions(): BaseLayoutProps {
  return {
    nav: {
      title: (
        <>
          <AgentkitMark />
          <span className="font-medium">{appName}</span>
        </>
      ),
    },
    links: [
      {
        text: "Docs",
        url: "/docs",
        active: "nested-url",
      },
    ],
    githubUrl: `https://github.com/${gitConfig.user}/${gitConfig.repo}`,
  };
}
```

- [ ] **Step 3: Build + typecheck gates**

Run:
```bash
bun --filter @kaji/docs build && bun --filter @kaji/docs typecheck
```
Expected: both exit 0.

- [ ] **Step 4: Commit**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy
git add apps/docs/components/icons.tsx apps/docs/lib/layout.shared.tsx
git commit -m "feat(docs): brand mark + nav links in baseOptions

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Tune docs layout density

**Files:**
- Modify: `apps/docs/app/docs/layout.tsx`

- [ ] **Step 1: Add containerProps for density + grid texture**

Replace `apps/docs/app/docs/layout.tsx` with:

```tsx
import { source } from "@/lib/source";
import { DocsLayout } from "fumadocs-ui/layouts/docs";
import { baseOptions } from "@/lib/layout.shared";

export default function Layout({ children }: LayoutProps<"/docs">) {
  return (
    <DocsLayout
      tree={source.getPageTree()}
      {...baseOptions()}
      containerProps={{ className: "bg-grid-texture" }}
    >
      {children}
    </DocsLayout>
  );
}
```

Note: keep fumadocs' sidebar (do NOT set `sidebar.enabled: false`). The `--fd-nav-height: 56px` and `--radius` from Task 1 drive the rest of the density.

- [ ] **Step 2: Build gate**

Run: `cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && bun --filter @kaji/docs build`
Expected: exit 0. If `containerProps` is not a valid prop on this `DocsLayout` version, remove it and instead add the `bg-grid-texture` class via the body in `app/layout.tsx`; rebuild. Report which path was used.

- [ ] **Step 3: Commit**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy
git add apps/docs/app/docs/layout.tsx
git commit -m "style(docs): docs layout density + grid texture container

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Original MDX UI components (callout + card)

**Files:**
- Create: `apps/docs/components/ui/callout.tsx`
- Create: `apps/docs/components/ui/card.tsx`
- Modify: `apps/docs/components/mdx.tsx`

These are original components styled with the new tokens. NOTE on paths: the docs app's `lib/` is git-tracked via a negation, but to avoid any `lib/`-style gitignore surprise these go under `components/ui/`, which is not affected.

- [ ] **Step 1: Create the Callout component**

Write `apps/docs/components/ui/callout.tsx`:

```tsx
import type { ReactNode } from "react";

export function Callout({
  title,
  children,
}: {
  title?: string;
  children: ReactNode;
}) {
  return (
    <div className="my-4 rounded-md border border-border bg-card px-4 py-3 text-card-foreground shadow-sm">
      {title ? <p className="mb-1 font-medium">{title}</p> : null}
      <div className="text-sm text-muted-foreground">{children}</div>
    </div>
  );
}
```

- [ ] **Step 2: Create the Card + Cards components**

Write `apps/docs/components/ui/card.tsx`:

```tsx
import Link from "next/link";
import type { ReactNode } from "react";

export function Cards({ children }: { children: ReactNode }) {
  return <div className="grid gap-3 sm:grid-cols-2 my-4">{children}</div>;
}

export function Card({
  title,
  description,
  href,
}: {
  title: string;
  description?: string;
  href: string;
}) {
  return (
    <Link
      href={href}
      className="rounded-md border border-border bg-card p-4 text-card-foreground no-underline shadow-sm transition-colors hover:bg-accent hover:text-accent-foreground"
    >
      <p className="font-medium">{title}</p>
      {description ? (
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      ) : null}
    </Link>
  );
}
```

- [ ] **Step 3: Register the components in the MDX map**

Replace `apps/docs/components/mdx.tsx` with:

```tsx
import defaultMdxComponents from "fumadocs-ui/mdx";
import type { MDXComponents } from "mdx/types";
import { Callout } from "@/components/ui/callout";
import { Card, Cards } from "@/components/ui/card";

export function getMDXComponents(components?: MDXComponents) {
  return {
    ...defaultMdxComponents,
    Callout,
    Card,
    Cards,
    ...components,
  } satisfies MDXComponents;
}

export const useMDXComponents = getMDXComponents;

declare global {
  type MDXProvidedComponents = ReturnType<typeof getMDXComponents>;
}
```

- [ ] **Step 4: Build + typecheck gates**

Run:
```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && bun --filter @kaji/docs build && bun --filter @kaji/docs typecheck
```
Expected: both exit 0. (Content does not yet use these; they are available for the home page in Task 6 and future content. fumadocs allows registering unused MDX components.)

- [ ] **Step 5: Commit**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy
git add apps/docs/components/ui/callout.tsx apps/docs/components/ui/card.tsx apps/docs/components/mdx.tsx
git commit -m "feat(docs): original Callout + Card MDX components

Token-driven (border/card/accent/shadow). Registered in the MDX map.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Real home page

**Files:**
- Modify: `apps/docs/app/(home)/page.tsx`

- [ ] **Step 1: Replace Hello World with an kaji front door**

Write `apps/docs/app/(home)/page.tsx`:

```tsx
import Link from "next/link";
import { Card, Cards } from "@/components/ui/card";

export default function HomePage() {
  return (
    <main className="bg-grid-texture flex flex-1 flex-col items-center justify-center px-4 py-20 text-center">
      <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
        kaji
      </h1>
      <p className="mt-4 max-w-xl text-muted-foreground">
        An embeddable, infra-free SDK for building agents in Python and
        TypeScript. Event-sourced runtime, tool registry, pluggable LLM
        providers, and STT/TTS voice modalities.
      </p>
      <div className="mt-8 flex gap-3">
        <Link
          href="/docs"
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm transition-opacity hover:opacity-90"
        >
          Read the docs
        </Link>
        <Link
          href="/docs/getting-started"
          className="rounded-md border border-border px-4 py-2 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground"
        >
          Get started
        </Link>
      </div>
      <div className="mt-12 w-full max-w-2xl text-left">
        <Cards>
          <Card
            title="Core concepts"
            description="Events, session state, the tool registry, the event bus, and providers."
            href="/docs/concepts/events"
          />
          <Card
            title="Architecture"
            description="The modality-agnostic ReAct runtime loop and where voice attaches."
            href="/docs/architecture"
          />
        </Cards>
      </div>
    </main>
  );
}
```

- [ ] **Step 2: Build + typecheck gates**

Run:
```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && bun --filter @kaji/docs build && bun --filter @kaji/docs typecheck
```
Expected: both exit 0.

- [ ] **Step 3: Commit**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy
git add "apps/docs/app/(home)/page.tsx"
git commit -m "feat(docs): real kaji home page

Replace Hello World with a token-driven hero + feature cards and CTAs
to the docs. No marketing chrome.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Full verification + browse dogfood

**Files:** none (verification only)

- [ ] **Step 1: Format + full Turbo gate sweep**

Run:
```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy
bun --filter @kaji/docs format
bunx turbo run build typecheck lint format:check --filter=@kaji/docs
```
Expected: all 4 tasks successful, lint 0 warnings/0 errors.

- [ ] **Step 2: Clean-clone build**

Run:
```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy
D=$(mktemp -d /tmp/alloy-clean.XXXXXX)
git archive HEAD apps/docs | tar -x -C "$D"
cd "$D/apps/docs" && bun install && bun run build
echo "CLEAN BUILD EXIT: $?"
```
Expected: exit 0, "Compiled successfully". This catches any untracked new file (especially `components/icons.tsx`, `components/ui/*`).

- [ ] **Step 3: Start dev server**

Run (background): `cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && bun --filter @kaji/docs dev`
Note the actual port.

- [ ] **Step 4: Dogfood with the gstack /browse skill (light + dark)**

Per `CLAUDE.md`, use `/browse` (never chrome MCP directly). Against the running URL:
- Load `/` (home): confirm the new hero, CTAs, and feature cards render with crisp `0.2rem` corners and the subtle grid texture.
- Load `/docs`: confirm enriched nav (brand mark + "kaji" + Docs link + GitHub + search + theme toggle), the 56px nav height, denser layout, grid texture, crisp corners on code blocks/cards.
- Toggle dark mode: confirm tokens resolve in both themes and there is NO two-toned clash between the shadcn tokens and `black.css` (background/foreground stay consistent). If clash: adjust the `:root`/`.dark` `--background`/`--foreground` to match black.css's fd tokens, rebuild, recheck.
- Verify a token utility actually applies: `$B js "getComputedStyle(document.querySelector('a[href=\"/docs\"]')||document.body).borderRadius"` or screenshot a card and confirm square-ish corners.
- Open `/docs/concepts/tool-registry`: code blocks still render, sidebar still works.
- `console --errors`: none.
- Screenshot home + a docs page in both themes; Read them to confirm.
- Compare against the live better-auth docs (`https://www.better-auth.com/docs`) side by side: corners, density, nav cluster.
- Fix any issue, rebuild, reload.

- [ ] **Step 5: Stop dev server.**

- [ ] **Step 6: Report**

Summarize: gate results (actual output), clean-build exit code, dogfood findings with screenshots (light + dark), token-completeness result, and any fixes. Do NOT ship or PR unless asked.

---

## Self-review

**Spec coverage:**
- Full token set (light + dark + @theme inline, all colors/charts/sidebar/radius/shadows/spacing/accordion) -> Task 1, with completeness gate Task 2 + dogfood Task 7. ✓
- Texture background -> Task 1 (`bg-grid-texture`), applied Tasks 4/6. ✓
- Nav chrome (logo, links, GitHub, search, theme) -> Task 3 (links + brand) + fumadocs defaults keep search/theme. ✓
- Density (56px nav, narrower column) -> Task 1 vars + Task 4 containerProps. ✓
- Original components (callout, card, icons) -> Tasks 3, 5. ✓
- Home page -> Task 6. ✓
- Keep fumadocs sidebar (no enabled:false) -> Task 4 note. ✓
- IP: token values adapted, components original, no verbatim component copy, no /tmp ref committed -> rules section + all component code is original. ✓
- Non-goals (no AI chat/Typesense/Framer/marketing/content rewrites) -> nothing adds them. ✓
- bun-only, branch feat/docs-restyle-2 -> rules section. ✓
- Verification: gates + clean-clone + dogfood (light+dark) + token completeness -> Tasks 2, 7. ✓

**Placeholder scan:** No TBD/TODO. Every file is given in full. Fallbacks (keyframes out of @theme, containerProps removal) are explicit. ✓

**Type/name consistency:** `AgentkitMark` (icons.tsx) used in layout.shared.tsx. `Callout`/`Card`/`Cards` defined in components/ui, imported in mdx.tsx and home page. `bg-grid-texture` defined in global.css, used in layout.tsx + home. Token names match better-auth source exactly. ✓

No gaps found.
