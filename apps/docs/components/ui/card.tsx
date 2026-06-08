import Link from "next/link";
import type { ReactNode } from "react";

export function Cards({ children }: { children: ReactNode }) {
  return <div className="grid gap-3 sm:grid-cols-2 my-4">{children}</div>;
}

export function Card({
  title,
  description,
  href,
}: {
  title: string;
  description?: string;
  href: string;
}) {
  return (
    <Link
      href={href}
      className="rounded-md border border-border bg-card p-4 text-card-foreground no-underline shadow-sm transition-colors hover:bg-accent hover:text-accent-foreground"
    >
      <p className="font-medium">{title}</p>
      {description ? <p className="mt-1 text-sm text-muted-foreground">{description}</p> : null}
    </Link>
  );
}
