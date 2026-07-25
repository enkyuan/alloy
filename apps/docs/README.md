# @kaji/docs

Public documentation for Kaji, built with [Astro](https://astro.build).

## Local development

```bash
# from repo root
bun --filter @kaji/docs dev

# or from this directory
bun dev
```

Open [http://localhost:3000](http://localhost:3000).

## Structure

| Path                         | Purpose                                |
| ---------------------------- | -------------------------------------- |
| `src/pages/index.astro`      | Landing page                           |
| `src/pages/docs/`            | Static documentation routes            |
| `content/`                   | MDX pages                              |
| `src/components/content/`    | MDX primitives and page behavior       |
| `src/components/navigation/` | Desktop, mobile, and page navigation   |
| `src/components/site/`       | Brand, footer, and landing demo        |
| `src/content.config.ts`      | Astro content collection schema        |
| `src/data/navigation.ts`     | Documentation information architecture |
| `src/styles/global.css`      | Agentation-derived visual system       |

## Content contracts

Documentation lives in `content/`. The collection schema in
`src/content.config.ts` controls frontmatter and page metadata.
`bun run check:sdk-sync` verifies the
documented SDK versions, CLI commands, event types, integration catalog, and
recovery anchors against the repository contracts.

When changing `kaji`, `kaji/ts`, or either embedded CLI, update the relevant
MDX page in the same pull request. Keep beta and experimental surfaces labeled
explicitly; do not turn local or unprotected evidence into a release claim.

## Checks

```bash
bun run check:sdk-sync
bun run build      # production build
bun run typecheck  # SDK sync + Astro diagnostics
bun run lint       # oxlint
bun run format:check
```

## Further reading

- [`kaji/README.md`](../../kaji/README.md) -- Kaji concepts, architecture, and Python SDK reference
- [`kaji/ts/README.md`](../../kaji/ts/README.md) -- TypeScript SDK reference
