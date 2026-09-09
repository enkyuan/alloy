import * as z from "zod";

import { isCapabilityResult } from "@/capabilities/result";
import type { ToolExecutionContext } from "@/runtime/context";
import {
  TOOL_ARGUMENT_VALIDATOR,
  isZodSchema,
  setToolArgumentValidator,
  toolArgumentValidator,
  toolParametersToJSONSchema,
  toolSpecFromSchema,
  type ToolHandler,
  type ToolParameters,
  type ToolRegistry,
  type ToolRisk,
  type ToolSpec,
} from "@/tools/registry";

type ArgsOf<P> = P extends z.ZodType ? z.input<P> : Record<string, unknown>;

export interface CapabilityDefinition<P extends ToolParameters> {
  readonly name: string;
  readonly description: string;
  readonly input: P;
  readonly risk: ToolRisk;
  readonly execute: (input: ArgsOf<P>, context: ToolExecutionContext) => Promise<unknown>;
  readonly timeout_ms?: number;
  readonly parallel_safe?: boolean;
  readonly metadata?: Readonly<Record<string, unknown>>;
}

/** A product operation compiled into the existing ToolRegistry execution path. */
export class Capability {
  constructor(
    readonly spec: ToolSpec,
    readonly handler: ToolHandler,
    readonly metadata: Readonly<Record<string, unknown>> = {},
  ) {}

  register(registry: ToolRegistry): void {
    registry.register(this.spec, this.handler);
  }
}

/** Define a product capability without creating a second execution path. */
export function capability<P extends ToolParameters>(
  definition: CapabilityDefinition<P>,
): Capability {
  const base = isZodSchema(definition.input)
    ? toolSpecFromSchema(definition.name, definition.description, definition.input, definition.risk)
    : {
        name: definition.name,
        description: definition.description,
        parameters: toolParametersToJSONSchema(definition.input),
        risk: definition.risk,
      };
  const spec = setToolArgumentValidator<ToolSpec>(
    {
      ...base,
      ...(definition.parallel_safe !== undefined
        ? { parallel_safe: definition.parallel_safe }
        : {}),
      ...(definition.timeout_ms !== undefined ? { timeout_ms: definition.timeout_ms } : {}),
    },
    base[TOOL_ARGUMENT_VALIDATOR] ?? toolArgumentValidator(definition.input),
  );
  const handler: ToolHandler = async (args, context) => {
    const result = await definition.execute(args as ArgsOf<P>, context);
    if (isCapabilityResult(result)) return result as unknown as Record<string, unknown>;
    return result !== null && typeof result === "object" && !Array.isArray(result)
      ? (result as Record<string, unknown>)
      : { result };
  };
  return new Capability(spec, handler, definition.metadata ?? {});
}
