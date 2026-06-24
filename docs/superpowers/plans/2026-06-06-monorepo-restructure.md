# Monorepo Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize the monorepo so all agentpay services live under `agentpay/`, all kaji SDK packages live under `kaji/`, and `apps/` holds only the web frontend — making the boundary between the two products structurally visible and scaling cleanly to future Go microservices.

**Architecture:** `agentpay/` contains every deployed agentpay service (`api`, `consumer`, `auth`) regardless of language. `kaji/` replaces `packages/` for all SDK packages (`sdk`, `serve`, `ts`). `apps/` narrows to `web` only. `docker/` is untouched — `docker/agentpay/` and `docker/kaji/` stay where they are, with compose context paths updated. `apps/docker/` (empty stubs) is deleted.

**Tech Stack:** Go 1.25 (go.mod module renames + internal import path sed), Bun/Turbo (workspace globs in package.json), GitHub Actions (working-directory + paths triggers), Python Poetry (path dep `../sdk` stays valid after parallel rename).

---

## File Map

| Old path | New path | Change type |
|---|---|---|
| `apps/api/` | `agentpay/api/` | move + module rename |
| `apps/consumer/` | `agentpay/consumer/` | move + module rename |
| `apps/auth/` | `agentpay/auth/` | move |
| `packages/sdk/` | `kaji/sdk/` | move |
| `packages/serve/` | `kaji/serve/` | move + path dep update |
| `packages/ts/` | `kaji/ts/` | move |
| `apps/web/` | `apps/web/` | unchanged |
| `apps/docker/` | *(deleted)* | empty stubs |
| `docker/agentpay/docker-compose.yml` | same | context path update |
| `package.json` | same | workspaces glob update |
| `turbo.json` | same | no change needed (uses package names not paths) |
| `.github/workflows/sdk-tests.yml` | same | working-directory + paths triggers |

---

## Task 1: Move agentpay services

Move the three deployed agentpay services into a new `agentpay/` top-level directory.

**Files:**
- Move: `apps/api/` → `agentpay/api/`
- Move: `apps/consumer/` → `agentpay/consumer/`
- Move: `apps/auth/` → `agentpay/auth/`
- Delete: `apps/docker/` (empty)

- [ ] **Step 1: Create the agentpay/ directory and move services**

```bash
mkdir -p agentpay
git mv apps/api agentpay/api
git mv apps/consumer agentpay/consumer
git mv apps/auth agentpay/auth
```

- [ ] **Step 2: Delete the empty apps/docker stubs**

```bash
git rm -r apps/docker
```

- [ ] **Step 3: Verify the moves**

```bash
ls agentpay/
# Expected: api  consumer  auth
ls apps/
# Expected: web  (apps/docker gone)
git status --short | head -30
# Should show renames for api, consumer, auth files; deletions for apps/docker
```

- [ ] **Step 4: Commit**

```bash
git add agentpay/ apps/
git commit -m "refactor: move agentpay services into agentpay/"
```

---

## Task 2: Move kaji SDK packages

Move all SDK packages from `packages/` into a new `kaji/` top-level directory.

**Files:**
- Move: `packages/sdk/` → `kaji/sdk/`
- Move: `packages/serve/` → `kaji/serve/`
- Move: `packages/ts/` → `kaji/ts/`

- [ ] **Step 1: Create kaji/ and move packages**

```bash
mkdir -p kaji
git mv packages/sdk kaji/sdk
git mv packages/serve kaji/serve
git mv packages/ts kaji/ts
```

- [ ] **Step 2: Verify**

```bash
ls kaji/
# Expected: sdk  serve  ts
ls packages/
# Expected: (empty or gone)
```

- [ ] **Step 3: Remove the now-empty packages/ directory**

```bash
# packages/ should be empty; if git rm leaves it, remove it
rmdir packages 2>/dev/null || true
```

- [ ] **Step 4: Commit**

```bash
git add kaji/ packages/
git commit -m "refactor: move kaji SDK packages into kaji/"
```

---

## Task 3: Update Go module names and internal imports for agentpay/api

The Go module `github.com/enkyuan/alloy/apps/api` is baked into `go.mod` and every `import` statement inside the package. Rename it to `github.com/enkyuan/alloy/agentpay/api`.

**Files:**
- Modify: `agentpay/api/go.mod` (module declaration)
- Modify: all `*.go` files under `agentpay/api/` (import paths)

- [ ] **Step 1: Update the module declaration**

Edit `agentpay/api/go.mod` line 1 from:
```
module github.com/enkyuan/alloy/apps/api
```
to:
```
module github.com/enkyuan/alloy/agentpay/api
```

- [ ] **Step 2: Update all internal import paths**

```bash
find agentpay/api -name "*.go" -exec \
  sed -i '' 's|github.com/enkyuan/alloy/apps/api|github.com/enkyuan/alloy/agentpay/api|g' {} +
```

- [ ] **Step 3: Verify no old paths remain**

```bash
grep -r "enkyuan/alloy/apps/api" agentpay/api/
# Expected: no output
```

- [ ] **Step 4: Verify the module still compiles**

```bash
cd agentpay/api && go build ./... && cd ../..
# Expected: no errors
```

- [ ] **Step 5: Commit**

```bash
git add agentpay/api/
git commit -m "refactor(api): update Go module path to agentpay/api"
```

---

## Task 4: Update Go module names and internal imports for agentpay/consumer

Same pattern as Task 3, for the consumer service.

**Files:**
- Modify: `agentpay/consumer/go.mod`
- Modify: all `*.go` files under `agentpay/consumer/`

- [ ] **Step 1: Update the module declaration**

Edit `agentpay/consumer/go.mod` line 1 from:
```
module github.com/enkyuan/alloy/apps/consumer
```
to:
```
module github.com/enkyuan/alloy/agentpay/consumer
```

- [ ] **Step 2: Update all internal import paths**

```bash
find agentpay/consumer -name "*.go" -exec \
  sed -i '' 's|github.com/enkyuan/alloy/apps/consumer|github.com/enkyuan/alloy/agentpay/consumer|g' {} +
```

- [ ] **Step 3: Verify no old paths remain**

```bash
grep -r "enkyuan/alloy/apps/consumer" agentpay/consumer/
# Expected: no output
```

- [ ] **Step 4: Verify the module still compiles**

```bash
cd agentpay/consumer && go build ./... && cd ../..
# Expected: no errors
```

- [ ] **Step 5: Commit**

```bash
git add agentpay/consumer/
git commit -m "refactor(consumer): update Go module path to agentpay/consumer"
```

---

## Task 5: Update the Poetry path dependency in kaji/serve

`kaji/serve` depends on `kaji/sdk` via a relative path dep. The relative path `../sdk` is still valid after both moved into `kaji/` together — but double-check and update if needed.

**Files:**
- Verify/modify: `kaji/serve/pyproject.toml`

- [ ] **Step 1: Check the current path dep**

```bash
grep -A2 "kaji" kaji/serve/pyproject.toml
# Should show: kaji = { path = "../sdk", develop = true }
```

- [ ] **Step 2: Confirm the relative path is still correct**

```bash
ls kaji/sdk/
# Expected: the sdk package is at kaji/sdk/ → ../sdk from kaji/serve/ is correct
```

If the grep in Step 1 shows a path other than `../sdk` (e.g., `../../packages/sdk`), update it:

```bash
sed -i '' 's|path = "../../packages/sdk"|path = "../sdk"|g' kaji/serve/pyproject.toml
```

- [ ] **Step 3: Verify Poetry can resolve the dep**

```bash
cd kaji/serve && poetry check && cd ../..
# Expected: All checks passed.
```

- [ ] **Step 4: Commit (only if a change was needed)**

```bash
git add kaji/serve/pyproject.toml
git commit -m "refactor(serve): update sdk path dep to kaji/sdk"
```

---

## Task 6: Update root package.json workspaces

The Bun workspace glob currently lists `"packages/*"` and `"apps/*"`. Update to `"agentpay/*"`, `"kaji/*"`, and `"apps/*"`.

**Files:**
- Modify: `package.json`

- [ ] **Step 1: Update the workspaces array**

Edit `package.json`. Change:
```json
"workspaces": [
  "packages/*",
  "apps/*"
]
```
to:
```json
"workspaces": [
  "agentpay/*",
  "kaji/*",
  "apps/*"
]
```

- [ ] **Step 2: Verify Bun resolves all workspaces**

```bash
bun install
# Expected: no errors; all workspace packages resolved
bun run build --dry-run 2>/dev/null || true
```

- [ ] **Step 3: Commit**

```bash
git add package.json bun.lock
git commit -m "refactor: update workspace globs for agentpay/ and kaji/ dirs"
```

---

## Task 7: Update docker/agentpay compose context paths

The compose file at `docker/agentpay/docker-compose.yml` references `../../apps/api` for the API build context. Update it to `../../agentpay/api`.

**Files:**
- Modify: `docker/agentpay/docker-compose.yml`

- [ ] **Step 1: Update the build context and env_file paths**

```bash
sed -i '' \
  's|../../apps/api|../../agentpay/api|g' \
  docker/agentpay/docker-compose.yml
```

- [ ] **Step 2: Verify the change**

```bash
grep -n "agentpay/api\|apps/api" docker/agentpay/docker-compose.yml
# Expected: only lines with ../../agentpay/api, none with ../../apps/api
```

- [ ] **Step 3: Verify the compose file is valid**

```bash
docker compose -f docker/agentpay/docker-compose.yml config --quiet
# Expected: no errors
```

- [ ] **Step 4: Commit**

```bash
git add docker/agentpay/docker-compose.yml
git commit -m "refactor(docker): update compose context paths after service moves"
```

---

## Task 8: Update GitHub Actions CI workflow

The workflow at `.github/workflows/sdk-tests.yml` has `working-directory` directives and `paths` triggers that reference `packages/` and `apps/api`. Update all of them.

**Files:**
- Modify: `.github/workflows/sdk-tests.yml`

- [ ] **Step 1: Update paths triggers**

In the `on.push.paths` and `on.pull_request.paths` sections, change:
```yaml
- "packages/sdk/**"
- "packages/serve/**"
- "packages/ts/**"
- "apps/api/**"
```
to:
```yaml
- "kaji/sdk/**"
- "kaji/serve/**"
- "kaji/ts/**"
- "agentpay/api/**"
```

- [ ] **Step 2: Update working-directory for sdk job**

Change:
```yaml
working-directory: packages/sdk
```
to:
```yaml
working-directory: kaji/sdk
```

And update the Poetry cache key hash path:
```yaml
key: poetry-sdk-${{ runner.os }}-py3.11-${{ hashFiles('packages/sdk/poetry.lock') }}
```
to:
```yaml
key: poetry-sdk-${{ runner.os }}-py3.11-${{ hashFiles('kaji/sdk/poetry.lock') }}
```

- [ ] **Step 3: Update working-directory for serve job**

Change:
```yaml
working-directory: packages/serve
```
to:
```yaml
working-directory: kaji/serve
```

And update the cache key:
```yaml
key: poetry-serve-${{ runner.os }}-py3.11-${{ hashFiles('packages/serve/poetry.lock') }}
```
to:
```yaml
key: poetry-serve-${{ runner.os }}-py3.11-${{ hashFiles('kaji/serve/poetry.lock') }}
```

- [ ] **Step 4: Update working-directory for ts-sdk job**

Change:
```yaml
working-directory: packages/ts
```
to:
```yaml
working-directory: kaji/ts
```

- [ ] **Step 5: Update working-directory and go-version-file for api job**

Change:
```yaml
working-directory: apps/api
```
to:
```yaml
working-directory: agentpay/api
```

And update the go-version-file:
```yaml
go-version-file: apps/api/go.mod
```
to:
```yaml
go-version-file: agentpay/api/go.mod
```

- [ ] **Step 6: Verify no old paths remain in the workflow**

```bash
grep -n "packages/\|apps/api" .github/workflows/sdk-tests.yml
# Expected: no output
```

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/sdk-tests.yml
git commit -m "ci: update workflow paths and working-dirs after monorepo restructure"
```

---

## Task 9: Smoke-test the full restructure

Verify that all moved pieces still build and resolve correctly.

- [ ] **Step 1: Verify Go services build**

```bash
cd agentpay/api && go vet ./... && cd ../..
cd agentpay/consumer && go vet ./... && cd ../..
# Expected: no errors from either
```

- [ ] **Step 2: Verify Python SDK tests still run**

```bash
cd kaji/sdk && poetry install --no-interaction --sync && poetry run pytest tests/ -q && cd ../..
# Expected: tests pass (same count as before)
```

- [ ] **Step 3: Verify kaji/serve resolves its SDK path dep**

```bash
cd kaji/serve && poetry install --no-interaction --sync && cd ../..
# Expected: no resolution errors
```

- [ ] **Step 4: Verify TypeScript SDK builds**

```bash
cd kaji/ts && bun install && bun run typecheck && bun run build && cd ../..
# Expected: no errors
```

- [ ] **Step 5: Verify no stray references to old paths**

```bash
grep -r "apps/api\|apps/consumer\|apps/auth\|packages/sdk\|packages/serve\|packages/ts" \
  --include="*.go" --include="*.yml" --include="*.yaml" \
  --include="*.json" --include="*.toml" \
  --exclude-dir=".git" --exclude-dir="node_modules" \
  .
# Expected: no output (or only lines inside docs/ that are historical references)
```

- [ ] **Step 6: Final commit**

```bash
git add -A
git status
# Review — should be clean or only docs/
git commit -m "chore: monorepo restructure complete — agentpay/ kaji/ apps/" \
  --allow-empty-message 2>/dev/null || \
git commit -m "chore: monorepo restructure complete — agentpay/ kaji/ apps/"
```
