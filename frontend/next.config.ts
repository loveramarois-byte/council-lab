import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  devIndicators: false,
  distDir: process.env.COUNCIL_NEXT_DIST_DIR || ".next",
  output: process.env.COUNCIL_STANDALONE === "1" ? "standalone" : undefined,
  async rewrites() {
    const backendUrl = process.env.COUNCIL_BACKEND_URL || "http://127.0.0.1:8001";
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
};

export default nextConfig;
