import { mkdtempSync, readFileSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { buildProgram, isEntrypoint } from "../src/index.js";

const STANDALONE_COMMANDS = ["doctor", "gen", "info", "init", "mcp", "secret", "upgrade"];
const PACKAGE_VERSION = (
  JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")) as {
    version: string;
  }
).version;

describe("standalone CLI program", () => {
  it("exposes only the standalone cross-language command set", () => {
    const commands = buildProgram()
      .commands.map((command) => command.name())
      .sort();

    expect(commands).toEqual(STANDALONE_COMMANDS);
    expect(commands).not.toContain("add");
    expect(commands).not.toContain("replay");
  });

  it("reports package metadata and every command in help", () => {
    const program = buildProgram();
    const help = program.helpInformation();

    expect(program.name()).toBe("kaji");
    expect(program.version()).toBe(PACKAGE_VERSION);
    for (const command of STANDALONE_COMMANDS) expect(help).toContain(command);
  });

  it("documents the beta provider contract in init help", () => {
    const init = buildProgram().commands.find((command) => command.name() === "init");

    expect(init?.helpInformation()).toContain("mock|openai|anthropic");
    expect(init?.helpInformation()).not.toContain("gemini");
    expect(init?.helpInformation()).not.toContain("kimi");
  });

  it.runIf(process.platform !== "win32")("recognizes a symlinked binary entry path", () => {
    const directory = mkdtempSync(join(tmpdir(), "kaji-cli-entry-"));
    const symlink = join(directory, "kaji");
    symlinkSync(fileURLToPath(new URL("../src/index.ts", import.meta.url)), symlink);

    expect(isEntrypoint(symlink)).toBe(true);
  });
});
