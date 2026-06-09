import type { Folder, Root } from "fumadocs-core/page-tree";
import type { LucideIcon } from "lucide-react";
import { Book, Boxes, Cpu, GitBranch, Layers, Radio, Rocket, Server, Wrench } from "lucide-react";
import type { ReactNode, SVGProps } from "react";

export interface SubpageItem {
  title: string;
  href?: string;
  icon?: ((props?: SVGProps<any>) => ReactNode) | LucideIcon;
  group?: boolean;
}

export interface ListItem {
  title: string;
  href?: string;
  icon: ((props?: SVGProps<any>) => ReactNode) | LucideIcon;
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
  Icon: ((props?: SVGProps<any>) => ReactNode) | LucideIcon;
  isNew?: boolean;
  list: ListItem[];
}

export function getPageTree(): Root {
  return {
    $id: "root",
    name: "docs",
    children: [
      {
        type: "folder",
        root: true,
        name: "Docs",
        description: "get started, concepts, and plugins.",
        children: contents.map(contentToPageTree),
      },
      {
        type: "folder",
        root: true,
        name: "Examples",
        description: "exmaples and guides.",
        children: examples.map(contentToPageTree),
      },
    ],
  };
}

function contentToPageTree(content: Content): Folder {
  return {
    type: "folder",
    icon: <content.Icon />,
    name: content.title,
    index: content.href
      ? {
          icon: <content.Icon />,
          name: content.title,
          type: "page",
          url: content.href,
        }
      : undefined,
    children: content.list
      .filter((item) => !item.group && (item.href || item.separator))
      .filter((item) => !item.external)
      .map((item) =>
        item.separator
          ? ({
              type: "separator",
              name: item.title,
            } as const)
          : ({
              type: "page",
              url: item.href!,
              name: item.title,
              icon: <item.icon />,
            } as const),
      ),
  };
}

export const contents: Content[] = [
  {
    title: "Get Started",
    Icon: Rocket,
    list: [
      { title: "Introduction", href: "/docs", icon: Book },
      { title: "Getting Started", href: "/docs/getting-started", icon: Rocket },
      { title: "Architecture", href: "/docs/architecture", icon: Layers },
      {
        title: "Reference Service",
        href: "/docs/reference-service",
        icon: Server,
      },
    ],
  },
  {
    title: "Concepts",
    Icon: Boxes,
    list: [
      { title: "Events", href: "/docs/concepts/events", icon: Radio },
      {
        title: "Session State",
        href: "/docs/concepts/session-state",
        icon: GitBranch,
      },
      {
        title: "Tool Registry",
        href: "/docs/concepts/tool-registry",
        icon: Wrench,
      },
      { title: "Event Bus", href: "/docs/concepts/event-bus", icon: Boxes },
      { title: "Providers", href: "/docs/concepts/providers", icon: Cpu },
    ],
  },
];

export const examples: Content[] = [];
