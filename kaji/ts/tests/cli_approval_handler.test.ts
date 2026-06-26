/**
 * Tests for `cliApprovalHandler`. Drives the factory with in-memory streams
 * so the prompt text and stdin reading are testable without a real tty.
 */
import { describe, expect, it } from "vitest";
import { Readable, Writable } from "node:stream";
import { cliApprovalHandler } from "../src/tools/cli_approval_handler";

function streamFromString(s: string): NodeJS.ReadableStream {
  return Readable.from([s]);
}

function captureWritable(): { stream: NodeJS.WritableStream; chunks: string[] } {
  const chunks: string[] = [];
  const stream = new Writable({
    write(chunk, _enc, cb) {
      chunks.push(chunk.toString());
      cb();
    },
  });
  return { stream, chunks };
}

describe("cliApprovalHandler", () => {
  it("returns true for 'y'", async () => {
    const out = captureWritable();
    const handler = cliApprovalHandler({ input: streamFromString("y\n"), output: out.stream });
    const result = await handler("ship_it", { force: true }, "write");
    expect(result).toBe(true);
    const printed = out.chunks.join("");
    expect(printed).toMatch(/ship_it/);
    expect(printed).toMatch(/write/);
    expect(printed).toMatch(/force/);
  });

  it("is case-insensitive on 'Y'", async () => {
    const out = captureWritable();
    const handler = cliApprovalHandler({ input: streamFromString("Y\n"), output: out.stream });
    const result = await handler("ship_it", {}, "write");
    expect(result).toBe(true);
  });

  it("returns false for 'n'", async () => {
    const out = captureWritable();
    const handler = cliApprovalHandler({ input: streamFromString("n\n"), output: out.stream });
    const result = await handler("ship_it", {}, undefined);
    expect(result).toBe(false);
  });

  it("returns false for any other input", async () => {
    const out = captureWritable();
    const handler = cliApprovalHandler({ input: streamFromString("maybe\n"), output: out.stream });
    const result = await handler("ship_it", {}, undefined);
    expect(result).toBe(false);
  });

  it("returns false on empty input", async () => {
    const out = captureWritable();
    const handler = cliApprovalHandler({ input: streamFromString("\n"), output: out.stream });
    const result = await handler("ship_it", {}, undefined);
    expect(result).toBe(false);
  });

  it("renders 'unknown' when risk is undefined", async () => {
    const out = captureWritable();
    const handler = cliApprovalHandler({ input: streamFromString("n\n"), output: out.stream });
    await handler("ship_it", {}, undefined);
    expect(out.chunks.join("")).toMatch(/risk: unknown/);
  });

  it("prints the optional label to disambiguate concurrent agents", async () => {
    const out = captureWritable();
    const handler = cliApprovalHandler({
      input: streamFromString("y\n"),
      output: out.stream,
      label: "agent-a",
    });
    await handler("ship_it", {}, "write");
    expect(out.chunks.join("")).toMatch(/\[agent-a\]/);
  });
});
