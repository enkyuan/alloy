"use client";

import Link from "next/link";
import { cn } from "@lib/utils";
import { BackArrowIcon, MenuLinesIcon } from "@components/icons";
import { Badge } from "@components/ui/badge";
import type { ListItem } from "@lib/sidebar-config";

export function MobileViewToggle({
  direction,
  label,
  onClick,
}: {
  direction: "back" | "menu";
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-2 w-full px-5 py-2.5 text-foreground/65 dark:text-foreground/45 hover:text-foreground/70 transition-colors border-b border-foreground/6"
    >
      {direction === "back" ? <BackArrowIcon /> : <MenuLinesIcon />}
      <span className="font-mono text-[10px] uppercase tracking-wider">{label}</span>
    </button>
  );
}

export function DocsSidebarItem({
  item,
  pathname,
  prefixHref,
  onClose,
}: {
  item: ListItem;
  pathname: string;
  prefixHref: (href: string) => string;
  onClose: () => void;
  index: number;
}) {
  if (item.separator || item.group) {
    return (
      <div className="flex flex-row items-center gap-2 mx-5 my-2">
        <p className="text-[10px] text-foreground/65 dark:text-foreground/45 uppercase tracking-wider">
          {item.title}
        </p>
        <div className="grow h-px bg-border" />
      </div>
    );
  }

  if (!item.href) return null;

  const active =
    pathname === item.href || (!!item.subpages?.length && pathname.startsWith(`${item.href}/`));

  return (
    <Link
      href={item.external ? item.href : prefixHref(item.href)}
      onClick={onClose}
      data-active={active || undefined}
      className={cn(
        "relative flex w-full items-center gap-2.5 px-5 py-1.5 text-[14px] transition-all duration-150",
        active
          ? "text-foreground bg-foreground/6"
          : "text-foreground/75 dark:text-foreground/60 hover:text-foreground/90 hover:bg-foreground/3",
      )}
    >
      <span
        className={cn(
          "flex size-5 shrink-0 items-center justify-center [&>svg]:size-[14px] transition-colors duration-150",
          active ? "text-foreground" : "text-foreground/75 dark:text-foreground/60",
        )}
      >
        <item.icon className="text-foreground/75" />
      </span>
      <span className="min-w-0 grow truncate">{item.title}</span>
      {item.isNew && (
        <Badge
          variant="outline"
          className={cn(
            "pointer-events-none border-dashed rounded-none px-1.5 py-0 text-[9px] uppercase tracking-wider",
            active
              ? "border-solid bg-foreground/10 text-foreground"
              : "text-foreground/70 dark:text-foreground/55 border-foreground/25",
          )}
        >
          New
        </Badge>
      )}
    </Link>
  );
}
