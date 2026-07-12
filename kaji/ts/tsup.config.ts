import { defineConfig } from "tsup";

const EXTERNAL_PROVIDERS = ["openai", "@anthropic-ai/sdk", "@google/genai"];

export default defineConfig([
  {
    entry: ["src/index.ts", "src/testing.ts"],
    format: ["esm", "cjs"],
    dts: true,
    sourcemap: true,
    clean: true,
    treeshake: true,
    // Provider SDKs are optional peer dependencies — consumers install only what they use.
    external: EXTERNAL_PROVIDERS,
  },
  {
    // Per-provider entry points for tree-shaking. Import only the provider you use:
    //   import { OpenAIProvider } from "@kaji/sdk/openai"
    entry: {
      openai: "src/providers/openai.ts",
      anthropic: "src/providers/anthropic.ts",
      integrations: "src/integrations/public.ts",
    },
    format: ["esm", "cjs"],
    dts: true,
    sourcemap: true,
    clean: false,
    treeshake: true,
    external: EXTERNAL_PROVIDERS,
  },
  {
    // `kaji` CLI. ESM only; tsup strips shebangs unless restored via banner.
    entry: [
      "src/cli/bin.ts",
      "src/cli/index.ts",
      "src/cli/init-worker.ts",
      "src/cli/integration-copy-worker.mjs",
    ],
    format: ["esm"],
    outDir: "dist/cli",
    sourcemap: true,
    clean: false,
    banner: { js: "#!/usr/bin/env node" },
    external: EXTERNAL_PROVIDERS,
  },
]);
