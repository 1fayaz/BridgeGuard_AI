/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    domains: [],
    unoptimized: false,
  },
  async rewrites() {
    return [
      {
        source: "/v1/:path*",
        destination: "/api/index",
      },
    ];
  },
};

export default nextConfig;
