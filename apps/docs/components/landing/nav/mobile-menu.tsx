"use client";

import { AnimatePresence, LazyMotion, domAnimation, m } from "motion/react";
import { RiArrowDownSLine } from "@remixicon/react";
import Link from "next/link";
import { useCallback } from "react";
import type { NavFileItem } from "@lib/landing/nav-data";
import type { MobileMenuSection } from "@lib/landing/nav-data";
import { contents } from "@components/sidebar-content";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@components/ui/accordion";
import { Badge } from "@components/ui/badge";
import { cn } from "@lib/utils";
import { getVersionFromPathname, versionedDocsHref } from "@lib/docs-versions";
import { usePathname } from "next/navigation";

interface NavMobileMenuProps {
  mobileMenuOpen: boolean;
  mobileView: "docs" | "nav";
  mobileDocSection: number;
  isDocs: boolean;
  navFiles: NavFileItem[];
  mobileMenuSections: MobileMenuSection[];
  setMobileMenuOpen: (open: boolean) => void;
  setMobileView: (view: "docs" | "nav") => void;
  setMobileDocSection: (fn: (prev: number) => number) => void;
}

// react-doctor-disable-next-line react-doctor/no-giant-component
export function NavMobileMenu({
  mobileMenuOpen,
  mobileView,
  mobileDocSection,
  isDocs,
  navFiles,
  mobileMenuSections,
  setMobileMenuOpen,
  setMobileView,
  setMobileDocSection,
}: NavMobileMenuProps) {
  const pathname = usePathname() || "/";
  const currentVersion = getVersionFromPathname(pathname);
  const prefixHref = (href: string) => versionedDocsHref(href, currentVersion);
  const isActive = useCallback((href: string) => pathname === href, [pathname]);
  const isActivePrefix = useCallback(
    (href: string) => pathname === href || pathname.startsWith(`${href}/`),
    [pathname],
  );

  return (
    <LazyMotion features={domAnimation}>
      <AnimatePresence>
        {mobileMenuOpen && (
          <m.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="lg:hidden fixed inset-0 z-[98] w-full bg-background/95 backdrop-blur-sm pointer-events-auto"
          >
            <div className="flex h-full flex-col pt-(--landing-topbar-height)">
              <div className="flex-1 min-h-0 overflow-y-auto">
                {isDocs && mobileView === "docs" ? (
                  <>
                    <button
                      type="button"
                      onClick={() => setMobileView("nav")}
                      className="flex items-center gap-2 w-full px-5 py-2.5 text-foreground/65 dark:text-foreground/45 hover:text-foreground/70 transition-colors border-b border-foreground/6"
                    >
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        width="12"
                        height="12"
                        viewBox="0 0 24 24"
                      >
                        <path fill="currentColor" d="M3 18h18v-2H3zm0-5h18v-2H3zm0-7v2h18V6z" />
                      </svg>
                      <span className="font-mono text-[10px] uppercase tracking-wider">Menu</span>
                    </button>

                    <div className="flex flex-col">
                      {contents.map((section, index) => (
                        <div key={section.title}>
                          <button
                            type="button"
                            className={cn(
                              "border-b border-foreground/6 w-full text-left flex gap-2 items-center px-5 py-3 transition-colors",
                              "font-medium text-sm tracking-wider",
                              mobileDocSection === index
                                ? "text-foreground bg-foreground/3"
                                : "text-foreground/70 hover:text-foreground hover:bg-foreground/3",
                            )}
                            onClick={() =>
                              setMobileDocSection((prev) => (prev === index ? -1 : index))
                            }
                          >
                            <section.Icon size={18} />
                            <span className="grow">{section.title}</span>
                            <RiArrowDownSLine
                              size={16}
                              className={cn(
                                "shrink-0 text-muted-foreground transition-transform duration-200",
                                mobileDocSection === index ? "rotate-180" : "",
                              )}
                            />
                          </button>
                          {mobileDocSection === index && (
                            <div className="relative overflow-hidden">
                              <div className="text-sm pt-0 pb-1">
                                {section.href && (
                                  <Link
                                    href={prefixHref(section.href)}
                                    onClick={() => setMobileMenuOpen(false)}
                                    data-active={pathname === section.href || undefined}
                                    className={cn(
                                      "relative flex items-center gap-2.5 px-5 py-1.5 text-[14px] transition-all duration-150",
                                      pathname === section.href
                                        ? "text-foreground bg-foreground/6"
                                        : "text-foreground/75 dark:text-foreground/60 hover:text-foreground/90 hover:bg-foreground/3",
                                    )}
                                  >
                                    <span className="truncate">Overview</span>
                                  </Link>
                                )}
                                {section.list.map((item, i) => {
                                  if (item.separator || item.group) {
                                    return (
                                      <div
                                        key={`sep-${item.title}-${i}`}
                                        className="flex flex-row items-center gap-2 mx-5 my-2"
                                      >
                                        <p className="text-[10px] text-foreground/65 dark:text-foreground/45 uppercase tracking-wider">
                                          {item.title}
                                        </p>
                                        <div className="grow h-px bg-border" />
                                      </div>
                                    );
                                  }
                                  if (item.external && item.href) {
                                    return (
                                      <Link
                                        key={item.href}
                                        href={item.href}
                                        onClick={() => setMobileMenuOpen(false)}
                                        className={cn(
                                          "relative flex w-full items-center gap-2.5 px-5 py-1.5 text-[14px] transition-all duration-150",
                                          "text-foreground/75 dark:text-foreground/60 hover:text-foreground/90 hover:bg-foreground/3",
                                        )}
                                      >
                                        <span className="text-foreground/75 transition-colors duration-150 dark:text-foreground/60">
                                          <span className="flex size-5 shrink-0 items-center justify-center [&>svg]:size-[14px]">
                                            <item.icon className="text-foreground/75" />
                                          </span>
                                        </span>
                                        <span className="min-w-0 grow truncate">{item.title}</span>
                                        {item.isNew && (
                                          <Badge
                                            className="pointer-events-none border-dashed rounded-none px-1.5 py-0 text-[9px] uppercase tracking-wider text-foreground/70 dark:text-foreground/55 border-foreground/25"
                                            variant="outline"
                                          >
                                            New
                                          </Badge>
                                        )}
                                      </Link>
                                    );
                                  }
                                  if (!item.href) return null;
                                  const active =
                                    pathname === item.href ||
                                    (!!item.subpages?.length &&
                                      pathname.startsWith(`${item.href}/`));
                                  return (
                                    <Link
                                      key={item.href}
                                      href={prefixHref(item.href)}
                                      onClick={() => setMobileMenuOpen(false)}
                                      data-active={active || undefined}
                                      className={cn(
                                        "relative flex w-full items-center gap-2.5 px-5 py-1.5 text-[14px] transition-all duration-150",
                                        active
                                          ? "text-foreground bg-foreground/6"
                                          : "text-foreground/75 dark:text-foreground/60 hover:text-foreground/90 hover:bg-foreground/3",
                                      )}
                                    >
                                      <span
                                        className={cn(
                                          "transition-colors duration-150",
                                          active
                                            ? "text-foreground"
                                            : "text-foreground/75 dark:text-foreground/60",
                                        )}
                                      >
                                        <span className="flex size-5 shrink-0 items-center justify-center [&>svg]:size-[14px]">
                                          <item.icon className="text-foreground/75" />
                                        </span>
                                      </span>
                                      <span className="min-w-0 grow truncate">{item.title}</span>
                                      {item.isNew && (
                                        <Badge
                                          className={cn(
                                            "pointer-events-none border-dashed rounded-none px-1.5 py-0 text-[9px] uppercase tracking-wider",
                                            active
                                              ? "border-solid bg-foreground/10 text-foreground"
                                              : "text-foreground/70 dark:text-foreground/55 border-foreground/25",
                                          )}
                                          variant="outline"
                                        >
                                          New
                                        </Badge>
                                      )}
                                    </Link>
                                  );
                                })}
                              </div>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <>
                    {isDocs && mobileView === "nav" && (
                      <button
                        type="button"
                        onClick={() => setMobileView("docs")}
                        className="flex items-center gap-2 w-full px-5 py-2.5 text-foreground/65 dark:text-foreground/45 hover:text-foreground/70 transition-colors border-b border-foreground/6"
                      >
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          width="12"
                          height="12"
                          viewBox="0 0 24 24"
                        >
                          <path
                            fill="currentColor"
                            d="M20 11H7.83l5.59-5.59L12 4l-8 8l8 8l1.41-1.41L7.83 13H20z"
                          />
                        </svg>
                        <span className="font-mono text-[10px] uppercase tracking-wider">Docs</span>
                      </button>
                    )}

                    {navFiles.map((item) => (
                      <Link
                        key={item.name}
                        href={item.href}
                        onClick={() => setMobileMenuOpen(false)}
                        className={cn(
                          "flex items-center gap-2.5 px-5 py-3.5 border-b border-foreground/6 transition-colors font-mono text-base uppercase tracking-wider",
                          isActive(item.path || item.href) || (item.href === "/docs" && isDocs)
                            ? "text-foreground bg-foreground/4"
                            : "text-foreground/75 dark:text-foreground/60 hover:bg-foreground/3",
                        )}
                      >
                        {item.name}
                      </Link>
                    ))}

                    <Accordion
                      type="multiple"
                      defaultValue={mobileMenuSections.reduce<string[]>((acc, s) => {
                        if (s.children?.some((item) => isActivePrefix(item.path || item.href))) {
                          acc.push(s.name);
                        }
                        return acc;
                      }, [])}
                      className="w-full"
                    >
                      {mobileMenuSections.map((section) => (
                        <AccordionItem
                          key={section.name}
                          value={section.name}
                          className="border-foreground/6"
                        >
                          {section.children ? (
                            <>
                              <AccordionTrigger className="px-5 py-3.5 font-mono text-base uppercase tracking-wider text-foreground/75 dark:text-foreground/60 hover:text-foreground hover:no-underline">
                                {section.name}
                              </AccordionTrigger>
                              <AccordionContent className="pb-0">
                                {section.children.map((item) => (
                                  <Link
                                    key={item.name}
                                    href={item.href}
                                    target={item.external ? "_blank" : undefined}
                                    rel={item.external ? "noreferrer" : undefined}
                                    onClick={() => setMobileMenuOpen(false)}
                                    className={cn(
                                      "flex items-center gap-2.5 pl-9 pr-5 py-2.5 transition-colors font-mono text-sm uppercase tracking-wider",
                                      isActivePrefix(item.path || item.href)
                                        ? "text-foreground bg-foreground/4"
                                        : "text-foreground/60 dark:text-foreground/45 hover:text-foreground hover:bg-foreground/3",
                                    )}
                                  >
                                    {item.name}
                                  </Link>
                                ))}
                              </AccordionContent>
                            </>
                          ) : (
                            <Link
                              href={section.href!}
                              onClick={() => setMobileMenuOpen(false)}
                              className={cn(
                                "flex items-center gap-2.5 px-5 py-3.5 transition-colors font-mono text-base uppercase tracking-wider",
                                isActive(section.href!)
                                  ? "text-foreground bg-foreground/4"
                                  : "text-foreground/75 dark:text-foreground/60 hover:text-foreground",
                              )}
                            >
                              {section.name}
                            </Link>
                          )}
                        </AccordionItem>
                      ))}
                    </Accordion>
                  </>
                )}
              </div>

              {!(isDocs && mobileView === "docs") && (
                <div className="shrink-0 border-t border-foreground/[0.06] bg-background px-5 py-4">
                  <Link
                    href="/docs/getting-started"
                    onClick={() => setMobileMenuOpen(false)}
                    className="flex items-center justify-center gap-1.5 w-full py-3 bg-foreground text-background font-mono text-sm uppercase tracking-wider transition-opacity hover:opacity-90"
                  >
                    get-started
                    <svg className="h-2.5 w-2.5 opacity-50" viewBox="0 0 10 10" fill="none">
                      <path d="M1 9L9 1M9 1H3M9 1V7" stroke="currentColor" strokeWidth="1.2" />
                    </svg>
                  </Link>
                </div>
              )}
            </div>
          </m.div>
        )}
      </AnimatePresence>
    </LazyMotion>
  );
}
