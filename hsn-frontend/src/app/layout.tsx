import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "HSN Classifier — AI-Powered GST Code Lookup",
  description: "Instantly classify products to their HSN/GST codes using AI",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased bg-white text-gray-900">{children}</body>
    </html>
  );
}
