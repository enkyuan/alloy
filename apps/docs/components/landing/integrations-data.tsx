import type { ReactNode } from "react";

export const featuredIcons: Record<string, () => ReactNode> = {
  "Next.js": () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 256 256">
      <defs>
        <linearGradient id="SVGkw9x5bVJ" x1="55.633%" x2="83.228%" y1="56.385%" y2="96.08%">
          <stop offset="0%" stopColor="#FFF" />
          <stop offset="100%" stopColor="#FFF" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="SVGE3ljGbCT" x1="50%" x2="49.953%" y1="0%" y2="73.438%">
          <stop offset="0%" stopColor="#FFF" />
          <stop offset="100%" stopColor="#FFF" stopOpacity="0" />
        </linearGradient>
        <circle id="SVGMFHNZdYm" cx="128" cy="128" r="128" />
      </defs>
      <mask id="SVGalfYF1HT" fill="#fff">
        <use href="#SVGMFHNZdYm" />
      </mask>
      <g mask="url(#SVGalfYF1HT)">
        <circle cx="128" cy="128" r="128" fill="currentColor" />
        <path
          fill="url(#SVGkw9x5bVJ)"
          d="M212.634 224.028L98.335 76.8H76.8v102.357h17.228V98.68L199.11 234.446a128 128 0 0 0 13.524-10.418"
        />
        <path fill="url(#SVGE3ljGbCT)" d="M163.556 76.8h17.067v102.4h-17.067z" />
      </g>
    </svg>
  ),
};

export const featured = [
  {
    name: "Next.js",
    icon: "nextJS",
    href: "/docs/integrations/next",
    snippet: "export { POST } from '@/lib/agent'",
  },
  {
    name: "Express",
    icon: "express",
    href: "/docs/integrations/express",
    snippet: "app.post('/agent', agent.handler)",
  },
  {
    name: "Fastify",
    icon: "fastify",
    href: "/docs/integrations/fastify",
    snippet: "fastify.post('/agent', agent.handler)",
  },
  {
    name: "Hono",
    icon: "hono",
    href: "/docs/integrations/hono",
    snippet: "app.post('/agent', agent.handler)",
  },
  {
    name: "Nuxt",
    icon: "nuxt",
    href: "/docs/integrations/nuxt",
    snippet: "defineEventHandler(agent.route)",
  },
  {
    name: "SvelteKit",
    icon: "svelteKit",
    href: "/docs/integrations/svelte-kit",
    snippet: "export const POST = agent.route",
  },
] as const;

export const moreFrameworks = [
  { name: "FastAPI", icon: "fastapi", href: "/docs/integrations/fastapi" },
  { name: "Flask", icon: "flask", href: "/docs/integrations/flask" },
  { name: "Django", icon: "django", href: "/docs/integrations/django" },
  { name: "Starlette", icon: "starlette", href: "/docs/integrations/starlette" },
  { name: "NestJS", icon: "nestJS", href: "/docs/integrations/nestjs" },
  { name: "TanStack", icon: "tanstack", href: "/docs/integrations/tanstack" },
  { name: "Remix", icon: "remix", href: "/docs/integrations/remix" },
  { name: "Astro", icon: "astro", href: "/docs/integrations/astro" },
  { name: "Elysia", icon: "elysia", href: "/docs/integrations/elysia" },
  { name: "Expo", icon: "expo", href: "/docs/integrations/expo" },
] as const;
