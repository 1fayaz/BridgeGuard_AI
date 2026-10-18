import type { Metadata } from "next";
import Link from "next/link";
import Image from "next/image";
import "./globals.css";
import HeaderNav from "@/components/HeaderNav";
import Footer from "@/components/Footer";
import PageLoader from "@/components/PageLoader";
import { BRIDGES } from "@/lib/data";

export const metadata: Metadata = {
  title: "BridgeGuard AI — Bridge Health Monitoring",
  description: "AI-powered IoT bridge structural health monitoring for Sindh Province, Pakistan",
  icons: {
    icon: "/logo-icon.png",
    shortcut: "/logo-icon.png",
    apple: "/logo-icon.png",
  },
  openGraph: {
    title: "BridgeGuard AI — Protecting Pakistan's Bridges",
    description: "AI-powered bridge monitoring. Real-time risk scores.",
    url: "https://bridge-guard-ai.vercel.app",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const alertCount = BRIDGES.reduce((n, b) => n + b.alerts.length, 0);

  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700&family=Montserrat:wght@600;700;800&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-screen bg-page-bg font-sans text-navy-deep antialiased">
        <PageLoader />

        {/* Permanent public-site ribbon — every page, always visible, never dismissible. */}
        <div className="bg-navy-deep px-4 py-1.5 text-center text-[12px] font-semibold tracking-wide text-white">
          Sample data, not real conditions.
        </div>
        <div
          className="h-[5px]"
          style={{ background: "linear-gradient(90deg, #00325D 0%, #0081D3 55%, #097F37 100%)" }}
        />

        <header className="sticky top-0 z-40 border-b border-border bg-white">
          <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-3.5 px-5 py-2.5 sm:px-10">
            <Link href="/" className="flex items-center gap-2.5">
              <Image src="/logo-icon.png" alt="" width={42} height={42} className="h-[42px] w-auto" priority />
              <span className="font-display text-lg font-extrabold tracking-tight text-navy">
                BridgeGuard <span className="text-safe">AI</span>
              </span>
            </Link>
            <HeaderNav alertCount={alertCount} />
            <div className="flex items-center gap-3">
              <span className="inline-flex items-center gap-2 rounded-full bg-safe-bg px-3.5 py-1.5 text-[13px] font-semibold text-safe-text">
                <span className="h-2 w-2 rounded-full bg-safe" />
                Live
              </span>
              <Link
                href="/demo"
                className="rounded-xl bg-blue px-4 py-2.5 text-sm font-bold text-white shadow-sm transition hover:bg-blue-bright"
              >
                Watch the demo
              </Link>
            </div>
          </div>
        </header>

        <main className="mx-auto max-w-[1200px] px-5 py-9 sm:px-10">{children}</main>

        <Footer />
      </body>
    </html>
  );
}
