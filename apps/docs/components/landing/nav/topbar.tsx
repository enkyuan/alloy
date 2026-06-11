"use client";

import Link from "next/link";
import { LazyMotion, domAnimation, m } from "motion/react";
import { RiSearch2Line } from "@remixicon/react";
import { ThemeToggle } from "@components/theme-toggle";
import { CloseIcon, HamburgerIcon } from "@components/icons";

interface TopbarProps {
  isKnownPage: boolean;
  isDocs: boolean;
  mobileMenuOpen: boolean;
  onMobileMenuToggle: () => void;
  onSearch?: () => void;
  leftPane?: React.ReactNode;
}

export function Topbar({
  isKnownPage,
  isDocs,
  mobileMenuOpen,
  onMobileMenuToggle,
  onSearch,
  leftPane,
}: TopbarProps) {
  return (
    <LazyMotion features={domAnimation}>
      <>
        {/* Left pane — logo (desktop, known pages) */}
        <m.div
          initial={{ x: -20, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          transition={{ duration: 0.28, ease: "easeOut" }}
          className={`${isKnownPage ? "lg:flex" : "lg:hidden"} hidden h-(--landing-topbar-height) shrink-0 items-stretch pointer-events-auto transition-[width] duration-300 ease-out`}
        >
          <Link
            href="/"
            className="flex h-full items-center gap-1 px-4 py-3 transition-colors duration-150"
          >
            {leftPane}
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
            {leftPane}
          </Link>
          <div className="flex items-center gap-1 pr-2">
            {isDocs && onSearch && (
              <button
                type="button"
                onClick={onSearch}
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
              onClick={onMobileMenuToggle}
              className="flex items-center justify-center size-8 text-foreground/75 dark:text-foreground/60 hover:text-foreground/85 transition-colors"
            >
              {mobileMenuOpen ? <CloseIcon /> : <HamburgerIcon />}
            </button>
          </div>
        </m.div>
      </>
    </LazyMotion>
  );
}
