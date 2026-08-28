import { describe, expect, it, vi } from "vitest";
import * as z from "zod";

import type { IntegrationManifestDocument } from "@/integrations/registry-loader";
import type { ToolSpec } from "@/tools/registry";
import { functionTool } from "@/integrations/functional";
import {
  executableIntegrationAbi,
  discoverIntegrationTools,
  inspectIntegrationModule,
  IntegrationAbiMismatchError,
  compareExecutableIntegrationAbi,
  compareManifestAbi,
  echoExecutableAbi,
  integrationAbiJson,
} from "../scripts/integration-abi";
import { tools as echoTools } from "../registry/echo/index";

const parameters = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  type: "object",
  properties: { message: { type: "string" } },
  required: ["message"],
  additionalProperties: false,
} as const;

function spec(overrides: Partial<ToolSpec> = {}): ToolSpec {
  return {
    name: "say",
    description: "Return the input string unchanged.",
    parameters,
    risk: "read",
    parallel_safe: false,
    ...overrides,
  };
}

function manifest(
  tools: readonly IntegrationManifestDocument["tools"][number][],
): IntegrationManifestDocument {
  return {
    name: "echo",
    version: "0.1.0",
    namespace: "echo",
    description: "Echo.",
    auth: { kind: "none" },
    files: ["index.ts"],
    tools: [...tools],
  };
}

const declaredSay = {
  name: "say",
  description: "Return the input string unchanged.",
  parameters,
  risk: "read",
  parallel_safe: false,
} as const;

describe("integration manifest executable ABI", () => {
  it("matches the shipped Echo manifest to side-effect-free executable metadata", () => {
    const executable = echoExecutableAbi();
    expect(executable.namespace).toBe("echo");
    expect(() =>
      compareExecutableIntegrationAbi(manifest(executable.tools), executable),
    ).not.toThrow();
  });

  it("rejects namespace drift", () => {
    const executable = executableIntegrationAbi(echoTools);
    const compare = () =>
      compareExecutableIntegrationAbi(
        { ...manifest(executable.tools), namespace: "other" },
        executable,
      );
    expect(compare).toThrowError(expect.objectContaining({ pointer: "/namespace" }));
    expect(compare).toThrowError(/INTEGRATION_ABI_MISMATCH/);
  });

  it("fails when any indexed executable differs from its canonical ABI", () => {
    const executable = {
      namespace: "echo",
      tools: [{ ...declaredSay, risk: "external_effect" as const }],
    };
    expect(() => compareExecutableIntegrationAbi(manifest([declaredSay]), executable)).toThrow(
      /INTEGRATION_ABI_MISMATCH at \/tools\/0\/risk/,
    );
  });

  it.each([
    ["description", "/tools/0/description", { description: "drift" }],
    ["risk", "/tools/0/risk", { risk: "write" as const }],
    ["parameters", "/tools/0/parameters/type", { parameters: { ...parameters, type: "array" } }],
    ["parallel_safe", "/tools/0/parallel_safe", { parallel_safe: true }],
    ["timeout_ms", "/tools/0/timeout_ms", { timeout_ms: 5 }],
  ])("rejects %s drift", (_field, pointer, override) => {
    expect(() => compareManifestAbi(manifest([declaredSay]), [spec(override)])).toThrowError(
      expect.objectContaining<Partial<IntegrationAbiMismatchError>>({
        pointer,
      }),
    );
  });

  it.each([
    ["missing", {}],
    ["non-boolean", { parallel_safe: "false" }],
  ])("rejects %s executable parallel_safe metadata", (_case, override) => {
    const malformed: Record<string, unknown> = { ...spec(), ...override };
    if (_case === "missing") delete malformed.parallel_safe;

    expect(() =>
      compareManifestAbi(manifest([declaredSay]), [malformed as unknown as ToolSpec]),
    ).toThrowError(
      expect.objectContaining<Partial<IntegrationAbiMismatchError>>({
        code: "INTEGRATION_ABI_MISMATCH",
        pointer: "/tools/0/parallel_safe",
      }),
    );
  });

  it("rejects a manifest tool missing from runtime exports", () => {
    expect(() =>
      compareManifestAbi(
        manifest([
          declaredSay,
          { ...declaredSay, name: "shout", description: "Return uppercased text." },
        ]),
        [spec()],
      ),
    ).toThrowError(expect.objectContaining({ pointer: "/tools/1" }));
  });

  it("rejects a runtime export missing from the manifest", () => {
    expect(() =>
      compareManifestAbi(manifest([declaredSay]), [
        spec(),
        spec({ name: "shout", description: "Return uppercased text." }),
      ]),
    ).toThrowError(expect.objectContaining({ pointer: "/tools/1" }));
  });

  it("rejects duplicate normalized executable names", () => {
    expect(() => compareManifestAbi(manifest([declaredSay]), [spec(), spec()])).toThrowError(
      expect.objectContaining({ pointer: "/tools/1/name" }),
    );
  });

  it("rejects duplicate manifest tool names", () => {
    expect(() =>
      compareManifestAbi(manifest([declaredSay, { ...declaredSay }]), [spec()]),
    ).toThrowError(expect.objectContaining({ pointer: "/tools/1/name" }));
  });

  it("ignores JSON object key order while comparing parameter schemas", () => {
    const reordered = {
      $schema: parameters.$schema,
      additionalProperties: false,
      required: ["message"],
      properties: { message: { type: "string" } },
      type: "object",
    };
    expect(() =>
      compareManifestAbi(manifest([{ ...declaredSay, parameters: reordered }]), [spec()]),
    ).not.toThrow();
  });

  it("reads only metadata and cannot execute a handler", () => {
    const handler = vi.fn(async ({ message }: { message: string }) => ({ message }));
    const tool = functionTool(
      {
        name: "say",
        namespace: "echo",
        description: "Return the input string unchanged.",
        parameters: z.strictObject({ message: z.string() }),
        risk: "read",
        parallel_safe: false,
      },
      handler,
    );
    expect(() => executableIntegrationAbi([tool])).not.toThrow();
    expect(handler).not.toHaveBeenCalled();
  });

  it("loads executable metadata through the generic inspector entry point", () => {
    const handler = vi.fn();
    const tools = vi.fn(() => [[spec(), handler] as const]);
    const inspectIntegration = vi.fn(() => ({ namespace: "echo", tools }));

    expect(inspectIntegrationModule({ inspectIntegration })).toEqual({
      namespace: "echo",
      tools: [declaredSay],
    });
    expect(inspectIntegration).toHaveBeenCalledOnce();
    expect(tools).toHaveBeenCalledOnce();
    expect(handler).not.toHaveBeenCalled();
  });

  it("rejects a missing inspector without exposing module values", () => {
    expect(() => inspectIntegrationModule({})).toThrowError(
      expect.objectContaining({ pointer: "/inspectIntegration" }),
    );
  });

  it("redacts top-level inspector errors", () => {
    const inspect = () => {
      throw new Error("secret inspector failure");
    };
    const run = () => inspectIntegrationModule({ inspectIntegration: inspect });

    expect(run).toThrowError(expect.objectContaining({ pointer: "/inspectIntegration" }));
    expect(run).not.toThrowError(/secret inspector failure/);
  });

  it("rejects mixed executable namespaces", () => {
    expect(() =>
      executableIntegrationAbi([echoTools[0], { namespace: "other", spec: echoTools[1].spec }]),
    ).toThrowError(expect.objectContaining({ pointer: "/tools/1/namespace" }));
  });

  it("rejects a BoundTool export omitted from the discovery list", () => {
    expect(() =>
      discoverIntegrationTools({ say: echoTools[0], shout: echoTools[1] }, [echoTools[0]]),
    ).toThrowError(expect.objectContaining({ pointer: "/exports/shout" }));
  });

  it("serializes typed CLI mismatch details without raw values", () => {
    const output = integrationAbiJson(() => {
      throw new IntegrationAbiMismatchError(
        "/exports/shout",
        "listed in tools",
        "unlisted BoundTool export",
      );
    });
    expect(JSON.parse(output)).toEqual({
      error: {
        code: "INTEGRATION_ABI_MISMATCH",
        pointer: "/exports/shout",
        expected: "<string length=15>",
        actual: "<string length=25>",
      },
    });
    expect(output).not.toContain("listed in tools");
    expect(output).not.toContain("unlisted BoundTool export");
  });

  it("summarizes primitive mismatches without printing rejected values", () => {
    const output = integrationAbiJson(() => {
      throw new IntegrationAbiMismatchError("/tools/0/timeout_ms", true, 12345);
    });
    expect(JSON.parse(output)).toEqual({
      error: {
        code: "INTEGRATION_ABI_MISMATCH",
        pointer: "/tools/0/timeout_ms",
        expected: "<boolean>",
        actual: "<number>",
      },
    });
    expect(output).not.toContain("12345");
  });
});
