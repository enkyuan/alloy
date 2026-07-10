import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const __dirname = dirname(fileURLToPath(import.meta.url));
const contractPath = resolve(__dirname, "../../contracts/beta-core-v1.json");
const canonicalPath = resolve(__dirname, "../../contracts/beta-core-v1.json");
const packagedPath = resolve(__dirname, "../contracts/beta-core-v1.json");

describe("production-beta contract", () => {
  it("pins the production-beta compatibility defaults", () => {
    const contract = JSON.parse(readFileSync(contractPath, "utf8"));

    expect(contract.runtime).toMatchObject({
      sameSessionTurns: "serialized",
      maxToolIterations: 5,
      contextWindowTurns: 32,
    });
    expect(contract.tools).toMatchObject({ maxConcurrency: 4, timeoutMs: 30_000 });
    expect(contract.events).toMatchObject({
      subscriberQueueCapacity: 1024,
      inMemoryStoreMaxEventsPerSession: 10_000,
    });
  });

  it("ships a byte-identical package copy", () => {
    expect(readFileSync(packagedPath)).toEqual(readFileSync(canonicalPath));
  });
});
