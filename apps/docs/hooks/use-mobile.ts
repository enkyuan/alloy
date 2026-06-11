"use client";

import { useEffect, useState } from "react";
import { useBreakpoint } from "@hooks/use-breakpoint";
import { contents } from "@lib/sidebar-config";

export function useMobile(pathname: string, isDocs: boolean) {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"docs" | "nav">("docs");
  const [docSection, setDocSection] = useState(-1);

  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  useBreakpoint(() => setOpen(false));

  const openMenu = () => {
    setOpen(true);
    setView(isDocs ? "docs" : "nav");
    if (isDocs) {
      const idx = contents.findIndex((s) => {
        const prefix = s.expandSectionForPathPrefix;
        if (prefix && (pathname === prefix || pathname.startsWith(`${prefix}/`))) return true;
        return s.list.some(
          (l) => l.href === pathname || (l.subpages?.length && pathname.startsWith(`${l.href}/`)),
        );
      });
      setDocSection(idx === -1 ? 0 : idx);
    }
  };

  return { open, setOpen, view, setView, docSection, setDocSection, openMenu };
}
