"use client";

import { useTheme } from "next-themes";

interface ProviderIconProps {
  className?: string;
  width?: number | string;
  height?: number | string;
}

// SVG source: svgl.app — OpenAI (spiral/gear mark, single-color)
export function OpenAILogo({ className, width = 14, height = 14 }: ProviderIconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={width}
      height={height}
      viewBox="0 0 24 24"
      fill="currentColor"
      className={className}
      aria-hidden="true"
    >
      <path d="M22.282 9.821a5.985 5.985 0 0 0-.516-4.91a6.05 6.05 0 0 0-6.51-2.9A6.07 6.07 0 0 0 4.981 4.18a5.99 5.99 0 0 0-3.998 2.9a6.05 6.05 0 0 0 .743 7.097a5.98 5.98 0 0 0 .51 4.911a6.05 6.05 0 0 0 6.515 2.9A5.98 5.98 0 0 0 13.26 24a6.06 6.06 0 0 0 5.772-4.206a5.99 5.99 0 0 0 3.997-2.9a6.06 6.06 0 0 0-.747-7.073M13.26 22.43a4.48 4.48 0 0 1-2.876-1.04l.141-.081l4.779-2.758a.8.8 0 0 0 .392-.681v-6.737l2.02 1.168a.07.07 0 0 1 .038.052v5.583a4.5 4.5 0 0 1-4.494 4.494M3.6 18.304a4.47 4.47 0 0 1-.535-3.014l.142.085l4.783 2.759a.77.77 0 0 0 .78 0l5.843-3.369v2.332a.08.08 0 0 1-.033.062L9.74 19.95a4.5 4.5 0 0 1-6.14-1.646M2.34 7.896a4.5 4.5 0 0 1 2.366-1.973V11.6a.77.77 0 0 0 .388.677l5.815 3.354l-2.02 1.168a.08.08 0 0 1-.071 0l-4.83-2.786A4.5 4.5 0 0 1 2.34 7.872zm16.597 3.855l-5.833-3.387L15.119 7.2a.08.08 0 0 1 .071 0l4.83 2.791a4.494 4.494 0 0 1-.676 8.105v-5.678a.79.79 0 0 0-.407-.667m2.01-3.023l-.141-.085l-4.774-2.782a.78.78 0 0 0-.785 0L9.409 9.23V6.897a.07.07 0 0 1 .028-.061l4.83-2.787a4.5 4.5 0 0 1 6.68 4.66zm-12.64 4.135l-2.02-1.164a.08.08 0 0 1-.038-.057V6.075a4.5 4.5 0 0 1 7.375-3.453l-.142.08l-4.778 2.758a.8.8 0 0 0-.393.681zm1.097-2.365l2.602-1.5l2.607 1.5v2.999l-2.597 1.5l-2.607-1.5z" />
    </svg>
  );
}

// SVG source: svgl.app — Google Gemini (four-pointed star mark, single-color)
export function GeminiLogo({ className, width = 14, height = 14 }: ProviderIconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={width}
      height={height}
      viewBox="0 0 24 24"
      fill="currentColor"
      className={className}
      aria-hidden="true"
    >
      <path d="M12 2c.46 5.17 4.83 9.54 10 10c-5.17.46-9.54 4.83-10 10c-.46-5.17-4.83-9.54-10-10C7.17 11.54 11.54 7.17 12 2z" />
    </svg>
  );
}

export function KimiLogo({ className, width = 14, height = 14 }: ProviderIconProps) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme !== "light";
  const kFill = isDark ? "white" : "black";

  return (
    <svg
      width={width}
      height={height}
      viewBox="0 0 24 25"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      <path
        d="M21.72 0.94C22.95 0.94 23.95 1.94 23.95 3.17C23.95 4.40 22.95 5.40 21.72 5.40H19.75C19.60 5.40 19.49 5.28 19.49 5.14V3.17C19.49 1.94 20.49 0.94 21.72 0.94Z"
        fill="#1783FF"
      />
      <path
        d="M9.39 13.95L17.82 5.59C17.98 5.43 17.89 5.12 17.68 5.12H13.14C13.14 5.12 13.04 5.14 13 5.18L3.92 14.19C3.78 14.33 3.57 14.21 3.57 13.98V5.39C3.57 5.24 3.47 5.12 3.35 5.12H0.22C0.10 5.12 0 5.24 0 5.39V23.92C0 24.07 0.10 24.19 0.22 24.19H3.35C3.47 24.19 3.57 24.07 3.57 23.92V20.14C3.57 20.06 3.6 19.98 3.65 19.93L6.47 17.14C6.54 17.07 6.63 17.06 6.71 17.11L14.24 22.65C15.47 23.48 16.85 23.99 18.25 24.14C18.37 24.15 18.48 24.03 18.48 23.87V20.31C18.48 20.17 18.4 20.06 18.29 20.05C17.47 19.92 16.66 19.60 15.94 19.11L9.42 14.39C9.28 14.30 9.27 14.07 9.39 13.95Z"
        fill={kFill}
      />
    </svg>
  );
}

// SVG source: svgl.app — OpenRouter wordmark icon (single-color)
export function OpenRouterLogo({ className, width = 14, height = 14 }: ProviderIconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={width}
      height={height}
      viewBox="0 0 24 24"
      fill="currentColor"
      className={className}
      aria-hidden="true"
    >
      <path d="M16.03 2L14.29 3.74l2.03 2.03-3.91 3.91-1.17-1.17L7.55 12.2l1.17 1.17-3.91 3.91-2.03-2.03L1.04 17l5.08 5.08 1.74-1.74-2.03-2.03 3.91-3.91 1.17 1.17 3.69-3.69-1.17-1.17 3.91-3.91 2.03 2.03L20.9 7.1Zm-3.35 13.3-1.74 1.74 1.53 1.53-1.74 1.74L16.97 24 22 18.97l-5.08-5.08-1.74 1.74z" />
    </svg>
  );
}

export function AnthropicLogo({ className, width = 14, height = 14 }: ProviderIconProps) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme !== "light";
  const fill = isDark ? "#ffffff" : "#000000";

  return (
    <svg
      width={width}
      height={height}
      viewBox="0 0 24 24"
      fill={fill}
      role="img"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      <path d="M17.3 3.54h-3.67l6.7 16.92H24Zm-10.61 0L0 20.46h3.74l1.37-3.55h7.01l1.37 3.55h3.74L10.54 3.54Zm-.37 10.22 2.29-5.95 2.29 5.95Z" />
    </svg>
  );
}
