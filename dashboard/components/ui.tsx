"use client";

import { useState, type ReactNode } from "react";

import { cn } from "@/lib/format";

export function Badge({
  children,
  className,
  tone,
}: {
  children: ReactNode;
  className?: string;
  tone?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset",
        tone ?? "bg-slate-100 text-slate-700 ring-slate-200",
        className,
      )}
    >
      {children}
    </span>
  );
}

export function SkorBar({
  nilai,
  label,
  compact = false,
}: {
  nilai: number | null;
  label?: string;
  compact?: boolean;
}) {
  const v = Math.max(0, Math.min(nilai ?? 0, 1));
  const warna = v >= 0.75 ? "bg-rose-500" : v >= 0.5 ? "bg-amber-500" : "bg-slate-400";
  return (
    <div className="w-full">
      {label && (
        <div className="mb-1 flex items-center justify-between text-xs text-slate-500">
          <span>{label}</span>
          <span className="font-mono text-slate-700">{nilai == null ? "—" : v.toFixed(2)}</span>
        </div>
      )}
      <div className={cn("w-full overflow-hidden rounded-full bg-slate-200", compact ? "h-1.5" : "h-2")}>
        <div className={cn("h-full rounded-full", warna)} style={{ width: `${v * 100}%` }} />
      </div>
    </div>
  );
}

export function CopyButton({ teks, label = "Salin" }: { teks: string; label?: string }) {
  const [tersalin, setTersalin] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(teks);
          setTersalin(true);
          setTimeout(() => setTersalin(false), 1600);
        } catch {
          setTersalin(false);
        }
      }}
      className="rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-600 transition hover:border-slate-400 hover:text-slate-900"
    >
      {tersalin ? "Tersalin" : label}
    </button>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-xl border border-slate-200 bg-white shadow-sm", className)}>
      {children}
    </section>
  );
}

export function CardHeader({
  judul,
  keterangan,
  aksi,
}: {
  judul: string;
  keterangan?: string;
  aksi?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">{judul}</h2>
        {keterangan && <p className="mt-1 text-sm text-slate-500">{keterangan}</p>}
      </div>
      {aksi}
    </header>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-5 py-10 text-center text-sm text-slate-500">{children}</div>;
}

export function ErrorBox({ pesan, onRetry }: { pesan: string; onRetry?: () => void }) {
  return (
    <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
      <p className="font-medium">Ada yang gagal</p>
      <p className="mt-1 text-rose-700">{pesan}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded-md border border-rose-300 bg-white px-3 py-1 text-xs font-medium text-rose-700 hover:bg-rose-100"
        >
          Coba lagi
        </button>
      )}
    </div>
  );
}

export function Skeleton({ baris = 3 }: { baris?: number }) {
  return (
    <div className="animate-pulse space-y-3 p-5">
      {Array.from({ length: baris }).map((_, i) => (
        <div key={i} className="h-4 rounded bg-slate-200" style={{ width: `${90 - i * 12}%` }} />
      ))}
    </div>
  );
}

export function Stat({ label, nilai, catatan }: { label: string; nilai: ReactNode; catatan?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-slate-900">{nilai}</p>
      {catatan && <p className="text-xs text-slate-500">{catatan}</p>}
    </div>
  );
}