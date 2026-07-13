import { GoogleOAuthClient, validateOAuthPrincipal } from "@/auth/oauth";
import { MacOSKeychainTokenStorage } from "@/auth/keychain";
import type { RunOptions } from "@/cli/index";
import {
  oauthManifest,
  type OAuthLoadedManifest,
  parseAuthArgs,
  qualifiedAuthCommand,
  renderClosedRecovery,
  withAuthSignal,
} from "@/cli/connect";
import { formatIntegrationError } from "@/integrations/registry-loader";

export const DISCONNECT_USAGE =
  "usage: kaji disconnect <name> --principal <stable-host-principal-id> [--force-local]";

function storage(opts: RunOptions, principal: string) {
  if (opts.keychainStorageFactory !== undefined) return opts.keychainStorageFactory();
  const value = new MacOSKeychainTokenStorage();
  (value as unknown as { preflight(principalId: string): string }).preflight(principal);
  return value;
}

function client(opts: RunOptions, options: ConstructorParameters<typeof GoogleOAuthClient>[0]) {
  return opts.googleOAuthClientFactory?.(options) ?? new GoogleOAuthClient(options);
}

export async function disconnectIntegration(rest: string[], opts: RunOptions): Promise<number> {
  const log = opts.log ?? ((message: string) => console.log(message));
  const err = opts.err ?? ((message: string) => console.error(message));
  const args = parseAuthArgs(rest, true);
  if (args === undefined) {
    err(DISCONNECT_USAGE);
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
  const command = qualifiedAuthCommand("disconnect", manifest.name);
  let result;
  try {
    const oauth = client(opts, {
      scopes: [...manifest.auth.scopes],
      storage: storage(opts, principal),
    });
    result = await withAuthSignal(opts, (signal) =>
      oauth.disconnect(principal, signal, { forceLocal: args.forceLocal }),
    );
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      err("Problem: Gmail authorization was cancelled.");
      err("Cause: The disconnect operation was cancelled before completion.");
      err(`Fix: Rerun \`${command}\`.`);
    } else if (!renderClosedRecovery(error, command, err)) {
      err("Problem: OAuth disconnect did not complete.");
      err("Cause: The provider revocation result is unavailable.");
      err(`Fix: Rerun \`${command}\`.`);
    }
    return 1;
  }
  if (result.localState === "revocation_pending") {
    err("Problem: Remote OAuth revocation is pending.");
    err("Cause: The provider did not confirm revocation.");
    err(`Fix: Retry \`${command}\` or add --force-local.`);
    err("You can also revoke Kaji manually in Google Account security settings.");
    return 1;
  }
  if (result.localState === "missing") {
    log(`No stored ${manifest.name} grant was found for the requested principal.`);
    return 0;
  }
  if (args.forceLocal && !result.remoteRevoked) {
    log(`Deleted the local ${manifest.name} grant for the requested principal.`);
    log("Warning: remote access may remain until revoked in Google Account settings.");
    return 0;
  }
  log(`Disconnected ${manifest.name} for the requested principal.`);
  log("Confirmed remote OAuth revocation and removed local credentials.");
  return 0;
}
