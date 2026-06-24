import { auth } from "./auth.js";

const PORT = process.env.PORT ?? "3000";
const ALLOWED_ORIGINS = (process.env.TRUSTED_ORIGINS ?? "http://localhost:5173").split(",");

function corsHeaders(origin: string | null) {
  const allowed = origin && ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return {
    "Access-Control-Allow-Origin": allowed,
    "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Allow-Credentials": "true",
  };
}

Bun.serve({
  port: PORT,
  async fetch(req) {
    const url = new URL(req.url);
    const origin = req.headers.get("origin");

    if (req.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    if (url.pathname.startsWith("/api/auth")) {
      const res = await auth.handler(req);
      const headers = new Headers(res.headers);
      for (const [k, v] of Object.entries(corsHeaders(origin))) {
        headers.set(k, v);
      }
      return new Response(res.body, { status: res.status, statusText: res.statusText, headers });
    }

    if (url.pathname === "/health") {
      return Response.json({ status: "ok" });
    }

    return new Response("not found", { status: 404 });
  },
});

console.log(`auth listening on port ${PORT}`);
