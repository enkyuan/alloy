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
  override readonly cause?: unknown;

  constructor(message: string, options: ProviderErrorOptions = {}) {
    super(message);
    this.name = new.target.name;
    this.service = options.service ?? "provider";
    this.action = options.action ?? "request";
    if (options.statusCode !== undefined) this.statusCode = options.statusCode;
    if (options.responseText !== undefined) this.responseText = options.responseText;
    if (options.cause !== undefined) this.cause = options.cause;
  }
}

export class ProviderConfigError extends ProviderError {
  constructor(message: string, options: Omit<ProviderErrorOptions, "action"> = {}) {
    super(message, { ...options, action: "configure" });
  }
}

export class ProviderAPIError extends ProviderError {
  constructor(message: string, options: Omit<ProviderErrorOptions, "action"> = {}) {
    super(message, { ...options, action: "api call" });
  }
}

export class ProviderConnectionError extends ProviderError {
  constructor(message: string, options: Omit<ProviderErrorOptions, "action"> = {}) {
    super(message, { ...options, action: "connect" });
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
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

function errorResponseText(error: unknown): string | undefined {
  if (typeof error !== "object" || error === null) return undefined;
  const response = "response" in error ? error.response : undefined;
  if (typeof response === "string") return response;
  if (typeof response === "object" && response !== null && "text" in response) {
    return typeof response.text === "string" ? response.text : undefined;
  }
  return undefined;
}

export function providerAPIErrorFromUnknown(service: string, error: unknown): ProviderAPIError {
  if (error instanceof ProviderAPIError) return error;
  if (error instanceof ProviderError) {
    return new ProviderAPIError(error.message, {
      service: error.service,
      statusCode: error.statusCode,
      responseText: error.responseText,
      cause: error,
    });
  }
  return new ProviderAPIError(`${service} request failed: ${errorMessage(error)}`, {
    service,
    statusCode: errorStatusCode(error),
    responseText: errorResponseText(error),
    cause: error,
  });
}
