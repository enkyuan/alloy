/** Fail-closed JSONL replay with a closed, redaction-safe output projection. */
import {
  validateNewEvent,
  validateStoredEvent,
  type KajiEvent as KajiEventType,
  type StoredKajiEvent as StoredKajiEventType,
} from "@/events/schemas";
import { renderJson, renderSummary, renderTree } from "@/cli/render";
import { readTextFile } from "@/cli/bun-io";

export interface ReplayOptions {
  log?: (msg: string) => void;
  err?: (msg: string) => void;
  noColor?: boolean;
  verbose?: boolean;
}

function usage(err: (message: string) => void, message?: string): number {
  if (message !== undefined) err(`Error: ${message}`);
  err(
    "usage: kaji replay <session.jsonl> [--format tree|summary|json] " +
      "[--filter <kind>] [--grep <pattern>] [--tail]",
  );
  return 2;
}

export async function replay(argv: string[], opts: ReplayOptions): Promise<number> {
  const log = opts.log ?? ((message: string) => process.stdout.write(message + "\n"));
  const err = opts.err ?? ((message: string) => process.stderr.write(message + "\n"));

  let format: "tree" | "summary" | "json" = "tree";
  let file: string | undefined;
  let filterKind: string | undefined;
  let grepPattern: string | undefined;
  let tail = false;

  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index]!;
    if (arg === "--format" || arg === "-f") {
      const value = argv[++index];
      if (value === undefined) return usage(err, "--format requires a value");
      if (value !== "tree" && value !== "summary" && value !== "json") {
        return usage(err, "--format must be tree, summary, or json");
      }
      format = value;
    } else if (arg === "--filter" || arg === "--grep") {
      const value = argv[++index];
      if (value === undefined || value.startsWith("--")) {
        return usage(err, `${arg} requires a value`);
      }
      if (arg === "--filter") filterKind = value;
      else grepPattern = value;
    } else if (arg === "--tail") {
      tail = true;
    } else if (arg.startsWith("-")) {
      return usage(err, `unknown argument: ${arg}`);
    } else if (file === undefined) {
      file = arg;
    } else {
      return usage(err, `unexpected path argument: ${arg}`);
    }
  }

  if (file === undefined) return usage(err);

  let raw: string;
  try {
    raw = await readTextFile(file);
  } catch {
    err("error_code=REPLAY_READ_FAILED reason=unreadable_file");
    return 1;
  }

  const events: Array<KajiEventType | StoredKajiEventType> = [];
  const lines = raw.split("\n");
  for (let index = 0; index < lines.length; index++) {
    const trimmed = lines[index]!.trim();
    if (trimmed.length === 0) continue;
    let value: unknown;
    try {
      value = JSON.parse(trimmed);
    } catch {
      err(`error_code=INVALID_REPLAY_LOG line=${index + 1} reason=invalid_json`);
      return 1;
    }
    try {
      const parsed =
        value !== null && typeof value === "object" && "sequence" in value
          ? validateStoredEvent(value)
          : validateNewEvent(value);
      events.push(parsed);
    } catch {
      err(`error_code=INVALID_REPLAY_LOG line=${index + 1} reason=invalid_event`);
      return 1;
    }
  }

  let filtered = events;
  if (filterKind !== undefined) filtered = filtered.filter((event) => event.type === filterKind);
  if (grepPattern !== undefined) {
    let expression: RegExp;
    try {
      expression = new RegExp(grepPattern, "i");
    } catch {
      err("error_code=INVALID_REPLAY_FILTER reason=invalid_pattern");
      return 1;
    }
    filtered = filtered.filter((event) => expression.test(JSON.stringify(event)));
  }
  if (tail) filtered = filtered.slice(-20);

  const color = !opts.noColor;
  const output =
    format === "tree"
      ? renderTree(filtered, { color })
      : format === "summary"
        ? renderSummary(filtered, { color })
        : renderJson(filtered);
  log(output);
  return 0;
}
