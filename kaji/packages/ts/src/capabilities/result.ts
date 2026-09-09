import { validateArtifactRef, type ArtifactRef } from "@/artifacts/types";
import { MAX_DURABLE_TOOL_RESULT_BYTES } from "@/events/errors";
import { durableJsonSnapshot, type DeepReadonly, type JsonValue } from "@/events/json";

export interface CapabilityResult<T extends JsonValue = JsonValue> {
  readonly value?: DeepReadonly<T>;
  readonly artifacts: readonly ArtifactRef[];
}

export function capabilityResult<T extends JsonValue = JsonValue>(
  value?: T,
  artifacts: readonly ArtifactRef[] = [],
): CapabilityResult<T> {
  const ids = new Set<string>();
  const validatedArtifacts = artifacts.map((item) => {
    const artifact = validateArtifactRef(item);
    if (ids.has(artifact.id)) throw new TypeError(`duplicate artifact id ${artifact.id}`);
    ids.add(artifact.id);
    return artifact;
  });
  const result: CapabilityResult<T> =
    value === undefined
      ? { artifacts: Object.freeze(validatedArtifacts) }
      : {
          value: durableJsonSnapshot(
            value,
            "tool_result",
            MAX_DURABLE_TOOL_RESULT_BYTES,
          ) as DeepReadonly<T>,
          artifacts: Object.freeze(validatedArtifacts),
        };
  return Object.freeze(result);
}
