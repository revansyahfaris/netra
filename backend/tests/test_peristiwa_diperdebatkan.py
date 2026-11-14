"""Kasus nyata Tiro (Pidie, 4 Nov 2026): peristiwa nyata yang detailnya diperdebatkan
tidak boleh dicap "terbukti diubah", apalagi kalau bantahannya hanya dari pihak yang dituduh."""

from ai import verifikasi_silang
from ai.verifikasi import tuduhan_kekerasan_aparat
from search.pipeline import sama_dengan_viral
from tests.test_ai_tahap4 import _hasil_tahap2_siap, _kandidat, _klaim

TEKS_TIRO = (
    "TNI melakukan Tembakan membabi buta terhadap sipil tak bersenjata pada acara Maulid di Tiro, "
    "Pidie 4 November 2026"
)
URL_MEDIA = "https://www.youtube.com/watch?v=7P9ecVUHdDg"


def _tahap2_media_saja(klaim):
    k = _kandidat(
        url=URL_MEDIA, metode="keyword", kemiripan=0.6, jenis_sumber="media",
        judul="Aparat Diduga Terlibat Penembakan Warga", rincian_skor={"teks": 0.6},
    )
    return _hasil_tahap2_siap(klaim, kandidat_bersih=[k])


def _jawaban_llm(**kw):
    dasar = {
        "status": "terbukti_diubah",
        "keyakinan": 0.95,
        "konsisten_dengan_sumber": False,
        "sumber_tertua_meragukan": False,
        "sumber_utama_url": URL_MEDIA,
        "manipulasi": {
            "dipotong": True, "tanggal_berbeda": False, "kutipan_tidak_ada": True,
            "konteks_berbeda": True, "lainnya": False,
        },
        "ringkasan": "Klaim disinformasi; TNI memakai munisi hampa.",
        "fakta_utama": "Bentrokan dipicu bendera.",
        "apa_yang_diubah": "Konteks dihilangkan.",
        "bukti": [{"jenis": "kutipan", "url": URL_MEDIA, "teks_sumber": "TNI klaim tak ada peluru tajam"}],
    }
    dasar.update(kw)
    return dasar


def test_deteksi_tuduhan_kekerasan_aparat():
    assert tuduhan_kekerasan_aparat(TEKS_TIRO)
    assert not tuduhan_kekerasan_aparat("Kasad disebut menyatakan TNI siap ambil alih pemerintahan sipil")
    assert not tuduhan_kekerasan_aparat("Pendaftaran Bintara TNI AD dipungut biaya Rp15 juta")


def test_tiro_dieskalasi_walau_llm_bilang_terbukti(monkeypatch):
    k = _klaim(claim_id="tiro", teks_klaim=TEKS_TIRO)
    monkeypatch.setattr("llm.tanya_multimodal_json", lambda parts, **kw: _jawaban_llm())
    h = verifikasi_silang(k, _tahap2_media_saja(k))
    assert h.status == "belum_bisa_diverifikasi"
    assert h.perlu_eskalasi
    assert h.keyakinan <= 0.5
    assert "dipotong" not in h.perubahan  # tidak ada bukti frame/transkrip
    assert "kekerasan oleh aparat" in (h.alasan_eskalasi or "")


def test_bantahan_hanya_pihak_tertuduh_dieskalasi(monkeypatch):
    k = _klaim(claim_id="b1", teks_klaim="Video ricuh di pasar disebut terjadi pekan ini")
    monkeypatch.setattr(
        "llm.tanya_multimodal_json",
        lambda parts, **kw: _jawaban_llm(bantahan_hanya_pihak_tertuduh=True, peristiwa_inti_terjadi=True),
    )
    h = verifikasi_silang(k, _tahap2_media_saja(k))
    assert h.status == "belum_bisa_diverifikasi"
    assert "pihak yang" in (h.alasan_eskalasi or "")


def test_rekaman_lama_terbukti_frame_tetap_boleh(monkeypatch):
    """Tuduhan kekerasan tetap bisa dibantah bila frame membuktikan rekamannya dari peristiwa lain."""
    k = _klaim(claim_id="lama", teks_klaim="Video prajurit TNI menembak warga, disebut terjadi minggu ini")
    jawaban = _jawaban_llm(
        sumber_utama_url="https://www.youtube.com/watch?v=ASLI-2019",
        manipulasi={"dipotong": False, "tanggal_berbeda": True, "kutipan_tidak_ada": False,
                    "konteks_berbeda": False, "lainnya": False},
        bukti=[{"jenis": "frame", "url": "https://www.youtube.com/watch?v=ASLI-2019", "cuplikan": "00:42"}],
    )
    monkeypatch.setattr("llm.tanya_multimodal_json", lambda parts, **kw: jawaban)
    h = verifikasi_silang(k, _hasil_tahap2_siap(k))  # kandidat frame_match 0.92
    assert h.status == "terbukti_diubah"


def test_keyakinan_dibatasi_tanpa_bukti_keras(monkeypatch):
    k = _klaim(claim_id="kut", teks_klaim="Kasad disebut menyatakan TNI siap ambil alih pemerintahan sipil")
    jawaban = _jawaban_llm(
        manipulasi={"dipotong": False, "tanggal_berbeda": False, "kutipan_tidak_ada": True,
                    "konteks_berbeda": False, "lainnya": False},
    )
    monkeypatch.setattr("llm.tanya_multimodal_json", lambda parts, **kw: jawaban)
    h = verifikasi_silang(k, _tahap2_media_saja(k))
    assert h.status == "terbukti_diubah"
    assert h.keyakinan <= 0.80


def test_konten_viral_tidak_jadi_kandidat_sendiri():
    viral = "https://x.com/achehsultanate/status/2117956103019631060"
    assert sama_dengan_viral(viral + "/video/1", viral)
    assert sama_dengan_viral("https://twitter.com/achehsultanate/status/2117956103019631060", viral)
    assert not sama_dengan_viral("https://x.com/indepenSumatera/status/2117945241085022297", viral)
