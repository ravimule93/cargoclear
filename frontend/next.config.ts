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
};

export default nextConfig;
