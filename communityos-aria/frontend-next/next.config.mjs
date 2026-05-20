/** @type {import('next').NextConfig} */

// Backend the Next.js dev/prod server proxies API calls to.
// Override with ARIA_API_TARGET in .env.local for local backend dev.
const ARIA_API = process.env.ARIA_API_TARGET || "https://aria-backend-vyn0.onrender.com";

const nextConfig = {
  reactStrictMode: true,

  // Same-origin proxy so the browser doesn't need CORS for the deployed
  // ARIA backend. app.js calls /aria/login, /aria/chat, /society/*, /health
  // — the Next server rewrites those to the live Render URL.
  async rewrites() {
    return [
      { source: "/aria/:path*", destination: `${ARIA_API}/aria/:path*` },
      { source: "/society/:path*", destination: `${ARIA_API}/society/:path*` },
      { source: "/health", destination: `${ARIA_API}/health` },
    ];
  },
};

export default nextConfig;
