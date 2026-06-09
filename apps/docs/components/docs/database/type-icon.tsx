// TypeIcon — inline SVG icon for each column type in DatabaseTable.
import { cn } from "@lib/utils";

const typeAliases: Record<string, string> = {
  text: "string",
  integer: "number",
  int: "number",
  bigint: "number",
  float: "number",
  double: "number",
  decimal: "number",
  bool: "boolean",
  object: "json",
  timestamp: "date",
  datetime: "date",
};

export function TypeIcon({ type }: { type: string }) {
  const raw = type.toLowerCase().replace("[]", "");
  const t = typeAliases[raw] ?? raw;
  const className = "size-3 shrink-0";

  if (t === "string" || t === "text") {
    return (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={cn(className, "text-emerald-600")}
      >
        <path d="M4 7V4h16v3" />
        <path d="M9 20h6" />
        <path d="M12 4v16" />
      </svg>
    );
  }
  if (t === "boolean") {
    return (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={cn(className, "text-violet-600 dark:text-violet-500")}
      >
        <rect width="20" height="12" x="2" y="6" rx="6" />
        <circle cx="16" cy="12" r="2" />
      </svg>
    );
  }
  if (t === "date") {
    return (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={cn(className, "text-sky-600")}
      >
        <path d="M8 2v4" />
        <path d="M16 2v4" />
        <rect width="18" height="18" x="3" y="4" rx="2" />
        <path d="M3 10h18" />
      </svg>
    );
  }
  if (t === "number") {
    return (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={cn(className, "text-orange-500 dark:text-orange-600")}
      >
        <path d="M4 9h16" />
        <path d="M4 15h16" />
        <path d="M10 3L8 21" />
        <path d="M16 3l-2 18" />
      </svg>
    );
  }
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn(className, "text-foreground/40")}
    >
      <path d="M8 3H7a2 2 0 0 0-2 2v5a2 2 0 0 1-2 2 2 2 0 0 1 2 2v5a2 2 0 0 0 2 2h1" />
      <path d="M16 3h1a2 2 0 0 1 2 2v5a2 2 0 0 0 2 2 2 2 0 0 0-2 2v5a2 2 0 0 1-2 2h-1" />
    </svg>
  );
}
