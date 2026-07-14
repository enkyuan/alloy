# @kaji/docs

Public documentation for Kaji, built with
[Fumadocs](https://fumadocs.dev) and Next.js.

## Local development

```bash
# from repo root
bun --filter @kaji/docs dev

# or from this directory
bun dev
```

Open [http://localhost:3000](http://localhost:3000).

## Structure

| Path                      | Purpose                              |
| ------------------------- | ------------------------------------ |
| `app/page.tsx`            | Landing page                         |
| `app/docs/`               | Documentation routes and layout      |
| `content/`                | MDX pages and navigation metadata    |
| `components/`             | Site, navigation, and MDX components |
| `lib/source.ts`           | Fumadocs content source adapter      |
| `app/api/search/route.ts` | Full-text search endpoint            |

## Content contracts

Documentation lives in `content/`. The source config in `source.config.ts`
controls frontmatter and page metadata. `bun run check:sdk-sync` verifies the
documented SDK versions, CLI commands, event types, integration catalog, and
recovery anchors against the repository contracts.

When changing `kaji`, `kaji/ts`, or either embedded CLI, update the relevant
MDX page in the same pull request. Keep beta and experimental surfaces labeled
explicitly; do not turn local or unprotected evidence into a release claim.

## Checks

```bash
bun run check:sdk-sync
bun run build      # production build
bun run typecheck  # tsc --noemit
bun run lint       # oxlint
bun run format:check
```

## Further reading

- [`kaji/README.md`](../../kaji/README.md) -- Kaji concepts, architecture, and Python SDK reference
- [`kaji/ts/README.md`](../../kaji/ts/README.md) -- TypeScript SDK reference
