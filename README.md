# Netra

Sistem pendukung Dinas Penerangan TNI AD untuk **memverifikasi dan mengklarifikasi konten viral yang dimanipulasi**.
Netra tidak mendeteksi hoaks (memakai sistem deteksi yang sudah ada). Netra melacak **sumber asli** sebuah konten,
membuktikan apa yang diubah, lalu menyiapkan klarifikasi yang disetujui petugas.

```
Deteksi (sistem yang ada) → Prioritas → Verifikasi → Klarifikasi → Persetujuan manusia
```

## Struktur

```
backend/
├── main.py            API penghubung semua modul (FastAPI)
├── schemas.py         Kontrak data: Klaim, KandidatSumber, HasilPencarian, HasilVerifikasi
├── config.py, llm.py  Konfigurasi & klien LLM bersama
├── priority/          Skor prioritas klaim                         (Faris)
├── search/            Pencarian & peringkat sumber asli            (Faris)
├── ai/                RAG, OCR/transkrip, perbandingan, klarifikasi (Adriel)
├── data/dummy/        Klaim & kandidat contoh untuk demo
└── tests/
dashboard/             Antrean, paket bukti, persetujuan petugas     (Farrel)
```

## Menjalankan backend

Butuh Python 3.10+ dan **ffmpeg** (untuk pencocokan frame & audio).

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # isi API key (opsional)
uvicorn main:app --reload
```

Buka `http://localhost:8000/docs`. Cek mode di `GET /health`.

**Tanpa API key** pun API tetap jalan: prioritas memakai klasifikasi kata kunci dan pencarian memakai
data contoh di `data/dummy/kandidat.json`. Isi `GEMINI_API_KEY` dan `SERPAPI_KEY` untuk mode live.

## Endpoint

| Endpoint | Fungsi |
|---|---|
| `POST /prioritas` | Terima klaim, beri skor & level prioritas |
| `GET /antrean` | Klaim terurut dari prioritas tertinggi |
| `POST /cari/{id}` | Cari kandidat sumber asli, terurut. Body opsional `{"url_manual": [...]}` |
| `GET /cari/{id}/proses` | Query yang dipakai & rincian skor tiap kandidat |
| `POST /verifikasi/{id}` | Bandingkan konten viral vs sumber, buat draf klarifikasi |
| `POST /pipeline/{id}` | Cari + verifikasi sekaligus (untuk demo) |
| `GET /persetujuan` | Antrean klaim yang menunggu keputusan petugas (`?status=semua` untuk semua) |
| `POST /persetujuan/{id}` | Petugas menyetujui/menolak, boleh mengedit draf lewat `draf_final` |
| `GET /bukti` · `GET /bukti/{id}` | Bukti publik (hanya klaim yang disetujui) |
| `GET /bukti/{id}/halaman` | Halaman bukti publik siap dibagikan |

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

Kalau sumber tertua pun terindikasi dimanipulasi atau tidak ada sumber pendukung,
status keluarannya `belum_bisa_diverifikasi` / `tidak_ditemukan` dan dieskalasi ke petugas.

## Model LLM

`GEMINI_MODEL` dipakai untuk tugas ringan (klasifikasi prioritas, pembuatan query).
`GEMINI_MODEL_VERIFIKASI` untuk OCR, perbandingan, dan klarifikasi:
`llm.tanya_json(prompt, model=config.GEMINI_MODEL_VERIFIKASI)`.

## Deploy (Render)

1. Push repo ke GitHub.
2. Di Render: **New + → Blueprint**, pilih repo ini (memakai `render.yaml` dan `backend/Dockerfile`).
3. Isi `GEMINI_API_KEY` dan `SERPAPI_KEY` di tab Environment.
4. Cek `https://<nama-service>.onrender.com/health`.

Paket gratis Render tidur setelah tidak dipakai, jadi buka `/health` sebelum demo supaya server bangun.
Data masih disimpan di memori: setiap restart kembali ke data demo.

## Tes

```bash
cd backend && pytest -q
```
