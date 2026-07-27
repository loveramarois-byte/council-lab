import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  devIndicators: false,
  output: process.env.COUNCIL_STANDALONE === "1" ? "standalone" : undefined,
};

export default nextConfig;
