import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, "../../..");

function read(path: string): string {
  return readFileSync(resolve(repoRoot, path), "utf8");
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
      "Keyed OpenAI live proof",
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
});
