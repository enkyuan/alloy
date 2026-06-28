/**
 * Per-model $/1M token cost table. Updated quarterly.
 * All rates are USD per 1,000,000 tokens.
 */
export interface ModelCostEntry {
  /** Cost in USD per 1M input tokens. */
  inputPer1M: number;
  /** Cost in USD per 1M output tokens. */
  outputPer1M: number;
}

/** Cost table keyed by model name (exact match, or prefix match via `lookupCost`). */
const COST_TABLE: Record<string, ModelCostEntry> = {
  // OpenAI
  "gpt-4o": { inputPer1M: 2.5, outputPer1M: 10.0 },
  "gpt-4o-mini": { inputPer1M: 0.15, outputPer1M: 0.6 },
  "gpt-4-turbo": { inputPer1M: 10.0, outputPer1M: 30.0 },
  "gpt-4": { inputPer1M: 30.0, outputPer1M: 60.0 },
  "gpt-3.5-turbo": { inputPer1M: 0.5, outputPer1M: 1.5 },
  o1: { inputPer1M: 15.0, outputPer1M: 60.0 },
  "o1-mini": { inputPer1M: 3.0, outputPer1M: 12.0 },
  "o3-mini": { inputPer1M: 1.1, outputPer1M: 4.4 },
  o3: { inputPer1M: 10.0, outputPer1M: 40.0 },
  "gpt-4.1": { inputPer1M: 2.0, outputPer1M: 8.0 },
  "gpt-4.1-mini": { inputPer1M: 0.4, outputPer1M: 1.6 },
  "gpt-4.1-nano": { inputPer1M: 0.1, outputPer1M: 0.4 },

  // Anthropic
  "claude-3-5-sonnet-20241022": { inputPer1M: 3.0, outputPer1M: 15.0 },
  "claude-3-5-sonnet": { inputPer1M: 3.0, outputPer1M: 15.0 },
  "claude-3-5-haiku-20241022": { inputPer1M: 0.8, outputPer1M: 4.0 },
  "claude-3-5-haiku": { inputPer1M: 0.8, outputPer1M: 4.0 },
  "claude-3-opus-20240229": { inputPer1M: 15.0, outputPer1M: 75.0 },
  "claude-3-opus": { inputPer1M: 15.0, outputPer1M: 75.0 },
  "claude-3-sonnet-20240229": { inputPer1M: 3.0, outputPer1M: 15.0 },
  "claude-3-haiku-20240307": { inputPer1M: 0.25, outputPer1M: 1.25 },
  "claude-opus-4": { inputPer1M: 15.0, outputPer1M: 75.0 },
  "claude-sonnet-4": { inputPer1M: 3.0, outputPer1M: 15.0 },
  "claude-haiku-4": { inputPer1M: 0.8, outputPer1M: 4.0 },

  // Gemini
  "gemini-2.5-flash": { inputPer1M: 0.15, outputPer1M: 0.6 },
  "gemini-2.5-pro": { inputPer1M: 1.25, outputPer1M: 10.0 },
  "gemini-2.0-flash": { inputPer1M: 0.1, outputPer1M: 0.4 },
  "gemini-1.5-flash": { inputPer1M: 0.075, outputPer1M: 0.3 },
  "gemini-1.5-pro": { inputPer1M: 1.25, outputPer1M: 5.0 },

  // Kimi / Moonshot (via OpenRouter)
  "moonshotai/kimi-k2": { inputPer1M: 0.6, outputPer1M: 2.5 },
  "moonshot-v1-8k": { inputPer1M: 0.12, outputPer1M: 0.12 },
  "moonshot-v1-32k": { inputPer1M: 0.48, outputPer1M: 0.48 },
  "moonshot-v1-128k": { inputPer1M: 1.92, outputPer1M: 1.92 },
};

/**
 * Look up cost for a model. Tries exact match, then prefix match (longest
 * prefix wins). Returns `undefined` when no entry matches.
 */
export function lookupCost(model: string): ModelCostEntry | undefined {
  if (model in COST_TABLE) return COST_TABLE[model];
  let best: ModelCostEntry | undefined;
  let bestLen = 0;
  for (const [key, entry] of Object.entries(COST_TABLE)) {
    if (model.startsWith(key) && key.length > bestLen) {
      best = entry;
      bestLen = key.length;
    }
  }
  return best;
}

/**
 * Calculate cost in USD for a given token count and model.
 * Returns 0 if the model is not in the cost table.
 */
export function calculateCostUsd(model: string, inputTokens: number, outputTokens: number): number {
  const entry = lookupCost(model);
  if (!entry) return 0;
  return (
    (inputTokens / 1_000_000) * entry.inputPer1M + (outputTokens / 1_000_000) * entry.outputPer1M
  );
}
