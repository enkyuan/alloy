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
  it("defines privileged journal recovery and disposal boundaries", () => {
    const readme = read("kaji/ts/README.md");
    const production = read("docs/kaji/production-beta.md");
    const ordering = read("docs/kaji/concurrency-and-ordering.md");

    for (const source of [readme, production]) {
      const document = source.replace(/\s+/gu, " ");
      expect(document).toContain("privileged full-fidelity journal");
      expect(document).toContain("not redaction-safe");
      expect(document).toContain("preselected session ID");
      expect(document).toContain("exclusive `afterSequence` cursor");
      expect(document).toContain("page until an empty page");
      expect(document).toContain("reduce to an allowlist");
      expect(document).toContain("best-effort timing and correlation");
      expect(document).toContain("does not delete retained history");
    }

    for (const source of [readme, production, ordering]) {
      const document = source.replace(/\s+/gu, " ");
      expect(document).toContain("VM string zeroization");
      expect(document).toContain("stop ingress");
      expect(document).toContain("process-local");
    }

    const normalizedReadme = readme.replace(/\s+/gu, " ");
    const normalizedProduction = production.replace(/\s+/gu, " ");
    const normalizedOrdering = ordering.replace(/\s+/gu, " ");
    expect(normalizedReadme).toContain("failed turns have no `TurnResult`");
    expect(normalizedReadme).toContain("generic provider failures have no durable recovery code");
    expect(normalizedReadme).toContain("releaseSettled()");
    expect(normalizedReadme).toContain("host ledger cleanup");
    expect(normalizedReadme).toContain("pageHistory");
    expect(normalizedReadme).toContain("safeJournalEvidence");
    expect(normalizedReadme).toContain("append-only while retained");

    const recoveryBlock = [...readme.matchAll(/```ts\n([\s\S]*?)\n```/gu)]
      .map((match) => match[1] ?? "")
      .find((block) => block.includes("stopIngress(sessionId)"));
    expect(recoveryBlock, "missing runnable failure-recovery block").toBeDefined();
    const compactRecovery = recoveryBlock?.replace(/\s+/gu, "") ?? "";
    const recoverySteps = [
      "stopIngress(sessionId)",
      "awaitruntime.drainTools(10_000)",
      "awaitruntime.drainProviders(10_000)",
      "awaitpageHistory(runtime,sessionId)",
      "handleEvidenceExportError(evidenceError)",
      "awaitruntime.purgeSession(sessionId)",
      "handleOriginalError(failure.error)",
    ];
    let priorStep = -1;
    for (const step of recoverySteps) {
      const nextStep = compactRecovery.indexOf(step);
      expect(nextStep, `missing or misordered recovery step: ${step}`).toBeGreaterThan(priorStep);
      priorStep = nextStep;
    }
    expect(compactRecovery).toContain("}finally{awaitruntime.purgeSession(sessionId);}");

    const pythonQuickstart = snippet(production, "installed-quickstart:python", "python");
    const typescriptQuickstart = snippet(production, "installed-quickstart:typescript", "ts");
    expect(pythonQuickstart).toContain("event.turn_id == text.turn_id");
    expect(typescriptQuickstart).toContain("event.turn_id === text.turnId");

    const pythonOutput = pythonQuickstart
      .split("\n")
      .filter((line) => /\bprint\s*\(/u.test(line))
      .join("\n");
    const typescriptOutput = typescriptQuickstart
      .split("\n")
      .filter((line) => /\bconsole\.(?:log|info|debug|warn|error)\s*\(/u.test(line))
      .join("\n");
    expect(pythonOutput).not.toMatch(/session_id|turn_id|\.sequence|\.events/u);
    expect(typescriptOutput).not.toMatch(/sessionId|turnId|\.sequence|\.events/u);

    expect(normalizedProduction).toContain("Provider or timeout failure");
    expect(normalizedProduction).toContain("Ordinary terminal tool failure");
    expect(normalizedProduction).toContain("Mid-provider cooperative cancellation");
    expect(normalizedProduction).toContain("Failure-event append failure");
    expect(normalizedProduction).toContain("## TypeScript-only purge and accounting");
    expect(normalizedProduction).toContain(
      "ships no persistent event store or distributed coordinator",
    );
    expect(normalizedProduction).toContain("does not release-certify host implementations");
    expect(normalizedProduction).toContain("durability, deletion, and cross-process correctness");

    expect(normalizedOrdering).toContain("cursor did not advance");
    expect(normalizedOrdering).toContain("reset the cursor to `0` after purge");
    expect(normalizedOrdering).toContain("privileged journal warning");
    expect(normalizedOrdering).toContain("does not cancel already-active work");
  });

  it("keeps stable core, experimental, and not-ported surfaces explicit", () => {
    const combined = [
      read("kaji/RELEASE_MATRIX.md"),
      read("kaji/README.md"),
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

  it("keeps the two-entry catalog and experimental quarantine explicit", () => {
    const readme = read("kaji/ts/README.md");
    expect(readme).toContain("--allow-experimental");
    expect(readme).toContain("`echo` is the only beta catalog entry");
    expect(readme).toContain("`github` is the only experimental");
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
    const python = JSON.parse(read("kaji/src/kaji/integrations/registry/index.json")) as {
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

  it("typechecks and runs every current TypeScript migration snippet", () => {
    const migration = read("docs/kaji/migrating-to-beta.md");
    const names = [
      "docs-test:typescript-migration-after",
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
