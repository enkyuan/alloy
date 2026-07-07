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
    expect(mvp).toContain("Plan 3 - Define the first-party integration catalog contract (implemented)");
    expect(mvp).not.toContain("Catalog contract still open");
    expect(mvp).not.toContain("no shared manifest/auth/credential shape");
  });
});
