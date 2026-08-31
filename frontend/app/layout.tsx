import type { Metadata } from "next";
import "./globals.css";
import Link from "next/link";

export const metadata: Metadata = {
  title: "BridgeGuard AI",
  description: "AI-powered bridge structural health monitoring",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <header className="bg-white border-b border-gray-100 h-14 flex items-center justify-between px-6 sticky top-0 z-50">
          <Link href="/" className="flex items-center gap-2 no-underline">
            <div className="w-8 h-8 rounded-lg flex items-center justify-center text-white text-base" style={{backgroundColor:"#0F6E56"}}>
              🌉
            </div>
            <div>
              <div className="text-sm font-medium text-gray-900">BridgeGuard AI</div>
              <div className="text-xs text-gray-400">Infrastructure monitoring</div>
            </div>
          </Link>
          <nav className="flex gap-1">
            <Link href="/" className="px-3 py-1.5 rounded-lg text-sm text-gray-600 hover:bg-gray-50 no-underline">Overview</Link>
            <Link href="/reports" className="px-3 py-1.5 rounded-lg text-sm text-gray-600 hover:bg-gray-50 no-underline">Reports</Link>
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}