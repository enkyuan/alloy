import { defineConfig, type Options } from "tsup";

const EXTERNAL_PROVIDERS: string[] = [];
const SOURCE_MAP_POLICY = {
  sourcemap: true,
  esbuildOptions(options) {
    options.sourcesContent = false;
  },
} satisfies Pick<Options, "sourcemap" | "esbuildOptions">;

export default defineConfig([
  {
    entry: ["src/index.ts"],
    format: ["esm", "cjs"],
    dts: true,
    ...SOURCE_MAP_POLICY,
    clean: false,
    treeshake: true,
    external: EXTERNAL_PROVIDERS,
  },
  {
    entry: {
      postgres: "src/backends/postgres/index.ts",
    },
    format: ["esm", "cjs"],
    dts: true,
    ...SOURCE_MAP_POLICY,
    clean: false,
    treeshake: true,
    // Keep package self-imports external so subpaths share the root runtime constructors.
    external: ["@irogane/kaji", "postgres"],
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
