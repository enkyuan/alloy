# TTHW evidence operator guide

This protocol produces the redacted JSON stored as
`KAJI_TTHW_EVIDENCE_JSON`. It never accepts a source checkout as a participant
environment. The final composer reuses the protected validator, derives all
artifact hashes and aggregate totals, and refuses to replace its output unless
the complete document passes.

## Inputs and cohort

Retain the exact release `manifest.json`, wheel, sdist, and npm tarball from the
exact `kaji-beta-artifacts` upload from the current tag-triggered `publish /
kaji` run in one read-only artifact directory. Record the workflow run ID and
artifact ID, and download the archive by that artifact ID while the
`tthw-evidence` job remains paused at its protected environment. Prior release,
rehearsal, and performance artifacts are invalid substitutes. Give each
participant only the generated receipt skeleton, manifest, and artifact
selected for their path. Do not give them a repository archive, editable
install, linked workspace, or local registry override.

Continue in the same operator shell used by the release runbook and create the
private cohort directory once:

```bash
: "${EVIDENCE_ROOT:?follow the release runbook first}"
: "${ARTIFACTS_DIR:?follow the release runbook first}"
TTHW_DIR="$EVIDENCE_ROOT/tthw"
mkdir -m 700 "$TTHW_DIR"
```

The checked-in participant template documents the closed receipt shape; its
placeholder candidate fields are not collection evidence. Generate each
candidate-bound skeleton from the retained manifest and artifacts before
collecting results. For example:

```bash
uv run --project kaji python kaji/scripts/compose_tthw_evidence.py \
  --generate-participant-template python \
  --release-manifest "$ARTIFACTS_DIR/manifest.json" \
  --artifacts-dir "$ARTIFACTS_DIR" \
  --output "$TTHW_DIR/user-001.json"
```

Repeat that command for all five assignments, changing the selected path and
output file. There is no operator-authored automated-timing input.
The generator verifies the canonical manifest and all three artifacts, then
atomically binds the selected wheel or npm tarball into an owner-only skeleton.
Every human attestation and lifecycle assertion remains `false`; the skeleton
is intentionally incomplete until the participant and operator verify each
claim.

Use exactly five distinct pseudonyms. Every participant must use arm64 macOS;
the split is exactly two Python, two npm, and one Bun. Any other distribution
is rejected. The following assignment binds each run to the artifact it
installs:

| Receipt | OS / architecture | Path | Artifact |
| --- | --- | --- | --- |
| `user-001` | macOS / arm64 | Python | wheel |
| `user-002` | macOS / arm64 | Python | wheel |
| `user-003` | macOS / arm64 | npm | npm tarball |
| `user-004` | macOS / arm64 | npm | npm tarball |
| `user-005` | macOS / arm64 | Bun | npm tarball |

Each participant starts in a new empty directory outside any Kaji checkout.
Record `uname -m` as `architecture` and `sw_vers -productVersion` as
`platformVersion`; they must report `arm64` and a numeric macOS version. Record
the literal output of `python --version`, `uv --version`,
`node --version`, `npm --version`, `bun --version`, and the installed
TypeScript compiler versions in `toolchain`. A command that is not used still
gets its installed version. `cleanEnvironment` and `noSourceCheckout` may be
set to `true` only after the operator verifies both conditions. Replace every
participant, owner, toolchain, and date placeholder. `reviewDate` must be the
actual review date. The composer records `collectedDate` and accepts only
reviews from that date or the preceding seven days. The protected release
validator separately requires `collectedDate` to be no more than seven days old
and not in the future.

Time these non-overlapping steps with a monotonic clock and record integer
milliseconds:

1. `artifact-install`: environment creation through successful artifact and
   dependency installation.
2. `scaffold-init`: CLI start through completed mock scaffold creation.
3. `no-key-run`: scaffold start through its first valid output.
4. `echo-setup`: Echo copy start through a runnable Echo proof file.
5. `echo-run`: Echo proof start through all lifecycle assertions passing.

Do not enter `noKeyTotalMs`, `echoTotalMs`, or summary values in a participant
receipt. Do not hand-edit its generated commit, manifest hash, artifact name,
package, version, or hash. The composer verifies those bindings and derives the
totals. Every checked-in `-1` timing is an invalid sentinel and must be replaced
with a real measurement.

## Python path

Set absolute paths first. Every Python participant installs the wheel; the
sdist remains bound by the aggregate release evidence but is not a TTHW
participant artifact.

```bash
export KAJI_ARTIFACTS=/absolute/path/to/kaji-release
export KAJI_PYTHON_ARTIFACT="$KAJI_ARTIFACTS/kaji_sdk-0.2.0b1-py3-none-any.whl"
mkdir "$HOME/kaji-tthw-python"
cd "$HOME/kaji-tthw-python"
python3 -m venv .venv
.venv/bin/python -m pip install "$KAJI_PYTHON_ARTIFACT"
.venv/bin/python -m kaji.cli --no-color init generated --provider mock --yes
cd generated
../.venv/bin/python agent.py
cd ..
.venv/bin/python -m kaji.cli --no-color add echo --out echo
```

The no-key run must print `text=mock response`, a nonempty `turn_id`, and a positive
integer `final_sequence`. Save this as `echo_loop.py` in the empty participant
directory and run it with `.venv/bin/python echo_loop.py`:

<!-- tthw-echo:python:start -->
```python
import asyncio

import kaji
from echo.echo import EchoIntegration
from kaji.infra.events import EventType


async def main() -> None:
    runtime = (
        kaji.AgentBuilder()
        .provider(
            kaji.get_provider(
                "mock",
                tool_call={"name": "echo_say", "args": {"message": "hello"}},
            )
        )
        .integration(EchoIntegration())
        .build()
    )
    result = await runtime.turn(
        "Call echo_say.",
        context=kaji.TurnContext(principal_id="tthw-user"),
    )
    requested = next(e for e in result.events if e.type == EventType.TOOL_CALL_REQUESTED)
    started = next(e for e in result.events if e.type == EventType.TOOL_CALL_STARTED)
    completed = next(e for e in result.events if e.type == EventType.TOOL_CALL_COMPLETED)
    assert requested.tool_call_id == started.tool_call_id == completed.tool_call_id
    assert completed.result == {"message": "hello"}
    assert result.text == "mock response"
    assert result.turn_id
    assert max(event.sequence or 0 for event in result.events) > 0
    unexpected_terminal_types = {
        EventType.AGENT_TURN_FAILED,
        EventType.AGENT_TURN_EXHAUSTED,
        EventType.TOOL_CALL_FAILED,
        EventType.CANCELLATION_REQUESTED,
        EventType.CANCELLATION_COMPLETED,
    }
    assert all(
        event.type not in unexpected_terminal_types for event in result.events
    )
    print("PASS: echo requested, started, completed, and observed")


asyncio.run(main())
```
<!-- tthw-echo:python:end -->

## npm path

Use a new empty directory. The first install supplies the package-owned CLI;
the generated scaffold is then pinned back to the same local tarball before it
is installed.

```bash
export KAJI_ARTIFACTS=/absolute/path/to/kaji-release
export KAJI_TARBALL="$KAJI_ARTIFACTS/kaji-sdk-0.2.0-beta.6.tgz"
mkdir "$HOME/kaji-tthw-npm"
cd "$HOME/kaji-tthw-npm"
npm init --yes
npm install "$KAJI_TARBALL" zod@4.3.6 tsx typescript@6.0.3 @types/node
./node_modules/.bin/kaji --no-color init generated --provider mock --yes
npm pkg set "dependencies.kaji-sdk=file:$KAJI_TARBALL" --prefix generated
npm install --prefix generated
npm run start --silent --prefix generated
./node_modules/.bin/kaji --no-color add echo --out echo
```

The no-key run must print
`text=The mock provider has completed the tool loop.`, a nonempty `turn_id`,
and a positive integer `final_sequence`.

## Bun path

Use the same tarball in another new empty directory. The short Node command
changes only the generated dependency from the registry version to the exact
local tarball.

```bash
export KAJI_ARTIFACTS=/absolute/path/to/kaji-release
export KAJI_TARBALL="$KAJI_ARTIFACTS/kaji-sdk-0.2.0-beta.6.tgz"
mkdir "$HOME/kaji-tthw-bun"
cd "$HOME/kaji-tthw-bun"
bun init --yes
bun remove typescript
bun add "$KAJI_TARBALL" zod@4.3.6 tsx @types/node
bun add --dev typescript@6.0.3
./node_modules/.bin/kaji --no-color init generated --provider mock --yes
node -e 'const fs=require("node:fs");const p="generated/package.json";const j=JSON.parse(fs.readFileSync(p));j.dependencies["kaji-sdk"]="file:"+process.argv[1];fs.writeFileSync(p,JSON.stringify(j,null,2)+"\n")' "$KAJI_TARBALL"
bun install --cwd generated
bun run --cwd generated start
./node_modules/.bin/kaji --no-color add echo --out echo
```

Save the following as `echo-loop.mts`. Run it with
`./node_modules/.bin/tsx echo-loop.mts` for npm or
`bun --no-install echo-loop.mts` for Bun:

<!-- tthw-echo:typescript:start -->
```ts
import { AgentBuilder, EventType } from "kaji-sdk";
import { MockProvider } from "kaji-sdk/testing";
import { EchoIntegration } from "./echo/index.ts";

const runtime = new AgentBuilder()
  .provider(
    new MockProvider({
      toolCall: { name: "echo_say", args: { message: "hello" } },
    }),
  )
  .integration(new EchoIntegration())
  .build();
const result = await runtime.turn("Call echo_say.", {
  context: { principalId: "tthw-user" },
});
const requested = result.events.find((event) => event.type === EventType.TOOL_CALL_REQUESTED);
const started = result.events.find((event) => event.type === EventType.TOOL_CALL_STARTED);
const completed = result.events.find((event) => event.type === EventType.TOOL_CALL_COMPLETED);
if (requested === undefined || started === undefined || completed === undefined) {
  throw new Error("missing Echo lifecycle event");
}
if (
  !("tool_call_id" in requested) ||
  !("tool_call_id" in started) ||
  !("tool_call_id" in completed) ||
  requested.tool_call_id !== started.tool_call_id ||
  started.tool_call_id !== completed.tool_call_id
) {
  throw new Error("Echo tool-call identity changed");
}
if (!("result" in completed) || JSON.stringify(completed.result) !== '{"message":"hello"}') {
  throw new Error("Echo result was not observed");
}
if (result.text !== "The mock provider has completed the tool loop.") {
  throw new Error("unexpected deterministic text");
}
if (result.turnId.length === 0 || Math.max(...result.events.map((event) => event.sequence)) <= 0) {
  throw new Error("missing turn or sequence identity");
}
const unexpectedTerminalTypes = new Set<string>([
  EventType.AGENT_TURN_FAILED,
  EventType.AGENT_TURN_EXHAUSTED,
  EventType.TOOL_CALL_FAILED,
  EventType.CANCELLATION_REQUESTED,
  EventType.CANCELLATION_COMPLETED,
]);
if (result.events.some((event) => unexpectedTerminalTypes.has(event.type))) {
  throw new Error("unexpected failed, exhausted, or cancelled terminal event");
}
console.log("PASS: echo requested, started, completed, and observed");
```
<!-- tthw-echo:typescript:end -->

Set every assertion in the receipt to `true` only when these checks pass. The
requested, started, and completed events must share one nonempty tool-call ID;
the completion result must contain the input message; the final text must be
the exact deterministic mock text; and no failed, exhausted, or cancelled
terminal event may occur. Set `noUnexpectedTerminalEvents` only after the
terminal-event check passes. Set `monotonicDurations` only after every step was
timed with a monotonic clock.

## Automated timings and composition

Download only the final `kaji-python-compat-3.14` and
`kaji-node-compat-24` artifacts from the exact protected workflow run being
reviewed. Record that run's numeric `RUN_ID`, positive integer `RUN_ATTEMPT`,
and the two exact artifact IDs. Extract them into separate owner-only
directories; never merge them with each other or with an `*-initial` artifact.
Verify both `compatibility-receipt.json` files name
`https://github.com/enkyuan/alloy/actions/runs/$RUN_ID` and the exact
`RUN_ATTEMPT`.

```bash
set -euo pipefail
umask 077
: "${RUN_ID:?set the exact protected workflow run ID}"
: "${RUN_ATTEMPT:?set the current protected workflow run attempt}"

PYTHON_COMPAT_ID="$(
  gh api "repos/enkyuan/alloy/actions/runs/$RUN_ID/artifacts?per_page=100" \
    --jq '.artifacts
      | map(select(.name == "kaji-python-compat-3.14" and .expired == false))
      | if length == 1 then .[0].id else error("expected one final Python 3.14 artifact") end'
)"
NODE_COMPAT_ID="$(
  gh api "repos/enkyuan/alloy/actions/runs/$RUN_ID/artifacts?per_page=100" \
    --jq '.artifacts
      | map(select(.name == "kaji-node-compat-24" and .expired == false))
      | if length == 1 then .[0].id else error("expected one final Node 24 artifact") end'
)"

PYTHON_COMPAT_DIR="$TTHW_DIR/compat-python-3.14"
NODE_COMPAT_DIR="$TTHW_DIR/compat-node-24"
mkdir -m 700 "$PYTHON_COMPAT_DIR" "$NODE_COMPAT_DIR"
gh api "repos/enkyuan/alloy/actions/artifacts/$PYTHON_COMPAT_ID/zip" \
  >"$TTHW_DIR/compat-python-3.14.zip"
gh api "repos/enkyuan/alloy/actions/artifacts/$NODE_COMPAT_ID/zip" \
  >"$TTHW_DIR/compat-node-24.zip"
unzip -q "$TTHW_DIR/compat-python-3.14.zip" -d "$PYTHON_COMPAT_DIR"
unzip -q "$TTHW_DIR/compat-node-24.zip" -d "$NODE_COMPAT_DIR"

EXPECTED_WORKFLOW_RUN="https://github.com/enkyuan/alloy/actions/runs/$RUN_ID"
for receipt in \
  "$PYTHON_COMPAT_DIR/compatibility-receipt.json" \
  "$NODE_COMPAT_DIR/compatibility-receipt.json"; do
  jq -e \
    --arg run "$EXPECTED_WORKFLOW_RUN" \
    --argjson attempt "$RUN_ATTEMPT" \
    '.workflowRun == $run and .workflowRunAttempt == $attempt and
     .conclusion == "passed" and .failureCode == null' \
    "$receipt" >/dev/null
done
```

The composer derives `automatedTimings.python` from
`receipt.timings.wheel` in the Python 3.14 receipt and derives
`automatedTimings.npm` from `receipt.timings.npm` and
`automatedTimings.bun` from `receipt.timings.bun` in the Node 24 receipt.
Python 3.11, Node 22, and `receipt.timings.sdist` remain
retained compatibility evidence; they are not canonical TTHW timing inputs.
The closed receipts also supply the measured runtime toolchain. Keep raw
participant receipts outside the repository and redact confusion notes before
composition.

Run the composer from the release checkout, listing each participant exactly
once:

```bash
uv run --project kaji python kaji/scripts/compose_tthw_evidence.py \
  --participant "$TTHW_DIR/user-001.json" \
  --participant "$TTHW_DIR/user-002.json" \
  --participant "$TTHW_DIR/user-003.json" \
  --participant "$TTHW_DIR/user-004.json" \
  --participant "$TTHW_DIR/user-005.json" \
  --python-compatibility-receipt \
    "$PYTHON_COMPAT_DIR/compatibility-receipt.json" \
  --node-compatibility-receipt \
    "$NODE_COMPAT_DIR/compatibility-receipt.json" \
  --expected-workflow-run \
    "https://github.com/enkyuan/alloy/actions/runs/$RUN_ID" \
  --expected-workflow-run-attempt "$RUN_ATTEMPT" \
  --release-manifest "$ARTIFACTS_DIR/manifest.json" \
  --artifacts-dir "$ARTIFACTS_DIR" \
  --output "$TTHW_DIR/KAJI_TTHW_EVIDENCE_JSON.json"
```

The output is newline-free canonical JSON written atomically with owner-only
permissions after `validate_tthw_evidence.py`'s deterministic document checks
pass. Do not copy it into `KAJI_TTHW_EVIDENCE_JSON` or approve the environment
separately. Hand this file only to `kaji/scripts/approve_tthw_gate.py` through
the protected-release command in [the release runbook](releasing.md); the helper
rejects terminal CR/LF bytes that GitHub CLI would otherwise remove, validates
the exact bytes, sets the environment secret, repeats the remote preflight, and
then approves the sole waiting job. At release time, the validator also rejects
a `collectedDate` in the future or more than seven days old. The serialized
document must be at most 49,152 bytes; the composer refuses to replace its
output above that exact environment-secret limit. No-key median must be under
5 minutes and every no-key run under 10; Echo median must be under 10 minutes
and every Echo run under 20. Never commit participant receipts or the composed
document.

A rehearsal may exercise this same derivation against its own current run and
attempt, but that document is rehearsal evidence only. Final publication proof
must be recomposed from the final artifacts and compatibility receipts emitted
by the tag-triggered protected publish workflow.
When rerunning a rehearsal, rerun the whole workflow so both compatibility
producer jobs and TTHW validation emit the same `RUN_ATTEMPT`; never rerun only
the TTHW job. Mixed-attempt receipts are intentionally rejected. The protected
publish workflow remains first-attempt-only.

## Performance evidence is separate

TTHW receipts bind only the exact release candidate and do not replace
performance evidence. The protected paired benchmark installs the immutable
artifact set in `kaji/benchmarks/beta-reference.json` beside that candidate on
three numbered `macos-15` matrix replicas in one workflow run attempt. Each
case records five adjacent matched A/B pairs after two warmups. Any per-pair
RSS ratio above `1.20` is a hard failure; timing passes only when all three
replica medians are at or below `1.20`, while a mixed result is inconclusive
and blocks release. All raw replica and runner/image receipts are retained;
diagnostic `RUNNER_NAME` values may repeat.

The separate protected 30-minute soak installs, hashes, and reports the exact
candidate with its own runner/image receipt. Neither the immutable reference
artifact nor any performance receipt may be used as a TTHW participant
artifact.
