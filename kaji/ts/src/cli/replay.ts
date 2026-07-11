/**
 * `kaji replay <session.jsonl>` — parse a JSONL event log and render it
 * to stdout in one of three formats: tree (default), summary, or json.
 *
 * All file I/O happens here; `render.ts` is pure (no I/O).
 */
import {
  KajiEvent,
  StoredKajiEvent,
  type KajiEvent as KajiEventType,
  type StoredKajiEvent as StoredKajiEventType,
} from "@/events/schemas";
import { renderJson, renderSummary, renderTree } from "@/cli/render";
import { readTextFile } from "@/cli/bun-io";

export interface ReplayOptions {
  log?: (msg: string) => void;
  err?: (msg: string) => void;
}

export async function replay(argv: string[], opts: ReplayOptions): Promise<number> {
  const log = opts.log ?? ((m: string) => process.stdout.write(m + "\n"));
  const err = opts.err ?? ((m: string) => process.stderr.write(m + "\n"));

  let format: "tree" | "summary" | "json" = "tree";
  let file: string | undefined;
  let filterKind: string | undefined;
  let grepPattern: string | undefined;
  let tail = false;

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]!;
    if (arg === "--format" || arg === "-f") {
      const fmt = argv[++i];
      if (fmt === "tree" || fmt === "summary" || fmt === "json") {
        format = fmt;
      } else {
        err(`--format must be tree, summary, or json`);
        return 1;
      }
    } else if (arg === "--filter") {
      filterKind = argv[++i];
    } else if (arg === "--grep") {
      grepPattern = argv[++i];
    } else if (arg === "--tail") {
      tail = true;
    } else if (!arg.startsWith("-")) {
      file = arg;
    }
  }

  if (!file) {
    err(
      "usage: kaji replay <session.jsonl> [--format tree|summary|json] " +
        "[--filter <kind>] [--grep <pattern>] [--tail]",
    );
    return 1;
  }

  let raw: string;
  try {
    raw = await readTextFile(file);
  } catch {
    err(`Cannot read file: ${file}`);
    return 1;
  }

  const events: Array<KajiEventType | StoredKajiEventType> = [];
  let nonBlankLines = 0;
  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    nonBlankLines++;
    try {
      const value: unknown = JSON.parse(trimmed);
      const parsed =
        value !== null && typeof value === "object" && "sequence" in value
          ? StoredKajiEvent.safeParse(value)
          : KajiEvent.safeParse(value);
      if (parsed.success) {
        events.push(parsed.data);
      }
      // Silently skip invalid / unrecognised event shapes
    } catch {
      // Skip non-JSON lines
    }
  }

  // A non-empty file that yields zero events is almost always the wrong file
  // or a corrupt log, not a legitimately empty session — warn instead of
  // silently succeeding with no output.
  if (nonBlankLines > 0 && events.length === 0) {
    err(`Warning: ${file} has ${nonBlankLines} line(s) but no parseable kaji events.`);
  }

  let filtered = events;
  if (filterKind) {
    filtered = filtered.filter((e) => e.type === filterKind);
  }
  if (grepPattern) {
    const re = new RegExp(grepPattern, "i");
    filtered = filtered.filter((e) => re.test(JSON.stringify(e)));
  }
  if (tail) {
    filtered = filtered.slice(-20);
  }

  let output: string;
  if (format === "tree") {
    output = renderTree(filtered);
  } else if (format === "summary") {
    output = renderSummary(filtered);
  } else {
    output = renderJson(filtered);
  }

  log(output);
  return 0;
}
