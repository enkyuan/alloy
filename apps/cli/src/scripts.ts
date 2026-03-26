import { readdir, readFile } from "node:fs/promises";
import { basename, extname, join, relative, sep } from "node:path";
import { CliState, ScriptFile, ScriptMetadata } from "./types";
import {
  formatScriptName,
  getScriptIcon,
  isExecutable,
  truncateText,
} from "./utils";
import { hydrateScriptsWithState } from "./state";

const SUPPORTED_EXTENSIONS = new Set([
  ".sh",
  ".bash",
  ".zsh",
  ".py",
  ".js",
  ".ts",
  ".mjs",
  ".cjs",
]);

const DEFAULT_DESCRIPTION_BY_BASENAME: Record<string, string> = {
  "setup.sh": "Initial setup and configuration",
  "startup.sh": "Start application services",
  "deploy.sh": "Deploy application to production",
  "test.sh": "Run the full test suite",
  "build.sh": "Build the project for production",
  "dev.sh": "Start development environment",
  "clean.sh": "Clean build artifacts",
  "lint.sh": "Run linting checks",
  "format.sh": "Format code with prettier",
  "migrate.sh": "Run database migrations",
  "seed.sh": "Seed database with test data",
  "backup.sh": "Create database backup",
  "restore.sh": "Restore from backup",
  "logs.sh": "View application logs",
  "status.sh": "Check service status",
};

const HEADER_BYTE_BUDGET = 8_192;
const PREVIEW_MAX_LINES = 18;
const PREVIEW_MAX_CHARACTERS = 1_200;

const FRONT_MATTER_BLOCK = /^---\s*\n([\s\S]*?)\n---/;
const INLINE_META_PREFIXES = ["#", "//", "--", ";"];

interface ExtractedMetadata {
  metadata: ScriptMetadata;
  remainder: string;
}

/**
 * Load scripts from the given directory, parse inline metadata, and merge persisted state.
 */
export async function loadScriptsFromDirectory(
  rootDir: string,
  state: CliState,
): Promise<ScriptFile[]> {
  const files = await collectScriptPaths(rootDir);
  const scripts: ScriptFile[] = [];

  for (const filePath of files) {
    const base = basename(filePath);
    const relativePath = relative(rootDir, filePath);
    const header = await readHeaderSegment(filePath);
    const { metadata } = extractMetadata(header);
    const description =
      metadata.description ??
      DEFAULT_DESCRIPTION_BY_BASENAME[base] ??
      "Execute script";
    const category = metadata.category ?? deriveCategory(relativePath);
    const icon = metadata.icon ?? getScriptIcon(base);
    const snippet = metadata.snippet ?? buildSnippet(metadata, header);

    const script: ScriptFile = {
      id: relativePath,
      name: metadata.heading ?? formatScriptName(base),
      path: filePath,
      relativePath,
      description,
      snippet,
      icon,
      category,
      tags: metadata.tags,
      executable: await isExecutable(filePath),
    };

    scripts.push(script);
  }

  const hydrated = hydrateScriptsWithState(scripts, state);

  const recentOrder = state.recentScriptIds ?? [];
  const recencyRank = new Map(recentOrder.map((id, index) => [id, index]));

  return hydrated.sort((a, b) => {
    const aRank = recencyRank.get(a.id);
    const bRank = recencyRank.get(b.id);
    const aIsRecent = aRank !== undefined;
    const bIsRecent = bRank !== undefined;

    if (aIsRecent && bIsRecent) {
      return (aRank as number) - (bRank as number);
    }
    if (aIsRecent) {
      return -1;
    }
    if (bIsRecent) {
      return 1;
    }

    return a.name.localeCompare(b.name);
  });
}

/**
 * Generate a preview block (first lines) for the given script path.
 */
export async function readScriptPreview(
  path: string,
  maxLines: number = PREVIEW_MAX_LINES,
  maxCharacters: number = PREVIEW_MAX_CHARACTERS,
): Promise<string> {
  try {
    const content = await readFile(path, "utf-8");
    const lines = content.replace(/\r\n/g, "\n").split("\n").slice(0, maxLines);

    const joined = lines.join("\n");
    return truncateText(joined, maxCharacters);
  } catch {
    return "Unable to read script contents for preview.";
  }
}

/**
 * Traverse the scripts directory (recursively) and collect supported files.
 */
async function collectScriptPaths(rootDir: string): Promise<string[]> {
  const discovered: string[] = [];
  const queue: string[] = [rootDir];

  while (queue.length > 0) {
    const current = queue.pop();
    if (!current) {
      continue;
    }

    let entries;
    try {
      entries = await readdir(current, { withFileTypes: true });
    } catch {
      continue;
    }

    for (const entry of entries) {
      if (entry.name.startsWith(".")) {
        continue;
      }

      const fullPath = join(current, entry.name);

      if (entry.isDirectory()) {
        queue.push(fullPath);
        continue;
      }

      if (!isSupportedScript(fullPath)) {
        continue;
      }

      discovered.push(fullPath);
    }
  }

  return discovered;
}

/**
 * Parse metadata from front matter and inline comment directives.
 */
function extractMetadata(header: string): ExtractedMetadata {
  const normalized = header.replace(/\r\n/g, "\n");
  let remainder = normalized;
  const metadata: ScriptMetadata = {};
  const frontMatter = normalized.match(FRONT_MATTER_BLOCK);

  if (frontMatter?.[1]) {
    Object.assign(metadata, parseFrontMatter(frontMatter[1]));
    remainder = normalized.slice(frontMatter[0].length).trimStart();
  }

  const inlineMeta = parseInlineMetadata(remainder);
  Object.assign(metadata, inlineMeta.metadata);
  remainder = inlineMeta.remainder;

  return { metadata, remainder };
}

/**
 * Parse YAML-ish front matter into ScriptMetadata.
 */
function parseFrontMatter(block: string): ScriptMetadata {
  const metadata: ScriptMetadata = {};
  const lines = block.split("\n");

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      continue;
    }

    const separatorIndex = trimmed.indexOf(":");
    if (separatorIndex === -1) {
      continue;
    }

    const key = trimmed.slice(0, separatorIndex).trim();
    const rawValue = trimmed.slice(separatorIndex + 1).trim();

    if (!rawValue) {
      continue;
    }

    switch (key) {
      case "description":
        metadata.description = rawValue;
        break;
      case "category":
        metadata.category = rawValue;
        break;
      case "icon":
        metadata.icon = rawValue;
        break;
      case "heading":
        metadata.heading = rawValue;
        break;
      case "snippet":
        metadata.snippet = rawValue;
        break;
      case "tags":
        metadata.tags = parseTags(rawValue);
        break;
      default:
        break;
    }
  }

  return metadata;
}

/**
 * Parse inline comment metadata directives (e.g., `# description: Foo`).
 */
function parseInlineMetadata(content: string): ExtractedMetadata {
  const metadata: ScriptMetadata = {};
  const lines = content.split("\n");
  const remainderLines: string[] = [];
  let inMetaBlock = true;

  for (const originalLine of lines) {
    const line = originalLine.trim();

    if (!line) {
      if (inMetaBlock) {
        continue;
      }
      remainderLines.push(originalLine);
      continue;
    }

    const prefix = INLINE_META_PREFIXES.find((token) => line.startsWith(token));

    if (!prefix) {
      inMetaBlock = false;
      remainderLines.push(originalLine);
      continue;
    }

    const directive = line.slice(prefix.length).trim();

    if (!directive.includes(":")) {
      if (!metadata.snippet) {
        metadata.snippet = directive;
      }
      continue;
    }

    const [rawKey, ...rest] = directive.split(":");
    const key = rawKey.trim().toLowerCase();
    const value = rest.join(":").trim();

    switch (key) {
      case "description":
        metadata.description = value;
        break;
      case "category":
        metadata.category = value;
        break;
      case "icon":
        metadata.icon = value;
        break;
      case "tags":
        metadata.tags = parseTags(value);
        break;
      case "heading":
        metadata.heading = value;
        break;
      case "snippet":
        metadata.snippet = value;
        break;
      default:
        break;
    }
  }

  return {
    metadata,
    remainder: remainderLines.join("\n"),
  };
}

/**
 * Build a fallback snippet when none is provided explicitly.
 */
function buildSnippet(
  metadata: ScriptMetadata,
  header: string,
): string | undefined {
  if (metadata.snippet) {
    return metadata.snippet;
  }

  const withoutFrontMatter = header.replace(FRONT_MATTER_BLOCK, "").trim();
  const lines = withoutFrontMatter.split("\n");

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#!")) {
      continue;
    }
    if (INLINE_META_PREFIXES.some((token) => trimmed.startsWith(token))) {
      continue;
    }
    return truncateText(trimmed, 120);
  }

  return undefined;
}

/**
 * Determine whether the file has a supported script extension.
 */
function isSupportedScript(filePath: string): boolean {
  const extension = extname(filePath).toLowerCase();
  return SUPPORTED_EXTENSIONS.has(extension);
}

/**
 * Extract the category from the relative path (top-level directory).
 */
function deriveCategory(relativePath: string): string | undefined {
  const segments = relativePath.split(sep).filter(Boolean);
  if (segments.length <= 1) {
    return undefined;
  }
  return segments[0];
}

/**
 * Read the first bytes of a script for metadata parsing.
 */
async function readHeaderSegment(path: string): Promise<string> {
  try {
    const content = await readFile(path, "utf-8");

    if (content.length <= HEADER_BYTE_BUDGET) {
      return content;
    }

    return content.slice(0, HEADER_BYTE_BUDGET);
  } catch {
    return "";
  }
}

/**
 * Parse tags from comma-separated or JSON-like syntax.
 */
function parseTags(raw: string): string[] | undefined {
  if (!raw) {
    return undefined;
  }

  const trimmed = raw.trim();

  if (trimmed.startsWith("[") && trimmed.endsWith("]")) {
    try {
      const parsed = JSON.parse(trimmed);
      if (Array.isArray(parsed)) {
        return parsed.map((value) => String(value).trim()).filter(Boolean);
      }
    } catch {
      /* fall through to fallback parsing */
    }
  }

  return trimmed
    .split(/[,|]/)
    .map((tag) => tag.trim())
    .filter(Boolean);
}
