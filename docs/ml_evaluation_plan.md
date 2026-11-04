# RENCANA EVALUASI PIPELINE WAJAH (FAR/FRR & THRESHOLD)

> **Status: BELUM DIEKSEKUSI.** Dokumen ini menjelaskan **metodologi**. Tidak ada
> angka akurasi, FAR, FRR, atau threshold yang diklaim sampai pengukuran nyata
> dilakukan dengan data yang sah (PRD BAB IV/4.4, BAB X/10.2, BAB XIII #7).
> Sesuai aturan: **jangan menyatakan fitur berhasil/akurat sebelum diuji.**

---

## 1. Mengapa ini penting

`face_verify_threshold` (default `0.45`, lihat `app/config.py`) menentukan batas
cosine-similarity yang diterima. Nilai ini **belum divalidasi**. Menurunkan
threshold agar demo "berhasil" menaikkan risiko orang lain lolos (False Accept).

Skor similarity **bukan** probabilitas identitas benar. Jangan ditampilkan sebagai
"persentase kepastian".

---

## 2. Data evaluasi yang dibutuhkan

Kumpulkan **data uji berizin** (persetujuan tertulis, PRD BAB VI):

| Set | Isi | Tujuan |
|---|---|---|
| Genuine pairs | ≥ 20 sampel per peserta, kondisi beragam (jarak, cahaya, sudut, ekspresi) | ukur FRR |
| Impostor pairs | setiap peserta dibandingkan dengan template peserta lain (semua pasangan berbeda) | ukur FAR |
| Spoof samples | foto cetak, foto layar HP, video replay | uji liveness |
| Degraded samples | buram, gelap, terang berlebih, jauh, banyak wajah | uji kualitas/penolakan |

Prasyarat: setidaknya ~30 peserta agar metrik bermakna. Minimal 1 peserta + 1
impostor untuk uji awal pipeline (bukan untuk finalisasi threshold).

---

## 3. Prosedur pengukuran

Untuk setiap threshold `t` pada grid (mis. 0.30 → 0.70, langkah 0.02):

1. Hitung similarity untuk semua pasangan genuine → `accepted = sim ≥ t`.
   `FRR(t) = ditolak_genuine / total_genuine`.
2. Hitung similarity untuk semua pasangan impostor.
   `FAR(t) = diterima_impostor / total_impostor`.
3. Catat latensi (ms) tiap tahap: decode → detect → align → embed → compare.
4. Pilih `t` pada titik **FAR yang dapat diterima** (mis. FAR ≤ 1%), lalu
   laporkan FRR yang menyertainya. Jangan sebaliknya.

Simpan hasil sebagai tabel + grafik FAR/FRR vs threshold. Catat:
model, versi bobot, preprocessing, ukuran gambar, perangkat (CPU/GPU), kondisi uji.

---

## 4. Uji liveness & kualitas

- Foto cetak & foto layar **harus ditolak** (ukur tingkat lolos palsu).
- Wajah asli **harus lolos** (ukur tingkat tolak palsu).
- Catat skor Laplacian (`liveness={score}` tersimpan di log verifikasi) untuk
  melihat sebaran nyata vs spoof → setel `face_liveness_min_laplacian`.
- Uji penolakan: tanpa wajah, banyak wajah, buram, gelap.

---

## 5. Kriteria penerimaan (PRD BAB XIII)

- Threshold berasal dari pengukuran (bukan nilai tutorial).
- FAR & FRR dilaporkan dengan kondisi pengujian dan keterbatasan.
- Liveness fail-closed (sudah diterapkan) terbukti menolak foto/layar.
- Tidak ada klaim akurasi tanpa bukti.

---

## 6. Harness yang sudah tersedia

- `tests/test_face_service.py` — menguji perilaku fail-closed (model hilang, tanpa
  wajah, banyak wajah, kualitas rendah, dimensi tidak cocok, liveness).
- `app/ai/face_service.py::verify_embedding(..., threshold=...)` — threshold
  dapat di-override saat pengukuran.

> Skrip pengukuran FAR/FRR end-to-end belum dibuat karena memerlukan data uji
> berizin. Akan dibuat setelah data tersedia.
