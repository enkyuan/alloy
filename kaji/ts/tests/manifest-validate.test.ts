import { mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  IntegrationValidationError,
  loadManifest,
  loadRegistryIndex,
  validateIndexDocument,
  validateManifestDocument,
  type IntegrationValidationCode,
} from "@/integrations/registry-loader";

const here = dirname(fileURLToPath(import.meta.url));
const registryRoot = join(here, "..", "registry");
const contractRoot = join(here, "..", "..", "contracts", "integrations");

interface ValidCase {
  name: string;
  target: "manifest" | "index";
  document: unknown;
}

interface InvalidCase {
  name: string;
  target: "manifest" | "index" | "registry";
  document?: unknown;
  index?: unknown;
  manifests?: Record<string, unknown>;
  files?: string[];
  expectedPath: string;
  expectedCode: IntegrationValidationCode;
}

const validCases = (
  JSON.parse(readFileSync(join(contractRoot, "conformance-valid.json"), "utf8")) as {
    cases: ValidCase[];
  }
).cases;
const invalidCases = (
  JSON.parse(readFileSync(join(contractRoot, "conformance-invalid.json"), "utf8")) as {
    cases: InvalidCase[];
  }
).cases;

async function capturedValidationError(
  action: () => Promise<unknown>,
): Promise<IntegrationValidationError> {
  let caught: unknown;
  try {
    await action();
  } catch (error) {
    caught = error;
  }
  expect(caught).toBeInstanceOf(IntegrationValidationError);
  return caught as IntegrationValidationError;
}

function writeRegistryCase(testCase: InvalidCase): string {
  const root = mkdtempSync(join(tmpdir(), "kaji-registry-contract-"));
  writeFileSync(join(root, "index.json"), JSON.stringify(testCase.index));
  for (const [relativePath, manifest] of Object.entries(testCase.manifests ?? {})) {
    const path = join(root, relativePath);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, JSON.stringify(manifest));
  }
  for (const relativePath of testCase.files ?? []) {
    const path = join(root, relativePath);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, "// fixture\n");
  }
  return root;
}

describe("integration contract conformance", () => {
  for (const testCase of validCases) {
    it(`accepts: ${testCase.name}`, async () => {
      if (testCase.target === "manifest") {
        await validateManifestDocument(testCase.document, { schemaRoot: registryRoot });
      } else {
        await validateIndexDocument(testCase.document, { schemaRoot: registryRoot });
      }
    });
  }

  for (const testCase of invalidCases) {
    it(`rejects with normalized error: ${testCase.name}`, async () => {
      let root: string | undefined;
      try {
        const error = await capturedValidationError(async () => {
          if (testCase.target === "manifest") {
            return validateManifestDocument(testCase.document, { schemaRoot: registryRoot });
          }
          if (testCase.target === "index") {
            return validateIndexDocument(testCase.document, { schemaRoot: registryRoot });
          }
          root = writeRegistryCase(testCase);
          const index = await loadRegistryIndex(root, { schemaRoot: registryRoot });
          const name = Object.keys(index.integrations)[0]!;
          return loadManifest(root, name, { schemaRoot: registryRoot, index });
        });
        expect(error.normalized()).toEqual({
          code: testCase.expectedCode,
          path: testCase.expectedPath,
        });
      } finally {
        if (root !== undefined) rmSync(root, { recursive: true, force: true });
      }
    });
  }

  it("returns every executable tool ABI field without defaulting it away", async () => {
    const testCase = validCases.find(
      (candidate) => candidate.name === "manifest with optional environment authentication",
    );
    expect(testCase?.target).toBe("manifest");
    const manifest = await validateManifestDocument(testCase!.document, {
      schemaRoot: registryRoot,
    });
    expect(manifest.tools[0]).toMatchObject({
      name: "search",
      description: "Search text.",
      parameters: { type: "object" },
      risk: "read",
      parallel_safe: true,
      timeout_ms: 1000,
    });
  });
});

describe("real registry", () => {
  it("loads every indexed manifest through the shared loader", async () => {
    const index = await loadRegistryIndex(registryRoot);
    const names = Object.keys(index.integrations).sort();
    expect(names).toEqual(["echo", "fs", "http", "sqlite", "web"]);
    for (const name of names) {
      const manifest = await loadManifest(registryRoot, name, { index });
      expect(manifest.name).toBe(name);
      for (const tool of manifest.tools) {
        expect(tool.parameters).toEqual(expect.any(Object));
        expect(typeof tool.parallel_safe).toBe("boolean");
        if (tool.timeout_ms !== undefined) expect(tool.timeout_ms).toBeGreaterThan(0);
      }
    }
  });

  it("revalidates a caller-supplied index before using its fast path", async () => {
    const invalidIndex = structuredClone(await loadRegistryIndex(registryRoot));
    invalidIndex.integrations.echo!.stability = "preview" as never;

    const error = await capturedValidationError(() =>
      loadManifest(registryRoot, "echo", { index: invalidIndex }),
    );
    expect(error.normalized()).toEqual({
      code: "INTEGRATION_SCHEMA_INVALID",
      path: "/integrations/echo/stability",
    });
  });

  it("rejects an indexed manifest symlink that escapes the registry", async () => {
    const root = mkdtempSync(join(tmpdir(), "kaji-registry-link-"));
    const outside = mkdtempSync(join(tmpdir(), "kaji-registry-outside-"));
    try {
      writeFileSync(
        join(root, "index.json"),
        JSON.stringify({
          $schema: "./index.schema.json",
          version: "0.1.0",
          integrations: {
            escape: {
              manifest: "escape/manifest.json",
              stability: "experimental",
              runtimes: ["typescript"],
            },
          },
        }),
      );
      writeFileSync(
        join(outside, "manifest.json"),
        JSON.stringify({
          name: "escape",
          version: "0.1.0",
          namespace: "escape",
          description: "escape",
          auth: { kind: "none" },
          files: ["index.ts"],
          tools: [
            {
              name: "escape",
              description: "escape",
              parameters: {},
              risk: "read",
              parallel_safe: false,
            },
          ],
        }),
      );
      writeFileSync(join(outside, "index.ts"), "// outside\n");
      symlinkSync(outside, join(root, "escape"));

      const error = await capturedValidationError(() =>
        loadManifest(root, "escape", { schemaRoot: registryRoot }),
      );
      expect(error.normalized()).toEqual({
        code: "INTEGRATION_SCHEMA_INVALID",
        path: "/integrations/escape/manifest",
      });
    } finally {
      rmSync(root, { recursive: true, force: true });
      rmSync(outside, { recursive: true, force: true });
    }
  });

  it("rejects a referenced source symlink that escapes the manifest directory", async () => {
    const root = mkdtempSync(join(tmpdir(), "kaji-source-link-"));
    const outside = mkdtempSync(join(tmpdir(), "kaji-source-outside-"));
    try {
      mkdirSync(join(root, "linked"));
      writeFileSync(
        join(root, "index.json"),
        JSON.stringify({
          $schema: "./index.schema.json",
          version: "0.1.0",
          integrations: {
            linked: {
              manifest: "linked/manifest.json",
              stability: "experimental",
              runtimes: ["typescript"],
            },
          },
        }),
      );
      writeFileSync(
        join(root, "linked", "manifest.json"),
        JSON.stringify({
          name: "linked",
          version: "0.1.0",
          namespace: "linked",
          description: "linked",
          auth: { kind: "none" },
          files: ["index.ts"],
          tools: [
            {
              name: "linked",
              description: "linked",
              parameters: {},
              risk: "read",
              parallel_safe: false,
            },
          ],
        }),
      );
      writeFileSync(join(outside, "index.ts"), "// outside\n");
      symlinkSync(join(outside, "index.ts"), join(root, "linked", "index.ts"));

      const error = await capturedValidationError(() =>
        loadManifest(root, "linked", { schemaRoot: registryRoot }),
      );
      expect(error.normalized()).toEqual({
        code: "INTEGRATION_SCHEMA_INVALID",
        path: "/files/0",
      });
    } finally {
      rmSync(root, { recursive: true, force: true });
      rmSync(outside, { recursive: true, force: true });
    }
  });
});
