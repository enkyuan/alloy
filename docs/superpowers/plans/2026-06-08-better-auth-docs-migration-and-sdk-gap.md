# Better-Auth Docs Migration + SDK Gap Review — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the better-auth docs app's design system + landing page into alloy's `apps/docs` 1:1 (rebranded to kaji, using `shape-40.svg`), then produce a TS-vs-Python SDK gap report with a prioritized closure plan.

**Architecture:** Both apps are fumadocs 16 + Tailwind 4 + Next 16. We swap alloy's *design layer* (CSS tokens, fonts, UI component library, MDX component specs, custom docs sidebar, landing) while keeping alloy's working content pipeline (`collections/server`, `source.config.ts`, `proxy.ts`, `app/llms.txt`, `app/og`). Dependencies are matched to better-auth exactly. The SDK review is a written report only — no SDK code changes.

**Tech Stack:** Next 16.2.7, React 19, fumadocs-ui/core/mdx 16.9.3, Tailwind CSS 4, Geist fonts, Radix UI, class-variance-authority, motion/react, lucide-react, bun (package manager).

**Source repo (read-only reference):** `/Users/Enkang.Yuan1/Desktop/Projects/better-auth/docs`
**Target:** `/Users/Enkang.Yuan1/Desktop/Projects/alloy/apps/docs`
**Logo source:** `/Users/Enkang.Yuan1/Downloads/shape-40.svg`

**Verification model:** This is a frontend migration; "tests" are `bun run typecheck` + `bun run lint` gates plus `/browse` QA. Bun is at `~/.bun/bin/bun` (not on PATH). All `bun` commands below run from `apps/docs` unless noted.

**Branch:** `feat/docs-restyle-2` (already checked out). Commit frequently.

---

## File Structure (what gets created / modified)

**Created in `apps/docs`:**
- `components.json` — shadcn config
- `lib/utils.ts` — `cn` + `mergeRefs` (replaces `lib/cn.ts`)
- `components/ui/*.tsx` — 22 primitives
- `components/docs/mdx-components.tsx`, `components/docs/docs-sidebar.tsx`, `components/docs/custom-sidebar.tsx`, `components/docs/icons.tsx`
- `components/mdx/mermaid.tsx`
- `components/sidebar-content.tsx` — hand-authored kaji nav tree
- `components/version-switcher.tsx`, `components/theme-toggle.tsx`, `components/providers.tsx`, `components/search-dialog.tsx`
- `components/landing/*.tsx` — landing suite
- `lib/docs-versions.ts`, `lib/metadata.ts`
- `public/logo.svg` — shape-40 mark
- `app/page.tsx` — rebranded landing (replaces `app/(home)/`)

**Modified in `apps/docs`:**
- `package.json` — add better-auth deps
- `app/global.css` — full token/animation port
- `app/layout.tsx` — fonts + providers + nav overlay + metadata
- `app/docs/layout.tsx` — custom sidebar wiring
- `components/mdx.tsx` — register ported MDX components
- `components/icons.tsx` — shape-40 `AgentkitMark`
- `lib/layout.shared.tsx` — nav title uses new mark
- `next.config.mjs` — optimizePackageImports + images

**Deleted in `apps/docs`:**
- `lib/cn.ts` (replaced by `lib/utils.ts`)
- `app/(home)/` (replaced by `app/page.tsx`)
- `components/ui/card.tsx`, `components/ui/callout.tsx` (replaced by better-auth versions)

**Created in repo root:**
- `docs/sdk-gap-analysis.md` — Part B report

---

## Part A — Docs Migration

### Task 1: Add dependencies (match better-auth)

**Files:**
- Modify: `apps/docs/package.json`

- [ ] **Step 1: Add the better-auth dependency set with bun**

From `apps/docs`, run (bun resolves versions; alloy's newer fumadocs/next pins stay):

```bash
cd apps/docs
~/.bun/bin/bun add \
  @radix-ui/react-accordion @radix-ui/react-alert-dialog @radix-ui/react-aspect-ratio \
  @radix-ui/react-avatar @radix-ui/react-checkbox @radix-ui/react-collapsible \
  @radix-ui/react-context-menu @radix-ui/react-dialog @radix-ui/react-dropdown-menu \
  @radix-ui/react-hover-card @radix-ui/react-icons @radix-ui/react-label \
  @radix-ui/react-menubar @radix-ui/react-navigation-menu @radix-ui/react-popover \
  @radix-ui/react-presence @radix-ui/react-progress @radix-ui/react-radio-group \
  @radix-ui/react-scroll-area @radix-ui/react-select @radix-ui/react-separator \
  @radix-ui/react-slider @radix-ui/react-slot @radix-ui/react-switch \
  @radix-ui/react-tabs @radix-ui/react-toggle @radix-ui/react-toggle-group \
  @radix-ui/react-tooltip radix-ui \
  class-variance-authority clsx cmdk vaul sonner next-themes \
  motion/react embla-carousel-react react-fast-marquee \
  recharts mermaid shiki rehype-highlight \
  react-hook-form @hookform/resolvers zod \
  date-fns input-otp lucide-react \
  @vercel/analytics @vercel/og \
  fumadocs-typescript
```

- [ ] **Step 2: Add dev deps**

```bash
~/.bun/bin/bun add -d tw-animate-css tailwindcss-animate
```

- [ ] **Step 3: Verify install resolves**

Run: `~/.bun/bin/bun install`
Expected: completes with no peer-dependency errors that block install. fumadocs stays at 16.9.3, next at 16.2.7.

- [ ] **Step 4: Commit**

```bash
git add apps/docs/package.json bun.lock
git commit -m "build(docs): add better-auth design-system dependencies"
```

---

### Task 2: Port `cn` utility + components.json

**Files:**
- Create: `apps/docs/lib/utils.ts`
- Delete: `apps/docs/lib/cn.ts`
- Create: `apps/docs/components.json`

- [ ] **Step 1: Create `lib/utils.ts`**

```typescript
import type { ClassValue } from "clsx";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function mergeRefs<T>(
  ...refs: (React.Ref<T> | undefined)[]
): React.RefCallback<T> {
  return (value) => {
    refs.forEach((ref) => {
      if (typeof ref === "function") {
        ref(value);
      } else if (ref) {
        (ref as React.MutableRefObject<T | null>).current = value;
      }
    });
  };
}
```

- [ ] **Step 2: Delete the old re-export**

```bash
rm apps/docs/lib/cn.ts
```

(No current importers of `@/lib/cn` exist — verified — so nothing else to update.)

- [ ] **Step 3: Create `components.json`**

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "new-york",
  "rsc": true,
  "tsx": true,
  "tailwind": {
    "config": "",
    "css": "app/global.css",
    "baseColor": "stone",
    "cssVariables": true,
    "prefix": ""
  },
  "iconLibrary": "lucide",
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils",
    "ui": "@/components/ui",
    "lib": "@/lib",
    "hooks": "@/hooks"
  }
}
```

- [ ] **Step 4: Typecheck**

Run: `~/.bun/bin/bun run typecheck`
Expected: PASS (utils.ts compiles; no broken imports).

- [ ] **Step 5: Commit**

```bash
git add apps/docs/lib/utils.ts apps/docs/components.json
git rm apps/docs/lib/cn.ts
git commit -m "feat(docs): port cn/mergeRefs util + shadcn components.json"
```

---

### Task 3: Port full `global.css` (tokens + animations)

**Files:**
- Modify: `apps/docs/app/global.css`

- [ ] **Step 1: Copy better-auth globals.css body into alloy global.css**

Read `/Users/Enkang.Yuan1/Desktop/Projects/better-auth/docs/app/globals.css` (954 lines). Write its content into `apps/docs/app/global.css`, with these adaptations at the very top — replace better-auth's import block:

```css
@import "tailwindcss";
@import "fumadocs-ui/css/black.css";
@import "fumadocs-ui/css/preset.css";
@import "tw-animate-css";
```

(better-auth's first lines also `@import "tailwindcss"` + fumadocs presets + tw-animate-css + a source-scan line; keep alloy's two fumadocs imports, add tw-animate-css, drop any better-auth `@source` line that points at better-auth paths. Keep everything else — `:root`, `.dark`, `@theme inline`, all `@keyframes`, `@utility`, `@layer base/utilities`, scrollbar, `.docs-layout`, code-block flat treatment, `prefers-reduced-motion` — verbatim.)

- [ ] **Step 2: Verify the dev server compiles the CSS**

Run: `~/.bun/bin/bun run dev` (background), then load `http://localhost:3000/docs`.
Expected: page renders, no Tailwind/PostCSS compile error in terminal. Stop the dev server after confirming.

- [ ] **Step 3: Typecheck (CSS doesn't typecheck, but confirm nothing else broke)**

Run: `~/.bun/bin/bun run typecheck`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add apps/docs/app/global.css
git commit -m "style(docs): port full better-auth globals.css (tokens + animations)"
```

---

### Task 4: Port UI component library (22 primitives)

**Files:**
- Create: `apps/docs/components/ui/{accordion,alert,badge,button,callout,card,checkbox,code-block,command,drawer,dynamic-code-block,form,input,label,popover,scroll-area,select,table,tabs,textarea,tooltip}.tsx`
- Create: `apps/docs/components/ui/use-copy-button.tsx`
- Delete: existing `apps/docs/components/ui/card.tsx`, `apps/docs/components/ui/callout.tsx`

- [ ] **Step 1: Copy all 22 ui files**

```bash
cp /Users/Enkang.Yuan1/Desktop/Projects/better-auth/docs/components/ui/*.tsx \
   /Users/Enkang.Yuan1/Desktop/Projects/alloy/apps/docs/components/ui/
```

This overwrites the old `card.tsx`/`callout.tsx` with better-auth's versions and adds the rest. All import `@/lib/utils` (cn) which now exists.

- [ ] **Step 2: Typecheck**

Run: `~/.bun/bin/bun run typecheck`
Expected: PASS. If failures, they will be import-path or fumadocs-version mismatches — fix by:
  - Any `@/lib/utils` import → already correct.
  - Any reference to a fumadocs export that moved between 16.7.9→16.9.3 → update the import to the 16.9.3 path (check `node_modules/fumadocs-ui`).

- [ ] **Step 3: Lint**

Run: `~/.bun/bin/bun run lint`
Expected: PASS (or only pre-existing warnings).

- [ ] **Step 4: Commit**

```bash
git add apps/docs/components/ui
git commit -m "feat(docs): port better-auth ui component library (22 primitives)"
```

---

### Task 5: Port MDX components + register them

**Files:**
- Create: `apps/docs/components/docs/mdx-components.tsx`
- Create: `apps/docs/components/mdx/mermaid.tsx`
- Create: `apps/docs/components/docs/icons.tsx`
- Modify: `apps/docs/components/mdx.tsx`

- [ ] **Step 1: Copy the MDX component files and icons**

```bash
mkdir -p apps/docs/components/docs apps/docs/components/mdx
cp /Users/Enkang.Yuan1/Desktop/Projects/better-auth/docs/components/docs/mdx-components.tsx apps/docs/components/docs/
cp /Users/Enkang.Yuan1/Desktop/Projects/better-auth/docs/components/docs/icons.tsx apps/docs/components/docs/
cp /Users/Enkang.Yuan1/Desktop/Projects/better-auth/docs/components/mdx/mermaid.tsx apps/docs/components/mdx/
```

- [ ] **Step 2: Update `components/mdx.tsx` to register the ported set**

Replace the file body with (merging better-auth's MDX overrides into alloy's existing `getMDXComponents` shape; `Card`/`Cards`/`Callout` now come from the ported `@/components/ui/*`):

```tsx
import defaultMdxComponents from "fumadocs-ui/mdx";
import type { MDXComponents } from "mdx/types";
import { Callout } from "@/components/ui/callout";
import { Card, Cards } from "@/components/ui/card";
import {
  APIMethod,
  DatabaseTable,
  DividerText,
  Endpoint,
  Features,
  ForkButton,
  GenerateAppleJwt,
  GenerateSecret,
} from "@/components/docs/mdx-components";

export function getMDXComponents(components?: MDXComponents) {
  return {
    ...defaultMdxComponents,
    Callout,
    Card,
    Cards,
    APIMethod,
    DatabaseTable,
    DividerText,
    Endpoint,
    Features,
    ForkButton,
    GenerateAppleJwt,
    GenerateSecret,
    ...components,
  } satisfies MDXComponents;
}

export const useMDXComponents = getMDXComponents;

declare global {
  type MDXProvidedComponents = ReturnType<typeof getMDXComponents>;
}
```

(Only export names that `mdx-components.tsx` actually defines should be imported. After copying in Step 1, open `components/docs/mdx-components.tsx` and reconcile this import list with its real exports — drop `AddToCursor` if it pulls assets we didn't copy; keep the rest. If `Card`/`Cards`/`Callout` are also exported from better-auth's mdx-components, prefer the `@/components/ui/*` versions to match alloy's structure.)

- [ ] **Step 3: Typecheck**

Run: `~/.bun/bin/bun run typecheck`
Expected: PASS. Fix any missing-import by either copying the missing dependency file from better-auth (e.g. a `@/components/ui/*` it references — already present) or removing the unused export from the registration map.

- [ ] **Step 4: Commit**

```bash
git add apps/docs/components/docs apps/docs/components/mdx apps/docs/components/mdx.tsx
git commit -m "feat(docs): port better-auth MDX component specs + register them"
```

---

### Task 6: Port logo mark (shape-40)

**Files:**
- Modify: `apps/docs/components/icons.tsx`
- Create: `apps/docs/public/logo.svg`

- [ ] **Step 1: Save the raw SVG to public**

Write `/Users/Enkang.Yuan1/Downloads/shape-40.svg` content to `apps/docs/public/logo.svg`:

```svg
<svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
<path d="M31 3V17L17 3H31Z" fill="#FF6E3C"/>
<path fill-rule="evenodd" clip-rule="evenodd" d="M45 31V17H31H17V31L3 17L17 3H3V17V31H17V45H31H45V31ZM45 31L31 45L17 31H31V17L45 31Z" fill="#FF6E3C"/>
</svg>
```

- [ ] **Step 2: Replace `AgentkitMark` with the shape-40 geometry**

Rewrite `apps/docs/components/icons.tsx` so `AgentkitMark` renders the shape-40 paths, defaulting to brand orange but overridable via props (nav passes a class to theme it):

```tsx
import type { SVGProps } from "react";

export function AgentkitMark({ fill = "#FF6E3C", ...props }: SVGProps<SVGSVGElement> & { fill?: string }) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      {...props}
    >
      <path d="M31 3V17L17 3H31Z" fill={fill} />
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M45 31V17H31H17V31L3 17L17 3H3V17V31H17V45H31H45V31ZM45 31L31 45L17 31H31V17L45 31Z"
        fill={fill}
      />
    </svg>
  );
}
```

- [ ] **Step 3: Typecheck**

Run: `~/.bun/bin/bun run typecheck`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add apps/docs/components/icons.tsx apps/docs/public/logo.svg
git commit -m "feat(docs): adopt shape-40 kaji logo mark"
```

---

### Task 7: Port supporting components (providers, theme-toggle, version-switcher, search-dialog, docs-versions)

**Files:**
- Create: `apps/docs/components/providers.tsx`, `apps/docs/components/theme-toggle.tsx`, `apps/docs/components/version-switcher.tsx`, `apps/docs/components/search-dialog.tsx`
- Create: `apps/docs/lib/docs-versions.ts`, `apps/docs/lib/metadata.ts`

- [ ] **Step 1: Copy the files**

```bash
cp /Users/Enkang.Yuan1/Desktop/Projects/better-auth/docs/components/providers.tsx apps/docs/components/
cp /Users/Enkang.Yuan1/Desktop/Projects/better-auth/docs/components/theme-toggle.tsx apps/docs/components/
cp /Users/Enkang.Yuan1/Desktop/Projects/better-auth/docs/components/version-switcher.tsx apps/docs/components/
cp /Users/Enkang.Yuan1/Desktop/Projects/better-auth/docs/components/search-dialog.tsx apps/docs/components/
cp /Users/Enkang.Yuan1/Desktop/Projects/better-auth/docs/lib/docs-versions.ts apps/docs/lib/
cp /Users/Enkang.Yuan1/Desktop/Projects/better-auth/docs/lib/metadata.ts apps/docs/lib/
```

- [ ] **Step 2: Reconcile `version-switcher.tsx` to single-version**

alloy has no beta docs. Open `components/version-switcher.tsx`; if `SidebarVersionSwitcher` hardcodes better-auth version paths, simplify it to render a static "kaji" label (or the current version from `apps/docs/package.json`). Keep the export name `SidebarVersionSwitcher` so the sidebar import (Task 8) resolves.

- [ ] **Step 3: Reconcile `search-dialog.tsx` and `metadata.ts`**

`search-dialog.tsx`: keep as-is if it only uses fumadocs search context; if it imports typesense, replace the search source with alloy's default fumadocs search (`/api/search` already exists at `app/api/search/route.ts`). `metadata.ts`: ensure `createMetadata` defaults reference kaji (title "kaji"), not Better Auth.

- [ ] **Step 4: Typecheck**

Run: `~/.bun/bin/bun run typecheck`
Expected: PASS. Resolve missing imports by copying the specific referenced file from better-auth or stubbing version logic.

- [ ] **Step 5: Commit**

```bash
git add apps/docs/components apps/docs/lib
git commit -m "feat(docs): port providers, theme-toggle, version-switcher, search-dialog"
```

---

### Task 8: Port custom docs sidebar + hand-author kaji nav tree

**Files:**
- Create: `apps/docs/components/docs/docs-sidebar.tsx`, `apps/docs/components/docs/custom-sidebar.tsx`
- Create: `apps/docs/components/sidebar-content.tsx`
- Modify: `apps/docs/app/docs/layout.tsx`

- [ ] **Step 1: Copy the sidebar components**

```bash
cp /Users/Enkang.Yuan1/Desktop/Projects/better-auth/docs/components/docs/docs-sidebar.tsx apps/docs/components/docs/
cp /Users/Enkang.Yuan1/Desktop/Projects/better-auth/docs/components/docs/custom-sidebar.tsx apps/docs/components/docs/
```

- [ ] **Step 2: Author `components/sidebar-content.tsx` for kaji**

Copy better-auth's `sidebar-content.tsx` as the structural template, then replace its `contents` array with an kaji nav tree mirroring `apps/docs/content/docs`. Use this tree (icons from lucide-react, matching the `ListItem`/`Section` types the template defines):

```tsx
// contents: one Section per group, list items point at /docs/* routes
// Section "Get Started": index (/docs), getting-started (/docs/getting-started),
//   architecture (/docs/architecture), reference-service (/docs/reference-service)
// Section "Concepts": events (/docs/concepts/events), session-state (/docs/concepts/session-state),
//   tool-registry (/docs/concepts/tool-registry), event-bus (/docs/concepts/event-bus),
//   providers (/docs/concepts/providers)
```

Concretely, set `contents` to:

```tsx
import { Book, Boxes, Cpu, GitBranch, Layers, Radio, Rocket, Server, Wrench } from "lucide-react";

export const contents: Section[] = [
  {
    title: "Get Started",
    list: [
      { title: "Introduction", href: "/docs", icon: Book },
      { title: "Getting Started", href: "/docs/getting-started", icon: Rocket },
      { title: "Architecture", href: "/docs/architecture", icon: Layers },
      { title: "Reference Service", href: "/docs/reference-service", icon: Server },
    ],
  },
  {
    title: "Concepts",
    list: [
      { title: "Events", href: "/docs/concepts/events", icon: Radio },
      { title: "Session State", href: "/docs/concepts/session-state", icon: GitBranch },
      { title: "Tool Registry", href: "/docs/concepts/tool-registry", icon: Wrench },
      { title: "Event Bus", href: "/docs/concepts/event-bus", icon: Boxes },
      { title: "Providers", href: "/docs/concepts/providers", icon: Cpu },
    ],
  },
];
```

(Match the exact `Section`/`ListItem` field names the copied template declares — adjust `title`/`href`/`icon` keys if they differ. Remove better-auth's `expandSectionForPathPrefix`/`subpages`/`group` usages unless our tree needs them.)

- [ ] **Step 3: Rewire `app/docs/layout.tsx`**

```tsx
import { source } from "@/lib/source";
import { DocsLayout } from "fumadocs-ui/layouts/docs";
import { baseOptions } from "@/lib/layout.shared";
import { DocsSidebar } from "@/components/docs/docs-sidebar";

export default function Layout({ children }: LayoutProps<"/docs">) {
  return (
    <>
      <DocsSidebar />
      <DocsLayout
        tree={source.getPageTree()}
        {...baseOptions()}
        nav={{ enabled: false }}
        searchToggle={{ enabled: false }}
        themeSwitch={{ enabled: false }}
        sidebar={{ enabled: false }}
        containerProps={{ className: "docs-layout" }}
      >
        {children}
      </DocsLayout>
    </>
  );
}
```

(If `DocsSidebar` requires a provider context (search), wrap with the fumadocs `RootProvider` already supplied in `app/layout.tsx`; if it needs the page list, pass `source.getPages()` per better-auth's provider pattern — copy `app/docs/provider.tsx` from better-auth if the sidebar imports `usePages`.)

- [ ] **Step 4: Typecheck + dev smoke**

Run: `~/.bun/bin/bun run typecheck` → PASS.
Run dev server, load `/docs`, confirm the custom sidebar renders with both sections and active-state tracking works. Stop the server.

- [ ] **Step 5: Commit**

```bash
git add apps/docs/components/docs apps/docs/components/sidebar-content.tsx apps/docs/app/docs/layout.tsx
git commit -m "feat(docs): port custom docs sidebar + kaji nav tree"
```

---

### Task 9: Port root layout (fonts, providers, metadata, nav overlay)

**Files:**
- Modify: `apps/docs/app/layout.tsx`
- Modify: `apps/docs/lib/layout.shared.tsx`

- [ ] **Step 1: Rewrite `app/layout.tsx`**

```tsx
import { GeistPixelSquare } from "geist/font/pixel";
import { Geist, Geist_Mono } from "next/font/google";
import "./global.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";
import { RootProvider } from "fumadocs-ui/provider/next";
import { Providers } from "@/components/providers";
import { StaggeredNavFiles } from "@/components/landing/staggered-nav-files";
import { appName } from "@/lib/shared";

const fontSans = Geist({ subsets: ["latin"], variable: "--font-sans" });
const fontMono = Geist_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  metadataBase: new URL("http://localhost:3000"),
  title: { template: `%s | ${appName}`, default: appName },
  description:
    "Embeddable SDK for building agents: event-sourced runtime, tool registry, pluggable LLM providers, and STT/TTS modalities.",
};

export default function Layout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      data-scroll-behavior="smooth"
      className={`${fontSans.variable} ${fontMono.variable} ${GeistPixelSquare.variable}`}
    >
      <body className="font-sans antialiased">
        <RootProvider>
          <Providers>
            <div className="relative min-h-dvh">
              <StaggeredNavFiles />
              {children}
            </div>
          </Providers>
        </RootProvider>
      </body>
    </html>
  );
}
```

(If `Providers` already wraps a theme provider that conflicts with `RootProvider`, keep `RootProvider` as the outer fumadocs provider and let `Providers` supply sonner Toaster only. The `StaggeredNavFiles` import resolves after Task 10. If executing strictly in order, comment out the `<StaggeredNavFiles />` line and its import until Task 10, then restore.)

- [ ] **Step 2: Update `lib/layout.shared.tsx` nav title**

The `AgentkitMark` already renders shape-40 (Task 6). Confirm `baseOptions()` still renders `<AgentkitMark />` + `<span>{appName}</span>`; pass a className so the mark inherits theme color in the nav if desired. No structural change required.

- [ ] **Step 3: Typecheck**

Run: `~/.bun/bin/bun run typecheck`
Expected: PASS (with StaggeredNavFiles either present from Task 10 or temporarily stubbed).

- [ ] **Step 4: Commit**

```bash
git add apps/docs/app/layout.tsx apps/docs/lib/layout.shared.tsx
git commit -m "feat(docs): port root layout (geist fonts, providers, nav overlay)"
```

---

### Task 10: Port landing page (rebranded to kaji)

**Files:**
- Create: `apps/docs/components/landing/*.tsx` (hero-title, hero-readme, line-field-bg, signature-mark, staggered-nav-files, footer, trusted-by, framework-sections, halftone-bg, logo-context-menu)
- Create: `apps/docs/app/page.tsx`
- Delete: `apps/docs/app/(home)/`

- [ ] **Step 1: Copy the landing suite**

```bash
mkdir -p apps/docs/components/landing
cp /Users/Enkang.Yuan1/Desktop/Projects/better-auth/docs/components/landing/*.tsx apps/docs/components/landing/
cp /Users/Enkang.Yuan1/Desktop/Projects/better-auth/docs/app/page.tsx apps/docs/app/page.tsx
```

- [ ] **Step 2: Remove the old home route group**

```bash
rm -rf "apps/docs/app/(home)"
```

- [ ] **Step 3: Rebrand copy + data**

Across `apps/docs/components/landing/*` and `app/page.tsx`, replace:
  - "Better Auth" / "better-auth" / "Better Auth Inc." → "kaji"
  - Hero tagline → "The embeddable SDK for building voice agents" (or the description string from `lib/shared`/metadata).
  - Hero CTA links → `/docs/getting-started` (Get Started) and the alloy GitHub repo (`https://github.com/enkyuan/alloy`).
  - Footer links → keep Docs (`/docs`) + GitHub; remove links to non-existent routes (blog/pricing/careers/changelog/legal) or point them at `/docs`.
  - Social links → alloy GitHub; remove `x.com/better_auth` or replace with a placeholder.
  - Logo references → `AgentkitMark` / `public/logo.svg`.
  - **`hero-readme.tsx` + `trusted-by.tsx`:** replace live better-auth npm/GitHub/partner data with static placeholder data (keep the chart/marquee layout; hardcode sample numbers, drop the contributor-API fetch). Remove any `getContributors()`/`getCommunityStats()` server calls in `app/page.tsx` and pass static props.
  - Any import of a better-auth-only lib (e.g. `@/lib/brand-assets`) → copy that lib from better-auth or inline the constants.

- [ ] **Step 4: Strip AI-chat from landing nav if referenced**

If `staggered-nav-files.tsx` imports `ai-chat.tsx` or command-menu/typesense, remove those imports and the corresponding nav entry (out of scope per spec). Keep theme-toggle + nav links.

- [ ] **Step 5: Typecheck**

Run: `~/.bun/bin/bun run typecheck`
Expected: PASS. Resolve each missing import by copying the referenced file from better-auth or removing the feature.

- [ ] **Step 6: Lint**

Run: `~/.bun/bin/bun run lint`
Expected: PASS or pre-existing-only warnings.

- [ ] **Step 7: Commit**

```bash
git add apps/docs/components/landing apps/docs/app/page.tsx
git rm -r "apps/docs/app/(home)"
git commit -m "feat(docs): port rebranded kaji landing page"
```

---

### Task 11: Config — next.config + favicon cleanup

**Files:**
- Modify: `apps/docs/next.config.mjs`

- [ ] **Step 1: Merge optimizePackageImports + images into next.config.mjs**

```mjs
import { createMDX } from "fumadocs-mdx/next";

const withMDX = createMDX();

/** @type {import('next').NextConfig} */
const config = {
  reactStrictMode: true,
  experimental: {
    optimizePackageImports: [
      "lucide-react",
      "motion/react",
      "@radix-ui/react-tabs",
      "@radix-ui/react-scroll-area",
      "@radix-ui/react-popover",
      "@radix-ui/react-select",
      "@radix-ui/react-checkbox",
    ],
  },
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**" },
      { protocol: "http", hostname: "**" },
    ],
  },
};

export default withMDX(config);
```

- [ ] **Step 2: Favicon cleanup (verify clean slate)**

alloy has no `app/icon.tsx`/`app/apple-icon.tsx`/`favicon.ico` (verified). The `app/og/docs/[...slug]/route.tsx` route is per-page social-card generation (renders `site={appName}`), NOT a text favicon — leave it. No removal action needed; this step confirms there is no text-based favicon to strip. User will drop favicon image files into `app/` or `public/` manually.

- [ ] **Step 3: Typecheck + build**

Run: `~/.bun/bin/bun run typecheck` → PASS.
Run: `~/.bun/bin/bun run build` → completes with no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/docs/next.config.mjs
git commit -m "build(docs): optimizePackageImports + image patterns"
```

---

### Task 12: Full verification + browse QA

**Files:** none (verification only)

- [ ] **Step 1: Clean build**

Run: `~/.bun/bin/bun run build`
Expected: PASS, no type/lint/compile errors.

- [ ] **Step 2: Start dev server and QA via /browse**

Run dev server. Use the gstack `/browse` skill (per CLAUDE.md, never use chrome MCP directly) to load:
  - `/` — landing renders, hero + nav + footer present, kaji branding, shape-40 logo, no "Better Auth" strings, no console errors.
  - `/docs` — custom sidebar with Get Started + Concepts sections, active-state tracking, MDX content styled (code blocks flat dark, callouts/cards styled), theme toggle works.
  - Toggle dark/light — tokens apply correctly.

- [ ] **Step 3: Visual diff against source**

Run better-auth docs locally (its own dev server on :3000) and compare `/docs` chrome + `/` layout side by side. Note any divergence; fix obvious breaks.

- [ ] **Step 4: Grep for residual better-auth branding**

Run: `grep -rin "better.auth\|better_auth" apps/docs --include="*.tsx" --include="*.ts" --include="*.css" | grep -v node_modules`
Expected: no user-facing strings remain (imports/comments referencing source are acceptable to clean up).

- [ ] **Step 5: Commit any QA fixes**

```bash
git add -A apps/docs
git commit -m "fix(docs): QA fixes from browse review"
```

---

## Part B — SDK Gap Report

### Task 13: Write the SDK gap-analysis report

**Files:**
- Create: `docs/sdk-gap-analysis.md`

- [ ] **Step 1: Write the report**

Create `docs/sdk-gap-analysis.md` with these sections (content is fully derived from the triage already done — see the design doc §B2/§B3):

  1. **Scope** — TS `kaji/ts/src` vs Python `kaji/sdk/kaji`, serve excluded. Note both share an event-sourced core.
  2. **Surface map** — table: module → exists in Python / exists in TS, for events, store, bus, replay, tools, runtime, providers, voice, knowledge, core infra, sessions, cancellation.
  3. **Aligned** — EventType taxonomy (identical), EventStore interface, tool registry shape (modulo naming).
  4. **Missing in TS** — real providers (openai/kimi/gemini), voice/STT/TTS, knowledge/RAG, core infra (config/redis/db/auth/observability), SessionManager/SessionStore, AgentStrategy, ToolPlanner, Swarm, neutral tool-payload translators.
  5. **Alignment issues** — the 18-row table from triage (field naming `userId`/`user_id`; tool-call shape `{id,name,args}` vs `{name,arguments,id}`; `toolCallId` threading; TOOL_CALL_FAILED projection; EventBus return/subscribe params; provider `generate` params + metrics; result stringification; emit ordering; cancellation model; `send()`/MAX_TOOL_ITERATIONS).
  6. **Critical cross-SDK divergences** — why event logs are not byte-for-byte replayable across SDKs today (tool-call field names, tool_call_id threading, failure projection, emit ordering).
  7. **Prioritized closure plan** — P0 wire-compat, P1 capability parity (port OpenAI provider + payload translators first), P2 ergonomics, P3 larger ports (voice/RAG/Redis/Swarm). For each item: the specific file(s) to change in each SDK and the decision required (e.g. "pick `args` vs `arguments` as the canonical wire key").

  Cite exact file paths (from the design doc's file-path appendix). Keep prose terse and technical (no em-dashes, per writing-style preference).

- [ ] **Step 2: Sanity-check the report against current code**

For each "alignment issue", re-open the cited TS and Python file and confirm the claim still holds (memories/triage are point-in-time). Fix any drifted claim.

Files to spot-check:
  - `kaji/ts/src/tools/registry.ts` vs `kaji/sdk/kaji/runtime/tools/registry.py` (ToolContext naming)
  - `kaji/ts/src/providers/base.ts` vs `kaji/sdk/kaji/runtime/providers/base.py` (tool-call shape, generate params)
  - `kaji/ts/src/sessions/replay.ts` vs `kaji/sdk/kaji/infra/events/replay.py` (toolCallId, failure projection)
  - `kaji/ts/src/events/bus.ts` vs `kaji/sdk/kaji/infra/events/bus.py` (publish/subscribe contract)

- [ ] **Step 3: Commit**

```bash
git add docs/sdk-gap-analysis.md
git commit -m "docs: TS-vs-Python SDK gap analysis + closure plan"
```

---

## Self-Review Notes

- **Spec coverage:** A1→Task 3, A2→Task 9, A3→Tasks 2+4, A4→Task 5, A5→Tasks 7+8, A6→Task 10, A7→Task 6 (+favicon in Task 11), A8→Task 11, A9→Task 1, A10→per-task + Task 12. Part B→Task 13. All covered.
- **Ordering note:** Task 9 references `StaggeredNavFiles` (Task 10). Either reorder 9 after 10, or use the stub-then-restore note in Task 9 Step 1. Subagent executor should do Task 10 before wiring the nav overlay live, OR keep the line commented until Task 10 completes.
- **Version-skew risk** handled by typecheck gate after every component task (4, 5, 7, 8, 10).
- **No SDK code changes** anywhere in Part A/B — Task 13 is report-only, satisfying the locked decision.
