/** @type {import('next').NextConfig} */

// Proxy target for /api/* → backend (set on Vercel at build time).
// Prefer BACKEND_URL so the browser bundle can stay same-origin (/api only).
// NEXT_PUBLIC_API_URL still works for backwards compatibility.
const backendUrl = process.env.BACKEND_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "";
const backendOrigin = backendUrl.replace(/\/$/, "");

if (process.env.NODE_ENV === "production" && !backendOrigin) {
  console.warn(
    "[next.config] Production build: neither BACKEND_URL nor NEXT_PUBLIC_API_URL is set. " +
      "Client uses same-origin /api; add BACKEND_URL (or NEXT_PUBLIC_API_URL) on Vercel so rewrites can reach your backend."
  );
}

const nextConfig = {
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
  async rewrites() {
    if (!backendOrigin) return [];
    return [
      {
        source: "/api/:path*",
        destination: `${backendOrigin}/:path*`,
      },
    ];
  },
};

export default nextConfig;
