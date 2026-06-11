# CodeLens — Live Codebase Reference Intelligence

> Sebuah tools yang berjalan aktif di background, memetakan seluruh referensi function, class, id, dan selector di dalam sebuah workspace — secara real-time — sebagai asupan konteks untuk AI agents.

---

## Konsep Inti

CodeLens bukan linter, bukan formatter. Tugasnya satu: **tahu siapa memanggil siapa, dari mana, dan seberapa sering** — lalu simpan itu dalam format yang bisa langsung dikonsumsi AI tanpa preprocessing tambahan.

Setiap kali ada perubahan file di workspace, registry diupdate otomatis. AI tidak perlu scan manual — tinggal query, langsung dapat konteks lengkap.

---

## Domain Tracking

CodeLens membagi workspace menjadi dua domain:

### 1. Frontend Domain (HTML / CSS / JS)

Target tracking: **`class`** dan **`id`** dari elemen HTML, dilacak ke seluruh referensi di CSS dan JS.

**Format output per entry:**

```json
{
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

**Flag yang dideteksi:**

| Flag | Kondisi |
|------|---------|
| `duplicate_define` | Selector/id di-define lebih dari 1x di CSS |
| `duplicate_ref` | Class/id dipanggil dari lebih dari 1 file JS |
| `dead` | Class/id ada di HTML tapi `ref_count: 0` di CSS dan JS |
| `html_id_collision` | ID yang sama muncul di lebih dari 1 elemen HTML |

---

### 2. Backend Domain (Rust + JS non-frontend)

Target tracking: **function-to-function calls**, membentuk directed graph.

**Cara membedakan JS frontend vs backend:**

CodeLens menggunakan folder convention. Bisa di-override via config.

```json
{
  "frontend_paths": ["src/client/", "public/", "frontend/"],
  "backend_paths":  ["src/server/", "src/api/", "src/"]
}
```

**Format output (edge list):**

```json
{
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

**Membaca cabang vs duplikat dari edge list:**

```
Cabang   → 1 node memiliki 2+ outgoing edges  (1 caller → banyak target)
Duplikat → 1 node memiliki 2+ incoming edges  (banyak caller → 1 target)
Dead     → ref_count: 0 (tidak ada incoming edge sama sekali)
```

Contoh visual dari edge list di atas:

```
main.rs:10
    └── auth.rs:42          ← dipanggil 1x (ref_count: 3 total dari file lain)
            ├── hash.rs:17  ← cabang A (ref_count: 0 = dead, tidak ada yang lain panggil)
            └── token.rs:88 ← cabang B
```

---

## Struktur Registry

CodeLens menyimpan semua data dalam JSON — satu format, zero ambiguity, langsung bisa dikonsumsi AI tanpa preprocessing.

```
workspace/
  .codelens/
    frontend.json     ← semua class/id dan referensinya
    backend.json      ← node + edge list semua function
    codelens.config.json
```

Registry diupdate setiap ada perubahan file (file watcher aktif).

**Prinsip desain JSON registry:**
- Tidak ada nested dalam yang tidak perlu — AI lebih mudah traverse flat structure
- Semua field eksplisit, tidak ada nilai implisit atau default tersembunyi
- `status` selalu hadir di setiap node — AI tidak perlu inferensi kondisi
- Array kosong `[]` lebih disukai daripada field yang dihapus — konsistensi schema

---

## Query Tool

AI memanggil satu function dengan input nama class/id/function, output adalah entry tunggal dari registry — sudah termasuk semua referensi, lokasi, dan status.

**Input:**
```json
{ "query": "verify_token", "domain": "backend" }
```

**Output:**
```json
{
  "node": {
    "id": "src/server/auth.rs:42",
    "fn": "verify_token",
    "ref_count": 3,
    "status": "active"
  },
  "callers": [
    { "from": "src/main.rs:10" },
    { "from": "src/middleware/guard.rs:55" },
    { "from": "src/api/login.rs:23" }
  ],
  "callees": [
    { "to": "src/utils/hash.rs:17",  "status": "dead" },
    { "to": "src/utils/token.rs:88", "status": "active" }
  ]
}
```

AI langsung tahu: function ini dipanggil 3x (dari mana saja), memanggil 2 function lain, dan salah satu target-nya dead.

---

## Status Reference

| Status | Arti |
|--------|------|
| `active` | Digunakan, ref_count > 0 |
| `dead` | Tidak ada yang reference, kandidat dead code / legacy |
| `duplicate_define` | Didefinisikan lebih dari sekali (CSS) |
| `duplicate_ref` | Direferensikan dari banyak tempat (perlu dicek intentional atau tidak) |
| `collision` | ID HTML muncul lebih dari 1x (bug) |

---

## Komponen yang Dibangun

| Komponen | Teknologi | Fungsi |
|----------|-----------|--------|
| File Watcher | Rust (`notify` crate) | Deteksi perubahan file real-time |
| Parser Frontend | JS/Rust | Extract class/id dari HTML, CSS, JS |
| Parser Backend | Rust (`tree-sitter`) | Extract function calls dari Rust + JS |
| Registry Writer | Rust | Tulis dan update `.codelens/*.json` |
| Query Tool | Rust / JS API | Filter dan return 1 entry dari registry |
| Visualizer | HTML/CSS/JS | Tampilkan graph interaktif dari registry |

---

## Catatan untuk v1

- Scope pertama: **reference duplikat** (bukan logic/semantic duplikat)
- Logic duplikat (dua function dengan isi mirip) masuk v2
- Query tool return format JSON flat, bukan nested tree
- Visualizer adalah UI terpisah yang consume registry yang sama

---

*CodeLens — karena AI yang baik tahu bukan hanya apa yang ada, tapi siapa yang pakai apa.*
