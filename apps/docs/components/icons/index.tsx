import type { SVGProps } from "react";

export function AgentkitMark({
  fill = "#FF6E3C",
  ...props
}: SVGProps<SVGSVGElement> & { fill?: string }) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      {...props}
    >
      <path d="M31 3V17L17 3H31Z" fill={fill} />
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M45 31V17H31H17V31L3 17L17 3H3V17V31H17V45H31H45V31ZM45 31L31 45L17 31H31V17L45 31Z"
        fill={fill}
      />
    </svg>
  );
}
