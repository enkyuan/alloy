import type { ReactNode, SVGProps } from "react";
import {
  RiBook2Line,
  RiBroadcastLine,
  RiCpuLine,
  RiGitBranchLine,
  RiRocket2Line,
  RiServerLine,
  RiStackFill,
  RiStackLine,
  RiToolsLine,
} from "@/components/icons/remix";

export interface SubpageItem {
  title: string;
  href?: string;
  icon?: (props?: SVGProps<any>) => ReactNode;
  group?: boolean;
}

export interface ListItem {
  title: string;
  href?: string;
  icon: (props?: SVGProps<any>) => ReactNode;
  group?: boolean;
  separator?: boolean;
  isNew?: boolean;
  subpages?: SubpageItem[];
  /** Navigates to a non-docs URL (e.g. `/llms.txt`) without a docs MDX page. */
  external?: boolean;
}

interface Content {
  title: string;
  href?: string;
  /** Expand this sidebar section when pathname is this URL or a child path (no extra nav row). */
  expandSectionForPathPrefix?: string;
  Icon: (props?: SVGProps<any>) => ReactNode;
  isNew?: boolean;
  list: ListItem[];
}

export const contents: Content[] = [
  {
    title: "Get Started",
    Icon: RiRocket2Line,
    list: [
      { title: "Introduction", href: "/docs", icon: RiBook2Line },
      { title: "Getting Started", href: "/docs/getting-started", icon: RiRocket2Line },
      { title: "Architecture", href: "/docs/architecture", icon: RiStackLine },
      {
        title: "Reference Service",
        href: "/docs/reference-service",
        icon: RiServerLine,
      },
    ],
  },
  {
    title: "Concepts",
    Icon: RiStackFill,
    list: [
      { title: "Events", href: "/docs/concepts/events", icon: RiBroadcastLine },
      {
        title: "Session State",
        href: "/docs/concepts/session-state",
        icon: RiGitBranchLine,
      },
      {
        title: "Tool Registry",
        href: "/docs/concepts/tool-registry",
        icon: RiToolsLine,
      },
      { title: "Event Bus", href: "/docs/concepts/event-bus", icon: RiStackFill },
      { title: "Providers", href: "/docs/concepts/providers", icon: RiCpuLine },
    ],
  },
];
