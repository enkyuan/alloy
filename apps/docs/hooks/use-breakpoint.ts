"use client";

import { useEffect, useState } from "react";

const LG = 1024;

export function useBreakpoint(onDesktop?: () => void) {
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${LG - 1}px)`);
    setIsMobile(mql.matches);
    const handler = (e: MediaQueryListEvent) => {
      setIsMobile(e.matches);
      if (!e.matches) onDesktop?.();
    };
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, [onDesktop]);

  return isMobile;
}
