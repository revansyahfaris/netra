import { Nav } from "@/components/Nav";

export default function LayoutInternal({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
      <main className="mx-auto w-full max-w-7xl flex-1 px-5 py-6">{children}</main>
      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 px-5 py-3 text-xs text-slate-500">
          <span>Netra · prototipe Dispenad · data demo bersifat simulasi</span>
          <span>Klarifikasi selalu melewati persetujuan petugas</span>
        </div>
      </footer>
    </div>
  );
}