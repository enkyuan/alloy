export interface ProviderErrorOptions {
  service?: string;
  action?: string;
  statusCode?: number;
  responseText?: string;
  cause?: unknown;
}

export class ProviderError extends Error {
  readonly service: string;
  readonly action: string;
  readonly statusCode?: number;
  readonly responseText?: string;

  constructor(message: string, options: ProviderErrorOptions = {}) {
    super(message);
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
  constructor(message: string, options: Omit<ProviderErrorOptions, "action"> = {}) {
    super(message, { ...options, action: "configure" });
  }
}

export class ProviderAPIError extends ProviderError {
  constructor(message: string, options: ProviderErrorOptions = {}) {
    super(message, { ...options, action: options.action ?? "api call" });
  }
}

export class ProviderConnectionError extends ProviderError {
  constructor(message: string, options: ProviderErrorOptions = {}) {
    super(message, { ...options, action: options.action ?? "connect" });
  }
}

export class ProviderRateLimitedError extends ProviderError {
  readonly retryAfterMs: number;
  readonly attempts: number;

  constructor(
    message: string,
    options: Omit<ProviderErrorOptions, "action"> & { retryAfterMs: number; attempts: number },
  ) {
    super(message, { ...options, action: "api call", statusCode: 429 });
    this.retryAfterMs = options.retryAfterMs;
    this.attempts = options.attempts;
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
