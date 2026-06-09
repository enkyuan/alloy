"use client";

import { AnimatePresence, LazyMotion, domAnimation, m } from "framer-motion";
import Link from "next/link";
import type { ReactNode } from "react";
import type { ListItem } from "@components/sidebar-content";
import { Badge } from "@components/ui/badge";
import { cn } from "@lib/utils";

type Section = {
  href?: string;
  list: ListItem[];
};

// ─── SidebarSection ───────────────────────────────────────────────────────────

export function SidebarSection({
  section,
  pathname,
  prefixHref,
}: {
  section: Section;
  pathname: string;
  prefixHref: (href: string) => string;
}) {
  return (
    <div className="pt-0 pb-1">
      {section.href && (
        <SidebarLink href={prefixHref(section.href)} active={pathname === section.href}>
          Overview
        </SidebarLink>
      )}
      {section.list.map((item, i) => {
        if (item.separator) {
          return (
            <div
              key={`sep-${item.title}-${i}`}
              className="flex flex-row items-center gap-2 mx-4 lg:mx-7 my-2"
            >
              <p className="text-[10px] text-foreground/45 uppercase tracking-wider">
                {item.title}
              </p>
              <div className="grow h-px bg-border" />
            </div>
          );
        }
        if (item.group) {
          return (
            <div
              key={`group-${item.title}-${i}`}
              className="flex flex-row items-center gap-2 mx-4 my-1 lg:mx-7"
            >
              <p className="text-[10px] text-foreground/45 uppercase tracking-wider">
                {item.title}
              </p>
              <div className="grow h-px bg-border" />
            </div>
          );
        }
        if (item.external && item.href) {
          return <SidebarExternalNavRow key={item.href} item={{ ...item, href: item.href }} />;
        }
        if (!item.href) return null;
        const hasSubpages = !!(item.subpages && item.subpages.length > 0);
        const subpageMatch =
          hasSubpages && item.subpages?.some((sp) => sp.href && pathname === sp.href);
        const active =
          pathname === item.href ||
          subpageMatch ||
          (!!(item.subpages && item.subpages.length > 0) && pathname.startsWith(`${item.href}/`));

        return (
          <SidebarItemWithSubpages
            key={item.href}
            item={item}
            active={active}
            pathname={pathname}
            hasSubpages={hasSubpages}
            prefixHref={prefixHref}
          />
        );
      })}
    </div>
  );
}

// ─── SidebarItemWithSubpages ──────────────────────────────────────────────────

function SidebarItemWithSubpages({
  item,
  active,
  pathname,
  hasSubpages,
  prefixHref,
}: {
  item: ListItem;
  active: boolean;
  pathname: string;
  hasSubpages: boolean | undefined;
  prefixHref: (href: string) => string;
}) {
  const showSubpages = hasSubpages && active;

  return (
    <div>
      <SidebarLink
        href={prefixHref(item.href || "")}
        active={active}
        icon={
          <span className="flex size-5 shrink-0 items-center justify-center [&>svg]:size-[14px]">
            <item.icon className="text-foreground/75" />
          </span>
        }
        isNew={item.isNew}
      >
        {item.title}
      </SidebarLink>
      <LazyMotion features={domAnimation}>
        <AnimatePresence initial={false}>
          {showSubpages && item.subpages && (
            <m.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.35, type: "spring", bounce: 0 }}
              className="overflow-hidden"
            >
              <div className="relative before:absolute before:left-[calc(1.75rem+0.75rem)] before:top-0 before:bottom-0 before:w-px before:bg-foreground/20">
                {item.subpages.map((subpage, i) => {
                  if (subpage.group) {
                    return (
                      <div
                        key={`subgroup-${subpage.title}-${i}`}
                        className="flex flex-row items-center gap-2 pl-[calc(1.75rem+0.75rem+0.75rem)] pr-4 py-1.5 mt-1 first:mt-0"
                      >
                        <p className="text-[10px] text-foreground/45 uppercase tracking-wider">
                          {subpage.title}
                        </p>
                        <div className="grow h-px bg-border" />
                      </div>
                    );
                  }
                  if (!subpage.href) return null;
                  return (
                    <SubpageLink
                      key={subpage.href}
                      href={prefixHref(subpage.href)}
                      active={pathname === subpage.href}
                      icon={subpage.icon ? <subpage.icon className="text-current" /> : undefined}
                    >
                      {subpage.title}
                    </SubpageLink>
                  );
                })}
              </div>
            </m.div>
          )}
        </AnimatePresence>
      </LazyMotion>
    </div>
  );
}

// ─── SubpageLink ──────────────────────────────────────────────────────────────

function SubpageLink({
  href,
  active,
  icon,
  children,
}: {
  href: string;
  active: boolean;
  icon?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Link
      href={href}
      data-active={active || undefined}
      className={cn(
        "relative flex items-center gap-1 pl-[calc(1.75rem+0.75rem+0.75rem)] pr-4 py-1 text-[13px] transition-all duration-150",
        active
          ? "text-foreground bg-foreground/6"
          : "text-foreground/55 hover:text-foreground/80 hover:bg-foreground/3",
      )}
    >
      {icon && (
        <span
          className={cn(
            "min-w-4 [&>svg]:size-[12px] transition-colors duration-150",
            active ? "text-foreground" : "text-foreground/55",
          )}
        >
          {icon}
        </span>
      )}
      <span className="truncate">{children}</span>
    </Link>
  );
}

// ─── SidebarExternalNavRow ────────────────────────────────────────────────────

function SidebarExternalNavRow({ item }: { item: ListItem & { href: string } }) {
  return (
    <Link
      href={item.href}
      className={`
        relative flex w-full items-center gap-2.5 px-4 py-1 text-[14px] transition-all duration-150
        text-foreground/65 hover:text-foreground/90 hover:bg-foreground/3
      `}
    >
      <span className="text-foreground/65 transition-colors duration-150">
        <span className="flex size-5 shrink-0 items-center justify-center [&>svg]:size-[14px]">
          <item.icon className="text-foreground/75" />
        </span>
      </span>
      <span className="min-w-0 grow truncate">{item.title}</span>
      {item.isNew && <NewBadge />}
    </Link>
  );
}

// ─── SidebarLink ─────────────────────────────────────────────────────────────

function SidebarLink({
  href,
  active,
  icon,
  isNew,
  children,
}: {
  href: string;
  active: boolean;
  icon?: ReactNode;
  isNew?: boolean;
  children: ReactNode;
}) {
  return (
    <Link
      href={href}
      data-active={active || undefined}
      className={`
        relative flex w-full items-center gap-2.5 px-4 py-1 text-[14px] transition-all duration-150
        ${
          active
            ? "text-foreground bg-foreground/6"
            : "text-foreground/65 hover:text-foreground/90 hover:bg-foreground/3"
        }
      `}
    >
      {icon && (
        <span
          className={`transition-colors duration-150 ${
            active ? "text-foreground" : "text-foreground/65"
          }`}
        >
          {icon}
        </span>
      )}
      <span className="min-w-0 grow truncate">{children}</span>
      {isNew && <NewBadge isSelected={active} />}
    </Link>
  );
}

// ─── NewBadge ─────────────────────────────────────────────────────────────────

function NewBadge({ isSelected }: { isSelected?: boolean }) {
  return (
    <Badge
      className={cn(
        "pointer-events-none no-underline! border-dashed decoration-transparent! rounded-none px-1.5 py-0 text-[9px] uppercase tracking-wider",
        isSelected
          ? "border-solid! bg-foreground/10 text-foreground"
          : "text-foreground/55 border-foreground/25",
      )}
      variant="outline"
    >
      New
    </Badge>
  );
}
