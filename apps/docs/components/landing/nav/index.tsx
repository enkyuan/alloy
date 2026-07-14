"use client";

import { AnimatePresence, m } from "motion/react";
import { RiArrowDownSLine } from "@remixicon/react";
import Link from "next/link";
import { cn } from "@lib/utils";
import { usePathname } from "next/navigation";
import { useNav } from "@lib/landing/use-nav";
import { useMobile } from "@hooks/use-mobile";
import { useDropdown } from "@hooks/use-dropdown";
import { KajiWordmark } from "@components/icons/logo";
import { ArrowUpRightIcon } from "@components/icons";
import { contents } from "@lib/sidebar-config";
import { DocsSidebarItem, MobileViewToggle } from "./helpers";
import { mobileMenuSections, navFiles } from "@lib/landing/nav-sections";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@components/ui/accordion";
import { getVersionFromPathname, versionedDocsHref } from "@lib/docs-versions";
import type { ListItem } from "@lib/sidebar-config";
import { Topbar } from "./topbar";
import { DesktopNavTabs } from "./desktop";

function MobileDocsSections({
  setMobileMenuOpen,
  mobileDocSection,
  setMobileDocSection,
  pathname,
  prefixHref,
}: {
  setMobileMenuOpen: (open: boolean) => void;
  mobileDocSection: number;
  setMobileDocSection: (idx: number | ((prev: number) => number)) => void;
  pathname: string;
  prefixHref: (href: string) => string;
}) {
  return (
    <div className="flex flex-col">
      {contents.map((section, index) => (
        <div key={section.title}>
          <button
            type="button"
            onClick={() => setMobileDocSection((prev) => (prev === index ? -1 : index))}
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
                {section.list.map((item: ListItem, i) => (
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
  );
}

function MobileMenuSectionsNav({
  isDocs,
  setMobileMenuOpen,
  isActive,
  isActivePrefix,
}: {
  isDocs: boolean;
  setMobileMenuOpen: (open: boolean) => void;
  isActive: (path: string) => boolean;
  isActivePrefix: (path: string) => boolean;
}) {
  return (
    <>
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
          if (s.children?.some((item) => isActivePrefix(item.path || item.href))) acc.push(s.name);
          return acc;
        }, [])}
        className="w-full"
      >
        {mobileMenuSections.map((section) => (
          <AccordionItem key={section.name} value={section.name} className="border-foreground/6">
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
  );
}

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
    <>
      <div className="fixed inset-x-0 top-0 z-[99] flex items-start pointer-events-none">
        <Topbar
          isKnownPage={isKnownPage}
          isDocs={isDocs}
          mobileMenuOpen={mobileMenuOpen}
          onMobileMenuToggle={() => (mobileMenuOpen ? setMobileMenuOpen(false) : openMobileMenu())}
          onSearch={() =>
            window.dispatchEvent(
              new KeyboardEvent("keydown", { key: "k", metaKey: true, bubbles: true }),
            )
          }
          leftPane={<KajiWordmark />}
          leftPaneWidthClass={styles.leftPaneWidthClass}
        />

        <DesktopNavTabs
          isKnownPage={isKnownPage}
          isDocs={isDocs}
          isResourcePage={isResourcePage}
          resourcesOpen={resourcesOpen}
          openDropdown={openDropdown}
          closeDropdown={closeDropdown}
          isActive={isActive}
          styles={styles}
        />
      </div>

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
                    <MobileDocsSections
                      setMobileMenuOpen={setMobileMenuOpen}
                      mobileDocSection={mobileDocSection}
                      setMobileDocSection={setMobileDocSection}
                      pathname={pathname}
                      prefixHref={prefixHref}
                    />
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
                    <MobileMenuSectionsNav
                      isDocs={isDocs}
                      setMobileMenuOpen={setMobileMenuOpen}
                      isActive={isActive}
                      isActivePrefix={isActivePrefix}
                    />
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
  );
}
