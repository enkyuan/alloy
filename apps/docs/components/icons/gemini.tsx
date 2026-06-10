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

  // Gemini has a complex multi-color gradient design
  // Using a simplified version that adapts to light/dark
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={width}
      height={height}
      viewBox="0 0 24 24"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      {isDark ? (
        <>
          {/* Dark mode: lighter colors */}
          <path
            d="M12 2c.46 5.17 4.83 9.54 10 10c-5.17.46-9.54 4.83-10 10c-.46-5.17-4.83-9.54-10-10C7.17 11.54 11.54 7.17 12 2z"
            fill="#3689FF"
          />
          <circle
            cx="12"
            cy="12"
            r="8"
            fill="none"
            stroke="#3689FF"
            strokeWidth="0.5"
            opacity="0.3"
          />
        </>
      ) : (
        <>
          {/* Light mode: darker colors */}
          <path
            d="M12 2c.46 5.17 4.83 9.54 10 10c-5.17.46-9.54 4.83-10 10c-.46-5.17-4.83-9.54-10-10C7.17 11.54 11.54 7.17 12 2z"
            fill="#1f2937"
          />
          <circle
            cx="12"
            cy="12"
            r="8"
            fill="none"
            stroke="#1f2937"
            strokeWidth="0.5"
            opacity="0.2"
          />
        </>
      )}
    </svg>
  );
}
