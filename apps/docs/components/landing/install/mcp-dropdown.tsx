"use client";

import { cn } from "@lib/utils";
import { CopyIcon, CheckIcon, PlusIcon } from "@components/docs/icons/ui";
import {
  CursorLogo,
  ClaudeCodeLogo,
  OpenCodeLogo,
  TerminalIcon,
} from "@components/docs/icons/editors";

const mcpCommands = [
  { name: "Cursor", command: "npx agentkit mcp --cursor" },
  { name: "Claude Code", command: "npx agentkit mcp --claude-code" },
  { name: "Open Code", command: "npx agentkit mcp --open-code" },
  { name: "Manual", command: "npx agentkit mcp --manual" },
];

type Props = {
  copied: boolean;
  open: boolean;
  onToggle: () => void;
  onClose: () => void;
  onCopy: (cmd: string) => void;
};

export function McpDropdown({ copied, open, onToggle, onClose, onCopy }: Props) {
  return (
    <div className="relative">
      <button
        type="button"
        onClick={onToggle}
        className="text-neutral-400 dark:text-neutral-500 hover:text-neutral-600 dark:hover:text-neutral-300 transition-colors p-1"
        aria-label="Add MCP"
      >
        {copied ? <CheckIcon className="h-4 w-4" /> : <PlusIcon className="h-4 w-4" />}
      </button>
      {open && (
        <>
          <button
            type="button"
            className="fixed inset-0 z-40 cursor-default"
            tabIndex={-1}
            aria-label="Close dropdown"
            onClick={onClose}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
            }}
          />
          <div className="absolute right-0 top-full mt-2 w-[160px] bg-white dark:bg-[#050505] border border-neutral-200 dark:border-white/[0.07] shadow-2xl shadow-black/10 dark:shadow-black/80 z-50 rounded-sm">
            {mcpCommands.map((mc, i) => (
              <button
                type="button"
                key={mc.name}
                onClick={() => onCopy(mc.command)}
                className={cn(
                  "flex items-center gap-2.5 w-full px-3 py-2 text-[12px] text-neutral-500 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-white hover:bg-neutral-100 dark:hover:bg-white/[0.05] transition-all text-left",
                  i < mcpCommands.length - 1 &&
                    "border-b border-neutral-100 dark:border-white/[0.06]",
                )}
              >
                <span className="flex items-center justify-center w-3.5 h-3.5 shrink-0">
                  {mc.name === "Cursor" && <CursorLogo className="h-3.5 w-3.5" />}
                  {mc.name === "Claude Code" && <ClaudeCodeLogo className="h-3.5 w-3.5" />}
                  {mc.name === "Open Code" && <OpenCodeLogo className="h-3.5 w-3.5" />}
                  {mc.name === "Manual" && <TerminalIcon className="h-3.5 w-3.5" />}
                </span>
                <span className="font-mono text-[11px]">{mc.name}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
