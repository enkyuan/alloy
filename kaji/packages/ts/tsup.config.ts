import { rmSync } from "node:fs";

import { defineConfig, type Options } from "tsup";

const EXTERNAL_PROVIDERS = ["openai", "@anthropic-ai/sdk"];
const SOURCE_MAP_POLICY = {
  sourcemap: true,
  esbuildOptions(options) {
    options.sourcesContent = false;
  },
} satisfies Pick<Options, "sourcemap" | "esbuildOptions">;

// Clean once before parallel configs build; per-config cleaning can delete faster outputs.
rmSync(new URL("./dist", import.meta.url), { recursive: true, force: true });

export default defineConfig([
  {
    entry: ["src/index.ts", "src/testing.ts"],
    format: ["esm", "cjs"],
    dts: true,
    ...SOURCE_MAP_POLICY,
    clean: false,
    treeshake: true,
    // Provider SDKs are optional peer dependencies — consumers install only what they use.
    external: EXTERNAL_PROVIDERS,
  },
  {
    // Per-provider entry points for tree-shaking. Import only the provider you use:
    //   import { OpenAIProvider } from "@irogane/kaji/openai"
    entry: {
      openai: "src/providers/openai.ts",
      anthropic: "src/providers/anthropic.ts",
      auth: "src/auth/index.ts",
      integrations: "src/integrations/public.ts",
      "integrations/github": "src/integrations/github.ts",
    },
    format: ["esm", "cjs"],
    dts: true,
    ...SOURCE_MAP_POLICY,
    clean: false,
    treeshake: true,
    // Keep package self-imports external so subpaths share the root runtime constructors.
    external: [...EXTERNAL_PROVIDERS, "@irogane/kaji"],
  },
  {
    // `kaji` CLI. ESM only; tsup strips shebangs unless restored via banner.
    entry: [
      "src/cli/bin.ts",
      "src/cli/index.ts",
      "src/cli/package-entry.ts",
      "src/cli/init-worker.ts",
    ],
    format: ["esm"],
    outDir: "dist/cli",
    dts: true,
    ...SOURCE_MAP_POLICY,
    clean: false,
    banner: { js: "#!/usr/bin/env node" },
    external: EXTERNAL_PROVIDERS,
  },
  {
    // JavaScript worker stays declaration-free; public CLI declarations come from TS entries above.
    entry: ["src/cli/integration-copy-worker.mjs"],
    format: ["esm"],
    outDir: "dist/cli",
    ...SOURCE_MAP_POLICY,
    clean: false,
    banner: { js: "#!/usr/bin/env node" },
    external: EXTERNAL_PROVIDERS,
  },
  {
    // CommonJS bridge loads the ESM CLI without bundling its import-meta-dependent internals.
    entry: ["src/cli/package-entry-cjs.ts"],
    format: ["cjs"],
    outDir: "dist/cli",
    dts: true,
    ...SOURCE_MAP_POLICY,
    clean: false,
    external: EXTERNAL_PROVIDERS,
  },
]);
