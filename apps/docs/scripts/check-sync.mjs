import { readdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join, relative, sep } from "node:path";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const read = (path) => readFile(join(root, path), "utf8");
const readJson = async (path) => JSON.parse(await read(path));

async function sourceFiles(directory) {
  const files = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...(await sourceFiles(path)));
    else if (path.endsWith(".mdx") || path.endsWith(".astro")) files.push(path);
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
  landingPage,
  typescriptExports,
  pythonExports,
  architecture,
  gettingStarted,
  navigationSource,
  sidebar,
  mobileNavigation,
  docsLibrary,
  llmsFullRoute,
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
  read("apps/docs/src/pages/index.astro"),
  read("kaji/ts/src/index.ts"),
  read("kaji/src/kaji/__init__.py"),
  read("apps/docs/content/architecture.mdx"),
  read("apps/docs/content/getting-started.mdx"),
  read("apps/docs/src/data/navigation.ts"),
  read("apps/docs/src/components/navigation/sidebar.astro"),
  read("apps/docs/src/components/navigation/mobile.astro"),
  read("apps/docs/src/lib/docs.ts"),
  read("apps/docs/src/pages/llms-full.txt.ts"),
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
  if (entry.stability === "beta") {
    requireText(row, "Beta", `integration row for ${name}`);
  } else {
    requireText(row, "WIP", `integration row for ${name}`);
    requireText(row, "`experimental`", `integration row for ${name}`);
  }
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
  [landingPage, "KAJI_API_KEY", "landing install prompt"],
  [landingPage, "npx kaji init", "landing CLI command"],
  [landingPage, "tool_spec_from_model", "Python tool example"],
  [landingPage, "async (ctx, args)", "TypeScript tool handler order"],
];
for (const [source, value, context] of staleClaims) {
  if (source.includes(value)) fail(`${context} still contains ${JSON.stringify(value)}`);
}

const displayedFiles = [
  ...(await sourceFiles(join(root, "apps/docs/content"))),
  ...(await sourceFiles(join(root, "apps/docs/src/components"))),
  ...(await sourceFiles(join(root, "apps/docs/src/pages"))),
];
const displayedSources = await Promise.all(
  displayedFiles.map(async (path) => [relative(root, path), await readFile(path, "utf8")]),
);

const contentRoot = join(root, "apps/docs/content");
const contentFiles = (await sourceFiles(contentRoot)).filter((path) => path.endsWith(".mdx"));
const contentSources = new Map(
  await Promise.all(contentFiles.map(async (path) => [path, await readFile(path, "utf8")])),
);
const routeForContent = (path) => {
  const id = relative(contentRoot, path)
    .split(sep)
    .join("/")
    .replace(/\.mdx$/u, "");
  if (id === "index") return "/docs";
  return `/docs/${id.endsWith("/index") ? id.slice(0, -"/index".length) : id}`;
};
const contentByRoute = new Map(
  [...contentSources].map(([path, source]) => [routeForContent(path), { path, source }]),
);
const navigationHrefs = [...navigationSource.matchAll(/\{\s*href:\s*"([^"]+)"[\s\S]*?\}/gu)].map(
  (match) => match[1],
);
const navigationDocsHrefs = navigationHrefs.filter((href) => href.startsWith("/docs"));

for (const route of contentByRoute.keys()) {
  if (!navigationDocsHrefs.includes(route)) fail(`navigation is missing ${route}`);
}
for (const href of navigationDocsHrefs) {
  if (!contentByRoute.has(href)) fail(`navigation points to missing content route ${href}`);
}
if (new Set(navigationHrefs).size !== navigationHrefs.length) {
  fail("navigation contains a duplicate href");
}

function headingSlug(text) {
  return text
    .replace(/<[^>]+>/gu, "")
    .replace(/[`*_~]/gu, "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/gu, "")
    .replace(/\s+/gu, "-")
    .replace(/-+/gu, "-");
}

const anchorsByRoute = new Map();
for (const [route, { source }] of contentByRoute) {
  const anchors = new Set(
    [...source.matchAll(/^#{2,6}\s+(.+)$/gmu)].map((match) => headingSlug(match[1])),
  );
  for (const match of source.matchAll(/\bid=["']([^"']+)["']/gu)) anchors.add(match[1]);
  anchorsByRoute.set(route, anchors);
}
for (const [path, source] of displayedSources) {
  for (const match of source.matchAll(
    /(?:\]\(|\bhref=["'])(\/docs(?:\/[A-Za-z0-9_./-]*)?(?:#[A-Za-z0-9_-]+)?)/gu,
  )) {
    const target = match[1];
    const [route, anchor] = target.split("#");
    if (!contentByRoute.has(route)) fail(`${path} links to missing route ${route}`);
    if (anchor && !anchorsByRoute.get(route)?.has(anchor)) {
      fail(`${path} links to missing anchor ${target}`);
    }
  }
}

for (const [name, entry] of catalog) {
  if (entry.stability !== "experimental") continue;
  const route = `/docs/integrations/${name}`;
  if (!contentByRoute.has(route)) continue;
  const item = navigationSource.match(
    new RegExp(`\\{\\s*href:\\s*"${route.replaceAll("/", "\\/")}"[^}]*\\}`, "u"),
  )?.[0];
  if (item === undefined || !item.includes('status: "wip"')) {
    fail(`${route} must use the accessible WIP navigation status`);
  }
}

for (const [path, source] of [
  ["desktop navigation", sidebar],
  ["mobile navigation", mobileNavigation],
]) {
  requireText(source, '<sup class="nav-wip" aria-label="work in progress">', path);
  requireText(source, "WIP", path);
}

const nodeMajors = typescriptPackage.engines.node.match(/\d+/gu) ?? [];
requireText(install, `Node.js ${nodeMajors.join(" or ")}`, "install runtime matrix");
const typescriptCurrent = typescriptPackage.devDependencies.typescript.replace(/^[^\d]*/u, "");
const typescript57 = typescriptPackage.devDependencies.typescript57.match(/@(.+)$/u)?.[1];
if (typescript57 === undefined) fail("TypeScript 5.7 compatibility version could not be read");
requireText(install, typescript57, "install compiler matrix");
requireText(install, typescriptCurrent, "install compiler matrix");
for (const [name, range] of Object.entries(typescriptPackage.peerDependencies)) {
  if (name === "@anthropic-ai/sdk") continue;
  requireText(install, `${name} ${range}`, `install peer contract for ${name}`);
}

if (!/\bpyyaml\b/iu.test(pythonProject)) {
  for (const [path, source] of displayedSources) {
    if (/\bkaji\s+gen\b[^\n]*--spec\s+\S+\.ya?ml\b/iu.test(source)) {
      fail(`${path} shows a YAML generator command without a declared PyYAML dependency`);
    }
  }
}
if (/audio\s*→\s*STT\s*→\s*\[runtime/iu.test(architecture)) {
  fail("architecture claims an end-to-end voice pipeline that is not composed");
}
requireText(gettingStarted, "git clone https://github.com/enkyuan/alloy.git", "source tutorial");
requireText(docsLibrary, "${entry.body}", "full-document Markdown generation");
requireText(llmsFullRoute, "docMarkdown(entry)", "llms-full route");

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
    /import\s+(?:type\s+)?\{([^}]+)\}\s+from\s+["']kaji-sdk["']/g,
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
    `${recoverySlugs.size} recovery anchors across ${contentByRoute.size} routes; ` +
    `checked ${displayedSymbolCount} displayed SDK symbols`,
);
