import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { INTEGRATION_RECOVERY } from "@/integrations/recovery";

describe("integration recovery contract", () => {
  it("matches every canonical packaged recovery row and field", () => {
    const contract = JSON.parse(
      readFileSync(
        resolve(import.meta.dirname, "../contracts/errors/integration-recovery-v1.json"),
        "utf8",
      ),
    ) as { entries: Record<string, Record<string, string>> };
    const runtime = Object.fromEntries(
      Object.entries(INTEGRATION_RECOVERY).map(([reason, recovery]) => [
        reason,
        {
          errorCode: recovery.errorCode,
          recoveryCode: recovery.recoveryCode,
          docUrl: recovery.docUrl,
          problem: recovery.problem,
          cause: recovery.cause,
          fix: recovery.fix,
        },
      ]),
    );

    expect(runtime).toEqual(contract.entries);
    expect(Object.isFrozen(INTEGRATION_RECOVERY)).toBe(true);
  });
});
