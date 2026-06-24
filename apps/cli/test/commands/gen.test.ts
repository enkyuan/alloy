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
});
