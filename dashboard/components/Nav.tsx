import Link from "next/link";

import { API_BASE } from "@/lib/api";

export function Nav() {
  return (
    <header className="border-b border-slate-800 bg-slate-900">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-4 px-5 py-3">
        <Link href="/antrean" className="flex items-baseline gap-3">
          <span className="text-lg font-semibold tracking-[0.2em] text-white">NETRA</span>
          <span className="hidden text-xs text-slate-400 sm:inline">
            Verifikasi &amp; klarifikasi konten viral
          </span>
        </Link>
        <nav className="ml-auto flex items-center gap-1 text-sm">
          <Link
            href="/antrean"
            className="rounded-md px-3 py-1.5 text-slate-300 transition hover:bg-slate-800 hover:text-white"
          >
            Antrean
          </Link>
          <a
            href={`${API_BASE}/docs`}
            target="_blank"
            rel="noreferrer"
            className="rounded-md px-3 py-1.5 text-slate-300 transition hover:bg-slate-800 hover:text-white"
          >
            API
          </a>
          <span className="ml-2 rounded-full border border-amber-400/40 bg-amber-400/10 px-2.5 py-0.5 text-xs font-medium text-amber-200">
            Prototipe · data simulasi
          </span>
        </nav>
      </div>
    </header>
  );
}