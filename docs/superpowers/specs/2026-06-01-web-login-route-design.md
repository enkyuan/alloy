# Web login route + TanStack file-based routing

Date: 2026-06-01
Package: `apps/web` (`@ryo/web`)

## Goal

Remove the Vite + React boilerplate theme/screen and replace it with a TanStack
file-based router. Add a `/login` route that renders a login page built from
shadcn's `login-01` block. Submit is a stub (no better-auth wiring yet).

## Current state

- `main.tsx` renders `App.tsx` directly. No router is wired.
- `@tanstack/react-router` is a dependency but `@tanstack/router-plugin` (the
  Vite plugin needed for file-based routing) is NOT installed.
- shadcn primitives live in `src/components/ui/` (config `components.json` aliases
  `ui` -> `@/components/ui`). Existing: button, input, badge.
- Boilerplate lives in `App.tsx`, `App.css`, `src/assets/{hero.png,react.svg,vite.svg}`,
  `public/icons.svg`, and a block of custom CSS vars at the top of `index.css`.
- TanStack Form + zod are already deps (used for the form).

## Remove

- `src/App.tsx`, `src/App.css`
- `src/assets/hero.png`, `src/assets/react.svg`, `src/assets/vite.svg`
  (only referenced by `App.tsx`)
- `public/icons.svg` (boilerplate sprite)
- The boilerplate CSS block at the top of `index.css`: custom vars (`--text`,
  `--text-h`, `--bg`, `--code-bg`, `--accent-bg`, `--social-bg`, `--shadow`,
  `--sans`/`--heading`/`--mono`, the root `font:`/color rules), the
  `prefers-color-scheme` overrides for those vars, `#root { width:1126px ... }`,
  `h1/h2/p/code/.counter` boilerplate typography, `#social` filter.

## Keep (in index.css)

- `@import` lines (tailwindcss, tw-animate-css, shadcn/tailwind.css, dm-sans)
- `@custom-variant dark`
- shadcn theme tokens: `--background`, `--foreground`, `--primary`, etc.
- `@theme inline` block, `.dark` block, `@layer base` block

## Add

1. **Router plugin** — add `@tanstack/router-plugin` as a devDependency. Wire
   `tanstackRouter({ target: 'react', autoCodeSplitting: true })` into
   `vite.config.ts`, placed BEFORE `react()`.
2. **Generated route tree** — `src/routeTree.gen.ts` (auto-generated; add to
   `apps/web/.gitignore`).
3. **Routes** (`src/routes/`):
   - `__root.tsx` — `createRootRoute`, renders `<Outlet />`.
   - `index.tsx` — minimal placeholder `/` route.
   - `login.tsx` — `createFileRoute('/login')`; component renders `<LoginPage />`.
4. **Page** — `src/components/pages/login.tsx` exporting `LoginPage`; centers/lays
   out the form.
5. **Auth form** — `src/components/auth/login.tsx` exporting the login form.
   Generated via `bunx shadcn@latest add login-01`, then the generated block file
   moved/renamed to this path with imports fixed. New shadcn primitives it pulls
   (e.g. card, label) land in `src/components/ui/`. Form uses TanStack Form + zod;
   `onSubmit` is a stub (no-op / console).
6. **main.tsx** — replace `<App />` with `createRouter({ routeTree })` +
   `<RouterProvider router={router} />` and the
   `declare module '@tanstack/react-router'` register block.

## Data flow

`main.tsx` (RouterProvider) -> match `/login` -> `routes/login.tsx` ->
`components/pages/login.tsx` (LoginPage) -> `components/auth/login.tsx` (form).
Form state via TanStack Form, validated by zod, `onSubmit` stubbed.

## Verification

- `bun run typecheck` passes
- `bun run build` passes
- `bun run dev` serves `/login` rendering the form, no boilerplate remnants

## Risks / notes

- `bunx shadcn add login-01` output filename and exact primitive set are unknown
  until run; move/rename whatever it produces into the target paths and fix imports.
- Per project memory, shadcn primitives belong in the ui dir only; live config
  points that at `src/components/ui/`, so follow the config.
