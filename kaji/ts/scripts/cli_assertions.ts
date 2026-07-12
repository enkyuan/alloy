export const EXPECTED_ECHO_DESCRIPTION =
  "Trivial echo integration. Two pure functions, no auth, no network. Proves the cross-language registry contract.";
export const EXPECTED_GITHUB_DESCRIPTION =
  "Repository-scoped GitHub code, issue, and comment tools.";

interface IntegrationRow {
  name: string;
  tier: "beta" | "experimental";
  version: string;
  description: string;
}

function parseIntegrationRow(line: string): IntegrationRow | undefined {
  const match = /^(\S+)\s{2,}\[(beta|experimental)\]\s{2,}v(\S+)\s{2,}(.+)$/u.exec(line);
  if (match === null) return undefined;
  return {
    name: match[1]!,
    tier: match[2]! as IntegrationRow["tier"],
    version: match[3]!,
    description: match[4]!,
  };
}

export function assertCliListOutput(output: string): void {
  const lines = output.split("\n").filter((line) => line.length > 0);
  const rows = lines.map(parseIntegrationRow);
  if (rows.some((row) => row === undefined)) {
    throw new Error("installed list-integrations emitted a malformed row");
  }
  const echoRows = rows.filter((row) => row?.name === "echo");
  if (echoRows.length !== 1) {
    throw new Error("installed list-integrations omitted the canonical Echo row");
  }
  const echo = echoRows[0]!;
  if (
    echo.tier !== "beta" ||
    echo.version !== "0.1.0" ||
    echo.description !== EXPECTED_ECHO_DESCRIPTION
  ) {
    throw new Error("installed list-integrations emitted a non-canonical Echo row");
  }
  const githubRows = rows.filter((row) => row?.name === "github");
  if (githubRows.length !== 1) {
    throw new Error("installed list-integrations omitted the canonical GitHub row");
  }
  const github = githubRows[0]!;
  if (
    github.tier !== "experimental" ||
    github.version !== "0.1.0" ||
    github.description !== EXPECTED_GITHUB_DESCRIPTION
  ) {
    throw new Error("installed list-integrations emitted a non-canonical GitHub row");
  }
}
