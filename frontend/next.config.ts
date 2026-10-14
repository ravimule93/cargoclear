import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Required for pdfjs-dist worker file serving
  webpack: (config) => {
    config.resolve.alias.canvas = false;
    return config;
  },
  // Experimental features for React 19 + App Router
  experimental: {
    serverActions: {
      bodySizeLimit: "50mb",
    },
  },
  async headers() {
    return [
      {
        // Never cache HTML / page routes or API proxy routes in CDN or browser
        source: "/((?!_next/static|_next/image|favicon.ico).*)",
        headers: [
          {
            key: "Cache-Control",
            value: "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0, s-maxage=0",
          },
        ],
      },
      {
        // Static assets with content-hashed names can be cached permanently
        source: "/_next/static/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=31536000, immutable",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
