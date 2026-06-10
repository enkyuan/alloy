"use client";

import dynamic from "next/dynamic";

const Agentation = dynamic(
  () => import("agentation").then((mod) => ({ default: mod.Agentation })),
  {
    ssr: false,
  },
);

export function AgentationClient() {
  return <Agentation />;
}
