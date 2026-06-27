import type { Metadata, Viewport } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "CricAtlas",
  description: "An evidence-first ODI cricket analysis workbench.",
};

export const viewport: Viewport = {
  themeColor: "#0f1418",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
