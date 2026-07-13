import { createHash } from "node:crypto";
import { accessSync, constants } from "node:fs";
import { platform as hostPlatform } from "node:os";
import { spawn } from "node:child_process";

import { IntegrationAuthError, IntegrationPolicyError } from "@/integrations/errors";
import {
  canonicalOAuthCredentialJson,
  snapshotOAuthCredentialRecord,
  validateOAuthPrincipal,
  type OAuthCredentialRecord,
  type OAuthTokenStorage,
} from "@/auth/oauth";

const SECURITY = "/usr/bin/security";
const INTEGRATION_NAME = /^[a-z][a-z0-9_-]*$/;
const MAX_INTEGRATION_NAME_LENGTH = 128;
const TIMEOUT_MS = 10_000;
const MAX_STDOUT_BYTES = 16 * 1024 + 1;
const MAX_STDERR_BYTES = 8 * 1024;
const TERM_GRACE_MS = 250;

export interface KeychainProcess {
  run(
    args: readonly string[],
    options: Readonly<{
      stdin?: string;
      signal: AbortSignal;
      timeoutMs: number;
      maxStdoutBytes: number;
    }>,
  ): Promise<Readonly<{ code: number; stdout: string }>>;
}

type SpawnChild = (
  command: string,
  args: readonly string[],
  options: Readonly<{ shell: false; stdio: readonly ["pipe", "pipe", "pipe"] }>,
) => ReturnType<typeof spawn>;

class ProcessFailure extends Error {
  constructor(readonly kind: "cancelled" | "timeout" | "overflow" | "failed") {
    super("Keychain process failed");
  }
}

class SpawnKeychainProcess implements KeychainProcess {
  constructor(private readonly spawnChild: SpawnChild = spawn as SpawnChild) {}

  run(
    args: readonly string[],
    options: Readonly<{
      stdin?: string;
      signal: AbortSignal;
      timeoutMs: number;
      maxStdoutBytes: number;
    }>,
  ): Promise<Readonly<{ code: number; stdout: string }>> {
    if (options.signal.aborted) return Promise.reject(new ProcessFailure("cancelled"));
    return new Promise((resolve, reject) => {
      let child: ReturnType<typeof spawn>;
      try {
        child = this.spawnChild(SECURITY, args, {
          shell: false,
          stdio: ["pipe", "pipe", "pipe"],
        });
      } catch {
        reject(new ProcessFailure("failed"));
        return;
      }
      const stdout: Buffer[] = [];
      let stdoutBytes = 0;
      let stderrBytes = 0;
      let failure: ProcessFailure | undefined;
      let grace: ReturnType<typeof setTimeout> | undefined;
      const terminate = (next: ProcessFailure) => {
        if (failure === undefined) failure = next;
        if (child.exitCode !== null || child.signalCode !== null) return;
        child.kill("SIGTERM");
        grace ??= setTimeout(() => {
          if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
        }, TERM_GRACE_MS);
      };
      child.stdout!.on("data", (chunk: Buffer) => {
        stdoutBytes += chunk.byteLength;
        if (stdoutBytes > options.maxStdoutBytes) terminate(new ProcessFailure("overflow"));
        else stdout.push(chunk);
      });
      child.stderr!.on("data", (chunk: Buffer) => {
        stderrBytes += chunk.byteLength;
        if (stderrBytes > MAX_STDERR_BYTES) terminate(new ProcessFailure("overflow"));
      });
      const onAbort = () => terminate(new ProcessFailure("cancelled"));
      options.signal.addEventListener("abort", onAbort, { once: true });
      const timeout = setTimeout(() => terminate(new ProcessFailure("timeout")), options.timeoutMs);
      child.once("error", () => terminate(new ProcessFailure("failed")));
      child.once("close", (code) => {
        clearTimeout(timeout);
        if (grace !== undefined) clearTimeout(grace);
        options.signal.removeEventListener("abort", onAbort);
        if (failure !== undefined) {
          reject(failure);
          return;
        }
        try {
          resolve({
            code: code ?? 1,
            stdout: new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(stdout)),
          });
        } catch {
          reject(new ProcessFailure("overflow"));
        }
      });
      child.stdin!.once("error", () => terminate(new ProcessFailure("failed")));
      child.stdin!.end(options.stdin);
    });
  }
}

function executable(): boolean {
  try {
    accessSync(SECURITY, constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

function serviceFor(integrationName: string): string {
  if (
    typeof integrationName !== "string" ||
    integrationName.length > MAX_INTEGRATION_NAME_LENGTH ||
    !INTEGRATION_NAME.test(integrationName)
  ) {
    throw new IntegrationPolicyError();
  }
  return `dev.kaji.oauth.${integrationName}`;
}

function accountFor(service: string, principalId: string): string {
  principalId = validateOAuthPrincipal(principalId);
  return createHash("sha256").update(`${service}\0${principalId}`, "utf8").digest("hex");
}

export class MacOSKeychainTokenStorage implements OAuthTokenStorage {
  private readonly process: KeychainProcess;
  private readonly platform: string;
  private readonly executable: boolean;
  private readonly service: string;

  constructor(integrationName = "gmail") {
    this.service = serviceFor(integrationName);
    this.process = new SpawnKeychainProcess();
    this.platform = hostPlatform();
    this.executable = executable();
  }

  /** @internal Source-relative tests only. */
  static _create(options: {
    process: KeychainProcess;
    platform: string;
    executable: boolean;
    integrationName?: string;
  }): MacOSKeychainTokenStorage {
    const service = serviceFor(options.integrationName ?? "gmail");
    const storage = Object.create(MacOSKeychainTokenStorage.prototype) as MacOSKeychainTokenStorage;
    Object.defineProperties(storage, {
      process: { value: options.process },
      platform: { value: options.platform },
      executable: { value: options.executable },
      service: { value: service },
    });
    return storage;
  }

  async load(principalId: string, signal: AbortSignal): Promise<OAuthCredentialRecord | undefined> {
    const account = this.preflight(principalId);
    const result = await this.run(
      ["find-generic-password", "-a", account, "-s", this.service, "-w"],
      { signal },
    );
    if (result.code === 44) return undefined;
    if (result.code !== 0) throw new IntegrationAuthError("keychain_locked");
    const output = result.stdout.endsWith("\n") ? result.stdout.slice(0, -1) : result.stdout;
    try {
      if (new TextEncoder().encode(output).byteLength > 16 * 1024) throw new Error();
      return snapshotOAuthCredentialRecord(JSON.parse(output) as unknown);
    } catch {
      throw new IntegrationAuthError("keychain_corrupt");
    }
  }

  async save(
    principalId: string,
    record: OAuthCredentialRecord,
    signal: AbortSignal,
  ): Promise<void> {
    const account = this.preflight(principalId);
    const stdin = canonicalOAuthCredentialJson(record);
    const result = await this.run(
      ["add-generic-password", "-a", account, "-s", this.service, "-U", "-w"],
      { signal, stdin },
    );
    if (result.code !== 0) throw new IntegrationAuthError("keychain_locked");
  }

  async delete(principalId: string, signal: AbortSignal): Promise<void> {
    const account = this.preflight(principalId);
    const result = await this.run(["delete-generic-password", "-a", account, "-s", this.service], {
      signal,
    });
    if (result.code !== 0 && result.code !== 44) {
      throw new IntegrationAuthError("keychain_locked");
    }
  }

  private preflight(principalId: string): string {
    const account = accountFor(this.service, principalId);
    if (this.platform !== "darwin" || !this.executable) {
      throw new IntegrationAuthError("keychain_unsupported");
    }
    return account;
  }

  private async run(
    args: readonly string[],
    options: Readonly<{ signal: AbortSignal; stdin?: string }>,
  ): Promise<Readonly<{ code: number; stdout: string }>> {
    try {
      return await this.process.run(args, {
        ...options,
        timeoutMs: TIMEOUT_MS,
        maxStdoutBytes: MAX_STDOUT_BYTES,
      });
    } catch (error) {
      if (error instanceof ProcessFailure && error.kind === "cancelled") {
        throw new DOMException("Keychain operation cancelled", "AbortError");
      }
      if (error instanceof ProcessFailure && error.kind === "overflow") {
        throw new IntegrationAuthError("keychain_corrupt");
      }
      throw new IntegrationAuthError("keychain_locked");
    }
  }
}

/** @internal Source-relative deterministic tests only. */
export function _createMacOSKeychainTokenStorageForTest(options: {
  process: KeychainProcess;
  platform: string;
  executable: boolean;
  integrationName?: string;
}): MacOSKeychainTokenStorage {
  return MacOSKeychainTokenStorage._create(options);
}

/** @internal Source-relative deterministic process-owner tests only. */
export function _createSpawnKeychainProcessForTest(spawnChild: SpawnChild): KeychainProcess {
  return new SpawnKeychainProcess(spawnChild);
}
