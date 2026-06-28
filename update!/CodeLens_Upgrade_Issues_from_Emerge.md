# CodeLens — Upgrade Issues (Serapan Fitur dari Emerge)

> **Repo target:** `https://github.com/Wolfvin/CodeLens.git` (branch `main`)
> **Repo referensi:** `https://github.com/glato/emerge.git` (branch `dev`)
> **Tanggal analisa:** 2026-06-28
> **Tujuan:** menyediakan daftar issue siap-pakai untuk upgrade CodeLens berikutnya, dengan menyerap pola/arsitektur/fitur dari Emerge — tool *interactive code analysis & graph visualization* yang fokus pada codebase-wide metrics dan visualisasi eksploratif.

> Dokumen ini melengkapi `CodeLens_Upgrade_Issues_from_Semgrep.md` (22 issue CL-001 s/d CL-022). Issue di sini menggunakan nomor lanjutan **CL-023 s/d CL-035**.

---

## Daftar Isi

1. [Ringkasan Eksekutif](#1-ringkasan-eksekutif)
2. [Snapshot Emerge — Fitur Referensi](#2-snapshot-emerge--fitur-referensi)
3. [Gap Analysis CodeLens vs Emerge](#3-gap-analysis-codelens-vs-emerge)
4. [Daftar Issue untuk Upgrade (CL-023 s/d CL-035)](#4-daftar-issue-untuk-upgrade-cl-023-s-d-cl-035)
5. [Roadmap & Sinergi dengan Issue Semgrep](#5-roadmap--sinergi-dengan-issue-semgrep)
6. [Appendix — Peta File Emerge ke Topik Issue](#6-appendix--peta-file-emerge-ke-topik-issue)

---

## 1. Ringkasan Eksekutif

Emerge (`glato/emerge`, juga dipublikasikan sebagai `emerge-viz` di PyPI) adalah tool analisa kode dengan **positioning yang sangat berbeda** dari Semgrep maupun CodeLens:

- **Semgrep** = static analysis rule engine (security, correctness, SCA)
- **CodeLens** = AI-native code intelligence (MCP, guard hooks, query-before-write)
- **Emerge** = exploratory codebase visualization & architecture metrics (force-directed graph, Louvain modularity, change coupling, TF-IDF semantic keywords)

Emerge tidak menemukan bug atau secret — dia **memvisualisasikan struktur dan kompleksitas arsitektur** dalam bentuk interactive HTML/D3 web app. Ini adalah ceruk yang CodeLens **belum sentuh sama sekali**. CodeLens punya `dashboard_engine.py` dan `--format ai`, tapi tidak punya *interactive force-directed graph visualization* dengan community detection.

**13 issue kandidat** (CL-023 s/d CL-035) terbagi dalam 4 tema:

| Tema | Jumlah Issue | Prioritas dominan |
|------|:---:|:---:|
| F. Code Metrics & Architecture Analysis | 4 | P1–P2 |
| G. Graph Visualization & Export | 4 | P1 |
| H. Git History & Change Coupling | 3 | P1–P2 |
| I. Configuration & UX Patterns | 2 | P2 |

**Prinsip serapan:** Emerge berlisensi MIT (sama dengan CodeLens), sehingga *copy-paste kode lebih aman* dibanding dari Semgrep (LGPL-2.1). Namun tetap prioritaskan pola dan arsitektur — bukan blind port — karena Emerge berbasis `pyparsing` + `networkx`, bukan `tree-sitter`.

---

## 2. Snapshot Emerge — Fitur Referensi

### 2.1 Identitas Repo

| Atribut | Nilai |
|---|---|
| Nama | Emerge (PyPI: `emerge-viz`) |
| Tagline | "Interactive code analysis & graph visualization" |
| Branch default | `dev` (bukan `main`) |
| Lisensi | MIT |
| Bahasa implementasi | Python 3.8/3.9/3.10 |
| Parser engine | `pyparsing` (bukan tree-sitter) + `networkx` untuk graph |
| Entry point | `emerge -c config.yaml` atau `python emerge.py -c config.yaml` |
| Jumlah file Python | ~50 file (7914 LOC total) |
| Subcommand | Tidak ada subcommand — single CLI dengan flag `-c`, `-v`, `-d`, `-e`, `-a LANGUAGE` |
| Distribusi | PyPI (`pip install emerge-viz`), Docker (`achtelik/emerge:2.0.0`) |

### 2.2 Arsitektur (Ringkas)

```
emerge/
├── emerge.py                    # CLI entry point
├── emerge/
│   ├── main.py                  # Main orchestrator (17 LOC, hanya argparser)
│   ├── analyzer.py              # Analyzer: brings together config + parsers + results (234 LOC)
│   ├── analysis.py              # Analysis: holds config, metrics, results (435 LOC)
│   ├── config.py                # YAML config parser (756 LOC)
│   ├── core.py                  # Core utilities (60 LOC)
│   ├── files.py                 # File scanning & filtering (161 LOC)
│   ├── graph.py                 # GraphRepresentation + GraphType enum (191 LOC)
│   ├── results.py               # FileResult, EntityResult classes (435 LOC)
│   ├── abstractresult.py        # AbstractResult ABC
│   ├── export.py                # 4 exporter: GraphML, Table, JSON, D3 (529 LOC)
│   ├── stats.py                 # Statistics tracker
│   ├── log.py                   # coloredlogs wrapper
│   ├── appear.py                # Bootstrap (116 LOC)
│   ├── configs/                 # 12 YAML template (default + 11 language)
│   │   ├── default.yaml
│   │   ├── java-template.yaml
│   │   ├── kotlin-template.yaml
│   │   ├── swift-template.yaml
│   │   ├── c-template.yaml
│   │   ├── cpp-template.yaml
│   │   ├── objc-template.yaml
│   │   ├── javascript-template.yaml
│   │   ├── typescript-template.yaml
│   │   ├── ruby-template.yaml
│   │   ├── groovy-template.yaml
│   │   ├── py-template.yaml
│   │   └── go-template.yaml
│   ├── languages/               # 12 parser (pyparsing-based)
│   │   ├── abstractparser.py   # AbstractParser + ParsingMixin + CoreParsingKeyword enum (290 LOC)
│   │   ├── javaparser.py        # Java (267 LOC) — file+entity scan
│   │   ├── swiftparser.py       # Swift (356 LOC) — file+entity scan, includes SwiftUI extraction
│   │   ├── kotlinparser.py      # Kotlin (290 LOC) — file+entity scan, Composable extraction
│   │   ├── groovyparser.py      # Groovy (274 LOC) — file+entity scan
│   │   ├── cparser.py           # C (170 LOC) — file scan only
│   │   ├── cppparser.py         # C++ (170 LOC) — file scan only
│   │   ├── objcparser.py        # Objective-C (165 LOC) — file scan only
│   │   ├── javascriptparser.py  # JavaScript (239 LOC) — file scan only
│   │   ├── typescriptparser.py  # TypeScript (233 LOC) — file scan only
│   │   ├── rubyparser.py        # Ruby (219 LOC) — file scan only
│   │   ├── pyparser.py          # Python (358 LOC) — file scan only
│   │   └── goparser.py          # Go (293 LOC) — file scan only
│   ├── metrics/
│   │   ├── abstractmetric.py   # AbstractMetric, CodeMetric, GraphMetric ABC
│   │   ├── metrics.py            # Metric base classes
│   │   ├── sloc/sloc.py          # Source Lines of Code (164 LOC)
│   │   ├── numberofmethods/      # Number of Methods (114 LOC)
│   │   ├── whitespace/whitespace.py  # Whitespace Complexity (Adam Tornhill impl, 81 LOC)
│   │   ├── faninout/faninout.py  # Fan-In / Fan-Out graph metric (138 LOC)
│   │   ├── modularity/modularity.py  # Louvain Modularity (188 LOC)
│   │   ├── tfidf/tfidf.py        # TF-IDF semantic keyword extraction (118 LOC, sklearn)
│   │   └── git/git.py            # Git metrics via PyDriller (234 LOC)
│   ├── output/html/             # Interactive D3 web app
│   │   ├── emerge.html
│   │   ├── resources/js/
│   │   │   ├── emerge_main.js       # D3 force simulation, UI logic
│   │   │   ├── emerge_graph.js      # Graph rendering
│   │   │   ├── emerge_data.js       # Generated data
│   │   │   ├── emerge_search.js     # Visual live search (OR'ed multi-term)
│   │   │   ├── emerge_heatmap.js    # Heatmap of hotspots (SLOC + Fan-Out score)
│   │   │   ├── emerge_hull.js       # Concave hull of clusters
│   │   │   ├── emerge_git.js        # Git author/contributor display
│   │   │   ├── emerge_ui.js         # UI controls
│   │   │   └── emerge_common.js
│   │   ├── resources/css/custom.css
│   │   └── vendors/                # Bootstrap 5.2.3, D3 v7.8.4, jQuery 3.6, Popper, Hull.js, simpleheat, daterangepicker, dark-mode-switch
│   └── tests/
│       ├── parsers/             # 12 test_*.py per language
│       ├── metrics/             # test_tfidf.py, test_number_of_methods.py
│       ├── config/              # test_config.py
│       └── testdata/            # 12 test data file per language
└── requirements.txt             # networkx, python-louvain, scikit-learn, pydriller, pyparsing, pygraphviz, prettytable, coloredlogs, pyperclip
```

### 2.3 Fitur Unggulan Emerge yang Relevan untuk CodeLens

#### A. YAML Configuration Schema (project + analysis level)

Emerge punya config schema dua-level yang sangat clean:

```yaml
project_name: java_project_example
loglevel: info
analyses:
- analysis_name: full java check
  source_directory: /path/to/source
  only_permit_languages: [java]
  only_permit_file_extensions: [.java]
  ignore_dependencies_containing: [java.util]
  ignore_dependencies_matching: ['^java\.util\.']
  ignore_entities_containing: [NotRelevantClass]
  ignore_entities_matching: ['^Test']
  import_aliases:
    "@foo": src/foo
  override_resolve_dependencies: [...]      # force-resolve deps
  override_do_not_resolve_dependencies: [...]  # force-treat as global
  file_scan:
  - number_of_methods
  - source_lines_of_code
  - dependency_graph
  - fan_in_out
  - louvain_modularity
  - tfidf
  - ws_complexity
  - git_metrics
  entity_scan:
  - dependency_graph
  - inheritance_graph
  - complete_graph
  - source_lines_of_code
  - number_of_methods
  - fan_in_out
  - louvain_modularity
  - tfidf
  export:
  - directory: /path/to/export
  - graphml
  - json
  - tabular_file
  - tabular_console_overall
  - d3
  appconfig:
    radius_fan_out: 0.1
    heatmap_sloc_weight: 1.5
    heatmap_score_limit: 300
```

Konfigurasi yang sangat ekspresif: filter bahasa, ekstensi, ignore pattern (substring + regex), import alias resolution, override resolve behavior, metric selection per-scan-type (file vs entity), export format selection, dan tuning parameter visualisasi.

#### B. Tiga Tipe Graph (Dependency, Inheritance, Complete)

- **Dependency graph** — `A imports B` edge (file atau entity level)
- **Inheritance graph** — `class A extends B` edge (entity level only)
- **Complete graph** — union dari dependency + inheritance
- **Filesystem graph** — directory tree sebagai graph
- **Change coupling graph** — file yang sering di-commit bersamaan (temporal edges dari git history)

CodeLens punya `callgraph_engine.py` dan `circular_engine.py` tapi tidak punya *inheritance graph* dan tidak punya *change coupling graph*.

#### C. Louvain Modularity untuk Community Detection

Implementasi `LouvainModularityMetric` di `emerge/metrics/modularity/modularity.py`:

- Pakai `python-louvain` library (`community.best_partition`)
- 5x optimization runs, lalu averaging untuk stabilitas
- Resolution parameter: 1.5 (lebih tinggi = lebih banyak komunitas kecil)
- Output: `louvain-communities-<graph>` (count), `louvain-modularity-<graph>` (score 0-1), `louvain-biggest-communities-<graph>` (top-5 distribusi)
- Per-node: `louvain-modularity-in-file` / `louvain-modularity-in-entity` (cluster ID assignment)

Ini adalah **architecture fitness metric** yang sangat berharga — memberitahu user apakah codebase modular atau "Big Ball of Mud".

#### D. TF-IDF untuk Semantic Keyword Extraction

Implementasi `TFIDFMetric` di `emerge/metrics/tfidf/tfidf.py`:

- Pakai `scikit-learn`'s `TfidfVectorizer`
- Bahasa-spesifik stopwords (12 set, satu per bahasa)
- Natural language stopwords (preposition, article, dll.)
- Output per-file: top-N keywords dengan TF-IDF score tertinggi
- Dipakai di web app untuk "semantic search" — cari file berdasarkan konsep, bukan literal string

CodeLens punya `semantic_engine.py` tapi fokusnya semantic *similarity* antar symbol, bukan keyword extraction per-file.

#### E. Whitespace Complexity (Adam Tornhill)

Implementasi `WhitespaceMetric` di `emerge/metrics/whitespace/whitespace.py`:

- Hitung indentasi level per-line (tabs + spaces/4)
- Total = sum of all line complexities
- **Insight**: indentasi dalam = nesting tinggi = complex code
- Lebih cepat dari cyclomatic complexity (no AST needed, just regex)
- Borrowed from Adam Tornhill's "Your Code as a Crime Scene" tools

CodeLens punya `complexity_engine.py` (cyclomatic + cognitive) tapi tidak punya whitespace complexity sebagai proxy cepat.

#### F. Fan-In / Fan-Out Graph Metrics

Implementasi `FanInOutMetric` di `emerge/metrics/faninout/faninout.py`:

- `FAN_IN_DEPENDENCY_GRAPH` — count edge masuk ke node
- `FAN_OUT_DEPENDENCY_GRAPH` — count edge keluar dari node
- `AVG_FAN_*` — rata-rata seluruh graph
- `MAX_FAN_*` — nilai maksimum
- `MAX_FAN_*_NAME` — nama node dengan fan tertinggi

CodeLens punya `callgraph_engine.py` tapi tidak ekspos fan-in/fan-out sebagai metrik eksplisit.

#### G. Change Coupling dari Git History

Implementasi di `emerge/metrics/git/git.py`:

- Pakai `PyDriller` untuk traverse commit history
- Untuk setiap commit, ambil daftar modified files
- Buat temporal edge antara setiap pasangan file yang di-commit bersamaan
- Output: `FILE_RESULT_CHANGE_COUPLING_GRAPH` — graph file yang "berubah bersama"
- Insight: file yang sering di-commit bersama = coupling tinggi = mungkin perlu di-refactor atau di-split

CodeLens punya `ownership_engine.py` (git blame) tapi tidak punya change coupling analysis.

#### H. Git-based Code Churn & Author Mapping

Di `emerge/metrics/git/git.py`:

- `file_churn[path] = added_lines + deleted_lines` per commit
- `filepath_author_map[path][author_email] = churn` — siapa berkontribusi ke file apa
- `metric_git_number_authors` — count unique author per file
- Heatmap berdasarkan churn = visualisasi hotspot maintenance

CodeLens `ownership_engine.py` hanya git blame (single author per line), tidak tracking churn multi-commit dan author diversity.

#### I. Interactive D3 Force-Directed Web App

Output `d3` export di `emerge/export.py` + `emerge/output/html/`:

- **Bootstrap 5.2.3** untuk UI panel
- **D3 v7.8.4** untuk force-directed graph simulation
- **Dark mode** support (dark-mode-switch)
- **Visual live search** — OR'ed multiple search terms, highlight matching nodes + edges
- **Heatmap overlay** — node dengan score tinggi (SLOC × Fan-Out) di-render dengan simpleheat.js
- **Concave hull** — cluster boundary visualization via hull.js
- **Date range picker** — filter git timeline
- **Node selection** — Shift+S select, Shift+R reset, Shift+F fade unselected
- **Cluster metrics panel** — % of total SLOC, avg fan-in/out per cluster
- **Keyboard shortcuts** untuk navigasi
- **Contributor display** — node berwarna ungu jika punya contributor, klik untuk lihat list
- **Change coupling overlay** — edge merah antara file yang coupled

CodeLens `dashboard_engine.py` hanya output JSON untuk dashboard eksternal — tidak ada interactive HTML visualization built-in.

#### J. Multiple Export Format

Emerge supports 6 export format (dipilih per-analysis):

| Format | Use case |
|---|---|
| `graphml` | GraphML XML — bisa dibuka di Gephi, yEd, Cytoscape |
| `json` | JSON terstruktur dengan all metrics + statistics |
| `tabular_file` | Text file dengan prettytable |
| `tabular_console` | Print all metrics ke console |
| `tabular_console_overall` | Print hanya overall metrics (bukan per-file) |
| `d3` | Full interactive HTML web app di subfolder `force-graph-html/` |

#### K. Import Aliases & Override Resolve

Emerge bisa:

- `import_aliases: {"@foo": "src/foo"}` — replace substring dalam dependency path
- `override_resolve_dependencies: [...]` — force resolve dep tertentu (bukan treat as global)
- `override_do_not_resolve_dependencies: [...]` — kebalikannya

CodeLens `edge_resolver.py` resolve cross-file edge tapi tidak punya mekanisme override user-configurable.

#### L. Entity-Level Scan untuk OOP Languages

Untuk Java/Kotlin/Swift/Groovy, Emerge ekstrak **entity** (class/struct/protocol) sebagai node terpisah, bukan hanya file. Ini memungkinkan:

- **Inheritance graph** — `class A extends B`
- **Complete graph** — union dependency + inheritance
- **Entity-level metrics** — SLOC per class, methods per class, fan-in/out per class
- **SwiftUI extraction** — ekstrak `View` declarative entities
- **Composable extraction** — ekstrak Jetpack Compose entities

CodeLens parser (terutama `js_backend_parser.py`, `rust_parser.py`) fokus pada function extraction, bukan class/entity-level untuk graph analysis.

#### M. Language Templates Auto-Generation

```bash
emerge -a java  # creates java-template.yaml from built-in template
```

12 template siap pakai (default + 11 language). User tinggal edit `source_directory` dan `export.directory`.

---

## 3. Gap Analysis CodeLens vs Emerge

Tabel ini fokus pada gap yang **belum dicakup** oleh issue Semgrep sebelumnya. Kolom "Sudah ada di Semgrep?" menandai apakah issue ini juga relevan untuk Semgrep (jika ya, mungkin sudah dipertimbangkan di dokumen sebelumnya).

| # | Topik | CodeLens | Emerge | Sudah di Semgrep? | Status |
|---|---|---|---|---|---|
| 23 | YAML project config (project + analysis level) | ⚠️ Hanya `.codelens/codelens.config.json` | ✅ Schema matang, multi-analysis | ⚠️ Sebagian (Semgrep pakai rule YAML, bukan project YAML) | **Perlu serap** |
| 24 | Louvain modularity / community detection | ❌ Tidak ada | ✅ 5-run averaging, resolution 1.5 | ❌ Tidak ada | **Perlu serap** |
| 25 | TF-IDF semantic keyword extraction | ❌ Tidak ada | ✅ sklearn + 12 bahasa stopwords | ❌ Tidak ada | **Perlu serap** |
| 26 | Whitespace complexity (Adam Tornhill) | ❌ Tidak ada | ✅ Regex-based, super cepat | ❌ Tidak ada | **Perlu serap** |
| 27 | Fan-In / Fan-Out graph metrics | ⚠️ Ada callgraph, tapi tidak ekspos sebagai metrik | ✅ Eksplisit dengan max/avg/name | ⚠️ Sebagian | **Perlu serap** |
| 28 | Inheritance graph (OOP class hierarchy) | ❌ Tidak ada | ✅ Java/Kotlin/Swift/Groovy | ❌ Tidak ada | **Perlu serap** |
| 29 | Change coupling graph (git history) | ❌ Tidak ada | ✅ PyDriller + temporal edges | ❌ Tidak ada | **Perlu serap** |
| 30 | Git code churn + author diversity | ⚠️ Hanya git blame single-author | ✅ Multi-commit churn + author map | ❌ Tidak ada | **Perlu serap** |
| 31 | Interactive D3 force-directed web app | ❌ Hanya JSON dashboard | ✅ Bootstrap + D3 + heatmap + hull | ⚠️ Ada web playground, bukan local | **Perlu serap** |
| 32 | GraphML export (Gephi/Cytoscape interop) | ❌ Tidak ada | ✅ `nx.write_graphml` | ❌ Tidak ada | **Perlu serap** |
| 33 | Heatmap visualization (SLOC × Fan-Out hotspot) | ❌ Tidak ada | ✅ simpleheat.js overlay | ❌ Tidak ada | **Perlu serap** |
| 34 | Concave hull cluster boundary | ❌ Tidak ada | ✅ hull.js per-cluster | ❌ Tidak ada | **Perlu serap** |
| 35 | Import aliases & override resolve config | ⚠️ Ada ignore list, tidak ada alias | ✅ `import_aliases` + `override_resolve_*` | ⚠️ Sebagian | **Perlu serap** |

**Catatan:** Issue #CL-023 (YAML config) sebagian overlap dengan rekomendasi Semgrep, tapi pendekatan Emerge berbeda — Emerge fokus pada multi-analysis config dengan metric selection, bukan rule schema.

---

## 4. Daftar Issue untuk Upgrade (CL-023 s/d CL-035)

Setiap issue ditulis dalam format siap-pakai sebagai GitHub issue body. Tinggal copy-paste ke `https://github.com/Wolfvin/CodeLens/issues/new`.

> Konvensi label: `priority:P0` (blocker), `priority:P1` (next release), `priority:P2` (backlog). Topik baru: `topic:metrics`, `topic:visualization`, `topic:git-history`, `topic:config`.

---

### Issue #CL-023 — YAML Project Configuration Schema (Multi-Analysis)

**Priority:** P1
**Topic:** config
**Estimasi:** 1-2 minggu
**Referensi Emerge:** `emerge/config.py` (756 LOC), `emerge/configs/*.yaml` (12 template)

#### Motivasi

CodeLens saat ini pakai `.codelens/codelens.config.json` yang berisi static config (frontend_paths, backend_paths, ignore, frameworks). Tidak ada cara untuk:

1. **Multi-analysis** — jalankan beberapa analysis preset sekaligus (e.g., security audit + quality check + architecture review) dengan config berbeda
2. **Metric selection** — pilih metric mana yang dijalankan per-analysis (e.g., "hanya SLOC + fan-in/out untuk analysis cepat, semua metric untuk audit lengkap")
3. **Override per-analysis** — ignore list, language restriction, file extension filter yang berbeda per-analysis
4. **Share config** — commit config YAML ke repo, sehingga seluruh tim pakai preset yang sama

Emerge punya schema dua-level (project + analysis) yang elegan untuk masalah ini.

#### Acceptance Criteria

- [ ] File `.codelens/codelens.yaml` (baru, berdampingan dengan `codelens.config.json` lama yang akan deprecated)
- [ ] Schema: `project_name`, `loglevel`, `analyses: [analysis_name, source_directory, only_permit_languages, only_permit_file_extensions, ignore_dependencies_containing, ignore_dependencies_matching, file_scan: [metric_list], entity_scan: [metric_list], export: [format_list], appconfig: {...}]`
- [ ] CLI command `codelens analyze -c <yaml-path>` — jalankan semua analysis di config
- [ ] CLI command `codelens analyze -c <yaml-path> --analysis-name <name>` — jalankan satu analysis spesifik
- [ ] Migrasi otomatis: `codelens migrate-config` — konversi `.codelens/codelens.config.json` lama ke `codelens.yaml` baru
- [ ] 6 template bawaan: `codelens init --template security-audit`, `--template quality-gate`, `--template architecture-review`, `--template ai-onboarding`, `--template ci-minimal`, `--template full-scan`
- [ ] Documentasi: `references/project-config.md` dengan 5+ contoh config
- [ ] Backward compatible: jika `codelens.yaml` tidak ada, fallback ke `codelens.config.json` lama

#### Langkah Implementasi

1. Definisi schema di `scripts/config_schema.py` (pydantic dataclass)
2. Tulis `scripts/commands/analyze.py` — orchestrator multi-analysis
3. Tulis `scripts/yaml_config_loader.py` — parser YAML dengan validation
4. Bikin 6 template di `scripts/configs/templates/`
5. Tambah subcommand `migrate-config`
6. Update `init` command untuk generate `codelens.yaml` (bukan `.json`)
7. Test di `tests/test_yaml_config.py`

#### Dependency

- Blocked by: tidak ada
- Blocks: #CL-024 (metric selection perlu schema), #CL-031 (export format selection), #CL-035 (import aliases)

---

### Issue #CL-024 — Louvain Modularity & Community Detection

**Priority:** P1
**Topic:** metrics, architecture
**Estimasi:** 1 minggu
**Referensi Emerge:** `emerge/metrics/modularity/modularity.py` (188 LOC)

#### Motivasi

CodeLens punya `circular_engine.py` (cycle detection) dan `smell_engine.py` (10 kategori smell), tapi tidak punya metrik yang menjawab pertanyaan:

> "Apakah codebase ini modular atau Big Ball of Mud?"

Louvain modularity adalah algoritma community detection yang:

- Hitung score 0-1 (semakin tinggi = semakin modular)
- Assign setiap node ke cluster ID
- Output distribusi 5 cluster terbesar
- Bisa di-run di dependency graph, call graph, atau file graph

Emerge menjalankan 5x run dengan averaging untuk stabilitas (Louvain non-deterministik).

#### Acceptance Criteria

- [ ] CLI command baru: `codelens modularity [workspace] [--graph dependency|call|inheritance|complete]`
- [ ] Output JSON: `{modularity_score: 0.21, communities_count: 3, biggest_communities: [0.49, 0.46, 0.05], node_clusters: {file_path: cluster_id, ...}}`
- [ ] CLI command baru: `codelens clusters [workspace] [--algorithm louvain|greedy-modularity|label-propagation]`
- [ ] Output clusters: list of cluster with members, SLOC, fan-in/out aggregate
- [ ] CLI command baru: `codelens ball-of-mud [workspace]` — return risk score 0-100 berdasarkan modularity + cluster overlap
- [ ] Tambah ke MCP server sebagai tool `codelens_modularity`, `codelens_clusters`, `codelens_ball_of_mud`
- [ ] Library: `networkx` + `python-louvain` (tambah ke `requirements.txt`)
- [ ] Benchmark: 5000 file dependency graph dalam <30 detik
- [ ] Documentasi: `references/architecture-metrics.md`

#### Langkah Implementasi

1. Tambah dependency `python-louvain` ke `setup.sh`
2. Tulis `scripts/modularity_engine.py` — adaptasi dari `emerge/metrics/modularity/modularity.py`
3. Tambah 3 command di `scripts/commands/`
4. Register di `_TOOL_DEFINITIONS` MCP server
5. Test di `tests/test_modularity_engine.py`
6. Benchmark dengan `benchmarks/fixtures/vulnerable_app/`

#### Dependency

- Blocked by: tidak ada (bisa reuse `callgraph_engine.py` dan `edge_resolver.py` untuk graph input)
- Blocks: #CL-033 (heatmap butuh cluster info), #CL-034 (hull butuh cluster boundary)

---

### Issue #CL-025 — TF-IDF Semantic Keyword Extraction per File

**Priority:** P2
**Topic:** metrics, semantic
**Estimasi:** 1 minggu
**Referensi Emerge:** `emerge/metrics/tfidf/tfidf.py` (118 LOC, sklearn-based)

#### Motivasi

CodeLens punya `semantic_engine.py` tapi fokus pada symbol similarity. Emerge mengambil pendekatan berbeda: ekstrak **top-N keyword** per file berdasarkan TF-IDF score.

Use case:

- "File ini tentang apa?" → top-5 keywords: `["user", "auth", "session", "token", "expire"]`
- Semantic search: cari file yang "tentang authentication" tanpa harus match kata literal "authentication"
- Onboarding AI agent: ketika user baru buka file, dapat keyword summary instan
- Detect duplicate concept: dua file dengan top-5 keyword sama mungkin duplikat

#### Acceptance Criteria

- [ ] CLI command baru: `codelens keywords [workspace] [--file <path>] [--top N] [--language auto|py|js|ts|...]`
- [ ] Output: `{file: "src/auth.py", top_keywords: [{word: "user", score: 0.42}, {word: "auth", score: 0.31}, ...]}`
- [ ] Bisa batch mode: `codelens keywords --all --top 10` — untuk semua file, return dict
- [ ] CLI command baru: `codelens semantic-search "authentication"` — return file yang top-keyword-nya match query
- [ ] Stopwords per-bahasa: Python, JS, TS, Java, Go, Rust, Ruby, PHP, C, C++, Swift, Kotlin (12 set, adaptasi dari emerge)
- [ ] Tambah ke MCP server: `codelens_keywords`, `codelens_semantic_search`
- [ ] Library: `scikit-learn` (tambah ke `requirements.txt`)
- [ ] Cache result di `.codelens/keywords_cache.json` (invalidate on file change)
- [ ] Documentasi: `references/semantic-keywords.md`

#### Langkah Implementasi

1. Tambah `scikit-learn` ke `setup.sh` requirements
2. Tulis `scripts/tfidf_engine.py` — adaptasi dari `emerge/metrics/tfidf/tfidf.py`
3. Definisi 12 set stopwords (copy dari emerge, MIT license kompatibel)
4. Tambah 2 command di `scripts/commands/`
5. Register MCP tools
6. Test di `tests/test_tfidf_engine.py`

#### Dependency

- Blocked by: tidak ada
- Blocks: #CL-031 (semantic search bisa integrate ke dashboard)

---

### Issue #CL-026 — Whitespace Complexity Metric (Fast Complexity Proxy)

**Priority:** P2
**Topic:** metrics, quality
**Estimasi:** 3 hari
**Referensi Emerge:** `emerge/metrics/whitespace/whitespace.py` (81 LOC), Adam Tornhill's "Your Code as a Crime Scene"

#### Motivasi

CodeLens `complexity_engine.py` hitung cyclomatic + cognitive complexity yang butuh AST parse — lambat untuk repo besar. Whitespace complexity adalah proxy yang:

- Hanya butuh regex (no AST)
- Hitung indentasi level per-line (tabs + spaces/4)
- 10-100x lebih cepat dari cyclomatic
- Korelasi tinggi dengan nesting depth (indentasi dalam = nested if/for/while = complex)
- Cocok untuk quick scan atau pre-filter (e.g., "tampilkan 20 file paling kompleks berdasarkan whitespace, lalu cyclomatic hanya untuk top-20")

#### Acceptance Criteria

- [ ] Tambah metric `ws_complexity` ke `complexity` command: `codelens complexity --metric ws`
- [ ] Output per-file: `{file: "src/foo.py", ws_complexity: 42.5, ws_complexity_per_line: 0.28}`
- [ ] Overall metric: `avg_ws_complexity`, `max_ws_complexity`, `max_ws_complexity_name`
- [ ] Bisa combine dengan cyclomatic: `codelens complexity --metric all` → output kedua metric
- [ ] Quick mode: `codelens complexity --quick --top 20` — hanya ws_complexity, no AST, untuk repo 5000 file <5 detik
- [ ] Tambah ke MCP tool `codelens_complexity` dengan parameter `metric: cyclomatic|cognitive|ws|all`
- [ ] Documentasi: section "Whitespace Complexity" di `references/quality-metrics.md`

#### Langkah Implementasi

1. Copy `emerge/metrics/whitespace/whitespace.py` ke `scripts/ws_complexity_engine.py` (MIT license, attribution di file header)
2. Adaptasi interface ke CodeLens `base_engine.py` pattern
3. Integrate di `scripts/commands/complexity.py`
4. Tambah `--quick` mode yang skip AST parse
5. Test di `tests/test_ws_complexity.py`

#### Dependency

- Blocked by: tidak ada
- Blocks: tidak ada

---

### Issue #CL-027 — Fan-In / Fan-Out Graph Metrics (Eksplisit)

**Priority:** P1
**Topic:** metrics, architecture
**Estimasi:** 3 hari
**Referensi Emerge:** `emerge/metrics/faninout/faninout.py` (138 LOC)

#### Motivasi

CodeLens `callgraph_engine.py` sudah membangun call graph, tapi tidak ekspos **fan-in** dan **fan-out** sebagai metrik eksplisit. Emerge menghitung:

- `fan_in` — count edge masuk (berapa banyak function yang memanggil function ini)
- `fan_out` — count edge keluar (berapa banyak function yang dipanggil function ini)
- `avg_fan_in`, `avg_fan_out` — rata-rata seluruh graph
- `max_fan_in`, `max_fan_out` — nilai maksimum
- `max_fan_in_name`, `max_fan_out_name` — nama function dengan fan tertinggi

Ini adalah metrik arsitektur kunci:

- Fan-in tinggi = utility function (banyak caller) → jangan diubah sembarangan
- Fan-out tinggi = "god function" (banyak dependency) → kandidat refactor
- Avg fan-in/out rendah = coupling rendah = arsitektur baik

#### Acceptance Criteria

- [ ] CLI command baru: `codelens fan-in-out [workspace] [--name FN] [--top N]`
- [ ] Jika `--name` diberikan: return fan-in dan fan-out untuk function spesifik + list caller/callee
- [ ] Jika tanpa `--name`: return top-N function dengan fan-in tertinggi + top-N dengan fan-out tertinggi
- [ ] Output overall: `{avg_fan_in, avg_fan_out, max_fan_in, max_fan_in_name, max_fan_out, max_fan_out_name}`
- [ ] Bisa filter by domain: `--domain backend|frontend`
- [ ] Tambah ke MCP server: `codelens_fan_in_out`
- [ ] Integrate dengan `impact` command: tampilkan fan-in/out di output impact analysis
- [ ] Documentasi: section "Fan-In / Fan-Out" di `references/architecture-metrics.md`

#### Langkah Implementasi

1. Tambah method `calculate_fan_in_out()` di `scripts/callgraph_engine.py`
2. Tulis `scripts/commands/fan_in_out.py`
3. Register di command registry
4. Tambah MCP tool definition
5. Update `impact_engine.py` untuk include fan-in/out
6. Test di `tests/test_fan_in_out.py`

#### Dependency

- Blocked by: tidak ada (callgraph sudah ada)
- Blocks: #CL-033 (heatmap butuh fan-out untuk hotspot score)

---

### Issue #CL-028 — Inheritance Graph (Class Hierarchy Visualization)

**Priority:** P2
**Topic:** metrics, architecture
**Estimasi:** 2-3 minggu
**Referensi Emerge:** `emerge/graph.py` (`GraphType.ENTITY_RESULT_INHERITANCE_GRAPH`), `emerge/languages/javaparser.py`, `emerge/languages/swiftparser.py`

#### Motivasi

CodeLens parser fokus pada function extraction (`js_backend_parser.py`, `rust_parser.py`, `python_parser.py`). Untuk OOP languages (Java, Kotlin, Swift, C++, Python class), belum ada graph yang menunjukkan **class inheritance hierarchy**.

Use case:

- "Class mana yang paling banyak di-extend?" → kandidat abstract base class yang penting
- "Class mana yang punya hierarchy paling dalam?" → smell god class
- "Apakah class X inherit dari class Y?" → impact analysis sebelum modify parent
- Circular inheritance detection (CodeLens sudah punya `circular_engine.py` tapi untuk module deps, bukan class inheritance)

#### Acceptance Criteria

- [ ] Extend `python_parser.py`, `js_backend_parser.py`, `ts_backend_parser.py`, `tsx_parser.py`, `rust_parser.py`, `vue_parser.py`, `svelte_parser.py` untuk extract class + parent class
- [ ] Extend fallback parsers untuk Java, Kotlin, Swift, C++, C#, PHP, Ruby (extract class + extends/implements)
- [ ] CLI command baru: `codelens inheritance [workspace] [--class NAME] [--depth N]`
- [ ] Jika `--class` diberikan: return ancestor chain + descendant tree
- [ ] Jika tanpa argumen: return overall inheritance stats (`{total_classes, max_depth, max_depth_class, classes_with_most_children: top-10}`)
- [ ] CLI command baru: `codelens god-class [workspace]` — detect class dengan >20 children atau >5 level depth
- [ ] Graph type baru di `callgraph_engine.py`: `inheritance_graph`
- [ ] Tambah ke MCP server: `codelens_inheritance`, `codelens_god_class`
- [ ] Output GraphML yang bisa dibuka di Gephi (lint ke Issue #CL-032)
- [ ] Documentasi: `references/inheritance-graph.md`

#### Langkah Implementasi

1. Audit setiap parser — tambahkan `extract_classes()` method
2. Tambah `inheritance_graph` build di `callgraph_engine.py`
3. Tulis `scripts/commands/inheritance.py` dan `scripts/commands/god_class.py`
4. Test dengan fixture `benchmarks/fixtures/vulnerable_app/src/complex_processor.py` (harusnya punya class hierarchy)
5. Test cross-bahasa: Python class yang inherit dari C extension (skip dengan warning)

#### Dependency

- Blocked by: tidak ada
- Blocks: tidak ada (tapi issue #CL-019 language coverage akan membantu ekstraksi inheritance di lebih banyak bahasa)

---

### Issue #CL-029 — Change Coupling Graph (Git History Analysis)

**Priority:** P1
**Topic:** git-history, architecture
**Estimasi:** 1-2 minggu
**Referensi Emerge:** `emerge/metrics/git/git.py` (234 LOC), `emerge/graph.py` (`GraphType.FILE_RESULT_CHANGE_COUPLING_GRAPH`)

#### Motivasi

Change coupling adalah konsep dari Adam Tornhill's "Your Code as a Crime Scene":

> "Files yang sering di-commit bersamaan = coupled secara logika, walaupun tidak ada import statement."

Contoh: `UserController.java` dan `UserView.java` tidak import satu sama lain, tapi 80% commit yang ubah salah satunya juga ubah yang lain → coupled.

Ini metrik yang **tidak bisa didapat dari static analysis** — perlu git history. Manfaat:

- Detect hidden coupling yang tidak terlihat dari import graph
- Predict impact: "kalau saya ubah file A, file mana yang juga harus di-ubah?"
- Find refactor candidate: file yang terlalu coupled mungkin harus di-merge atau di-split
- Detect "shotgun surgery" smell: satu perubahan kebutuhan touch 20 file

CodeLens `ownership_engine.py` hanya git blame. Tidak ada temporal edge analysis.

#### Acceptance Criteria

- [ ] CLI command baru: `codelens change-coupling [workspace] [--commit-limit 150] [--exclude-merge] [--since YYYY-MM-DD]`
- [ ] Output: graph file dengan temporal edge weight = jumlah commit yang touch kedua file bersamaan
- [ ] CLI command baru: `codelens shotgun-surgery [workspace] [--threshold 10]` — detect file yang sering di-touch bersamaan dengan >10 file lain
- [ ] CLI command baru: `codelens coupled-with <file>` — return top-10 file yang paling sering coupled dengan file input
- [ ] Integrate dengan `impact` command: tampilkan "files coupled by git history" di output impact analysis
- [ ] Library: `pydriller` (tambah ke `requirements.txt`)
- [ ] Output GraphML (lint ke Issue #CL-032)
- [ ] Tambah ke MCP server: `codelens_change_coupling`, `codelens_shotgun_surgery`, `codelens_coupled_with`
- [ ] Performance: 1000 commit dalam <60 detik
- [ ] Documentasi: `references/change-coupling.md`

#### Langkah Implementasi

1. Tambah `pydriller` ke `setup.sh` requirements
2. Tulis `scripts/change_coupling_engine.py` — adaptasi dari `emerge/metrics/git/git.py`
3. Tulis 3 command di `scripts/commands/`
4. Update `impact_engine.py` untuk include coupled files
5. Register MCP tools
6. Test dengan repo CodeLens sendiri sebagai fixture
7. Documentasi

#### Dependency

- Blocked by: tidak ada
- Blocks: tidak ada (tapi sinergi dengan #CL-030 git churn)

---

### Issue #CL-030 — Git Code Churn & Author Diversity Metrics

**Priority:** P2
**Topic:** git-history, ownership
**Estimasi:** 1 minggu
**Referensi Emerge:** `emerge/metrics/git/git.py` (variable `file_churn`, `filepath_author_map`)

#### Motivasi

CodeLens `ownership_engine.py` pakai `git blame` — hanya tahu author terakhir per line. Emerge menghitung:

- `code_churn` per file = sum of (added + deleted lines) across N commit terakhir
- `number_authors` per file = count unique contributor
- `author_map` per file = `{author_email: churn_contribution}`

Use case:

- "File ini di-churn 5000 line dalam 30 hari terakhir" → hotspot maintenance, mungkin perlu refactor
- "File ini ditulis 1 author saja" → bus factor risk
- "File ini di-churn 5 author berbeda" → mungkin tidak ada owner yang jelas, conflict risk
- Heatmap code churn = visualisasi hotspot (lint ke #CL-033)

#### Acceptance Criteria

- [ ] Extend `ownership_engine.py` untuk include `code_churn`, `number_authors`, `author_map`
- [ ] CLI command baru: `codelens hotspot [workspace] [--metric churn|authors|both] [--top N] [--since YYYY-MM-DD]`
- [ ] Output: top-N file dengan churn tertinggi, dengan breakdown per-author
- [ ] CLI command baru: `codelens bus-factor [workspace]` — return files dengan number_authors < 2 (single-author risk)
- [ ] Extend `ownership` command output dengan field baru: `code_churn_30d`, `code_churn_90d`, `number_authors`, `top_contributors: [{email, churn}]`
- [ ] Library: `pydriller` (sudah ditambah di #CL-029)
- [ ] Tambah ke MCP server: `codelens_hotspot`, `codelens_bus_factor`
- [ ] Documentasi: section "Code Churn & Author Diversity" di `references/git-metrics.md` (baru)

#### Langkah Implementasi

1. Refactor `scripts/ownership_engine.py` untuk traverse git history (bukan hanya `git blame`)
2. Tambah 2 command baru
3. Extend output `ownership` command
4. Register MCP tools
5. Test dengan repo CodeLens sendiri

#### Dependency

- Blocked by: #CL-029 (library `pydriller` harus sudah ditambah)
- Blocks: #CL-033 (heatmap bisa overlay churn)

---

### Issue #CL-031 — Interactive D3 Force-Directed Web App Dashboard

**Priority:** P1
**Topic:** visualization
**Estimasi:** 3-4 minggu
**Referensi Emerge:** `emerge/output/html/` (full Bootstrap + D3 + jQuery + hull.js + simpleheat.js app), `emerge/export.py::D3Exporter`

#### Motivasi

CodeLens `dashboard_engine.py` hanya menghasilkan JSON untuk dashboard eksternal. Tidak ada **interactive visualization built-in**. Emerge menghasilkan self-contained HTML web app yang bisa langsung `file://` di browser — dengan fitur:

- **Force-directed graph** — node = file/function/class, edge = dependency/call/inheritance
- **Cluster coloring** — Louvain modularity assignment, cluster ID menentukan warna
- **Node size** — proporsional ke SLOC, fan-out, atau metric lain
- **Hover tooltip** — tampilkan semua metric node
- **Click** — highlight node + neighbors, fade yang lain
- **Search** — visual live search dengan OR'ed multi-term
- **Heatmap overlay** — node dengan score tinggi di-render dengan simpleheat
- **Cluster hull** — concave hull boundary per-cluster
- **Dark mode** toggle
- **Keyboard shortcuts** — Shift+S select, Shift+R reset, Shift+F fade
- **Date range picker** — filter git timeline
- **Zoom/pan/drag** — standard D3 force graph interaction

Ini adalah **visi killer feature** untuk CodeLens — bayangkan AI agent run `codelens scan`, lalu user buka `file:///path/.codelens/dashboard/emerge.html` dan bisa eksplor arsitektur secara interaktif. Jauh lebih komunikatif daripada JSON dump.

#### Acceptance Criteria

- [ ] CLI command baru: `codelens dashboard [workspace] [--graph dependency|call|inheritance|coupling|all] [--open]`
- [ ] Flag `--open` otomatis buka browser default ke `file:///path/.codelens/dashboard/index.html`
- [ ] Output: self-contained HTML + JS + CSS di `.codelens/dashboard/`
- [ ] Vendor libraries bundled: D3 v7, Bootstrap 5, jQuery 3.6, simpleheat.js, hull.js, daterangepicker, dark-mode-switch
- [ ] Fitur minimal: force-directed graph, node size by metric, hover tooltip, click highlight, search, dark mode
- [ ] Fitur lanjutan: heatmap overlay, cluster hull, date range picker (untuk git metrics)
- [ ] Bisa switch graph type di UI (radio button): dependency / call / inheritance / change coupling
- [ ] Bisa switch metric untuk node size (dropdown): SLOC / fan-out / complexity / churn
- [ ] Export PNG/SVG dari graph (D3 built-in)
- [ ] Performance: render 5000 node di <3 detik, smooth pan/zoom
- [ ] Mobile responsive (Bootstrap sudah handle sebagian besar)
- [ ] Documentasi: `references/interactive-dashboard.md` dengan screenshot
- [ ] Tambah ke MCP server: `codelens_dashboard` — generate dan return file path

#### Langkah Implementasi

1. Copy vendor libraries dari `emerge/output/html/vendors/` ke `scripts/dashboard/vendors/`
2. Adaptasi `emerge/output/html/emerge.html` → `scripts/dashboard/template.html`
3. Adaptasi 8 JS file (`emerge_main.js`, `emerge_graph.js`, `emerge_data.js`, `emerge_search.js`, `emerge_heatmap.js`, `emerge_hull.js`, `emerge_git.js`, `emerge_ui.js`) — rename prefix `emerge_` → `codelens_`, sesuaikan metric names
4. Tulis `scripts/dashboard_engine_v2.py` (replace existing `dashboard_engine.py`) — generate data JSON + template render
5. Tulis `scripts/commands/dashboard.py`
6. Tambah CLI argparser
7. Test dengan `benchmarks/fixtures/vulnerable_app/`
8. Performance tuning: jika >5000 node, sampling atau clustering otomatis

#### Dependency

- Blocked by: #CL-024 (Louvain untuk cluster coloring), #CL-027 (fan-in/out untuk node size), #CL-029 (change coupling graph untuk graph type baru)
- Blocks: #CL-033 (heatmap), #CL-034 (hull)

---

### Issue #CL-032 — GraphML Export (Gephi/Cytoscape/yEd Interop)

**Priority:** P1
**Topic:** output, visualization
**Estimasi:** 2-3 hari
**Referensi Emerge:** `emerge/export.py::GraphExporter.export_graph_as_graphml` (1 baris: `nx.write_graphml(graph, path)`)

#### Motivasi

GraphML adalah format XML standar untuk graph yang didukung oleh:

- **Gephi** — open-source graph visualization desktop app (sangat powerful untuk exploratory analysis)
- **Cytoscape** — bioinformatics graph tool, juga populer untuk code graph
- **yEd** — diagram editor dengan layout algorithm
- **Neo4j** — graph database bisa import GraphML

CodeLens saat ini hanya output JSON + SARIF + Markdown. Dengan GraphML, user bisa:

- Eksplor graph di Gephi dengan layout algorithm canggih (ForceAtlas 2, OpenOrd, dll.)
- Filter node/edge dengan Gephi's filter pipeline
- Run community detection algorithm lain (Louvain, Modularity, Connected Components) di Gephi
- Export ke PNG/SVG/PDF dengan kualitas publikasi

#### Acceptance Criteria

- [ ] Flag `--format graphml` di `scan`, `trace`, `impact`, `circular`, `callgraph` (baru), `change-coupling` (baru)
- [ ] Output: `.codelens/exports/<command>-<timestamp>.graphml`
- [ ] GraphML node attributes: `name`, `file`, `line`, `language`, `sloc`, `fan_in`, `fan_out`, `complexity`, `cluster_id`
- [ ] GraphML edge attributes: `type` (call/import/inherit/coupling), `weight` (untuk coupling)
- [ ] Bisa combine multiple graph: `--format graphml --graph dependency,inheritance,coupling`
- [ ] Library: `networkx` (kemungkinan sudah ada jika #CL-024 diimplementasi)
- [ ] Documentasi: section "GraphML Export" di `references/output-formats.md`
- [ ] Tutorial: cara buka di Gephi (5 langkah dengan screenshot)

#### Langkah Implementasi

1. Pastikan `networkx` ada di `requirements.txt`
2. Tambah method `to_graphml()` di setiap engine yang punya graph (`callgraph_engine.py`, `circular_engine.py`, `edge_resolver.py`, `change_coupling_engine.py` baru)
3. Tambah `--format graphml` di argparser
4. Test dengan Gephi (manual QA)

#### Dependency

- Blocked by: #CL-024 (networkx dependency)
- Blocks: tidak ada

---

### Issue #CL-033 — Heatmap Visualization (SLOC × Fan-Out Hotspot)

**Priority:** P2
**Topic:** visualization
**Estimasi:** 3-5 hari
**Referensi Emerge:** `emerge/output/html/resources/js/emerge_heatmap.js`, `emerge/output/html/vendors/simpleheat/simpleheat.js`, `emerge/analysis.py::appconfig.heatmap_*`

#### Motivasi

Heatmap adalah cara visual untuk menunjukkan **hotspot** — file/function yang berisiko tinggi. Emerge menghitung hotspot score sebagai weighted sum:

```
hotspot_score = (sloc_weight × sloc) + (fan_out_weight × fan_out)
```

Default weight: SLOC 1.5, Fan-Out 1.7. Score threshold: base 10, limit 300. File dengan score di atas threshold di-render dengan warna panas (merah → kuning).

Use case:

- Quick scan: "Mana 20 file paling berisiko?" → lihat heatmap
- Communicate risk ke stakeholder non-teknis (heatmap lebih intuitif daripada JSON metric)
- Track hotspot over time: heatmap bulan ini vs bulan lalu → apakah refactor berhasil mengurangi hotspot?

#### Acceptance Criteria

- [ ] CLI command baru: `codelens hotspot-score [workspace] [--top N] [--weights sloc:1.5,fan_out:1.7,churn:1.3]`
- [ ] Output JSON: `[{file, sloc, fan_out, churn, hotspot_score, severity}, ...]` sorted by score desc
- [ ] Integrate ke dashboard (#CL-031): toggle "Show Heatmap" — overlay simpleheat.js di atas graph
- [ ] Configurable weights via `codelens.yaml`: `appconfig.heatmap_sloc_weight`, `heatmap_fan_out_weight`, `heatmap_churn_weight`, `heatmap_score_base`, `heatmap_score_limit`
- [ ] Heatmap mode: `metric` (SLOC × Fan-Out), `churn` (git churn), `hybrid` (combined)
- [ ] Bisa export heatmap data sebagai CSV untuk spreadsheet
- [ ] Tambah ke MCP server: `codelens_hotspot_score`
- [ ] Documentasi: `references/hotspot-visualization.md`

#### Langkah Implementasi

1. Tulis `scripts/hotspot_engine.py` — weighted sum calculation
2. Tambah command `hotspot-score`
3. Integrate ke dashboard JS (`emerge_heatmap.js` → `codelens_heatmap.js`)
4. Tambah config keys di YAML schema (#CL-023)
5. Register MCP tool
6. Test dengan fixture `vulnerable_app/`

#### Dependency

- Blocked by: #CL-027 (fan-out metric), #CL-031 (dashboard untuk overlay)
- Blocks: tidak ada

---

### Issue #CL-034 — Concave Hull Cluster Boundary Visualization

**Priority:** P2
**Topic:** visualization
**Estimasi:** 2-3 hari
**Referensi Emerge:** `emerge/output/html/resources/js/emerge_hull.js`, `emerge/output/html/vendors/hull/hull.js`

#### Motivasi

Setelah #CL-024 (Louvain modularity) memberi setiap node cluster ID, dan #CL-031 (dashboard) merender graph force-directed, **concave hull** menggambar boundary melingkupi setiap cluster. Manfaat:

- Visual boundary antar cluster → cepat identifikasi "cluster mana yang besar?", "cluster mana yang overlap?"
- Detect "Big Ball of Mud": jika hull semua cluster overlap jadi satu → arsitektur jelek
- Detect isolated cluster: hull tidak overlap sama sekali → modularitas baik
- Click hull untuk select semua node di cluster

#### Acceptance Criteria

- [ ] Integrate `hull.js` ke dashboard vendor libraries (sudah ada di #CL-031)
- [ ] Adaptasi `emerge_hull.js` → `codelens_hull.js`
- [ ] Toggle "Show Cluster Hulls" di dashboard UI
- [ ] Click hull → select all nodes in cluster, fade others
- [ ] Hover hull → highlight boundary, show cluster metrics (SLOC total, avg fan-in, dll.)
- [ ] Color hull = cluster color (alpha 0.2 untuk fill, 1.0 untuk stroke)
- [ ] Bisa toggle individual hull: checkbox per cluster ID di side panel
- [ ] Documentasi: section "Cluster Hull Visualization" di `references/interactive-dashboard.md`

#### Langkah Implementasi

1. Hull.js sudah bundled di #CL-031
2. Port `emerge_hull.js` logic ke `codelens_hull.js`
3. Tambah toggle UI di dashboard template
4. Test dengan fixture `vulnerable_app/` yang punya multi-module structure

#### Dependency

- Blocked by: #CL-024 (cluster ID assignment), #CL-031 (dashboard)
- Blocks: tidak ada

---

### Issue #CL-035 — Import Aliases & Override Resolve Configuration

**Priority:** P2
**Topic:** config, edge-resolution
**Estimasi:** 1 minggu
**Referensi Emerge:** `emerge/config.py` (key `import_aliases`, `override_resolve_dependencies`, `override_do_not_resolve_dependencies`)

#### Motivasi

CodeLens `edge_resolver.py` resolve cross-file import edge dengan heuristik (basename matching, path search). Tapi tidak ada cara untuk user meng-override:

1. **Import aliases** — modern JS/TS pakai path alias (`@components/Button` → `src/components/Button`). CodeLens tidak tahu mapping ini, sehingga edge ke `@components/Button` tidak ter-resolve.
2. **Force resolve** — beberapa dependency eksternal (e.g., `lodash`) sebenarnya punya type definition lokal. User ingin CodeLens treat `import _ from 'lodash'` sebagai edge ke `src/types/lodash.d.ts`.
3. **Force NOT resolve** — sebaliknya, dependency yang ter-resolve tapi sebenarnya global (e.g., `react` di monorepo) ingin diabaikan.

Emerge punya 3 key konfigurasi untuk kasus ini.

#### Acceptance Criteria

- [ ] Tambah key `import_aliases` di `codelens.yaml` (lint ke #CL-023): `{"@components": "src/components", "@utils": "src/utils"}`
- [ ] Auto-detect import aliases dari:
  - `tsconfig.json` paths
  - `jsconfig.json` paths
  - `package.json` imports field
  - `vite.config.js`/`webpack.config.js` resolve.alias
- [ ] Tambah key `override_resolve_dependencies: [...]` — force resolve dep tertentu
- [ ] Tambah key `override_do_not_resolve_dependencies: [...]` — force treat as global
- [ ] Update `edge_resolver.py` untuk konsumsi config ini
- [ ] CLI command `codelens resolve-check <dependency>` — debug apakah dependency ter-resolve atau tidak, dan kenapa
- [ ] Documentasi: section "Import Aliases & Override Resolve" di `references/project-config.md`

#### Langkah Implementasi

1. Tambah 3 field di YAML schema (#CL-023)
2. Tulis `scripts/import_alias_detector.py` — auto-detect dari config file populer
3. Update `edge_resolver.py` untuk apply aliases sebelum resolve
4. Tambah `resolve-check` command
5. Test dengan repo Next.js + Tailwind (typical alias usage)

#### Dependency

- Blocked by: #CL-023 (YAML config schema)
- Blocks: tidak ada

---

## 5. Roadmap & Sinergi dengan Issue Semgrep

### 5.1 Matriks Prioritas (lanjutan dari dokumen Semgrep)

| Issue | Priority | Effort | Dependency | Tema |
|---|:---:|:---:|---|---|
| #CL-023 YAML Project Config | P1 | 1-2w | — | config |
| #CL-024 Louvain Modularity | P1 | 1w | — | metrics, architecture |
| #CL-027 Fan-In/Fan-Out | P1 | 3d | — | metrics, architecture |
| #CL-029 Change Coupling Graph | P1 | 1-2w | — | git-history, architecture |
| #CL-031 Interactive D3 Dashboard | P1 | 3-4w | #CL-024, #CL-027, #CL-029 | visualization |
| #CL-032 GraphML Export | P1 | 2-3d | #CL-024 | output, visualization |
| #CL-025 TF-IDF Keywords | P2 | 1w | — | metrics, semantic |
| #CL-026 Whitespace Complexity | P2 | 3d | — | metrics, quality |
| #CL-028 Inheritance Graph | P2 | 2-3w | — | metrics, architecture |
| #CL-030 Git Code Churn | P2 | 1w | #CL-029 | git-history, ownership |
| #CL-033 Heatmap Visualization | P2 | 3-5d | #CL-027, #CL-031 | visualization |
| #CL-034 Concave Hull | P2 | 2-3d | #CL-024, #CL-031 | visualization |
| #CL-035 Import Aliases Config | P2 | 1w | #CL-023 | config, edge-resolution |

### 5.2 Sinergi dengan Issue Semgrep (CL-001 s/d CL-022)

Beberapa issue Emerge **mempengaruhi** atau **dipengaruhi** oleh issue Semgrep:

| Issue Emerge | Sinergi dengan Issue Semgrep |
|---|---|
| #CL-023 YAML Config | Bisa jadi tempat unified config untuk Semgrep rule path (`rule_pack: ./rules/`) — kombinasikan dengan #CL-021 (Config Resolver Semgrep) |
| #CL-024 Louvain Modularity | Hasil cluster ID bisa jadi input untuk #CL-001 rule language (e.g., "rule hanya fire di cluster X") |
| #CL-026 Whitespace Complexity | Bisa pre-filter untuk #CL-009 (Pre-Filtering Optimization) — file dengan ws_complexity rendah skip AST parse |
| #CL-027 Fan-In/Fan-Out | Hasil fan-in tinggi = "popular function" → bisa prioritaskan untuk #CL-020 (Disk Cache) |
| #CL-028 Inheritance Graph | Untuk OOP language, inheritance edge bisa jadi input ke #CL-019 (Language Coverage Go/Java/Ruby/PHP/C++) — parser harus ekstrak `extends`/`implements` |
| #CL-029 Change Coupling | Hasil coupled-files bisa enhance #CL-010 (Baseline/Diff Scan) — saat baseline commit, juga mark coupled files sebagai "probable affected" |
| #CL-030 Git Code Churn | Bisa enhance #CL-017 (Historical Secrets) — prioritaskan commit dengan churn tinggi untuk secret scan |
| #CL-031 Interactive Dashboard | Bisa visualize finding dari Semgrep rule (#CL-001) — node berwarna merah jika ada security finding |
| #CL-032 GraphML Export | Bisa export finding Semgrep sebagai graph attribute → analyze di Gephi |
| #CL-035 Import Aliases | Bisa enhance #CL-001 pattern matching — `$X` metavariable bisa resolve alias |

### 5.3 Quick Wins (bisa mulai minggu ini, tanpa dependency)

Issue-issue ini bisa langsung dikerjakan tanpa menunggu fondasi:

1. **#CL-026 Whitespace Complexity** — 3 hari, copy dari emerge (MIT, attribution)
2. **#CL-027 Fan-In/Fan-Out** — 3 hari, reuse `callgraph_engine.py` yang sudah ada
3. **#CL-032 GraphML Export** — 2-3 hari, satu baris `nx.write_graphml` per graph
4. **#CL-024 Louvain Modularity** — 1 minggu, adaptasi dari emerge (188 LOC)
5. **#CL-025 TF-IDF Keywords** — 1 minggu, adaptasi dari emerge (118 LOC)

Kelima quick win ini **total ~4 minggu effort** untuk satu developer, dan akan menambah 5 metric/feature baru yang signifikan.

### 5.4 3-Sprint Roadmap Tambahan (lanjutan dari dokumen Semgrep)

Jika ditambahkan ke roadmap Semgrep yang sudah ada:

#### Sprint 4 — Architecture Metrics Foundation
Fokus: metric arsitektur yang belum ada.

- #CL-024 Louvain Modularity (1w)
- #CL-027 Fan-In/Fan-Out (3d)
- #CL-026 Whitespace Complexity (3d)
- #CL-025 TF-IDF Keywords (1w, paralel)
- #CL-023 YAML Project Config (1-2w, paralel)

#### Sprint 5 — Git History & Coupling
Fokus: insight dari git history yang tidak bisa didapat dari static analysis.

- #CL-029 Change Coupling Graph (1-2w)
- #CL-030 Git Code Churn (1w, setelah #CL-029)
- #CL-028 Inheritance Graph (2-3w, paralel)
- #CL-035 Import Aliases Config (1w, setelah #CL-023)

#### Sprint 6 — Interactive Visualization
Fokus: killer feature untuk diferensiasi.

- #CL-031 Interactive D3 Dashboard (3-4w, prioritas tinggi)
- #CL-032 GraphML Export (2-3d, paralel)
- #CL-033 Heatmap Visualization (3-5d, setelah #CL-031)
- #CL-034 Concave Hull (2-3d, setelah #CL-031)

### 5.5 Total Estimasi Effort Tambahan

- **P1 (Sprint 4-6):** ~10-14 minggu
- **P2 (backlog):** ~6-9 minggu
- **Total jika satu developer:** ~16-23 minggu (4-6 bulan)
- **Total jika 3 developer paralel:** ~6-8 minggu (1.5-2 bulan)

### 5.6 Pertimbangan Strategis

**Kenapa issue Emerge penting meskipun CodeLens sudah punya positioning AI-native?**

1. **AI agent butuh visual context** — saat AI agent bekerja di codebase besar, dia perlu "melihat" struktur. Dashboard interaktif (#CL-031) bisa menjadi shared artifact antara AI dan human reviewer.
2. **Architecture metric = decision support** — fan-in/out, modularity, change coupling membantu AI agent (dan human) memutuskan "apakah aman mengubah function X?" lebih baik daripada hanya `impact` command.
3. **Visualisasi = differentiation** — Semgrep punya web playground (online), tapi tidak ada local interactive dashboard. CodeLens bisa unggul di sini.
4. **Onboarding** — dashboard interaktif adalah cara tercepat untuk onboarding developer baru ke codebase yang tidak familiar.
5. **Cross-tool interop** — GraphML export membuka ekosistem Gephi/Cytoscape yang punya ribinan user.

**Yang TIDAK perlu diserap dari Emerge:**

1. **`pyparsing` parser** — CodeLens sudah pakai `tree-sitter` yang lebih akurat. Jangan downgrade.
2. **Entity extraction hanya untuk 4 bahasa** (Java/Kotlin/Swift/Groovy) — CodeLens harus ekstrak class di semua OOP language yang didukung, bukan subset.
3. **`pyparsing` grammar definitions** — terlalu verbose dan rapuh dibanding tree-sitter.
4. **Docker container distribution** — CodeLens sudah distribusi via `pip`/`setup.sh`. Docker opsional, bukan prioritas.
5. **`pyperclip` clipboard integration** — niche feature, skip.

---

## 6. Appendix — Peta File Emerge ke Topik Issue

| Issue | File Referensi Emerge |
|---|---|
| #CL-023 | `emerge/config.py` (756 LOC), `emerge/configs/*.yaml` (12 template), `emerge/analysis.py` (Analysis class) |
| #CL-024 | `emerge/metrics/modularity/modularity.py` (188 LOC), `emerge/graph.py` (`GraphType.ENTITY_RESULT_*`) |
| #CL-025 | `emerge/metrics/tfidf/tfidf.py` (118 LOC, sklearn), `emerge/analysis.py` (stopwords integration) |
| #CL-026 | `emerge/metrics/whitespace/whitespace.py` (81 LOC), Adam Tornhill's "Your Code as a Crime Scene" |
| #CL-027 | `emerge/metrics/faninout/faninout.py` (138 LOC) |
| #CL-028 | `emerge/graph.py` (`GraphType.ENTITY_RESULT_INHERITANCE_GRAPH`, `GraphType.ENTITY_RESULT_COMPLETE_GRAPH`), `emerge/languages/javaparser.py` (entity extraction), `emerge/languages/swiftparser.py` (SwiftUI extraction), `emerge/languages/kotlinparser.py` (Composable extraction) |
| #CL-029 | `emerge/metrics/git/git.py` (234 LOC, `_calculate_git_metrics`), `emerge/graph.py` (`GraphType.FILE_RESULT_CHANGE_COUPLING_GRAPH`) |
| #CL-030 | `emerge/metrics/git/git.py` (variable `file_churn`, `filepath_author_map`, `metric_git_number_authors`), `emerge/output/html/resources/js/emerge_git.js` |
| #CL-031 | `emerge/output/html/emerge.html`, `emerge/output/html/resources/js/emerge_main.js`, `emerge/export.py::D3Exporter.export_d3_force_directed_graph`, `emerge/output/html/vendors/` (Bootstrap, D3 v7.8.4, jQuery, Popper, Hull.js, simpleheat, daterangepicker, dark-mode-switch) |
| #CL-032 | `emerge/export.py::GraphExporter.export_graph_as_graphml` (1 LOC: `nx.write_graphml(graph, path)`) |
| #CL-033 | `emerge/output/html/resources/js/emerge_heatmap.js`, `emerge/output/html/vendors/simpleheat/simpleheat.js`, `emerge/analysis.py::appconfig.heatmap_*` |
| #CL-034 | `emerge/output/html/resources/js/emerge_hull.js`, `emerge/output/html/vendors/hull/hull.js` |
| #CL-035 | `emerge/config.py` (line 531-554, key `import_aliases`, `override_resolve_dependencies`, `override_do_not_resolve_dependencies`), `emerge/languages/abstractparser.py::ParsingMixin.resolve_relative_dependency_path` |

---

## 7. Catatan Akhir

### 7.1 Aturan Serapan dari Emerge

Berbeda dengan Semgrep (LGPL-2.1), **Emerge berlisensi MIT** — sama dengan CodeLens. Ini memberi fleksibilitas lebih:

- ✅ **Boleh copy-paste kode** dengan attribution di file header (e.g., `# Adapted from emerge (glato/emerge), MIT License`)
- ✅ **Boleh adaptasi algoritma** tanpa konflik lisensi
- ✅ **Boleh bundle vendor JS** (D3, Bootstrap, jQuery — semuanya MIT atau kompatibel)
- ⚠️ **Tetap prioritaskan pola** — bukan blind port. Emerge pakai `pyparsing`, CodeLens pakai `tree-sitter`. Adaptasi logic, bukan parser code.
- ⚠️ **Test dengan fixture CodeLens** — jangan asumsi fixture Emerge compatible. Buat fixture baru di `tests/fixtures/` jika perlu.

### 7.2 Quick Comparison: CodeLens vs Emerge vs Semgrep

| Dimensi | CodeLens | Emerge | Semgrep |
|---|---|---|---|
| **Positioning** | AI-native code intelligence | Codebase visualization & architecture metrics | Static analysis rule engine |
| **Parser engine** | tree-sitter (9 bahasa) + regex fallback (20+) | pyparsing (12 bahasa) | tree-sitter + pfff (40+ bahasa) |
| **CLI command count** | 56 | 1 (single CLI with `-c` flag) | 10 subcommand |
| **MCP tool count** | 49 | 0 (no MCP support) | 9 |
| **Output format** | JSON, SARIF, Markdown | GraphML, JSON, D3 HTML, tabular | 8 formatter |
| **Interactive visualization** | ❌ (JSON only) | ✅ D3 force-directed web app | ⚠️ Web playground (online) |
| **Architecture metrics** | ⚠️ (callgraph, circular) | ✅ (Louvain, fan-in/out, TF-IDF, change coupling) | ❌ |
| **Git history analysis** | ⚠️ (blame only) | ✅ (change coupling, churn, author) | ❌ |
| **Rule language** | ⚠️ (sources/sinks/sanitizers list) | ❌ (no rule language) | ✅ (pattern + metavariable) |
| **AI agent integration** | ✅ (MCP, guard, AI flags) | ❌ | ✅ (MCP, hooks, prompts) |
| **CI/CD** | ✅ (GitHub Actions, GitLab CI, pre-commit) | ⚠️ (Docker only) | ✅ (matang, baseline, diff scan) |
| **License** | MIT | MIT | LGPL-2.1 |

**Insight strategis:** CodeLens + Emerge feature set = **AI-native architecture intelligence** — ceruk yang belum diisi siapapun. Semgrep terlalu fokus security rule, Emerge tidak punya AI integration, SonarQube terlalu enterprise. CodeLens dengan dashboard interaktif + Louvain + change coupling + MCP akan menjadi tool yang unik.

### 7.3 Urutan Rekomendasi Eksekusi

Jika harus memilih **5 issue pertama** untuk mulai minggu depan (mix quick win + high impact):

1. **#CL-026 Whitespace Complexity** (3 hari) — quick win, copy dari emerge
2. **#CL-027 Fan-In/Fan-Out** (3 hari) — quick win, reuse callgraph
3. **#CL-024 Louvain Modularity** (1 minggu) — foundation untuk dashboard
4. **#CL-032 GraphML Export** (2-3 hari) — quick win, buka ekosistem Gephi
5. **#CL-029 Change Coupling Graph** (1-2 minggu) — high impact, fitur unik yang tidak ada di Semgrep

Total ~4 minggu untuk satu developer, hasilkan 5 fitur baru yang langsung visible di CLI output.

Setelah itu, prioritaskan **#CL-031 Interactive D3 Dashboard** (3-4 minggu) sebagai killer feature untuk diferensiasi pasar.

---

**Dokumen ini disusun dari analisa langsung terhadap:**
- `https://github.com/Wolfvin/CodeLens.git` (branch `main`, checkout 2026-06-28)
- `https://github.com/glato/emerge.git` (branch `dev`, checkout 2026-06-28)
- Melengkapi `CodeLens_Upgrade_Issues_from_Semgrep.md` (22 issue CL-001 s/d CL-022)
