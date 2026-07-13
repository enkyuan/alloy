import { vi } from "vitest";

const OFFLINE = process.env.KAJI_OFFLINE_GATE === "1";
const ERROR = "KAJI offline gate blocked network access";

function blocked(): never {
  throw new Error(ERROR);
}

async function blockedAsync(): Promise<never> {
  throw new Error(ERROR);
}

if (OFFLINE) {
  globalThis.fetch = blockedAsync as unknown as typeof globalThis.fetch;
}

vi.mock("node:net", async (importOriginal) => {
  const original = await importOriginal<typeof import("node:net")>();
  if (!OFFLINE) return original;
  return { ...original, connect: blocked, createConnection: blocked };
});

vi.mock("node:dns", async (importOriginal) => {
  const original = await importOriginal<typeof import("node:dns")>();
  if (!OFFLINE) return original;
  return {
    ...original,
    getHostByAddr: blocked,
    lookup: blocked,
    lookupService: blocked,
    resolve: blocked,
    resolve4: blocked,
    resolve6: blocked,
    resolveAny: blocked,
    resolveCaa: blocked,
    resolveCname: blocked,
    resolveMx: blocked,
    resolveNaptr: blocked,
    resolveNs: blocked,
    resolvePtr: blocked,
    resolveSoa: blocked,
    resolveSrv: blocked,
    resolveTxt: blocked,
    reverse: blocked,
  };
});

vi.mock("node:dns/promises", async (importOriginal) => {
  const original = await importOriginal<typeof import("node:dns/promises")>();
  if (!OFFLINE) return original;
  return {
    ...original,
    lookup: blockedAsync,
    lookupService: blockedAsync,
    resolve: blockedAsync,
    resolve4: blockedAsync,
    resolve6: blockedAsync,
    resolveAny: blockedAsync,
    resolveCaa: blockedAsync,
    resolveCname: blockedAsync,
    resolveMx: blockedAsync,
    resolveNaptr: blockedAsync,
    resolveNs: blockedAsync,
    resolvePtr: blockedAsync,
    resolveSoa: blockedAsync,
    resolveSrv: blockedAsync,
    resolveTxt: blockedAsync,
    reverse: blockedAsync,
  };
});

vi.mock("node:http", async (importOriginal) => {
  const original = await importOriginal<typeof import("node:http")>();
  if (!OFFLINE) return original;
  return { ...original, get: blocked, request: blocked };
});

vi.mock("node:https", async (importOriginal) => {
  const original = await importOriginal<typeof import("node:https")>();
  if (!OFFLINE) return original;
  return { ...original, get: blocked, request: blocked };
});
