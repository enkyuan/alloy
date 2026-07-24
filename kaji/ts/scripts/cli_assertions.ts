export const EXPECTED_ECHO_DESCRIPTION =
  "Trivial echo integration. Two pure functions, no auth, no network. Proves the cross-language registry contract.";
export const EXPECTED_GITHUB_DESCRIPTION =
  "Repository-scoped GitHub code, issue, and comment tools.";

export function assertCliListOutput(output: string): void {
  let rows: Array<Record<string, unknown>>;
  try {
    const parsed: unknown = JSON.parse(output);
    if (!Array.isArray(parsed) || parsed.some((row) => typeof row !== "object" || row === null)) {
      throw new Error();
    }
    rows = parsed as Array<Record<string, unknown>>;
  } catch {
    throw new Error("installed list-integrations emitted malformed JSON");
  }
  const echoRows = rows.filter((row) => row.name === "echo");
  if (echoRows.length !== 1) {
    throw new Error("installed list-integrations omitted the canonical Echo row");
  }
  const echo = echoRows[0]!;
  if (
    JSON.stringify(echo) !==
    JSON.stringify({
      name: "echo",
      version: "0.1.0",
      stability: "beta",
      runtimes: ["python", "typescript"],
      auth: { kind: "none", provider: null },
      experimental_opt_in_required: false,
      next_commands: {
        python: "python -m kaji.cli add echo",
        typescript: "bun --no-install -e 'import(\"kaji-sdk/cli\")' -- add echo",
      },
    })
  ) {
    throw new Error("installed list-integrations emitted a non-canonical Echo row");
  }
  const githubRows = rows.filter((row) => row.name === "github");
  if (githubRows.length !== 1) {
    throw new Error("installed list-integrations omitted the canonical GitHub row");
  }
  const github = githubRows[0]!;
  if (
    github.stability !== "experimental" ||
    github.version !== "0.1.0" ||
    JSON.stringify(github.auth) !== JSON.stringify({ kind: "env", provider: null }) ||
    JSON.stringify(github.next_commands) !==
      JSON.stringify({
        python: "python -m kaji.cli add github --allow-experimental",
        typescript:
          "bun --no-install -e 'import(\"kaji-sdk/cli\")' -- add github --allow-experimental",
      })
  ) {
    throw new Error("installed list-integrations emitted a non-canonical GitHub row");
  }
}
