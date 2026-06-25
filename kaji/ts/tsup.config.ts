import { defineConfig } from "tsup";

export default defineConfig([
  {
    entry: ["src/index.ts", "src/testing.ts"],
    format: ["esm", "cjs"],
    dts: true,
    sourcemap: true,
    clean: true,
    treeshake: true,
    // openai and @anthropic-ai/sdk are optional peer dependencies. Marking them
    // external ensures they are never included in dist/ — consumers must install
    // them separately. Dynamic imports in the provider files already guard
    // runtime loading; this makes the build-time signal match.
    external: ["openai", "@anthropic-ai/sdk"],
  },
  {
    // `kaji` CLI binary. ESM only; tsup strips shebangs unless restored via
    // banner. The `bin` field in package.json points at `dist/cli/index.js`.
    entry: ["src/cli/index.ts"],
    format: ["esm"],
    outDir: "dist/cli",
    sourcemap: true,
    clean: false,
    banner: { js: "#!/usr/bin/env node" },
  },
]);
