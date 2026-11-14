"""Evaluasi Netra pada semua kasus demo, supaya hasilnya bisa dicek ulang siapa pun.

Jalankan dari folder backend:

    python scripts/evaluasi.py                 # mode demo, gratis, tanpa API key
    python scripts/evaluasi.py --live          # pakai Gemini & SerpAPI dari .env (berbayar)
    python scripts/evaluasi.py --tulis ../docs/hasil-evaluasi.md

Label kebenaran per kasus ada di data/evaluasi_label.json dan diisi tim, bukan oleh sistem.
Kasus yang labelnya kosong tetap ditampilkan, tapi tidak dihitung ke akurasi.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LABEL_STATUS = {
    "terbukti_diubah": "Terbukti diubah",
    "tidak_ditemukan": "Sumber tidak ditemukan",
    "belum_bisa_diverifikasi": "Dieskalasi ke petugas",
}


def siapkan_lingkungan(live: bool) -> None:
    # Database sementara agar evaluasi tidak menyentuh data demo yang dipakai juri
    os.environ["DATABASE_URL"] = ""
    os.environ["SQLITE_PATH"] = str(Path(tempfile.mkdtemp()) / "evaluasi.db")
    os.environ["SEED_KALAU_KOSONG"] = "0"
    os.environ["IZINKAN_SEED"] = "1"
    os.environ["DEMO_KASUS_NYATA"] = "1"
    os.environ["BATAS_PROSES_HARIAN"] = "0"
    os.environ["JEDA_PROSES_ULANG_MENIT"] = "0"
    if not live:
        os.environ["GEMINI_API_KEY"] = ""
        os.environ["SERPAPI_KEY"] = ""
        os.environ["STT_BASE_URL"] = ""


def muat_label() -> dict:
    p = ROOT / "data" / "evaluasi_label.json"
    if not p.exists():
        return {}
    return {k: v for k, v in json.loads(p.read_text()).items() if not k.startswith("_")}


def jalankan(live: bool) -> list[dict]:
    siapkan_lingkungan(live)
    from fastapi.testclient import TestClient

    import main

    c = TestClient(main.app)
    c.post("/seed")
    label = muat_label()
    baris = []
    for item in c.get("/antrean").json():
        k = item["klaim"]
        mulai = time.perf_counter()
        r = c.post(f"/pipeline/{k['claim_id']}")
        durasi = time.perf_counter() - mulai
        if r.status_code != 200:
            baris.append({"id": k["claim_id"], "klaim": k["teks_klaim"], "galat": r.text[:120]})
            continue
        h = r.json()
        kandidat = h["pencarian"]["kandidat"]
        v = h["verifikasi"]
        harapan = (label.get(k["claim_id"]) or {}).get("status")
        baris.append(
            {
                "id": k["claim_id"],
                "klaim": k["teks_klaim"],
                "prioritas": k.get("skor_prioritas"),
                "level": k.get("level"),
                "sumber_teratas": kandidat[0]["url"] if kandidat else None,
                "skor_teratas": kandidat[0].get("skor") if kandidat else None,
                "jumlah_kandidat": len(kandidat),
                "status": v["status"],
                "keyakinan": v.get("keyakinan"),
                "jumlah_bukti": len(v.get("bukti") or []),
                "eskalasi": v.get("perlu_eskalasi"),
                "harapan": harapan,
                "cocok": (harapan == v["status"]) if harapan else None,
                "detik": round(durasi, 1),
            }
        )
    return baris


def ke_markdown(baris: list[dict], live: bool) -> str:
    dinilai = [b for b in baris if b.get("cocok") is not None]
    benar = sum(1 for b in dinilai if b["cocok"])
    salah_tuduh = sum(
        1 for b in dinilai if b["status"] == "terbukti_diubah" and b["harapan"] != "terbukti_diubah"
    )
    out = [
        "# Hasil evaluasi Netra",
        "",
        f"Mode: **{'live (Gemini + SerpAPI)' if live else 'demo (tanpa API berbayar)'}** · "
        f"{len(baris)} kasus · dibuat dengan `python scripts/evaluasi.py`",
        "",
    ]
    if dinilai:
        out += [
            f"- Status verifikasi sesuai label tim: **{benar}/{len(dinilai)}**",
            f"- Salah menuduh konten asli sebagai manipulasi (false positive): **{salah_tuduh}**",
            "",
        ]
    out += [
        "| Kasus | Klaim | Prioritas | Status Netra | Label tim | Keyakinan | Bukti | Waktu |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for b in baris:
        if "galat" in b:
            out.append(f"| {b['id']} | {b['klaim'][:60]} | – | galat: {b['galat']} | | | | |")
            continue
        klaim = b["klaim"].replace("|", "/")
        klaim = klaim if len(klaim) <= 70 else klaim[:67] + "..."
        prio = f"{b['prioritas']:.2f} ({b['level']})" if b["prioritas"] is not None else "–"
        yakin = f"{b['keyakinan']:.0%}" if b["keyakinan"] is not None else "–"
        tanda = "" if b["cocok"] is None else (" ✓" if b["cocok"] else " ✗")
        out.append(
            f"| {b['id']} | {klaim} | {prio} | {LABEL_STATUS.get(b['status'], b['status'])}{tanda} | "
            f"{LABEL_STATUS.get(b['harapan'], '–') if b['harapan'] else '–'} | {yakin} | "
            f"{b['jumlah_bukti']} | {b['detik']}s |"
        )
    out += [
        "",
        "Catatan: mode demo memakai kandidat sumber yang sudah disiapkan di `data/`, jadi angka ini "
        "menguji logika peringkat, verifikasi, dan eskalasi, bukan kualitas mesin pencari.",
    ]
    return "\n".join(out) + "\n"


def utama() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="pakai API berbayar dari .env")
    ap.add_argument("--tulis", help="simpan tabel markdown ke file ini")
    a = ap.parse_args()
    baris = jalankan(a.live)
    md = ke_markdown(baris, a.live)
    print(md)
    if a.tulis:
        Path(a.tulis).write_text(md)
        print(f"Tersimpan di {a.tulis}")


if __name__ == "__main__":
    utama()
