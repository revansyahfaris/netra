"""Titik masuk untuk Hugging Face Spaces (SDK Gradio).

Space Gradio menjalankan `python app.py`. File ini menyalakan API FastAPI Netra apa adanya
(semua endpoint tetap di /health, /antrean, /cari/..., /docs) dan menambahkan halaman uji
sederhana di /ui. Jalankan lokal: python app.py
"""

import json
import os

import gradio as gr
import uvicorn
from fastapi.responses import RedirectResponse

from main import app, cari, pipeline


def _jalankan(claim_id: str, mode: str) -> str:
    claim_id = (claim_id or "").strip()
    if not claim_id:
        return "Isi claim_id dulu, misalnya c002"
    try:
        hasil = pipeline(claim_id) if mode == "pipeline" else cari(claim_id)
        return json.dumps(hasil.model_dump(mode="json"), ensure_ascii=False, indent=2)
    except Exception as e:  # tampilkan pesan error di UI, bukan crash
        return f"Gagal: {getattr(e, 'detail', e)}"


with gr.Blocks(title="Netra") as ui:
    gr.Markdown(
        "# Netra\nVerifikasi & klarifikasi konten viral terkait TNI AD.\n\n"
        "Dokumentasi API lengkap: [/docs](/docs) · Status: [/health](/health)"
    )
    with gr.Row():
        kotak_id = gr.Textbox(label="claim_id", value="c002")
        mode = gr.Radio(["cari", "pipeline"], value="cari", label="Mode")
    tombol = gr.Button("Jalankan")
    keluaran = gr.Code(language="json", label="Hasil")
    tombol.click(_jalankan, [kotak_id, mode], keluaran)

@app.get("/", include_in_schema=False)
def beranda():
    # Halaman depan Space langsung menampilkan UI uji
    return RedirectResponse("/ui")


# API tetap di root; UI uji dipasang di /ui
app = gr.mount_gradio_app(app, ui, path="/ui")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "7860")))
