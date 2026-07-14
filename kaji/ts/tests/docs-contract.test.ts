import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, "../../..");
const packageRoot = resolve(repoRoot, "kaji/ts");

function read(path: string): string {
  return readFileSync(resolve(repoRoot, path), "utf8");
}

function snippet(document: string, name: string, language: string): string {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern =
    "<!-- " +
    escaped +
    ":start -->\\s*`{3}" +
    language +
    "\\n([\\s\\S]*?)\\n`{3}\\s*<!-- " +
    escaped +
    ":end -->";
  const match = document.match(new RegExp(pattern));
  expect(match, `missing ${name}`).not.toBeNull();
  return match?.[1] ?? "";
}

describe("cross-SDK release matrix docs", () => {
  it("keeps stable core, experimental, and not-ported surfaces explicit", () => {
    const combined = [
      read("kaji/RELEASE_MATRIX.md"),
      read("kaji/sdk/README.md"),
      read("kaji/ts/README.md"),
      read("docs/MVP.md"),
    ].join("\n");

    for (const phrase of [
      "Stable core",
      "Experimental Python-only",
      "TypeScript Not Ported",
      "OpenAI-compatible factories",
      "Redis realtime/history",
      "voice/TTS",
      "DocumentRAG",
      "Keyed OpenAI + Anthropic proof",
      "gpt-5.4-mini",
      "Promotion criteria",
      "TS not ported",
    ]) {
      expect(combined).toContain(phrase);
    }

    const tsReadme = read("kaji/ts/README.md");
    expect(tsReadme).toContain("TS not ported");
    expect(tsReadme).toContain("OpenAI-compatible factories");
  });

  it("does not describe the manifest contract as missing", () => {
    const mvp = read("docs/MVP.md");

    expect(mvp).toContain("Catalog contract implemented");
    expect(mvp).toContain(
      "Plan 3 - Define the first-party integration catalog contract (implemented)",
    );
    expect(mvp).not.toContain("Catalog contract still open");
    expect(mvp).not.toContain("no shared manifest/auth/credential shape");
  });

  it("keeps experimental catalog quarantine and transport ownership explicit", () => {
    const readme = read("kaji/ts/README.md");
    expect(readme).toContain("--allow-experimental");
    expect(readme).toContain("direct-import templates outside the beta guarantee");
    expect(readme).toContain("application-owned bound transport or egress proxy");
    expect(readme).toContain("does not provide a native");
  });

  it("matches the machine-readable beta feature tiers exactly", () => {
    const tiers = JSON.parse(read("kaji/contracts/feature-tiers-v1.json")) as Record<
      "stable" | "experimental",
      Array<{ id: string; surface: string }>
    >;
    const matrix = read("kaji/RELEASE_MATRIX.md");

    for (const tier of ["stable", "experimental"] as const) {
      const marker = matrix.match(new RegExp(`<!-- beta-${tier}:\\s*([^>]*) -->`));
      expect(marker).not.toBeNull();
      const actual = (marker?.[1] ?? "")
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean)
        .sort();
      expect(actual).toEqual(tiers[tier].map(({ id }) => id).sort());
    }

    const stableSection = matrix.split("## Stable Core", 2)[1]?.split("\n## ", 1)[0] ?? "";
    for (const { surface } of tiers.stable) {
      expect(stableSection).toContain(`| ${surface} | Stable core | Stable core |`);
    }
  });

  it("matches both integration registry stability indexes", () => {
    const matrix = read("kaji/RELEASE_MATRIX.md");
    const python = JSON.parse(read("kaji/sdk/src/kaji/integrations/registry/index.json")) as {
      integrations: Record<string, { stability: string; runtimes: string[] }>;
    };
    const typescript = JSON.parse(read("kaji/ts/registry/index.json")) as {
      integrations: Record<string, { stability: string; runtimes: string[] }>;
    };
    const entries = { ...typescript.integrations, ...python.integrations };

    for (const [name, entry] of Object.entries(entries)) {
      expect(matrix).toContain(`| ${name} | ${entry.stability} | ${entry.runtimes.join(", ")} |`);
    }
  });

  it("typechecks and runs every TypeScript migration before/after snippet", () => {
    const migration = read("docs/kaji/migrating-to-beta.md");
    const names = [
      "docs-test:typescript-migration-before",
      "docs-test:typescript-migration-after",
      "docs-test:typescript-replay-before",
      "docs-test:typescript-replay-after",
      "docs-test:typescript-approval-before",
      "docs-test:typescript-approval-after",
      "docs-test:typescript-risk-context-before",
      "docs-test:typescript-risk-context-after",
      "docs-test:typescript-cursor-before",
      "docs-test:typescript-cursor-after",
      "docs-test:typescript-zod-before",
      "docs-test:typescript-zod-after",
    ];
    const workdir = mkdtempSync(resolve(packageRoot, ".docs-contract-"));
    try {
      for (const [index, name] of names.entries()) {
        writeFileSync(resolve(workdir, `${index}.mts`), snippet(migration, name, "ts"));
      }
      writeFileSync(
        resolve(workdir, "tsconfig.json"),
        JSON.stringify({
          extends: "../tsconfig.json",
          compilerOptions: { noEmit: true },
          include: ["*.mts"],
        }),
      );
      execFileSync(
        "node",
        [resolve(packageRoot, "node_modules/typescript/bin/tsc"), "--project", "tsconfig.json"],
        { cwd: workdir, stdio: "inherit" },
      );
      for (const index of names.keys()) {
        execFileSync("bun", [resolve(workdir, `${index}.mts`)], {
          cwd: packageRoot,
          stdio: "pipe",
        });
      }
    } finally {
      rmSync(workdir, { recursive: true, force: true });
    }
  }, 30_000);

  it("executes manifest and index migrations as invalid/valid schema pairs", () => {
    const migration = read("docs/kaji/migrating-to-beta.md");
    const manifestBefore = JSON.parse(snippet(migration, "docs-test:manifest-before", "json"));
    const manifestAfter = JSON.parse(snippet(migration, "docs-test:manifest-after", "json"));
    const indexBefore = JSON.parse(snippet(migration, "docs-test:index-before", "json"));
    const indexAfter = JSON.parse(snippet(migration, "docs-test:index-after", "json"));
    const ajv = new Ajv2020({ allErrors: true, strict: true });
    addFormats(ajv);
    const validateManifest = ajv.compile(
      JSON.parse(read("kaji/contracts/integrations/manifest.schema.json")),
    );
    const validateIndex = ajv.compile(
      JSON.parse(read("kaji/contracts/integrations/index.schema.json")),
    );

    expect(validateManifest(manifestBefore)).toBe(false);
    expect(validateManifest(manifestAfter)).toBe(true);
    expect(validateIndex(indexBefore)).toBe(false);
    expect(validateIndex(indexAfter)).toBe(true);
  });
});
