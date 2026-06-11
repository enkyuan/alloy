"use client";

import { AnimatePresence, LazyMotion, domAnimation, m } from "motion/react";
import { RiArrowDownSLine, RiArrowRightUpLongLine, RiSearch2Line } from "@remixicon/react";
import Link from "next/link";
import { cn } from "@lib/utils";
import { usePathname } from "next/navigation";
import { useNav } from "@lib/landing/use-nav";
import { useMobile } from "@hooks/use-mobile";
import { useDropdown } from "@hooks/use-dropdown";
import { ThemeToggle } from "@components/theme-toggle";
import { AgentkitWordmark } from "@components/icons/logo";
import { AgentPayLogo } from "@components/icons/agentpay";
import {
  ArrowUpRightIcon,
  ChevronDownSmallIcon,
  CloseIcon,
  HamburgerIcon,
} from "@components/icons";
import { contents } from "@lib/sidebar-config";
import { ResourcesDropdown } from "./dropdowns";
import { DocsSidebarItem, MobileViewToggle } from "./helpers";
import { mobileMenuSections, navFiles, navTabs } from "@lib/landing/nav-sections";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@components/ui/accordion";
import { getVersionFromPathname, versionedDocsHref } from "@lib/docs-versions";

// react-doctor-disable-next-line react-doctor/no-giant-component
export function Nav() {
  const pathname = usePathname() || "/";
  const { isDocs, isResourcePage, isKnownPage, isActive, isActivePrefix, styles } =
    useNav(pathname);
  const { open: resourcesOpen, openDropdown, closeDropdown } = useDropdown();
  const {
    open: mobileMenuOpen,
    setOpen: setMobileMenuOpen,
    view: mobileView,
    setView: setMobileView,
    docSection: mobileDocSection,
    setDocSection: setMobileDocSection,
    openMenu: openMobileMenu,
  } = useMobile(pathname, isDocs);

  const currentVersion = getVersionFromPathname(pathname);
  const prefixHref = (href: string) => versionedDocsHref(href, currentVersion);

  return (
    <LazyMotion features={domAnimation}>
      <>
        {/* ── Topbar ──────────────────────────────────────────────── */}
        <div className="fixed inset-x-0 top-0 z-[99] flex items-start pointer-events-none">
          {/* Left pane — logo (desktop, known pages) */}
          <m.div
            initial={{ x: -20, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            transition={{ duration: 0.28, ease: "easeOut" }}
            className={`${styles.leftPaneWidthClass} hidden ${isKnownPage ? "lg:flex" : "lg:hidden"} h-(--landing-topbar-height) shrink-0 items-stretch pointer-events-auto transition-[width] duration-300 ease-out`}
          >
            <Link
              href="/"
              className="flex h-full items-center gap-1 px-4 py-3 transition-colors duration-150"
            >
              <AgentkitWordmark />
            </Link>
          </m.div>

          {/* Mobile topbar */}
          <m.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.28, ease: "easeOut" }}
            className="flex lg:hidden items-center justify-between w-full h-(--landing-topbar-height) border-b border-foreground/[0.06] bg-background pointer-events-auto"
          >
            <Link
              href="/"
              className="flex h-full items-center gap-1 px-4 transition-colors duration-150"
            >
              <AgentkitWordmark />
            </Link>
            <div className="flex items-center gap-1 pr-2">
              {isDocs && (
                <button
                  type="button"
                  onClick={() =>
                    window.dispatchEvent(
                      new KeyboardEvent("keydown", { key: "k", metaKey: true, bubbles: true }),
                    )
                  }
                  className="flex items-center justify-center size-8 text-foreground/50 hover:text-foreground/80 transition-colors"
                  aria-label="Search"
                >
                  <RiSearch2Line className="size-4" />
                </button>
              )}
              <div className="flex items-center justify-center size-8 text-foreground/50 [&_button]:text-foreground/50 [&_button:hover]:text-foreground/80">
                <ThemeToggle />
              </div>
              <button
                type="button"
                onClick={() => (mobileMenuOpen ? setMobileMenuOpen(false) : openMobileMenu())}
                className="flex items-center justify-center size-8 text-foreground/75 dark:text-foreground/60 hover:text-foreground/85 transition-colors"
              >
                {mobileMenuOpen ? <CloseIcon /> : <HamburgerIcon />}
              </button>
            </div>
          </m.div>

          {/* Desktop nav tabs */}
          <m.div
            initial={{ y: -10, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: 0.28, delay: 0.04, ease: "easeOut" }}
            className={`hidden lg:flex flex-1 items-stretch min-w-0 h-[calc(var(--landing-topbar-height)+1px)] border-b bg-background pointer-events-auto ${styles.navBottomBorderClass}`}
          >
            {!isKnownPage && (
              <Link
                href="/"
                className={`flex h-full shrink-0 items-center gap-1 px-4 lg:px-7 py-3 border-r ${styles.tabDividerClass} transition-colors duration-150`}
              >
                <AgentkitWordmark />
              </Link>
            )}

            {navTabs.map((tab) => {
              const isFile = tab.type === "file";
              const active =
                isFile && (isActive(tab.href || "") || (tab.href === "/docs" && isDocs));
              const dropdownActive = !isFile && isResourcePage;

              return (
                <m.div
                  key={tab.id}
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.2, delay: tab.delay, ease: "easeOut" }}
                  className="relative flex-1"
                  onMouseEnter={isFile ? undefined : openDropdown}
                  onMouseLeave={isFile ? undefined : closeDropdown}
                >
                  {isFile ? (
                    <Link
                      href={tab.href || "#"}
                      target={tab.external ? "_blank" : undefined}
                      rel={tab.external ? "noreferrer" : undefined}
                      className={cn(
                        "group/tab relative flex items-center justify-center gap-1.5 px-2 xl:px-4 py-3 h-full border-r transition-colors duration-150",
                        styles.tabDividerClass,
                        active
                          ? `bg-background border-b-2 ${styles.activeTabBorderClass}`
                          : "hover:bg-foreground/[0.03]",
                      )}
                    >
                      <span
                        className={cn(
                          "whitespace-nowrap font-mono text-xs uppercase tracking-wider transition-colors duration-150",
                          active
                            ? "text-foreground"
                            : "text-foreground/65 dark:text-foreground/50 group-hover/tab:text-foreground/75",
                        )}
                      >
                        {tab.label}
                      </span>
                    </Link>
                  ) : (
                    <div
                      className={cn(
                        "group/tab flex items-center justify-center gap-1.5 px-2 xl:px-4 py-3 h-full cursor-pointer transition-colors duration-150",
                        dropdownActive
                          ? `bg-background border-b-2 ${styles.activeTabBorderClass}`
                          : resourcesOpen
                            ? "bg-foreground/[0.04]"
                            : "hover:bg-foreground/[0.03]",
                      )}
                    >
                      <span
                        className={cn(
                          "whitespace-nowrap font-mono text-xs uppercase tracking-wider transition-colors duration-150",
                          dropdownActive
                            ? "text-foreground"
                            : resourcesOpen
                              ? "text-foreground/80"
                              : "text-foreground/65 dark:text-foreground/50 group-hover/tab:text-foreground/75",
                        )}
                      >
                        {tab.label}
                      </span>
                      <ChevronDownSmallIcon
                        className={cn(
                          "text-foreground/55 dark:text-foreground/40 transition-transform duration-200",
                          resourcesOpen && "rotate-180",
                        )}
                      />
                      <ResourcesDropdown
                        isOpen={resourcesOpen}
                        dropdownBorderClass={styles.dropdownBorderClass}
                        onClose={() => closeDropdown()}
                      />
                    </div>
                  )}
                </m.div>
              );
            })}

            {/* AgentPay */}
            <m.div
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, delay: 0.2, ease: "easeOut" }}
              className="relative flex-1"
            >
              <a
                href=""
                target="_blank"
                rel="noreferrer"
                className={`group/tab flex items-center justify-center gap-2 px-5 xl:px-4 py-3 h-full cursor-pointer border-l border-r ${styles.tabDividerClass} transition-colors duration-150 hover:bg-foreground/[0.03]`}
              >
                <span className="whitespace-nowrap font-mono text-xs uppercase tracking-wider text-foreground/65 dark:text-foreground/50 group-hover/tab:text-foreground/75 transition-colors duration-150">
                  Try AgentPay
                </span>
                <span className="text-foreground/65 dark:text-foreground/50 group-hover/tab:text-foreground/75 [&_svg]:size-3 transition-colors duration-150">
                  <AgentPayLogo />
                </span>
              </a>
            </m.div>

            {/* Sign In */}
            <m.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.2, delay: 0.24, ease: "easeOut" }}
              className="flex shrink-0 items-stretch"
            >
              <m.a
                href=""
                target="_blank"
                rel="noreferrer"
                whileHover="hovered"
                className="flex items-center gap-2 px-5 py-3 cursor-pointer font-mono text-xs uppercase tracking-wider bg-foreground text-background transition-opacity duration-150 hover:opacity-90"
              >
                <span>Sign In</span>
                <m.span
                  variants={{
                    hovered: { x: 1, y: -2, transition: { duration: 0.2, ease: "easeOut" } },
                  }}
                  className="flex items-center"
                >
                  <RiArrowRightUpLongLine size={14} />
                </m.span>
              </m.a>
            </m.div>
          </m.div>
        </div>

        {/* ── Mobile overlay ───────────────────────────────────────── */}
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
                      <MobileViewToggle
                        direction="menu"
                        label="Menu"
                        onClick={() => setMobileView("nav")}
                      />
                      <div className="flex flex-col">
                        {contents.map((section, index) => (
                          <div key={section.title}>
                            <button
                              type="button"
                              onClick={() =>
                                setMobileDocSection((prev) => (prev === index ? -1 : index))
                              }
                              className={cn(
                                "border-b border-foreground/6 w-full text-left flex gap-2 items-center px-5 py-3 transition-colors font-medium text-sm tracking-wider",
                                mobileDocSection === index
                                  ? "text-foreground bg-foreground/3"
                                  : "text-foreground/70 hover:text-foreground hover:bg-foreground/3",
                              )}
                            >
                              <section.Icon size={18} />
                              <span className="grow">{section.title}</span>
                              <RiArrowDownSLine
                                size={16}
                                className={cn(
                                  "shrink-0 text-muted-foreground transition-transform duration-200",
                                  mobileDocSection === index && "rotate-180",
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
                                  {section.list.map((item, i) => (
                                    <DocsSidebarItem
                                      key={item.href ?? `sep-${i}`}
                                      item={item}
                                      index={i}
                                      pathname={pathname}
                                      prefixHref={prefixHref}
                                      onClose={() => setMobileMenuOpen(false)}
                                    />
                                  ))}
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
                        <MobileViewToggle
                          direction="back"
                          label="Docs"
                          onClick={() => setMobileView("docs")}
                        />
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
                          if (s.children?.some((item) => isActivePrefix(item.path || item.href)))
                            acc.push(s.name);
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
                      <ArrowUpRightIcon className="opacity-50" />
                    </Link>
                  </div>
                )}
              </div>
            </m.div>
          )}
        </AnimatePresence>
      </>
    </LazyMotion>
  );
}
