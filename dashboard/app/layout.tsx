import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Netra — Verifikasi & Klarifikasi Konten Viral",
  description:
    "Sistem pendukung verifikasi sumber asli konten viral dan penyusunan klarifikasi dengan persetujuan petugas.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id">
      <body className="min-h-screen">{children}</body>
    </html>
  );
}