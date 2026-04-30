---
name: codelens
description: >
  CodeLens v2 — Live Codebase Reference Intelligence (Tree-sitter Edition).
  WAJIB aktifkan skill ini SETIAP KALI akan membuat, mengedit, atau menghapus HTML class/id,
  CSS selector, JSX className, atau function di Rust/JS/TS. Gunakan sebelum menulis kode baru
  yang melibatkan id, class, className, atau function name — untuk mencegah collision,
  overwrite logic lama, dan dead code. Trigger juga saat user minta "cek apakah id ini sudah ada",
  "lihat semua yang pakai class X", "ada function apa saja yang panggil Y", "scan workspace saya",
  "audit dead code", "cek duplicate CSS", "tampilkan semua reference ke N", atau "detect frameworks".
  Supports: HTML, CSS, JS, TS/TSX, Rust, Vue SFC, Svelte, Tailwind CSS, SCSS.
  Powered by tree-sitter for accurate AST-based parsing.
---

# CodeLens v2

Sebelum AI menulis class/id/function baru, CodeLens harus dicek. Ini bukan opsional.

## Apa yang Baru di v2

- **Tree-sitter powered**: AST-based parsing, bukan regex — akurat dan reliable
- **TSX/JSX support**: `className` di React, template literals, conditional classes
- **Vue SFC**: `:class` binding, scoped styles, script setup
- **Svelte**: `class:` directive, scoped styles
- **Tailwind CSS**: utility class detection, config parsing, dynamic class flagging
- **Framework auto-detect**: dari package.json dan config files
- **Incremental scan**: hanya re-parse file yang berubah
- **Better edge resolution**: cross-file function tracking yang akurat
- **6 languages**: HTML, CSS, JS, TS/TSX, Rust, Python

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

### 1. `codelens_init` — Initialize Workspace

Jalankan sekali di awal. Auto-detect frameworks dan buat config.

```bash
python3 "$CODELENS_DIR/scripts/codelens.py" init /path/to/workspace
```

### 2. `codelens_scan` — Scan Workspace

Scan seluruh workspace dan build registry. Gunakan `--incremental` untuk hanya re-parse file yang berubah.

```bash
# Full scan
python3 "$CODELENS_DIR/scripts/codelens.py" scan /path/to/workspace

# Incremental scan (hanya file yang berubah)
python3 "$CODELENS_DIR/scripts/codelens.py" scan /path/to/workspace --incremental
```

### 3. `codelens_query` — Pre-write Check (PALING PENTING)

Panggil ini **SEBELUM** membuat class, id, className, atau function baru.

```bash
# Query di domain tertentu
python3 "$CODELENS_DIR/scripts/codelens.py" query "modal-btn" /path/to/workspace --domain frontend

# Auto-detect domain
python3 "$CODELENS_DIR/scripts/codelens.py" query "verify_token" /path/to/workspace

# Filter berdasarkan file
python3 "$CODELENS_DIR/scripts/codelens.py" query "hash_password" /path/to/workspace --domain backend --file "src/utils/"
```

**Aturan untuk AI:**
- `found: true` + `status: active` → JANGAN buat ulang. Extend yang ada.
- `found: true` + `status: dead` → Ada tapi tidak dipakai. Reuse atau hapus dulu.
- `found: true` + `status: duplicate_ref` → Dipanggil dari banyak tempat. Hati-hati edit.
- `found: true` + `status: collision` → BUG AKTIF. STOP. Fix dulu.
- `found: false` → Aman. Lanjut buat.

### 4. `codelens_list` — List dengan Filter

```bash
# Semua dead code
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain all --filter dead

# ID collision (bug HTML)
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain frontend --filter collision

# Duplicate CSS
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain frontend --filter duplicate_define

# Backend dead functions
python3 "$CODELENS_DIR/scripts/codelens.py" list /path/to/workspace --domain backend --filter dead
```

### 5. `codelens_detect` — Detect Frameworks

```bash
python3 "$CODELENS_DIR/scripts/codelens.py" detect /path/to/workspace
```

### 6. `codelens_watch` — File Watcher

```bash
python3 "$CODELENS_DIR/scripts/codelens.py" watch /path/to/workspace
```

---

## Alur Kerja AI

```
User minta buat fitur baru yang ada id/class/function
          │
          ▼
1. Cek apakah registry sudah ada
   - Jika belum → codelens_init + codelens_scan
          │
          ▼
2. Panggil codelens_query untuk nama yang akan dibuat
          │
          ├─ found: false → Lanjut buat
          ├─ found: true + active → EXTEND jangan overwrite
          ├─ found: true + dead → Tanya user: reuse atau hapus?
          ├─ found: true + duplicate_ref → LIST semua referrers dulu
          └─ found: true + collision → STOP. Report. Fix dulu.
          │
          ▼
3. Setelah buat → re-scan (incremental)
          │
          ▼
4. Flag dead code dan collision ke user
```

---

## Supported Languages & Frameworks

| Language | Parser | Tracks |
|----------|--------|--------|
| HTML | tree-sitter-html | id, class |
| CSS | tree-sitter-css | .class, #id selectors |
| SCSS/Less | regex fallback | .class, #id selectors |
| JavaScript | tree-sitter-javascript | DOM selectors, function calls |
| TypeScript/TSX | tree-sitter-typescript | className, function calls, components |
| Rust | tree-sitter-rust | fn declarations, calls, impl blocks |
| Vue SFC | regex | :class, class, id, scoped styles |
| Svelte | regex | class:, class, id, scoped styles |
| Tailwind CSS | pattern detection | utility classes, @apply, dynamic patterns |

---

## Status & Flag Reference

| Status | Level | Arti | AI Action |
|--------|-------|------|-----------|
| `active` | node | Digunakan, ref_count > 0 | Normal, lanjut |
| `dead` | node | Tidak ada yang reference | Flag ke user |
| `duplicate_ref` | node | Referensi dari banyak tempat | List semua caller |
| `collision` | node | ID di >1 HTML elemen (bug) | STOP, fix dulu |
| `duplicate_define` | flag | Didefinisikan >1x | Warning ke user |

**Prioritas Action:**
1. `collision` → **STOP, fix dulu**
2. `duplicate_define` → **WARNING**
3. `dead` → **TANYA dulu**
4. `duplicate_ref` → **LIST semua caller dulu**
5. `active` → **Normal, lanjut**
6. `found: false` → **Aman, lanjut buat**

---

## Integrasi ke AI Agent

CodeLens menggunakan **passive integration** — AI agent memanggil CLI/API secara manual saat dibutuhkan.

### 3 Cara Integrasikan

| Method | Best For | Latency |
|--------|----------|---------|
| **CLI (subprocess)** | Agent apapun, non-Python | ~200-500ms |
| **Python API (import)** | Python-based agents | ~50-100ms |
| **JSON file read** | Read-only, dashboard | ~1ms |

### Quick Integration (CLI)

```python
import subprocess, json
CLI = "/path/to/skills/codelens/scripts/codelens.py"

def cl_query(name, workspace):
    r = subprocess.run(["python3", CLI, "query", name, workspace],
                       capture_output=True, text=True, timeout=30)
    return json.loads(r.stdout)
```

### Quick Integration (Python API)

```python
import sys; sys.path.insert(0, "/path/to/skills/codelens/scripts")
from codelens import cmd_scan, cmd_query, cmd_list, cmd_init

cmd_init("/workspace")                    # Once
cmd_scan("/workspace")                    # Before work
result = cmd_query("btn-primary", "/workspace")  # Before write
cmd_scan("/workspace", incremental=True)  # After write
```

### Aturan Integrasi WAJIB

1. **Query sebelum write** — SELALU panggil `codelens_query` sebelum membuat class/id/function baru
2. **Scan setelah write** — Jalankan `codelens_scan --incremental` setelah modifikasi kode
3. **STOP pada collision** — Jangan lanjut kalau ada ID collision, report ke user
4. **Report dead code** — Jangan silently ignore, tunjukkan ke user
5. **Handle errors gracefully** — Tangani ImportError dan FileNotFoundError

### Integration Guide Lengkap

Untuk detail lengkap cara integrasikan CodeLens ke berbagai tipe AI agent,
baca: **`references/agent-integration.md`**

Covers:
- CLI & Python API integration patterns
- JSON output schemas untuk setiap command
- Decision trees (pre-write, post-write, refactoring)
- Integration patterns per agent type (editor, reviewer, refactoring, docs)
- Error handling & graceful degradation
- Multi-agent coordination
- Integration checklist

---

## Referensi Lebih Lanjut

Load file referensi berikut untuk detail:

- `references/agent-integration.md` — **Panduan integrasi ke AI agent (CLI, Python API, JSON schemas, decision trees)**
- `references/parser-rules.md` — Aturan parsing per bahasa
- `references/query-examples.md` — Contoh query dan interpretasi output
- `references/status-codes.md` — Detail semua status dan flag
