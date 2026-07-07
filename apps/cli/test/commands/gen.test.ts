import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { gen } from "../../src/commands/gen.js";

const spec = JSON.stringify({
  info: { title: "Pet API" },
  servers: [{ url: "https://api.example.com" }],
  paths: {
    "/pets/{id}": { get: { operationId: "getPet", summary: "fetch a pet" } },
    "/pets": { post: { operationId: "createPet", summary: "create pet" } },
  },
});

const typedSpec = JSON.stringify({
  info: { title: "Pet API" },
  servers: [{ url: "https://api.example.com" }],
  paths: {
    "/pets/{id}": {
      get: {
        operationId: "getPet",
        summary: "fetch a pet",
        parameters: [
          {
            name: "id",
            in: "path",
            required: true,
            schema: { type: "string" },
          },
          {
            name: "limit",
            in: "query",
            required: false,
            description: "max related items",
            schema: { type: "integer" },
          },
        ],
      },
      patch: {
        operationId: "updatePet",
        summary: "update a pet",
        parameters: [
          {
            name: "id",
            in: "path",
            required: true,
            schema: { type: "string" },
          },
          {
            name: "dryRun",
            in: "query",
            required: false,
            schema: { type: "boolean" },
          },
        ],
      },
    },
  },
});

const pathLevelSpec = JSON.stringify({
  info: { title: "Pet API" },
  servers: [{ url: "https://api.example.com" }],
  paths: {
    "/pets/{id}": {
      parameters: [
        {
          name: "id",
          in: "path",
          required: true,
          description: "pet identifier",
          schema: { type: "integer" },
        },
        {
          name: "fields",
          in: "query",
          required: false,
          schema: { type: "number" },
        },
      ],
      get: {
        operationId: "getPet",
        summary: "fetch a pet",
        parameters: [
          {
            name: "fields",
            in: "query",
            required: true,
            description: "comma-separated field list",
            schema: { type: "string" },
          },
        ],
      },
    },
  },
});

describe("gen command", () => {
  it("generates TypeScript tools", async () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-gen-"));
    const specPath = join(dir, "spec.json");
    writeFileSync(specPath, spec);
    await gen.parseAsync(["node", "kaji", "--spec", specPath, "--out", dir, "--lang", "ts"]);
    const out = readFileSync(join(dir, "index.ts"), "utf-8");
    expect(out).toMatch(/export const tools/);
    expect(out).toMatch(/get_pet/);
  });

  it("generates Python tools", async () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-gen-"));
    const specPath = join(dir, "spec.json");
    writeFileSync(specPath, spec);
    await gen.parseAsync(["node", "kaji", "--spec", specPath, "--out", dir, "--lang", "python"]);
    const out = readFileSync(join(dir, "tools.py"), "utf-8");
    expect(out).toMatch(/TOOLS\s*=/);
    expect(out).toMatch(/async def get_pet/);
  });

  it("generates TypeScript query params without a body for GET", async () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-gen-"));
    const specPath = join(dir, "spec.json");
    writeFileSync(specPath, typedSpec);
    await gen.parseAsync(["node", "kaji", "--spec", specPath, "--out", dir, "--lang", "ts"]);
    const out = readFileSync(join(dir, "index.ts"), "utf-8");
    expect(out).toContain('limit: { type: "integer", description: "max related items" }');
    expect(out).toContain('required: ["id"]');
    expect(out).toContain('url.searchParams.set("limit"');
    const getPet = out.slice(out.indexOf("export async function get_pet"), out.indexOf("export async function update_pet"));
    expect(getPet).not.toContain("JSON.stringify");
    expect(getPet).toContain("if (!r.ok)");
  });

  it("generates TypeScript write bodies excluding path and query params", async () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-gen-"));
    const specPath = join(dir, "spec.json");
    writeFileSync(specPath, typedSpec);
    await gen.parseAsync(["node", "kaji", "--spec", specPath, "--out", dir, "--lang", "ts"]);
    const out = readFileSync(join(dir, "index.ts"), "utf-8");
    const updatePet = out.slice(out.indexOf("export async function update_pet"));
    expect(updatePet).toContain('const bodyKeys = new Set(["id", "dryRun"])');
    expect(updatePet).toContain("body: JSON.stringify(body)");
    expect(updatePet).toContain('url.searchParams.set("dryRun"');
  });

  it("generates Python query params and HTTP errors", async () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-gen-"));
    const specPath = join(dir, "spec.json");
    writeFileSync(specPath, typedSpec);
    await gen.parseAsync(["node", "kaji", "--spec", specPath, "--out", dir, "--lang", "python"]);
    const out = readFileSync(join(dir, "tools.py"), "utf-8");
    expect(out).toContain('"limit": {"type": "integer", "description": "max related items"}');
    expect(out).toContain('"required": ["id"]');
    expect(out).toContain('params = {k: args[k] for k in ("limit",) if k in args}');
    expect(out).toContain("r.raise_for_status()");
  });

  it("merges path item parameters with operation-level overrides", async () => {
    const dir = mkdtempSync(join(tmpdir(), "kaji-gen-"));
    const specPath = join(dir, "spec.json");
    writeFileSync(specPath, pathLevelSpec);
    await gen.parseAsync(["node", "kaji", "--spec", specPath, "--out", dir, "--lang", "ts"]);
    const out = readFileSync(join(dir, "index.ts"), "utf-8");
    expect(out).toContain('id: { type: "integer", description: "pet identifier" }');
    expect(out).toContain('fields: { type: "string", description: "comma-separated field list" }');
    expect(out).toContain('required: ["id", "fields"]');
  });
});
