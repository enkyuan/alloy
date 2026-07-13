export interface ProviderErrorOptions {
  service?: string;
  action?: string;
  statusCode?: number;
  responseText?: string;
  cause?: unknown;
}

const PROVIDER_ERROR_BRAND = Symbol.for("kaji.ProviderError.v1");
const PROVIDER_CONFIG_ERROR_BRAND = Symbol.for("kaji.ProviderConfigError.v1");
const PROVIDER_API_ERROR_BRAND = Symbol.for("kaji.ProviderAPIError.v1");
const PROVIDER_CONNECTION_ERROR_BRAND = Symbol.for("kaji.ProviderConnectionError.v1");
const PROVIDER_RATE_LIMITED_ERROR_BRAND = Symbol.for("kaji.ProviderRateLimitedError.v1");
const PROVIDER_OUTPUT_LIMIT_ERROR_BRAND = Symbol.for("kaji.ProviderOutputLimitError.v1");

function brand(value: object, key: symbol): void {
  Object.defineProperty(value, key, { value: true });
}

function hasBrand(value: unknown, key: symbol): boolean {
  return typeof value === "object" && value !== null && Reflect.get(value, key) === true;
}

export class ProviderError extends Error {
  readonly service: string;
  readonly action: string;
  readonly statusCode?: number;
  readonly responseText?: string;

  static [Symbol.hasInstance](value: unknown): boolean {
    return hasBrand(value, PROVIDER_ERROR_BRAND);
  }

  constructor(message: string, options: ProviderErrorOptions = {}) {
    super(message);
    brand(this, PROVIDER_ERROR_BRAND);
    this.name = new.target.name;
    this.service = options.service ?? "provider";
    this.action = options.action ?? "request";
    if (options.statusCode !== undefined) this.statusCode = options.statusCode;
    // Response bodies are vendor-controlled and may contain credentials.
    // Keep the compatibility property undefined rather than retaining them.
    // Deliberately discard vendor causes: SDK errors are public values and
    // vendor exceptions may retain request bodies, credentials, or headers.
  }
}

export class ProviderConfigError extends ProviderError {
  static [Symbol.hasInstance](value: unknown): boolean {
    return hasBrand(value, PROVIDER_CONFIG_ERROR_BRAND);
  }

  constructor(message: string, options: Omit<ProviderErrorOptions, "action"> = {}) {
    super(message, { ...options, action: "configure" });
    brand(this, PROVIDER_CONFIG_ERROR_BRAND);
  }
}

export class ProviderAPIError extends ProviderError {
  static [Symbol.hasInstance](value: unknown): boolean {
    return hasBrand(value, PROVIDER_API_ERROR_BRAND);
  }

  constructor(message: string, options: ProviderErrorOptions = {}) {
    super(message, { ...options, action: options.action ?? "api call" });
    brand(this, PROVIDER_API_ERROR_BRAND);
  }
}

export class ProviderConnectionError extends ProviderError {
  static [Symbol.hasInstance](value: unknown): boolean {
    return hasBrand(value, PROVIDER_CONNECTION_ERROR_BRAND);
  }

  constructor(message: string, options: ProviderErrorOptions = {}) {
    super(message, { ...options, action: options.action ?? "connect" });
    brand(this, PROVIDER_CONNECTION_ERROR_BRAND);
  }
}

export class ProviderRateLimitedError extends ProviderError {
  readonly retryAfterMs: number;
  readonly attempts: number;

  static [Symbol.hasInstance](value: unknown): boolean {
    return hasBrand(value, PROVIDER_RATE_LIMITED_ERROR_BRAND);
  }

  constructor(
    message: string,
    options: Omit<ProviderErrorOptions, "action"> & { retryAfterMs: number; attempts: number },
  ) {
    super(message, { ...options, action: "api call", statusCode: 429 });
    brand(this, PROVIDER_RATE_LIMITED_ERROR_BRAND);
    this.retryAfterMs = options.retryAfterMs;
    this.attempts = options.attempts;
  }
}

export type ProviderOutputDimension = "text" | "tool_arguments" | "total_response" | "tool_calls";

export class ProviderOutputLimitError extends Error {
  readonly code = "PROVIDER_OUTPUT_LIMIT" as const;
  readonly phase = "provider_stream" as const;
  readonly retryable = false as const;
  readonly outcome = "unknown" as const;

  static [Symbol.hasInstance](value: unknown): boolean {
    return hasBrand(value, PROVIDER_OUTPUT_LIMIT_ERROR_BRAND);
  }

  constructor(
    readonly dimension: ProviderOutputDimension,
    readonly limit: number,
  ) {
    if (
      !(["text", "tool_arguments", "total_response", "tool_calls"] as const).includes(dimension)
    ) {
      throw new TypeError("unknown provider output dimension");
    }
    if (!Number.isSafeInteger(limit) || limit < 1) {
      throw new RangeError("provider output limit must be a positive safe integer");
    }
    const unit = dimension === "tool_calls" ? "calls" : "bytes";
    super(`Provider output exceeded ${dimension} limit of ${limit} ${unit}`);
    brand(this, PROVIDER_OUTPUT_LIMIT_ERROR_BRAND);
    this.name = "ProviderOutputLimitError";
  }
}

function errorStatusCode(error: unknown): number | undefined {
  if (typeof error !== "object" || error === null) return undefined;
  const status = "status" in error ? error.status : undefined;
  const statusCode = "statusCode" in error ? error.statusCode : undefined;
  return typeof status === "number"
    ? status
    : typeof statusCode === "number"
      ? statusCode
      : undefined;
}

const NETWORK_ERROR_CODES = new Set([
  "EAI_AGAIN",
  "ECONNABORTED",
  "ECONNREFUSED",
  "ECONNRESET",
  "ENETUNREACH",
  "ENOTFOUND",
  "ETIMEDOUT",
  "UND_ERR_CONNECT_TIMEOUT",
]);
const NETWORK_ERROR_TYPE_NAMES = new Set([
  "APIConnectionError",
  "APIConnectionTimeoutError",
  "APITimeoutError",
]);

function isNetworkError(error: unknown): boolean {
  if (typeof error !== "object" || error === null) return false;
  const code = "code" in error ? error.code : undefined;
  const constructorName = error.constructor?.name;
  return (
    (typeof code === "string" && NETWORK_ERROR_CODES.has(code)) ||
    (typeof constructorName === "string" && NETWORK_ERROR_TYPE_NAMES.has(constructorName))
  );
}

export function providerAPIErrorFromUnknown(
  service: string,
  error: unknown,
  action = "request",
): ProviderError {
  if (error instanceof ProviderConfigError) {
    return new ProviderConfigError(`${service} configuration failed`, {
      service,
      statusCode: error.statusCode,
    });
  }
  if (error instanceof ProviderConnectionError) {
    return new ProviderConnectionError(`${service} ${action} failed due to a network error`, {
      service,
      action,
      statusCode: error.statusCode,
    });
  }
  if (error instanceof ProviderRateLimitedError) {
    return new ProviderRateLimitedError(`${service} rate limit exceeded`, {
      service,
      retryAfterMs: error.retryAfterMs,
      attempts: error.attempts,
    });
  }
  if (error instanceof ProviderError) {
    return new ProviderAPIError(`${service} ${action} failed`, {
      service,
      action,
      statusCode: error.statusCode,
    });
  }
  if (isNetworkError(error)) {
    return new ProviderConnectionError(`${service} ${action} failed due to a network error`, {
      service,
      action,
    });
  }
  return new ProviderAPIError(`${service} ${action} failed`, {
    service,
    action,
    statusCode: errorStatusCode(error),
  });
}

export interface NormalizedProviderError {
  type: "api" | "auth" | "config" | "network" | "rate_limit";
  code:
    | "PROVIDER_API_ERROR"
    | "PROVIDER_AUTH_ERROR"
    | "PROVIDER_CONFIG_ERROR"
    | "PROVIDER_NETWORK_ERROR"
    | "PROVIDER_RATE_LIMITED";
  service: string;
  action: string;
  status: number | null;
  retryable: boolean;
}

export function normalizeProviderError(error: ProviderError): NormalizedProviderError {
  const status = error.statusCode ?? null;
  if (error instanceof ProviderConfigError) {
    return {
      type: "config",
      code: "PROVIDER_CONFIG_ERROR",
      service: error.service,
      action: error.action,
      status,
      retryable: false,
    };
  }
  if (error instanceof ProviderConnectionError) {
    return {
      type: "network",
      code: "PROVIDER_NETWORK_ERROR",
      service: error.service,
      action: error.action,
      status,
      retryable: true,
    };
  }
  if (error instanceof ProviderRateLimitedError || status === 429) {
    return {
      type: "rate_limit",
      code: "PROVIDER_RATE_LIMITED",
      service: error.service,
      action: error.action,
      status,
      retryable: true,
    };
  }
  if (status === 401 || status === 403) {
    return {
      type: "auth",
      code: "PROVIDER_AUTH_ERROR",
      service: error.service,
      action: error.action,
      status,
      retryable: false,
    };
  }
  return {
    type: "api",
    code: "PROVIDER_API_ERROR",
    service: error.service,
    action: error.action,
    status,
    retryable: status !== null && status >= 500,
  };
}
