"use client";

import { useTheme } from "next-themes";

interface ProviderIconProps {
  className?: string;
  width?: number | string;
  height?: number | string;
}

export function OpenRouterLogo({ className, width = 24, height = 24 }: ProviderIconProps) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={width}
      height={height}
      viewBox="0 0 512 512"
      fill="none"
      stroke={isDark ? "#ffffff" : "#111111"}
      className={className}
      aria-hidden="true"
    >
      <g clipPath="url(#openrouter_clip0)">
        <path
          d="M3 248.945C18 248.945 76 236 106 219C136 202 136 202 198 158C276.497 102.293 332 120.945 423 120.945"
          strokeWidth="90"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M511 121.5L357.25 210.268L357.25 32.7324L511 121.5Z"
          fill={isDark ? "#ffffff" : "#111111"}
        />
        <path
          d="M0 249C15 249 73 261.945 103 278.945C133 295.945 133 295.945 195 339.945C273.497 395.652 329 377 420 377"
          strokeWidth="90"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M508 376.445L354.25 287.678L354.25 465.213L508 376.445Z"
          fill={isDark ? "#ffffff" : "#111111"}
        />
      </g>
      <defs>
        <clipPath id="openrouter_clip0">
          <rect width="512" height="512" fill="white" />
        </clipPath>
      </defs>
    </svg>
  );
}
