import Link from "next/link";
import { RiAddLine, RiNpmjsFill } from "@remixicon/react";
import { formatCount } from "@lib/landing/readme-footer-utils";

export type CommunityHeroStats = {
  npmDownloads: number;
  npmWeeklyHistory: number[];
  githubStars: number;
  contributors: number;
};

// react-doctor-disable-next-line only-export-components, react-doctor/only-export-components
export { formatCount } from "@lib/landing/readme-footer-utils";

export function ReadmeFooter({ stats }: { stats: CommunityHeroStats }) {
  return (
    <div className="relative mt-10 pt-8 pb-16 overflow-hidden">
      {/* Watermark logo */}
      <div
        className="absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none select-none opacity-[0.04] dark:opacity-[0.05]"
        aria-hidden="true"
      >
        <svg
          width="200"
          height="200"
          viewBox="0 0 48 48"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <path d="M31 3V17L17 3H31Z" className="fill-foreground" />
          <path
            fillRule="evenodd"
            clipRule="evenodd"
            d="M45 31V17H31H17V31L3 17L17 3H3V17V31H17V45H31H45V31ZM45 31L31 45L17 31H31V17L45 31Z"
            className="fill-foreground"
          />
        </svg>
      </div>

      {/* Dot grid */}
      <div
        className="absolute inset-0 pointer-events-none select-none"
        aria-hidden="true"
        style={{
          backgroundImage: "radial-gradient(circle, currentColor 0.5px, transparent 0.5px)",
          backgroundSize: "24px 24px",
          opacity: 0.03,
        }}
      />

      {/* CTA */}
      <div className="relative space-y-6">
        <p className="text-center text-lg text-balance text-foreground/60 dark:text-foreground/50 tracking-tight">
          Ship agents in minutes, not months.
        </p>

        <div className="flex items-center justify-center gap-2">
          {stats.npmDownloads > 0 && (
            <a href="https://github.com/enkyuan/alloy" target="_blank" rel="noopener noreferrer">
              <div className="flex items-center gap-1.5 px-2.5 hover:bg-foreground/4 rounded-sm transition-colors text-foreground/50 dark:text-foreground/50">
                <RiNpmjsFill className="size-[11px] -translate-y-px" />
                <span className="text-xs font-mono">{formatCount(stats.npmDownloads)} / week</span>
              </div>
            </a>
          )}
          {stats.githubStars > 0 && (
            <a href="https://github.com/enkyuan/alloy" target="_blank" rel="noopener noreferrer">
              <div className="flex items-center gap-1.5 px-2.5 hover:bg-foreground/4 rounded-sm transition-colors text-foreground/50 dark:text-foreground/50">
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="11"
                  height="11"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="size-[11px] -translate-y-px"
                >
                  <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                </svg>
                <span className="text-xs font-mono">{formatCount(stats.githubStars)} stars</span>
              </div>
            </a>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-center gap-4 pt-1">
          <Link
            href="/docs/installation"
            className="inline-flex items-center gap-1.5 px-4 sm:px-5 py-2 bg-neutral-900 text-neutral-100 dark:bg-neutral-100 dark:text-neutral-900 text-xs sm:text-sm font-medium hover:opacity-90 transition-colors"
          >
            Get Started
          </Link>
          <Link
            href="https://github.com/enkyuan/alloy"
            className="relative inline-flex items-center gap-1.5 px-4 sm:px-5 py-2 text-neutral-600 dark:text-neutral-300 text-xs sm:text-sm font-medium transition-colors group"
          >
            <span
              className="absolute inset-0 opacity-[0.04] group-hover:opacity-[0.08] transition-opacity"
              style={{
                backgroundImage: `repeating-linear-gradient(
                  -45deg,
                  transparent,
                  transparent 4px,
                  currentColor 4px,
                  currentColor 5px
                )`,
              }}
            />
            <span className="absolute top-0 -left-[6px] -right-[6px] h-px bg-foreground/20 group-hover:bg-foreground/30 transition-colors" />
            <span className="absolute bottom-0 -left-[6px] -right-[6px] h-px bg-foreground/20 group-hover:bg-foreground/30 transition-colors" />
            <span className="absolute left-0 -top-[6px] -bottom-[6px] w-px bg-foreground/20 group-hover:bg-foreground/30 transition-colors" />
            <span className="absolute right-0 -top-[6px] -bottom-[6px] w-px bg-foreground/20 group-hover:bg-foreground/30 transition-colors" />
            <span className="absolute -bottom-[6px] -right-[6px] font-mono text-[8px] text-foreground/40 dark:text-foreground/50 leading-none select-none translate-x-1/2 translate-y-1/2">
              <RiAddLine size={8} />
            </span>
            <span className="relative">GitHub </span>
          </Link>
        </div>
      </div>
    </div>
  );
}
