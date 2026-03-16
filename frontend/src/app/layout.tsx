import type { Metadata } from "next";
import "./globals.css";
import StoreHydrator from "@/components/StoreHydrator";

export const metadata: Metadata = {
  title: "FPL · Intelligence",
  description: "Squad analysis and transfer intelligence for Fantasy Premier League.",
  icons: {
    icon: [
      { url: "/favicon.ico?v=3", sizes: "any" },
      { url: "/favicon-32.png?v=3", type: "image/png", sizes: "32x32" },
      { url: "/icon.svg?v=3", type: "image/svg+xml" },
    ],
    shortcut: "/favicon.ico?v=3",
    apple: "/apple-touch-icon.png?v=3",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="icon" href="/favicon.ico?v=3" sizes="any" />
        <link rel="icon" href="/favicon-32.png?v=3" type="image/png" sizes="32x32" />
        <link rel="icon" href="/icon.svg?v=3" type="image/svg+xml" />
        <link rel="shortcut icon" href="/favicon.ico?v=3" />
        <link rel="apple-touch-icon" href="/apple-touch-icon.png?v=3" sizes="180x180" />
        {/* Fontshare — Clash Display + Satoshi */}
        <link rel="preconnect" href="https://api.fontshare.com" />
        <link
          href="https://api.fontshare.com/v2/css?f[]=clash-display@400,500,600,700&f[]=satoshi@400,500,600,700&display=swap"
          rel="stylesheet"
        />
        {/* Google Fonts — JetBrains Mono */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <StoreHydrator />
        {children}
      </body>
    </html>
  );
}
