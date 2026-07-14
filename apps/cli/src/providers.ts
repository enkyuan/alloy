export const PROVIDERS = ["mock", "openai", "anthropic"] as const;

export type Provider = (typeof PROVIDERS)[number];

export const PROVIDER_ENV_KEYS: Partial<Record<Provider, string>> = {
  openai: "OPENAI_API_KEY",
  anthropic: "ANTHROPIC_API_KEY",
};

export const TYPESCRIPT_PROVIDER_PACKAGES: Partial<Record<Provider, string>> = {
  openai: "openai",
  anthropic: "@anthropic-ai/sdk",
};

export function isProvider(value: string | undefined): value is Provider {
  return PROVIDERS.includes(value as Provider);
}
