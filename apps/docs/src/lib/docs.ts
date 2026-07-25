import type { CollectionEntry } from "astro:content";
import { navigationItems } from "@/data/navigation";

export function docSlug(id: string): string | undefined {
  if (id === "index") return undefined;
  return id.endsWith("/index") ? id.slice(0, -"/index".length) : id;
}

export function docHref(id: string): string {
  const slug = docSlug(id);
  return slug === undefined ? "/docs" : `/docs/${slug}`;
}

export function adjacentDocs(currentHref: string): {
  previous?: (typeof navigationItems)[number];
  next?: (typeof navigationItems)[number];
} {
  const docsOnly = navigationItems.filter((item) => item.href.startsWith("/docs"));
  const index = docsOnly.findIndex((item) => item.href === currentHref);

  if (index === -1) return {};

  return {
    previous: docsOnly[index - 1],
    next: docsOnly[index + 1],
  };
}

export function docMarkdown(entry: CollectionEntry<"docs">): string {
  return `# ${entry.data.title}

${entry.data.description}

${entry.body}`;
}
