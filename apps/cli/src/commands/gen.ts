import { Command } from "commander";
import * as p from "@clack/prompts";
import chalk from "chalk";
import { readFileSync, mkdirSync, writeFileSync, existsSync } from "node:fs";
import { resolve, extname } from "node:path";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface OpenApiOperation {
  operationId?: string;
  summary?: string;
  description?: string;
  tags?: string[];
  parameters?: Array<{
    name: string;
    in: string;
    required?: boolean;
  }>;
}

interface OpenApiSpec {
  paths?: Record<string, Record<string, OpenApiOperation>>;
  servers?: Array<{ url: string }>;
  info?: { title?: string };
}

// ---------------------------------------------------------------------------
// Minimal YAML → JSON converter (no dependencies)
// Supports only the subset needed to parse OpenAPI path blocks:
// scalars, block mappings, block sequences, quoted strings, multi-line values.
// For production use, add js-yaml.
// ---------------------------------------------------------------------------

/**
 * Extremely minimal YAML parser — covers the OpenAPI 3.x path section well
 * enough for V0 code-gen.  Handles:
 *   - block mappings (key: value)
 *   - block sequences (- item)
 *   - quoted strings ('…' and "…")
 *   - null / bool / number scalars
 *   - comments (#)
 *   - indented nesting via indent tracking
 *
 * Does NOT handle: anchors, merge keys, flow objects/arrays, multi-doc files.
 */
function parseYaml(text: string): unknown {
  const lines = text.split(/\r?\n/);
  let pos = 0;

  function currentIndent(line: string): number {
    let i = 0;
    while (i < line.length && line[i] === " ") i++;
    return i;
  }

  function isBlankOrComment(line: string): boolean {
    const t = line.trim();
    return t === "" || t.startsWith("#");
  }

  function parseScalar(raw: string): unknown {
    const t = raw.trim();
    if (t === "" || t === "null" || t === "~") return null;
    if (t === "true") return true;
    if (t === "false") return false;
    const n = Number(t);
    if (!Number.isNaN(n) && t !== "") return n;
    // Strip inline comments
    const noComment = t.replace(/\s+#.*$/, "");
    // Strip quotes
    if (
      (noComment.startsWith('"') && noComment.endsWith('"')) ||
      (noComment.startsWith("'") && noComment.endsWith("'"))
    ) {
      return noComment.slice(1, -1);
    }
    return noComment;
  }

  function parseMapping(baseIndent: number): Record<string, unknown> {
    const obj: Record<string, unknown> = {};

    while (pos < lines.length) {
      // Skip blanks/comments
      while (pos < lines.length && isBlankOrComment(lines[pos])) pos++;
      if (pos >= lines.length) break;

      const line = lines[pos];
      const ind = currentIndent(line);
      if (ind < baseIndent) break;

      const trimmed = line.trim();
      if (trimmed.startsWith("#")) {
        pos++;
        continue;
      }

      // Sequence items at this level belong to a parent
      if (trimmed.startsWith("- ")) break;

      // Parse key: value
      const colonIdx = trimmed.indexOf(": ");
      const bareColon = trimmed.endsWith(":");

      if (colonIdx === -1 && !bareColon) {
        // Not a key line — skip
        pos++;
        continue;
      }

      let key: string;
      let inlineValue: string | null;

      if (bareColon && colonIdx === -1) {
        key = trimmed.slice(0, -1).trim();
        inlineValue = null;
      } else {
        key = trimmed.slice(0, colonIdx).trim();
        inlineValue = trimmed.slice(colonIdx + 2).trim();
      }

      // Strip quotes from key
      if (
        (key.startsWith('"') && key.endsWith('"')) ||
        (key.startsWith("'") && key.endsWith("'"))
      ) {
        key = key.slice(1, -1);
      }

      pos++;

      if (inlineValue === null || inlineValue === "") {
        // Value is on next lines
        // Skip blanks
        while (pos < lines.length && isBlankOrComment(lines[pos])) pos++;
        if (pos >= lines.length) {
          obj[key] = null;
          continue;
        }
        const nextLine = lines[pos];
        const nextInd = currentIndent(nextLine);
        const nextTrim = nextLine.trim();

        if (nextInd <= ind && !isBlankOrComment(nextLine)) {
          obj[key] = null;
          continue;
        }

        if (nextTrim.startsWith("- ") || nextTrim === "-") {
          obj[key] = parseSequence(nextInd);
        } else {
          obj[key] = parseMapping(nextInd);
        }
      } else {
        obj[key] = parseScalar(inlineValue);
      }
    }

    return obj;
  }

  function parseSequence(baseIndent: number): unknown[] {
    const arr: unknown[] = [];

    while (pos < lines.length) {
      while (pos < lines.length && isBlankOrComment(lines[pos])) pos++;
      if (pos >= lines.length) break;

      const line = lines[pos];
      const ind = currentIndent(line);
      if (ind < baseIndent) break;

      const trimmed = line.trim();
      if (!trimmed.startsWith("- ") && trimmed !== "-") break;

      const itemContent = trimmed === "-" ? "" : trimmed.slice(2).trim();
      pos++;

      if (itemContent === "") {
        // Value is on next lines
        while (pos < lines.length && isBlankOrComment(lines[pos])) pos++;
        if (pos >= lines.length) {
          arr.push(null);
          continue;
        }
        const nextLine = lines[pos];
        const nextInd = currentIndent(nextLine);
        const nextTrim = nextLine.trim();

        if (nextTrim.startsWith("- ")) {
          arr.push(parseSequence(nextInd));
        } else {
          arr.push(parseMapping(nextInd));
        }
      } else {
        // Check if inline mapping follows
        if (itemContent.includes(": ") || itemContent.endsWith(":")) {
          // Parse as an inline mapping merged with subsequent indented lines
          const tempLines = [" ".repeat(baseIndent + 2) + itemContent];
          // Peek ahead for continuation
          while (pos < lines.length && !isBlankOrComment(lines[pos])) {
            const l = lines[pos];
            const li = currentIndent(l);
            if (li <= baseIndent) break;
            tempLines.push(l);
            pos++;
          }
          lines.splice(pos - tempLines.length + 1, 0);
          // Parse the mini-mapping
          const miniParser = parseYaml(tempLines.join("\n"));
          arr.push(miniParser);
        } else {
          arr.push(parseScalar(itemContent));
        }
      }
    }

    return arr;
  }

  // Entry point
  while (pos < lines.length && isBlankOrComment(lines[pos])) pos++;
  if (pos >= lines.length) return {};

  const firstLine = lines[pos];
  const firstInd = currentIndent(firstLine);
  const firstTrim = firstLine.trim();

  if (firstTrim.startsWith("- ")) {
    return parseSequence(firstInd);
  }
  return parseMapping(firstInd);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const HTTP_METHODS = ["get", "post", "put", "patch", "delete", "head", "options", "trace"];

/** Convert any string to snake_case. */
function toSnakeCase(s: string): string {
  return s
    .replace(/([A-Z])/g, "_$1")
    .replace(/[-\s]+/g, "_")
    .replace(/[^a-zA-Z0-9_]/g, "")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "")
    .toLowerCase();
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
  pathParams: string[];
  risk: "read" | "write";
}

function parseSpec(spec: OpenApiSpec): ParsedOperation[] {
  const ops: ParsedOperation[] = [];
  const paths = spec.paths ?? {};

  for (const [path, methods] of Object.entries(paths)) {
    if (!methods || typeof methods !== "object") continue;
    for (const method of HTTP_METHODS) {
      const op = (methods as Record<string, OpenApiOperation>)[method];
      if (!op || !op.operationId) continue;

      const operationId = op.operationId;
      const fnName = toSnakeCase(operationId);
      const summary = op.summary ?? op.description ?? operationId;
      const tag = op.tags?.[0];
      const pathParams = extractPathParams(path);
      const risk: "read" | "write" = method === "get" ? "read" : "write";

      ops.push({
        operationId,
        fnName,
        method: method.toUpperCase(),
        path,
        summary,
        tag,
        pathParams,
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

function generateToolsArray(ops: ParsedOperation[], prefix: string): string {
  const entries = ops.map((op) => {
    const name = prefix ? `${prefix}_${op.fnName}` : op.fnName;
    const props = op.pathParams
      .map((p) => `        ${p}: { type: "string", description: "${p} path param" }`)
      .join(",\n");
    const required =
      op.pathParams.length > 0
        ? `\n      required: [${op.pathParams.map((p) => `"${p}"`).join(", ")}],`
        : "";
    const tag = op.tag ? `\n    tags: ["${op.tag}"],` : "";

    return `  {
    name: "${name}",
    description: "${op.summary.replace(/"/g, '\\"')}",
    parameters: {
      type: "object",
      properties: {
${props || "        // no path params"}
      },${required}
    },
    risk: "${op.risk}",${tag}
  }`;
  });

  return `export const tools: ToolSpec[] = [\n${entries.join(",\n")},\n];`;
}

function generateHandlers(ops: ParsedOperation[], _baseUrl: string, prefix: string): string {
  return ops
    .map((op) => {
      const name = prefix ? `${prefix}_${op.fnName}` : op.fnName;
      // Build URL: replace {param} with template literal ${args.param}
      const urlPath = op.path.replace(/\{([^}]+)\}/g, "${args.$1}");
      const hasBody = op.method !== "GET" && op.method !== "HEAD" && op.method !== "OPTIONS";
      const bodyLines = hasBody ? `\n    body: JSON.stringify(args),` : "";
      const contentTypeHeader = hasBody ? `, "Content-Type": "application/json"` : "";

      return `export async function ${name}(args: Record<string, unknown>): Promise<unknown> {
  const url = new URL(\`\${BASE_URL}${urlPath}\`);
  const r = await fetch(url.toString(), {
    method: "${op.method}",
    headers: { Authorization: \`Bearer \${API_KEY}\`${contentTypeHeader} },${bodyLines}
  });
  return r.json();
}`;
    })
    .join("\n\n");
}

function generateFile(spec: OpenApiSpec, ops: ParsedOperation[], prefix: string): string {
  const baseUrl = inferBaseUrl(spec);
  const envVarName = inferEnvVarName(spec);

  const toolsArray = generateToolsArray(ops, prefix);
  const handlers = generateHandlers(ops, baseUrl, prefix);

  return `// Auto-generated by agentkit gen. Do not edit.
import type { ToolSpec } from "@agentkit/sdk";

// Auth: set ${envVarName} in your environment
const BASE_URL = "${baseUrl}";
const API_KEY = process.env.${envVarName} ?? "";

${toolsArray}

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
  .action(async (opts: { spec: string; out: string; prefix: string }) => {
    console.log();
    p.intro(chalk.bold("agentkit gen"));

    const specPath = resolve(opts.spec);
    const outDir = resolve(opts.out);

    if (!existsSync(specPath)) {
      p.cancel(`Spec file not found: ${specPath}`);
      process.exit(1);
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
      process.exit(1);
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
      process.exit(1);
    }

    s.stop("Spec loaded");

    // ---- Parse operations ----
    const ops = parseSpec(spec);
    if (ops.length === 0) {
      p.cancel("No operations with operationId found in spec.");
      process.exit(1);
    }

    p.log.info(`Found ${chalk.cyan(ops.length)} operations`);

    // ---- Generate ----
    const s2 = p.spinner();
    s2.start("Generating");

    const code = generateFile(spec, ops, opts.prefix);

    mkdirSync(outDir, { recursive: true });
    const outFile = `${outDir}/index.ts`;
    writeFileSync(outFile, code, "utf-8");

    s2.stop(`Written to ${chalk.green(outFile)}`);

    p.outro(
      `${chalk.green("✓")} Generated ${ops.length} tool${ops.length === 1 ? "" : "s"} → ${outFile}`,
    );
  });
