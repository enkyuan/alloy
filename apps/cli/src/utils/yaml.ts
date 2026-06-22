// ---------------------------------------------------------------------------
// Minimal YAML → JSON converter (no dependencies)
// Supports only the subset needed to parse OpenAPI path blocks:
// scalars, block mappings, block sequences, quoted strings, multi-line values.
// For production use, add js-yaml.
// ---------------------------------------------------------------------------

/**
 * Extremely minimal YAML parser — covers the OpenAPI 3.x path section well
 * enough for V0 code-gen.  Handles:
 *   - block mappings (key: value)
 *   - block sequences (- item)
 *   - quoted strings ('…' and "…")
 *   - null / bool / number scalars
 *   - comments (#)
 *   - indented nesting via indent tracking
 *
 * Does NOT handle: anchors, merge keys, flow objects/arrays, multi-doc files.
 */
export function parseYaml(text: string): unknown {
  const lines = text.split(/\r?\n/);
  let pos = 0;

  function currentIndent(line: string): number {
    let i = 0;
    while (i < line.length && line[i] === " ") i++;
    return i;
  }

  function isBlankOrComment(line: string): boolean {
    const t = line.trim();
    return t === "" || t.startsWith("#");
  }

  function parseScalar(raw: string): unknown {
    const t = raw.trim();
    if (t === "" || t === "null" || t === "~") return null;
    if (t === "true") return true;
    if (t === "false") return false;
    const n = Number(t);
    if (!Number.isNaN(n) && t !== "") return n;
    // Strip inline comments
    const noComment = t.replace(/\s+#.*$/, "");
    // Strip quotes
    if (
      (noComment.startsWith('"') && noComment.endsWith('"')) ||
      (noComment.startsWith("'") && noComment.endsWith("'"))
    ) {
      return noComment.slice(1, -1);
    }
    return noComment;
  }

  function parseMapping(baseIndent: number): Record<string, unknown> {
    const obj: Record<string, unknown> = {};

    while (pos < lines.length) {
      // Skip blanks/comments
      while (pos < lines.length && isBlankOrComment(lines[pos])) pos++;
      if (pos >= lines.length) break;

      const line = lines[pos];
      const ind = currentIndent(line);
      if (ind < baseIndent) break;

      const trimmed = line.trim();
      if (trimmed.startsWith("#")) {
        pos++;
        continue;
      }

      // Sequence items at this level belong to a parent
      if (trimmed.startsWith("- ")) break;

      // Parse key: value
      const colonIdx = trimmed.indexOf(": ");
      const bareColon = trimmed.endsWith(":");

      if (colonIdx === -1 && !bareColon) {
        // Not a key line — skip
        pos++;
        continue;
      }

      let key: string;
      let inlineValue: string | null;

      if (bareColon && colonIdx === -1) {
        key = trimmed.slice(0, -1).trim();
        inlineValue = null;
      } else {
        key = trimmed.slice(0, colonIdx).trim();
        inlineValue = trimmed.slice(colonIdx + 2).trim();
      }

      // Strip quotes from key
      if (
        (key.startsWith('"') && key.endsWith('"')) ||
        (key.startsWith("'") && key.endsWith("'"))
      ) {
        key = key.slice(1, -1);
      }

      pos++;

      if (inlineValue === null || inlineValue === "") {
        // Value is on next lines
        // Skip blanks
        while (pos < lines.length && isBlankOrComment(lines[pos])) pos++;
        if (pos >= lines.length) {
          obj[key] = null;
          continue;
        }
        const nextLine = lines[pos];
        const nextInd = currentIndent(nextLine);
        const nextTrim = nextLine.trim();

        if (nextInd <= ind && !isBlankOrComment(nextLine)) {
          obj[key] = null;
          continue;
        }

        if (nextTrim.startsWith("- ") || nextTrim === "-") {
          obj[key] = parseSequence(nextInd);
        } else {
          obj[key] = parseMapping(nextInd);
        }
      } else {
        obj[key] = parseScalar(inlineValue);
      }
    }

    return obj;
  }

  function parseSequence(baseIndent: number): unknown[] {
    const arr: unknown[] = [];

    while (pos < lines.length) {
      while (pos < lines.length && isBlankOrComment(lines[pos])) pos++;
      if (pos >= lines.length) break;

      const line = lines[pos];
      const ind = currentIndent(line);
      if (ind < baseIndent) break;

      const trimmed = line.trim();
      if (!trimmed.startsWith("- ") && trimmed !== "-") break;

      const itemContent = trimmed === "-" ? "" : trimmed.slice(2).trim();
      pos++;

      if (itemContent === "") {
        // Value is on next lines
        while (pos < lines.length && isBlankOrComment(lines[pos])) pos++;
        if (pos >= lines.length) {
          arr.push(null);
          continue;
        }
        const nextLine = lines[pos];
        const nextInd = currentIndent(nextLine);
        const nextTrim = nextLine.trim();

        if (nextTrim.startsWith("- ")) {
          arr.push(parseSequence(nextInd));
        } else {
          arr.push(parseMapping(nextInd));
        }
      } else {
        // Check if inline mapping follows
        if (itemContent.includes(": ") || itemContent.endsWith(":")) {
          // Parse as an inline mapping merged with subsequent indented lines
          const tempLines = [" ".repeat(baseIndent + 2) + itemContent];
          // Peek ahead for continuation
          while (pos < lines.length && !isBlankOrComment(lines[pos])) {
            const l = lines[pos];
            const li = currentIndent(l);
            if (li <= baseIndent) break;
            tempLines.push(l);
            pos++;
          }
          lines.splice(pos - tempLines.length + 1, 0);
          // Parse the mini-mapping
          const miniParser = parseYaml(tempLines.join("\n"));
          arr.push(miniParser);
        } else {
          arr.push(parseScalar(itemContent));
        }
      }
    }

    return arr;
  }

  // Entry point
  while (pos < lines.length && isBlankOrComment(lines[pos])) pos++;
  if (pos >= lines.length) return {};

  const firstLine = lines[pos];
  const firstInd = currentIndent(firstLine);
  const firstTrim = firstLine.trim();

  if (firstTrim.startsWith("- ")) {
    return parseSequence(firstInd);
  }
  return parseMapping(firstInd);
}
