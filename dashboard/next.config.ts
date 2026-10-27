import type { NextConfig } from "next";

// A Vercel deployment has no backend, so it is the read-only demo unless told otherwise.
const demoMode = process.env.NEXT_PUBLIC_DEMO_MODE ?? (process.env.VERCEL ? "true" : "false");

const nextConfig: NextConfig = {
  // Standalone output is for the Docker image; Vercel uses its own build output.
  output: process.env.VERCEL ? undefined : "standalone",
  env: { NEXT_PUBLIC_DEMO_MODE: demoMode },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
