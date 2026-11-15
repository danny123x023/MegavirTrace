import type { NextConfig } from "next";

// The browser talks only to this origin; /api/* is proxied to the FastAPI service (which keeps
// the strict Origin check).  In production nginx does the same proxying.
const BACKEND = process.env.MEGAVIR_BACKEND_URL ?? "http://127.0.0.1:8000";

const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'" + (process.env.NODE_ENV === "development" ? " 'unsafe-eval'" : ""),
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "worker-src 'self' blob:",
  "connect-src 'self'",
  "font-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
].join("; ");

const nextConfig: NextConfig = {
  poweredByHeader: false,
  agentRules: false,
  allowedDevOrigins: ["127.0.0.1"],
  // AI answers can take several tool rounds; the default proxy limit (30 s) would cut them off
  experimental: { proxyTimeout: 120_000 },
  // Explore lived at "/" before the landing page: shared links and embed cards on other sites keep working
  async redirects() {
    return ["v", "place", "bbox"].map((key) => ({ source: "/", has: [{ type: "query" as const, key }], destination: "/explore", permanent: false }));
  },
  async rewrites() {
    const api = [{ source: "/api/:path*", destination: `${BACKEND}/:path*` }];
    if (process.env.NODE_ENV !== "development") return api;
    // In development /sw.js is a worker that removes itself and any worker a production build left
    // on this address (public/sw-reset.js); "beforeFiles" lets it take precedence over public/sw.js.
    return { beforeFiles: [{ source: "/sw.js", destination: "/sw-reset.js" }], afterFiles: api, fallback: [] };
  },
  async headers() {
    return [
      {
        source: "/((?!embed).*)",
        headers: [
          { key: "Content-Security-Policy", value: csp + "; frame-ancestors 'none'" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
        ],
      },
      {
        source: "/embed/:path*",
        headers: [{ key: "Content-Security-Policy", value: csp + "; frame-ancestors *" }],
      },
    ];
  },
};

export default nextConfig;
