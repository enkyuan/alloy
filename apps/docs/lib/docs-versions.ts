export interface DocsVersion {
  label: string;
  version: string;
  branch: string;
  slug: string | null;
  badge: string | null;
}

export const docsVersions: DocsVersion[] = [
  {
    label: "Latest",
    version: "0.0",
    branch: "main",
    slug: null,
    badge: null,
  },
];

const latestVersion = docsVersions.find((v) => v.slug === null)!;

function getVersionBySlug(slug: string): DocsVersion | undefined {
  return docsVersions.find((v) => v.slug === slug);
}

export function versionedDocsHref(path: string, version: DocsVersion): string {
  if (!version.slug) return path;
  const stripped = path.replace(/^\/docs/, "");
  return `/docs/${version.slug}${stripped}`;
}

export function getVersionFromPathname(_pathname: string): DocsVersion {
  return latestVersion;
}

export function stripVersionPrefix(pathname: string, _version: DocsVersion): string {
  return pathname;
}

function scopeDocsHref(href: string | undefined, _version: DocsVersion): string | undefined {
  return href;
}

function resolveVersionFromSlug(slug: string[]): {
  version: DocsVersion;
  relSlug: string[];
} {
  return { version: latestVersion, relSlug: slug };
}
