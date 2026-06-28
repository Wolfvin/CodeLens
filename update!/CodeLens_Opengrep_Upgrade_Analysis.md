# CodeLens × Opengrep — Analisis Fitur & Issue Upgrade Plan

> **Repo referensi:** [`opengrep/opengrep`](https://github.com/opengrep/opengrep) (fork LGPL-2.1 dari Semgrep v1.100.0, versi terbaru dianalisa: **v1.23.0**, 18 Jun 2026)
> **Repo target:** `Wolfvin/CodeLens` (analisa commit `main` terbaru)
> **Tanggal analisa:** 2026-06-28
> **Bahasa dokumen:** Indonesia (sesuai input user)
> **Tujuan:** Identifikasi fitur opengrep yang bisa diserap ke CodeLens, daftar peningkatan yang *sudah di-adjust*, dan terbitkan template issue GitHub untuk masing-masing gap.

---

## 0. TL;DR — Ringkasan Eksekutif

CodeLens adalah **AI-native code intelligence** (Python, tree-sitter + regex fallback, 58 command, MCP server 49 tools). Posisinya: *pre-write safety* untuk AI agent, bukan SAST murni. Kekuatan utama: MCP native, guard pre/post-write, plugin YAML sederhana, auto-setup zero-config.

Opengrep adalah **SAST engine matang** (OCaml core + Python CLI, 30+ bahasa, taint analysis interfile, SCA lockfile parsing, autofix deterministic, LSP server, Nuitka self-contained binary, Windows native). Posisinya: pengganti open Semgrep CE setelah Semgrep Inc. memindahkan fitur critical ke lisensi komersial.

**Verdict kunci:** CodeLens **tidak boleh menyalin arsitektur OCaml** opengrep — itu melanggar niche AI-native CodeLens. Yang harus diserap adalah **konsep fitur & DX (developer experience)** yang opengrep punya dan CodeLens belum, terutama:

1. **Pattern matching semantik ala Semgrep** (`pattern: $X.unwrap()`) — saat ini CodeLens hanya punya `search` regex dan rule YAML statis (sources/sinks/sanitizers). Tidak ada *generic pattern language*.
2. **SCA dependency-aware rule** (`project-depends-on`) dengan parsing 18 lockfile format.
3. **Intrafile cross-function taint** dengan signature extractor + call graph topological sort.
4. **`nosem` inline suppression** + custom ignore pattern (`--opengrep-ignore-pattern`).
5. **Per-rule timeout, dynamic timeout, max-match-per-file**.
6. **LSP server beneran** (CodeLens hanya punya `lsp-status` checker, bukan LSP server).
7. **`test` & `validate` command** untuk rule YAML (snapshot testing + schema validation).
8. **Multi-output formatter** (text/json/sarif/gitlab-sast/gitlab-secrets/junit-xml/emacs/vim).
9. **Self-contained binary** via PyInstaller/Nuitka (CodeLens masih `python3 scripts/codelens.py`).
10. **`ci` command** untuk CI/CD integration dengan baseline scan + diff scan.

Detail per-fitur dan issue template ada di Section 4 & 5.

---

## 1. Inventory Fitur CodeLens (current state)

Dihimpun dari `README.md`, `SKILL.md`, `CHANGELOG.md`, `skill.json`, dan source code `scripts/`.

### 1.1 Arsitektur

| Lapisan | Implementasi | Status |
|---|---|---|
| CLI entry | `scripts/codelens.py` (1171 baris, argparse) | ✅ matang |
| Command registry | `scripts/commands/__init__.py` (auto-import, 58 command) | ✅ |
| Engine layer | 41 file `*_engine.py` (avg ~500-3700 LOC) | ✅ |
| Parser layer | 11 tree-sitter parser + 25 fallback regex parser (total 41 file) | ✅ hybrid |
| Registry store | `.codelens/{frontend,backend}.json` + SQLite (`migrate`) | ✅ dual |
| MCP server | `scripts/mcp_server.py` (1934 LOC, JSON-RPC over stdio) | ✅ 49 tools |
| Plugin system | `scripts/plugin_system.py` (4 tipe: rule_pack/engine/formatter/command) | ✅ 3-tier discovery |
| Formatter | `scripts/formatters/{markdown,sarif}.py` | ⚠️ hanya 2 |
| Output | JSON default, `--format ai` normalized, `--lite` minimal | ✅ |
| CI/CD | `.github/workflows/codelens-{ci,quality-gate,sarif,benchmark}.yml` | ✅ 4 workflow |
| Pre-commit hook | `scripts/pre_commit_hook.py` | ✅ |
| VS Code extension | disebut di README tapi tidak ada di repo (separate?) | ⚠️ verifikasi |
| LSP integration | `scripts/lsp_client.py` + `lsp-status` command (client only) | ❌ bukan server |
| Benchmark | `benchmarks/run_benchmarks.py` + fixtures (clean_app, vulnerable_app) | ✅ |

### 1.2 Command categories (58 command, per `skill.json` + listing `scripts/commands/`)

| Kategori | Command | Jumlah |
|---|---|---|
| **Setup** | `init`, `scan`, `validate`, `migrate` | 4 |
| **Pre-write** | `query`, `impact`, `refactor-safe`, `guard` | 4 |
| **Navigation** | `summary`, `context`, `trace`, `search`, `symbols`, `outline`, `dependents`, `list`, `ask`, `missing-refs` | 10 |
| **Architecture** | `entrypoints`, `api-map`, `state-map`, `detect`, `handbook`, `diff`, `circular` | 7 |
| **Security** | `secrets`, `dataflow`, `vuln-scan`, `env-check`, `taint`, `regex-audit`, `binary-scan`, `artifact-scan` | 8 |
| **Quality** | `smell`, `complexity`, `dead-code`, `debug-leak`, `missing-refs`, `side-effect`, `perf-hint`, `css-deep`, `a11y` | 9 |
| **Refactoring** | `test-map`, `stack-trace`, `config-drift`, `ownership`, `type-infer` | 5 |
| **Advanced** | `analyze`, `self-analyze`, `fix` (autofix), `plugin`, `benchmark`, `history`, `dashboard`, `watch`, `serve` (MCP), `lsp-status`, `check` | 11 |

### 1.3 Bahasa yang didukung

- **Tree-sitter full:** HTML, CSS, SCSS, JS, TS, TSX/JSX, Rust, Python, Vue SFC, Svelte, Blade
- **Fallback regex parser (25 bahasa):** C, C++, C#, Dart, Elixir, GDScript, Go, Haskell, HTML, Java, JS, Kotlin, Lua, Nim, ObjC, PHP, Python, R, Ruby, Rust, Scala, Shell, Swift, Vim, Zig, JS frontend, CSS

Catatan: README mengklaim "28+ languages" — itu akurat jika fallback dihitung, tapi untuk taint analysis AST-level hanya **Python, JS, TS, TSX, Rust** yang fully wired (lainnya hanya fallback struktur).

### 1.4 Aturan keamanan (rule YAML)

- `scripts/rules/python_security.yaml` (199 LOC, ~8 rule: SQL inj, cmd inj, path traversal, SSRF, XSS, ...)
- `scripts/rules/javascript_security.yaml` (202 LOC, ~8 rule)
- `scripts/plugins/owasp_top10/rules/owasp_top10.yaml` (907 LOC, 36 rule, OWASP 2021 A01-A10)
- `scripts/plugins/compliance/rules/{hipaa,pci_dss}.yaml` (53 rule)

Schema rule CodeLens:
```yaml
rules:
  - id: py/sql-injection
    name: SQL Injection
    language: python
    severity: critical
    cwe: CWE-89
    message: "..."
    sources: [flask.request.args, ...]
    sinks: [cursor.execute, ...]
    sanitizers: [parameterized_query, ...]
```

**Ini adalah taint rule berbasis daftar nama fungsi, bukan pattern matching.** Tidak ada metavariable, tidak ada `pattern:`, tidak ada `pattern-either`, tidak ada `metavariable-regex`. Inilah gap terbesar vs opengrep.

### 1.5 Taint analysis — yang sudah ada

| Engine | File | Pendekatan | Lokalitas |
|---|---|---|---|
| `semantic_engine.py` | (regex-based v1) | Daftar source/sink statis | intra-file |
| `ast_taint_engine.py` (3756 LOC) | AST tree-sitter, CFG basic block, path-sensitive | intra-file, inter-procedural dalam 1 file |
| `crossfile_taint_engine.py` (947 LOC) | CFG + call graph regex | cross-file, time budget 30s |
| `callgraph_engine.py` (3540 LOC) | Tree-sitter + import resolution + inter-procedural | cross-file, time budget 120s |

Confidence scoring: 0.95+ (direct source→sink), 0.80+ (through call), 0.60+ (partial sanitizer), 0.40+ (indirect).

### 1.6 Vulnerability scanning

- `vulnscan_engine.py` + `osv_client.py` (1616 LOC): OSV.dev API + SQLite cache (TTL 24h, max 100MB), 9 ecosystem (PyPI, npm, Go, Maven, Cargo, NuGet, RubyGems, Pub, Hex), batch query 100/batch, rate limit 10 req/s.
- Native audit fallback: `npm audit --json`, `cargo audit --json`, `pip audit --format json`, `govulncheck ./...`.
- Lockfile parser sendiri: package-lock.json, Cargo.lock, poetry.lock, go.sum.
- **Tidak ada parser** untuk: pnpm-lock.yaml, yarn.lock (v1/v2/v3), Pipfile.lock, Gemfile.lock, composer.lock, packages.lock.json, pubspec.lock, Package.resolved, gradle.lockfile, pom.xml + maven_dep_tree.txt, mix.lock.

### 1.7 Plugin & rule marketplace

- Plugin manifest: `plugin.yaml` (4 tipe: `rule_pack`, `engine`, `formatter`, `command`)
- 3-tier discovery: `.codelens/plugins/` (local, prioritas 30) → `~/.codelens/plugins/` (user, 20) → `scripts/plugins/` (builtin, 10)
- **Marketplace belum aktif**: `REGISTRY_INDEX_URL = "https://registry.codelens.dev/api/v1/plugins"` ada di code tapi domain belum resolve (masih TODO).

### 1.8 Output & integrasi

- Format output: `markdown`, `sarif` (v2.1.0), `ai` (normalized), `lite`
- GitHub Actions: 4 workflow (CI, quality-gate, SARIF upload, benchmark)
- MCP: 49 tool, protocol version 2025-03-26, stdio + optional HTTP/SSE
- Tidak ada formatter: GitLab SAST, GitLab Secrets, JUnit XML, Emacs, Vim, text (plain)

### 1.9 Distribusi

- Install: `bash setup.sh` (pip install tree-sitter + grammar packages)
- Entry: `python3 scripts/codelens.py <command>`
- **Tidak ada binary release**, tidak ada `install.sh`, tidak ada package di PyPI/homebrew/npm.

---

## 2. Inventory Fitur Opengrep (reference)

Dihimpun dari `README.md`, `OPENGREP.md`, `CHANGELOG.md`, struktur `cli/src/semgrep/`, `src/osemgrep/`, `src/{tainting,engine,fixing,sca,targeting,matching,parsing,analyzing,il,call_graph,naming,optimizing,printing}/`, `languages/`, dan `interfaces/`.

### 2.1 Arsitektur

| Lapisan | Implementasi | Catatan |
|---|---|---|
| Core engine | OCaml 5.3.0 (multicore, shared-memory parallelism) | Native binary, bukan Python |
| Python CLI | `cli/src/semgrep/` (click + cmdliner hybrid) | Wrapper + RPC ke core |
| OCaml CLI (osemgrep) | `src/osemgrep/` (cmdliner, menggantikan pysemgrep) | Subcommands: scan, test, validate, lsp, ci, install-ci, login, publish, show |
| Rule parser | `src/parsing/Parse_rule*.ml` + ATD schema `interfaces/` | Schema versioned |
| Pattern matcher | `src/matching/Generic_vs_generic.ml` + `Matching_generic.ml` | Generic AST matching dengan metavariable |
| Taint engine | `src/tainting/` (15 file .ml) | Dataflow + signature extraction + shape inference |
| IL (intermediate lang) | `src/il/` + `src/analyzing/AST_to_IL.ml` | Generic IR untuk cross-language dataflow |
| Call graph | `src/call_graph/` (Call_graph.ml, Graph_reachability.ml, Graph_serialization.ml) | Untuk interfile taint |
| Autofix | `src/fixing/` (Autofix.ml, Autofix_metavar_replacement.ml, Fixed_lines.ml) | Deterministic, metavariable substitution |
| SCA | `src/sca/` + `cli/src/semdep/parsers/` (18 parser) | Lockfile + manifest + transitivity |
| Targeting | `src/targeting/` (Find_targets.ml, Semgrepignore.ml, Filter_target.ml) | `.semgrepignore` file |
| Naming/typing | `src/naming/Naming_AST.ml` + `src/typing/` | Resolution untuk cross-file |
| Optimizing | `src/optimizing/` (Analyze_pattern.ml, Mini_rules_filter.ml, Semgrep_prefilter.atd) | Pattern analysis → prefilter |
| LSP server | `src/osemgrep/language_server/` (LS.ml + requests/notifications/custom_*) | LSP 3.17 compliant |
| Formatters | `cli/src/semgrep/formatter/` (8 format) | text, json, sarif, gitlab-sast, gitlab-secrets, junit-xml, emacs, vim |
| Output | `cli/src/semgrep/output.py` + `core_output.py` | Incremental streaming output |
| Aliengrep | `libs/aliengrep/` | Generic mode (pengganti Spacegrep) untuk file tanpa grammar |
| Distribution | Nuitka self-contained binary + Cosign signed releases | Tidak butuh Python di target |

### 2.2 Bahasa yang didukung (38 bahasa, dari `languages/`)

Apex, Bash, C, C++, C#, Clojure, Crystal, Dart, Dockerfile, Elixir, Go, Hack, HTML, Java, JavaScript, JSON, Jsonnet, JSX, Julia, Kotlin, Lisp, Lua, Move (Aptos+Sui), OCaml, PHP, PromQL, Protobuf, Python, QL, R, Regexp, Ruby, Rust, Scala, Scheme, Solidity, Swift, Terraform, TypeScript, TSX, Visual Basic, YAML, Generic (Aliengrep/Spacegrep)

**Yang tidak ada di CodeLens:** Apex, Bash, C, C++, Clojure, Crystal, Dockerfile, Elixir, Hack, Jsonnet, Julia, Lisp, Move, OCaml, PromQL, Protobuf, QL, R, Regexp, Ruby (fallback only), Scheme, Solidity, Terraform, VB, Generic mode.

### 2.3 Rule schema (penuh, dari `interfaces/Rule_options.atd`)

Opengrep rule YAML mendukung:

- `pattern`, `pattern-either`, `pattern-regex`, `patterns`, `pattern-inside`, `pattern-not-inside`, `pattern-not`, `pattern-not-regex`, `metavariable-pattern`, `metavariable-regex`, `metavariable-comparison`
- `fix`, `fix-regex` (autofix deterministic)
- `paths: { include, exclude }` (per-rule targeting)
- `options:` (per-rule engine config, 20+ field):
  - `constant_propagation`, `symbolic_propagation`
  - `taint_match_on`, `taint_focus_on`, `taint_unify_mvars`
  - `taint_assume_safe_{functions,indexes,comparisons,booleans,numbers}`
  - `taint_only_propagate_through_assignments`
  - `taint_intrafile` (cross-function intrafile taint)
  - `guarded_taint_signatures` (branch-condition guards)
  - `ac_matching`, `commutative_boolop`, `symmetric_eq`
  - `vardef_assign`, `flddef_assign`, `attr_expr`, `unify_ids_strictly`
- `metadata:` (free-form, untuk SARIF tags & custom routing)
- `max-match-per-file` (per-rule match cap)
- `timeout` (per-rule timeout override)
- `dynamic_timeout: true` + `dynamic_timeout_unit_kb` + `dynamic_timeout_max_multiplier`
- `depends-on: { ecosystem, package, version }` (SCA rule — match hanya jika dep vulnerable)
- `join:` (multi-step rule, SQL-like join antar match)

### 2.4 Taint analysis

Dari `src/tainting/`:

- **Object initialization detection** (`Object_initialization.ml`): treat `new Foo()` sebagai taint carrier, track `this.x`/`self.y` per class.
- **Signature extraction** (`Taint_signature_extractor.ml`): summary per function — bagaimana taint mengalir dari param → return/field/global/sink. Topological sort call graph supaya callee di-process sebelum caller.
- **Shape inference** (`Taint_shape.ml`): infer shape variabel (list, dict, set, object) untuk propagation akurat.
- **Guarded signatures** (`Effect_guard.ml` + `Taint_rule_inst.ml`): attach branch-condition ke taint effect, evaluasi di call site (experimental).
- **Taint lambdas** (`Taint_lambdas.ml`): higher-order function support, 12 bahasa.
- **Intrafile mode** (`--taint-intrafile`): cross-function dalam 1 file (mirip Semgrep `--pro-intrafile`).
- **Interfile mode** (`--interfile-timeout N`): cross-file dengan time budget.
- **Taint fixpoint timeout**: deprecated, sekarang adaptive.

### 2.5 SCA (Software Composition Analysis)

- **18 parser lockfile/manifest** (`cli/src/semdep/parsers/`): cargo, composer, gem, go_mod, gradle, mix, package_lock, packages_lock_c_sharp, pipfile, pnpm, poetry, pom_tree, pubspec_lock, requirements, swiftpm, yarn + preprocessor.
- **Matchers** (`cli/src/semdep/matchers/`): base, gradle, pip_requirements (normalisasi nama paket, semver range).
- **Transitivity** (`src/sca/SCA_transitivity.ml`): direct vs transitive dependency.
- **Subproject resolution** (`cli/src/semgrep/resolve_subprojects.py` + `subproject.py`): cari lockfile terdekat per source file.
- **Dependency-aware rule** (`cli/src/semgrep/dependency_aware_rule.py`): rule match hanya jika `depends-on` cocok dengan dependency tree.
- **OSV parsing** untuk lockfile tanpa source code.

### 2.6 Command CLI (dari `src/osemgrep/cli_scan/Scan_CLI.ml` + `cli/src/semgrep/commands/`)

Subcommand utama:

| Command | Fungsi |
|---|---|
| `scan` | Run scan dengan rule config |
| `test` | Snapshot testing untuk rule (`*.test.yaml` + `*.fixed.*`) |
| `validate` | Validasi schema rule YAML + pattern parseability |
| `lsp` | Start LSP server (3.17) |
| `ci` | CI mode: baseline scan + diff scan + upload |
| `install-ci` | Install Semgrep CI di GitHub/GitLab |
| `login` | Auth ke semgrep.dev / opengrep registry |
| `publish` | Publish rule pack ke registry |
| `show` | Dump AST / pattern matching explanation |

### 2.7 CLI flags penting (dari `Scan_CLI.ml` + `commands/scan.py`)

Performance & resource control:
- `--jobs N` (parallelism)
- `--max-memory MB`
- `--timeout SEC`, `--timeout-threshold`, `--interfile-timeout`
- `--dynamic-timeout`, `--dynamic-timeout-unit-kb`, `--dynamic-timeout-max-multiplier`
- `--allow-rule-timeout-control` (enable per-rule `timeout:`)
- `--max-target-bytes`
- `--max-match-per-file`, `--max-chars-per-line`, `--max-lines-per-finding`, `--max-log-list-entries`
- `--optimizations`

Targeting:
- `--include`, `--exclude`, `--force-exclude`
- `--use-git-ignore/--no-git-ignore`
- `--scan-unknown-extensions/--skip-unknown-extensions`
- `--baseline-commit SHA` (diff scan vs commit)
- `--diff-depth N`
- `--opengrep-ignore-pattern <regex>` (custom nosemgrep keyword)
- `--semgrepignore-filename <name>`

Output:
- `--text`, `--json`, `--sarif`, `--gitlab-sast`, `--gitlab-secrets`, `--junit-xml`, `--emacs`, `--vim`
- `--output FILE`, `--incremental-output`, `--incremental-output-postprocess`
- `--files-with-matches`
- `--dataflow-traces` (render taint path di SARIF)
- `--inline-metavariables` (substitusi metavar di metadata)
- `--output-enclosing-context` (laporkan function/class enclosing match)

Engine:
- `--pro`, `--pro-languages`, `--pro-path-sensitive`
- `--taint-intrafile`
- `--guarded-taint-signatures`
- `--oss-only`
- `--secrets` (secret detection mode)
- `--no-secrets-validation`, `--historical-secrets`, `--allow-untrusted-validators`, `--allow-local-builds`

Autofix:
- `--autofix/--no-autofix`
- `--replacement STR`

Rule source:
- `--config PATH|URL|auto`, `--pattern STR`, `--lang LANG`
- `--severity ERROR|WARNING|INFO`
- `--exclude-rule ID`

### 2.8 Inline suppression & ignore

- `# nosemgrep` (default keyword) — suppress single-line finding
- `# nosemgrep: rule-id-1, rule-id-2` — selective suppression
- `--opengrep-ignore-pattern <regex>` — custom keyword (mis. `# codelens-ignore`)
- `.semgrepignore` file (mirip `.gitignore`, ditangani `src/targeting/Semgrepignore.ml`)
- `--semgrepignore-filename <name>` — custom ignore filename

### 2.9 Distribusi & release

- `install.sh` (Linux/macOS) + `install.ps1` (Windows) — download binary dari GitHub releases
- Nuitka self-contained binary (tidak butuh Python runtime di target)
- Cosign signing untuk release artifacts (verifikasi provenance)
- Native Windows support (sejak fork, sebelumnya process-fork parallelism tidak jalan di Windows)
- Release channel: GitHub Releases, dengan versioning semver ketat

### 2.10 LSP server capabilities (dari `src/osemgrep/language_server/LS.ml`)

- LSP 3.17 compliant
- File operation filters (create/rename/delete)
- Custom requests & notifications (folder `custom_requests/`, `custom_commands/`)
- Diagnostics publish (publishDiagnostics)
- Code actions (autofix suggestions)
- Hover (rule documentation)
- Workspace folders support

### 2.11 Test & validate command

**`semgrep test`** (`src/osemgrep/cli_test/Test_subcommand.ml`):
- Snapshot testing: `rule.yaml` + `target.py` + `target.expected.json`
- Fixtest: `target.py` + `target.fixed.py` (verifikasi autofix output)
- Diagnosis: diff actual vs expected, report pass/fail per rule
- Multi-target support (sejak fork)
- `--test-ignore-todo/--no-test-ignore-todo` (skip TODO markers)

**`semgrep validate`** (`src/osemgrep/cli_validate/Validate_subcommand.ml`):
- YAML syntax check
- Schema validation (Parse_rule.ml + jsonschema fallback)
- Pattern parseability check (compile pattern ke AST, cek error)
- `--pro` flag untuk validate pro-language patterns

---

## 3. Gap Analysis — CodeLens vs Opengrep

Skala: 🔴 (CodeLens tidak punya, opengrep punya matang) · 🟡 (CodeLens punya sebagian/lo-fi) · 🟢 (CodeLens sudah setara atau lebih baik)

| # | Kapabilitas | CodeLens | Opengrep | Gap severity |
|---|---|---|---|---|
| 1 | **Pattern matching semantik** (`pattern: $X.unwrap()`) | 🔴 tidak ada, hanya `search` regex + rule source/sink statis | 🟢 full Generic_vs_generic matcher | 🔴 critical |
| 2 | **Metavariable capture & substitution** | 🔴 tidak ada | 🟢 `$X`, `$...ARGS`, typed metavar | 🔴 critical |
| 3 | **Pattern combinator** (`pattern-either`, `pattern-inside`, `pattern-not`) | 🔴 tidak ada | 🟢 full | 🔴 critical |
| 4 | **`metavariable-regex` / `metavariable-comparison`** | 🔴 tidak ada | 🟢 full | 🔴 high |
| 5 | **Intrafile cross-function taint** (signature extraction) | 🟡 `ast_taint_engine.py` punya inter-proc dalam 1 file, tapi tanpa signature extraction & topological sort | 🟢 `--taint-intrafile` + `Taint_signature_extractor.ml` | 🟡 medium |
| 6 | **Interfile taint dengan call graph** | 🟡 `callgraph_engine.py` ada (3540 LOC), tapi import resolution masih best-effort | 🟢 `src/call_graph/` matang + Graph_reachability | 🟡 medium |
| 7 | **Higher-order function / lambda taint** | 🔴 tidak ada | 🟢 `Taint_lambdas.ml`, 12 bahasa | 🔴 high |
| 8 | **Guarded taint signatures** (branch-condition) | 🔴 tidak ada | 🟢 experimental `Effect_guard.ml` | 🟡 medium |
| 9 | **SCA: lockfile parser breadth** | 🟡 4 format (package-lock, Cargo.lock, poetry.lock, go.sum) | 🟢 18 format (semua ecosystem) | 🔴 high |
| 10 | **SCA: dependency-aware rule** (`depends-on`) | 🔴 tidak ada | 🟢 `dependency_aware_rule.py` | 🔴 high |
| 11 | **SCA: transitivity (direct vs transitive)** | 🔴 tidak ada | 🟢 `SCA_transitivity.ml` | 🟡 medium |
| 12 | **SCA: subproject resolution** | 🔴 tidak ada | 🟢 `resolve_subprojects.py` | 🟡 medium |
| 13 | **Autofix deterministic** (`fix:` + metavariable) | 🟡 `autofix_engine.py` ada (5 kategori: secrets_mask, dead_code, debug_leak, import_cleanup, todo_fixme) — tapi fix-nya hardcoded per kategori, bukan dari rule | 🟢 `fix:` field di rule YAML + `Autofix_metavar_replacement.ml` | 🔴 high |
| 14 | **Inline suppression** (`nosem`) | 🔴 tidak ada | 🟢 `nosemgrep.py` + custom pattern | 🔴 high |
| 15 | **`.semgrepignore` file** | 🟡 ada `DEFAULT_IGNORE_DIRS` di `utils.py` (hardcoded list) | 🟢 `.semgrepignore` file + `Semgrepignore.ml` parser | 🟡 medium |
| 16 | **Per-rule timeout** | 🔴 tidak ada (hanya global signal timeout di secrets engine) | 🟢 `timeout:` field + `--allow-rule-timeout-control` | 🔴 high |
| 17 | **Dynamic timeout** (scale with file size) | 🔴 tidak ada | 🟢 `--dynamic-timeout` + unit_kb + max_multiplier | 🟡 medium |
| 18 | **`max-match-per-file`** | 🔴 tidak ada (hanya global `--top N`) | 🟢 per-rule option | 🟡 medium |
| 19 | **LSP server** (publish diagnostics, code actions) | 🔴 hanya `lsp-status` checker + `lsp_client.py` (client ke LSP eksternal) | 🟢 full LSP 3.17 server | 🔴 high |
| 20 | **`test` command** (snapshot testing rule) | 🔴 tidak ada (benchmark ada, tapi bukan rule test) | 🟢 `Test_subcommand.ml` | 🔴 high |
| 21 | **`validate` command** (rule schema validation) | 🔴 `validate` command CodeLens beda — validate registry vs filesystem, bukan validate rule YAML | 🟢 `Validate_subcommand.ml` | 🔴 high |
| 22 | **Multi-output formatter** | 🟡 2 format (markdown, sarif) | 🟢 8 format (text, json, sarif, gitlab-sast, gitlab-secrets, junit-xml, emacs, vim) | 🔴 high |
| 23 | **Incremental output streaming** | 🔴 tidak ada (semua output di akhir) | 🟢 `--incremental-output` + `--incremental-output-postprocess` | 🟡 medium |
| 24 | **`--dataflow-traces`** (render taint path di SARIF) | 🟡 CodeLens render taint path di JSON output, tapi belum di SARIF | 🟢 full | 🟡 medium |
| 25 | **`--output-enclosing-context`** | 🔴 tidak ada | 🟢 laporkan class/function enclosing match | 🟡 medium |
| 26 | **`--inline-metavariables`** | 🔴 tidak ada (karena tidak ada metavar) | 🟢 substitusi metavar value di metadata | 🟢 N/A (gap tidak relevan sebelum #1/#2) |
| 27 | **`baseline-commit` + diff scan** | 🟡 `diff` command compare snapshot registry, bukan diff source vs commit | 🟢 `--baseline-commit SHA` + `--diff-depth N` | 🟡 medium |
| 28 | **`ci` command** (CI orchestration) | 🟡 ada GitHub Actions workflow, tapi tidak ada `ci` command yang orchestrate | 🟢 `commands/ci.py` + `install-ci` | 🟡 medium |
| 29 | **`publish` command** (rule registry upload) | 🔴 marketplace URL ada tapi belum aktif | 🟢 `commands/publish.py` ke semgrep.dev | 🟡 medium |
| 30 | **`login` command** (auth) | 🔴 tidak ada | 🟢 `commands/login.py` | 🟡 low |
| 31 | **Self-contained binary** | 🔴 `python3 scripts/codelens.py` only | 🟢 Nuitka + Cosign | 🔴 high (UX) |
| 32 | **Native Windows support** | ⚠️ Python cross-platform, tapi tidak di-test; pre-commit hook asumsi Unix | 🟢 native sejak fork | 🟡 medium |
| 33 | **Generic mode (Aliengrep)** untuk file tanpa grammar | 🔴 tidak ada (fallback regex parser per bahasa) | 🟢 `libs/aliengrep/` (pengganti Spacegrep) | 🟡 medium |
| 34 | **Constant propagation** | 🟡 `typeinfer_engine.py` ada type inference, bukan constant propagation di matcher | 🟢 `Dataflow_svalue.ml` + `Constant_propagation.ml` + `options.constant_propagation` | 🟡 medium |
| 35 | **Symbolic propagation** | 🔴 tidak ada | 🟢 `options.symbolic_propagation` | 🟡 medium |
| 36 | **Equivalence rules** (`equivalences:` field) | 🔴 tidak ada | 🟢 `Parse_equivalences.ml` | 🟡 low |
| 37 | **Join mode** (multi-step rule) | 🔴 tidak ada | 🟢 `cli/src/semgrep/join_rule.py` (SQL-like join antar match) | 🟡 medium |
| 38 | **Generic AST (`AST_generic.ml`)** unified cross-lang | 🟡 setiap parser tree-sitter punya transform sendiri ke registry CodeLens | 🟢 satu AST_generic untuk semua bahasa | 🔴 high (arsitektur) |
| 39 | **Rule `metadata:` field** (free-form, SARIF tags) | 🟡 rule CodeLens punya `cwe`, `owasp`, `severity` — tidak free-form metadata | 🟢 `metadata:` dict bebas | 🟡 medium |
| 40 | **`paths: { include, exclude }`** per-rule | 🔴 tidak ada (hanya global ignore) | 🟢 per-rule targeting | 🟡 medium |
| 41 | **Performance: parallelism** | 🔴 single-threaded scan | 🟢 OCaml 5.3 multicore + `--jobs N` | 🔴 high (perf) |
| 42 | **Performance: pattern prefilter** | 🔴 scan semua rule untuk semua file | 🟢 `Mini_rules_filter.ml` + `Analyze_pattern.ml` (skip file yang tidak mungkin match) | 🟡 medium |
| 43 | **Community rule registry** (r2c rules) | 🔴 marketplace TODO | 🟢 ribuan rule publik di semgrep.dev/r/opengrep | 🔴 high (ecosystem) |
| 44 | **MCP server** | 🟢 native, 49 tools, JSON-RPC | 🔴 tidak ada (Semgrep Inc. punya App API, bukan MCP) | 🟢 **CodeLens unggul** |
| 45 | **AI-optimized output** (`--format ai`, `--lite`, `--top N`) | 🟢 native | 🔴 tidak ada | 🟢 **CodeLens unggul** |
| 46 | **Guard pre/post-write hook** | 🟢 native (`guard` command) | 🔴 tidak ada | 🟢 **CodeLens unggul** |
| 47 | **Auto-setup zero-config** | 🟢 init+scan otomatis jika registry belum ada | 🟡 ada `--config auto` tapi tidak auto-bootstrap | 🟢 **CodeLens unggul** |
| 48 | **Workspace auto-detect** | 🟢 walk-up parent dir + last workspace cache | 🟡 `--project-root` manual | 🟢 **CodeLens unggul** |
| 49 | **Frontend analysis** (CSS deep, a11y, Tailwind) | 🟢 native | 🔴 tidak ada (bukan niche SAST) | 🟢 **CodeLens unggul** |
| 50 | **Code intelligence** (call graph, impact, refactor-safe) | 🟢 native | 🟡 call graph ada tapi untuk taint, bukan untuk refactor analysis | 🟢 **CodeLens unggul** |

### Ringkasan gap count

- 🔴 critical/high gap: **20 item** (sebagian besar di pattern matching, SCA, autofix, suppression, LSP, test/validate)
- 🟡 medium gap: **17 item**
- 🟢 CodeLens unggul: **7 item** (MCP, AI output, guard, auto-setup, workspace detect, frontend, code intelligence)

---

## 4. Peningkatan yang SUDAH Di-adjust untuk CodeLens

Berikut adalah fitur-fitur opengrep yang **secara konseptual sudah ada di CodeLens** dengan pendekatan berbeda (sehingga tidak perlu diserap 1:1), atau sudah disesuaikan dengan niche AI-native CodeLens:

### 4.1 ✅ Output SARIF v2.1.0 — sudah ada
- CodeLens: `scripts/formatters/sarif.py` (443 LOC), mapping severity → level/rank, GitHub code scanning upload via `codelens-sarif.yml`
- Opengrep: `cli/src/semgrep/formatter/sarif.py` (118 LOC, RPC ke OCaml)
- **Sudah adjusted**: CodeLens generate SARIF langsung dari Python, tidak butuh RPC ke core OCaml. Yang perlu ditambah: `--dataflow-traces` rendering di SARIF (saat ini hanya di JSON).

### 4.2 ✅ Plugin system (4 tipe) — sudah ada, malah lebih kaya dari opengrep rule_pack-only
- CodeLens: `rule_pack`, `engine`, `formatter`, `command` (4 tipe), 3-tier discovery
- Opengrep: hanya rule_pack (rule YAML), tidak ada plugin engine/formatter/command
- **Sudah adjusted**: CodeLens lebih fleksibel. Yang perlu ditambah: marketplace URL aktif (saat ini `REGISTRY_INDEX_URL` masih TODO).

### 4.3 ✅ Security rule pack (OWASP Top 10 + Compliance) — sudah ada
- CodeLens: 36 OWASP rule + 53 compliance rule (HIPAA, PCI-DSS) — total 89 rule
- Opengrep: ribuan rule di registry, tapi OWASP/compliance pack-nya tersebar
- **Sudah adjusted**: CodeLens punya pack kurated builtin. Yang perlu ditambah: rule schema yang support pattern matching (saat ini hanya source/sink list).

### 4.4 ✅ Taint analysis AST-level — sudah ada (3 generasi)
- CodeLens: `semantic_engine.py` (v1 regex) → `ast_taint_engine.py` (v2 CFG tree-sitter, 3756 LOC) → `crossfile_taint_engine.py` (v3 cross-file) → `callgraph_engine.py` (v4 tree-sitter + import resolution, 3540 LOC)
- Opengrep: `src/tainting/` (15 file OCaml, signature extraction + shape + guard)
- **Sudah adjusted**: CodeLens punya 4 generasi engine. Yang perlu diserap: signature extraction pattern (topological sort callee-before-caller) dan higher-order function support.

### 4.5 ✅ Vulnerability scanning (OSV.dev) — sudah ada
- CodeLens: `osv_client.py` (1616 LOC) + SQLite cache + 9 ecosystem + native audit fallback
- Opengrep: `src/sca/` + `cli/src/semdep/` (18 lockfile parser + transitivity)
- **Sudah adjusted**: CodeLens punya OSV integration matang. Yang perlu diserap: 14 lockfile parser tambahan (pnpm, yarn v1-3, Pipfile, Gemfile, composer, packages.lock.json, pubspec, Package.resolved, gradle, pom_tree, mix) + transitivity + subproject resolution.

### 4.6 ✅ Incremental scanning — sudah ada
- CodeLens: `scripts/incremental.py` (find changed files, merge registry, mtime cache)
- Opengrep: `--incremental-output` (streaming output, beda konsep — incremental output, bukan incremental scan)
- **Sudah adjusted**: CodeLens incremental scan lebih dekat ke `--baseline-commit` opengrep. Yang perlu ditambah: streaming output incremental (emit finding saat ketemu, bukan tunggu scan selesai).

### 4.7 ✅ Pre-commit hook — sudah ada
- CodeLens: `scripts/pre_commit_hook.py` (131 LOC, config `.codelens/pre-commit.yaml`)
- Opengrep: tidak ada pre-commit hook native (pakai `semgrep-action` GitHub Action)
- **Sudah adjusted**: CodeLens lebih unggul di sini.

### 4.8 ✅ GitHub Actions workflows — sudah ada (4 workflow)
- CodeLens: `codelens-ci.yml`, `codelens-quality-gate.yml`, `codelens-sarif.yml`, `codelens-benchmark.yml`
- Opengrep: tidak ship workflow di repo (user pakai `semgrep-action` dari marketplace)
- **Sudah adjusted**: CodeLens ship workflow siap pakai. Yang perlu ditambah: `install-ci` command yang orchestrate setup workflow otomatis.

### 4.9 ✅ Framework auto-detection — sudah ada, malah lebih kaya
- CodeLens: `framework_detect.py` — React/Next.js, Vue/Nuxt, Svelte/SvelteKit, Tailwind, Express, Fastify, Koa, Hono, Django, Flask, FastAPI, pytest, poetry, setuptools, tox, sphinx, nox, hatch, Tauri, Drupal, C/CMake, Lua
- Opengrep: tidak ada framework detection (SAST tidak butuh ini)
- **Sudah adjusted**: CodeLens unggul. Tidak perlu serap.

### 4.10 ✅ MCP server — CodeLens unggul
- CodeLens: 49 tool, MCP 2025-03-26, stdio + HTTP/SSE
- Opengrep: tidak ada MCP server (Semgrep Inc. punya App API proprietary)
- **Sudah adjusted**: ini adalah **differentiator utama CodeLens**. Tidak perlu serap.

### 4.11 ✅ AI-optimized output (`--format ai`, `--lite`, `--top N`, `--max-tokens N`) — CodeLens unggul
- CodeLens: normalized schema `{stats, items[], truncated, recommendations}`, per-command lite mode, smart sort
- Opengrep: tidak ada equivalent (output human-centric atau SARIF)
- **Sudah adjusted**: differentiator. Tidak perlu serap.

### 4.12 ✅ Guard pre/post-write hook — CodeLens unggul (killer feature)
- CodeLens: `guard pre --file X --symbol Y --action create`, `guard post --file X --diff ...`, `guard snapshot`, `guard verify`
- Opengrep: tidak ada equivalent
- **Sudah adjusted**: differentiator. Tidak perlu serap.

### 4.13 ✅ Auto-setup zero-config — CodeLens unggul
- CodeLens: auto `init` + `scan` jika registry belum ada, dengan `--max-files 3000` cap
- Opengrep: `--config auto` download dari registry, tidak auto-bootstrap
- **Sudah adjusted**: differentiator. Tidak perlu serap.

### 4.14 ✅ Workspace auto-detect — CodeLens unggul
- CodeLens: walk-up 10 level parent + last workspace cache (`~/.codelens/.codelens_last_workspace`)
- Opengrep: `--project-root` manual
- **Sudah adjusted**: differentiator. Tidak perlu serap.

### 4.15 ✅ Frontend analysis (CSS deep, a11y, Tailwind, Vue/Svelte) — CodeLens unggul
- CodeLens: `cssdeep_engine.py`, `a11y_engine.py` (WCAG 2.1), `tailwind_detector.py`, Vue/Svelte parser
- Opengrep: tidak ada (bukan niche SAST)
- **Sudah adjusted**: differentiator. Tidak perlu serap.

### 4.16 ✅ Code intelligence (call graph, impact, refactor-safe, trace) — CodeLens unggul
- CodeLens: `callgraph_engine.py`, `impact_engine.py`, `refactor_safe_engine.py`, `trace_engine.py` (bidirectional, depth-controlled)
- Opengrep: call graph ada tapi untuk taint, bukan untuk refactor analysis
- **Sudah adjusted**: differentiator. Tidak perlu serap.

---

## 5. Issue Template — Serap Fitur Opengrep ke CodeLens

Setiap issue di bawah sudah diformat siap copy-paste ke GitHub issue tracker `Wolfvin/CodeLens`. Urutan berdasarkan prioritas (P0 = critical, P1 = high, P2 = medium, P3 = low).

### 📋 Issue #1 [P0] — Semantic Pattern Matching Engine (`pattern:` field di rule YAML)

```markdown
**Title:** [P0] Implement semantic pattern matching engine (Semgrep-compatible `pattern:` syntax)

## Motivation
CodeLens saat ini hanya punya 2 mekanisme deteksi:
1. `search` command — regex literal, tidak understanding AST
2. Rule YAML `sources/sinks/sanitizers` — daftar nama fungsi statis

Tidak ada cara untuk menulis pattern semantik seperti `pattern: $X.unwrap()` atau `pattern: eval($INPUT)`. Ini adalah gap terbesar vs opengrep/Semgrep dan membatasi ekspresifitas rule CodeLens secara fundamental.

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi:
  - `src/matching/Generic_vs_generic.ml` (core matcher)
  - `src/matching/Matching_generic.ml` (metavariable binding)
  - `libs/ast_generic/AST_generic.ml` (unified AST)
  - `src/parsing/Parse_pattern.ml` (pattern parser)
  - `scripts/cheatsheet.json` (pattern examples)

## Acceptance Criteria
- [ ] Tambahkan field `pattern` di rule YAML schema CodeLens (kompatibel dengan format Semgrep dasar)
- [ ] Support metavariable sederhana: `$X`, `$VAR`, `$...ARGS` (rest/variadic)
- [ ] Support pattern combinator minimal: `pattern`, `pattern-either`, `pattern-not`
- [ ] Matcher bekerja di atas tree-sitter AST (bukan regex) untuk Python, JS, TS, Rust (4 bahasa awal)
- [ ] Integrasi dengan `taint` command: rule dengan `pattern:` bisa di-run via `codelens taint --rules my-rule.yaml`
- [ ] Dokumentasi: tambah `references/pattern-syntax.md` dengan 20+ contoh
- [ ] Test: snapshot test untuk 50 pattern (positive + negative case)

## Implementation Notes
- **Jangan** port OCaml matcher ke Python 1:1 (terlalu berat). Implementasi Python native di atas tree-sitter AST sudah cukup untuk v1.
- Pertimbangkan library `tree_sitter` query language (S-expression) sebagai backbone, tambahkan layer syntactic sugar agar mirip Semgrep pattern.
- unified AST: CodeLens belum punya `AST_generic` unified. Untuk v1, bisa buat matcher per-bahasa dengan shared interface.

## Non-goals
- Tidak perlu kompatibel 100% dengan Semgrep pattern syntax (80% cukup)
- Tidak perlu pattern-inside/pattern-not-inside di v1 (v2)
- Tidak perlu metavariable-pattern/metavariable-regex di v1 (v2)

## Priority
P0 — ini adalah fondasi untuk semua issue SAST berikutnya.
```

---

### 📋 Issue #2 [P0] — Metavariable Capture & Substitution

```markdown
**Title:** [P0] Metavariable capture, binding, and substitution in pattern matching

## Motivation
Menyusul Issue #1. Tanpa metavariable, pattern matching tidak lebih berguna dari regex. Metavariable (`$X`) memungkinkan:
- Capture value untuk reporting (e.g., "eval() called with: $X = user_input")
- Substitution untuk autofix (e.g., ganti `$X.unwrap()` → `$X.unwrap_or_default()`)
- Constraint propagation (e.g., `metavariable-regex: $X must match ^user_`)

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi:
  - `src/matching/Matching_generic.ml` (metavariable env)
  - `src/fixing/Autofix_metavar_replacement.ml` (substitution di fix)
  - `interfaces/Rule_options.atd` (options.taint_unify_mvars dll)

## Acceptance Criteria
- [ ] Metavariable binding: `$X` capture AST node (expression, statement, atau type)
- [ ] Rest metavariable: `$...ARGS` capture zero atau lebih argumen
- [ ] Typed metavariable (v2): `$X: string` hanya match string literal
- [ ] Metavariable env: disimpan per-match, bisa diakses di `message`, `fix`, dan output JSON
- [ ] `--inline-metavariables` flag: substitusi metavar value di `metadata` JSON output
- [ ] Test: 30+ case untuk binding, 10+ untuk rest, 5+ untuk typed

## Implementation Notes
- Metavariable env = `Dict[str, ASTNode]`, di-merge saat nested match
- Rest metavar bind ke list ASTNode, join dengan `, ` saat substitution string
- Untuk typed metavar, cek `node.type` tree-sitter setelah match

## Priority
P0 — blocker untuk Issue #3 (autofix dari rule), #5 (metavariable-regex).
```

---

### 📋 Issue #3 [P1] — Autofix dari Rule YAML (`fix:` field)

```markdown
**Title:** [P1] Rule-driven autofix via `fix:` and `fix-regex:` field

## Motivation
CodeLens sudah punya `autofix_engine.py` dengan 5 kategori hardcoded (secrets_mask, dead_code, debug_leak, import_cleanup, todo_fixme). Tapi tidak ada cara untuk user mendefinisikan fix di rule YAML — fix terikat ke kategori engine, bukan ke rule.

Opengrep support `fix: "replacement string with $X"` dan `fix-regex:` (regex-based substitution) di setiap rule. Ini memungkinkan ribuan rule komunitas dengan fix siap pakai.

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi:
  - `src/fixing/Autofix.ml` + `Autofix_metavar_replacement.ml` (OCaml core)
  - `cli/src/semgrep/autofix.py` (Python wrapper, RPC ke core)
  - `src/fixing/Fixed_lines.ml` (line-level patch application)
  - `src/fixing/Hybrid_print.ml` (diff rendering)

## Current State
- `scripts/autofix_engine.py` (740 LOC) — 5 kategori, confidence scoring, dry-run, risk assessment
- `scripts/commands/fix.py` — `--categories`, `--dry-run`, `--apply`, `--min-confidence`, `--max-risk`

## Acceptance Criteria
- [ ] Field `fix: "string"` di rule YAML — replacement string dengan metavariable substitution
- [ ] Field `fix-regex: { regex, replacement, count }` — regex-based substitution (untuk pattern yang tidak bisa di-express dengan template string)
- [ ] Integrasi dengan `codelens fix --rules my-rule.yaml` — apply fix dari rule
- [ ] Diff output (unified diff format) saat `--dry-run`
- [ ] Conflict detection: jika 2 fix overlap, lapor dan skip
- [ ] Fix history audit trail (sudah ada di `autofix_engine.py`, extend untuk rule-driven fix)
- [ ] Test: snapshot test dengan `target.py` + `target.fixed.py` (mirip `semgrep test`)

## Implementation Notes
- Reuse `autofix_engine.py` confidence/risk framework — rule-driven fix default `confidence: 0.85, risk: safe`
- Fix string parsing: cari `$X` di string, substitusi dari metavariable env (Issue #2)
- Untuk fix-regex, gunakan `re.sub` dengan count parameter

## Priority
P1 — depend on Issue #1, #2.
```

---

### 📋 Issue #4 [P1] — Inline Suppression (`nosem` equivalent)

```markdown
**Title:** [P1] Inline suppression annotation (`# codelens-ignore`)

## Motivation
CodeLens tidak punya cara untuk suppress finding secara inline. User harus edit `.codelens/config.json` ignore list atau disable rule sepenuhnya. Opengrep/semgrep punya `# nosemgrep` yang sangat populer:

```python
eval(user_input)  # nosemgrep: py/eval-injection
```

Tanpa fitur ini, false positive noise di codebase besar menjadi masalah adopsi.

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi:
  - `cli/src/semgrep/nosemgrep.py` (filter logic)
  - `--opengrep-ignore-pattern <regex>` CLI flag (custom keyword)
  - `--semgrepignore-filename <name>` (custom ignore filename)

## Acceptance Criteria
- [ ] Default keyword: `codelens-ignore` (lebih brandable dari `nosem`)
- [ ] Syntax: `<code>  // codelens-ignore: rule-id-1, rule-id-2` (suppress specific rule)
- [ ] Syntax: `<code>  // codelens-ignore` (suppress semua rule di baris ini)
- [ ] Multi-line: `/* codelens-ignore-next: rule-id */` di baris sebelum finding
- [ ] `--codelens-ignore-pattern <regex>` flag — custom keyword (mis. untuk kompatibilitas dengan `nosemgrep`)
- [ ] Finding yang di-suppress tetap di-report dengan `status: suppressed` (bukan dihilangkan), agar audit-able
- [ ] SARIF output: gunakan `suppressions` field per SARIF spec
- [ ] Test: 20+ case untuk berbagai syntax + edge case (comment di string, nested comment, dll)

## Implementation Notes
- Detect comment per-bahasa di parser layer (sudah ada tree-sitter comment node)
- Cek pattern `codelens-ignore(:\s*([\w-, ]+))?` di comment text
- Simpan suppression info di registry finding, filter di output layer
- Untuk fallback regex parser, scan baris yang sama dengan finding line

## Priority
P1 — quick win, high UX impact.
```

---

### 📋 Issue #5 [P1] — Per-rule Timeout & Dynamic Timeout

```markdown
**Title:** [P1] Per-rule timeout override and dynamic timeout (scale with file size)

## Motivation
CodeLens saat ini hanya punya global signal timeout di `secrets_engine.py` (`PER_FILE_REGEX_TIMEOUT = 5s`) dan global time budget di `callgraph_engine.py` (120s). Tidak ada per-rule timeout.

Masalah: rule yang complex (taint cross-file, multi-pattern) bisa hang di file besar tanpa cara untuk user batasi. Opengrep punya:
- `timeout:` field per-rule (override global `--timeout`)
- `--dynamic-timeout` (scale timeout dengan file size, mis. 1s per 10KB, max 5x)
- `--dynamic-timeout-unit-kb` + `--dynamic-timeout-max-multiplier` (fine-tune)
- `--allow-rule-timeout-control` (security: rule untrusted tidak bisa set timeout infinite)

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi:
  - `cli/src/semgrep/commands/scan.py` (CLI flag parsing)
  - `src/osemgrep/cli_scan/Scan_CLI.ml` (OCaml CLI, line `dynamic-timeout*`)
  - `interfaces/Rule_options.atd` (rule option schema)

## Acceptance Criteria
- [ ] Field `timeout: <seconds>` di rule YAML — per-rule timeout override
- [ ] Global `--timeout <seconds>` CLI flag (default: 30s)
- [ ] Global `--dynamic-timeout` flag — enable size-scaled timeout
- [ ] `--dynamic-timeout-unit-kb <KB>` (default: 10) — basis ukuran
- [ ] `--dynamic-timeout-max-multiplier <N>` (default: 5) — cap multiplier
- [ ] `--allow-rule-timeout-control/--forbid-rule-timeout-control` flag (default: forbid, untuk keamanan rule untrusted)
- [ ] Finding yang timeout di-report sebagai `status: timeout, rule_id: X` (bukan silent skip)
- [ ] Test: rule dengan `timeout: 0.1` di file 10KB harus timeout

## Implementation Notes
- Pakai `signal.alarm` (Unix) atau `threading.Timer` (cross-platform) — CodeLens sudah pakai signal di `secrets_engine.py`
- Dynamic timeout formula: `effective = min(global_timeout, base + (file_size_kb * unit_kb * multiplier))`
- Log timeout event untuk profiling

## Priority
P1 — prevent hang di production, critical untuk CI adoption.
```

---

### 📋 Issue #6 [P1] — SCA: 14 Lockfile Parser Tambahan

```markdown
**Title:** [P1] SCA: tambah 14 lockfile parser (pnpm, yarn, Pipfile, Gemfile, composer, NuGet, pubspec, SwiftPM, gradle, maven, mix, ...)

## Motivation
CodeLens `vulnscan_engine.py` + `osv_client.py` sudah support 9 ecosystem via OSV.dev API, tapi parser lockfile hanya 4 format:
- ✅ package-lock.json (npm)
- ✅ Cargo.lock (Rust)
- ✅ poetry.lock (Python)
- ✅ go.sum (Go)

Opengrep support 18 format (`cli/src/semdep/parsers/`). Gap 14 format:
- ❌ pnpm-lock.yaml (v6, v9, workspace)
- ❌ yarn.lock (v1, v2, v3)
- ❌ Pipfile.lock
- ❌ Gemfile.lock
- ❌ composer.lock
- ❌ packages.lock.json (NuGet)
- ❌ pubspec.lock (Dart)
- ❌ Package.resolved (SwiftPM v1/v2/v3)
- ❌ gradle.lockfile + build.gradle (maven_dep_tree.txt)
- ❌ pom.xml + maven_dep_tree.txt
- ❌ mix.lock (Elixir)
- ❌ requirements.txt (parsing kompleks dengan comparator)
- ❌ Pipfile (manifest, bukan lock)
- ❌ pyproject.toml (Poetry dependencies)

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi (salin struktur, port ke Python):
  - `cli/src/semdep/parsers/pnpm.py`
  - `cli/src/semdep/parsers/yarn.py`
  - `cli/src/semdep/parsers/pipfile.py`
  - `cli/src/semdep/parsers/gem.py`
  - `cli/src/semdep/parsers/composer.py`
  - `cli/src/semdep/parsers/packages_lock_c_sharp.py`
  - `cli/src/semdep/parsers/pubspec_lock.py`
  - `cli/src/semdep/parsers/swiftpm.py`
  - `cli/src/semdep/parsers/gradle.py`
  - `cli/src/semdep/parsers/pom_tree.py`
  - `cli/src/semdep/parsers/mix.py`
  - `cli/src/semdep/parsers/requirements.py`
  - `cli/src/semdep/matchers/pip_requirements.py` (semver range matching)

## Acceptance Criteria
- [ ] 14 parser baru di `scripts/parsers/lockfile_*_parser.py`
- [ ] Setiap parser return `List[Dependency]` dengan field: `name, version, ecosystem, source_file, transitivity`
- [ ] Integrasi dengan `vulnscan_engine.py`: lockfile baru otomatis di-scan
- [ ] Integrasi dengan `osv_client.py`: batch query untuk dependency baru
- [ ] Test fixture: 1 sample lockfile per format (ambil dari `cli/tests/default/e2e/targets/dependency_aware/` opengrep)
- [ ] Edge case: lockfile malformed, empty, nested workspace, comment

## Implementation Notes
- Jangan import `semdep` Python package langsung (license LGPL, tapi coupling). Port logic ke CodeLens native.
- `requirements.txt` paling tricky (matcher di `cli/src/semdep/matchers/pip_requirements.py` punya normalisasi nama paket PEP 503 + semver range PEP 440).
- Untuk gradle & maven: perlu `gradle dependencies` / `mvn dependency:tree` output parsing (bukan parse build.gradle langsung — terlalu complex).

## Priority
P1 — critical untuk SCA coverage parity.
```

---

### 📋 Issue #7 [P1] — SCA: Dependency-Aware Rule (`depends-on`)

```markdown
**Title:** [P1] SCA: dependency-aware rule (`project-depends-on` field)

## Motivation
CodeLens `vuln-scan` cek apakah dependency punya CVE. Tapi tidak bisa nulis rule seperti "jika project depend on `log4j < 2.17`, laporkan finding di semua file Java". Opengrep punya:

```yaml
rules:
  - id: java.log4j.log4shell
    patterns:
      - pattern: Jndi.lookup($X)
    project-depends-on:
      - namespace: maven
        package: org.apache.logging.log4j:log4j-core
        version: "< 2.17.0"
    severity: CRITICAL
    message: "Potential Log4Shell (CVE-2021-44228)"
```

Rule ini hanya match jika dependency tree mengandung log4j < 2.17. Tanpa ini, rule false-positive di project yang sudah upgrade.

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi:
  - `cli/src/semgrep/dependency_aware_rule.py` (filter logic)
  - `cli/src/semdep/matchers/base.py` (semver range matching)
  - `cli/src/semgrep/resolve_subprojects.py` (cari lockfile terdekat per source file)
  - `cli/src/semgrep/subproject.py` (subproject resolution)

## Acceptance Criteria
- [ ] Field `project-depends-on: [{ namespace, package, version }]` di rule YAML
- [ ] Namespace support: pypi, npm, maven, cargo, gem, go, nuget, pub, hex, composer, mix, swiftpm, gradle
- [ ] Version: PEP 440 (pip), semver (npm/cargo/nuget), Maven range, Gemfile tilde
- [ ] Rule match hanya jika: (a) pattern match di code, DAN (b) dependency tree mengandung paket di version range
- [ ] `codelens taint --rules sca-rule.yaml` — jalankan dengan dependency-aware filter
- [ ] Output: finding extra field `matched_dependencies: [{ name, version, ecosystem }]`
- [ ] Test: fixture `log4shell-vulnerable/` (match) + `log4shell-safe/` (no match)

## Implementation Notes
- Depend on Issue #6 (lockfile parser) untuk dependency tree
- Subproject resolution: cari lockfile terdekat dari source file (walk up parent dir)
- Cache dependency tree per subproject (invalidate saat lockfile mtime change)

## Priority
P1 — depend on Issue #1, #6.
```

---

### 📋 Issue #8 [P1] — LSP Server (publishDiagnostics + Code Actions)

```markdown
**Title:** [P1] Implement LSP server (publish diagnostics + code actions for autofix)

## Motivation
CodeLens punya `scripts/lsp_client.py` (client ke LSP eksternal seperti pyright/rust-analyzer) dan `lsp-status` command (cek availability). Tapi CodeLens **bukan** LSP server — tidak publish diagnostics ke editor.

Opengrep punya LSP server 3.17 compliant (`src/osemgrep/language_server/`) yang publish diagnostics, code actions (autofix), dan hover (rule docs). Ini critical untuk IDE adoption — developer mau lihat finding inline di editor, bukan run CLI terpisah.

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi:
  - `src/osemgrep/cli_lsp/Lsp_CLI.ml` + `Lsp_subcommand.ml` (entry point)
  - `src/osemgrep/language_server/LS.ml` (main loop, Lwt-based)
  - `src/osemgrep/language_server/requests/` (LSP request handlers)
  - `src/osemgrep/language_server/notifications/` (LSP notification handlers)
  - `src/osemgrep/language_server/custom_requests/` + `custom_commands/` (CodeLens-specific extensions)

## Acceptance Criteria
- [ ] Command baru: `codelens lsp` — start LSP server over stdio
- [ ] LSP 3.17 compliant (test dengan `vscode-languageclient` + `pylsp`)
- [ ] `textDocument/publishDiagnostics` — push finding ke editor saat file open/save
- [ ] `textDocument/codeAction` — suggest autofix untuk finding di baris tertentu
- [ ] `textDocument/hover` — show rule documentation + taint path
- [ ] File operation filters: `workspace/didCreateFiles`, `didRenameFiles`, `didDeleteFiles` (rescan affected)
- [ ] Incremental: re-parse hanya file yang berubah (reuse `incremental.py`)
- [ ] Integrasi dengan MCP server: bisa run paralel (LSP untuk editor, MCP untuk AI agent)

## Implementation Notes
- Gunakan `pylsp` (Python LSP framework) atau implement minimal JSON-RPC over stdio manual
- CodeLens sudah punya JSON-RPC implementation di `mcp_server.py` — reuse pattern
- Performance: LSP butuh sub-100ms response. Cache registry in-memory, invalidate on file change.
- Jangan reimplement LSP dari nol jika `pygls` (general language server framework) bisa dipakai.

## Non-goals
- Tidak perlu full LSP feature parity dengan opengrep (v1: diagnostics + codeAction + hover cukup)
- Tidak perlu workspace folder multi-root di v1

## Priority
P1 — critical untuk IDE adoption, beda segmen dengan MCP (editor human vs AI agent).
```

---

### 📋 Issue #9 [P1] — `test` Command (Snapshot Testing untuk Rule)

```markdown
**Title:** [P1] `codelens test` command — snapshot testing for rule YAML

## Motivation
CodeLens punya `benchmarks/` dengan fixture (`clean_app/`, `vulnerable_app/`) dan `ground_truth.yaml`, tapi ini untuk benchmark akurasi engine, bukan untuk rule author.

Rule author butuh cara untuk:
1. Tulis rule `my-rule.yaml`
2. Buat test case `target.py` (kode yang harus kena finding)
3. Buat expected output `target.expected.json` (finding yang diharapkan)
4. Run `codelens test my-rule.yaml` → pass/fail per test case
5. Untuk rule dengan `fix:`, buat `target.fixed.py` → verifikasi autofix output

Opengrep punya `semgrep test` yang sangat populer (`src/osemgrep/cli_test/Test_subcommand.ml`).

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi:
  - `src/osemgrep/cli_test/Test_subcommand.ml` (test runner)
  - `src/osemgrep/cli_test/Diagnosis.ml` (diff reporter)
  - `cli/src/semgrep/test.py` (legacy Python impl, deprecated)
  - `cli/tests/default/e2e/targets/test_test/` (test fixture examples)

## Acceptance Criteria
- [ ] Command baru: `codelens test <rule.yaml>` atau `codelens test <rule-dir/>`
- [ ] Test file convention: `<rule>.yaml` + `<rule>.test.yaml` (inline) atau `<rule>.yaml` + `targets/<name>.<ext>` + `<name>.expected.json`
- [ ] Fixtest: `<target>.<ext>` + `<target>.fixed.<ext>` — verifikasi autofix output
- [ ] Diagnosis: diff actual vs expected, report pass/fail per rule, exit code non-zero jika ada fail
- [ ] `--test-ignore-todo/--no-test-ignore-todo` flag — skip `# todoruleid` markers
- [ ] Multi-target support: 1 rule bisa test multiple target file
- [ ] Output: human-readable summary + optional `--json` untuk CI

## Implementation Notes
- Test file format: gunakan inline YAML dengan `# ruleid: <id>` dan `# ok: <no-finding-expected>` comment marker (mirip semgrep)
- Atau: separate file approach (target + expected.json) — lebih verbose tapi lebih explicit
- Reuse `benchmarks/run_benchmarks.py` pattern untuk fixture loading

## Priority
P1 — critical untuk rule ecosystem (author tidak akan tulis rule tanpa test).
```

---

### 📋 Issue #10 [P1] — `validate` Command (Rule Schema Validation)

```markdown
**Title:** [P1] `codelens validate` command — rule YAML schema + pattern validation

## Motivation
CodeLens `validate` command saat ini validate **registry vs filesystem** (cek apakah symbol di registry masih ada di file). Itu berbeda dari yang dibutuhkan: validate **rule YAML**.

User yang tulis rule butuh feedback cepat: apakah YAML syntactically valid? Apakah schema correct? Apakah pattern bisa di-parse (untuk bahasa target)? Opengrep punya `semgrep validate`:

```bash
$ opengrep validate my-rule.yaml
✓ my-rule.yaml: 3 rules valid
# atau
✗ my-rule.yaml: rule 'py/eval' has invalid pattern: unexpected token at line 5
```

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi:
  - `src/osemgrep/cli_validate/Validate_subcommand.ml` (validate logic)
  - `cli/src/semgrep/rule_lang.py` (YAML parser + jsonschema fallback)
  - `src/parsing/Parse_rule.ml` (rule parser + validation)

## Current State
- CodeLens `validate` command = validate registry (beda fungsi)
- Tidak ada rule YAML validator

## Acceptance Criteria
- [ ] Command baru: `codelens rule-validate <rule.yaml>` (atau rename existing `validate` → `registry-validate`)
- [ ] YAML syntax check (catch unclosed quote, indentation error)
- [ ] Schema validation: required field (`id`, `message`, `severity`, `language`), enum (`severity: critical|high|medium|low|info`)
- [ ] Pattern parseability: compile `pattern:` ke AST untuk bahasa target (detect syntax error di pattern)
- [ ] Cross-field validation: `patterns:` dan `pattern:` mutually exclusive; `fix:` require `pattern:` atau `patterns:`
- [ ] Output: per-rule pass/fail + specific error message dengan line number
- [ ] Exit code: 0 jika semua valid, 1 jika ada error
- [ ] CI integration: bisa dipakai di pre-commit hook

## Implementation Notes
- Rename existing `validate` → `registry-validate` (atau `fs-validate`) untuk avoid confusion
- JSON Schema untuk rule YAML: definisikan di `references/rule-schema.json`, validate dengan `jsonschema` library
- Pattern parseability: reuse tree-sitter parser dari `grammar_loader.py`, parse pattern string, catch exception

## Priority
P1 — quick win, high DX impact untuk rule author.
```

---

### 📋 Issue #11 [P1] — Multi-Output Formatter (GitLab SAST, JUnit XML, text, emacs, vim)

```markdown
**Title:** [P1] Tambah 6 output formatter: text, gitlab-sast, gitlab-secrets, junit-xml, emacs, vim

## Motivation
CodeLens hanya punya 2 formatter: `markdown` dan `sarif`. Untuk CI/CD adoption, banyak platform butuh format lain:

- **GitLab SAST** — GitLab CI native format untuk security scan
- **GitLab Secrets** — GitLab native format untuk secret detection
- **JUnit XML** — universal test result format (bisa di-render di Jenkins, GitLab, CI dashboard)
- **text** — human-readable plain text (untuk terminal output tanpa color)
- **emacs** — single-line format untuk Emacs `compile-mode` (clickable link)
- **vim** — single-line format untuk Vim `quickfix` (clickable link)

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi (struktur mirip, port ke CodeLens schema):
  - `cli/src/semgrep/formatter/text.py`
  - `cli/src/semgrep/formatter/gitlab_sast.py`
  - `cli/src/semgrep/formatter/gitlab_secrets.py`
  - `cli/src/semgrep/formatter/junit_xml.py`
  - `cli/src/semgrep/formatter/emacs.py`
  - `cli/src/semgrep/formatter/vim.py`
  - `cli/src/semgrep/formatter/base.py` (base class)

## Current State
- `scripts/formatters/markdown.py` + `sarif.py`
- `scripts/formatters/__init__.py` — `format_output()` dispatcher

## Acceptance Criteria
- [ ] 6 formatter baru di `scripts/formatters/`
- [ ] Global flag `--format <name>` (atau `--text`, `--json`, `--sarif`, `--gitlab-sast`, `--gitlab-secrets`, `--junit-xml`, `--emacs`, `--vim`)
- [ ] `--output <file>` — write ke file (bisa multiple: `--text-output a.txt --sarif-output b.sarif`)
- [ ] `--incremental-output` — stream finding saat ditemukan (bukan tunggu akhir) — depend on Issue #14
- [ ] Setiap formatter implement base class dengan `format(findings, rules, errors, extra) -> str`
- [ ] Test: snapshot test per formatter dengan fixture finding

## Implementation Notes
- JUnit XML: gunakan `junit-xml` PyPI package atau generate manual (schema simple)
- GitLab SAST: schema di `https://gitlab.com/help/user/application_security/sast/index.json`
- text format: table dengan kolom `rule_id | severity | file:line | message`
- emacs/vim: format `<file>:<line>:<col>: <message>`

## Priority
P1 — critical untuk CI/CD platform coverage.
```

---

### 📋 Issue #12 [P1] — Self-Contained Binary Distribution

```markdown
**Title:** [P1] Distribute CodeLens as self-contained binary (PyInstaller / Nuitka)

## Motivation
CodeLens saat ini hanya bisa dijalankan dengan `python3 scripts/codelens.py <command>`, yang require:
1. Python 3.8+ terinstall
2. `pip install tree-sitter pyyaml watchdog` + 10 grammar package
3. `bash setup.sh` (1-3 menit install)

Ini barrier adopsi tinggi untuk:
- CI/CD pipeline (cold start lambat)
- User non-Python (Node/Rust/Go developer)
- Pre-commit hook (setup manual per repo)

Opengrep solve ini dengan Nuitka self-contained binary + Cosign signing. CodeLens bisa pakai PyInstaller (lebih simple, Python native).

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi:
  - `scripts/build-nuitka.sh` (Nuitka build script)
  - `install.sh` (Linux/macOS installer)
  - `install.ps1` (Windows installer)
  - `Dockerfile` (container distribution)
  - Cosign signing di release workflow

## Acceptance Criteria
- [ ] Build script `scripts/build-binary.sh` — produce single binary `codelens` (Linux x64, macOS x64/arm64, Windows x64)
- [ ] Binary include: Python runtime + tree-sitter + all grammar + all CodeLens source + PyYAML + watchdog
- [ ] Binary size target: <50MB (compressed)
- [ ] Cold start time: <500ms (vs 200-500ms per CLI invocation saat ini via python3)
- [ ] `install.sh` + `install.ps1` — download binary dari GitHub releases, install ke `/usr/local/bin/codelens`
- [ ] GitHub Actions release workflow: build binary untuk 5 target OS+arch, upload ke Releases, sign dengan Cosign (atau GPG sebagai fallback)
- [ ] Homebrew tap: `brew install codelens/tap/codelens` (optional, v2)
- [ ] Docker image: `ghcr.io/wolfvin/codelens:latest` untuk CI

## Implementation Notes
- PyInstaller lebih simple dari Nuitka untuk Python project. Coba PyInstaller dulu.
- Tree-sitter grammar adalah .so/.dll — perlu bundle explicit. PyInstaller `--add-data` flag.
- Watchdog optional (hanya untuk `watch` command) — bisa lazy-import agar tidak wajib di binary.
- Test binary di fresh Docker container (Ubuntu 22.04, Debian 12, Alpine) untuk verify no system dependency.

## Priority
P1 — high UX impact, tapi bukan blocker functional.
```

---

### 📋 Issue #13 [P2] — Intrafile Cross-Function Taint (Signature Extraction)

```markdown
**Title:** [P2] Intrafile cross-function taint analysis with signature extraction

## Motivation
CodeLens `ast_taint_engine.py` (3756 LOC) sudah support inter-procedural taint dalam 1 file, tapi pendekatannya adalah inline propagation — tidak ada signature extraction. Setiap call site re-analyze callee body.

Opengrep punya approach yang lebih scalable:
1. Extract signature per function (topological sort callee-before-caller)
2. Store signature di database
3. Replays signature di call site (tidak re-analyze callee body)

Hasilnya: lebih cepat (callee di-analyze sekali, bukan per call site) + lebih akurat (signature capture summary taint flow).

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi:
  - `src/tainting/Taint_signature_extractor.ml` (signature extraction + topological sort)
  - `src/tainting/Sig_inst.ml` (signature instantiation at call site)
  - `src/tainting/Shape_and_sig.ml` (signature database)
  - `src/tainting/Object_initialization.ml` (constructor detection)
  - `docs/INTRA_FUNCTION_IMPLEMENTATION.md` (design doc)
  - `src/tainting/Taint_lambdas.ml` (higher-order function support)

## Current State
- `ast_taint_engine.py` — inter-procedural inline, no signature
- `crossfile_taint_engine.py` — cross-file, regex-based call graph
- `callgraph_engine.py` — tree-sitter + import resolution, inter-procedural

## Acceptance Criteria
- [ ] Extract taint signature per function: `{ params_tainted: [bool], returns_tainted: bool, fields_tainted: {name: bool}, sinks_reached: [sink_id] }`
- [ ] Topological sort call graph supaya callee di-analyze sebelum caller
- [ ] Signature database in-memory (per scan session)
- [ ] Replay signature di call site (tidak re-analyze callee body)
- [ ] Object initialization detection: `new Foo()` → taint carrier, track `this.x`/`self.y`
- [ ] Higher-order function support: callback yang ter-taint, propagate ke caller
- [ ] Flag `--taint-intrafile` untuk enable (default off, untuk backward compat)
- [ ] Performance: 2x lebih cepat dari inline approach di file dengan 50+ function
- [ ] Test: fixture `taint_intrafile.py` dengan 20+ cross-function case

## Implementation Notes
- Topological sort: gunakan `graphlib.TopologicalSorter` (Python 3.9+, atau `networkx` untuk 3.8)
- Signature = dataclass `TaintSignature(params, returns, fields, sinks, sanitizers)`
- Object init: detect `new Foo()` / `Foo()` (Python) / `new Foo()` (JS/TS/Rust)
- Lambda: capture closure variable yang ter-taint, propagate ke return value

## Priority
P2 — improve accuracy & performance, bukan blocker functional.
```

---

### 📋 Issue #14 [P2] — Incremental Output Streaming

```markdown
**Title:** [P2] Incremental output streaming (`--incremental-output`)

## Motivation
CodeLens saat ini collect semua finding, baru output di akhir scan. Untuk repo besar (5000+ file), ini berarti user tunggu 30-120 detik tanpa feedback. Opengrep punya `--incremental-output` yang stream finding saat ditemukan.

Use case:
- CI pipeline: fail-fast kalau ada critical finding (tidak tunggu scan selesai)
- Editor integration: show finding di terminal saat scan berjalan
- Long scan: user bisa Ctrl+C awal kalau sudah lihat pattern masalah

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi:
  - `cli/src/semgrep/output.py` (OutputHandler dengan incremental mode)
  - `--incremental-output` CLI flag
  - `--incremental-output-postprocess` (autofix + nosem postprocessing juga incremental)

## Acceptance Criteria
- [ ] Flag `--incremental-output` — emit finding ke stdout saat ditemukan (JSON Lines format: 1 JSON object per baris)
- [ ] Flag `--incremental-output-postprocess` — apply autofix + suppression inline (bukan batch di akhir)
- [ ] Integrasi dengan `--output <file>` — write ke file saat ditemukan (append mode)
- [ ] Integrasi dengan SARIF: tidak bisa incremental (SARIF butuh array complete), jadi SARIF tetap batch di akhir
- [ ] Progress bar: tampilkan `Scanning: 234/5000 files, 12 findings` di stderr
- [ ] Exit code: 1 jika ada finding dengan severity >= threshold (configurable `--error-on-severity high`)

## Implementation Notes
- JSON Lines (`*.jsonl`) = 1 JSON object per baris, newline-delimited. Mudah di-parse oleh downstream tool.
- Untuk autofix incremental: hold file lock, apply fix per-finding, release. Conflict detection per-file.
- Progress bar: gunakan `tqdm` atau `rich.progress` (sudah common dependency)

## Priority
P2 — nice-to-have, improve UX untuk long scan.
```

---

### 📋 Issue #15 [P2] — Generic Mode (Aliengrep) untuk File Tanpa Grammar

```markdown
**Title:** [P2] Generic pattern mode for files without tree-sitter grammar (Aliengrep equivalent)

## Motivation
CodeLens punya 25 fallback regex parser untuk bahasa tanpa tree-sitter grammar (C, C++, Java, Kotlin, Swift, Ruby, Scala, Elixir, Dart, Lua, Nim, ObjC, PHP, R, Shell, Vim, Zig, GDScript, Haskell, Blade). Tapi fallback parser ini structural — tidak bisa match pattern semantik.

Opengrep punya "Aliengrep" (pengganti Spacegrep) — generic pattern mode yang bisa match file apa pun (config, log, template, custom DSL) dengan pattern seperti `hello($...ARGS)`.

Use case:
- Scan file `.env`, `.ini`, `.conf` dengan pattern `password = $X`
- Scan custom DSL (SQL DDL, GraphQL schema, HCL, TOML) tanpa grammar dedicated
- Scan log file untuk pattern anomaly

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi:
  - `libs/aliengrep/` (7 file .ml: Conf, Match, Pat_AST, Pat_compile, Pat_lexer, ...)
  - `README.md` di `libs/aliengrep/` (syntax doc)

## Acceptance Criteria
- [ ] Bahasa `generic` di rule YAML: `languages: [generic]`
- [ ] Pattern syntax: `func($...ARGS)`, `key = $VALUE`, `<!-- $COMMENT -->`
- [ ] Tokenizer: split file jadi token (identifier, string, number, operator, punctuation)
- [ ] Matcher: pattern di-compile ke token pattern, match di token stream
- [ ] Metavariable support: `$X` capture token sequence
- [ ] Test: 20+ case untuk berbagai file format (env, ini, conf, log, custom DSL)

## Implementation Notes
- Aliengrep approach: lexer sederhana (regex-based tokenizer) + pattern compiler + matcher
- Token type: `IDENT, STRING, NUMBER, OP, PUNCT, NEWLINE, COMMENT`
- Pattern `$...ARGS` match zero or more token sampai `)`
- Jangan reimplement Spacegrep/Aliengrep 1:1 — adapt ke CodeLens rule schema

## Priority
P2 — expand coverage tanpa invest grammar tree-sitter per bahasa.
```

---

### 📋 Issue #16 [P2] — `ci` Command (CI Orchestration with Baseline Scan)

```markdown
**Title:** [P2] `codelens ci` command — CI orchestration with baseline diff scan

## Motivation
CodeLens ship 4 GitHub Actions workflow, tapi tidak ada `ci` command yang orchestrate. User harus compose workflow manual.

Opengrep punya `semgrep ci` yang:
1. Detect CI environment (GitHub Actions, GitLab CI, Jenkins, Bitbucket)
2. Run scan dengan config dari `--config auto` atau registry
3. Compare dengan baseline commit (hanya report finding di file yang berubah, atau file yang berubah + dependents)
4. Upload hasil ke SARIF + CodeLens dashboard (jika login)
5. Fail build jika ada finding dengan severity >= threshold

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi:
  - `cli/src/semgrep/commands/ci.py` (966+ LOC, full orchestration)
  - `cli/src/semgrep/commands/install_ci.py` (install CI workflow)
  - `cli/src/semgrep/git.py` (baseline handler, diff calculation)
  - `--baseline-commit SHA` flag + `--diff-depth N`

## Current State
- 4 workflow GitHub Actions terpisah (CI, quality-gate, SARIF, benchmark)
- `diff` command compare registry snapshot, bukan diff vs git commit
- Tidak ada baseline scan (report hanya finding baru)

## Acceptance Criteria
- [ ] Command `codelens ci` — orchestrate full CI scan
- [ ] Auto-detect CI environment dari env var (`GITHUB_ACTIONS`, `GITLAB_CI`, `JENKINS_URL`, `BITBUCKET_BUILD_NUMBER`)
- [ ] `--baseline-commit SHA` — hanya report finding di file yang berubah sejak SHA
- [ ] `--diff-depth N` — include file yang depend (transitif) ke file berubah (default: 0, hanya direct change)
- [ ] `--error-on-severity <level>` — exit code 1 jika ada finding >= level
- [ ] Auto-upload SARIF ke GitHub code scanning (jika di GitHub Actions)
- [ ] `codelens install-ci` — generate workflow file `.github/workflows/codelens.yml` di repo target
- [ ] Support GitLab CI (`.gitlab-ci.yml`), Jenkins (`Jenkinsfile`), Bitbucket Pipelines (`bitbucket-pipelines.yml`)

## Implementation Notes
- Baseline: `git diff --name-only <SHA> HEAD` untuk dapat changed files, filter finding ke file tersebut
- Diff-depth: reuse `dependents_engine.py` untuk cari transitive dependents
- install-ci: template workflow di `scripts/templates/codelens-ci-{github,gitlab,jenkins}.yml.tmpl`

## Priority
P2 — improve CI/CD story, tapi workflow manual sudah work.
```

---

### 📋 Issue #17 [P2] — Constant Propagation & Symbolic Propagation di Matcher

```markdown
**Title:** [P2] Constant propagation and symbolic propagation in pattern matcher

## Motivation
Saat CodeLens match pattern `password = $X`, ia tidak tahu apakah `$X` adalah literal `"hardcoded"` atau variabel `os.getenv("PASSWORD")`. Opengrep punya `options.constant_propagation: true` (default) yang resolve `PASSWORD = "literal"` di scope sebelum match.

Use case:
- Rule `pattern: password = "..."` hanya match jika RHS adalah string literal (bukan variabel)
- Rule `pattern: eval($INPUT)` tidak match jika `INPUT = "safe_constant"`

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi:
  - `src/analyzing/Constant_propagation.ml` (constant folding)
  - `src/analyzing/Dataflow_svalue.ml` (symbolic value propagation)
  - `interfaces/Rule_options.atd` — `constant_propagation`, `symbolic_propagation` options

## Acceptance Criteria
- [ ] Constant propagation: track `X = "literal"` di scope, resolve `$X` ke literal saat match
- [ ] Symbolic propagation (opt-in, `options.symbolic_propagation: true`): resolve `$X` ke expression sederhana (bukan hanya literal)
- [ ] Per-rule option: `options: { constant_propagation: false }` untuk disable
- [ ] Test: 30+ case untuk const prop, 10+ untuk symbolic

## Implementation Notes
- Constant prop: dataflow forward, track `var -> literal_value` map per scope
- Symbolic prop: extend ke `var -> AST_node` (lebih kompleks, bisa cause false positive)
- Reuse `dataflow_engine.py` framework

## Priority
P2 — depend on Issue #1 (pattern matching).
```

---

### 📋 Issue #18 [P2] — Join Rule Mode (Multi-Step Pattern)

```markdown
**Title:** [P2] Join rule mode — multi-step pattern matching with SQL-like join

## Motivation
CodeLens rule saat ini match 1 pattern per finding. Untuk detect cross-file vulnerability (e.g., user input di `views.py` flows ke template `user.html.j2` yang render tanpa escape), butuh multi-step:

Opengrep `join:` mode:
```yaml
rules:
  - id: flask-stored-xss
    join:
      steps:
        - patterns: [pattern: request.args.get($X)]
          as: source_match
        - patterns: [pattern: render_template($T, **$KWARGS)]
          as: render_match
        - patterns: [pattern: $T.contains($X)]
          as: template_match
      condition: source_match.x == render_match.kwargs.x AND template_match.t == render_match.t
```

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi:
  - `cli/src/semgrep/join_rule.py` (Python impl, SQL-like via peewee ORM)
  - `cli/tests/default/e2e/targets/join_rules/` (test fixture)

## Acceptance Criteria
- [ ] Field `join:` di rule YAML dengan `steps:` dan `condition:`
- [ ] Step: list of pattern, output `as: <name>`
- [ ] Condition: join key (mis. `step1.x == step2.x`)
- [ ] Output: finding dengan `matched_steps: [{name, location, metavars}]`
- [ ] Test: fixture `join_rules/` dengan 5+ multi-step case

## Implementation Notes
- Pendekatan opengrep: store match di SQLite (peewee), join via SQL query. Berat tapi scalable.
- Alternatif CodeLens: in-memory join (list of dict), filter dengan Python expression. Lebih simple, cukup untuk <10000 match.
- Mulai dengan in-memory, pindah ke SQLite jika performance issue.

## Priority
P2 — depend on Issue #1, #2.
```

---

### 📋 Issue #19 [P2] — `--dataflow-traces` di SARIF Output

```markdown
**Title:** [P2] Render taint path/dataflow trace in SARIF output

## Motivation
CodeLens render taint path di JSON output (`"taint_path": "request.args → user_input → query → cursor.execute"`), tapi SARIF output hanya berisi location akhir (sink). Opengrep punya `--dataflow-traces` yang render full path di SARIF `codeFlows` field.

Use case:
- GitHub code scanning UI show full taint path (clickable step-by-step)
- Azure DevOps render dataflow graph
- VS Code SARIF Viewer navigate through taint flow

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi:
  - `cli/src/semgrep/formatter/sarif.py` (dataflow trace rendering)
  - `--dataflow-traces` CLI flag

## Current State
- `scripts/formatters/sarif.py` (443 LOC) — basic SARIF, no `codeFlows`
- JSON output sudah punya `taint_path` field

## Acceptance Criteria
- [ ] Flag `--dataflow-traces` — enable codeFlows di SARIF
- [ ] SARIF `codeFlows` field per finding: array of `threadFlow` (1 per taint path)
- [ ] Setiap `threadFlowLocation` berisi: `location` (file:line:col), `message` (node name), `stackFrame` (function)
- [ ] Test: SARIF validate dengan SARIF Validator (`sarif-validator` npm package)

## Implementation Notes
- SARIF spec `codeFlows`: https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html#_Toc34317651
- Reuse `taint_path` dari JSON output, convert ke `threadFlow` structure

## Priority
P2 — quick win, high value untuk SARIF consumer.
```

---

### 📋 Issue #20 [P2] — Rule `metadata:` Field (Free-Form) + `paths:` Per-Rule Targeting

```markdown
**Title:** [P2] Rule `metadata:` free-form field + `paths: {include, exclude}` per-rule targeting

## Motivation
CodeLens rule YAML punya field fixed (`id`, `name`, `language`, `severity`, `cwe`, `owasp`, `message`, `sources`, `sinks`, `sanitizers`). Tidak ada field free-form untuk metadata custom (mis. `confidence`, `likelihood`, `impact`, `references`, `tags`).

Opengrep punya `metadata:` dict bebas + `paths: {include, exclude}` per-rule.

Use case:
- `metadata: { confidence: high, likelihood: medium, impact: high }` — untuk risk scoring custom
- `metadata: { references: ["https://owasp.org/..."] }` — link ke dokumentasi
- `paths: { include: ["src/api/**"], exclude: ["tests/**"] }` — rule hanya berlaku di direktori tertentu

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi:
  - `cli/src/semgrep/rule.py` — `path_dict`, `options_dict`, metadata handling
  - `interfaces/Rule_options.atd`

## Acceptance Criteria
- [ ] Field `metadata:` — dict bebas, serialized ke SARIF `properties` dan JSON output `metadata`
- [ ] Field `paths: { include: [...], exclude: [...] }` — per-rule glob pattern
- [ ] `include` / `exclude` support `**` recursive glob (via `wcmatch` atau `pathlib`)
- [ ] SARIF `properties` field: include semua metadata key-value
- [ ] Test: rule dengan metadata + paths, verify filtering

## Implementation Notes
- `metadata` = `Dict[str, Any]`, no schema validation (free-form)
- `paths` filter applied sebelum scan, setelah rule load
- Glob: gunakan `wcmatch.glob` (sudah dipakai opengrep) atau `pathlib.Path.glob`

## Priority
P2 — quick win, enable richer rule ecosystem.
```

---

### 📋 Issue #21 [P3] — `.codelensignore` File (Custom Ignore Pattern)

```markdown
**Title:** [P3] `.codelensignore` file (gitignore-style untuk scan target)

## Motivation
CodeLens saat ini hardcode `DEFAULT_IGNORE_DIRS` di `utils.py` (dist/, build/, vendor/, node_modules/, .git/, dll). User tidak bisa customize tanpa edit source atau set config per-workspace.

Opengrep punya `.semgrepignore` file (gitignore syntax) yang user bisa taruh di project root.

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi:
  - `cli/src/semgrep/ignores.py` (FileIgnore class, fnmatch-based)
  - `src/targeting/Semgrepignore.ml` (OCaml parser)
  - `--semgrepignore-filename <name>` flag (custom filename)

## Acceptance Criteria
- [ ] File `.codelensignore` di workspace root — gitignore syntax
- [ ] Support: `**` recursive, `*` wildcard, `!` negation, comment dengan `#`
- [ ] 3-tier: workspace `.codelensignore` (highest) → user `~/.codelensignore` → builtin default
- [ ] `--codelensignore-filename <name>` flag — custom filename (mis. `.codelensignore.prod`)
- [ ] Builtin default: ship `scripts/data/default-codelensignore` dengan pattern umum (node_modules, .git, dist, build, vendor, *.min.js, *.map)
- [ ] Log: report file yang di-ignore di scan summary

## Implementation Notes
- Gunakan `pathspec` PyPI package (gitignore spec compliant) — lebih robust dari fnmatch manual
- Atau port `fnmatch` logic dari `cli/src/semgrep/ignores.py` opengrep

## Priority
P3 — nice-to-have, improve configurability.
```

---

### 📋 Issue #22 [P3] — `--output-enclosing-context` (Report Function/Class Enclosing Match)

```markdown
**Title:** [P3] `--output-enclosing-context` flag — report enclosing function/class/module

## Motivation
Saat CodeLens report finding `eval(user_input)` di file `app.py` line 42, user tidak tahu function mana yang mengandungnya (apakah `def handler():`? `class Controller:`? top-level?). Opengrep punya `--output-enclosing-context` yang add field `enclosing_context: { type: "function", name: "handler", class: "Controller" }`.

Use case:
- Group finding by function/class di dashboard
- Filter "semua finding di class Controller"
- SARIF `taxa` untuk categorize

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi: `--output-enclosing-context` flag di `cli/src/semgrep/commands/scan.py`

## Acceptance Criteria
- [ ] Flag `--output-enclosing-context` — add `enclosing_context` field di JSON output
- [ ] Field: `{ type: "function"|"method"|"class"|"module", name: str, qualified_name: str }`
- [ ] SARIF: gunakan `properties.enclosing_context`
- [ ] Reuse `outline_engine.py` untuk dapat enclosing scope

## Implementation Notes
- Tree-sitter: walk up parent node, cari `function_definition` / `class_definition` / `method_definition`
- Fallback regex parser: track current function/class selama parse

## Priority
P3 — quick win, improve finding triage.
```

---

### 📋 Issue #23 [P3] — Marketplace Registry (Activate `registry.codelens.dev`)

```markdown
**Title:** [P3] Activate plugin/rule marketplace at registry.codelens.dev

## Motivation
CodeLens `plugin_system.py` sudah punya `REGISTRY_INDEX_URL = "https://registry.codelens.dev/api/v1/plugins"` tapi domain belum resolve. Marketplace belum aktif.

Opengrep/semgrep punya registry matang di semgrep.dev dengan ribuan rule, r2c rulesets, dan `semgrep publish` command.

Tanpa marketplace aktif, ekosistem rule CodeLens tidak bisa tumbuh — user harus copy-paste rule manual.

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi:
  - `cli/src/semgrep/commands/publish.py` (publish rule pack)
  - `cli/src/semgrep/commands/login.py` (auth)
  - `cli/src/semgrep/app/scans.py` (registry API client)
  - Registry: `https://semgrep.dev/r/` (ribuan rule publik)

## Current State
- `scripts/plugin_system.py` — 4 plugin type, 3-tier discovery, tapi marketplace URL TODO
- Tidak ada `publish` command
- Tidak ada `login` command

## Acceptance Criteria
- [ ] Deploy API di `registry.codelens.dev` (atau subdomain lain) — endpoint:
  - `GET /api/v1/plugins` — list plugin
  - `GET /api/v1/plugins/<name>` — download plugin pack
  - `POST /api/v1/plugins` — publish (auth required)
  - `GET /api/v1/rulesets` — list ruleset
- [ ] Command `codelens plugin publish <path>` — upload plugin pack ke registry
- [ ] Command `codelens login` — auth via API token (simpan di `~/.codelens/credentials`)
- [ ] Command `codelens plugin install <name>` — download dari registry, install ke `~/.codelens/plugins/`
- [ ] `codelens scan --plugins auto` — auto-fetch recommended plugin dari registry
- [ ] Registry backend: bisa simple SQLite + FastAPI, atau static JSON di GitHub Pages (MVP)

## Implementation Notes
- MVP: static JSON index di GitHub Pages (`https://wolfvin.github.io/codelens-registry/index.json`) — tidak butuh server
- v2: deploy API server (FastAPI + SQLite/PostgreSQL) untuk publish + auth
- Rule pack format: ZIP file berisi `plugin.yaml` + rule YAML + README + LICENSE

## Priority
P3 — critical untuk ecosystem growth, tapi butuh infra setup.
```

---

### 📋 Issue #24 [P3] — `show` Command (AST Dump & Pattern Match Explanation)

```markdown
**Title:** [P3] `codelens show` command — dump AST and explain pattern match

## Motivation
Rule author butuh debug tool: kenapa pattern saya tidak match? Opengrep punya `semgrep show` yang:
1. Dump AST generic dari file target
2. Dump compiled pattern AST
3. Show match explanation step-by-step (which metavar bind to which node)

## Reference
- Repo: https://github.com/opengrep/opengrep
- File referensi:
  - `src/osemgrep/cli_show/Show_subcommand.ml`
  - `src/osemgrep/cli_show/Show_HTML.ml` (HTML rendering)

## Acceptance Criteria
- [ ] Command `codelens show <file>` — dump tree-sitter AST (S-expression format)
- [ ] Command `codelens show --pattern <pat> --lang <lang>` — dump compiled pattern AST
- [ ] `--explain` flag — saat match, show step-by-step metavariable binding
- [ ] `--html` flag — render AST ke HTML (interactive tree, expandable node)

## Implementation Notes
- Tree-sitter node punya `.sexp()` method untuk S-expression dump
- HTML render: gunakan `tree-sitter-cli` HTML output atau custom Jinja2 template

## Priority
P3 — DX tool untuk rule author, depend on Issue #1.
```

---

## 6. Prioritas & Roadmap

### 6.1 Rekomendasi urutan eksekusi (quarter-based)

**Q3 2026 (P0 — Foundation):**
1. Issue #1 — Pattern matching engine
2. Issue #2 — Metavariable capture & substitution

**Q3 2026 (P1 — SAST parity):**
3. Issue #3 — Autofix dari rule
4. Issue #4 — Inline suppression
5. Issue #5 — Per-rule timeout
6. Issue #10 — `validate` command (quick win)
7. Issue #9 — `test` command

**Q4 2026 (P1 — SCA & Distribution):**
8. Issue #6 — 14 lockfile parser
9. Issue #7 — Dependency-aware rule
10. Issue #8 — LSP server
11. Issue #11 — Multi-output formatter
12. Issue #12 — Self-contained binary

**Q1 2027 (P2 — Performance & Depth):**
13. Issue #13 — Intrafile signature extraction
14. Issue #14 — Incremental output streaming
15. Issue #17 — Constant/symbolic propagation
16. Issue #19 — SARIF dataflow traces

**Q2 2027 (P2/P3 — Ecosystem):**
17. Issue #15 — Generic mode (Aliengrep)
18. Issue #16 — `ci` command
19. Issue #18 — Join rule mode
20. Issue #20 — `metadata:` + `paths:` field
21. Issue #21 — `.codelensignore` file
22. Issue #22 — `--output-enclosing-context`
23. Issue #23 — Marketplace registry
24. Issue #24 — `show` command

### 6.2 Dependency graph

```
Issue #1 (pattern) ─┬─→ Issue #2 (metavar) ─┬─→ Issue #3 (autofix dari rule)
                    │                        ├─→ Issue #17 (const prop)
                    │                        ├─→ Issue #18 (join rule)
                    │                        └─→ Issue #24 (show command)
                    └─→ Issue #15 (generic mode)

Issue #6 (lockfile) ──→ Issue #7 (dep-aware rule)

Issue #8 (LSP) — independen
Issue #9 (test) — depend on #1
Issue #10 (validate) — depend on #1
Issue #11 (formatter) — independen
Issue #12 (binary) — independen
Issue #13 (intrafile taint) — independen (improve existing)
Issue #14 (incremental output) — independen
Issue #4 (nosem) — independen
Issue #5 (timeout) — independen
Issue #16 (ci) — depend on #11, #19
Issue #19 (SARIF traces) — independen
Issue #20 (metadata + paths) — independen
Issue #21 (.codelensignore) — independen
Issue #22 (enclosing context) — independen
Issue #23 (marketplace) — independen (infra)
```

### 6.3 Yang TIDAK perlu diserap dari opengrep

Untuk menjaga niche CodeLens sebagai AI-native tool:

1. ❌ **OCaml core engine** — CodeLens stay Python, invest di tree-sitter Python binding. OCaml rewrite terlalu mahal, dan CodeLens bukan SAST murni.
2. ❌ **Pro engine features** (`--pro-path-sensitive`, `--pro-languages`) — ini fitur komersial Semgrep Inc., opengrep tidak punya fully. CodeLens tidak perlu.
3. ❌ **Semgrep App integration** (`login`, `publish`, `ci` upload ke semgrep.dev) — CodeLens tidak terikat vendor SaaS.
4. ❌ **Secrets detection mode** (`--secrets`, `--historical-secrets`) — CodeLens sudah punya `secrets_engine.py` yang lebih kaya (entropy, .env scan, .gitignore check).
5. ❌ **Rule schema v2 ATD-based** — CodeLens pakai YAML schema sederhana, tidak perlu ATD codegen.
6. ❌ **Multicore parallelism OCaml 5.3** — Python `multiprocessing` cukup untuk CodeLens scale.
7. ❌ **`install-ci` ke Bitbucket/Jenkins** di v1 — fokus GitHub + GitLab dulu.

---

## 7. Catatan Implementasi & Risiko

### 7.1 License compliance

- Opengrep: **LGPL-2.1** — boleh reference code untuk inspirasi, tapi **jangan copy-paste code verbatim** ke CodeLens (MIT). LGPL mengharuskan derivative work tetap LGPL atau link dynamic.
- CodeLens MIT boleh reference algorithm & architecture, implementasi ulang dari nol.
- Rule YAML schema: opengrep/semgrep rule schema adalah de facto standard, amal reference (tidak copyrightable).

### 7.2 Backward compatibility

- Semua fitur baru harus opt-in via flag atau field baru di rule YAML. Default behavior CodeLens tidak boleh break.
- Existing rule YAML (`scripts/rules/*.yaml`, `scripts/plugins/**/*.yaml`) harus tetap work tanpa modifikasi.
- `validate` command rename: gunakan deprecation warning 1 version sebelum rename (`codelens validate` → warning → `codelens registry-validate` di v7.3+).

### 7.3 Performance budget

- Pattern matching engine (Issue #1): target <2x slowdown vs current `search` regex. Gunakan prefilter (analyze pattern, skip file yang tidak mungkin match) — opengrep punya `Mini_rules_filter.ml`.
- LSP server (Issue #8): target <100ms response time. Cache registry in-memory, invalidate on file change.
- 14 lockfile parser (Issue #6): parsing harus <1s per lockfile. Lazy parse (hanya saat `vuln-scan` di-run).

### 7.4 Testing strategy

- Setiap fitur baru harus ship dengan:
  1. Unit test (pytest, di `tests/unit/`)
  2. Integration test (di `tests/integration/` dengan fixture)
  3. Snapshot test untuk rule (Issue #9 framework)
  4. Benchmark (di `benchmarks/`) untuk performance regression
- Real-world validation: run di repo test yang sudah ada di CHANGELOG (spacedrive, redis, neovim, fastapi, exercism/python) untuk verify no regression.

---

## 8. Penutup

Analisis ini mengidentifikasi **24 issue upgrade** dari opengrep ke CodeLens, dengan breakdown:
- 2 issue P0 (critical foundation)
- 10 issue P1 (SAST/SCA parity)
- 8 issue P2 (depth & ecosystem)
- 4 issue P3 (polish & DX)

CodeLens sudah unggul di 7 area (MCP, AI output, guard, auto-setup, workspace detect, frontend, code intelligence) — pertahankan dan_DOUBLE-DOWN di situ sebagai differentiator. Yang diserap dari opengrep adalah **konsep fitur & DX**, bukan arsitektur OCaml.

Eksekusi sesuai roadmap Q3 2026 → Q2 2027, dengan dependency graph sebagai panduan urutan. Patoki backward compatibility, performance budget, dan testing strategy agar tidak break adoption existing.

---

*Dokumen ini dihasilkan dari analisa source code `Wolfvin/CodeLens` (commit `main` per 2026-06-28) dan `opengrep/opengrep` v1.23.0 (18 Jun 2026). Semua reference path file merujuk ke struktur repo masing-masing saat tanggal analisa.*
