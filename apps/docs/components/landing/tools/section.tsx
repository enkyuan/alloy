"use client";

import { useState } from "react";
import { DynamicCodeBlock } from "@components/ui/dynamic-code-block";
import { cn } from "@lib/utils";

type ToolLanguage = "py" | "ts";

export function ToolsSection() {
  const [language, setLanguage] = useState<ToolLanguage>("py");

  const languages = [
    { id: "py" as const, label: "Python" },
    { id: "ts" as const, label: "TypeScript" },
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

  return (
    <div className="flex flex-col gap-3 pt-2 pb-1">
      {/* Language Switcher */}
      <div className="flex gap-1">
        {languages.map((lang) => (
          <button
            key={lang.id}
            type="button"
            onClick={() => setLanguage(lang.id)}
            className={cn(
              "px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider transition-colors border-b-2 -mb-px",
              language === lang.id
                ? "text-foreground/85 border-b-foreground/50"
                : "text-foreground/50 hover:text-foreground/65 border-b-transparent",
            )}
          >
            {lang.label}
          </button>
        ))}
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
