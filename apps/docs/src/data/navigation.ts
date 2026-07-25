export interface NavigationItem {
  href: string;
  label: string;
  status?: "wip";
}

export interface NavigationSection {
  label?: string;
  items: NavigationItem[];
}

export const navigation: NavigationSection[] = [
  {
    items: [
      { href: "/", label: "Overview" },
      { href: "/docs", label: "Introduction" },
      { href: "/docs/install", label: "Install", status: "wip" },
      { href: "/docs/getting-started", label: "Getting Started", status: "wip" },
      { href: "/docs/cli", label: "CLI" },
      { href: "/docs/integrations", label: "Integrations" },
      { href: "/docs/architecture", label: "Architecture" },
    ],
  },
  {
    label: "Concepts",
    items: [
      { href: "/docs/concepts/events", label: "Events" },
      { href: "/docs/concepts/session-state", label: "Session State" },
      { href: "/docs/concepts/runtime", label: "Runtime" },
      { href: "/docs/concepts/tool-registry", label: "Tool Registry" },
      { href: "/docs/concepts/event-bus", label: "Event Delivery" },
      { href: "/docs/concepts/providers", label: "Providers" },
    ],
  },
  {
    label: "Integrations",
    items: [
      { href: "/docs/integrations/github", label: "GitHub", status: "wip" },
      { href: "/docs/integrations/recovery-v1", label: "Recovery v1" },
    ],
  },
  {
    label: "Operations",
    items: [
      { href: "/docs/reference-service", label: "Reference Service", status: "wip" },
      { href: "/docs/troubleshooting", label: "Troubleshooting" },
    ],
  },
];

export const navigationItems = navigation.flatMap((section) => section.items);
