/**
 * Integration abstract base class: namespace-scoped tool bundle.
 * Mirrors `agentkit.runtime.integrations.base.Integration`.
 */
import type { ToolSpec, ToolHandler } from "../tools/registry";
import { ToolRegistry } from "../tools/registry";

export abstract class Integration {
  /** The namespace prefix applied to all tools in this integration. */
  abstract readonly namespace: string;

  /** Return all [spec, handler] pairs for this integration. */
  abstract tools(): [ToolSpec, ToolHandler][];

  /** Register all tools into the given registry, namespace-prefixed. */
  register(registry: ToolRegistry): void {
    for (const [spec, handler] of this.tools()) {
      registry.register({ ...spec, name: `${this.namespace}.${spec.name}` }, handler);
    }
  }
}
