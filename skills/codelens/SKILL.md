---
name: codelens
description: >
  CodeLens v4 — Live Codebase Reference Intelligence (Tree-sitter Edition).
  WAJIB aktifkan skill ini SETIAP KALI akan membuat, mengedit, atau menghapus HTML class/id,
  CSS selector, JSX className, atau function di Rust/JS/TS. Gunakan sebelum menulis kode baru
  yang melibatkan id, class, className, atau function name — untuk mencegah collision,
  overwrite logic lama, dan dead code. Trigger juga saat user minta "cek apakah id ini sudah ada",
  "lihat semua yang pakai class X", "ada function apa saja yang panggil Y", "scan workspace saya",
  "audit dead code", "cek duplicate CSS", "tampilkan semua reference ke N", atau "detect frameworks".
  v3 adds: data flow analysis, code smell detection, side-effect analysis, refactoring safety,
  enhanced dead code, error propagation, test coverage mapping, config drift detection,
  lightweight type inference, and code ownership analysis.
  v4 adds: hardcoded secret detection, execution entry point mapping, API route→handler mapping,
  global state management tracking, environment variable auditing, debug code leak detection,
  cyclomatic/cognitive complexity scoring, ReDoS-vulnerable regex auditing, accessibility auditing.
  Supports: HTML, CSS, JS, TS/TSX, Rust, Python, Vue SFC, Svelte, Tailwind CSS, SCSS.
  Powered by tree-sitter for accurate AST-based parsing.
---

# CodeLens v4

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

## Apa yang Baru di v3

- **Data Flow Analysis**: Track data dari sources ke sinks, deteksi taint violations
- **Code Smell Detection**: 10 kategori smell dengan health score
- **Side Effect Analysis**: Klasifikasi pure vs impure function
- **Refactoring Safety**: Pre-flight rename/move check dengan risk assessment
- **Enhanced Dead Code**: Unreachable code, unused exports, zombie CSS
- **Error Propagation**: Simulasi crash paths, temukan unhandled errors
- **Test Coverage Map**: Fungsi mana yang sudah ditest, mana yang belum
- **Config Drift**: Package.json vs actual imports mismatch detection
- **Type Inference**: Lightweight type inference untuk JS/Python
- **Code Ownership**: Git blame-based, temukan stale code dan owners

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

# both directions
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
python3 "$CODELENS_DIR/scripts/codelens.py" outline /path/to/workspace --file src/auth.ts

# Outline dengan detail level
python3 "$CODELENS_DIR/scripts/codelens.py" outline /path/to/workspace --file src/auth.ts --detail full

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

## v3 P0: Dataflow & Smell

### 18. `codelens_dataflow` — Data Flow Analysis (Source→Sink)

Trace di mana data mengalir dari sources (user input, env vars, file reads, API responses) ke sinks (DB queries, HTML output, command exec, file writes, HTTP headers). Deteksi taint violations (data yang sampai ke dangerous sinks tanpa sanitization).

- Menunjukkan safe paths (data yang melewati sanitizers)
- Risk level: none/low/medium/high/critical

**AI Use Case:** "Apakah user input pernah sampai ke SQL query tanpa sanitization?"

```bash
# Full workspace scan
python3 "$CODELENS_DIR/scripts/codelens.py" dataflow /path/to/workspace

# Filter berdasarkan source type
python3 "$CODELENS_DIR/scripts/codelens.py" dataflow /path/to/workspace --source user_input

# Filter berdasarkan sink type
python3 "$CODELENS_DIR/scripts/codelens.py" dataflow /path/to/workspace --sink db_query
```

**Options:** `--source` (user_input, dom_input, env_var, file_input, api_response), `--sink` (db_query, html_output, command_exec, file_write, http_header), `--depth`

### 19. `codelens_smell` — Code Smell Detection

Deteksi 10 kategori code smell: long_fn, deep_nesting, many_params, large_file, callback_hell, magic_values, god_object, complex_conditional, duplicate_pattern, inconsistent. Setiap smell punya severity (info/warning/critical) dan refactoring suggestion. Menghitung health_score (0-100).

**AI Use Case:** "Apa yang harus saya refactor pertama di codebase ini?"

```bash
# Semua kategori
python3 "$CODELENS_DIR/scripts/codelens.py" smell /path/to/workspace

# Kategori spesifik
python3 "$CODELENS_DIR/scripts/codelens.py" smell /path/to/workspace --categories long_fn god_object

# Hanya smell critical
python3 "$CODELENS_DIR/scripts/codelens.py" smell /path/to/workspace --severity critical
```

---

## v3 P1: Side-effect, Refactor-safe, Dead-code

### 20. `codelens_side-effect` — Side Effect Analysis

Tag function sebagai pure vs impure. Deteksi 7 kategori side-effect: DOM, State, Network, IO, Timer, Random, External. Menghitung purity ratio untuk seluruh workspace.

**AI Use Case:** "Apakah aman memanggil function ini berkali-kali?"

```bash
# Full workspace
python3 "$CODELENS_DIR/scripts/codelens.py" side-effect /path/to/workspace

# Function spesifik
python3 "$CODELENS_DIR/scripts/codelens.py" side-effect /path/to/workspace --name processOrder

# Filter by file
python3 "$CODELENS_DIR/scripts/codelens.py" side-effect /path/to/workspace --file src/orders.ts
```

### 21. `codelens_refactor-safe` — Refactoring Safety Check

Pre-flight check sebelum rename/move symbol. Deteksi: string refs, dynamic access, eval refs, meta-programming, test refs, config refs, doc refs, import breaks, CSS refs. Safety level: safe/mostly_safe/cautious/risky/dangerous. Menghasilkan pre-refactor checklist.

**AI Use Case:** "Bisakah saya safely rename function ini?"

```bash
# Cek rename safety
python3 "$CODELENS_DIR/scripts/codelens.py" refactor-safe verify_token /path/to/workspace --action rename --new-name validate_token

# Cek move safety
python3 "$CODELENS_DIR/scripts/codelens.py" refactor-safe auth /path/to/workspace --action move --new-name src/auth/
```

### 22. `codelens_dead-code` — Enhanced Dead Code Detection

Lebih dari sekadar 0-ref_count: deteksi unreachable code, unused exports, zombie CSS, unused variables, dead event listeners.

**AI Use Case:** "Kode apa yang bisa saya hapus dengan aman?"

```bash
# Semua kategori
python3 "$CODELENS_DIR/scripts/codelens.py" dead-code /path/to/workspace

# Kategori spesifik
python3 "$CODELENS_DIR/scripts/codelens.py" dead-code /path/to/workspace --categories unreachable unused_exports
```

---

## v3 P2: Stack-trace, Test-map, Config-drift

### 23. `codelens_stack-trace` — Error Propagation Simulation

Simulasi apa yang terjadi jika sebuah function throw: trace error ke atas call stack. Tunjukkan caller mana yang punya try/catch (handled) dan yang tidak (unhandled → crash). Crash risk: low/medium/high/critical.

**AI Use Case:** "Kalau ini gagal, apa yang rusak?"

```bash
python3 "$CODELENS_DIR/scripts/codelens.py" stack-trace verify_token /path/to/workspace

# Dengan tipe error spesifik
python3 "$CODELENS_DIR/scripts/codelens.py" stack-trace processOrder /path/to/workspace --error-type NetworkError
```

### 24. `codelens_test-map` — Test Coverage Mapping

Map function mana yang punya test coverage. Strategi: file name matching, function name matching, import matching. Temukan file tanpa test sama sekali.

**AI Use Case:** "Apakah function ini sudah ditest sebelum saya modifikasi?"

```bash
# Full workspace
python3 "$CODELENS_DIR/scripts/codelens.py" test-map /path/to/workspace

# Function spesifik
python3 "$CODELENS_DIR/scripts/codelens.py" test-map /path/to/workspace --function verify_token
```

### 25. `codelens_config-drift` — Dependency Drift Detection

Validasi package.json/Cargo.toml/requirements.txt vs actual imports. Temukan: missing deps, unused deps, phantom imports.

**AI Use Case:** "Apakah ada package yang lupa di-install atau dideklarasikan tapi tidak pernah dipakai?"

```bash
python3 "$CODELENS_DIR/scripts/codelens.py" config-drift /path/to/workspace
```

---

## v3 P3: Type-infer, Ownership

### 26. `codelens_type-infer` — Lightweight Type Inference

Infer tipe untuk variabel dan function JS/Python. Strategi: literal inference, return type inference, known API return types, propagation. Skip file yang sudah punya TypeScript annotations.

**AI Use Case:** "Tipe apa yang dikembalikan function ini?"

```bash
# Full workspace
python3 "$CODELENS_DIR/scripts/codelens.py" type-infer /path/to/workspace

# File spesifik
python3 "$CODELENS_DIR/scripts/codelens.py" type-infer /path/to/workspace --file src/utils.ts

# Function spesifik
python3 "$CODELENS_DIR/scripts/codelens.py" type-infer /path/to/workspace --function processOrder
```

### 27. `codelens_ownership` — Code Ownership Analysis

Git blame-based ownership: siapa yang terakhir menyentuh apa, seberapa tua kode ini. Temukan stale code, hotspots (banyak author), orphan files (tidak ada perubahan baru). Fallback ke mtime kalau git tidak tersedia.

**AI Use Case:** "Siapa yang harus saya tanya sebelum mengubah ini?"

```bash
# Full workspace
python3 "$CODELENS_DIR/scripts/codelens.py" ownership /path/to/workspace

# File spesifik
python3 "$CODELENS_DIR/scripts/codelens.py" ownership /path/to/workspace --file src/auth.ts

# Function spesifik
python3 "$CODELENS_DIR/scripts/codelens.py" ownership /path/to/workspace --function verify_token
```

---

## v4 P0: Secrets, Entrypoints

### 28. `codelens_secrets` — Hardcoded Secret Detection

Deteksi API keys, passwords, tokens, connection strings, private keys, dan secret keys yang hardcoded di source code. Termasuk Shannon entropy detection untuk flag high-entropy strings yang mungkin secret. Scan .env files dan cek .gitignore.

**AI Use Case:** "Ada API key yang tercecer di codebase?"

```bash
# Full workspace scan
python3 "$CODELENS_DIR/scripts/codelens.py" secrets /path/to/workspace

# Filter severity
python3 "$CODELENS_DIR/scripts/codelens.py" secrets /path/to/workspace --severity critical
```

**Categories:** api_key, password, token, connection_string, private_key, secret_key, oauth, webhook

### 29. `codelens_entrypoints` — Execution Entry Point Mapping

Map semua execution entry points: main(), HTTP handlers, event listeners, CLI commands, cron jobs, workers, module exports, test entries. "Di mana aplikasi ini dimulai?"

**AI Use Case:** "Bagaimana cara menjalankan kode ini? Endpoint mana yang bisa dipanggil?"

```bash
# Semua entry points
python3 "$CODELENS_DIR/scripts/codelens.py" entrypoints /path/to/workspace

# Hanya HTTP handlers
python3 "$CODELENS_DIR/scripts/codelens.py" entrypoints /path/to/workspace --type http_handler

# Hanya main entry
python3 "$CODELENS_DIR/scripts/codelens.py" entrypoints /path/to/workspace --type main
```

**Types:** main, http_handler, event_handler, cli_command, cron_job, worker, module_export, test_entry

---

## v4 P1: API Map, State Map, Env Check

### 30. `codelens_api-map` — REST/GraphQL/gRPC Route Mapping

Map semua route ke handler: Express, Fastify, Koa, Hono, Next.js, Nuxt, Django, Flask, FastAPI, GraphQL, gRPC, tRPC. Extract method, path, handler name, middleware chain. Flag auth-protected vs public routes.

**AI Use Case:** "Endpoint apa saja yang ada? Apa yang handle POST /users?"

```bash
# Semua routes
python3 "$CODELENS_DIR/scripts/codelens.py" api-map /path/to/workspace

# Filter method
python3 "$CODELENS_DIR/scripts/codelens.py" api-map /path/to/workspace --method POST

# Filter path
python3 "$CODELENS_DIR/scripts/codelens.py" api-map /path/to/workspace --path "/api/users"
```

### 31. `codelens_state-map` — Global State Tracking

Track state management: Redux, React Context, Zustand, MobX, Pinia, Vuex, Recoil, Jotai, XState, module-level state. Map reads/writes per state slice.

**AI Use Case:** "Komponen mana yang baca/tulis state ini?"

```bash
# Semua state
python3 "$CODELENS_DIR/scripts/codelens.py" state-map /path/to/workspace

# Store spesifik
python3 "$CODELENS_DIR/scripts/codelens.py" state-map /path/to/workspace --store userSlice
```

### 32. `codelens_env-check` — Environment Variable Audit

Audit env vars: mana yang referenced, required (no fallback), undocumented, missing dari .env.example. Cek naming inconsistencies dan secrets di .env files.

**AI Use Case:** "Env var apa yang harus diset sebelum deploy? Apa yang lupa di .env.example?"

```bash
# Full audit
python3 "$CODELENS_DIR/scripts/codelens.py" env-check /path/to/workspace

# Cek var spesifik
python3 "$CODELENS_DIR/scripts/codelens.py" env-check /path/to/workspace --var DATABASE_URL
```

---

## v4 P2: Debug Leak, Complexity

### 33. `codelens_debug-leak` — Debug Code Leak Detection

Deteksi kode debug yang tertinggal: console.log, print(), debugger, TODO/FIXME/HACK, commented-out code blocks, test skips, mock data, dev-only guards. Context-aware (skip console.error di catch blocks, downgrade findings di test files).

**AI Use Case:** "Apa yang harus dibersihkan sebelum production?"

```bash
# Semua kategori
python3 "$CODELENS_DIR/scripts/codelens.py" debug-leak /path/to/workspace

# Kategori spesifik
python3 "$CODELENS_DIR/scripts/codelens.py" debug-leak /path/to/workspace --category console_log
```

**Categories:** console_log, print_statement, debugger, todo_fixme, commented_code, test_skip, mock_data, dev_only

### 34. `codelens_complexity` — Complexity Scoring

Compute cyclomatic + cognitive complexity per function dengan angka presisi. Berbeda dari `smell` yang deteksi pattern secara kualitatif — tool ini memberi score numerik. Cyclomatic: 1-5 simple, 6-10 moderate, 11-20 complex, 21-50 very complex, 50+ untamable. Cognitive: SonarSource spec dengan nesting increment.

**AI Use Case:** "Function mana yang paling kompleks dan perlu di-refactor?"

```bash
# Full workspace
python3 "$CODELENS_DIR/scripts/codelens.py" complexity /path/to/workspace

# Function spesifik
python3 "$CODELENS_DIR/scripts/codelens.py" complexity /path/to/workspace --name processOrder

# Threshold filter
python3 "$CODELENS_DIR/scripts/codelens.py" complexity /path/to/workspace --threshold 20
```

---

## v4 P3: Regex Audit, A11y

### 35. `codelens_regex-audit` — Regex Pattern Auditing

Audit regex patterns: ReDoS-vulnerable patterns (nested quantifiers, overlapping alternatives), overly broad patterns, incorrect escaping, unsafe RegExp constructor (dynamic input), performance issues.

**AI Use Case:** "Ada regex yang bisa causing DoS? Pattern yang salah?"

```bash
# Full audit
python3 "$CODELENS_DIR/scripts/codelens.py" regex-audit /path/to/workspace

# Filter severity
python3 "$CODELENS_DIR/scripts/codelens.py" regex-audit /path/to/workspace --severity critical
```

**Categories:** redos_vulnerable, overly_broad, incorrect_escaping, unsafe_constructor, performance

### 36. `codelens_a11y` — Accessibility Auditing

Deteksi a11y issues: missing alt text, form labels, ARIA issues, keyboard navigation, semantic HTML, color contrast, heading order, vague link text, focus management. Mapped ke WCAG 2.1 criteria.

**AI Use Case:** "Apakah komponen ini accessible? Apa yang perlu diperbaiki?"

```bash
# Full audit
python3 "$CODELENS_DIR/scripts/codelens.py" a11y /path/to/workspace

# Kategori spesifik
python3 "$CODELENS_DIR/scripts/codelens.py" a11y /path/to/workspace --category missing_alt

# Filter severity
python3 "$CODELENS_DIR/scripts/codelens.py" a11y /path/to/workspace --severity critical
```

**Categories:** missing_alt, missing_label, aria_issues, keyboard_nav, semantic_html, color_contrast, heading_order, link_text, focus_management

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

### Security Auditing Flow (v3)

```
User: "Is this API endpoint secure?"
          │
          ▼
1. codelens dataflow workspace --source user_input
   → Find where user input flows
          │
          ▼
2. codelens dataflow workspace --sink db_query
   → Check if unsanitized data reaches SQL
          │
          ▼
3. codelens side-effect processOrder workspace
   → Check if function has network/IO side effects
          │
          ▼
4. codelens smell workspace --severity critical
   → Find critical code smells nearby
          │
          ▼
5. Report: "Security findings..."
```

### Pre-Refactoring Flow (v3)

```
User: "Rename verify_token to validate_token"
          │
          ▼
1. codelens refactor-safe verify_token workspace --action rename --new-name validate_token
   → Check for hidden risks
          │
          ├─ safety: dangerous → STOP. Report risks.
          ├─ safety: risky → Warning. List string refs.
          └─ safety: safe → Proceed with rename.
          │
          ▼
2. codelens impact verify_token workspace --action modify
   → Check how many files affected
          │
          ▼
3. codelens test-map workspace --function verify_token
   → Check if tested (update test names too)
          │
          ▼
4. Rename + codelens scan workspace --incremental
```

### Security Audit Flow (v4 — Enhanced)

```
User: "Is this codebase secure for production?"
          │
          ▼
1. codelens secrets workspace
   → Find hardcoded API keys, passwords, tokens
          │
          ▼
2. codelens dataflow workspace --source user_input --sink db_query
   → Check unsanitized data flow to SQL
          │
          ▼
3. codelens dataflow workspace --source user_input --sink html_output
   → Check XSS risk
          │
          ▼
4. codelens env-check workspace
   → Find required env vars without fallbacks
          │
          ▼
5. codelens regex-audit workspace --severity critical
   → Find ReDoS-vulnerable regex
          │
          ▼
6. codelens debug-leak workspace
   → Find leftover debug code for cleanup
          │
          ▼
7. Report: "Security findings..."
```

### Web App Understanding Flow (v4)

```
User: "I need to understand this web app"
          │
          ▼
1. codelens entrypoints workspace
   → "Where does this app start? What are the entry points?"
          │
          ▼
2. codelens api-map workspace
   → "What endpoints exist? Which handlers serve them?"
          │
          ▼
3. codelens state-map workspace
   → "What global state exists? Who reads/writes it?"
          │
          ▼
4. codelens outline workspace --all
   → "What's the file structure?"
          │
          ▼
5. codelens dependents <key-file> workspace --direction graph
   → "How do modules relate?"
```

### Quality Gate Flow (v4)

```
User: "Is this code ready for production?"
          │
          ▼
1. codelens smell workspace
   → Health score and smell categories
          │
          ▼
2. codelens complexity workspace --threshold 20
   → Find overly complex functions
          │
          ▼
3. codelens debug-leak workspace
   → Leftover debug code?
          │
          ▼
4. codelens dead-code workspace
   → Unused code to remove?
          │
          ▼
5. codelens a11y workspace
   → Accessibility issues?
          │
          ▼
6. codelens secrets workspace
   → Leaked credentials?
          │
          ▼
7. Report: "Quality gate pass/fail..."
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
