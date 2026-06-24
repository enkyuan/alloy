# @kaji/docs

public documentation site for kaji. built with [fumadocs](https://fumadocs.dev) on next.js.

## running locally

```bash
# from repo root
bun --filter @kaji/docs dev

# or from this directory
bun dev
```

open [http://localhost:3000](http://localhost:3000).

## structure

| path                      | purpose                            |
| ------------------------- | ---------------------------------- |
| `app/(home)`              | landing page                       |
| `app/docs`                | documentation layout and pages     |
| `content/docs/`           | MDX source files for all doc pages |
| `lib/source.ts`           | fumadocs content source adapter    |
| `app/api/search/route.ts` | full-text search endpoint          |

## content

documentation content lives in `content/docs/` as MDX files. the source
config in `source.config.ts` controls frontmatter schema and page
metadata. a CI test (`test/docs-sync`) checks that code examples in the
docs match the shipped SDK surface.

## development

```bash
bun run build      # production build
bun run typecheck  # tsc --noemit
bun run lint       # eslint
```

## further reading

- [`kaji/README.md`](../../kaji/README.md) -- kaji concepts and architecture
- [`kaji/sdk/README.md`](../../kaji/sdk/README.md) -- Python SDK reference
- [`kaji/ts/README.md`](../../kaji/ts/README.md) -- TypeScript SDK reference
