import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "FRUZAQLA Content Generator — Solistic Health",
  description: "Generate FDA-compliant pharma marketing content from approved claims and clinical literature",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <nav className="bg-primary text-white px-6 py-3 flex items-center gap-4 text-sm shadow-sm">
          <a href="/" className="font-bold text-base tracking-tight">Solistic Health</a>
          <span className="opacity-30">|</span>
          <span className="text-xs opacity-60">FRUZAQLA Content Studio</span>
          <div className="flex-1" />
          <a href="/chat" className="opacity-70 hover:opacity-100 transition-opacity">Briefing</a>
          <a href="/preview" className="opacity-70 hover:opacity-100 transition-opacity">Preview</a>
        </nav>
        <main className="max-w-5xl mx-auto px-4 py-8">{children}</main>
      </body>
    </html>
  );
}
