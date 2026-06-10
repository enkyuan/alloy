// SVG icon and pattern components used in the nav menus.
import type React from "react";

export const FrameworkLogoIcon: React.FC<{ className?: string }> = ({ className }) => (
  <svg
    viewBox="0 0 30 45"
    fill="currentColor"
    className={`${className ?? ""} rotate-12`}
    aria-hidden="true"
  >
    <path fillRule="evenodd" clipRule="evenodd" d="M0 0H15V15H30V30H15V45H0V30V15V0Z" />
  </svg>
);

export const InfraLogoIcon: React.FC<{ className?: string }> = ({ className }) => (
  <svg
    viewBox="30 0 30 45"
    fill="currentColor"
    className={`${className ?? ""} -rotate-12`}
    aria-hidden="true"
  >
    <path fillRule="evenodd" clipRule="evenodd" d="M45 30V15H30V0H45H60V15V30V45H45H30V30H45Z" />
  </svg>
);

export const CommunityIcon: React.FC<{ className?: string }> = ({ className }) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    width="1em"
    height="1em"
    viewBox="0 0 20 20"
    className={className}
    aria-hidden="true"
  >
    <path
      fill="currentColor"
      d="M10 3a2 2 0 1 0 0 4a2 2 0 0 0 0-4M7 5a3 3 0 1 1 6 0a3 3 0 0 1-6 0M5.053 9.996q-.051.244-.051.504v.545l-2.631.705a.5.5 0 0 0-.354.612l.647 2.415A3 3 0 0 0 5.98 16.97c.23.31.495.594.789.843l-.171.05a4 4 0 0 1-4.9-2.828l-.647-2.415a1.5 1.5 0 0 1 1.061-1.837zm9.949 1.049V10.5q-.001-.26-.05-.504l2.94.788a1.5 1.5 0 0 1 1.06 1.837l-.647 2.415a4 4 0 0 1-5.07 2.778q.443-.376.789-.843a3 3 0 0 0 3.315-2.194l.648-2.415a.5.5 0 0 0-.354-.612zM15 6.5a1.5 1.5 0 1 1 3 0a1.5 1.5 0 0 1-3 0M16.5 4a2.5 2.5 0 1 0 0 5a2.5 2.5 0 0 0 0-5m-13 1a1.5 1.5 0 1 0 0 3a1.5 1.5 0 0 0 0-3M1 6.5a2.5 2.5 0 1 1 5 0a2.5 2.5 0 0 1-5 0M7.5 9A1.5 1.5 0 0 0 6 10.5V14a4 4 0 0 0 8 0v-3.5A1.5 1.5 0 0 0 12.5 9zM7 10.5a.5.5 0 0 1 .5-.5h5a.5.5 0 0 1 .5.5V14a3 3 0 1 1-6 0z"
    />
  </svg>
);

export const TimelinePattern: React.FC<{ className?: string }> = ({ className }) => (
  <svg
    width="56"
    height="56"
    viewBox="0 0 56 56"
    fill="none"
    shapeRendering="geometricPrecision"
    className={className}
    aria-hidden="true"
  >
    <line x1="6" y1="6" x2="6" y2="50" stroke="currentColor" strokeWidth="1" />
    <circle cx="6" cy="10" r="1.75" fill="currentColor" />
    <circle cx="6" cy="28" r="1.75" fill="currentColor" />
    <circle cx="6" cy="46" r="1.75" fill="currentColor" />
    <line x1="14" y1="10" x2="50" y2="10" stroke="currentColor" strokeWidth="1" />
    <line x1="14" y1="28" x2="40" y2="28" stroke="currentColor" strokeWidth="1" />
    <line x1="14" y1="46" x2="32" y2="46" stroke="currentColor" strokeWidth="1" />
  </svg>
);

export const ScribblePattern: React.FC<{ className?: string }> = ({ className }) => (
  <svg
    width="64"
    height="34"
    viewBox="0 0 64 34"
    fill="none"
    className={className}
    aria-hidden="true"
  >
    <path
      d="M2 14 C 8 2, 14 2, 18 14 S 28 26, 34 14 S 48 2, 54 14 S 62 20, 62 20"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      fill="none"
    />
    <path
      d="M4 26 C 10 22, 20 28, 28 24 S 44 28, 52 24"
      stroke="currentColor"
      strokeWidth="1.1"
      strokeLinecap="round"
      fill="none"
      opacity="0.7"
    />
  </svg>
);

export const VerticalLinesPattern: React.FC<{ className?: string }> = ({ className }) => {
  const cols = 72;
  const width = cols * 3;
  const height = 100;
  const lines: React.ReactElement[] = [];
  for (let i = 0; i < cols; i++) {
    const x = i * 3 + 1;
    lines.push(
      <line key={i} x1={x} y1={0} x2={x} y2={height} stroke="currentColor" strokeWidth="0.75" />,
    );
  }
  return (
    <svg
      width="100%"
      height="100%"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={className}
      aria-hidden="true"
    >
      {lines}
    </svg>
  );
};
