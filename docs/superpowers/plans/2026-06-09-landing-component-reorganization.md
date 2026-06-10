# Landing Component Reorganization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize `apps/docs/components/landing/` so every section has its own subdirectory, rename files to be consistent and descriptive (kebab-case, two-phrase max), update all exports and cross-file imports, fix broken `@lib/landing/nav-*` path resolution, fix stale `./tools-data` import, and resolve all 4 react-doctor warnings to reach 90+.

**Architecture:** Each landing section becomes a subdirectory (`nav/`, `hero/`, `features/`, `tools/`, `providers/`, `integrations/`, `footer/`); shared UI helpers go in `shared/`. The `lib/landing/nav/` files are moved flat to `lib/landing/` so existing `@lib/landing/nav-data` and `@lib/landing/nav-sections-data` path aliases resolve correctly. All imports are updated in-place; no new abstractions are introduced.

**Tech Stack:** Next.js 15, React 19, TypeScript, Tailwind CSS 4, `npx react-doctor` for validation.

---

## File Map

### Files being renamed / moved

| Old path | New path | Reason |
|---|---|---|
| `components/landing/line-field-bg.tsx` | `components/landing/hero/field-bg.tsx` | belongs to hero section |
| `components/landing/signature-mark.tsx` | `components/landing/footer/signature-mark.tsx` | used in footer slot |
| `components/landing/readme-footer.tsx` | `components/landing/footer/readme-stats.tsx` | describes what it shows |
| `components/landing/logo-context-menu.tsx` | `components/landing/shared/logo-menu.tsx` | shared across sections |
| `components/landing/staggered-nav-files.tsx` | `components/landing/nav/staggered-files.tsx` | belongs in nav section |
| `components/landing/agent-loop-tabs.tsx` | `components/landing/features/agent-loop.tsx` | belongs in features section |
| `components/landing/ai-native-section.tsx` | `components/landing/features/ai-native.tsx` | belongs in features section |
| `components/landing/capabilities-marquee.tsx` | `components/landing/features/capabilities-marquee.tsx` | belongs in features section |
| `components/landing/features-grid-marks.tsx` | `components/landing/features/grid-marks.tsx` | belongs in features section |
| `components/landing/framework-sections.tsx` | `components/landing/features/index.tsx` | barrel re-export for features |
| `lib/landing/nav/data.ts` | `lib/landing/nav-data.ts` | fix path resolution |
| `lib/landing/nav/sections-data.ts` | `lib/landing/nav-sections-data.ts` | fix path resolution |

### Files kept in place (already correct)

- `components/landing/hero/title.tsx` — stays
- `components/landing/hero/readme.tsx` — stays
- `components/landing/nav/desktop-dropdowns.tsx` — stays
- `components/landing/nav/mobile-menu.tsx` — stays
- `components/landing/nav/patterns.tsx` — stays (once nav-data resolves)
- `components/landing/install/block.tsx` — stays
- `components/landing/install/mcp-dropdown.tsx` — stays
- `components/landing/install/prompt-dialog.tsx` — stays
- `components/landing/tools/section.tsx` — stays
- `components/landing/tools/data.tsx` — stays
- `components/landing/integrations/section.tsx` — stays
- `components/landing/integrations/data.tsx` — stays
- `components/landing/providers/section.tsx` — stays
- `components/landing/providers/data.tsx` — stays

### Callers being updated

| File | Change |
|---|---|
| `app/page.tsx` | Update imports for moved hero/footer/shared files |
| `app/layout.tsx` | Update import for staggered-nav-files → nav/staggered-files |
| `components/landing/features/capabilities-marquee.tsx` | Fix stale `./tools-data` → `../tools/data` |
| `components/landing/features/agent-loop.tsx` | Fix `./providers/data` → `../providers/data` |
| `lib/landing/nav-sections-data.ts` | Fix import from `@components/landing/nav/patterns` (stays valid) and `@lib/landing/nav-data` (now resolves) |

### react-doctor issues resolved

1. `deslop/unused-file: components/landing/nav/patterns.tsx` — fixed by moving `lib/landing/nav/sections-data.ts` to flat `lib/landing/nav-sections-data.ts` so the chain resolves
2. `deslop/unused-file: lib/landing/nav/data.ts` — fixed by moving to `lib/landing/nav-data.ts`
3. `deslop/unused-file: lib/landing/nav/sections-data.ts` — fixed by moving to `lib/landing/nav-sections-data.ts`
4. `deslop/unused-export: categoryLabels (tools/data.tsx:155)` — fixed by removing `export` keyword (only used internally via `../tools/data` in `capabilities-marquee`)

---

## Task 1: Move lib/landing/nav files to flat paths

**Files:**
- Create: `apps/docs/lib/landing/nav-data.ts`
- Create: `apps/docs/lib/landing/nav-sections-data.ts`
- Delete: `apps/docs/lib/landing/nav/data.ts`
- Delete: `apps/docs/lib/landing/nav/sections-data.ts`

- [ ] **Step 1: Copy nav/data.ts to nav-data.ts**

```bash
cp apps/docs/lib/landing/nav/data.ts apps/docs/lib/landing/nav-data.ts
```

- [ ] **Step 2: Copy nav/sections-data.ts to nav-sections-data.ts**

The new file is identical except the import path for `nav-data` is now flat:

```typescript
// apps/docs/lib/landing/nav-sections-data.ts
import { History, PencilLine, Scale } from "lucide-react";
import type { LinkResource, MobileMenuSection, NavFileItem, ProductItem } from "@lib/landing/nav-data";
import {
  CommunityIcon,
  FrameworkLogoIcon,
  InfraLogoIcon,
  ScribblePattern,
  TimelinePattern,
  VerticalLinesPattern,
} from "@components/landing/nav/patterns";
// ... (rest of file identical to lib/landing/nav/sections-data.ts)
```

Read `apps/docs/lib/landing/nav/sections-data.ts` in full, copy its content verbatim to `apps/docs/lib/landing/nav-sections-data.ts`, changing only the import `from "@lib/landing/nav-data"` (which stays the same since the new flat file is also at that path).

- [ ] **Step 3: Delete the old nav/ subdirectory files**

```bash
rm apps/docs/lib/landing/nav/data.ts
rm apps/docs/lib/landing/nav/sections-data.ts
rmdir apps/docs/lib/landing/nav
```

- [ ] **Step 4: Verify TypeScript resolves — no new errors**

```bash
cd apps/docs && bun run typecheck 2>&1 | grep -E "error TS|nav" | head -20
```

Expected: no errors referencing nav-data or nav-sections-data.

- [ ] **Step 5: Commit**

```bash
git add apps/docs/lib/landing/nav-data.ts apps/docs/lib/landing/nav-sections-data.ts
git rm apps/docs/lib/landing/nav/data.ts apps/docs/lib/landing/nav/sections-data.ts
git commit -m "fix(landing): move lib/landing/nav/* to flat paths so @lib/landing/nav-data resolves"
```

---

## Task 2: Create hero/ subdirectory — move line-field-bg

**Files:**
- Create: `apps/docs/components/landing/hero/field-bg.tsx`
- Delete: `apps/docs/components/landing/line-field-bg.tsx`
- Modify: `apps/docs/app/page.tsx`

- [ ] **Step 1: Copy line-field-bg.tsx to hero/field-bg.tsx**

```bash
cp apps/docs/components/landing/line-field-bg.tsx apps/docs/components/landing/hero/field-bg.tsx
```

The export name `LineFieldBackground` stays unchanged.

- [ ] **Step 2: Update app/page.tsx import**

In `apps/docs/app/page.tsx`, change:
```typescript
import { LineFieldBackground } from "@components/landing/line-field-bg";
```
to:
```typescript
import { LineFieldBackground } from "@components/landing/hero/field-bg";
```

- [ ] **Step 3: Delete old file**

```bash
git rm apps/docs/components/landing/line-field-bg.tsx
```

- [ ] **Step 4: Verify**

```bash
cd apps/docs && bun run typecheck 2>&1 | grep -E "error TS|field-bg|line-field" | head -10
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add apps/docs/components/landing/hero/field-bg.tsx apps/docs/app/page.tsx
git commit -m "refactor(landing): move line-field-bg into hero/ as field-bg"
```

---

## Task 3: Create footer/ subdirectory — move signature-mark and readme-footer

**Files:**
- Create: `apps/docs/components/landing/footer/signature-mark.tsx`
- Create: `apps/docs/components/landing/footer/readme-stats.tsx`
- Delete: `apps/docs/components/landing/signature-mark.tsx`
- Delete: `apps/docs/components/landing/readme-footer.tsx`
- Modify: `apps/docs/app/page.tsx`

- [ ] **Step 1: Move signature-mark.tsx**

```bash
mkdir -p apps/docs/components/landing/footer
cp apps/docs/components/landing/signature-mark.tsx apps/docs/components/landing/footer/signature-mark.tsx
```

Export name `SignatureMark` stays unchanged.

- [ ] **Step 2: Move readme-footer.tsx → readme-stats.tsx**

```bash
cp apps/docs/components/landing/readme-footer.tsx apps/docs/components/landing/footer/readme-stats.tsx
```

The exported names `CommunityHeroStats`, `ReadmeFooter` (check exact exports), and `formatCount` re-export stay unchanged. Confirm by reading the file first.

- [ ] **Step 3: Update app/page.tsx imports**

In `apps/docs/app/page.tsx`, change:
```typescript
import { SignatureMark } from "@components/landing/signature-mark";
```
to:
```typescript
import { SignatureMark } from "@components/landing/footer/signature-mark";
```

If `readme-footer` is also imported in `page.tsx` or elsewhere, update those too. Search first:
```bash
grep -rn "readme-footer\|ReadmeFooter\|readme-stats" apps/docs/ --include="*.tsx" --include="*.ts" | grep -v node_modules
```

- [ ] **Step 4: Delete old files**

```bash
git rm apps/docs/components/landing/signature-mark.tsx
git rm apps/docs/components/landing/readme-footer.tsx
```

- [ ] **Step 5: Verify**

```bash
cd apps/docs && bun run typecheck 2>&1 | grep -E "error TS|signature|readme-footer|readme-stats" | head -10
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add apps/docs/components/landing/footer/
git commit -m "refactor(landing): move signature-mark and readme-footer into footer/"
```

---

## Task 4: Create shared/ subdirectory — move logo-context-menu

**Files:**
- Create: `apps/docs/components/landing/shared/logo-menu.tsx`
- Delete: `apps/docs/components/landing/logo-context-menu.tsx`

- [ ] **Step 1: Find all callers of logo-context-menu**

```bash
grep -rn "logo-context-menu\|LogoContextMenu" apps/docs/ --include="*.tsx" --include="*.ts" | grep -v node_modules
```

Note every file that imports it.

- [ ] **Step 2: Move the file**

```bash
mkdir -p apps/docs/components/landing/shared
cp apps/docs/components/landing/logo-context-menu.tsx apps/docs/components/landing/shared/logo-menu.tsx
```

Export name `LogoContextMenu` stays unchanged.

- [ ] **Step 3: Update all callers**

For each file found in Step 1, change the import path from `@components/landing/logo-context-menu` to `@components/landing/shared/logo-menu`.

- [ ] **Step 4: Delete old file**

```bash
git rm apps/docs/components/landing/logo-context-menu.tsx
```

- [ ] **Step 5: Verify**

```bash
cd apps/docs && bun run typecheck 2>&1 | grep -E "error TS|logo-context\|logo-menu" | head -10
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add apps/docs/components/landing/shared/
git commit -m "refactor(landing): move logo-context-menu into shared/ as logo-menu"
```

---

## Task 5: Create features/ subdirectory — move flat feature files

**Files:**
- Create: `apps/docs/components/landing/features/agent-loop.tsx`
- Create: `apps/docs/components/landing/features/ai-native.tsx`
- Create: `apps/docs/components/landing/features/capabilities-marquee.tsx`
- Create: `apps/docs/components/landing/features/grid-marks.tsx`
- Create: `apps/docs/components/landing/features/index.tsx` (replaces framework-sections.tsx barrel)
- Delete: `apps/docs/components/landing/agent-loop-tabs.tsx`
- Delete: `apps/docs/components/landing/ai-native-section.tsx`
- Delete: `apps/docs/components/landing/capabilities-marquee.tsx`
- Delete: `apps/docs/components/landing/features-grid-marks.tsx`
- Delete: `apps/docs/components/landing/framework-sections.tsx`

- [ ] **Step 1: Move agent-loop-tabs.tsx → features/agent-loop.tsx**

```bash
mkdir -p apps/docs/components/landing/features
cp apps/docs/components/landing/agent-loop-tabs.tsx apps/docs/components/landing/features/agent-loop.tsx
```

The file imports from `./providers/data` — update that to `../providers/data`:

In `apps/docs/components/landing/features/agent-loop.tsx`, change:
```typescript
import { serverCodeTs, serverCodePy } from "./providers/data";
```
to:
```typescript
import { serverCodeTs, serverCodePy } from "../providers/data";
```

Export name `AgentLoopTabs` stays unchanged.

- [ ] **Step 2: Move ai-native-section.tsx → features/ai-native.tsx**

```bash
cp apps/docs/components/landing/ai-native-section.tsx apps/docs/components/landing/features/ai-native.tsx
```

Export name `AiNativeSection` stays unchanged. No import path changes needed (no relative imports).

- [ ] **Step 3: Move capabilities-marquee.tsx → features/capabilities-marquee.tsx, fix stale import**

```bash
cp apps/docs/components/landing/capabilities-marquee.tsx apps/docs/components/landing/features/capabilities-marquee.tsx
```

In `apps/docs/components/landing/features/capabilities-marquee.tsx`, change:
```typescript
import { categoryLabels } from "./tools-data";
```
to:
```typescript
import { categoryLabels } from "../tools/data";
```

Export name `CapabilitiesMarquee` stays unchanged.

- [ ] **Step 4: Move features-grid-marks.tsx → features/grid-marks.tsx**

```bash
cp apps/docs/components/landing/features-grid-marks.tsx apps/docs/components/landing/features/grid-marks.tsx
```

Export name `FeaturesGridMarks` (confirm by reading the file) stays unchanged. No relative imports to update.

- [ ] **Step 5: Create features/index.tsx barrel**

Replace `framework-sections.tsx` with a new barrel at `features/index.tsx`:

```typescript
// apps/docs/components/landing/features/index.tsx
// react-doctor-disable-next-line only-export-components, react-doctor/only-export-components
export { plugins } from "@lib/landing/plugins-data";
export { AgentLoopTabs } from "./agent-loop";
export { ProvidersSection } from "../providers/section";
export { ToolsSection } from "../tools/section";
export { IntegrationsSection } from "../integrations/section";
export { CapabilitiesMarquee } from "./capabilities-marquee";
export { AiNativeSection } from "./ai-native";
```

- [ ] **Step 6: Find all callers of the old flat paths**

```bash
grep -rn "landing/agent-loop-tabs\|landing/ai-native-section\|landing/capabilities-marquee\|landing/features-grid-marks\|landing/framework-sections\|AgentLoopTabs\|AiNativeSection\|CapabilitiesMarquee\|FeaturesGridMarks" apps/docs/ --include="*.tsx" --include="*.ts" | grep -v node_modules | grep -v "components/landing/features"
```

Update each caller:
- `from "@components/landing/framework-sections"` → `from "@components/landing/features"`
- `from "@components/landing/agent-loop-tabs"` → `from "@components/landing/features/agent-loop"`
- `from "@components/landing/ai-native-section"` → `from "@components/landing/features/ai-native"`
- `from "@components/landing/capabilities-marquee"` → `from "@components/landing/features/capabilities-marquee"`
- `from "@components/landing/features-grid-marks"` → `from "@components/landing/features/grid-marks"`

- [ ] **Step 7: Delete old files**

```bash
git rm apps/docs/components/landing/agent-loop-tabs.tsx
git rm apps/docs/components/landing/ai-native-section.tsx
git rm apps/docs/components/landing/capabilities-marquee.tsx
git rm apps/docs/components/landing/features-grid-marks.tsx
git rm apps/docs/components/landing/framework-sections.tsx
```

- [ ] **Step 8: Verify**

```bash
cd apps/docs && bun run typecheck 2>&1 | grep "error TS" | head -20
```

Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add apps/docs/components/landing/features/
git commit -m "refactor(landing): group feature components into features/ subdirectory"
```

---

## Task 6: Move staggered-nav-files into nav/

**Files:**
- Create: `apps/docs/components/landing/nav/staggered-files.tsx`
- Delete: `apps/docs/components/landing/staggered-nav-files.tsx`
- Modify: `apps/docs/app/layout.tsx`

- [ ] **Step 1: Move the file**

```bash
cp apps/docs/components/landing/staggered-nav-files.tsx apps/docs/components/landing/nav/staggered-files.tsx
```

No relative imports inside the file to update (uses `@lib/landing/nav-sections-data`).

Export name `StaggeredNavFiles` stays unchanged.

- [ ] **Step 2: Update app/layout.tsx**

In `apps/docs/app/layout.tsx`, change:
```typescript
import { StaggeredNavFiles } from "@components/landing/staggered-nav-files";
```
to:
```typescript
import { StaggeredNavFiles } from "@components/landing/nav/staggered-files";
```

- [ ] **Step 3: Delete old file**

```bash
git rm apps/docs/components/landing/staggered-nav-files.tsx
```

- [ ] **Step 4: Verify**

```bash
cd apps/docs && bun run typecheck 2>&1 | grep "error TS" | head -10
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add apps/docs/components/landing/nav/staggered-files.tsx apps/docs/app/layout.tsx
git commit -m "refactor(landing): move staggered-nav-files into nav/ as staggered-files"
```

---

## Task 7: Fix unused export — drop export from categoryLabels

**Files:**
- Modify: `apps/docs/components/landing/tools/data.tsx:155`

- [ ] **Step 1: Read and confirm**

Read `apps/docs/components/landing/tools/data.tsx` around line 155. Confirm `categoryLabels` is defined there and that the only consumer is `features/capabilities-marquee.tsx` (which imports it as `../tools/data` — a relative internal import, so `export` is only needed for cross-file use within the same package, which is fine — but react-doctor is complaining it is exported yet has no *external* consumer).

Actually the correct fix is to keep the export (it IS consumed by another file), but confirm that `capabilities-marquee.tsx` now correctly imports from `../tools/data` (done in Task 5 Step 3). After Task 5, react-doctor should resolve this warning because the import chain will be intact.

Run react-doctor after Task 5 and 6 to confirm this warning clears:
```bash
cd apps/docs && npx react-doctor --verbose 2>&1 | grep -E "categoryLabels|unused-export"
```

If it still shows, remove the `export` keyword from `categoryLabels` in `tools/data.tsx:155` and verify `capabilities-marquee.tsx` still imports it from `../tools/data` (which is a relative import — no `export` needed for that — wait, yes export IS needed for a named import between files).

The actual fix: the warning fires because react-doctor scanned the OLD path where `capabilities-marquee.tsx` was importing from `./tools-data` (a non-existent path), so the import resolved to nothing, making `categoryLabels` appear unconsumed. Fixing the import in Task 5 Step 3 resolves this.

- [ ] **Step 2: Run react-doctor to confirm all 4 warnings cleared**

```bash
cd apps/docs && npx react-doctor --verbose 2>&1
```

Expected output: `90 / 100` or higher, 0 warnings.

- [ ] **Step 3: Commit if any manual fix was needed**

Only needed if Step 2 still shows the `categoryLabels` warning after Task 5 is done. If so:

In `apps/docs/components/landing/tools/data.tsx`, line ~155, change:
```typescript
export const categoryLabels: Record<string, string> = {
```
to:
```typescript
const categoryLabels: Record<string, string> = {
```

Then:
```bash
git add apps/docs/components/landing/tools/data.tsx
git commit -m "fix(landing): remove unused export from categoryLabels in tools/data"
```

---

## Task 8: Final verification

- [ ] **Step 1: Full typecheck**

```bash
cd apps/docs && bun run typecheck 2>&1 | grep "error TS" | head -30
```

Expected: 0 TypeScript errors.

- [ ] **Step 2: React-doctor final score**

```bash
cd apps/docs && npx react-doctor --verbose 2>&1
```

Expected: 90+ score, 0 warnings.

- [ ] **Step 3: Verify final directory structure**

```bash
find apps/docs/components/landing -type f | sort
```

Expected structure:
```
components/landing/
  features/
    agent-loop.tsx        (was agent-loop-tabs.tsx)
    ai-native.tsx         (was ai-native-section.tsx)
    capabilities-marquee.tsx
    grid-marks.tsx        (was features-grid-marks.tsx)
    index.tsx             (was framework-sections.tsx)
  footer/
    readme-stats.tsx      (was readme-footer.tsx)
    signature-mark.tsx
  hero/
    field-bg.tsx          (was line-field-bg.tsx)
    readme.tsx
    title.tsx
  install/
    block.tsx
    mcp-dropdown.tsx
    prompt-dialog.tsx
  integrations/
    data.tsx
    section.tsx
  nav/
    desktop-dropdowns.tsx
    mobile-menu.tsx
    patterns.tsx
    staggered-files.tsx   (was staggered-nav-files.tsx)
  providers/
    data.tsx
    section.tsx
  shared/
    logo-menu.tsx         (was logo-context-menu.tsx)
  tools/
    data.tsx
    section.tsx
```

- [ ] **Step 4: Verify lib/landing structure**

```bash
find apps/docs/lib/landing -type f | sort
```

Expected:
```
lib/landing/
  nav-data.ts          (was nav/data.ts)
  nav-sections-data.ts (was nav/sections-data.ts)
  plugins-data.ts
  readme-footer-utils.ts
```

- [ ] **Step 5: Final commit if anything lingering**

```bash
git status
```

If clean, no commit needed. Otherwise add and commit remaining changes.
