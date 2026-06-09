"use client";

import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { RiAddLine, RiNpmjsFill } from "../icons/remix";
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
          Ship agents in minutes, not months.
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
            href="https://github.com/enkyuan/alloy"
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
            <span className="relative">GitHub </span>
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
              . Build text, voice, and multi-modal agents with a tool registry and pluggable LLM
              providers, in one{" "}
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

            <div className="relative mb-2">
              {/* + marks at the four outer corners — on outer wrapper so overflow-hidden on the grid doesn't clip them */}
              {(
                [
                  ["0%", "0%"],
                  ["100%", "0%"],
                  ["0%", "100%"],
                  ["100%", "100%"],
                ] as [string, string][]
              ).map(([left, top]) => (
                <RiAddLine
                  key={`${left}-${top}`}
                  className="hidden md:block absolute size-[9px] text-foreground/30 dark:text-foreground/20 select-none z-20 pointer-events-none -translate-x-1/2 -translate-y-1/2"
                  style={{ left, top }}
                />
              ))}
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 border border-foreground/[0.08] overflow-hidden">
                {[
                  {
                    label: "Framework Agnostic",
                    headline: "Works with your stack.",
                    desc: "Python and TypeScript, with route handlers for every major framework.",
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
                          {/* Python */}
                          <svg
                            xmlns="http://www.w3.org/2000/svg"
                            width="15"
                            height="15"
                            viewBox="0 0 24 24"
                            className="text-[#3776AB] opacity-90 transition-all duration-300 group-hover/card:opacity-100 group-hover/card:animate-[icon-bounce_0.4s_ease-out_0s]"
                          >
                            <path
                              fill="currentColor"
                              d="M11.914 0C5.82 0 6.2 2.656 6.2 2.656l.007 2.752h5.814v.826H3.9S0 5.789 0 11.969c0 6.18 3.403 5.96 3.403 5.96h2.031v-2.867s-.109-3.408 3.35-3.408h5.762s3.239.052 3.239-3.13V3.147S18.28 0 11.914 0m-3.21 1.818a1.049 1.049 0 1 1 0 2.098a1.049 1.049 0 0 1 0-2.098"
                            />
                            <path
                              fill="currentColor"
                              d="M12.086 24c6.094 0 5.714-2.656 5.714-2.656l-.007-2.752h-5.814v-.826h8.121S24 18.211 24 12.031c0-6.18-3.403-5.96-3.403-5.96h-2.031v2.867s.109 3.408-3.35 3.408H9.454s-3.239-.052-3.239 3.13v5.377S5.72 24 12.086 24m3.21-1.818a1.049 1.049 0 1 1 0-2.098a1.049 1.049 0 0 1 0 2.098"
                            />
                          </svg>
                          {/* TypeScript */}
                          <svg
                            xmlns="http://www.w3.org/2000/svg"
                            width="15"
                            height="15"
                            viewBox="0 0 24 24"
                            className="text-[#3178C6] opacity-90 transition-all duration-300 group-hover/card:opacity-100 group-hover/card:animate-[icon-bounce_0.4s_ease-out_0.05s]"
                          >
                            <path
                              fill="currentColor"
                              d="M1.125 0C.502 0 0 .502 0 1.125v21.75C0 23.498.502 24 1.125 24h21.75c.623 0 1.125-.502 1.125-1.125V1.125C24 .502 23.498 0 22.875 0zm17.363 9.75c.612 0 1.154.037 1.627.111a6.38 6.38 0 0 1 1.306.34v2.458a3.95 3.95 0 0 0-.643-.361a5.093 5.093 0 0 0-.717-.26a5.453 5.453 0 0 0-1.426-.2c-.3 0-.573.028-.819.086a2.1 2.1 0 0 0-.623.242c-.17.104-.3.229-.393.374a.888.888 0 0 0-.14.49c0 .196.053.373.156.529.104.156.252.304.443.444s.423.276.696.41c.273.135.582.274.926.416.47.197.892.407 1.266.628.374.222.695.473.963.753.268.279.472.598.614.957.142.359.214.776.214 1.253 0 .657-.125 1.21-.373 1.656a3.033 3.033 0 0 1-1.012 1.085a4.38 4.38 0 0 1-1.487.596c-.566.12-1.163.18-1.79.18a9.916 9.916 0 0 1-1.84-.164a5.544 5.544 0 0 1-1.512-.493v-2.63a5.033 5.033 0 0 0 3.237 1.2c.333 0 .624-.03.872-.09.249-.06.456-.144.623-.25.166-.108.29-.234.373-.38a1.023 1.023 0 0 0-.074-1.089a2.12 2.12 0 0 0-.537-.5a5.597 5.597 0 0 0-.807-.444a27.72 27.72 0 0 0-1.007-.436c-.918-.383-1.602-.852-2.053-1.405-.45-.553-.676-1.222-.676-2.005 0-.614.123-1.141.369-1.582.246-.441.58-.804 1.004-1.089a4.494 4.494 0 0 1 1.47-.629a7.536 7.536 0 0 1 1.77-.201zm-15.113.188h9.563v2.166H9.506v9.646H6.789v-9.646H3.375z"
                            />
                          </svg>
                        </div>
                      )}
                    </motion.div>
                  </Link>
                ))}
              </div>
            </div>

            <div className="my-4">
              <div className="flex items-center gap-4">
                <span className="text-lg font-medium text-foreground/90 dark:text-foreground/80 tracking-tight shrink-0">
                  Runtime
                </span>
                <div className="flex-1 border-t border-foreground/10"></div>
              </div>
              <p className="text-[15px] sm:text-base text-foreground/50 mt-1">
                Event-sourced agent loop, tool registry, and pluggable providers.
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
