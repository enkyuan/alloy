"use client";

import { AnimatePresence, LazyMotion, domAnimation, m } from "motion/react";
import Link from "next/link";
import { useState } from "react";
import { cn } from "@lib/utils";
import { AgentLoopTabs } from "../features/agent-loop";
import { CapabilitiesMarquee } from "../features/capabilities-marquee";
import { ProvidersSection, ProviderLogosGrid } from "../providers/section";
import { ToolsSection } from "../tools/section";
import { FeaturesGridMarks } from "../features/grid-marks";
import { InstallBlock } from "../install/block";
import { ReadmeFooter, type CommunityHeroStats } from "../footer/readme-stats";
import { ArrowUpRightIcon } from "@components/docs/icons/ui";
import { PythonLogo, TypeScriptLogo } from "@components/docs/icons/languages";

const featureCards = [
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
    label: "Modalities",
    headline: "Text and voice.",
    desc: "Streaming text agents or full voice loops with STT/TTS — same runtime core.",
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
];

const runtimeTabs = [
  { id: "loop", label: "Agent Loop" },
  { id: "tools", label: "Tool Registry" },
  { id: "providers", label: "Pluggable Providers" },
] as const;

type RuntimeTabId = (typeof runtimeTabs)[number]["id"];

const runtimeTabDescriptions: Record<RuntimeTabId, string> = {
  loop: "An event-sourced ReAct loop. Replay session state, call the provider, run tool calls, repeat until done.",
  providers:
    "Swap LLM providers behind one interface. OpenAI, Kimi, Gemini, and more, with no lock-in.",
  tools: "Register any function as a tool. One provider-neutral payload, translated per provider.",
};

export function HeroReadMe({ stats }: { stats: CommunityHeroStats }) {
  const [frameworkTab, setFrameworkTab] = useState<RuntimeTabId>("loop");

  return (
    <LazyMotion features={domAnimation}>
      <m.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.5, delay: 0.15, ease: "easeOut" }}
        className="flex flex-col w-full"
      >
        {/* Markdown content */}
        <div className="flex-1 overflow-x-hidden no-scrollbar">
          <div className="p-5 lg:px-8 lg:pt-20">
            <m.article
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

              <div
                id="features-grid"
                className="relative grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 mb-2 border border-foreground/[0.08] overflow-hidden"
              >
                {featureCards.map((feature, i) => {
                  const href = "href" in feature ? feature.href : "#";
                  return (
                    <Link key={feature.label} href={href} className="contents">
                      <m.div
                        whileHover={{
                          y: -2,
                          transition: { duration: 0.2, ease: "easeOut" },
                        }}
                        className={cn(
                          "group/card relative p-4 lg:p-5 border-foreground/[0.08] min-h-[100px] transition-all duration-200 hover:bg-foreground/[0.02] hover:shadow-[inset_0_1px_0_0_rgba(128,128,128,0.1)] hover:z-10",
                          i < 8 && "border-b",
                          i >= 6 && "md:border-b-0",
                          i % 2 === 0 && i < 8 && "sm:border-r",
                          i % 3 === 2 && "md:border-r-0",
                          i % 2 !== 0 && i % 3 !== 2 && "md:border-r",
                        )}
                      >
                        {/* Arrow icon — top right, visible on hover */}
                        <span className="absolute top-3 right-3 lg:top-4 lg:right-4 opacity-0 -translate-y-0.5 group-hover/card:opacity-100 group-hover/card:translate-y-0 transition-all duration-200">
                          <ArrowUpRightIcon
                            size={16}
                            className="text-foreground/40 dark:text-foreground/50"
                          />
                        </span>
                        <div className="mb-1">
                          <div className="text-[11px] font-mono text-violet-600 dark:text-violet-400 tracking-wider transition-colors duration-200 group-hover/card:text-violet-500 dark:group-hover/card:text-violet-300 font-semibold">
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
                            <PythonLogo
                              size={15}
                              className="text-[#3776AB] opacity-90 transition-all duration-300 group-hover/card:opacity-100 group-hover/card:animate-[icon-bounce_0.4s_ease-out_0s]"
                            />
                            <TypeScriptLogo
                              size={15}
                              className="text-[#3178C6] opacity-90 transition-all duration-300 group-hover/card:opacity-100 group-hover/card:animate-[icon-bounce_0.4s_ease-out_0.05s]"
                            />
                          </div>
                        )}
                      </m.div>
                    </Link>
                  );
                })}
                {/* + marks rendered by FeaturesGridMarks — positions measured from actual card rects */}
                <FeaturesGridMarks />
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
                        <m.div
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
                        </m.div>
                      </AnimatePresence>
                    </div>

                    <div className="flex flex-row lg:flex-col lg:w-56 lg:shrink-0 border-t lg:border-t-0 lg:border-l border-foreground/[0.1] bg-neutral-50 dark:bg-black overflow-x-auto lg:overflow-visible">
                      {runtimeTabs.map((tab) => (
                        <button
                          key={tab.id}
                          type="button"
                          onClick={() => setFrameworkTab(tab.id)}
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
                      {frameworkTab === "providers" ? (
                        <div className="hidden lg:flex flex-col flex-1">
                          <ProviderLogosGrid exclude={["OpenAI"]} />
                          <div className="flex-1 flex items-end p-4">
                            <p className="text-[13px] leading-relaxed text-foreground/60 dark:text-foreground/50">
                              {runtimeTabDescriptions.providers}
                            </p>
                          </div>
                        </div>
                      ) : (
                        <div className="hidden lg:flex flex-1 items-end p-4">
                          <p className="text-[13px] leading-relaxed text-foreground/60 dark:text-foreground/50">
                            {runtimeTabDescriptions[frameworkTab]}
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                <div className="mt-8">
                  <CapabilitiesMarquee />
                </div>
              </div>
              <ReadmeFooter stats={stats} />
            </m.article>
          </div>
        </div>
      </m.div>
    </LazyMotion>
  );
}
