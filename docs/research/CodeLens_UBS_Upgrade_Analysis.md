# CodeLens × Ultimate Bug Scanner (UBS) — Analisis Fitur & Issue Upgrade Plan

> **Repo referensi:** [`Dicklesworthstone/ultimate_bug_scanner`](https://github.com/Dicklesworthstone/ultimate_bug_scanner) (MIT + OpenAI/Anthropic Rider, versi dianalisa: **v5.3.3**, latest git tag `v5.2.75` per 2026-05-06)
> **Repo target:** `Wolfvin/CodeLens` (analisa commit `main` per 2026-06-28)
> **Tanggal analisa:** 2026-06-28
> **Bahasa dokumen:** Indonesia (sesuai input user)
> **Tujuan:** Identifikasi fitur UBS yang bisa diserap ke CodeLens, daftar peningkatan yang *sudah di-adjust*, dan terbitkan template issue GitHub untuk masing-masing gap.

---

## 0. TL;DR — Ringkasan Eksekutif

Ultimate Bug Scanner (UBS) adalah **AI-native bug scanner** yang sangat berbeda dari opengrep: bukan SAST engine pattern-matching, melainkan **meta-runner Bash** yang mengorkestrasi 10 scanner module per-bahasa (`ubs-js.sh`, `ubs-python.sh`, dll, total 62K LOC Bash). Filosofi UBS: **smoke detector** (3-5 detik scan, ~30 rule per bahasa, 10-20% false positive acceptable karena LLM filter cepat) vs **building inspector** (ESLint/SonarQube yang komprehensif tapi lambat).

CodeLens dan UBS **sama-sama AI-native**, tapi dengan niche berbeda:
- **CodeLens** = code intelligence platform (registry, call graph, MCP server, guard pre/post-write, 58 command)
- **UBS** = bug-focused scanner (one-shot scan, fast feedback, multi-language unified report, agent guardrails)

**Verdict kunci:** CodeLens **tidak boleh jadi UBS clone** — CodeLens punya MCP + registry + 58 command yang UBS tidak punya. Yang harus diserap dari UBS adalah **DX (developer experience) & agent integration patterns** yang CodeLens belum punya, terutama:

1. **ast-grep rule engine** (UBS pakai ast-grep untuk pattern matching AST, CodeLens masih regex+tree-sitter ad-hoc)
2. **`# ubs:ignore` inline suppression** (CodeLens belum punya)
3. **`.ubsignore` file** (CodeLens hanya punya `DEFAULT_IGNORE_DIRS` hardcoded)
4. **10 agent integrations** auto-detect (Claude Code, Cursor, Codex, Gemini, Windsurf, Cline, OpenCode, Aider, Continue, Copilot, TabNine, Replit)
5. **Git safety guard** (block `git reset --hard`, `rm -rf`, `git push --force` dari agent)
6. **`ubs doctor` environment audit** (CodeLens belum ada)
7. **`ubs sessions` install log** (CodeLens belum ada)
8. **Comparison/baseline scan** (`--comparison baseline.json` → delta JSON)
9. **HTML report** standalone (CodeLens belum ada)
10. **TOON format** (token-optimized output, ~50% lebih kecil dari JSON)
11. **Manifest-driven test suite** dengan `require_substrings` + `forbid_substrings` (402 test case, lebih kaya dari CodeLens benchmark)
12. **Rule quality harness** dengan golden snapshot (regression detection untuk rule akurasi)
13. **Ast-grep auto-provisioning** (download binary per-platform, SHA-256 verified)
14. **Minisign + Cosign release signing** (CodeLens belum sign release)
15. **Homebrew tap + Scoop + Nix flake + Docker image** distribusi multi-channel
16. **Cross-language async error detection** dengan pattern konsisten di 10 bahasa
17. **Resource lifecycle correlation** (acquire vs release pair matching)
18. **Type narrowing helpers** untuk Rust/Kotlin/Swift/C#/TypeScript (CodeLens hanya punya `typeinfer_engine.py` generik)
19. **`--profile=strict|loose`** (CodeLens tidak punya preset profile)
20. **`--category=<name>`** untuk focused scan (CodeLens belum punya category filter)

Detail per-fitur dan issue template ada di Section 4 & 5.

---

## 1. Inventory Fitur CodeLens (recap)

Dari analisa dokumen sebelumnya (CodeLens vs opengrep), CodeLens punya:
- 58 CLI command (auto-import via `scripts/commands/__init__.py`)
- 41 file `*_engine.py` (avg 500-3700 LOC)
- 11 tree-sitter parser + 25 fallback regex parser (total 41 file)
- MCP server 49 tool (MCP 2025-03-26, JSON-RPC stdio + HTTP/SSE)
- Plugin system 4 tipe (`rule_pack`, `engine`, `formatter`, `command`), 3-tier discovery
- 2 formatter (markdown, sarif v2.1.0)
- OSV.dev integration (9 ecosystem, SQLite cache, native audit fallback)
- 4 GitHub Actions workflow
- 89 rule YAML builtin (OWASP 36 + HIPAA 26 + PCI-DSS 27)

CodeLens **belum punya** (yang relevan untuk serapan UBS):
- Inline suppression (`# codelens-ignore`)
- `.codelensignore` file (gitignore-style)
- `doctor` command (env audit)
- `sessions` command (install log)
- HTML report
- TOON format
- Comparison/baseline delta
- Profile preset (`strict`/`loose`)
- Category pack filter
- ast-grep integration (CodeLens pakai tree-sitter ad-hoc, bukan ast-grep)
- Agent integration auto-detect (Claude Code hook, Cursor rules, Codex rules, dll)
- Git safety guard
- Release signing (minisign/cosign)
- Homebrew/Scoop/Nix distribution
- Manifest-driven test dengan substring assertion
- Rule quality harness dengan golden snapshot

---

## 2. Inventory Fitur Ultimate Bug Scanner (UBS)

Dihimpun dari `README.md` (2684 baris), `SKILL.md`, `CHANGELOG.md`, `AGENTS.md`, source code `ubs` (3594 LOC), `modules/ubs-*.sh` (62K LOC total), `modules/helpers/`, `test-suite/manifest.json` (402 case), `docs/`, dan `install.sh` (3750 LOC).

### 2.1 Arsitektur

| Lapisan | Implementasi | Catatan |
|---|---|---|
| Meta-runner | `ubs` (Bash 5+, 3594 LOC) | Language detection + dispatch + merge via jq |
| Language modules | 10 file `modules/ubs-*.sh` (62K LOC total) | JS, Python, Rust, Go, Java, C/C++, Ruby, Swift, C#, Elixir |
| Pattern matching | ripgrep (regex) + ast-grep (AST) + helper Python/Go/JS | Hybrid 4-layer |
| Helper assets | `modules/helpers/*.py` (8 file) + `.go` (1) + `.js` (1) | AST walker untuk resource lifecycle + type narrowing |
| Output formats | text, json, jsonl, sarif, html, TOON (6 format) | Merged via jq |
| Test harness | `test-suite/manifest.json` (402 case) + `run_manifest.py` | Snapshot + substring + exit code + totals assertion |
| Rule quality | `test-suite/quality/rule_quality_harness.py` + `goldens/rule_coverage.json` | Golden snapshot untuk rule coverage regression |
| Distribution | install.sh + Homebrew + Scoop + Nix flake + Docker + GitHub Releases | Multi-channel |
| Signing | minisign (SHA256SUMS) + Cosign (OCI image, keyless, Rekor transparency log) | Defense in depth |
| Module integrity | SHA-256 embedded di `ubs` meta-runner, verified before execution | Supply-chain hardening |
| Auto-update | opt-in via `UBS_ENABLE_AUTO_UPDATE=1`, force-disable `UBS_NO_AUTO_UPDATE=1` | CI-safe |

### 2.2 Bahasa yang didukung (10 bahasa)

JavaScript/TypeScript, Python, C/C++, Rust, Go, Java, Ruby, Swift, C#, Elixir. Kotlin di-handle via `ubs-java.sh` (extension `.kt`/`.kts`).

Catatan: **CodeLens support 28+ bahasa via fallback regex parser**, tapi untuk analisis security taint AST-level hanya 4 bahasa (Python, JS, TS, Rust). UBS support 10 bahasa dengan ast-grep rule packs untuk semua.

### 2.3 Detection categories (per-bahasa, 18-23 kategori)

Dari `print_header` di setiap module:

**JavaScript/TS (19 category):**
1. Null Safety & Defensive Programming
2. Math & Arithmetic Pitfalls
3. Array & Collection Safety
4. Type Coercion & Comparison Traps
5. Async/Await & Promise Pitfalls (paling kaya: missing await, React hooks deps, async forEach/flatMap/reduce/predicate/sort-comparator, EventEmitter, JSX async listener, Promise.all map/forEach guard)
6. Error Handling Anti-Patterns
7. Security Vulnerabilities (XSS, prototype pollution, eval, SQL inj, JWT bypass, CORS, cookies, randomness, TLS, SSRF, response headers, path traversal, archive extraction, target blank, dangerous HTML, dll)
8. Function & Scope Issues
9. Parsing & Type Conversion Bugs
10. Control Flow Gotchas
11. Debugging & Production Code
12. Memory Leaks & Performance
13. Variable & Scope Issues
14. Code Quality Markers
15. Regex & String Safety (ReDoS)
16. DOM Manipulation Safety
17. TypeScript Strictness
18. Node.js I/O & Modules
19. Resource Lifecycle Correlation

**Python (23 category):** sama struktur + tambahan:
- UV-Powered Extra Analyzers (ruff, bandit, pip-audit, mypy, safety, detect-secrets via uvx)
- Deprecations & Py3.13 Migrations
- Packaging & Config Hygiene
- Notebook Hygiene (`.ipynb` checks)

**Rust (20 category):** Ownership & Error Handling Macros, Unsafe & Memory, Concurrency & Async, Numeric & Float, Collections & Iterators, String & Allocation, Filesystem & Process, Security, Code Quality, Module & Visibility, Tests & Benches, Lints & Style (fmt/clippy), Build Health (check/test), Dependency Hygiene, API Misuse, Domain-Specific, ast-grep Rule Pack, Meta Stats, Resource Lifecycle, Async Locking Across Await.

### 2.4 Rule schema (ast-grep YAML)

UBS pakai ast-grep rule format (kompatibel dengan `--rules=DIR`):

```yaml
id: custom.no-console-in-prod
language: javascript
rule:
  any:
    - pattern: console.log($$$)
    - pattern: console.debug($$$)
    - pattern: console.info($$$)
severity: warning
message: "console statements should be removed before production"
note: "Use a proper logging library or remove debug statements"
```

Ast-grep mendukung:
- `pattern`, `any`, `all`, `not`, `inside`, `has`, `precedes`, `follows`
- `kind` (tree-sitter node type)
- `regex` (literal regex pada node text)
- Metavariable: `$X`, `$$$ARGS` (multi), `$NAME` (named)
- `stopBy: end` (ancestor traversal — lihat Section 2.5)
- `constraints` (metavariable type constraint)
- `utils` (reusable rule definitions)

### 2.5 Ancestor-aware pattern matching (`stopBy: end`)

Teknik novel UBS untuk reduce false positive. Contoh:

```yaml
rule:
  all:
    - pattern: fetch($ARGS)
    - not:
        inside:
          kind: try_statement
          stopBy: end           # ← traverse ALL ancestors, bukan immediate parent
    - not:
        inside:
          pattern: $_.catch($$)  # Check for .catch() in chain
          stopBy: end
```

Tanpa `stopBy: end`, ast-grep hanya cek immediate parent (ExpressionStatement), false positive untuk `try { fetch() } catch {}`. Dengan `stopBy: end`, ast-grep walk up entire ancestor tree. Diterapkan di 19+ rule di JS module.

### 2.6 Cross-language async error detection

Pattern konsisten di 10 bahasa:

| Language | Pattern | What UBS Detects |
|---|---|---|
| JS/TS | `promise.then()` tanpa `.catch()`, `new Promise(async ...)`, `forEach(async ...)`, async predicate, async timer/event/JSX callback, `Promise.all(map(...))` tanpa return | Dangling promises, missing await, unawaitable async callbacks |
| Python | `asyncio.create_task()` tanpa `await` | Orphaned tasks, unclosed coroutines |
| Go | Goroutine tanpa error channel | Fire-and-forget, leaked contexts |
| Rust | `.unwrap()`/`.expect()` setelah `if let Some` guard | Panic after partial guard |
| Java | `CompletableFuture` tanpa `.exceptionally()` | Swallowed exceptions |
| Ruby | `Thread.new` tanpa `.join` | Zombie threads |
| C++ | `std::async` tanpa `.get()` | Ignored futures |
| Swift | `Task {}` tanpa error handling | Unstructured concurrency leaks |
| C# | `Task.Wait()`, `.Result`, `throw ex;` | Sync-over-async deadlock, stack-trace loss |

### 2.7 Resource lifecycle correlation

AST-based detector untuk acquire/release mismatch. Contoh Python (`modules/helpers/resource_lifecycle_py.py`, 402 LOC):

```python
TARGET_SIGS = {
    (None, "open"): "file_handle",
    ("subprocess", "Popen"): "popen_handle",
    ("asyncio", "create_task"): "asyncio_task",
}
RELEASE_METHODS = {
    "file_handle": {"close"},
    "popen_handle": {"wait", "communicate", "terminate", "kill"},
    "asyncio_task": {"cancel"},
}
```

Helper walk AST, track setiap acquire call, cek apakah ada matching release (`.close()`, `with open(...)`, `await asyncio.gather(...)`, dll). Kalau tidak ada → finding dengan line number akurat.

Coverage per-bahasa:
- Python: file/socket/Popen/asyncio task
- Go: `context.With*` + cancel, `time.NewTicker/NewTimer` + Stop, `os.Open` + Close, mutex Lock/Unlock symmetry
- Java: `FileInputStream`, JDBC, `ExecutorService` shutdown, `Thread` join (via ast-grep rule: `java.resource.executor-no-shutdown`, dll)
- C#: `CancellationTokenSource`, stream readers/writers, `HttpRequestMessage`, `Task.Run` handles
- C++: `malloc/free`, `fopen/fclose`, RAII
- Ruby: `File.open` + block, `Tempfile.create`
- Swift: `defer` symmetry
- Elixir: `File.*`, `send_file`, `send_download`

### 2.8 Type narrowing helpers

AST-based type narrowing analysis (CodeLens hanya punya `typeinfer_engine.py` generik, bukan type narrowing khusus):

| Bahasa | Helper | Fokus |
|---|---|---|
| TypeScript/JS | `type_narrowing_ts.js` (325 LOC, pakai `typescript` npm package via tsserver) | Null guards, optional chaining, type predicates, discriminated unions |
| C# | `type_narrowing_csharp.py` | Null guards, `TryGetValue` fallthrough, dereference after failed narrowing |
| Rust | `type_narrowing_rust.py` | `if let Some/Ok` guard + subsequent `.unwrap()`/`.expect()` |
| Kotlin | `type_narrowing_kotlin.py` | Nullable types, smart casts, `.kt`/`.kts` |
| Swift | `type_narrowing_swift.py` | Optional binding, guard statements, ObjC bridging |

### 2.9 Output formats (6 format)

| Format | Flag | Use case |
|---|---|---|
| text | (default) | Human-readable terminal |
| json | `--format=json` | Machine parsing, scripting |
| jsonl | `--format=jsonl` | Streaming, Beads/`jq` integration |
| sarif | `--format=sarif` | GitHub code scanning |
| html | `--html-report=file.html` | Standalone HTML dashboard untuk PR/chat |
| toon | `--format=toon` | TOON (Token-Optimized Object Notation), ~50% lebih kecil dari JSON, LLM-optimized |

**TOON** = format kustom UBS yang kompres JSON dengan schema inference. Sample size: 15KB JSON → 7.5KB TOON (49.6% saving), ~34% token saving untuk LLM.

### 2.10 Inline suppression & ignore

- **Inline:** `eval(trustedCode);  // ubs:ignore` (same-line) atau `// ubs:ignore -- reason` (dengan alasan)
- **`# ubs:ignore`** (Python), `// ubs:ignore` (JS), `# ubs:ignore` (Ruby) — bekerja di 10 bahasa
- **Block comment** tidak didukung (hanya line comment)
- **`.ubsignore` file** (gitignore-style syntax):
  - 1 glob per line, `#` untuk comment
  - Auto-load dari `PROJECT/.ubsignore`, override dengan `--ignore-file=/path/to/file`
  - `--suggest-ignore` untuk print kandidat direktori besar yang perlu di-ignore

### 2.11 CLI flags penting

```bash
ubs [OPTIONS] [PROJECT_DIR] [OUTPUT_FILE]

Core:
  -v, --verbose            Show 10 code samples per finding (default: 3)
  -q, --quiet              Minimal output (summary only)
  --ci                     CI mode (stable output, no colors, UTC ISO-8601)
  --fail-on-warning        Exit 1 on warnings (strict mode)
  --version                Print version
  --profile=MODE           strict|loose (preset)
  --baseline=FILE          Compare findings against baseline JSON (alias --comparison)
  -h, --help

Git Integration:
  --staged                 Scan only staged files
  --diff, --git-diff       Scan working tree vs HEAD

Output Control:
  --format=FMT             text|json|jsonl|sarif|toon
  --beads-jsonl=FILE       Write JSONL for Beads/"strung"
  --no-color               Disable ANSI
  --report-json=FILE       Enriched summary (project, totals, git, comparison)
  --html-report=FILE       Standalone HTML dashboard
  --comparison=FILE        Diff vs baseline JSON → delta block

File Selection:
  --include-ext=CSV        File extensions (default: auto-detect)
  --exclude=GLOB[,...]     Additional paths to exclude
  --skip-size-check        Skip directory size guard
  --ignore-file=PATH       Custom .ubsignore path
  --suggest-ignore         Print large-dir candidates (no changes)

Performance:
  --jobs=N                 Parallel jobs for ripgrep (default: auto-detect)
  --skip-type-narrowing    Disable helper-backed guard analysis (faster)
  --max-file-size=SIZE     ripgrep limit

Rule Control:
  --skip=CSV               Skip categories by number (e.g., --skip=11,14)
  --skip-LANG=N[,M,...]    Skip categories in one language only (e.g., --skip-js=8)
  --rules=DIR              Additional ast-grep rules directory (merged with builtin)
  --category=NAME          Focus scan on category pack (e.g., --category=resource-lifecycle)
  --only=LANG[,LANG,...]   Language filter (faster)
  --no-auto-update         Disable auto-update check
  --update-modules         Force module re-download

Maintenance:
  doctor                   Audit environment + module integrity
  doctor --fix             Auto-repair missing dependencies
  sessions                 Show last installer session log
  sessions --entries=N     Last N sessions
  sessions --raw           Full unformatted log

Exit Codes:
  0 = No critical issues
  1 = Critical issues found (or warnings with --fail-on-warning)
  2 = Environment error (missing ast-grep, etc.)
```

### 2.12 Agent integrations (12+ auto-detect)

`install.sh` deteksi coding agent di workstation dan auto-wire guardrails:

| Agent | Detection Signal | Integration Type |
|---|---|---|
| Claude Code | `.claude/` directory | Hooks + rules (`.claude/hooks/on-file-write.sh`) |
| Cursor | `.cursor/` directory | Rules file (`.cursor/rules`) |
| Codex CLI | `.codex/` directory | Rules file/dir (`.codex/rules/ubs.md`, support v0.77.0+ format) |
| Gemini Code Assist | `.gemini/` directory | Rules file (`.gemini/rules`) |
| Windsurf | `.windsurf/` directory | Rules file + command palette snippet |
| Cline | `.cline/` directory | Markdown instructions (`.cline/rules`) |
| OpenCode MCP | `.opencode/` directory | Local MCP instructions |
| Aider | `.aider.conf.yml` | Lint command config (`lint-cmd: "ubs --fail-on-warning ."`, `auto-lint: true`) |
| Continue | `.continue/` directory | Rules file |
| GitHub Copilot | VS Code extensions | Workspace settings |
| TabNine | `.tabnine/` directory | Configuration |
| Replit | `replit.com` detection | Environment setup |

`--easy-mode` flag: auto-install semua dependency, accept semua prompt, detect semua agent, wire guardrails tanpa interaksi.

### 2.13 Git safety guard (untuk AI agents)

`.claude/hooks/git_safety_guard.py` intercept shell command sebelum eksekusi:

| Blocked Command | Why | Safe Alternative |
|---|---|---|
| `git checkout -- <file>` | Discards uncommitted changes | `git stash` first |
| `git reset --hard` | Destroys all uncommitted work | `git reset --soft` atau `git stash` |
| `git clean -f` | Removes untracked files forever | `git clean -n` (dry-run) first |
| `git push --force` | Rewrites shared history | `git push --force-with-lease` |
| `rm -rf` on non-temp paths | Deletes files irrecoverably | Explicit temp path required |
| `git branch -D` | Deletes unmerged branches | `git branch -d` (safe delete) |
| `git stash drop/clear` | Loses stashed work | Manual review first |

Pintar: allow `rm -rf` hanya untuk `${TMPDIR}/...`, `/tmp/...`, `/var/tmp/...`. Block untuk project dirs, home folders, ambiguous paths.

### 2.14 Manifest-driven test suite (402 case)

`test-suite/manifest.json` (11828 baris, 402 case). Schema:

```json
{
  "id": "python-resource-lifecycle",
  "path": "test-suite/python/buggy",
  "language": "python",
  "tags": ["python", "resource", "buggy"],
  "args": ["--only=python", "--category=resource-lifecycle"],
  "env": {"NO_COLOR": "1"},
  "expect": {
    "exit_code": "nonzero",
    "totals": {
      "critical": {"min": 3},
      "warning": {"min": 1}
    },
    "require_substrings": ["context manager", "file handle"],
    "forbid_substrings": ["..."],
    "require_substrings_stderr": ["..."]
  }
}
```

Artifact capture: `stdout.log`, `stderr.log`, `result.json` per test case. Runner: `test-suite/run_manifest.py` (support `--case`, `--list`, `--fail-fast`).

### 2.15 Rule quality harness dengan golden snapshot

`test-suite/quality/rule_quality_harness.py` + `test-suite/goldens/rule_coverage.json` (4484 baris):

- Track `buggy_cases_with_required_substrings`, `clean_cases_with_forbidden_substrings`, `strict_zero_clean_cases`
- Detect `weak_cases` (test case yang tidak strict — clean tapi tidak zero findings, atau missing substring)
- 3 scope: `all` (282 case), `campaign` (179 case), `smoke` (22 case)
- Regression: jika rule berubah dan coverage turun, golden snapshot fail

### 2.16 Distribution channels (5 channel)

| Channel | Command |
|---|---|
| Homebrew (macOS/Linux) | `brew install dicklesworthstone/tap/ubs` |
| Scoop (Windows) | `scoop bucket add dicklesworthstone https://github.com/Dicklesworthstone/scoop-bucket && scoop install dicklesworthstone/ubs` |
| Nix flake | `nix run github:Dicklesworthstone/ultimate_bug_scanner` atau `nix develop` |
| Docker/OCI | `docker run --rm ghcr.io/dicklesworthstone/ubs-tools ubs --help` |
| curl install | `curl -fsSL https://raw.githubusercontent.com/.../install.sh \| bash` |

### 2.17 Release signing (defense in depth)

| Layer | Tool | Scope |
|---|---|---|
| Installer + SHA256SUMS | minisign | `SHA256SUMS` signed dengan minisign private key (offline), verify dengan `UBS_MINISIGN_PUBKEY` |
| OCI image | Cosign keyless (OIDC) | Sign by digest (bukan tag), Rekor transparency log, SBOM + SLSA provenance attestation |
| Module/helper | SHA-256 embedded di `ubs` meta-runner | Verified before execution, fail closed |
| Auto-update | opt-in `UBS_ENABLE_AUTO_UPDATE=1` | `UBS_NO_AUTO_UPDATE=1` force-disable |

### 2.18 Module lazy download + checksum

```bash
declare -A MODULE_CHECKSUMS=(
  [cpp]='f054b77189ac66e81fa5c918d4605430272ccb67d9c875f126673182fda85805'
  [python]='e61c1b4885519572f8aead605fe7be5df066a5160edbbb42b6e1a3bf75f94fde'
  # ... 10 modules
)
declare -A HELPER_CHECKSUMS=(
  ['helpers/resource_lifecycle_py.py']='1e884ff42c988fa6a19f9b8f8375bde2334ebcde61735bc4f10b7dc3c900483e'
  # ... 13 helpers
)
```

Module di-download dari `https://raw.githubusercontent.com/Dicklesworthstone/ultimate_bug_scanner/v${UBS_VERSION}/modules/ubs-%s.sh` saat first use, cached di `${XDG_DATA_HOME:-$HOME/.local/share}/ubs/modules`. Invalid checksum → fail closed, tidak eksekusi.

### 2.19 Pre-commit hook (auto checksum update)

`.githooks/pre-commit` block commit jika `SHA256SUMS` stale. Developer modify module → hook auto-update checksums → commit passes. Memastikan setiap release punya verified checksum tanpa intervensi manual.

### 2.20 Nix flake (reproducible builds)

`flake.nix`:
- `packages.default` — install `ubs` ke `$out/bin/ubs`
- `devShells.default` — `bashInteractive`, `shellcheck`, `git`, `cmake`, `python3`, `jq`, `ripgrep`, `uv`
- `nixosModules.ubs` — NixOS module dengan `programs.ubs.enable`
- `nix flake check` jalan di CI untuk determinism

### 2.21 Auto-provisioning ast-grep

UBS auto-download ast-grep binary per-platform (SHA-256 verified):

| Platform | Binary |
|---|---|
| macOS ARM64 | `ast-grep-aarch64-apple-darwin` |
| macOS Intel | `ast-grep-x86_64-apple-darwin` |
| Linux ARM64 | `ast-grep-aarch64-unknown-linux-gnu` |
| Linux x64 | `ast-grep-x86_64-unknown-linux-gnu` |
| Windows x64 | `ast-grep-x86_64-pc-windows-msvc.exe` |

Cached di `$TOOLS_DIR/ast-grep/<version>/<platform>/`. Fallback ke regex detection jika download gagal (graceful degradation).

### 2.22 MCP Agent Mail integration

UBS disebut terintegrasi dengan `mcp_agent_mail` (project sibling):
- Agent tulis code → trigger UBS via MCP tool call
- QA agent run UBS, post findings ke thread
- Multi-agent coordination dengan file reservation (lease)

### 2.23 Beads JSONL integration

`--beads-jsonl=findings.jsonl` emit JSONL untuk issue tracker Beads:
```jsonl
{"type":"finding","severity":"critical","category":1,"file":"src/app.js","line":42,"message":"Null pointer access"}
{"type":"summary","totals":{"critical":1,"warning":1,"info":0},"timestamp":"2025-01-05T12:00:00Z"}
```

Pipe langsung: `ubs . --beads-jsonl=/dev/stdout | bd import --from-jsonl`

### 2.24 Comparison/baseline delta scan

```bash
# Capture baseline
ubs --ci --report-json .ubs/baseline.json .

# Compare
ubs --ci --comparison .ubs/baseline.json --report-json .ubs/latest.json --html-report .ubs/latest.html .
```

Output `latest.json` berisi `comparison.delta` block: `{critical: +2, warning: -1, info: 0}` (delta vs baseline). HTML report render trend. SARIF `automationDetails` keyed by comparison id untuk grouping CI runs.

### 2.25 Git metadata enrichment (GitHub permalinks)

Saat run di git repo dengan GitHub remote:
- Text output annotate `path:line` dengan permalink `https://github.com/<org>/<repo>/blob/<sha>/<path>#L<line>`
- JSON output dapat `git.repository`, `git.commit`, `git.blob_base`
- SARIF `versionControlProvenance` + `automationDetails`

---

## 3. Gap Analysis — CodeLens vs UBS

Skala: 🔴 (CodeLens tidak punya, UBS punya matang) · 🟡 (CodeLens punya sebagian/lo-fi) · 🟢 (CodeLens sudah setara atau lebih baik)

| # | Kapabilitas | CodeLens | UBS | Gap severity |
|---|---|---|---|---|
| 1 | **ast-grep rule engine** (pattern matching AST dengan metavariable) | 🔴 tree-sitter ad-hoc, tidak ada rule YAML pattern | 🟢 full ast-grep integration, `--rules=DIR` | 🔴 high |
| 2 | **Ancestor-aware matching** (`stopBy: end`) | 🔴 tidak ada | 🟢 19+ rule pakai teknik ini | 🟡 medium |
| 3 | **Inline suppression** (`# ubs:ignore`) | 🔴 tidak ada | 🟢 cross-10-bahasa | 🔴 high |
| 4 | **`.ubsignore` file** (gitignore-style) | 🔴 hanya `DEFAULT_IGNORE_DIRS` hardcoded | 🟢 full gitignore parser + `--suggest-ignore` | 🔴 high |
| 5 | **`doctor` command** (env audit) | 🔴 tidak ada | 🟢 `ubs doctor --fix` (curl/wget, ast-grep, ripgrep, jq, typos, Node, tsserver, checksum verify) | 🔴 high |
| 6 | **`sessions` command** (install log) | 🔴 tidak ada | 🟢 `ubs sessions --entries=N` (timestamp, agent detected, integration configured) | 🟡 medium |
| 7 | **HTML report** standalone | 🔴 tidak ada | 🟢 `--html-report=file.html` dengan trend dashboard | 🔴 high |
| 8 | **TOON format** (token-optimized) | 🟡 `--format ai` normalized, tapi bukan TOON compression | 🟢 ~50% lebih kecil dari JSON | 🟡 medium |
| 9 | **Comparison/baseline delta** | 🟡 `diff` command compare registry snapshot, bukan delta finding | 🟢 `--comparison baseline.json` → delta block + HTML trend | 🟡 medium |
| 10 | **`--profile=strict\|loose`** preset | 🔴 tidak ada | 🟢 2 preset | 🟡 medium |
| 11 | **`--category=<name>`** filter | 🔴 tidak ada (CodeLens pakai command terpisah per concern) | 🟢 narrows language set + suppress unrelated | 🟡 medium |
| 12 | **10 agent integrations** auto-detect | 🟡 MCP server (untuk AI agent), tapi tidak auto-wire ke Claude Code/Cursor/Codex/Gemini/Windsurf/Cline/OpenCode/Aider/Continue/Copilot | 🟢 12+ agent auto-detect + rules file/hook injection | 🔴 high |
| 13 | **Git safety guard** (block destructive git) | 🔴 tidak ada | 🟢 `.claude/hooks/git_safety_guard.py` intercept `git reset --hard`, `rm -rf`, dll | 🔴 high |
| 14 | **ast-grep auto-provisioning** (download binary per-platform, SHA-256 verified) | 🔴 CodeLens pakai tree-sitter Python binding via setup.sh | 🟢 5 platform binary auto-download | 🟡 medium |
| 15 | **Release signing** (minisign + Cosign) | 🔴 tidak ada | 🟢 minisign untuk installer + Cosign keyless untuk OCI | 🔴 high |
| 16 | **Module/helper SHA-256 verification** | 🔴 CodeLens bundle semua di repo, tidak ada lazy download | 🟢 embedded checksum, fail closed | 🟡 medium |
| 17 | **Homebrew tap distribution** | 🔴 tidak ada | 🟢 `brew install dicklesworthstone/tap/ubs` | 🔴 high |
| 18 | **Scoop distribution** (Windows) | 🔴 tidak ada | 🟢 scoop bucket | 🟡 medium |
| 19 | **Nix flake** (reproducible builds) | 🔴 tidak ada | 🟢 packages.default + devShells.default + nixosModules | 🟡 medium |
| 20 | **Docker/OCI image** | 🔴 tidak ada | 🟢 `ghcr.io/dicklesworthstone/ubs-tools` | 🟡 medium |
| 21 | **Manifest-driven test** (substring + exit + totals assertion) | 🟡 `benchmarks/` punya fixture + ground_truth.yaml, tapi tidak se-expresif UBS manifest | 🟢 402 case dengan require/forbid_substrings + stderr check | 🔴 high |
| 22 | **Rule quality harness** (golden snapshot regression) | 🔴 tidak ada | 🟢 `rule_quality_harness.py` + `goldens/rule_coverage.json` track weak cases | 🔴 high |
| 23 | **Cross-language async error detection** (10 bahasa konsisten) | 🟡 `ast_taint_engine.py` hanya Python/JS/TS/Rust | 🟢 10 bahasa dengan pattern setara | 🟡 medium |
| 24 | **Resource lifecycle correlation** (acquire/release pair matching) | 🟡 `deadcode_engine.py` detect unused, bukan acquire/release mismatch | 🟢 AST walker untuk file/socket/Popen/asyncio/ExecutorService/CancellationTokenSource/malloc-free | 🔴 high |
| 25 | **Type narrowing helpers** (Rust/Kotlin/Swift/C#/TS khusus) | 🟡 `typeinfer_engine.py` generik, bukan type narrowing specific | 🟢 5 helper per-bahasa, AST-based | 🟡 medium |
| 26 | **`--staged` / `--diff`** git-aware scan | 🔴 tidak ada (CodeLens `scan --incremental` beda konsep — mtime-based, bukan git) | 🟢 native git integration | 🔴 high |
| 27 | **`--only=LANG`** language filter | 🔴 tidak ada (CodeLens scan semua bahasa sekaligus) | 🟢 skip irrelevant scanner | 🟡 medium |
| 28 | **`--skip=CSV`** + `--skip-LANG=N`** per-category skip | 🔴 tidak ada | 🟢 global + per-language skip | 🟡 medium |
| 29 | **`--jobs=N`** parallelism control | 🔴 single-threaded scan | 🟢 ripgrep parallel + auto-detect cores | 🔴 high (perf) |
| 30 | **`--max-file-size`** | 🟡 `MAX_FILE_SIZE` global di `secrets_engine.py`, tidak configurable | 🟢 `--max-file-size=25M` | 🟡 medium |
| 31 | **`--max-detailed N`** cap code samples | 🟡 `--top N` mirip, tapi untuk list items, bukan code samples | 🟢 cap detail per finding | 🟡 low |
| 32 | **`--timeout-seconds N`** global tool timeout | 🟡 `PER_FILE_REGEX_TIMEOUT = 5s` hardcoded di secrets | 🟢 configurable global | 🟡 medium |
| 33 | **`--list-categories`** command | 🔴 tidak ada (CodeLens list via `--help`) | 🟢 print category index per module | 🟡 low |
| 34 | **Severity normalization** (cross-language) | 🟡 CodeLens severity di rule YAML (critical/high/medium/low/info), tapi tidak normalize dari external tool output | 🟢 ESLint error→critical, Pylint E/F→critical, Clippy deny→critical, dll | 🟡 medium |
| 35 | **`--ci` mode** (stable UTC ISO-8601, no color) | 🟡 CodeLens CI via env var `CI=true`, tapi tidak ada `--ci` flag explicit | 🟢 explicit flag | 🟡 low |
| 36 | **`--update-modules`** force re-download | 🔴 N/A (CodeLens tidak ada lazy module) | 🟢 force refresh | 🟡 low |
| 37 | **`--no-auto-update`** flag | 🔴 N/A | 🟢 disable auto-update check | 🟡 low |
| 38 | **uv-powered analyzers** (ruff, bandit, pip-audit, mypy, safety, detect-secrets via uvx) | 🔴 tidak ada (CodeLens punya engines sendiri) | 🟢 auto-invoke via `uvx` jika tersedia | 🟡 medium |
| 39 | **Notebook hygiene** (`.ipynb` checks) | 🔴 tidak ada | 🟡 Python module Category 23 | 🟡 low |
| 40 | **Py3.13 migration checks** | 🔴 tidak ada | 🟡 Python module Category 21 | 🟡 low |
| 41 | **`--beads-jsonl`** integration | 🔴 tidak ada (CodeLens JSONL belum ada) | 🟢 JSONL untuk Beads issue tracker | 🟡 medium |
| 42 | **Pre-commit hook auto checksum update** | 🔴 CodeLens pre-commit hook static, tidak auto-update | 🟢 `.githooks/pre-commit` block stale checksum | 🟡 low |
| 43 | **`install.sh --easy-mode`** (zero-interaction install) | 🔴 CodeLens `setup.sh` interactive | 🟢 auto-install deps + accept prompts + wire agent guardrails | 🔴 high (UX) |
| 44 | **`install.sh --dry-run`** | 🔴 tidak ada | 🟢 preview semua install action tanpa touch disk | 🟡 medium |
| 45 | **`install.sh --self-test`** | 🔴 tidak ada | 🟢 run smoke test post-install, exit non-zero jika fail | 🟡 medium |
| 46 | **`install.sh --uninstall`** | 🔴 tidak ada | 🟢 clean uninstall (binary + RC + config + hooks) | 🟡 medium |
| 47 | **Installer session logging** | 🔴 tidak ada | 🟢 `~/.config/ubs/session.md` dengan timestamp, agent, integration | 🟡 medium |
| 48 | **Codex CLI v0.77.0+ format migration** | 🔴 N/A | 🟢 auto-detect file vs directory format | 🟡 low |
| 49 | **Aider lint-cmd config** | 🔴 N/A | 🟢 auto-add `lint-cmd: "ubs --fail-on-warning ."` ke `~/.aider.conf.yml` | 🟡 low |
| 50 | **Continue.dev rules** | 🔴 N/A | 🟢 `.continue/` directory rules | 🟡 low |
| 51 | **GitHub Copilot workspace settings** | 🔴 N/A | 🟢 VS Code extension settings | 🟡 low |
| 52 | **MCP server (49 tools, JSON-RPC)** | 🟢 native | 🔴 tidak ada | 🟢 **CodeLens unggul** |
| 53 | **AI-optimized output** (`--format ai`, `--lite`, `--top N`, `--max-tokens N`) | 🟢 native | 🔴 hanya TOON | 🟢 **CodeLens unggul** |
| 54 | **Guard pre/post-write hook** | 🟢 native (`guard pre`, `guard post`, `guard snapshot`, `guard verify`) | 🔴 tidak ada | 🟢 **CodeLens unggul** |
| 55 | **Auto-setup zero-config** | 🟢 auto `init` + `scan` jika registry belum ada | 🟡 `--config auto` tapi tidak auto-bootstrap | 🟢 **CodeLens unggul** |
| 56 | **Workspace auto-detect** | 🟢 walk-up parent + last workspace cache | 🟡 default current dir | 🟢 **CodeLens unggul** |
| 57 | **Code intelligence** (call graph, impact, refactor-safe, trace, dependents) | 🟢 5 engine khusus | 🔴 tidak ada (UBS hanya bug scan) | 🟢 **CodeLens unggul** |
| 58 | **Frontend analysis** (CSS deep, a11y, Tailwind, Vue/Svelte) | 🟢 native | 🔴 tidak ada | 🟢 **CodeLens unggul** |
| 59 | **Plugin system** (4 tipe: rule_pack/engine/formatter/command) | 🟢 4 tipe + 3-tier discovery | 🔴 hanya `--rules=DIR` (ast-grep rule pack) | 🟢 **CodeLens unggul** |
| 60 | **Live CVE/OSV scanning** (9 ecosystem, SQLite cache) | 🟢 native | 🔴 tidak ada (UBS fokus code-level bug, bukan dependency) | 🟢 **CodeLens unggul** |

### Ringkasan gap count

- 🔴 critical/high gap: **18 item** (sebagian besar di agent integration, distribution, test harness, ast-grep rule engine)
- 🟡 medium gap: **26 item**
- 🟢 CodeLens unggul: **9 item** (MCP, AI output, guard, auto-setup, workspace detect, code intelligence, frontend, plugin, CVE)

UBS menang di: **DX, distribution, test infrastructure, agent integration, supply-chain security**.
CodeLens menang di: **AI-native intelligence, MCP, code analysis depth, CVE scanning, plugin ecosystem**.

---

## 4. Peningkatan yang SUDAH Di-adjust untuk CodeLens

Berikut fitur UBS yang **secara konseptual sudah ada di CodeLens** dengan pendekatan berbeda, atau sudah disesuaikan dengan niche CodeLens:

### 4.1 ✅ Multi-format output — sudah ada (parsial)
- **CodeLens:** 2 format (markdown, sarif v2.1.0) + `--format ai` normalized + `--lite` minimal
- **UBS:** 6 format (text, json, jsonl, sarif, html, toon)
- **Sudah adjusted:** CodeLens punya AI-optimized output yang UBS tidak punya. Yang perlu diserap: HTML report, JSONL, TOON, text (plain).

### 4.2 ✅ Pre-commit hook — sudah ada
- **CodeLens:** `scripts/pre_commit_hook.py` (131 LOC, config `.codelens/pre-commit.yaml` dengan severity/max_findings/commands/auto_fix)
- **UBS:** `.git/hooks/pre-commit` shell script (block commit jika critical finding)
- **Sudah adjusted:** CodeLens lebih configurable. Yang perlu diserap: auto-update checksum pattern (untuk plugin/rule integrity).

### 4.3 ✅ GitHub Actions workflows — sudah ada (4 workflow)
- **CodeLens:** `codelens-ci.yml`, `codelens-quality-gate.yml`, `codelens-sarif.yml`, `codelens-benchmark.yml`
- **UBS:** tidak ship workflow (user pakai `ubs . --ci --fail-on-warning` di step)
- **Sudah adjusted:** CodeLens ship workflow siap pakai. Yang perlu ditambah: `install-ci` command yang generate workflow otomatis.

### 4.4 ✅ Inline suppression via rule YAML — sudah ada (parsial, berbeda konsep)
- **CodeLens:** Plugin rule_pack bisa di-skip via config (`.codelens/codelens.config.json` ignore list)
- **UBS:** `# ubs:ignore` inline comment, same-line
- **Sudah adjusted:** CodeLens belum punya inline suppression per-finding — ini yang perlu diserap (Issue #3 di dokumen opengrep, Issue #2 di dokumen ini).

### 4.5 ✅ Test/benchmark fixture — sudah ada (beda pendekatan)
- **CodeLens:** `benchmarks/fixtures/{clean_app,vulnerable_app}/` + `ground_truth.yaml` + `run_benchmarks.py`
- **UBS:** `test-suite/manifest.json` 402 case + `run_manifest.py` + `rule_quality_harness.py` + `goldens/`
- **Sudah adjusted:** CodeLens punya benchmark untuk akurasi engine. Yang perlu diserap: manifest schema (substring/forbid/totals assertion) + golden snapshot regression untuk rule coverage.

### 4.6 ✅ Plugin rule YAML — sudah ada, lebih kaya dari UBS `--rules=DIR`
- **CodeLens:** Plugin 4 tipe (`rule_pack`, `engine`, `formatter`, `command`), 3-tier discovery, 89 rule builtin (OWASP 36 + HIPAA 26 + PCI-DSS 27)
- **UBS:** Hanya ast-grep rule pack via `--rules=DIR`
- **Sudah adjusted:** CodeLens lebih fleksibel. Yang perlu diserap: ast-grep format support (kompatibel dengan rule ekosystem ast-grep/Semgrep).

### 4.7 ✅ MCP server — CodeLens unggul
- **CodeLens:** 49 tool, MCP 2025-03-26, stdio + HTTP/SSE
- **UBS:** Tidak ada MCP server (UBS fokus CLI + agent rules file injection)
- **Sudah adjusted:** differentiator utama. Tidak perlu serap.

### 4.8 ✅ AI-optimized output (`--format ai`, `--lite`, `--top N`, `--max-tokens N`) — CodeLens unggul
- **CodeLens:** Normalized schema `{stats, items[], truncated, recommendations}`, per-command lite mode, smart sort
- **UBS:** TOON (token compression, tapi bukan semantic normalization)
- **Sudah adjusted:** CodeLens lebih sophisticated untuk AI consumption. Yang perlu diserap: TOON sebagai format tambahan (opsional, untuk LLM dengan context window sangat ketat).

### 4.9 ✅ Guard pre/post-write hook — CodeLens unggul (killer feature)
- **CodeLens:** `guard pre --file X --symbol Y --action create`, `guard post --file X --diff ...`, `guard snapshot`, `guard verify`
- **UBS:** Tidak ada equivalent (UBS hanya `ubs --fail-on-warning .` di Claude Code file-write hook)
- **Sudah adjusted:** differentiator. Tidak perlu serap. Yang bisa di-adjust: integrasikan git safety guard UBS ke `guard pre` command CodeLens.

### 4.10 ✅ Auto-setup zero-config — CodeLens unggul
- **CodeLens:** Auto `init` + `scan` jika registry belum ada, dengan `--max-files 3000` cap
- **UBS:** `install.sh --easy-mode` (auto-install deps, tapi tidak auto-bootstrap scan)
- **Sudah adjusted:** CodeLens lebih smart. Yang bisa diserap: `--easy-mode` installer flag untuk auto-wire agent guardrails.

### 4.11 ✅ Workspace auto-detect — CodeLens unggul
- **CodeLens:** Walk-up 10 level parent + last workspace cache (`~/.codelens/.codelens_last_workspace`)
- **UBS:** Default current directory
- **Sudah adjusted:** differentiator. Tidak perlu serap.

### 4.12 ✅ Code intelligence (call graph, impact, refactor-safe, trace, dependents) — CodeLens unggul
- **CodeLens:** `callgraph_engine.py` (3540 LOC), `impact_engine.py`, `refactor_safe_engine.py`, `trace_engine.py` (bidirectional, depth-controlled), `dependents_engine.py`
- **UBS:** Tidak ada (UBS bukan code intelligence tool, hanya bug scanner)
- **Sudah adjusted:** differentiator. Tidak perlu serap.

### 4.13 ✅ Frontend analysis (CSS deep, a11y, Tailwind, Vue/Svelte) — CodeLens unggul
- **CodeLens:** `cssdeep_engine.py`, `a11y_engine.py` (WCAG 2.1), `tailwind_detector.py`, Vue/Svelte parser
- **UBS:** Tidak ada (UBS bukan frontend analysis tool)
- **Sudah adjusted:** differentiator. Tidak perlu serap.

### 4.14 ✅ Live CVE/OSV scanning — CodeLens unggul
- **CodeLens:** `osv_client.py` (1616 LOC) + SQLite cache + 9 ecosystem + native audit fallback (`npm audit`, `cargo audit`, `pip audit`, `govulncheck`)
- **UBS:** Tidak ada (UBS fokus code-level bug, bukan dependency CVE)
- **Sudah adjusted:** differentiator. Tidak perlu serap.

### 4.15 ✅ Plugin system (4 tipe) — CodeLens unggul
- **CodeLens:** 4 tipe (`rule_pack`, `engine`, `formatter`, `command`), 3-tier discovery (local/user/builtin)
- **UBS:** Hanya `--rules=DIR` (ast-grep rule pack, no plugin engine/formatter/command)
- **Sudah adjusted:** CodeLens lebih fleksibel. Yang bisa diserap: ast-grep rule format support sebagai tipe baru di rule_pack (kompatibel dengan ekosistem ast-grep).

### 4.16 ✅ Security rule pack (OWASP + Compliance) — sudah ada
- **CodeLens:** 36 OWASP rule + 53 compliance rule (HIPAA + PCI-DSS)
- **UBS:** Rule pack per-bahasa (tidak ada OWASP/compliance curated pack)
- **Sudah adjusted:** CodeLens lebih kurated. Yang perlu diserap: cross-language async error detection pattern (10 bahasa konsisten).

---

## 5. Issue Template — Serap Fitur UBS ke CodeLens

Setiap issue di bawah sudah diformat siap copy-paste ke GitHub issue tracker `Wolfvin/CodeLens`. Urutan berdasarkan prioritas (P0 = critical, P1 = high, P2 = medium, P3 = low).

### 📋 Issue #1 [P0] — Inline Suppression (`# codelens-ignore`)

```markdown
**Title:** [P0] Inline suppression annotation (`# codelens-ignore`)

## Motivation
CodeLens tidak punya cara untuk suppress finding secara inline. User harus edit `.codelens/config.json` ignore list atau disable rule sepenuhnya. Tanpa fitur ini, false positive noise di codebase besar menjadi masalah adopsi.

UBS punya `# ubs:ignore` yang sangat populer dan bekerja cross-10-bahasa:

```python
eval(user_input)  # ubs:ignore
exec(validated_code)  # ubs:ignore -- admin-only trusted input
# ubs:ignore-next-line
dangerousOperation();
```

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `ubs` meta-runner (`count_lines()` helper yang strip `ubs:ignore` sebelum count)
  - `modules/ubs-python.sh` (Category filtering, grep -v 'ubs:ignore')
  - CHANGELOG v5.3.0: `#51 — ubs:ignore now respected by every count pipeline` (21 bypass pattern fixed across 6 modules)
  - CHANGELOG v5.3.1: follow-up 3 additional pipelines
  - CHANGELOG v5.3.2: 2 more source-scanning count pipelines (golang, swift)
  - README "Inline Suppression Comments" section

## Acceptance Criteria
- [ ] Default keyword: `codelens-ignore` (brandable, lebih panjang dari `nosem`)
- [ ] Syntax same-line: `<code>  // codelens-ignore: rule-id-1, rule-id-2` (suppress specific rule)
- [ ] Syntax same-line blanket: `<code>  // codelens-ignore` (suppress semua rule di baris ini)
- [ ] Syntax with reason: `<code>  // codelens-ignore -- reason text` (recommended)
- [ ] Syntax next-line: `// codelens-ignore-next-line` di baris sebelum finding
- [ ] Cross-language: Python (`#`), JS/TS/C/C++/Java/Rust/Go/Swift (`//`), Ruby (`#`), HTML (`<!-- -->`), CSS (`/* */`)
- [ ] **Tidak support block comment** (hanya line comment, untuk avoid scope ambiguity)
- [ ] Finding yang di-suppress tetap di-report dengan `status: suppressed` (audit-able, bukan dihilangkan)
- [ ] SARIF output: gunakan `suppressions` field per SARIF spec v2.1.0
- [ ] `--codelens-ignore-pattern <regex>` flag — custom keyword (mis. untuk kompatibilitas dengan `nosemgrep` atau `ubs:ignore`)
- [ ] Test: 30+ case untuk berbagai syntax + edge case (comment di string literal, nested comment, multi-rule suppress)
- [ ] **Critical:** pastikan suppression dihormati oleh SEMUA count pipeline (pelajari UBS #51 bug — 21 bypass pattern yang missed oleh v5.3.0)

## Implementation Notes
- Detect comment per-bahasa di parser layer (sudah ada tree-sitter comment node)
- Cek pattern `codelens-ignore(:\s*([\w-, ]+))?(\s*--\s*.*)?$` di comment text
- Simpan suppression info di registry finding (`finding.suppressed = true`, `finding.suppressed_rules = [ids]`, `finding.suppressed_reason = "..."`)
- Filter di output layer, jangan filter di engine (suppressed finding tetap di-registry untuk audit)
- Untuk fallback regex parser: scan baris yang sama dengan finding line + 1 baris sebelumnya (untuk `ignore-next-line`)
- **Penting:** audit semua count pipeline (analog UBS #51 sweep) — pastikan `grep -c` / `wc -l` tidak bypass suppression

## Priority
P0 — quick win, high UX impact, blocker untuk production adoption di codebase besar.
```

---

### 📋 Issue #2 [P0] — `.codelensignore` File (gitignore-style)

```markdown
**Title:** [P0] `.codelensignore` file (gitignore-style untuk scan target)

## Motivation
CodeLens saat ini hardcode `DEFAULT_IGNORE_DIRS` di `utils.py` (dist/, build/, vendor/, node_modules/, .git/, dll). User tidak bisa customize tanpa edit source atau set config per-workspace.

UBS punya `.ubsignore` file (gitignore syntax) yang:
- Auto-load dari `PROJECT/.ubsignore`
- Support: `**` recursive, `*` wildcard, `!` negation, comment dengan `#`
- 3-tier: workspace `.ubsignore` (highest) → user `~/.ubsignore` → builtin default
- `--ignore-file=<path>` flag untuk custom filename
- `--suggest-ignore` flag untuk print kandidat direktori besar yang perlu di-ignore

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `ubs` meta-runner (`load_ignore_patterns()` function — Python parser via `python3 - <<'PY'`)
  - README "Ignoring Paths with `.ubsignore`" section
  - `.ubsignore` default file di repo root

## Current State
- CodeLens: `DEFAULT_IGNORE_DIRS` hardcoded di `utils.py`
- CodeLens: `.codelens/codelens.config.json` ignore list (per-workspace, tapi bukan gitignore syntax)

## Acceptance Criteria
- [ ] File `.codelensignore` di workspace root — gitignore syntax (pathspec library)
- [ ] Support: `**` recursive, `*` wildcard, `?` single char, `!` negation, `#` comment, blank line
- [ ] 3-tier: workspace `.codelensignore` (highest) → user `~/.codelensignore` → builtin default `scripts/data/default-codelensignore`
- [ ] `--codelensignore-filename <name>` flag — custom filename (mis. `.codelensignore.prod`)
- [ ] `--ignore-file <path>` flag — explicit path (override auto-discovery)
- [ ] `--suggest-ignore` flag — print top 10 direktori terbesar yang mungkin perlu di-ignore (no changes applied, just suggest)
- [ ] Builtin default: ship `scripts/data/default-codelensignore` dengan pattern umum:
  ```
  # Default CodeLens ignore
  node_modules/
  .git/
  .hg/
  .svn/
  dist/
  build/
  target/
  out/
  bin/
  vendor/
  third_party/
  .venv/
  venv/
  __pycache__/
  .mypy_cache/
  .pytest_cache/
  .ruff_cache/
  *.min.js
  *.min.css
  *.map
  *.bundle.js
  .next/
  .nuxt/
  .turbo/
  .expo/
  coverage/
  .coverage
  ```
- [ ] Log: report file yang di-ignore di scan summary (`"ignored_files": 234, "ignored_patterns_loaded": "workspace+user+default"`)
- [ ] Integrasi dengan semua command yang scan file (bukan hanya `scan`, juga `secrets`, `smell`, `complexity`, dll)

## Implementation Notes
- Gunakan `pathspec` PyPI package (gitignore spec compliant, lebih robust dari fnmatch manual) — `pip install pathspec`
- Atau port Python parser dari UBS `load_ignore_patterns()` (lebih simple, tidak butuh dependency)
- Cache compiled pattern per scan session (invalidate saat `.codelensignore` mtime change)
- `--suggest-ignore`: walk top-level dirs, hitung total size, print yang >50MB

## Priority
P0 — quick win, high configurability impact.
```

---

### 📋 Issue #3 [P1] — `doctor` Command (Environment Audit)

```markdown
**Title:** [P1] `codelens doctor` command — environment audit + auto-repair

## Motivation
CodeLens butuh Python 3.8+, tree-sitter, multiple grammar packages, watchdog (opsional), git (opsional). Saat install gagal atau scan error, user tidak punya cara cepat untuk diagnose masalah.

UBS punya `ubs doctor` yang:
- Audit curl/wget, ast-grep, ripgrep, jq, typos, Node.js, tsserver availability
- Verify module/helper checksum integrity
- Check writable cache directory
- `--fix` flag: auto-redownload missing/corrupted modules, install missing dependencies via brew/cargo/npm
- Print human-readable report: `✓ curl available (curl 8.4.0)`, `✗ ast-grep not found`

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `ubs` meta-runner (`doctor` subcommand, ~200 LOC)
  - README "Maintenance Commands" section
  - `install.sh` post-install doctor run

## Current State
- CodeLens: tidak ada equivalent. User harus manual cek `python3 -c "import tree_sitter"`, `pip list | grep tree-sitter`, dll.

## Acceptance Criteria
- [ ] Command baru: `codelens doctor` — audit environment
- [ ] Checks:
  - Python version (3.8+ required, recommend 3.11+)
  - tree-sitter package (`pip show tree-sitter`)
  - tree-sitter grammar packages (`tree-sitter-python`, `tree-sitter-javascript`, `tree-sitter-typescript`, `tree-sitter-rust`, `tree-sitter-html`, `tree-sitter-css` — 6 minimum)
  - PyYAML (`pip show pyyaml`)
  - watchdog (`pip show watchdog` — optional, for `watch` command)
  - git binary (`git --version` — optional, for `ownership` command)
  - SQLite (`python3 -c "import sqlite3"` — for `migrate` command)
  - urllib (`python3 -c "import urllib.request"` — for `vuln-scan` OSV API)
  - Writable `.codelens/` directory in workspace
  - Writable `~/.codelens/` cache directory
  - CodeLens version + latest available (check GitHub Releases API)
- [ ] `--fix` flag: auto-install missing dependencies via `pip install --user tree-sitter tree-sitter-python ...`
- [ ] `--verbose` flag: print full path setiap tool (bukan hanya version)
- [ ] Output: human-readable dengan ✓/✗ symbols + color (respect `--no-color` dan `NO_COLOR` env)
- [ ] JSON output via `--format=json` untuk CI parsing
- [ ] Exit code: 0 jika semua OK, 1 jika ada warning, 2 jika ada critical missing
- [ ] Integrasi dengan `setup.sh`: jalankan `doctor` di akhir setup, report status

## Implementation Notes
- Implementasi di `scripts/commands/doctor.py` (register ke command registry)
- Reuse `utils.py` `safe_import()` pattern untuk graceful import check
- Untuk `--fix`: pakai `subprocess.run([sys.executable, "-m", "pip", "install", "--user", ...])`, capture output, report success/failure per package
- Color: gunakan `utils.py` existing color helpers (jika ada) atau `colorama` (sudah common dependency)

## Priority
P1 — critical untuk onboarding UX, reduce support burden.
```

---

### 📋 Issue #4 [P1] — 12+ Agent Integrations Auto-Detect

```markdown
**Title:** [P1] Auto-detect 12+ coding agents and wire guardrails during install

## Motivation
CodeLens punya MCP server (49 tools) untuk AI agent, tapi user harus manual configure Claude Desktop / VS Code Copilot via `mcp_config.json`. Tidak ada auto-wire ke agent lain (Cursor, Codex, Gemini, Windsurf, Cline, OpenCode, Aider, Continue, Copilot, TabNine, Replit).

UBS `install.sh` auto-detect 12+ agent dan inject rules file/hook tanpa interaksi:

| Agent | Detection | Integration |
|---|---|---|
| Claude Code | `.claude/` dir | Hooks + rules (`.claude/hooks/on-file-write.sh`) |
| Cursor | `.cursor/` dir | Rules file (`.cursor/rules`) |
| Codex CLI | `.codex/` dir | Rules file/dir (support v0.77.0+ format migration) |
| Gemini Code Assist | `.gemini/` dir | Rules file |
| Windsurf | `.windsurf/` dir | Rules + command palette snippet |
| Cline | `.cline/` dir | Markdown instructions |
| OpenCode MCP | `.opencode/` dir | Local MCP instructions |
| Aider | `.aider.conf.yml` | Lint command config (`lint-cmd`, `auto-lint: true`) |
| Continue | `.continue/` dir | Rules file |
| GitHub Copilot | VS Code extensions | Workspace settings |
| TabNine | `.tabnine/` dir | Configuration |
| Replit | `replit.com` detection | Environment setup |

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `install.sh` (`detect_agents()` function, `append_quick_reference_block()`, `wire_agent_guardrails()`)
  - README "Extended Agent Detection" section
  - README "AI Agent Integration (The Real Magic)" section
  - Codex CLI v0.77.0+ migration note (file → directory format)

## Current State
- CodeLens: `mcp_config.json` untuk Claude Desktop / VS Code Copilot (manual)
- CodeLens: `guard` command (pre/post-write hook) — tapi user harus manual wire ke agent

## Acceptance Criteria
- [ ] `setup.sh` (atau `install.sh` baru) auto-detect agent di workstation:
  - Claude Code: cek `~/.claude/` atau `./.claude/`
  - Cursor: cek `~/.cursor/` atau `./.cursor/`
  - Codex CLI: cek `~/.codex/` (support v0.77.0+ format: file vs directory)
  - Gemini: cek `~/.gemini/`
  - Windsurf: cek `~/.windsurf/`
  - Cline: cek `~/.cline/`
  - OpenCode: cek `~/.opencode/`
  - Aider: cek `~/.aider.conf.yml`
  - Continue: cek `~/.continue/`
  - GitHub Copilot: cek VS Code extensions
  - TabNine: cek `~/.tabnine/`
  - Replit: cek `replit.com` env
- [ ] Untuk setiap agent detected, inject:
  - Rules file: `.cursor/rules/codelens.md`, `.codex/rules/codelens.md`, `.gemini/rules/codelens.md`, dll (content: "Before marking task complete, run `codelens query <name>` + `codelens smell` + `codelens secrets`. Fix all critical findings.")
  - Hook (Claude Code only): `.claude/hooks/on-file-write.sh` yang trigger `codelens scan --incremental` + `codelens guard post --file $FILE_PATH`
  - Lint command (Aider): add `lint-cmd: "codelens smell --fail-on-warning"` dan `auto-lint: true` ke `~/.aider.conf.yml`
  - MCP config (jika agent support MCP): inject CodeLens MCP server config ke agent's MCP config file
- [ ] `--easy-mode` flag: auto-wire semua detected agent tanpa prompt
- [ ] `--skip-hooks` flag: skip hook injection (rules file only)
- [ ] Codex CLI v0.77.0+ migration: auto-detect format (file `.codex/rules` vs directory `.codex/rules/`), write ke lokasi yang benar
- [ ] Session log: catat agent yang detected + integration yang configured ke `~/.codelens/session.md` (Issue #5)
- [ ] Idempotent: re-run `setup.sh` tidak duplicate rules file entry (detect existing `codelens` block, replace if outdated)

## Implementation Notes
- Implementasi di `scripts/install.py` (Python, bukan Bash — lebih portable)
- Rules file template: `scripts/templates/agent-rules-{cursor,codex,gemini,windsurf,cline,opencode,aider,continue}.md.tmpl`
- Hook template: `scripts/templates/claude-on-file-write.sh.tmpl`
- Untuk Aider: parse YAML `~/.aider.conf.yml`, tambah/replace `lint-cmd` dan `auto-lint` key
- Untuk Codex: cek `os.path.isfile("~/.codex/rules")` vs `os.path.isdir("~/.codex/rules/")` — handle keduanya

## Priority
P1 — critical untuk agent ecosystem adoption (CodeLens niche-nya AI-native, harus terintegrasi seamless dengan semua agent).
```

---

### 📋 Issue #5 [P1] — Git Safety Guard (Block Destructive Commands from Agents)

```markdown
**Title:** [P1] Git safety guard — block destructive git/rm commands from AI agents

## Motivation
AI coding agent (Claude Code, Cursor, Codex) kadang menjalankan destructive command yang bisa wipe jam-jam kerja: `git reset --hard`, `git clean -fd`, `rm -rf`, `git push --force`, `git branch -D`, `git stash drop/clear`.

UBS ship `.claude/hooks/git_safety_guard.py` yang intercept shell command sebelum eksekusi dan block pattern berbahaya dengan actionable error message (agent bisa self-correct).

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `.claude/hooks/git_safety_guard.py` (Python script, hook ke Claude Code command execution pipeline)
  - README "Safety Guards for AI Coding Agents" section
  - AGENTS.md "Irreversible Git & Filesystem Actions" section (RULE: never run `git reset --hard`, `git clean -fd`, `rm -rf` tanpa explicit user authorization)

## Current State
- CodeLens: tidak ada equivalent. `guard pre`/`guard post` command check code changes, bukan shell command.

## Acceptance Criteria
- [ ] Script `scripts/git_safety_guard.py` — intercept shell command sebelum eksekusi
- [ ] Blocked commands (with safe alternative):
  - `git checkout -- <file>` → saran: `git stash` first
  - `git reset --hard` → saran: `git reset --soft` atau `git stash`
  - `git clean -f` / `git clean -fd` → saran: `git clean -n` (dry-run) first
  - `git push --force` → saran: `git push --force-with-lease`
  - `rm -rf <non-temp>` → saran: explicit temp path required
  - `git branch -D` → saran: `git branch -d` (safe delete)
  - `git stash drop` / `git stash clear` → saran: manual review first
- [ ] Intelligent temp path detection: allow `rm -rf` hanya untuk:
  - `${TMPDIR}/...` (macOS/Linux temp)
  - `/tmp/...` dan `/var/tmp/...`
  - System-defined temporary locations
- [ ] Block `rm -rf` untuk: project directories, home folders, ambiguous paths
- [ ] Actionable error message: jelaskan *why* command blocked + *what to do instead*, agar agent bisa self-correct
  ```
  ❌ BLOCKED: git reset --hard
  Reason: Destroys all uncommitted work permanently.
  Safe alternative: git reset --soft (keeps changes staged) atau git stash (simpan sementara)
  If you really need hard reset, ask user for explicit authorization.
  ```
- [ ] Integrasi dengan Claude Code: install ke `.claude/hooks/git_safety_guard.py` saat `setup.sh` (Issue #4)
- [ ] Integrasi dengan `guard pre` command CodeLens: `codelens guard pre --command "git reset --hard"` → return `{allowed: false, reason: "...", alternative: "..."}`
- [ ] Bypass: env var `CODELENS_SKIP_SAFETY_GUARD=1` untuk user yang explicit trust (not recommended)
- [ ] Audit log: catat semua blocked command ke `~/.codelens/safety-guard.log` dengan timestamp + agent + command
- [ ] Test: 30+ case untuk berbagai destructive pattern + edge case (path traversal, quoted args, env var expansion)

## Implementation Notes
- Parse shell command (gunakan `shlex.split()` untuk robust parsing)
- Pattern matching: regex + path analysis
- Untuk path analysis: resolve relative path ke absolute, cek apakah di temp dir whitelist
- Hook mechanism: Claude Code execute hook script sebelum setiap shell command, pass command via stdin/env var
- Untuk integrasi `guard pre`: extend `guard` command dengan `--command <shell-cmd>` flag

## Priority
P1 — critical untuk AI agent safety, prevent catastrophic data loss.
```

---

### 📋 Issue #6 [P1] — HTML Report Standalone Dashboard

```markdown
**Title:** [P1] Standalone HTML report dashboard (`--html-report=file.html`)

## Motivation
CodeLens output saat ini: JSON, SARIF, markdown, text. Tidak ada format visual yang bisa di-attach ke PR atau share di chat (Slack/Discord/Teams) tanpa rendering tool.

UBS punya `--html-report=file.html` yang generate standalone HTML dashboard:
- Totals (critical/warning/info per language)
- Trend vs baseline (jika `--comparison` di-set)
- Per-language breakdown (chart bar)
- Top findings dengan file:line permalink ke GitHub
- Self-contained: 1 file HTML, no external CSS/JS dependency, bisa di-buka di browser apapun

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `ubs` meta-runner (`generate_html_report()` function, Python via `python3 - <<'PY'`)
  - README "Category Packs & Shareable Reports" section
  - `test-suite/shareable/test_shareable_reports.py` (assert HTML snippet: "UBS Report", "Per-language totals", "Critical")

## Current State
- CodeLens: tidak ada HTML output. `dashboard` command generate HTML visualization tapi terpisah dari scan output.

## Acceptance Criteria
- [ ] Flag `--html-report=<file.html>` di `scan` command (dan command lain yang produce findings)
- [ ] HTML self-contained: 1 file, embed CSS inline (no external stylesheet), embed JS inline (jika perlu chart)
- [ ] Section:
  - Header: project name, timestamp, CodeLens version, scan duration
  - Summary card: total critical/warning/info dengan color-coded badge
  - Trend chart (jika `--comparison` di-set): line chart delta vs baseline
  - Per-language breakdown: bar chart (reuse `benchmarks/fixtures/` data struktur)
  - Per-command breakdown: table (smell=12, secrets=3, vuln-scan=5, dll)
  - Top 20 findings: list dengan file:line permalink, severity badge, message, rule_id
  - Footer: link ke full JSON report, link ke SARIF, generation timestamp
- [ ] GitHub permalink: jika di-run di git repo dengan GitHub remote, annotate `file:line` dengan `https://github.com/<org>/<repo>/blob/<sha>/<path>#L<line>`
- [ ] Responsive: works di mobile (PR preview di GitHub mobile app)
- [ ] Dark mode support: respect `prefers-color-scheme` CSS media query
- [ ] Print-friendly: CSS `@media print` untuk PDF export via browser
- [ ] Test: snapshot test dengan fixture, assert snippet: "CodeLens Report", "Summary", "Findings"

## Implementation Notes
- Gunakan Jinja2 template (`scripts/templates/html_report.j2`)
- Chart: pure CSS bar chart (no JS dependency) atau inline SVG
- Untuk permalink: reuse `git` module (sudah ada di CodeLens untuk `ownership` command)
- HTML escape semua user-controlled content (file path, message) untuk prevent XSS di report

## Priority
P1 — high value untuk PR review workflow + non-technical stakeholder reporting.
```

---

### 📋 Issue #7 [P1] — Comparison/Baseline Delta Scan

```markdown
**Title:** [P1] Comparison/baseline delta scan (`--comparison baseline.json`)

## Motivation
CodeLens `diff` command saat ini compare registry snapshot (structur diff: symbol added/removed/changed). Tapi tidak compare finding delta (mis. "regresi: 3 new critical finding sejak baseline").

UBS punya `--comparison=<baseline.json>` yang:
- Compare current scan totals vs baseline
- Output delta block: `{critical: +2, warning: -1, info: 0}`
- Inject ke JSON output (`comparison.delta` field)
- Inject ke HTML report (trend chart)
- Inject ke SARIF (`automationDetails` keyed by comparison id, untuk grouping CI runs)

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `ubs` meta-runner (`compare_to_baseline()` function)
  - README "Category Packs & Shareable Reports" section
  - `test-suite/shareable/test_shareable_reports.py` (assert `comparison` block + `delta` keys)

## Current State
- CodeLens: `diff` command compare registry snapshot (symbol diff), bukan finding delta
- CodeLens: `history` command show trend data, tapi tidak compare 2 specific run

## Acceptance Criteria
- [ ] Flag `--comparison=<baseline.json>` di `scan` dan command yang produce findings
- [ ] Baseline format: JSON hasil scan sebelumnya (dengan `--report-json=baseline.json`)
- [ ] Delta computation: compare current totals vs baseline totals per severity + per command + per language
- [ ] Output delta block di JSON: `{"comparison": {"baseline_timestamp": "...", "delta": {"critical": +2, "warning": -1, "info": 0, "total": +1}}}`
- [ ] Output delta di HTML report: trend card (↑ critical +2, ↓ warning -1)
- [ ] Output delta di SARIF: `automationDetails.guid` = comparison id (untuk grouping CI runs di GitHub code scanning)
- [ ] New findings only mode: `--new-only` flag — report hanya finding yang TIDAK ada di baseline (suppress pre-existing)
- [ ] Resolved findings: `--show-resolved` flag — report finding yang ada di baseline tapi TIDAK di current (sudah di-fix)
- [ ] Test: fixture dengan baseline + current, verify delta computation

## Implementation Notes
- Finding identity: hash dari `(rule_id, file, line, severity)` — sama dengan UBS approach
- Baseline JSON: extend existing `scan` output dengan `findings[]` array (saat ini hanya summary)
- Untuk `--new-only`: filter finding yang hash-nya tidak ada di baseline `findings[]`
- SARIF `automationDetails`: `{guid: "<comparison-id>", id: "codelens/<workspace>/<timestamp>"}`

## Priority
P1 — critical untuk CI regression detection ("PR ini introduce 3 new critical finding").
```

---

### 📋 Issue #8 [P1] — `--staged` and `--diff` Git-Aware Scan

```markdown
**Title:** [P1] `--staged` and `--diff` git-aware scan (only changed files)

## Motivation
CodeLens `scan --incremental` saat ini mtime-based (rescan file yang mtime change sejak scan terakhir). Tapi:
- Tidak integrate dengan git staging area (file yang akan di-commit)
- Tidak compare vs HEAD (working tree changes)

UBS punya:
- `--staged` — scan hanya file yang staged untuk commit (`git diff --cached --name-only --diff-filter=ACMR`)
- `--diff` / `--git-diff` — scan hanya modified files (working tree vs HEAD, `git diff --name-only`)

Use case:
- Pre-commit hook: scan hanya staged file (fast, <1s vs full scan 30s)
- PR review: scan hanya diff vs main branch
- CI: scan hanya file yang berubah di PR

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `ubs` meta-runner (`--staged` dan `--diff` flag handler, `git diff` subprocess)
  - README "Basic Usage" section
  - SKILL.md "Quick Scans" section

## Current State
- CodeLens: `scan --incremental` (mtime-based, bukan git-based)
- CodeLens: tidak ada `--staged` atau `--diff` flag

## Acceptance Criteria
- [ ] Flag `--staged` di `scan` dan command yang produce findings
  - Run `git diff --cached --name-only --diff-filter=ACMR` untuk dapat staged files
  - Filter: hanya file yang match `--include-ext` (atau auto-detect by language)
  - Scan hanya file-file tersebut
- [ ] Flag `--diff` / `--git-diff` di `scan` dan command yang produce findings
  - Run `git diff --name-only` untuk dapat working tree changes vs HEAD
  - Scan hanya file-file tersebut
- [ ] Flag `--diff-vs=<ref>` — scan file yang berubah vs git ref (branch/tag/commit)
  - Run `git diff --name-only <ref> HEAD`
  - Contoh: `--diff-vs=main` untuk PR review
- [ ] Combine dengan `--comparison` (Issue #7): baseline = main branch scan, current = PR scan, delta = new findings di PR
- [ ] Performance: <1s untuk <50 changed files (vs 30s full scan)
- [ ] Output: tetap full JSON/SARIF/HTML, tapi `files_scanned` hanya count changed files
- [ ] Warning jika bukan git repo: "Not a git repository, --staged/--diff ignored. Use full scan instead."
- [ ] Integrasi dengan `pre_commit_hook.py`: default scan hanya staged file (fast feedback)

## Implementation Notes
- `subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"], capture_output=True, text=True, cwd=workspace)`
- Parse output, split by newline, filter empty + filter by extension
- Pass file list ke scanner engine (modify scanner untuk accept explicit file list, bukan walk directory)
- Reuse `incremental.py` framework untuk file list handling

## Priority
P1 — critical untuk pre-commit hook performance + CI PR review.
```

---

### 📋 Issue #9 [P1] — Manifest-Driven Test Suite (Substring + Exit + Totals Assertion)

```markdown
**Title:** [P1] Manifest-driven test suite with substring/exit/totals assertion (UBS-style)

## Motivation
CodeLens `benchmarks/` punya fixture (`clean_app/`, `vulnerable_app/`) + `ground_truth.yaml` + `run_benchmarks.py`, tapi:
- Hanya assert totals (count critical/warning), tidak assert substring di output
- Tidak assert exit code
- Tidak assert stderr output
- Tidak support `forbid_substrings` (assert bahwa string tertentu TIDAK boleh muncul)
- Tidak ada artifact capture (stdout.log, stderr.log, result.json per test case)

UBS `test-suite/manifest.json` (402 case, 11828 baris) dengan schema expressif:

```json
{
  "id": "python-resource-lifecycle",
  "path": "test-suite/python/buggy",
  "args": ["--only=python", "--category=resource-lifecycle"],
  "env": {"NO_COLOR": "1"},
  "expect": {
    "exit_code": "nonzero",
    "totals": {"critical": {"min": 3}, "warning": {"min": 1}},
    "require_substrings": ["context manager", "file handle"],
    "forbid_substrings": ["false positive pattern"],
    "require_substrings_stderr": ["WARNING: ..."]
  }
}
```

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `test-suite/manifest.json` (11828 baris, 402 case)
  - `test-suite/run_manifest.py` (test runner, ~300 LOC)
  - `test-suite/run_all.sh` (CI entry point)
  - README "Test Suite Infrastructure" section

## Current State
- CodeLens: `benchmarks/run_benchmarks.py` + `benchmarks/fixtures/{clean_app,vulnerable_app}/ground_truth.yaml`
- CodeLens: assert totals only, no substring/exit/stderr assertion

## Acceptance Criteria
- [ ] Manifest file: `benchmarks/manifest.json` (extend existing `ground_truth.yaml` atau replace dengan JSON)
- [ ] Schema per test case:
  - `id` (unique identifier)
  - `description` (human-readable)
  - `path` (fixture directory atau file)
  - `language` (filter)
  - `tags` (untuk `--tag` filter, mis. `["security", "buggy"]`)
  - `args` (CLI args, mis. `["--only=python", "--category=resource-lifecycle"]`)
  - `env` (environment variables, mis. `{"NO_COLOR": "1"}`)
  - `expect`:
    - `exit_code`: `"zero"`, `"nonzero"`, atau integer spesifik
    - `totals`: `{"critical": {"min": 3, "max": 10}, "warning": {"min": 1}}`
    - `require_substrings`: list string yang HARUS ada di stdout
    - `forbid_substrings`: list string yang TIDAK boleh ada di stdout
    - `require_substrings_stderr`: list string yang HARUS ada di stderr
    - `forbid_substrings_stderr`: list string yang TIDAK boleh ada di stderr
- [ ] Test runner: `benchmarks/run_manifest.py` (port dari UBS `run_manifest.py`)
  - `--case <id>` — run specific case
  - `--list` — list all case IDs
  - `--fail-fast` — stop on first failure
  - `--tag <tag>` — filter by tag
  - `--verbose` — print full stdout/stderr per case
- [ ] Artifact capture: `benchmarks/artifacts/<case_id>/{stdout.log, stderr.log, result.json}`
- [ ] Report: pass/fail per case, summary totals, duration
- [ ] CI integration: jalankan di GitHub Actions `codelens-ci.yml`, fail PR jika test fail
- [ ] Migrate existing `benchmarks/fixtures/` ke manifest format (50+ case awal)
- [ ] Add new fixture per language: Python buggy/clean, JS buggy/clean, Rust buggy/clean, dll (target 200+ case dalam 3 bulan)

## Implementation Notes
- Port `test-suite/run_manifest.py` dari UBS (Python, ~300 LOC, MIT license — kompatibel dengan CodeLens MIT)
- Substring assertion: case-sensitive by default, `--ignore-case` flag untuk case-insensitive
- Untuk `exit_code: "nonzero"`: accept any non-zero exit code (1, 2, dll)
- Artifact retention: 30 hari di CI, configurable

## Priority
P1 — critical untuk rule regression detection + CI quality gate.
```

---

### 📋 Issue #10 [P1] — Rule Quality Harness dengan Golden Snapshot

```markdown
**Title:** [P1] Rule quality harness with golden snapshot (regression detection untuk rule akurasi)

## Motivation
CodeLens `benchmarks/` cek apakah engine menemukan bug di fixture, tapi tidak track **rule coverage regression**: jika developer modify rule dan coverage turun (mis. rule yang sebelumnya catch 10 bug sekarang hanya catch 5), tidak ada alert.

UBS punya `test-suite/quality/rule_quality_harness.py` + `test-suite/goldens/rule_coverage.json` (4484 baris) yang:
- Track `buggy_cases_with_required_substrings` (case buggy yang harus catch certain substring)
- Track `clean_cases_with_forbidden_substrings` (case clean yang tidak boleh produce certain substring)
- Track `strict_zero_clean_cases` (case clean yang harus zero finding)
- Detect `weak_cases` (case yang tidak strict — clean tapi tidak zero, atau missing substring)
- 3 scope: `all` (282 case), `campaign` (179 case), `smoke` (22 case)
- Regression: jika rule berubah dan coverage turun, golden snapshot fail

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `test-suite/quality/rule_quality_harness.py` (~400 LOC)
  - `test-suite/goldens/rule_coverage.json` (4484 baris, golden snapshot)
  - `test-suite/goldens/ast_grep_rule_pack_sarif.json` (SARIF golden untuk ast-grep rule)

## Current State
- CodeLens: tidak ada equivalent. `benchmarks/` hanya track totals, bukan coverage regression.

## Acceptance Criteria
- [ ] Script `benchmarks/rule_quality_harness.py` — run UBS-style quality check
- [ ] Golden snapshot: `benchmarks/goldens/rule_coverage.json`
- [ ] Track per scope:
  - `all`: semua test case
  - `campaign`: subset penting (security + critical bug)
  - `smoke`: quick check (10-20 case, <30s)
- [ ] Metrics per scope:
  - `buggy_cases_with_required_substrings`: count buggy case yang pass substring assertion
  - `clean_cases_with_forbidden_substrings`: count clean case yang tidak produce forbidden substring
  - `strict_zero_clean_cases`: count clean case yang zero finding
  - `weak_cases`: list case yang tidak strict (dengan reasons: `clean_missing_forbid_substrings`, `clean_not_strict_zero_critical_warning`, dll)
- [ ] Compare current run vs golden: jika metric turun, fail dengan diff
- [ ] `--update-goldens` flag: regenerate golden snapshot (untuk intentional rule change)
- [ ] CI integration: jalankan di `codelens-quality-gate.yml`, fail PR jika regression
- [ ] Report: human-readable summary + JSON untuk CI parsing

## Implementation Notes
- Port `test-suite/quality/rule_quality_harness.py` dari UBS (Python, ~400 LOC, MIT license)
- Golden snapshot format: JSON dengan nested scope → metric → value
- `weak_cases` detection: iterate semua clean case, cek apakah (a) punya `forbid_substrings`, (b) zero critical+warning finding
- Diff: bandingkan current vs golden per metric, report delta

## Priority
P1 — critical untuk rule maintenance (rule author tahu jika change mereka break coverage).
```

---

### 📋 Issue #11 [P1] — Homebrew Tap + Scoop + Nix Flake Distribution

```markdown
**Title:** [P1] Multi-channel distribution: Homebrew tap + Scoop + Nix flake + Docker image

## Motivation
CodeLens saat ini hanya bisa di-install via:
1. `git clone https://github.com/Wolfvin/CodeLens.git` + `bash setup.sh` (manual, butuh Python 3.8+)
2. Tidak ada binary release
3. Tidak ada package manager integration

Barrier adopsi tinggi untuk:
- User non-Python (Node/Rust/Go developer)
- CI pipeline (cold start lambat, setup 1-3 menit)
- Enterprise user yang mau `brew install` standard

UBS distribusi via 5 channel: Homebrew, Scoop, Nix, Docker, curl install. Semua signed dengan minisign/cosign.

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `install.sh` (3750 LOC, curl-pipe installer)
  - `flake.nix` (Nix flake: packages.default + devShells.default + nixosModules.ubs)
  - `Dockerfile` (debian:bookworm-slim base)
  - Homebrew tap: `dicklesworthstone/tap/ubs` (separate repo `homebrew-tap`)
  - Scoop bucket: `dicklesworthstone/scoop-bucket` (separate repo)
  - `scripts/release/` (release automation)

## Current State
- CodeLens: `git clone` + `bash setup.sh` only
- CodeLens: tidak ada binary, tidak ada package manager integration

## Acceptance Criteria
- [ ] **Homebrew tap** (macOS/Linux):
  - Create separate repo `Wolfvin/homebrew-tap`
  - Formula `codelens.rb` — install via `brew install wolfvin/tap/codelens`
  - Auto-update via `brew upgrade`
  - `brew uninstall codelens` untuk clean remove
- [ ] **Scoop bucket** (Windows):
  - Create separate repo `Wolfvin/scoop-bucket`
  - Manifest `codelens.json` — install via `scoop bucket add wolfvin https://github.com/Wolfvin/scoop-bucket && scoop install wolfvin/codelens`
- [ ] **Nix flake**:
  - `flake.nix` di repo CodeLens
  - `packages.default` — install `codelens` ke `$out/bin/codelens`
  - `devShells.default` — Python 3.11 + tree-sitter + grammar packages + PyYAML + watchdog
  - `nixosModules.codelens` — NixOS module dengan `programs.codelens.enable`
  - `nix run github:Wolfvin/CodeLens` — run tanpa install
  - `nix develop` — dev shell untuk contributor
  - `nix flake check` di CI untuk determinism
- [ ] **Docker/OCI image**:
  - `Dockerfile` di repo CodeLens (base `python:3.11-slim` atau `debian:bookworm-slim`)
  - Image: `ghcr.io/wolfvin/codelens:latest` + tag per version
  - Multi-arch: linux/amd64 + linux/arm64
  - `docker run --rm -v $(pwd):/workspace ghcr.io/wolfvin/codelens scan /workspace`
- [ ] **curl install** (one-liner):
  - `install.sh` (port dari UBS, ~1000 LOC simplified)
  - `curl -fsSL https://raw.githubusercontent.com/Wolfvin/CodeLens/main/install.sh | bash`
  - Auto-detect OS + arch, download binary atau fallback ke Python install
  - `--install-dir`, `--no-path-modify`, `--skip-hooks`, `--non-interactive` flags
- [ ] **GitHub Releases**:
  - Auto-cut release saat tag push (`v*.*.*`)
  - Release assets: `codelens-linux-x64`, `codelens-linux-arm64`, `codelens-macos-x64`, `codelens-macos-arm64`, `codelens-windows-x64.exe`, `SHA256SUMS`, `SHA256SUMS.minisig`
  - SBOM + SLSA provenance attestation
- [ ] **PyPI publish** (optional, untuk `pip install codelens`):
  - `pyproject.toml` sudah ada, tinggal configure build + publish
  - `pip install codelens` untuk Python user
  - Auto-publish saat release via GitHub Actions

## Implementation Notes
- Homebrew formula: Ruby DSL, specify `url`, `sha256`, `depends_on "python@3.11"`, `bin "codelens"`
- Scoop manifest: JSON, specify `url`, `hash`, `bin`
- Nix flake: Nix expression language, gunakan `pkgs.python311.withPackages (ps: [ps.tree-sitter ps.pyyaml])`
- Docker multi-arch: `docker buildx build --platform linux/amd64,linux/arm64`
- Binary build: PyInstaller (Issue #12 dari dokumen opengrep) atau Nuitka
- CI: GitHub Actions matrix build untuk 5 platform target

## Priority
P1 — critical untuk adopsi (barrier install tinggi = user drop off).
```

---

### 📋 Issue #12 [P1] — Release Signing (minisign + Cosign)

```markdown
**Title:** [P1] Release signing: minisign untuk installer + Cosign keyless untuk OCI image

## Motivation
CodeLens release saat ini tidak signed. User tidak bisa verify authenticity binary/installer yang di-download. Supply-chain attack risk: jika GitHub release di-compromise, attacker bisa replace binary dengan malware.

UBS ship 2-layer signing:
1. **minisign** untuk installer + SHA256SUMS (offline private key, verify dengan `UBS_MINISIGN_PUBKEY`)
2. **Cosign keyless** (OIDC) untuk OCI image — sign by digest (bukan tag), Rekor transparency log, SBOM + SLSA provenance attestation

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `scripts/verify.sh` (minisign verifier)
  - `scripts/verify_sha256sums.sh` (SHA256SUMS verifier)
  - `docs/security.md` (threat model + controls + verification guide)
  - `docs/release.md` (release playbook)
  - GitHub Actions: cosign sign + attestation upload

## Current State
- CodeLens: tidak ada release signing
- CodeLens: tidak ada SHA256SUMS file

## Acceptance Criteria
- [ ] **minisign signing untuk installer + SHA256SUMS**:
  - Generate minisign keypair (offline, simpan private key di GitHub Secret sebagai base64)
  - Saat release: compute SHA256SUMS untuk semua release assets, sign dengan minisign private key
  - Upload `SHA256SUMS` + `SHA256SUMS.minisig` ke GitHub Release
  - Publish public key di README + `docs/security.md`
  - Verifier script: `scripts/verify.sh --version vX.Y.Z` — download SHA256SUMS + signature, verify, then check install.sh
- [ ] **Cosign keyless signing untuk OCI image**:
  - GitHub Actions dengan `cosign sign --yes` (OIDC token)
  - Sign by digest (bukan tag, untuk prevent mutable tag attack)
  - Upload ke Rekor transparency log
  - SBOM (SPDX format) attestation
  - SLSA provenance attestation
  - Verifier: `cosign verify ghcr.io/wolfvin/codelens@sha256:<hash>`, `cosign verify-attestation --type spdx`, `cosign verify-attestation --type https://slsa.dev/provenance/v1`
- [ ] **Module/helper SHA-256 verification** (jika CodeLens adopt lazy module download):
  - Embed SHA-256 checksum di meta-runner untuk setiap module/helper
  - Verify sebelum eksekusi, fail closed jika mismatch
  - `codelens doctor --fix` (Issue #3) untuk redownload corrupted module
- [ ] **Threat model documentation**: `docs/security.md` (port dari UBS, adapt ke CodeLens)
  - Threat: tampered release artifacts, mutable image tags, module supply chain, installer auto-update, compromised signing keys
  - Controls: signed checksums, cosign keyless, immutable references, module integrity, no silent auto-update
- [ ] **Verification guide**: `docs/security.md` section "Verification guide" dengan 3 step (installer, OCI, module cache)
- [ ] **Key rotation procedure**: dokumentasi cara rotate minisign key (generate new, update secrets + docs, deprecate old key)

## Implementation Notes
- minisign: install via `brew install minisign` atau `cargo install minisign-verify`
- Cosign: install via `brew install cosign` atau `pip install cosign`
- GitHub Actions: `sigstore/cosign-installer@v3` + `sigstore/cosign-action@v3`
- SBOM generation: `syft` atau `cyclonedx-bom`
- SLSA provenance: `slsa-framework/slsa-github-generator/.github/workflows/generator_container_slsa3.yml`
- Private key storage: GitHub Secret `MINISIGN_PRIVATE_KEY` (base64), GitHub Secret `MINISIGN_PASSWORD`

## Priority
P1 — critical untuk supply-chain security, terutama jika CodeLens adopt lazy module download (Issue #14).
```

---

### 📋 Issue #13 [P1] — `sessions` Command (Install Log)

```markdown
**Title:** [P1] `codelens sessions` command — view installer session history

## Motivation
CodeLens `setup.sh` jalankan install dependencies + init workspace + scan. Tapi tidak ada log yang catat:
- Kapan install dijalankan
- Agent apa yang detected (Issue #4)
- Integration apa yang configured (Claude Code hook, Cursor rules, dll)
- Error/warning selama install
- Environment details (Python version, OS, arch)

User tidak bisa re-check apa yang dilakukan installer. Untuk support debugging, perlu session log.

UBS punya `ubs sessions`:
- `ubs sessions` — show last session summary
- `ubs sessions --entries=N` — last N sessions
- `ubs sessions --raw` — full unformatted log
- Log di `$XDG_CONFIG_HOME/ubs/session.md` (atau `~/.config/ubs/session.md`)

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `install.sh` (`log_session()` function, append ke `~/.config/ubs/session.md`)
  - README "Session Logging" section
  - README "Maintenance Commands" section

## Current State
- CodeLens: tidak ada session log. `setup.sh` print ke stdout, tapi tidak persist.

## Acceptance Criteria
- [ ] `setup.sh` log setiap install session ke `~/.codelens/session.md`
- [ ] Log format (Markdown):
  ```markdown
  ## Session: 2026-06-28 14:30:22 UTC
  
  **Duration:** 45 seconds
  **Python:** 3.11.5
  **OS:** Linux 6.5.0-ubuntu
  **Arch:** x86_64
  
  ### Detected Agents
  - ✓ Claude Code (.claude/ directory found)
  - ✓ Cursor (.cursor/ directory found)
  - ✗ Codex CLI (not detected)
  
  ### Configured Integrations
  - ✓ Claude Code hook: .claude/hooks/on-file-write.sh
  - ✓ Cursor rules: .cursor/rules/codelens.md
  - ✓ MCP config: ~/.config/claude-desktop/codelens-mcp.json
  
  ### Dependencies Installed
  - ✓ tree-sitter 0.20.4
  - ✓ tree-sitter-python 0.20.0
  - ✓ tree-sitter-javascript 0.20.0
  - ✓ PyYAML 6.0.1
  
  ### Warnings
  - ⚠ watchdog not installed (watch command disabled)
  - ⚠ git not found (ownership command disabled)
  
  ### Errors
  (none)
  ```
- [ ] Command `codelens sessions` — show last session (formatted, human-readable)
- [ ] `codelens sessions --entries=N` — show last N sessions (default: 1)
- [ ] `codelens sessions --raw` — full unformatted log (cat-style)
- [ ] `codelens sessions --config-dir=<path>` — custom config location
- [ ] `codelens sessions --json` — JSON output untuk scripting
- [ ] Integrasi dengan `setup.sh`: append session setelah install selesai
- [ ] Integrasi dengan `doctor` (Issue #3): doctor baca session terakhir untuk diagnose

## Implementation Notes
- Session log append-only (jangan overwrite)
- Rotate jika >1MB (keep last 50 sessions)
- Format: Markdown (human-readable) + JSON sidecar (`~/.codelens/session.json`) untuk programmatic access
- `sessions` command: parse Markdown, pretty-print

## Priority
P1 — improve support UX, help user re-check what installer did.
```

---

### 📋 Issue #14 [P2] — ast-grep Rule Engine Integration

```markdown
**Title:** [P2] ast-grep rule engine integration (compatible rule format)

## Motivation
CodeLens saat ini pakai tree-sitter ad-hoc untuk pattern matching (di `ast_taint_engine.py`, `callgraph_engine.py`, dll). Tidak ada rule YAML pattern language yang user-friendly.

UBS pakai ast-grep (https://ast-grep.github.io/) yang:
- Pattern matching AST dengan metavariable (`$X`, `$$$ARGS`)
- Rule YAML format (human-readable, easy to extend)
- Ancestor-aware matching (`stopBy: end` — traverse entire ancestor tree)
- `--rules=DIR` flag untuk load custom rule pack
- Kompatibel dengan ast-grep rule ecosystem (ribuan rule publik)

Ast-grep rule example:
```yaml
id: no-eval-user-input
language: javascript
rule:
  pattern: eval($INPUT)
severity: critical
message: "eval() with user input - RCE vulnerability"
```

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `modules/ubs-js.sh` (ast-grep rule pack invocation)
  - `modules/ubs-python.sh` (ast-grep rule pack invocation)
  - README "Custom AST-Grep Rules" section
  - README "AST Rule Architecture: Ancestor-Aware Pattern Matching" section
  - README "ast-grep Auto-Provisioning" section

Catatan: ast-grep juga dipakai opengrep (sebagai alternatif generic mode). Jika CodeLens sudah implement Issue #1 (pattern matching engine) dari dokumen opengrep, issue ini bisa jadi alternative approach (pakai ast-grep binary instead of build matcher from scratch).

## Current State
- CodeLens: tree-sitter ad-hoc, no rule YAML pattern language
- CodeLens: plugin rule_pack hanya support source/sink list statis

## Acceptance Criteria
- [ ] Bundle ast-grep binary (auto-provisioning per-platform, SHA-256 verified — seperti UBS approach)
  - Platforms: macOS ARM64/Intel, Linux ARM64/x64, Windows x64
  - Cache di `~/.codelens/ast-grep/<version>/<platform>/`
  - Fallback ke tree-sitter ad-hoc jika ast-grep unavailable (graceful degradation)
- [ ] Support ast-grep rule YAML format di plugin rule_pack:
  ```yaml
  id: codelens/js-no-eval-user-input
  language: javascript
  rule:
    pattern: eval($INPUT)
  severity: critical
  message: "eval() with user input - RCE vulnerability"
  metadata:
    cwe: CWE-95
    owasp: A03:2021
  ```
- [ ] `--rules=DIR` flag di `scan`, `taint`, `secrets` command — load custom ast-grep rule pack (merged with builtin)
- [ ] Integrasi dengan plugin system: rule_pack plugin bisa berisi ast-grep rule YAML
- [ ] Ancestor-aware matching: support `inside`, `has`, `precedes`, `follows` dengan `stopBy: end`
- [ ] Metavariable: `$X` (single node), `$$$ARGS` (multi-node), `$NAME` (named capture)
- [ ] Constraints: `metavariable-regex`, `metavariable-comparison` (depend on Issue #2 opengrep doc)
- [ ] Test: 50+ ast-grep rule yang catch real bug (port dari UBS builtin rule pack)
- [ ] Dokumentasi: `references/ast-grep-rule-syntax.md` dengan 30+ contoh

## Implementation Notes
- Ast-grep binary: download dari GitHub releases `https://github.com/ast-grep/ast-grep/releases`
- Invocation: `ast-grep scan --json --rules <dir> <target>`
- Parse JSON output, convert ke CodeLens finding format
- Untuk ancestor-aware: ast-grep native support `stopBy: end` di `inside`/`has`/`precedes`/`follows` directive
- Performance: ast-grep sangat cepat (Rust-based), bisa parallel

## Decision Point
- **Option A:** Build pattern matcher from scratch (Issue #1 opengrep doc) — full control, no external dependency, tapi 2-3 sprint kerja
- **Option B:** Integrate ast-grep binary (issue ini) — leverage mature ecosystem, 1 sprint, tapi external dependency
- **Recommendation:** Option B dulu (quick win), Option A sebagai long-term goal jika perlu deeper integration

## Priority
P2 — alternative approach to Issue #1 (opengrep doc). Quick win jika pilih Option B.
```

---

### 📋 Issue #15 [P2] — Cross-Language Async Error Detection (10 Bahasa Konsisten)

```markdown
**Title:** [P2] Cross-language async error detection with consistent pattern (10 languages)

## Motivation
CodeLens `ast_taint_engine.py` support Python/JS/TS/Rust untuk taint analysis. Tapi untuk async error detection (missing await, unhandled promise, goroutine leak, dll), CodeLens tidak punya pattern konsisten cross-language.

UBS detect async error di 10 bahasa dengan pattern setara:

| Language | Pattern | What UBS Detects |
|---|---|---|
| JS/TS | `promise.then()` tanpa `.catch()`, `new Promise(async ...)`, `forEach(async ...)`, async predicate, async timer/event/JSX callback, `Promise.all(map(...))` tanpa return | Dangling promises, missing await, unawaitable async callbacks |
| Python | `asyncio.create_task()` tanpa `await` | Orphaned tasks, unclosed coroutines |
| Go | Goroutine tanpa error channel | Fire-and-forget, leaked contexts |
| Rust | `.unwrap()`/`.expect()` setelah `if let Some` guard | Panic after partial guard |
| Java | `CompletableFuture` tanpa `.exceptionally()` | Swallowed exceptions |
| Ruby | `Thread.new` tanpa `.join` | Zombie threads |
| C++ | `std::async` tanpa `.get()` | Ignored futures |
| Swift | `Task {}` tanpa error handling | Unstructured concurrency leaks |
| C# | `Task.Wait()`, `.Result`, `throw ex;` | Sync-over-async deadlock, stack-trace loss |

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `modules/ubs-js.sh` Category 5 (Async/Await & Promise Pitfalls) — paling kaya
  - `modules/ubs-python.sh` Category 5 (Async/Await Pitfalls)
  - `modules/ubs-golang.sh` Category 3 (Concurrency & Async Pitfalls)
  - `modules/ubs-rust.sh` Category 3 (Concurrency & Async Pitfalls) + Category 20 (Async Locking Across Await)
  - `modules/ubs-java.sh` (CompletableFuture checks)
  - `modules/ubs-cpp.sh` (std::async checks)
  - `modules/ubs-ruby.sh` (Thread.new checks)
  - `modules/ubs-swift.sh` (Task {} checks)
  - `modules/ubs-csharp.sh` (Task.Wait/.Result checks)
  - README "Cross-Language Async Error Detection" section

## Current State
- CodeLens: `ast_taint_engine.py` support Python/JS/TS/Rust taint, tapi bukan async-specific
- CodeLens: tidak ada async error detection untuk Go/Java/Ruby/C++/Swift/C#

## Acceptance Criteria
- [ ] Async error detection di 10 bahasa (JS/TS, Python, Go, Rust, Java, Ruby, C++, Swift, C#, Elixir)
- [ ] Pattern konsisten per bahasa (port dari UBS):
  - JS/TS: missing await, unhandled promise, async callback in forEach/map/reduce/predicate/sort-comparator, async timer/event/JSX listener, Promise.all(map) return guard
  - Python: `asyncio.create_task()` tanpa `await`, unclosed coroutine
  - Go: goroutine tanpa error channel, leaked context, `context.With*` tanpa cancel
  - Rust: `.unwrap()`/`.expect()` setelah `if let Some` guard, async lock across await
  - Java: `CompletableFuture` tanpa `.exceptionally()`, missing `join()`
  - Ruby: `Thread.new` tanpa `.join`
  - C++: `std::async` tanpa `.get()`
  - Swift: `Task {}` tanpa error handling, unstructured concurrency
  - C#: `Task.Wait()`, `.Result`, `throw ex;`, `async void`
- [ ] Integrasi dengan `taint` command: `codelens taint` jalankan async error detection
- [ ] Output: finding dengan `category: "async-error"`, `sub_category: "missing-await"`, `language: "python"`, `file:line`, `message`, `suggested_fix`
- [ ] Test: fixture per bahasa (buggy + clean), 10+ case per bahasa

## Implementation Notes
- Implementasi di `scripts/async_error_engine.py` (new engine)
- Register ke command registry: `codelens async-scan` atau integrate ke `taint`
- Untuk JS/TS: ast-grep rule pack (paling mature di UBS)
- Untuk Python: AST walker (port dari UBS `modules/helpers/` jika ada, atau implement baru dengan `ast` module)
- Untuk Go: tree-sitter Go grammar + AST walker
- Untuk Rust: tree-sitter Rust grammar + AST walker

## Priority
P2 — improve async bug coverage, high value untuk polyglot project.
```

---

### 📋 Issue #16 [P2] — Resource Lifecycle Correlation (Acquire/Release Pair Matching)

```markdown
**Title:** [P2] Resource lifecycle correlation — detect acquire without matching release

## Motivation
CodeLens `deadcode_engine.py` detect unused code, tapi tidak detect resource lifecycle imbalance: file dibuka tanpa close, socket dibuka tanpa shutdown, Popen tanpa wait, asyncio task tanpa cancel, ExecutorService tanpa shutdown, dll.

UBS punya AST-based detector (`modules/helpers/resource_lifecycle_*.py` untuk Python/Go/Java/C#/C++/Ruby/Swift) yang:
- Track setiap acquire call (open, socket, Popen, create_task, etc.)
- Cek matching release (close, shutdown, wait, cancel, etc.)
- Report imbalance dengan line number akurat

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `modules/helpers/resource_lifecycle_py.py` (402 LOC, Python AST walker)
  - `modules/helpers/resource_lifecycle_go.go` (Go AST walker)
  - `modules/helpers/resource_lifecycle_java.py` (Java AST walker)
  - `modules/helpers/resource_lifecycle_csharp.py` (C# AST walker)
  - `modules/helpers/resource_lifecycle_cpp.py` (C++ AST walker)
  - `modules/helpers/resource_lifecycle_ruby.py` (Ruby AST walker)
  - `modules/helpers/resource_lifecycle_swift.py` (Swift AST walker)
  - README "Resource lifecycle heuristics in each language" section

## Current State
- CodeLens: `deadcode_engine.py` detect unused, bukan acquire/release mismatch
- CodeLens: tidak ada resource lifecycle engine

## Acceptance Criteria
- [ ] New engine: `scripts/resource_lifecycle_engine.py`
- [ ] New command: `codelens resource-lifecycle` (atau integrate ke `smell`)
- [ ] Support 7 bahasa awal: Python, Go, Java, C#, C++, Ruby, Swift
- [ ] Per-bahasa detection (port dari UBS helpers):
  - **Python**: `open()`, `socket.socket()`, `subprocess.Popen()`, `asyncio.create_task()` tanpa `with`/`close()`/`wait()`/`cancel()`
  - **Go**: `context.With*()` tanpa `defer cancel()`, `time.NewTicker/NewTimer` tanpa `Stop()`, `os.Open/OpenFile` tanpa `defer Close()`, mutex `Lock`/`Unlock` symmetry
  - **Java**: `FileInputStream`, JDBC `Connection`/`Statement`/`ResultSet`, `ExecutorService` tanpa `shutdown()`, `Thread` tanpa `join()` — via ast-grep rule: `java.resource.executor-no-shutdown`, `java.resource.thread-no-join`, `java.resource.jdbc-no-close`, `java.resource.resultset-no-close`, `java.resource.statement-no-close`
  - **C#**: `CancellationTokenSource`, stream readers/writers, `HttpRequestMessage`, `Task.Run`/`Task.Factory.StartNew` handles tanpa observe
  - **C++**: `malloc`/`free`, `fopen`/`fclose`, RAII violation
  - **Ruby**: `File.open` tanpa block, `Tempfile.create` tanpa close
  - **Swift**: `defer` symmetry, `URLSession` task tanpa resume/cancel
- [ ] Output per finding: `category: "resource-lifecycle"`, `sub_category: "file-handle-leak"`, `acquire_line: 42`, `release_line: null` (or matching release line), `message: "File handle fh opened without context manager or close()"`
- [ ] Severity mapping:
  - `file_handle` → critical (data loss risk)
  - `socket_handle` → warning
  - `popen_handle` → warning (zombie process)
  - `asyncio_task` → warning (orphaned task)
  - `executor_service` → critical (thread leak)
- [ ] Remediation suggestion: `"Use 'with open(...)' or explicitly call .close()"`
- [ ] Test: fixture per bahasa (buggy + clean), port dari UBS `test-suite/{python,golang,java,csharp,cpp,ruby,swift}/buggy/resource_lifecycle.*`

## Implementation Notes
- Python: pakai `ast` module (stdlib), walk AST, track `Call` node untuk acquire pattern, cek `With`/`Attribute` untuk release
- Go: pakai `go/ast` library (perlu Go runtime) atau tree-sitter Go grammar
- Java/C#/C++/Ruby/Swift: pakai tree-sitter grammar masing-masing
- Atau gunakan ast-grep rule (Issue #14) — lebih simple, kompatibel dengan UBS approach

## Priority
P2 — high value untuk production reliability (resource leak = memory leak = OOM crash).
```

---

### 📋 Issue #17 [P2] — `--profile=strict|loose` Preset + `--category=<name>` Filter

```markdown
**Title:** [P2] `--profile=strict|loose` preset + `--category=<name>` focused scan filter

## Motivation
CodeLens tidak punya preset profile. User harus manual combine flag untuk strict CI mode (`--fail-on-warning` + `--severity=critical` + `--format=sarif` + ...). Tidak ada way to focus scan ke category tertentu (mis. "hanya scan resource-lifecycle issues").

UBS punya:
- `--profile=strict` — fail on warnings, enforce high standards (CI mode)
- `--profile=loose` — skip TODO/debug/code-quality nits when prototyping
- `--category=resource-lifecycle` — focus scan, narrows language set + suppress unrelated categories

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `ubs` meta-runner (`--profile` flag handler, `--category` flag handler)
  - SKILL.md "Profiles" section
  - SKILL.md "Category Packs" section
  - README "Advanced Configuration" section

## Current State
- CodeLens: tidak ada profile preset
- CodeLens: tidak ada category filter (pakai command terpisah: `smell`, `secrets`, `vuln-scan`, dll)

## Acceptance Criteria
- [ ] `--profile=strict` flag:
  - Set `--fail-on-warning` (exit 1 jika ada warning+)
  - Set `--severity=critical,high` (hanya report critical+high)
  - Set `--format=sarif` (default untuk CI)
  - Set `--ci` mode (stable UTC ISO-8601 timestamp, no color)
  - Enable all category (no skip)
- [ ] `--profile=loose` flag:
  - Skip category: TODO/FIXME markers, debug code, code quality nits
  - Set `--severity=critical,high` (hanya report yang penting)
  - Disable `--fail-on-warning` (exit 0 bahkan jika ada warning)
  - Untuk prototyping workflow
- [ ] `--profile=balanced` flag (default):
  - Current CodeLens behavior (no change)
- [ ] `--category=<name>` flag di `scan`, `taint`, `smell`:
  - `--category=security` — hanya security finding (SQL inj, XSS, eval, secrets, dll)
  - `--category=resource-lifecycle` — hanya resource leak (Issue #16)
  - `--category=async-error` — hanya async issue (Issue #15)
  - `--category=performance` — hanya perf hint (N+1, sync blocking, memory leak)
  - `--category=quality` — hanya code smell (complexity, dead code, debug leak)
  - `--category=accessibility` — hanya a11y (WCAG 2.1)
  - `--category=frontend` — hanya CSS deep + a11y + Tailwind
  - `--category=backend` — hanya API map + state map + entrypoints
- [ ] Category pack: auto-narrow language set (mis. `--category=resource-lifecycle` hanya scan Python/Go/Java/C# yang punya helper)
- [ ] `--list-categories` command — print semua category yang available per language
- [ ] Combine: `codelens scan --profile=strict --category=security`

## Implementation Notes
- Profile: mapping ke set of flag, apply di CLI parser
- Category: filter di output layer (semua engine jalan, tapi hanya finding dengan matching `category` di-report)
- Atau: category select subset engine yang jalan (lebih efficient)

## Priority
P2 — improve UX untuk CI vs prototyping workflow.
```

---

### 📋 Issue #18 [P2] — Type Narrowing Helpers (Rust/Kotlin/Swift/C#/TS)

```markdown
**Title:** [P2] Type narrowing helpers for Rust/Kotlin/Swift/C#/TypeScript

## Motivation
CodeLens `typeinfer_engine.py` adalah generik lightweight type inference. Tidak ada type narrowing specific: detect `if (value == null)` guard yang kemudian diikuti `value!!` (Kotlin), `value!` (Swift), `.unwrap()` (Rust setelah `if let Some`), `TryGetValue` fallthrough (C#), `if (!user) return; ... user.name` (TS — type not narrowed).

UBS punya 5 helper per-bahasa:
- `type_narrowing_ts.js` (325 LOC, pakai `typescript` npm package via tsserver)
- `type_narrowing_csharp.py`
- `type_narrowing_rust.py`
- `type_narrowing_kotlin.py`
- `type_narrowing_swift.py`

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `modules/helpers/type_narrowing_ts.js` (325 LOC)
  - `modules/helpers/type_narrowing_csharp.py`
  - `modules/helpers/type_narrowing_rust.py`
  - `modules/helpers/type_narrowing_kotlin.py`
  - `modules/helpers/type_narrowing_swift.py`
  - README "AST-Based Type Narrowing Analysis" section

## Current State
- CodeLens: `typeinfer_engine.py` generik, tidak type narrowing specific

## Acceptance Criteria
- [ ] 5 type narrowing helper (port dari UBS atau implement baru):
  - **TypeScript/JS**: null guard, optional chaining, type predicates, discriminated unions — pakai `typescript` npm package via tsserver
  - **C#**: null guard, `TryGetValue` fallthrough, dereference after failed narrowing
  - **Rust**: `if let Some/Ok` guard + subsequent `.unwrap()`/`.expect()` outside exiting block
  - **Kotlin**: nullable types, smart casts, `if (value == null) log(); value!!` pattern
  - **Swift**: optional binding, `guard let` statements, force unwrap `value!` after log-and-continue
- [ ] Integrasi dengan `taint` command atau new command `codelens type-narrow`
- [ ] Output per finding: `category: "type-narrowing"`, `language: "rust"`, `file:line`, `message: "if let Some(x) = ... then x.unwrap() is redundant — use x directly"`, `suggested_fix`
- [ ] `--skip-type-narrowing` flag — disable helper-backed guard analysis (faster scan, fallback ke heuristik)
- [ ] Test: fixture per bahasa (buggy + clean), port dari UBS `test-suite/{rust,kotlin,swift,csharp,js}/type_narrowing/`

## Implementation Notes
- TypeScript helper butuh Node.js + `typescript` npm package — auto-provisioning seperti UBS approach
- Rust/Kotlin/Swift/C# helper: Python script yang walk tree-sitter AST
- Atau gunakan ast-grep rule (Issue #14) — lebih simple, kompatibel dengan UBS approach

## Priority
P2 — improve type safety detection, high value untuk Rust/Swift/Kotlin project.
```

---

### 📋 Issue #19 [P2] — TOON Format (Token-Optimized Object Notation)

```markdown
**Title:** [P2] TOON format — token-optimized output for LLM with tight context window

## Motivation
CodeLens `--format ai` normalized schema sudah LLM-friendly, tapi tetap JSON (verbose key repetition, braces, quotes). Untuk LLM dengan context window sangat ketat (mis. older GPT-3.5 dengan 4K token), JSON bisa terlalu besar.

UBS punya TOON (Token-Optimized Object Notation) yang:
- Kompres JSON dengan schema inference
- ~50% lebih kecil dari JSON (sample: 15KB JSON → 7.5KB TOON)
- ~34% token saving untuk LLM
- Format: `findings[65]{severity,count,title,description}:` + CSV-like rows

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `docs/reports/RESEARCH_FINDINGS.md` (TOON integration analysis, sample size comparison)
  - `ubs` meta-runner (`--format=toon` handler, TOON encoder via `tru` binary)
  - `test-suite/manifest.json` (TOON test case: `toon-format`, `toon-format-env-var`, `toon-format-fallback`)
  - Fallback: jika `tru` binary unavailable, fallback ke JSON dengan warning stderr

## Current State
- CodeLens: `--format ai` normalized, tapi tetap JSON
- CodeLens: tidak ada TOON equivalent

## Acceptance Criteria
- [ ] New format: `--format=toon`
- [ ] TOON encoder: implementasi Python native (tidak butuh external `tru` binary)
- [ ] Format spec:
  - Schema inference: `findings[65]{severity,count,title,description}:` (array of 65 items dengan 4 field)
  - CSV-like rows: `critical,9,"SQL Injection","User input flows into SQL query"`
  - Nested object: `scanners[3]{language,files,critical,warning,info}:`
  - Scalar field: `project: "/path/to/dir"`, `timestamp: "2026-06-28T14:30:22Z"`
- [ ] Fallback: jika TOON encoder error, fallback ke `--format ai` (JSON) dengan warning stderr
- [ ] Env var: `CODELENS_OUTPUT_FORMAT=toon` untuk set default format
- [ ] Test: snapshot test dengan fixture, compare byte size vs JSON
- [ ] Dokumentasi: `references/toon-format.md` dengan spec + 20+ contoh
- [ ] Performance: TOON encoding <100ms untuk 1000 finding

## Implementation Notes
- TOON encoder: Python class dengan `encode(data: Any) -> str`
- Schema inference: detect array of uniform dict, emit schema header
- CSV-like rows: escape comma, quote, newline dengan backslash
- Untuk nested: recurse dengan indent
- Alternative: gunakan `tru` binary dari UBS (Rust-based, fast) — tapi add external dependency

## Priority
P2 — nice-to-have untuk LLM dengan tight context window, low priority jika `--format ai` sudah cukup.
```

---

### 📋 Issue #20 [P2] — JSONL Streaming Output + Beads Integration

```markdown
**Title:** [P2] JSONL streaming output + Beads/issue-tracker integration

## Motivation
CodeLens output saat ini batch (semua finding di akhir scan). Untuk CI pipeline yang butuh stream finding ke downstream tool (issue tracker, dashboard, Slack notification), tidak ada format yang cocok.

UBS punya:
- `--format=jsonl` — line-delimited JSON, 1 object per baris
- `--beads-jsonl=<file>` — write JSONL untuk Beads issue tracker
- Pipe pattern: `ubs . --beads-jsonl=/dev/stdout | bd import --from-jsonl`

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `ubs` meta-runner (`--format=jsonl` handler, `--beads-jsonl` handler)
  - README "Beads/Strung JSONL Integration" section
  - `test-suite/manifest.json` (jsonl test case)

## Current State
- CodeLens: tidak ada JSONL output
- CodeLens: tidak ada issue tracker integration

## Acceptance Criteria
- [ ] New format: `--format=jsonl`
- [ ] JSONL schema: 1 JSON object per baris, newline-delimited
  ```jsonl
  {"type":"scanner","project":"/path","language":"python","files":42,"critical":1,"warning":3,"info":12,"timestamp":"2026-06-28T14:30:22Z"}
  {"type":"finding","severity":"critical","category":"security","rule_id":"py/sql-injection","file":"src/api.py","line":42,"col":5,"message":"SQL Injection"}
  {"type":"finding","severity":"warning","category":"quality","rule_id":"smell/long-function","file":"src/utils.py","line":100,"col":1,"message":"Function too long"}
  {"type":"totals","project":"/path","files":99,"critical":1,"warning":3,"info":27,"timestamp":"2026-06-28T14:30:24Z"}
  ```
- [ ] Stream mode: emit finding saat ditemukan (jangan tunggu akhir scan) — depend on Issue #14 opengrep doc (incremental output)
- [ ] `--jsonl-output=<file>` flag — write JSONL ke file (selain stdout)
- [ ] `--jsonl-summary-only` flag — hanya emit summary, tidak emit individual finding
- [ ] Integrasi dengan issue tracker:
  - Beads: `codelens scan --jsonl-output=/dev/stdout | bd import --from-jsonl`
  - GitHub Issues: script `scripts/import-to-github-issues.py` yang parse JSONL, create GitHub issue per finding
  - JIRA: script `scripts/import-to-jira.py`
- [ ] Test: snapshot test dengan fixture, verify JSONL format

## Implementation Notes
- JSONL encoder: `json.dumps(finding) + "\n"` per finding
- Stream mode: print finding saat ditemukan di engine, bukan collect semua dulu
- Untuk Beads: Beads CLI (`bd`) support `--from-jsonl` flag
- Untuk GitHub Issues: gunakan `gh issue create --title "..." --body "..."` via subprocess

## Priority
P2 — nice-to-have untuk CI pipeline integration.
```

---

### 📋 Issue #21 [P2] — `--jobs=N` Parallelism + `--only=LANG` Filter

```markdown
**Title:** [P2] `--jobs=N` parallelism control + `--only=LANG` language filter

## Motivation
CodeLens scan saat ini single-threaded. Untuk repo besar (5000+ file), scan bisa 30-120 detik. Tidak ada way untuk:
- Control parallelism (mis. limit ke 4 core di CI shared runner)
- Filter language (mis. "hanya scan Python, skip JS/TS/Rust")

UBS punya:
- `--jobs=N` — parallel jobs untuk ripgrep (default: auto-detect cores)
- `--only=LANG[,LANG,...]` — language filter (skip irrelevant scanner)
- `JOBS` env var — same as `--jobs=N`

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `ubs` meta-runner (`--jobs` flag, `--only` flag)
  - `modules/ubs-python.sh` (ripgrep `-j` flag passthrough)
  - README "Performance Optimizations" section

## Current State
- CodeLens: single-threaded scan
- CodeLens: scan semua bahasa sekaligus (no `--only` filter)

## Acceptance Criteria
- [ ] `--jobs=N` flag di `scan` dan command yang scan file
  - `--jobs=0` — auto-detect cores (default)
  - `--jobs=1` — single-threaded (deterministic output untuk CI)
  - `--jobs=16` — explicit core count
- [ ] `JOBS` env var — same as `--jobs=N`
- [ ] `--only=LANG[,LANG,...]` flag — language filter
  - `--only=python` — hanya scan Python file
  - `--only=js,ts` — hanya scan JS/TS file
  - `--only=python,rust,go` — polyglot filter
- [ ] `--exclude=LANG[,LANG,...]` flag — exclude language
  - `--exclude=js` — scan semua kecuali JS (mis. jika ast-grep tidak available)
- [ ] Language alias: `js` (JavaScript), `ts` (TypeScript), `tsx` (TSX), `py` (Python), `rs` (Rust), `go` (Go), `java`, `kt` (Kotlin), `rb` (Ruby), `swift`, `cs` (C#), `cpp` (C/C++), `ex` (Elixir)
- [ ] Performance: 2-4x faster dengan `--jobs=N` di multi-core machine
- [ ] Output: tetap full JSON/SARIF/HTML, tapi `files_scanned` hanya count file yang match filter

## Implementation Notes
- `--jobs=N`: gunakan `concurrent.futures.ThreadPoolExecutor(max_workers=N)` atau `multiprocessing.Pool(N)`
- CodeLens engine saat ini synchronous — perlu refactor untuk concurrent execution
- `--only=LANG`: filter file list sebelum pass ke scanner, skip parser yang tidak relevan
- Language detection: pakai file extension (`.py` → python, `.js` → js, dll)

## Priority
P2 — improve performance untuk large repo, high value untuk CI.
```

---

### 📋 Issue #22 [P2] — `--skip=CSV` + `--skip-LANG=N` Per-Category Skip

```markdown
**Title:** [P2] `--skip=CSV` global + `--skip-LANG=N` per-language category skip

## Motivation
CodeLens tidak punya way to skip specific detection category. User harus disable rule sepenuhnya via config. Tidak ada granular control per-category atau per-language.

UBS punya:
- `--skip=11,14` — skip category 11 (debug code) dan 14 (TODO markers) globally
- `--skip-LANG=N[,M,...]` — skip category di satu language only (mis. `--skip-js=8`)
- Stderr warning on ambiguous bare `--skip=N` (category number tidak stabil cross-language)

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `ubs` meta-runner (`--skip` flag, `--skip-LANG` flag, warning logic)
  - CHANGELOG v5.3.0: `#52 — per-language --skip-LANG=N plus loud warning on ambiguous bare --skip=N`
  - `test-suite/shareable/test_skip_categories.py` (regression test)

## Current State
- CodeLens: tidak ada category skip (pakai command terpisah atau disable rule via config)

## Acceptance Criteria
- [ ] `--skip=CSV` flag — skip category by number globally
  - `--skip=11,14` — skip category 11 dan 14
- [ ] `--skip-LANG=N[,M,...]` flag — skip category di satu language
  - `--skip-js=8` — skip category 8 di JS module only
  - `--skip-python=14` — skip category 14 di Python module only
  - LANG alias: `js`, `py`, `rs`, `go`, `java`, `kt`, `rb`, `swift`, `cs`, `cpp`, `ex`
- [ ] Combine: bare `--skip=N` (global) + `--skip-LANG=N` (per-language) merge ke single CSV per module
- [ ] Stderr warning on ambiguous bare `--skip=N`:
  - Jika bare `--skip=N` digunakan DAN 2+ language module akan run
  - Print warning: "Category 8 maps to 'FUNCTION & SCOPE ISSUES' in JS but 'SECURITY FINDINGS' in Rust. Use `--skip-js=8` or `--skip-rust=8` for clarity."
  - Single-language run (`--only=js --skip=8`) tetap quiet
  - Per-language flag use tetap quiet
- [ ] `--list-categories` command — print category index per language (lihat Issue #17)
- [ ] Test: regression test untuk 4 scenario (mirip UBS `test_skip_categories.py`):
  - Single-language `--skip=N`: no warning
  - Polyglot `--skip=N`: warning emitted, names cat per language
  - `--skip-LANG=N`: only target module affected
  - Bare `--skip=N` + `--skip-LANG=N` combine correctly

## Implementation Notes
- Category number tidak stabil cross-language (UBS lesson learned) — hence per-language flag
- Embed category name lookup per module (harvest dari `print_header "N. NAME"` lines)
- Warning logic: cek jika bare `--skip=N` + 2+ module active

## Priority
P2 — improve rule control granularity, reduce false positive noise.
```

---

### 📋 Issue #23 [P2] — Docker/OCI Image + GitHub Container Registry

```markdown
**Title:** [P2] Docker/OCI image + GitHub Container Registry publishing

## Motivation
CodeLens tidak ship Docker image. User yang mau run di CI tanpa install Python dependency tidak bisa. Untuk enterprise dengan air-gapped network, Docker image adalah opsi terbaik.

UBS ship `ghcr.io/dicklesworthstone/ubs-tools` (debian:bookworm-slim base):
- `docker run --rm ghcr.io/dicklesworthstone/ubs-tools ubs --help`
- `docker run --rm -v /:/host ghcr.io/dicklesworthstone/ubs-tools bash -c "cd /host/path && ubs ."`

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `Dockerfile` (debian:bookworm-slim base, install Python + ast-grep + ripgrep + jq)
  - GitHub Actions: build + push ke GHCR
  - README "Option 4: Docker / OCI" section

## Current State
- CodeLens: tidak ada Dockerfile
- CodeLens: tidak ada GHCR publishing

## Acceptance Criteria
- [ ] `Dockerfile` di repo root
  - Base: `python:3.11-slim` (lebih kecil dari debian:bookworm-slim, sudah include Python)
  - Install: tree-sitter + grammar packages + PyYAML + watchdog + git + ripgrep
  - Multi-stage build: stage 1 install deps, stage 2 copy hanya yang perlu (smaller image)
  - Target size: <200MB (compressed)
- [ ] Multi-arch build: `linux/amd64` + `linux/arm64`
  - Gunakan `docker buildx`
- [ ] GitHub Actions workflow: `.github/workflows/docker-publish.yml`
  - Trigger: push tag `v*.*.*`
  - Build multi-arch
  - Push ke `ghcr.io/wolfvin/codelens:latest` + `ghcr.io/wolfvin/codelens:vX.Y.Z`
  - Sign dengan Cosign (Issue #12)
  - SBOM + SLSA provenance attestation
- [ ] Usage pattern:
  ```bash
  # Scan current directory
  docker run --rm -v $(pwd):/workspace ghcr.io/wolfvin/codelens scan /workspace
  
  # Scan specific path
  docker run --rm -v /path/to/project:/workspace ghcr.io/wolfvin/codelens scan /workspace
  
  # With config
  docker run --rm -v $(pwd):/workspace -v ~/.codelens:/root/.codelens ghcr.io/wolfvin/codelens scan /workspace
  ```
- [ ] Dokumentasi: README "Docker Usage" section
- [ ] Security: run as non-root user di container (create `codelens` user)
- [ ] Health check: `HEALTHCHECK CMD codelens --version`

## Implementation Notes
- Multi-arch: `docker buildx build --platform linux/amd64,linux/arm64 --tag ghcr.io/wolfvin/codelens:latest --push .`
- GHCR: gunakan `GITHUB_TOKEN` dengan `packages: write` permission
- Cosign: `cosign sign --yes ghcr.io/wolfvin/codelens@sha256:<digest>`
- SBOM: `syft ghcr.io/wolfvin/codelens:latest -o spdx-json > sbom.spdx.json`

## Priority
P2 — improve CI/CD adoption, especially untuk enterprise dengan air-gapped network.
```

---

### 📋 Issue #24 [P3] — Aider Lint Command Auto-Config + Continue.dev Rules

```markdown
**Title:** [P3] Aider lint command auto-config + Continue.dev rules integration

## Motivation
UBS auto-detect Aider (`~/.aider.conf.yml`) dan inject `lint-cmd: "ubs --fail-on-warning ."` + `auto-lint: true`. CodeLens belum support Aider integration.

Aider adalah AI pair programming tool yang popular. Dengan auto-lint, setiap Aider session run CodeLens sebelum complete task.

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `install.sh` (`configure_aider()` function, parse + modify `~/.aider.conf.yml`)
  - README "Aider-Specific Integration" section

## Current State
- CodeLens: tidak ada Aider integration
- CodeLens: tidak ada Continue.dev integration

## Acceptance Criteria
- [ ] Aider integration (saat `setup.sh` atau `install.sh`):
  - Detect `~/.aider.conf.yml` existence
  - Parse YAML
  - Add/replace `lint-cmd: "codelens smell --fail-on-warning"` (atau `codelens scan --fail-on-warning`)
  - Set `auto-lint: true`
  - Idempotent: re-run tidak duplicate entry
- [ ] Continue.dev integration:
  - Detect `~/.continue/` directory
  - Create `~/.continue/rules/codelens.md` dengan content:
    ```markdown
    ## CodeLens Quality Gate
    
    Before marking any task as complete:
    1. Run `codelens query <name>` to check for collision
    2. Run `codelens smell` to detect code smells
    3. Run `codelens secrets` to detect hardcoded secrets
    4. Fix ALL critical findings (🔥)
    5. Review warnings (⚠️) and fix if trivial
    6. Only then mark task complete
    
    If CodeLens finds critical issues, your task is NOT done.
    ```
- [ ] Document di README "Agent Integration" section

## Implementation Notes
- Aider config: `ruamel.yaml` (sudah common dependency, preserve comment + formatting)
- Continue.dev: just write markdown file ke `~/.continue/rules/`

## Priority
P3 — nice-to-have untuk Aider/Continue.dev user.
```

---

### 📋 Issue #25 [P3] — `install.sh --dry-run` + `--self-test` + `--uninstall`

```markdown
**Title:** [P3] `install.sh --dry-run` + `--self-test` + `--uninstall` flags

## Motivation
CodeLens `setup.sh` saat ini interactive, tidak ada preview mode, tidak ada self-test, tidak ada clean uninstall. User hesitant untuk run installer karena tidak tahu apa yang akan diubah.

UBS `install.sh` punya:
- `--dry-run` — print semua install action tanpa touch disk
- `--self-test` — run smoke test post-install, exit non-zero jika fail
- `--uninstall` — clean uninstall (binary + RC + config + hooks)

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `install.sh` (`--dry-run`, `--self-test`, `--uninstall` flag handler)
  - README "Installer Safety Nets" section

## Current State
- CodeLens: `setup.sh` interactive, no dry-run/self-test/uninstall

## Acceptance Criteria
- [ ] `--dry-run` flag:
  - Print semua install action (downloads, PATH edits, hook writes, cleanup)
  - Tidak touch disk
  - Tetap resolve config, detect agents, show exactly what *would* change
  - Use case: audit installer, demo ke teammate, validate CI step
- [ ] `--self-test` flag:
  - Setelah install, run `test-suite/install/run_tests.sh` (atau equivalent smoke test)
  - Exit non-zero jika smoke suite fail
  - Use case: CI/CD jobs prove installer works end-to-end
  - Note: butuh working tree dengan test suite (curl-pipe dari GitHub tidak bisa self-test)
- [ ] `--uninstall` flag:
  - Delete CodeLens binary
  - Remove shell RC snippets/aliases
  - Remove `~/.codelens/` config directory
  - Remove agent hooks (Claude Code, Cursor, Codex, dll yang di-wire saat install)
  - `--non-interactive` flag: auto-confirm semua prompt (untuk scripted uninstall)
  - Use case: clean remove CodeLens dari workstation
- [ ] Combine flags: `--dry-run --no-path-modify --skip-hooks --non-interactive` (preview everything without touching dotfiles)
- [ ] `--easy-mode --self-test --skip-hooks` (CI-friendly install yang self-test)

## Implementation Notes
- Dry-run: implement sebagai "what-if" mode, semua write operation di-ganti dengan `echo "WOULD: ..."`
- Self-test: subprocess run `python3 -m pytest test-suite/install/` atau shell script `test-suite/install/run_tests.sh`
- Uninstall: track semua file yang di-write saat install (log ke `~/.codelens/installed-files.txt`), uninstall baca log dan delete

## Priority
P3 — improve installer safety + DX, low effort high value.
```

---

### 📋 Issue #26 [P3] — uv-Powered External Analyzers (ruff, bandit, pip-audit, mypy)

```markdown
**Title:** [P3] uv-powered external analyzers (ruff, bandit, pip-audit, mypy, safety, detect-secrets)

## Motivation
CodeLens punya engine sendiri untuk Python analysis (`smell_engine.py`, `secrets_engine.py`, `vulnscan_engine.py`, dll). Tapi user yang sudah invest di tool eksternal (ruff, bandit, pip-audit, mypy) tidak bisa leverage hasil scan tersebut di CodeLens output.

UBS Python module Category 20 ("UV-POWERED EXTRA ANALYZERS") auto-invoke tool eksternal via `uvx`:
- `ruff check` — Python linter (fast, banyak rule)
- `bandit` — Python security scanner
- `pip-audit` — dependency vulnerability scanner
- `mypy` — type checker
- `safety` — dependency vulnerability scanner (alternative)
- `detect-secrets` — secret scanner (alternative ke builtin)

Hasil di-merge ke output CodeLens, sehingga 1 scan produce finding dari semua tool.

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `modules/ubs-python.sh` Category 20 (UV-POWERED EXTRA ANALYZERS)
  - README "Python Tooling (uv + CPython 3.13)" section

## Current State
- CodeLens: `vulnscan_engine.py` sudah invoke `npm audit`, `cargo audit`, `pip audit`, `govulncheck` jika available
- CodeLens: tidak invoke ruff, bandit, mypy, safety, detect-secrets

## Acceptance Criteria
- [ ] Detect `uv`/`uvx` availability (`command -v uvx`)
- [ ] If available, auto-invoke external analyzer:
  - `uvx ruff check --json <workspace>` — parse JSON, convert ke CodeLens finding
  - `uvx bandit -r <workspace> -f json` — parse JSON, convert ke CodeLens finding
  - `uvx pip-audit --format json` — parse JSON (sudah ada di `vulnscan_engine.py`, extend ke uvx)
  - `uvx mypy <workspace> --json` — parse JSON, convert ke CodeLens finding (type error)
  - `uvx safety check --json` — parse JSON (alternative ke pip-audit)
  - `uvx detect-secrets scan <workspace> --json` — parse JSON (alternative ke builtin `secrets_engine.py`)
- [ ] Flag `--skip-external-analyzers` — disable semua uvx invocation (untuk air-gapped env atau faster scan)
- [ ] Flag `--external-analyzer=<name>` — enable specific analyzer only (mis. `--external-analyzer=ruff,bandit`)
- [ ] Output: finding dengan `source: "ruff"`, `source: "bandit"`, dll — agar user tahu asal finding
- [ ] Severity normalization (port dari UBS):
  - ruff `E` → critical, `W` → warning, `C` → info
  - bandit `HIGH` → critical, `MEDIUM` → warning, `LOW` → info
  - mypy `error` → critical, `warning` → warning
- [ ] Test: mock uvx output, verify parser

## Implementation Notes
- `uvx` = `uv tool run` (uv adalah package manager Rust-based yang fast)
- Jika `uvx` tidak available, fallback ke `pip install --user <tool>` lalu invoke langsung
- Parser per tool: berbeda JSON schema, implement parser terpisah
- Untuk pip-audit: sudah ada integrasi di `vulnscan_engine.py`, extend untuk support `uvx` invocation

## Priority
P3 — nice-to-have untuk user yang sudah invest di tool eksternal, low effort (just parser + subprocess).
```

---

### 📋 Issue #27 [P3] — Pre-commit Hook Auto-Update Checksum

```markdown
**Title:** [P3] Pre-commit hook auto-update checksum (block stale checksum commit)

## Motivation
Jika CodeLens adopt lazy module download (Issue #14) atau plugin marketplace (Issue #23 opengrep doc), developer modify module tapi lupa update SHA-256 checksum di meta-runner. Release ship dengan stale checksum, user fail verify.

UBS ship `.githooks/pre-commit` yang:
- Detect jika `modules/ubs-*.sh` atau `modules/helpers/*` berubah
- Auto-update checksum di `ubs` meta-runner (via `scripts/update_checksums.sh`)
- Block commit jika checksum masih stale

## Reference
- Repo: https://github.com/Dicklesworthstone/ultimate_bug_scanner
- File referensi:
  - `.githooks/pre-commit` (shell script)
  - `scripts/update_checksums.sh` (regenerate checksum)
  - `scripts/update_checksums.py` (Python helper)
  - `scripts/update_sha256sums.sh` (update SHA256SUMS file)
  - `scripts/verify_checksums.sh` (verify)
  - README "Supply-Chain Safeguards" section

## Current State
- CodeLens: `pre_commit_hook.py` static (run scan sebelum commit), tidak auto-update checksum
- CodeLens: tidak ada lazy module download (semua bundle di repo)

## Acceptance Criteria
- [ ] Jika CodeLens adopt lazy module download (Issue #14):
  - `.githooks/pre-commit` detect perubahan di `scripts/modules/*.py` atau `scripts/helpers/*`
  - Auto-run `scripts/update_checksums.py` untuk regenerate SHA-256 di `scripts/codelens.py` (atau meta-runner)
  - Stage updated file
  - Block commit jika checksum masih stale (force developer run update script)
- [ ] Jika CodeLens adopt plugin marketplace (Issue #23 opengrep doc):
  - `.githooks/pre-commit` detect perubahan di `scripts/plugins/**`
  - Auto-update `SHA256SUMS` file
  - Sign dengan minisign jika private key available (Issue #12)
  - Block commit jika `SHA256SUMS` stale
- [ ] `scripts/update_checksums.py` — Python script yang:
  - Walk semua module/helper file
  - Compute SHA-256
  - Update embedded checksum di meta-runner (replace di `MODULE_CHECKSUMS` dict)
  - Update `SHA256SUMS` file
- [ ] `scripts/verify_checksums.sh` — shell script yang:
  - Verify semua module/helper SHA-256 match embedded checksum
  - Exit non-zero jika mismatch
- [ ] Setup: `git config core.hooksPath .githooks` saat `setup.sh`
- [ ] Dokumentasi: `CONTRIBUTING.md` section "Modifying Modules"

## Implementation Notes
- Pre-commit hook: shell script, exit non-zero untuk block commit
- Checksum update: `hashlib.sha256(file_content).hexdigest()`
- Embedded checksum: gunakan regex replace di meta-runner source code
- Untuk `SHA256SUMS`: format `<sha256>  <filepath>` per baris

## Priority
P3 — only relevant jika CodeLens adopt lazy module download atau plugin marketplace. Skip jika tidak.
```

---

## 6. Prioritas & Roadmap

### 6.1 Rekomendasi urutan eksekusi (quarter-based)

**Q3 2026 (P0 — Quick Win DX):**
1. Issue #1 — Inline suppression (`# codelens-ignore`)
2. Issue #2 — `.codelensignore` file
3. Issue #3 — `doctor` command

**Q3 2026 (P1 — Agent & Distribution):**
4. Issue #4 — 12+ agent integrations auto-detect
5. Issue #5 — Git safety guard
6. Issue #11 — Homebrew + Scoop + Nix + Docker distribution
7. Issue #12 — Release signing (minisign + Cosign)
8. Issue #13 — `sessions` command

**Q4 2026 (P1 — Test & Report):**
9. Issue #6 — HTML report
10. Issue #7 — Comparison/baseline delta
11. Issue #8 — `--staged` / `--diff` git-aware scan
12. Issue #9 — Manifest-driven test suite
13. Issue #10 — Rule quality harness dengan golden snapshot

**Q1 2027 (P2 — Engine & Pattern):**
14. Issue #14 — ast-grep rule engine integration
15. Issue #15 — Cross-language async error detection
16. Issue #16 — Resource lifecycle correlation
17. Issue #17 — `--profile` + `--category` filter
18. Issue #18 — Type narrowing helpers
19. Issue #21 — `--jobs=N` + `--only=LANG`

**Q2 2027 (P2/P3 — Output & Polish):**
20. Issue #19 — TOON format
21. Issue #20 — JSONL streaming + Beads integration
22. Issue #22 — `--skip=CSV` + `--skip-LANG=N`
23. Issue #23 — Docker image + GHCR
24. Issue #24 — Aider + Continue.dev integration
25. Issue #25 — `--dry-run` + `--self-test` + `--uninstall`
26. Issue #26 — uv-powered external analyzers
27. Issue #27 — Pre-commit hook auto-update checksum

### 6.2 Dependency graph

```
Issue #1 (inline suppression) — independen
Issue #2 (.codelensignore) — independen
Issue #3 (doctor) — independen
Issue #4 (agent integrations) ──→ Issue #5 (git safety guard, di-wire via agent hook)
                              ──→ Issue #13 (sessions, log agent yang detected)
Issue #5 (git safety guard) — independen
Issue #6 (HTML report) ──→ Issue #7 (comparison, inject ke HTML)
Issue #7 (comparison) — independen
Issue #8 (--staged/--diff) ──→ Issue #7 (combine: baseline = main, current = PR diff)
Issue #9 (manifest test) ──→ Issue #10 (rule quality harness, pakai manifest)
Issue #10 (rule quality) ──→ Issue #9 (manifest)
Issue #11 (distribution) ──→ Issue #12 (signing, sign semua release asset)
                        ──→ Issue #23 (Docker, bagian dari distribution)
Issue #12 (signing) — independen
Issue #13 (sessions) ──→ Issue #4 (agent detection, log ke session)
Issue #14 (ast-grep) ──→ Issue #15 (async error, pakai ast-grep rule pack)
                    ──→ Issue #16 (resource lifecycle, pakai ast-grep rule pack)
                    ──→ Issue #18 (type narrowing, pakai ast-grep rule pack)
Issue #15 (async error) — depend on Issue #14 (atau tree-sitter ad-hoc)
Issue #16 (resource lifecycle) — depend on Issue #14 (atau tree-sitter ad-hoc)
Issue #17 (profile + category) — independen
Issue #18 (type narrowing) — depend on Issue #14 (atau tree-sitter ad-hoc)
Issue #19 (TOON) — independen
Issue #20 (JSONL) — independen
Issue #21 (--jobs + --only) — independen
Issue #22 (--skip) ──→ Issue #17 (category filter, berkaitan)
Issue #23 (Docker) ──→ Issue #11 (distribution)
Issue #24 (Aider + Continue) ──→ Issue #4 (agent integrations)
Issue #25 (installer flags) ──→ Issue #11 (distribution)
Issue #26 (uv analyzers) — independen
Issue #27 (pre-commit checksum) ──→ Issue #14 (lazy module, jika adopt)
                               ──→ Issue #12 (signing, jika adopt)
```

### 6.3 Yang TIDAK perlu diserap dari UBS

Untuk menjaga niche CodeLens sebagai code intelligence platform (bukan pure bug scanner):

1. ❌ **Pure Bash meta-runner** — CodeLens stay Python, lebih maintainable + extensible. Bash baik untuk UBS karena scope terbatas (10 scanner module), tapi CodeLens punya 58 command + 41 engine + MCP server — terlalu complex untuk Bash.
2. ❌ **TOON encoder via `tru` binary** — implementasi Python native cukup (Issue #19), tidak perlu external Rust binary.
3. ❌ **Module lazy download dari GitHub** — CodeLens bundle semua di repo (tidak butuh lazy download). Pertimbangkan hanya jika adopt plugin marketplace (Issue #23 opengrep doc).
4. ❌ **Codex CLI v0.77.0+ format migration logic** — terlalu spesifik ke Codex, biarkan user manual migrate jika perlu.
5. ❌ **TabNine + Replit integration** — user base kecil, prioritas rendah. Fokus Claude Code + Cursor + Codex + Gemini + Windsurf + Cline + OpenCode + Aider + Continue dulu.
6. ❌ **Notebook hygiene (`.ipynb` checks)** — terlalu niche, skip kecuali ada demand tinggi.
7. ❌ **Py3.13 migration checks** — terlalu spesifik Python version, skip kecuali ada demand.
8. ❌ **UV-powered analyzers sebagai pengganti engine CodeLens** — CodeLens engine lebih sophisticated, uvx hanya untuk complement (bukan replace).

### 6.4 Synergy dengan dokumen opengrep (sebelumnya)

Beberapa issue di dokumen ini overlap dengan dokumen opengrep. Mapping:

| Issue UBS doc | Issue opengrep doc | Notes |
|---|---|---|
| #1 (inline suppression) | #4 (inline suppression) | Sama, gabungkan |
| #2 (.codelensignore) | #21 (.codelensignore) | Sama, gabungkan |
| #3 (doctor) | — | Baru, hanya di UBS doc |
| #6 (HTML report) | — | Baru, hanya di UBS doc |
| #7 (comparison delta) | #7 (baseline diff) | Mirip, gabungkan |
| #8 (--staged/--diff) | #8 (baseline-commit) | Mirip, gabungkan |
| #9 (manifest test) | #9 (test command) | Berbeda: UBS manifest untuk engine regression, opengrep test untuk rule YAML. Implementasi keduanya |
| #10 (rule quality harness) | — | Baru, hanya di UBS doc |
| #11 (distribution) | #12 (self-contained binary) | Mirip, gabungkan |
| #12 (signing) | — | Baru, hanya di UBS doc |
| #14 (ast-grep) | #1 (pattern matching) | Alternative approach: opengrep build from scratch, UBS integrate ast-grep binary. Pilih salah satu atau keduanya |
| #15 (async error) | — | Baru, hanya di UBS doc |
| #16 (resource lifecycle) | — | Baru, hanya di UBS doc |
| #17 (profile + category) | — | Baru, hanya di UBS doc |
| #18 (type narrowing) | — | Baru, hanya di UBS doc |
| #19 (TOON) | — | Baru, hanya di UBS doc |
| #20 (JSONL) | #11 (multi-output formatter) | Mirip, gabungkan |
| #21 (--jobs + --only) | — | Baru, hanya di UBS doc |
| #22 (--skip) | — | Baru, hanya di UBS doc |

**Rekomendasi:** saat create GitHub issue, reference kedua dokumen (UBS + opengrep) jika overlap. Untuk issue yang sama, pilih satu issue number (bukan duplicate).

---

## 7. Catatan Implementasi & Risiko

### 7.1 License compliance

- UBS: **MIT + OpenAI/Anthropic Rider** — boleh copy-paste code ke CodeLens (juga MIT). Tapi attribution recommended (credits di `NOTICE` atau README).
- CodeLens MIT: aman reference + port code dari UBS.
- ast-grep: **MIT license** — boleh bundle binary.
- Untuk port helper Python (`resource_lifecycle_py.py`, `type_narrowing_*.py`, dll): include attribution `# Ported from UBS (https://github.com/Dicklesworthstone/ultimate_bug_scanner) MIT license`.

### 7.2 Backward compatibility

- Semua fitur baru harus opt-in via flag atau file baru. Default behavior CodeLens tidak boleh break.
- Existing `.codelens/codelens.config.json` ignore list tetap work (`.codelensignore` adalah addition, bukan replacement).
- `setup.sh` existing tetap work; `install.sh` baru (Issue #11) adalah alternative untuk user yang mau package manager install.
- `validate` command rename (jika terjadi konflik): gunakan deprecation warning 1 version sebelum rename.

### 7.3 Performance budget

- Inline suppression (Issue #1): overhead <5% (regex check per finding line)
- `.codelensignore` (Issue #2): overhead <2% (pathspec compile sekali per scan)
- `doctor` (Issue #3): <5 detik untuk full audit
- HTML report (Issue #6): <500ms untuk generate 1000 finding
- Comparison delta (Issue #7): <100ms untuk compare 2 baseline
- `--staged`/`--diff` (Issue #8): <1s untuk <50 changed files
- ast-grep integration (Issue #14): ast-grep native cepat (Rust), overhead minimal
- `--jobs=N` (Issue #21): 2-4x speedup di 8-core machine

### 7.4 Testing strategy

- Setiap fitur baru harus ship dengan:
  1. Unit test (pytest, di `tests/unit/`)
  2. Integration test (di `tests/integration/` dengan fixture)
  3. Manifest test case (Issue #9 framework)
  4. Rule quality harness (Issue #10 framework, jika relevan)
  5. Benchmark (di `benchmarks/`) untuk performance regression
- Real-world validation: run di repo test yang sudah ada di CHANGELOG (spacedrive, redis, neovim, fastapi, exercism/python) untuk verify no regression.

### 7.5 Security consideration

- Git safety guard (Issue #5): pastikan tidak ada bypass (path traversal, env var expansion, quoted args). Test dengan 30+ destructive pattern.
- Release signing (Issue #12): private key storage aman di GitHub Secret (base64 encoded). Jangan commit private key ke repo.
- ast-grep auto-provisioning (Issue #14): verify SHA-256 binary sebelum execute. Fail closed jika mismatch.
- Agent integration (Issue #4): jangan overwrite existing config tanpa backup. Detect existing `codelens` block, replace jika outdated, preserve lainnya.

### 7.6 Documentation plan

Untuk setiap issue yang merged, update:
- `README.md` — user-facing documentation, quick start example
- `SKILL.md` — AI agent reference, command list
- `SKILL-QUICK.md` — quick reference card
- `CHANGELOG.md` — version history entry
- `references/<topic>.md` — detailed reference jika fitur complex (mis. `references/ast-grep-rule-syntax.md`, `references/codelensignore.md`)
- `AGENTS.md` — jika fitur relevant untuk AI agent workflow

---

## 8. Penutup

Analisis ini mengidentifikasi **27 issue upgrade** dari UBS ke CodeLens, dengan breakdown:
- 3 issue P0 (quick win DX: suppression, ignore file, doctor)
- 10 issue P1 (agent integration, distribution, test infrastructure, reporting)
- 9 issue P2 (engine depth, pattern matching, output format, performance)
- 5 issue P3 (polish, integrasi kecil, nice-to-have)

CodeLens sudah unggul di 9 area (MCP, AI output, guard, auto-setup, workspace detect, code intelligence, frontend, plugin, CVE) — pertahankan dan double-down di situ sebagai differentiator. Yang diserap dari UBS adalah **DX, distribution, test infrastructure, agent integration, supply-chain security** — area di mana UBS lebih matang.

UBS dan CodeLens **sama-sama AI-native**, tapi dengan niche berbeda:
- **UBS** = smoke detector (fast, multi-language bug scan, agent guardrails)
- **CodeLens** = code intelligence platform (registry, call graph, MCP, guard pre/post-write, 58 command)

CodeLens tidak boleh jadi UBS clone. Yang diserap adalah **patterns dan DX**, bukan arsitektur Bash. Setelah serapan ini, CodeLens akan menjadi **code intelligence platform yang juga punya smoke detector capability** — best of both worlds.

Eksekusi sesuai roadmap Q3 2026 → Q2 2027, dengan dependency graph sebagai panduan urutan. Patoki backward compatibility, performance budget, testing strategy, dan security consideration agar tidak break adoption existing.

---

*Dokumen ini dihasilkan dari analisa source code `Wolfvin/CodeLens` (commit `main` per 2026-06-28) dan `Dicklesworthstone/ultimate_bug_scanner` v5.3.3 (latest git tag `v5.2.75` per 2026-05-06). Semua reference path file merujuk ke struktur repo masing-masing saat tanggal analisa.*
