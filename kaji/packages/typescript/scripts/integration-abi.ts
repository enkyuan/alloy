import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { BoundTool } from "../src/integrations/functional";
import type {
  IntegrationManifestDocument,
  IntegrationManifestTool,
} from "../src/integrations/registry-loader";
import type { JSONSchema, ToolRisk, ToolSpec } from "../src/tools/registry";
import * as echoModule from "../registry/echo/index";

export interface ManifestToolAbi {
  readonly name: string;
  readonly description: string;
  readonly parameters: JSONSchema;
  readonly risk: ToolRisk;
  readonly parallel_safe: boolean;
  readonly timeout_ms?: number;
}

export interface ExecutableIntegrationAbi {
  readonly namespace: string;
  readonly tools: readonly ManifestToolAbi[];
}

type MetadataTool = Pick<BoundTool, "namespace" | "spec">;
type IntegrationModule = Readonly<Record<string, unknown>>;

const missing = Symbol("missing");

function pointerPart(value: string): string {
  return value.replaceAll("~", "~0").replaceAll("/", "~1");
}

function displayValue(value: unknown): string {
  if (value === missing) return "<missing>";
  if (value === null) return "<null>";
  if (typeof value === "boolean") return "<boolean>";
  if (typeof value === "number") return "<number>";
  if (typeof value === "string") return `<string length=${value.length}>`;
  if (Array.isArray(value)) return `<array length=${value.length}>`;
  if (typeof value === "object") return `<object keys=${Object.keys(value).length}>`;
  return `<${typeof value}>`;
}

export class IntegrationAbiMismatchError extends Error {
  readonly code = "INTEGRATION_ABI_MISMATCH" as const;

  constructor(
    readonly pointer: string,
    readonly expected: unknown,
    readonly actual: unknown,
  ) {
    super(
      `INTEGRATION_ABI_MISMATCH at ${pointer}: expected ${displayValue(expected)}, actual ${displayValue(actual)}`,
    );
    this.name = "IntegrationAbiMismatchError";
  }

  normalized(): {
    code: "INTEGRATION_ABI_MISMATCH";
    pointer: string;
    expected: string;
    actual: string;
  } {
    return {
      code: this.code,
      pointer: this.pointer,
      expected: displayValue(this.expected),
      actual: displayValue(this.actual),
    };
  }
}

function normalizeTool(tool: IntegrationManifestTool | ToolSpec, index: number): ManifestToolAbi {
  const record = tool as unknown as Record<string, unknown>;
  const parallelSafe = Object.hasOwn(record, "parallel_safe") ? record.parallel_safe : missing;
  if (typeof parallelSafe !== "boolean") {
    throw new IntegrationAbiMismatchError(`/tools/${index}/parallel_safe`, "boolean", parallelSafe);
  }
  return {
    name: tool.name,
    description: tool.description,
    parameters: tool.parameters,
    risk: tool.risk,
    parallel_safe: parallelSafe,
    ...(tool.timeout_ms === undefined ? {} : { timeout_ms: tool.timeout_ms }),
  };
}

function normalizedTools(
  tools: readonly (IntegrationManifestTool | ToolSpec)[],
): readonly ManifestToolAbi[] {
  const normalized = tools
    .map((tool, index) => normalizeTool(tool, index))
    .sort((left, right) => left.name.localeCompare(right.name));
  for (let index = 1; index < normalized.length; index++) {
    if (normalized[index - 1]!.name === normalized[index]!.name) {
      throw new IntegrationAbiMismatchError(
        `/tools/${index}/name`,
        "unique normalized tool name",
        normalized[index]!.name,
      );
    }
  }
  return normalized;
}

interface Mismatch {
  pointer: string;
  expected: unknown;
  actual: unknown;
}

function firstMismatch(expected: unknown, actual: unknown, pointer = ""): Mismatch | undefined {
  if (Object.is(expected, actual)) return undefined;
  if (Array.isArray(expected) || Array.isArray(actual)) {
    if (!Array.isArray(expected) || !Array.isArray(actual)) {
      return { pointer: pointer || "/", expected, actual };
    }
    const length = Math.max(expected.length, actual.length);
    for (let index = 0; index < length; index++) {
      const mismatch = firstMismatch(
        index < expected.length ? expected[index] : missing,
        index < actual.length ? actual[index] : missing,
        `${pointer}/${index}`,
      );
      if (mismatch !== undefined) return mismatch;
    }
    return undefined;
  }
  if (
    typeof expected === "object" &&
    expected !== null &&
    typeof actual === "object" &&
    actual !== null
  ) {
    const expectedRecord = expected as Record<string, unknown>;
    const actualRecord = actual as Record<string, unknown>;
    const keys = [
      ...new Set([...Object.keys(expectedRecord), ...Object.keys(actualRecord)]),
    ].sort();
    for (const key of keys) {
      const mismatch = firstMismatch(
        Object.hasOwn(expectedRecord, key) ? expectedRecord[key] : missing,
        Object.hasOwn(actualRecord, key) ? actualRecord[key] : missing,
        `${pointer}/${pointerPart(key)}`,
      );
      if (mismatch !== undefined) return mismatch;
    }
    return undefined;
  }
  return { pointer: pointer || "/", expected, actual };
}

export function compareManifestAbi(
  manifest: IntegrationManifestDocument,
  specs: readonly ToolSpec[],
): void {
  const mismatch = firstMismatch(normalizedTools(manifest.tools), normalizedTools(specs), "/tools");
  if (mismatch !== undefined) {
    throw new IntegrationAbiMismatchError(mismatch.pointer, mismatch.expected, mismatch.actual);
  }
}

export function compareExecutableIntegrationAbi(
  manifest: IntegrationManifestDocument,
  executable: ExecutableIntegrationAbi,
): void {
  if (manifest.namespace !== executable.namespace) {
    throw new IntegrationAbiMismatchError("/namespace", manifest.namespace, executable.namespace);
  }
  compareManifestAbi(manifest, executable.tools);
}

export function executableIntegrationAbi(tools: readonly MetadataTool[]): ExecutableIntegrationAbi {
  const namespace = tools[0]?.namespace;
  if (namespace === undefined || namespace.length === 0) {
    throw new IntegrationAbiMismatchError("/namespace", "non-empty namespace", namespace);
  }
  for (let index = 1; index < tools.length; index++) {
    if (tools[index]!.namespace !== namespace) {
      throw new IntegrationAbiMismatchError(
        `/tools/${index}/namespace`,
        namespace,
        tools[index]!.namespace,
      );
    }
  }
  return { namespace, tools: normalizedTools(tools.map((tool) => tool.spec)) };
}

function isMetadataTool(value: unknown): value is MetadataTool {
  return value instanceof BoundTool;
}

export function discoverIntegrationTools(
  module: IntegrationModule,
  declared: readonly MetadataTool[],
): readonly MetadataTool[] {
  const exports = Object.entries(module)
    .filter((entry): entry is [string, MetadataTool] => isMetadataTool(entry[1]))
    .sort(([left], [right]) => left.localeCompare(right));
  const declaredSet = new Set(declared);
  for (const [name, tool] of exports) {
    if (!declaredSet.has(tool)) {
      throw new IntegrationAbiMismatchError(
        `/exports/${pointerPart(name)}`,
        "listed in tools",
        "unlisted BoundTool export",
      );
    }
  }
  const exportedSet = new Set(exports.map(([, tool]) => tool));
  for (let index = 0; index < declared.length; index++) {
    if (!exportedSet.has(declared[index]!)) {
      throw new IntegrationAbiMismatchError(
        `/tools/${index}`,
        "named BoundTool export",
        "unexported tool metadata",
      );
    }
  }
  return declared;
}

export function inspectIntegrationModule(module: IntegrationModule): ExecutableIntegrationAbi {
  const inspector = module.inspectIntegration;
  if (typeof inspector !== "function") {
    throw new IntegrationAbiMismatchError(
      "/inspectIntegration",
      "side-effect-free inspector function",
      inspector,
    );
  }

  let integration: unknown;
  try {
    integration = inspector();
  } catch (error) {
    throw new IntegrationAbiMismatchError(
      "/inspectIntegration",
      "side-effect-free inspector result",
      error,
    );
  }
  if (typeof integration !== "object" || integration === null) {
    throw new IntegrationAbiMismatchError("/inspectIntegration", "integration object", integration);
  }

  const inspected = integration as Record<string, unknown>;
  const namespace = inspected.namespace;
  if (typeof namespace !== "string" || namespace.length === 0) {
    throw new IntegrationAbiMismatchError("/namespace", "non-empty namespace", namespace);
  }
  const toolsMethod = inspected.tools;
  if (typeof toolsMethod !== "function") {
    throw new IntegrationAbiMismatchError("/tools", "metadata method", toolsMethod);
  }

  let pairs: unknown;
  try {
    pairs = toolsMethod.call(integration);
  } catch (error) {
    throw new IntegrationAbiMismatchError("/tools", "side-effect-free metadata", error);
  }
  if (!Array.isArray(pairs)) {
    throw new IntegrationAbiMismatchError("/tools", "array of tool pairs", pairs);
  }
  const specs = pairs.map((pair, index) => {
    if (!Array.isArray(pair) || typeof pair[0] !== "object" || pair[0] === null) {
      throw new IntegrationAbiMismatchError(`/tools/${index}`, "tool metadata pair", pair);
    }
    return pair[0] as ToolSpec;
  });
  return { namespace, tools: normalizedTools(specs) };
}

export function echoExecutableAbi(): ExecutableIntegrationAbi {
  return inspectIntegrationModule(echoModule);
}

export async function loadExecutableIntegrationAbi(
  integrationName: string,
): Promise<ExecutableIntegrationAbi> {
  if (!/^[a-z][a-z0-9_-]*$/.test(integrationName)) {
    throw new IntegrationAbiMismatchError("/integration", "safe integration name", integrationName);
  }
  let module: IntegrationModule;
  try {
    module = (await import(`../registry/${integrationName}/index.ts`)) as IntegrationModule;
  } catch (error) {
    throw new IntegrationAbiMismatchError("/inspectIntegration", "importable module", error);
  }
  return inspectIntegrationModule(module);
}

export function integrationAbiJson(
  load: () => ExecutableIntegrationAbi = echoExecutableAbi,
): string {
  try {
    return JSON.stringify(load());
  } catch (error) {
    if (!(error instanceof IntegrationAbiMismatchError)) throw error;
    return JSON.stringify({ error: error.normalized() });
  }
}

async function integrationAbiJsonFor(integrationName: string): Promise<string> {
  try {
    return JSON.stringify(await loadExecutableIntegrationAbi(integrationName));
  } catch (error) {
    if (!(error instanceof IntegrationAbiMismatchError)) throw error;
    return JSON.stringify({ error: error.normalized() });
  }
}

async function main(): Promise<number> {
  const args = process.argv.slice(2);
  if (args.length !== 2 || args[0] !== "--json") {
    console.error("usage: integration-abi.ts --json <integration>");
    return 2;
  }
  console.log(await integrationAbiJsonFor(args[1]!));
  return 0;
}

if (process.argv[1] !== undefined && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  process.exit(await main());
}
