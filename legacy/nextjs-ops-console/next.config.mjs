/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Keep external integration packages (nodemailer, bullmq, ioredis, prisma)
  // out of the edge/bundling concerns where needed.
  experimental: {
    serverComponentsExternalPackages: [
      "@prisma/client",
      "bullmq",
      "ioredis",
      "nodemailer",
      "exceljs",
    ],
  },
};

export default nextConfig;
