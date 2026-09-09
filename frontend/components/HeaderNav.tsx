"use client";
import { useLang } from "@/lib/lang-context";

export default function HeaderNav() {
  const { lang, t, toggleLang } = useLang();
  return (
    <nav className="header-nav flex items-center gap-1 text-sm font-medium">
      <a
        href="/"
        className="rounded-md px-4 py-2 text-slate-300 transition hover:bg-white/10 hover:text-white"
      >
        {t.overview}
      </a>
      <a
        href="/agents"
        className="rounded-md px-4 py-2 text-slate-300 transition hover:bg-white/10 hover:text-white"
      >
        {t.agents}
      </a>
      <a
        href="/reports"
        className="rounded-md px-4 py-2 text-slate-300 transition hover:bg-white/10 hover:text-white"
      >
        {t.reports}
      </a>
      <button
        onClick={toggleLang}
        className="ms-3 rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 transition hover:bg-white/10 hover:text-white"
        aria-label={lang === "en" ? "Switch to Urdu" : "Switch to English"}
      >
        {lang === "en" ? "اردو" : "English"}
      </button>
    </nav>
  );
}
