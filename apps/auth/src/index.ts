import { auth } from "./auth.js";

const PORT = process.env.PORT ?? "3000";

Bun.serve({
  port: PORT,
  async fetch(req) {
    const url = new URL(req.url);

    if (url.pathname.startsWith("/api/auth")) {
      return auth.handler(req);
    }

    if (url.pathname === "/health") {
      return Response.json({ status: "ok" });
    }

    return new Response("not found", { status: 404 });
  },
});

console.log(`auth listening on port ${PORT}`);
