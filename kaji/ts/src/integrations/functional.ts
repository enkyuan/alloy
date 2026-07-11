/**
 * Function-level `functionTool` for one-off tools without an `Integration` subclass.
 * Mirrors `kaji.runtime.integrations.functional`.
 *
 * The class-based `Integration` path remains the right shape for namespaced,
 * multi-tool bundles. This module adds a lightweight alternative for the common
 * case of "I have one async function; expose it as a tool."
 *
 *   const getWeather = functionTool(
 *     { description: "Return weather.", parameters: z.object({ city: z.string() }) },
 *     async ({ city }) => ({ city, tempF: 68 }),
 *   );
 *
 *   const runtime = new AgentBuilder().provider(p).tool(getWeather).build();
 */
import * as z from "zod";

import {
  TOOL_ARGUMENT_VALIDATOR,
  providerSafeToolName,
  setToolArgumentValidator,
  toolArgumentValidator,
  type ToolHandler,
  type ToolMeta,
  type ToolRegistry,
  type ToolSpec,
  toolParametersToJSONSchema,
} from "@/tools/registry";
import type { ToolExecutionContext } from "@/runtime/context";
import {
  cloneToolExecutionArguments,
  consumeValidationReceipt,
  validateIsolatedToolArguments,
} from "@/tools/validation";

type ArgsOf<P> = P extends z.ZodType ? z.input<P> : Record<string, unknown>;

/** Signature accepted by `functionTool`. Zod validates the provider arguments,
 * but its defaults, coercions, and transformations are deliberately discarded.
 * The second context parameter may be ignored and matches registry handlers. */
export type FunctionToolHandler<P> = (
  args: ArgsOf<P>,
  context: ToolExecutionContext,
) => Promise<unknown>;

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
      setToolArgumentValidator(
        {
          ...this.spec,
          name: providerSafeToolName(catalogName, { onMutate: warnOnSanitize }),
          catalogName,
        },
        this.spec[TOOL_ARGUMENT_VALIDATOR],
      ),
      this.handler,
    );
  }
}

function warnOnSanitize(original: string, sanitized: string): void {
  console.warn(
    `[kaji] tool name ${JSON.stringify(original)} sanitized to ${JSON.stringify(sanitized)} for provider compatibility`,
  );
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
 * Build a single tool from a meta + handler pair. The handler receives the
 * a byte-equivalent isolated clone after validation succeeds.
 */
export function functionTool<P extends z.ZodType | Record<string, unknown>>(
  meta: FunctionToolMeta<P>,
  handler: FunctionToolHandler<P>,
): BoundTool {
  const name = meta.name ?? handler.name ?? "tool";
  const argumentValidator = toolArgumentValidator(meta.parameters as never);
  const spec = setToolArgumentValidator<ToolSpec>(
    {
      name,
      description: meta.description,
      parameters: toolParametersToJSONSchema(meta.parameters as never),
      risk: meta.risk,
      ...(meta.tags !== undefined ? { tags: meta.tags } : {}),
      ...(meta.enabled !== undefined ? { enabled: meta.enabled } : {}),
      ...(meta.parallel_safe !== undefined ? { parallel_safe: meta.parallel_safe } : {}),
      ...(meta.timeout_ms !== undefined ? { timeout_ms: meta.timeout_ms } : {}),
    },
    argumentValidator,
  );

  const adapter: ToolHandler = async (args, context) => {
    let executionArgs = args;
    if (
      argumentValidator !== undefined &&
      !consumeValidationReceipt(context, args, argumentValidator)
    ) {
      executionArgs = cloneToolExecutionArguments(name, args);
      await validateIsolatedToolArguments(name, executionArgs, argumentValidator);
    }
    const result = await handler(executionArgs as ArgsOf<P>, context);
    // ToolHandler must return an object; wrap primitives/arrays.
    if (result !== null && typeof result === "object" && !Array.isArray(result)) {
      return result as Record<string, unknown>;
    }
    return { result };
  };
  return new BoundTool(spec, adapter, meta.namespace ?? "fn");
}
