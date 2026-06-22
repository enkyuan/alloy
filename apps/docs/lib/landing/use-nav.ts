"use client";

import { useCallback } from "react";
import { resourceFiles } from "@lib/landing/nav-sections";

export type NavStyles = {
  leftPaneWidthClass: string;
  navBottomBorderClass: string;
  tabDividerClass: string;
  activeTabBorderClass: string;
  dropdownBorderClass: string;
};

export type UseNavResult = {
  isDocs: boolean;
  isPricingPage: boolean;
  isResourcePage: boolean;
  isKnownPage: boolean;
  isActive: (href: string) => boolean;
  isActivePrefix: (href: string) => boolean;
  styles: NavStyles;
};

export function useNav(pathname: string): UseNavResult {
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
  const styles: NavStyles = {
    leftPaneWidthClass: isNarrowLeft
      ? "w-[22vw] max-w-[300px]"
      : isPricingPage || isResourcePage
        ? "w-[30%]"
        : "w-[40%]",
    navBottomBorderClass: isNarrowLeft ? "border-foreground/5" : "border-foreground/[0.1]",
    tabDividerClass: isNarrowLeft ? "border-foreground/4" : "border-foreground/[0.06]",
    activeTabBorderClass: isNarrowLeft ? "border-b-foreground/50" : "border-b-foreground/60",
    dropdownBorderClass: isNarrowLeft ? "border-foreground/6" : "border-foreground/[0.08]",
  };

  return { isDocs, isPricingPage, isResourcePage, isKnownPage, isActive, isActivePrefix, styles };
}
