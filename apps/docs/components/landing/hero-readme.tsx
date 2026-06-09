"use client";

import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { RiNpmjsFill } from "../icons/remix";
import {
  AgentLoopTabs,
  CapabilitiesMarquee,
  IntegrationsSection,
  ProvidersSection,
  ToolsSection,
} from "./framework-sections";

const mcpCommands = [
  { name: "Cursor", command: "npx agentkit mcp --cursor" },
  { name: "Claude Code", command: "npx agentkit mcp --claude-code" },
  { name: "Open Code", command: "npx agentkit mcp --open-code" },
  { name: "Manual", command: "npx agentkit mcp --manual" },
];

const aiPromptText = `Set up an agent in my project using agentkit (agentkit npm package).

1. Install agentkit.

2. Create lib/agent.ts — instantiate the agent runtime with:
   - An LLM provider (OpenAI or Kimi)
   - A tool registry with my project's tools
   - The in-memory event bus for local development

3. Wire up the agent loop so it can call tools and stream responses.

4. Add the API route handler for my framework (e.g. app/api/agent/route.ts for Next.js App Router).

5. Add AGENTKIT_API_KEY to my .env if it doesn't exist.

Refer to github.com/enkyuan/alloy for exact API and tool syntax.`;

function InstallBlock() {
  const [mode, setMode] = useState<"cli" | "prompt" | "mcp">("cli");
  const [copied, setCopied] = useState(false);
  const [pmOpen, setPmOpen] = useState(false);
  const [promptOpen, setPromptOpen] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);
  const [contentHeight, setContentHeight] = useState<number | "auto">("auto");
  const [overflow, setOverflow] = useState<"hidden" | "visible">("visible");

  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      setContentHeight(el.offsetHeight);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useLayoutEffect(() => {
    setOverflow("hidden");
  }, [mode]);

  useLayoutEffect(() => {
    if (pmOpen) {
      setOverflow("visible");
    }
  }, [pmOpen]);

  const copy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setPmOpen(false);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="mb-6 rounded-md border border-foreground/[0.1] relative">
      {/* Tabs */}
      <div className="flex items-center border-b border-foreground/[0.1]">
        <button
          onClick={() => {
            setMode("cli");
            setCopied(false);
            setPmOpen(false);
          }}
          className={cn(
            "px-4 py-2 text-[12px] transition-colors duration-150 relative",
            mode === "cli"
              ? "text-neutral-800 dark:text-neutral-200"
              : "text-neutral-400 dark:text-neutral-500 hover:text-neutral-600 dark:hover:text-neutral-400",
          )}
        >
          CLI
          {mode === "cli" && (
            <div className="absolute bottom-0 left-4 right-4 h-[1.5px] bg-neutral-600 dark:bg-neutral-400" />
          )}
        </button>
        <button
          onClick={() => {
            setMode("prompt");
            setCopied(false);
            setPmOpen(false);
          }}
          className={cn(
            "px-4 py-2 text-[12px] transition-colors duration-150 relative",
            mode === "prompt"
              ? "text-neutral-800 dark:text-neutral-200"
              : "text-neutral-400 dark:text-neutral-500 hover:text-neutral-600 dark:hover:text-neutral-400",
          )}
        >
          Prompt
          {mode === "prompt" && (
            <div className="absolute bottom-0 left-4 right-4 h-[1.5px] bg-neutral-600 dark:bg-neutral-400" />
          )}
        </button>
        <button
          onClick={() => {
            setMode("mcp");
            setCopied(false);
            setPmOpen(false);
          }}
          className={cn(
            "px-4 py-2 text-[12px] transition-colors duration-150 relative",
            mode === "mcp"
              ? "text-neutral-800 dark:text-neutral-200"
              : "text-neutral-400 dark:text-neutral-500 hover:text-neutral-600 dark:hover:text-neutral-400",
          )}
        >
          MCP
          {mode === "mcp" && (
            <div className="absolute bottom-0 left-4 right-4 h-[1.5px] bg-neutral-600 dark:bg-neutral-400" />
          )}
        </button>
      </div>

      {/* Content */}
      <motion.div
        animate={{ height: contentHeight }}
        initial={false}
        transition={{ duration: 0.3, ease: [0.25, 0.1, 0.25, 1] }}
        onAnimationComplete={() => setOverflow("visible")}
        style={{ overflow }}
      >
        <div ref={contentRef}>
          <AnimatePresence mode="wait" initial={false}>
            <div>
              {mode === "cli" ? (
                <div className="flex items-center justify-between bg-neutral-100/50 dark:bg-[#050505] px-4 py-3">
                  <code
                    className="text-[13px]"
                    style={{ fontFamily: "var(--font-geist-pixel-square)" }}
                  >
                    <span className="text-purple-600/90 dark:text-purple-400/90">pip</span>{" "}
                    <span className="text-neutral-700 dark:text-neutral-300">install agentkit</span>
                  </code>
                  <div className="relative">
                    <button
                      onClick={() => copy("pip install agentkit")}
                      className="text-neutral-400 dark:text-neutral-500 hover:text-neutral-600 dark:hover:text-neutral-300 transition-colors p-1"
                      aria-label="Copy command"
                    >
                      {copied ? (
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          viewBox="0 0 24 24"
                          className="h-4 w-4"
                        >
                          <path
                            fill="currentColor"
                            d="M9 16.17L4.83 12l-1.42 1.41L9 19L21 7l-1.41-1.41z"
                          />
                        </svg>
                      ) : (
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          viewBox="0 0 24 24"
                          className="h-4 w-4"
                        >
                          <path
                            fill="currentColor"
                            d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2m0 16H8V7h11z"
                          />
                        </svg>
                      )}
                    </button>
                  </div>
                </div>
              ) : mode === "mcp" ? (
                <div className="flex items-center justify-between bg-neutral-100/50 dark:bg-[#050505] px-4 py-3">
                  <code
                    className="text-[13px] truncate"
                    style={{ fontFamily: "var(--font-geist-pixel-square)" }}
                  >
                    <span className="text-purple-600/90 dark:text-purple-400/90">npx</span>{" "}
                    <span className="text-neutral-700 dark:text-neutral-300">agentkit mcp</span>
                  </code>
                  <div className="relative">
                    <button
                      onClick={() => {
                        if (copied) return;
                        setPmOpen(!pmOpen);
                      }}
                      className="text-neutral-400 dark:text-neutral-500 hover:text-neutral-600 dark:hover:text-neutral-300 transition-colors p-1"
                      aria-label="Add MCP"
                    >
                      {copied ? (
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          viewBox="0 0 24 24"
                          className="h-4 w-4"
                        >
                          <path
                            fill="currentColor"
                            d="M9 16.17L4.83 12l-1.42 1.41L9 19L21 7l-1.41-1.41z"
                          />
                        </svg>
                      ) : (
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          viewBox="0 0 24 24"
                          className="h-4 w-4"
                        >
                          <path fill="currentColor" d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6z" />
                        </svg>
                      )}
                    </button>
                    {pmOpen && (
                      <>
                        <div
                          className="fixed inset-0 z-40"
                          role="button"
                          tabIndex={-1}
                          aria-label="Close dropdown"
                          onClick={() => setPmOpen(false)}
                          onKeyDown={(e) => {
                            if (e.key === "Escape") setPmOpen(false);
                          }}
                        />
                        <div className="absolute right-0 top-full mt-2 w-[160px] bg-white dark:bg-[#050505] border border-neutral-200 dark:border-white/[0.07] shadow-2xl shadow-black/10 dark:shadow-black/80 z-50 rounded-sm">
                          {mcpCommands.map((mc, i) => (
                            <button
                              key={mc.name}
                              onClick={() => copy(mc.command)}
                              className={cn(
                                "flex items-center gap-2.5 w-full px-3 py-2 text-[12px] text-neutral-500 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-white hover:bg-neutral-100 dark:hover:bg-white/[0.05] transition-all text-left",
                                i < mcpCommands.length - 1 &&
                                  "border-b border-neutral-100 dark:border-white/[0.06]",
                              )}
                            >
                              <span className="flex items-center justify-center w-3.5 h-3.5 shrink-0">
                                {mc.name === "Cursor" && (
                                  <svg
                                    xmlns="http://www.w3.org/2000/svg"
                                    className="h-3.5 w-3.5"
                                    viewBox="0 0 24 24"
                                  >
                                    <path
                                      fill="currentColor"
                                      d="M11.503.131L1.891 5.678a.84.84 0 0 0-.42.726v11.188c0 .3.162.575.42.724l9.609 5.55a1 1 0 0 0 .998 0l9.61-5.55a.84.84 0 0 0 .42-.724V6.404a.84.84 0 0 0-.42-.726L12.497.131a1.01 1.01 0 0 0-.996 0M2.657 6.338h18.55c.263 0 .43.287.297.515L12.23 22.918c-.062.107-.229.064-.229-.06V12.335a.59.59 0 0 0-.295-.51l-9.11-5.257c-.109-.063-.064-.23.061-.23"
                                    />
                                  </svg>
                                )}
                                {mc.name === "Claude Code" && (
                                  <svg
                                    xmlns="http://www.w3.org/2000/svg"
                                    className="h-3.5 w-3.5"
                                    viewBox="0 0 16 16"
                                  >
                                    <path
                                      fill="currentColor"
                                      d="m6.96 15.2l.224-.992l.256-1.28l.208-1.024l.192-1.264l.112-.416l-.016-.032l-.08.016l-.96 1.312l-1.456 1.968l-1.152 1.216l-.272.112l-.48-.24l.048-.448l.272-.384l1.584-2.032l.96-1.264l.624-.72l-.016-.096h-.032l-4.224 2.752L2 12.48l-.336-.304l.048-.496l.16-.16l1.264-.88l3.152-1.76l.048-.16l-.048-.08h-.16L5.6 8.608L3.808 8.56l-1.552-.064l-1.52-.08l-.384-.08L0 7.856l.032-.24l.32-.208l.464.032l1.008.08l1.52.096l1.104.064l1.632.176h.256l.032-.112l-.08-.064l-.064-.064L4.64 6.56L2.944 5.44l-.896-.656l-.48-.336l-.24-.304l-.096-.672l.432-.48l.592.048l.144.032l.592.464l1.264.976L5.92 5.744l.24.192l.112-.064v-.048l-.112-.176l-.896-1.632l-.96-1.664l-.432-.688l-.112-.416a1.7 1.7 0 0 1-.064-.48l.496-.672L4.464 0l.672.096l.272.24l.416.944l.656 1.488l1.04 2.016l.304.608l.16.544l.064.176h.112v-.096l.08-1.152l.16-1.392l.16-1.792l.048-.512l.256-.608l.496-.32l.384.176l.32.464l-.048.288L9.84 2.4l-.384 1.936l-.24 1.312h.144l.16-.176l.656-.864l1.104-1.376l.48-.544l.576-.608l.368-.288h.688l.496.752l-.224.784l-.704.896l-.592.752l-.848 1.136l-.512.912l.048.064h.112l1.904-.416l1.04-.176l1.216-.208l.56.256l.064.256l-.224.544l-1.312.32l-1.536.304l-2.288.544l-.032.016l.032.048l1.024.096l.448.032h1.088l2.016.144l.528.352l.304.416l-.048.336l-.816.4l-1.088-.256l-2.56-.608l-.864-.208h-.128v.064l.736.72l1.328 1.2l1.68 1.552l.08.384l-.208.32l-.224-.032l-1.472-1.12l-.576-.496l-1.28-1.072h-.08v.112l.288.432l1.568 2.352l.08.72l-.112.224l-.416.144l-.432-.08l-.928-1.28l-.944-1.456l-.768-1.296l-.08.064l-.464 4.832l-.208.24l-.48.192l-.4-.304z"
                                    />
                                  </svg>
                                )}
                                {mc.name === "Open Code" && (
                                  <svg
                                    className="h-3.5 w-3.5"
                                    viewBox="0 0 32 40"
                                    fill="none"
                                    xmlns="http://www.w3.org/2000/svg"
                                  >
                                    <g clipPath="url(#oc)">
                                      <path
                                        d="M24 32H8V16H24V32Z"
                                        fill="currentColor"
                                        opacity="0.5"
                                      />
                                      <path
                                        d="M24 8H8V32H24V8ZM32 40H0V0H32V40Z"
                                        fill="currentColor"
                                      />
                                    </g>
                                    <defs>
                                      <clipPath id="oc">
                                        <rect width="32" height="40" fill="white" />
                                      </clipPath>
                                    </defs>
                                  </svg>
                                )}
                                {mc.name === "Manual" && (
                                  <svg
                                    xmlns="http://www.w3.org/2000/svg"
                                    className="h-3.5 w-3.5"
                                    viewBox="0 0 24 24"
                                  >
                                    <path
                                      fill="none"
                                      stroke="currentColor"
                                      strokeLinecap="round"
                                      strokeLinejoin="round"
                                      strokeWidth="2"
                                      d="M12 19h8M4 17l6-6l-6-6"
                                    />
                                  </svg>
                                )}
                              </span>
                              <span className="font-mono text-[11px]">{mc.name}</span>
                            </button>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                </div>
              ) : (
                <div className="bg-neutral-100/50 dark:bg-[#050505] px-5 py-4">
                  <p className="text-[13px] font-medium text-neutral-700 dark:text-neutral-200 leading-relaxed">
                    Set up an agent in my project using agentkit.
                  </p>
                  <div className="relative mt-1.5">
                    <p className="text-[11px] text-neutral-400 dark:text-neutral-500 leading-relaxed line-clamp-2">
                      Install agentkit. Create lib/agent.ts with the{" "}
                      <code className="text-neutral-500 dark:text-neutral-400">agent runtime</code>,
                      register your tools, add the route handler, and start the loop...
                    </p>
                    <div className="absolute bottom-0 left-0 right-0 h-6 bg-gradient-to-t from-neutral-100/50 dark:from-[#050505] to-transparent pointer-events-none" />
                  </div>
                  <div className="flex items-center justify-between mt-3 pt-2 border-t border-foreground/[0.04]">
                    <button
                      onClick={() => setPromptOpen(true)}
                      className="flex items-center gap-1 text-[11px] text-neutral-400 dark:text-neutral-500 hover:text-neutral-600 dark:hover:text-neutral-300 transition-colors"
                    >
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        viewBox="0 0 24 24"
                        className="h-3 w-3"
                      >
                        <path
                          fill="currentColor"
                          d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5M12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5s5 2.24 5 5s-2.24 5-5 5m0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3s3-1.34 3-3s-1.34-3-3-3"
                        />
                      </svg>
                      View full prompt
                    </button>
                    <button
                      onClick={() => copy(aiPromptText)}
                      className="flex items-center gap-1.5 text-[11px] text-neutral-400 dark:text-neutral-500 hover:text-neutral-600 dark:hover:text-neutral-300 transition-colors"
                    >
                      {copied ? (
                        <>
                          <svg
                            xmlns="http://www.w3.org/2000/svg"
                            viewBox="0 0 24 24"
                            className="h-3.5 w-3.5"
                          >
                            <path
                              fill="currentColor"
                              d="M9 16.17L4.83 12l-1.42 1.41L9 19L21 7l-1.41-1.41z"
                            />
                          </svg>
                          Copied
                        </>
                      ) : (
                        <>
                          <svg
                            xmlns="http://www.w3.org/2000/svg"
                            viewBox="0 0 24 24"
                            className="h-3.5 w-3.5"
                          >
                            <path
                              fill="currentColor"
                              d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2m0 16H8V7h11z"
                            />
                          </svg>
                          Copy prompt
                        </>
                      )}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </AnimatePresence>
        </div>
      </motion.div>

      {/* Prompt dialog */}
      <AnimatePresence>
        {promptOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 lg:left-[40%] z-50 flex items-center justify-center"
            onClick={() => setPromptOpen(false)}
          >
            {/* Backdrop - only covers right/content side */}
            <div className="absolute inset-0 bg-black/50 dark:bg-black/70 backdrop-blur-sm" />

            {/* Dialog */}
            <motion.div
              initial={{ opacity: 0, y: 8, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 8, scale: 0.98 }}
              transition={{ duration: 0.2, ease: "easeOut" }}
              onClick={(e) => e.stopPropagation()}
              className="relative w-[calc(100%-2rem)] max-w-lg mx-4 bg-neutral-50 dark:bg-[#0a0a0a] border border-neutral-200 dark:border-white/[0.06] rounded-sm shadow-2xl"
            >
              {/* Close */}
              <button
                onClick={() => setPromptOpen(false)}
                className="absolute top-3 right-3 text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300 transition-colors z-10"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" className="h-4 w-4">
                  <path
                    fill="currentColor"
                    d="M19 6.41L17.59 5L12 10.59L6.41 5L5 6.41L10.59 12L5 17.59L6.41 19L12 13.41L17.59 19L19 17.59L13.41 12z"
                  />
                </svg>
              </button>

              {/* Content */}
              <div className="px-5 py-5 max-h-[60vh] overflow-y-auto">
                <p className="text-[12px] font-mono text-neutral-600 dark:text-neutral-400 leading-[1.9] whitespace-pre-line">
                  {aiPromptText}
                </p>
              </div>

              {/* Footer */}
              <div className="flex justify-end px-5 py-3 border-t border-neutral-200 dark:border-white/[0.06]">
                <button
                  onClick={() => copy(aiPromptText)}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] rounded-sm border border-neutral-200 dark:border-white/[0.08] text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200 hover:bg-neutral-100 dark:hover:bg-white/[0.04] transition-colors"
                >
                  {copied ? (
                    <>
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        viewBox="0 0 24 24"
                        className="h-3.5 w-3.5"
                      >
                        <path
                          fill="currentColor"
                          d="M9 16.17L4.83 12l-1.42 1.41L9 19L21 7l-1.41-1.41z"
                        />
                      </svg>
                      Copied
                    </>
                  ) : (
                    <>
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        viewBox="0 0 24 24"
                        className="h-3.5 w-3.5"
                      >
                        <path
                          fill="currentColor"
                          d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2m0 16H8V7h11z"
                        />
                      </svg>
                      Copy prompt
                    </>
                  )}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

type CommunityHeroStats = {
  npmDownloads: number;
  npmWeeklyHistory: number[];
  githubStars: number;
  contributors: number;
};

function formatCount(num: number | null | undefined): string {
  if (num == null) return "—";
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`;
  if (num >= 1_000) return `${(num / 1_000).toFixed(num >= 10_000 ? 0 : 1)}k`;
  return num.toString();
}

function _NpmSparkline({ data: raw }: { data: number[] }) {
  // Drop the last bucket — it's the incomplete current week
  const data = raw.length > 2 ? raw.slice(0, -1) : raw;
  const w = 120;
  const h = 32;
  const pad = 1;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const points = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * (w - pad * 2);
    const y = h - pad - ((v - min) / range) * (h - pad * 2);
    return `${x},${y}`;
  });
  const line = points.join(" ");
  const areaPath = `M${points[0]} ${points.map((p) => `L${p}`).join(" ")} L${w - pad},${h} L${pad},${h} Z`;

  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="shrink-0 ml-auto">
      <defs>
        <linearGradient id="npm-spark-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" className="[stop-color:theme(colors.emerald.500)]" stopOpacity="0.15" />
          <stop offset="100%" className="[stop-color:theme(colors.emerald.500)]" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill="url(#npm-spark-fill)" />
      <polyline
        points={line}
        fill="none"
        className="stroke-emerald-500/50"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

function ReadmeFooter({ stats }: { stats: CommunityHeroStats }) {
  return (
    <div className="relative mt-10 pt-8 pb-16 overflow-hidden">
      {/* Watermark logo */}
      <div
        className="absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none select-none opacity-[0.04] dark:opacity-[0.05]"
        aria-hidden="true"
      >
        <svg
          width="200"
          height="200"
          viewBox="0 0 48 48"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <path d="M31 3V17L17 3H31Z" className="fill-foreground" />
          <path
            fillRule="evenodd"
            clipRule="evenodd"
            d="M45 31V17H31H17V31L3 17L17 3H3V17V31H17V45H31H45V31ZM45 31L31 45L17 31H31V17L45 31Z"
            className="fill-foreground"
          />
        </svg>
      </div>

      {/* Dot grid */}
      <div
        className="absolute inset-0 pointer-events-none select-none"
        aria-hidden="true"
        style={{
          backgroundImage: "radial-gradient(circle, currentColor 0.5px, transparent 0.5px)",
          backgroundSize: "24px 24px",
          opacity: 0.03,
        }}
      />

      {/* CTA */}
      <div className="relative space-y-6">
        <p className="text-center text-lg text-balance text-foreground/60 dark:text-foreground/50 tracking-tight">
          Ship a tool-using agent in minutes, not months.
        </p>

        <div className="flex items-center justify-center gap-2">
          {stats.npmDownloads > 0 && (
            <a href="https://github.com/enkyuan/alloy" target="_blank" rel="noopener noreferrer">
              <div className="flex items-center gap-1.5 px-2.5 hover:bg-foreground/4 rounded-sm transition-colors text-foreground/50 dark:text-foreground/50">
                <RiNpmjsFill className="size-[11px] -translate-y-px" />
                <span className="text-xs font-mono">{formatCount(stats.npmDownloads)} / week</span>
              </div>
            </a>
          )}
          {stats.githubStars > 0 && (
            <a href="https://github.com/enkyuan/alloy" target="_blank" rel="noopener noreferrer">
              <div className="flex items-center gap-1.5 px-2.5 hover:bg-foreground/4 rounded-sm transition-colors text-foreground/50 dark:text-foreground/50">
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
                  className="size-[11px] -translate-y-px"
                >
                  <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                </svg>
                <span className="text-xs font-mono">{formatCount(stats.githubStars)} stars</span>
              </div>
            </a>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-center gap-4 pt-1">
          <Link
            href="/docs/installation"
            className="inline-flex items-center gap-1.5 px-4 sm:px-5 py-2 bg-neutral-900 text-neutral-100 dark:bg-neutral-100 dark:text-neutral-900 text-xs sm:text-sm font-medium hover:opacity-90 transition-colors"
          >
            Get Started
          </Link>
          <Link
            href="/docs/getting-started"
            className="relative inline-flex items-center gap-1.5 px-4 sm:px-5 py-2 text-neutral-600 dark:text-neutral-300 text-xs sm:text-sm font-medium transition-colors group"
          >
            <span
              className="absolute inset-0 opacity-[0.04] group-hover:opacity-[0.08] transition-opacity"
              style={{
                backgroundImage: `repeating-linear-gradient(
                  -45deg,
                  transparent,
                  transparent 4px,
                  currentColor 4px,
                  currentColor 5px
                )`,
              }}
            />
            <span className="absolute top-0 -left-[6px] -right-[6px] h-px bg-foreground/20 group-hover:bg-foreground/30 transition-colors" />
            <span className="absolute bottom-0 -left-[6px] -right-[6px] h-px bg-foreground/20 group-hover:bg-foreground/30 transition-colors" />
            <span className="absolute left-0 -top-[6px] -bottom-[6px] w-px bg-foreground/20 group-hover:bg-foreground/30 transition-colors" />
            <span className="absolute right-0 -top-[6px] -bottom-[6px] w-px bg-foreground/20 group-hover:bg-foreground/30 transition-colors" />
            <span className="absolute -bottom-[6px] -right-[6px] font-mono text-[8px] text-foreground/40 dark:text-foreground/50 leading-none select-none translate-x-1/2 translate-y-1/2">
              +
            </span>
            <span className="relative">Sign In </span>
          </Link>
        </div>
      </div>
    </div>
  );
}

export function HeroReadMe({ stats }: { stats: CommunityHeroStats }) {
  const [frameworkTab, setFrameworkTab] = useState<"loop" | "providers" | "tools" | "integrations">(
    "loop",
  );

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5, delay: 0.15, ease: "easeOut" }}
      className="flex flex-col w-full"
    >
      {/* Markdown content */}
      <div className="flex-1 overflow-x-hidden no-scrollbar">
        <div className="p-5 lg:px-8 lg:pt-20">
          <motion.article
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4, delay: 0.3 }}
            className="no-scrollbar pb-0"
          >
            <h1 className="flex items-center gap-3 text-sm sm:text-[15px] font-mono text-neutral-900 dark:text-neutral-100 mb-4 sm:mb-5">
              README
              <span className="flex-1 h-px bg-foreground/15" />
            </h1>

            <p className="text-sm sm:text-[15px] text-foreground/80 mb-6 sm:mb-8 leading-relaxed">
              The agent runtime that lives{" "}
              <span className="font-medium text-foreground/90 dark:text-foreground/80">
                inside your app
              </span>
              . An event-sourced agent loop, a tool registry, pluggable LLM providers, and STT/TTS
              voice, in one{" "}
              <span className="font-medium text-foreground/90 dark:text-foreground/80">
                embeddable SDK
              </span>{" "}
              for Python and TypeScript.
            </p>

            <InstallBlock />

            <div className="flex items-center gap-4 my-4 mt-8">
              <span className="text-lg font-medium text-foreground/90 dark:text-foreground/80 tracking-tight shrink-0">
                Features
              </span>
              <div className="flex-1 border-t border-foreground/10" />
            </div>

            <div className="relative grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 mb-2 border border-foreground/[0.08] overflow-hidden">
              {[
                {
                  label: "Framework Agnostic",
                  headline: "Works with your stack.",
                  desc: "Next.js, Nuxt, SvelteKit, Astro, Hono, and 20+ more.",
                  logos: true,
                  href: "/docs",
                },
                {
                  label: "Agent Loop",
                  headline: "Event-sourced runtime.",
                  desc: "A tool-using agent loop with replay and full event history.",
                  href: "/docs",
                },
                {
                  label: "Tools",
                  headline: "Tool registry + toolgen.",
                  desc: "Register functions as tools with a provider-neutral payload.",
                  href: "/docs",
                },
                {
                  label: "Providers",
                  headline: "Pluggable LLM providers.",
                  desc: "OpenAI, Kimi, and Gemini behind one streaming interface.",
                  href: "/docs",
                },
                {
                  label: "Voice",
                  headline: "STT/TTS modalities.",
                  desc: "Speech-to-text and text-to-speech for voice agents.",
                  href: "/docs",
                },
                {
                  label: "Retrieval",
                  headline: "RAG tool retriever.",
                  desc: "Pluggable embedder and cache to select tools by relevance.",
                  href: "/docs",
                },
                {
                  label: "Event Bus",
                  headline: "In-memory or Redis.",
                  desc: "Run infra-free locally, swap in Redis for live fan-out.",
                  href: "/docs",
                },
                {
                  label: "Observability",
                  headline: "Replay & projection.",
                  desc: "Every turn is an event; project state and replay sessions.",
                  href: "/docs",
                },
                {
                  label: "Two SDKs",
                  headline: "Python & TypeScript.",
                  desc: "The same runtime core, embeddable in either ecosystem.",
                  href: "/docs",
                },
              ].map((feature, i) => (
                <Link
                  key={feature.label}
                  href={"href" in feature ? feature.href : "#"}
                  className="contents"
                >
                  <motion.div
                    whileHover={{
                      y: -2,
                      transition: { duration: 0.2, ease: "easeOut" },
                    }}
                    className={cn(
                      "group/card relative p-4 lg:p-5 border-foreground/[0.08] min-h-[100px] transition-all duration-200 hover:bg-foreground/[0.02] hover:shadow-[inset_0_1px_0_0_rgba(128,128,128,0.1)] hover:z-10",
                      // Bottom border: all except last; 3-col last row starts at 6
                      i < 8 && "border-b",
                      i >= 6 && "md:border-b-0",
                      // Right border: none on mobile
                      // 2-col: left column (even indices) gets right border
                      i % 2 === 0 && i < 8 && "sm:border-r",
                      // 3-col: remove right border on 3rd column, add on odd indices that need it
                      i % 3 === 2 && "md:border-r-0",
                      i % 2 !== 0 && i % 3 !== 2 && "md:border-r",
                    )}
                  >
                    {/* Arrow icon — top right, visible on hover */}
                    <span className="absolute top-3 right-3 lg:top-4 lg:right-4 opacity-0 -translate-y-0.5 group-hover/card:opacity-100 group-hover/card:translate-y-0 transition-all duration-200">
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        width="16"
                        height="16"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        className="text-foreground/40 dark:text-foreground/50"
                      >
                        <line x1="7" y1="17" x2="17" y2="7" />
                        <polyline points="7 7 17 7 17 17" />
                      </svg>
                    </span>
                    <div className="mb-1">
                      <div className="text-[11px] font-mono text-foreground/45 dark:text-foreground/30 tracking-wider transition-colors duration-200 group-hover/card:text-foreground/60 dark:group-hover/card:text-foreground/40">
                        {String(i + 1).padStart(2, "0")}
                      </div>
                      <div className="text-[13px] font-medium text-foreground/80 dark:text-neutral-100 transition-colors duration-200">
                        {feature.headline}
                      </div>
                    </div>
                    <div className="text-[13px] text-neutral-500 dark:text-neutral-400 leading-relaxed transition-colors duration-200 group-hover/card:text-neutral-400 dark:group-hover/card:text-neutral-300">
                      {feature.desc}
                    </div>
                    {"logos" in feature && feature.logos && (
                      <div className="flex items-center gap-3.5 mt-3">
                        {/* Next.js */}
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          width="15"
                          height="15"
                          viewBox="0 0 24 24"
                          className="text-neutral-800 dark:text-neutral-200 opacity-90 transition-all duration-300 group-hover/card:opacity-100 group-hover/card:animate-[icon-bounce_0.4s_ease-out_0s]"
                        >
                          <path
                            fill="currentColor"
                            d="M12 22C6.477 22 2 17.523 2 12S6.477 2 12 2s10 4.477 10 10s-4.477 10-10 10m4-14h-1.35v4H16zM9.346 9.71l6.059 7.828l1.054-.809L9.683 8H8v7.997h1.346z"
                          />
                        </svg>
                        {/* Nuxt */}
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          width="15"
                          height="15"
                          viewBox="0 0 24 24"
                          className="text-[#00DC82] opacity-90 transition-all duration-300 group-hover/card:opacity-100 group-hover/card:animate-[icon-bounce_0.4s_ease-out_0.05s]"
                        >
                          <path
                            fill="currentColor"
                            d="M13.2 18.666h7.4c.236 0 .462-.083.667-.2c.204-.117.415-.264.533-.466c.118-.203.2-.433.2-.667s-.082-.464-.2-.667l-5-8.6a1.2 1.2 0 0 0-.467-.466a1.6 1.6 0 0 0-.733-.2c-.236 0-.462.083-.667.2a1.2 1.2 0 0 0-.466.466l-1.267 2.2L10.667 6c-.118-.203-.262-.417-.467-.534s-.43-.133-.667-.133c-.236 0-.462.016-.666.133s-.416.33-.534.534l-6.2 10.666c-.118.203-.133.433-.133.667s.015.464.133.667c.118.202.33.35.534.466s.43.2.666.2H8c1.85 0 3.195-.83 4.133-2.4l2.267-3.933l1.2-2.067l3.667 6.267H14.4zm-5.267-2.133H4.667l4.866-8.4l2.467 4.2l-1.634 2.848c-.623 1.02-1.333 1.352-2.433 1.352"
                          />
                        </svg>
                        {/* SvelteKit */}
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          width="13"
                          height="15"
                          viewBox="0 0 426 512"
                          className="text-[#FF3E00] opacity-90 transition-all duration-300 group-hover/card:opacity-100 group-hover/card:animate-[icon-bounce_0.4s_ease-out_0.1s]"
                        >
                          <path
                            fill="currentColor"
                            d="M403.508 229.23C491.235 87.7 315.378-58.105 190.392 23.555L71.528 99.337c-57.559 37.487-82.55 109.513-47.45 183.53c-87.761 133.132 83.005 289.03 213.116 205.762l118.864-75.782c64.673-42.583 79.512-116.018 47.45-183.616m-297.592-80.886l118.69-75.739c77.973-46.679 167.756 34.942 135.388 110.992c-19.225-15.274-40.65-24.665-56.923-28.894c6.186-24.57-22.335-42.796-42.174-30.106l-118.95 75.48c-29.411 20.328 1.946 62.138 31.014 44.596l45.33-28.895c101.725-57.403 198 80.425 103.38 147.975l-118.692 75.739C131.455 485.225 34.11 411.96 67.592 328.5c17.786 13.463 36.677 23.363 56.923 28.894c-4.47 28.222 24.006 41.943 42.476 30.365L285.64 312.02c29.28-21.955-2.149-61.692-30.97-44.595l-45.504 28.894c-100.56 58.77-199.076-80.42-103.25-147.975"
                          />
                        </svg>
                        {/* TanStack Start */}
                        <svg
                          height="13"
                          viewBox="0 0 663 660"
                          width="13"
                          className="text-[#EF4444] opacity-90 transition-all duration-300 group-hover/card:opacity-100 group-hover/card:animate-[icon-bounce_0.4s_ease-out_0.15s]"
                          xmlns="http://www.w3.org/2000/svg"
                        >
                          <path
                            d="m305.114318.62443771c8.717817-1.14462121 17.926803-.36545135 26.712694-.36545135 32.548987 0 64.505987 5.05339923 95.64868 14.63098274 39.74418 12.2236582 76.762804 31.7666864 109.435876 57.477568 40.046637 31.5132839 73.228974 72.8472109 94.520714 119.2362609 39.836383 86.790386 39.544267 191.973146-1.268422 278.398081-26.388695 55.880442-68.724007 102.650458-119.964986 136.75724-41.808813 27.828603-90.706831 44.862601-140.45707 50.89341-63.325458 7.677926-131.784923-3.541603-188.712259-32.729444-106.868873-54.795293-179.52309291-165.076271-180.9604082-285.932068-.27660564-23.300971.08616998-46.74071 4.69884909-69.814998 7.51316071-37.57857 20.61272131-73.903917 40.28618971-106.877282 21.2814003-35.670293 48.7704861-67.1473767 81.6882804-92.5255597 38.602429-29.7610135 83.467691-51.1674988 130.978372-62.05777669 11.473831-2.62966514 22.9946-4.0869914 34.57273-5.4964306l3.658171-.44480576c3.050084-.37153079 6.104217-.74794222 9.162589-1.14972654zm-110.555861 549.44131429c-14.716752 1.577863-30.238964 4.25635-42.869928 12.522173 2.84343.683658 6.102369.004954 9.068638 0 7.124652-.011559 14.317732-.279903 21.434964.032202 17.817402.781913 36.381729 3.63214 53.58741 8.350042 22.029372 6.040631 41.432961 17.928687 62.656049 25.945156 22.389644 8.456554 44.67706 11.084675 68.427 11.084675 11.96813 0 23.845573-.035504 35.450133-3.302696-6.056202-3.225083-14.72582-2.619864-21.434964-3.963236-14.556814-2.915455-28.868774-6.474936-42.869928-11.470264-10.304996-3.676672-20.230803-8.214291-30.11097-12.848661l-6.348531-2.985046c-9.1705-4.309263-18.363277-8.560752-27.845391-12.142608-24.932161-9.418465-52.560181-14.071964-79.144482-11.221737zm22.259385-62.614168c-29.163917 0-58.660076 5.137344-84.915434 18.369597-6.361238 3.206092-12.407546 7.02566-18.137277 11.258891-1.746125 1.290529-4.841829 2.948483-5.487351 5.191839-.654591 2.275558 1.685942 4.182039 3.014086 5.637703 6.562396-3.497556 12.797498-7.199878 19.78612-9.855246 45.19892-17.169893 99.992458-13.570779 145.098218 2.172348 22.494346 7.851335 43.219483 19.592421 65.129314 28.800338 24.503461 10.297807 49.53043 16.975034 75.846795 20.399104 31.04195 4.037546 66.433549.7654 94.808495-13.242161 9.970556-4.921843 23.814245-12.422267 28.030337-23.320339-5.207047.454947-9.892236 2.685918-14.83959 4.224149-7.866632 2.445646-15.827248 4.51974-23.908229 6.138887-27.388113 5.486604-56.512458 6.619429-84.091013 1.639788-25.991939-4.693152-50.142596-14.119246-74.179513-24.03502l-3.068058-1.268177c-2.045137-.846788-4.089983-1.695816-6.135603-2.544467l-3.069142-1.272366c-12.279956-5.085721-24.606928-10.110797-37.210937-14.51024-24.485325-8.546552-50.726667-13.784628-76.671218-13.784628zm51.114145-447.9909432c-34.959602 7.7225298-66.276908 22.7605319-96.457338 41.7180089-17.521434 11.0054099-34.281927 22.2799893-49.465301 36.4444283-22.5792616 21.065423-39.8360564 46.668751-54.8866988 73.411509-15.507372 27.55357-25.4498976 59.665686-30.2554517 90.824149-4.7140432 30.568106-5.4906485 62.70747-.0906864 93.301172 6.7503648 38.248526 19.5989769 74.140579 39.8896436 107.337631 6.8187918-3.184625 11.659796-10.445603 17.3128555-15.336896 11.4149428-9.875888 23.3995608-19.029311 36.2745548-26.928535 4.765981-2.923712 9.662222-5.194315 14.83959-7.275014 1.953055-.785216 5.14604-1.502727 6.06527-3.647828 1.460876-3.406732-1.240754-9.335897-1.704904-12.865654-1.324845-10.095517-2.124534-20.362774-1.874735-30.549941.725492-29.668947 6.269727-59.751557 16.825623-87.521453 7.954845-20.924233 20.10682-39.922168 34.502872-56.971512 4.884699-5.785498 10.077731-11.170545 15.437296-16.512656 3.167428-3.157378 7.098271-5.858983 9.068639-9.908915-10.336599.006606-20.674847 2.987289-30.503603 6.013385-21.174447 6.519522-41.801477 16.19312-59.358362 29.841512-8.008432 6.226409-13.873368 14.387371-21.44733 20.939921-2.32322 2.010516-6.484901 4.704691-9.695199 3.187928-4.8500728-2.29042-4.1014979-11.835213-4.6571581-16.222019-2.1369011-16.873476 4.2548401-38.216325 12.3778671-52.843142 13.039878-23.479694 37.150915-43.528712 65.467327-42.82854 12.228647.302197 22.934587 4.551115 34.625711 7.324555-2.964621-4.211764-6.939158-7.28162-10.717482-10.733763-9.257431-8.459031-19.382979-16.184864-30.503603-22.028985-4.474136-2.350694-9.291232-3.77911-14.015169-5.506421-2.375159-.867783-5.36616-2.062533-6.259834-4.702213-1.654614-4.888817 7.148561-9.416813 10.381943-11.478522 12.499882-7.969406 27.826705-14.525258 42.869928-14.894334 23.509209-.577147 46.479246 12.467678 56.162903 34.665926 3.404469 7.803171 4.411273 16.054969 5.079109 24.382907l.121749 1.56229.174325 2.345587c.01913.260708.038244.521433.057403.782164l.11601 1.56437.120128 1.563971c7.38352-6.019164 12.576553-14.876995 19.78612-21.323859 16.861073-15.07846 39.936636-21.7722 61.831627-14.984333 19.786945 6.133107 36.984382 19.788105 47.105807 37.959541 2.648042 4.754231 10.035685 16.373942 4.698379 21.109183-4.177345 3.707277-9.475079.818243-13.880788-.719162-3.33605-1.16376-6.782939-1.90214-10.241828-2.585698l-1.887262-.369639c-.629089-.122886-1.257979-.246187-1.886079-.372129-11.980496-2.401886-25.91652-2.152533-37.923398-.041284-7.762754 1.364839-15.349083 4.127545-23.083807 5.271929v1.651348c21.149714.175043 41.608563 12.240618 52.043268 30.549941 4.323267 7.585468 6.482428 16.267431 8.138691 24.770223 2.047864 10.50918.608423 21.958802-2.263037 32.201289-.962925 3.433979-2.710699 9.255807-6.817143 10.046802-2.902789.558982-5.36781-2.330878-7.024898-4.279468-4.343878-5.10762-8.475879-9.96341-13.573278-14.374161-12.895604-11.157333-26.530715-21.449361-40.396663-31.373138-7.362086-5.269452-15.425755-12.12007-23.908229-15.340199 2.385052 5.745041 4.721463 11.086326 5.532694 17.339156 2.385876 18.392716-5.314223 35.704625-16.87179 49.540445-3.526876 4.222498-7.29943 8.475545-11.744712 11.755948-1.843407 1.360711-4.156734 3.137561-6.595373 2.752797-7.645687-1.207961-8.555849-12.73272-9.728176-18.637115-3.970415-19.998652-2.375984-39.861068 3.132802-59.448534-4.901187 2.485279-8.443727 7.923994-11.521293 12.385111-6.770975 9.816439-12.645804 20.199291-16.858599 31.375615-16.777806 44.519521-16.616219 96.664142 5.118834 139.523233 2.427098 4.786433 6.110614 4.144058 10.894733 4.144058.720854 0 1.44257-.004515 2.164851-.010924l2.168232-.022283c4.338648-.045438 8.686803-.064635 12.979772.508795 2.227588.297243 5.320818.032202 7.084256 1.673642 2.111344 1.966755.986008 5.338808.4996 7.758859-1.358647 6.765574-1.812904 12.914369-1.812904 19.816178 9.02412-1.398692 11.525415-15.866153 14.724172-23.118874 3.624982-8.216283 7.313444-16.440823 10.667192-24.770223 1.648843-4.093692 3.854171-8.671229 3.275427-13.210785-.649644-5.10184-4.335633-10.510831-6.904531-14.862134-4.86244-8.234447-10.389363-16.70834-13.969002-25.595896-2.861567-7.104926-.197036-15.983399 7.871579-18.521521 4.450228-1.400344 9.198073 1.345848 12.094266 4.562675 6.07269 6.74328 9.992815 16.777697 14.401823 24.692609l34.394873 61.925556c2.920926 5.243856 5.848447 10.481933 8.836976 15.687808 1.165732 2.031158 2.352075 5.167068 4.740424 6.0332 2.127008.77118 5.033095-.325315 7.148561-.748886 5.492297-1.099798 10.97635-2.287117 16.488434-3.28288 6.605266-1.193099 16.673928-.969342 21.434964-6.129805-6.963066-2.205375-15.011895-2.074919-22.259386-1.577863-4.352947.298894-9.178287 1.856116-13.178381-.686135-5.953149-3.783239-9.910373-12.522173-13.552668-18.377854-8.980425-14.439388-17.441465-29.095929-26.041008-43.760726l-1.376261-2.335014-2.765943-4.665258c-1.380597-2.334387-2.750786-4.67476-4.079753-7.036188-1.02723-1.826391-2.549937-4.233231-1.078344-6.24705 1.545791-2.114476 4.91472-2.239146 7.956473-2.243117l.603351.000261c1.195428.001526 2.315572.002427 3.222811-.11692 12.27399-1.615019 24.718635-2.952611 37.098976-2.952611-.963749-3.352237-3.719791-7.141255-2.838484-10.73046 1.972017-8.030506 13.526287-10.543033 18.899867-4.780653 3.60767 3.868283 5.704174 9.192229 8.051303 13.859765 3.097352 6.162006 6.624228 12.118418 9.940876 18.16483 5.805578 10.585967 12.146205 20.881297 18.116667 31.375615.49237.865561.999687 1.726685 1.512269 2.587098l.771613 1.290552c2.577138 4.303168 5.164895 8.635123 6.553094 13.461506-20.735854-.9487-36.30176-25.018751-45.343193-41.283704-.721369 2.604176.450959 4.928448 1.388326 7.431066 1.948109 5.197619 4.276275 10.147535 7.20627 14.862134 4.184765 6.732546 8.982075 13.665732 15.313633 18.553722 11.236043 8.673707 26.05255 8.721596 39.572241 7.794364 8.669619-.595311 19.50252-4.542034 28.030338-1.864372 8.513803 2.673532 11.940924 12.063098 6.884745 19.276187-3.787393 5.403211-8.842747 7.443452-15.128962 8.257566 4.445282 9.53571 10.268996 18.385285 14.490036 28.072919 1.758491 4.035895 3.59118 10.22102 7.8048 12.350433 2.805507 1.416857 6.824562.09743 9.85761.034678-3.043765-8.053625-8.742992-14.887729-11.541904-23.118874 8.533589.390544 16.786875 4.843404 24.732651 7.685374 15.630376 5.590144 31.063836 11.701854 46.475333 17.86913l7.112077 2.848685c6.338978 2.538947 12.71588 5.052299 18.961699 7.812528 2.285297 1.009799 5.449427 3.370401 7.975455 1.917215 2.061054-1.186494 3.394144-4.015253 4.665403-5.931643 3.55573-5.361927 6.775921-10.928622 9.965609-16.513481 12.774414-22.36586 22.143967-46.872692 28.402976-71.833646 20.645168-82.323009 2.934117-173.156241-46.677107-241.922507-19.061454-26.420745-43.033164-49.262193-69.46165-68.1783861-66.13923-47.336721-152.911262-66.294198-232.486917-48.7172481zm135.205158 410.5292842c-17.532977 4.570931-35.601827 8.714164-53.58741 11.040088 2.365265 8.052799 8.145286 15.885969 12.376218 23.118874 1.635653 2.796558 3.3859 6.541816 6.618457 7.755557 3.651364 1.370619 8.063669-.853747 11.508927-1.975838-1.595256-4.364513-4.279573-8.292245-6.476657-12.385112-.905215-1.687677-2.305907-3.685809-1.559805-5.68972 1.410585-3.786541 7.266452-3.563609 10.509727-4.221671 8.54678-1.733916 17.004522-3.898008 25.557073-5.611281 3.150939-.631641 7.538512-2.342438 10.705115-1.285575 2.371037.791232 3.800147 2.744743 5.152304 4.781948l.606196.918752c.80912 1.222827 1.637246 2.41754 2.671212 3.351165 3.457625 3.121874 8.628398 3.60159 13.017619 4.453686-2.678546-6.027421-7.130424-11.301001-9.984571-17.339156-1.659561-3.511592-3.023155-8.677834-6.656381-10.707341-5.005064-2.795733-15.341663 2.461334-20.458024 3.795624zm-110.472507-40.151706c-.825246 10.467897-4.036369 18.984725-9.068639 28.072919 5.76683.729896 11.649079.989984 17.312856 2.39363 4.244947 1.051908 8.156828 3.058296 12.366325 4.211763-2.250671-6.157877-6.426367-11.651913-9.661398-17.339156-3.266358-5.740912-6.189758-12.717032-10.949144-17.339156z"
                            fill="currentColor"
                            transform="translate(.9778)"
                          />
                        </svg>
                        {/* Solid Start */}
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          width="15"
                          height="15"
                          viewBox="0 0 128 128"
                          className="text-[#2C4F7C] dark:text-[#66AAEE] opacity-90 transition-all duration-300 group-hover/card:opacity-100 group-hover/card:animate-[icon-bounce_0.4s_ease-out_0.2s]"
                        >
                          <path
                            fill="currentColor"
                            d="M61.832 4.744c-3.205.058-6.37.395-9.45 1.07l-2.402.803c-4.806 1.603-8.813 4.005-11.216 7.21l-1.602 2.404l-12.017 20.828l.166.031c-4.785 5.823-5.007 14.07-.166 21.6c1.804 2.345 4.073 4.431 6.634 6.234l-15.445 4.982L.311 97.946s42.46 32.044 75.306 24.033l2.403-.801c5.322-1.565 9.292-4.48 11.683-8.068l.334.056l16.022-28.84c3.204-5.608 2.404-12.016-1.602-18.425a36 36 0 0 0-7.059-6.643l15.872-5.375l14.42-24.033S92.817 4.19 61.831 4.744z"
                          />
                        </svg>
                        {/* Expo */}
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          width="15"
                          height="15"
                          viewBox="0 0 32 32"
                          className="text-neutral-800 dark:text-neutral-200 opacity-90 transition-all duration-300 group-hover/card:opacity-100 group-hover/card:animate-[icon-bounce_0.4s_ease-out_0.25s]"
                        >
                          <path
                            fill="currentColor"
                            d="M24.292 15.547a3.93 3.93 0 0 0 4.115-3.145a2.57 2.57 0 0 0-2.161-1.177c-2.272-.052-3.491 2.651-1.953 4.323zm-9.177-10.85l5.359-3.104L18.766.63l-7.391 4.281l.589.328l1.119.629l2.032-1.176zm6.046-3.39c.089.027.161.1.188.188l2.484 7.593a.285.285 0 0 1-.125.344a5.06 5.06 0 0 0-2.317 5.693a5.066 5.066 0 0 0 5.401 3.703a.3.3 0 0 1 .307.203l2.563 7.803a.3.3 0 0 1-.125.344l-7.859 4.771a.3.3 0 0 1-.131.036a.26.26 0 0 1-.203-.041l-2.765-1.797a.3.3 0 0 1-.109-.129l-5.396-12.896l-8.219 4.875c-.016.011-.037.021-.052.032a.3.3 0 0 1-.261-.021l-1.859-1.093a.283.283 0 0 1-.115-.381l7.953-15.749a.27.27 0 0 1 .135-.131L18.615.045a.29.29 0 0 1 .292-.005zm-8.322 5.1l-1.932-1.089l-7.693 15.229l1.396.823l6.631-9.015a.28.28 0 0 1 .271-.12a.29.29 0 0 1 .235.177l7.228 17.296l1.933 1.251l-8.063-24.552zm13.406 10.557c-2.256 0-3.787-2.292-2.923-4.376c.86-2.083 3.563-2.619 5.156-1.025c.595.593.928 1.396.928 2.235a3.16 3.16 0 0 1-3.161 3.167z"
                          />
                        </svg>
                        {/* +14 more */}
                        <div className="flex items-center justify-center size-[20px] border border-dashed border-foreground/[0.1] text-foreground/35 dark:text-foreground/20 transition-all duration-300 group-hover/card:text-foreground/60 dark:group-hover/card:text-foreground/40 group-hover/card:border-foreground/20 group-hover/card:animate-[icon-bounce_0.4s_ease-out_0.3s]">
                          <span className="text-[7px] font-mono leading-none">+14</span>
                        </div>
                      </div>
                    )}
                  </motion.div>
                </Link>
              ))}
              {/* + marks at grid intersections */}
              <span className="hidden md:block absolute top-1/3 left-1/3 -translate-x-1/2 -translate-y-1/2 font-mono  -mt-[1px] -ml-[.5px] text-[10px] text-foreground/35 dark:text-foreground/20 select-none z-10">
                +
              </span>
              <span className="hidden md:block absolute top-1/3 left-2/3 -translate-x-1/2 -translate-y-1/2 font-mono -mt-[1px] -ml-[.5px] text-[10px] text-foreground/35 dark:text-foreground/20 select-none z-10">
                +
              </span>
              <span className="hidden md:block absolute top-2/3 left-1/3 -translate-x-1/2 -translate-y-1/2 font-mono  -mt-[1px] -ml-[.5px] text-[10px] text-foreground/35 dark:text-foreground/20 select-none z-10">
                +
              </span>
              <span className="hidden md:block absolute top-2/3 left-2/3 -translate-x-1/2 -translate-y-1/2 font-mono  -mt-[1px] -ml-[.5px] text-[10px] text-foreground/35 dark:text-foreground/20 select-none z-10">
                +
              </span>
            </div>

            <div className="my-4">
              <div className="flex items-center gap-4">
                <span className="text-lg font-medium text-foreground/90 dark:text-foreground/80 tracking-tight shrink-0">
                  Framework
                </span>
                <div className="flex-1 border-t border-foreground/10"></div>
              </div>
              <p className="text-[15px] sm:text-base text-foreground/50 mt-1">
                A complete agent runtime for Python and TypeScript.
              </p>
            </div>

            <div className="mt-8 mb-10">
              <div className="border-r border-foreground/[0.1] bg-foreground/[0.01] overflow-hidden">
                <div className="flex flex-col lg:flex-row">
                  <div className="min-w-0 flex-1 min-h-[320px] sm:min-h-[360px] lg:h-[400px] overflow-hidden">
                    <AnimatePresence mode="wait" initial={false}>
                      <motion.div
                        key={frameworkTab}
                        initial={{ opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -4 }}
                        transition={{ duration: 0.2, ease: "easeOut" }}
                        className="pr-3 sm:pr-5 pb-5 h-full"
                      >
                        {frameworkTab === "loop" && <AgentLoopTabs />}
                        {frameworkTab === "providers" && <ProvidersSection />}
                        {frameworkTab === "tools" && <ToolsSection />}
                        {frameworkTab === "integrations" && <IntegrationsSection />}
                      </motion.div>
                    </AnimatePresence>
                  </div>

                  <div className="flex flex-row lg:flex-col lg:w-56 lg:shrink-0 border-t lg:border-t-0 lg:border-l border-foreground/[0.1] bg-neutral-50 dark:bg-black overflow-x-auto lg:overflow-visible">
                    {[
                      { id: "loop", label: "Agent Loop" },
                      { id: "providers", label: "Pluggable Providers" },
                      { id: "tools", label: "Tool Registry" },
                      { id: "integrations", label: "Integrations" },
                    ].map((tab) => (
                      <button
                        key={tab.id}
                        type="button"
                        onClick={() =>
                          setFrameworkTab(tab.id as "loop" | "providers" | "tools" | "integrations")
                        }
                        className={cn(
                          "relative flex-1 lg:flex-none text-left px-3 sm:px-4 py-2.5 sm:py-3 text-[10px] sm:text-[11px] lg:text-xs font-mono tracking-wider uppercase transition-colors border-r lg:border-r-0 lg:border-b last:border-r-0 lg:last:border-b-0 border-foreground/[0.08] whitespace-nowrap lg:whitespace-normal",
                          frameworkTab === tab.id
                            ? "text-foreground/85 bg-foreground/[0.04]"
                            : "text-foreground/45 hover:text-foreground/70",
                        )}
                      >
                        {tab.label}
                        {frameworkTab === tab.id && (
                          <span className="absolute inset-y-0 right-0 w-[1.5px] bg-foreground/65 hidden lg:block" />
                        )}
                      </button>
                    ))}
                    <div className="hidden lg:flex flex-1 items-end p-4">
                      <p className="text-[13px] leading-relaxed text-foreground/60 dark:text-foreground/50">
                        {frameworkTab === "loop" &&
                          "An event-sourced ReAct loop. Replay session state, call the provider, run tool calls, repeat until done."}
                        {frameworkTab === "providers" &&
                          "Swap LLM providers behind one interface. OpenAI, Kimi, and Gemini, with no lock-in."}
                        {frameworkTab === "tools" &&
                          "Register any function as a tool. One provider-neutral payload, translated per provider."}
                        {frameworkTab === "integrations" &&
                          "Works with every major framework. Drop the agent route handler into your stack."}
                      </p>
                    </div>
                  </div>
                </div>
              </div>

              <div className="mt-8">
                <CapabilitiesMarquee />
              </div>
            </div>
            <ReadmeFooter stats={stats} />
          </motion.article>
        </div>
      </div>
    </motion.div>
  );
}
