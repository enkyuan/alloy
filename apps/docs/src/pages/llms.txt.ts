import { getCollection } from "astro:content";
import { docHref } from "@/lib/docs";

export async function GET() {
  const entries = await getCollection("docs");
  const index = entries
    .map((entry) => `${entry.data.title}: ${entry.data.description}\n${docHref(entry.id)}`)
    .join("\n\n");

  return new Response(`# Kaji documentation\n\n${index}\n`, {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}
