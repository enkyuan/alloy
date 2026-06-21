/**
 * Vitest config for integration tests.
 *
 * Runs only files under tests/integration/ and excludes the regular unit test
 * suite.  Intended for manual or optional CI runs where real API keys are
 * available.
 *
 * Usage:
 *   OPENAI_API_KEY=... ANTHROPIC_API_KEY=... bun run test:integration
 */
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/integration/**/*.test.ts"],
  },
});
