/**
 * Echo integration. The simplest possible Kaji integration.
 *
 * Two pure functions, no auth, no network. Installed by `kaji add echo`.
 */
import { functionTool } from "@kaji/sdk";
import { z } from "zod";

export const say = functionTool(
  {
    description: "Return the input string unchanged.",
    parameters: z.object({ message: z.string() }),
    risk: "read",
  },
  async ({ message }) => ({ message }),
);

export const shout = functionTool(
  {
    description: "Return the input string uppercased.",
    parameters: z.object({ message: z.string() }),
    risk: "read",
  },
  async ({ message }) => ({ message: message.toUpperCase() }),
);
