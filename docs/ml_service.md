# LAYANAN ML WAJAH TERPISAH (PRD BAB III)

Komponen Computer-Vision dijalankan sebagai **proses FastAPI terpisah** sehingga
aplikasi web utama tidak memerlukan stack CV dan **tidak pernah** menentukan
absensi. Service hanya mengembalikan hasil terstruktur (wajah terdeteksi /
kualitas / embedding / similarity / liveness) + kode alasan.

> Service **tidak** menyentuh database dan **tidak** menyimpan catatan absensi.
> Keputusan absensi tetap di aplikasi utama.

---

## 1. Menjalankan

```powershell
# Terminal 1 — layanan ML (port 9000)
.\.venv\Scripts\uvicorn.exe ml_service.main:app --host 127.0.0.1 --port 9000

# Terminal 2 — aplikasi web
.\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000
```

Konfigurasi `.env`:

```
FACE_SERVICE_URL=http://127.0.0.1:9000
FACE_SERVICE_TOKEN=<acak-panjang>     # WAJIB, dipakai kedua sisi
FACE_SERVICE_TIMEOUT_SECONDS=8
FACE_MAX_IMAGE_BYTES=4000000
FACE_SERVICE_RATE_PER_MINUTE=120
```

Jika `FACE_SERVICE_URL` **kosong**, aplikasi memakai model **in-process** (mode dev).
Untuk produksi, isi `FACE_SERVICE_URL` + `FACE_SERVICE_TOKEN`.

> Jalankan service ML hanya di jaringan internal/loopback, dan gunakan TLS bila
> melewati host. Jangan mengekspos port ke publik.

---

## 2. Endpoint internal (butuh `X-Service-Token`)

| Method | Path | Keterangan |
|---|---|---|
| GET | `/health` | status + `model_ready` (tanpa token) |
| GET | `/model/status` | engine, ready, threshold, liveness ambang |
| POST | `/face/liveness` | hasil liveness fail-closed |
| POST | `/face/register` | embedding + kualitas (+ thumbnail opsional) |
| POST | `/face/verify` | 1:1 verify → matched/similarity/threshold/reason_code |

Kode alasan (`X-Reason-Code`): `model_unavailable`, `no_face`, `multiple_faces`,
`face_too_small`, `face_blurry`, `face_bad_lighting`, `empty_embedding`,
`embedding_dim_mismatch`, `low_quality`.

Pengaman: token internal, batas ukuran payload (`FACE_MAX_IMAGE_BYTES`),
timeout klien, dan rate limit per klien.

---

## 3. Perilaku saat layanan gagal (fail-closed)

Jika layanan ML tidak dapat diakses / timeout / 5xx:

1. Aplikasi utama mengembalikan **HTTP 503** dengan pesan jelas.
2. **Absensi TIDAK dicatat otomatis.** Tidak ada penerimaan diam-diam.
3. **Prosedur manual terawasi (BAB III):**
   - Peserta melapor ke admin/pembimbing.
   - Admin/pembimbing mencatat absensi lewat akun berwenang
     (`POST /attendance` atau `POST /api/attendance/manual`).
   - Tindakan ini tercatat pada log audit/aktivitas.
   - Jika lokasi meragukan, gunakan alur **Review Lokasi**.

> Manual hanya oleh role `admin`/`pembimbing` yang terautentikasi; bukan oleh peserta.

---

## 4. Rollback

- **Kembali ke in-process:** kosongkan `FACE_SERVICE_URL`, restart aplikasi web.
  (Perilaku model identik karena memakai `FaceRecognitionService` yang sama.)
- **Matikan layanan ML:** hentikan proses `ml_service`; aplikasi otomatis 503 →
  prosedur manual.
- **Rollback kode:** gunakan Git (branch terpisah per tahap).

---

## 5. Catatan privasi

- Embedding dihitung di service ML, dikirim **hanya** antar layanan internal
  ber-token (bukan ke browser).
- Foto mentah diproses di memori dan tidak disimpan.
- Template embedding disimpan terenkripsi oleh aplikasi utama, bukan oleh service ML.
