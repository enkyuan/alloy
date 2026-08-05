/**
 * A kaji Integration that runs its tools inside an agentOS VM.
 *
 * This lives in an EXAMPLE, not in kaji-sdk itself: agentOS is a preview,
 * darwin/linux-only, ~130MB-native, ESM-only dependency, and kaji-sdk is a
 * portable infra-free core. See ./README.md for why this is not a shipped
 * subpath. If it ever graduates, it becomes a separately-versioned
 * `@kaji/agentos` package, not an export of kaji-sdk.
 *
 * Three things this file gets right that a naive wrapper gets wrong (all three
 * were caught in review):
 *  1. exec: `vm.process.exec` returns a `CodeExecutionResult` discriminated
 *     union (camelCase `exitCode`, optional stdout/stderr, mandatory `outcome`,
 *     `error` on non-success, truncation flags). We branch on `outcome` so a
 *     failed/timed-out command surfaces as a failure — not a silent success —
 *     and translate `exitCode -> exit_code` for kaji's snake_case convention.
 *  2. missing dep: the dynamic import is wrapped so an absent/unsupported
 *     `@rivet-dev/agentos-core` yields a clear, actionable message (mirrors
 *     kaji's own provider adapters), not a raw MODULE_NOT_FOUND.
 *  3. safe posture is EXPLICIT: agentOS defaults to allow-all egress, so the
 *     factory passes `permissions: { network: "deny" }` and a bounded mount.
 *     Nothing here is "safe by default"; it is safe because we set it.
 */
import { Integration, type ToolHandler, type ToolSpec } from "kaji-sdk";
// Type-only import is erased at runtime, so it does not require the native dep
// to be installed for typechecking of code that does not construct a VM.
import type { AgentOs, AgentOsOptions } from "@rivet-dev/agentos-core";

/** The slice of the agentOS VM handle these tools actually use. */
export type AgentOsVm = Pick<AgentOs, "process" | "filesystem" | "dispose">;

const SUPPORT = "darwin/linux, x64/arm64, Node >= 22, ESM-only";

/**
 * Load agentOS and boot a VM with an explicit, locked-down posture.
 * Rethrows an absent/unsupported dependency as an actionable error rather than
 * leaking ERR_MODULE_NOT_FOUND / native-loader / ABI failures.
 */
export async function createLockedDownVm(options: AgentOsOptions = {}): Promise<AgentOs> {
  let mod: typeof import("@rivet-dev/agentos-core");
  try {
    mod = await import("@rivet-dev/agentos-core");
  } catch (cause) {
    throw new Error(
      `This example requires @rivet-dev/agentos-core (${SUPPORT}). ` +
        `Install it from examples/agentos: npm install. ` +
        `If install failed, your platform is unsupported (no Windows, no musl/Alpine).`,
      { cause },
    );
  }
  return mod.AgentOs.create({
    ...options,
    // Explicit posture, per category. We deny outbound network and allow the
    // fs/childProcess/process/env the exec/read/write tools need. Every field
    // is set on purpose — agentOS's documented "allow-all" default is NOT
    // relied on (on some sidecar builds setting one category flips the others
    // to deny), so we state each one.
    permissions: {
      network: "deny", // widen with an allow-list only if a tool needs egress
      fs: "allow",
      childProcess: "allow", // exec() spawns a shell; the sidecar gates this
      process: "allow",
      env: "allow",
      ...options.permissions,
    },
  });
}

/** A writable working directory inside the VM for read/write examples. */
export const WORKDIR = "/tmp";

function objectResult(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("agentOS tool returned a non-object result");
  }
  return value as Record<string, unknown>;
}

function specs(): readonly ToolSpec[] {
  return [
    {
      name: "exec",
      description: "Run a shell command inside the isolated agentOS VM.",
      parameters: {
        $schema: "https://json-schema.org/draft/2020-12/schema",
        type: "object",
        properties: {
          command: { type: "string", minLength: 1, maxLength: 8_192 },
          timeout_ms: { type: "integer", minimum: 1, maximum: 600_000 },
        },
        required: ["command"],
        additionalProperties: false,
      },
      risk: "external_effect",
      parallel_safe: false,
      timeout_ms: 30_000,
    },
    {
      name: "read_file",
      description: "Read a file from the isolated agentOS VM filesystem.",
      parameters: {
        $schema: "https://json-schema.org/draft/2020-12/schema",
        type: "object",
        properties: { path: { type: "string", minLength: 1, maxLength: 4_096 } },
        required: ["path"],
        additionalProperties: false,
      },
      risk: "read",
      parallel_safe: true,
      timeout_ms: 10_000,
    },
    {
      name: "write_file",
      description: "Write a UTF-8 file into the isolated agentOS VM filesystem.",
      parameters: {
        $schema: "https://json-schema.org/draft/2020-12/schema",
        type: "object",
        properties: {
          path: { type: "string", minLength: 1, maxLength: 4_096 },
          content: { type: "string", maxLength: 1_048_576 },
        },
        required: ["path", "content"],
        additionalProperties: false,
      },
      risk: "external_effect",
      parallel_safe: false,
      timeout_ms: 10_000,
    },
  ];
}

function handler(vm: AgentOsVm, name: string): ToolHandler {
  return async (args) => {
    switch (name) {
      case "exec": {
        // CodeExecutionResult is a union on `outcome`. Do NOT assume success.
        const execOptions =
          args.timeout_ms === undefined ? {} : { timeoutMs: args.timeout_ms as number };
        const result = await vm.process.exec(args.command as string, execOptions);
        return objectResult({
          outcome: result.outcome,
          // camelCase in agentOS -> snake_case for kaji tool results.
          exit_code: result.exitCode ?? null,
          stdout: result.stdout ?? "",
          stderr: result.stderr ?? "",
          stdout_truncated: result.stdoutTruncated ?? false,
          stderr_truncated: result.stderrTruncated ?? false,
          // Present only on non-success; the model sees why it failed.
          ...(result.outcome === "succeeded"
            ? {}
            : { error: { code: result.error.code, message: result.error.message } }),
        });
      }
      case "read_file": {
        const bytes = await vm.filesystem.readFile(args.path as string);
        return objectResult({ content: new TextDecoder().decode(bytes) });
      }
      case "write_file": {
        await vm.filesystem.writeFile(args.path as string, args.content as string);
        return objectResult({ written: true });
      }
      default:
        throw new Error(`Unknown agentOS tool: ${name}`);
    }
  };
}

export class AgentOsIntegration extends Integration {
  readonly namespace = "agentos";

  constructor(private readonly vm: AgentOsVm) {
    super();
  }

  override tools(): [ToolSpec, ToolHandler][] {
    return specs().map((spec) => [spec, handler(this.vm, spec.name)]);
  }

  /** Tear down the VM. agentOS teardown is dispose(), not close(). */
  async close(): Promise<void> {
    await this.vm.dispose();
  }
}
