# TypeScript onboarding evidence

This policy records deterministic onboarding proof for the exact
`kaji-sdk-0.2.0-beta.11.tgz` release candidate. It runs from the candidate
artifact rather than a source checkout and is required in both the rehearsal
and tag-triggered protected release workflows.

The evidence makes a deliberately narrow claim: the candidate completed the
documented npm and Bun install, scaffold, no-key, Echo lifecycle, cold, and
warm phases in exactly these GitHub-hosted Linux/x64 cells:

| Cell | Runner | Runtime |
| --- | --- | --- |
| Node 22 | `ubuntu-22.04` / `ubuntu22` | exact `v22.x.y` |
| Node 24 | `ubuntu-24.04` / `ubuntu24` | exact `v24.x.y` |

This is automated compatibility and onboarding evidence. It is not a
five-human measurement, not a macOS or arm64 onboarding claim, not a Windows
onboarding claim, and not a fully offline dependency-installation claim. The
separate GitHub-hosted macOS/arm64 performance and soak jobs retain their own
runner and image evidence; they do not widen this onboarding claim.

## Exact inputs and retained output

The workflow resolves exactly one unexpired artifact for each of
`kaji-beta-artifacts`, `kaji-node-compat-22`, and `kaji-node-compat-24` from
the current run attempt. It requeries each artifact by numeric ID, checks its
canonical `sha256:<hex>` REST digest, current run ID, attempt `1`, head commit,
and expected name, then authenticates the raw REST ZIP bytes before reading
members. A prior-run archive, extracted receipt, rebuilt tarball, name-only
download, or later same-named artifact cannot substitute.

The unprotected `typescript-onboarding-archive-calibration` job and protected
`typescript-onboarding-evidence` job independently repeat that lookup, byte
authentication, receipt validation, and two-cell aggregate recomputation. The
protected job waits at `kaji-beta-onboarding` only after calibration succeeds;
it does not consume or trust calibration output.

A successful protected job retains exactly these files in
`kaji-typescript-onboarding-evidence`:

- `status.json`
- `validation.log`
- `typescript-onboarding-evidence.json`

The aggregate is validated by
`kaji/contracts/release/typescript-onboarding-evidence-v1.schema.json`. Its
closed fields bind:

- the exact commit, release-manifest SHA-256, npm tarball name, size, and
  SHA-256;
- the producer and Node compatibility artifact names, IDs, REST digests,
  current run ID, attempt, head SHA, and raw receipt SHA-256 values;
- the workflow run URL, workflow ref, workflow SHA, job, configured runner
  label, actual Linux/X64 identity, image OS/version, and exact Node runtime;
- npm, Bun 1.3.11, TypeScript 5.7.3 and TypeScript 6.0.3 toolchain versions;
- passed `artifactInstall`, `scaffoldInit`, `noKeyRun`, `echoSetup`,
  `echoRun`, `coldRun`, and `warmRun` phases for npm and Bun;
- deterministic text, nonempty turn identity, positive final sequence, one
  ordered Echo `requested` → `started` → `completed` lifecycle, one nonempty
  tool-call identity, exact `{"message":"hello"}` result, absence of failed,
  exhausted, or cancelled terminal events, and equal cold/warm terminal
  behavior;
- nonnegative observed cold-setup-to-output and warm-run durations. These are
  retained observations, not human timing thresholds or performance gates.

Any missing, extra, failed, byte-different, cross-run, cross-attempt,
wrong-runner, wrong-runtime, or wrong-artifact value fails closed.

## Canonical Echo snippets

The release smokes extract these marked blocks and run them unchanged against
installed artifacts. The Python block remains an installed-wheel compatibility
smoke; it is not one of the two TypeScript onboarding cells.

After the installed Python CLI stages Echo into `echo/`, save the following as
`echo_loop.py` and run it with the installed Python interpreter:

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

For either TypeScript package manager, the installed CLI first stages Echo into
`echo/`. Save the following as `echo-loop.mts`. Run it with
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

These deterministic snippets exercise the exact lifecycle assertions embedded
in each npm and Bun onboarding proof. They do not replace the raw-archive
identity checks, protected environment review, keyed provider gate, publisher
review, performance/soak evidence, SBOM/provenance attestations, or exact npm
registry-byte verification required by the
[release runbook](releasing.md).
