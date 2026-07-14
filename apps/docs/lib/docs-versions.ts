export interface DocsVersion {
  label: string;
  version: string;
  branch: string;
  slug: string | null;
  badge: string | null;
}

export const docsVersions: DocsVersion[] = [
  {
    label: "0.2 beta candidate",
    version: "0.2",
    branch: "main",
    slug: null,
    badge: "pre-release",
  },
];

const latestVersion = docsVersions.find((v) => v.slug === null)!;

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
