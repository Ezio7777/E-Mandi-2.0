import type { NextConfig } from "next";

const imageHosts = (process.env.IMAGE_REMOTE_HOSTS ?? "")
  .split(",").map((h) => h.trim()).filter(Boolean);

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(self), microphone=(self), geolocation=(self)" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin-allow-popups" },
];

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  images: {
    formats: ["image/avif", "image/webp"],
    remotePatterns: imageHosts.map((hostname) => ({ protocol: "https" as const, hostname })),
  },
  experimental: { optimizePackageImports: ["lucide-react", "framer-motion", "recharts"] },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};
export default nextConfig;
