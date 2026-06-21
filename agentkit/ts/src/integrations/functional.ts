/**
 * Function-level `FunctionTool` for one-off tools without an `Integration` subclass.
 * Mirrors `agentkit.runtime.integrations.functional`.
 *
 * The class-based `Integration` path remains the right shape for namespaced,
 * multi-tool bundles. This module adds a lightweight alternative for the common
 * case of "I have one async function; expose it as a tool."
 *
 *   const getWeather = FunctionTool(
 *     { description: "Return weather.", parameters: z.object({ city: z.string() }) },
 *     async ({ city }) => ({ city, tempF: 68 }),
 *   );
 *
 *   const runtime = new AgentBuilder().provider(p).tool(getWeather).build();
 */
import { z } from "zod";

import {
  providerSafeToolName,
  type ToolHandler,
  type ToolMeta,
  type ToolRegistry,
  type ToolSpec,
  toolParametersToJSONSchema,
} from "../tools/registry";

type ArgsOf<P> = P extends z.ZodType ? z.infer<P> : Record<string, unknown>;

/** Signature accepted by `FunctionTool`. The handler receives parsed arguments
 * (typed via Zod inference) directly — no `ctx` parameter. The return value is
 * normalised to an object (primitives become `{ result: <value> }`) before
 * being emitted as the tool result. */
export type FunctionToolHandler<P> = (args: ArgsOf<P>) => Promise<unknown>;

/** Tool packaged with its spec + adapter handler, registrable like an Integration. */
export class BoundTool {
  constructor(
    readonly spec: ToolSpec,
    readonly handler: ToolHandler,
    readonly namespace: string = "fn",
  ) {}

  register(registry: ToolRegistry): void {
    const catalogName = `${this.namespace}.${this.spec.name}`;
    registry.register(
      { ...this.spec, name: providerSafeToolName(catalogName), catalogName },
      this.handler,
    );
  }
}

export interface FunctionToolMeta<P> extends Omit<ToolMeta, "parameters"> {
  /** Tool name. Defaults to the handler's `.name` if available. */
  name?: string;
  /** Zod schema or JSON Schema describing the arguments. */
  parameters: P;
  /** Namespace prefix (defaults to "fn"). */
  namespace?: string;
}

/**
 * Build a single tool from a meta + handler pair. The handler receives parsed
 * arguments (typed via Zod inference) directly.
 */
export function FunctionTool<P extends z.ZodType | Record<string, unknown>>(
  meta: FunctionToolMeta<P>,
  handler: FunctionToolHandler<P>,
): BoundTool {
  const name = meta.name ?? handler.name ?? "tool";
  const spec: ToolSpec = {
    name,
    description: meta.description,
    parameters: toolParametersToJSONSchema(meta.parameters as never),
    ...(meta.risk !== undefined ? { risk: meta.risk } : {}),
    ...(meta.tags !== undefined ? { tags: meta.tags } : {}),
    ...(meta.enabled !== undefined ? { enabled: meta.enabled } : {}),
  };

  const adapter: ToolHandler = async (_ctx, args) => {
    const result = await handler(args as ArgsOf<P>);
    // ToolHandler must return an object; wrap primitives/arrays.
    if (result !== null && typeof result === "object" && !Array.isArray(result)) {
      return result as Record<string, unknown>;
    }
    return { result };
  };
  return new BoundTool(spec, adapter, meta.namespace ?? "fn");
}
