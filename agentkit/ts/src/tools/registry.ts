/**
 * Tool registry for LLM-callable functions, mirroring
 * `agentkit.runtime.tools.registry`. A process-level registry holds specs and
 * handlers; tools run with a `ToolContext` and need no infra by default.
 */
import { z } from "zod";

/** A JSON Schema object describing a tool's parameters. */
export type JSONSchema = Record<string, unknown>;

/** Definition of a tool exposed to the LLM. */
export interface ToolSpec {
  name: string;
  description: string;
  parameters: JSONSchema;
  tags?: string[];
  enabled?: boolean;
}

/**
 * Execution context for registered tools. `db` is optional: tools that don't
 * touch a database (the default for an embedded SDK) receive `undefined`. A
 * host that needs persistence injects its own handle here.
 */
export interface ToolContext {
  userId: string;
  db?: unknown;
}

/** A tool handler: receives the context and validated args, returns a result. */
export type ToolHandler = (
  ctx: ToolContext,
  args: Record<string, unknown>,
) => Promise<Record<string, unknown>>;

const toolSpecs = new Map<string, ToolSpec>();
const toolHandlers = new Map<string, ToolHandler>();

/** Register a tool handler under its spec's name. Throws on a duplicate name. */
export function registerTool(spec: ToolSpec, handler: ToolHandler): void {
  if (toolSpecs.has(spec.name)) {
    throw new Error(`Tool already registered: ${spec.name}`);
  }
  toolSpecs.set(spec.name, spec);
  toolHandlers.set(spec.name, handler);
}

export interface ListToolSpecsOptions {
  tags?: string[];
  enabledOnly?: boolean;
}

function filterSpecs(all: ToolSpec[], options: ListToolSpecsOptions): ToolSpec[] {
  const { tags, enabledOnly = true } = options;
  let specs = all;
  if (enabledOnly) specs = specs.filter((s) => s.enabled !== false);
  if (tags && tags.length > 0) {
    const tagSet = new Set(tags);
    specs = specs.filter((s) => s.tags?.some((t) => tagSet.has(t)));
  }
  return specs;
}

/** Return registered tool specs, optionally filtered by tags or enabled status. */
export function listToolSpecs(options: ListToolSpecsOptions = {}): ToolSpec[] {
  return filterSpecs([...toolSpecs.values()], options);
}

/**
 * Build a tool spec from a Zod schema, reducing it to the
 * `{ type, properties, required }` shape the LLM tool API expects (mirrors the
 * Python `tool_spec_from_model`).
 */
export function toolSpecFromSchema(name: string, description: string, schema: z.ZodType): ToolSpec {
  const json = z.toJSONSchema(schema) as {
    properties?: Record<string, unknown>;
    required?: string[];
  };
  return {
    name,
    description,
    parameters: {
      type: "object",
      properties: json.properties ?? {},
      required: json.required ?? [],
    },
  };
}

/** Execute a registered tool call for a given user. Rejects on an unknown tool. */
export async function executeTool(
  userId: string,
  toolName: string,
  toolArgs: Record<string, unknown>,
  db?: unknown,
): Promise<Record<string, unknown>> {
  const handler = toolHandlers.get(toolName);
  if (handler === undefined) {
    throw new Error(`Unknown tool: ${toolName}`);
  }
  return handler({ userId, db }, toolArgs);
}

/** Clear the registry. Primarily for tests. */
export function clearTools(): void {
  toolSpecs.clear();
  toolHandlers.clear();
}

/**
 * Scoped tool registry for per-agent or per-tenant isolation.
 *
 * The module-level `registerTool`, `listToolSpecs`, and `executeTool`
 * functions share a single global registry suitable for simple setups.
 * Use `ToolRegistry` when you need multiple isolated registries.
 *
 * @example
 * ```ts
 * const registry = new ToolRegistry();
 * registry.register({ name: "ping", description: "...", parameters: {} }, async (_ctx, _args) => ({ pong: true }));
 * const runtime = new AgentRuntime({ ..., tools: registry.listSpecs() });
 * ```
 */
export class ToolRegistry {
  private readonly specs = new Map<string, ToolSpec>();
  private readonly handlers = new Map<string, ToolHandler>();

  register(spec: ToolSpec, handler: ToolHandler): this {
    if (this.specs.has(spec.name)) {
      throw new Error(`Tool already registered: ${spec.name}`);
    }
    this.specs.set(spec.name, spec);
    this.handlers.set(spec.name, handler);
    return this;
  }

  listSpecs(options: ListToolSpecsOptions = {}): ToolSpec[] {
    return filterSpecs([...this.specs.values()], options);
  }

  async execute(
    userId: string,
    toolName: string,
    toolArgs: Record<string, unknown>,
    db?: unknown,
  ): Promise<Record<string, unknown>> {
    const handler = this.handlers.get(toolName);
    if (handler === undefined) {
      throw new Error(`Unknown tool: ${toolName}`);
    }
    return handler({ userId, db }, toolArgs);
  }

  clear(): void {
    this.specs.clear();
    this.handlers.clear();
  }
}
