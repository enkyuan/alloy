# Poetry → uv + hatchling Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Poetry with uv (package manager + lockfile + workflow) and hatchling (build backend) across `kaji/sdk`, `kaji/serve`, CI, Dockerfile, and contributor docs, so the `src/` layout works editable, builds reproduce via lockfile, and dependency resolution is 10–50× faster.

**Architecture:** Single PR. Both packages migrate together because `kaji/serve` has a path-dep on `kaji/sdk` and they share CI workflows. Hatchling's `sources` directive remaps `src/` → `kaji` (and `src/` → `kaji_serve`) at build time; hatchling implements PEP 660 editable installs that honor the remap, which `poetry-core` does not. uv reads PEP 621 `[project]` tables, manages a frozen `uv.lock` per package, and supports path+editable dependencies via `[tool.uv.sources]`.

**Tech Stack:** uv ≥ 0.5, hatchling, Python 3.11+, GitHub Actions (`astral-sh/setup-uv@v3`), Docker multi-stage build (`ghcr.io/astral-sh/uv:python3.11-bookworm-slim` builder + `python:3.11-slim` runtime).

## Global Constraints

- Python: `requires-python = ">=3.11,<4"` in both packages.
- Both packages keep their existing PyPI names: `kaji` and `kaji-serve`.
- Source layout: `kaji/sdk/src/...` (package = `kaji`), `kaji/serve/src/...` (package = `kaji_serve`).
- Lockfiles: `kaji/sdk/uv.lock` and `kaji/serve/uv.lock`. Both committed.
- Dev dependencies under PEP 735 `[dependency-groups] dev`, not `[tool.uv.dev-dependencies]`.
- Path dep shape: extras on `[project] dependencies`, source = `{ path = "../sdk", editable = true }` only (no `extras = [...]` on the source — that's the unsupported Shape B).
- Build backend: `hatchling` for both packages. `poetry-core` removed entirely.
- Registry data files (`*.json`, `*.py`, `*.md`, `*.ts` under `kaji/sdk/src/integrations/registry/`) MUST ship in the wheel via `[tool.hatch.build.targets.wheel.force-include]`. The `.ts` files are runtime-loaded by `install_integration()` — missing them is a silent production break.
- No emojis in code, comments, or docs unless they're already present.
- Branch: work continues on `feat/public-surface`.

The conversation that produced this plan (build-backend trade-offs, why poetry-core's editable install doesn't honor `to=` remaps, decision to commit to uv + hatchling) is the spec. The `/plan-eng-review` output in that conversation is the design review — do not re-litigate the decisions captured below.

---

## Map of Changes

```
Repo                            What happens
.
├── kaji/
│   ├── sdk/
│   │   ├── kaji/               → renamed to src/  (T3)
│   │   ├── src/                  NEW (after T3, before T4)
│   │   │   └── __init__.py       was kaji/__init__.py
│   │   ├── pyproject.toml      → rewritten: [project] + hatchling + uv (T4)
│   │   ├── pytest.ini          → DELETED, folded into pyproject (T4)
│   │   ├── poetry.lock         → DELETED (T4)
│   │   ├── uv.lock             → NEW (T4)
│   │   ├── README.md           → Development section updated to uv (T8)
│   │   ├── dist/               → wiped before first uv build (T1)
│   │   └── .venv/              → wiped before first uv sync (T1)
│   └── serve/
│       ├── kaji_serve/         → renamed to src/  (T3)
│       ├── src/                  NEW (after T3, before T5)
│       │   └── __init__.py       was kaji_serve/__init__.py
│       ├── pyproject.toml      → rewritten: [project] + hatchling + uv (T5)
│       │                         (currently DELETED in worktree — T1 restores)
│       └── uv.lock             → NEW (T5)
├── .github/
│   ├── actions/
│   │   ├── setup-python-poetry/  → DELETED (T6)
│   │   └── setup-python-uv/      → NEW (T6)
│   │       └── action.yml
│   └── workflows/
│       ├── python.test.yml     → rewritten to use uv (T6)
│       ├── python.lint.yml     → rewritten to use uv (T6)
│       └── python.format.yml   → rewritten to use uv (T6)
└── Dockerfile                  → multi-stage uv build (T7)
```

## Current Torn State (resolved by T1)

```
git index:        kaji/sdk/src.tmp/kaji/...           (RD: staged renames)
                  kaji/serve/src.tmp/kaji_serve/...   (RD: staged renames)
                  kaji/sdk/pyproject.toml             (M)
                  kaji/sdk/poetry.lock                (M)
worktree:         kaji/sdk/src/...                    (untracked)
                  kaji/serve/src/...                  (untracked)
                  kaji/serve/pyproject.toml           (deleted)
HEAD (truth):     kaji/sdk/kaji/...                   (the package, intact)
                  kaji/serve/kaji_serve/...           (the package, intact)
                  kaji/sdk/pyproject.toml             (Poetry config)
                  kaji/serve/pyproject.toml           (Poetry config)
                  kaji/sdk/poetry.lock                (Poetry lockfile)
```

T1 restores everything to HEAD. T3 then performs the rename cleanly in one shot.

---

## Task 1: Recover the working tree to session-start state

**Files:**
- Modify: `kaji/sdk/` (working tree + index reset)
- Modify: `kaji/serve/` (working tree + index reset)
- Delete: `kaji/sdk/src/` (untracked dir)
- Delete: `kaji/serve/src/` (untracked dir)
- Delete: `kaji/sdk/src.tmp/` (if present)
- Delete: `kaji/serve/src.tmp/` (if present)

**Interfaces:**
- Consumes: nothing (entry task)
- Produces: a clean working tree where `git status` shows only `M ryo/README.md` (pre-existing, unrelated)

- [ ] **Step 1: Verify the torn state before touching anything**

```bash
git status --short kaji/sdk kaji/serve | head -20
ls kaji/sdk/src 2>/dev/null | head -5
ls kaji/serve/src 2>/dev/null | head -5
ls kaji/serve/pyproject.toml 2>&1
```

Expected: see `RD` entries pointing at `src.tmp/`, untracked `src/` listings showing `__init__.py cli core ...` and `__init__.py modalities runtime server workers`, and `ls: kaji/serve/pyproject.toml: No such file or directory`.

If you don't see this state, STOP. The plan assumes the specific torn state in "Current Torn State" above. Re-read git status and decide if the plan still applies.

- [ ] **Step 2: Reset the index for both package dirs**

```bash
git reset HEAD kaji/sdk kaji/serve
```

Expected: no error. The 40+ `RD` entries disappear from `git status`. Untracked `src/` dirs remain. `kaji/serve/pyproject.toml` is still shown as deleted (it's tracked, was deleted in worktree).

- [ ] **Step 3: Restore tracked files in worktree from HEAD**

```bash
git checkout -- kaji/sdk kaji/serve
```

Expected: `kaji/serve/pyproject.toml` reappears. `kaji/sdk/pyproject.toml` and `kaji/sdk/poetry.lock` revert to HEAD content. `kaji/sdk/kaji/` and `kaji/serve/kaji_serve/` are intact. Untracked `src/` dirs in both packages are still present (checkout does not touch untracked).

- [ ] **Step 4: Confirm untracked `src/` dirs contain only Python source we've already moved**

```bash
diff -r kaji/sdk/kaji kaji/sdk/src 2>&1 | head -20
diff -r kaji/serve/kaji_serve kaji/serve/src 2>&1 | head -20
```

Expected: empty output (or only `__pycache__` differences). If you see unexpected files in `src/` that aren't in HEAD's package dir, STOP and investigate before deleting.

- [ ] **Step 5: Remove the untracked stale dirs**

```bash
rm -rf kaji/sdk/src kaji/serve/src
rm -rf kaji/sdk/src.tmp kaji/serve/src.tmp  # no-op if already absent
```

- [ ] **Step 6: Wipe stale Poetry-era artifacts**

```bash
rm -rf kaji/sdk/.venv
rm -rf kaji/sdk/dist
find kaji/sdk kaji/serve -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
find kaji/sdk kaji/serve -name '.ruff_cache' -type d -exec rm -rf {} + 2>/dev/null || true
```

- [ ] **Step 7: Verify clean state**

```bash
git status --short
ls kaji/sdk/kaji/__init__.py kaji/serve/kaji_serve/__init__.py kaji/sdk/pyproject.toml kaji/serve/pyproject.toml
```

Expected: `git status --short` shows only ` M ryo/README.md` (pre-existing, unrelated to this plan). All four `ls` paths print without error.

- [ ] **Step 8: Commit nothing yet**

This task changes only state that should not exist (the half-done rename). There is no positive change to commit; the next task starts the actual migration.

---

## Task 2: Install uv and verify corp-network reachability

**Files:**
- None (toolchain setup)

**Interfaces:**
- Consumes: clean working tree from T1
- Produces: a working `uv` binary on PATH; verified ability to reach pypi.org through whatever cert / proxy environment exists

This task exists because Poetry hit `SSLError(CERTIFICATE_VERIFY_FAILED)` against pypi on the dev machine (corporate MITM proxy). uv uses rustls and may or may not honor the same CA store. We verify before sinking time into a migration that can't lock.

- [ ] **Step 1: Check if uv is already installed**

```bash
command -v uv && uv --version
```

If a version prints (≥ 0.5 expected), skip to Step 3.

- [ ] **Step 2: Install uv via Astral's installer**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
exec "$SHELL" -l  # reload PATH
command -v uv && uv --version
```

Expected: prints something like `uv 0.5.x` or newer.

- [ ] **Step 3: Smoke-test uv against pypi**

```bash
mkdir -p /tmp/uv-network-check && cd /tmp/uv-network-check
cat > pyproject.toml <<'EOF'
[project]
name = "uv-network-check"
version = "0.0.0"
requires-python = ">=3.11"
dependencies = ["requests"]
EOF
uv lock 2>&1 | tail -20
cd -
```

Expected: uv resolves and writes `uv.lock`. No SSL errors. If you see `SSLError`, `CERTIFICATE_VERIFY_FAILED`, or `unable to get local issuer certificate`, STOP. Set `SSL_CERT_FILE` to the corp CA bundle (commonly `/etc/ssl/cert.pem` on macOS, `/etc/ssl/certs/ca-certificates.crt` on Debian, or the file your IT department provides) and retry. If the failure persists, the migration is blocked until cert is resolved; do not continue.

- [ ] **Step 4: Clean up the smoke check**

```bash
rm -rf /tmp/uv-network-check
```

- [ ] **Step 5: Commit nothing**

This task changes only the dev machine's toolchain; nothing in the repo changes.

---

## Task 3: Rename packages to `src/` layout

**Files:**
- Move: `kaji/sdk/kaji/` → `kaji/sdk/src/`
- Move: `kaji/serve/kaji_serve/` → `kaji/serve/src/`

**Interfaces:**
- Consumes: clean working tree from T1, uv from T2
- Produces: `kaji/sdk/src/__init__.py` and `kaji/serve/src/__init__.py` exist; the old `kaji/` and `kaji_serve/` directories no longer exist

This step is intentionally separate from T4/T5 (pyproject rewrite) so the rename shows up as a clean `git mv` in history. Tests will be broken between T3 and T4 — that is expected and is the reason no commit happens until T4 completes the matched pyproject change.

- [ ] **Step 1: Rename the SDK package directory**

```bash
git mv kaji/sdk/kaji kaji/sdk/src
```

Expected: no error. `git status` shows ~80 `R` (rename) entries under `kaji/sdk/`.

- [ ] **Step 2: Rename the serve package directory**

```bash
git mv kaji/serve/kaji_serve kaji/serve/src
```

Expected: no error. `git status` shows additional `R` entries under `kaji/serve/`.

- [ ] **Step 3: Verify the moves**

```bash
ls kaji/sdk/src/__init__.py kaji/serve/src/__init__.py
test ! -d kaji/sdk/kaji && echo "old sdk dir gone"
test ! -d kaji/serve/kaji_serve && echo "old serve dir gone"
```

Expected: both `__init__.py` paths exist, both `gone` lines print.

- [ ] **Step 4: Do not commit yet**

The package dirs were renamed but `pyproject.toml` still has Poetry's `packages = [{ include = "kaji" }]`. Committing now would leave the repo in a broken state. T4 fixes this in the same commit.

---

## Task 4: Rewrite `kaji/sdk/pyproject.toml` to PEP 621 + hatchling + uv

**Files:**
- Modify: `kaji/sdk/pyproject.toml` (full rewrite)
- Delete: `kaji/sdk/pytest.ini` (folded into pyproject)
- Delete: `kaji/sdk/poetry.lock`
- Create: `kaji/sdk/uv.lock` (generated by `uv lock`)

**Interfaces:**
- Consumes: renamed `src/` layout from T3
- Produces:
  - `[project]` table with `name = "kaji"`, `requires-python = ">=3.11,<4"`, runtime deps, scripts, optional-dependencies (extras)
  - `[build-system]` using `hatchling`
  - `[tool.hatch.build.targets.wheel.sources]` mapping `src` → `kaji`
  - `[tool.hatch.build.targets.wheel.force-include]` shipping the registry data files
  - `[dependency-groups]` table with a `dev` group (PEP 735)
  - `[tool.pytest.ini_options]`, `[tool.coverage.*]`, `[tool.pyrefly]` preserved
  - A wheel that contains `kaji/integrations/registry/**/*.ts` (verified in Step 8 — this is the silent-failure gate)

- [ ] **Step 1: Write the failing verification test**

There is no new code to TDD here; instead, the verification test is a shell command that proves the wheel is correct. Capture it in a script so future runs can reuse it. Create `kaji/sdk/scripts/verify_wheel_contents.sh`:

```bash
mkdir -p kaji/sdk/scripts
cat > kaji/sdk/scripts/verify_wheel_contents.sh <<'EOF'
#!/usr/bin/env bash
# Verifies the built wheel ships everything the SDK needs at runtime.
# Run after `uv build --wheel`. Exits non-zero on any missing artifact.
set -euo pipefail

WHEEL=$(ls -t dist/*.whl 2>/dev/null | head -1)
if [ -z "$WHEEL" ]; then
  echo "FAIL: no wheel under dist/. Run 'uv build --wheel' first." >&2
  exit 1
fi

echo "Inspecting $WHEEL"

# Top-level package present, remap worked.
unzip -l "$WHEEL" | grep -q 'kaji/__init__.py' \
  || { echo "FAIL: kaji/__init__.py missing from wheel (sources remap broken)"; exit 1; }

# py.typed shipped.
unzip -l "$WHEEL" | grep -q 'kaji/py.typed' \
  || { echo "FAIL: kaji/py.typed missing from wheel"; exit 1; }

# Registry data files of every format.
for ext in json py md ts; do
  COUNT=$(unzip -l "$WHEEL" | grep -cE "kaji/integrations/registry/.*\.${ext}\$" || true)
  if [ "$COUNT" -eq 0 ]; then
    echo "FAIL: no .${ext} files under kaji/integrations/registry/ in wheel" >&2
    echo "      hatchling force-include is misconfigured. install_integration() will break for end users." >&2
    exit 1
  fi
  echo "  ok: $COUNT .${ext} files"
done

echo "PASS: wheel contents verified"
EOF
chmod +x kaji/sdk/scripts/verify_wheel_contents.sh
```

- [ ] **Step 2: Run the verification (expect fail — no wheel yet)**

```bash
cd kaji/sdk && ./scripts/verify_wheel_contents.sh 2>&1; cd -
```

Expected: `FAIL: no wheel under dist/. Run 'uv build --wheel' first.` This proves the test is wired to fail when its precondition isn't met.

- [ ] **Step 3: Write the new `kaji/sdk/pyproject.toml`**

Replace `kaji/sdk/pyproject.toml` entirely with:

```toml
[project]
name = "kaji"
version = "0.1.0"
description = "An embeddable SDK for building agentic platforms (text + voice)."
readme = "README.md"
requires-python = ">=3.11,<4"
authors = [
    { name = "enkyuan", email = "yuan.enkng@gmail.com" },
]
dependencies = [
    "pydantic[email]>=2.12.0,<3",
    "pydantic-settings>=2.11.0,<3",
    "httpx>=0.27.0,<0.28",
    "msgpack>=1.1.2,<2",
]

[project.optional-dependencies]
anthropic = ["anthropic>=0.40.0,<1"]
dev-ui = ["rich>=13.0.0,<14"]
gemini = ["google-genai>=1.0.0,<2"]
google-tools = [
    "google-api-python-client>=2.108.0,<3",
    "google-auth>=2.25.0,<3",
    "google-auth-oauthlib>=1.2.0,<2",
    "google-auth-httplib2>=0.2.0,<1",
]
oauth-keyring = ["keyring>=24.0.0,<26"]
openai = ["openai>=2.0.0,<3"]
providers = ["anthropic>=0.40.0,<1", "google-genai>=1.0.0,<2", "openai>=2.0.0,<3"]
realtime = ["redis[asyncio]>=6.4.0,<7"]

[project.scripts]
kaji = "kaji.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src"]

[tool.hatch.build.targets.wheel.sources]
"src" = "kaji"

# The integrations registry holds dual-language manifest assets that
# install_integration() loads at runtime. Hatchling's default file selection
# is Python-only; force-include copies the entire registry tree (json/py/md/ts)
# into the wheel under kaji/integrations/registry/. Missing .ts files would
# silently break install_integration("echo", ...) on installed wheels.
[tool.hatch.build.targets.wheel.force-include]
"src/integrations/registry" = "kaji/integrations/registry"
"src/py.typed" = "kaji/py.typed"

[tool.hatch.build.targets.sdist]
include = [
    "src/",
    "tests/",
    "README.md",
    "CHANGELOG.md",
    "pyproject.toml",
    "scripts/",
]

[dependency-groups]
dev = [
    "pyrefly>=0.45.1,<0.46",
    "ruff>=0.11.0,<0.12",
    "pytest>=9.0.2,<10",
    "pytest-asyncio>=1.3.0,<2",
    "pytest-cov>=7.0.0,<8",
    "fakeredis>=2.33.0,<3",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
addopts = [
    "--cov=kaji",
    "--cov-report=term-missing",
]
filterwarnings = [
    "ignore::DeprecationWarning",
]
markers = [
    "integration: tests that call real LLM APIs (skipped if API keys absent)",
]

[tool.pyrefly]
project-includes = [
    "**/*.py*",
    "**/*.ipynb",
]

[tool.coverage.run]
source = ["kaji"]
branch = true
omit = ["*/__init__.py", "*/tests/*"]

[tool.coverage.report]
show_missing = true
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
    "\\.\\.\\.",
    "if __name__ == .__main__.:",
]
```

- [ ] **Step 4: Delete files now superseded**

```bash
rm kaji/sdk/pytest.ini
rm kaji/sdk/poetry.lock
```

- [ ] **Step 5: Generate the uv lockfile**

```bash
cd kaji/sdk
uv lock
cd -
```

Expected: writes `kaji/sdk/uv.lock`. No errors. If you see an SSL error here, T2 didn't fully resolve cert issues — go back and fix.

- [ ] **Step 6: Sync the venv and verify `import kaji` works editable**

```bash
cd kaji/sdk
uv sync
uv run python -c "import kaji; print('kaji from:', kaji.__file__)"
uv run python -c "from kaji import AgentBuilder, AgentRuntime, get_provider; print('exports OK')"
uv run python -c "from kaji.cli import main; print('cli OK')"
cd -
```

Expected:
- `kaji from: /Users/.../kaji/sdk/src/__init__.py` (or hatchling's editable shim; the path points into `src/`, not a copy)
- `exports OK`
- `cli OK`

If any import fails, hatchling's editable PEP 660 hook didn't install correctly — re-check `[tool.hatch.build.targets.wheel.sources]` syntax.

- [ ] **Step 7: Build the wheel**

```bash
cd kaji/sdk
uv build --wheel
cd -
ls kaji/sdk/dist/
```

Expected: `kaji-0.1.0-py3-none-any.whl` (or similar) in `kaji/sdk/dist/`.

- [ ] **Step 8: Run the wheel verification (mandatory gate)**

```bash
cd kaji/sdk && ./scripts/verify_wheel_contents.sh; cd -
```

Expected output:
```
Inspecting dist/kaji-0.1.0-py3-none-any.whl
  ok: N .json files
  ok: N .py files
  ok: N .md files
  ok: N .ts files
PASS: wheel contents verified
```

If any line shows FAIL, the build is broken. Do not proceed. Most likely cause is a typo in `force-include` mapping — re-read Step 3's pyproject and confirm `"src/integrations/registry" = "kaji/integrations/registry"` is verbatim.

- [ ] **Step 9: Run the SDK test suite**

```bash
cd kaji/sdk
uv run pytest tests/test_quickstart.py -q
uv run pytest tests/ -m "not integration"
cd -
```

Expected: quickstart smoke passes, non-integration suite passes (or shows the same pass/fail count as before this migration — there should be no migration-induced regressions). If a test that previously passed now fails, investigate before continuing.

- [ ] **Step 10: Run the install-smoke (proves the wheel works in a clean venv)**

```bash
python3.11 -m venv /tmp/kaji-install-smoke
/tmp/kaji-install-smoke/bin/pip install --quiet kaji/sdk/dist/*.whl
/tmp/kaji-install-smoke/bin/python kaji/sdk/scripts/smoke_install.py
rm -rf /tmp/kaji-install-smoke
```

Expected: smoke script prints `ok: kaji.<name>` for every required export, then completes without error.

- [ ] **Step 11: Commit (combined rename + sdk migration)**

```bash
git add kaji/sdk/ \
        -- ':!kaji/sdk/dist' ':!kaji/sdk/.venv' ':!kaji/sdk/coverage.xml'
git status --short
git commit -m "$(cat <<'EOF'
refactor(sdk): migrate kaji to uv + hatchling, adopt src/ layout

Replace poetry-core build backend with hatchling so PEP 660 editable
installs honor the sources remap (src/ -> kaji). Move dependency
management to uv with PEP 621 [project] and PEP 735 [dependency-groups].

Fold pytest.ini into [tool.pytest.ini_options]. Force-include the
integrations registry data files (json/py/md/ts) so install_integration()
keeps working in installed wheels.
EOF
)"
```

Expected: commit succeeds. `git status` shows only `kaji/serve/`, CI, Dockerfile, README still pending (they're untouched by this task) and the unrelated `ryo/README.md`.

---

## Task 5: Rewrite `kaji/serve/pyproject.toml` to PEP 621 + hatchling + uv

**Files:**
- Modify: `kaji/serve/pyproject.toml` (full rewrite from HEAD content)
- Create: `kaji/serve/uv.lock`

**Interfaces:**
- Consumes:
  - Renamed `src/` layout from T3
  - The migrated `kaji/sdk/` package (T4) — `kaji-serve` path-depends on it
- Produces:
  - `[project]` for `kaji-serve` with the path-dep on `kaji` expressed via uv Shape A
  - Hatchling build with `src` → `kaji_serve` remap
  - `uv.lock` that resolves `kaji` editably from `../sdk`

- [ ] **Step 1: Write `kaji/serve/pyproject.toml`**

Replace the file entirely (it was deleted in worktree and reappeared from HEAD in T1, so this is a rewrite of the HEAD content):

```toml
[project]
name = "kaji-serve"
version = "0.1.0"
description = "FastAPI + workers reference service for the Kaji SDK."
readme = "README.md"
requires-python = ">=3.11,<4"
authors = [
    { name = "enkyuan", email = "yuan.enkng@gmail.com" },
]
dependencies = [
    # Shape A: extras live on the project dep; uv.sources is path-only.
    "kaji[realtime,providers]",
    "fastapi>=0.119.0,<0.120",
    "uvicorn>=0.37.0,<0.38",
    "websockets>=13.0,<16",
    "sqlalchemy>=2.0.44,<3",
    "alembic>=1.17.0,<2",
    "psycopg2-binary>=2.9.11,<3",
    "python-jose>=3.5.0,<4",
    "passlib>=1.7.4,<2",
    "asyncpg>=0.30.0,<0.31",
    "python-multipart>=0.0.9,<0.1",
    "taskiq>=0.11.20,<0.12",
    "taskiq-redis>=1.1.2,<2",
]

[tool.uv.sources]
kaji = { path = "../sdk", editable = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src"]

[tool.hatch.build.targets.wheel.sources]
"src" = "kaji_serve"

[tool.hatch.build.targets.sdist]
include = [
    "src/",
    "tests/",
    "alembic/",
    "alembic.ini",
    "README.md",
    "pyproject.toml",
]

[dependency-groups]
dev = [
    "ruff>=0.11.0,<0.12",
    "pytest>=9.0.2,<10",
    "pytest-asyncio>=1.3.0,<2",
    "pytest-cov>=7.0.0,<8",
    "fakeredis>=2.33.0,<3",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
filterwarnings = [
    "ignore::DeprecationWarning",
]

[tool.coverage.run]
source = ["kaji_serve"]
branch = true
omit = ["*/__init__.py", "*/tests/*"]

[tool.coverage.report]
show_missing = true
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
    "\\.\\.\\.",
    "if __name__ == .__main__.:",
]
```

- [ ] **Step 2: Generate the serve lockfile**

```bash
cd kaji/serve
uv lock
cd -
```

Expected: writes `kaji/serve/uv.lock`. Resolves `kaji` from `../sdk` editably with extras `realtime` and `providers` activated.

If `uv lock` fails complaining about Shape A vs Shape B, double-check: the `"kaji[realtime,providers]"` string lives in `[project] dependencies`, the source `{ path = "../sdk", editable = true }` has NO `extras = [...]` key, and `[tool.uv.sources].kaji` matches the bare name `kaji` in `[project] dependencies`.

- [ ] **Step 3: Sync the serve venv**

```bash
cd kaji/serve
uv sync
cd -
```

Expected: pulls SDK editably plus its `realtime` (redis) and `providers` (anthropic, openai, google-genai) extras, plus serve's own deps.

- [ ] **Step 4: Verify imports resolve, including transitive extras**

```bash
cd kaji/serve
uv run python -c "import kaji_serve; print('kaji_serve from:', kaji_serve.__file__)"
uv run python -c "import kaji"
uv run python -c "from redis import asyncio; from openai import OpenAI; import anthropic; print('extras OK')"
uv run python -c "from kaji_serve.server.app import app; print('app OK')"
cd -
```

Expected: all four lines print success. `extras OK` proves the path-dep + extras shape correctly activates `realtime` and `providers`. `app OK` proves the FastAPI app object still constructs.

- [ ] **Step 5: Run the serve test suite**

```bash
cd kaji/serve
uv run pytest tests/ -q
cd -
```

Expected: same pass/fail count as before the migration. If tests that need Postgres fail because the DB isn't running, that's expected locally; CI will run them.

- [ ] **Step 6: Commit**

```bash
git add kaji/serve/
git commit -m "$(cat <<'EOF'
refactor(serve): migrate kaji-serve to uv + hatchling, adopt src/ layout

Mirror the sdk migration: PEP 621 [project], hatchling build backend
with src/ -> kaji_serve sources remap, [dependency-groups] dev, and
uv-managed lockfile.

Express the sdk path-dep via uv Shape A: extras on the project dep
(kaji[realtime,providers]), source under [tool.uv.sources] is path
and editable only.
EOF
)"
```

---

## Task 6: Replace CI to use uv

**Files:**
- Delete: `.github/actions/setup-python-poetry/` (entire dir)
- Create: `.github/actions/setup-python-uv/action.yml`
- Modify: `.github/workflows/python.test.yml`
- Modify: `.github/workflows/python.lint.yml`
- Modify: `.github/workflows/python.format.yml`

**Interfaces:**
- Consumes: uv-managed packages from T4 + T5
- Produces:
  - New composite action `setup-python-uv` that installs uv, restores its cache, and runs `uv sync`
  - Three workflows that use `uv run` instead of `poetry run` and `uv build --wheel` instead of `poetry build --format wheel`
  - All workflow `paths:` filters updated to point at the new action

The current CI has three workflows. Each one uses the `setup-python-poetry` composite action, which we replace wholesale.

- [ ] **Step 1: Write the new composite action**

```bash
mkdir -p .github/actions/setup-python-uv
```

Create `.github/actions/setup-python-uv/action.yml`:

```yaml
name: Setup Python uv
description: Set up Python, install uv, cache the uv store, and run uv sync.

inputs:
  working-directory:
    description: Directory containing pyproject.toml and uv.lock.
    required: true
  python-version:
    description: Python version to install.
    required: false
    default: "3.11"
  sync-args:
    description: Arguments passed to `uv sync` (e.g. `--extra openai`).
    required: false
    default: "--frozen"

runs:
  using: composite
  steps:
    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: ${{ inputs.python-version }}

    - name: Install uv
      uses: astral-sh/setup-uv@v3
      with:
        enable-cache: true
        cache-dependency-glob: ${{ format('{0}/uv.lock', inputs.working-directory) }}

    - name: Sync dependencies
      shell: bash
      working-directory: ${{ inputs.working-directory }}
      run: uv sync ${{ inputs.sync-args }}
```

- [ ] **Step 2: Delete the old composite action**

```bash
git rm -r .github/actions/setup-python-poetry
```

- [ ] **Step 3: Rewrite `.github/workflows/python.test.yml`**

Replace the file contents with:

```yaml
name: test / python

on:
  push:
    branches: [main]
    paths:
      - "kaji/sdk/**"
      - "kaji/serve/**"
      - ".github/actions/setup-python-uv/**"
      - ".github/workflows/python.test.yml"
  pull_request:
    paths:
      - "kaji/sdk/**"
      - "kaji/serve/**"
      - ".github/actions/setup-python-uv/**"
      - ".github/workflows/python.test.yml"

jobs:
  sdk:
    name: kaji/sdk
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: kaji/sdk
    steps:
      - uses: actions/checkout@v4

      - uses: ./.github/actions/setup-python-uv
        with:
          working-directory: kaji/sdk

      - name: Run quickstart smoke
        run: uv run pytest tests/test_quickstart.py -q

      - name: Run non-network tests
        run: uv run pytest tests/ -m "not integration" --cov=kaji --cov-report=xml --cov-fail-under=35

      - name: Upload coverage
        uses: actions/upload-artifact@v4
        with:
          name: coverage-sdk
          path: kaji/sdk/coverage.xml
          retention-days: 7

  sdk-install-smoke:
    name: kaji/sdk install smoke
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: kaji/sdk
    steps:
      - uses: actions/checkout@v4

      - uses: ./.github/actions/setup-python-uv
        with:
          working-directory: kaji/sdk

      - name: Build wheel
        run: uv build --wheel

      - name: Verify wheel contents
        run: ./scripts/verify_wheel_contents.sh

      - name: Install wheel in clean venv
        run: |
          python -m venv /tmp/kaji-smoke-venv
          /tmp/kaji-smoke-venv/bin/pip install --quiet dist/*.whl
          /tmp/kaji-smoke-venv/bin/python scripts/smoke_install.py

  serve:
    name: kaji/serve
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: postgres
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U postgres -d postgres"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
    env:
      POSTGRES_HOST: localhost
      POSTGRES_PORT: 5432
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: postgres
    defaults:
      run:
        working-directory: kaji/serve
    steps:
      - uses: actions/checkout@v4

      - uses: ./.github/actions/setup-python-uv
        with:
          working-directory: kaji/serve

      - name: Run tests
        run: uv run pytest tests/ --cov=kaji_serve --cov-report=xml --cov-fail-under=35

      - name: Upload coverage
        uses: actions/upload-artifact@v4
        with:
          name: coverage-serve
          path: kaji/serve/coverage.xml
          retention-days: 7

  live-openai:
    name: live provider / openai
    runs-on: ubuntu-latest
    env:
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
    defaults:
      run:
        working-directory: kaji/sdk
    steps:
      - uses: actions/checkout@v4

      - uses: ./.github/actions/setup-python-uv
        with:
          working-directory: kaji/sdk
          sync-args: "--frozen --extra openai"

      - name: Run OpenAI integration smoke
        run: uv run pytest -m integration tests/integration/test_openai_provider.py

  live-anthropic:
    name: live provider / anthropic
    runs-on: ubuntu-latest
    env:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
    defaults:
      run:
        working-directory: kaji/sdk
    steps:
      - uses: actions/checkout@v4

      - uses: ./.github/actions/setup-python-uv
        with:
          working-directory: kaji/sdk
          sync-args: "--frozen --extra anthropic"

      - name: Run Anthropic integration smoke
        run: uv run pytest -m integration tests/integration/test_anthropic_provider.py
```

- [ ] **Step 4: Rewrite `.github/workflows/python.lint.yml`**

Replace the file contents with:

```yaml
name: lint / python

on:
  push:
    branches: [main]
    paths:
      - "kaji/sdk/**"
      - "kaji/serve/**"
      - ".github/actions/setup-python-uv/**"
      - ".github/workflows/python.lint.yml"
  pull_request:
    paths:
      - "kaji/sdk/**"
      - "kaji/serve/**"
      - ".github/actions/setup-python-uv/**"
      - ".github/workflows/python.lint.yml"

jobs:
  sdk:
    name: kaji/sdk
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: kaji/sdk
    steps:
      - uses: actions/checkout@v4

      - uses: ./.github/actions/setup-python-uv
        with:
          working-directory: kaji/sdk

      - name: Type check
        run: uv run pyrefly check

      - name: Lint
        run: uv run ruff check src tests

  serve:
    name: kaji/serve
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: kaji/serve
    steps:
      - uses: actions/checkout@v4

      - uses: ./.github/actions/setup-python-uv
        with:
          working-directory: kaji/serve

      - name: Lint
        run: uv run ruff check src tests alembic
```

Note the `ruff check` targets: `src` replaces the old `kaji` / `kaji_serve` package names because lint runs against the on-disk path. Tests/alembic stay as-is.

- [ ] **Step 5: Rewrite `.github/workflows/python.format.yml`**

Replace the file contents with:

```yaml
name: format / python

on:
  push:
    branches: [main]
    paths:
      - "kaji/sdk/**"
      - "kaji/serve/**"
      - ".github/actions/setup-python-uv/**"
      - ".github/workflows/python.format.yml"
  pull_request:
    paths:
      - "kaji/sdk/**"
      - "kaji/serve/**"
      - ".github/actions/setup-python-uv/**"
      - ".github/workflows/python.format.yml"

jobs:
  sdk:
    name: kaji/sdk
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: kaji/sdk
    steps:
      - uses: actions/checkout@v4

      - uses: ./.github/actions/setup-python-uv
        with:
          working-directory: kaji/sdk

      - name: Check formatting
        run: uv run ruff format --check .

  serve:
    name: kaji/serve
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: kaji/serve
    steps:
      - uses: actions/checkout@v4

      - uses: ./.github/actions/setup-python-uv
        with:
          working-directory: kaji/serve

      - name: Check formatting
        run: uv run ruff format --check .
```

- [ ] **Step 6: Verify nothing else references the old action**

```bash
grep -rn 'setup-python-poetry' .github/ docs/ kaji/ 2>/dev/null
```

Expected: no output. If anything matches, update it before commit.

- [ ] **Step 7: Verify the YAML parses**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/actions/setup-python-uv/action.yml'))"
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/python.test.yml'))"
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/python.lint.yml'))"
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/python.format.yml'))"
```

Expected: each command exits cleanly with no output. (If `yaml` isn't installed locally, `python3 -m venv /tmp/yamlcheck && /tmp/yamlcheck/bin/pip install pyyaml` first.)

- [ ] **Step 8: Commit**

```bash
git add .github/
git commit -m "$(cat <<'EOF'
ci: switch python workflows from poetry to uv

Replace setup-python-poetry composite action with setup-python-uv
(astral-sh/setup-uv@v3 + uv sync --frozen). Update test/lint/format
workflows to use `uv run` and `uv build --wheel`. Wire the wheel
content verification gate into the install-smoke job.

Lint targets switch from `kaji`/`kaji_serve` to `src` (on-disk path
under the new src/ layout). Live-provider jobs use
`uv sync --frozen --extra <name>` instead of poetry's `-E <name>`.
EOF
)"
```

---

## Task 7: Multi-stage Dockerfile using uv

**Files:**
- Modify: `Dockerfile`

**Interfaces:**
- Consumes: `kaji/serve/uv.lock` from T5, the new layouts from T3
- Produces: an image where `import kaji; import kaji_serve` succeeds and the existing CMD (`uvicorn kaji_serve.server.app:app ...`) starts

- [ ] **Step 1: Read the current Dockerfile to confirm what we're replacing**

```bash
cat Dockerfile
```

You should see a single-stage build using `python:3.11-slim`, installing Poetry via `pip install poetry==2.4.1`, and running `cd kaji/serve && poetry install --only main`. Everything from `# Install Poetry` through `RUN python -c "import kaji; import kaji_serve"` is what we replace.

- [ ] **Step 2: Write the new Dockerfile**

Replace the file entirely with:

```dockerfile
# syntax=docker/dockerfile:1.7

# --- Stage 1: build deps and editable install via uv ---------------------
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

ARG BUILD_COMMIT=unknown
LABEL build.commit="${BUILD_COMMIT}"

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/kaji/serve/.venv

WORKDIR /app

# System deps that some Python packages (psycopg2-binary, etc.) need to import.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the monorepo. kaji/serve has a path dep on ../sdk, so both must be present.
COPY . .

# Install. Frozen = lockfile must already exist and resolve; no remote re-resolution.
# --no-dev = skip the [dependency-groups].dev group; the image is for runtime.
RUN cd kaji/serve && uv sync --frozen --no-dev

# --- Stage 2: slim runtime ----------------------------------------------
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/kaji/serve/.venv/bin:${PATH}"

# Runtime system deps (psql client for entrypoint waits, curl for healthcheck).
RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Bring in the synced venv plus the source tree.
COPY --from=builder /app /app

# Fail at build time if either package is unimportable. Catches stale image
# layers built before the monorepo restructure.
RUN python -c "import kaji; import kaji_serve"

# Non-root user.
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["uvicorn", "kaji_serve.server.app:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 3: Build the image**

```bash
docker build -t kaji-uv-test .
```

Expected: build completes. The `RUN python -c "import kaji; import kaji_serve"` step passes (it would fail loudly otherwise).

- [ ] **Step 4: Smoke-test the image's imports outside the build**

```bash
docker run --rm kaji-uv-test python -c "import kaji; import kaji_serve; from redis import asyncio; print('runtime OK')"
```

Expected: `runtime OK`.

- [ ] **Step 5: Smoke-test the entrypoint starts**

```bash
docker run --rm -d --name kaji-uv-boot kaji-uv-test
sleep 3
docker logs kaji-uv-boot 2>&1 | head -20
docker stop kaji-uv-boot >/dev/null
```

Expected: logs show uvicorn starting up. The container won't pass its healthcheck without Postgres, but the process should at least begin to start (no `ModuleNotFoundError`, no `command not found`). If you see an immediate crash, fix before continuing.

- [ ] **Step 6: Clean up local test image**

```bash
docker rmi kaji-uv-test
```

- [ ] **Step 7: Commit**

```bash
git add Dockerfile
git commit -m "$(cat <<'EOF'
build(docker): multi-stage Dockerfile using uv

Stage 1 uses ghcr.io/astral-sh/uv:python3.11-bookworm-slim as the build
image to run `uv sync --frozen --no-dev` against the lockfile. Stage 2
is python:3.11-slim with only the synced venv and source copied in;
uv itself is not present in the runtime image.

Keeps the existing import smoke check at build time.
EOF
)"
```

---

## Task 8: Update `kaji/sdk/README.md` Development section

**Files:**
- Modify: `kaji/sdk/README.md` (lines around the Development section, currently lines 144–173)

**Interfaces:**
- Consumes: working uv setup from T4
- Produces: contributor docs that match how the toolchain actually works post-migration

- [ ] **Step 1: Read the current Development section**

```bash
sed -n '144,173p' kaji/sdk/README.md
```

Expected: prose mentioning `Poetry`, `poetry install`, `poetry run pytest`, `poetry run pyrefly check`, `poetry run ruff check kaji`, and live-provider invocations using `poetry run pytest -m integration`.

- [ ] **Step 2: Replace the Development section**

Use the Edit tool to replace this block:

```markdown
## Development

**Prerequisites:** Python 3.11+, [Poetry](https://python-poetry.org/).

```bash
cd kaji/sdk
poetry install
poetry run pytest tests/          # no API keys required
poetry run pyrefly check          # static type check
poetry run ruff check kaji        # lint
```

Live provider tests are opt-in:

```bash
OPENAI_API_KEY=... poetry run pytest -m integration tests/integration/test_openai_provider.py
ANTHROPIC_API_KEY=... poetry run pytest -m integration tests/integration/test_anthropic_provider.py
```

The SDK test suite needs no environment. The service tests under
`kaji/serve/tests/` cover the FastAPI app and workers; those need Postgres
(see [`kaji/serve/README.md`](../serve/README.md)).

## Testing without API keys

The default test path mocks provider HTTP clients and requires no keys:

```bash
poetry run pytest -m "not integration"
```
```

With:

```markdown
## Development

**Prerequisites:** Python 3.11+, [uv](https://docs.astral.sh/uv/).

```bash
cd kaji/sdk
uv sync                           # creates .venv, installs deps + dev group
uv run pytest tests/              # no API keys required
uv run pyrefly check              # static type check
uv run ruff check src             # lint
```

Live provider tests are opt-in (the extras pull in the corresponding SDK):

```bash
uv sync --extra openai
OPENAI_API_KEY=... uv run pytest -m integration tests/integration/test_openai_provider.py

uv sync --extra anthropic
ANTHROPIC_API_KEY=... uv run pytest -m integration tests/integration/test_anthropic_provider.py
```

The SDK test suite needs no environment. The service tests under
`kaji/serve/tests/` cover the FastAPI app and workers; those need Postgres
(see [`kaji/serve/README.md`](../serve/README.md)).

## Testing without API keys

The default test path mocks provider HTTP clients and requires no keys:

```bash
uv run pytest -m "not integration"
```
```

- [ ] **Step 3: Verify no `poetry` references remain in install/dev docs**

```bash
grep -n 'poetry' kaji/sdk/README.md
```

Expected: either no output, or only mentions of "Poetry" in a context that's clearly historical (e.g. a "previously used" note — not expected here, but possible). If install-related `poetry` lines remain, fix them.

- [ ] **Step 4: Commit**

```bash
git add kaji/sdk/README.md
git commit -m "docs(sdk): update Development section to uv

Replace poetry-based contributor commands with uv equivalents.
Live-provider tests now activate extras via 'uv sync --extra <name>'
instead of poetry's '-E <name>' on install."
```

---

## Final verification (run after all 8 tasks land)

These checks duplicate per-task verification but run as one block so the
reviewer can see end-to-end health without re-tracing the per-task steps.

- [ ] **A. Lockfiles present and frozen-resolvable**

```bash
ls kaji/sdk/uv.lock kaji/serve/uv.lock
cd kaji/sdk && uv sync --frozen && cd -
cd kaji/serve && uv sync --frozen && cd -
```

Expected: both lockfiles exist; both `--frozen` syncs succeed without resolving.

- [ ] **B. Imports work editable in both packages**

```bash
cd kaji/sdk && uv run python -c "import kaji; from kaji.cli import main" && cd -
cd kaji/serve && uv run python -c "import kaji; import kaji_serve; from redis import asyncio; from openai import OpenAI" && cd -
```

Expected: no output, no errors.

- [ ] **C. Wheel ships everything**

```bash
cd kaji/sdk
rm -rf dist
uv build --wheel
./scripts/verify_wheel_contents.sh
cd -
```

Expected: `PASS: wheel contents verified` with non-zero counts for json/py/md/ts.

- [ ] **D. Install-smoke passes**

```bash
python3.11 -m venv /tmp/final-smoke
/tmp/final-smoke/bin/pip install --quiet kaji/sdk/dist/*.whl
/tmp/final-smoke/bin/python kaji/sdk/scripts/smoke_install.py
rm -rf /tmp/final-smoke
```

Expected: smoke script exits cleanly.

- [ ] **E. Docker builds and runs**

```bash
docker build -t kaji-final .
docker run --rm kaji-final python -c "import kaji; import kaji_serve"
docker rmi kaji-final
```

Expected: build succeeds, imports succeed, image cleaned up.

- [ ] **F. No `poetry` references survive in load-bearing files**

```bash
grep -rln '\bpoetry\b' Dockerfile .github/ kaji/sdk/pyproject.toml kaji/serve/pyproject.toml kaji/sdk/README.md
```

Expected: no output. (CHANGELOG.md and docs/superpowers/plans/ are out of scope and may contain historical mentions.)

- [ ] **G. Working tree is clean**

```bash
git status
```

Expected: only the pre-existing `ryo/README.md` modification (or nothing). All other migration changes are committed.

---

## Rollback plan

If the migration fails verification at any task boundary, roll back to the last clean commit:

```bash
git log --oneline -10                              # find the commit before the migration started
git reset --hard <commit-before-T4>                # discard all migration commits
rm -rf kaji/sdk/.venv kaji/serve/.venv             # discard uv-created venvs
rm -f kaji/sdk/uv.lock kaji/serve/uv.lock          # discard new lockfiles
```

Per-task rollback is also possible — each task's commit is self-contained — but a multi-task rollback is cleaner than picking and choosing.

---

## Why this plan looks the way it does (cross-references to the engineering review)

- **Path A confirmed.** Full Poetry replacement, hatchling backend, src/ layout, single PR. See the `/plan-eng-review` output preceding this plan.
- **No outside voice (codex) was run** — the corporate MITM proxy almost certainly blocks codex's network calls the same way it blocks Poetry's. Skip recorded in the review.
- **The `.ts` files in `kaji/integrations/registry/`** are the single highest-risk regression: missing them produces no test failure, only a runtime error in `install_integration()` for end users. T4 Step 8 is the gate that prevents it.
- **Shape A for the path dep** (extras on `[project] dependencies`, source under `[tool.uv.sources]` is path+editable only) is the documented uv pattern; Shape B (extras on the source) has limited support and is avoided.
- **PEP 735 `[dependency-groups]`** is preferred over `[tool.uv.dev-dependencies]` for portability — pip 25+, hatch, and other tools also read it.
- **`uv build --wheel`** replaces `poetry build --format wheel`. Same poetry-core-built wheel today; hatchling-built wheel post-migration.
