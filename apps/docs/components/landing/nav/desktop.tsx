"use client";

import Link from "next/link";
import { LazyMotion, domAnimation, m } from "motion/react";
import { cn } from "@lib/utils";
import { ChevronDownSmallIcon } from "@components/icons";
import { ResourcesDropdown } from "./dropdowns";
import { navTabs } from "@lib/landing/nav-sections";

const STATE_ACTIVE = "text-foreground";
const STATE_INACTIVE = "text-foreground/65 dark:text-foreground/50";
const STATE_INACTIVE_HOVER = "text-foreground/75";

interface DesktopNavTabsProps {
  isKnownPage: boolean;
  isDocs: boolean;
  isResourcePage: boolean;
  resourcesOpen: boolean;
  openDropdown: () => void;
  closeDropdown: () => void;
  isActive: (path: string) => boolean;
  styles: {
    tabDividerClass: string;
    activeTabBorderClass: string;
    navBottomBorderClass: string;
    dropdownBorderClass: string;
  };
}

export function DesktopNavTabs({
  isKnownPage,
  isDocs,
  isResourcePage,
  resourcesOpen,
  openDropdown,
  closeDropdown,
  isActive,
  styles,
}: DesktopNavTabsProps) {
  return (
    <LazyMotion features={domAnimation}>
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
            {/* Logo */}
          </Link>
        )}

        {navTabs.map((tab) => {
          const isFile = tab.type === "file";
          const active = isFile && (isActive(tab.href || "") || (tab.href === "/docs" && isDocs));
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
                        ? STATE_ACTIVE
                        : `${STATE_INACTIVE} group-hover/tab:${STATE_INACTIVE_HOVER}`,
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
                        ? STATE_ACTIVE
                        : resourcesOpen
                          ? "text-foreground/80"
                          : `${STATE_INACTIVE} group-hover/tab:${STATE_INACTIVE_HOVER}`,
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
                    onClose={closeDropdown}
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
          </m.a>
        </m.div>
      </m.div>
    </LazyMotion>
  );
}
