import { DynamicCodeBlock } from "@components/ui/dynamic-code-block";
import { providerDrivers, moreProviders, providerSnippets } from "./data";

const allProviders = [...providerDrivers, ...moreProviders];

export function ProvidersSection() {
  const featured = allProviders.find((d) => d.name === "OpenAI")!;
  const others = allProviders.filter((d) => d.name !== "OpenAI");

  return (
    <div className="h-full flex items-center" suppressHydrationWarning>
      <div className="w-full max-w-[920px] mx-auto">
        <div className="grid grid-cols-4 sm:grid-cols-6 gap-0">
          {/* OpenAI — intentionally larger feature tile */}
          <div className="col-span-2 sm:col-span-3 row-span-2 relative border-b border-r border-dashed border-foreground/[0.06] p-3 sm:p-4 min-h-[200px] sm:min-h-[240px] cursor-default hover:bg-gradient-to-br hover:from-foreground/[0.02] hover:to-violet-500/[0.015] transition-colors overflow-hidden group/provider">
            <div className="absolute top-2 right-2 sm:top-3 sm:right-3 text-[10px] font-semibold text-white bg-violet-600 dark:bg-violet-500 px-2 py-0.5 rounded opacity-0 group-hover/provider:opacity-100 transition-opacity duration-200">
              default
            </div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-foreground/80 dark:text-foreground/70 [&_svg]:w-5 [&_svg]:h-5 [&_svg]:grayscale-0 [&_svg]:opacity-100">
                {featured.icon()}
              </span>
              <span className="text-[13px] font-mono text-foreground/85 dark:text-foreground/75">
                {featured.name}
              </span>
            </div>
            <div suppressHydrationWarning>
              <DynamicCodeBlock
                lang="ts"
                code={providerSnippets.OpenAI}
                allowCopy={false}
                codeblock={{
                  className:
                    "border-0 rounded-none my-0 shadow-none bg-transparent [&_div]:bg-transparent [&_div]:text-[11px] [&_pre]:!p-0 [&_pre]:!overflow-hidden [&_div]:!overflow-hidden [&_code]:!overflow-hidden",
                }}
              />
            </div>
            <div className="absolute inset-y-0 right-0 w-14 bg-gradient-to-l from-background to-transparent pointer-events-none" />
            <div className="absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-background to-transparent pointer-events-none" />
          </div>

          {/* Other providers */}
          {others.map((provider) => (
            <div
              key={provider.name}
              className="flex flex-col items-center justify-center gap-2 py-4 sm:py-5 border-b border-r border-dashed border-foreground/[0.06] cursor-default hover:bg-gradient-to-br hover:from-violet-500/[0.08] hover:to-violet-500/[0.02] transition-colors group/prov"
            >
              <span className="text-foreground/80 dark:text-foreground/70 [&_svg]:w-6 [&_svg]:h-6 group-hover/prov:scale-110 transition-transform duration-200">
                {provider.icon()}
              </span>
              <span className="text-[10px] font-mono text-foreground/70 dark:text-foreground/60 group-hover/prov:text-foreground/80 transition-colors duration-200">
                {provider.name}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
