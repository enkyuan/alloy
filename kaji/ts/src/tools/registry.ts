/**
 * Tool registry for LLM-callable functions, mirroring
 * `kaji.runtime.tools.registry`. A process-level registry holds specs and
 * handlers; tools run with a `ToolContext` and need no infra by default.
 */
import * as z from "zod";

import {
  TOOL_ARGUMENT_VALIDATOR,
  ToolArgumentValidationError,
  ToolSchemaValidator,
  addToolSchema,
  assertToolArgumentsJsonSafe,
  attachValidationReceipt,
  claimValidationReceipt,
  clearToolSchemas,
  cloneToolExecutionArguments,
  consumeScopedValidationReceipt,
  revokeValidationReceipt,
  snapshotToolSchemaJson,
  validateToolArgumentsForExecution,
  type ToolArgumentValidator,
} from "@/tools/validation";

export { TOOL_ARGUMENT_VALIDATOR } from "@/tools/validation";

/** A JSON Schema object describing a tool's parameters. */
export type JSONSchema = Readonly<Record<string, unknown>>;

/** Parameter schema accepted at tool authoring boundaries. */
export type ToolParameters = JSONSchema | z.ZodType;

/** Risk level for a tool, used by ToolPolicy to gate execution. */
export type ToolRisk = "read" | "write" | "external_effect" | "financial" | "destructive" | "admin";

/** Definition of a tool exposed to the LLM. */
export interface ToolSpec {
  readonly name: string;
  readonly description: string;
  readonly parameters: JSONSchema;
  readonly catalogName?: string;
  readonly tags?: readonly string[];
  readonly enabled?: boolean;
  /** Risk classification for policy enforcement and approval routing.
   * undefined = unclassified, treated as "read" by default policies. */
  readonly risk?: ToolRisk;
  readonly [TOOL_ARGUMENT_VALIDATOR]?: ToolArgumentValidator;
}

export function setToolArgumentValidator<T extends ToolSpec>(
  spec: T,
  validator: ToolArgumentValidator | undefined,
): T {
  if (validator !== undefined) {
    Object.defineProperty(spec, TOOL_ARGUMENT_VALIDATOR, { value: validator });
  }
  return spec;
}

export function snapshotToolSpec(spec: ToolSpec): ToolSpec {
  const snapshot = setToolArgumentValidator<ToolSpec>(
    {
      name: spec.name,
      description: spec.description,
      parameters: snapshotToolSchemaJson(spec.name, spec.parameters),
      ...(spec.catalogName !== undefined ? { catalogName: spec.catalogName } : {}),
      ...(spec.tags !== undefined ? { tags: Object.freeze([...spec.tags]) } : {}),
      ...(spec.enabled !== undefined ? { enabled: spec.enabled } : {}),
      ...(spec.risk !== undefined ? { risk: spec.risk } : {}),
    },
    spec[TOOL_ARGUMENT_VALIDATOR],
  );
  return Object.freeze(snapshot);
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
export type TaggedHandler = ToolHandler & {
  [TOOL_META]?: ToolMeta;
  [TOOL_ARGUMENT_VALIDATOR]?: ToolArgumentValidator;
};

export interface ProviderSafeToolNameOptions {
  /**
   * Called once with `(original, sanitized)` when the name was changed.
   * Not invoked when the input is already provider-safe. With no callback,
   * the sanitizer has no side effects (no log, no global state), so
   * registering many tools at startup stays quiet by default.
   */
  onMutate?: (original: string, sanitized: string) => void;
}

export function providerSafeToolName(name: string, opts: ProviderSafeToolNameOptions = {}): string {
  const safe = name.replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "") || "tool";
  if (safe !== name && opts.onMutate) {
    opts.onMutate(name, safe);
  }
  return safe;
}

export function isZodSchema(parameters: ToolParameters): parameters is z.ZodType {
  return typeof parameters === "object" && parameters !== null && "_zod" in parameters;
}

export function toolArgumentValidator(
  parameters: ToolParameters,
): ToolArgumentValidator | undefined {
  if (!isZodSchema(parameters)) return undefined;
  const parseAsync = parameters.parseAsync.bind(parameters);
  return async (toolName, args) => {
    assertToolArgumentsJsonSafe(toolName, args);
    try {
      await parseAsync(args);
    } catch (error) {
      if (error instanceof z.ZodError && error.issues.length > 0) {
        const issue = [...error.issues].sort((left, right) => {
          const leftPath = left.path.map(String).join("/");
          const rightPath = right.path.map(String).join("/");
          if (leftPath !== rightPath) return leftPath < rightPath ? -1 : 1;
          return left.code < right.code ? -1 : left.code > right.code ? 1 : 0;
        })[0]!;
        throw ToolArgumentValidationError.fromValidationIssue(toolName, issue.path, issue.code);
      }
      throw ToolArgumentValidationError.fromValidationIssue(toolName, [], "custom");
    }
  };
}

function schemaParameters(schema: z.ZodType): JSONSchema {
  return z.toJSONSchema(schema, { io: "input" }) as JSONSchema;
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
  return setToolArgumentValidator(
    {
      name,
      description: meta.description,
      parameters: toolParametersToJSONSchema(meta.parameters),
      ...(meta.risk !== undefined ? { risk: meta.risk } : {}),
      ...(meta.tags !== undefined ? { tags: meta.tags } : {}),
      ...(meta.enabled !== undefined ? { enabled: meta.enabled } : {}),
    },
    (handler as TaggedHandler)[TOOL_ARGUMENT_VALIDATOR],
  );
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
 * Build a tool spec from a Zod schema while preserving its complete validation
 * schema, including nested constraints and references.
 */
export function toolSpecFromSchema(name: string, description: string, schema: z.ZodType): ToolSpec {
  return setToolArgumentValidator(
    {
      name,
      description,
      parameters: schemaParameters(schema),
    },
    toolArgumentValidator(schema),
  );
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
  private readonly schemaValidator: ToolSchemaValidator;

  constructor(schemaValidator: ToolSchemaValidator = new ToolSchemaValidator()) {
    this.schemaValidator = schemaValidator;
  }

  register(spec: ToolSpec, handler: ToolHandler): this;
  register(name: string, handler: ToolHandler): this;
  register(specOrName: ToolSpec | string, handler: ToolHandler): this {
    const sourceSpec =
      typeof specOrName === "string" ? specFromTagged(specOrName, handler) : specOrName;
    if (this.specs.has(sourceSpec.name)) {
      throw new Error(`Tool already registered: ${sourceSpec.name}`);
    }
    const spec = snapshotToolSpec(sourceSpec);
    addToolSchema(this.schemaValidator, spec.name, spec);
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
    let executionArgs = toolArgs;
    let receipt = consumeScopedValidationReceipt(this.schemaValidator, toolName, executionArgs);
    if (receipt === undefined) {
      executionArgs = cloneToolExecutionArguments(toolName, toolArgs);
      receipt = await validateToolArgumentsForExecution(
        this.schemaValidator,
        toolName,
        executionArgs,
      );
      if (
        receipt !== undefined &&
        !claimValidationReceipt(this.schemaValidator, receipt, toolName, executionArgs)
      ) {
        throw new Error(`Tool validation receipt could not be claimed: ${toolName}`);
      }
    }
    const context = { userId, db };
    if (receipt !== undefined) attachValidationReceipt(context, receipt);
    try {
      return await handler(context, executionArgs);
    } finally {
      if (receipt !== undefined) revokeValidationReceipt(receipt);
    }
  }

  clear(): void {
    this.specs.clear();
    this.handlers.clear();
    clearToolSchemas(this.schemaValidator);
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
