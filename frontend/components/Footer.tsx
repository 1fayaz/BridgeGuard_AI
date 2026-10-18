import Link from "next/link";
import Image from "next/image";

export default function Footer() {
  return (
    <footer className="mt-12 border-t border-border bg-white">
      <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-9 px-5 py-9 sm:px-10">
        <Image
          src="/logo-full.png"
          alt="BridgeGuard AI — smarter bridges, safer tomorrow"
          width={190}
          height={186}
          className="h-auto w-[140px] sm:w-[170px]"
        />
        <p className="max-w-[460px] flex-1 text-[15px] leading-relaxed text-navy-text" style={{ minWidth: 260 }}>
          BridgeGuard AI watches bridges around the clock, so engineers can act
          before a problem becomes a danger.
        </p>
        <nav className="flex flex-col gap-2.5 text-[15px] font-semibold text-navy">
          <Link href="/">Overview</Link>
          <Link href="/alerts">Alerts</Link>
          <Link href="/agents">AI Agents</Link>
          <Link href="/reports">Reports</Link>
        </nav>
      </div>
      <div className="bg-page-bg px-5 py-3.5 text-center text-[13px] text-navy-muted sm:px-10">
        Demonstration screens with sample data. Final safety decisions are
        always made by a qualified engineer.
      </div>
    </footer>
  );
}
