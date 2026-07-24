"use client";

import { AnimatePresence, LazyMotion, domAnimation, m } from "motion/react";
import { useEffect, useReducer, useRef, useState } from "react";
import { cn } from "@lib/utils";
import { CopyIcon, CheckIcon, EyeIcon } from "@components/docs/icons/ui";
import { McpDropdown } from "../install/mcp-dropdown";
import { PromptDialog } from "../install/prompt-dialog";

const aiPromptText = `Set up a TypeScript agent in my project using kaji-sdk.

1. Install kaji-sdk@0.2.0-beta.2, zod@>=4.3 <5, and openai.

2. Create agent.ts with AgentBuilder and the OpenAI provider. Use the default
   in-memory event store/committer; do not add a database or server.

3. Add one functionTool with an explicit Zod schema and an explicit risk.
   Pass a stable principalId and deadlineAfter(...) to turn().

4. Run one runtime.turn(...) call and print its text, sessionId, and turnId.

5. Read OPENAI_API_KEY from the environment. Do not invent a Kaji-specific
   provider key or log credentials, prompts, tool arguments, or raw errors.

Use only public kaji-sdk exports and follow https://kaji.dev/docs/getting-started.`;

type UIState = { copied: boolean; pmOpen: boolean; promptOpen: boolean };
type UIAction =
  | { type: "copy" }
  | { type: "copy_reset" }
  | { type: "pm_toggle" }
  | { type: "pm_close" }
  | { type: "prompt_open" }
  | { type: "prompt_close" }
  | { type: "reset" };

function uiReducer(state: UIState, action: UIAction): UIState {
  switch (action.type) {
    case "copy":
      return { ...state, copied: true, pmOpen: false };
    case "copy_reset":
      return { ...state, copied: false };
    case "pm_toggle":
      return { ...state, pmOpen: !state.pmOpen };
    case "pm_close":
      return { ...state, pmOpen: false };
    case "prompt_open":
      return { ...state, promptOpen: true };
    case "prompt_close":
      return { ...state, promptOpen: false };
    case "reset":
      return { copied: false, pmOpen: false, promptOpen: false };
    default:
      return state;
  }
}

export function InstallBlock() {
  const [mode, setMode] = useState<"install" | "cli" | "prompt" | "mcp">("cli");
  const [ui, dispatch] = useReducer(uiReducer, { copied: false, pmOpen: false, promptOpen: false });
  const contentRef = useRef<HTMLDivElement>(null);
  const [contentHeight, setContentHeight] = useState<number | "auto">("auto");
  const [animationDone, setAnimationDone] = useState(true);

  const { copied, pmOpen, promptOpen } = ui;

  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      setContentHeight(el.offsetHeight);
    });
    // react-doctor-disable-next-line no-initialize-state, react-doctor/no-initialize-state
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const overflow: "hidden" | "visible" = pmOpen || animationDone ? "visible" : "hidden";

  const copy = (text: string) => {
    navigator.clipboard.writeText(text);
    dispatch({ type: "copy" });
    setTimeout(() => dispatch({ type: "copy_reset" }), 1500);
  };

  return (
    <LazyMotion features={domAnimation}>
      <div className="mb-6 rounded-md border border-foreground/[0.1] relative">
        {/* Tabs */}
        <div className="flex items-center border-b border-foreground/[0.1]">
          {(["cli", "install", "prompt", "mcp"] as const).map((id) => (
            <button
              type="button"
              key={id}
              onClick={() => {
                setMode(id);
                dispatch({ type: "reset" });
                setAnimationDone(false);
              }}
              className={cn(
                "px-4 py-2 text-[12px] transition-colors duration-150 relative capitalize",
                mode === id
                  ? "text-neutral-800 dark:text-neutral-200"
                  : "text-neutral-400 dark:text-neutral-500 hover:text-neutral-600 dark:hover:text-neutral-400",
              )}
            >
              {id === "mcp" ? "MCP" : id === "prompt" ? "Prompt" : id === "cli" ? "CLI" : "Install"}
              {mode === id && (
                <div className="absolute bottom-0 left-4 right-4 h-[1.5px] bg-neutral-600 dark:bg-neutral-400" />
              )}
            </button>
          ))}
        </div>

        {/* Content */}
        <m.div
          animate={{ height: contentHeight }}
          initial={false}
          transition={{ duration: 0.3, ease: [0.25, 0.1, 0.25, 1] }}
          onAnimationComplete={() => setAnimationDone(true)}
          style={{ overflow }}
        >
          <div ref={contentRef}>
            <AnimatePresence mode="wait" initial={false}>
              <div>
                {mode === "install" ? (
                  <div className="flex items-center justify-between bg-neutral-100/50 dark:bg-[#050505] px-4 py-3">
                    <code
                      className="text-[13px]"
                      style={{ fontFamily: "var(--font-geist-pixel-square)" }}
                    >
                      <span className="text-purple-600/90 dark:text-purple-400/90">pip</span>{" "}
                      <span className="text-neutral-700 dark:text-neutral-300">
                        install kaji-sdk==0.2.0b1
                      </span>
                    </code>
                    <button
                      type="button"
                      onClick={() => copy("pip install kaji-sdk==0.2.0b1")}
                      className="text-neutral-400 dark:text-neutral-500 hover:text-neutral-600 dark:hover:text-neutral-300 transition-colors p-1"
                      aria-label="Copy command"
                    >
                      {copied ? <CheckIcon size={16} /> : <CopyIcon size={16} />}
                    </button>
                  </div>
                ) : mode === "cli" ? (
                  <div className="flex items-center justify-between bg-neutral-100/50 dark:bg-[#050505] px-4 py-3">
                    <code
                      className="text-[13px]"
                      style={{ fontFamily: "var(--font-geist-pixel-square)" }}
                    >
                      <span className="text-purple-600/90 dark:text-purple-400/90">bunx</span>{" "}
                      <span className="text-neutral-700 dark:text-neutral-300">
                        --package=kaji-sdk@0.2.0-beta.2 kaji init ./my-agent --provider openai --yes
                      </span>
                    </code>
                    <button
                      type="button"
                      onClick={() =>
                        copy(
                          "bunx --package=kaji-sdk@0.2.0-beta.2 kaji init ./my-agent --provider openai --yes",
                        )
                      }
                      className="text-neutral-400 dark:text-neutral-500 hover:text-neutral-600 dark:hover:text-neutral-300 transition-colors p-1"
                      aria-label="Copy command"
                    >
                      {copied ? <CheckIcon size={16} /> : <CopyIcon size={16} />}
                    </button>
                  </div>
                ) : mode === "mcp" ? (
                  <div className="flex items-center justify-between bg-neutral-100/50 dark:bg-[#050505] px-4 py-3">
                    <code
                      className="text-[13px] truncate"
                      style={{ fontFamily: "var(--font-geist-pixel-square)" }}
                    >
                      <span className="text-neutral-700 dark:text-neutral-300">
                        MCP setup coming soon
                      </span>
                    </code>
                    <McpDropdown
                      copied={copied}
                      open={pmOpen}
                      onToggle={() => {
                        if (!copied) dispatch({ type: "pm_toggle" });
                      }}
                      onClose={() => dispatch({ type: "pm_close" })}
                      onCopy={copy}
                    />
                  </div>
                ) : (
                  <div className="bg-neutral-100/50 dark:bg-[#050505] px-5 py-4">
                    <p className="text-[13px] font-medium text-neutral-700 dark:text-neutral-200 leading-relaxed">
                      Set up a TypeScript agent using kaji-sdk.
                    </p>
                    <div className="relative mt-1.5">
                      <p className="text-[11px] text-neutral-400 dark:text-neutral-500 leading-relaxed line-clamp-2">
                        Install kaji-sdk. Create agent.ts with the{" "}
                        <code className="text-neutral-500 dark:text-neutral-400">
                          agent runtime
                        </code>
                        , register one risk-classified tool, and run one turn...
                      </p>
                      <div className="absolute bottom-0 left-0 right-0 h-6 bg-gradient-to-t from-neutral-100/50 dark:from-[#050505] to-transparent pointer-events-none" />
                    </div>
                    <div className="flex items-center justify-between mt-3 pt-2 border-t border-foreground/[0.04]">
                      <button
                        type="button"
                        onClick={() => dispatch({ type: "prompt_open" })}
                        className="flex items-center gap-1 text-[11px] text-neutral-400 dark:text-neutral-500 hover:text-neutral-600 dark:hover:text-neutral-300 transition-colors"
                      >
                        <EyeIcon size={12} />
                        View full prompt
                      </button>
                      <button
                        type="button"
                        onClick={() => copy(aiPromptText)}
                        className="flex items-center gap-1.5 text-[11px] text-neutral-400 dark:text-neutral-500 hover:text-neutral-600 dark:hover:text-neutral-300 transition-colors"
                      >
                        {copied ? (
                          <>
                            <CheckIcon size={14} />
                            Copied
                          </>
                        ) : (
                          <>
                            <CopyIcon size={14} />
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
        </m.div>

        {/* Prompt dialog */}
        <PromptDialog
          open={promptOpen}
          copied={copied}
          promptText={aiPromptText}
          onClose={() => dispatch({ type: "prompt_close" })}
          onCopy={copy}
        />
      </div>
    </LazyMotion>
  );
}
