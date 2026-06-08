/**
 * Provider registry: a process-level map from name to `ModelProvider`.
 * Mirrors `agentkit.runtime.providers.registry`.
 */
import type { ModelProvider } from "./base";

const providers = new Map<string, ModelProvider>();

/** Register a provider under a name. Throws on duplicate. */
export function registerProvider(name: string, provider: ModelProvider): void {
  if (providers.has(name)) {
    throw new Error(`Provider already registered: ${name}`);
  }
  providers.set(name, provider);
}

/** Retrieve a registered provider. Throws if not found. */
export function getProvider(name: string): ModelProvider {
  const p = providers.get(name);
  if (p === undefined) {
    throw new Error(
      `Unknown provider: ${name}. Register it with registerProvider() first.`,
    );
  }
  return p;
}

/** Clear all registrations. For tests. */
export function clearProviders(): void {
  providers.clear();
}
