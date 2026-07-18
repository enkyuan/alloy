import type { RemixiconComponentType } from "@remixicon/react";
import {
  RiBook2Line,
  RiBroadcastLine,
  RiCpuLine,
  RiGitBranchLine,
  RiPlugLine,
  RiRocket2Line,
  RiServerLine,
  RiStackFill,
  RiStackLine,
  RiTerminalBoxLine,
  RiToolsLine,
} from "@remixicon/react";

export interface SubpageItem {
  title: string;
  href?: string;
  icon?: RemixiconComponentType;
  group?: boolean;
}

export interface ListItem {
  title: string;
  href?: string;
  icon: RemixiconComponentType;
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
  Icon: RemixiconComponentType;
  isNew?: boolean;
  list: ListItem[];
}

export const contents: Content[] = [
  {
    title: "Get Started",
    Icon: RiRocket2Line,
    list: [
      { title: "Introduction", href: "/docs", icon: RiBook2Line },
      { title: "Install", href: "/docs/install", icon: RiRocket2Line },
      { title: "Getting Started", href: "/docs/getting-started", icon: RiRocket2Line },
      { title: "CLI", href: "/docs/cli", icon: RiTerminalBoxLine },
      {
        title: "Integrations",
        href: "/docs/integrations",
        icon: RiPlugLine,
        subpages: [
          {
            title: "GitHub",
            href: "/docs/integrations/github",
          },
          {
            title: "Recovery v1",
            href: "/docs/integrations/recovery-v1",
          },
        ],
      },
      { title: "Architecture", href: "/docs/architecture", icon: RiStackLine },
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
      { title: "Runtime", href: "/docs/concepts/runtime", icon: RiStackLine },
      {
        title: "Tool Registry",
        href: "/docs/concepts/tool-registry",
        icon: RiToolsLine,
      },
      { title: "Event Delivery", href: "/docs/concepts/event-bus", icon: RiStackFill },
      { title: "Providers", href: "/docs/concepts/providers", icon: RiCpuLine },
    ],
  },
  {
    title: "Operations",
    Icon: RiServerLine,
    list: [
      {
        title: "Reference Service",
        href: "/docs/reference-service",
        icon: RiServerLine,
      },
      {
        title: "Troubleshooting",
        href: "/docs/troubleshooting",
        icon: RiToolsLine,
      },
    ],
  },
];
