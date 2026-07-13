import { createHash } from "node:crypto";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { describe, expect, it, vi } from "vitest";

import {
  _createMacOSKeychainTokenStorageForTest,
  _createSpawnKeychainProcessForTest,
  type KeychainProcess,
} from "../src/auth/keychain";
import type { OAuthCredentialRecord } from "../src/auth/oauth";

const principal = "User:123";
const service = "dev.kaji.oauth.gmail";
const account = createHash("sha256").update(`${service}\0${principal}`).digest("hex");
const record: OAuthCredentialRecord = Object.freeze({
  schemaVersion: 1,
  state: "active",
  tokens: Object.freeze({
    accessToken: "secret-access",
    refreshToken: "secret-refresh",
    expiresAtEpochMs: 1_700_000_000_000,
    grantedScopes: Object.freeze(["scope/a"]),
    tokenType: "Bearer",
  }),
});

class Process implements KeychainProcess {
  readonly calls: Array<{
    readonly args: readonly string[];
    readonly options: Readonly<{
      stdin?: string;
      signal: AbortSignal;
      timeoutMs: number;
      maxStdoutBytes: number;
    }>;
  }> = [];
  readonly results: Array<Readonly<{ code: number; stdout: string }>>;

  constructor(
    results: readonly Readonly<{ code: number; stdout: string }>[] = [{ code: 0, stdout: "" }],
  ) {
    this.results = [...results];
  }

  async run(
    args: readonly string[],
    options: Readonly<{
      stdin?: string;
      signal: AbortSignal;
      timeoutMs: number;
      maxStdoutBytes: number;
    }>,
  ): Promise<Readonly<{ code: number; stdout: string }>> {
    if (options.signal.aborted) throw options.signal.reason;
    this.calls.push({ args: [...args], options });
    return this.results.shift()!;
  }
}

const storage = (
  process: KeychainProcess,
  platform = "darwin",
  executable = true,
  integrationName = "gmail",
) => _createMacOSKeychainTokenStorageForTest({ process, platform, executable, integrationName });

describe("MacOSKeychainTokenStorage", () => {
  it("uses exact fixed argv, hashed account, and JSON stdin", async () => {
    const process = new Process();
    await storage(process).save(principal, record, new AbortController().signal);
    expect(process.calls[0]?.args).toEqual([
      "add-generic-password",
      "-a",
      account,
      "-s",
      service,
      "-U",
      "-w",
    ]);
    expect(JSON.parse(process.calls[0]?.options.stdin ?? "")).toMatchObject({
      tokens: { accessToken: "secret-access" },
    });
    expect(JSON.stringify(process.calls[0]?.args)).not.toContain(principal);
  });

  it("scopes service and account hashes by validated integration name", async () => {
    const gmailProcess = new Process();
    const calendarProcess = new Process();
    await storage(gmailProcess).save(principal, record, new AbortController().signal);
    await storage(calendarProcess, "darwin", true, "calendar").save(
      principal,
      record,
      new AbortController().signal,
    );

    const gmailArgs = gmailProcess.calls[0]!.args;
    const calendarArgs = calendarProcess.calls[0]!.args;
    expect(gmailArgs[gmailArgs.indexOf("-s") + 1]).toBe("dev.kaji.oauth.gmail");
    expect(calendarArgs[calendarArgs.indexOf("-s") + 1]).toBe("dev.kaji.oauth.calendar");
    expect(gmailArgs[gmailArgs.indexOf("-a") + 1]).toBe(account);
    expect(calendarArgs[calendarArgs.indexOf("-a") + 1]).toBe(
      createHash("sha256").update(`dev.kaji.oauth.calendar\0${principal}`).digest("hex"),
    );
    expect(calendarArgs[calendarArgs.indexOf("-a") + 1]).not.toBe(account);
  });

  it.each(["Calendar", "calendar.oauth", "a".repeat(129)])(
    "rejects invalid integration %s before platform or process side effects",
    (integrationName) => {
      const process = new Process();
      expect(() => storage(process, "linux", false, integrationName)).toThrowError(
        expect.objectContaining({ error_code: "INTEGRATION_POLICY_REJECTED" }),
      );
      expect(process.calls).toEqual([]);
    },
  );

  it("loads and deletes with fixed commands", async () => {
    const process = new Process([
      { code: 0, stdout: JSON.stringify(record) + "\n" },
      { code: 0, stdout: "" },
    ]);
    const keychain = storage(process);
    await expect(keychain.load(principal, new AbortController().signal)).resolves.toEqual(record);
    await keychain.delete(principal, new AbortController().signal);
    expect(process.calls[0]?.args).toEqual([
      "find-generic-password",
      "-a",
      account,
      "-s",
      service,
      "-w",
    ]);
    expect(process.calls[1]?.args).toEqual([
      "delete-generic-password",
      "-a",
      account,
      "-s",
      service,
    ]);
  });

  it("maps missing to undefined and corruption to a redacted auth error", async () => {
    await expect(
      storage(new Process([{ code: 44, stdout: "" }])).load(
        principal,
        new AbortController().signal,
      ),
    ).resolves.toBeUndefined();
    const corrupt = storage(new Process([{ code: 0, stdout: "private-corrupt" }]));
    let captured: unknown;
    try {
      await corrupt.load(principal, new AbortController().signal);
    } catch (error) {
      captured = error;
    }
    expect(captured).toMatchObject({
      error_code: "INTEGRATION_AUTH_ERROR",
      reason_code: "keychain_corrupt",
    });
    expect(String(captured)).not.toContain("private-corrupt");
  });

  it("rejects invalid principal and unsupported platform before process", async () => {
    const process = new Process();
    await expect(
      storage(process).load("bad@principal", new AbortController().signal),
    ).rejects.toMatchObject({ error_code: "INTEGRATION_POLICY_REJECTED" });
    await expect(
      storage(process, "linux").load(principal, new AbortController().signal),
    ).rejects.toMatchObject({
      error_code: "INTEGRATION_AUTH_ERROR",
      reason_code: "keychain_unsupported",
    });
    expect(process.calls).toEqual([]);
  });

  it("never retains token, stdout, or raw principal in errors", async () => {
    const process = new Process([{ code: 1, stdout: "secret-access" }]);
    let captured: unknown;
    try {
      await storage(process).save(principal, record, new AbortController().signal);
    } catch (error) {
      captured = error;
    }
    const rendered = String(captured) + JSON.stringify(captured);
    expect(rendered).not.toContain("secret-access");
    expect(rendered).not.toContain(principal);
  });

  it("accepts the exact record bound and rejects plus one", async () => {
    const wire = JSON.stringify(record);
    const exact = wire + " ".repeat(16 * 1024 - new TextEncoder().encode(wire).byteLength);
    await expect(
      storage(new Process([{ code: 0, stdout: exact }])).load(
        principal,
        new AbortController().signal,
      ),
    ).resolves.toEqual(record);
    await expect(
      storage(new Process([{ code: 0, stdout: exact + " " }])).load(
        principal,
        new AbortController().signal,
      ),
    ).rejects.toMatchObject({
      error_code: "INTEGRATION_AUTH_ERROR",
      reason_code: "keychain_corrupt",
    });
  });

  it("does not report a failed save before the process settles", async () => {
    class LateProcess implements KeychainProcess {
      readonly entered = Promise.withResolvers<void>();
      readonly release = Promise.withResolvers<void>();
      mutated = false;

      async run(
        _args: readonly string[],
        options: Readonly<{
          stdin?: string;
          signal: AbortSignal;
          timeoutMs: number;
          maxStdoutBytes: number;
        }>,
      ): Promise<Readonly<{ code: number; stdout: string }>> {
        this.entered.resolve();
        await new Promise<void>((resolve) =>
          options.signal.addEventListener("abort", () => resolve(), { once: true }),
        );
        await this.release.promise;
        this.mutated = true;
        throw new Error("private late failure");
      }
    }

    const process = new LateProcess();
    const controller = new AbortController();
    const pending = storage(process).save(principal, record, controller.signal);
    await process.entered.promise;
    controller.abort(new Error("abort-secret"));
    await Promise.resolve();
    let settled = false;
    void pending.then(
      () => {
        settled = true;
      },
      () => {
        settled = true;
      },
    );
    await Promise.resolve();
    expect(settled).toBe(false);
    process.release.resolve();
    await expect(pending).rejects.toMatchObject({ error_code: "INTEGRATION_AUTH_ERROR" });
    expect(process.mutated).toBe(true);
  });

  it("terms, kills, and reaps a spawned child before cancellation returns", async () => {
    vi.useFakeTimers();
    try {
      const signals: string[] = [];
      const child = new EventEmitter() as EventEmitter & {
        stdin: PassThrough;
        stdout: PassThrough;
        stderr: PassThrough;
        exitCode: number | null;
        signalCode: NodeJS.Signals | null;
        kill(signal: NodeJS.Signals): boolean;
      };
      child.stdin = new PassThrough();
      child.stdout = new PassThrough();
      child.stderr = new PassThrough();
      child.exitCode = null;
      child.signalCode = null;
      child.kill = (signal) => {
        signals.push(signal);
        if (signal === "SIGKILL") {
          child.signalCode = signal;
          queueMicrotask(() => child.emit("close", null));
        }
        return true;
      };
      const spawnChild = vi.fn(() => child as never);
      const process = _createSpawnKeychainProcessForTest(spawnChild);
      const controller = new AbortController();
      const pending = process.run(["delete-generic-password"], {
        signal: controller.signal,
        timeoutMs: 10_000,
        maxStdoutBytes: 16 * 1024 + 1,
      });
      const rejected = expect(pending).rejects.toThrow("Keychain process failed");
      controller.abort(new Error("abort-secret"));
      await Promise.resolve();
      expect(signals).toEqual(["SIGTERM"]);
      await vi.advanceTimersByTimeAsync(250);
      await rejected;
      expect(signals).toEqual(["SIGTERM", "SIGKILL"]);
      expect(spawnChild).toHaveBeenCalledWith("/usr/bin/security", ["delete-generic-password"], {
        shell: false,
        stdio: ["pipe", "pipe", "pipe"],
      });
    } finally {
      vi.useRealTimers();
    }
  });
});
