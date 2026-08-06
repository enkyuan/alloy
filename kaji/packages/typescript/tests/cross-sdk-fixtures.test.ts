import { readFileSync } from "node:fs";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const SDK_ROOT = fileURLToPath(new URL("../", import.meta.url));
const EXPORTER = fileURLToPath(new URL("../scripts/export_parity.ts", import.meta.url));
const SCENARIOS = fileURLToPath(
  new URL("../../../contracts/parity/scenarios.json", import.meta.url),
);
const TOOLS = new URL("../../../contracts/tools/", import.meta.url);
const SNAPSHOT_KEYS = [
  "events",
  "operation_trace",
  "provider_requests",
  "provider_responses",
  "replay",
  "result",
];

async function runExporter(poison: string): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    const subprocess = spawn("bun", ["run", EXPORTER], {
      cwd: SDK_ROOT,
      env: {
        ...process.env,
        OPENAI_API_KEY: poison,
        ANTHROPIC_API_KEY: poison,
        GOOGLE_API_KEY: poison,
        TZ: "UTC",
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    const stdout: Buffer[] = [];
    const stderr: Buffer[] = [];
    subprocess.stdout.on("data", (chunk: Buffer) => stdout.push(chunk));
    subprocess.stderr.on("data", (chunk: Buffer) => stderr.push(chunk));
    subprocess.on("error", reject);
    subprocess.on("close", (exitCode) => {
      const diagnostics = Buffer.concat(stderr).toString("utf8");
      try {
        expect(exitCode, diagnostics).toBe(0);
        resolve(Buffer.concat(stdout));
      } catch (error) {
        reject(error);
      }
    });
  });
}

describe("cross-SDK fixture exporter", () => {
  it("is byte-stable and covers every declared scenario", async () => {
    const first = await runExporter("must-not-be-read-a");
    const second = await runExporter("must-not-be-read-b");

    expect(first).toEqual(second);
    const exported = JSON.parse(new TextDecoder().decode(first));
    const contract = JSON.parse(readFileSync(SCENARIOS, "utf8"));
    expect(exported.scenarios.map((row: any) => row.id)).toEqual(
      contract.scenarios.map((row: any) => row.id),
    );
    expect(exported.scenarios).toHaveLength(67);
    for (const row of exported.scenarios) {
      expect(Object.keys(row.snapshot).sort()).toEqual(SNAPSHOT_KEYS);
    }
    const snapshots = new Map<string, any>(
      exported.scenarios.map((row: any) => [row.id, row.snapshot] as const),
    );
    for (const [scenarioId, service, action, cost] of [
      ["openai-non-stream", "openai", "request", 0.00001725],
      ["openai-stream", "openai", "stream", 0.00001725],
      ["anthropic-non-stream", "anthropic", "request", 0.00006],
      ["anthropic-stream", "anthropic", "stream", 0.00006],
    ] as const) {
      const result = snapshots.get(scenarioId)!.result;
      expect(result.cost_usd).toBe(cost);
      expect(result.provider_error).toEqual({
        type: "network",
        code: "PROVIDER_NETWORK_ERROR",
        service,
        action,
        status: null,
        retryable: true,
      });
    }
    expect(
      Object.fromEntries(
        [
          "replay-json-boolean",
          "replay-json-null",
          "replay-json-number",
          "replay-json-integral-float",
          "replay-json-negative-zero",
          "replay-json-exponent-boundaries",
          "replay-json-numeric-keys",
          "replay-json-safe-integer-boundary",
          "replay-json-utf16-keys",
          "replay-json-string",
          "replay-json-array",
        ].map((id) => [id, snapshots.get(id)!.result.tool_content]),
      ),
    ).toEqual({
      "replay-json-boolean": "true",
      "replay-json-null": "null",
      "replay-json-number": "7.5",
      "replay-json-integral-float": "1",
      "replay-json-negative-zero": "0",
      "replay-json-exponent-boundaries":
        "[0.000001,1.25e-7,4503599627370495.5,-4503599627370495.5]",
      "replay-json-numeric-keys": '{"10":"ten","2":"two"}',
      "replay-json-safe-integer-boundary": "9007199254740991",
      "replay-json-utf16-keys": '{"\u{10000}":"astral","\ue000":"bmp"}',
      "replay-json-string": '"café"',
      "replay-json-array": "[1,false,null]",
    });
    expect(snapshots.get("replay-json-unrepresentable-integer")!.result).toEqual({
      event_count: 3,
      rejection: "integer_outside_i_json_safe_range",
    });

    const referenced = contract.scenarios
      .filter((row: any) => row.kind === "tool-schema")
      .map((row: any) => `${row.fixtureFile}:${row.fixture}`)
      .sort();
    const canonical = ["conformance-valid.json", "conformance-invalid.json"]
      .flatMap((filename) =>
        JSON.parse(readFileSync(new URL(filename, TOOLS), "utf8")).cases.map(
          (fixture: any) => `${filename}:${fixture.name}`,
        ),
      )
      .sort();
    expect(referenced).toEqual(canonical);
  }, 30_000);

  it("does not read provider keys or construct network clients", () => {
    const source = readFileSync(EXPORTER, "utf8");

    for (const forbidden of [
      "OPENAI_API_KEY",
      "ANTHROPIC_API_KEY",
      "GOOGLE_API_KEY",
      "process.env",
      "new OpenAIProvider(",
      "new AnthropicProvider(",
      "fetch(",
      "expected-normalized.json",
    ]) {
      expect(source).not.toContain(forbidden);
    }
    expect(source).toContain("class FixtureOpenAIProvider extends OpenAIProvider");
    expect(source).toContain("class FixtureAnthropicProvider extends AnthropicProvider");
    expect(source).toContain("protected override async createClient()");
  });
});
