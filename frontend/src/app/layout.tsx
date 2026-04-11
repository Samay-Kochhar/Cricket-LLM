import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CricAtlas",
  description: "An evidence-first ODI cricket analysis workbench.",
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
