# Netra

**Netra tidak menebak hoaks. Netra membuktikannya.**

Sistem pendukung Dinas Penerangan TNI AD untuk **memverifikasi dan mengklarifikasi konten viral yang dimanipulasi**.
Deteksi sudah dikerjakan sistem yang ada. Netra mengambil alih setelahnya: melacak **sumber asli**,
membuktikan **apa yang diubah**, lalu menyiapkan klarifikasi yang **disetujui petugas** sebelum tayang.

```
Deteksi (sistem yang ada) → Prioritas → Verifikasi → Klarifikasi → Persetujuan manusia
```

| | |
|---|---|
| Demo | https://netra-app.tokorejeki.my.id |
| API (Swagger) | https://netra-app.tokorejeki.my.id/api/docs |
| Video presentasi | _(tautan menyusul)_ |
| Slide | _(tautan menyusul)_ |

Tim: Muhammad Faris Revansyah (prioritas, pencarian sumber, API), Farrel Adhi Pratama (pipeline data,
dashboard), Adriel Christofer Widya (lapisan AI: STT, OCR, RAG, verifikasi silang). Teknik Komputer,
Universitas Diponegoro.

## Untuk panelis: coba dalam 3 menit

1. Buka **Demo**. Antrean sudah berisi klaim yang diurutkan menurut prioritas.
2. Buka salah satu kasus berikut dan lihat kandidat sumber asli, rincian skor, dan paket bukti:

   | Kasus | Yang diperlihatkan |
   |---|---|
   | `r001` Intan Jaya | Video lama (2021) diedarkan ulang dengan narasi baru. Sumber paling awal ditemukan. |
   | `r002` Kapuspen | Kutipan pejabat dipelintir. Teks asli dibandingkan dengan narasi viral. |
   | `c002` Kasad | Jalur formal: klaim dicek ke korpus rilis resmi, kutipan tidak pernah ada. |
   | `c001b` | Kasus sulit: semua kandidat meragukan, jadi Netra **tidak memaksa** klarifikasi dan mengeskalasi ke petugas. |
   | `c004` | Tidak ada sumber pendukung, hasilnya `tidak_ditemukan` + eskalasi. |

3. Isi nama petugas, pilih **Setujui klarifikasi** atau **Tolak / minta perbaikan**, lalu buka **Lihat halaman bukti publik**.
   Setiap keputusan tercatat di audit trail.

Klaim baru bisa ditambahkan lewat **+ Tambah klaim** (teks klaim plus tautan media viralnya). Proses live
memanggil layanan berbayar dan bisa memakan beberapa menit, jadi pada link publik prosesnya dibatasi
(`BATAS_PROSES_HARIAN`, `JEDA_PROSES_ULANG_MENIT`). Hasil yang sudah tersimpan selalu bisa dibuka.

## Kenapa Netra berbeda

- **Membuktikan, bukan memberi skor "hoaks atau bukan".** Keluarannya sumber asli, bagian yang diubah,
  dan bukti berpasangan (teks viral vs teks sumber, detik ke berapa potongan berasal).
- **Dua jalur verifikasi.** Peristiwa formal dicek ke korpus rilis resmi (RAG). Konten informal dilacak
  lewat mesin pencari, YouTube, Google Lens, lalu dibuktikan dengan pencocokan frame (perceptual hash)
  dan pola audio.
- **Jujur saat ragu.** Kalau sumber tertua pun meragukan atau bukti saling bertentangan, status menjadi
  `belum_bisa_diverifikasi` dan dieskalasi, bukan dipaksakan.
- **Manusia tetap memutuskan.** Tidak ada klarifikasi yang tayang tanpa persetujuan petugas.

## Keamanan dan keandalan

- **Tahan buzzer:** korroborasi dihitung per penerbit unik, kontribusi akun pribadi dibatasi, dan
  hasil yang hanya mirip gambar tanpa membahas klaim tidak ikut menyumbang skor.
- **Anti halusinasi:** LLM hanya boleh menyalin URL dari daftar sumber yang ditemukan, dan temuan pihak
  lain (misalnya artikel cek fakta) wajib disebut sebagai temuan sumber tersebut.
- **Audit trail** untuk setiap pencarian, verifikasi, dan keputusan petugas.
- **Rahasia aman:** API key dikirim lewat header dan tidak tercetak di log; `.env` tidak masuk repo.
- **Pengaman biaya** untuk link publik: kuota proses harian dan jeda proses ulang per klaim.

## Evaluasi

Semua kasus demo bisa diuji ulang dengan satu perintah, tanpa API key:

```bash
cd backend && python scripts/evaluasi.py --tulis ../docs/hasil-evaluasi.md
```

Hasil terakhir ada di [`docs/hasil-evaluasi.md`](docs/hasil-evaluasi.md). Label kebenaran tiap kasus
ditulis tim di `backend/data/evaluasi_label.json`. Tambah `--live` untuk memakai Gemini dan SerpAPI.

## Pemetaan ke kriteria penilaian

| Kriteria | Di mana terlihat |
|---|---|
| Relevansi & manfaat bagi TNI AD | Kasus nyata TNI (r001–r003), alur kerja Dispenad, persetujuan petugas |
| Inovasi teknis | Pelacakan sumber asli + pencocokan frame/audio + RAG korpus resmi, bukan sekadar klasifikasi |
| Fungsionalitas prototipe | Demo live, 120+ tes otomatis (`pytest`), skrip evaluasi |
| Kelayakan implementasi | Docker, Postgres, berjalan di server satuan; biaya API per kasus terukur |
| Kualitas dokumentasi | README ini, `docs/kontrak-data.md`, `docs/skrip-demo.md` |

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
docker/                Container layanan STT (Whisper)                  (Adriel)
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

Dashboard memanggil API di `NEXT_PUBLIC_API_URL` (default `/api`, diteruskan ke backend lewat `next.config.mjs`). Tidak ada login;
ada pemilih "bertindak sebagai petugas" yang tercatat di audit trail.

Halaman:

| Rute | Isi |
|---|---|
| `/antrean` | Antrean klaim terurut prioritas, filter status/level, ringkasan angka |
| `/klaim/{id}` | Kandidat + rincian skor, paket bukti, draf klarifikasi 3 format, persetujuan, audit |
| `/bukti/{id}` | Halaman bukti publik (tanpa catatan internal), diberi label SIMULASI |

## Menjalankan layanan STT (Docker)

Untuk layanan Speech-to-Text (`faster-whisper` `large-v3-turbo`) via Docker di port `8100` (pastikan Docker Desktop sudah berjalan):

```bash
cd docker
docker compose up -d
# atau untuk mode CPU tanpa GPU NVIDIA:
# docker compose -f compose.cpu.yaml up -d
```

Unduh model sekali saja dari terminal/PowerShell mana saja:

```powershell
curl.exe -X POST "http://localhost:8100/v1/models/deepdml%2Ffaster-whisper-large-v3-turbo-ct2"
```

Setelah selesai, layanan bisa diakses di `http://localhost:8100/` (tab **Speech-to-Text**) atau API docs di `http://localhost:8100/docs`. Lihat detail lengkap di [docker/README.md](docker/README.md).

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
4. Peringkat kandidat: kemiripan 28%, tanggal unggah paling awal 22% (hanya penuh untuk kandidat
   yang relevan), jenis sumber 15%, korroborasi penerbit independen 10%, kecocokan audio 9%,
   resolusi 8%, bebas watermark 8%. Hasil Google Lens yang hanya mirip gambar tapi tidak membahas
   klaim dibatasi skornya, supaya foto generik dari berita lain tidak dianggap sumber asli.

**Persetujuan manusia** — draf klarifikasi hanya tayang setelah petugas menyetujui. Penolakan wajib
disertai catatan. Setiap keputusan masuk audit trail.

Kalau sumber tertua pun terindikasi dimanipulasi atau tidak ada sumber pendukung,
status keluarannya `belum_bisa_diverifikasi` / `tidak_ditemukan` dan dieskalasi ke petugas —
bukan dipaksakan menjadi klarifikasi.

## Deploy

Demo publik berjalan di server sendiri lewat **Cloudflare Tunnel** (tanpa membuka port, HTTPS otomatis):
backend di `localhost:8000`, dashboard di `localhost:3000`, STT di `localhost:8100`, lalu
`cloudflared tunnel run --token <token>`. Token yang sama bisa dijalankan di beberapa mesin sekaligus
sebagai cadangan; URL tidak berubah saat server dipindah.

Server dengan Docker: pakai `backend/Dockerfile` (container jalan sebagai user non-root).

Untuk masa penjurian, isi di `.env` server: `IZINKAN_SEED=0` (tombol reset disembunyikan),
`BATAS_PROSES_HARIAN`, dan `JEDA_PROSES_ULANG_MENIT`.

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