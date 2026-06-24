# @ryo/web

studio -- the merchant-facing dashboard for ryo. lets merchants configure agents,
connect payment providers, manage their wallet, and inspect webhook deliveries.

**stack:** react 19, typescript, vite, tanstack router + query + form, tailwind css v4, shadcn/ui, better-auth, zod.

## running locally

```bash
bun install
bun dev   # default port 5173
```

**environment variables** (copy from `.env.example`):

| variable        | purpose                                                    |
| --------------- | ---------------------------------------------------------- |
| `VITE_API_URL`  | base url for `@ryo/api` (default `http://localhost:8090`)  |
| `VITE_AUTH_URL` | base url for `@ryo/auth` (default `http://localhost:8080`) |

## routes

| path         | description                              |
| ------------ | ---------------------------------------- |
| `/`          | landing / redirect to dashboard or login |
| `/login`     | email + password sign-in                 |
| `/signup`    | account creation                         |
| `/dashboard` | agent list and org overview              |
| `/webhooks`  | register and inspect webhook deliveries  |

## development

```bash
bun run build      # production build
bun run typecheck  # tsc --noemit
bun run lint       # eslint
```

ui primitives (shadcn components) go in `src/ui/` only.

## further reading

- [`ryo/README.md`](../../ryo/README.md) -- ryo product overview, api routes, data model
