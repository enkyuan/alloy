import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  resolve: {
    alias: {
      "kaji/integrations": fileURLToPath(
        new URL("./src/integrations/public.ts", import.meta.url),
      ),
      "kaji": fileURLToPath(new URL("./src/index.ts", import.meta.url)),
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    include: ["tests/**/*.test.ts", "examples/**/*.test.ts"],
    setupFiles: ["./tests/offline-setup.ts"],
  },
});
