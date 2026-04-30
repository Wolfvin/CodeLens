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

## P1 Tools — Search, Trace, Impact

### 7. `codelens_search` — Code Search

Cari regex pattern di seluruh workspace. Seperti ripgrep tapi built-in.

```bash
# Cari semua useEffect
python3 "$CODELENS_DIR/scripts/codelens.py" search "useEffect" /path/to/workspace

# Cari di file tertentu saja
python3 "$CODELENS_DIR/scripts/codelens.py" search "router\\.post" /path/to/workspace --type js

# Case-insensitive + context lines
python3 "$CODELENS_DIR/scripts/codelens.py" search "CREATE TABLE" /path/to/workspace --ignore-case --context 3

# Whole word
python3 "$CODELENS_DIR/scripts/codelens.py" search "Button" /path/to/workspace --type tsx --whole-word
```

**Options:** `--type`, `--file`, `--max-results`, `--context`, `--ignore-case`, `--whole-word`

### 8. `codelens_symbols` — Symbol Search

Cari symbol di registry (bukan di file). Lebih cepat dari search.

```bash
# Exact match
python3 "$CODELENS_DIR/scripts/codelens.py" symbols "btn" /path/to/workspace

# Fuzzy search (partial match)
python3 "$CODELENS_DIR/scripts/codelens.py" symbols "modal" /path/to/workspace --fuzzy

# Backend only
python3 "$CODELENS_DIR/scripts/codelens.py" symbols "auth" /path/to/workspace --domain backend --fuzzy
```

### 9. `codelens_trace` — Deep Call Chain

Trace call chain dari symbol. Untuk root cause analysis dan impact assessment.

```bash
# Trace callers (siapa yang manggil function ini)
python3 "$CODELENS_DIR/scripts/codelens.py" trace "verify_token" /path/to/workspace --direction up

# Trace callees (function ini manggil apa)
python3 "$CODELENS_DIR/scripts/codelens.py" trace "verify_token" /path/to/workspace --direction down

# Both directions
python3 "$CODELENS_DIR/scripts/codelens.py" trace "verify_token" /path/to/workspace --direction both --depth 5
```

**AI Use Case:** "Bug di render() → trace ke mana asalnya" → `trace render workspace --direction up`

### 10. `codelens_impact` — Change Impact Analysis

Prediksi dampak jika symbol diubah atau dihapus. Wajib sebelum refactoring.

```bash
# Cek impact kalau modify
python3 "$CODELENS_DIR/scripts/codelens.py" impact "verify_token" /path/to/workspace --action modify

# Cek impact kalau delete
python3 "$CODELENS_DIR/scripts/codelens.py" impact "btn-primary" /path/to/workspace --action delete
```

**Output:** risk level (low/medium/high/critical), affected files, direct/indirect dependents, recommendations.

**AI Action:**
- `risk: critical` → JANGAN ubah. Report ke user.
- `risk: high` → Warning. List semua affected dulu.
- `risk: medium` → Hati-hati. Jalankan tests.
- `risk: low` → Aman, lanjut.

---

## P2 Tools — Outline, Missing-refs, Diff, Circular

### 11. `codelens_outline` — File Structure Outline

Lihat struktur file tanpa baca full content. Semua function, class, import, export.

```bash
# Outline satu file
python3 "$CODELENS_DIR/scripts/codelens.py" outline src/auth.ts /path/to/workspace

# Outline dengan detail level
python3 "$CODELENS_DIR/scripts/codelens.py" outline src/auth.ts /path/to/workspace --detail full

# Outline semua file di workspace
python3 "$CODELENS_DIR/scripts/codelens.py" outline /path/to/workspace --all
```

### 12. `codelens_missing-refs` — CSS/HTML Mismatch Detection

Detek bug: class di HTML tapi gak ada di CSS, CSS selector tapi gak ada HTML, typo.

```bash
python3 "$CODELENS_DIR/scripts/codelens.py" missing-refs /path/to/workspace
```

**Detects:**
- `css_no_html` — CSS class didefinisikan tapi gak pernah dipakai
- `html_no_css` — HTML/JSX class dipakai tapi gak ada CSS definition
- `css_id_no_html` — CSS style ID tapi gak ada HTML definition
- `js_id_no_html` — JS reference ID tapi gak ada HTML definition
- `possible_typos` — Dead class yang mirip active class (kemungkinan typo)

### 13. `codelens_diff` — Registry Diff

Compare registry sekarang vs snapshot terakhir. Track apa yang berubah.

```bash
# Diff vs snapshot terakhir
python3 "$CODELENS_DIR/scripts/codelens.py" diff /path/to/workspace

# List semua snapshot
python3 "$CODELENS_DIR/scripts/codelens.py" diff /path/to/workspace --list-snapshots

# Compare dua snapshot spesifik
python3 "$CODELENS_DIR/scripts/codelens.py" diff /path/to/workspace --snapshot1 20240101T120000Z --snapshot2 20240102T090000Z
```

**Note:** Snapshot otomatis disimpan setiap kali `scan` dijalankan.

### 14. `codelens_circular` — Circular Dependency Detection

Deteksi circular: function calls, import chains, CSS @import.

```bash
# Cek semua
python3 "$CODELENS_DIR/scripts/codelens.py" circular /path/to/workspace

# Hanya function call cycles
python3 "$CODELENS_DIR/scripts/codelens.py" circular /path/to/workspace --domain backend

# Hanya import cycles
python3 "$CODELENS_DIR/scripts/codelens.py" circular /path/to/workspace --domain imports
```

**Severity:** `critical` (2-node cycle), `warning` (3+ node cycle), `info` (long chain)

---

## P3 Tools — Context, Dependents, Validate

### 15. `codelens_context` — Rich Symbol Context

Semua yang AI butuh tentang symbol: definition code, callers, callees, file outline, imports.

```bash
python3 "$CODELENS_DIR/scripts/codelens.py" context "verify_token" /path/to/workspace

# Tanpa source code
python3 "$CODELENS_DIR/scripts/codelens.py" context "verify_token" /path/to/workspace --no-code

# Context lines lebih banyak
python3 "$CODELENS_DIR/scripts/codelens.py" context "verify_token" /path/to/workspace --context-lines 10
```

**Returns:** definition, code_snippet, callers, callees, nearby_symbols, file_outline, imports

### 16. `codelens_dependents` — Module-Level Import Tracking

Siapa yang import file ini? Level module, bukan function.

```bash
# Siapa yang import file ini?
python3 "$CODELENS_DIR/scripts/codelens.py" dependents src/utils/auth.ts /path/to/workspace

# File ini import apa?
python3 "$CODELENS_DIR/scripts/codelens.py" dependents src/utils/auth.ts /path/to/workspace --direction dependencies

# Full dependency graph
python3 "$CODELENS_DIR/scripts/codelens.py" dependents src/utils/auth.ts /path/to/workspace --direction graph
```

### 17. `codelens_validate` — Registry Sanity Check

Cek apakah registry masih sinkron dengan file system.

```bash
python3 "$CODELENS_DIR/scripts/codelens.py" validate /path/to/workspace
```

**Detects:**
- `missing_files` — File di registry tapi sudah dihapus
- `unregistered_files` — File baru yang belum di-scan
- `stale_references` — Line number yang sudah berubah
- `orphan_entries` — Entry yang semua file referensinya sudah hilang

---

## Alur Kerja AI

### Basic Flow (Pre-write Check)

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

### Advanced Flow (Bug Investigation)

```
User: "Bug di modal gak close"
          │
          ▼
1. codelens_search "closeModal" workspace
   → Cari di mana closeModal didefinisikan dan dipanggil
          │
          ▼
2. codelens_context "closeModal" workspace
   → Lihat definition code, callers, callees, imports
          │
          ▼
3. codelens_trace "closeModal" workspace --direction up
   → Trace siapa yang manggil closeModal (full chain)
          │
          ▼
4. codelens_missing-refs workspace
   → Cek apakah ada CSS class yang kelewat atau ID yang salah
          │
          ▼
5. Report ke user: "Bug ditemukan di ..."
```

### Pre-Delete Flow (Safe Removal)

```
User: "Hapus function X"
          │
          ▼
1. codelens_impact "X" workspace --action delete
   → Cek risk level dan affected files
          │
          ├─ risk: critical → STOP. Report ke user.
          ├─ risk: high → Warning. List affected.
          └─ risk: low → Lanjut.
          │
          ▼
2. Hapus function X
          │
          ▼
3. codelens_scan workspace --incremental
          │
          ▼
4. codelens_list workspace --filter dead
   → Cek dead code baru yang mungkin tercipta
          │
          ▼
5. codelens_diff workspace
   → Verify perubahan yang terjadi
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
