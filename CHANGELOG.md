# Changelog

All notable changes to this project will be documented in this file.

## [0.0.1.0] - 2026-06-07

### Changed

- **Monorepo restructure**: all agentpay services now live under `agentpay/` (`api`, `consumer`, `auth`) and all agentkit SDK packages under `agentkit/` (`sdk`, `serve`, `ts`). The product boundary between agentpay (deployed services) and agentkit (embeddable SDK) is now structurally visible in the directory layout.
- Go module paths renamed: `github.com/enkyuan/alloy/apps/api` → `github.com/enkyuan/alloy/agentpay/api`; `github.com/enkyuan/alloy/apps/consumer` → `github.com/enkyuan/alloy/agentpay/consumer`. All internal import paths updated.
- Docker Compose build contexts and volume mounts updated to new paths (`docker/agentpay/docker-compose.yml`, `docker/agentkit/docker-compose.yml`).
- Root `Dockerfile` `pip install` path updated from `packages/serve` → `agentkit/serve`.
- Root `package.json` workspace globs updated to `agentpay/*`, `agentkit/*`, `apps/*`.
- CI workflow paths triggers and `working-directory` values updated; `agentpay/consumer/**` and `agentpay/auth/**` added to trigger paths.
- `.gitignore` corrected: secrets path fixed to `docker/agentpay/.env`; consumer binary path added at `agentpay/consumer/consumer`.

### Fixed

- Stale `packages/` and `apps/` path references removed from `AGENTS.md`, `README.md`, `docs/AGENTKIT.md`, `docs/SETUP.md`, `docs/ROADMAP.md`, `agentkit/sdk/agentkit/README.md`.
- Go migrations step added to CI `api` job to prevent false test failures on fresh checkouts.
