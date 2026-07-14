import { Command } from "commander";
import * as p from "@clack/prompts";
import chalk from "chalk";
import { load as parseYaml } from "js-yaml";
import { readFileSync, mkdirSync, writeFileSync, existsSync } from "node:fs";
import { extname, join, resolve } from "node:path";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type PrimitiveType = "string" | "integer" | "number" | "boolean";
type ParamLocation = "path" | "query";
type Lang = "ts" | "python";

const LANGS = ["ts", "python"] as const;

interface OpenApiParameter {
  name: string;
  in: string;
  required?: boolean;
  description?: string;
  schema?: { type?: string };
}

interface OpenApiOperation {
  operationId?: string;
  summary?: string;
  description?: string;
  tags?: string[];
  parameters?: OpenApiParameter[];
}

interface OpenApiPathItem {
  parameters?: OpenApiParameter[];
  [method: string]: OpenApiOperation | OpenApiParameter[] | undefined;
}

interface OpenApiSpec {
  paths?: Record<string, OpenApiPathItem>;
  servers?: Array<{ url: string }>;
  info?: { title?: string };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const HTTP_METHODS = ["get", "post", "put", "patch", "delete", "head", "options", "trace"];

/** Convert any string to snake_case. */
function toSnakeCase(s: string): string {
  const normalized = s
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1_$2")
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/[-\s]+/g, "_")
    .replace(/[^a-zA-Z0-9_]/g, "")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "")
    .toLowerCase();
  if (!normalized) return "operation";
  return /^\d/.test(normalized) ? `_${normalized}` : normalized;
}

/** Extract `{param}` names from a URL path template. */
function extractPathParams(path: string): string[] {
  const matches = path.match(/\{([^}]+)\}/g) ?? [];
  return matches.map((m) => m.slice(1, -1));
}

interface ParsedOperation {
  operationId: string;
  fnName: string;
  method: string;
  path: string;
  summary: string;
  tag: string | undefined;
  params: ParamInfo[];
  risk: "read" | "write";
}

interface ParamInfo {
  name: string;
  location: ParamLocation;
  required: boolean;
  type: PrimitiveType;
  description: string;
}

function normalizePrimitiveType(type: string | undefined): PrimitiveType {
  if (type === "integer" || type === "number" || type === "boolean") return type;
  return "string";
}

function parseParameters(
  path: string,
  pathItemParams: OpenApiParameter[] | undefined,
  operationParams: OpenApiParameter[] | undefined,
): ParamInfo[] {
  const byKey = new Map<string, ParamInfo>();
  for (const p of [...(pathItemParams ?? []), ...(operationParams ?? [])]) {
    if (p.in !== "path" && p.in !== "query") continue;
    const location = p.in;
    byKey.set(`${location}:${p.name}`, {
      name: p.name,
      location,
      required: location === "path" || p.required === true,
      type: normalizePrimitiveType(p.schema?.type),
      description: p.description ?? `${p.name} ${location} param`,
    });
  }
  for (const name of extractPathParams(path)) {
    const key = `path:${name}`;
    if (!byKey.has(key)) {
      byKey.set(key, {
        name,
        location: "path",
        required: true,
        type: "string",
        description: `${name} path param`,
      });
    }
  }
  return [...byKey.values()];
}

function parseSpec(spec: OpenApiSpec): ParsedOperation[] {
  const ops: ParsedOperation[] = [];
  const paths = spec.paths ?? {};

  for (const [path, methods] of Object.entries(paths)) {
    if (!methods || typeof methods !== "object") continue;
    const pathItemParams = Array.isArray(methods.parameters) ? methods.parameters : undefined;
    for (const method of HTTP_METHODS) {
      const op = methods[method] as OpenApiOperation | undefined;
      if (!op || Array.isArray(op) || !op.operationId) continue;

      const operationId = op.operationId;
      const fnName = toSnakeCase(operationId);
      const summary = op.summary ?? op.description ?? operationId;
      const tag = op.tags?.[0];
      const params = parseParameters(path, pathItemParams, op.parameters);
      const risk: "read" | "write" = method === "get" ? "read" : "write";

      ops.push({
        operationId,
        fnName,
        method: method.toUpperCase(),
        path,
        summary,
        tag,
        params,
        risk,
      });
    }
  }

  return ops;
}

// ---------------------------------------------------------------------------
// Code generation
// ---------------------------------------------------------------------------

function inferBaseUrl(spec: OpenApiSpec): string {
  return spec.servers?.[0]?.url ?? "https://api.example.com";
}

function inferEnvVarName(spec: OpenApiSpec): string {
  const title = spec.info?.title ?? "API";
  return toSnakeCase(title).toUpperCase() + "_API_KEY";
}

function tsPropertyKey(name: string): string {
  return /^[A-Za-z_$][\w$]*$/.test(name) ? name : JSON.stringify(name);
}

function pythonTuple(names: string[]): string {
  return `(${names.map((name) => JSON.stringify(name)).join(", ")}${names.length === 1 ? "," : ""})`;
}

function pythonUrlExpression(path: string): string {
  const pieces: string[] = [];
  let offset = 0;
  for (const match of path.matchAll(/\{([^}]+)\}/g)) {
    const index = match.index ?? 0;
    if (index > offset) pieces.push(JSON.stringify(path.slice(offset, index)));
    pieces.push(`quote(str(args[${JSON.stringify(match[1]!)}]), safe="")`);
    offset = index + match[0].length;
  }
  if (offset < path.length) pieces.push(JSON.stringify(path.slice(offset)));
  return ["BASE_URL", ...pieces].join(" + ");
}

function tsUrlExpression(path: string): string {
  const pieces: string[] = [];
  let offset = 0;
  for (const match of path.matchAll(/\{([^}]+)\}/g)) {
    const index = match.index ?? 0;
    if (index > offset) pieces.push(JSON.stringify(path.slice(offset, index)));
    pieces.push(`encodeURIComponent(String(args[${JSON.stringify(match[1]!)}]))`);
    offset = index + match[0].length;
  }
  if (offset < path.length) pieces.push(JSON.stringify(path.slice(offset)));
  return ["BASE_URL", ...pieces].join(" + ");
}

function generateToolsArray(ops: ParsedOperation[], prefix: string): string {
  const entries = ops.map((op) => {
    const name = prefix ? `${prefix}_${op.fnName}` : op.fnName;
    const props = op.params
      .map(
        (p) =>
          `        ${tsPropertyKey(p.name)}: { type: "${p.type}", description: ${JSON.stringify(p.description)} }`,
      )
      .join(",\n");
    const requiredParams = op.params.filter((p) => p.required).map((p) => p.name);
    const required =
      requiredParams.length > 0
        ? `\n      required: [${requiredParams.map((p) => JSON.stringify(p)).join(", ")}],`
        : "";
    const tag = op.tag ? `\n    tags: [${JSON.stringify(op.tag)}],` : "";

    return `  {
    name: ${JSON.stringify(name)},
    description: ${JSON.stringify(op.summary)},
    parameters: {
      type: "object",
      properties: {
${props || "        // no params"}
      },${required}
    },
    risk: "${op.risk}",${tag}
  }`;
  });

  return `export const tools: ToolSpec[] = [\n${entries.join(",\n")},\n];`;
}

function generateHandlers(ops: ParsedOperation[], envVarName: string, prefix: string): string {
  return ops
    .map((op) => {
      const name = prefix ? `${prefix}_${op.fnName}` : op.fnName;
      const urlExpression = tsUrlExpression(op.path);
      const hasBody = op.method !== "GET" && op.method !== "HEAD" && op.method !== "OPTIONS";
      const queryParams = op.params.filter((p) => p.location === "query");
      const queryLines = queryParams
        .map(
          (p) => `  if (args[${JSON.stringify(p.name)}] !== undefined) {
    url.searchParams.set(${JSON.stringify(p.name)}, String(args[${JSON.stringify(p.name)}]));
  }`,
        )
        .join("\n");
      const paramNames = op.params.map((p) => p.name);
      const bodySetup =
        hasBody && paramNames.length > 0
          ? `  const bodyKeys = new Set([${paramNames.map((p) => JSON.stringify(p)).join(", ")}]);
  const body = Object.fromEntries(Object.entries(args).filter(([k]) => !bodyKeys.has(k)));
`
          : "";
      const bodyLines = hasBody
        ? `\n    body: JSON.stringify(${paramNames.length > 0 ? "body" : "args"}),`
        : "";
      const contentTypeHeader = hasBody ? `, "Content-Type": "application/json"` : "";

      return `export async function ${name}(args: Record<string, unknown>): Promise<unknown> {
  if (!API_KEY) throw new Error(${JSON.stringify(`${envVarName} is required`)});
  const url = new URL(${urlExpression});
${queryLines ? `${queryLines}\n` : ""}${bodySetup}
  const r = await fetch(url.toString(), {
    method: "${op.method}",
    headers: { Authorization: \`Bearer \${API_KEY}\`${contentTypeHeader} },${bodyLines}
  });
  if (!r.ok) {
    throw new Error(\`${op.method} \${url.pathname} failed: \${r.status} \${await r.text()}\`);
  }
  return r.status === 204 ? {} : r.json();
}`;
    })
    .join("\n\n");
}

function generateTsFile(spec: OpenApiSpec, ops: ParsedOperation[], prefix: string): string {
  const baseUrl = inferBaseUrl(spec);
  const envVarName = inferEnvVarName(spec);

  const toolsArray = generateToolsArray(ops, prefix);
  const handlers = generateHandlers(ops, envVarName, prefix);

  return `// Auto-generated by kaji gen. Do not edit.
import type { ToolSpec } from "@kaji/sdk";

// Auth: set ${envVarName} in your environment
const BASE_URL = ${JSON.stringify(baseUrl)};
const API_KEY = process.env[${JSON.stringify(envVarName)}] ?? "";

${toolsArray}

${handlers}
`;
}

function generatePythonFile(spec: OpenApiSpec, ops: ParsedOperation[], prefix: string): string {
  const baseUrl = inferBaseUrl(spec);
  const envVarName = inferEnvVarName(spec);

  const toolEntries = ops
    .map((op) => {
      const name = prefix ? `${prefix}_${op.fnName}` : op.fnName;
      const props = op.params
        .map(
          (p) =>
            `            ${JSON.stringify(p.name)}: {"type": "${p.type}", "description": ${JSON.stringify(p.description)}}`,
        )
        .join(",\n");
      const requiredParams = op.params.filter((p) => p.required).map((p) => p.name);
      const required =
        requiredParams.length > 0
          ? `, "required": [${requiredParams.map((p) => JSON.stringify(p)).join(", ")}]`
          : "";
      return `    {
        "name": ${JSON.stringify(name)},
        "description": ${JSON.stringify(op.summary)},
        "parameters": {
            "type": "object",
            "properties": {
${props || "                # no params"}
            }${required}
        },
        "risk": "${op.risk}"
    }`;
    })
    .join(",\n");

  const handlers = ops
    .map((op) => {
      const name = prefix ? `${prefix}_${op.fnName}` : op.fnName;
      const urlExpression = pythonUrlExpression(op.path);
      const hasBody = op.method !== "GET" && op.method !== "HEAD" && op.method !== "OPTIONS";
      const queryParams = op.params.filter((p) => p.location === "query").map((p) => p.name);
      const allParams = op.params.map((p) => p.name);
      const paramsLine =
        queryParams.length > 0
          ? `    params = {k: args[k] for k in ${pythonTuple(queryParams)} if k in args}\n`
          : "";
      const paramsArg = queryParams.length > 0 ? ", params=params" : "";
      const bodyLine =
        hasBody && allParams.length > 0
          ? `    body = {k: v for k, v in args.items() if k not in ${pythonTuple(allParams)}}\n`
          : "";
      const jsonArg = hasBody ? `, json=${allParams.length > 0 ? "body" : "args"}` : "";

      return `async def ${name}(args: dict[str, object]) -> object:
    if not API_KEY:
        raise RuntimeError(${JSON.stringify(`${envVarName} is required`)})
    url = ${urlExpression}
${paramsLine}${bodyLine}
    async with httpx.AsyncClient() as c:
        r = await c.request("${op.method}", url, headers={"Authorization": f"Bearer {API_KEY}"}${paramsArg}${jsonArg})
        r.raise_for_status()
        return {} if r.status_code == 204 else r.json()`;
    })
    .join("\n\n");

  return `# Auto-generated by kaji gen. Do not edit.
import os
from urllib.parse import quote

import httpx

BASE_URL = ${JSON.stringify(baseUrl)}
API_KEY = os.environ.get("${envVarName}", "")

TOOLS = [
${toolEntries},
]

${handlers}
`;
}

// ---------------------------------------------------------------------------
// Command
// ---------------------------------------------------------------------------

export const gen = new Command("gen")
  .description("generate tool stubs from an OpenAPI spec")
  .requiredOption("--spec <path>", "path to OpenAPI spec file (JSON or YAML)")
  .requiredOption("--out <dir>", "output directory")
  .option("--prefix <prefix>", "prefix for tool names", "")
  .option("--lang <lang>", "ts|python", "ts")
  .action(async (opts: { spec: string; out: string; prefix: string; lang: string }) => {
    console.log();
    p.intro(chalk.bold("kaji gen"));

    const specPath = resolve(opts.spec);
    const outDir = resolve(opts.out);

    if (!LANGS.includes(opts.lang as Lang)) {
      p.cancel(`--lang must be one of: ${LANGS.join(", ")}`);
      process.exitCode = 2;
      return;
    }
    const lang = opts.lang as Lang;

    if (!existsSync(specPath)) {
      p.cancel(`Spec file not found: ${specPath}`);
      process.exitCode = 1;
      return;
    }

    // ---- Load spec ----
    const s = p.spinner();
    s.start("Reading spec");

    let raw: string;
    try {
      raw = readFileSync(specPath, "utf-8");
    } catch (err) {
      s.stop("Failed to read spec");
      p.cancel(String(err));
      process.exitCode = 1;
      return;
    }

    let spec: OpenApiSpec;
    const ext = extname(specPath).toLowerCase();
    try {
      if (ext === ".json") {
        spec = JSON.parse(raw) as OpenApiSpec;
      } else if (ext === ".yaml" || ext === ".yml") {
        spec = parseYaml(raw) as OpenApiSpec;
      } else {
        // Try JSON first, fall back to YAML
        try {
          spec = JSON.parse(raw) as OpenApiSpec;
        } catch {
          spec = parseYaml(raw) as OpenApiSpec;
        }
      }
    } catch (err) {
      s.stop("Failed to parse spec");
      p.cancel(`Parse error: ${String(err)}`);
      process.exitCode = 1;
      return;
    }

    s.stop("Spec loaded");

    // ---- Parse operations ----
    const ops = parseSpec(spec);
    if (ops.length === 0) {
      p.cancel("No operations with operationId found in spec.");
      process.exitCode = 1;
      return;
    }

    p.log.info(`Found ${chalk.cyan(ops.length)} operations`);

    // ---- Generate ----
    const s2 = p.spinner();
    s2.start("Generating");

    const file = lang === "python" ? "tools.py" : "index.ts";
    const code =
      lang === "python"
        ? generatePythonFile(spec, ops, opts.prefix)
        : generateTsFile(spec, ops, opts.prefix);

    mkdirSync(outDir, { recursive: true });
    const outFile = join(outDir, file);
    writeFileSync(outFile, code, "utf-8");

    s2.stop(`Written to ${chalk.green(outFile)}`);

    p.outro(
      `${chalk.green("✓")} Generated ${ops.length} tool${ops.length === 1 ? "" : "s"} → ${outFile}`,
    );
  });
