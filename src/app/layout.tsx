import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CRM 营销自动化平台",
  description: "CRM + 全链路营销自动化 MVP",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
