import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [tanstackRouter({ target: "react", autoCodeSplitting: true }), react(), tailwindcss()],
  resolve: {
    alias: {
      "@/components/ui": path.resolve(import.meta.dirname, "./src/components/ui"),
      "@/components": path.resolve(import.meta.dirname, "./src/components"),
      "@/lib": path.resolve(import.meta.dirname, "./src/lib"),
      "@/hooks": path.resolve(import.meta.dirname, "./src/hooks"),
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
});
