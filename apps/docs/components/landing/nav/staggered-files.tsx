"use client";

import { LazyMotion, domAnimation, m } from "framer-motion";
import { Search } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ThemeToggle } from "@components/theme-toggle";
import { AgentkitWordmark } from "../../icons/logo";
import { AgentPayLogo } from "../../icons/agentpay";
import { contents } from "../../sidebar-content";
import LogoContextMenu from "../shared/logo-menu";
import { NavMobileMenu } from "./mobile-menu";
import { ResourcesDropdown } from "./desktop-dropdowns";
import { mobileMenuSections, navFiles, resourceFiles } from "@lib/landing/nav-sections-data";

// react-doctor-disable-next-line prefer-useReducer, react-doctor/prefer-useReducer, react-doctor/no-giant-component
export function StaggeredNavFiles() {
  const pathname = usePathname() || "/";
  const [resourcesOpen, setResourcesOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [mobileView, setMobileView] = useState<"docs" | "nav">("docs");
  const [mobileDocSection, setMobileDocSection] = useState(-1);
  const resourcesTimeout = useRef<NodeJS.Timeout>(undefined);

  useEffect(() => {
    document.body.style.overflow = mobileMenuOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [mobileMenuOpen]);

  useEffect(() => {
    const mql = window.matchMedia("(min-width: 1024px)");
    const handler = () => {
      if (mql.matches) {
        setMobileMenuOpen(false);
      }
    };
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  const openResources = () => {
    clearTimeout(resourcesTimeout.current);
    setResourcesOpen(true);
  };
  const closeResources = () => {
    resourcesTimeout.current = setTimeout(() => setResourcesOpen(false), 150);
  };
  const isActive = useCallback((href: string) => pathname === href, [pathname]);
  const isActivePrefix = useCallback(
    (href: string) => pathname === href || pathname.startsWith(`${href}/`),
    [pathname],
  );
  const isDocs = pathname.startsWith("/docs");
  const isPricingPage = pathname === "/pricing";
  const isResourcePage =
    !isDocs &&
    resourceFiles.some((r) => {
      const matchPath = r.path || r.href;
      return pathname === matchPath || pathname.startsWith(`${matchPath}/`);
    });
  const isKnownPage =
    isActive("/") || isDocs || isPricingPage || isResourcePage || isActive("/enterprise");
  const isNarrowLeft = isDocs;
  const leftPaneWidthClass = isNarrowLeft
    ? "w-[22vw] max-w-[300px]"
    : isPricingPage || isResourcePage
      ? "w-[30%]"
      : "w-[40%]";
  const navBottomBorderClass = isNarrowLeft ? "border-foreground/5" : "";
  const tabDividerClass = isNarrowLeft ? "border-foreground/4" : "border-foreground/[0.06]";
  const activeTabBorderClass = isNarrowLeft ? "border-b-foreground/50" : "border-b-foreground/60";
  const dropdownBorderClass = isNarrowLeft ? "border-foreground/6" : "border-foreground/[0.08]";
  const _router = useRouter();
  return (
    <LazyMotion features={domAnimation}>
      <>
        <div className="fixed top-0 left-0 right-0 z-[99] flex items-start pointer-events-none">
          {/* Left — Logo */}
          <m.div
            initial={{ x: -20, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            transition={{ duration: 0.28, ease: "easeOut" }}
            className={`${leftPaneWidthClass} hidden ${isKnownPage ? "lg:flex" : "lg:hidden"} h-(--landing-topbar-height) items-stretch shrink-0 pointer-events-auto transition-[width] duration-300 ease-out`}
          >
            <Link
              href="/"
              className="flex h-full items-center gap-1 px-4 py-3 transition-colors duration-150"
            >
              <LogoContextMenu logo={<AgentkitWordmark />} />
            </Link>
          </m.div>

          {/* Mobile — Logo + hamburger */}
          <m.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.28, ease: "easeOut" }}
            className="lg:hidden flex items-center justify-between w-full h-(--landing-topbar-height) pointer-events-auto bg-background border-b border-foreground/[0.06]"
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
                  onClick={() => {
                    window.dispatchEvent(
                      new KeyboardEvent("keydown", {
                        key: "k",
                        metaKey: true,
                        bubbles: true,
                      }),
                    );
                  }}
                  className="flex items-center justify-center size-8 text-foreground/50 hover:text-foreground/80 transition-colors"
                  aria-label="Search"
                >
                  <Search className="size-4" />
                </button>
              )}
              <div className="flex items-center justify-center size-8 text-foreground/50 [&_button]:text-foreground/50 [&_button:hover]:text-foreground/80">
                <ThemeToggle />
              </div>
              <button
                type="button"
                onClick={() => {
                  const opening = !mobileMenuOpen;
                  setMobileMenuOpen(opening);
                  if (opening) {
                    setMobileView(isDocs ? "docs" : "nav");
                    if (isDocs) {
                      const idx = contents.findIndex((s) => {
                        const prefix = s.expandSectionForPathPrefix;
                        if (prefix && (pathname === prefix || pathname.startsWith(`${prefix}/`))) {
                          return true;
                        }
                        return s.list.some(
                          (l) =>
                            l.href === pathname ||
                            (l.subpages?.length && pathname.startsWith(`${l.href}/`)),
                        );
                      });
                      setMobileDocSection(idx === -1 ? 0 : idx);
                    }
                  }
                }}
                className="flex items-center justify-center size-8 text-foreground/75 dark:text-foreground/60 hover:text-foreground/85 transition-colors"
              >
                {mobileMenuOpen ? (
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    width="18"
                    height="18"
                    viewBox="0 0 24 24"
                  >
                    <path
                      fill="currentColor"
                      d="M19 6.41L17.59 5L12 10.59L6.41 5L5 6.41L10.59 12L5 17.59L6.41 19L12 13.41L17.59 19L19 17.59L13.41 12z"
                    />
                  </svg>
                ) : (
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    width="18"
                    height="18"
                    viewBox="0 0 24 24"
                  >
                    <path fill="currentColor" d="M3 18h18v-2H3zm0-5h18v-2H3zm0-7v2h18V6z" />
                  </svg>
                )}
              </button>
            </div>
          </m.div>

          {/* Right — Nav tabs (desktop) */}
          <m.div
            initial={{ y: -10, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: 0.28, delay: 0.04, ease: "easeOut" }}
            className={`flex-1 hidden lg:flex h-[calc(var(--landing-topbar-height)+1px)] items-stretch border-b bg-background pointer-events-auto min-w-0 ${navBottomBorderClass}`}
          >
            {/* Inline logo when left pane is hidden */}
            {!isKnownPage && (
              <Link
                href="/"
                className={`flex h-full items-center gap-1 shrink-0 px-4 lg:px-7 py-3 border-r ${tabDividerClass} transition-colors duration-150`}
              >
                <LogoContextMenu logo={<AgentkitWordmark />} />
              </Link>
            )}
            {/* File tabs */}
            {navFiles.map((item, index) => {
              const active = isActive(item.path || item.href) || (item.href === "/docs" && isDocs);
              return (
                <m.div
                  key={item.name}
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{
                    duration: 0.2,
                    delay: 0.05 + index * 0.03,
                    ease: "easeOut",
                  }}
                  className="flex-1"
                >
                  <Link
                    href={item.href}
                    target={item.external ? "_blank" : undefined}
                    rel={item.external ? "noreferrer" : undefined}
                    className={`group/tab relative flex items-center justify-center gap-1.5 px-2 xl:px-4 py-3 h-full border-r ${tabDividerClass} transition-colors duration-150 ${
                      active
                        ? `bg-background border-b-2 ${activeTabBorderClass}`
                        : "bg-transparent hover:bg-foreground/[0.03]"
                    }`}
                  >
                    <span
                      className={`font-mono text-xs uppercase tracking-wider transition-colors duration-150 whitespace-nowrap ${
                        active
                          ? "text-foreground"
                          : "text-foreground/65 dark:text-foreground/50 group-hover/tab:text-foreground/75"
                      }`}
                    >
                      {item.name}
                    </span>
                  </Link>
                </m.div>
              );
            })}

            {/* Resources folder tab */}
            <m.div
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, delay: 0.17, ease: "easeOut" }}
              className="relative flex-1"
              onMouseEnter={openResources}
              onMouseLeave={closeResources}
            >
              <div
                className={`group/tab flex items-center justify-center gap-1.5 px-2 xl:px-4 py-3 h-full cursor-pointer transition-colors duration-150 ${
                  isResourcePage
                    ? `bg-background border-b-2 ${activeTabBorderClass}`
                    : resourcesOpen
                      ? "bg-foreground/[0.04]"
                      : "hover:bg-foreground/[0.03]"
                }`}
              >
                <span
                  className={`font-mono text-xs uppercase tracking-wider transition-colors duration-150 whitespace-nowrap ${
                    isResourcePage
                      ? "text-foreground"
                      : resourcesOpen
                        ? "text-foreground/80"
                        : "text-foreground/65 dark:text-foreground/50 group-hover/tab:text-foreground/75"
                  }`}
                >
                  resources
                </span>
                <svg
                  className={`h-2 w-2 text-foreground/55 dark:text-foreground/40 transition-transform duration-200 ${
                    resourcesOpen ? "rotate-180" : ""
                  }`}
                  viewBox="0 0 10 6"
                  fill="none"
                >
                  <path d="M1 1L5 5L9 1" stroke="currentColor" strokeWidth="1.2" />
                </svg>
              </div>

              <ResourcesDropdown
                isOpen={resourcesOpen}
                dropdownBorderClass={dropdownBorderClass}
                onClose={() => setResourcesOpen(false)}
              />
            </m.div>

            {/* AgentPay tab */}
            <m.div
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, delay: 0.22, ease: "easeOut" }}
              className="relative flex-1"
            >
              <a
                href="https://agentpay.ai"
                target="_blank"
                rel="noreferrer"
                className="group/tab flex items-center justify-center gap-1.5 px-2 xl:px-4 py-3 h-full cursor-pointer border-r border-foreground/[0.06] transition-colors duration-150 hover:bg-foreground/[0.03]"
              >
                <span className="text-foreground/80 dark:text-foreground/70 [&_svg]:w-4 [&_svg]:h-4">
                  <AgentPayLogo />
                </span>
                <span className="font-mono text-xs uppercase tracking-wider transition-colors duration-150 whitespace-nowrap text-foreground/65 dark:text-foreground/50 group-hover/tab:text-foreground/75">
                  agentpay
                </span>
              </a>
            </m.div>

            {/* Sign In CTA — always visible */}
            <m.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.2, delay: 0.24, ease: "easeOut" }}
              className="flex items-stretch shrink-0"
            >
              <a
                href="https://agentpay.ai"
                target="_blank"
                rel="noreferrer"
                className="flex items-center cursor-pointer gap-2 px-5 py-3 bg-foreground text-background hover:opacity-90 transition-colors duration-150"
              >
                <span className="font-mono text-xs uppercase tracking-wider">Sign In</span>
              </a>
            </m.div>
          </m.div>
        </div>

        <NavMobileMenu
          mobileMenuOpen={mobileMenuOpen}
          mobileView={mobileView}
          mobileDocSection={mobileDocSection}
          isDocs={isDocs}
          navFiles={navFiles}
          mobileMenuSections={mobileMenuSections}
          setMobileMenuOpen={setMobileMenuOpen}
          setMobileView={setMobileView}
          setMobileDocSection={setMobileDocSection}
        />
      </>
    </LazyMotion>
  );
}
