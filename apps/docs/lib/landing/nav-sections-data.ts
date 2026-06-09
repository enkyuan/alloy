import { History, PencilLine, Scale } from "lucide-react";
import type {
  LinkResource,
  MobileMenuSection,
  NavFileItem,
  ProductItem,
} from "@lib/landing/nav-data";
import {
  CommunityIcon,
  FrameworkLogoIcon,
  InfraLogoIcon,
  ScribblePattern,
  TimelinePattern,
  VerticalLinesPattern,
} from "@components/landing/nav/patterns";

export const navFiles: NavFileItem[] = [
  { name: "readme", href: "/" },
  { name: "docs", href: "/docs" },
];

export const products: ProductItem[] = [
  {
    title: "SDK",
    tagline: "Open source",
    description:
      "The embeddable agent runtime. Event-sourced core, tool registry, and pluggable LLM providers.",
    href: "/docs/getting-started",
    activatesTab: false,
    Icon: FrameworkLogoIcon,
    Pattern: VerticalLinesPattern,
    patternClassName:
      "absolute inset-0 w-full h-full text-primary/10 pointer-events-none [mask-image:linear-gradient(to_left,black_0%,transparent_40%)]",
  },
  {
    title: "Modalities",
    tagline: "Voice & RAG",
    description: "STT/TTS modalities, retrieval-augmented generation, and tool generation.",
    href: "/docs",
    activatesTab: false,
    Icon: InfraLogoIcon,
    Pattern: VerticalLinesPattern,
    patternClassName:
      "absolute inset-0 w-full h-full text-primary/10 pointer-events-none [mask-image:linear-gradient(to_left,black_0%,transparent_40%)]",
  },
];

export const featuredResources: ProductItem[] = [
  {
    title: "Docs",
    tagline: "Reference",
    description: "Guides, API reference, and examples",
    href: "/docs",
    Icon: PencilLine,
    Pattern: ScribblePattern,
    patternClassName:
      "absolute right-3 top-3 text-foreground/30 group-hover/p:text-foreground/60 transition-colors duration-200 pointer-events-none",
  },
  {
    title: "GitHub",
    tagline: "Source",
    description: "Browse the source and contribute",
    href: "https://github.com/enkyuan/alloy",
    Icon: History,
    Pattern: TimelinePattern,
    patternClassName:
      "absolute right-3 top-3 text-foreground/30 group-hover/p:text-foreground/60 transition-colors duration-200 pointer-events-none",
  },
];

export const linkResources: LinkResource[] = [
  { title: "Docs", href: "/docs", Icon: CommunityIcon },
  { title: "GitHub", href: "https://github.com/enkyuan/alloy", Icon: Scale },
];

export const resourceFiles: NavFileItem[] = [
  ...featuredResources.map((r) => ({
    name: r.title.toLowerCase(),
    href: r.href,
  })),
  ...linkResources.map((r) => ({
    name: r.title.toLowerCase(),
    href: r.href,
  })),
];

export const mobileMenuSections: MobileMenuSection[] = [
  {
    name: "products",
    children: products.map((p) => ({
      name: p.title.toLowerCase(),
      href: p.href,
    })),
  },
  { name: "resources", children: resourceFiles },
];
