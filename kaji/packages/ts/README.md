# Kaji (TypeScript)

Kaji is an embeddable, infra-free TypeScript SDK for capability execution with
an event-sourced journal, typed tools, fail-closed policy, and session replay.

This `0.3.0-alpha.1` candidate ships the retained capability product: one-shot
`Kaji.execute` over a registered `capability`. There is no agent loop and no
provider adapter in the TypeScript package; policy and approval enforcement
live in the execution planner.

## Install

Build or obtain the candidate tarball, then install it with the required Zod
peer:

```bash
npm install ./irogane-kaji-0.3.0-alpha.1.tgz zod
# or: bun add ./irogane-kaji-0.3.0-alpha.1.tgz zod
```

Kaji requires Zod `>=4.3 <5`. It supports Node 22.x and 24.x. See the
[install guide](https://github.com/enkyuan/alloy/blob/main/apps/docs/content/install.mdx)
for source-checkout and compatibility details.

## First run: no key

Save this as `quickstart.mts`, then run `npm exec -- tsx quickstart.mts` or
`bun quickstart.mts`.

<!-- docs-test:readme-no-key:typescript:start -->
```ts
import { Kaji, capability, capabilityResult } from "@irogane/kaji";
import * as z from "zod";

const echo = capability({
  name: "echo",
  description: "Echo the provided message back.",
  input: z.object({ message: z.string() }),
  risk: "read",
  execute: async (input) => capabilityResult({ message: input.message }),
});

const result = await Kaji.execute({
  capability: echo,
  input: { message: "Hello, Kaji." },
  principal: "local-user",
});
console.log(JSON.stringify(result.value));
```
<!-- docs-test:readme-no-key:typescript:end -->

This proves capability execution without credentials, servers, or enabled
tools. The default journal and idempotency ledger are bounded, in-memory, and
process-local.

## Idempotent retries

Supplying `sessionId` makes same-session retries of one capability deduplicate
to a single execution: the retry returns the recorded result without running
the hook again. Changed input in the same session rejects with
`ToolExecutionError`; distinct sessions run independently.

<!-- docs-test:readme-openai:typescript:start -->
```ts
import { Kaji, capability, capabilityResult } from "@irogane/kaji";
import * as z from "zod";

const echo = capability({
  name: "echo",
  description: "Echo the provided message back.",
  input: z.object({ message: z.string() }),
  risk: "read",
  execute: async (input) => capabilityResult({ message: input.message }),
});

const sessionId = "retry-session";
const first = await Kaji.execute({
  capability: echo,
  input: { message: "hello" },
  principal: "caller",
  sessionId,
});
const retry = await Kaji.execute({
  capability: echo,
  input: { message: "hello" },
  principal: "caller",
  sessionId,
});
console.log(JSON.stringify(first.value), JSON.stringify(retry.value));
```
<!-- docs-test:readme-openai:typescript:end -->

## Next steps

- [Getting started](https://github.com/enkyuan/alloy/blob/main/apps/docs/content/getting-started.mdx)
- [Tool policy and approval](https://github.com/enkyuan/alloy/blob/main/apps/docs/content/concepts/tool-registry.mdx)
- [Lifecycle and data handling](https://github.com/enkyuan/alloy/blob/main/apps/docs/content/concepts/lifecycle.mdx)
- [Events](https://github.com/enkyuan/alloy/blob/main/apps/docs/content/concepts/event-bus.mdx)

## License

Kaji is source-available under the
[Functional Source License 1.1, ALv2 Future License](https://spdx.org/licenses/FSL-1.1-ALv2.html).
It permits internal commercial use, modification, and redistribution for permitted purposes,
but excludes competing commercial products and services; each version becomes Apache-2.0 after
two years. FSL is not an OSI-approved open-source license.
