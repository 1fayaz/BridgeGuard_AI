import type { Metadata } from "next";
import "./globals.css";
import { LangProvider } from "@/lib/lang-context";
import HeaderNav from "@/components/HeaderNav";

export const metadata: Metadata = {
  title: "BridgeGuard AI — Bridge Health Monitoring",
  description: "AI-powered IoT bridge structural health monitoring for Sindh Province, Pakistan",
  icons: {
    icon: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🌉</text></svg>",
    shortcut: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🌉</text></svg>",
    apple: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🌉</text></svg>",
  },
  openGraph: {
    title: "BridgeGuard AI — Protecting Pakistan's Bridges",
    description: "AI-powered bridge monitoring. Real-time risk scores. $199/month.",
    url: "https://bridge-guard-ai.vercel.app",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-gradient-to-br from-slate-50 via-sky-50/40 to-indigo-50/30 text-slate-900">
        <LangProvider>
          <header className="sticky top-0 z-50 border-b border-white/10 bg-slate-900/90 backdrop-blur-md">
            <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-4">
              <a href="/" className="flex items-center gap-2 text-xl font-bold tracking-tight text-white">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-sky-400 to-indigo-500 text-sm shadow-lg shadow-sky-500/25">
                  BG
                </span>
                BridgeGuard AI
              </a>
              <HeaderNav />
            </div>
          </header>
          <main className="mx-auto max-w-7xl px-4 py-10">{children}</main>
        </LangProvider>
      </body>
    </html>
  );
}
