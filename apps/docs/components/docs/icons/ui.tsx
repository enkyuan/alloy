interface IconProps {
  size?: number;
  color?: string;
  className?: string;
}

export function CopyIcon({ size = 16, color, className }: IconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      style={color ? { color } : undefined}
      className={className}
    >
      <path
        fill="currentColor"
        d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2m0 16H8V7h11z"
      />
    </svg>
  );
}

export function CheckIcon({ size = 16, color, className }: IconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      style={color ? { color } : undefined}
      className={className}
    >
      <path fill="currentColor" d="M9 16.17L4.83 12l-1.42 1.41L9 19L21 7l-1.41-1.41z" />
    </svg>
  );
}

export function CloseIcon({ size = 16, color, className }: IconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      style={color ? { color } : undefined}
      className={className}
    >
      <path
        fill="currentColor"
        d="M19 6.41L17.59 5L12 10.59L6.41 5L5 6.41L10.59 12L5 17.59L6.41 19L12 13.41L17.59 19L19 17.59L13.41 12z"
      />
    </svg>
  );
}

export function EyeIcon({ size = 16, color, className }: IconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      style={color ? { color } : undefined}
      className={className}
    >
      <path
        fill="currentColor"
        d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5M12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5s5 2.24 5 5s-2.24 5-5 5m0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3s3-1.34 3-3s-1.34-3-3-3"
      />
    </svg>
  );
}

export function GitHubIcon({ size = 16, color, className }: IconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 15 15"
      width={size}
      height={size}
      style={color ? { color } : undefined}
      className={className}
      fill="currentColor"
    >
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M7.50 0.25C3.50 0.25 0.25 3.50 0.25 7.50C0.25 10.70 2.33 13.42 5.21 14.38C5.57 14.45 5.70 14.22 5.70 14.03C5.70 13.86 5.70 13.40 5.69 12.80C3.68 13.23 3.25 11.82 3.25 11.82C2.93 10.99 2.44 10.76 2.44 10.76C1.79 10.31 2.49 10.32 2.49 10.32C3.22 10.38 3.59 11.07 3.59 11.07C4.23 12.18 5.30 11.86 5.71 11.67C5.78 11.21 5.96 10.89 6.17 10.70C4.55 10.52 2.86 9.90 2.86 7.12C2.86 6.33 3.13 5.68 3.61 5.18C3.53 4.99 3.28 4.26 3.68 3.26C3.68 3.26 4.28 3.06 5.69 4.00C6.26 3.84 6.88 3.76 7.50 3.76C8.12 3.76 8.74 3.84 9.32 4.00C10.72 3.06 11.32 3.26 11.32 3.26C11.71 4.26 11.47 4.99 11.39 5.18C11.87 5.68 12.14 6.33 12.14 7.12C12.14 9.91 10.44 10.52 8.82 10.70C9.08 10.92 9.30 11.36 9.30 12.04C9.30 13.00 9.30 13.77 9.30 14.03C9.30 14.22 9.42 14.45 9.79 14.38C12.67 13.42 14.75 10.70 14.75 7.50C14.75 3.50 11.50 0.25 7.50 0.25Z"
      />
    </svg>
  );
}

export function ArrowUpRightIcon({ size = 16, color, className }: IconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      width={size}
      height={size}
      style={color ? { color } : undefined}
      className={className}
    >
      <line x1="7" y1="17" x2="17" y2="7" />
      <polyline points="7 7 17 7 17 17" />
    </svg>
  );
}

export function PlusIcon({ size = 16, color, className }: IconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      style={color ? { color } : undefined}
      className={className}
    >
      <path fill="currentColor" d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6z" />
    </svg>
  );
}
