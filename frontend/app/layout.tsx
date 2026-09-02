import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BridgeGuard AI",
  description: "AI-powered IoT bridge infrastructure health monitoring",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50 text-slate-900">
        <header className="bg-slate-900 text-white">
          <div className="mx-auto max-w-6xl px-4 py-4 flex items-center justify-between">
            <a href="/" className="text-xl font-bold tracking-tight">
              BridgeGuard AI
            </a>
            <nav className="flex gap-6 text-sm font-medium">
              <a href="/" className="hover:text-sky-300 transition">
                Overview
              </a>
              <a href="/agents" className="hover:text-sky-300 transition">
                AI Agents
              </a>
              <a href="/reports" className="hover:text-sky-300 transition">
                Reports
              </a>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
      </body>
    </html>
  );
}
