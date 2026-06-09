// cSpell:ignore SVGE SVGMFHN Galf
"use client";

import Link from "next/link";
import { useState } from "react";
import { Icons as frameworkIcons } from "@/components/docs/icons";
import { RiArrowRightUpLine } from "@/components/icons/remix";
import { DynamicCodeBlock } from "@/components/ui/dynamic-code-block";
import { toolIcons, builtinTools, toolIconForName, categoryLabels } from "./tools-data";
import {
  providerDrivers,
  moreProviders,
  providerSnippets,
  serverCodeTs,
  serverCodePy,
} from "./providers-data";
import { featuredIcons, featured, moreFrameworks } from "./integrations-data";

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
  { name: "Text", category: "modality" },
  { name: "Voice", category: "modality" },
  { name: "STT / TTS", category: "modality" },
  { name: "Agent Loop", category: "runtime" },
  { name: "Tool Planner", category: "runtime" },
  { name: "Cancellation", category: "runtime" },
  { name: "Replay", category: "events" },
  { name: "Projection", category: "events" },
  { name: "In-Memory Bus", category: "events" },
  { name: "Redis Bus", category: "events" },
  { name: "MCP", category: "tools" },
];

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
          browse all <RiArrowRightUpLine className="size-[10px]" />
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
