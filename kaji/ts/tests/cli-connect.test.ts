import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { runCli, type RunOptions } from "@/cli/index";
import type {
  GoogleOAuthClient,
  GoogleOAuthClientOptions,
  OAuthCredentialRecord,
  OAuthTokenStorage,
} from "@/auth/oauth";
import { IntegrationAuthError } from "@/integrations/errors";

const __dirname = dirname(fileURLToPath(import.meta.url));
const shippedSchemaRoot = join(__dirname, "..", "registry");
const principal = "tenant:user-123";
const connectCommand =
  "bun node_modules/@kaji/sdk/dist/cli/bin.js connect gmail --principal <stable-host-principal-id>";
const disconnectCommand =
  "bun node_modules/@kaji/sdk/dist/cli/bin.js disconnect gmail --principal <stable-host-principal-id>";

type CliOAuthClient = Pick<GoogleOAuthClient, "connect" | "disconnect">;

interface AuthRunOptions extends RunOptions {
  /** Closed environment seam: commands read only manifest-declared names. */
  env: Readonly<Record<string, string | undefined>>;
  signal: AbortSignal;
  keychainStorageFactory: () => OAuthTokenStorage;
  googleOAuthClientFactory: (options: GoogleOAuthClientOptions) => CliOAuthClient;
}

class FakeStorage implements OAuthTokenStorage {
  load(): Promise<OAuthCredentialRecord | undefined> {
    throw new Error("CLI must delegate credential I/O to the OAuth client");
  }

  save(): Promise<void> {
    throw new Error("CLI must delegate credential I/O to the OAuth client");
  }

  delete(): Promise<void> {
    throw new Error("CLI must delegate credential I/O to the OAuth client");
  }
}

class FakeClient implements CliOAuthClient {
  readonly connectCalls: Array<readonly [string, AbortSignal]> = [];
  readonly disconnectCalls: Array<
    readonly [string, AbortSignal, Readonly<{ forceLocal?: boolean }>]
  > = [];
  connectError?: unknown;
  disconnectError?: unknown;
  disconnectResult: Awaited<ReturnType<GoogleOAuthClient["disconnect"]>> = {
    localState: "deleted",
    remoteRevoked: true,
  };

  async connect(principalId: string, signal: AbortSignal): Promise<void> {
    this.connectCalls.push([principalId, signal]);
    if (this.connectError !== undefined) throw this.connectError;
  }

  async disconnect(
    principalId: string,
    signal: AbortSignal,
    options: Readonly<{ forceLocal?: boolean }> = {},
  ): ReturnType<GoogleOAuthClient["disconnect"]> {
    this.disconnectCalls.push([principalId, signal, options]);
    if (this.disconnectError !== undefined) throw this.disconnectError;
    return this.disconnectResult;
  }
}

function manifest(
  name: string,
  auth:
    | Readonly<{ kind: "none" }>
    | Readonly<{ kind: "env"; env: string }>
    | Readonly<{
        kind: "oauth";
        provider: string;
        clientIdEnv: string;
        clientSecretEnv?: string;
        scopes: readonly string[];
      }>,
): object {
  return {
    name,
    version: "0.1.0",
    namespace: name,
    description: `${name} fixture`,
    auth,
    files: [`${name}.ts`],
    tools: [
      {
        name: "ping",
        description: "fixture tool",
        parameters: {
          $schema: "https://json-schema.org/draft/2020-12/schema",
          type: "object",
          additionalProperties: false,
        },
        risk: "read",
        parallel_safe: true,
      },
    ],
  };
}

function writeRegistry(root: string): void {
  const manifests = {
    gmail: manifest("gmail", {
      kind: "oauth",
      provider: "google",
      clientIdEnv: "GOOGLE_CLIENT_ID",
      clientSecretEnv: "GOOGLE_CLIENT_SECRET",
      scopes: ["scope/read", "scope/write"],
    }),
    none: manifest("none", { kind: "none" }),
    token: manifest("token", { kind: "env", env: "PRIVATE_TOKEN" }),
    unsupported: manifest("unsupported", {
      kind: "oauth",
      provider: "github",
      clientIdEnv: "GITHUB_CLIENT_ID",
      scopes: ["scope/read"],
    }),
  };
  for (const [name, document] of Object.entries(manifests)) {
    mkdirSync(join(root, name), { recursive: true });
    writeFileSync(join(root, name, "manifest.json"), JSON.stringify(document));
    writeFileSync(join(root, name, `${name}.ts`), "export {};\n");
  }
  writeFileSync(
    join(root, "index.json"),
    JSON.stringify({
      $schema: "./index.schema.json",
      version: "0.1.0",
      integrations: Object.fromEntries(
        Object.keys(manifests).map((name) => [
          name,
          {
            manifest: `${name}/manifest.json`,
            stability: "experimental",
            runtimes: ["typescript"],
          },
        ]),
      ),
    }),
  );
  writeFileSync(
    join(root, "index.schema.json"),
    readFileSync(join(shippedSchemaRoot, "index.schema.json")),
  );
  const schema = readFileSync(join(shippedSchemaRoot, "schema.json"), "utf8").replace(
    '"provider": { "enum": ["google"] }',
    '"provider": { "enum": ["google", "github"] }',
  );
  writeFileSync(join(root, "schema.json"), schema);
}

function trackedEnvironment(
  values: Readonly<Record<string, string | undefined>>,
  reads: string[],
): Readonly<Record<string, string | undefined>> {
  return new Proxy(Object.create(null) as Record<string, string | undefined>, {
    get(_target, property) {
      if (typeof property !== "string") return undefined;
      reads.push(property);
      return values[property];
    },
    ownKeys() {
      throw new Error("CLI must not enumerate the environment");
    },
  });
}

describe("kaji connect and disconnect", () => {
  let temp: string;
  let registryRoot: string;
  let stdout: string[];
  let stderr: string[];
  let envReads: string[];
  let storage: FakeStorage;
  let client: FakeClient;
  let storageFactoryCalls: number;
  let clientOptions: GoogleOAuthClientOptions[];
  let controller: AbortController;

  beforeEach(() => {
    temp = mkdtempSync(join(tmpdir(), "kaji-cli-connect-"));
    registryRoot = join(temp, "registry");
    mkdirSync(registryRoot);
    writeRegistry(registryRoot);
    stdout = [];
    stderr = [];
    envReads = [];
    storage = new FakeStorage();
    client = new FakeClient();
    storageFactoryCalls = 0;
    clientOptions = [];
    controller = new AbortController();
  });

  afterEach(() => rmSync(temp, { recursive: true, force: true }));

  function options(
    env: Readonly<Record<string, string | undefined>> = trackedEnvironment(
      {
        GOOGLE_CLIENT_ID: "private-client-id",
        GOOGLE_CLIENT_SECRET: "private-client-secret",
      },
      envReads,
    ),
  ): AuthRunOptions {
    return {
      registryRoot,
      schemaRoot: registryRoot,
      log: (message) => stdout.push(message),
      err: (message) => stderr.push(message),
      env,
      signal: controller.signal,
      keychainStorageFactory: () => {
        storageFactoryCalls += 1;
        return storage;
      },
      googleOAuthClientFactory: (constructed) => {
        clientOptions.push(constructed);
        return client;
      },
    };
  }

  function output(): string {
    return [...stdout, ...stderr].join("\n");
  }

  it("prints the installed package owner/version and owns both commands", async () => {
    const code = await runCli(["--help"], options());

    expect(code).toBe(0);
    expect(stdout[0]).toBe("kaji (@kaji/sdk) 0.2.0-beta.1");
    expect(output()).toContain("connect");
    expect(output()).toContain("disconnect");
    expect(envReads).toEqual([]);
    expect(storageFactoryCalls).toBe(0);
  });

  it.each([
    [["connect"], "usage: kaji connect <name> --principal <stable-host-principal-id>"],
    [["connect", "gmail"], "usage: kaji connect <name> --principal <stable-host-principal-id>"],
    [
      ["connect", "gmail", "--principal", principal, "--principal", "other"],
      "usage: kaji connect <name> --principal <stable-host-principal-id>",
    ],
    [
      ["connect", "gmail", "--principal", principal, "--force-local"],
      "usage: kaji connect <name> --principal <stable-host-principal-id>",
    ],
    [
      ["disconnect"],
      "usage: kaji disconnect <name> --principal <stable-host-principal-id> [--force-local]",
    ],
    [
      ["disconnect", "gmail", "--principal", principal, "--unknown"],
      "usage: kaji disconnect <name> --principal <stable-host-principal-id> [--force-local]",
    ],
  ])("rejects malformed arguments as usage before side effects: %j", async (argv, usage) => {
    const code = await runCli(argv, options());

    expect(code).toBe(2);
    expect(output()).toContain(usage);
    expect(envReads).toEqual([]);
    expect(storageFactoryCalls).toBe(0);
    expect(clientOptions).toEqual([]);
  });

  it("validates the principal before registry, environment, or auth construction", async () => {
    const opts = options();
    opts.registryRoot = join(temp, "must-not-be-read");
    opts.schemaRoot = opts.registryRoot;

    const code = await runCli(
      ["connect", "gmail", "--principal", "private@invalid-principal"],
      opts,
    );

    expect(code).toBe(1);
    expect(output()).toContain("INTEGRATION_POLICY_REJECTED");
    expect(output()).not.toContain("private@invalid-principal");
    expect(envReads).toEqual([]);
    expect(storageFactoryCalls).toBe(0);
    expect(clientOptions).toEqual([]);
  });

  it.each([
    ["missing", "Unknown integration"],
    ["none", "OAuth authentication"],
    ["token", "OAuth authentication"],
    ["unsupported", "Google OAuth"],
  ])("rejects %s before environment or auth construction", async (name, expected) => {
    const code = await runCli(["connect", name, "--principal", principal], options());

    expect(code).toBe(1);
    expect(output()).toContain(expected);
    expect(output()).not.toContain(principal);
    expect(envReads).toEqual([]);
    expect(storageFactoryCalls).toBe(0);
    expect(clientOptions).toEqual([]);
  });

  it("reads only declared credential names and rejects a missing client ID before auth construction", async () => {
    const env = trackedEnvironment({ GOOGLE_CLIENT_SECRET: "private-secret" }, envReads);
    const code = await runCli(["connect", "gmail", "--principal", principal], options(env));

    expect(code).toBe(1);
    expect(envReads).toEqual(["GOOGLE_CLIENT_ID"]);
    expect(storageFactoryCalls).toBe(0);
    expect(clientOptions).toEqual([]);
    expect(output()).toContain("INTEGRATION_AUTH_REQUIRED: GOOGLE_CLIENT_ID is not set.");
    expect(output()).toContain("Create a Google Desktop OAuth client");
    expect(output()).toContain(connectCommand);
    expect(output()).not.toContain(principal);
    expect(output()).not.toContain("private-secret");
  });

  it.each([
    [
      new IntegrationAuthError("keychain_missing"),
      "The Keychain command could not be found.",
      "/usr/bin/security",
    ],
    [
      new IntegrationAuthError("keychain_unsupported"),
      "This host cannot provide the required macOS Keychain boundary.",
      "supported macOS host",
    ],
  ])(
    "renders storage construction failures without constructing a client",
    async (error, cause, fix) => {
      const opts = options();
      opts.keychainStorageFactory = () => {
        storageFactoryCalls += 1;
        throw error;
      };

      const code = await runCli(["connect", "gmail", "--principal", principal], opts);

      expect(code).toBe(1);
      expect(storageFactoryCalls).toBe(1);
      expect(clientOptions).toEqual([]);
      expect(output()).toContain("Problem:");
      expect(output()).toContain(`Cause: ${cause}`);
      expect(output()).toContain("Fix:");
      expect(output()).toContain(fix);
      expect(output()).not.toContain(principal);
    },
  );

  it("constructs Task 5 with manifest credentials and delegates explicit connect", async () => {
    const opts = options();
    const code = await runCli(["connect", "gmail", "--principal", principal], opts);

    expect(code).toBe(0);
    expect(envReads).toEqual(["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]);
    expect(storageFactoryCalls).toBe(1);
    expect(clientOptions).toEqual([
      {
        clientId: "private-client-id",
        clientSecret: "private-client-secret",
        scopes: ["scope/read", "scope/write"],
        storage,
      },
    ]);
    expect(client.connectCalls).toEqual([[principal, controller.signal]]);
    expect(client.disconnectCalls).toEqual([]);
    expect(stdout).toEqual([
      "Connected gmail for the requested principal.",
      "Stored refresh credentials in macOS Keychain service dev.kaji.oauth.gmail.",
    ]);
    expect(output()).not.toContain(principal);
    expect(output()).not.toContain("private-client-id");
    expect(output()).not.toContain("private-client-secret");
  });

  it("disconnect reads no environment or client metadata and delegates a pending record", async () => {
    const env = trackedEnvironment({}, envReads);
    client.disconnectResult = { localState: "revocation_pending", remoteRevoked: false };

    const code = await runCli(["disconnect", "gmail", "--principal", principal], options(env));

    expect(code).toBe(1);
    expect(envReads).toEqual([]);
    expect(storageFactoryCalls).toBe(1);
    expect(clientOptions).toEqual([
      {
        scopes: ["scope/read", "scope/write"],
        storage,
      },
    ]);
    expect(client.disconnectCalls).toEqual([[principal, controller.signal, { forceLocal: false }]]);
    expect(output()).toContain("revocation is pending");
    expect(output()).toContain(disconnectCommand);
    expect(output()).toContain("--force-local");
    expect(output()).toContain("Google Account");
    expect(output()).not.toContain(principal);
  });

  it("passes explicit force-local and warns that remote access may remain", async () => {
    client.disconnectResult = { localState: "deleted", remoteRevoked: false };

    const code = await runCli(
      ["disconnect", "gmail", "--principal", principal, "--force-local"],
      options(trackedEnvironment({}, envReads)),
    );

    expect(code).toBe(0);
    expect(envReads).toEqual([]);
    expect(client.disconnectCalls).toEqual([[principal, controller.signal, { forceLocal: true }]]);
    expect(output()).toContain("Deleted the local gmail grant");
    expect(output()).toContain("remote access may remain");
    expect(output()).toContain("Google Account");
    expect(output()).not.toContain(principal);
  });

  it.each(["connect", "disconnect"])(
    "maps %s cancellation to bounded problem, cause, and package-qualified fix",
    async (command) => {
      const privateReason = `cancelled for ${principal} using private-client-secret`;
      const cancellation = new DOMException(privateReason, "AbortError");
      if (command === "connect") client.connectError = cancellation;
      else client.disconnectError = cancellation;

      const code = await runCli([command, "gmail", "--principal", principal], options());

      expect(code).toBe(1);
      expect(output()).toContain("Problem: Gmail authorization was cancelled.");
      expect(output()).toContain(
        `Cause: The ${command} operation was cancelled before completion.`,
      );
      expect(output()).toContain(
        `Fix: Rerun \`bun node_modules/@kaji/sdk/dist/cli/bin.js ${command} gmail --principal <stable-host-principal-id>\`.`,
      );
      expect(output()).not.toContain(privateReason);
      expect(output()).not.toContain(principal);
      expect(output()).not.toContain("private-client-secret");
    },
  );

  it("renders only closed Task 5 recovery fields and never an exception message", async () => {
    const error = new IntegrationAuthError("keychain_locked");
    error.message = `${principal} private-client-id private-client-secret provider-response`;
    client.connectError = error;

    const code = await runCli(["connect", "gmail", "--principal", principal], options());

    expect(code).toBe(1);
    expect(output()).toContain("Problem: The macOS Keychain is locked.");
    expect(output()).toContain(
      "Cause: The stored integration grant cannot be read while Keychain is locked.",
    );
    expect(output()).toContain("Fix: Unlock the login Keychain and retry.");
    expect(output()).not.toContain(principal);
    expect(output()).not.toContain("private-client-id");
    expect(output()).not.toContain("private-client-secret");
    expect(output()).not.toContain("provider-response");
  });
});
