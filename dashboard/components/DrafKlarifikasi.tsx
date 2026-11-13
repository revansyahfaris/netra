"use client";

import { useState } from "react";

import type { DrafKlarifikasi as Draf } from "@/lib/api";
import { cn } from "@/lib/format";
import { CopyButton } from "./ui";

const TAB = [
  { kunci: "kartu", label: "Kartu visual" },
  { kunci: "pendek", label: "Versi pendek" },
  { kunci: "whatsapp", label: "WhatsApp" },
] as const;

export function DrafKlarifikasi({ draf }: { draf: Draf }) {
  const [aktif, setAktif] = useState<(typeof TAB)[number]["kunci"]>("kartu");
  const teks = draf[aktif];

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-5 py-3">
        {TAB.map((t) => (
          <button
            key={t.kunci}
            type="button"
            onClick={() => setAktif(t.kunci)}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium transition",
              aktif === t.kunci
                ? "bg-slate-900 text-white"
                : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
            )}
          >
            {t.label}
          </button>
        ))}
        <div className="ml-auto">
          <CopyButton teks={teks} label="Salin draf" />
        </div>
      </div>
      <div className="px-5 py-4">
        <p className="whitespace-pre-wrap rounded-lg bg-slate-50 px-4 py-3 text-sm leading-relaxed text-slate-800 ring-1 ring-inset ring-slate-200">
          {teks}
        </p>
        <p className="mt-2 text-xs text-slate-500">
          Draf dari lapisan AI. Wajib diperiksa dan disetujui petugas sebelum tayang.
        </p>
      </div>
    </div>
  );
}