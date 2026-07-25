import { getCollection } from "astro:content";
import { docHref, docMarkdown } from "@/lib/docs";

export async function GET() {
  const entries = await getCollection("docs");
  const body = entries
    .map((entry) => `${docMarkdown(entry)}\n\nSource: ${docHref(entry.id)}`)
    .join("\n\n---\n\n");

  return new Response(body, {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}
