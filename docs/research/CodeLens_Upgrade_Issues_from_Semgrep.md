# CodeLens — Upgrade Issues (Serapan Fitur dari Semgrep)

> **Repo target:** `https://github.com/Wolfvin/CodeLens.git` (branch `main`, v8.1 per README / v7.2 per SKILL-QUICK — ada drift label antar file)
> **Repo referensi:** `https://github.com/semgrep/semgrep.git` (branch `develop`)
> **Tanggal analisa:** 2026-06-28
> **Tujuan:** menyediakan daftar issue siap-pakai untuk upgrade CodeLens berikutnya, dengan menyerap pola/arsitektur/fitur dari Semgrep yang sejalan dengan positioning CodeLens sebagai *AI-native code intelligence*.

---

## Daftar Isi

1. [Ringkasan Eksekutif](#1-ringkasan-eksekutif)
2. [Snapshot CodeLens — Fitur Saat Ini](#2-snapshot-codelens--fitur-saat-ini)
3. [Snapshot Semgrep — Fitur Referensi](#3-snapshot-semgrep--fitur-referensi)
4. [Gap Analysis — Apa yang Sudah vs Belum Diserap](#4-gap-analysis--apa-yang-sudah-vs-belum-diserap)
5. [Peningkatan yang Sudah Di-Adjust di CodeLens](#5-peningkatan-yang-sudah-di-adjust-di-codelens)
6. [Daftar Issue untuk Next Upgrade](#6-daftar-issue-untuk-next-upgrade)
7. [Roadmap & Prioritas](#7-roadmap--prioritas)
8. [Appendix — Peta File Semgrep ke Topik Issue](#8-appendix--peta-file-semgrep-ke-topik-issue)

---

## 1. Ringkasan Eksekutif

CodeLens dan Semgrep memiliki positioning yang **berbeda namun saling melengkapi**:

- **Semgrep** adalah *general-purpose static analysis platform* dengan rule language berbasis pattern matching, dukungan 30+ bahasa, ekosistem registry berisi 20.000+ rule, dan engine cross-file/interfile yang matang.
- **CodeLens** adalah *AI-native code intelligence* yang dioptimalkan untuk alur kerja AI agent (MCP, guard hooks, query-before-write, output `--format ai`) dengan fokus pada frontend breadth dan integrasi VS Code.

Dari analisa terhadap kedua repo, terdapat **22 issue kandidat** yang bisa diangkat untuk upgrade CodeLens berikutnya, dikelompokkan dalam 5 tema:

| Tema | Jumlah Issue | Prioritas dominan |
|------|:---:|:---:|
| A. Rule Language & Matching Engine | 6 | P0–P1 |
| B. Output, Format & LSP | 4 | P1 |
| C. CI/CD, Performance & Targeting | 4 | P1 |
| D. MCP, Hooks & AI Agent Surface | 4 | P0–P1 |
| E. SCA, Language Coverage & Registry | 4 | P1–P2 |

**Prinsip serapan:** *copy the pattern, not the implementation*. Semgrep ditulis dalam OCaml + Python; CodeLens ditulis dalam Python + tree-sitter. Sebagian besar issue di bawah berfokus pada penyerapan **konsep, struktur rule, dan UX CLI** — bukan porting kode.

---

## 2. Snapshot CodeLens — Fitur Saat Ini

### 2.1 Identitas Repo

| Atribut | Nilai |
|---|---|
| Nama | CodeLens |
| Tagline (README) | "AI-Native Code Intelligence" |
| Versi (README) | v8.1 |
| Versi (SKILL.md / SKILL-QUICK.md) | v7.2 *(drift label — perlu disinkronkan)* |
| Lisensi | MIT |
| Bahasa implementasi | Python 3.8+ |
| Parser engine | tree-sitter + regex fallback (28+ grammar) |
| Entry point | `python3 scripts/codelens.py <command>` |
| Jumlah file tracked | 288 |
| Jumlah CLI command | 56 (per README) / 45 (per SKILL-QUICK) — perlu disinkronkan |
| Jumlah MCP tool | 49 (per README) |
| Vendor target | AI agent / coding assistant |

### 2.2 Arsitektur (Ringkas)

```
CodeLens/
├── scripts/
│   ├── codelens.py              # CLI entry point (56 commands)
│   ├── mcp_server.py            # MCP server (stdio + HTTP/SSE), 49 tools
│   ├── registry.py              # Registry read/write/build
│   ├── plugin_system.py         # 4 plugin types, 3-tier discovery
│   ├── pre_commit_hook.py       # Pre-commit integration
│   ├── lsp_client.py            # LSP client (bukan server)
│   ├── osv_client.py            # OSV.dev API client untuk CVE
│   ├── grammar_loader.py        # Lazy tree-sitter loader
│   ├── framework_detect.py      # Auto-detect React/Vue/Svelte/Tailwind/...
│   ├── incremental.py           # Incremental scan
│   ├── edge_resolver.py         # Cross-file edge resolution
│   ├── autofix_engine.py        # Autofix engine
│   ├── ast_taint_engine.py      # AST taint analysis (3755 LOC)
│   ├── crossfile_taint_engine.py
│   ├── dataflow_engine.py
│   ├── secrets_engine.py        # 1575 LOC
│   ├── vulnscan_engine.py       # 2103 LOC
│   ├── smell_engine.py / complexity_engine.py / deadcode_engine.py
│   ├── ... (40+ engine files)
│   ├── commands/                # 56 command modules
│   ├── formatters/              # sarif.py + markdown.py (2 formatter)
│   ├── parsers/                 # 9 tree-sitter parser + 20+ fallback
│   ├── plugins/
│   │   ├── owasp_top10/         # 36 rules (907-line YAML)
│   │   └── compliance/          # 53 rules (HIPAA + PCI-DSS)
│   └── rules/
│       ├── javascript_security.yaml
│       └── python_security.yaml
├── vscode-codelens/             # VS Code extension
├── benchmarks/                  # clean_app + vulnerable_app fixtures
├── tests/                       # 25+ test files
├── .github/workflows/           # CI, benchmark, quality gate, SARIF
└── references/                  # parser-rules, query-examples, status-codes, changelog, agent-integration
```

### 2.3 Kategori Fitur Saat Ini

#### A. Core Commands (P0)
`init`, `scan [--incremental] [--max-files N]`, `query "name"`, `list`, `detect`, `watch`, `validate`

#### B. Search & Understanding (P1)
`search`, `symbols`, `trace`, `impact`, `context`, `outline`, `missing-refs`, `dependents`, `ask`

#### C. Quality & Security (P0–P1)
`secrets`, `vuln-scan`, `dataflow`, `env-check`, `smell`, `complexity`, `dead-code`, `debug-leak`

#### D. Architecture (P1)
`entrypoints`, `api-map`, `state-map`, `diff`, `circular`

#### E. Refactoring & Advanced (P2–P3)
`refactor-safe`, `side-effect`, `stack-trace`, `test-map`, `config-drift`, `type-infer`, `ownership`, `regex-audit`, `a11y`, `perf-hint`, `css-deep`, `taint`, `fix`, `guard`, `binary-scan`, `artifact-scan`

#### F. Utility & AI Surface
`serve` (MCP server), `summary`, `handbook`, `history`, `plugin`, `lsp-status`, `migrate`, `benchmark`, `check`, `self-analyze`, `dashboard`

#### G. AI-Optimized Output
- `--lite` (per-command minimal output)
- `--format ai` (normalized `{stats, items[], truncated, recommendations}`)
- `--top N` dengan smart default 20
- `--max-tokens N` auto-truncate
- `CODELENS_AI_MODE=1` env var
- Auto-setup (init + scan) capped 3000 file

#### H. Plugin System (4 tipe)
`rule_pack`, `engine`, `formatter`, `command` — dengan 3-tier discovery (`.codelens/plugins/` > `~/.codelens/plugins/` > `scripts/plugins/`). Ada konstanta `REGISTRY_INDEX_URL = "https://registry.codelens.dev/api/v1/plugins"` tapi **marketplace belum aktif**.

#### I. MCP Server
- Transport: **stdio** (default) + **HTTP/SSE** opsional (`--port 8080`)
- Implementasi: hand-rolled JSON-RPC 2.0 di atas `http.server` stdlib (bukan FastMCP SDK)
- Tools: 49 (mapping 1:1 dari CLI commands ke `codelens_<cmd>` tool)
- Tidak ada MCP hooks, tidak ada MCP prompts/skills

#### J. Output Formatter (hanya 2)
`sarif` (SARIF v2.1.0) dan `markdown`. Tidak ada `junit_xml`, `emacs`, `vim`, `gitlab_sast`, `gitlab_secrets`.

#### K. CI/CD Integration
- GitHub Actions: `codelens-ci.yml`, `codelens-sarif.yml`, `codelens-quality-gate.yml`, `codelens-benchmark.yml`
- GitLab CI: `.gitlab-ci.yml`
- Pre-commit hook: `pre_commit_hook.py`
- **Tidak ada** baseline/diff scan mode, **tidak ada** `nosemgrep`-style inline suppression

#### L. Language & Framework Coverage
- **Tree-sitter (full):** HTML, CSS, JS, TS/TSX, Rust, Python, Vue, Svelte, SCSS
- **Regex fallback:** C, C++, C#, Java, Kotlin, Swift, Scala, Ruby, PHP, Go, Dart, Elixir, Lua, Haskell, Nim, R, ObjC, Vim, Zig, GDScript, Shell, Blade, Python (fallback), HTML/CSS/JS backend/frontend (fallback)
- **Framework auto-detect:** React/Next.js, Vue/Nuxt, Svelte/SvelteKit, Tailwind, Express, Fastify, Koa, Hono, Django, Flask, FastAPI

### 2.4 Known Gaps di CodeLens (per README "Honest Competitive Positioning")

| Dimensi | Skor CodeLens | Skor Semgrep | Gap |
|---|:---:|:---:|:---:|
| Plugin/Rule Ecosystem | 2 | **8** | Besar |
| CI/CD & SARIF | 5 | 8 | Sedang |
| Taint Analysis Depth | 5 | 7 | Sedang |
| IDE Integration | 4 | **9** | Besar |
| Community & Maturity | 1 | 7 | Sangat Besar |
| Cross-File Analysis | 6 | 7 | Kecil |
| Live CVE Scanning | 7 | 8 | Kecil |

CodeLens sendiri mengakui kekuatannya ada di **AI Agent Integration (8), Frontend Breadth (8), MCP/AI-Native Design (9)** — itulah ceruk yang harus dipertahankan sambil menyerap kekuatan Semgrep di ekosistem rule, CI/CD, dan IDE.

---

## 3. Snapshot Semgrep — Fitur Referensi

### 3.1 Identitas Repo

| Atribut | Nilai |
|---|---|
| Nama | Semgrep |
| Tagline | "Code scanning at ludicrous speed" |
| Versi | lihat CHANGELOG.md (file 420 KB, rilis mingguan) |
| Lisensi | LGPL-2.1 |
| Bahasa implementasi | OCaml (engine core) + Python (CLI) + Rust (osemgrep experimental) |
| Parser engine | tree-sitter + pfff (legacy) + aliengrep (generic) |
| Entry point | `semgrep <subcommand>` (default: `scan`) |
| Jumlah subcommand CLI | 10 (`scan`, `ci`, `login`, `logout`, `lsp`, `mcp`, `publish`, `show`, `test`, `validate`, `install-semgrep-pro`) |
| Jumlah MCP tool | 9 (lebih sedikit dari CodeLens, tapi lebih fokus) |
| Jumlah formatter | 8 (text, json, sarif, gitlab_sast, gitlab_secrets, emacs, vim, junit_xml) |
| Bahasa didukung | 40+ (Apex, Bash, C, C++, C#, Clojure, Dart, Dockerfile, Elixir, Go, Hack, HTML, Java, JS, JSON, Jsonnet, Julia, Kotlin, Lisp, Lua, OCaml, PHP, PowerShell, PromQL, Protobuf, Python, QL, R, Ruby, Rust, Scala, Scheme, Solidity, Swift, Terraform, TS, Vue, XML, YAML, Cairo, Circom, Gosu, Move, FGA) |
| Package manager SCA | 15 (NuGet, Pub, go mod, Gradle, Maven, npm, Yarn 1/2/3, pnpm, Composer, pip, Pipenv, Poetry, RubyGems, Cargo, SwiftPM) |
| Rule registry | 20.000+ rule (community + Pro) |

### 3.2 Arsitektur (Ringkas)

```
semgrep/
├── src/                           # OCaml engine (parsing + matching + taint)
│   ├── ast_generic/               # Generic AST (universal IR untuk semua bahasa)
│   ├── parsing/                   # Parse_rule.ml, Parse_target.ml, Parse_pattern.ml
│   ├── matching/                  # Match_patterns.ml, Matching_generic.ml
│   ├── tainting/                  # Xtaint.ml, Taint.ml, OSS_dataflow_tainting.ml
│   ├── analyzing/                 # CFG_build, Constant_propagation, Dataflow_*
│   ├── naming/                    # Name resolution
│   ├── typing/                    # Type inference untuk metavariable-type
│   ├── engine/                    # Match_rules.ml, Match_taint_spec.ml, ReDoS, Entropy
│   ├── fixing/                    # Autofix.ml, Autofix_metavar_replacement.ml
│   ├── targeting/                 # File filtering & glob matching
│   ├── metachecking/              # Rule validation (Check_rule.ml)
│   ├── prefiltering/              # Regex pre-match sebelum AST matching
│   ├── core_scan/                 # Parallel target scanning (Parmap_targets)
│   ├── sca/                       # Dependency, Lockfile, Manifest, Sbom
│   ├── rule/                      # Rule.ml, Pattern.ml, SCA_pattern.ml
│   ├── il/                        # Intermediate Language (CFG-based)
│   ├── osemgrep/                  # Next-gen CLI (OCaml, menggantikan pysemgrep perlahan)
│   │   ├── cli_scan/              # Scan_CLI.ml (81 Term.t option flags!)
│   │   ├── cli_ci/                # Ci_subcommand, Ci_CLI, Git_metadata
│   │   ├── cli_lsp/               # Lsp_subcommand, Lsp_CLI
│   │   ├── cli_mcp/               # Mcp_subcommand
│   │   ├── cli_test/              # Test_subcommand (rule testing)
│   │   ├── cli_validate/          # Validate_subcommand
│   │   ├── cli_login/             # Login (oauth)
│   │   └── cli_install_semgrep_pro/
│   ├── lsp_legacy/                # LSP server lama (Legacy_language_server.ml)
│   └── spacegrep/                 # Generic pattern matcher (untuk bahasa tanpa grammar)
├── cli/src/semgrep/               # Python CLI (legacy "pysemgrep", fallback)
│   ├── commands/                  # scan.py, ci.py, login.py, mcp.py, install.py, publish.py
│   ├── formatter/                 # 8 formatter
│   ├── mcp/                       # MCP server (FastMCP-based, hooks, prompts)
│   │   ├── server.py              # 9 tools + register/deregister pattern
│   │   ├── semgrep.py
│   │   ├── hooks/                 # post_tool, supply_chain, inject_secure_defaults, stop, settings
│   │   └── utilities/
│   ├── app/                       # auth, scans, session, project_config, version
│   ├── semdep/                    # SCA parser 15 package manager
│   │   └── parsers/               # cargo, composer, gem, go_mod, gradle, mix, packages_lock_c_sharp, pipfile, pnpm, poetry, pom_tree, pubspec_lock, requirements, swiftpm, yarn
│   ├── external/                  # git_url_parser, pymmh3
│   ├── rule.py, rule_lang.py, rule_match.py
│   ├── config_resolver.py         # URL/registry/local config resolution
│   ├── target_manager.py
│   ├── output.py + formatter/
│   ├── autofix.py
│   ├── git.py                     # Git integration (baseline, diff, blame)
│   ├── nosemgrep.py               # Inline suppression (`# nosemgrep`)
│   ├── metrics.py + telemetry.py  # Privacy-aware metrics
│   ├── profile_manager.py         # Rule profile management
│   ├── dependency_aware_rule.py   # Rule hanya fire kalau dep ada
│   ├── join_rule.py               # Cross-file join via secondary files
│   └── resolve_subprojects.py
├── tests/                         # e2e, unit, performance, consistency
├── changelog.d/                   # Scriv fragments (changelog management)
└── .github/ + Dockerfile + Makefile + flake.nix + semgrep.opam
```

### 3.3 Fitur Unggulan Semgrep yang Relevan untuk Diserap

#### A. Rule Language (Paling Berbeda dengan CodeLens)

Semgrep rule adalah YAML yang berisi **pattern** dengan **metavariable** (`$X`, `$FN`, `...`). Contoh:

```yaml
rules:
  - id: arg-reassign
    pattern-either:
      - pattern: $X = 1
      - pattern: $X = 2
    message: "$X is being assigned to one or two"
    languages: [python]
    severity: WARNING
```

Kombinator pattern yang didukung (dari `src/parsing/Parse_rule_formula.ml`):

| Key | Fungsi |
|---|---|
| `pattern` | Match satu pattern |
| `patterns` | Daftar pattern (semua harus match, urutan) |
| `pattern-either` | OR — salah satu match |
| `pattern-inside` | Match hanya jika berada **di dalam** match pattern lain |
| `pattern-not-inside` | Negasi `pattern-inside` |
| `pattern-not` | Negasi `pattern` |
| `pattern-regex` | Match dengan regex (bukan AST) |
| `pattern-not-regex` | Negasi regex |
| `pattern-where-python` | Custom Python predicate (Pro only) |

Kombinator taint (dari `src/parsing/Parse_rule.ml`):

| Key | Fungsi |
|---|---|
| `pattern-sources` | Daftar sumber taint |
| `pattern-sinks` | Daftar sink taint |
| `pattern-sanitizers` | Daftar sanitizer |
| `pattern-propagators` | Propagasi taint dengan label (`from`, `to`, `label`, `requires`, `replace-labels`) |
| `propagators` | Bentuk baru (semgrep `taint:` mode) |
| `sources` / `sinks` / `sanitizers` | Sintaks baru taint mode |

Constraint metavariable (dari `src/parsing/Parse_rule_formula.ml`):

| Key | Fungsi |
|---|---|
| `focus-metavariable` | Highlight lokasi spesifik di hasil match |
| `metavariable-regex` | Filter metavariable dengan regex |
| `metavariable-pattern` | Sub-pattern pada metavariable |
| `metavariable-comparison` | Perbandingan numerik/komparasi |
| `metavariable-type` | Filter berdasarkan tipe (Pro) |

#### B. Taint Engine (Xtaint)

- File: `src/tainting/Xtaint.ml`, `Taint.ml`, `OSS_dataflow_tainting.ml`
- **Propagator dengan label & requires** — fitur lanjutan yang lebih ekspresif dari sekadar sources/sinks/sanitizers
- Taint trace dengan label multiset (label bisa `A`, `B`, `[C, D]`)
- `replace-labels` memungkinkan transformasi label di tengah propagasi
- Coverage stats per-file (`Taint_coverage_stats.ml`)

#### C. Output Formatters (8 total)

| Formatter | Use case |
|---|---|
| `text` | Default terminal output |
| `json` | Machine-readable |
| `sarif` | SARIF v2.1.0 untuk GitHub Code Scanning |
| `gitlab_sast` | GitLab SAST report JSON |
| `gitlab_secrets` | GitLab Secrets Detection report |
| `junit_xml` | CI integration (Jenkins, GitLab CI) |
| `emacs` | Flycheck-compatible |
| `vim` | ALE-compatible / quickfix |

#### D. LSP Server

- File: `src/osemgrep/cli_lsp/Lsp_CLI.ml`, `Lsp_subcommand.ml`, `src/lsp_legacy/`
- Perintah `semgrep lsp` menjalankan server LSP native
- Didukung di VS Code, Neovim, dll.
- Custom commands & notifications untuk integrasi yang lebih dalam

#### E. MCP Server dengan Hooks & Prompts

File: `cli/src/semgrep/mcp/`

- 9 tool fokus: `semgrep_scan`, `semgrep_scan_remote`, `semgrep_scan_with_custom_rule`, `semgrep_findings`, `semgrep_scan_supply_chain`, `get_abstract_syntax_tree`, `get_supported_languages`, `semgrep_rule_schema`, `semgrep_whoami`
- **Hooks** (auto-trigger): `post_tool`, `supply_chain`, `inject_secure_defaults`, `stop`, `settings`
- **Prompts/Skills**: `write_custom_semgrep_rule` — bantu AI menulis rule baru
- **Dua transport**: `stdio` + `streamable-http` (port 8000 default)
- Integrasi dengan Claude Code plugin marketplace dan Cursor marketplace

#### F. CI Mode & Diff Scan

- `semgrep ci` subcommand dedicated untuk CI/CD
- `--baseline-commit` — hanya laporkan finding yang muncul setelah commit tertentu
- `--diff-scan` — scan hanya file yang berubah (file: `src/osemgrep/cli_scan/Diff_scan.ml`)
- Git metadata tracking (author, commit, PR info)
- Auto-detect CI provider (GitHub Actions, GitLab CI, CircleCI, dll.)

#### G. Inline Suppression

- `# nosemgrep` — skip finding di baris tertentu
- `# nosemgrep: rule-id-1, rule-id-2` — skip dengan rule ID eksplisit
- File: `cli/src/semgrep/nosemgrep.py`
- Bekerja sama dengan `--disable-nosem` untuk enforce stricter policy

#### H. Prefiltering Performance

- File: `src/prefiltering/Analyze_pattern.ml`, `Analyze_rule.ml`
- Sebelum AST matching, lakukan regex pre-match pada source code
- Skip file yang tidak mungkin match → speedup 5-10x pada repo besar
- Mengkombinasikan regex dari multi-rule menjadi satu alternation

#### I. Rule Metachecking & Validation

- File: `src/metachecking/Check_rule.ml`, `cli/src/semgrep/commands/scan.py` (`o_strict`, `o_validate`)
- `semgrep validate` — validasi syntax rule sebelum run
- `--strict` — exit non-zero jika ada warning
- Error reporting yang detail dengan lokasi tepat di YAML

#### J. Rule Test Framework

- `semgrep test` — jalankan rule terhadap fixture dengan expected result
- File: `src/osemgrep/cli_test/Test_subcommand.ml`
- Skema: setiap rule punya `ruleid/tests/` dengan file `.test.yaml` berisi input + expected findings
- Memudahkan contributor menulis rule baru dengan regression protection

#### K. Config Resolver & Registry

- File: `cli/src/semgrep/config_resolver.py`
- Menerima: URL, local path, registry ID (`p/ci`, `p/owasp-top-10`), `auto`
- Cache rule hasil download di `~/.semgrep/`
- Verifikasi checksum/signature untuk rule dari registry
- Pull secret/Pro rules dengan token auth

#### L. Dependency-Aware Rules

- File: `cli/src/semgrep/dependency_aware_rule.py`
- Rule bisa declare `metadata.dependencies` — hanya fire jika dependency terbukti ada di lockfile
- Mengurangi false positive dramatis (e.g., rule "insecure-pickle" hanya fire jika `pickle` benar-benar dipakai)

#### M. Join Rule (Cross-File)

- File: `cli/src/semgrep/join_rule.py`
- Rule bisa baca secondary files untuk konteks tambahan
- Memungkinkan: "rule A fire hanya jika rule B juga match di file lain"
- Lebih ringan dari full interfile analysis

#### N. SCA (Supply Chain Analysis)

- 15 parser package manager (lihat daftar di atas)
- Reachability analysis: apakah vulnerable function benar-benar dipanggil?
- Lockfile + manifest parsing
- SBOM generation (`src/sca/Sbom.ml`)
- Ekosystem-aware version comparison (`semver_specifier.py`)

#### O. Telemetry dengan Privacy Controls

- File: `cli/src/semgrep/metrics.py`, `telemetry.py`
- Default: pseudonymous, opt-out dengan `--metrics=off`
- Hanya kategori data yang tidak sensitif (rule ID, language, file count)
- Transparansi: `metrics.md` (38 KB) dokumentasi lengkap

#### P. Profile Manager

- File: `cli/src/semgrep/profile_manager.py`
- Simpan konfigurasi rule sebagai "profile"
- Switch antar profile (e.g., `security-audit`, `code-review`, `ci-strict`)
- Share profile antar tim via file YAML

#### Q. Disk Cache & Parallel Scanning

- File: `src/core_scan/Disk_cache.ml`, `Parmap_targets.ml`, `Concurrent_map_targets.ml`
- Cache AST parse result di disk → next scan 10x lebih cepat
- Parallel scanning dengan parmap (job pool berbasis process)
- `--num-jobs`, `--max-memory_mb`, `--x-mem-policy` untuk kontrol resource

#### R. Aliengrep (Generic Pattern Matching)

- File: `src/aliengrep/`
- Untuk bahasa tanpa grammar formal (config, ERB, Jinja, template)
- Pattern matching berbasis token + struktur longgar
- Memungkinkan rule Dockerfile, Terraform, YAML, ERB, Jinja

#### S. ReDoS Detection

- File: `src/engine/ReDoS.ml`
- Deteksi regex dengan catastrophic backtracking
- CodeLens punya `regexaudit_engine.py` tapi hanya di level "suspicious pattern", bukan analisis automata

---

## 4. Gap Analysis — Apa yang Sudah vs Belum Diserap

Tabel ini membandingkan **apa yang sudah diimplementasikan di CodeLens** vs **apa yang ada di Semgrep** untuk setiap topik. Kolom "Status" menandai apakah serapan diperlukan.

| # | Topik | CodeLens | Semgrep | Status |
|---|---|---|---|---|
| 1 | Pattern-based rule language | ❌ Hanya daftar sources/sinks | ✅ `pattern`, `pattern-either`, `pattern-inside`, dst. | **Perlu serap** |
| 2 | Metavariable matching | ❌ Tidak ada | ✅ `$X`, `$FN`, `...`, dengan constraint | **Perlu serap** |
| 3 | Metavariable constraint | ❌ Tidak ada | ✅ `metavariable-regex`, `-pattern`, `-comparison`, `-type` | **Perlu serap** |
| 4 | Pattern-where-python | ❌ Tidak ada | ✅ Custom Python predicate | **Perlu serap** |
| 5 | Taint propagator (label + requires) | ⚠️ Punya sources/sinks/sanitizer saja | ✅ Propagator dengan label multiset | **Perlu serap** |
| 6 | Output formatter | ⚠️ 2 (sarif, markdown) | ✅ 8 (text, json, sarif, gitlab_sast, gitlab_secrets, junit_xml, emacs, vim) | **Perlu serap** |
| 7 | LSP server | ❌ Hanya `lsp_client.py` (klien) | ✅ Native LSP server | **Perlu serap** |
| 8 | LSP custom commands | ❌ Tidak ada | ✅ `src/lsp_legacy/custom_commands/` | **Perlu serap** |
| 9 | Pre-filtering optimization | ❌ Tidak ada | ✅ `src/prefiltering/` | **Perlu serap** |
| 10 | Baseline / diff scan | ⚠️ Ada `diff` command tapi bukan CI baseline | ✅ `--baseline-commit`, `--diff-scan` | **Perlu serap** |
| 11 | Inline suppression (`nosemgrep`) | ❌ Tidak ada | ✅ `# nosemgrep` + `--disable-nosem` | **Perlu serap** |
| 12 | Strict mode | ⚠️ Tidak eksplisit | ✅ `--strict` exit non-zero on warning | **Perlu serap** |
| 13 | Rule metachecking | ❌ Tidak ada | ✅ `src/metachecking/` + `semgrep validate` | **Perlu serap** |
| 14 | Rule test framework | ⚠️ Benchmarks ada, tapi bukan rule-level | ✅ `semgrep test` + `.test.yaml` | **Perlu serap** |
| 15 | MCP hooks (post_tool, dll.) | ❌ Tidak ada | ✅ 5 hook type | **Perlu serap** |
| 16 | MCP prompts/skills | ❌ Tidak ada | ✅ `write_custom_semgrep_rule` | **Perlu serap** |
| 17 | MCP transport streamable-http | ⚠️ HTTP/SSE ada (basic) | ✅ FastMCP streamable-http | **Perlu upgrade** |
| 18 | MCP tool: `get_abstract_syntax_tree` | ❌ Tidak ada | ✅ Ekspos AST ke AI agent | **Perlu serap** |
| 19 | MCP tool: `scan_with_custom_rule` | ❌ Tidak ada | ✅ Live rule testing via MCP | **Perlu serap** |
| 20 | SCA package manager | ⚠️ 7 (npm, yarn, pnpm, bun, cargo, pip, go) | ✅ 15 | **Perlu serap** |
| 21 | Language coverage (tree-sitter full) | ⚠️ 9 bahasa | ✅ 40+ bahasa | **Perlu serap bertahap** |
| 22 | Historical secrets scan | ❌ Tidak ada | ✅ `--historical-secrets` (scan git history) | **Perlu serap** |
| 23 | Config resolver (URL/registry/local) | ⚠️ Konstan `REGISTRY_INDEX_URL` tapi belum aktif | ✅ Matang | **Perlu serap** |
| 24 | Dependency-aware rules | ❌ Tidak ada | ✅ `metadata.dependencies` | **Perlu serap** |
| 25 | Join rule (cross-file) | ⚠️ `crossfile_taint_engine.py` ada | ✅ `join_rule.py` general-purpose | **Pertahankan + belajar pola** |
| 26 | Autofix metavariable replacement | ⚠️ `autofix_engine.py` ada, perlu audit | ✅ `Autofix_metavar_replacement.ml` | **Audit & upgrade** |
| 27 | Disk cache AST parse | ❌ Registry ada tapi parse result tidak di-cache | ✅ `Disk_cache.ml` | **Perlu serap** |
| 28 | Parallel scanning (process pool) | ⚠️ Incremental ada, parmap tidak | ✅ `Parmap_targets.ml` | **Perlu serap** |
| 29 | Aliengrep (generic matcher) | ⚠️ Regex fallback ada | ✅ Token-based generic matcher | **Pertahankan regex fallback, evaluate upgrade** |
| 30 | ReDoS detection | ⚠️ `regexaudit_engine.py` pattern-based | ✅ Automata-based `ReDoS.ml` | **Audit depth** |
| 31 | Telemetry | ❌ Tidak ada | ✅ Opt-in pseudonymous | **Pertimbangkan (privacy-first)** |
| 32 | Profile manager | ❌ Tidak ada | ✅ `profile_manager.py` | **Perlu serap** |
| 33 | Changelog management (scriv) | ⚠️ CHANGELOG.md manual | ✅ `changelog.d/` fragment-based | **Pertimbangkan** |

**Catatan:** CodeLens sudah unggul di area MCP tool count (49 vs 9), AI-optimized output (`--lite`, `--format ai`), frontend breadth, dan zero-config auto-setup — area ini **tidak perlu** diserap dari Semgrep, justru bisa menjadi pembeda.

---

## 5. Peningkatan yang Sudah Di-Adjust di CodeLens

Sebelum masuk ke daftar issue baru, ini adalah **peningkatan yang SUDAH ada di CodeLens** dan tidak perlu diimplementasikan ulang. Pemilik repo perlu memastikan konsistensi internal antara dokumentasi dan kode.

### 5.1 AI-Native Surface (Kekuatan CodeLens, Pertahankan)

| Peningkatan | Bukti Implementasi | Catatan |
|---|---|---|
| MCP server dengan 49 tool | `scripts/mcp_server.py` (1933 LOC) | 1:1 mapping CLI → MCP tool |
| `--format ai` normalized schema | `scripts/codelens.py`, `SKILL-QUICK.md` | `{stats, items[], truncated, recommendations}` |
| `--lite` per-command | 10+ command punya lite mode | Lihat tabel di SKILL-QUICK.md |
| `--top N` smart default 20 | Semua list command | Sort-aware (severity/complexity) |
| `--max-tokens N` | Semua command | Auto-truncate list terbesar |
| Auto-setup (init + scan) | Zero-config | Cap 3000 file |
| `CODELENS_AI_MODE=1` | Env var | `--format ai` jadi default |
| Workspace auto-detect | 4-strategy: cwd → parent → cache → fallback | Lihat SKILL.md |
| Guard hooks (`--pre`/`--post`) | `commands/guard.py` | Pre-write safety check |

### 5.2 Plugin & Rule System (Fondasi Ada, Perlu Dipertajam)

| Peningkatan | Bukti | Catatan |
|---|---|---|
| 4 plugin type | `scripts/plugin_system.py` (1462 LOC) | `rule_pack`, `engine`, `formatter`, `command` |
| 3-tier discovery | Local > User > Built-in | Priority map 30/20/10 |
| Plugin manifest | `plugin.yaml` | Required fields: `name`, `version`, `type`, `description` |
| OWASP Top 10 rules | `scripts/plugins/owasp_top10/rules/owasp_top10.yaml` (907 LOC, 36 rule) | A01–A10 lengkap |
| Compliance rules | `scripts/plugins/compliance/rules/hipaa.yaml`, `pci_dss.yaml` (53 rule) | HIPAA + PCI-DSS |
| Built-in security rule | `scripts/rules/python_security.yaml` (199 LOC), `javascript_security.yaml` | Source/sink/sanitizer list |

### 5.3 Engine Matang (40+ engine, tidak perlu rewrite)

`a11y_engine.py`, `apimap_engine.py`, `ast_taint_engine.py` (3755 LOC), `autofix_engine.py`, `base_engine.py`, `callgraph_engine.py`, `circular_engine.py`, `complexity_engine.py`, `configdrift_engine.py`, `context_engine.py`, `convention_engine.py`, `crossfile_taint_engine.py`, `cssdeep_engine.py`, `dashboard_engine.py`, `dataflow_engine.py`, `deadcode_engine.py`, `debugleak_engine.py`, `dependents_engine.py`, `diff_engine.py`, `edge_resolver.py`, `entrypoints_engine.py`, `envcheck_engine.py`, `history_engine.py`, `hybrid_engine.py`, `impact_engine.py`, `missing_refs.py`, `outline_engine.py`, `ownership_engine.py`, `perfhint_engine.py`, `regexaudit_engine.py`, `search_engine.py`, `secrets_engine.py` (1575 LOC), `semantic_engine.py`, `sideeffect_engine.py`, `smell_engine.py`, `stacktrace_engine.py`, `statemap_engine.py`, `testmap_engine.py`, `trace_engine.py`, `typeinfer_engine.py`, `validate_engine.py`, `vulnscan_engine.py` (2103 LOC).

### 5.4 Parser Coverage (9 tree-sitter + 20+ fallback)

Tree-sitter: HTML, CSS, JS frontend, JS backend, Rust, TS backend, TSX, Vue, Svelte, Python, Blade, Tailwind detector.
Regex fallback: C, C++, C#, Java, Kotlin, Swift, Scala, Ruby, PHP, Go, Dart, Elixir, Lua, Haskell, Nim, R, ObjC, Vim, Zig, GDScript, Shell.

### 5.5 CI/CD & Distribution

- GitHub Actions: `codelens-ci.yml`, `codelens-sarif.yml`, `codelens-quality-gate.yml`, `codelens-benchmark.yml`
- GitLab CI: `.gitlab-ci.yml`
- VS Code extension: `vscode-codelens/` (Diagnostics Provider, Code Actions, Guard hooks, Health status bar)
- Pre-commit hook: `scripts/pre_commit_hook.py`
- Benchmark harness: `benchmarks/check_regression.py`, `benchmarks/run_benchmarks.py` dengan fixture `clean_app` dan `vulnerable_app`

### 5.6 Documentation Hierarchy

`README.md` → `SKILL.md` → `SKILL-QUICK.md` → `references/{agent-integration.md, parser-rules.md, query-examples.md, status-codes.md, changelog.md}` — sudah cukup lengkap dan AI-friendly.

---

## 6. Daftar Issue untuk Next Upgrade

Setiap issue di bawah ditulis dalam format yang siap dipakai sebagai **GitHub issue body**. Tinggal copy-paste ke `https://github.com/Wolfvin/CodeLens/issues/new`.

> Konvensi label: `priority:P0` (blocker), `priority:P1` (next release), `priority:P2` (backlog), `topic:rule-engine`, `topic:mcp`, `topic:ci-cd`, `topic:lsp`, `topic:sca`, `topic:performance`, `topic:output`, `topic:lang-coverage`.

---

### Issue #CL-001 — Pattern-Based Rule Language (Phase 1: Core Matcher)

**Priority:** P0
**Topic:** rule-engine
**Estimasi:** 3-5 minggu
**Referensi Semgrep:** `src/parsing/Parse_rule_formula.ml`, `src/matching/Match_patterns.ml`, `src/matching/Matching_generic.ml`, `src/rule/Pattern.ml`

#### Motivasi

Rule CodeLens saat ini hanya berupa daftar `sources` / `sinks` / `sanitizers` (lihat `scripts/rules/python_security.yaml`). Ini tidak bisa mengekspresikan pola seperti:

- "Function `$FN` yang menerima `$INPUT` dan mengirim ke `eval($INPUT)`"
- "Assignment `$X = $X` (self-assignment, bug)"
- "`if ($COND) return $X; $X = $Y;` (dead code setelah return)"

Pattern matching berbasis metavariable adalah **fondasi** dari semua rule tool yang matang (Semgrep, CodeQL, ASTgrep). Tanpa ini, ekosistem rule CodeLens tidak bisa berkembang.

#### Acceptance Criteria

- [ ] Bisa menulis rule YAML dengan key `pattern`, `patterns`, `pattern-either`, `pattern-inside`, `pattern-not`, `pattern-not-inside`, `pattern-regex`, `pattern-not-regex`
- [ ] Metavariable `$X`, `$FN`, `$ARG` match identifier/literal/expr secara generik
- [ ] Ellipsis `...` match zero-or-more args/stmts/args
- [ ] Engine bisa dijalankan untuk Python, JS, TS (3 bahasa awal)
- [ ] Backward compatible dengan rule `sources/sinks/sanitizers` lama (auto-translate ke `pattern-sources`/`pattern-sinks`/`pattern-sanitizers`)
- [ ] Benchmark: scan 1000 file dalam <10 detik untuk 100 rule pattern
- [ ] Dokumentasi: `references/rule-syntax.md` dengan 20+ contoh

#### Langkah Implementasi

1. Tulis `scripts/rule_pattern_parser.py` — parser YAML untuk pattern + metavariable
2. Tulis `scripts/rule_matcher.py` — matching engine berbasis tree-sitter AST + metavariable binding
3. Refactor `scripts/ast_taint_engine.py` agar bisa konsumsi rule baru
4. Auto-translator: konversi `scripts/rules/*.yaml` lama → format baru
5. Tambah CLI command: `codelens rule-check --rules <path> --target <path>`
6. Test fixtures di `tests/fixtures/rule_patterns/`

#### Dependency

- Blocked by: tidak ada
- Blocks: #CL-002 (metavariable constraint), #CL-003 (taint propagator), #CL-014 (rule test framework), #CL-019 (MCP scan-with-custom-rule)

---

### Issue #CL-002 — Metavariable Constraints (`metavariable-regex`, `-pattern`, `-comparison`)

**Priority:** P1
**Topic:** rule-engine
**Estimasi:** 1-2 minggu
**Referensi Semgrep:** `src/parsing/Parse_rule_formula.ml` (key `focus-metavariable`, `metavariable-regex`, `metavariable-pattern`, `metavariable-comparison`, `metavariable-type`)

#### Motivasi

Setelah pattern matching dasar (Issue #CL-001), diperlukan kemampuan memfilter match berdasarkan:

- **Regex**: `$URL` harus match `^https?://` (eliminasi false positive)
- **Sub-pattern**: `$FN` harus match pattern `eval\(...\)` (nested matching)
- **Comparison**: `$N > 1000` (numerik threshold)
- **Focus**: highlight baris spesifik saat metavariable muncul di multi-baris

#### Acceptance Criteria

- [ ] Empat key baru didukung: `metavariable-regex`, `metavariable-pattern`, `metavariable-comparison`, `focus-metavariable`
- [ ] `metavariable-regex: { $X: "^https?://" }` memfilter match yang `$X` tidak match regex
- [ ] `metavariable-pattern: { $X: eval(...) }` memfilter match yang `$X` tidak match sub-pattern
- [ ] `metavariable-comparison: { $N: "> 1000" }` mendukung `>`, `<`, `>=`, `<=`, `==`, `!=` pada literal numeric
- [ ] `focus-metavariable: $X` mengubah `start_line`/`end_line` match ke posisi metavariable
- [ ] Bisa dikombinasikan dalam `patterns: [...]`

#### Langkah Implementasi

1. Extend `scripts/rule_pattern_parser.py` untuk parse 4 key baru
2. Tambah evaluator di `scripts/rule_matcher.py`
3. Untuk `metavariable-comparison`, gunakan `ast.literal_eval` untuk safety
4. Update `references/rule-syntax.md` dengan section "Metavariable Constraints"
5. Test fixtures: `tests/fixtures/rule_patterns/metavar_*.yaml`

#### Dependency

- Blocked by: #CL-001
- Blocks: tidak ada

---

### Issue #CL-003 — Taint Propagator dengan Label & Requires

**Priority:** P1
**Topic:** rule-engine, taint
**Estimasi:** 2-3 minggu
**Referensi Semgrep:** `src/tainting/Xtaint.ml`, `src/parsing/Parse_rule.ml` (key `propagators`, `pattern-propagators`, `label`, `requires`, `replace-labels`)

#### Motivasi

Taint engine CodeLens (`ast_taint_engine.py`) saat ini hanya mengenali source → sink dengan sanitizer sebagai penghapus. Tidak bisa ekspresikan:

- "Taint dari `request.args` mendapat label `USER_INPUT`, taint dari `os.environ` mendapat label `ENV`"
- "Function `decrypt()` membutuhkan label `ENCRYPTED` dan menggantinya dengan `PLAINTEXT`"
- "Propagasi taint dari argumen `$FROM` ke field `$TO.x` hanya jika label `A` sudah ada"

Ini adalah model **taint multiset berbasis label** yang jauh lebih ekspresif dan mengurangi false positive.

#### Acceptance Criteria

- [ ] Schema rule mendukung `taint:` mode dengan `sources`, `sinks`, `sanitizers`, `propagators`
- [ ] Setiap source/sink/propagator bisa declare `label` (string atau list)
- [ ] Propagator mendukung `requires` (label yang harus sudah ada) dan `replace-labels` (label yang dihapus/diganti)
- [ ] Engine `ast_taint_engine.py` diupgrade untuk track label multiset per-variable
- [ ] Backward compatible dengan rule `pattern-sources`/`pattern-sinks`/`pattern-sanitizers` lama (default label: `TAINT`)
- [ ] Test case: rule SSRF dengan label `URL` + propagator `requests.get(url)` → require `URL`, replace dengan `HTTP_REQUEST`
- [ ] Output finding menyertakan label trace: `[{label: "URL", origin: "request.args['url']", line: 12}, ...]`

#### Langkah Implementasi

1. Baca `src/tainting/Xtaint.ml` untuk memahami model data (set of labels, propagator rules)
2. Tambah `scripts/taint_label.py` — label multiset data structure
3. Refactor `ast_taint_engine.py` untuk track label, bukan boolean
4. Update `scripts/rules/python_security.yaml` SSRF rule untuk pakai label
5. Tambah sub-command `codelens taint-trace --name <fn>` untuk visualisasi label flow
6. Dokumentasi: `references/taint-labels.md`

#### Dependency

- Blocked by: #CL-001
- Blocks: tidak ada

---

### Issue #CL-004 — Pattern Combinators Lengkap (`pattern-where-python` opsional)

**Priority:** P2
**Topic:** rule-engine
**Estimasi:** 1 minggu
**Referensi Semgrep:** `src/parsing/Parse_rule_formula.ml` (key `pattern-where-python`)

#### Motivasi

Beberapa rule tidak bisa diekspresikan dengan pattern matching murni — perlu logika Python custom, contoh:

- "String literal `$S` panjangnya > 100 dan mengandung karakter non-ASCII"
- "List `$L` punya elemen dengan field `id` duplikat"

`pattern-where-python` di Semgrep memungkinkan ini dengan safety guarantee (subset Python).

#### Acceptance Criteria

- [ ] Key `pattern-where-python` didukung, menerima Python expression sebagai string
- [ ] Expression dieksekusi dalam sandbox `eval()` dengan hanya metavariable bound + built-in terbatas (`len`, `str`, `int`, `re.match`, dll.)
- [ ] Default: **disabled** (harus `--enable-pattern-where-python` flag eksplisit karena risiko keamanan)
- [ ] Dokumentasi warning: hanya untuk rule yang dipercaya, jangan untuk rule dari registry publik tanpa audit
- [ ] Test case: rule "long string literal" dengan `pattern-where-python: len($S) > 100`

#### Langkah Implementasi

1. Implementasi sandbox executor di `scripts/rule_matcher.py`
2. Whitelist built-in yang diizinkan
3. Tambah flag `--enable-pattern-where-python` di CLI
4. Update `_TOOL_DEFINITIONS` di `mcp_server.py` agar MCP tool juga bisa enable

#### Dependency

- Blocked by: #CL-001
- Blocks: tidak ada

---

### Issue #CL-005 — Rule Metachecking & Validation Command

**Priority:** P1
**Topic:** rule-engine, tooling
**Estimasi:** 1 minggu
**Referensi Semgrep:** `src/metachecking/Check_rule.ml`, `cli/src/semgrep/commands/scan.py` (option `o_validate`, `o_strict`)

#### Motivasi

Saat ini, jika user menulis rule YAML dengan typo (e.g., `pattern-eiter` bukan `pattern-either`), CodeLens akan **silent skip** rule tersebut. Tidak ada validasi. Ini menyebabkan false sense of security.

#### Acceptance Criteria

- [ ] CLI command baru: `codelens rule-validate [--strict] <rule-path>`
- [ ] Exit code 0 jika semua rule valid, exit 1 jika ada error, exit 2 jika ada warning (dan `--strict`)
- [ ] Check: required field (`id`, `languages`, `severity`, `message`)
- [ ] Check: unknown key (warning, bukan error)
- [ ] Check: tipe field benar (`severity: critical|high|medium|low|info`)
- [ ] Check: language didukung
- [ ] Check: pattern bisa di-parse (untuk rule pattern-based)
- [ ] Output format: text (default), json (`--format json`)
- [ ] Bisa dipakai sebagai pre-commit hook

#### Langkah Implementasi

1. Tulis `scripts/commands/rule_validate.py`
2. Tulis `scripts/rule_validator.py` dengan kelas `RuleValidator`
3. Tambah ke registry command di `scripts/commands/__init__.py`
4. Tambah ke `_TOOL_DEFINITIONS` di `mcp_server.py`
5. Dokumentasi: section "Rule Validation" di `references/rule-syntax.md`
6. Update `pre_commit_hook.py` untuk auto-validate rule sebelum commit

#### Dependency

- Blocked by: #CL-001
- Blocks: #CL-014 (rule test framework)

---

### Issue #CL-006 — Rule Test Framework (`codelens rule-test`)

**Priority:** P1
**Topic:** rule-engine, tooling
**Estimasi:** 1-2 minggu
**Referensi Semgrep:** `src/osemgrep/cli_test/Test_subcommand.ml`, `cli/tests/default/e2e/rules/`

#### Motivasi

Untuk membangun ekosistem rule yang sehat, contributor perlu cara menulis **regression test** untuk rule mereka. Saat ini, CodeLens punya `benchmarks/` tapi tidak ada fixture per-rule dengan expected result.

#### Acceptance Criteria

- [ ] CLI command baru: `codelens rule-test <rule-path>`
- [ ] Format fixture: `<rule-id>/(pass|fail).<ext>` — file yang seharusnya tidak match (pass) atau match (fail)
- [ ] Alternatif: `.test.yaml` dengan `rule`, `samples` (`{path, expect_match: bool}`)
- [ ] Output: `<rule-id>: PASS (3/3 samples)` atau `<rule-id>: FAIL — expected match at line 5 but no match`
- [ ] Exit code 0 jika semua rule pass test, exit 1 jika ada failure
- [ ] CI: tambah job `codelens-test` di `codelens-ci.yml` yang run `codelens rule-test scripts/rules/`
- [ ] Migrasikan minimal 10 rule dari `python_security.yaml` dan `javascript_security.yaml` ke fixture test

#### Langkah Implementasi

1. Tulis `scripts/commands/rule_test.py`
2. Tulis `scripts/rule_test_runner.py` untuk orchestration
3. Bikin `tests/rule_fixtures/` directory
4. Tambah subcommand ke registry
5. Tambah CI step
6. Dokumentasi: `references/rule-testing.md`

#### Dependency

- Blocked by: #CL-001, #CL-005
- Blocks: tidak ada

---

### Issue #CL-007 — Output Formatter Tambahan (junit_xml, emacs, vim, gitlab_sast, gitlab_secrets)

**Priority:** P1
**Topic:** output
**Estimasi:** 1 minggu
**Referensi Semgrep:** `cli/src/semgrep/formatter/` (8 file formatter)

#### Motivasi

CodeLens saat ini hanya punya `sarif.py` dan `markdown.py`. User CI/CD yang menggunakan GitLab CI atau Jenkins tidak bisa konsumsi output CodeLens langsung — perlu konversi manual.

#### Acceptance Criteria

- [ ] `--format junit_xml` — output JUnit XML untuk Jenkins/GitLab CI test report
- [ ] `--format emacs` — output Flycheck-compatible (format `path:line:col:severity:message`)
- [ ] `--format vim` — output quickfix-compatible (format `path:line:col:text`)
- [ ] `--format gitlab_sast` — GitLab SAST JSON schema v2 (lihat `cli/src/semgrep/formatter/gitlab_sast.py` di Semgrep)
- [ ] `--format gitlab_secrets` — GitLab Secrets Detection JSON schema
- [ ] `--format json` — JSON terstruktur (sudah ada, pastikan konsisten dengan schema lain)
- [ ] `--format text` — plain text untuk terminal (sudah ada default, dokumentasikan)
- [ ] Semua formatter menerima objek finding yang sama (interface terdefinisi di `scripts/formatters/base.py`)
- [ ] Update `references/output-formats.md` (baru) dengan contoh output masing-masing

#### Langkah Implementasi

1. Definisi `Finding` dataclass di `scripts/formatters/base.py` (jika belum ada)
2. Tulis 5 formatter baru di `scripts/formatters/`
3. Register di CLI argument parser
4. Port pola dari `cli/src/semgrep/formatter/*.py` Semgrep (lisensi LGPL — perlu attribution)
5. Test dengan `tests/test_formatters.py` (extend file yang sudah ada)

#### Dependency

- Blocked by: tidak ada
- Blocks: tidak ada

---

### Issue #CL-008 — LSP Server Native (`codelens lsp`)

**Priority:** P1
**Topic:** lsp, ide
**Estimasi:** 3-4 minggu
**Referensi Semgrep:** `src/osemgrep/cli_lsp/Lsp_CLI.ml`, `src/osemgrep/cli_lsp/Lsp_subcommand.ml`, `src/lsp_legacy/server/`, `src/lsp_legacy/custom_commands/`

#### Motivasi

CodeLens punya `scripts/lsp_client.py` (klien untuk LSP eksternal) tapi **tidak punya LSP server sendiri**. VS Code extension `vscode-codelens/` berkomunikasi via subprocess CLI, bukan via LSP. Ini berarti:

- Tidak bisa integrate dengan Neovim, Emacs (lsp-mode), Helix, Zed, dll.
- Tidak ada hover, go-to-definition, code lens (ironis namanya), inline diagnostic real-time
- VS Code extension harus re-implement banyak hal yang seharusnya jadi LSP server responsibility

#### Acceptance Criteria

- [ ] CLI command baru: `codelens lsp [--port 8080] [--stdio]`
- [ ] Implement LSP 3.17 spec: `initialize`, `initialized`, `textDocument/didOpen`, `didChange`, `didSave`, `didClose`, `textDocument/publishDiagnostics`, `textDocument/hover`, `textDocument/definition`, `textDocument/references`, `textDocument/codeLens`, `textDocument/codeAction`
- [ ] Custom command (non-standard): `codelens/query`, `codelens/impact`, `codelens/guard` — expose command CodeLens ke editor
- [ ] Bisa dipakai oleh Neovim (dengan `nvim-lspconfig`) dan VS Code (update `vscode-codelens/` untuk pakai LSP)
- [ ] Documentasi: `references/lsp-integration.md` dengan config Neovim, VS Code, Emacs
- [ ] Performance: response time < 50ms untuk hover/definition pada file yang sudah di-scan

#### Langkah Implementasi

1. Pertimbangkan pakai library `pylsp` atau `pygls` (Python LSP framework) — jangan reimplement dari nol
2. Tulis `scripts/lsp_server.py` — main entry, transport (stdio + TCP)
3. Tulis `scripts/lsp_handlers/` — satu handler per LSP method
4. Update `vscode-codelens/extension.js` untuk pakai LSP daripada CLI subprocess
5. Tambah integrasi test: jalankan LSP server + kirimkan request, assert response

#### Dependency

- Blocked by: tidak ada (bisa parallel dengan #CL-001)
- Blocks: #CL-018 (MCP `get_abstract_syntax_tree` bisa reuse LSP infrastructure)

---

### Issue #CL-009 — Pre-Filtering Optimization (Regex Pre-Match sebelum AST)

**Priority:** P1
**Topic:** performance
**Estimasi:** 1-2 minggu
**Referensi Semgrep:** `src/prefiltering/Analyze_pattern.ml`, `src/prefiltering/Analyze_rule.ml`

#### Motivasi

Saat ini, `scan` CodeLens mem-parse semua file dengan tree-sitter, lalu jalankan semua rule. Untuk repo besar (5000+ file) dengan 100+ rule, ini lambat. Banyak file bisa di-skip lebih awal jika rule jelas tidak akan match.

Contoh: rule "no `eval()` call" tidak akan match file yang tidak mengandung string literal `eval`. Pre-filter dengan regex `eval\b` eliminasi 90%+ file dalam <1 detik.

#### Acceptance Criteria

- [ ] Untuk setiap rule pattern, otomatis derive "fast regex" (e.g., `eval(...)` → `eval`)
- [ ] Sebelum AST parse, jalankan `grep` (atau `ripgrep`) untuk filter file kandidat
- [ ] Statistik: jumlah file pre-filtered vs full-scanned terekspos di output
- [ ] Bisa di-disable dengan `--no-prefilter` (untuk debugging)
- [ ] Benchmark: repo 5000 file + 100 rule → target 3x speedup vs baseline (sebelum issue ini)

#### Langkah Implementasi

1. Tambah `scripts/prefilter.py` — derive regex dari pattern AST
2. Pakai `ripgrep` via subprocess (lebih cepat dari Python `re` untuk multi-file)
3. Integrate di `scripts/codelens.py` scan command, sebelum `registry.build()`
4. Tambah metric di output: `{prefilter: {total_files: 5000, passed: 320, skipped: 4680, time_ms: 820}}`
5. Tambah benchmark di `benchmarks/check_regression.py`

#### Dependency

- Blocked by: #CL-001 (perlu pattern AST untuk derive regex)
- Blocks: tidak ada

---

### Issue #CL-010 — Baseline Commit & Diff Scan Mode untuk CI

**Priority:** P1
**Topic:** ci-cd
**Estimasi:** 1-2 minggu
**Referensi Semgrep:** `cli/src/semgrep/git.py`, `src/osemgrep/cli_scan/Diff_scan.ml`, opsi `o_baseline_commit`, `o_use_git`

#### Motivasi

CI paling efektif bila hanya melaporkan **finding baru** yang diperkenalkan oleh PR ini, bukan seluruh backlog. CodeLens `diff` command sudah ada tapi hanya membandingkan registry snapshot, bukan git commit.

#### Acceptance Criteria

- [ ] Flag `--baseline-commit <SHA>` di `scan`, `secrets`, `dataflow`, `vuln-scan`, `smell`, `complexity`, `dead-code`, `taint`
- [ ] Hanya file yang berubah antara baseline dan HEAD yang discan
- [ ] Finding dianggap "new" jika lokasi-nya (file:line) tidak ada di baseline
- [ ] Output tambahan: `{new_findings: N, preexisting_findings: M, total: N+M}`
- [ ] CLI flag `--diff-scan` (alias `--baseline-commit HEAD~1`)
- [ ] GitHub Actions workflow baru: `codelens-pr-check.yml` yang otomatis set `--baseline-commit ${{ github.event.pull_request.base.sha }}`
- [ ] Documentasi: section "CI Baseline Mode" di `references/ci-cd.md` (baru)

#### Langkah Implementasi

1. Tambah `scripts/git_integration.py` — wrapper `git diff --name-only <SHA> HEAD`
2. Filter target file list sebelum scan
3. Untuk "new finding" detection: cache finding di `.codelens/baseline_<SHA>.json`
4. Update GitHub Actions workflow
5. Tambah flag di argparser tiap command

#### Dependency

- Blocked by: tidak ada
- Blocks: tidak ada

---

### Issue #CL-011 — Inline Suppression (`# nolens` / `# nosemgrep` kompatibel)

**Priority:** P1
**Topic:** rule-engine, ci-cd
**Estimasi:** 3-5 hari
**Referensi Semgrep:** `cli/src/semgrep/nosemgrep.py`

#### Motivasi

Saat CodeLens report false positive, user perlu cara men-skip-nya tanpa harus disable rule globally. Standar industri adalah inline comment `# nosemgrep` (Semgrep) atau `// eslint-disable-next-line` (ESLint). Untuk interoperabilitas, CodeLens harus **mendukung `# nosemgrep` (kompatibel) DAN `# nolens` (native)**.

#### Acceptance Criteria

- [ ] Inline comment `# nolens` dan `# nosemgrep` di akhir baris → skip finding di baris itu
- [ ] `# nolens: rule-id-1, rule-id-2` → skip dengan rule ID eksplisit
- [ ] Komentar multi-bahasa: `#` (Python/Ruby/Shell/YAML), `//` (JS/TS/Rust/Java/C/C++), `/* */` (CSS/JS multi-line), `<!-- -->` (HTML), `--` (SQL/Lua)
- [ ] Flag `--disable-nolens` untuk enforce stricter policy (CI/CD production)
- [ ] Statistik di output: `{suppressed: N, by_rule: {rule-a: 3, rule-b: 1}}`
- [ ] Documentasi: section "Inline Suppression" di `references/suppression.md` (baru)

#### Langkah Implementasi

1. Tambah `scripts/suppression.py` — parse inline comment per bahasa
2. Integrate di output stage: filter finding yang suppressed
3. Tambah flag di argparser
4. Tambah unit test untuk 5 bahasa berbeda

#### Dependency

- Blocked by: tidak ada
- Blocks: tidak ada

---

### Issue #CL-012 — Strict Mode & Error Threshold

**Priority:** P2
**Topic:** ci-cd
**Estimasi:** 3 hari
**Referensi Semgrep:** opsi `o_strict`, `o_error` di `src/osemgrep/cli_scan/Scan_CLI.ml`

#### Motivasi

Saat ini, CodeLens exit 0 bahkan jika ada warning atau parse error. Untuk CI yang ketat, perlu exit non-zero jika ada kondisi tertentu.

#### Acceptance Criteria

- [ ] Flag `--strict` — exit non-zero jika ada warning (rule invalid, parse error, dll.)
- [ ] Flag `--error` — exit non-zero hanya jika ada finding dengan severity >= `high`
- [ ] Flag `--severity-threshold <level>` — exit non-zero jika ada finding dengan severity >= threshold
- [ ] Combine dengan `--max-findings N` — exit non-zero jika total finding > N
- [ ] Documentasi di `references/ci-cd.md`

#### Langkah Implementasi

1. Tambah 4 flag di argparser global
2. Di akhir eksekusi command, evaluasi exit code berdasarkan flag
3. Test exit code di integration test

#### Dependency

- Blocked by: tidak ada
- Blocks: tidak ada

---

### Issue #CL-013 — MCP Hooks (post_tool, supply_chain, inject_secure_defaults, stop, settings)

**Priority:** P0
**Topic:** mcp, ai-agent
**Estimasi:** 2-3 minggu
**Referensi Semgrep:** `cli/src/semgrep/mcp/hooks/` (5 hook file: `post_tool.py`, `supply_chain.py`, `inject_secure_defaults.py`, `stop.py`, `settings.py`)

#### Motivasi

MCP server CodeLens saat ini hanya reaktif (AI harus panggil tool secara eksplisit). Sementara itu, **Semgrep Guardian** punya konsep hooks yang otomatis trigger setelah AI generate file. Ini sangat penting untuk mencegah AI agent menulis kode yang insecure — hook `post_tool` akan auto-scan file yang baru ditulis dan kirim feedback ke agent.

Ini adalah **ceruk utama CodeLens** sebagai "AI-native" tool — justru harus jadi P0.

#### Acceptance Criteria

- [ ] Hook `post_tool` — setelah AI agent menulis file, auto-run `secrets` + `dataflow` + `smell` pada file tersebut
- [ ] Hook `supply_chain` — setelah AI mengubah `package.json`/`requirements.txt`/`Cargo.toml`, auto-run `vuln-scan`
- [ ] Hook `inject_secure_defaults` — sebelum AI generate file baru, inject secure defaults (e.g., `helmet` untuk Express app)
- [ ] Hook `stop` — sebelum AI agent menyelesaikan task, jalankan final guard check
- [ ] Hook `settings` — baca konfigurasi hook dari `.codelens/hooks.json`
- [ ] Hook lifecycle terdokumentasi: `pre_tool_use` / `post_tool_use` / `on_session_start` / `on_session_end`
- [ ] Bisa disable per-hook via config
- [ ] Documentasi: `references/mcp-hooks.md` dengan contoh integrasi Claude Code, Cursor, VS Code Copilot

#### Langkah Implementasi

1. Baca `cli/src/semgrep/mcp/hooks/*.py` Semgrep untuk pola
2. Tambah hook registry di `scripts/mcp_server.py`
3. Define MCP notification `notifications/progress` untuk hook events
4. Tambah konfigurasi `.codelens/hooks.json` schema
5. Implementasi 5 hook di `scripts/mcp_hooks/`
6. Test dengan Claude Code sandbox

#### Dependency

- Blocked by: tidak ada
- Blocks: tidak ada

---

### Issue #CL-014 — MCP Prompt: `write_custom_codelens_rule` (Skill untuk AI)

**Priority:** P1
**Topic:** mcp, ai-agent
**Estimasi:** 1 minggu
**Referensi Semgrep:** `cli/src/semgrep/mcp/server.py` (function `write_custom_semgrep_rule`, `get_semgrep_rule_schema`, `get_semgrep_rule_yaml`)

#### Motivasi

AI agent seperti Claude Code sering diminta user "tulis rule CodeLens untuk pattern X". Saat ini AI harus menebak schema rule. Dengan **MCP prompt** (skill), AI bisa panggil `write_custom_codelens_rule(description="deteksi SQL injection di Flask")` → dapat rule YAML siap pakai + validasi.

#### Acceptance Criteria

- [ ] MCP prompt baru: `write_custom_codelens_rule` dengan parameter `description` (string)
- [ ] MCP prompt baru: `get_codelens_rule_schema` — return JSON schema rule
- [ ] MCP prompt baru: `get_codelens_rule_yaml(rule_id)` — return template YAML untuk rule ID tertentu
- [ ] Output: rule YAML lengkap dengan `id`, `pattern`, `languages`, `message`, `severity`, contoh false positive case
- [ ] Bisa dipanggil dari Claude Code: `/write_custom_codelens_rule description="..."`
- [ ] Documentasi: `references/mcp-prompts.md`

#### Langkah Implementasi

1. Extend `scripts/mcp_server.py` untuk handle `prompts/list` dan `prompts/get` (MCP spec)
2. Tambah 3 prompt ke `_PROMPT_DEFINITIONS`
3. Implementasi logic: LLM-templating (bisa via OpenAI/Z.ai API atau hardcoded template)
4. Test dengan Claude Code

#### Dependency

- Blocked by: #CL-001 (perlu schema rule pattern baru)
- Blocks: tidak ada

---

### Issue #CL-015 — MCP Tool: `get_abstract_syntax_tree` dan `codelens_scan_with_custom_rule`

**Priority:** P1
**Topic:** mcp, ai-agent
**Estimasi:** 1 minggu
**Referensi Semgrep:** `cli/src/semgrep/mcp/server.py` (function `get_abstract_syntax_tree`, `semgrep_scan_with_custom_rule`)

#### Motivasi

AI agent yang ingin menganalisa kode sering perlu:

1. **AST representation** — untuk reasoning tentang struktur kode (bukan raw text)
2. **Live rule testing** — coba rule baru tanpa save ke file dulu

Saat ini MCP CodeLens hanya ekspos command yang sudah ada. Tambah 2 tool ini akan sangat memperkaya kemampuan AI.

#### Acceptance Criteria

- [ ] MCP tool `codelens_get_ast(path, language?)` — return AST sebagai JSON tree (tree-sitter S-expression atau nested dict)
- [ ] MCP tool `codelens_scan_with_custom_rule(rule_yaml, target_path)` — run rule ad-hoc, return finding tanpa perlu save rule
- [ ] Output AST bisa di-filter (e.g., hanya function declaration, hanya class)
- [ ] Performance: AST generation <100ms untuk file <10K LOC
- [ ] Documentasi: section di `references/mcp-tools.md` (baru)

#### Langkah Implementasi

1. Tambah 2 entry ke `_TOOL_DEFINITIONS` di `scripts/mcp_server.py`
2. Implementasi handler — reuse `grammar_loader.py` untuk AST, dan `rule_matcher.py` (Issue #CL-001) untuk custom rule
3. Test dengan fixture `tests/fixtures/`
4. Bisa return AST dalam 2 format: `sexp` (string) dan `json` (nested dict)

#### Dependency

- Blocked by: #CL-001 (untuk `scan_with_custom_rule`)
- Blocks: tidak ada

---

### Issue #CL-016 — MCP Transport: Streamable HTTP (FastMCP-compat)

**Priority:** P1
**Topic:** mcp
**Estimasi:** 1 minggu
**Referensi Semgrep:** `cli/src/semgrep/mcp/server.py` (mendukung `stdio` + `streamable-http`)

#### Motivasi

MCP server CodeLens saat ini mendukung HTTP/SSE berbasis `http.server` stdlib (lihat `start_http_server` di `scripts/mcp_server.py:1734`). Tapi ini bukan implementasi spec **Streamable HTTP** resmi (yang support session resume, pagination, dll.). Beberapa client MCP modern (Claude Code, Cursor) prefer streamable-http karena lebih reliable untuk remote deployment.

#### Acceptance Criteria

- [ ] Implementasi streamable-http per MCP spec 2025-06-18 (atau terbaru)
- [ ] Endpoint `/mcp` menerima POST dengan `Accept: text/event-stream`
- [ ] Support session ID via `Mcp-Session-Id` header
- [ ] Bisa di-deploy di Docker container dengan port expose
- [ ] Documentasi: cara deploy di Kubernetes / Docker Compose
- [ ] Bisa concurrent handle 100+ session (stress test)

#### Langkah Implementasi

1. Pertimbangkan migrasi ke `mcp` Python SDK (resmi dari Anthropic) daripada hand-rolled JSON-RPC
2. Atau implementasi streamable-http manual di atas `aiohttp`/`starlette`
3. Update `mcp_config.json` untuk dokumentasi config client
4. Tambah integration test: spawn server streamable-http + client connect + tool call

#### Dependency

- Blocked by: tidak ada
- Blocks: tidak ada

---

### Issue #CL-017 — Historical Secrets Scan (Git History)

**Priority:** P2
**Topic:** security, secrets
**Estimasi:** 1-2 minggu
**Referensi Semgrep:** opsi `o_historical_secrets` di `src/osemgrep/cli_scan/Scan_CLI.ml`

#### Motivasi

Secret leak paling berbahaya adalah yang sudah terlanjur di-commit ke git history (dan mungkin sudah di-`rm` tapi masih bisa di-`git log -p`). Scan hanya working tree tidak cukup. Semgrep punya `--historical-secrets` yang scan semua commit di git history.

#### Acceptance Criteria

- [ ] Flag `--historical` di `secrets` command
- [ ] Untuk setiap commit di git history (default: HEAD~1000..HEAD, atau `--since <date>`), scan diff untuk secret
- [ ] Output: `{commit_sha, file, line, secret_type, severity, author, date}`
- [ ] Bisa filter by author, date range, file path
- [ ] Performance: 1000 commit dalam <60 detik (gunakan `git log -p --all --diff-filter=AM`)
- [ ] Bisa export ke JSON untuk audit
- [ ] Documentasi: `references/historical-scan.md`

#### Langkah Implementasi

1. Tambah `scripts/git_history.py` — wrapper `git log -p`
2. Untuk setiap diff, jalankan `secrets_engine.py` hanya pada added lines
3. Deduplicate finding (secret yang sama di commit berbeda)
4. Update `secrets` command dengan flag `--historical`, `--since`, `--author`, `--max-commits`

#### Dependency

- Blocked by: tidak ada
- Blocks: tidak ada

---

### Issue #CL-018 — SCA Package Manager Tambahan (NuGet, Pub, SwiftPM, Mix, Gradle, Maven, Composer, Gem)

**Priority:** P1
**Topic:** sca
**Estimasi:** 2-3 minggu
**Referensi Semgrep:** `cli/src/semdep/parsers/` (15 file parser)

#### Motivasi

CodeLens `vuln-scan` saat ini mendukung 7 package manager (npm, yarn, pnpm, bun, cargo, pip, go). Semgrep mendukung 15 — termasuk ekosistem .NET (NuGet), Flutter (Pub), Swift (SwiftPM), Elixir (Mix), JVM (Gradle, Maven), PHP (Composer), Ruby (Gem). Untuk user di ekosistem tersebut, CodeLens tidak bisa jadi satu-satunya alat.

#### Acceptance Criteria

- [ ] Parser untuk 8 package manager baru: NuGet (`packages.lock.json`), Pub (`pubspec.lock`), SwiftPM (`Package.resolved`), Mix (`mix.lock`), Gradle (`gradle.lockfile`), Maven (`pom.xml` + dependency tree), Composer (`composer.lock`), Gem (`Gemfile.lock`)
- [ ] Integrasi dengan `osv_client.py` — semua ecosystem yang OSV support harus bisa query
- [ ] Update `framework_detect.py` untuk auto-detect project type baru
- [ ] Output konsisten dengan schema yang sudah ada
- [ ] Documentasi: section "Supported Package Managers" di README
- [ ] Test fixture: `tests/fixtures/sca/<ecosystem>/`

#### Langkah Implementasi

1. Untuk setiap package manager, baca contoh lockfile di Semgrep (`cli/src/semdep/parsers/<name>.py`) untuk referensi struktur
2. Tulis parser Python di `scripts/sca_parsers/<name>.py`
3. Register di `scripts/vulnscan_engine.py`
4. Tambah detection di `framework_detect.py`
5. Tambah unit test per parser

#### Dependency

- Blocked by: tidak ada
- Blocks: tidak ada

---

### Issue #CL-019 — Language Coverage: Go, Java, Ruby, PHP, C/C++ (Tree-Sitter Full)

**Priority:** P2
**Topic:** lang-coverage
**Estimasi:** 6-10 minggu (bisa dibagi per bahasa)
**Referensi Semgrep:** `cli/src/semgrep/semgrep_interfaces/Lang.ml` (40+ bahasa)

#### Motivasi

CodeLens punya tree-sitter parser untuk 9 bahasa (Python, JS, TS, TSX, Rust, HTML, CSS, Vue, Svelte). Bahasa populer lain (Go, Java, Ruby, PHP, C/C++) hanya dapat regex fallback — yang artinya **pattern matching berbasis AST tidak akan bekerja** untuk bahasa-bahasa ini. Karena Issue #CL-001 membutuhkan AST, ini akan jadi batas adopsi.

#### Acceptance Criteria (per bahasa, issue bisa di-split)

- [ ] **Go**: tree-sitter-go, parser `scripts/parsers/go_parser.py` dengan function/method/interface detection
- [ ] **Java**: tree-sitter-java, parser untuk class/method/annotation
- [ ] **Ruby**: tree-sitter-ruby, parser untuk method/block/module
- [ ] **PHP**: tree-sitter-php, parser untuk class/function/trait
- [ ] **C/C++**: tree-sitter-c, tree-sitter-cpp, parser untuk function/struct/class
- [ ] Setiap bahasa: 20+ test fixture, 10+ rule pattern contoh
- [ ] Update `references/parser-rules.md` dengan section per-bahasa
- [ ] Benchmark: parse 1000 file Go dalam <30 detik

#### Langkah Implementasi (per bahasa)

1. Add tree-sitter grammar ke `setup.sh`
2. Tulis parser Python di `scripts/parsers/<lang>_parser.py`
3. Register di `grammar_loader.py`
4. Test di `tests/test_<lang>_parser.py`
5. Tambah rule contoh di `scripts/rules/<lang>_security.yaml`

#### Dependency

- Blocked by: #CL-001 (pattern matching butuh AST)
- Blocks: tidak ada

---

### Issue #CL-020 — Disk Cache untuk AST Parse Result

**Priority:** P1
**Topic:** performance
**Estimasi:** 1 minggu
**Referensi Semgrep:** `src/core_scan/Disk_cache.ml`, `src/core_scan/Disk_cache.mli`

#### Motivasi

Saat user run `scan` lalu `scan --incremental` lalu `secrets` lalu `smell`, AST di-parse berulang kali untuk file yang sama. Untuk repo 5000 file, ini duplikasi kerja yang signifikan. Disk cache (key = file content hash) eliminasi ini.

#### Acceptance Criteria

- [ ] Cache di `~/.codelens/cache/` dengan struktur `<hash>.ast.pkl` (atau format lain)
- [ ] Cache key: SHA-256 dari file content + parser version
- [ ] Hit ratio terekspos di output: `{cache: {hits: 4823, misses: 177, size_mb: 124}}`
- [ ] Auto-evict entry yang >30 hari tidak diakses
- [ ] `codelens cache clear` command untuk purge
- [ ] Bisa di-disable dengan `--no-cache` (untuk benchmark)
- [ ] Thread-safe (multiple process bisa baca cache bersamaan)

#### Langkah Implementasi

1. Tambah `scripts/disk_cache.py` — wrapper `pickle` dengan lock file
2. Integrate di `grammar_loader.py` dan `base_parser.py`
3. Tambah CLI command `codelens cache clear` dan `codelens cache stats`
4. Tambah metric di output scan

#### Dependency

- Blocked by: tidak ada
- Blocks: tidak ada

---

### Issue #CL-021 — Config Resolver (URL, Registry, Local Path)

**Priority:** P1
**Topic:** rule-engine, distribution
**Estimasi:** 2-3 minggu
**Referensi Semgrep:** `cli/src/semgrep/config_resolver.py`

#### Motivasi

Konstanta `REGISTRY_INDEX_URL = "https://registry.codelens.dev/api/v1/plugins"` sudah ada di `plugin_system.py` tapi **marketplace belum aktif**. User tidak bisa `codelens scan --config https://example.com/my-rules.yaml` atau `--config p/owasp-top-10`. Padahal ini adalah cara utama distribusi rule di Semgrep.

#### Acceptance Criteria

- [ ] Flag `--config <path>` di `scan`, `secrets`, `dataflow`, `taint`, `vuln-scan` (dan semua command yang konsumsi rule)
- [ ] Menerima: local path (`./rules.yaml`), URL (`https://...`), registry ID (`p/owasp-top-10`), `auto` (default set)
- [ ] Cache download di `~/.codelens/configs/`
- [ ] Verifikasi checksum SHA-256 untuk rule dari URL/registry
- [ ] Bisa combine multiple config: `--config p/owasp-top-10 --config ./custom.yaml`
- [ ] Mendukung auth token untuk registry private: `CODELENS_REGISTRY_TOKEN` env var
- [ ] Documentasi: `references/rule-distribution.md`

#### Langkah Implementasi

1. Tambah `scripts/config_resolver.py` — resolver multi-source
2. Update plugin marketplace endpoint (`REGISTRY_INDEX_URL`) — pastikan backend-nya ready atau dokumentasikan status
3. Tambah flag di argparser
4. Tambah HTTP client dengan retry + checksum verification
5. Documentasi

#### Dependency

- Blocked by: #CL-001 (perlu schema rule pattern baru)
- Blocks: tidak ada

---

### Issue #CL-022 — Dependency-Aware Rules & Join Rule (Cross-File Multi-Source)

**Priority:** P2
**Topic:** rule-engine, taint
**Estimasi:** 2-3 minggu
**Referensi Semgrep:** `cli/src/semgrep/dependency_aware_rule.py`, `cli/src/semgrep/join_rule.py`

#### Motivasi

Dua fitur lanjutan yang mengurangi false positive:

1. **Dependency-aware**: rule `no-insecure-pickle` hanya fire jika `pickle` benar-benar di-import. Tanpa ini, rule fire pada setiap `import pickle` comment, menambah noise.
2. **Join rule**: rule A fire hanya jika rule B juga match di file lain. Contoh: "Endpoint terbuka untuk public (`@app.route('/admin')`) DAN tidak ada `@login_required` di file manapun yang import route ini".

CodeLens punya `crossfile_taint_engine.py` tapi hanya untuk taint — belum general-purpose join.

#### Acceptance Criteria

- [ ] Rule bisa declare `metadata.dependencies: [package-name]` — hanya fire jika package ada di lockfile
- [ ] Rule bisa declare `metadata.depends_on_pattern: import pickle` — hanya fire jika pattern muncul di file yang sama
- [ ] Join rule schema baru: `join: { on: $X, secondary: {file: ..., pattern: ...} }`
- [ ] Engine join rule: read secondary files, match pattern, combine dengan primary match
- [ ] Output finding menyertakan metadata dependency status
- [ ] Documentasi: `references/advanced-rules.md`

#### Langkah Implementasi

1. Tambah field metadata di `rule_validator.py`
2. Modifikasi `rule_matcher.py` untuk check dependency
3. Tambah `scripts/join_rule_engine.py`
4. Test fixtures dengan multi-file scenario

#### Dependency

- Blocked by: #CL-001, #CL-005, #CL-018 (SCA parser untuk dependency check)
- Blocks: tidak ada

---

## 7. Roadmap & Prioritas

### 7.1 Matriks Prioritas

| Issue | Priority | Effort | Dependency | Tema |
|---|:---:|:---:|---|---|
| #CL-001 Pattern Rule Language | P0 | 3-5w | — | rule-engine |
| #CL-013 MCP Hooks | P0 | 2-3w | — | mcp |
| #CL-002 Metavariable Constraint | P1 | 1-2w | #CL-001 | rule-engine |
| #CL-003 Taint Propagator Label | P1 | 2-3w | #CL-001 | rule-engine, taint |
| #CL-005 Rule Metachecking | P1 | 1w | #CL-001 | tooling |
| #CL-006 Rule Test Framework | P1 | 1-2w | #CL-001, #CL-005 | tooling |
| #CL-007 Output Formatter | P1 | 1w | — | output |
| #CL-008 LSP Server | P1 | 3-4w | — | lsp, ide |
| #CL-009 Pre-Filtering | P1 | 1-2w | #CL-001 | performance |
| #CL-010 Baseline/Diff Scan | P1 | 1-2w | — | ci-cd |
| #CL-011 Inline Suppression | P1 | 3-5d | — | rule-engine |
| #CL-014 MCP Prompt write_rule | P1 | 1w | #CL-001 | mcp |
| #CL-015 MCP AST + custom_rule | P1 | 1w | #CL-001 | mcp |
| #CL-016 Streamable HTTP MCP | P1 | 1w | — | mcp |
| #CL-018 SCA Package Manager | P1 | 2-3w | — | sca |
| #CL-020 Disk Cache AST | P1 | 1w | — | performance |
| #CL-021 Config Resolver | P1 | 2-3w | #CL-001 | distribution |
| #CL-004 Pattern-Where-Python | P2 | 1w | #CL-001 | rule-engine |
| #CL-012 Strict Mode | P2 | 3d | — | ci-cd |
| #CL-017 Historical Secrets | P2 | 1-2w | — | security |
| #CL-019 Language Coverage | P2 | 6-10w | #CL-001 | lang-coverage |
| #CL-022 Dependency/Join Rule | P2 | 2-3w | #CL-001, #CL-018 | rule-engine, taint |

### 7.2 Rekomendasi 3-Sprint Roadmap (2 minggu/sprint)

#### Sprint 1 — Fondasi Rule Engine
Fokus: pecahkan masalah terbesar (rule language) dan AI-native unggulan (MCP hooks).

- #CL-001 Pattern Rule Language (3w, mulai minggu 1)
- #CL-013 MCP Hooks (2-3w, paralel)
- #CL-007 Output Formatter (1w, paralel)
- #CL-011 Inline Suppression (3-5d, paralel)
- #CL-020 Disk Cache AST (1w, paralel)

#### Sprint 2 — Quality of Life & AI Surface
Fokus: validasi, testing, AI prompts, dan LSP.

- #CL-002 Metavariable Constraint (1-2w, setelah #CL-001 selesai)
- #CL-005 Rule Metachecking (1w, paralel dengan #CL-002)
- #CL-006 Rule Test Framework (1-2w, setelah #CL-005)
- #CL-014 MCP Prompt write_rule (1w, setelah #CL-001)
- #CL-015 MCP AST + custom_rule (1w, setelah #CL-001)
- #CL-008 LSP Server (3-4w, mulai Sprint 2, selesai Sprint 3)
- #CL-016 Streamable HTTP MCP (1w, paralel)

#### Sprint 3 — Performance, CI, & Coverage
Fokus: performance, CI baseline, SCA, dan distribusi rule.

- #CL-003 Taint Propagator Label (2-3w)
- #CL-009 Pre-Filtering (1-2w, setelah #CL-001)
- #CL-010 Baseline/Diff Scan (1-2w)
- #CL-018 SCA Package Manager (2-3w)
- #CL-021 Config Resolver (2-3w)
- #CL-012 Strict Mode (3d)
- #CL-017 Historical Secrets (1-2w)

### 7.3 Total Estimasi Effort

- **P0 (wajib Sprint 1):** ~7-10 minggu
- **P1 (Sprint 1-3):** ~22-30 minggu
- **P2 (backlog):** ~10-16 minggu
- **Total jika satu developer:** ~40-56 minggu (10-14 bulan)
- **Total jika 3 developer paralel:** ~14-20 minggu (3.5-5 bulan)

### 7.4 Quick Wins (bisa mulai minggu ini, tanpa dependency)

Issue-issue ini bisa langsung dikerjakan tanpa menunggu #CL-001:

1. **#CL-007 Output Formatter** — 1 minggu, copy-paste pola dari Semgrep
2. **#CL-011 Inline Suppression** — 3-5 hari, implementasi sederhana
3. **#CL-012 Strict Mode** — 3 hari, hanya argparser + exit code logic
4. **#CL-013 MCP Hooks** — 2-3 minggu, prioritas tinggi untuk positioning AI-native
5. **#CL-020 Disk Cache AST** — 1 minggu, isolasi di `grammar_loader.py`

---

## 8. Appendix — Peta File Semgrep ke Topik Issue

| Issue | File Referensi Semgrep |
|---|---|
| #CL-001 | `src/parsing/Parse_rule_formula.ml`, `src/matching/Match_patterns.ml`, `src/matching/Matching_generic.ml`, `src/rule/Pattern.ml`, `src/rule/Xpattern.ml` |
| #CL-002 | `src/parsing/Parse_rule_formula.ml` (baris dengan `metavariable-*` dan `focus-metavariable`), `src/engine/Metavariable_*.ml` |
| #CL-003 | `src/tainting/Xtaint.ml`, `src/tainting/Taint.ml`, `src/tainting/OSS_dataflow_tainting.ml`, `src/parsing/Parse_rule.ml` (key `propagators`) |
| #CL-004 | `src/parsing/Parse_rule_formula.ml` (key `pattern-where-python`) |
| #CL-005 | `src/metachecking/Check_rule.ml`, `src/metachecking/Translate_rule.ml`, `cli/src/semgrep/commands/scan.py` (opsi `o_validate`, `o_strict`) |
| #CL-006 | `src/osemgrep/cli_test/Test_subcommand.ml`, `src/osemgrep/cli_test/Test_CLI.ml`, `cli/tests/default/e2e/rules/` |
| #CL-007 | `cli/src/semgrep/formatter/{junit_xml,emacs,vim,gitlab_sast,gitlab_secrets}.py` |
| #CL-008 | `src/osemgrep/cli_lsp/Lsp_CLI.ml`, `src/osemgrep/cli_lsp/Lsp_subcommand.ml`, `src/lsp_legacy/server/`, `src/lsp_legacy/custom_commands/` |
| #CL-009 | `src/prefiltering/Analyze_pattern.ml`, `src/prefiltering/Analyze_rule.ml` |
| #CL-010 | `cli/src/semgrep/git.py`, `src/osemgrep/cli_scan/Diff_scan.ml`, `src/osemgrep/cli_scan/Scan_CLI.ml` (opsi `o_baseline_commit`) |
| #CL-011 | `cli/src/semgrep/nosemgrep.py` |
| #CL-012 | `src/osemgrep/cli_scan/Scan_CLI.ml` (opsi `o_strict`, `o_error`) |
| #CL-013 | `cli/src/semgrep/mcp/hooks/{post_tool,supply_chain,inject_secure_defaults,stop,settings}.py` |
| #CL-014 | `cli/src/semgrep/mcp/server.py` (function `write_custom_semgrep_rule`, `get_semgrep_rule_schema`, `get_semgrep_rule_yaml`) |
| #CL-015 | `cli/src/semgrep/mcp/server.py` (function `get_abstract_syntax_tree`, `semgrep_scan_with_custom_rule`) |
| #CL-016 | `cli/src/semgrep/mcp/server.py` (class `FastMCP`, transport `streamable-http`), `cli/src/semgrep/commands/mcp.py` |
| #CL-017 | `src/osemgrep/cli_scan/Scan_CLI.ml` (opsi `o_historical_secrets`) |
| #CL-018 | `cli/src/semdep/parsers/{cargo,composer,gem,go_mod,gradle,mix,packages_lock_c_sharp,poetry,pubspec_lock,swiftpm,yarn,requirements,pnpm,pipfile,pom_tree}.py` |
| #CL-019 | `cli/src/semgrep/semgrep_interfaces/Lang.ml` (40+ bahasa), `src/parsing/Parse_target.ml` |
| #CL-020 | `src/core_scan/Disk_cache.ml`, `src/core_scan/Disk_cache.mli` |
| #CL-021 | `cli/src/semgrep/config_resolver.py` |
| #CL-022 | `cli/src/semgrep/dependency_aware_rule.py`, `cli/src/semgrep/join_rule.py` |

---

## 9. Catatan Akhir

### 9.1 Konsistensi Internal CodeLens yang Perlu Diperbaiki (Quick Fix)

Sebelum mulai issue besar, ada beberapa inkonsistensi di repo CodeLens yang harus diperbaiki dulu:

1. **Version drift**: README klaim v8.1, SKILL.md klaim v7.2, SKILL-QUICK.md klaim v7.2.0. Pilih satu source of truth.
2. **Command count drift**: README klaim 56 commands, SKILL-QUICK klaim 45 commands. Hitung aktual dan sinkronkan.
3. **MCP tool count drift**: README klaim 49 tools, kode menampilkan dynamic discovery. Hitung aktual.
4. **`references/changelog.md` vs root `CHANGELOG.md`**: ada dua file changelog, pastikan sinkron atau hapus salah satu.

### 9.2 Aturan Serapan

Untuk menghindari trap "rewrite everything from scratch":

1. **Copy pattern, not code** — Semgrep LGPL-2.1, CodeLens MIT. Lisensi berbeda, jangan copy-paste kode mentah. Pahami pola, implementasi ulang.
2. **Preserve CodeLens identity** — Jangan ubah positioning CodeLens jadi "Semgrep clone". CodeLens unggul di AI-native + frontend breadth, itu yang harus dipertahankan.
3. **Incremental adoption** — Issue P0/P1 dulu, baru P2. Jangan multiplex 22 issue sekaligus.
4. **Test dengan real codebase** — Sebelum merge, benchmark di repo `benchmarks/fixtures/vulnerable_app/` dan (idealnya) satu repo open-source besar (e.g., `spacedriveapp/spacedrive` yang sudah dipakai di CHANGELOG).

### 9.3 Yang TIDAK Perlu Diserap dari Semgrep

Beberapa hal di Semgrep sengaja **tidak masuk daftar issue** karena:

- **Metrics/telemetry** — privacy-first positioning CodeLens lebih penting daripada data collection. Skip untuk sekarang.
- **Semgrep AppSec Platform integration** — ini produk komersial Semgrep, Inc., bukan open-source fitur.
- **Pro engine** (interfile path-sensitive) — membutuhkan tim PhD + OCaml expertise. Out of scope untuk CodeLens.
- **`osemgrep` rewrite di OCaml** — CodeLens sudah Python + tree-sitter, tidak perlu migrasi bahasa.
- **20.000+ rule registry** — tidak realistis untuk di-port. Bangun ekosistem sendiri bertahap.

### 9.4 Cross-Reference dengan CONTEXT.md Regrets

Konteks yang diberikan dari `_skills/context-snapshot/Regrets/CONTEXT.md` adalah untuk tool Regrets (output-fingerprint regression testing), **bukan CodeLens**. Regrets dan CodeLens adalah dua tool yang berbeda tapi saling melengkapi:

- **Regrets**: capture input→output function sebagai golden contract, validate setelah refactor. Pendekatan *dynamic* + fingerprinting.
- **CodeLens**: static analysis, AST-based, AI-native. Pendekatan *static* + pattern matching.
- **Semgrep**: static analysis, pattern-based, ecosystem matang. Pendekatan *static* + rule language.

Saran integrasi masa depan (out of scope dokumen ini, tapi catat): CodeLens + Regrets bisa saling mengisi — CodeLens menemukan *code smell*, Regrets memvalidasi *behavior contract* tidak rusak setelah refactor.

---

**Dokumen ini disusun dari analisa langsung terhadap:**
- `https://github.com/Wolfvin/CodeLens.git` (branch `main`, checkout 2026-06-28)
- `https://github.com/semgrep/semgrep.git` (branch `develop`, checkout 2026-06-28)
- `_skills/context-snapshot/Regrets/CONTEXT.md` (konteks tambahan)
