// This is YOUR echo integration. Edit it.
// Common customizations:
//   1. Trim the tools array to just what your agent needs
//   2. Tighten Zod schemas — make fields required if your agent should never miss them
//   3. Add helper tools your agent wants but the API doesn't have natively
// Updates: re-run `kaji add echo` to diff against the latest version we ship.

import { functionTool } from "@kaji/sdk";
import { z } from "zod";

export const say = functionTool(
  {
    name: "say",
    namespace: "echo",
    description: "Return the input string unchanged.",
    parameters: z.object({ message: z.string() }),
    risk: "read",
  },
  async ({ message }) => ({ message }),
);

export const shout = functionTool(
  {
    name: "shout",
    namespace: "echo",
    description: "Return the input string uppercased.",
    parameters: z.object({ message: z.string() }),
    risk: "read",
  },
  async ({ message }) => ({ message: message.toUpperCase() }),
);
