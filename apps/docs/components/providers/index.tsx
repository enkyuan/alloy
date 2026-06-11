"use client";

import type { ReactNode } from "react";
import { Toaster } from "sonner";
import dynamic from "next/dynamic";

const Agentation = dynamic(
  () => import("agentation").then((mod) => ({ default: mod.Agentation })),
  { ssr: false },
);

interface ProvidersProps {
  children: ReactNode;
  /** Mount Agentation dev overlay. Should only be true outside production. */
  withAgentation?: boolean;
}

export function Providers({ children, withAgentation = false }: ProvidersProps) {
  return (
    <>
      {children}
      <Toaster />
      {withAgentation && <Agentation />}
    </>
  );
}
