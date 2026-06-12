/**
 * Integration abstract base class: namespace-scoped tool bundle.
 * Mirrors `agentkit.runtime.integrations.base.Integration`.
 */
import type { JSONSchema, ToolHandler, ToolSpec } from "../tools/registry";
import { ToolRegistry } from "../tools/registry";

interface ToolMeta {
  description: string;
  parameters: JSONSchema;
  risk?: ToolSpec["risk"];
  tags?: string[];
  enabled?: boolean;
}

const TOOL_META = Symbol("tool_meta");

type TaggedHandler = ToolHandler & { [TOOL_META]?: ToolMeta };

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
  (handler as TaggedHandler)[TOOL_META] = meta;
  return handler;
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
        const spec: ToolSpec = {
          name: key,
          description: meta.description,
          parameters: meta.parameters,
          ...(meta.risk !== undefined ? { risk: meta.risk } : {}),
          ...(meta.tags !== undefined ? { tags: meta.tags } : {}),
          ...(meta.enabled !== undefined ? { enabled: meta.enabled } : {}),
        };
        result.push([spec, value as ToolHandler]);
      }
    }
    return result;
  }

  /** Register all tools into the given registry, namespace-prefixed. */
  register(registry: ToolRegistry): void {
    for (const [spec, handler] of this.tools()) {
      registry.register({ ...spec, name: `${this.namespace}.${spec.name}` }, handler);
    }
  }
}
