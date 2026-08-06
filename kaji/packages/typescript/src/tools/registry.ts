/**
 * Tool registry for LLM-callable functions, mirroring
 * `kaji.runtime.tools.registry`. A process-level registry holds specs and
 * handlers; tools run with a `ToolExecutionContext` and need no infra by default.
 */
import * as z from "zod";

import { snapshotToolExecutionContext, type ToolExecutionContext } from "@/runtime/context";
import {
  TOOL_ARGUMENT_VALIDATOR,
  ToolArgumentValidationError,
  ToolSchemaValidationError,
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
export type ToolRisk = "read" | "write" | "external_effect" | "destructive" | "admin";
const TOOL_RISKS = new Set<ToolRisk>(["read", "write", "external_effect", "destructive", "admin"]);

export class UnclassifiedToolRiskError extends Error {
  readonly code = "UNCLASSIFIED_TOOL_RISK" as const;
  readonly retryable = false;
  readonly outcome = "not_started" as const;

  constructor(readonly toolName: string) {
    super("Enabled tools require an explicit risk classification");
    this.name = "UnclassifiedToolRiskError";
  }
}

/** Definition of a tool exposed to the LLM. */
export interface ToolSpec {
  readonly name: string;
  readonly description: string;
  readonly parameters: JSONSchema;
  readonly catalogName?: string;
  readonly tags?: readonly string[];
  readonly enabled?: boolean;
  /** Risk classification for policy enforcement and approval routing. */
  readonly risk: ToolRisk;
  /** Explicit opt-in for bounded overlap with adjacent parallel-safe tools. */
  readonly parallel_safe?: boolean;
  /** Per-tool execution deadline. Must be a positive integer when present. */
  readonly timeout_ms?: number;
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
  assertToolRisk(spec);
  assertToolExecutionSettings(spec);
  const snapshot = setToolArgumentValidator<ToolSpec>(
    {
      name: spec.name,
      description: spec.description,
      parameters: snapshotToolSchemaJson(spec.name, spec.parameters),
      ...(spec.catalogName !== undefined ? { catalogName: spec.catalogName } : {}),
      ...(spec.tags !== undefined ? { tags: Object.freeze([...spec.tags]) } : {}),
      ...(spec.enabled !== undefined ? { enabled: spec.enabled } : {}),
      risk: spec.risk,
      ...(spec.parallel_safe !== undefined ? { parallel_safe: spec.parallel_safe } : {}),
      ...(spec.timeout_ms !== undefined ? { timeout_ms: spec.timeout_ms } : {}),
    },
    spec[TOOL_ARGUMENT_VALIDATOR],
  );
  return Object.freeze(snapshot);
}

function assertToolExecutionSettings(spec: ToolSpec): void {
  if (spec.parallel_safe !== undefined && typeof spec.parallel_safe !== "boolean") {
    throw new TypeError(`Tool ${spec.name} parallel_safe must be a boolean`);
  }
  if (
    spec.timeout_ms !== undefined &&
    (!Number.isInteger(spec.timeout_ms) || spec.timeout_ms < 1)
  ) {
    throw new TypeError(`Tool ${spec.name} timeout_ms must be a positive integer`);
  }
}

function assertToolRisk(spec: ToolSpec): void {
  if (spec.risk === undefined) {
    if (spec.enabled !== false) throw new UnclassifiedToolRiskError(spec.name);
    return;
  }
  if (!TOOL_RISKS.has(spec.risk)) throw ToolSchemaValidationError.invalidRisk(spec.name);
}

/** Fail closed when a planner attempts to execute a spec without a known risk. */
export function assertClassifiedToolSpec(spec: ToolSpec): void {
  if (spec.risk === undefined) throw new UnclassifiedToolRiskError(spec.name);
  if (!TOOL_RISKS.has(spec.risk)) throw ToolSchemaValidationError.invalidRisk(spec.name);
}

/** A tool handler: receives validated args and canonical execution context. */
export type ToolHandler = (
  args: Record<string, unknown>,
  context: ToolExecutionContext,
) => Promise<Record<string, unknown>>;

/** Metadata attached to a handler by `tool(meta, fn)`. */
export interface ToolMeta {
  description: string;
  parameters: ToolParameters;
  risk: ToolRisk;
  tags?: string[];
  enabled?: boolean;
  parallel_safe?: boolean;
  timeout_ms?: number;
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
      risk: meta.risk,
      ...(meta.tags !== undefined ? { tags: meta.tags } : {}),
      ...(meta.enabled !== undefined ? { enabled: meta.enabled } : {}),
      ...(meta.parallel_safe !== undefined ? { parallel_safe: meta.parallel_safe } : {}),
      ...(meta.timeout_ms !== undefined ? { timeout_ms: meta.timeout_ms } : {}),
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

function assertCanonicalExecutionCall(args: IArguments): void {
  if (
    args.length !== 3 ||
    typeof args[0] !== "string" ||
    args[0].trim().length === 0 ||
    typeof args[1] !== "object" ||
    args[1] === null ||
    Array.isArray(args[1]) ||
    typeof args[2] !== "object" ||
    args[2] === null ||
    Array.isArray(args[2])
  ) {
    throw new TypeError("execute expects (toolName, toolArgs, ToolExecutionContext)");
  }
}

/**
 * Build a tool spec from a Zod schema while preserving its complete validation
 * schema, including nested constraints and references.
 */
export function toolSpecFromSchema(
  name: string,
  description: string,
  schema: z.ZodType,
  risk: ToolRisk,
): ToolSpec {
  return setToolArgumentValidator(
    {
      name,
      description,
      parameters: schemaParameters(schema),
      risk,
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
 * registry.register(
 *   { name: "ping", description: "...", parameters: {}, risk: "read" },
 *   async (_args, context) => ({ pong: true, principalId: context.principalId }),
 * );
 * await registry.execute("ping", {}, {
 *   principalId: "user-1",
 *   sessionId: "session-1",
 *   turnId: "turn-1",
 *   requestId: "request-1",
 *   traceId: "trace-1",
 *   toolCallId: "call-1",
 *   idempotencyKey: "session-1:call-1",
 *   signal: new AbortController().signal,
 *   metadata: {},
 * });
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
    toolName: string,
    toolArgs: Record<string, unknown>,
    context: ToolExecutionContext,
  ): Promise<Record<string, unknown>> {
    assertCanonicalExecutionCall(arguments);
    const executionContext = snapshotToolExecutionContext(context);
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
    if (receipt !== undefined) attachValidationReceipt(executionContext, receipt);
    try {
      return await handler(executionArgs, executionContext);
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
  toolName: string,
  toolArgs: Record<string, unknown>,
  context: ToolExecutionContext,
): Promise<Record<string, unknown>> {
  assertCanonicalExecutionCall(arguments);
  return defaultRegistry.execute(toolName, toolArgs, context);
}

/** Clear the process-default registry. Primarily for tests. */
export function clearTools(): void {
  defaultRegistry.clear();
}
