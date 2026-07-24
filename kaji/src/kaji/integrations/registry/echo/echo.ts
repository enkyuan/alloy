// This is YOUR echo integration. Edit it.
// Common customizations:
//   1. Trim the tools array to just what your agent needs
//   2. Tighten Zod schemas — make fields required if your agent should never miss them
//   3. Add helper tools your agent wants but the API doesn't have natively
// Updates: re-run `kaji add echo` to diff against the latest version we ship.

import { functionTool, Integration } from "kaji-sdk";
import * as z from "zod";

const messageParameters = z.strictObject({ message: z.string() });

export const say = functionTool(
  {
    name: "say",
    namespace: "echo",
    description: "Return the input string unchanged.",
    parameters: messageParameters,
    risk: "read",
    parallel_safe: false,
  },
  async ({ message }) => ({ message }),
);

export const shout = functionTool(
  {
    name: "shout",
    namespace: "echo",
    description: "Return the input string uppercased.",
    parameters: messageParameters,
    risk: "read",
    parallel_safe: false,
  },
  async ({ message }) => ({ message: message.toUpperCase() }),
);

/** Side-effect-free metadata source for registry ABI verification. */
export const tools = Object.freeze([say, shout] as const);

export class EchoIntegration extends Integration {
  readonly namespace = "echo";

  override tools() {
    return tools.map(
      (bound) => [bound.spec, bound.handler] as [typeof bound.spec, typeof bound.handler],
    );
  }
}

/** Construct Echo without executing a tool or reading runtime state. */
export function inspectIntegration(): EchoIntegration {
  return new EchoIntegration();
}
