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

// Agentation portals into document.body and injects styles into document.head.
// Astro replaces both during a client-side swap, so bridge only those two surfaces.
let agentationRoot;
const agentationStyleSelector = 'style[id^="feedback-"], style#agentation-color-tokens';

const unmountAgentation = () => {
  agentationRoot?.unmount();
  agentationRoot = undefined;
};

const prepareAgentationSwap = (event) => {
  document.querySelectorAll(agentationStyleSelector).forEach((style) => {
    event.newDocument.head.append(style.cloneNode(true));
  });
  unmountAgentation();
};

const mountAgentation = () => {
  if (agentationRoot) return;

  const agentationContainer = document.querySelector("[data-agentation-mount]");
  if (!agentationContainer) return;

  agentationRoot = createRoot(agentationContainer);
  agentationRoot.render(createElement(Agentation));
};

mountAgentation();
document.addEventListener("astro:before-swap", prepareAgentationSwap);
document.addEventListener("astro:page-load", mountAgentation);`,
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
      noDiscovery: true,
    },
  },
});
