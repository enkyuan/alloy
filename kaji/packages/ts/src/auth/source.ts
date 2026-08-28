/** Interface for reading secrets at runtime. v1 default: env-only. */
export interface SecretSource {
  get(key: string): Promise<string | undefined>;
}

/**
 * Reads secrets from process.env. Default for all v1 integrations.
 * v1.1 will add VaultSecretSource, DopplerSecretSource, AWSSecretsSource.
 */
export class EnvSecretSource implements SecretSource {
  async get(key: string): Promise<string | undefined> {
    return process.env[key];
  }
}
