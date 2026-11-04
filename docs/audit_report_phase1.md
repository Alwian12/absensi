# LAPORAN AUDIT FASE 1 — Monitoring PKL

> Dokumen ini dimulai sebagai hasil **Fase 1: Discovery dan Audit Total** (BAB II PRD)
> dan kini mencantumkan **status perbaikan** setiap temuan.
> Tanggal audit: 2026-10-27 · Status akhir: **80 tes lulus, `get_errors` bersih, migrasi `0003_indexes` (head)**.

### RINGKASAN STATUS TEMUAN

| ID | Temuan | Status |
|---|---|---|
| F-01 | Bypass auth via cookie `user_id` | ✅ FIXED (signed session) |
| F-02 | `/api/dashboard` publik | ✅ FIXED (wajib auth) |
| F-03 | Impersonasi endpoint wajah | ✅ FIXED (via F-01) |
| F-04 | Absensi dari client / token di query | ⚠️ Sebagian — semua tulis tetap di backend; constraint unik harian belum ditambah |
| F-05 | CSRF dilewati `/api/`,`/face/`; logout GET | ✅ FIXED |
| F-06 | Kunci biometrik = JWT secret | ✅ FIXED (+ fallback dekripsi legacy) |
| F-07 | Default secret/`debug` | ✅ FIXED (tolak start bila `DEBUG=false` + secret lemah) |
| F-08 | Parser CSRF multipart rapuh | ✅ FIXED (parser `email` stdlib) |
| F-09 | Dependensi mati (`python-jose`, `passlib`) | ✅ FIXED |
| F-10 | `/admin/backup` perlu verifikasi | ⚠️ Perlu uji lanjutan manual |
| F-11/F-12 | Fallback embedding palsu & center-crop | ✅ FIXED (fail-closed) |
| F-13 | Liveness fail-open | ✅ FIXED (fail-closed) |
| F-14 | Threshold 0.45 arbitrer | ⚠️ Terkonfigurasi + metodologi siap; **angka final menunggu data uji berizin** |
| F-15 | Skor disajikan sebagai kepastian | ✅ FIXED |
| F-16 | Registrasi 1 sampel tanpa cek kualitas | ✅ FIXED (multi-sampel + konsistensi) |
| F-17 | Liveness tak tercatat | ✅ FIXED (skor di log) — kolom khusus belum |
| F-18 | Thumbnail biometrik dikirim ke browser | ⚠️ Masih ada (terenkripsi); kebijakan retensi perlu keputusan |
| F-19 | DDL tanpa versi saat startup | ✅ FIXED (Alembic 0001→0003) |
| F-20 | Duplikasi `get_db`/auth helper | ✅ FIXED |
| F-21 | Indeks minim & N+1 | ✅ FIXED (10 indeks + bulk-load) |
| F-22 | Rate limit in-memory & endpoint wajah tanpa batas | ✅ FIXED (DB-backed + 429) |
| F-23 | Folder/dependensi mati | ✅ FIXED (requirements) |
| F-24 | CDN eksternal & gaya tidak konsisten | ✅ FIXED (semua divendor) |
| F-25 | Alur absensi belum lengkap state-nya | ✅ FIXED (stage + pemetaan alasan) |

**Sisa yang bukan pekerjaan kode:** pengukuran FAR/FRR pada data uji berizin; keputusan kebijakan retensi thumbnail; verifikasi manual endpoint backup; serta pengisian `FACE_ENCRYPTION_KEY`, `FACE_SERVICE_URL`, `FACE_SERVICE_TOKEN` di produksi.

### STATUS PERBAIKAN
- **2026-10-27 — Tahap A (dimulai): F-01, F-02, F-03 SELESAI & diuji.**
  - Sesi diganti menjadi **cookie bertanda tangan** (`session`) via `app/security/session.py` (HMAC-SHA256 atas `user_id` + `session_version` + `exp`).
  - Semua router (`web`, `admin`, `leave`, `attendance`, `journal`, `reports`, `dashboard`) kini memakai resolver tunggal `resolve_user` / `get_current_user`. Cookie `user_id`/`session_ver` **tidak lagi dipercaya** (hanya dibersihkan saat login/logout).
  - `/api/dashboard` kini **wajib autentikasi**.
  - Tes ditambah: cookie `user_id` palsu ditolak, login menerbitkan cookie sesi bertanda tangan, dashboard butuh auth. **27 tes lulus.**
  - **Tahap A SELESAI**: F-05 (CSRF untuk `/api/`+`/face/`, header `X-CSRF-Token`, logout via POST), F-06 (`app/security/face_crypto.py` dukung kunci khusus + dekripsi legacy), F-07 (`app/config.py` tolak secret lemah saat `DEBUG=false`).
- **2026-10-27 — Tahap B (inti ML) SELESAI & diuji.**
  - F-11/F-12 **FIXED**: fallback embedding grayscale & center-crop sebagai keputusan **dihapus**. `extract_embedding` **fail-closed** (model_unavailable / no_face / multiple_faces / low_quality).
  - F-13 **FIXED**: `check_liveness` fail-closed (error/tanpa cv2 → `passed=False`).
  - F-14 **sebagian**: threshold kini dari `settings.face_verify_threshold` (dapat di-override) — **metodologi** pengukuran FAR/FRR ada di `docs/ml_evaluation_plan.md` (belum ada metrik sampai data uji tersedia).
  - F-15 **FIXED (label)**: skor tidak lagi di-remap menjadi "confidence" semu; UI menampilkan "skor kemiripan".
  - F-17 **parsial**: skor liveness dicatat ke `message` log verifikasi (kolom khusus direkomendasikan menyusul).
  - Tes: `tests/test_face_service.py` (9 kasus fail-closed). **Total 43 tes lulus.**
  - Belum: F-16 (multi-sampel registrasi), F-19 (Alembic), redesign UI (F-24/F-25).
- **2026-10-27 — BAB III: service ML terpisah SELESAI & diuji.**
  - `ml_service/` (FastAPI): `/health`, `/model/status`, `/face/{liveness,register,verify}` dengan auth token internal, batas ukuran payload, rate limit.
  - `app/ai/face_client.py`: klien (stdlib `urllib`, tanpa dependency baru) ber-antarmuka sama dengan `FaceRecognitionService`; gagal/timeout/5xx → `reason_code="service_unavailable"`.
  - `web.py` memilih klien bila `FACE_SERVICE_URL` diisi, selain itu in-process (dev). `service_unavailable` → **HTTP 503 fail-closed**.
  - Prosedur manual terawasi + rollback: `docs/ml_service.md`.
  - Tes: `tests/test_face_client.py` (4) + `tests/test_ml_service.py` (5). **Total 52 tes lulus.**
- **2026-10-27 — F-16: registrasi wajah multi-sampel SELESAI & diuji.**
  - `face_service.register_embedding_multi`: minimal `FACE_REGISTER_MIN_SAMPLES` sampel berkualitas, cek **konsistensi** antar-embedding (`FACE_EMBEDDING_CONSISTENCY_MIN`), template = rata-rata embedding ter-normalisasi. Kode alasan: `too_few_samples`, `inconsistent_samples`.
  - Endpoint `/face/register` (web) menerima `images_base64` (fallback `image_base64`); **liveness fail-closed per sampel**.
  - ML service `/face/register` menerima `images_base64`; klien `register_embedding_multi`.
  - Frontend `attendance.js` mengambil **5 sampel** berurutan saat registrasi.
  - Tes: `tests/test_face_service.py` (+3) & `tests/test_ml_service.py` (+2). **Total 57 tes lulus.**
- **2026-10-27 — F-19: migrasi schema dengan Alembic SELESAI & diuji.**
  - Scaffolding: `alembic.ini`, `alembic/env.py` (pakai `settings.database_url` + `Base.metadata`), `alembic/versions/0001_baseline_schema.py`, `alembic/script.py.mako`.
  - `patch_legacy_schema()` (DDL mentah tiap startup) **dihapus** dari `app/main.py`; diganti `run_migrations()` (`app/db_migrate.py` → `alembic upgrade head`).
  - Baseline `0001_baseline` **idempotent & non-destruktif**: DB baru → buat tabel; DB lama → tambah kolom yang hilang; DB termigrasi → no-op. `downgrade()` no-op (kebijakan non-destruktif).
  - CLI: `scripts/migrate.ps1`; dokumentasi `docs/migrations.md`.
  - Tes: `tests/test_migrations.py` (revisi tercatat, idempotent, tabel & kolom ada). **Total 60 tes lulus.**
- **2026-10-27 — F-24 (bagian aset/CDN): frontend konsisten & offline-ready SELESAI & diuji.**
  - Tailwind CDN, Bootstrap CDN (index & journal_signature), Chart.js CDN, dan Google Fonts **dihapus**; diganti aset lokal di `app/static/vendor/`.
  - Font **Plus Jakarta Sans** (latin subset, woff2, 5 bobot ≈ 134 KB) divendor via `scripts/vendor_fonts.py` → `app/static/vendor/fonts.css` + `fonts/`.
  - `index.html`: kelas Tailwind `grid lg:grid-cols-2 …` diganti Bootstrap `row/col-lg-*`; font DM Sans/Sora diseragamkan ke Plus Jakarta Sans (satu sistem tipografi).
  - `/static/vendor/` sudah memakai cache 7 hari (immutable) dari `StaticCacheMiddleware`.
  - Tes: `tests/test_frontend_assets.py` (11) — tidak ada CDN, aset vendor ada, `fonts.css` hanya URL lokal, halaman `/` dan `/login` bersih. **Total 71 tes lulus.**
- **2026-10-27 — F-22: rate limiting SELESAI & diuji.**
  - `app/services/rate_limiter.py`: `SimpleRateLimiter` (in-memory) + **`DatabaseRateLimiter`** (persisten, tabel `rate_limit_event`) dengan antarmuka sama; login lockout kini bertahan setelah restart dan berlaku lintas worker (`RATE_LIMIT_PERSISTENT=true`).
  - Endpoint biometrik (`/api/face/verify`, `/api/face/register`) kini dibatasi **per user (10/menit)** dan **per IP (30/menit)**, diterapkan **sebelum** pekerjaan model; respons **429 + `Retry-After`**.
  - Migrasi baru `0002_rate_limit` (tabel `rate_limit_event` + indeks, non-destruktif).
  - Tes: `tests/test_security.py` (+2 limiter) & `tests/test_business_flows.py` (+1 → 429). **Total 75 tes lulus.**
- **2026-10-27 — F-21, F-08, F-09, F-20, F-25 SELESAI & diuji.**
  - **F-21 (performa):** migrasi `0003_indexes` menambah indeks pada `absensi(user_id, attendance_date)`, `absensi(attendance_date)`, `absensi(location_review_status)`, `jurnal(user_id, tanggal)`, `jurnal(status)`, `face_verification_logs(user_id, created_at)`, `face_verification_logs(created_at)`, `notifikasi(user_id, is_read)`, `activity_log(user_id, created_at)`, `permohonan_izin(user_id, tanggal)`. N+1 di rekap CSV dihapus (bulk-load 4 query, bukan 3×N); tren analitik jadi **1 query agregat** (sebelumnya 2×N).
  - **F-08 (CSRF parser):** ekstraksi token multipart kini memakai parser `email` stdlib (bukan pemindaian byte), tahan terhadap urutan field, kutip, dan boundary.
  - **F-09 (dependensi):** `python-jose` & `passlib` dihapus dari `requirements.txt` (tidak pernah diimpor); `bcrypt` & `cryptography` dideklarasikan eksplisit.
  - **F-20 (duplikasi):** delapan salinan `get_db` diganti satu implementasi di `app/database.py` (tipe `Iterator[Session]` benar); empat salinan `get_request_user` didelegasikan ke `require_user` di `app/security/session.py`.
  - **F-25 (alur absensi):** state baru `processing`, `no_face`, `low_quality` + `stageForError()` memetakan pesan/kode alasan server ke panduan spesifik (BAB VIII).
  - Tes: CSRF multipart/urlencoded, indeks migrasi, stage kelengkapan, tanpa CDN di JS. **Total 80 tes lulus.**

---

## 0. TEMUAN BLOKER — KETIDAKSESUAIAN STACK

| Aspek | PRD menyatakan | Fakta di repository |
|---|---|---|
| Backend utama | **PHP native** | **Python + FastAPI** (`app/main.py`, `requirements.txt`) |
| Komponen ML | Python (terpisah) | Sudah menyatu di dalam aplikasi Python (`app/ai/face_service.py`) |
| Database | existing | MySQL (`absensi`), diakses langsung oleh aplikasi Python |

**Implikasi:** Instruksi PRD ("pertahankan PHP native", "buat service Python terpisah", "jangan beri kredensial DB ke Python") **tidak dapat diterapkan apa adanya**, karena seluruh backend sudah Python dan sudah mengakses DB utama secara langsung.

Sesuai BAB XII ("Gunakan kode dan konfigurasi project sebagai sumber kebenaran"), audit ini dilanjutkan terhadap **kode nyata (Python/FastAPI)**. Keputusan arah arsitektur memerlukan **persetujuan pengguna** (lihat bagian 12).

---

## 1. INVENTARIS STRUKTUR & TEKNOLOGI

**Framework & bahasa**
- Backend: FastAPI (`app/main.py`), Uvicorn, SQLAlchemy 2.x, Pydantic v2, `pydantic-settings`.
- Template: Jinja2 (`app/templates`), di-`mount` dari `app/templates` dan `app/static`.
- Frontend: HTML + Bootstrap (vendored) + CSS custom (`app/static/styles.css`) + JS vanilla (`app/static/js/*`). PWA (`manifest.json`, `sw.js`).
- ML/CV: `opencv-python`, `insightface` (buffalo_l), `numpy`, `pillow`.
- Lain: `pandas`, `openpyxl`, `reportlab` (ekspor), `passlib`, `python-jose`, `alembic` (lihat temuan F-13/F-14), `mysqlclient`.

**Database:** SQLAlchemy engine di `app/database.py`. Default `sqlite:///./app.db`; `.env` memakai `mysql://root:@localhost:3306/absensi` (root, password kosong).

**Struktur folder:** `app/{ai,authentication,models,repositories,routers,schemas,security,services,utils}`, `templates`, `static`, `tests`, `docs`, `scripts`, `backups`.
- Catatan: `app/repositories/` hanya berisi `__init__.py` (belum dipakai). `app/schemas/` hanya `auth.py`.

---

## 2. PETA FITUR (yang benar-benar ada)

| Modul | Halaman/Endpoint | Status |
|---|---|---|
| Autentikasi | `/login`, `/register`, `/logout`, `/auth/login`, `/auth/register` | Ada |
| Dashboard | `/dashboard`, `/api/dashboard` (role-aware di web; `/api/dashboard` publik) | Ada |
| Absensi wajah | `/attendance`, `/face/verify` + `/api/face/verify`, `/face/register` + `/api/face/register`, `/api/face/thumbnail` | Ada |
| Absensi manual | `/attendance` (POST, admin/pembimbing), `/api/attendance/manual` | Ada |
| Riwayat absensi | `/attendance`, `/attendance/calendar`, `/api/attendance/history` | Ada |
| Review lokasi/geofence | `/location-reviews`, `/admin/office-geofence`, `/institutions/{id}/geofence`, `/attendance/{id}/location-review` | Ada |
| Jurnal | `/journal`, `/journal/{id}/sign`, `/journal-signature/{token}`, `/api/journal` | Ada |
| Izin/cuti | `/leave`, `/leave/{id}/review`, `/api/activity-log` | Ada |
| Peserta | `/participants`, `/profile`, `/profile/participant` | Ada |
| Pembimbing | `/supervisors`, `/supervisors/create-account` | Ada |
| Instansi | `/institutions`, `/institutions/{id}/geofence` | Ada |
| Penilaian | `/assessments` | Ada |
| Pengumuman | `/announcements` | Ada |
| Log audit | `/admin-audit`, `/face-logs`, `/face-logs/export.csv`, `/activity-log` | Ada |
| Notifikasi | `/api/notifications`, `.../read`, `.../read-all` | Ada |
| Laporan/ekspor | `/api/reports/attendance/excel`, `/attendance/pdf`, `/peserta/{id}/pdf`, `/peserta/{id}/sertifikat`, `/analytics/trend`, `/rekap/csv`, `/admin/backup` | Ada |
| Admin user mgmt | `/users/{id}/password`, `/force-logout`, `/soft-delete`, `/delete` | Ada |
| Kalender | `/attendance/calendar` | Ada |

---

## 3. PETA ENDPOINT (ringkas per router)

- **`app/routers/auth.py`** (prefix `/auth`): `POST /login`, `POST /register` — login JSON, mengembalikan JWT.
- **`app/routers/web.py`** (web utama, tanpa prefix): halaman + aksi form + endpoint wajah. **Kunci aplikasi ada di sini.**
- **`app/routers/attendance.py`** (prefix `/api/attendance`): `POST /checkin`, `GET /history`, `POST /manual`.
- **`app/routers/journal.py`** (prefix `/api/journal`): `POST ""`, `GET ""`.
- **`app/routers/dashboard.py`** (prefix `/api/dashboard`): `GET ""` (**publik**).
- **`app/routers/reports.py`** (prefix `/api/reports`): 6 endpoint ekspor.
- **`app/routers/leave.py`**: `/leave`, `/leave/{id}/review`, `/activity-log`.
- **`app/routers/admin.py`**: `supervisors`, `participants`, `institutions`, `assessments`, `announcements`, `admin-audit`, `face-logs`, `users/*`, `admin/backup`.

---

## 4. SKEMA DATABASE (nama tabel = Bahasa Indonesia)

| Tabel | Kolom penting | Relasi |
|---|---|---|
| `users` | id, username(uniq), email(uniq), password_hash, role, is_active, **session_version**, deleted_at | — |
| `peserta` | user_id(uniq FK), nama_lengkap, jurusan, instansi, tanggal_mulai/selesai | → users |
| `pembimbing` | user_id(uniq FK), nama_lengkap, nip, jabatan, bidang | → users |
| `instansi` | nama_instansi, alamat, kontak, office_lat/lng/radius_m/grace_m/max_accuracy_m | — |
| `absensi` | user_id FK, attendance_date, check_in_time, check_out_time, status, confidence_score, lat/lng, distance_from_office_m, requires_location_review, location_review_*, alasan_pulang_cepat | → users |
| `jurnal` | user_id FK, tanggal, kegiatan, output, status, komentar, signed_by_supervisor_id FK, signed_at, signature_token | → users, pembimbing |
| `permohonan_izin` | user_id FK, tanggal, jenis, keterangan, status, reviewed_by FK | → users |
| `penilaian` | user_id FK, nilai, catatan | → users |
| `pengumuman` | author_user_id FK, title, content, is_active | → users |
| `notifikasi` | user_id FK, message, type, is_read | → users |
| `app_settings` | key(PK), value | — |
| `activity_log` | user_id FK, action, detail, ip | → users |
| `admin_audit_log` | admin_user_id FK, action, target_user_id FK, detail, ip | → users |
| `face_embeddings` | user_id(uniq FK), embedding_json(encrypted), thumbnail_encrypted | → users |
| `face_verification_logs` | user_id FK(idx), action, matched, attempt_blocked, similarity, confidence, engine, message, source_ip | → users |

**Catatan skema:** (a) tidak ada tabel periode PKL/jadwal/penempatan tersendiri — hanya `tanggal_mulai/selesai` di `peserta`; (b) tidak ada kolom `liveness_score`; (c) indeks minim (kecuali PK/uniq/beberapa idx).

---

## 5. ARSITEKTUR SAAT INI (aktual)

```
Browser (Jinja2 + fetch base64 kamera)
   │  cookie user_id / session_ver (TIDAK ditandatangani)
   ▼
FastAPI routers ──► get_current_user()  // hanya cek cookie user_id
   │
   ├─ web.py: /face/verify ──► FaceRecognitionService (in-process)
   │                              └─ insightface buffalo_l  (fallback: Haar + center-crop + grayscale 64x64)
   ├─ SQLAlchemy ◄─ MySQL (kredensial root)
   └─ CSRF middleware (lewati /api/, /login, /register)
```

Tidak ada pemisahan service ML; tidak ada message queue; ML berjalan **in-process** di proses web.

---

## 6. DAFTAR TEMUAN (FINDINGS)

Klasifikasi: **C**=Critical, **H**=High, **M**=Medium, **L**=Low.

### KEAMANAN & AUTENTIKASI

**F-01 [C] Bypass autentikasi total via cookie `user_id` tanpa tanda tangan**
- Lokasi: `app/routers/web.py::get_current_user` (baris ~85), diulang di `app/routers/attendance.py::get_request_user`, `app/routers/journal.py::get_request_user`, `app/routers/reports.py::get_request_user`.
- Reproduksi: `curl --cookie "user_id=1" http://host/dashboard` → masuk sebagai user id 1.
- Akar masalah: sesi tidak memakai token bertanda tangan; `user_id` dipercaya mentah. Cek `session_ver` hanya dijalankan **jika cookie ada** (`if stored_ver is not None`), sehingga menghilangkan cookie `session_ver` menonaktifkan proteksi force-logout.
- Dampak: penyerang dapat menyamar sebagai admin/peserta mana pun (IDOR penuh, akses semua data & aksi).
- Rekomendasi: ganti sesi dengan **token bertanda tangan (HMAC) yang memuat user_id + session_version + exp**, verifikasi di semua dependency. (Lihat DB: `users.session_version` sudah tersedia untuk ini.)

**F-02 [C] Endpoint `/api/dashboard` publik (tanpa autentikasi)**
- Lokasi: `app/routers/dashboard.py::dashboard`.
- Bukti: `tests/test_smoke_routes.py::test_dashboard_api_responds_with_aggregate_counts` mengirim request **tanpa cookie** dan mengharapkan 200.
- Dampak: kebocoran agregat (jumlah user/absensi/jurnal).
- Rekomendasi: wajibkan autentikasi + pembatasan role.

**F-03 [C] Verifikasi wajah & absensi dapat dilakukan untuk identitas lain** (kombinasi F-01)
- Lokasi: `web.py::verify_face`, `web.py::register_face`.
- Akar masalah: `current_user` berasal dari cookie tak bertanda tangan.
- Dampak: (a) penyerang menyamar sebagai peserta lain; (b) **menimpa template embedding peserta lain** dengan wajah penyerang (perusakan biometrik + pencurian identitas absensi).
- Rekomendasi: perbaiki F-01; tambah otorisasi & audit untuk re-registrasi.

**F-04 [H] Absensi ditentukan client + tidak ada pengesahan backend yang kuat untuk absensi manual**
- Lokasi: `web.py::create_attendance` (POST `/attendance`) menerima `user_id` + `status` dari form; `attendance.py::checkin` menerima `token` sebagai **query string**.
- Dampak: pencatatan absensi tanpa verifikasi wajah/lokasi (oleh admin/pembimbing sah, tapi tanpa aturan bisnis/duplikasi).
- Rekomendasi: pusatkan semua penulisan absensi pada satu service ber-tansaksi, tambahkan constraint hari+user unik.

**F-05 [H] CSRF dilewati untuk `/api/` dan `/login`, `/register`; logout via GET**
- Lokasi: `app/security/csrf.py` (`_SKIP_PREFIXES`, `_SKIP_PATHS`), `web.py::logout` (GET).
- Dampak: login-CSRF, logout-CSRF, dan karena `/api/*` memakai cookie auth (F-01) maka aksi API juga rentan CSRF.
- Rekomendasi: jangan lewati `/api/` yang memakai cookie auth; logout via POST + CSRF.

**F-06 [H] Kunci enkripsi biometrik berasal dari JWT secret; `FACE_ENCRYPTION_KEY` kosong**
- Lokasi: `app/security/face_crypto.py::_get_fernet` (`settings.face_encryption_key or settings.jwt_secret_key`); `.env` → `FACE_ENCRYPTION_KEY=` (kosong).
- Dampak: tidak ada pemisahan kunci (melanggar BAB VI "kunci terpisah dari database"); mengubah JWT secret membuat seluruh template tak terdekripsi.
- Rekomendasi: kunci enkripsi khusus, wajib diisi, disimpan di luar DB, plus strategi rotasi.

**F-07 [H] Default konfigurasi tidak aman**
- Lokasi: `app/config.py` → `jwt_secret_key="change-me"`, `debug=True`, `cookie_secure=False`.
- Dampak: bila `.env` tidak dipakai, JWT dapat dipalsukan.
- Rekomendasi: tolak startup jika secret default/kosong di produksi; paksa `cookie_secure=True` saat HTTPS.

**F-08 [M] Parsing CSRF multipart manual rapuh**
- Lokasi: `app/security/csrf.py` (pencarian marker `name="csrf_token"` pada byte body).
- Dampak: potensi gagal/lolos pada payload tertentu (mis. urutan field berbeda).
- Rekomendasi: gunakan parser form standar/`python-multipart` resmi.

**F-09 [M] JWT kustom tanpa `jti`/revocation aktif; `python-jose`/`passlib` tercantum tapi tak dipakai**
- Lokasi: `app/authentication/jwt_handler.py`; `requirements.txt`.
- Dampak: dependensi mati (attack surface/typo-install), tidak ada daftar token tercabut selain bump `session_version`.
- Rekomendasi: rapikan dependensi; pertimbangkan library mapan.

**F-10 [M] `/admin/backup` — perlu verifikasi otorisasi & isi ekspor**
- Lokasi: `app/routers/admin.py::admin_backup` (baris 565). Perlu dipastikan hanya admin + tidak membocorkan template biometrik. (Perlu uji lanjutan.)

### MACHINE LEARNING / PIPELINE WAJAH

**F-11 [C] Fallback embedding bukan pengenal wajah sebenarnya & gagal senyap**
- Lokasi: `app/ai/face_service.py::_extract_embedding` (fallback `fallback-opencv`: resize 64x64 grayscale → flatten → normalisasi) dan `extract_embedding`.
- Akar masalah: jika InsightFace gagal dimuat, sistem tetap "berfungsi" dengan vektor piksel 4096-d. Ini mengukur korelasi piksel, bukan identitas; dapat menghasilkan kecocokan keliru.
- Dampak: verifikasi tidak sah namun tampak berhasil (melanggar prinsip "jangan nyatakan verifikasi berhasil hanya berdasarkan deteksi").
- Rekomendasi: **hapus fallback** untuk keputusan verifikasi; jika model tidak siap → tolak (fail-closed) dengan kode alasan, bukan fallback kecocokan.

**F-12 [C] `_detect_face` selalu mengembalikan hasil (center-crop) → "wajah tidak terdeteksi" tak pernah terjadi**
- Lokasi: `face_service.py::_detect_face` (fallback center crop 70%).
- Dampak: sampel non-wajah tetap diproses; registrasi/verifikasi bisa lolos tanpa wajah nyata.
- Rekomendasi: jika detektor Haar/model tidak menemukan wajah, kembalikan error eksplisit.

**F-13 [C] Liveness fail-open & lemah**
- Lokasi: `face_service.py::check_liveness` → `passed: True` saat error/skip; metrik hanya varians Laplacian (ambang 15.0).
- Dampak: foto/layar bermodus mudah lolos; kegagalan pemrosesan justru dianggap "lolos".
- Rekomendasi: fail-closed; gunakan model anti-spoof yang diuji; catat skor + metode.

**F-14 [C] Threshold verifikasi arbitrer (0.45) tanpa validasi FAR/FRR**
- Lokasi: `face_service.py::verify_embedding(threshold=0.45)`; dipanggil tanpa parameter khusus di `web.py::verify_face`.
- Dampak: melanggar BAB IV/4.4 ("jangan pakai threshold sembarang"; "skor bukan probabilitas").
- Rekomendasi: tentukan threshold dari data validasi, dokumentasikan metrik, konfigurasikan per model.

**F-15 [H] `confidence` = remap linear similarity → berisiko ditampilkan sebagai "kepastian identitas"**
- Lokasi: `face_service.py::verify_embedding` (`(similarity+1)/2`), dikembalikan `web.py` ke client + disimpan `absensi.confidence_score`.
- Dampak: menyesatkan (melanggar BAB VIII "jangan tampilkan skor sebagai persentase kepastian").
- Rekomendasi: jangan sajikan sebagai persentase; simpan metrik mentah + label kualitas.

**F-16 [H] Registrasi wajah tidak punya pemeriksaan kualitas multi-sampel & konsistensi**
- Lokasi: `face_service.py::register_embedding` + `web.py::register_face`.
- Dampak: satu frame yang lolos saja sudah cukup (melanggar BAB V/5.2); tidak ada cek blur/pose/konsistensi.
- Rekomendasi: ambil beberapa sampel, tolak kualitas rendah, cek konsistensi embedding, simpan 1 template agregat/beberapa terukur.

**F-17 [M] Tidak ada pencatatan `liveness` di `face_verification_logs`; tidak ada re-registration guard/audit**
- Lokasi: model `face_verification_logs`, `web.py::register_face`.
- Rekomendasi: tambah kolom liveness + audit re-registrasi (otorisasi admin).

**F-18 [M] Thumbnail wajah disimpan & dikirim kembali ke browser**
- Lokasi: `face_embeddings.thumbnail_encrypted`, `web.py::get_face_thumbnail` mengembalikan data URL (terdekripsi) ke client.
- Dampak: bertentangan dengan semangat minimisasi biometrik (PRD: jangan simpan foto; jangan kirim template ke browser). Thumbnail bukan template, tetapi tetap biometrik wajah.
- Rekomendasi: evaluasi kebutuhan; bila tak perlu, buang; bila perlu, tampilkan sekali di registrasi saja.

### ARSITEKTUR, DATABASE, KONFIGURASI

**F-19 [H] Migrasi tidak terkendali: `patch_legacy_schema()` menjalankan `ALTER TABLE` saat startup**
- Lokasi: `app/main.py::patch_legacy_schema` (46+ statement manual), juga `Base.metadata.create_all` + `seed_default_settings` saat import.
- Dampak: skema tidak ter-versi; rawan drift; `alembic` tercantum tapi tak dipakai; efek samping saat import (sulit diuji).
- Rekomendasi: adopsi Alembic; pindahkan seeding/DDL ke migrasi/lifespan terkontrol.

**F-20 [M] Naming campur (Indonesia/Inggris) & dua gaya API (halaman form + `/api/*`) dengan pengulangan `get_request_user` di 4 file**
- Dampak: duplikasi (melanggar DRY/reuse), titik perbaikan berulang.
- Rekomendasi: satukan dependency auth ke satu modul.

**F-21 [M] N+1/`SELECT *` potensial & indeks minim**
- Lokasi: pola query di `admin.py`, `reports.py`, `web.py` (mis. `db.query(...).all()` lalu akses relasi), laporan memuat seluruh tabel.
- Rekomendasi: eager loading, kolom eksplisit, pagination (sebagian sudah ada), tambah indeks pada kolom filter (user_id, attendance_date, created_at).

**F-22 [M] Rate limiter login in-memory per-proses**
- Lokasi: `app/services/rate_limiter.py`.
- Dampak: tidak efektif pada multi-worker/restart; tidak ada rate limit untuk endpoint wajah.
- Rekomendasi: simpan di store bersama (DB/Redis) + batasi endpoint biometrik.

**F-23 [L] `app/repositories/` kosong; `passlib`/`python-jose`/`alembic` belum benar-benar dipakai**
- Rekomendasi: bersihkan dependensi & folder mati.

### FRONTEND / UI-UX

**F-24 [M] Inkonsistensi stack CSS & ketergantungan CDN eksternal**
- Lokasi: `templates/layout.html` (Bootstrap vendored + `styles.css`), tetapi `index.html`/`journal_signature.html`/`face_logs.html` memuat **CDN** (Tailwind CDN, Bootstrap CDN, Chart.js CDN).
- Dampak: konflik gaya antar halaman; gagal total bila offline/instansi memblokir CDN (lingkungan instansi).
- Rekomendasi: pilih **satu** sistem (PRD menyarankan Tailwind bila cocok) lalu vendorkan aset; hapus CDN.
- Catatan: `layout.html` sudah cukup modern (tema/density, PWA, aria-label, font lokal-Google). Redesign sebaiknya **evolutif**, bukan bongkar total.

**F-25 [M] Belum ada alur absensi bertahap yang eksplisit + status/empty/error state baku**
- PRD BAB VIII menuntut tahapan (kamera siap → wajah terdeteksi → kualitas → proses → hasil → alasan gagal). Perlu audit visual `attendance.html` + `static/js/attendance.js` (belum dibaca menyeluruh).

---

## 7. HASIL AUDIT PIPELINE WAJAH (ringkas BAB II/2.3)

- Model: InsightFace **buffalo_l** (deteksi + embedding 512-d). **Tetapi** ada 3 jalur fallback yang menurunkan jaminan: Haar cascade, center-crop, dan vektor grayscale 64x64.
- Preprocessing: hanya decode → (insightface) langsung `.get()`; **tidak ada face alignment eksplisit** sebelum embedding (InsightFace menangani sebagian), tidak ada cek ukuran wajah minimal/ketajaman.
- Kualitas: tidak ada pemeriksaan blur/pose/pencahayaan terstruktur.
- Threshold: 0.45, arbitrer.
- Liveness: Laplacian, fail-open.
- Keputusan final: **sudah di backend** (baik) — tetapi backend mempercayai identitas dari cookie lemah (F-01) dan hasil model yang bisa jatuh ke fallback (F-11/F-12).

**Kesimpulan:** saat ini sistem **tidak konsisten** membandingkan identitas (kadang hanya korelasi piksel). Belum memenuhi acceptance criteria PRD BAB XIII #6 & #7.

---

## 8. TES & DOKUMENTASI

- `tests/test_smoke_routes.py`: sengaja menguji `/api/dashboard` tanpa auth → mengunci perilaku publik (perlu diubah bersama F-02).
- `tests/test_auth.py`, `tests/test_business_flows.py`: menyentuh **DB MySQL bersama** (lihat `/memories/repo/testing.md`) — perlu isolasi/transaksi uji.
- `docs/` sudah kaya (api_specification, endpoint_matrix_final, implementation_plan, final_readiness_checklist, dll) — **selaraskan** dengan temuan di atas.
- Tidak ditemukan test untuk pipeline wajah (kualitas, threshold, liveness, fallback) — **wajib ditambah**.

---

## 9. RENCANA TEKNIS (usulan, menunggu persetujuan)

### Strategi umum
Perubahan kecil & terukur, tiap langkah diuji, tidak menghapus fitur lama. Semua di branch terpisah + backup.

### Tahap A — Keamanan fondasi (paling mendesak, tanpa ubah UX)
1. **Sesi bertanda tangan** (F-01/F-03): buat dependency auth tunggal `app/security/session.py` yang menerbitkan cookie sesi ber-HMAC (user_id+session_version+exp), lalu ganti `get_current_user` & 4 `get_request_user` untuk memakainya.
   - File: `app/security/session.py` (baru), `app/routers/web.py`, `attendance.py`, `journal.py`, `reports.py`, `app/services/…`.
   - Uji: impersonation ditolak; force-logout tetap jalan; regresi login/logout.
2. **Amankan `/api/dashboard`** (F-02) — auth + role. Uji: 401 tanpa sesi.
3. **CSRF & logout** (F-05) — POST logout + token; jangan lewati `/api/` yang cookie-based.
4. **Kunci biometrik & config** (F-06/F-07) — `FACE_ENCRYPTION_KEY` wajib; tolak default secret; `cookie_secure` produksi.

### Tahap B — ML fail-closed & terukur (prasyarat sebelum klaim akurasi)
5. Hapus jalur fallback keputusan (F-11/F-12); liveness fail-closed (F-13).
6. Bangun **set validasi** + ukur FAR/FRR/latensi → tetapkan threshold (F-14); simpan metrik, jangan tampilkan skor sebagai persentase (F-15).
7. Registrasi multi-sampel + cek kualitas/konsistensi (F-16); catat liveness + audit re-registrasi (F-17).
8. Pertimbangkan **service ML terpisah** (FastAPI) + API internal ber-autentikasi, timeout, rate limit, **fail-closed** dengan prosedur manual. (Sesuai BENANG MERAH PRD; memerlukan keputusan stack — bagian 12.)

### Tahap C — Arsitektur & DB
9. Alembic + hentikan `patch_legacy_schema()` saat startup (F-19).
10. Konsolidasi auth dependency (F-20), tambah constraint unik absensi/hari & indeks (F-04/F-21), rate limit bersama (F-22).

### Tahap D — UI/UX
11. Tetapkan satu sistem desain (rekomendasi: **Tailwind vendored**), migrasi bertahap per halaman, **tanpa kehilangan fitur** (F-24).
12. Redesign halaman absensi jadi alur bertahap + state lengkap (F-25).

### Risiko utama
- Mengubah sesi (Tahap A) menyentuh semua halaman → butuh uji regresi menyeluruh.
- Mengganti enkripsi/threshold (B) berisiko mengunci template lama → siapkan migrasi template & re-registrasi terjadwal.
- Service ML terpisah menambah kompleksitas ops (2 proses) → butuh runbook + fallback manual.

### Strategi pengujian
- Unit: face_service (mock model), threshold, liveness.
- Integrasi: login→registrasi→verifikasi→absensi di **DB uji terisolasi** (bukan MySQL produksi).
- Keamanan: impersonation (F-01), CSRF, IDOR laporan, rate limit.
- Regresi: seluruh smoke test + test_business_flows sebelum/sesudah.

---

## 10. ASUMSI & BATASAN
- Audit ini berbasis pembacaan statis + struktur; **belum menjalankan** aplikasi/uji runtime (agar tidak mengganggu sistem berjalan).
- `attendance.html`, `static/js/attendance.js`, `admin.py`/`reports.py` bagian ekspor, dan `scheduler.py` **belum dibaca menyeluruh** → akan dilanjutkan sebelum menyentuh file terkait.
- Temuan F-10 perlu verifikasi uji lanjutan.

---

## 11. PERTANYAAN YANG MEMBUTUHKAN PERSETUJUAN (STOP — BAB XII)
1. **Stack**: PRD menyebut PHP native, tetapi repo adalah Python/FastAPI. Mana yang benar — (a) lanjutkan Python/FastAPI (realistis, tanpa migrasi besar), atau (b) memang ada aplikasi PHP terpisah yang harus diaudit?
2. **Service ML**: tetap **in-process** (sederhana) atau dipisah jadi **service Python FastAPI** (sesuai semangat PRD, lebih aman/terukur)?
3. **Template biometrik**: izinkan penyimpanan template embedding permanen (terenkripsi) atau **tanpa template persisten** (verifikasi per sesi)? Ini menentukan kelayakan verifikasi lintas sesi.
4. **Prioritas**: mulai dari **Tahap A (keamanan)** lebih dulu (rekomendasi saya) atau langsung ke ML/UI?
