import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow cross-origin requests to the Cloud Run API during development
  async rewrites() {
    const apiBase = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8080";
    return [
      {
        source: "/api/proxy/:path*",
        destination: `${apiBase}/api/v1/:path*`,
      },
    ];
  },

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
};

export default nextConfig;
