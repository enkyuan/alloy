import * as z from "zod";

import { MAX_DURABLE_TOOL_RESULT_BYTES } from "@/events/errors";
import { durableJsonSnapshot, type DeepReadonly, type JsonValue } from "@/events/json";

const namespacedType = /^[^/\s]+\/[^/\s]+$/;
const uriWithScheme = /^[A-Za-z][A-Za-z0-9+.-]*:/;

export interface ArtifactRef {
  readonly id: string;
  readonly type: string;
  readonly uri: string;
  readonly version?: string;
  readonly media_type?: string;
  readonly metadata?: DeepReadonly<Record<string, JsonValue>>;
}

export const ArtifactRefSchema = z
  .object({
    id: z.string().min(1),
    type: z.string().regex(namespacedType),
    uri: z.string().regex(uriWithScheme),
    version: z.string().min(1).optional(),
    media_type: z.string().min(1).optional(),
    metadata: z.record(z.string(), z.unknown()).optional(),
  })
  .strict()
  .superRefine((value, ctx) => {
    try {
      durableJsonSnapshot(value, "artifact_ref", MAX_DURABLE_TOOL_RESULT_BYTES);
    } catch {
      ctx.addIssue({ code: "custom", message: "artifact ref must be bounded durable JSON" });
    }
  });

export function validateArtifactRef(value: unknown): ArtifactRef {
  return durableJsonSnapshot(
    ArtifactRefSchema.parse(value),
    "artifact_ref",
    MAX_DURABLE_TOOL_RESULT_BYTES,
  ) as unknown as ArtifactRef;
}

export function artifact(
  id: string,
  type: string,
  uri: string,
  options: Omit<ArtifactRef, "id" | "type" | "uri"> = {},
): ArtifactRef {
  return validateArtifactRef({ id, type, uri, ...options });
}
