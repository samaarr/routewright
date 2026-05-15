/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  experimental: {
    typedRoutes: true,
  },
  // In dev, proxy /api/* to the FastAPI backend so the browser never makes
  // a cross-origin request and no CORS headers are needed.
  // In production (Vercel → Railway), set NEXT_PUBLIC_API_URL instead.
  async rewrites() {
    return process.env.NEXT_PUBLIC_API_URL
      ? [] // production: direct fetch, no proxy
      : [{ source: "/api/:path*", destination: "http://localhost:8000/api/:path*" }];
  },
};

module.exports = nextConfig;
