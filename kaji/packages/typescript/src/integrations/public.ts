import { durableJsonSnapshot } from "@/events/json";
import { MAX_DURABLE_TOOL_RESULT_BYTES } from "@/events/schemas";

export {
  INTEGRATION_RECOVERY,
  closedRecoveryFields,
  type IntegrationRecoveryFields,
  type IntegrationRecoveryReason,
} from "@/contracts/integration-recovery";
export type { BoundedResponse } from "@/integrations/safe-fetch";
export {
  createGitHubRequester,
  createGmailRequester,
  type FixedOriginRequester,
} from "@/integrations/fixed-origin";
export {
  IntegrationAuthRequiredError,
  IntegrationExecutionError,
  IntegrationPolicyError,
  IntegrationRateLimitedError,
  IntegrationTransientReadError,
} from "@/integrations/errors";

/** Detach and deeply freeze one integration result under the durable tool cap. */
export function snapshotIntegrationResult(value: unknown): unknown {
  return durableJsonSnapshot(value, "tool_result", MAX_DURABLE_TOOL_RESULT_BYTES);
}
