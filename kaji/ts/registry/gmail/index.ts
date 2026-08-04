// This is YOUR Gmail integration. Edit it.

import {
  Integration,
  type MetricsSink,
  type ToolExecutionContext,
  type ToolHandler,
  type ToolSpec,
  type TraceSink,
} from "kaji-sdk";
import { createGmailRequester } from "kaji-sdk/integrations";

import { GmailClient } from "./client";

export type SharedGmailClient = Pick<GmailClient, "listMessages" | "getMessage" | "sendMessage">;

function parameters(
  properties: Readonly<Record<string, unknown>>,
  required: readonly string[],
): Record<string, unknown> {
  return {
    $schema: "https://json-schema.org/draft/2020-12/schema",
    type: "object",
    properties,
    required: [...required],
    additionalProperties: false,
  };
}

function specs(): readonly ToolSpec[] {
  return [
    {
      name: "list_messages",
      description:
        "List messages in the authenticated user's mailbox. Pass `page_token` from a prior result's `next_page_token` to page through results.",
      parameters: parameters(
        {
          query: { type: "string", minLength: 1, maxLength: 1_024 },
          max_results: { type: "integer", minimum: 1, maximum: 100, default: 10 },
          page_token: { type: "string", minLength: 1, maxLength: 2_048 },
        },
        [],
      ),
      risk: "read",
      parallel_safe: true,
      timeout_ms: 10_000,
    },
    {
      name: "get_message",
      description: "Get a message from the authenticated user's mailbox.",
      parameters: parameters(
        {
          message_id: { type: "string", minLength: 1, maxLength: 128 },
        },
        ["message_id"],
      ),
      risk: "read",
      parallel_safe: true,
      timeout_ms: 10_000,
    },
    {
      name: "send_message",
      description:
        "Send an email as the authenticated user. `raw` is the complete RFC 2822 message, base64url-encoded.",
      parameters: parameters(
        {
          raw: { type: "string", minLength: 1, maxLength: 1_048_576 },
        },
        ["raw"],
      ),
      risk: "external_effect",
      parallel_safe: false,
      timeout_ms: 15_000,
    },
  ];
}

function objectResult(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("Gmail client returned an invalid tool result");
  }
  return value as Record<string, unknown>;
}

function handler(client: SharedGmailClient, name: string): ToolHandler {
  return async (args, context) => {
    switch (name) {
      case "list_messages":
        return objectResult(
          await client.listMessages(context, {
            ...(args.query === undefined ? {} : { query: args.query as string }),
            ...(args.max_results === undefined ? {} : { maxResults: args.max_results as number }),
            ...(args.page_token === undefined ? {} : { pageToken: args.page_token as string }),
          }),
        );
      case "get_message":
        return objectResult(
          await client.getMessage(context, { messageId: args.message_id as string }),
        );
      case "send_message":
        return objectResult(await client.sendMessage(context, { raw: args.raw as string }));
      default:
        throw new Error("Unknown Gmail tool");
    }
  };
}

export function createSharedGmailToolBindings(
  client: SharedGmailClient,
): [ToolSpec, ToolHandler][] {
  return specs().map((spec) => [spec, handler(client, spec.name)]);
}

export class GmailIntegration extends Integration {
  readonly namespace = "gmail";
  private closeOwnedRequester: (() => void) | undefined;

  constructor(
    private readonly client: SharedGmailClient,
    closeOwnedRequester?: () => void,
  ) {
    super();
    this.closeOwnedRequester = closeOwnedRequester;
  }

  override tools(): [ToolSpec, ToolHandler][] {
    return createSharedGmailToolBindings(this.client);
  }

  close(): void {
    const close = this.closeOwnedRequester;
    if (close === undefined) return;
    close();
    this.closeOwnedRequester = undefined;
  }
}

export interface CreateGmailIntegrationOptions {
  readonly tokenFor: (context: ToolExecutionContext) => Promise<string>;
  readonly metricsSink?: MetricsSink;
  readonly traceSink?: TraceSink;
}

export function createGmailIntegration(options: CreateGmailIntegrationOptions): GmailIntegration {
  const { metricsSink, traceSink, ...clientOptions } = options;
  const http = createGmailRequester({ metricsSink, traceSink });
  return new GmailIntegration(new GmailClient({ ...clientOptions, http }), () => http.close());
}

function createGmailIntegrationForTest(client: SharedGmailClient): GmailIntegration {
  return new GmailIntegration(client);
}

const inspectionClient = new Proxy(
  {},
  {
    get: () => async () => {
      throw new Error("inspection dependencies must not execute");
    },
  },
) as SharedGmailClient;

export function inspectIntegration(): GmailIntegration {
  return createGmailIntegrationForTest(inspectionClient);
}
