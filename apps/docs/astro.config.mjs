import mdx from "@astrojs/mdx";
import { defineConfig } from "astro/config";

const agentation = () => ({
  name: "@kaji/docs-agentation",
  hooks: {
    "astro:config:setup": ({ command, injectScript }) => {
      if (command !== "dev") return;

      injectScript(
        "page",
        `import { Agentation } from "agentation";
import { createElement } from "react";
import { createRoot } from "react-dom/client";

let agentationRoot;

const mountAgentation = () => {
  if (agentationRoot) return;

  const agentationContainer = document.createElement("div");
  agentationContainer.dataset.agentationMount = "";
  document.body.append(agentationContainer);
  agentationRoot = createRoot(agentationContainer);
  agentationRoot.render(createElement(Agentation));
};

mountAgentation();`,
      );
    },
  },
});

export default defineConfig({
  integrations: [mdx(), agentation()],
  markdown: {
    shikiConfig: {
      theme: "github-light",
      wrap: true,
    },
  },
  output: "static",
  vite: {
    optimizeDeps: {
      include: ["agentation", "react", "react-dom/client"],
    },
  },
});
