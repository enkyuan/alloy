"use client";

import { useTheme } from "next-themes";

interface ProviderIconProps {
  className?: string;
  width?: number | string;
  height?: number | string;
}

export function GeminiLogo({ className, width = 24, height = 24 }: ProviderIconProps) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={width}
      height={height}
      viewBox="0 0 296 298"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      <defs>
        <mask
          id="gemini_mask"
          width="296"
          height="298"
          x="0"
          y="0"
          maskUnits="userSpaceOnUse"
          style={{ maskType: "alpha" }}
        >
          <path
            fill="#3186FF"
            d="M141.201 4.886c2.282-6.17 11.042-6.071 13.184.148l5.985 17.37a184.004 184.004 0 0 0 111.257 113.049l19.304 6.997c6.143 2.227 6.156 10.91.02 13.155l-19.35 7.082a184.001 184.001 0 0 0-109.495 109.385l-7.573 20.629c-2.241 6.105-10.869 6.121-13.133.025l-7.908-21.296a184 184 0 0 0-109.02-108.658l-19.698-7.239c-6.102-2.243-6.118-10.867-.025-13.132l20.083-7.467A183.998 183.998 0 0 0 133.291 26.28l7.91-21.394Z"
          />
        </mask>
        <linearGradient id="gemini_grad1" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor={isDark ? "#60A5FA" : "#1F2937"} />
          <stop offset="100%" stopColor={isDark ? "#3689FF" : "#374151"} />
        </linearGradient>
      </defs>
      <g mask="url(#gemini_mask)">
        <rect width="296" height="298" fill="url(#gemini_grad1)" />
      </g>
    </svg>
  );
}
