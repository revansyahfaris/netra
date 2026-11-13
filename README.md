# Netra

Sistem pendukung Dinas Penerangan TNI AD untuk **memverifikasi dan mengklarifikasi konten viral yang dimanipulasi**.
Netra tidak mendeteksi hoaks (memakai sistem deteksi yang sudah ada). Netra melacak **sumber asli** sebuah konten,
membuktikan apa yang diubah, lalu menyiapkan klarifikasi yang **disetujui petugas** sebelum tayang.

```
Deteksi (sistem yang ada) → Prioritas → Verifikasi → Klarifikasi → Persetujuan manusia
```

Dokumen: [`PRD.md`](PRD.md) · [`task.md`](task.md) · [`docs/kontrak-data.md`](docs/kontrak-data.md) · [`docs/skrip-demo.md`](docs/skrip-demo.md)

## Struktur

```
backend/
├── main.py            API penghubung semua modul (FastAPI)
├── schemas.py         Kontrak data v2: Klaim, KandidatSumber, HasilVerifikasi, Bukti, persetujuan
├── config.py, llm.py  Konfigurasi & klien LLM bersama
├── priority/          Skor prioritas klaim                         (Faris)
├── search/            Pencarian & peringkat sumber asli            (Faris)
├── ai/                RAG, OCR/transkrip, perbandingan, klarifikasi (Adriel)
├── store/             Penyimpanan Postgres/SQLite, audit, seed     (Farrel)
├── data/dummy/        Klaim & kandidat contoh untuk demo
└── tests/
dashboard/             Antrean, paket bukti, persetujuan petugas, bukti publik (Farrel)
docs/                  Kontrak data & skrip demo
```

## Menjalankan backend

Butuh Python 3.10+ dan **ffmpeg** di PATH (untuk pencocokan frame & audio).

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # isi DATABASE_URL / API key (opsional)
uvicorn main:app --reload
```

Buka `http://localhost:8000/docs`. Cek mode di `GET /health`.

**Tanpa API key** pun API tetap jalan: prioritas memakai klasifikasi kata kunci dan pencarian memakai
data contoh di `data/dummy/kandidat.json`. Isi `GEMINI_API_KEY` dan `SERPAPI_KEY` untuk mode live.

**Database:** kosongkan `DATABASE_URL` untuk SQLite lokal (`backend/data/netra.db`), atau isi connection
string Postgres/Neon. Tabel dibuat otomatis, data demo dimuat saat database masih kosong. Kalau Postgres
tidak bisa dihubungi saat start (DNS putus, Neon tidur), backend mencoba sekali lagi lalu memakai SQLite
lokal supaya API tetap jalan. Cek `database` di `GET /health`.

**Model LLM:** `GEMINI_MODEL` untuk tugas ringan (klasifikasi prioritas, pembuatan query),
`GEMINI_MODEL_VERIFIKASI` untuk OCR, perbandingan, dan klarifikasi:
`llm.tanya_json(prompt, model=config.GEMINI_MODEL_VERIFIKASI, thinking="medium")`.
Default `thinking="low"` supaya cepat dan hemat token. API key dikirim lewat header dan tidak pernah
tercetak di log.

## Menjalankan dashboard

```bash
cd dashboard
npm install
npm run dev          # http://localhost:3000
```

Dashboard memanggil API di `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`). Tidak ada login;
ada pemilih "bertindak sebagai petugas" yang tercatat di audit trail.

Halaman:

| Rute | Isi |
|---|---|
| `/antrean` | Antrean klaim terurut prioritas, filter status/level, ringkasan angka |
| `/klaim/{id}` | Kandidat + rincian skor, paket bukti, draf klarifikasi 3 format, persetujuan, audit |
| `/bukti/{id}` | Halaman bukti publik (tanpa catatan internal), diberi label SIMULASI |

## Endpoint

| Endpoint | Fungsi |
|---|---|
| `POST /prioritas` | Terima klaim, beri skor & level prioritas |
| `GET /antrean?status=&level=` | Klaim terurut, lengkap dengan status verifikasi |
| `GET /klaim/{id}` | Klaim + pencarian + verifikasi + riwayat audit |
| `POST /cari/{id}` | Cari kandidat sumber asli, terurut. Body opsional `{"url_manual": [...]}` |
| `GET /cari/{id}/proses` | Query yang dipakai & rincian skor tiap kandidat |
| `POST /verifikasi/{id}` | Bandingkan konten viral vs sumber, buat draf klarifikasi |
| `PATCH /verifikasi/{id}/persetujuan` | Petugas menyetujui / menolak (`keputusan`, `petugas`, `catatan`) |
| `GET /bukti/{id}` | Proyeksi publik untuk halaman bukti |
| `GET /statistik` | Angka ringkas untuk dashboard |
| `POST /pipeline/{id}` | Cari + verifikasi sekaligus (untuk demo) |
| `POST /seed` | Reset data demo (dev) |

## Cara kerja

**Prioritas** — `skor = 0.4·sensitivitas + 0.3·laju_sebar + 0.2·jangkauan + 0.1·kebaruan`.
Sensitivitas dari klasifikasi topik oleh LLM (pimpinan, operasi, SARA, keselamatan, umum),
cadangannya daftar kata kunci. Level: tinggi ≥ 0.65, sedang ≥ 0.4.

**Pencarian sumber asli**
1. LLM membuat variasi query: kutipan persis + kata kunci tanpa narasi waktu yang dipelintir.
2. Pencarian Google (kata kunci & kutipan), YouTube, dan Google Lens untuk gambar (SerpAPI).
3. Untuk video: unduh kandidat (yt-dlp), cocokkan frame dengan perceptual hash
   (tepi frame dipotong supaya watermark tidak mengganggu) dan cocokkan pola audio.
   Hasilnya juga menunjukkan detik ke berapa potongan viral berasal di video asli.
4. Peringkat kandidat: kemiripan 30%, tanggal unggah paling awal 25%, jenis sumber 15%,
   resolusi 10%, bebas watermark 10%, kecocokan audio 10%.

**Persetujuan manusia** — draf klarifikasi hanya tayang setelah petugas menyetujui. Penolakan wajib
disertai catatan. Setiap keputusan masuk audit trail.

Kalau sumber tertua pun terindikasi dimanipulasi atau tidak ada sumber pendukung,
status keluarannya `belum_bisa_diverifikasi` / `tidak_ditemukan` dan dieskalasi ke petugas —
bukan dipaksakan menjadi klarifikasi.

## Deploy

**Hugging Face Spaces (gratis, tanpa kartu):** buat Space SDK **Gradio** (template Blank, CPU basic),
isi secret `GEMINI_API_KEY`, `SERPAPI_KEY`, `DATABASE_URL`, `GEMINI_MODEL`, `GEMINI_MODEL_VERIFIKASI`,
lalu push isi folder `backend/` ke repo Space (jangan timpa `README.md` milik Space). `app.py`
menjalankan API FastAPI yang sama, plus halaman uji di `/ui`; `packages.txt` memasang ffmpeg.

**Render / server dengan Docker:** pakai `backend/Dockerfile` (atau `render.yaml`). Container jalan
sebagai user non-root.

Space/instance gratis tidur kalau lama tidak dipakai: buka `/health` sebelum demo.

## Tes

```bash
cd backend && pytest -q
```

## Kasus demo

| Kasus | Klaim | Jalur | Status |
|---|---|---|---|
| Formal | `c002` | RAG korpus resmi → kutipan tidak ada | `terbukti_diubah` |
| Informal | `c001` | frame match video 2019 → potongan 00:42 | `terbukti_diubah` |
| Worst case | `c001b` | semua kandidat pribadi/watermark | `belum_bisa_diverifikasi` + eskalasi |
| Tanpa sumber | `c004` | tidak ada kandidat | `tidak_ditemukan` + eskalasi |

Semua data demo sintetis dan diberi label SIMULASI.

**Kasus nyata (opsional, `DEMO_KASUS_NYATA=1`):** `r001` video Intan Jaya (rekaman 2021, narasi 2026),
`r002` pelintiran pernyataan Kapuspen TNI 2019, `r003` video tank ke Kepri (konten lama 2023). Data di
`backend/data/kasus_nyata/`, kandidat memakai artikel klarifikasi yang benar-benar ada. Menyebut
peristiwa dan pejabat nyata, jadi sepakati tim sebelum dipakai di video.