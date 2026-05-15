/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Output static-export-friendly build by default; Vercel auto-detects features.
  poweredByHeader: false,
  experimental: {
    typedRoutes: true,
  },
};

module.exports = nextConfig;
