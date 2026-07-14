import { readdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join, relative } from "node:path";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const read = (path) => readFile(join(root, path), "utf8");
const readJson = async (path) => JSON.parse(await read(path));

async function sourceFiles(directory) {
  const files = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...(await sourceFiles(path)));
    else if (path.endsWith(".mdx") || path.endsWith(".tsx")) files.push(path);
  }
  return files;
}

function fail(message) {
  throw new Error(`docs SDK sync check failed: ${message}`);
}

function requireText(source, value, context) {
  if (!source.includes(value)) fail(`${context} is missing ${JSON.stringify(value)}`);
}

const [
  install,
  cli,
  events,
  integrations,
  recovery,
  pythonProject,
  typescriptPackage,
  featureTiers,
  pythonRegistry,
  typescriptRegistry,
  eventTypes,
  recoveryContract,
  installBlock,
  toolShowcase,
  typescriptExports,
  pythonExports,
] = await Promise.all([
  read("apps/docs/content/install.mdx"),
  read("apps/docs/content/cli.mdx"),
  read("apps/docs/content/concepts/events.mdx"),
  read("apps/docs/content/integrations/index.mdx"),
  read("apps/docs/content/integrations/recovery-v1.mdx"),
  read("kaji/pyproject.toml"),
  readJson("kaji/ts/package.json"),
  readJson("kaji/contracts/feature-tiers-v1.json"),
  readJson("kaji/src/kaji/integrations/registry/index.json"),
  readJson("kaji/ts/registry/index.json"),
  read("kaji/ts/src/events/types.ts"),
  readJson("kaji/contracts/errors/integration-recovery-v1.json"),
  read("apps/docs/components/landing/install/block.tsx"),
  read("apps/docs/components/landing/tools/section.tsx"),
  read("kaji/ts/src/index.ts"),
  read("kaji/src/kaji/__init__.py"),
]);

const pythonVersion = pythonProject.match(/^version = "([^"]+)"$/m)?.[1];
if (pythonVersion === undefined) fail("Python package version could not be read");
requireText(install, `\`${pythonVersion}\``, "install guide");
requireText(install, `\`${typescriptPackage.version}\``, "install guide");

for (const runtime of Object.values(featureTiers.cliCommands)) {
  for (const command of [...runtime.stable, ...runtime.experimental]) {
    requireText(cli, `\`${command}\``, "CLI command matrix");
  }
}

const documentedEventTypes = new Set(
  [...eventTypes.matchAll(/:\s*"([a-z]+(?:\.[a-z]+)+)"/g)].map((match) => match[1]),
);
for (const eventType of documentedEventTypes) {
  requireText(events, `\`${eventType}\``, "events reference");
}

const catalog = new Map();
for (const registry of [pythonRegistry, typescriptRegistry]) {
  for (const [name, entry] of Object.entries(registry.integrations)) {
    const existing = catalog.get(name);
    if (
      existing !== undefined &&
      (existing.stability !== entry.stability ||
        JSON.stringify(existing.runtimes) !== JSON.stringify(entry.runtimes))
    ) {
      fail(`shared integration ${name} differs between SDK registries`);
    }
    catalog.set(name, entry);
  }
}
for (const [name, entry] of catalog) {
  const row = integrations.split("\n").find((line) => line.startsWith(`| \`${name}\``));
  if (row === undefined) fail(`integration catalog is missing ${name}`);
  const stability = entry.stability === "beta" ? "Beta" : "Experimental";
  requireText(row, stability, `integration row for ${name}`);
  const runtimes = entry.runtimes
    .map((runtime) => (runtime === "python" ? "Python" : "TypeScript"))
    .join(", ");
  requireText(row, runtimes, `integration row for ${name}`);
}

const recoverySlugs = new Set(
  recovery
    .split("\n")
    .filter((line) => line.startsWith("## "))
    .map((line) =>
      line
        .slice(3)
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9\s-]/g, "")
        .replace(/\s+/g, "-"),
    ),
);
for (const entry of Object.values(recoveryContract.entries)) {
  const anchor = new URL(entry.docUrl).hash.slice(1);
  if (!recoverySlugs.has(anchor)) fail(`recovery guide is missing #${anchor}`);
}

const staleClaims = [
  [installBlock, "KAJI_API_KEY", "landing install prompt"],
  [installBlock, "npx kaji init", "landing CLI command"],
  [toolShowcase, "tool_spec_from_model", "Python tool example"],
  [toolShowcase, "async (ctx, args)", "TypeScript tool handler order"],
];
for (const [source, value, context] of staleClaims) {
  if (source.includes(value)) fail(`${context} still contains ${JSON.stringify(value)}`);
}

const displayedFiles = [
  ...(await sourceFiles(join(root, "apps/docs/content"))),
  ...(await sourceFiles(join(root, "apps/docs/components/landing"))),
];
const displayedSources = await Promise.all(
  displayedFiles.map(async (path) => [relative(root, path), await readFile(path, "utf8")]),
);

const publicTypescriptNames = new Set(["VERSION"]);
for (const match of typescriptExports.matchAll(/export(?:\s+type)?\s*\{([\s\S]*?)\}\s*from/g)) {
  for (const rawName of match[1].split(",")) {
    const name = rawName
      .trim()
      .replace(/^type\s+/, "")
      .split(/\s+as\s+/)
      .at(-1);
    if (name) publicTypescriptNames.add(name);
  }
}

const publicPythonNames = new Set(
  [...pythonExports.matchAll(/^\s+"([A-Za-z_]\w*)":\s*"kaji\./gm)].map((match) => match[1]),
);
publicPythonNames.add("__version__");

let displayedSymbolCount = 0;
for (const [path, source] of displayedSources) {
  if (source.includes("poetry install") || source.includes("poetry run")) {
    fail(`${path} still documents Poetry instead of the repository's uv workflow`);
  }

  for (const match of source.matchAll(
    /import\s+(?:type\s+)?\{([^}]+)\}\s+from\s+["']@kaji\/sdk["']/g,
  )) {
    for (const rawName of match[1].split(",")) {
      const name = rawName
        .trim()
        .replace(/^type\s+/, "")
        .split(/\s+as\s+/)[0];
      if (!name) continue;
      displayedSymbolCount += 1;
      if (!publicTypescriptNames.has(name)) {
        fail(`${path} imports non-public TypeScript symbol ${name}`);
      }
    }
  }

  for (const match of source.matchAll(
    /from\s+kaji\s+import\s+([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)/g,
  )) {
    for (const name of match[1].split(",").map((value) => value.trim())) {
      displayedSymbolCount += 1;
      if (!publicPythonNames.has(name)) fail(`${path} imports non-public Python symbol ${name}`);
    }
  }

  for (const match of source.matchAll(/\bkaji\.([A-Z]\w*|[a-z]\w*(?:_[a-z0-9]\w*)+)/g)) {
    const name = match[1];
    displayedSymbolCount += 1;
    if (!publicPythonNames.has(name)) fail(`${path} references non-public Python symbol ${name}`);
  }
}

requireText(integrations, "No Gmail manifest, client, or tool bundle", "integration status");
console.log(
  `OK: docs match SDK ${pythonVersion} / ${typescriptPackage.version}, ` +
    `${documentedEventTypes.size} event types, ${catalog.size} integrations, and ` +
    `${recoverySlugs.size} recovery anchors; checked ${displayedSymbolCount} displayed SDK symbols`,
);
