/** `kaji add`: rollback-safe copied integration bundle installation. */
import { join, resolve } from "node:path";

import {
  BundleTransitionError,
  classifyIntegrationBundle,
  installIntegrationBundle,
  type BundleStatus,
} from "@/cli/integration-copy";
import {
  formatIntegrationError,
  IntegrationExperimentalError,
  loadManifest,
  loadRegistryIndex,
  type LoadedIntegrationManifest,
  type RegistryIndexDocument,
} from "@/integrations/registry-loader";

export interface AddOptions {
  readonly registryRoot: string;
  readonly schemaRoot?: string;
  readonly log?: (message: string) => void;
}

interface Args {
  readonly name: string;
  readonly out?: string;
  readonly force: boolean;
  readonly allowExperimental: boolean;
  readonly check: boolean;
  readonly json: boolean;
}

function parseArgs(argv: string[], log: (message: string) => void): Args | undefined {
  const name = argv[0];
  if (name === undefined || name.startsWith("-")) {
    log("usage: kaji add <name> [--out <dir>] [--force] [--allow-experimental] [--check] [--json]");
    return undefined;
  }
  let out: string | undefined;
  let force = false;
  let allowExperimental = false;
  let check = false;
  let json = false;
  for (let index = 1; index < argv.length; index += 1) {
    const argument = argv[index]!;
    if (argument === "--out") {
      const value = argv[++index];
      if (value === undefined || value.startsWith("--")) {
        log("--out requires a value");
        return undefined;
      }
      out = value;
    } else if (argument === "--force") {
      force = true;
    } else if (argument === "--allow-experimental") {
      allowExperimental = true;
    } else if (argument === "--check") {
      check = true;
    } else if (argument === "--json") {
      json = true;
    } else {
      log(`Unknown argument: ${argument}`);
      return undefined;
    }
  }
  if (check && force) {
    log("--check cannot be combined with --force");
    return undefined;
  }
  return { name, out, force, allowExperimental, check, json };
}

function exitCode(status: BundleStatus): number {
  return { current: 0, absent: 3, outdated: 4, modified: 5, demoted: 6 }[status.state];
}

function shellQuote(value: string): string {
  return /^[A-Za-z0-9_./:@+-]+$/u.test(value) ? value : `'${value.replaceAll("'", `'"'"'`)}'`;
}

function nextCommand(status: BundleStatus, manifest: LoadedIntegrationManifest): string {
  const command = ["bunx", "--package", "@kaji/sdk", "kaji", "add", manifest.name];
  if (manifest.stability === "experimental") command.push("--allow-experimental");
  command.push("--out", status.destination);
  if (status.state === "outdated") command.push("--force");
  else if (status.state !== "absent") command.push("--check");
  return command.map(shellQuote).join(" ");
}

function renderStatus(
  status: BundleStatus,
  manifest: LoadedIntegrationManifest,
  json: boolean,
  log: (message: string) => void,
): void {
  const next_command = nextCommand(status, manifest);
  if (json) {
    log(
      JSON.stringify({
        state: status.state,
        integration: manifest.name,
        runtime: "typescript",
        destination: status.destination,
        reason_code: status.reasonCode,
        next_command,
      }),
    );
    return;
  }
  log(`${status.state}: ${manifest.name} at ${status.destination} (${status.reasonCode})`);
  log(`next: ${next_command}`);
}

function setupGuidance(manifest: LoadedIntegrationManifest, log: (message: string) => void): void {
  if (manifest.name === "github" && manifest.auth.kind === "env") {
    log("next: set GITHUB_TOKEN to a fine-grained token limited to the configured repositories");
    log(`docs: ${manifest.auth.docs}`);
  } else if (manifest.auth.kind === "env") {
    log(`next: set ${manifest.auth.env} in your environment`);
  }
}

export async function add(argv: string[], opts: AddOptions): Promise<number> {
  const log = opts.log ?? ((message: string) => console.log(message));
  const args = parseArgs(argv, log);
  if (args === undefined) return argv.includes("--check") && argv.includes("--force") ? 2 : 1;

  let index: RegistryIndexDocument;
  try {
    index = await loadRegistryIndex(opts.registryRoot, { schemaRoot: opts.schemaRoot });
  } catch (error) {
    log(formatIntegrationError(error));
    return 1;
  }
  const entry = index.integrations[args.name];
  if (entry === undefined) {
    const available = Object.keys(index.integrations).sort().join(", ") || "(none)";
    log(`Unknown integration: '${args.name}'. Available: ${available}`);
    return 1;
  }
  if (entry.stability === "experimental" && !args.allowExperimental && !args.check) {
    log(formatIntegrationError(new IntegrationExperimentalError(args.name)));
    return 1;
  }

  let manifest: LoadedIntegrationManifest;
  try {
    manifest = await loadManifest(opts.registryRoot, args.name, {
      schemaRoot: opts.schemaRoot,
      index,
    });
  } catch (error) {
    log(formatIntegrationError(error));
    return 1;
  }
  const destination = resolve(args.out ?? join("./integrations", args.name));
  const context = { manifest, entry, destination, runtime: "typescript" as const };
  if (args.check) {
    try {
      const status = await classifyIntegrationBundle(context);
      renderStatus(status, manifest, args.json, log);
      return exitCode(status);
    } catch (error) {
      log(error instanceof Error ? error.message : "Integration check failed");
      return 1;
    }
  }

  let status: BundleStatus;
  try {
    status = await installIntegrationBundle({ ...context, force: args.force });
  } catch (error) {
    if (error instanceof BundleTransitionError) {
      renderStatus(error.status, manifest, args.json, log);
      return exitCode(error.status);
    }
    log(error instanceof Error ? error.message : "Integration copy failed");
    return 1;
  }
  if (args.json) {
    renderStatus(status, manifest, true, log);
    return 0;
  }
  if (status.written.length > 0)
    log(`Wrote ${status.written.length} file(s) to ${status.destination}`);
  else log(`Current integration: ${manifest.name} at ${status.destination}`);
  setupGuidance(manifest, log);
  return 0;
}
