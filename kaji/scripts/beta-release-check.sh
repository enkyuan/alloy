#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

RELEASE=0
if [ "${1:-}" = "--release" ]; then
  RELEASE=1
  shift
fi
if [ "$#" -ne 0 ]; then
  echo "FAIL: usage: $0 [--release]" >&2
  exit 2
fi
export PATH="${HOME:-}/.local/bin:${HOME:-}/.bun/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
export UV_SYSTEM_CERTS="${UV_SYSTEM_CERTS:-true}"

section() {
  printf '\n==> %s\n' "$1"
}

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "$1 is required for $2"
}

run_in_dir() {
  local label="$1"
  local directory="$2"
  shift 2
  section "$label"
  (cd "$directory" && "$@")
}

run_no_key_live_skip() {
  section "No-key live gate skip hygiene"
  (unset OPENAI_API_KEY KAJI_LIVE_OPENAI_MODEL KAJI_REQUIRE_LIVE_KEYS; \
    bash "$ROOT/kaji/scripts/live-openai-tool-loop.sh")
}

run_required_key_failure() {
  section "Required-key live gate failure hygiene"
  local output status
  set +e
  output="$(unset OPENAI_API_KEY KAJI_LIVE_OPENAI_MODEL; \
    KAJI_REQUIRE_LIVE_KEYS=1 bash "$ROOT/kaji/scripts/live-openai-tool-loop.sh" 2>&1)"
  status=$?
  set -e
  [ "$status" -eq 2 ] || fail "required OpenAI key check returned $status instead of 2"
  printf '%s\n' "$output"
}

require_command bun "TypeScript SDK release gates"
require_command node "installed npm package proof"
require_command npm "npm artifact construction"
require_command uv "Python SDK release gates"

run_no_key_live_skip
run_required_key_failure
run_in_dir "ast-grep structural audit" "$ROOT" bun run audit:ast-grep
run_in_dir "Cross-SDK behavioral parity" "$ROOT" \
  uv run --project kaji/sdk python kaji/scripts/check-sdk-parity.py
run_in_dir "Shared beta contract" "$ROOT" \
  uv run --project kaji/sdk python kaji/scripts/check-beta-contract.py
run_in_dir "Packaged beta contract synchronization" "$ROOT" \
  uv run --project kaji/sdk python kaji/scripts/sync-beta-contracts.py --check
run_in_dir "Integration contract synchronization" "$ROOT" \
  uv run --project kaji/sdk python kaji/scripts/sync-integration-contracts.py --check
run_in_dir "Deterministic complexity and quick benchmark smoke" "$ROOT" \
  bash kaji/scripts/run-beta-benchmarks.sh --quick

run_in_dir "TypeScript unit tests" "$ROOT/kaji/ts" bun run test
run_in_dir "TypeScript typecheck" "$ROOT/kaji/ts" bun run typecheck
run_in_dir "TypeScript build" "$ROOT/kaji/ts" bun run build
run_in_dir "TypeScript package smoke" "$ROOT/kaji/ts" bun run package:smoke

run_in_dir "Python unit tests" "$ROOT/kaji/sdk" uv run pytest -m "not integration"
run_in_dir "Python typecheck" "$ROOT/kaji/sdk" \
  uv run python scripts/typecheck_ty.py --output-format concise
run_in_dir "Python lint" "$ROOT/kaji/sdk" uv run ruff check src tests
run_in_dir "Python artifact smoke" "$ROOT/kaji/sdk" bash scripts/release_smoke.sh

if [ "$RELEASE" -eq 1 ]; then
  ARTIFACTS="$ROOT/.artifacts/kaji-release"
  RELEASE_TMP="$(mktemp -d "${TMPDIR:-/tmp}/kaji-release.XXXXXX")"
  trap 'rm -rf "$RELEASE_TMP"' EXIT
  rm -rf "$ARTIFACTS"
  mkdir -p "$ARTIFACTS"

  run_in_dir "Python format" "$ROOT/kaji/sdk" uv run ruff format --check src tests
  run_in_dir "Python lint (release)" "$ROOT/kaji/sdk" uv run ruff check src tests
  run_in_dir "Python typecheck (release)" "$ROOT/kaji/sdk" \
    uv run python scripts/typecheck_ty.py --output-format concise
  run_in_dir "Python tests (release)" "$ROOT/kaji/sdk" uv run pytest
  run_in_dir "Python release artifacts" "$ROOT/kaji/sdk" bash scripts/release_smoke.sh
  run_in_dir "Python metadata" "$ROOT/kaji/sdk" uv run twine check dist/*

  run_in_dir "TypeScript format" "$ROOT/kaji/ts" bun run format:check
  run_in_dir "TypeScript lint" "$ROOT/kaji/ts" bun run lint
  run_in_dir "TypeScript typecheck (release)" "$ROOT/kaji/ts" bun run typecheck
  run_in_dir "TypeScript registry typecheck" "$ROOT/kaji/ts" bun run typecheck:registry
  run_in_dir "TypeScript registry validation" "$ROOT/kaji/ts" bun run validate:registry
  run_in_dir "TypeScript integration validation" "$ROOT/kaji/ts" bun run check:integrations
  run_in_dir "TypeScript tests (release)" "$ROOT/kaji/ts" bun run test
  run_in_dir "TypeScript build (release)" "$ROOT/kaji/ts" bun run build
  run_in_dir "TypeScript package smoke (release)" "$ROOT/kaji/ts" bun run package:smoke
  run_in_dir "TypeScript publint" "$ROOT/kaji/ts" bun x publint
  run_in_dir "TypeScript type artifact audit" "$ROOT/kaji/ts" \
    env npm_config_cache="$RELEASE_TMP/attw-npm-cache" bun x attw --pack .

  section "Locked production dependency audits"
  (cd "$ROOT/kaji/sdk" && \
    uv export --locked --no-dev --no-emit-project \
      --extra openai --extra anthropic \
      --output-file "$RELEASE_TMP/requirements.txt" && \
    uv run pip-audit --require-hashes --requirement "$RELEASE_TMP/requirements.txt")
  (cd "$ROOT/kaji/sdk" && \
    uv run pip-audit --require-hashes --requirement build-requirements.txt)
  (cd "$ROOT/kaji/ts" && bun audit --production)

  section "Construct release npm tarball"
  npm_config_cache="$RELEASE_TMP/npm-cache" npm pack \
    --ignore-scripts --pack-destination "$ARTIFACTS" "$ROOT/kaji/ts"
  TARBALL_COUNT="$(find "$ARTIFACTS" -maxdepth 1 -type f -name '*.tgz' | wc -l | tr -d ' ')"
  [ "$TARBALL_COUNT" -eq 1 ] || fail "expected exactly one npm tarball, found $TARBALL_COUNT"
  TARBALL="$(find "$ARTIFACTS" -maxdepth 1 -type f -name '*.tgz' -print)"

  run_in_dir "Exact TypeScript artifact contents" "$ROOT" \
    uv run --project kaji/sdk python kaji/scripts/verify_npm_package.py "$TARBALL"
  run_in_dir "Exact TypeScript artifact install smoke" "$ROOT/kaji/ts" \
    bun scripts/smoke-installed.mts "$TARBALL"
  run_in_dir "Reverify final Python artifacts" "$ROOT/kaji/sdk" \
    bash scripts/verify_wheel.sh dist

  COMMIT="${KAJI_RELEASE_COMMIT:-${GITHUB_SHA:-}}"
  if [ -n "$COMMIT" ]; then
    run_in_dir "Package metadata and checksum manifest" "$ROOT" \
      uv run --project kaji/sdk python kaji/scripts/verify-package-metadata.py \
        --release --commit "$COMMIT" --artifacts-dir "$ARTIFACTS"
  else
    run_in_dir "Local package metadata and checksum manifest" "$ROOT" \
      uv run --project kaji/sdk python kaji/scripts/verify-package-metadata.py \
        --artifacts-dir "$ARTIFACTS"
  fi
fi

if [ "$RELEASE" -eq 0 ] && [ "${KAJI_RUN_KEYED_LIVE:-0}" = "1" ]; then
  section "Protected keyed provider proof"
  bash "$ROOT/kaji/scripts/live-provider-proof.sh"
elif [ "$RELEASE" -eq 0 ]; then
  section "Protected keyed provider proof"
  echo "SKIP: not requested; no keyed provider evidence is claimed."
fi

echo
if [ "$RELEASE" -eq 1 ]; then
  echo "PASS: offline release rehearsal; keyed/provider/publish readiness NOT claimed"
else
  echo "PASS: Kaji beta checks completed"
fi
