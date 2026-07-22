# TTHW evidence operator guide

This protocol produces the redacted JSON stored as
`KAJI_TTHW_EVIDENCE_JSON`. It never accepts a source checkout as a participant
environment. The final composer reuses the protected validator, derives all
artifact hashes and aggregate totals, and refuses to replace its output unless
the complete document passes.

## Inputs and cohort

Retain the exact release `manifest.json`, wheel, sdist, and npm tarball in one
read-only artifact directory. Give each participant only the generated receipt
skeleton, manifest, and artifact selected for their path. Do not give them a
repository archive, editable install, linked workspace, or local registry
override.

The checked-in participant template documents the closed receipt shape; its
placeholder candidate fields are not collection evidence. Generate each
candidate-bound skeleton from the retained manifest and artifacts before
collecting results. For example:

```bash
uv run --project kaji python kaji/scripts/compose_tthw_evidence.py \
  --generate-participant-template python \
  --release-manifest /secure/kaji-release/manifest.json \
  --artifacts-dir /secure/kaji-release \
  --output /secure/tthw/user-001.json
```

Repeat that command for all five assignments, changing the selected path and
output file. Copy
`kaji/contracts/release/tthw-automated-timings.template.json` once per release.
The generator verifies the canonical manifest and all three artifacts, then
atomically binds the selected wheel or npm tarball into an owner-only skeleton.

Use exactly five distinct pseudonyms. Every participant must use arm64 macOS;
the following assignment covers Python, npm, and Bun while binding each run to
the artifact it installs:

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
set to `true` only after the operator verifies both conditions.

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
export KAJI_TARBALL="$KAJI_ARTIFACTS/kaji-sdk-0.2.0-beta.2.tgz"
mkdir "$HOME/kaji-tthw-npm"
cd "$HOME/kaji-tthw-npm"
npm init --yes
npm install "$KAJI_TARBALL" zod@4.3.6 tsx typescript @types/node
./node_modules/.bin/kaji --no-color init generated --provider mock --yes
npm pkg set "dependencies.@kaji/sdk=file:$KAJI_TARBALL" --prefix generated
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
export KAJI_TARBALL="$KAJI_ARTIFACTS/kaji-sdk-0.2.0-beta.2.tgz"
mkdir "$HOME/kaji-tthw-bun"
cd "$HOME/kaji-tthw-bun"
bun init --yes
bun add "$KAJI_TARBALL" zod@4.3.6 tsx typescript @types/node
./node_modules/.bin/kaji --no-color init generated --provider mock --yes
node -e 'const fs=require("node:fs");const p="generated/package.json";const j=JSON.parse(fs.readFileSync(p));j.dependencies["@kaji/sdk"]="file:"+process.argv[1];fs.writeFileSync(p,JSON.stringify(j,null,2)+"\n")' "$KAJI_TARBALL"
bun install --cwd generated
bun run --cwd generated start
./node_modules/.bin/kaji --no-color add echo --out echo
```

Save the following as `echo-loop.ts`. Run it with
`./node_modules/.bin/tsx echo-loop.ts` for npm or `bun echo-loop.ts` for Bun:

<!-- tthw-echo:typescript:start -->
```ts
import { AgentBuilder, EventType } from "@kaji/sdk";
import { MockProvider } from "@kaji/sdk/testing";
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
console.log("PASS: echo requested, started, completed, and observed");
```
<!-- tthw-echo:typescript:end -->

Set every assertion in the receipt to `true` only when these checks pass. The
requested, started, and completed events must share one nonempty tool-call ID;
the completion result must contain the input message; the final text must be
the exact deterministic mock text; and no failed, exhausted, or cancelled
terminal event may occur.

## Automated timings and composition

Populate the automated-timings template from the retained exact-artifact
Python, npm, and Bun cold/warm smoke receipts. Do not substitute participant
wall-clock estimates. Keep raw participant receipts outside the repository and
redact confusion notes before composition.

Run the composer from the release checkout, listing each participant exactly
once:

```bash
uv run --project kaji python kaji/scripts/compose_tthw_evidence.py \
  --participant /secure/tthw/user-001.json \
  --participant /secure/tthw/user-002.json \
  --participant /secure/tthw/user-003.json \
  --participant /secure/tthw/user-004.json \
  --participant /secure/tthw/user-005.json \
  --automated-timings /secure/tthw/automated-timings.json \
  --release-manifest /secure/kaji-release/manifest.json \
  --artifacts-dir /secure/kaji-release \
  --output /secure/tthw/KAJI_TTHW_EVIDENCE_JSON.json
```

The output is written atomically with owner-only permissions after
`validate_tthw_evidence.py` passes. Copy the file bytes, without shell quoting
or a trailing explanation, into the protected `KAJI_TTHW_EVIDENCE_JSON`
secret. Never commit participant receipts or the composed document.

## Calibration A and release candidate B

A reviewed calibration run records its own commit and artifact identity, called
artifact set A, for auditability. The committed baseline remains applicable to
a later candidate B only when all four explicit applicability dimensions are
identical: benchmark source hash, dependency-lock hash, runtime/toolchain
versions, and pinned-runner fingerprint. The baseline's calibration commit and
manifest are provenance, not a requirement that A and B share package bytes.

The protected full benchmark and 30-minute soak are different evidence. They
must install, hash, and report candidate B's own wheel and npm tarball and must
bind their receipts to B's commit and release-manifest hash. A fingerprint
mismatch invalidates the baseline and requires recalibration; a fingerprint
match never permits full or soak receipts to refer to A's artifacts.
