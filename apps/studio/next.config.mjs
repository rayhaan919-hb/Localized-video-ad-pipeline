/** @type {import('next').NextConfig} */
const nextConfig = {
  transpilePackages: ['@video-ad/remotion'],
  reactStrictMode: true,
  eslint: {
    ignoreDuringBuilds: true,
  },
};

export default nextConfig;
