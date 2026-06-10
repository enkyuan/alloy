"use client";

export { OpenAILogo } from "./openai";
export { GeminiLogo } from "./gemini";
export { OpenRouterLogo } from "./openrouter";

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
