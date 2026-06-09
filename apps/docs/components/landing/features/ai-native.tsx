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

// react-doctor-disable-next-line unused-export, deslop/unused-export
export function AiNativeSection() {
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
