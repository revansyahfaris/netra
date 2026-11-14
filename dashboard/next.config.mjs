const backendInternalUrl = (process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:8000").replace(
  /\/+$/,
  "",
);

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  devIndicators: false,
  async rewrites() {
    if (process.env.NEXT_PUBLIC_API_URL?.trim()) {
      return [];
    }
    return [
      {
        source: "/api/:path*",
        destination: `${backendInternalUrl}/:path*`,
      },
      {
        source: "/openapi.json",
        destination: `${backendInternalUrl}/openapi.json`,
      },
    ];
  },
};

export default nextConfig;
