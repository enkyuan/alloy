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
    // `kaji` CLI. ESM only; tsup strips shebangs unless restored via banner.
    // `bin.ts` is the binary entry (package.json `bin` points at dist/cli/bin.js);
    // `index.ts` is the importable runCli surface used by tests and any host
    // embedding kaji's command dispatch.
    entry: ["src/cli/bin.ts", "src/cli/index.ts"],
    format: ["esm"],
    outDir: "dist/cli",
    sourcemap: true,
    clean: false,
    banner: { js: "#!/usr/bin/env node" },
    // Defensive: today the CLI doesn't reach into providers, but if a future
    // CLI subcommand imports from `src/index.ts` we don't want either SDK to
    // get inlined into the bin.
    external: ["openai", "@anthropic-ai/sdk"],
  },
]);
