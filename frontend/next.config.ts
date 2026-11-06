import type { NextConfig } from "next";
const backend = process.env.SPECTRA_BACKEND_URL ?? "http://127.0.0.1:8000";
const config: NextConfig = {
  poweredByHeader: false,
  distDir: process.env.SELBY_FRONTEND_TEST_DIST_DIR ?? ".next",
  // JSON/base64 evidence transport: 25 MiB originals plus encoding overhead.
  experimental: { proxyClientMaxBodySize: '36mb' },
  async rewrites() {
    // Intake endpoints retain their internal namespace and enforce staff on the backend.
    const internal = { source: "/internal/intake/:path*", destination: `${backend}/internal/intake/:path*` };
    return [{ source: "/api/library/:path*", destination: `${backend}/api/library/:path*` }, internal, { source: "/api/catalog/:path*", destination: `${backend}/api/catalog/:path*` }, { source: "/internal/inspection/:path*", destination: `${backend}/internal/inspection/:path*` }, { source: "/internal/labels/:path*", destination: `${backend}/internal/labels/:path*` }, { source: "/internal/customer-operations/:path*", destination: `${backend}/internal/customer-operations/:path*` }, { source: "/api/addresses/:path*", destination: `${backend}/api/addresses/:path*` }, { source: "/api/submissions/:path*", destination: `${backend}/api/submissions/:path*` }, { source: "/api/auth/:path*", destination: `${backend}/api/auth/:path*` }];
  },
  async headers() {
    return [{ source: '/admin/:path*', headers: [{ key: 'Cache-Control', value: 'private, no-store' }, { key: 'Referrer-Policy', value: 'no-referrer' }] }];
  },
};
export default config;

