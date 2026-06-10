"use client";
import { useTheme } from "next-themes";

import { Button } from "@components/ui/button";

export function ThemeToggle() {
  const { setTheme, resolvedTheme } = useTheme();

  return (
    <Button
      variant="link"
      size="icon"
      onClick={() => setTheme(resolvedTheme === "light" ? "dark" : "light")}
      suppressHydrationWarning
    >
      {/* Sun icon - visible in light mode */}
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="1em"
        height="1em"
        viewBox="0 0 24 24"
        className="hidden dark:hidden [html.light_&]:block"
        suppressHydrationWarning
      >
        <g
          fill="none"
          stroke="#888888"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="2"
        >
          <path strokeDasharray="2" strokeDashoffset="0" d="M12 21v1M21 12h1M12 3v-1M3 12h-1" />
          <path
            strokeDasharray="2"
            strokeDashoffset="0"
            d="M18.5 18.5l0.5 0.5M18.5 5.5l0.5 -0.5M5.5 5.5l-0.5 -0.5M5.5 18.5l-0.5 0.5"
          />
          <animateTransform
            attributeName="transform"
            dur="30s"
            repeatCount="indefinite"
            type="rotate"
            values="0 12 12;360 12 12"
          />
        </g>
        <circle cx="12" cy="12" r="6" fill="#424242" />
      </svg>
      {/* Moon icon - visible in dark mode */}
      <svg
        className="hidden [html.dark_&]:block h-6 w-5"
        viewBox="0 0 32 32"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        suppressHydrationWarning
      >
        <path
          d="M16 2.67V29.33C19.54 29.33 22.93 27.93 25.43 25.43C27.93 22.93 29.33 19.54 29.33 16C29.33 12.46 27.93 9.07 25.43 6.57C22.93 4.07 19.54 2.67 16 2.67Z"
          fill="#fff"
        />
      </svg>
      <span className="sr-only">Toggle theme</span>
    </Button>
  );
}
