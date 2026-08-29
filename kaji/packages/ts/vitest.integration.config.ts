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
import { fileURLToPath } from "node:url";

export default defineConfig({
  resolve: {
    alias: {
      "@irogane/kaji/integrations": fileURLToPath(
        new URL("./src/integrations/public.ts", import.meta.url),
      ),
      "@irogane/kaji": fileURLToPath(new URL("./src/index.ts", import.meta.url)),
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    include: ["tests/integration/**/*.test.ts"],
  },
});
