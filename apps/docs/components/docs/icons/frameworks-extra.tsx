// Extended framework icons — tanstack, expo, nitro — split out to keep
// icons-frameworks.tsx under 400 lines.
import type { SVGProps } from "react";
import { cn } from "@lib/utils";

export const FrameworkIconsExtended = {
  tanstack: (props?: SVGProps<any>) => (
    <svg
      className={cn(props?.className)}
      xmlns="http://www.w3.org/2000/svg"
      width="1.2em"
      height="1.2em"
      viewBox="0 0 100 100"
    >
      <mask
        id="a"
        style={{ maskType: "alpha" }}
        maskUnits="userSpaceOnUse"
        x="0"
        y="0"
        width="100"
        height="100"
      >
        <circle cx="50" cy="50" r="50" className="fill-foreground" />
      </mask>
      <g mask="url(#a)">
        <circle
          cx="11"
          cy="119"
          r="52"
          className="fill-muted-foreground stroke-foreground"
          strokeWidth="4"
        />
        <circle
          cx="10"
          cy="125"
          r="52"
          className="fill-muted-foreground stroke-foreground"
          strokeWidth="4"
        />
        <circle
          cx="9"
          cy="131"
          r="52"
          className="fill-muted-foreground stroke-muted-foreground"
          strokeWidth="4"
        />
        <circle
          cx="88"
          cy="119"
          r="52"
          className="fill-muted-foreground stroke-foreground"
          strokeWidth="4"
        />
        <path
          className="fill-foreground"
          d="M89 35h2v5h-2zM83 34l2 1-1 4h-2zM77 31l2 1-3 4-2-1zM73 27l1 1-3 4-1-2zM70 23l1 1-4 3-1-2zM68 18v2l-4 1-1-2zM68 11l1 2-5 1-1-2zM69 6v2h-5V6z"
        />
        <circle
          cx="89"
          cy="125"
          r="52"
          className="fill-muted-foreground stroke-foreground"
          strokeWidth="4"
        />
        <circle
          cx="90"
          cy="131"
          r="52"
          className="fill-muted-foreground stroke-muted-foreground"
          strokeWidth="4"
        />
        <ellipse cx="49.5" cy="119" rx="41.5" ry="51" className="fill-muted-foreground" />
        <path
          d="M34 38v-9c1 1 2 4 5 6l7 30-8 2c-1-23-2-23-4-29Z"
          className="fill-foreground stroke-muted-foreground"
        />
        <path
          fillRule="evenodd"
          clipRule="evenodd"
          d="M95 123c0 31-20 57-45 57S5 154 5 123c0-27 14-50 33-56l12-2c25 0 45 26 45 58Zm-45 47c22 0 39-22 39-50S72 70 50 70s-39 22-39 50 17 50 39 50Z"
          className="fill-foreground"
        />
        <path
          d="M34 29c-4-8-11-5-14-4 2 3 5 4 9 4h5Z"
          className="fill-foreground stroke-muted-foreground"
        />
        <path
          d="M25 38c-1 6 0 14 2 18 5-7 7-13 7-18v-9c-5 1-7 5-9 9Z"
          className="fill-muted-foreground"
        />
        <path
          d="M34 29c-1 3-5 11-5 16m5-16c-5 1-7 5-9 9-1 6 0 14 2 18 5-7 7-13 7-18v-9Z"
          className="stroke-muted-foreground"
        />
        <path
          d="M44 18c-10 1-11 7-10 11l4-3c5-4 6-7 6-8Z"
          className="fill-foreground stroke-muted-foreground"
        />
        <path d="M34 29h7l18 4c-3-6-9-14-21-7l-4 3Z" className="fill-foreground" />
        <path
          d="M34 29c4-2 12-5 18-1m-18 1h7l18 4c-3-6-9-14-21-7l-4 3Z"
          className="stroke-muted-foreground"
        />
        <path
          d="M32 29a1189 1189 0 0 1-16 19c0-17 7-18 13-19h5a14 14 0 0 1-2 0Z"
          className="fill-foreground"
        />
        <path
          d="M34 29c-5 1-7 5-9 9l-9 10c0-17 7-18 13-19h5Zm0 0c-5 2-11 3-14 10"
          className="stroke-muted-foreground"
        />
        <path d="M41 29c9 2 13 10 15 14a25 25 0 0 1-22-14h7Z" className="fill-foreground" />
        <path
          d="M34 29c3 1 11 5 15 9m-15-9h7c9 2 13 10 15 14a25 25 0 0 1-22-14Z"
          className="stroke-muted-foreground"
        />
        <circle
          cx="91.5"
          cy="12.5"
          r="18.5"
          className="fill-foreground stroke-muted-foreground"
          strokeWidth="2"
        />
      </g>
    </svg>
  ),
  expo: (props?: SVGProps<any>) => (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="1.2em"
      height="1.2em"
      viewBox="0 0 32 32"
      {...props}
    >
      <path
        fill="currentColor"
        d="M24.292 15.547a3.93 3.93 0 0 0 4.115-3.145a2.57 2.57 0 0 0-2.161-1.177c-2.272-.052-3.491 2.651-1.953 4.323zm-9.177-10.85l5.359-3.104L18.766.63l-7.391 4.281l.589.328l1.119.629l2.032-1.176zm6.046-3.39c.089.027.161.1.188.188l2.484 7.593a.285.285 0 0 1-.125.344a5.06 5.06 0 0 0-2.317 5.693a5.066 5.066 0 0 0 5.401 3.703a.3.3 0 0 1 .307.203l2.563 7.803a.3.3 0 0 1-.125.344l-7.859 4.771a.3.3 0 0 1-.131.036a.26.26 0 0 1-.203-.041l-2.765-1.797a.3.3 0 0 1-.109-.129l-5.396-12.896l-8.219 4.875c-.016.011-.037.021-.052.032a.3.3 0 0 1-.261-.021l-1.859-1.093a.283.283 0 0 1-.115-.381l7.953-15.749a.27.27 0 0 1 .135-.131L18.615.045a.29.29 0 0 1 .292-.005zm-8.322 5.1l-1.932-1.089l-7.693 15.229l1.396.823l6.631-9.015a.28.28 0 0 1 .271-.12a.29.29 0 0 1 .235.177l7.228 17.296l1.933 1.251l-8.063-24.552zm13.406 10.557c-2.256 0-3.787-2.292-2.923-4.376c.86-2.083 3.563-2.619 5.156-1.025c.595.593.928 1.396.928 2.235a3.16 3.16 0 0 1-3.161 3.167z"
      ></path>
    </svg>
  ),
  nitro: (props?: SVGProps<any>) => (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      fill="currentColor"
      width="1.2em"
      height="1.2em"
      viewBox="0 0 40 40"
      {...props}
    >
      <g clipPath="url(#a)">
        <path
          fill="currentColor"
          fillRule="evenodd"
          d="M35.217 7.02C28.047-1.383 15.424-2.384 7.02 4.785c-8.404 7.169-9.404 19.792-2.236 28.196 7.17 8.403 19.793 9.404 28.196 2.235 8.404-7.169 9.404-19.793 2.236-28.196Zm-9.964 10.497c.77 0 1.262.836.876 1.502l-.112.192L18.47 31.63a.773.773 0 0 1-.661.372h-.72a.755.755 0 0 1-.732-.944l2.048-7.919a1 1 0 0 0-.968-1.25h-3.146a1 1 0 0 1-.968-1.25l3.09-11.955a.923.923 0 0 1 .895-.68c.05 0 .097 0 .135.002h3.168a1 1 0 0 1 .991 1.134l-.02.143-1.207 7.067a1 1 0 0 0 .985 1.168h3.893Z"
          clipRule="evenodd"
        />
        <mask
          id="d"
          x={0}
          y={0}
          maskUnits="userSpaceOnUse"
          style={{
            maskType: "alpha",
          }}
        >
          <circle cx={20} cy={20.001} r={20} fill="currentColor" />
        </mask>
        <g filter="url(#e)" mask="url(#d)">
          <path
            fill="currentColor"
            d="M1.111 13.427a20 20 0 1 0 37.957.541l-5.815 1.84a13.901 13.901 0 1 1-26.381-.376l-5.76-2.005Z"
          />
        </g>
      </g>
      <defs>
        <clipPath id="a">
          <path fill="#fff" d="M0 0h146v40.001H0z" />
        </clipPath>
        <filter
          id="e"
          x={-10}
          y={3.427}
          colorInterpolationFilters="sRGB"
          filterUnits="userSpaceOnUse"
        >
          <feFlood floodOpacity={0} result="BackgroundImageFix" />
          <feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
          <feGaussianBlur result="effect1_foregroundBlur_115_108" stdDeviation={5} />
        </filter>
      </defs>
    </svg>
  ),
};
