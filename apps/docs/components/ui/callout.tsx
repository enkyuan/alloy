import type { ReactNode } from "react";

export function Callout({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className="my-4 rounded-md border border-border bg-card px-4 py-3 text-card-foreground shadow-sm">
      {title ? <p className="mb-1 font-medium">{title}</p> : null}
      <div className="text-sm text-muted-foreground">{children}</div>
    </div>
  );
}
