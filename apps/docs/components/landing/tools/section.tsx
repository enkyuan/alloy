export function ToolsSection() {
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

  return (
    <div className="flex flex-col gap-3 pt-2 pb-1">
      <div className="flex flex-col gap-1">
        <span className="text-[9px] font-mono uppercase tracking-widest text-foreground/45 dark:text-foreground/35">
          Python
        </span>
        <pre className="text-[11px] font-mono leading-relaxed text-foreground/80 dark:text-foreground/70 whitespace-pre overflow-x-auto">
          {pySnippet}
        </pre>
      </div>
      <div className="border-t border-dashed border-foreground/[0.06]" />
      <div className="flex flex-col gap-1">
        <span className="text-[9px] font-mono uppercase tracking-widest text-foreground/45 dark:text-foreground/35">
          TypeScript
        </span>
        <pre className="text-[11px] font-mono leading-relaxed text-foreground/80 dark:text-foreground/70 whitespace-pre overflow-x-auto">
          {tsSnippet}
        </pre>
      </div>
    </div>
  );
}
