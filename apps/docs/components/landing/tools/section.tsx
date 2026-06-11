"use client";

import { useState } from "react";
import { DynamicCodeBlock } from "@components/ui/dynamic-code-block";

type ToolLanguage = "py" | "ts";

export function ToolsSection() {
  const [language, setLanguage] = useState<ToolLanguage>("py");

  const languages = [
    { id: "py" as const, label: "Python", filename: "tools.py" },
    { id: "ts" as const, label: "TypeScript", filename: "tools.ts" },
  ];

  const pySnippet = `from agentkit import register_tool, tool_spec_from_model

class WeatherArgs(BaseModel):
    city: str

@register_tool(tool_spec_from_model(
    "get_weather", "Look up the weather", WeatherArgs
))
async def get_weather(ctx, args):
    return await fetch_weather(args["city"])`;

  const tsSnippet = `import { registerTool, toolSpecFromSchema } from "@agentkit/sdk"
import { z } from "zod"

registerTool(
  toolSpecFromSchema("get_weather", "Look up the weather",
    z.object({ city: z.string() }),
  ),
  async (ctx, args) => fetchWeather(args.city),
)`;

  const snippets: Record<ToolLanguage, string> = {
    py: pySnippet,
    ts: tsSnippet,
  };

  const current = languages.find((l) => l.id === language)!;

  return (
    <div className="flex flex-col gap-3 pt-2 pb-1">
      <div className="flex items-center justify-between px-0 py-0">
        <span className="text-[11px] font-mono text-foreground/50 dark:text-foreground/40">
          {current.filename}
        </span>
        <div className="flex items-center gap-0.5 text-[10px] font-mono">
          {languages.map((lang) => (
            <button
              key={lang.id}
              type="button"
              onClick={() => setLanguage(lang.id)}
              className={
                language === lang.id
                  ? "px-1.5 py-0.5 rounded-sm text-foreground/80 bg-foreground/[0.06]"
                  : "px-1.5 py-0.5 rounded-sm text-foreground/40 hover:text-foreground/65 transition-colors"
              }
            >
              {lang.label}
            </button>
          ))}
        </div>
      </div>

      {/* Syntax-highlighted Code Block */}
      <DynamicCodeBlock
        lang={language}
        code={snippets[language]}
        allowCopy={false}
        codeblock={{
          className:
            "border-0 rounded-none my-0 shadow-none bg-transparent [&_div]:bg-transparent [&_div]:text-[11px] [&_pre]:!p-0 [&_pre]:!overflow-hidden [&_div]:!overflow-hidden [&_code]:!overflow-hidden",
        }}
      />
    </div>
  );
}
