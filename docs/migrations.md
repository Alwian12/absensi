# MIGRASI DATABASE (ALEMBIC)

Sejak perbaikan **F-19**, skema database dikelola oleh **migrasi berversi** (Alembic),
bukan lagi DDL mentah yang dijalankan setiap startup.

---

## 1. Lokasi & konfigurasi

| Berkas | Fungsi |
|---|---|
| `alembic.ini` | konfigurasi Alembic (`script_location`, logging) |
| `alembic/env.py` | memakai `app.config.settings.database_url` + `Base.metadata` |
| `alembic/versions/` | berkas migrasi |
| `scripts/migrate.ps1` | pembantu CLI |

URL database **tidak** di-hardcode di `alembic.ini`; diambil dari `.env` lewat
`app.config.settings`.

---

## 2. Migrasi baseline `0001_baseline`

Bersifat **idempotent & non-destruktif** — aman dijalankan pada database apa pun:

- **DB baru** → membuat semua tabel dari model.
- **DB lama** → membuat tabel yang belum ada + menambah kolom lama yang belum ada.
- **DB sudah termigrasi** → tidak melakukan apa-apa.

`downgrade()` sengaja **kosong** (no-op). Kebijakan proyek melarang `DROP TABLE`/
hapus data otomatis tanpa izin eksplisit. Untuk rollback skema, buat revisi baru
yang eksplisit dan disetujui.

---

## 3. Perintah

```powershell
# Terapkan semua migrasi (aman diulang)
.\scripts\migrate.ps1
# atau
.\.venv\Scripts\python.exe -m alembic upgrade head

# Lihat revisi aktif
.\.venv\Scripts\python.exe -m alembic current

# Riwayat
.\.venv\Scripts\python.exe -m alembic history --verbose
```

Aplikasi **tidak** menjalankan migrasi saat startup; tabel dibuat lewat `Base.metadata.create_all`. Jalankan `alembic upgrade head` manual bila diperlukan.

---

## 4. Menambah migrasi baru

```powershell
.\.venv\Scripts\python.exe -m alembic revision -m "tambah_kolom_x"
# edit berkas di alembic/versions/, lalu:
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Panduan:
- Gunakan `op.add_column` / `op.create_table` yang **idempotent** bila menyentuh
  database yang sudah berisi data produksi.
- Jangan menulis `DROP`/penghapusan data tanpa persetujuan.
- Uji migrasi pada salinan database sebelum rilis.

---

## 5. Baseline database yang sudah berjalan

Database produksi yang sudah ada akan otomatis menjadi revisi `0001_baseline`
saat `upgrade head` pertama dijalankan karena migrasi baseline tidak merusak apa pun
(tabel/kolom yang sudah ada dilewati). Tidak perlu `stamp` manual.
