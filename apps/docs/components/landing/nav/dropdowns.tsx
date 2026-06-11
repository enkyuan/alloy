// Nav dropdown panels.
import { AnimatePresence, LazyMotion, domAnimation, m } from "motion/react";
import Link from "next/link";
import { featuredResources, linkResources } from "@lib/landing/nav-sections";
import { GitHubIcon } from "@components/docs/icons/ui";

// ─── ResourcesDropdown ───────────────────────────────────────────────────────

interface ResourcesDropdownProps {
  isOpen: boolean;
  dropdownBorderClass: string;
  onClose: () => void;
}

export function ResourcesDropdown({
  isOpen,
  dropdownBorderClass,
  onClose,
}: ResourcesDropdownProps) {
  return (
    <LazyMotion features={domAnimation}>
      <AnimatePresence>
        {isOpen && (
          <m.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.12, ease: "easeOut" }}
            className={`absolute top-full -right-px z-50 w-[480px] max-w-[calc(100vw-2rem)] border-x border-b ${dropdownBorderClass} bg-background shadow-2xl shadow-black/20 dark:shadow-black/60`}
          >
            <div className="grid grid-cols-2 divide-x divide-foreground/[0.06]">
              {featuredResources.map((r) => (
                <Link
                  key={r.title}
                  href={r.href}
                  onClick={onClose}
                  className="group/p relative flex h-full flex-col gap-2.5 p-4 overflow-hidden hover:bg-foreground/[0.03] transition-colors"
                >
                  {r.BgPattern && <r.BgPattern className={r.bgPatternClassName ?? ""} />}
                  {r.Pattern && (
                    <r.Pattern
                      className={
                        r.patternClassName ??
                        "absolute right-0 top-0 text-foreground/[0.09] group-hover/p:text-foreground/25 transition-colors duration-200 pointer-events-none"
                      }
                    />
                  )}
                  <div className="relative flex items-center">
                    <span className="flex size-8 items-center justify-center border border-foreground/[0.1] text-foreground/70 group-hover/p:text-foreground group-hover/p:border-foreground/25 transition-colors bg-background">
                      <r.Icon className="size-4" />
                    </span>
                  </div>
                  <div className="relative flex flex-col gap-0.5">
                    <span className="text-[13px] font-medium text-foreground/90 group-hover/p:text-foreground transition-colors">
                      {r.title}
                    </span>
                    <span className="text-[11px] leading-relaxed text-foreground/55 dark:text-foreground/45">
                      {r.description}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
            {/* <div className="grid grid-cols-4 divide-x divide-foreground/[0.06] border-t border-foreground/[0.06]">
              {linkResources.map((r) => (
                <Link
                  key={r.title}
                  href={r.href}
                  onClick={onClose}
                  className="group/p relative flex items-center gap-2 px-3 py-3 hover:bg-foreground/[0.03] transition-colors"
                >
                  <r.Icon className="size-3.5 text-foreground/55 group-hover/p:text-foreground/80 transition-colors" />
                  <span className="text-[12px] font-medium text-foreground/75 group-hover/p:text-foreground transition-colors">
                    {r.title}
                  </span>
                </Link>
              ))}
            </div> */}
            <div className="grid w-full grid-cols-[repeat(auto-fit,minmax(1.75rem,1fr))] items-center justify-items-center gap-y-0.5 border-t border-foreground/[0.06] px-2 py-2">
              <a
                href="https://github.com/enkyuan/alloy"
                target="_blank"
                rel="noreferrer"
                className="flex items-center justify-center p-1 text-foreground/55 dark:text-foreground/40 hover:text-foreground/75 transition-colors"
                aria-label="GitHub"
              >
                <GitHubIcon size={14} />
              </a>
            </div>
          </m.div>
        )}
      </AnimatePresence>
    </LazyMotion>
  );
}
