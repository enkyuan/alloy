import type Anthropic from "@anthropic-ai/sdk";
import type OpenAI from "openai";

import { AnthropicProvider, type AnthropicProviderOptions } from "@/providers/anthropic";
import { OpenAIProvider, type OpenAIProviderOptions } from "@/providers/openai";

export class TestOpenAIProvider extends OpenAIProvider {
  constructor(
    opts: OpenAIProviderOptions,
    private readonly fakeClient: OpenAI,
  ) {
    super(opts);
  }

  protected override async createClient(): Promise<OpenAI> {
    return this.fakeClient;
  }
}

export class TestAnthropicProvider extends AnthropicProvider {
  constructor(
    opts: AnthropicProviderOptions,
    private readonly fakeClient: Anthropic,
  ) {
    super(opts);
  }

  protected override async createClient(): Promise<Anthropic> {
    return this.fakeClient;
  }
}
