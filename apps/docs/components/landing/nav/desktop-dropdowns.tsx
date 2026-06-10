// Desktop nav dropdown panels extracted to keep staggered-nav-files.tsx under 400 lines.
import { AnimatePresence, LazyMotion, domAnimation, m } from "framer-motion";
import Link from "next/link";
import { featuredResources, linkResources } from "@lib/landing/nav-sections-data";

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
            className={`absolute top-full right-0 z-50 w-[480px] max-w-[calc(100vw-2rem)] border ${dropdownBorderClass} bg-background shadow-2xl shadow-black/20 dark:shadow-black/60`}
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
            <div className="grid grid-cols-4 divide-x divide-foreground/[0.06] border-t border-foreground/[0.06]">
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
            </div>
            <div className="grid w-full grid-cols-[repeat(auto-fit,minmax(1.75rem,1fr))] items-center justify-items-center gap-y-0.5 border-t border-foreground/[0.06] px-2 py-2">
              <a
                href="https://github.com/enkyuan/alloy"
                target="_blank"
                rel="noreferrer"
                className="flex items-center justify-center p-1 text-foreground/55 dark:text-foreground/40 hover:text-foreground/75 transition-colors"
                aria-label="GitHub"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="14"
                  height="14"
                  viewBox="0 0 256 250"
                >
                  <path
                    fill="currentColor"
                    d="M128.001 0C57.317 0 0 57.307 0 128.001c0 56.554 36.676 104.535 87.535 121.46c6.397 1.185 8.746-2.777 8.746-6.158c0-3.052-.12-13.135-.174-23.83c-35.61 7.742-43.124-15.103-43.124-15.103c-5.823-14.795-14.213-18.73-14.213-18.73c-11.613-7.944.876-7.78.876-7.78c12.853.902 19.621 13.19 19.621 13.19c11.417 19.568 29.945 13.911 37.249 10.64c1.149-8.272 4.466-13.92 8.127-17.116c-28.431-3.236-58.318-14.212-58.318-63.258c0-13.975 5-25.394 13.188-34.358c-1.329-3.224-5.71-16.242 1.24-33.874c0 0 10.749-3.44 35.21 13.121c10.21-2.836 21.16-4.258 32.038-4.307c10.878.049 21.837 1.47 32.066 4.307c24.431-16.56 35.165-13.12 35.165-13.12c6.967 17.63 2.584 30.65 1.255 33.873c8.207 8.964 13.173 20.383 13.173 34.358c0 49.163-29.944 59.988-58.447 63.157c4.591 3.972 8.682 11.762 8.682 23.704c0 17.126-.148 30.91-.148 35.126c0 3.407 2.304 7.398 8.792 6.14C219.37 232.5 256 184.537 256 128.002C256 57.307 198.691 0 128.001 0"
                  />
                </svg>
              </a>
            </div>
          </m.div>
        )}
      </AnimatePresence>
    </LazyMotion>
  );
}
