"use client";

import { ExternalLink } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";
import { useState } from "react";
import { Button } from "@components/ui/button";
import { cn } from "@lib/utils";
import { DatabaseTable } from "./database/table";

export { DatabaseTable };

// ─── GenerateSecret ──────────────────────────────────────────────────────────

function generateRandomString(length: number): string {
  const chars = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  let result = "";
  const array = new Uint8Array(length);
  crypto.getRandomValues(array);
  for (let i = 0; i < length; i++) {
    result += chars[array[i] % chars.length];
  }
  return result;
}

export function GenerateSecret() {
  const [generated, setGenerated] = useState(false);
  return (
    <div className="my-2">
      <Button
        variant="outline"
        size="sm"
        disabled={generated}
        onClick={() => {
          const elements = document.querySelectorAll("pre code span.line span");
          for (let i = 0; i < elements.length; i++) {
            if (elements[i].textContent === "AGENTKIT_SECRET=") {
              elements[i].textContent = `AGENTKIT_SECRET=${generateRandomString(32)}`;
              setGenerated(true);
              setTimeout(() => {
                elements[i].textContent = "AGENTKIT_SECRET=";
                setGenerated(false);
              }, 5000);
            }
          }
        }}
      >
        {generated ? "Generated" : "Generate Secret"}
      </Button>
    </div>
  );
}

// ─── APIMethod ───────────────────────────────────────────────────────────────

export function APIMethod({
  children,
  path,
  method = "GET",
}: {
  children?: ReactNode;
  path?: string;
  method?: string;
  [key: string]: unknown;
}) {
  return (
    <div className="my-4 rounded-lg border bg-card p-4">
      {path && (
        <div className="mb-3 flex items-center gap-2 font-mono text-sm">
          <span className="rounded bg-primary/10 px-2 py-0.5 text-xs font-semibold uppercase text-primary">
            {method}
          </span>
          <span className="text-muted-foreground/80">{path}</span>
        </div>
      )}
      <div className="prose-sm">{children}</div>
    </div>
  );
}

// ─── Endpoint ────────────────────────────────────────────────────────────────

function Method({ method }: { method: string }) {
  return (
    <div className="flex items-center justify-center h-6 px-2 text-sm font-semibold uppercase border rounded-lg select-none w-fit font-display bg-background">
      {method}
    </div>
  );
}

export function Endpoint({
  path,
  method = "GET",
  isServerOnly,
  className,
}: {
  path?: string;
  method?: string;
  isServerOnly?: boolean;
  className?: string;
  [key: string]: unknown;
}) {
  return (
    <div
      className={cn(
        "relative flex items-center w-full gap-2 p-2 border-t border-x border-border bg-fd-secondary/50 group",
        className,
      )}
    >
      <Method method={method || "GET"} />
      <span className="font-mono text-sm text-muted-foreground/80">{path}</span>
    </div>
  );
}

// ─── ForkButton ──────────────────────────────────────────────────────────────

export function ForkButton({ url }: { url: string }) {
  return (
    <div className="flex items-center gap-2 my-2">
      <Link href={`https://codesandbox.io/p/github/${url}`} target="_blank">
        <Button className="gap-2" variant="outline" size="sm">
          <ExternalLink size={12} />
          Open in Stackblitz
        </Button>
      </Link>
      <Link href={`https://github.com/${url}`} target="_blank">
        <Button className="gap-2" variant="secondary" size="sm">
          <svg
            viewBox="0 0 15 15"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            className="size-4"
          >
            <path
              d="M7.50 0.25C3.50 0.25 0.25 3.50 0.25 7.50C0.25 10.70 2.33 13.42 5.21 14.38C5.57 14.45 5.70 14.22 5.70 14.03C5.70 13.86 5.70 13.40 5.69 12.80C3.68 13.23 3.25 11.82 3.25 11.82C2.93 10.99 2.44 10.76 2.44 10.76C1.79 10.31 2.49 10.32 2.49 10.32C3.22 10.38 3.59 11.07 3.59 11.07C4.23 12.18 5.30 11.86 5.71 11.67C5.78 11.21 5.96 10.89 6.17 10.70C4.55 10.52 2.86 9.90 2.86 7.12C2.86 6.33 3.13 5.68 3.61 5.18C3.53 4.99 3.28 4.26 3.68 3.26C3.68 3.26 4.28 3.06 5.69 4.00C6.26 3.84 6.88 3.76 7.50 3.76C8.12 3.76 8.74 3.84 9.32 4.00C10.72 3.06 11.32 3.26 11.32 3.26C11.71 4.26 11.47 4.99 11.39 5.18C11.87 5.68 12.14 6.33 12.14 7.12C12.14 9.91 10.44 10.52 8.82 10.70C9.08 10.92 9.30 11.36 9.30 12.04C9.30 13.00 9.30 13.77 9.30 14.03C9.30 14.22 9.42 14.45 9.79 14.38C12.67 13.42 14.75 10.70 14.75 7.50C14.75 3.50 11.50 0.25 7.50 0.25Z"
              fill="currentColor"
              fillRule="evenodd"
              clipRule="evenodd"
            />
          </svg>
          View on GitHub
        </Button>
      </Link>
    </div>
  );
}

// ─── AddToCursor ─────────────────────────────────────────────────────────────

export function AddToCursor() {
  return (
    <div className="w-max">
      <Link
        href="cursor://anysphere.cursor-deeplink/mcp/install?name=agentkit&config=eyJ1cmwiOiJodHRwczovL21jcC5hZ2VudGtpdC5jb20vbWNwIn0="
        className="dark:hidden"
      >
        <Image
          src="https://cursor.com/deeplink/mcp-install-dark.svg"
          alt="Add agentkit MCP to Cursor"
          width={128}
          height={32}
          unoptimized
        />
      </Link>

      <Link
        href="cursor://anysphere.cursor-deeplink/mcp/install?name=agentkit&config=eyJ1cmwiOiJodHRwczovL21jcC5hZ2VudGtpdC5jb20vbWNwIn0="
        className="dark:block hidden"
      >
        <Image
          src="https://cursor.com/deeplink/mcp-install-light.svg"
          alt="Add agentkit MCP to Cursor"
          width={128}
          height={32}
          unoptimized
        />
      </Link>
    </div>
  );
}

// ─── DividerText ─────────────────────────────────────────────────────────────

export function DividerText({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-center justify-center w-full">
      <div className="w-full border-b border-muted"></div>
      <div className="flex items-center justify-center w-full text-muted-foreground/80">
        {children}
      </div>
      <div className="w-full border-b border-muted"></div>
    </div>
  );
}

// ─── GenerateAppleJwt ────────────────────────────────────────────────────────

export function GenerateAppleJwt() {
  return (
    <div className="my-4 rounded-lg border bg-card p-4 text-sm text-muted-foreground/80">
      See the Apple documentation for generating a client secret JWT.
    </div>
  );
}

// ─── Features (placeholder) ─────────────────────────────────────────────────

export function Features({ stars }: { stars?: string | null }) {
  return null;
}
