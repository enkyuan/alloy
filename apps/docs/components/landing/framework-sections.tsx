// cSpell:ignore SVGE SVGMFHN Galf
"use client";

import Link from "next/link";
import { type ReactNode, useState } from "react";
import { Icons as frameworkIcons } from "@/components/docs/icons";
import { RiArrowUpLine } from "@/components/icons/remix";
import { DynamicCodeBlock } from "@/components/ui/dynamic-code-block";

// Tool-category glyphs for the tools showcase. Keyed by tool category, not provider brand.
export const toolIcons: Record<string, () => ReactNode> = {
  Function: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M4 21q1 0 1.5-.5T6 18.5V8a4 4 0 0 1 4-4M9 13h6"
      />
    </svg>
  ),
  Http: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M12 21a9 9 0 1 0 0-18a9 9 0 0 0 0 18M3 12h18M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18"
      />
    </svg>
  ),
  Database: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M12 8c4.418 0 8-1.343 8-3s-3.582-3-8-3s-8 1.343-8 3s3.582 3 8 3M4 5v6c0 1.657 3.582 3 8 3s8-1.343 8-3V5M4 11v6c0 1.657 3.582 3 8 3s8-1.343 8-3v-6"
      />
    </svg>
  ),
  Search: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="m21 21l-4.35-4.35M11 18a7 7 0 1 0 0-14a7 7 0 0 0 0 14"
      />
    </svg>
  ),
  File: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2zM14 2v6h6"
      />
    </svg>
  ),
  Code: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="m16 18l6-6l-6-6M8 6l-6 6l6 6"
      />
    </svg>
  ),
  Mcp: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M3 12L12 3l9 9M6 15l6-6l6 6M9 18l3-3l3 3"
      />
    </svg>
  ),
  Voice: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3M5 10v1a7 7 0 0 0 14 0v-1M12 18v4"
      />
    </svg>
  ),
};

// Built-in and example tools you register with the tool registry. Provider-neutral payloads.
export const builtinTools = [
  "get_weather",
  "web_search",
  "http_request",
  "sql_query",
  "read_file",
  "write_file",
  "run_code",
  "send_email",
  "fetch_url",
  "list_files",
  "create_event",
  "get_balance",
  "vector_search",
  "summarize",
  "translate",
  "extract_json",
  "classify",
  "transcribe",
  "synthesize",
  "call_mcp",
  "get_time",
  "geocode",
];

// Tool name -> category glyph used by the tools grid.
export const toolIconForName: Record<string, string> = {
  get_weather: "Http",
  web_search: "Search",
  http_request: "Http",
  sql_query: "Database",
  read_file: "File",
  write_file: "File",
  run_code: "Code",
  send_email: "Function",
  fetch_url: "Http",
  list_files: "File",
  create_event: "Function",
  get_balance: "Database",
  vector_search: "Search",
  summarize: "Function",
  translate: "Function",
  extract_json: "Code",
  classify: "Function",
  transcribe: "Voice",
  synthesize: "Voice",
  call_mcp: "Mcp",
  get_time: "Function",
  geocode: "Http",
};

// agentkit capabilities and extension points, grouped by area.
export const plugins = [
  { name: "OpenAI", category: "provider" },
  { name: "Kimi", category: "provider" },
  { name: "Gemini", category: "provider" },
  { name: "Mock Provider", category: "provider" },
  { name: "Tool Registry", category: "tools" },
  { name: "Toolgen", category: "tools" },
  { name: "Neutral Payloads", category: "tools" },
  { name: "Tool Retriever", category: "tools" },
  { name: "RAG Embedder", category: "retrieval" },
  { name: "Embedding Cache", category: "retrieval" },
  { name: "History Store", category: "retrieval" },
  { name: "STT", category: "voice" },
  { name: "TTS", category: "voice" },
  { name: "Voice Loop", category: "voice" },
  { name: "Agent Loop", category: "runtime" },
  { name: "Tool Planner", category: "runtime" },
  { name: "Cancellation", category: "runtime" },
  { name: "Replay", category: "events" },
  { name: "Projection", category: "events" },
  { name: "In-Memory Bus", category: "events" },
  { name: "Redis Bus", category: "events" },
  { name: "MCP", category: "tools" },
];

export const categoryLabels: Record<string, string> = {
  provider: "Provider",
  tools: "Tools",
  retrieval: "Retrieval",
  voice: "Voice",
  runtime: "Runtime",
  events: "Events",
};

const _categoryColors: Record<string, string> = {
  provider: "text-violet-500/50 dark:text-violet-400/40",
  tools: "text-sky-500/50 dark:text-sky-400/40",
  retrieval: "text-emerald-500/50 dark:text-emerald-400/40",
  voice: "text-pink-500/50 dark:text-pink-400/40",
  runtime: "text-amber-500/50 dark:text-amber-400/40",
  events: "text-red-500/50 dark:text-red-400/40",
};

const providerDrivers = [
  {
    name: "OpenAI",
    icon: () => (
      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
        <path
          fill="currentColor"
          d="M22.282 9.821a5.985 5.985 0 0 0-.516-4.91a6.05 6.05 0 0 0-6.51-2.9A6.07 6.07 0 0 0 4.981 4.18a5.99 5.99 0 0 0-3.998 2.9a6.05 6.05 0 0 0 .743 7.097a5.98 5.98 0 0 0 .51 4.911a6.05 6.05 0 0 0 6.515 2.9A5.98 5.98 0 0 0 13.26 24a6.06 6.06 0 0 0 5.772-4.206a5.99 5.99 0 0 0 3.997-2.9a6.06 6.06 0 0 0-.747-7.073M13.26 22.43a4.48 4.48 0 0 1-2.876-1.04l.141-.081l4.779-2.758a.8.8 0 0 0 .392-.681v-6.737l2.02 1.168a.07.07 0 0 1 .038.052v5.583a4.5 4.5 0 0 1-4.494 4.494M3.6 18.304a4.47 4.47 0 0 1-.535-3.014l.142.085l4.783 2.759a.77.77 0 0 0 .78 0l5.843-3.369v2.332a.08.08 0 0 1-.033.062L9.74 19.95a4.5 4.5 0 0 1-6.14-1.646M2.34 7.896a4.5 4.5 0 0 1 2.366-1.973V11.6a.77.77 0 0 0 .388.677l5.815 3.354l-2.02 1.168a.08.08 0 0 1-.071 0l-4.83-2.786A4.5 4.5 0 0 1 2.34 7.872zm16.597 3.855l-5.833-3.387L15.119 7.2a.08.08 0 0 1 .071 0l4.83 2.791a4.494 4.494 0 0 1-.676 8.105v-5.678a.79.79 0 0 0-.407-.667m2.01-3.023l-.141-.085l-4.774-2.782a.78.78 0 0 0-.785 0L9.409 9.23V6.897a.07.07 0 0 1 .028-.061l4.83-2.787a4.5 4.5 0 0 1 6.68 4.66zm-12.64 4.135l-2.02-1.164a.08.08 0 0 1-.038-.057V6.075a4.5 4.5 0 0 1 7.375-3.453l-.142.08l-4.778 2.758a.8.8 0 0 0-.393.681zm1.097-2.365l2.602-1.5l2.607 1.5v2.999l-2.597 1.5l-2.607-1.5z"
        />
      </svg>
    ),
  },
  {
    name: "Kimi",
    icon: () => (
      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
        <path
          fill="none"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="2"
          d="M5 4v16M5 12h6l5-5M11 12l5 5"
        />
      </svg>
    ),
  },
  {
    name: "Gemini",
    icon: () => (
      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
        <path
          fill="currentColor"
          d="M12 2c.5 5.5 4.5 9.5 10 10c-5.5.5-9.5 4.5-10 10c-.5-5.5-4.5-9.5-10-10c5.5-.5 9.5-4.5 10-10"
        />
      </svg>
    ),
  },
];

const moreProviders = [
  {
    name: "Mock",
    icon: () => (
      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
        <path
          fill="none"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="2"
          d="M4 6h16M4 12h16M4 18h10"
        />
      </svg>
    ),
  },
  {
    name: "Anthropic",
    icon: () => (
      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24">
        <path
          fill="none"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="2"
          d="M7 18L13 4l6 14M9.5 13h6"
        />
      </svg>
    ),
  },
];

const providerSnippets: Record<string, string> = {
  OpenAI: `import { AgentRuntime } from "@agentkit/sdk"
import { OpenAIProvider } from "@agentkit/sdk/providers"
import { InMemoryEventBus } from "@agentkit/sdk/events"

const runtime = new AgentRuntime({
  provider: new OpenAIProvider({
    apiKey: process.env.OPENAI_API_KEY,
    model: "gpt-4o",
  }),
  tools: registry.list(),
  bus: new InMemoryEventBus(),
})`,
  Kimi: `provider: new KimiProvider({
  apiKey: process.env.KIMI_API_KEY,
})`,
  Gemini: `provider: new GeminiProvider({
  apiKey: process.env.GEMINI_API_KEY,
})`,
  Mock: `provider: new MockProvider()`,
  Anthropic: `// roadmap: not yet shipped
provider: new AnthropicProvider()`,
};

export const serverCodeTs = `import { AgentRuntime } from "@agentkit/sdk"
import { OpenAIProvider } from "@agentkit/sdk/providers"
import { InMemoryEventBus } from "@agentkit/sdk/events"
import { ToolRegistry, tool } from "@agentkit/sdk/tools"

const registry = new ToolRegistry()

registry.add(
  tool("get_weather", "Look up the weather for a city", {
    city: { type: "string" },
  }, async ({ city }) => fetchWeather(city)),
)

export const agent = new AgentRuntime({
  provider: new OpenAIProvider({
    apiKey: process.env.OPENAI_API_KEY,
    model: "gpt-4o",
  }),
  tools: registry.list(),
  bus: new InMemoryEventBus(),
})`;

export const serverCodePy = `from agentkit.runtime.agents.runtime import AgentRuntime
from agentkit.runtime.providers.openai import OpenAIProvider
from agentkit.infra.events.bus import InMemoryEventBus
from agentkit.runtime.tools.registry import register_tool, tool_spec_from_model


@register_tool(tool_spec_from_model("get_weather", "Look up the weather", WeatherArgs))
async def get_weather(ctx, args):
    return await fetch_weather(args["city"])


agent = AgentRuntime(
    provider=OpenAIProvider(model="gpt-4o"),
    bus=InMemoryEventBus(),
    store=store,
    planner=planner,
)`;

export function AgentLoopTabs() {
  const [lang, setLang] = useState<"ts" | "py">("ts");
  const code = lang === "ts" ? serverCodeTs : serverCodePy;
  const filename = lang === "ts" ? "lib/agent.ts" : "agent.py";

  return (
    <div className="relative">
      <div className="absolute -inset-4 bg-gradient-to-br from-foreground/[0.02] via-transparent to-foreground/[0.02] rounded-2xl blur-xl pointer-events-none dark:from-foreground/[0.03] dark:to-foreground/[0.03]" />

      <div className="relative overflow-hidden bg-neutral-50 dark:bg-black">
        <div className="flex items-center justify-between px-3 py-1.5">
          <span className="inline-flex items-center gap-1.5 text-[11px] font-mono text-foreground/50 dark:text-foreground/40">
            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 32 32">
              <rect
                width="28"
                height="28"
                x="2"
                y="2"
                fill="currentColor"
                opacity="0.3"
                rx="1.312"
              />
              <path
                fill="currentColor"
                fillRule="evenodd"
                d="M18.245 23.759v3.068a6.5 6.5 0 0 0 1.764.575a11.6 11.6 0 0 0 2.146.192a10 10 0 0 0 2.088-.211a5.1 5.1 0 0 0 1.735-.7a3.54 3.54 0 0 0 1.181-1.266a4.47 4.47 0 0 0 .186-3.394a3.4 3.4 0 0 0-.717-1.117a5.2 5.2 0 0 0-1.123-.877a12 12 0 0 0-1.477-.734q-.6-.249-1.08-.484a5.5 5.5 0 0 1-.813-.479a2.1 2.1 0 0 1-.516-.518a1.1 1.1 0 0 1-.181-.618a1.04 1.04 0 0 1 .162-.571a1.4 1.4 0 0 1 .459-.436a2.4 2.4 0 0 1 .726-.283a4.2 4.2 0 0 1 .956-.1a6 6 0 0 1 .808.058a6 6 0 0 1 .856.177a6 6 0 0 1 .836.3a4.7 4.7 0 0 1 .751.422V13.9a7.5 7.5 0 0 0-1.525-.4a12.4 12.4 0 0 0-1.9-.129a8.8 8.8 0 0 0-2.064.235a5.2 5.2 0 0 0-1.716.733a3.66 3.66 0 0 0-1.171 1.271a3.73 3.73 0 0 0-.431 1.845a3.6 3.6 0 0 0 .789 2.34a6 6 0 0 0 2.395 1.639q.63.26 1.175.509a6.5 6.5 0 0 1 .942.517a2.5 2.5 0 0 1 .626.585a1.2 1.2 0 0 1 .23.719a1.1 1.1 0 0 1-.144.552a1.3 1.3 0 0 1-.435.441a2.4 2.4 0 0 1-.726.292a4.4 4.4 0 0 1-1.018.105a5.8 5.8 0 0 1-1.969-.35a5.9 5.9 0 0 1-1.805-1.045m-5.154-7.638h4v-2.527H5.938v2.527H9.92v11.254h3.171Z"
              />
            </svg>
            {filename}
          </span>

          <div className="flex items-center gap-0.5 text-[10px] font-mono">
            {(["ts", "py"] as const).map((id) => (
              <button
                key={id}
                type="button"
                onClick={() => setLang(id)}
                className={
                  lang === id
                    ? "px-1.5 py-0.5 rounded-sm text-foreground/80 bg-foreground/[0.06]"
                    : "px-1.5 py-0.5 rounded-sm text-foreground/40 hover:text-foreground/65 transition-colors"
                }
              >
                {id === "ts" ? "TypeScript" : "Python"}
              </button>
            ))}
          </div>
        </div>

        <div className="relative h-[310px] overflow-hidden">
          <DynamicCodeBlock
            lang={lang}
            code={code}
            codeblock={{
              className:
                "border-0 rounded-none my-0 shadow-none bg-neutral-50 dark:bg-black [&_div]:bg-neutral-50 [&_div]:dark:bg-black [&_div]:text-[12px]",
              "data-line-numbers": true,
            }}
          />
          <div className="absolute bottom-0 left-0 right-0 h-12 bg-gradient-to-t from-background to-transparent pointer-events-none" />
        </div>
      </div>
    </div>
  );
}

const allProviders = [...providerDrivers, ...moreProviders];

export function ProvidersSection() {
  const featured = allProviders.find((d) => d.name === "OpenAI")!;
  const others = allProviders.filter((d) => d.name !== "OpenAI");

  return (
    <div className="h-full flex items-center">
      <div className="w-full max-w-[920px] mx-auto">
        <div className="grid grid-cols-4 sm:grid-cols-6 gap-0">
          {/* OpenAI — intentionally larger feature tile */}
          <div className="col-span-2 sm:col-span-3 row-span-2 relative border-b border-r border-dashed border-foreground/[0.06] p-3 sm:p-4 min-h-[200px] sm:min-h-[240px] cursor-default hover:bg-foreground/[0.02] transition-colors overflow-hidden">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-foreground/80 dark:text-foreground/70 [&_svg]:w-5 [&_svg]:h-5 [&_svg]:grayscale-0 [&_svg]:opacity-100">
                {featured.icon()}
              </span>
              <span className="text-[13px] font-mono text-foreground/85 dark:text-foreground/75">
                {featured.name}
              </span>
            </div>
            <DynamicCodeBlock
              lang="ts"
              code={providerSnippets.OpenAI}
              allowCopy={false}
              codeblock={{
                className:
                  "border-0 rounded-none my-0 shadow-none bg-transparent [&_div]:bg-transparent [&_div]:text-[11px] [&_pre]:!p-0 [&_pre]:!overflow-hidden [&_div]:!overflow-hidden [&_code]:!overflow-hidden",
              }}
            />
            <div className="absolute inset-y-0 right-0 w-14 bg-gradient-to-l from-background to-transparent pointer-events-none" />
            <div className="absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-background to-transparent pointer-events-none" />
          </div>

          {/* Other providers */}
          {others.map((provider) => (
            <div
              key={provider.name}
              className="flex flex-col items-center justify-center gap-2 py-4 sm:py-5 border-b border-r border-dashed border-foreground/[0.06] cursor-default hover:bg-foreground/[0.02] transition-colors"
            >
              <span className="text-foreground/80 dark:text-foreground/70 [&_svg]:w-6 [&_svg]:h-6">
                {provider.icon()}
              </span>
              <span className="text-[10px] font-mono text-foreground/70 dark:text-foreground/60">
                {provider.name}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function ToolsSection() {
  return (
    <div>
      <div className="flex gap-0 items-stretch min-h-[350px]">
        <div className="shrink-0 w-[100px] flex flex-col justify-center items-center">
          <span className="text-3xl font-light text-foreground/85 dark:text-foreground/75 tabular-nums">
            {builtinTools.length}+
          </span>
          <span className="text-[10px] font-mono uppercase tracking-widest text-foreground/45 dark:text-foreground/35 mt-1">
            Tools
          </span>
          <span className="text-[9px] font-mono text-foreground/40 dark:text-foreground/30 mt-2 text-center leading-snug px-1">
            register any function
          </span>
        </div>

        <div className="relative flex-1 h-[350px] overflow-hidden">
          <div className="grid grid-cols-4 h-full">
            {builtinTools.map((toolName) => {
              const Icon = toolIcons[toolIconForName[toolName] ?? "Function"];
              return (
                <span
                  key={toolName}
                  className="group inline-flex flex-col items-center justify-center gap-1.5 py-2 text-foreground/80 dark:text-foreground/70 border-b border-dashed border-foreground/[0.06] cursor-default bg-transparent hover:bg-foreground/[0.03] transition-colors"
                >
                  <span className="inline-flex size-7 items-center justify-center shrink-0 text-foreground/85 dark:text-foreground/75 [&_svg]:w-5 [&_svg]:h-5">
                    {Icon ? Icon() : toolIcons.Function()}
                  </span>
                  <span className="text-[9px] font-mono text-foreground/75 dark:text-foreground/65 truncate max-w-[88px]">
                    {toolName}
                  </span>
                </span>
              );
            })}
          </div>

          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-background to-transparent" />
        </div>
      </div>
    </div>
  );
}

const featuredIcons: Record<string, () => ReactNode> = {
  "Next.js": () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 256 256">
      <defs>
        <linearGradient id="SVGkw9x5bVJ" x1="55.633%" x2="83.228%" y1="56.385%" y2="96.08%">
          <stop offset="0%" stopColor="#FFF" />
          <stop offset="100%" stopColor="#FFF" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="SVGE3ljGbCT" x1="50%" x2="49.953%" y1="0%" y2="73.438%">
          <stop offset="0%" stopColor="#FFF" />
          <stop offset="100%" stopColor="#FFF" stopOpacity="0" />
        </linearGradient>
        <circle id="SVGMFHNZdYm" cx="128" cy="128" r="128" />
      </defs>
      <mask id="SVGalfYF1HT" fill="#fff">
        <use href="#SVGMFHNZdYm" />
      </mask>
      <g mask="url(#SVGalfYF1HT)">
        <circle cx="128" cy="128" r="128" fill="currentColor" />
        <path
          fill="url(#SVGkw9x5bVJ)"
          d="M212.634 224.028L98.335 76.8H76.8v102.357h17.228V98.68L199.11 234.446a128 128 0 0 0 13.524-10.418"
        />
        <path fill="url(#SVGE3ljGbCT)" d="M163.556 76.8h17.067v102.4h-17.067z" />
      </g>
    </svg>
  ),
  TanStack: () => (
    <svg height="20" viewBox="0 0 663 660" width="20" xmlns="http://www.w3.org/2000/svg">
      <path
        fill="currentColor"
        d="m305.114318.62443771c8.717817-1.14462121 17.926803-.36545135 26.712694-.36545135 32.548987 0 64.505987 5.05339923 95.64868 14.63098274 39.74418 12.2236582 76.762804 31.7666864 109.435876 57.477568 40.046637 31.5132839 73.228974 72.8472109 94.520714 119.2362609 39.836383 86.790386 39.544267 191.973146-1.268422 278.398081-26.388695 55.880442-68.724007 102.650458-119.964986 136.75724-41.808813 27.828603-90.706831 44.862601-140.45707 50.89341-63.325458 7.677926-131.784923-3.541603-188.712259-32.729444-106.868873-54.795293-179.52309291-165.076271-180.9604082-285.932068-.27660564-23.300971.08616998-46.74071 4.69884909-69.814998 7.51316071-37.57857 20.61272131-73.903917 40.28618971-106.877282 21.2814003-35.670293 48.7704861-67.1473767 81.6882804-92.5255597 38.602429-29.7610135 83.467691-51.1674988 130.978372-62.05777669 11.473831-2.62966514 22.9946-4.0869914 34.57273-5.4964306l3.658171-.44480576c3.050084-.37153079 6.104217-.74794222 9.162589-1.14972654zm-110.555861 549.44131429c-14.716752 1.577863-30.238964 4.25635-42.869928 12.522173 2.84343.683658 6.102369.004954 9.068638 0 7.124652-.011559 14.317732-.279903 21.434964.032202 17.817402.781913 36.381729 3.63214 53.58741 8.350042 22.029372 6.040631 41.432961 17.928687 62.656049 25.945156 22.389644 8.456554 44.67706 11.084675 68.427 11.084675 11.96813 0 23.845573-.035504 35.450133-3.302696-6.056202-3.225083-14.72582-2.619864-21.434964-3.963236-14.556814-2.915455-28.868774-6.474936-42.869928-11.470264-10.304996-3.676672-20.230803-8.214291-30.11097-12.848661l-6.348531-2.985046c-9.1705-4.309263-18.363277-8.560752-27.845391-12.142608-24.932161-9.418465-52.560181-14.071964-79.144482-11.221737zm22.259385-62.614168c-29.163917 0-58.660076 5.137344-84.915434 18.369597-6.361238 3.206092-12.407546 7.02566-18.137277 11.258891-1.746125 1.290529-4.841829 2.948483-5.487351 5.191839-.654591 2.275558 1.685942 4.182039 3.014086 5.637703 6.562396-3.497556 12.797498-7.199878 19.78612-9.855246 45.19892-17.169893 99.992458-13.570779 145.098218 2.172348 22.494346 7.851335 43.219483 19.592421 65.129314 28.800338 24.503461 10.297807 49.53043 16.975034 75.846795 20.399104 31.04195 4.037546 66.433549.7654 94.808495-13.242161 9.970556-4.921843 23.814245-12.422267 28.030337-23.320339-5.207047.454947-9.892236 2.685918-14.83959 4.224149-7.866632 2.445646-15.827248 4.51974-23.908229 6.138887-27.388113 5.486604-56.512458 6.619429-84.091013 1.639788-25.991939-4.693152-50.142596-14.119246-74.179513-24.03502l-3.068058-1.268177c-2.045137-.846788-4.089983-1.695816-6.135603-2.544467l-3.069142-1.272366c-12.279956-5.085721-24.606928-10.110797-37.210937-14.51024-24.485325-8.546552-50.726667-13.784628-76.671218-13.784628zm51.114145-447.9909432c-34.959602 7.7225298-66.276908 22.7605319-96.457338 41.7180089-17.521434 11.0054099-34.281927 22.2799893-49.465301 36.4444283-22.5792616 21.065423-39.8360564 46.668751-54.8866988 73.411509-15.507372 27.55357-25.4498976 59.665686-30.2554517 90.824149-4.7140432 30.568106-5.4906485 62.70747-.0906864 93.301172 6.7503648 38.248526 19.5989769 74.140579 39.8896436 107.337631 6.8187918-3.184625 11.659796-10.445603 17.3128555-15.336896 11.4149428-9.875888 23.3995608-19.029311 36.2745548-26.928535 4.765981-2.923712 9.662222-5.194315 14.83959-7.275014 1.953055-.785216 5.14604-1.502727 6.06527-3.647828 1.460876-3.406732-1.240754-9.335897-1.704904-12.865654-1.324845-10.095517-2.124534-20.362774-1.874735-30.549941.725492-29.668947 6.269727-59.751557 16.825623-87.521453 7.954845-20.924233 20.10682-39.922168 34.502872-56.971512 4.884699-5.785498 10.077731-11.170545 15.437296-16.512656 3.167428-3.157378 7.098271-5.858983 9.068639-9.908915-10.336599.006606-20.674847 2.987289-30.503603 6.013385-21.174447 6.519522-41.801477 16.19312-59.358362 29.841512-8.008432 6.226409-13.873368 14.387371-21.44733 20.939921-2.32322 2.010516-6.484901 4.704691-9.695199 3.187928-4.8500728-2.29042-4.1014979-11.835213-4.6571581-16.222019-2.1369011-16.873476 4.2548401-38.216325 12.3778671-52.843142 13.039878-23.479694 37.150915-43.528712 65.467327-42.82854 12.228647.302197 22.934587 4.551115 34.625711 7.324555-2.964621-4.211764-6.939158-7.28162-10.717482-10.733763-9.257431-8.459031-19.382979-16.184864-30.503603-22.028985-4.474136-2.350694-9.291232-3.77911-14.015169-5.506421-2.375159-.867783-5.36616-2.062533-6.259834-4.702213-1.654614-4.888817 7.148561-9.416813 10.381943-11.478522 12.499882-7.969406 27.826705-14.525258 42.869928-14.894334 23.509209-.577147 46.479246 12.467678 56.162903 34.665926 3.404469 7.803171 4.411273 16.054969 5.079109 24.382907l.121749 1.56229.174325 2.345587c.01913.260708.038244.521433.057403.782164l.11601 1.56437.120128 1.563971c7.38352-6.019164 12.576553-14.876995 19.78612-21.323859 16.861073-15.07846 39.936636-21.7722 61.831627-14.984333 19.786945 6.133107 36.984382 19.788105 47.105807 37.959541 2.648042 4.754231 10.035685 16.373942 4.698379 21.109183-4.177345 3.707277-9.475079.818243-13.880788-.719162-3.33605-1.16376-6.782939-1.90214-10.241828-2.585698l-1.887262-.369639c-.629089-.122886-1.257979-.246187-1.886079-.372129-11.980496-2.401886-25.91652-2.152533-37.923398-.041284-7.762754 1.364839-15.349083 4.127545-23.083807 5.271929v1.651348c21.149714.175043 41.608563 12.240618 52.043268 30.549941 4.323267 7.585468 6.482428 16.267431 8.138691 24.770223 2.047864 10.50918.608423 21.958802-2.263037 32.201289-.962925 3.433979-2.710699 9.255807-6.817143 10.046802-2.902789.558982-5.36781-2.330878-7.024898-4.279468-4.343878-5.10762-8.475879-9.96341-13.573278-14.374161-12.895604-11.157333-26.530715-21.449361-40.396663-31.373138-7.362086-5.269452-15.425755-12.12007-23.908229-15.340199 2.385052 5.745041 4.721463 11.086326 5.532694 17.339156 2.385876 18.392716-5.314223 35.704625-16.87179 49.540445-3.526876 4.222498-7.29943 8.475545-11.744712 11.755948-1.843407 1.360711-4.156734 3.137561-6.595373 2.752797-7.645687-1.207961-8.555849-12.73272-9.728176-18.637115-3.970415-19.998652-2.375984-39.861068 3.132802-59.448534-4.901187 2.485279-8.443727 7.923994-11.521293 12.385111-6.770975 9.816439-12.645804 20.199291-16.858599 31.375615-16.777806 44.519521-16.616219 96.664142 5.118834 139.523233 2.427098 4.786433 6.110614 4.144058 10.894733 4.144058.720854 0 1.44257-.004515 2.164851-.010924l2.168232-.022283c4.338648-.045438 8.686803-.064635 12.979772.508795 2.227588.297243 5.320818.032202 7.084256 1.673642 2.111344 1.966755.986008 5.338808.4996 7.758859-1.358647 6.765574-1.812904 12.914369-1.812904 19.816178 9.02412-1.398692 11.525415-15.866153 14.724172-23.118874 3.624982-8.216283 7.313444-16.440823 10.667192-24.770223 1.648843-4.093692 3.854171-8.671229 3.275427-13.210785-.649644-5.10184-4.335633-10.510831-6.904531-14.862134-4.86244-8.234447-10.389363-16.70834-13.969002-25.595896-2.861567-7.104926-.197036-15.983399 7.871579-18.521521 4.450228-1.400344 9.198073 1.345848 12.094266 4.562675 6.07269 6.74328 9.992815 16.777697 14.401823 24.692609l34.394873 61.925556c2.920926 5.243856 5.848447 10.481933 8.836976 15.687808 1.165732 2.031158 2.352075 5.167068 4.740424 6.0332 2.127008.77118 5.033095-.325315 7.148561-.748886 5.492297-1.099798 10.97635-2.287117 16.488434-3.28288 6.605266-1.193099 16.673928-.969342 21.434964-6.129805-6.963066-2.205375-15.011895-2.074919-22.259386-1.577863-4.352947.298894-9.178287 1.856116-13.178381-.686135-5.953149-3.783239-9.910373-12.522173-13.552668-18.377854-8.980425-14.439388-17.441465-29.095929-26.041008-43.760726l-1.376261-2.335014-2.765943-4.665258c-1.380597-2.334387-2.750786-4.67476-4.079753-7.036188-1.02723-1.826391-2.549937-4.233231-1.078344-6.24705 1.545791-2.114476 4.91472-2.239146 7.956473-2.243117l.603351.000261c1.195428.001526 2.315572.002427 3.222811-.11692 12.27399-1.615019 24.718635-2.952611 37.098976-2.952611-.963749-3.352237-3.719791-7.141255-2.838484-10.73046 1.972017-8.030506 13.526287-10.543033 18.899867-4.780653 3.60767 3.868283 5.704174 9.192229 8.051303 13.859765 3.097352 6.162006 6.624228 12.118418 9.940876 18.16483 5.805578 10.585967 12.146205 20.881297 18.116667 31.375615.49237.865561.999687 1.726685 1.512269 2.587098l.771613 1.290552c2.577138 4.303168 5.164895 8.635123 6.553094 13.461506-20.735854-.9487-36.30176-25.018751-45.343193-41.283704-.721369 2.604176.450959 4.928448 1.388326 7.431066 1.948109 5.197619 4.276275 10.147535 7.20627 14.862134 4.184765 6.732546 8.982075 13.665732 15.313633 18.553722 11.236043 8.673707 26.05255 8.721596 39.572241 7.794364 8.669619-.595311 19.50252-4.542034 28.030338-1.864372 8.513803 2.673532 11.940924 12.063098 6.884745 19.276187-3.787393 5.403211-8.842747 7.443452-15.128962 8.257566 4.445282 9.53571 10.268996 18.385285 14.490036 28.072919 1.758491 4.035895 3.59118 10.22102 7.8048 12.350433 2.805507 1.416857 6.824562.09743 9.85761.034678-3.043765-8.053625-8.742992-14.887729-11.541904-23.118874 8.533589.390544 16.786875 4.843404 24.732651 7.685374 15.630376 5.590144 31.063836 11.701854 46.475333 17.86913l7.112077 2.848685c6.338978 2.538947 12.71588 5.052299 18.961699 7.812528 2.285297 1.009799 5.449427 3.370401 7.975455 1.917215 2.061054-1.186494 3.394144-4.015253 4.665403-5.931643 3.55573-5.361927 6.775921-10.928622 9.965609-16.513481 12.774414-22.36586 22.143967-46.872692 28.402976-71.833646 20.645168-82.323009 2.934117-173.156241-46.677107-241.922507-19.061454-26.420745-43.033164-49.262193-69.46165-68.1783861-66.13923-47.336721-152.911262-66.294198-232.486917-48.7172481zm135.205158 410.5292842c-17.532977 4.570931-35.601827 8.714164-53.58741 11.040088 2.365265 8.052799 8.145286 15.885969 12.376218 23.118874 1.635653 2.796558 3.3859 6.541816 6.618457 7.755557 3.651364 1.370619 8.063669-.853747 11.508927-1.975838-1.595256-4.364513-4.279573-8.292245-6.476657-12.385112-.905215-1.687677-2.305907-3.685809-1.559805-5.68972 1.410585-3.786541 7.266452-3.563609 10.509727-4.221671 8.54678-1.733916 17.004522-3.898008 25.557073-5.611281 3.150939-.631641 7.538512-2.342438 10.705115-1.285575 2.371037.791232 3.800147 2.744743 5.152304 4.781948l.606196.918752c.80912 1.222827 1.637246 2.41754 2.671212 3.351165 3.457625 3.121874 8.628398 3.60159 13.017619 4.453686-2.678546-6.027421-7.130424-11.301001-9.984571-17.339156-1.659561-3.511592-3.023155-8.677834-6.656381-10.707341-5.005064-2.795733-15.341663 2.461334-20.458024 3.795624zm-110.472507-40.151706c-.825246 10.467897-4.036369 18.984725-9.068639 28.072919 5.76683.729896 11.649079.989984 17.312856 2.39363 4.244947 1.051908 8.156828 3.058296 12.366325 4.211763-2.250671-6.157877-6.426367-11.651913-9.661398-17.339156-3.266358-5.740912-6.189758-12.717032-10.949144-17.339156z"
      />
    </svg>
  ),
};

const featured = [
  {
    name: "Next.js",
    icon: "nextJS",
    href: "/docs/integrations/next",
    snippet: "export { POST } from '@/lib/agent'",
  },
  {
    name: "TanStack",
    icon: "tanstack",
    href: "/docs/integrations/tanstack",
    snippet: "createServerFileRoute().handler(agent.route)",
  },
  {
    name: "Nuxt",
    icon: "nuxt",
    href: "/docs/integrations/nuxt",
    snippet: "export default defineEventHandler(agent.route)",
  },
  {
    name: "SvelteKit",
    icon: "svelteKit",
    href: "/docs/integrations/svelte-kit",
    snippet: "export const POST = agent.route",
  },
  {
    name: "Astro",
    icon: "astro",
    href: "/docs/integrations/astro",
    snippet: "export const POST = agent.route",
  },
  {
    name: "Hono",
    icon: "hono",
    href: "/docs/integrations/hono",
    snippet: "app.post('/agent', agent.handler)",
  },
] as const;

const moreFrameworks = [
  { name: "React", icon: "react", href: "/docs/integrations/react" },
  { name: "Vue", icon: "vue", href: "/docs/integrations/vue" },
  { name: "Remix", icon: "remix", href: "/docs/integrations/remix" },
  {
    name: "Solid Start",
    icon: "solidStart",
    href: "/docs/integrations/solid-start",
  },
  { name: "Express", icon: "express", href: "/docs/integrations/express" },
  { name: "Fastify", icon: "fastify", href: "/docs/integrations/fastify" },
  { name: "NestJS", icon: "nestJS", href: "/docs/integrations/nestjs" },
  { name: "Elysia", icon: "elysia", href: "/docs/integrations/elysia" },
  { name: "Nitro", icon: "nitro", href: "/docs/integrations/nitro" },
  { name: "Expo", icon: "expo", href: "/docs/integrations/expo" },
  { name: "Lynx", icon: "lynx", href: "/docs/integrations/lynx" },
  { name: "Encore", icon: "encore", href: "/docs/integrations/encore" },
  { name: "Convex", icon: "convex", href: "/docs/integrations/convex" },
] as const;

export function IntegrationsSection() {
  return (
    <div className="pt-3 pl-5">
      {/* Featured integrations */}
      <div className="space-y-0">
        {featured.map((fw) => {
          const customIcon = featuredIcons[fw.name];
          const fallbackIcon = frameworkIcons[fw.icon as keyof typeof frameworkIcons];
          const renderIcon = customIcon || fallbackIcon;
          return (
            <Link
              key={fw.name}
              href={fw.href}
              className="group flex items-center gap-3 py-2.5 border-b border-dashed border-foreground/[0.06] last:border-b-0 hover:bg-foreground/[0.02] -mx-2 px-2 transition-colors"
            >
              <span className="text-foreground/80 dark:text-foreground/70 group-hover:text-foreground/95 transition-colors [&_svg]:w-5 [&_svg]:h-5 shrink-0">
                {renderIcon?.()}
              </span>
              <span className="text-[13px] font-medium text-foreground/90 dark:text-foreground/80 group-hover:text-foreground transition-colors shrink-0 w-20">
                {fw.name}
              </span>
              <span className="text-[11px] font-mono text-foreground/60 dark:text-foreground/50 group-hover:text-foreground/75 transition-colors truncate">
                {fw.snippet}
              </span>
              <svg
                className="h-3 w-3 opacity-0 group-hover:opacity-40 transition-opacity shrink-0 ml-auto"
                viewBox="0 0 10 10"
                fill="none"
              >
                <path d="M1 9L9 1M9 1H3M9 1V7" stroke="currentColor" strokeWidth="1.2" />
              </svg>
            </Link>
          );
        })}
      </div>

      {/* More frameworks */}
      <div className="mt-4">
        <p className="text-[9px] font-mono uppercase tracking-widest text-foreground/55 dark:text-foreground/45 mb-2">
          + {moreFrameworks.length} more
        </p>
        <div className="flex flex-wrap gap-1.5">
          {moreFrameworks.map((fw) => {
            const iconFn = frameworkIcons[fw.icon as keyof typeof frameworkIcons];
            return (
              <Link
                key={fw.name}
                href={fw.href}
                className="group inline-flex items-center gap-1.5 px-2 py-1 border border-foreground/[0.1] hover:border-foreground/[0.2] hover:bg-foreground/[0.03] transition-colors"
              >
                <span className="text-foreground/75 dark:text-foreground/65 group-hover:text-foreground transition-colors [&_svg]:w-3 [&_svg]:h-3">
                  {iconFn?.()}
                </span>
                <span className="text-[9px] font-mono text-foreground/75 dark:text-foreground/65 group-hover:text-foreground transition-colors">
                  {fw.name}
                </span>
              </Link>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export function CapabilitiesMarquee() {
  const half = Math.ceil(plugins.length / 2);
  const row1 = plugins.slice(0, half);
  const row2 = plugins.slice(half);

  return (
    <div>
      <Link
        href="/docs"
        className="flex items-center justify-between w-full mb-4 text-[10px] font-mono text-foreground/35 dark:text-foreground/50 hover:text-foreground/55 transition-colors uppercase tracking-wider border-b border-dashed border-foreground/[0.1] px-3 py-1.5 bg-foreground/[0.02] hover:bg-foreground/[0.04]"
      >
        <span className="text-xs text-foreground/85 dark:text-foreground/75">Capabilities</span>
        <span className="flex items-center gap-1">
          browse all <RiArrowUpLine className="size-[10px] rotate-45" />
        </span>
      </Link>

      <div className="relative overflow-hidden">
        {/* Row 1 — scrolls left */}
        <div className="flex animate-[marquee_40s_linear_infinite] mb-1.5">
          {[...row1, ...row1].map((plugin, i) => (
            <span
              key={`${plugin.name}-${i}`}
              className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 mr-1.5 text-[11px] text-foreground dark:text-foreground/90 border border-foreground/[0.06] rounded-sm cursor-default whitespace-nowrap"
            >
              {plugin.name}
              <span className="text-[7px] font-mono uppercase tracking-wider text-foreground/50 ">
                {categoryLabels[plugin.category]}
              </span>
            </span>
          ))}
        </div>

        {/* Row 2 — scrolls right */}
        <div className="flex animate-[marquee-reverse_45s_linear_infinite]">
          {[...row2, ...row2].map((plugin, i) => (
            <span
              key={`${plugin.name}-${i}`}
              className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 mr-1.5 text-[11px] text-foreground dark:text-foreground/90 border border-foreground/[0.06] rounded-sm cursor-default whitespace-nowrap"
            >
              {plugin.name}
              <span className="text-[7px] font-mono uppercase tracking-wider text-foreground/50 ">
                {categoryLabels[plugin.category]}
              </span>
            </span>
          ))}
        </div>

        {/* Side fades */}
        <div className="absolute inset-y-0 left-0 w-12 bg-gradient-to-r from-background to-transparent pointer-events-none" />
        <div className="absolute inset-y-0 right-0 w-12 bg-gradient-to-l from-background to-transparent pointer-events-none" />
      </div>
    </div>
  );
}

export function AiNativeSection() {
  const steps = [
    { label: "mcp", text: "Connected to agentkit docs" },
    { label: "skill", text: "agentkit/add-provider → openai" },
    { label: "skill", text: "agentkit/add-tool → get_weather" },
    { label: "write", text: "lib/agent.ts", lines: 18 },
    { label: "done", text: "AgentRuntime + tool wired up" },
  ];

  const mcpClients = [
    { name: "Claude Code", cmd: "claude mcp add agentkit" },
    { name: "Cursor", cmd: "cursor mcp add agentkit" },
    { name: "VS Code", cmd: "code --add-mcp agentkit" },
  ];

  return (
    <div className="mt-8">
      <div className="flex items-center gap-3 mb-3">
        <div className="flex-1 border-t border-foreground/10" />
        <span className="text-[10px] text-foreground/50 dark:text-foreground/50 font-mono tracking-wider uppercase shrink-0">
          AI Native
        </span>
      </div>
      <p className="text-[14px] text-foreground/80 dark:text-foreground/70 leading-[1.9] mb-5">
        Your agent lives in{" "}
        <span className="text-foreground/90 dark:text-foreground/80">your codebase</span>, so AI can
        wire it up. Ships with{" "}
        <span className="inline-flex items-center gap-1 text-foreground/90 dark:text-foreground/80">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="11"
            height="11"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="opacity-75"
          >
            <path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z" />
            <path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z" />
            <path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4" />
            <path d="M17.599 6.5a3 3 0 0 0 .399-1.375" />
            <path d="M6.003 5.125A3 3 0 0 0 6.401 6.5" />
            <path d="M3.477 10.896a4 4 0 0 1 .585-.396" />
            <path d="M19.938 10.5a4 4 0 0 1 .585.396" />
            <path d="M6 18a4 4 0 0 1-1.967-.516" />
            <path d="M19.967 17.484A4 4 0 0 1 18 18" />
          </svg>
          MCP server
        </span>
        ,{" "}
        <span className="inline-flex items-center gap-1 text-foreground/90 dark:text-foreground/80">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="11"
            height="11"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="opacity-75"
          >
            <polyline points="4 17 10 11 4 5" />
            <line x1="12" x2="20" y1="19" y2="19" />
          </svg>
          Claude Code skills
        </span>
        , and{" "}
        <span className="inline-flex items-center gap-1 text-foreground/90 dark:text-foreground/80">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="11"
            height="11"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="opacity-75"
          >
            <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
            <polyline points="14 2 14 8 20 8" />
          </svg>
          Cursor rules
        </span>
        .
      </p>

      <div className="border border-dashed border-foreground/[0.08] overflow-hidden">
        {/* Prompt line */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-foreground/[0.06] bg-foreground/[0.015]">
          <span className="text-foreground/50 font-mono text-xs select-none">&rsaquo;</span>
          <span className="text-[11px] font-mono text-foreground/80 dark:text-foreground/70">
            Add an OpenAI agent with a weather tool
          </span>
        </div>

        {/* Steps */}
        <div className="divide-y divide-foreground/[0.04]">
          {steps.map((step) => (
            <div key={step.text} className="flex items-center gap-2.5 px-3 py-1.5">
              <span className="text-[8px] font-mono uppercase tracking-wider text-foreground/60 dark:text-foreground/50 w-8 shrink-0">
                {step.label}
              </span>
              <span className="text-[10px] font-mono text-foreground/75 dark:text-foreground/65 truncate">
                {step.text}
              </span>
              {"lines" in step && typeof step.lines === "number" && (
                <span className="text-[9px] font-mono text-emerald-600/80 dark:text-emerald-400/70 ml-auto shrink-0">
                  +{step.lines}
                </span>
              )}
              {step.label === "done" && (
                <svg
                  width="10"
                  height="10"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="text-foreground/60 ml-auto shrink-0"
                >
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              )}
            </div>
          ))}
        </div>

        {/* MCP clients */}
        <div className="border-t border-foreground/[0.06] bg-foreground/[0.015]">
          <div className="flex divide-x divide-foreground/[0.06]">
            {mcpClients.map((mc) => (
              <div key={mc.name} className="flex-1 px-3 py-2">
                <p className="text-[8px] font-mono uppercase tracking-wider text-foreground/55 dark:text-foreground/45 mb-0.5">
                  {mc.name}
                </p>
                <code className="text-[9px] font-mono text-foreground/70 dark:text-foreground/55 truncate block">
                  {mc.cmd}
                </code>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
