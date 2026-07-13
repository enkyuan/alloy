/**
 * `kaji list-integrations`: enumerate every integration in the registry
 * catalog (`registry/index.json`) and print its stable row contract:
 * `name  [tier]  version  description`.
 *
 * Follows the same flow as `kaji add` so the two commands agree on what
 * "available" means: an entry in `index.json`, not just a directory under
 * `registry/`.
 */
import type { RunOptions } from "@/cli/index";
import { TYPESCRIPT_SDK_CLI } from "@/cli/package-identity";
import {
  formatIntegrationError,
  loadManifest,
  loadRegistryIndex,
} from "@/integrations/registry-loader";

interface DiscoveryRow {
  name: string;
  version: string;
  stability: "experimental" | "beta";
  runtimes: string[];
  auth: { kind: "none" | "env" | "oauth"; provider: "google" | null };
  experimental_opt_in_required: boolean;
  next_commands: Record<string, string>;
}

function discoveryRow(manifest: Awaited<ReturnType<typeof loadManifest>>): DiscoveryRow {
  const experimental = manifest.stability === "experimental";
  const next_commands: Record<string, string> = {};
  for (const runtime of [...manifest.runtimes].sort()) {
    let command: string;
    if (manifest.auth.kind === "oauth") {
      command =
        runtime === "python"
          ? `python -m kaji.cli connect ${manifest.name} --principal <stable-host-principal-id>`
          : `${TYPESCRIPT_SDK_CLI} connect ${manifest.name} --principal <stable-host-principal-id>`;
    } else {
      command =
        runtime === "python"
          ? `python -m kaji.cli add ${manifest.name}`
          : `${TYPESCRIPT_SDK_CLI} add ${manifest.name}`;
      if (experimental) command += " --allow-experimental";
    }
    next_commands[runtime] = command;
  }
  return {
    name: manifest.name,
    version: manifest.version,
    stability: manifest.stability,
    runtimes: [...manifest.runtimes].sort(),
    auth: {
      kind: manifest.auth.kind,
      provider: manifest.auth.kind === "oauth" ? manifest.auth.provider : null,
    },
    experimental_opt_in_required: experimental,
    next_commands,
  };
}

export async function listIntegrations(rest: string[], opts: RunOptions): Promise<number> {
  const log = opts.log ?? ((m: string) => console.log(m));
  const err = opts.err ?? ((m: string) => console.error(m));
  const json = rest.length === 1 && rest[0] === "--json";
  if (rest.length !== 0 && !json) {
    err("usage: kaji list-integrations [--json]");
    return 2;
  }
  let index;
  try {
    index = await loadRegistryIndex(opts.registryRoot, { schemaRoot: opts.schemaRoot });
  } catch (error) {
    err(formatIntegrationError(error));
    return 1;
  }
  const entries = Object.keys(index.integrations).sort((a, b) => a.localeCompare(b));
  if (entries.length === 0 && !json) {
    log("No integrations found.");
    return 0;
  }
  const rows: DiscoveryRow[] = [];
  for (const name of entries) {
    try {
      const manifest = await loadManifest(opts.registryRoot, name, {
        schemaRoot: opts.schemaRoot,
        index,
      });
      rows.push(discoveryRow(manifest));
    } catch (error) {
      err(formatIntegrationError(error));
      return 1;
    }
  }
  if (json) {
    log(JSON.stringify(rows));
    return 0;
  }
  for (const row of rows) {
    const auth =
      row.auth.provider === null ? row.auth.kind : `${row.auth.kind}:${row.auth.provider}`;
    log(
      `${row.name}  [${row.stability}]  v${row.version}  auth=${auth}  runtimes=${row.runtimes.join(",")}`,
    );
    for (const [runtime, command] of Object.entries(row.next_commands)) {
      log(`  ${runtime}: ${command}`);
    }
  }
  return 0;
}
