"use client";

import { AnimatePresence, LazyMotion, MotionConfig, domAnimation, m } from "motion/react";
import { useSearchContext } from "fumadocs-ui/contexts/search";
import { RiArrowDownSLine } from "@remixicon/react";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { contents } from "@lib/sidebar-config";
import { ThemeToggle } from "@components/theme-toggle";
import { SidebarVersionSwitcher } from "@components/version-switcher";
import { getVersionFromPathname, stripVersionPrefix, versionedDocsHref } from "@lib/docs-versions";
import { cn } from "@lib/utils";
import { SidebarSection } from "./items";

export function DocsSidebar() {
  const pathname = usePathname();
  const { setOpenSearch } = useSearchContext();
  const currentVersion = getVersionFromPathname(pathname);
  const prefixHref = (href: string) => versionedDocsHref(href, currentVersion);
  // For matching, strip the version prefix from pathname so we can compare against canonical href
  const canonicalPathname = stripVersionPrefix(pathname, currentVersion);
  const [currentOpen, setCurrentOpen] = useState(0);
  const navRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const defaultValue = contents.findIndex((item) => {
      const prefix = item.expandSectionForPathPrefix;
      if (prefix && (canonicalPathname === prefix || canonicalPathname.startsWith(`${prefix}/`))) {
        return true;
      }
      return item.list.some(
        (listItem) =>
          listItem.href === canonicalPathname ||
          (listItem.subpages &&
            listItem.subpages.length > 0 &&
            canonicalPathname.startsWith(`${listItem.href}/`)) ||
          listItem.subpages?.some((sp) => sp.href && canonicalPathname === sp.href),
      );
    });
    setCurrentOpen(defaultValue === -1 ? 0 : defaultValue);
  }, [canonicalPathname]);

  // Scroll the active item into view after section expands
  useEffect(() => {
    const timer = setTimeout(() => {
      const nav = navRef.current;
      if (!nav) return;
      const activeEl = nav.querySelector<HTMLElement>("[data-active='true']");
      if (!activeEl) return;

      const navRect = nav.getBoundingClientRect();
      const elRect = activeEl.getBoundingClientRect();

      // Only scroll if the active item is outside the visible area
      const isAbove = elRect.top < navRect.top;
      const isBelow = elRect.bottom > navRect.bottom;

      if (isAbove || isBelow) {
        activeEl.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    }, 380); // wait for expand animation to finish

    return () => clearTimeout(timer);
  }, [pathname, currentOpen]);

  return (
    <LazyMotion features={domAnimation}>
      <m.aside
        initial={{ x: -24, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        transition={{ duration: 0.28, ease: "easeOut" }}
        className="fixed left-0 top-[var(--landing-topbar-height)] bottom-0 w-[22vw] max-w-[300px] hidden lg:flex flex-col z-30 bg-background border-r border-foreground/5 transition-[width] duration-300 ease-out"
      >
        <SidebarVersionSwitcher />

        <button
          type="button"
          className="group/search flex w-full items-center gap-2 px-4 py-[9px] border-b border-foreground/5 text-sm text-foreground/55 hover:text-foreground/80 hover:bg-foreground/3 transition-colors"
          onClick={() => setOpenSearch(true)}
        >
          <svg
            className="size-4 shrink-0 text-foreground opacity-55 group-hover/search:opacity-80 transition-opacity"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="11" cy="11" r="5.5" />
            <path d="m15 15l4 4" />
          </svg>
          <span className="truncate">Search</span>
          <kbd className="ml-auto inline-flex items-center gap-0.5 shrink-0 text-[10px] font-mono text-foreground/40 border border-foreground/10 rounded-md px-1.5 py-0.5">
            <span className="text-[11px]">&#8984;</span>K
          </kbd>
        </button>

        {/* Scrollable navigation area */}
        <nav
          ref={navRef}
          className="flex-1 overflow-y-auto overflow-x-hidden pb-3 sidebar-scroll"
          style={{
            maskImage:
              "linear-gradient(to bottom, transparent, white 1rem, white calc(100% - 2rem), transparent 100%)",
          }}
        >
          <MotionConfig transition={{ duration: 0.35, type: "spring", bounce: 0 }}>
            <div className="flex flex-col">
              {contents.map((section, index) => (
                <div key={section.title}>
                  <button
                    type="button"
                    className={cn(
                      "border-b border-foreground/6 w-full text-left flex gap-2 items-center px-4 py-2.5 transition-colors",
                      "font-medium text-sm tracking-wider",
                      currentOpen === index
                        ? "text-foreground bg-foreground/3"
                        : "text-foreground/70 hover:text-foreground hover:bg-foreground/3",
                    )}
                    onClick={() => {
                      setCurrentOpen((prev) => (prev === index ? -1 : index));
                    }}
                  >
                    <section.Icon className="size-4.5" />
                    <span className="grow tracking-normal">{section.title}</span>
                    <RiArrowDownSLine
                      size={16}
                      className={cn(
                        "shrink-0 text-muted-foreground transition-transform duration-200",
                        currentOpen === index ? "rotate-180" : "",
                      )}
                    />
                  </button>
                  <AnimatePresence initial={false}>
                    {currentOpen === index && (
                      <m.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: "auto" }}
                        exit={{ opacity: 0, height: 0 }}
                        className="relative overflow-hidden"
                      >
                        <m.div className="text-sm">
                          <SidebarSection
                            section={section}
                            pathname={canonicalPathname}
                            prefixHref={prefixHref}
                          />
                        </m.div>
                      </m.div>
                    )}
                  </AnimatePresence>
                </div>
              ))}
            </div>
          </MotionConfig>
        </nav>

        {/* Footer: GitHub + Theme Toggle */}
        <div className="flex items-center gap-1 p-2 border-t border-foreground/5 text-foreground/40">
          <a
            href="https://github.com/enkyuan/alloy"
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center justify-center size-8 hover:text-foreground/70 hover:bg-foreground/5 transition-colors"
            aria-label="GitHub"
          >
            <svg role="img" viewBox="0 0 24 24" fill="currentColor" className="size-4">
              <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
            </svg>
          </a>
          <div className="ms-auto [&_button]:text-foreground/40 [&_button:hover]:text-foreground/70">
            <ThemeToggle />
          </div>
        </div>
      </m.aside>
    </LazyMotion>
  );
}
