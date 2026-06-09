import Link from "next/link";
import { RiArrowRightUpLine } from "@remixicon/react";
import { categoryLabels } from "../tools/data";
import { plugins } from "@lib/landing/plugins-data";

export function CapabilitiesMarquee() {
  const half = Math.ceil(plugins.length / 2);
  const row1 = plugins.slice(0, half);
  const row2 = plugins.slice(half);

  return (
    <div>
      <Link
        href="/docs"
        className="flex items-center justify-between w-full mb-4 text-[10px] font-mono text-foreground/35 dark:text-foreground/50 hover:text-foreground/55 transition-colors uppercase tracking-wider border-b border-dashed border-foreground/[0.1] px-3 py-1.5 bg-foreground/[0.02] hover:bg-foreground/[0.04]"
      >
        <span className="text-xs text-foreground/85 dark:text-foreground/75">Capabilities</span>
        <span className="flex items-center gap-1">
          browse all <RiArrowRightUpLine className="size-[10px]" />
        </span>
      </Link>

      <div className="relative overflow-hidden">
        {/* Row 1 — scrolls left */}
        <div className="flex animate-[marquee_40s_linear_infinite] mb-1.5">
          {[...row1, ...row1].map((plugin, i) => (
            <span
              key={`${plugin.name}-${i}`}
              className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 mr-1.5 text-[11px] text-foreground dark:text-foreground/90 border border-foreground/[0.06] rounded-sm cursor-default whitespace-nowrap"
            >
              {plugin.name}
              <span className="text-[7px] font-mono uppercase tracking-wider text-foreground/50 ">
                {categoryLabels[plugin.category]}
              </span>
            </span>
          ))}
        </div>

        {/* Row 2 — scrolls right */}
        <div className="flex animate-[marquee-reverse_45s_linear_infinite]">
          {[...row2, ...row2].map((plugin, i) => (
            <span
              key={`${plugin.name}-${i}`}
              className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 mr-1.5 text-[11px] text-foreground dark:text-foreground/90 border border-foreground/[0.06] rounded-sm cursor-default whitespace-nowrap"
            >
              {plugin.name}
              <span className="text-[7px] font-mono uppercase tracking-wider text-foreground/50 ">
                {categoryLabels[plugin.category]}
              </span>
            </span>
          ))}
        </div>

        {/* Side fades */}
        <div className="absolute inset-y-0 left-0 w-12 bg-gradient-to-r from-background to-transparent pointer-events-none" />
        <div className="absolute inset-y-0 right-0 w-12 bg-gradient-to-l from-background to-transparent pointer-events-none" />
      </div>
    </div>
  );
}
