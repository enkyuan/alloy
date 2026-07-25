import { getCollection, type CollectionEntry } from "astro:content";
import { docMarkdown, docSlug } from "@/lib/docs";

interface Props {
  entry: CollectionEntry<"docs">;
}

export async function getStaticPaths() {
  const entries = await getCollection("docs");

  return entries.map((entry) => ({
    params: { slug: docSlug(entry.id) },
    props: { entry },
  }));
}

export function GET({ props }: { props: Props }) {
  return new Response(docMarkdown(props.entry), {
    headers: { "Content-Type": "text/markdown; charset=utf-8" },
  });
}
