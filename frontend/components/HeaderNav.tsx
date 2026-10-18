"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const ACTIVE = "text-navy shadow-[inset_0_-3px_0_#0081D3]";
const INACTIVE = "text-navy-text hover:bg-page-bg";

function NavLink({ href, children, exact }: { href: string; children: React.ReactNode; exact?: boolean }) {
  const pathname = usePathname();
  const active = exact ? pathname === href : pathname.startsWith(href);
  return (
    <Link
      href={href}
      className={`rounded-md px-4 py-4 text-[15px] font-semibold transition ${active ? ACTIVE : INACTIVE}`}
    >
      {children}
    </Link>
  );
}

/** Nav uses a fixed sample alert count badge sourced from lib/data.ts fixtures — real counts (once
 * a live alerts endpoint exists) replace this value, not the badge's presence. */
export default function HeaderNav({ alertCount }: { alertCount: number }) {
  return (
    <nav className="flex flex-wrap items-center gap-0.5 text-sm font-medium">
      <NavLink href="/" exact>
        Overview
      </NavLink>
      <NavLink href="/alerts">
        Alerts
        {alertCount > 0 && (
          <span className="ms-2 rounded-full bg-urgent px-2 py-0.5 text-xs font-bold text-white">
            {alertCount}
          </span>
        )}
      </NavLink>
      <NavLink href="/agents">AI Agents</NavLink>
      <NavLink href="/reports">Reports</NavLink>
    </nav>
  );
}
