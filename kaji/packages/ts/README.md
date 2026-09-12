# Kaji (TypeScript)

Kaji is an embeddable, infra-free TypeScript SDK for building agents with an
event-sourced runtime, typed tools, and session replay.

This `0.3.0-alpha.1` candidate has local release evidence but is not a claim of
npm registry availability. OpenAI is the recommended live-provider path;
Anthropic, Gemini, Kimi, and OpenRouter are opt-in WIP adapters. Use
`MockProvider` for deterministic local and test runs.

### Provider parity

| Provider category | Python | TypeScript |
| --- | --- | --- |
| OpenAI | Yes (stable) | Yes (stable) |
| Anthropic | Yes (experimental/WIP) | Yes (experimental/WIP) |
| Kimi / Gemini providers | Yes (experimental/WIP) | Yes (experimental/WIP, OpenAI-compatible factories) |
| OpenRouter | No | Yes (experimental/WIP) |
| MockProvider | Yes (stable) | Yes (stable) |

## Install

Build or obtain the candidate tarball, then install it with the required Zod
peer. Add `openai` only for a live OpenAI runtime:

```bash
npm install ./irogane-kaji-0.3.0-alpha.1.tgz zod
npm install openai
# or: bun add ./irogane-kaji-0.3.0-alpha.1.tgz zod openai
```

Kaji requires Zod `>=4.3 <5`; `openai` is an optional peer. It supports Node
22.x and 24.x. See the [install guide](https://github.com/enkyuan/alloy/blob/main/apps/docs/content/install.mdx)
for source-checkout and compatibility details.

## First run: no key

Save this as `quickstart.mts`, then run `npm exec -- tsx quickstart.mts` or
`bun quickstart.mts`.

<!-- docs-test:readme-no-key:typescript:start -->
```ts
import { AgentBuilder } from "@irogane/kaji";
import { MockProvider } from "@irogane/kaji/testing";

const runtime = new AgentBuilder().provider(new MockProvider({ reply: "hello" })).build();
const result = await runtime.turn("Say hello.");
console.log(result.text);
```
<!-- docs-test:readme-no-key:typescript:end -->

This proves the runtime without credentials or enabled tools.

## First live agent

Set `OPENAI_API_KEY`, then give tools an explicit risk, caller identity, and
deadline. This example uses a read-only tool:

```bash
export OPENAI_API_KEY=...
```

<!-- docs-test:readme-openai:typescript:start -->
```ts
import { AgentBuilder, deadlineAfter, functionTool, openai } from "@irogane/kaji";
import { z } from "zod";

const getWeather = functionTool(
  {
    name: "get_weather",
    description: "Look up weather for a city.",
    parameters: z.object({ city: z.string() }),
    risk: "read",
  },
  async ({ city }, context) => ({ city, principal: context.principalId, tempF: 68 }),
);

const runtime = new AgentBuilder().provider(openai()).tool(getWeather).build();
const result = await runtime.turn("Weather in Seattle?", {
  context: {
    principalId: "weather-app",
    deadlineAtMs: deadlineAfter(30_000),
  },
});
console.log(result.text);
```
<!-- docs-test:readme-openai:typescript:end -->

## Next steps

- [Getting started](https://github.com/enkyuan/alloy/blob/main/apps/docs/content/getting-started.mdx)
- [Tool policy and approval](https://github.com/enkyuan/alloy/blob/main/apps/docs/content/concepts/tool-registry.mdx)
- [Lifecycle and data handling](https://github.com/enkyuan/alloy/blob/main/apps/docs/content/concepts/lifecycle.mdx)
- [Providers](https://github.com/enkyuan/alloy/blob/main/apps/docs/content/concepts/providers.mdx)
- [Integrations](https://github.com/enkyuan/alloy/blob/main/apps/docs/content/integrations/index.mdx)

## License

Kaji is source-available under the
[Functional Source License 1.1, ALv2 Future License](https://spdx.org/licenses/FSL-1.1-ALv2.html).
It permits internal commercial use, modification, and redistribution for permitted purposes,
but excludes competing commercial products and services; each version becomes Apache-2.0 after
two years. FSL is not an OSI-approved open-source license.
