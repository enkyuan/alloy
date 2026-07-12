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
  "gpt-5.5": { inputPer1M: 5.0, outputPer1M: 30.0 },
  "gpt-5.4": { inputPer1M: 2.5, outputPer1M: 15.0 },
  "gpt-5.4-mini": { inputPer1M: 0.75, outputPer1M: 4.5 },
  "gpt-5.4-nano": { inputPer1M: 0.2, outputPer1M: 1.25 },
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

const MAX_SAFE_TOKEN_COUNT = 9_007_199_254_740_991;
const TOKENS_PER_RATE_UNIT = 1_000_000n;
const USD_SCALE = 10_000_000_000n;
const MAX_RATE_SIGNIFICANT_DIGITS = 32;
const MAX_RATE_FRACTIONAL_DIGITS = 32;
const MAX_RATE_ABSOLUTE_EXPONENT = 32n;
const MAX_RATE_TEXT_LENGTH = 65;
const DECIMAL_RATE = /^(0|[1-9][0-9]*)(?:\.([0-9]*[1-9]))?$/;
const SCIENTIFIC_RATE = /^([1-9])(?:\.([0-9]*[1-9]))?e(-?[1-9][0-9]*)$/;

interface DecimalParts {
  coefficient: bigint;
  scale: number;
}

function assertTokenCount(name: string, value: number): void {
  if (typeof value !== "number" || !Number.isFinite(value) || !Number.isInteger(value)) {
    throw new TypeError(`${name} must be an integer`);
  }
  if (value < 0 || value > MAX_SAFE_TOKEN_COUNT) {
    throw new RangeError(`${name} must be between 0 and ${MAX_SAFE_TOKEN_COUNT}, inclusive`);
  }
}

function boundedExponent(value: string): number {
  const negative = value.startsWith("-");
  const digits = value.replace(/^[+-]/, "");
  const normalized = digits.replace(/^0+/, "") || "0";
  if (normalized.length > 2) throw new RangeError("cost rate exponent exceeds 32");
  const magnitude = BigInt(normalized);
  if (magnitude > MAX_RATE_ABSOLUTE_EXPONENT) {
    throw new RangeError("cost rate exponent exceeds 32");
  }
  const bounded = Number(magnitude);
  return negative ? -bounded : bounded;
}

function numericRateText(value: number): string {
  if (!Number.isFinite(value)) {
    throw new TypeError("cost rate must be a finite number or canonical decimal string");
  }
  if (value < 0) throw new RangeError("cost rate must be non-negative");
  if (value === 0) return "0";
  const [rawMantissa, exponentText] = value.toString().toLowerCase().split("e");
  const mantissa = rawMantissa!.includes(".")
    ? rawMantissa!.replace(/0+$/, "").replace(/\.$/, "")
    : rawMantissa!;
  if (exponentText === undefined) return mantissa;
  const exponent = boundedExponent(exponentText);
  return exponent === 0 ? mantissa : `${mantissa}e${exponent}`;
}

function decimalParts(value: string | number): DecimalParts {
  if (typeof value !== "string" && typeof value !== "number") {
    throw new TypeError("cost rate must be a finite number or canonical decimal string");
  }
  const source = typeof value === "number" ? numericRateText(value) : value;
  if (source.length === 0 || source.length > MAX_RATE_TEXT_LENGTH) {
    throw new RangeError("cost rate exceeds the canonical length bound");
  }
  let match = DECIMAL_RATE.exec(source);
  let exponent = 0;
  if (!match) {
    match = SCIENTIFIC_RATE.exec(source);
    if (!match) throw new TypeError("cost rate is not a canonical non-negative decimal");
    exponent = boundedExponent(match[3]!);
  }
  const fraction = match[2] ?? "";
  const significant = `${match[1]}${fraction}`.replace(/^0+/, "") || "0";
  if (significant.length > MAX_RATE_SIGNIFICANT_DIGITS) {
    throw new RangeError("cost rate exceeds 32 significant digits");
  }
  if (fraction.length > MAX_RATE_FRACTIONAL_DIGITS) {
    throw new RangeError("cost rate exceeds 32 fractional digits");
  }
  let coefficient = BigInt(`${match[1]}${fraction}`);
  let scale = fraction.length - exponent;
  if (scale < 0) {
    coefficient *= 10n ** BigInt(-scale);
    scale = 0;
  }
  return { coefficient, scale };
}

function canonicalUsd(units: bigint): string {
  const whole = units / USD_SCALE;
  const fraction = (units % USD_SCALE).toString().padStart(10, "0").replace(/0+$/, "");
  return fraction ? `${whole}.${fraction}` : whole.toString();
}

/** @internal Shared-fixture entry point; not exported from the package root. */
export function calculateCostFromRatesUsdCanonical(
  inputTokens: number,
  outputTokens: number,
  inputPer1M: string | number,
  outputPer1M: string | number,
): string {
  assertTokenCount("inputTokens", inputTokens);
  assertTokenCount("outputTokens", outputTokens);
  const input = decimalParts(inputPer1M);
  const output = decimalParts(outputPer1M);
  const rateScale = Math.max(input.scale, output.scale);
  const numerator =
    BigInt(inputTokens) * input.coefficient * 10n ** BigInt(rateScale - input.scale) +
    BigInt(outputTokens) * output.coefficient * 10n ** BigInt(rateScale - output.scale);
  const denominator = TOKENS_PER_RATE_UNIT * 10n ** BigInt(rateScale);
  const scaled = numerator * USD_SCALE;
  let units = scaled / denominator;
  const remainder = scaled % denominator;
  const comparison = remainder * 2n - denominator;
  if (comparison > 0n || (comparison === 0n && units % 2n === 1n)) units += 1n;
  return canonicalUsd(units);
}

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

/** @internal Shared-fixture entry point; not exported from the package root. */
export function calculateCostUsdCanonical(
  model: string,
  inputTokens: number,
  outputTokens: number,
): string {
  assertTokenCount("inputTokens", inputTokens);
  assertTokenCount("outputTokens", outputTokens);
  const entry = lookupCost(model);
  if (!entry) return "0";
  return calculateCostFromRatesUsdCanonical(
    inputTokens,
    outputTokens,
    entry.inputPer1M,
    entry.outputPer1M,
  );
}

/**
 * Calculate cost in USD for a given token count and model.
 * Returns 0 if the model is not in the cost table.
 */
export function calculateCostUsd(model: string, inputTokens: number, outputTokens: number): number {
  return Number(calculateCostUsdCanonical(model, inputTokens, outputTokens));
}
