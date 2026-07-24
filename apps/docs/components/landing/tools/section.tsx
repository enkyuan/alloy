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

  const pySnippet = `import kaji

@kaji.function_tool(risk="read")
async def get_weather(
    context: kaji.ToolExecutionContext,
    city: str,
) -> dict:
    """Look up the weather for a city."""
    return {"city": city, "principal": context.principal_id}

runtime = kaji.AgentBuilder().provider(provider).tool(get_weather).build()`;

  const tsSnippet = `import { AgentBuilder, functionTool } from "kaji-sdk"
import { z } from "zod"

const getWeather = functionTool(
  {
    name: "get_weather",
    description: "Look up the weather for a city.",
    parameters: z.object({ city: z.string() }),
    risk: "read",
  },
  async ({ city }, context) => ({ city, principal: context.principalId }),
)

const runtime = new AgentBuilder().provider(provider).tool(getWeather).build()`;

  const snippets: Record<ToolLanguage, string> = {
    py: pySnippet,
    ts: tsSnippet,
  };

  const current = languages.find((l) => l.id === language)!;

  return (
    <div className="relative overflow-hidden bg-neutral-50 dark:bg-black">
      <div className="flex items-center justify-between px-3 py-1.5">
        <span className="inline-flex items-center gap-1.5 text-[11px] font-mono text-foreground/50 dark:text-foreground/40">
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 32 32">
            <rect width="28" height="28" x="2" y="2" fill="currentColor" opacity="0.3" rx="1.312" />
            <path
              fill="currentColor"
              fillRule="evenodd"
              d="M18.245 23.759v3.068a6.5 6.5 0 0 0 1.764.575a11.6 11.6 0 0 0 2.146.192a10 10 0 0 0 2.088-.211a5.1 5.1 0 0 0 1.735-.7a3.54 3.54 0 0 0 1.181-1.266a4.47 4.47 0 0 0 .186-3.394a3.4 3.4 0 0 0-.717-1.117a5.2 5.2 0 0 0-1.123-.877a12 12 0 0 0-1.477-.734q-.6-.249-1.08-.484a5.5 5.5 0 0 1-.813-.479a2.1 2.1 0 0 1-.516-.518a1.1 1.1 0 0 1-.181-.618a1.04 1.04 0 0 1 .162-.571a1.4 1.4 0 0 1 .459-.436a2.4 2.4 0 0 1 .726-.283a4.2 4.2 0 0 1 .956-.1a6 6 0 0 1 .808.058a6 6 0 0 1 .856.177a6 6 0 0 1 .836.3a4.7 4.7 0 0 1 .751.422V13.9a7.5 7.5 0 0 0-1.525-.4a12.4 12.4 0 0 0-1.9-.129a8.8 8.8 0 0 0-2.064.235a5.2 5.2 0 0 0-1.716.733a3.66 3.66 0 0 0-1.171 1.271a3.73 3.73 0 0 0-.431 1.845a3.6 3.6 0 0 0 .789 2.34a6 6 0 0 0 2.395 1.639q.63.26 1.175.509a6.5 6.5 0 0 1 .942.517a2.5 2.5 0 0 1 .626.585a1.2 1.2 0 0 1 .23.719a1.1 1.1 0 0 1-.144.552a1.3 1.3 0 0 1-.435.441a2.4 2.4 0 0 1-.726.292a4.4 4.4 0 0 1-1.018.105a5.8 5.8 0 0 1-1.969-.35a5.9 5.9 0 0 1-1.805-1.045m-5.154-7.638h4v-2.527H5.938v2.527H9.92v11.254h3.171Z"
            />
          </svg>
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

      <div className="relative overflow-hidden">
        <DynamicCodeBlock
          lang={language}
          code={snippets[language]}
          allowCopy={false}
          codeblock={{
            className:
              "border-0 rounded-none my-0 shadow-none bg-neutral-50 dark:bg-black [&_div]:bg-neutral-50 [&_div]:dark:bg-black [&_div]:text-[12px]",
            "data-line-numbers": true,
          }}
        />
      </div>
    </div>
  );
}
