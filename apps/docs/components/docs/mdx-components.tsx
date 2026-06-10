"use client";

import { RiExternalLinkLine } from "@remixicon/react";
import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";
import { useState } from "react";
import { Button } from "@components/ui/button";
import { cn } from "@lib/utils";
import { DatabaseTable } from "./database/table";
import { GitHubIcon } from "./icons/ui";

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
          <RiExternalLinkLine size={12} />
          Open in Stackblitz
        </Button>
      </Link>
      <Link href={`https://github.com/${url}`} target="_blank">
        <Button className="gap-2" variant="secondary" size="sm">
          <GitHubIcon className="size-4" />
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
