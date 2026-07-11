/**
 * Integration abstract base class: namespace-scoped tool bundle.
 * Mirrors `kaji.runtime.integrations.base.Integration`.
 */
import type { ToolHandler, ToolSpec } from "@/tools/registry";
import {
  TOOL_META,
  TOOL_ARGUMENT_VALIDATOR,
  ToolRegistry,
  providerSafeToolName,
  setToolArgumentValidator,
  toolArgumentValidator,
  toolParametersToJSONSchema,
} from "@/tools/registry";
import type { TaggedHandler, ToolMeta } from "@/tools/registry";
import {
  cloneToolExecutionArguments,
  consumeValidationReceipt,
  validateIsolatedToolArguments,
} from "@/tools/validation";

/**
 * Mark a handler function as a tool with the given metadata.
 *
 * Usage on an Integration subclass:
 *
 *   readonly retrieveCharge = tool(
 *     { description: "Retrieve a charge", parameters: {...}, risk: "read" },
 *     async (ctx, args) => { ... },
 *   );
 *
 * `Integration.tools()` will auto-discover all own properties that are
 * handlers marked this way.
 */
export function tool(meta: ToolMeta, handler: ToolHandler): ToolHandler {
  const argumentValidator = toolArgumentValidator(meta.parameters);
  const adapter: ToolHandler = async (args, context) => {
    let executionArgs = args;
    if (
      argumentValidator !== undefined &&
      !consumeValidationReceipt(context, args, argumentValidator)
    ) {
      const toolName = handler.name || "tool";
      executionArgs = cloneToolExecutionArguments(toolName, args);
      await validateIsolatedToolArguments(toolName, executionArgs, argumentValidator);
    }
    return handler(executionArgs, context);
  };
  (adapter as TaggedHandler)[TOOL_META] = meta;
  if (argumentValidator !== undefined) {
    Object.defineProperty(adapter, TOOL_ARGUMENT_VALIDATOR, { value: argumentValidator });
  }
  return adapter;
}

export abstract class Integration {
  /** The namespace prefix applied to all tools in this integration. */
  abstract readonly namespace: string;

  /** Return all [spec, handler] pairs for this integration.
   *
   * The default implementation scans own instance properties for handlers
   * marked with `tool(meta, fn)`. Override to return tuples manually.
   */
  tools(): [ToolSpec, ToolHandler][] {
    const result: [ToolSpec, ToolHandler][] = [];
    for (const key of Object.getOwnPropertyNames(this)) {
      if (key.startsWith("_")) continue;
      const value = (this as Record<string, unknown>)[key];
      if (typeof value !== "function") continue;
      const meta = (value as TaggedHandler)[TOOL_META];
      if (meta) {
        const spec = setToolArgumentValidator<ToolSpec>(
          {
            name: key,
            description: meta.description,
            parameters: toolParametersToJSONSchema(meta.parameters),
            risk: meta.risk,
            ...(meta.tags !== undefined ? { tags: meta.tags } : {}),
            ...(meta.enabled !== undefined ? { enabled: meta.enabled } : {}),
          },
          (value as TaggedHandler)[TOOL_ARGUMENT_VALIDATOR],
        );
        result.push([spec, value as ToolHandler]);
      }
    }
    return result;
  }

  /** Register all tools into the given registry, namespace-prefixed. */
  register(registry: ToolRegistry): void {
    for (const [spec, handler] of this.tools()) {
      const catalogName = `${this.namespace}.${spec.name}`;
      registry.register(
        setToolArgumentValidator(
          {
            ...spec,
            name: providerSafeToolName(catalogName, { onMutate: warnOnSanitize }),
            catalogName,
          },
          spec[TOOL_ARGUMENT_VALIDATOR],
        ),
        handler,
      );
    }
  }
}

function warnOnSanitize(original: string, sanitized: string): void {
  console.warn(
    `[kaji] tool name ${JSON.stringify(original)} sanitized to ${JSON.stringify(sanitized)} for provider compatibility`,
  );
}
