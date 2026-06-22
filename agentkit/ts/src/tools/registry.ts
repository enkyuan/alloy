/**
 * Tool registry for LLM-callable functions, mirroring
 * `agentkit.runtime.tools.registry`. A process-level registry holds specs and
 * handlers; tools run with a `ToolContext` and need no infra by default.
 */
import { z } from "zod";

/** A JSON Schema object describing a tool's parameters. */
export type JSONSchema = Record<string, unknown>;

/** Parameter schema accepted at tool authoring boundaries. */
export type ToolParameters = JSONSchema | z.ZodType;

/** Risk level for a tool, used by ToolPolicy to gate execution. */
export type ToolRisk = "read" | "write" | "external_effect" | "financial" | "destructive" | "admin";

/** Definition of a tool exposed to the LLM. */
export interface ToolSpec {
  name: string;
  description: string;
  parameters: JSONSchema;
  catalogName?: string;
  tags?: string[];
  enabled?: boolean;
  /** Risk classification for policy enforcement and approval routing.
   * undefined = unclassified, treated as "read" by default policies. */
  risk?: ToolRisk;
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

/** Metadata attached to a handler by `tool(meta, fn)`. */
export interface ToolMeta {
  description: string;
  parameters: ToolParameters;
  risk?: ToolRisk;
  tags?: string[];
  enabled?: boolean;
}

/** Symbol key used to tag a handler with its ToolMeta. */
export const TOOL_META = Symbol("tool_meta");

/** A ToolHandler that may carry attached ToolMeta (set by `tool()`). */
export type TaggedHandler = ToolHandler & { [TOOL_META]?: ToolMeta };

export function providerSafeToolName(name: string): string {
  return name.replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "") || "tool";
}

function isZodSchema(parameters: ToolParameters): parameters is z.ZodType {
  return typeof parameters === "object" && parameters !== null && "_zod" in parameters;
}

function schemaParameters(schema: z.ZodType): JSONSchema {
  const json = z.toJSONSchema(schema) as {
    properties?: Record<string, unknown>;
    required?: string[];
  };
  return {
    type: "object",
    properties: json.properties ?? {},
    required: json.required ?? [],
  };
}

export function toolParametersToJSONSchema(parameters: ToolParameters): JSONSchema {
  return isZodSchema(parameters) ? schemaParameters(parameters) : parameters;
}

function specFromTagged(name: string, handler: ToolHandler): ToolSpec {
  const meta = (handler as TaggedHandler)[TOOL_META];
  if (!meta) {
    throw new Error(
      `handler for "${name}" has no TOOL_META — wrap it with tool(meta, fn) before registering by name`,
    );
  }
  return {
    name,
    description: meta.description,
    parameters: toolParametersToJSONSchema(meta.parameters),
    ...(meta.risk !== undefined ? { risk: meta.risk } : {}),
    ...(meta.tags !== undefined ? { tags: meta.tags } : {}),
    ...(meta.enabled !== undefined ? { enabled: meta.enabled } : {}),
  };
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

/**
 * Build a tool spec from a Zod schema, reducing it to the
 * `{ type, properties, required }` shape the LLM tool API expects (mirrors the
 * Python `tool_spec_from_model`).
 */
export function toolSpecFromSchema(name: string, description: string, schema: z.ZodType): ToolSpec {
  return {
    name,
    description,
    parameters: schemaParameters(schema),
  };
}

/**
 * Scoped tool registry for per-agent or per-tenant isolation.
 *
 * The module-level `registerTool`, `listToolSpecs`, and `executeTool`
 * functions delegate to a single default `ToolRegistry` instance, which is
 * sufficient for simple setups. Construct your own `ToolRegistry` when you
 * need multiple isolated registries.
 *
 * @example
 * ```ts
 * const registry = new ToolRegistry();
 * registry.register({ name: "ping", description: "...", parameters: {} }, async (_ctx, _args) => ({ pong: true }));
 * const planner = new ToolPlanner({
 *   executor: (name, args) => registry.execute("user-1", name, args),
 *   specs: new Map(registry.listSpecs().map((s) => [s.name, s])),
 * });
 * const runtime = new AgentRuntime({ ..., tools: registry.listSpecs(), planner });
 * ```
 */
export class ToolRegistry {
  private readonly specs = new Map<string, ToolSpec>();
  private readonly handlers = new Map<string, ToolHandler>();

  register(spec: ToolSpec, handler: ToolHandler): this;
  register(name: string, handler: ToolHandler): this;
  register(specOrName: ToolSpec | string, handler: ToolHandler): this {
    const spec = typeof specOrName === "string" ? specFromTagged(specOrName, handler) : specOrName;
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
      throw new UnknownToolError(toolName);
    }
    return handler({ userId, db }, toolArgs);
  }

  clear(): void {
    this.specs.clear();
    this.handlers.clear();
  }
}

/** Thrown when a tool is requested by name but not registered. */
export class UnknownToolError extends Error {
  constructor(public readonly toolName: string) {
    super(`Unknown tool: ${toolName}`);
    this.name = "UnknownToolError";
  }
}

/** Process-default registry that the module-level functions delegate to. */
const defaultRegistry = new ToolRegistry();

/** Register a tool handler on the process-default registry. Accepts either a
 * full ToolSpec + handler, or a pre-tagged handler (from `tool(meta, fn)`)
 * with just a name string. */
export function registerTool(spec: ToolSpec, handler: ToolHandler): void;
export function registerTool(name: string, handler: ToolHandler): void;
export function registerTool(specOrName: ToolSpec | string, handler: ToolHandler): void {
  const spec = typeof specOrName === "string" ? specFromTagged(specOrName, handler) : specOrName;
  defaultRegistry.register(spec, handler);
}

/** Return registered tool specs from the process-default registry. */
export function listToolSpecs(options: ListToolSpecsOptions = {}): ToolSpec[] {
  return defaultRegistry.listSpecs(options);
}

/** Execute a registered tool call from the process-default registry. */
export async function executeTool(
  userId: string,
  toolName: string,
  toolArgs: Record<string, unknown>,
  db?: unknown,
): Promise<Record<string, unknown>> {
  return defaultRegistry.execute(userId, toolName, toolArgs, db);
}

/** Clear the process-default registry. Primarily for tests. */
export function clearTools(): void {
  defaultRegistry.clear();
}
