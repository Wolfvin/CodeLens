---
name: codelens
description: >
  CodeLens — Live Codebase Reference Intelligence. WAJIB aktifkan skill ini SETIAP KALI akan membuat,
  mengedit, atau menghapus HTML class/id, CSS selector, atau function di Rust/JS. Gunakan sebelum
  menulis kode baru yang melibatkan id, class, atau function name — untuk mencegah collision,
  overwrite logic lama, dan dead code. Trigger juga saat user minta "cek apakah id ini sudah ada",
  "lihat semua yang pakai class X", "ada function apa saja yang panggil Y", "scan workspace saya",
  "audit dead code", "cek duplicate CSS", atau "tampilkan semua reference ke N".
  Covers both frontend (HTML/CSS/JS class+id tracking) and backend (Rust+JS function call graph).
---

# CodeLens

Sebelum AI menulis class/id/function baru, CodeLens harus dicek. Ini bukan opsional.

## Masalah yang Diselesaikan

Skenario yang SERING terjadi tanpa CodeLens:
1. AI buat `#modal-btn` baru
2. Ternyata `#modal-btn` sudah punya JS logic di `app.js:55`
3. AI tulis JS baru → overwrite logic lama
4. AI panik, hapus JS baru → logic lama balik tapi fitur baru tidak jalan
5. Dua-duanya broken

CodeLens mencegah ini dengan memberi AI **visibilitas penuh** sebelum menulis apapun.

---

## Skill Location

```
{project_path}/skills/codelens
```

---

## Prerequisites

Jalankan setup sekali sebelum menggunakan CodeLens:

```bash
bash "$CODELENS_DIR/setup.sh"
```

---

## Tools yang Tersedia

### 1. `codelens_scan` — Scan Workspace

Jalankan sekali di awal session atau saat diminta user. Men-scan seluruh workspace dan membangun registry.

**Cara panggil:**
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" scan /path/to/workspace
```

**Output:** Update registry di `.codelens/frontend.json` dan `.codelens/backend.json`.

Setelah scan, bisa aktifkan file watcher — registry update sendiri setiap ada perubahan file:
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" watch /path/to/workspace
```

---

### 2. `codelens_query` — Pre-write Check (PALING PENTING)

Panggil ini **SEBELUM** membuat class, id, atau function baru.

**Cara panggil:**
```bash
# Query di domain tertentu
python3 "$CODELENS_DIR/scripts/codelens.py" query "modal-btn" /path/to/workspace --domain frontend

# Auto-detect domain (cari di frontend dulu, lalu backend)
python3 "$CODELENS_DIR/scripts/codelens.py" query "verify_token" /path/to/workspace

# Filter berdasarkan file
python3 "$CODELENS_DIR/scripts/codelens.py" query "hash_password" /path/to/workspace --domain backend --file "src/utils/"
```

**Output jika sudah exist:**
```json
{
  "found": true,
  "type": "id",
  "domain": "frontend",
  "name": "modal-btn",
  "ref_count": 2,
  "status": "active",
  "css": [
    { "path": "src/styles/main.css", "line": 42, "flag": null }
  ],
  "js": [
    { "path": "src/app.js", "line": 55, "flag": null },
    { "path": "src/components/modal.js", "line": 88, "flag": null }
  ]
}
```

**Output jika belum exist:**
```json
{ "found": false, "query": "modal-btn", "domain": "auto" }
```

**Aturan untuk AI:**
- `found: true` → JANGAN buat ulang. Extend yang ada, atau diskusi dengan user dulu.
- `found: false` → Aman untuk dibuat. Lanjut.
- `status: "dead"` → Ada tapi tidak dipakai. Bisa reuse atau hapus dulu.
- `status: "collision"` → BUG AKTIF. Hentikan. Fix dulu sebelum lanjut.

---

### 3. `codelens_list` — List Semua dengan Filter

Untuk audit, debugging, atau request seperti "tampilkan semua dead code".

**Cara panggil:**
```bash
# Semua frontend entry
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain frontend --filter all

# Semua dead code (frontend + backend)
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain all --filter dead

# Semua ID collision (bug HTML)
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain frontend --filter collision

# Semua duplicate CSS define
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain frontend --filter duplicate_define

# Semua backend dead functions
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain backend --filter dead
```

**Filter yang tersedia:** `all` | `dead` | `duplicate_define` | `duplicate_ref` | `collision` | `active`

**Output:**
```json
{
  "domain": "frontend",
  "filter": "dead",
  "count": 2,
  "results": [
    { "type": "class", "name": "old-header", "ref_count": 0, "status": "dead", "defined_in": "src/styles/legacy.css:12" },
    { "type": "id", "name": "sidebar-v1", "ref_count": 0, "status": "dead", "defined_in": "index.html:88" }
  ]
}
```

---

### 4. `codelens_init` — Initialize Config

Buat direktori `.codelens/` dan file config default.

**Cara panggil:**
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" init /path/to/workspace
```

---

## Alur Kerja AI

```
User minta buat fitur baru yang ada id/class/function
          │
          ▼
1. Cek apakah registry sudah ada
   - Jika belum → jalankan codelens_scan dulu
          │
          ▼
2. Panggil codelens_query untuk nama yang akan dibuat
          │
          ├─ found: false → Lanjut buat
          ├─ found: true + status: active → Baca existing logic, EXTEND jangan overwrite
          ├─ found: true + status: dead → Tanya user: reuse atau hapus?
          ├─ found: true + status: duplicate_ref → List semua referrers, hati-hati edit
          └─ found: true + status: collision → STOP. Report ke user. Fix dulu.
          │
          ▼
3. Setelah buat → jika file watcher aktif, registry auto-update
   Jika tidak → jalankan codelens_scan lagi
          │
          ▼
4. Jika ada status "dead" atau "collision" → flag ke user
```

---

## Registry Format

Registry disimpan di `.codelens/` di root workspace. JSON only.

### `.codelens/frontend.json`
Berisi semua class dan id beserta referensinya di CSS dan JS.

### `.codelens/backend.json`
Berisi semua function node dan edge list (call graph).

### `.codelens/codelens.config.json`
Konfigurasi path dan ignore patterns.

---

## Konfigurasi Default

```json
{
  "frontend_paths": ["src/client/", "public/", "frontend/", "static/", "templates/"],
  "backend_paths": ["src/server/", "src/api/", "src/"],
  "watch": true,
  "ignore": ["node_modules/", "dist/", ".git/", "build/", "target/", "__pycache__/"]
}
```

Untuk mengubah, edit `.codelens/codelens.config.json` di root workspace.

---

## Status & Flag Reference

| Status | Level | Arti | AI Action |
|--------|-------|------|-----------|
| `active` | node | Digunakan, ref_count > 0 | Normal, lanjut |
| `dead` | node | Tidak ada yang reference | Flag ke user, tanya reuse/hapus |
| `duplicate_ref` | node | Direferensikan dari banyak tempat | List semua caller, hati-hati edit |
| `collision` | node | ID HTML muncul di >1 elemen (bug) | STOP, fix dulu |
| `duplicate_define` | flag | Selector/function didefinisikan >1x | Warning ke user |

**Prioritas Action:**
1. `collision` → **STOP, fix dulu**
2. `duplicate_define` → **WARNING, tunjukkan ke user**
3. `dead` + user mau edit → **TANYA dulu**
4. `duplicate_ref` + user mau edit → **LIST semua caller dulu**
5. `active` → **Normal, lanjut**
6. `found: false` → **Aman, lanjut buat**

---

## Domain Tracking

### Frontend Domain (HTML / CSS / JS)
Target: **class** dan **id** dari elemen HTML, dilacak ke seluruh referensi di CSS dan JS.

### Backend Domain (Rust + JS non-frontend)
Target: **function-to-function calls**, membentuk directed graph.

JS frontend vs backend ditentukan berdasarkan folder convention di config:
- File di `frontend_paths` → JS Frontend Parser (DOM selector tracking)
- File di `backend_paths` → JS Backend Parser (function call graph)
- Default (tidak cocok keduanya) → JS Backend Parser

---

## Referensi Lebih Lanjut

Load file referensi berikut untuk detail lebih lengkap:

- `references/parser-rules.md` — Aturan parsing per bahasa (HTML, CSS, JS, Rust)
- `references/query-examples.md` — Contoh query untuk berbagai use case
- `references/status-codes.md` — Detail lengkap semua status dan flag
