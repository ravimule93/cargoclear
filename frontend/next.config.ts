import type { NextConfig } from "next";

export const createNextConfig = (environment = process.env.NODE_ENV): NextConfig => ({
  // Bypass legacy immutable dev chunks, including browsers that do not support
  // Clear-Site-Data. Next serves this local asset prefix without changing routes.
  assetPrefix: environment === "development" ? "/_cc-dev-assets" : undefined,
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
        // Only production assets are content-hashed. Development chunk names
        // stay stable across edits and must not keep serving stale JS or CSS.
        source: "/_next/static/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: environment === "production"
              ? "public, max-age=31536000, immutable"
              : "no-store, no-cache, must-revalidate, max-age=0",
          },
        ],
      },
    ];
  },
});

export default createNextConfig();
