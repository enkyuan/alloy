"use client";

import { useEffect, useState } from "react";

const MOBILE_BREAKPOINT = 1024;

/** Returns true when the viewport is narrower than the lg breakpoint (1024px). */
export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`);
    setIsMobile(mql.matches);
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  return isMobile;
}

/** Calls `onDesktop` when the viewport crosses into lg (≥1024px). */
export function useOnDesktop(onDesktop: () => void): void {
  useEffect(() => {
    const mql = window.matchMedia(`(min-width: ${MOBILE_BREAKPOINT}px)`);
    const handler = (e: MediaQueryListEvent) => {
      if (e.matches) onDesktop();
    };
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, [onDesktop]);
}
