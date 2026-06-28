# CodeLens ↔ OpenTaint — Analisis Fitur & Rencana Upgrade (Issue Tracker)

> **Repo yang dianalisis sebagai sumber upgrade:** `seqra/opentaint` (https://github.com/seqra/opentaint.git)
> **Repo target upgrade:** `Wolfvin/CodeLens` (https://github.com/Wolfvin/CodeLens)
> **Tanggal analisis:** 2026-06-28
> **Versi CodeLens saat ini:** v8.1 (README) / v7.2.0 (`skill.json`, `pyproject.toml`) — *catatan: terdapat inkonsistensi penomoran versi antara README dan metadata skill yang harus dirapikan*
> **Versi OpenTaint saat ini:** v0.x (CLI `release-cli.yaml`, branch `main` commit `73330dd6`)

---

## Daftar Isi

1. [Ringkasan Eksekutif](#1-ringkasan-eksekutif)
2. [Analisis Fitur CodeLens](#2-analisis-fitur-codelens)
3. [Analisis Fitur OpenTaint (Repo Referensi)](#3-analisis-fitur-opentaint-repo-referensi)
4. [Matriks Komparasi Fitur](#4-matriks-komparasi-fitur)
5. [Peningkatan yang Sudah Di-adjust di CodeLens](#5-peningkatan-yang-sudah-di-adjust-di-codelens)
6. [Daftar Issue untuk Next Upgrade (Serapan dari OpenTaint)](#6-daftar-issue-untuk-next-upgrade-serapan-dari-opentaint)
7. [Prioritas & Roadmap Eksekusi](#7-prioritas--roadmap-eksekusi)
8. [Catatan Teknis & Risiko](#8-catatan-teknis--risiko)

---

## 1. Ringkasan Eksekutif

CodeLens adalah platform **code intelligence AI-native** berbasis Python (tree-sitter + regex hybrid) yang fokus pada *pre-write safety check*, kualitas kode, dan integrasi MCP untuk agent. CodeLens memiliki 58 command files (di `scripts/commands/`), MCP server dengan 49 tools, VS Code extension, plugin system, dan 4 GitHub Actions workflows.

OpenTaint adalah **formal inter-procedural taint analysis engine** berbasis Kotlin/Go (untuk JVM — Java/Kotlin/Spring) yang dirancang sebagai alternatif open-source untuk Semgrep Pro dan CodeQL. Repo ini menonjol karena: (a) engine formal berbasis automata yang jauh lebih dalam dari AST-pattern matcher biasa, (b) workflow agent-based end-to-end (`appsec-agent`) yang sudah punya 13 skill terstruktur, (c) sistem **approximation** (passThrough + dataflow) untuk library method yang taint-nya tidak bisa dijangkau engine, dan (d) tooling **rule-authoring** + **debug-rule** dengan fact-reachability trace.

**Posisi strategis:** CodeLens unggul di breadth (28+ bahasa, frontend, MCP-native) namun lemah di **kedalaman taint analysis formal** dan **workflow agent end-to-end**. OpenTaint unggul di **kedalaman formal taint** (khusus JVM) namun sempit (Java/Kotlin/Spring only, roadmap Python/Go/C#/JS/TS belum dirilis). Upgrade CodeLens berikutnya paling berdampak jika menyerap **arsitektur workflow agent**, **paradigma approximation**, **rule-authoring tooling**, dan **debug-trace** dari OpenTaint — sambil tetap mempertahankan breadth bahasa CodeLens.

---

## 2. Analisis Fitur CodeLens

### 2.1 Arsitektur Umum

CodeLens adalah **monorepo Python** dengan struktur:

| Direktori / File | Peran |
|---|---|
| `scripts/codelens.py` | Entry point CLI (58 command files di `scripts/commands/`) |
| `scripts/*_engine.py` | Engine per-kemampuan (~25 engine: `ast_taint_engine.py` 3.756 LOC, `crossfile_taint_engine.py` 946 LOC, `dataflow_engine.py` 1.097 LOC, `plugin_system.py` 1.462 LOC, `mcp_server.py` 1.934 LOC, dll.) |
| `scripts/parsers/` | 40+ parser: tree-sitter native (HTML, CSS, JS, TS, TSX, Vue, Svelte, Python, Rust) + fallback regex (untuk 20+ bahasa lain: Java, Kotlin, Go, C, C++, C#, Swift, Scala, Ruby, PHP, Dart, Haskell, Elixir, Lua, Nim, R, Zig, Shell, Vim, GDScript, Blade, Objective-C) |
| `scripts/plugins/` | Plugin built-in: `owasp_top10/` (36 rules), `compliance/` (HIPAA, PCI-DSS) |
| `scripts/formatters/` | Output formatter: `markdown.py`, `sarif.py` |
| `scripts/rules/` | Aturan YAML built-in: `python_security.yaml`, `javascript_security.yaml` |
| `vscode-codelens/` | VS Code extension (Diagnostics Provider, Code Actions, Guard hooks, Health status) |
| `.github/workflows/` | 4 workflow: `codelens-ci.yml`, `codelens-sarif.yml`, `codelens-benchmark.yml`, `codelens-quality-gate.yml` |
| `benchmarks/` | Benchmark suite + regression checker + fixture vulnerable_app & clean_app |
| `references/` | 5 dokumen: `agent-integration.md`, `parser-rules.md`, `query-examples.md`, `status-codes.md`, `changelog.md` |
| `mcp_config.json` | Konfigurasi Claude Desktop / VS Code Copilot MCP |
| `skill.json` & `SKILL.md` & `SKILL-QUICK.md` | Skill manifest untuk distribusi sebagai ClawHub skill |

### 2.2 Kategori Command (58 command files)

Dari enumerasi `scripts/commands/`, berikut distribusi command CodeLens:

**Setup & Lifecycle (5):** `init`, `scan`, `validate`, `watch`, `migrate`

**Pre-Write Safety (4):** `query`, `impact`, `refactor-safe`, `guard` (pre/post-write hooks untuk AI agent)

**Navigation & Search (10):** `summary`, `context`, `trace`, `search`, `symbols`, `outline`, `dependents`, `list`, `ask`, `history`

**Architecture (6):** `entrypoints`, `api-map`, `state-map`, `detect`, `handbook`, `diff`

**Security (5):** `secrets`, `dataflow`, `taint`, `vuln-scan`, `env-check`

**Quality (8):** `smell`, `complexity`, `dead-code`, `debug-leak`, `circular`, `missing-refs`, `side-effect`, `perf-hint`

**Refactoring (3):** `test-map`, `stack-trace`, `config-drift`

**Frontend (2):** `css-deep`, `a11y`

**Advanced (7):** `analyze`, `type-infer`, `ownership`, `regex-audit`, `binary-scan`, `artifact-scan`, `self-analyze`

**Utility & Service (5):** `serve` (MCP), `plugin`, `benchmark`, `check`, `lsp-status`, `fix`, `dashboard`

> *Catatan: README menyebut "56 commands" dan `skill.json` menyebut "45 commands" — angka aktual berdasarkan file count adalah 58. Inkonsistensi ini perlu dirapikan di issue terpisah.*

### 2.3 Kapabilitas Teknis Kunci

**AST Taint Engine (`ast_taint_engine.py`, 3.756 LOC):**
- Berbasis tree-sitter (Python, JavaScript, TypeScript, TSX)
- Membangun Control Flow Graph (CFG) dengan basic blocks, branches, joins
- Path-sensitive forward taint propagation
- Scope-aware (function boundaries, closures, class methods)
- Inter-procedural **dalam satu file** (tidak cross-file di engine utama)
- Sanitizer-aware
- Confidence scoring (0.40–0.95+)
- Taint path rendering: `request.args → user_input → query → cursor.execute`

**Cross-File Taint Engine (`crossfile_taint_engine.py`, 946 LOC):**
- Workspace-wide call graph
- Import resolution
- Bidirectional taint propagation
- Terpisah dari `ast_taint_engine.py` (tidak terintegrasi penuh)

**Dataflow Engine (`dataflow_engine.py`, 1.097 LOC):** User-defined source→sink taint analysis berbasis YAML rules.

**MCP Server (`mcp_server.py`, 1.934 LOC):**
- MCP spec `2025-03-26` via JSON-RPC 2.0 over stdio
- 49 tools (semua command CodeLens ter-expose sebagai MCP tool)
- In-memory registry caching, sub-millisecond query setelah initial scan
- Mode `--watch` untuk live update
- HTTP/SSE transport opsional via `--port`
- Resource exposure: codebase registry sebagai MCP resources

**Plugin System (`plugin_system.py`, 1.462 LOC):**
- 4 tipe plugin: `rule_pack`, `engine`, `formatter`, `command`
- 3-tier discovery: `.codelens/plugins/` (project) > `~/.codelens/plugins/` (user) > `scripts/plugins/` (built-in)
- Plugin manifest `plugin.yaml`
- Plugin isolation (plugin failure tidak crash CodeLens)
- Roadmap marketplace: `REGISTRY_INDEX_URL = "https://registry.codelens.dev/api/v1/plugins"` (belum aktif)
- Built-in plugins: OWASP Top 10 (36 rules — A01 Broken Access Control sampai A10 SSRF), Compliance (HIPAA, PCI-DSS — 53 rules)

**AI-Native Features:**
- `--format ai` (normalized schema: `{stats, items[], truncated, recommendations}`)
- `--lite` (command-specific minimal output, 10+ command punya lite mode tailored)
- `--top N` (smart default 20, sort-aware: severity/complexity)
- `--max-tokens N` (auto-truncate untuk context window budget)
- `CODELENS_AI_MODE=1` env var (default `--format ai`)
- Zero-config: auto-init + auto-scan saat registry belum ada (cap 3000 file)
- Workspace auto-detect (walk up 10 levels cari project root)
- Guard hooks: `codelens guard --pre/--post` untuk AI workflow

**CI/CD:**
- GitHub Actions: SARIF v2.1.0 upload ke GitHub Code Scanning
- GitLab CI: `.gitlab-ci.yml` di root
- Pre-commit hook: `scripts/pre_commit_hook.py`
- VS Code extension dengan Diagnostics Provider + Health status bar

**Benchmark & Regression:**
- `benchmarks/run_benchmarks.py` + `check_regression.py`
- Fixture: `vulnerable_app/` (ground truth YAML, 9 file contoh vulnerability) dan `clean_app/`
- Test: `pytest.ini` + direktori `tests/`

### 2.4 Bahasa yang Didukung

**Native tree-sitter (presisi AST penuh):** HTML, CSS, SCSS, JavaScript, TypeScript, TSX/JSX, Python, Rust, Vue SFC, Svelte

**Fallback regex (limited):** Java, Kotlin, Scala, Go, C, C++, C#, Objective-C, Swift, Dart, PHP, Ruby, Haskell, Elixir, Lua, Nim, R, Zig, Shell, Vim, GDScript, Blade

**Framework auto-detect:** React/Next.js, Vue/Nuxt, Svelte/SvelteKit, Tailwind CSS, Express, Fastify, Koa, Hono, Django, Flask, FastAPI

### 2.5 Kelemahan CodeLens Saat Ini

1. **Taint analysis inter-procedural terbatas** — engine utama hanya intra-file; cross-file ada di engine terpisah dan tidak terintegrasi penuh.
2. **Tidak ada library method approximation** — saat taint "mati" di method library eksternal (mis. `Map.computeIfAbsent`, `Mono.map`), CodeLens tidak punya mekanisme untuk memodelkan propagasi taint-nya.
3. **Tidak ada rule-authoring workflow formal** — user harus menulis YAML rule manual tanpa tooling test+verify+iterate.
4. **Tidak ada debug-trace untuk taint** — user tidak bisa lihat di instruksi mana taint "mati" saat sebuah rule tidak ter-fire.
5. **Tidak ada PoC generation** — finding statis tidak bisa dikonfirmasi secara dinamis.
6. **Tidak ada attack surface discovery** — tidak ada yang setara `discover-attack-surface` untuk scan dependency package mana yang punya source/sink potensial.
7. **Tidak ada triage workflow terstruktur** — `analyze` command ada, tetapi tidak ada workflow TP/FP verdict per-finding dengan tracking file.
8. **Skill agent tidak ada** — CodeLens punya `SKILL.md` dan `SKILL-QUICK.md` untuk satu skill statis; tidak ada orkestrasi multi-skill seperti `appsec-agent` OpenTaint.
9. **Tidak ada model caching terpisah** — registry CodeLens adalah monolit; tidak ada konsep "compiled project model" yang reusable lintas scan dengan dependensi ter-resolve.
10. **Inkonsistensi versioning & command count** antara README (56), skill.json (45), dan actual file count (58).

---

## 3. Analisis Fitur OpenTaint (Repo Referensi)

### 3.1 Arsitektur Umum

OpenTaint adalah **monorepo polyglot** dengan struktur:

| Komponen | Teknologi | Peran |
|---|---|---|
| `core/opentaint-java-querylang/` | Kotlin | Engine formal berbasis automata: parsing Semgrep YAML pattern → action list → automata → taint rule. ~80+ file Kotlin di `pattern/conversion/`, `pattern/conversion/taint/`, `pattern/conversion/automata/` |
| `core/opentaint-jvm-autobuilder/` | Kotlin | Auto-build Maven/Gradle project → resolve dependencies → compiled project model. `ProjectResolver.kt`, `MavenProjectResolver.kt`, `GradleProjectResolver.kt`, `GoProjectResolver.kt` (roadmap Go) |
| `cli/` | Go | CLI binary: `scan`, `compile`, `project`, `summary`, `health`, `test rule`, `test approximation`, `pull`, `update`, `prune`. Distribusi via Homebrew, npm (`@seqra/opentaint`), npx, install.sh, install.ps1, Docker |
| `rules/` | YAML | Built-in rules: `ruleset/java/lib/generic/` (16 generic sink/source rule), `ruleset/java/lib/spring/` (8 Spring-specific rule), `ruleset/java/security/` (20 security rule: XSS, SQLi, SSRF, XXE, LDAP, CRLF, CSRF, deserialization, path traversal, command injection, code injection, crypto, dll.) + `rules/test/` dengan 20+ sample Java file |
| `skills/` | Markdown + Python | **13 skill** untuk AI agent workflow (lihat 3.3) |
| `github/` | YAML composite action | GitHub Action: auto-resolve version, install, compile, scan, upload SARIF ke GitHub Code Scanning |
| `gitlab/` | YAML | GitLab CI template |
| `docs/` | Markdown | 7 doc utama + 21 terjemahan README |
| `infra/` | Dockerfile | Image dependencies untuk autobuilder |
| `scripts/` | Shell + Python | Installer (`install.sh`, `install.cmd`, `install.ps1`) + CI helper (`wait-for-http-server`, `run-installer-*`) + `resolve_opentaint_version.py` |

### 3.2 Engine Formal — Yang Membuat OpenTaint Berbeda

**Berdasarkan direktori `core/opentaint-java-querylang/src/main/kotlin/org/opentaint/semgrep/pattern/conversion/`:**

1. **Semgrep YAML compatibility** — user bisa menulis rule dengan syntax Semgrep (`pattern-either`, `pattern-not`, `metavariable-pattern`, `focus-metavariable`, `metavariable-regex`, dll.) — lihat `SemgrepPatternParser.kt`, `SemgrepYamlParsing.kt`, `SemgrepRuleLoader.kt`.

2. **Pattern → Action List → Automata → Taint Rule pipeline:**
   - `PatternToActionListConverter.kt` — konversi pattern AST ke action list
   - `ActionListBuilder.kt` — bangun action list
   - `ActionListToAutomata.kt` — action list → finite automata
   - `SemgrepRuleAutomataBuilder.kt` — rule → automata
   - `SemgrepRuleToAutomata.kt` — orchestration

3. **Automata operations (formal language theory):**
   - `Determinization.kt` — NFA → DFA
   - `Minimization.kt` — minimize DFA
   - `Intersection.kt` — automata intersection
   - `Complement.kt` — negasi bahasa
   - `Totalization.kt` — complete automata
   - `SimplifyAutomata.kt` — simplifikasi
   - `AcceptPrefix.kt` / `AcceptSuffix.kt` — prefix/suffix closure
   - `UnifyMetavars.kt` — unify metavariable binding
   - `Traverse.kt` — traversal

4. **Taint-specific conversion (`taint/` subdirectory, 18 file):**
   - `TaintAutomataGeneration.kt`, `TaintEdgesGeneration.kt`
   - `TaintRegisterStateAutomataBuilder.kt`, `TaintRegisterAutomataCreation.kt`
   - `MethodFormulaSimplifier.kt`, `SimplifiedMethodFormulaDNF.kt`
   - **Composition strategies** (`composition/` 5 file): `TaintPassCompositionStrategy`, `JoinRightCompositionStrategy`, `TaintSinkCompositionStrategy`, `TaintSourceCompositionStrategy`, `TaintCleanCompositionStrategy`
   - `JoinRuleProcessing.kt` — multi-rule join (source rule + sink rule → security rule)

5. **Taint engine features:**
   - Inter-procedural full dataflow (cross-function, cross-class)
   - Tracks taint through persistence layers (stored / second-order injection dimodelkan engine)
   - Alias analysis (branch `saloed/alias-2`, `misonijnik/add-approximations`, `DanielELog/must_alias` — pengembangan aktif)
   - Lambda/callback/async taint propagation (via dataflow approximation)
   - Spring endpoint auto-discovery (WebMVC, WebFlux, WebFlux functional)
   - Method-level taint reachability trace (via `test rule reachability`)

### 3.3 Skill Agent (13 Skill) — Workflow End-to-End

Direktori `skills/` berisi 13 skill markdown yang dirancang untuk AI agent (Claude Code, Cursor, dll.). Skill di-install via `npx skills add https://github.com/seqra/opentaint`.

| Skill | Peran |
|---|---|
| `appsec-agent` | **Orchestrator utama** — end-to-end JVM appsec workflow dengan 2 dimensi: scan_level (lite/normal/deep) × triage_level (static/dynamic). Dispatch ke subagent via skill tool. State tracking via `.opentaint/tracking/state.yaml`. Resource limit: global cap 7 subagent, RAM cap `max(1, min(cores, floor(free_GB/2), 7))` untuk heavy agent. |
| `build-project` | Build Maven/Gradle project → compiled model di `.opentaint/project/project.yaml`. Heavy RAM (JVM). |
| `run-scan` | Run `opentaint scan` dengan `--track-external-methods`. Output: SARIF + `dropped-external-methods.yaml` + `approximated-external-methods.yaml`. |
| `analyze-findings` | Triage TP/FP per-finding. Split bundle (1 rule → multiple vuln). Walk codeFlow source→sink. Verdict + notes di `findings/<name>.yaml`. |
| `generate-poc` | Dynamic confirmation: start app (`spring-boot:run`, `docker compose`), bind `127.0.0.1` only, kirim payload (SQLi, cmd injection, path traversal, XSS, SSRF, XXE), assert observable evidence. Register instance di `poc-servers.yaml` untuk teardown. |
| `discover-attack-surface` | Depth pass: untuk 1 dependency package, gunakan `scripts/package-usages.sh` untuk ekstrak bytecode invocation list → klasifikasi source/sink. Cek built-in coverage (full/partial/none). Tulis rule plan di `tracking/rules/lib/<pkg>.yaml`. |
| `triage-dependencies` | Mark dependency mana yang potentially source/sink (web framework, ORM, HTTP client, deserializer, template engine, LDAP/JNDI). Dismiss infrastructure (logging, build plugin, ASM, test lib). |
| `create-test-project` | Buat test project dengan `@PositiveRuleSample` / `@NegativeRuleSample` annotation untuk verify rule. |
| `create-rule` | Author source/sink lib rule (`options.lib: true`, `severity: NOTE`). Wire ke generic `Taint` marker. Test dengan `test rule run` sampai semua sample pass. |
| `assemble-lib-rules` | Per vuln class, tulis join rule yang wire source + sink (`mode: join`, `on: 'src.$UNTRUSTED -> sink.$UNTRUSTED'`). |
| `analyze-external-methods` | Identifikasi method di `dropped-external-methods.yaml` yang butuh approximation. Klasifikasi: passthrough vs dataflow vs skipped. |
| `create-pass-through-approximation` | Simple from→to copy (YAML). Override built-in at rule level. |
| `create-dataflow-approximation` | Code-based Java `@Approximate` class untuk lambda/callback/async. Compiled ke `.class` oleh CLI. Override passthrough. |
| `debug-rule` | Fact-reachability trace: `test rule reachability <rule-id>` → `debug-ifds-fact-reachability.sarif` sibling file. Localize di instruction mana taint mati. Klasifikasi: missing model / rule defect / engine bug. |
| `report-analyzer-issue` | Format report engine bug untuk upstream. |

### 3.4 CLI Command Surface

| Command | Subcommand | Peran |
|---|---|---|
| `scan` | — | Auto-detect Maven/Gradle → build → scan. Atau scan pre-built model via `--project-model`. |
| `compile` | — | Build project model terpisah dari scan. |
| `project` | — | Buat model dari precompiled JAR/class (untuk source tidak tersedia). |
| `summary` | — | Lihat SARIF: filter by severity, path, rule-id, partial-fingerprint; group-by severity/rule-id/file-path; verbose code flow. |
| `health` | `--rules` / `--analyzer` / `--autobuilder` / `--runtime` | Diagnosa path dependency. |
| `test rule` | `init`, `run`, `reachability` | Rule authoring & debugging. |
| `test approximation` | `init`, `run` | Approximation authoring & testing. |
| `pull` | — | Download analyzer deps. |
| `update` | — | Update CLI. |
| `prune` | — | Hapus artifact & cache stale. |

### 3.5 Distribusi & CI/CD

- **Install channels:** install.sh (Linux/macOS), install.ps1 (Windows), Homebrew cask (`seqra/tap/opentaint`), npm (`@seqra/opentaint`), npx (zero-install), Docker (`ghcr.io/seqra/opentaint:latest`)
- **Versioned release:** GitHub Releases dengan floating tag (`v0`, `v0.x`) + exact (`v0.x.y`). Script `resolve_opentaint_version.py` untuk resolve.
- **Bundle JRE:** `cli/scripts/bundle-jre.sh` — binary bisa bundle JRE sendiri.
- **GitHub Action:** composite action dengan input `project-root`, `upload-sarif`, `opentaint-version`, `rules-path`, `token`, `artifact-name`, `upload-artifact`, `debug`, `timeout`, `severity`, `java-version`.
- **GitLab CI:** `gitlab/opentaint.gitlab-ci.yml`.
- **CI workflows di repo:** 16 workflow GitHub Actions (ci-analyzer, ci-cli, ci-github, ci-dataflow, ci-autobuilder, ci-ir, ci-rules, ci-analyzer-owasp, pr-title, publish-analyzer, publish-autobuilder, publish-cli, publish-github, publish-go-server, publish-infra-dependencies, release-rules, release-cli, release-github, release-gitlab, update-cli-versions, update-floating-tags)
- **Translation:** 21 bahasa README (termasuk Bahasa Indonesia `README.id.md`).

### 3.6 Approximation System — Inovasi Kunci

OpenTaint memecahkan masalah "taint mati di library method" dengan dua mekanisme:

**PassThrough Approximation** (YAML, sederhana):
- Format: from→to copy (mis. `String.valueOf($X)` → `$X`)
- Override built-in di rule level
- Tidak butuh compilation
- Untuk propagasi trivial

**Dataflow Approximation** (Java code, kompleks):
- `@Approximate(TargetClass.class)` annotation
- `OpentaintNdUtil.nextBool()` untuk non-deterministic branch (engine considers both paths)
- `@ArgumentTypeContext` untuk lambda/functional-interface parameter
- Wrapper-returning pattern (Mono/Flux/Optional/Stream): extract → apply → re-wrap
- Compiled oleh CLI ke `.class` saat scan
- Untuk lambda/callback/async chain
- **One class, one approximation** — bijection enforced at load

**Tracking file schema:**
```yaml
# .opentaint/tracking/approximations/<package-kebab>-passthrough.yaml
package: com.foo
artifact: null
stages:
  description: done
  written: pending
methods:
  - target: "com.foo.Wrapper#getValue"
    type: passthrough
```

### 3.7 Rule Format (Semgrep-compatible)

OpenTaint menggunakan YAML format yang kompatibel dengan Semgrep:

```yaml
rules:
  - id: my-custom-sink
    options:
      lib: true           # wajib untuk lib rule
    severity: NOTE        # NOTE untuk lib rule, ERROR/WARNING untuk security rule
    message: Custom dangerous operation
    languages: [java]
    mode: taint           # taint | join (default structural)
    pattern-sinks:
      - patterns:
          - pattern-either:
              - pattern: (java.sql.Statement $S).executeQuery($UNTRUSTED)
          - focus-metavariable: $UNTRUSTED
```

**Join rule** (security rule yang wire source + sink):
```yaml
rules:
  - id: sqli-execute-query
    severity: ERROR
    metadata:
      cwe: CWE-89
      short-description: SQL Injection via executeQuery
    languages: [java]
    mode: join
    join:
      refs:
        - rule: java/lib/generic/servlet-untrusted-data-source.yaml#java-servlet-untrusted-data-source
          as: src
        - rule: java/lib/generic/data-query-injection-sinks.yaml#java-execute-query-sink
          as: sink
      on:
        - 'src.$UNTRUSTED -> sink.$UNTRUSTED'
```

### 3.8 Built-in Rule Coverage (Java)

20 security rule di `rules/ruleset/java/security/`:

- `sqli.yaml`, `xss.yaml`, `ssrf.yaml`, `xxe.yaml`
- `command-injection.yaml`, `code-injection.yaml`, `path-traversal.yaml`
- `ldap.yaml`, `crlf-injection.yaml`, `csrf.yaml`
- `unsafe-deserialization.yaml`, `log-injection.yaml`
- `hardcoded-credentials.yaml`, `weak-authentication.yaml`
- `insecure-design.yaml`, `sensitive-data-exposure.yaml`
- `external-configuration-control.yaml`, `crypto.yaml`
- `permissions.yaml`, `data-query-injection.yaml`, `strings.yaml`

16 generic source/sink di `rules/ruleset/java/lib/generic/` + 8 Spring-specific di `lib/spring/`.

---

## 4. Matriks Komparasi Fitur

| Kapabilitas | CodeLens | OpenTaint | Gap CodeLens |
|---|:---:|:---:|---|
| **Bahasa native AST** | 10 (HTML/CSS/SCSS/JS/TS/TSX/Python/Rust/Vue/Svelte) | 1 (Java) + roadmap 5 | — (CodeLens unggul) |
| **Bahasa fallback regex** | 20+ | 0 | — (CodeLens unggul) |
| **Frontend analysis** | ✅ deep (CSS deep, a11y, framework detect) | ❌ | — (CodeLens unggul) |
| **JVM/Spring analysis** | ❌ (fallback regex only) | ✅ formal | besar |
| **Taint engine — intra-file** | ✅ AST-based path-sensitive | ✅ formal automata | medium |
| **Taint engine — inter-procedural cross-file** | ⚠️ engine terpisah, tidak terintegrasi penuh | ✅ unified | besar |
| **Taint engine — persistence/stored injection** | ❌ | ✅ dimodelkan engine | besar |
| **Taint engine — alias analysis** | ⚠️ basic | ✅ + branch aktif (must_alias, add-approximations) | sedang |
| **Taint engine — async/lambda/callback** | ❌ | ✅ via dataflow approximation | besar |
| **Library method approximation** | ❌ | ✅ passThrough + dataflow | **besar (gap kritis)** |
| **Rule format** | YAML custom (sources/sinks/sanitizers list) | Semgrep-compatible YAML + `mode: join` | sedang |
| **Rule authoring workflow** | ❌ manual | ✅ 5 skill (test-project → create-rule → assemble-lib-rules → debug-rule → report-analyzer-issue) | **besar** |
| **Rule test harness** | ⚠️ benchmark fixture saja | ✅ `@PositiveRuleSample`/`@NegativeRuleSample` annotation + `test rule run` | besar |
| **Debug trace untuk taint** | ❌ | ✅ fact-reachability SARIF (`debug-ifds-fact-reachability.sarif`) | **besar (gap kritis)** |
| **Attack surface discovery** | ❌ | ✅ `discover-attack-surface` + `triage-dependencies` | besar |
| **Triage workflow** | ⚠️ `analyze` command (bulk) | ✅ per-finding TP/FP verdict + tracking file | besar |
| **PoC generation (dynamic confirm)** | ❌ | ✅ `generate-poc` (start app, payload, assert) | **besar** |
| **Agent orchestrator** | ❌ (single skill statis) | ✅ `appsec-agent` (multi-skill, state tracking, resource cap) | **besar** |
| **Project model caching** | ⚠️ registry monolit | ✅ compiled model terpisah, reusable, cache key dari path | sedang |
| **Compiled project model** | ❌ | ✅ `project.yaml` + `dependencies/` + `moduleClasses` | sedang |
| **Plugin / extension marketplace** | ⚠️ 3-tier discovery, URL belum aktif | ❌ | — (CodeLens unggul) |
| **MCP server** | ✅ 49 tools, stdio + HTTP/SSE | ❌ | — (CodeLens unggul) |
| **VS Code extension** | ✅ Diagnostics + Code Actions + Guard hooks | ❌ (rekomendasi pakai SARIF Viewer Microsoft) | — (CodeLens unggul) |
| **Pre-write safety check** | ✅ `query` + `guard` (AI-native) | ❌ | — (CodeLens unggul) |
| **AI-optimized output** | ✅ `--format ai`, `--lite`, `--top N`, `--max-tokens N` | ⚠️ `--quiet`, `--debug`, partial fingerprint | — (CodeLens unggul) |
| **SARIF output** | ✅ v2.1.0 | ✅ v2.1.0 dengan codeFlow | setara |
| **CI/CD** | GitHub Actions + GitLab CI | GitHub Action composite + GitLab CI template + 16 GH workflow | OpenTaint lebih matang |
| **Installer channels** | manual `git clone` + `setup.sh` | install.sh, install.ps1, Homebrew, npm, npx, Docker | OpenTaint jauh lebih matang |
| **Versioning** | v7.2/v8.1 inkonsisten | v0.x semver + floating tag | OpenTaint lebih konsisten |
| **Benchmark** | ✅ `run_benchmarks.py` + `check_regression.py` + fixture | ❌ | — (CodeLens unggul) |
| **Translation** | ❌ | ✅ 21 bahasa (termasuk Indonesia) | OpenTaint unggul |
| **Compliance rules** | ✅ HIPAA, PCI-DSS (53 rules) | ❌ | — (CodeLens unggul) |
| **OWASP Top 10** | ✅ 36 rules | ⚠️ implicit (rules tidak di-tag OWASP eksplisit) | — (CodeLens unggul) |
| **Documentation depth** | 5 reference file | 7 doc utama + 21 translation + 13 skill file | OpenTaint lebih luas |

---

## 5. Peningkatan yang Sudah Di-adjust di CodeLens

Berikut hal yang **sudah dimiliki CodeLens** dan **tidak perlu** diserap dari OpenTaint, atau bahkan lebih baik dari OpenTaint:

### 5.1 Breadth Bahasa & Frontend
- ✅ 10 bahasa native tree-sitter + 20+ bahasa fallback regex (OpenTaint hanya Java)
- ✅ Frontend deep analysis: `css-deep` (unused variables, orphan keyframes, specificity wars, z-index abuse), `a11y` (WCAG 2.1), framework auto-detect (React/Vue/Svelte/Tailwind)
- ✅ Parser tree-sitter untuk Vue SFC, Svelte component — tidak ada di OpenTaint

### 5.2 MCP & AI-Native Design
- ✅ MCP server 49 tools (OpenTaint tidak punya MCP)
- ✅ `--format ai` normalized schema (OpenTaint output SARIF + terminal pretty print saja)
- ✅ `--lite` per-command tailored output (10+ command)
- ✅ `--top N` smart default dengan sort-aware truncation
- ✅ `--max-tokens N` untuk context window budget
- ✅ Zero-config auto-init + auto-scan (OpenTaint butuh `health` check manual)
- ✅ Workspace auto-detect (OpenTaint butuh `--project-root` eksplisit)

### 5.3 Pre-Write Safety & Guard Hooks
- ✅ `query "name"` dengan status decision rules (CREATE/EXTEND/ASK/STOP) — *unik di CodeLens, tidak ada di OpenTaint*
- ✅ `guard --pre/--post` untuk AI agent workflow
- ✅ `refactor-safe` rename/move safety check
- ✅ `impact` change impact analysis dengan risk level (critical/high/medium/low)

### 5.4 Plugin System & Marketplace Foundation
- ✅ 4 plugin types (rule_pack/engine/formatter/command) vs OpenTaint yang monolitik
- ✅ 3-tier discovery (project/user/built-in) dengan priority ordering
- ✅ Plugin isolation (failure tidak crash)
- ✅ Built-in OWASP Top 10 (36 rules) + Compliance (HIPAA, PCI-DSS — 53 rules)

### 5.5 VS Code Extension
- ✅ Native VS Code extension dengan Diagnostics Provider, Code Actions, Guard hooks, Health status bar
- ✅ OpenTaint hanya rekomendasikan pakai third-party SARIF Viewer

### 5.6 Benchmark & Regression
- ✅ `benchmarks/run_benchmarks.py` + `check_regression.py`
- ✅ Fixture `vulnerable_app/` dengan `ground_truth.yaml` + `clean_app/`
- ✅ GitHub Actions `codelens-benchmark.yml`

### 5.7 Wide Command Surface (58 command)
- ✅ Quality (smell, complexity, dead-code, debug-leak, circular, missing-refs, side-effect, perf-hint)
- ✅ Architecture (entrypoints, api-map, state-map, handbook, diff)
- ✅ Refactoring (test-map, stack-trace, config-drift)
- ✅ Advanced (type-infer, ownership, regex-audit, binary-scan, artifact-scan, self-analyze)
- ✅ Utility (serve, plugin, benchmark, check, lsp-status, fix, dashboard)

### 5.8 Compliance & Tagging
- ✅ OWASP Top 10 (36 rules dengan `cwe:` + `owasp:` metadata di YAML)
- ✅ HIPAA + PCI-DSS (53 rules)
- ✅ Tag-based plugin discovery (`skill.json` tags)

---

## 6. Daftar Issue untuk Next Upgrade (Serapan dari OpenTaint)

Berikut **issue-issue konkret** untuk diajukan ke repo CodeLens, dikelompokkan per tema. Setiap issue sudah disertai: motivasi (referensi OpenTaint), acceptance criteria, dan scope teknis.

### Tema A: Taint Engine — Kedalaman Formal

---

#### Issue A1 — Unified Cross-File Inter-Procedural Taint Engine

**Motivasi (OpenTaint):** Engine formal OpenTaint melakukan inter-procedural taint analysis terintegrasi (cross-function, cross-class, cross-file) dalam satu pass. CodeLens saat ini punya `ast_taint_engine.py` (intra-file) dan `crossfile_taint_engine.py` (terpisah, 946 LOC) yang tidak terintegrasi penuh — taint yang cross file boundary sering hilang.

**Acceptance Criteria:**
- [ ] `ast_taint_engine.py` dan `crossfile_taint_engine.py` di-merge atau di-refactor menjadi satu pipeline unified
- [ ] Taint propagation menjangkau minimum 5 hop inter-procedural lintas file (saat ini default 1 hop)
- [ ] Taint path rendering menampilkan cross-file chain: `file_a.py:handler → request.args → file_b.py:sanitize → file_c.py:db.execute`
- [ ] Benchmark: detect vulnerability di `benchmarks/fixtures/vulnerable_app/src/` yang sebelumnya missed (target: +3 finding baru dari ground_truth.yaml)
- [ ] Performance budget: scan 1000-file repo < 60 detik (saat ini ~30-120 detik untuk 1000-5000 file)

**Scope teknis:**
- Refactor `ast_taint_engine.py` (3.756 LOC) untuk konsumsi call graph dari `crossfile_taint_engine.py`
- Tambahkan `--max-depth N` flag (default 5) untuk batas inter-procedural hop
- Update `dataflow` dan `taint` command untuk pakai engine unified
- Update `--format ai` schema untuk include `taint_path[]` dengan `file:line` per hop

**Estimasi effort:** 3-4 minggu (high complexity, core engine rewrite)

---

#### Issue A2 — Persistence / Stored Injection Modeling

**Motivasi (OpenTaint):** Engine OpenTaint otomatis memodelkan stored / second-order injection (data dipersist → dibaca kembali di flow lain) tanpa perlu source/sink/propagator tambahan. CodeLens tidak punya ini — stored injection (mis. data dari form disimpan ke DB, lalu dibaca di endpoint lain dan masuk ke SQL query) tidak terdeteksi.

**Acceptance Criteria:**
- [ ] Taint yang mencapai persistence sink (DB write, file write, cache set) di-tag sebagai `persisted_taint`
- [ ] Saat data dibaca dari persistence source (DB read, file read, cache get) di flow lain, taint di-resume
- [ ] Config: `persistence_sinks: [db.session.add, fs.writeFileSync, cache.set]` dan `persistence_sources: [Model.query, fs.readFileSync, cache.get]` di YAML rule
- [ ] Taint path rendering menampilkan `[persisted via db.session.add @ file_a.py:42]` marker
- [ ] Test fixture baru di `benchmarks/fixtures/vulnerable_app/src/stored_injection.py` dengan ground truth

**Scope teknis:**
- Tambah `PersistenceTracker` class di `ast_taint_engine.py`
- Taint tag set: `clean`, `tainted`, `persisted_taint`
- Persistence sink/source pattern YAML di `scripts/rules/python_security.yaml` dan `javascript_security.yaml`

**Estimasi effort:** 2 minggu

---

#### Issue A3 — Library Method Approximation System (passThrough + dataflow)

**Motivasi (OpenTaint):** OpenTaint memecahkan "taint mati di library method" dengan dua mekanisme:
- **PassThrough** (YAML, sederhana): from→to copy, mis. `String.valueOf($X)` → taint `$X` ke result
- **Dataflow Approximation** (Java code, kompleks): `@Approximate(TargetClass.class)` dengan `OpentaintNdUtil.nextBool()` non-deterministic branch, untuk lambda/callback/async

CodeLens tidak punya mekanisme ini. Setiap taint yang masuk library method eksternal (mis. `Map.computeIfAbsent`, `Promise.then`, `Optional.map`, `_.get`) hilang.

**Acceptance Criteria:**
- [ ] Direktori baru: `scripts/approximations/` dengan sub-direktori `passthrough/` dan `dataflow/`
- [ ] PassThrough format YAML:
  ```yaml
  # scripts/approximations/passthrough/js_promise.yaml
  approximations:
    - target: "Promise.then"
      from: "$0"           # argumen pertama
      to: "return"          # ke return value
    - target: "Promise.then"
      from: "this"
      to: "return"
  ```
- [ ] Dataflow approximation via Python plugin (karena CodeLens Python-based, tidak bisa pakai `@Approximate` Java):
  ```python
  # scripts/approximations/dataflow/js_promise_chain.py
  def approximate_promise_then(input_taint, callback):
      # Model: taint on this flows through callback to result
      if input_taint.on_self and callback.taint_propagates:
          return TaintResult(propagate_to="return", confidence=0.85)
  ```
- [ ] `codelens scan --approximations <dir>` flag (repeatable, merge dengan built-in)
- [ ] Built-in approximation untuk ~30 library method umum: `Promise.then/catch/finally`, `Optional.map/flatMap`, `Array.map/filter/reduce`, `Map.computeIfAbsent`, `_.get/_.set`, `Object.entries`, `JSON.parse/stringify`, `Buffer.from/toString`
- [ ] `codelens scan --track-external-methods` → emit `dropped-methods.yaml` (method yang taint-nya mati) dan `approximated-methods.yaml` (sudah dimodelkan)
- [ ] Dokumentasi: `references/approximations.md` dengan authoring guide

**Scope teknis:**
- Tambah `ApproximationEngine` class
- Hook ke `ast_taint_engine.py` saat call ke external method terdeteksi
- Plugin API untuk user-defined approximation (Python module)
- Override semantics: built-in bisa di-override oleh user (mirip OpenTaint passThrough override)

**Estimasi effort:** 4-5 minggu (high complexity, new subsystem)

---

#### Issue A4 — Debug-Trace Taint Engine (Fact-Reachability)

**Motivasi (OpenTaint):** Skill `debug-rule` OpenTaint menyediakan `test rule reachability <rule-id>` yang emit SARIF sibling `debug-ifds-fact-reachability.sarif` berisi per-instruction fact-reachability data — user bisa lihat **di instruksi mana taint "mati"**. CodeLens tidak punya ini; user hanya lihat "rule tidak ter-fire" tanpa tahu kenapa.

**Acceptance Criteria:**
- [ ] Command baru: `codelens debug-rule <rule-id> [--entry-point FQN]`
- [ ] Output: SARIF sibling file `debug-fact-reachability.sarif` dengan per-instruction taint fact state
- [ ] Output human-readable: `taint_killed_at: file.py:42 in function 'sanitize_input' at instruction 'return cleaned'`
- [ ] Klasifikasi otomatis:
  - `missing_approximation` (method di `dropped-methods.yaml`)
  - `rule_defect` (mistaken sanitizer, unmatched sink/source variant)
  - `engine_issue` (plain propagation kill)
- [ ] Integrasi dengan `--track-external-methods` (Issue A3)
- [ ] MCP tool: `debug_rule` exposed via MCP server

**Scope teknis:**
- Tambah `DebugTraceEngine` di engine baru
- Instrument `ast_taint_engine.py` dengan fact logging (toggle via `--debug-trace`)
- Output format mengikuti SARIF `codeFlows` dengan `kinds: ["taint_fact"]`

**Estimasi effort:** 3 minggu

---

### Tema B: Rule Authoring Workflow

---

#### Issue B1 — Rule Test Harness dengan Positive/Negative Sample Annotation

**Motivasi (OpenTaint):** OpenTaint punya `test rule init`, `test rule run`, dan convention `@PositiveRuleSample`/`@NegativeRuleSample` annotation. CodeLens hanya punya `benchmarks/fixtures/vulnerable_app/ground_truth.yaml` (bulk), tidak ada per-rule isolated test.

**Acceptance Criteria:**
- [ ] Command baru: `codelens test rule init <output-dir>` — scaffold test project dengan `sources/`, `sinks/`, `test-rules/` struktur
- [ ] Command baru: `codelens test rule run <test-project> --ruleset <dir>`
- [ ] Convention annotation di kode sample:
  ```python
  # @PositiveRuleSample(rule_id="sqli-db-execute", reason="direct taint flow to cursor.execute")
  def sqli_positive_1(request):
      user_input = request.args.get("id")
      cursor.execute("SELECT * FROM users WHERE id = " + user_input)  # expected: finding
  
  # @NegativeRuleSample(rule_id="sqli-db-execute", reason="parameterized query")
  def sqli_negative_1(request):
      user_input = request.args.get("id")
      cursor.execute("SELECT * FROM users WHERE id = %s", (user_input,))  # expected: no finding
  ```
- [ ] Output `test-result.json` per rule: `{rule_id, falseNegative: N, falsePositive: N, skipped: N, samples_total: N}`
- [ ] Output `test-results.sarif` untuk IDE integration
- [ ] CI workflow baru `.github/workflows/codelens-rule-tests.yml`

**Scope teknis:**
- Tambah `test_rule_engine.py` 
- Parser annotation di `base_parser.py` (extract `@PositiveRuleSample`/`@NegativeRuleSample` dari comment)
- Test runner dengan isolation per rule

**Estimasi effort:** 2 minggu

---

#### Issue B2 — Semgrep-Compatible Rule Format (Optional Mode)

**Motivasi (OpenTaint):** OpenTaint menggunakan format YAML yang kompatibel dengan Semgrep (`pattern-either`, `pattern-not`, `metavariable-pattern`, `focus-metavariable`, `metavariable-regex`, `mode: taint`, `mode: join`). CodeLens menggunakan format YAML custom dengan list `sources`/`sinks`/`sanitizers`. Kompatibilitas Semgrep akan buka ekosistem rule yang sudah ada (ribuan rule di Semgrep Registry).

**Acceptance Criteria:**
- [ ] Format YAML baru yang backward-compatible dengan format lama
- [ ] Support `mode: taint` dengan `pattern-sources`, `pattern-sinks`, `pattern-sanitizers`
- [ ] Support `mode: join` dengan `refs:` dan `on: 'src.$X -> sink.$X'`
- [ ] Support `pattern-either`, `pattern-not`, `pattern-not-inside`, `pattern-inside`
- [ ] Support `metavariable-pattern`, `metavariable-regex`, `focus-metavariable`
- [ ] Converter: import Semgrep rule dari URL/file → CodeLens format (best-effort, dengan warning untuk unsupported feature)
- [ ] Dokumentasi: `references/rule-format.md` dengan migration guide dari format lama
- [ ] Backward-compat: format lama tetap berfungsi (deprecation warning)

**Scope teknis:**
- Refactor `dataflow_engine.py` untuk support dua mode
- Tambah `SemgrepPatternParser` (port dari Kotlin `SemgrepPatternParser.kt` — adaptasi ke Python)
- Tambah `rule_converter.py` untuk import Semgrep rule

**Estimasi effort:** 5-6 minggu (high complexity, parser port)

---

#### Issue B3 — Attack Surface Discovery & Dependency Triage

**Motivasi (OpenTaint):** Skill `discover-attack-surface` dan `triage-dependencies` OpenTaint: untuk tiap dependency package, ekstrak bytecode invocation list (project-used members only), klasifikasi source/sink potensial, tulis rule plan. CodeLens tidak punya — user harus manual tentukan package mana yang relevan.

**Acceptance Criteria:**
- [ ] Command baru: `codelens triage-deps [workspace]`
  - Baca `package.json`, `requirements.txt`, `pyproject.toml`, `Cargo.toml`, `go.mod`
  - Klasifikasi setiap dependency: `flagged` (web framework, ORM, HTTP client, deserializer, template engine) / `dismissed` (logging, build tool, test lib, data structure) / `unsure` (peek import)
  - Output: `.codelens/triage/deps.yaml` dengan `{package, status, notes}`
- [ ] Command baru: `codelens discover-surface <package-name>`
  - Ekstrak project-used members dari source code (grep import + call site, bukan bytecode — karena CodeLens multi-bahasa)
  - Klasifikasi: source (network/persistence/serialization/messaging/execution entry), sink (query/command/file/path/deser/template/EL/LDAP/JNDI/reflection), propagator (pass-through, engine handle)
  - Cek built-in rule coverage: `full` / `partial` / `none`
  - Output: `.codelens/triage/surface/<package-kebab>.yaml`
- [ ] Integrasi dengan plugin system: auto-suggest rule_pack plugin untuk package dengan `partial` / `none` coverage

**Scope teknis:**
- Tambah `triage_engine.py` dan `discover_surface_engine.py`
- Pattern library di `scripts/rules/package_classifications.yaml` (knowledge base package → category)
- Grep-based usage extraction (multi-bahasa)

**Estimasi effort:** 3 minggu

---

### Tema C: Agent Orchestration & Workflow

---

#### Issue C1 — Multi-Skill Agent Orchestrator (setara `appsec-agent`)

**Motivasi (OpenTaint):** Skill `appsec-agent` OpenTaint adalah orchestrator end-to-end dengan:
- 2 dimensi: `scan_level` (lite/normal/deep) × `triage_level` (static/dynamic)
- Pipeline fixed: build → [discover] → scan → [approximation iteration] → triage → [PoC]
- Dispatch ke subagent via Skill tool dengan template prompt
- State tracking via `.opentaint/tracking/state.yaml`
- Resource limit: global cap 7 subagent, RAM cap formula
- Resumption via artifact-based position reconstruction

CodeLens hanya punya `SKILL.md` statis. Tidak ada orchestrator.

**Acceptance Criteria:**
- [ ] Skill baru: `appsec-orchestrator` di `skills/appsec-orchestrator/SKILL.md`
- [ ] Workflow dimensions:
  - `scan_level`: lite (scan saja) / normal (scan + triage) / deep (scan + triage + discover-surface + new rule authoring)
  - `triage_level`: static (TP/FP verdict dari model) / dynamic (static + PoC generation)
- [ ] Pipeline phases (sequential via artifact):
  ```
  scan → [deep: discover-surface + create-rule] → triage → [dynamic: generate-poc] → assemble report
  ```
- [ ] State tracking: `.codelens/tracking/state.yaml`
  ```yaml
  scan_level: deep
  triage_level: dynamic
  phases:
    scan: done
    discover: in_progress
    rules: pending
    triage: pending
    poc: pending
  ```
- [ ] Resource limit: global cap 7 subagent, RAM-aware cap untuk heavy engine (scan, create-rule)
- [ ] Resumption: skip phase yang artifact-nya sudah ada (`.codelens/results/report.sarif` → scan done)
- [ ] Universal rules:
  - Hanya orchestrator yang tulis `.codelens/vulnerabilities.md` dan `state.yaml`
  - Subagent tidak boleh scan main project (kecuali run-scan)
  - Subagent tidak boleh triage (verdict hanya dari analyze-findings)

**Scope teknis:**
- Buat direktori `skills/appsec-orchestrator/` dengan SKILL.md + references/
- Tambah command `codelens orchestrate` yang start workflow
- Tambah `.codelens/tracking/` directory convention

**Estimasi effort:** 2 minggu (mostly documentation + 1 new command)

---

#### Issue C2 — Triage Workflow dengan Per-Finding TP/FP Verdict

**Motivasi (OpenTaint):** Skill `analyze-findings` OpenTaint: split bundle (1 rule → multiple vuln), walk codeFlow source→sink per result, verdict TP/FP per logical finding, tracking file `.opentaint/tracking/findings/<name>.yaml`. CodeLens `analyze` command hanya memberikan bulk analysis.

**Acceptance Criteria:**
- [ ] Command baru: `codelens triage [workspace] [--rule-id ID]`
- [ ] Untuk setiap finding di SARIF/registry:
  - Walk taint path source → hops → sink
  - Auto-suggest verdict berdasarkan heuristik (sanitizer presence, source attacker-controlled, sink safe-for-input)
  - Interaktif (jika TTY) atau batch (jika `--format ai`)
- [ ] Output: `.codelens/triage/findings/<slug>.yaml`
  ```yaml
  finding_name: brave-hopper
  rule_id: sqli-db-execute
  sarif_hashes: [abc123, def456]
  verdict: TP          # pending | TP | FP
  notes: >
    request.args.get("id") is attacker-controlled; reaches cursor.execute
    via string concatenation without parameterization → TP
  poc: pending
  poc_script: null
  ```
- [ ] Split bundle: 1 rule dengan multiple distinct vuln → multiple finding file
- [ ] Merge duplicate: same sink + same flow → 1 finding dengan multiple `sarif_hashes`
- [ ] MCP tool: `triage_finding` untuk verdict per-finding via MCP

**Scope teknis:**
- Tambah `triage_engine.py` (refactor dari `analyze` command)
- Heuristik engine: source classification (network, persistence, config, constant), sink safety check
- YAML schema untuk finding tracking

**Estimasi effort:** 2-3 minggu

---

#### Issue C3 — PoC Generation (Dynamic Vulnerability Confirmation)

**Motivasi (OpenTaint):** Skill `generate-poc` OpenTaint: start app (`spring-boot:run`, `docker compose`), bind `127.0.0.1` only, kirim payload (SQLi, cmd injection, path traversal, XSS, SSRF, XXE), assert observable evidence (rows returned, file contents, command output, time delay, OOB callback), record outcome (confirmed/failed). CodeLens tidak punya dynamic confirmation.

**Acceptance Criteria:**
- [ ] Command baru: `codelens generate-poc <finding-name> [--base-url URL]`
- [ ] Jika `--base-url` tidak diberikan, auto-start app:
  - Detect framework (Django: `python manage.py runserver 127.0.0.1:8000`, Flask: `flask run`, Express: `npm start`, FastAPI: `uvicorn main:app`)
  - Bind ke `127.0.0.1` saja (security: tidak pernah `0.0.0.0` kecuali explicit opt-in)
  - Wait for HTTP server ready (port polling)
  - Register instance di `.codelens/tracking/poc-servers.yaml` untuk teardown
- [ ] Payload library per vuln class:
  - SQLi: `' OR '1'='1`, `UNION SELECT`, time-based `pg_sleep(5)`
  - Command injection: `;cat /etc/passwd`, `|id`
  - Path traversal: `../../../etc/passwd`
  - XSS: `<script>alert(1)</script>`
  - SSRF: `http://169.254.169.254/latest/meta-data/`
  - XXE: `<!ENTITY xxe SYSTEM "file:///etc/passwd">`
- [ ] Assertion engine: observable evidence (HTTP response body, status code, response time, OOB callback)
- [ ] Output: `.codelens/pocs/<finding_name>.py` (self-contained, re-runnable)
- [ ] Update finding tracking: `poc: confirmed | failed`, `poc_script: <path>`, evidence in `notes`
- [ ] Teardown: `codelens poc-teardown` untuk stop semua registered instance
- [ ] Security: refuse to bind ke public interface; warning di log

**Scope teknis:**
- Tambah `poc_engine.py` dengan payload library
- Framework start detector (reuse `framework_detect.py`)
- HTTP client wrapper (uses `requests` or `httpx`)
- Process manager untuk tracking started instances

**Estimasi effort:** 3-4 minggu

---

### Tema D: Distribusi & DX

---

#### Issue D1 — Multi-Channel Installer (Homebrew, npm, pipx, Docker)

**Motivasi (OpenTaint):** OpenTaint distribusi via 6 channel: install.sh, install.ps1, Homebrew cask, npm (`@seqra/opentaint`), npx (zero-install), Docker. CodeLens hanya `git clone` + `bash setup.sh`.

**Acceptance Criteria:**
- [ ] `scripts/install/install.sh` (Linux/macOS) — curl-able: `curl -fsSL https://codelens.dev/install.sh | bash`
- [ ] `scripts/install/install.ps1` (Windows PowerShell) — `irm https://codelens.dev/install.ps1 | iex`
- [ ] Homebrew tap: `brew install --cask wolfvin/tap/codelens`
- [ ] npm package: `npm install -g @wolfvin/codelens` (wrapper yang invoke `python3 codelens.py`)
- [ ] npx: `npx @wolfvin/codelens scan` (zero-install, butuh Node.js)
- [ ] pipx: `pipx install codelens` (setelah pyproject.toml entry point diaktifkan — lihat Issue D2)
- [ ] Docker: `docker run --rm -v $(pwd):/project ghcr.io/wolfvin/codelens:latest scan /project`
- [ ] Versioned release dengan floating tag (`v8`, `v8.x`) + exact (`v8.x.y`)
- [ ] Script `scripts/resolve_codelens_version.py` untuk CI version resolution
- [ ] GitHub Actions workflow: `release-cli.yaml`, `publish-npm.yaml`, `publish-homebrew.yaml`, `publish-docker.yaml`, `update-floating-tags.yaml`

**Scope teknis:**
- Tambah `scripts/install/` directory
- Tambah `cli/wrapper.js` untuk npm package (Node.js wrapper ke Python)
- Tambah `Dockerfile` di root
- Update `pyproject.toml` dengan entry point (Issue D2)
- Setup GHCR untuk Docker image

**Estimasi effort:** 2 minggu

---

#### Issue D2 — Python Package Entry Point & pipx Support

**Motivasi (OpenTaint):** OpenTaint CLI adalah binary Go yang standalone. CodeLens Python-based, tapi `pyproject.toml` line 65-67 secara eksplisit mengatakan: *"Entry point removed — codelens is run directly via python3 codelens.py. The scripts/ directory uses sys.path-based imports, not a proper Python package."* Ini memblok `pip install codelens` dan `pipx install codelens`.

**Acceptance Criteria:**
- [ ] Refactor `scripts/` menjadi proper Python package `codelens/` dengan `__init__.py`
- [ ] Convert sys.path-based imports ke absolute imports (`from codelens.engine import ...`)
- [ ] Tambah entry point di `pyproject.toml`:
  ```toml
  [project.scripts]
  codelens = "codelens.cli:main"
  ```
- [ ] `pip install codelens` → `codelens --help` works
- [ ] `pipx install codelens` → isolated install
- [ ] Backward-compat: `python3 scripts/codelens.py` tetap berfungsi (legacy mode, deprecation warning)
- [ ] Update README Installation section
- [ ] Release ke PyPI (GH Actions workflow `publish-pypi.yaml`)

**Scope teknis:**
- Rename `scripts/` → `codelens/` (atau symlink untuk backward-compat)
- Tambah `codelens/__init__.py`, `codelens/cli.py` (entry point wrapper)
- Update semua import statement
- Update `setup.sh` untuk mendeteksi pip install vs legacy

**Estimasi effort:** 1-2 minggu (mostly mechanical refactor)

---

#### Issue D3 — Versioning Konsisten & CHANGELOG.md yang Terstruktur

**Motivasi (OpenTaint):** OpenTaint konsisten v0.x dengan semver + floating tag. CodeLens inkonsisten: README bilang v8.1, `skill.json` & `pyproject.toml` bilang v7.2.0, `SKILL.md` bilang v7.2. Command count juga inkonsisten: README "56 commands", `skill.json` "45 commands", actual file count 58.

**Acceptance Criteria:**
- [ ] Single source of truth untuk version: `codelens/__version__.py` (atau `codelens/constants.py`)
- [ ] Semua file baca dari source of truth itu: `pyproject.toml` (dynamic version), `skill.json`, `README.md` (badge), `SKILL.md`, `mcp_server.py` (`MCP_SERVER_VERSION`)
- [ ] Single source of truth untuk command count: auto-generate dari `len(os.listdir('scripts/commands')) - 1` (exclude `__init__.py`)
- [ ] Update README & skill.json dengan angka aktual (58 command, version konsisten)
- [ ] CHANGELOG.md format mengikuti Keep a Changelog (sudah ada, tapi perlu audit)
- [ ] Pre-release hook: CI cek bahwa version di semua file konsisten sebelum release

**Scope teknis:**
- Buat `codelens/_version.py` dengan `__version__ = "8.1.0"`
- Update `pyproject.toml`: `dynamic = ["version"]` dengan `[tool.setuptools.dynamic] version = {attr = "codelens._version.__version__"}`
- Update `skill.json`: hapus field `version`, baca dari `_version.py` saat build
- CI check di `codelens-quality-gate.yml`

**Estimasi effort:** 3 hari

---

#### Issue D4 — GitLab CI Template & Translation README

**Motivasi (OpenTaint):** OpenTaint punya `gitlab/opentaint.gitlab-ci.yml` template siap pakai + 21 terjemahan README (termasuk Bahasa Indonesia). CodeLens punya `.gitlab-ci.yml` di root (1.543 bytes, basic) dan tidak ada translation.

**Acceptance Criteria:**
- [ ] Pindahkan `.gitlab-ci.yml` ke `gitlab/codelens.gitlab-ci.yml` (template, include-able)
- [ ] Template support: variable input (`CODELENS_VERSION`, `PROJECT_ROOT`, `UPLOAD_SARIF`, `SEVERITY`)
- [ ] Job: `codelens-scan` (install + scan + upload SARIF as artifact + optional GitLab Code Quality report)
- [ ] Tambah `docs/translations/README.id.md` (Bahasa Indonesia)
- [ ] Tambah minimal 5 terjemahan lagi: `README.zh.md`, `README.ja.md`, `README.es.md`, `README.fr.md`, `README.de.md`
- [ ] Language selector link di README.md utama (seperti OpenTaint)

**Scope teknis:**
- Refactor `.gitlab-ci.yml` jadi template
- Translate README (bisa pakai AI assistance, review oleh native speaker)
- Update root README dengan language selector

**Estimasi effort:** 1 minggu

---

### Tema E: Documentation & Knowledge

---

#### Issue E1 — Approximation Authoring Guide

**Motivasi (OpenTaint):** OpenTaint punya skill `create-pass-through-approximation` dan `create-dataflow-approximation` dengan SKILL.md detail berisi pattern, constraint, troubleshooting. CodeLens perlu dokumentasi serupa untuk approximation system yang akan dibangun di Issue A3.

**Acceptance Criteria:**
- [ ] File baru: `references/approximations.md`
- [ ] Section: "When to use passThrough vs dataflow approximation"
- [ ] Section: "Authoring passThrough YAML" dengan 10+ contoh
- [ ] Section: "Authoring dataflow approximation (Python plugin)" dengan 5+ contoh
- [ ] Section: "Testing approximation" (integrasi dengan Issue B1 test harness)
- [ ] Section: "Troubleshooting" (target class mismatch, signature mismatch, over-broad propagation)
- [ ] Section: "Built-in approximation list" (auto-generated dari `scripts/approximations/`)

**Estimasi effort:** 1 minggu (paralel dengan Issue A3)

---

#### Issue E2 — Agent Integration Guide Update

**Motivasi (OpenTaint):** OpenTaint punya 13 skill file terstruktur dengan delegation pattern, tracking schema, resource limit formula. CodeLens `references/agent-integration.md` perlu update untuk support multi-skill orchestrator (Issue C1).

**Acceptance Criteria:**
- [ ] Update `references/agent-integration.md`:
  - Tambah section "Multi-skill orchestrator pattern"
  - Tambah section "State tracking via `.codelens/tracking/state.yaml`"
  - Tambah section "Resource limit formula" (port dari OpenTaint: `cap_heavy = max(1, min(cores, floor(free_GB / 2), 7))`)
  - Tambah section "Subagent dispatch template"
  - Tambah section "Resumption via artifact-based position reconstruction"
- [ ] Tambah `references/rule-authoring.md`:
  - Section "Rule anatomy" (sources, sinks, sanitizers, metadata)
  - Section "Test-driven rule authoring" (integrasi Issue B1)
  - Section "Debugging rules" (integrasi Issue A4)
  - Section "Semgrep compatibility" (jika Issue B2 dikerjakan)

**Estimasi effort:** 1 minggu

---

### Tema F: Quality & Housekeeping

---

#### Issue F1 — Consolidate Taint Engine (Hapus Engine Duplikasi)

**Motivasi:** CodeLens punya 4 engine terkait taint yang overlapping: `ast_taint_engine.py` (3.756 LOC), `crossfile_taint_engine.py` (946 LOC), `dataflow_engine.py` (1.097 LOC), `semantic_engine.py` (regex-based, legacy). Ini menyulitkan maintenance dan behavior tidak konsisten antar engine.

**Acceptance Criteria:**
- [ ] Audit semua 4 engine: documented behavior, test coverage, actual usage
- [ ] Deprecate `semantic_engine.py` (regex-based legacy) — pindahkan rule ke `ast_taint_engine.py` atau `dataflow_engine.py`
- [ ] Konsolidasi `crossfile_taint_engine.py` ke `ast_taint_engine.py` (lihat Issue A1)
- [ ] Tambah deprecation warning di `semantic_engine.py`: `"WARNING: semantic_engine is deprecated since v8.x, use ast_taint_engine or dataflow_engine instead. Will be removed in v9.x."`
- [ ] Migration guide di `references/changelog.md`

**Estimasi effort:** 2 minggu

---

#### Issue F2 — Command Count & Version Source of Truth

(Lihat juga Issue D3 — ini subset yang lebih kecil jika D3 tertunda)

**Acceptance Criteria:**
- [ ] Auto-generate `skill.json` `command_categories` dari `scripts/commands/` directory listing
- [ ] Script `scripts/generate_skill_metadata.py` yang baca `scripts/commands/*.py` (extract command name dari argparser) → tulis `skill.json`
- [ ] CI check: `skill.json` harus match actual command files (fail jika mismatch)
- [ ] Update README dengan angka aktual

**Estimasi effort:** 3 hari

---

## 7. Prioritas & Roadmap Eksekusi

Roadmap diurutkan berdasarkan **impact** (kedalaman fitur baru) dan **dependency** (issue yang block issue lain):

### Fase 1 — Fondasi (Q3 2026, ~6-8 minggu)

| Issue | Effort | Dependency | Impact |
|---|---|---|---|
| **D3** Versioning konsisten | 3 hari | — | tinggi (unblock semua) |
| **F2** Command count source of truth | 3 hari | D3 | sedang |
| **D2** Python package entry point | 1-2 minggu | — | tinggi (unblock D1) |
| **A1** Unified cross-file taint engine | 3-4 minggu | — | **kritis** |
| **F1** Consolidate taint engine | 2 minggu | A1 | sedang |

### Fase 2 — Approximation & Rule Authoring (Q4 2026, ~10-12 minggu)

| Issue | Effort | Dependency | Impact |
|---|---|---|---|
| **A3** Library method approximation | 4-5 minggu | A1 (soft) | **kritis** |
| **A4** Debug-trace taint engine | 3 minggu | A3 | tinggi |
| **B1** Rule test harness | 2 minggu | — | tinggi |
| **B2** Semgrep-compatible format | 5-6 minggu | — | tinggi (buka ekosistem) |
| **E1** Approximation authoring guide | 1 minggu | A3 | sedang |

### Fase 3 — Agent Workflow & Dynamic Confirm (Q1 2027, ~8-10 minggu)

| Issue | Effort | Dependency | Impact |
|---|---|---|---|
| **C2** Triage workflow per-finding | 2-3 minggu | — | tinggi |
| **C3** PoC generation | 3-4 minggu | C2 | tinggi |
| **C1** Multi-skill orchestrator | 2 minggu | C2, C3, A4 | **strategis** |
| **A2** Persistence/stored injection | 2 minggu | A1 | sedang |
| **B3** Attack surface discovery | 3 minggu | — | sedang |

### Fase 4 — Distribusi & DX (Q2 2027, ~4-5 minggu)

| Issue | Effort | Dependency | Impact |
|---|---|---|---|
| **D1** Multi-channel installer | 2 minggu | D2 | tinggi (DX) |
| **D4** GitLab CI template + translation | 1 minggu | — | sedang |
| **E2** Agent integration guide update | 1 minggu | C1 | sedang |

### Total Estimasi: ~28-35 minggu (~7-9 bulan)

**Quick win pertama yang bisa langsung di-PR:** Issue D3 (versioning konsisten) — 3 hari, no dependency, unblock banyak hal.

---

## 8. Catatan Teknis & Risiko

### 8.1 Risiko Teknis

1. **Porting Semgrep parser dari Kotlin ke Python (Issue B2)** — OpenTaint punya ~80 file Kotlin di `pattern/conversion/` yang implementasi Semgrep pattern parsing. Porting ke Python bukan trivial; estimated 5-6 minggu bisa membengkak. **Mitigasi:** Mulai dengan subset pattern (pattern-either, pattern-not, focus-metavariable) yang cover 80% use case; tambah sisanya iteratif.

2. **Cross-file taint engine performance (Issue A1)** — Engine unified bisa jadi 2-3x lebih lambat dari intra-file saja. **Mitigasi:** Incremental scan wajib (sudah ada), cache call graph di registry, tambah `--max-depth` flag untuk batasi hop.

3. **Approximation plugin Python (Issue A3)** — Tidak bisa langsung port `@Approximate` Java annotation ke Python. Perlu design API baru. **Mitigasi:** Pelajari Python AST manipulation library (`ast`, `inspect`); pertimbangkan decorator-based API `@approximate(target="Promise.then")`.

4. **PoC generation security (Issue C3)** — Risiko PoC script dieksekusi di machine user. **Mitigasi:** Bind `127.0.0.1` only (hardcoded, tidak bisa override tanpa `--allow-public-bind` eksplisit); sandboxing via Docker jika memungkinkan; warning di log.

5. **Backward compatibility rule format (Issue B2)** — Format YAML lama harus tetap berfungsi. **Mitigasi:** Versioning di YAML frontmatter (`format_version: 1` vs `format_version: 2`); deprecation warning di v8.x, removal di v10.x.

### 8.2 Risiko Non-Teknis

1. **Scope creep** — 16 issue adalah jumlah besar. **Mitigasi:** Roadmap bertahap (Fase 1-4); setiap fase dirilis sebagai minor version (v8.2, v8.3, v9.0, v9.1).

2. **Maintenance burden** — Engine unified + approximation + agent orchestrator = surface area besar. **Mitigasi:** Investasi di test coverage (Issue B1) dan benchmark regression (sudah ada) sebelum tambah fitur baru.

3. **Komunitas OpenTaint lebih aktif di JVM** — Jika CodeLens fokus serap konsep OpenTaint, pastikan tetap differentiated di breadth (frontend, multi-bahasa). **Mitigasi:** Issue-issue di atas semua mempertahankan breadth CodeLens; tidak ada yang menyempitkan ke JVM only.

### 8.3 Yang TIDAK Perlu Diserap dari OpenTaint

Beberapa hal OpenTaint tidak relevant atau inferior untuk CodeLens:

1. **JVM-specific autobuilder** (`MavenProjectResolver`, `GradleProjectResolver`) — CodeLens multi-bahasa, tidak perlu Maven/Gradle specific.
2. **Semgrep Java pattern parser** (`SemgrepJavaPattern.kt`, `JavaLanguageStrategy.kt`) — CodeLens perlu multi-bahasa parser, bukan Java-only.
3. **Spring endpoint auto-discovery** — Spesifik Spring; CodeLens perlu generic web framework detection (sudah ada di `framework_detect.py`).
4. **CLI binary Go** — CodeLens sudah Python-based, tidak perlu rewrite ke Go.
5. **CodeQL/CodeChecker integration** — CodeLens sudah punya SARIF + GitHub Code Scanning integration.

### 8.4 Konvensi Penamaan yang Diadopsi dari OpenTaint

Berikut konvensi OpenTaint yang worth diadopsi di CodeLens:

- `.codelens/tracking/state.yaml` — state file untuk orchestrator (vs OpenTaint `.opentaint/tracking/state.yaml`)
- `.codelens/triage/findings/<slug>.yaml` — per-finding tracking file
- `.codelens/pocs/<finding_name>.py` — PoC script location
- `.codelens/approximations/passthrough/` dan `dataflow/` — approximation directory structure
- `dropped-methods.yaml` + `approximated-methods.yaml` — file naming untuk external method tracking
- `finding_name` dengan docker-style slug (mis. `brave-hopper`, `clever-einstein`) — human-readable random ID
- `partial-fingerprint` untuk SARIF finding deduplication (OpenTaint pakai `vulnerabilityWithTraceHash/v1` key)

---

## Penutup

Dokumen ini adalah **analisis komprehensif** yang menjadi dasar perencanaan upgrade CodeLens berikutnya. Setiap issue di Section 6 sudah dirancang untuk bisa langsung di-PR ke GitHub Issue Tracker CodeLens dengan format yang actionable.

**Rekomendasi eksekusi:**
1. Mulai dari **Fase 1** (Issue D3, F2, D2, A1, F1) — fondasi yang unblock sisanya.
2. Issue **A1 (unified taint engine)** dan **A3 (approximation system)** adalah dua highest-impact item — prioritaskan resource terbaik.
3. Issue **C1 (multi-skill orchestrator)** adalah strategic differentiator yang membuat CodeLens setara dengan OpenTaint dalam hal agent workflow — wajib di Fase 3.
4. Issue **D1 (multi-channel installer)** dan **D2 (pipx support)** akan signifikan menurunkan barrier to entry — prioritaskan di Fase 4 untuk boost adoption.

**Repo referensi:** https://github.com/seqra/opentaint.git (Apache 2.0 + MIT dual license — kompatibel untuk inspiration/adaptasi dengan attribusi).
