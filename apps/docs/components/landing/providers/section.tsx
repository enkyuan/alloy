import { DynamicCodeBlock } from "@components/ui/dynamic-code-block";
import { providerDrivers, moreProviders, providerSnippets } from "./data";

const allProviders = [...providerDrivers, ...moreProviders];

export function ProviderLogosGrid({ exclude }: { exclude?: string[] }) {
  const providers = exclude ? allProviders.filter((p) => !exclude.includes(p.name)) : allProviders;
  return (
    <div className="grid grid-cols-2 w-full divide-x divide-y divide-dashed divide-foreground/[0.06]">
      {providers.map((provider) => (
        <div
          key={provider.name}
          className="flex flex-col items-center justify-center gap-1.5 py-3 px-2 cursor-default hover:bg-gradient-to-br hover:from-violet-500/[0.08] hover:to-violet-500/[0.02] transition-colors group/prov"
        >
          <span className="text-foreground/80 dark:text-foreground/70 [&_svg]:w-4 [&_svg]:h-4 group-hover/prov:scale-110 transition-transform duration-200">
            {provider.icon()}
          </span>
          <span className="text-[9px] font-mono text-foreground/70 dark:text-foreground/60 group-hover/prov:text-foreground/80 transition-colors duration-200 text-center">
            {provider.name}
          </span>
        </div>
      ))}
    </div>
  );
}

export function ProvidersSection() {
  const featured = allProviders.find((d) => d.name === "OpenAI")!;

  return (
    <div className="h-full flex" suppressHydrationWarning>
      <div className="w-full">
        <div className="relative p-3 sm:p-4 min-h-[200px] sm:min-h-[240px] cursor-default overflow-hidden group/provider">
          <div className="absolute top-2 right-2 sm:top-3 sm:right-3 text-[10px] font-semibold text-white bg-orange-500 dark:bg-orange-500 px-2 py-0.5 rounded opacity-0 group-hover/provider:opacity-100 transition-opacity duration-200">
            default
          </div>
          <div className="flex items-center gap-2 mb-2">
            <span className="text-foreground/80 dark:text-foreground/70 [&_svg]:w-5 [&_svg]:h-5">
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
                "data-line-numbers": true,
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
