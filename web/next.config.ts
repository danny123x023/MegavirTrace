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
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND}/:path*` }];
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
