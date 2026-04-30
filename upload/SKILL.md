---
name: codelens
description: >
  CodeLens adalah live reference intelligence tool untuk workspace frontend dan backend.
  Gunakan skill ini setiap kali AI akan membuat, mengedit, atau menghapus HTML class/id,
  CSS selector, atau function di Rust/JS. WAJIB trigger sebelum menulis kode baru yang
  melibatkan id, class, atau function name — untuk mencegah collision, overwrite logic lama,
  dan dead code. Trigger juga saat user minta "cek apakah id ini sudah ada", "lihat semua
  yang pakai class X", "ada function apa saja yang panggil Y", atau "scan workspace saya".
---

# CodeLens

Sebelum AI menulis class/id/function baru, CodeLens harus dicek. Ini bukan opsional.

## Masalah yang diselesaikan

Skenario yang SERING terjadi tanpa CodeLens:
1. AI buat `#modal-btn` baru
2. Ternyata `#modal-btn` sudah punya JS logic di `app.js:55`
3. AI tulis JS baru → overwrite logic lama
4. AI panik, hapus JS baru → logic lama balik tapi fitur baru tidak jalan
5. Dua-duanya broken

CodeLens mencegah ini dengan memberi AI **visibilitas penuh** sebelum menulis apapun.

---

## Tools yang tersedia

### 1. `codelens_query` — Pre-write Check (PALING PENTING)

Panggil ini SEBELUM membuat class, id, atau function baru.

**Input:**
```json
{ "query": "modal-btn", "domain": "frontend" }
```

**Output jika sudah exist:**
```json
{
  "found": true,
  "type": "id",
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
{ "found": false, "query": "modal-btn", "domain": "frontend" }
```

**Aturan:**
- `found: true` → JANGAN buat ulang. Extend yang ada, atau diskusi dengan user dulu.
- `found: false` → Aman untuk dibuat. Lanjut.
- `status: "dead"` → Ada tapi tidak dipakai. Bisa reuse atau hapus dulu.

---

### 2. `codelens_scan` — Scan Workspace

Jalankan sekali di awal session atau saat diminta user.

**Input:**
```json
{ "workspace": "/path/to/project" }
```

**Output:** Update registry di `.codelens/frontend.json` dan `.codelens/backend.json`.

Setelah scan, file watcher aktif otomatis — registry update sendiri setiap ada perubahan file.

---

### 3. `codelens_list` — List Semua dengan Filter

Untuk audit, debugging, atau request seperti "tampilkan semua dead code".

**Input:**
```json
{ "domain": "frontend", "filter": "dead" }
```

**Filter yang tersedia:** `all` | `dead` | `duplicate_define` | `duplicate_ref` | `collision` | `active`

**Output:**
```json
{
  "domain": "frontend",
  "filter": "dead",
  "count": 3,
  "results": [
    { "type": "class", "name": "old-header", "ref_count": 0, "status": "dead", "defined_in": "src/styles/legacy.css:12" },
    { "type": "id",    "name": "sidebar-v1", "ref_count": 0, "status": "dead", "defined_in": "index.html:88" }
  ]
}
```

---

## Registry Format

Registry disimpan di `.codelens/` di root workspace. JSON only.

### `.codelens/frontend.json`

```json
{
  "last_updated": "2025-01-01T00:00:00Z",
  "workspace": "/path/to/project",
  "classes": [
    {
      "name": "btn-primary",
      "ref_count": 3,
      "status": "duplicate_ref",
      "css": [
        { "path": "src/styles/main.css",   "line": 42, "flag": null },
        { "path": "src/styles/button.css", "line": 17, "flag": "duplicate_define" }
      ],
      "js": [
        { "path": "src/components/modal.js", "line": 88, "flag": null },
        { "path": "src/utils/toggle.js",     "line": 31, "flag": null }
      ]
    }
  ],
  "ids": [
    {
      "name": "sidebar-nav",
      "ref_count": 2,
      "status": "active",
      "defined_in_html": [
        { "path": "index.html", "line": 44, "flag": null }
      ],
      "css": [
        { "path": "src/styles/layout.css", "line": 104, "flag": null }
      ],
      "js": [
        { "path": "src/app.js", "line": 55, "flag": null }
      ]
    }
  ]
}
```

### `.codelens/backend.json`

```json
{
  "last_updated": "2025-01-01T00:00:00Z",
  "workspace": "/path/to/project",
  "nodes": [
    {
      "id": "src/server/auth.rs:42",
      "fn": "verify_token",
      "file": "src/server/auth.rs",
      "line": 42,
      "ref_count": 3,
      "status": "active"
    },
    {
      "id": "src/utils/hash.rs:17",
      "fn": "hash_password",
      "file": "src/utils/hash.rs",
      "line": 17,
      "ref_count": 0,
      "status": "dead"
    }
  ],
  "edges": [
    { "from": "src/main.rs:10",        "to": "src/server/auth.rs:42" },
    { "from": "src/server/auth.rs:42", "to": "src/utils/hash.rs:17" },
    { "from": "src/server/auth.rs:42", "to": "src/utils/token.rs:88" }
  ]
}
```

---

## Status & Flag Reference

| Status | Level | Arti |
|--------|-------|------|
| `active` | node | Digunakan, ref_count > 0 |
| `dead` | node | Tidak ada yang reference — kandidat legacy/dead code |
| `duplicate_ref` | node | Direferensikan dari banyak tempat |
| `collision` | node | ID HTML muncul di lebih dari 1 elemen (bug) |
| `duplicate_define` | flag (per-referensi) | Selector/function didefinisikan lebih dari 1x |

**Membaca cabang vs duplikat dari backend edge list:**
- **Cabang** → 1 node punya 2+ outgoing edges (1 caller → banyak target)
- **Duplikat** → 1 node punya 2+ incoming edges (banyak caller → 1 target)
- **Dead** → ref_count: 0, tidak ada incoming edge

---

## Alur Kerja AI

```
User minta buat fitur baru yang ada id/class/function
          ↓
1. Panggil codelens_query dulu
          ↓
    found: false → Lanjut buat
    found: true  → Baca existing logic, extend jangan overwrite
          ↓
2. Setelah buat → registry auto-update via file watcher
          ↓
3. Jika ada status "dead" atau "collision" → flag ke user
```

---

## Konfigurasi

`.codelens/codelens.config.json`

```json
{
  "frontend_paths": ["src/client/", "public/", "frontend/"],
  "backend_paths":  ["src/server/", "src/api/", "src/"],
  "watch": true,
  "ignore": ["node_modules/", "dist/", ".git/"]
}
```

---

## Referensi Lebih Lanjut

- `references/parser-rules.md` — Aturan parsing per bahasa (HTML, CSS, JS, Rust)
- `references/status-codes.md` — Detail lengkap semua status dan flag
- `references/query-examples.md` — Contoh query untuk berbagai use case
