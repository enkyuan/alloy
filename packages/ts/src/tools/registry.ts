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

/** Return all registered tool specs. */
export function listToolSpecs(): ToolSpec[] {
  return [...toolSpecs.values()];
}

/**
 * Build a tool spec from a Zod schema, reducing it to the
 * `{ type, properties, required }` shape the LLM tool API expects (mirrors the
 * Python `tool_spec_from_model`).
 */
export function toolSpecFromSchema(
  name: string,
  description: string,
  schema: z.ZodType,
): ToolSpec {
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
