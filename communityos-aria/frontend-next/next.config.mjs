/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Useful for Vercel previews — exposes the build commit if Vercel sets it.
  env: {
    BUILD_SHA: process.env.VERCEL_GIT_COMMIT_SHA || 'dev',
  },
};

export default nextConfig;
