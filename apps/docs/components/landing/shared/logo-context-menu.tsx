"use client";

import { RiCodeLine, RiDownloadCloud2Line, RiPaletteLine, RiTextBlock } from "@remixicon/react";
import Link from "next/link";
import { useTheme } from "next-themes";
import type React from "react";
import { useState } from "react";
import { useOnDesktop } from "@hooks/use-mobile";
import { toast } from "sonner";
import { Popover, PopoverAnchor, PopoverContent } from "@components/ui/popover";
import { brandAssetPaths } from "@lib/brand-assets";

interface LogoContextMenuProps {
  logo: React.ReactNode;
}

const itemClassName =
  "flex items-center gap-2 w-full px-2 py-1.5 text-sm rounded-sm hover:bg-accent hover:text-accent-foreground transition-colors cursor-pointer outline-hidden [&_svg]:size-4 [&_svg]:text-muted-foreground";

export default function LogoContextMenu({ logo }: LogoContextMenuProps) {
  const [open, setOpen] = useState(false);
  const { resolvedTheme } = useTheme();
  const variant = resolvedTheme === "dark" ? "light" : "dark";

  useOnDesktop(() => setOpen(false));

  const copySvg = async (svgPath: string, label: string) => {
    try {
      const res = await fetch(svgPath);
      if (!res.ok) {
        throw new Error(`Failed to fetch ${svgPath}`);
      }
      const text = await res.text();
      await navigator.clipboard.writeText(text);
      toast.success("", { description: `${label} copied to clipboard` });
    } catch {
      toast.error("", { description: `Failed to copy ${label} to clipboard` });
    } finally {
      setOpen(false);
    }
  };

  const downloadAllAssets = () => {
    const link = document.createElement("a");
    link.href = brandAssetPaths.assetsZip;
    link.download = "agentkit-brand-assets.svg";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    toast.success("Downloading all assets...");
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverAnchor asChild>
        <div
          onContextMenu={(e) => {
            e.preventDefault();
            setOpen(true);
          }}
          className="cursor-pointer"
        >
          {logo}
        </div>
      </PopoverAnchor>
      <PopoverContent align="start" sideOffset={8} className="w-56 p-1">
        <button
          type="button"
          onClick={() => void copySvg(brandAssetPaths.mark[variant].svg, "Logo SVG")}
          className={itemClassName}
        >
          <RiCodeLine />
          Copy Logo as SVG
        </button>
        <button
          type="button"
          onClick={() => void copySvg(brandAssetPaths.wordmark[variant].svg, "Wordmark SVG")}
          className={itemClassName}
        >
          <RiTextBlock />
          Copy Wordmark as SVG
        </button>
        <button type="button" onClick={downloadAllAssets} className={itemClassName}>
          <RiDownloadCloud2Line />
          Download Brand Assets
        </button>
        <div className="-mx-1 my-1 h-px bg-border" />
        <Link href="/docs" onClick={() => setOpen(false)} className={itemClassName}>
          <RiPaletteLine />
          Visit Docs
        </Link>
      </PopoverContent>
    </Popover>
  );
}
