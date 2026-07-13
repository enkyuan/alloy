import { GoogleOAuthClient, validateOAuthPrincipal } from "@/auth/oauth";
import { MacOSKeychainTokenStorage } from "@/auth/keychain";
import type { RunOptions } from "@/cli/index";
import { TYPESCRIPT_SDK_CLI } from "@/cli/package-identity";
import { closedRecoveryFields, recoveryForReason } from "@/integrations/recovery";
import {
  formatIntegrationError,
  loadManifest,
  loadRegistryIndex,
  type IntegrationAuth,
  type LoadedIntegrationManifest,
} from "@/integrations/registry-loader";

export type OAuthLoadedManifest = Omit<LoadedIntegrationManifest, "auth"> & {
  readonly auth: Extract<IntegrationAuth, { kind: "oauth" }>;
};

export interface AuthArgs {
  readonly name: string;
  readonly principal: string;
  readonly forceLocal: boolean;
}

export const CONNECT_USAGE = "usage: kaji connect <name> --principal <stable-host-principal-id>";

export function parseAuthArgs(
  rest: readonly string[],
  allowForceLocal: boolean,
): AuthArgs | undefined {
  let name: string | undefined;
  let principal: string | undefined;
  let forceLocal = false;
  for (let index = 0; index < rest.length; index++) {
    const argument = rest[index]!;
    if (argument === "--principal") {
      if (principal !== undefined) return undefined;
      const value = rest[index + 1];
      if (value === undefined || value.startsWith("--")) return undefined;
      principal = value;
      index++;
    } else if (argument === "--force-local" && allowForceLocal) {
      if (forceLocal) return undefined;
      forceLocal = true;
    } else if (argument.startsWith("-") || name !== undefined) {
      return undefined;
    } else {
      name = argument;
    }
  }
  if (name === undefined || principal === undefined) return undefined;
  return { name, principal, forceLocal };
}

export function qualifiedAuthCommand(action: "connect" | "disconnect", name: string): string {
  return `${TYPESCRIPT_SDK_CLI} ${action} ${name} ` + "--principal <stable-host-principal-id>";
}

export async function oauthManifest(name: string, opts: RunOptions): Promise<OAuthLoadedManifest> {
  const index = await loadRegistryIndex(opts.registryRoot, { schemaRoot: opts.schemaRoot });
  const manifest = await loadManifest(opts.registryRoot, name, {
    schemaRoot: opts.schemaRoot,
    index,
  });
  if (manifest.auth.kind !== "oauth") {
    throw new Error(`Integration '${name}' does not use OAuth authentication.`);
  }
  if (manifest.auth.provider !== "google") {
    throw new Error(`Integration '${name}' does not use Google OAuth.`);
  }
  return manifest as OAuthLoadedManifest;
}

export function renderClosedRecovery(
  error: unknown,
  command: string,
  output: (message: string) => void,
): boolean {
  const fields = closedRecoveryFields(error);
  if (fields === undefined) return false;
  const recovery = recoveryForReason(fields.reason_code);
  output(`Problem: ${recovery.problem}`);
  output(`Cause: ${recovery.cause}`);
  output(`Fix: ${recovery.fix}`);
  output(`Command: ${command}`);
  return true;
}

export async function withAuthSignal<T>(
  opts: RunOptions,
  operation: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  if (opts.signal !== undefined) return operation(opts.signal);
  const controller = new AbortController();
  const cancel = () => controller.abort(new DOMException("CLI auth cancelled", "AbortError"));
  process.once("SIGINT", cancel);
  process.once("SIGTERM", cancel);
  try {
    return await operation(controller.signal);
  } finally {
    process.removeListener("SIGINT", cancel);
    process.removeListener("SIGTERM", cancel);
  }
}

function storage(opts: RunOptions, integrationName: string, principal: string) {
  if (opts.keychainStorageFactory !== undefined) {
    return opts.keychainStorageFactory(integrationName);
  }
  const value = new MacOSKeychainTokenStorage(integrationName);
  (value as unknown as { preflight(principalId: string): string }).preflight(principal);
  return value;
}

function client(opts: RunOptions, options: ConstructorParameters<typeof GoogleOAuthClient>[0]) {
  return opts.googleOAuthClientFactory?.(options) ?? new GoogleOAuthClient(options);
}

export async function connectIntegration(rest: string[], opts: RunOptions): Promise<number> {
  const log = opts.log ?? ((message: string) => console.log(message));
  const err = opts.err ?? ((message: string) => console.error(message));
  const args = parseAuthArgs(rest, false);
  if (args === undefined) {
    err(CONNECT_USAGE);
    return 2;
  }
  let principal: string;
  try {
    principal = validateOAuthPrincipal(args.principal);
  } catch {
    err("INTEGRATION_POLICY_REJECTED: The principal identifier is invalid.");
    return 1;
  }
  let manifest: OAuthLoadedManifest;
  try {
    manifest = await oauthManifest(args.name, opts);
  } catch (error) {
    err(
      error instanceof Error && error.message.includes("OAuth")
        ? error.message
        : formatIntegrationError(error),
    );
    return 1;
  }
  const environment = opts.env ?? process.env;
  const clientId = environment[manifest.auth.clientIdEnv];
  const command = qualifiedAuthCommand("connect", manifest.name);
  if (clientId === undefined || clientId.length === 0) {
    err(`INTEGRATION_AUTH_REQUIRED: ${manifest.auth.clientIdEnv} is not set.`);
    err("Create a Google Desktop OAuth client and load the manifest-declared client ID.");
    err(command);
    return 1;
  }
  const clientSecret =
    manifest.auth.clientSecretEnv === undefined
      ? undefined
      : environment[manifest.auth.clientSecretEnv];
  try {
    const oauth = client(opts, {
      clientId,
      ...(clientSecret === undefined ? {} : { clientSecret }),
      scopes: [...manifest.auth.scopes],
      storage: storage(opts, manifest.name, principal),
    });
    await withAuthSignal(opts, (signal) => oauth.connect(principal, signal));
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      err("Problem: Gmail authorization was cancelled.");
      err("Cause: The connect operation was cancelled before completion.");
      err(`Fix: Rerun \`${command}\`.`);
    } else if (!renderClosedRecovery(error, command, err)) {
      err("Problem: Google OAuth consent did not complete.");
      err("Cause: The provider denied or failed installed-app consent.");
      err(`Fix: Rerun \`${command}\`.`);
    }
    return 1;
  }
  log(`Connected ${manifest.name} for the requested principal.`);
  log(`Stored refresh credentials in macOS Keychain service dev.kaji.oauth.${manifest.name}.`);
  return 0;
}
