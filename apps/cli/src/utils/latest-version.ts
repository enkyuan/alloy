export async function fetchLatestVersion(
  pkg: string,
  signal?: AbortSignal,
): Promise<string | null> {
  try {
    const r = await fetch(`https://registry.npmjs.org/${pkg}/latest`, { signal });
    if (!r.ok) return null;
    const json = (await r.json()) as { version?: string };
    return json.version ?? null;
  } catch {
    return null;
  }
}
