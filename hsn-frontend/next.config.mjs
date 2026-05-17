/** @type {import('next').NextConfig} */

// BACKEND_URL (Vercel server env) or NEXT_PUBLIC_API_URL — see README_DEPLOYMENT.md
const backendUrl = (
  process.env.NEXT_PUBLIC_API_URL ||
  process.env.BACKEND_URL ||
  ''
).replace(/\/$/, '');

const nextConfig = {
  env: {
    // Expose backend URL to client when set at build time (optional; /api proxy still works)
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || process.env.BACKEND_URL || '',
  },
  async rewrites() {
    if (!backendUrl) {
      console.warn(
        '[next.config] Set BACKEND_URL or NEXT_PUBLIC_API_URL on Vercel so /api proxies to Render.'
      );
      return [];
    }
    return [{ source: '/api/:path*', destination: `${backendUrl}/:path*` }];
  },
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
        ],
      },
    ];
  },
};

export default nextConfig;
