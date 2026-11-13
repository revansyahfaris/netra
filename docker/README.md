# Docker Services — Netra

Folder ini berisi konfigurasi container pendukung untuk modul AI Netra, dimulai dari layanan **Speech-to-Text (STT)** berbasis **Speaches** (`faster-whisper`) menggunakan model `deepdml/faster-whisper-large-v3-turbo-ct2`.

Layanan STT berjalan pada port **`8100`** (`http://localhost:8100`) agar tidak bentrok dengan server FastAPI Netra di port `8000`.

## Prasyarat

* **Docker Desktop** sudah terpasang dan dalam keadaan berjalan (*Engine running*, mode Linux containers).
* Untuk mode GPU: driver NVIDIA terbaru di host Windows dengan dukungan GPU WSL2/Docker aktif.

## 1. Menjalankan Container STT

### Mode GPU NVIDIA (Default — disarankan)
```bash
cd docker
docker compose up -d
```

### Mode CPU (Jika tidak ada GPU NVIDIA)
```bash
cd docker
docker compose -f compose.cpu.yaml up -d
```

### Cek Status & Health
```bash
docker compose ps
docker compose logs -f stt
```

Cek health endpoint:
```bash
curl http://localhost:8100/health
```
Jika sehat, responsnya `OK`.

## 2. Unduh Model Whisper (Sekali Saja)

Model belum terunduh saat container pertama kali menyala. Unduh model `deepdml/faster-whisper-large-v3-turbo-ct2` (~1,5–1,6 GB) menggunakan salah satu cara berikut:

**Lewat PowerShell / terminal (bisa dijalankan dari folder mana saja):**
```powershell
curl.exe -X POST "http://localhost:8100/v1/models/deepdml%2Ffaster-whisper-large-v3-turbo-ct2"
```
*(Di Linux/macOS/Git Bash, gunakan `curl` biasa.)*

Atau lewat Swagger UI di `http://localhost:8100/docs` pada endpoint `POST /v1/models/{model_id}`.

* Model diunduh langsung oleh container ke volume Docker **`speaches-hf-hub-cache`**, sehingga **tidak masuk ke folder project** dan **tetap tersimpan** meski container di-restart.
* Verifikasi model sudah terpasang:
  ```bash
  curl http://localhost:8100/v1/models
  ```

## 3. Cara Menguji & Menggunakan

### Lewat Web UI (`http://localhost:8100/`)
1. Buka `http://localhost:8100/` di browser dan pindah ke tab **Speech-to-Text**.
2. Pilih model `deepdml/faster-whisper-large-v3-turbo-ct2` pada dropdown **Model**.
3. Upload/rekam audio, lalu klik **Generate**.

> **Catatan:** Tab pertama **Audio Chat** memang akan menampilkan *Connection error* karena membutuhkan server Chat LLM eksternal yang terpisah. Abaikan tab tersebut dan langsung pakai tab **Speech-to-Text** atau akses API docs di `http://localhost:8100/docs`.

### Lewat API (`/v1/audio/transcriptions`)
Contoh uji via `curl` (Linux/macOS/Git Bash):
```bash
curl -X POST http://localhost:8100/v1/audio/transcriptions \
  -H "Authorization: Bearer local" \
  -F "file=@audio.wav" \
  -F "model=deepdml/faster-whisper-large-v3-turbo-ct2" \
  -F "language=id" \
  -F "response_format=verbose_json"
```
*(Di PowerShell Windows, ganti `curl` dengan `curl.exe`.)*

## 4. Mode Aman untuk Tunnel / Production (`STT_API_KEY`)

Jika layanan STT akan diekspos ke luar lewat Cloudflare Tunnel atau internet, **jangan biarkan tanpa API key**:
1. Salin `docker/.env.example` menjadi `docker/.env` lalu isi `STT_API_KEY` dengan token acak yang panjang.
2. Isi `STT_API_KEY` yang sama di `backend/.env` (dan `STT_BASE_URL=https://subdomain-kamu.com` jika backend terpisah).
3. Jalankan dengan overlay `compose.secure.yaml` (mengaktifkan proteksi `API_KEY` dan mematikan Gradio UI):
   ```bash
   cd docker
   docker compose -f compose.yaml -f compose.secure.yaml up -d
   ```
   *(Jika mode CPU: `docker compose -f compose.cpu.yaml -f compose.secure.yaml up -d`.)*

## 5. Menghentikan Layanan

```bash
cd docker
docker compose down
```
*(Jangan tambahkan flag `-v` jika tidak ingin menghapus volume cache model yang sudah diunduh.)*
