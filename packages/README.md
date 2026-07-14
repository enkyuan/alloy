# Packages

Private TypeScript packages shared by multiple Alloy applications. Deployable
applications and published developer tools belong in [`apps/`](../apps).

| Path               | Name           | Purpose                                                                          |
| ------------------ | -------------- | -------------------------------------------------------------------------------- |
| [`ui`](ui)         | `@kaji/ui`     | Shared UI utilities and opt-in development helpers used by the web and docs apps |
| [`shared`](shared) | `@kaji/shared` | Base, React, and Node TypeScript configurations for workspace packages           |

These packages expose source directly to workspace consumers and are not
published independently. Install dependencies at the repository root, then run
focused checks:

```bash
bun --filter @kaji/ui format:check
bun --filter @kaji/ui typecheck
bun --filter @kaji/shared format:check
```

`@kaji/shared` contains configuration only. Changes to its exported tsconfig
files must be verified against every consuming workspace: `apps/web`,
`apps/cli`, and `packages/ui`.
