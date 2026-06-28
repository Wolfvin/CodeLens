# CodeLens ↔ Repomix — Analisis Fitur & Rencana Upgrade (Issue Tracker)

> **Repo yang dianalisis sebagai sumber upgrade:** `yamadashy/repomix` (https://github.com/yamadashy/repomix.git)
> **Repo target upgrade:** `Wolfvin/CodeLens` (https://github.com/Wolfvin/CodeLens)
> **Tanggal analisis:** 2026-06-28
> **Versi Repomix saat ini:** v1.15.0 (`package.json`)
> **Versi CodeLens saat ini:** v8.1 (README) / v7.2.0 (`skill.json`, `pyproject.toml`) — *catatan: terdapat inkonsistensi penomoran versi yang sudah didokumentasikan di analisis OpenTaint sebelumnya*

---

## Daftar Isi

1. [Ringkasan Eksekutif](#1-ringkasan-eksekutif)
2. [Analisis Fitur Repomix (Repo Referensi)](#2-analisis-fitur-repomix-repo-referensi)
3. [Matriks Komparasi Fitur Repomix vs CodeLens](#3-matriks-komparasi-fitur-repomix-vs-codelens)
4. [Peningkatan yang Sudah Di-adjust di CodeLens](#4-peningkatan-yang-sudah-di-adjust-di-codelens)
5. [Daftar Issue untuk Next Upgrade (Serapan dari Repomix)](#5-daftar-issue-untuk-next-upgrade-serapan-dari-repomix)
6. [Prioritas & Roadmap Eksekusi](#6-prioritas--roadmap-eksekusi)
7. [Catatan Teknis & Risiko](#7-catatan-teknis--risiko)

---

## 1. Ringkasan Eksekutif

Repomix adalah **codebase packer** — satu tool CLI TypeScript/Node.js yang fokus pada **satu hal saja**: mengubah seluruh repository menjadi satu file (XML/Markdown/JSON/Plain) yang dioptimalkan untuk konsumsi LLM. Dengan satu perintah `repomix`, output siap di-paste ke ChatGPT/Claude/Gemini/DeepSeek/dll.

**Filosofi Repomix:** *narrow and deep* — fokus pada packing + token optimization + security check, bukan code analysis. Lawan dengan CodeLens yang *wide and analytical* — 58 command, MCP server, taint analysis, plugin system.

**Posisi strategis:** CodeLens dan Repomix **tidak overlap secara langsung** — CodeLens adalah *code intelligence* (analysis), Repomix adalah *codebase packing* (context delivery). Namun Repomix punya beberapa kapabilitas yang **berguna sebagai output mode CodeLens** dan bisa diserap sebagai fitur tambahan, terutama:

1. **Multi-format AI-friendly output** (XML/Markdown/JSON/Plain) dengan struktur yang sudah teruji — CodeLens saat ini hanya punya `--format ai` (JSON) dan SARIF.
2. **Token counting per-file dan per-repository** menggunakan `gpt-tokenizer` dengan multiple encoding (`o200k_base`, `cl100k_base`, dll) — CodeLens hanya punya `--max-tokens N` truncation tanpa token counter sebenarnya.
3. **Code compression via tree-sitter** (`--compress`) — ekstrak signature class/function/interface, buang implementation → ~70% token reduction. CodeLens tidak punya ini.
4. **Remote repository processing** (`--remote user/repo`) tanpa manual clone — via GitHub archive API.
5. **Security check dengan Secretlint** yang lebih matang (preset-recommend dengan banyak rule) — CodeLens punya `secrets` engine sendiri tapi lebih sederhana.
6. **Agent Skills generation** — auto-generate `.claude/skills/<name>/` dengan SKILL.md + references/ dari codebase.
7. **Watch mode** dengan debounce 300ms dan timestamp logging — CodeLens punya `watch` tapi tanpa debounce eksplisit di README.
8. **Split output** (`--split-output 20mb`) — bagi output menjadi multiple numbered files untuk codebase besar.
9. **Output style customization** (header text, instruction file, parsable style, line numbers, remove comments, remove empty lines, truncate base64).
10. **stdin input** (`--stdin`) — pipe list file path dari `find`/`fzf`/`rg`/`fd`/`git ls-files`.

**Rekomendasi tingkat tinggi:** Serap Repomix sebagai **output mode tambahan** di CodeLens (`codelens pack` command) tanpa menggantikan fungsi analysis yang sudah ada. Ini membuat CodeLens menjadi **dual-purpose tool**: analysis (existing 58 command) + context delivery (new `pack` command). Bersama dengan serapan dari OpenTaint (taint depth) yang sudah dianalisis sebelumnya, CodeLens akan menjadi tool yang lengkap untuk AI-native code workflow.

---

## 2. Analisis Fitur Repomix (Repo Referensi)

### 2.1 Arsitektur Umum

Repomix adalah **monorepo TypeScript/Node.js** dengan struktur:

| Direktori / File | Peran |
|---|---|
| `src/index.ts` | Public API exports untuk library usage — `pack()`, `collectFiles()`, `processFiles()`, `searchFiles()`, `TokenCounter`, `runCli()`, dll |
| `src/cli/` | CLI entry: `cliRun.ts`, `cliReport.ts`, `cliSpinner.ts`, `cliTokenBudget.ts` + `actions/` (default, init, mcp, remote, watch, migration, version) |
| `src/config/` | Config system: `configSchema.ts` (valibot schema), `configLoad.ts` (multi-format loader), `defaultIgnore.ts` (164-line default ignore list), `globalDirectory.ts` |
| `src/core/packager.ts` | Core orchestrator — koordinasi file collect → process → output |
| `src/core/file/` | File pipeline: `fileCollect.ts`, `fileSearch.ts`, `fileProcess.ts`, `fileProcessContent.ts`, `fileManipulate.ts`, `fileRead.ts`, `fileTreeGenerate.ts`, `filePathSort.ts`, `fileStdin.ts`, `permissionCheck.ts`, `packageJsonParse.ts`, `truncateBase64.ts`, `workers/fileProcessWorker.ts` |
| `src/core/git/` | Git integration: `gitCommand.ts`, `gitRemoteParse.ts`, `gitRemoteHandle.ts`, `gitRemoteUrl.ts`, `gitHubArchive.ts`, `gitHubArchiveApi.ts`, `gitRepositoryHandle.ts`, `gitLogHandle.ts`, `gitDiffHandle.ts`, `archiveEntryFilter.ts` |
| `src/core/metrics/` | Token counting: `TokenCounter.ts`, `calculateMetrics.ts`, `calculateFileMetrics.ts`, `calculateOutputMetrics.ts`, `calculateGitDiffMetrics.ts`, `calculateGitLogMetrics.ts`, `metricsWorkerRunner.ts`, `tokenCountCache.ts`, `tokenEncodings.ts`, `workers/calculateMetricsWorker.ts` |
| `src/core/output/` | Output generation: `outputGenerate.ts`, `outputStyleDecorate.ts`, `outputSort.ts`, `outputSplit.ts`, `outputStyles/{markdown,xml,plain,json}Style.ts`, `outputStyleUtils.ts` |
| `src/core/output/outputStyles/` | 4 output style: XML (default), Markdown, JSON, Plain |
| `src/core/treeSitter/` | Tree-sitter for compression: `parseFile.ts`, `loadLanguage.ts`, `languageConfig.ts`, `languageParser.ts`, `queries/query{Lang}.ts` (16 language query), `parseStrategies/{Base,Css,Default,Go,Python,TypeScript,Vue}ParseStrategy.ts` |
| `src/core/skill/` | Agent Skills generation: `packSkill.ts`, `skillSectionGenerators.ts`, `skillStatistics.ts`, `skillStyle.ts`, `skillTechStack.ts`, `skillUtils.ts`, `writeSkillOutput.ts` |
| `src/core/security/` | Security: `securityCheck.ts`, `validateFileSafety.ts`, `filterOutUntrustedFiles.ts`, `workers/securityCheckWorker.ts` (uses `@secretlint/core` + `@secretlint/secretlint-rule-preset-recommend`) |
| `src/core/tokenCount/` | Token count tree: `buildTokenCountStructure.ts`, `types.ts` |
| `src/mcp/` | MCP server: `mcpServer.ts` (8 tools) + `tools/{packCodebase,packRemoteRepository,attachPackedOutput,readRepomixOutput,grepRepomixOutput,fileSystemReadFile,fileSystemReadDirectory,generateSkill,mcpToolRuntime}Tool.ts` + `prompts/packRemoteRepositoryPrompts.ts` |
| `src/shared/` | Utilities: `logger.ts`, `types.ts`, `errorHandle.ts`, `patternUtils.ts`, `sizeParse.ts`, `tmpDir.ts`, `processConcurrency.ts`, `unifiedWorker.ts`, `memoryUtils.ts`, `asyncMap.ts`, `constants.ts` |
| `browser/` | Chrome/Firefox extension (`wxt.config.ts`, `entrypoints/{background,content}.ts`, 11 locale `_locales/`) |
| `website/` | repomix.com web app: `client/` (Vue + Vite, 7 locale guide) + `server/` (Hono backend dengan Cloudflare Turnstile + rate limit + zip processor) + `compose.yml` + `compose.bundle.yml` |
| `skills/repomix-explorer/SKILL.md` | Pre-built skill untuk AI agent — natural language codebase exploration |
| `bin/repomix.cjs` | Binary entry point untuk npm install |
| `Dockerfile` | Docker image: `ghcr.io/yamadashy/repomix` |
| `flake.nix` + `flake.lock` | Nix flake untuk NixOS users |
| `llms-install.md` | LLM-friendly install instructions |
| `repomix-instruction.md` | Default instruction yang di-embed ke output |
| `repomix.config.json` | Config default repo sendiri |
| `biome.json` + `typos.toml` | Linter (Biome + Oxlint + tsgo + secretlint) + typo checker |

### 2.2 Command Surface

Repomix punya **command surface yang sangat sempit** dibanding CodeLens (58 command), namun setiap command punya banyak flag:

**Main command:** `repomix [path]` (default action — pack directory)

**Subcommand:**
- `repomix --init` — generate `repomix.config.json`
- `repomix --mcp` — run as MCP server
- `repomix --watch` / `-w` — watch mode (auto re-pack)
- `repomix --version` / `-v` — show version
- `repomix --remote <url>` — pack remote GitHub repo
- `repomix --stdin` — read file paths from stdin
- `repomix --skill-generate [name]` — generate Claude Agent Skills

**CLI flag categories (50+ flags):**

| Kategori | Jumlah flag | Contoh |
|---|---|---|
| CLI Input/Output | 7 | `--verbose`, `--quiet`, `--stdout`, `--stdin`, `--copy`, `--token-count-tree`, `--top-files-len` |
| Repomix Output | 22 | `-o`, `--style`, `--output-file-path-style`, `--parsable-style`, `--compress`, `--output-show-line-numbers`, `--no-file-summary`, `--no-directory-structure`, `--no-files`, `--remove-comments`, `--remove-empty-lines`, `--truncate-base64`, `--header-text`, `--instruction-file-path`, `--split-output`, `--include-empty-directories`, `--include-full-directory-structure`, `--no-git-sort-by-changes`, `--include-diffs`, `--include-logs`, `--include-logs-count` |
| File Selection | 5 | `--include`, `-i`/`--ignore`, `--no-gitignore`, `--no-dot-ignore`, `--no-default-patterns` |
| Remote Repository | 3 | `--remote`, `--remote-branch`, `--remote-trust-config` |
| Configuration | 3 | `-c`/`--config`, `--init`, `--global` |
| Security | 1 | `--no-security-check` |
| Token Count | 2 | `--token-count-encoding`, `--token-budget` |
| MCP | 1 | `--mcp` |
| Agent Skills | 4 | `--skill-generate`, `--skill-project-name`, `--skill-output`, `-f`/`--force` |
| Watch Mode | 1 | `-w`/`--watch` |

### 2.3 Output Format — Yang Membuat Repomix Berbeda

Repomix mendukung **4 output style** dengan struktur yang sudah teruji untuk LLM comprehension:

#### XML (default) — direkomendasikan untuk Claude/Anthropic
```xml
This file is a merged representation of the entire codebase, combining all repository files into a single document.

<file_summary>
  (Metadata and usage AI instructions)
</file_summary>

<directory_structure>
src/
  cli/
  cliOutput.ts
  index.ts
(...remaining directories)
</directory_structure>

<files>
<file path="src/index.js">
  // File contents here
</file>
(...remaining files)
</files>

<instruction>
(Custom instructions from output.instructionFilePath)
</instruction>
```

Referensi Anthropic tentang XML tags untuk prompt engineering: https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/use-xml-tags

#### Markdown — human-friendly
````markdown
This file is a merged representation of the entire codebase...

# File Summary
(Metadata and usage AI instructions)

# Repository Structure
```
src/
  cli/
    cliOutput.ts
    index.ts
```

# Repository Files

## File: src/index.js
```
// File contents here
```

# Instruction
(Custom instructions)
````

#### JSON — programmable
```json
{
  "fileSummary": {
    "generationHeader": "...",
    "purpose": "...",
    "fileFormat": "...",
    "usageGuidelines": "...",
    "notes": "..."
  },
  "userProvidedHeader": "...",
  "directoryStructure": "...",
  "files": {
    "src/index.js": "// File contents here",
    "src/utils.js": "..."
  },
  "instruction": "..."
}
```

Mendukung `jq` query untuk post-processing.

#### Plain Text — universal
```text
================================================================
File Summary
================================================================
(Metadata)

================================================================
Directory Structure
================================================================
src/
  cli/

================================================================
Files
================================================================

================
File: src/index.js
================
// File contents
```

### 2.4 Token Counting — Yang Membuat Repomix Berbeda

Repomix menggunakan `gpt-tokenizer` (npm package) untuk token counting yang akurat per-model:

**Supported encodings** (`src/core/metrics/tokenEncodings.ts`):
- `o200k_base` (default — GPT-4o, o1, o3)
- `cl100k_base` (GPT-3.5-turbo, GPT-4)
- `p50k_base` (text-davinci-003, Codex)
- `r50k_base` / `gpt2` (legacy GPT-3)

**Fitur token counting:**
- `--token-count-tree [threshold]` — tampilkan file tree dengan token count per file; threshold untuk filter file dengan ≥N tokens
- `--top-files-len <number>` — N file terbesar di summary (default 5)
- `--token-budget <number>` — exit dengan non-zero code jika output melebihi N tokens (untuk CI guard)
- `--token-count-encoding <encoding>` — pilih tokenizer model
- Per-file, per-directory, per-language, per-output token breakdown
- Cache token count (`tokenCountCache.ts`) untuk performance

**Token optimization features:**
- `--compress` — tree-sitter code compression (~70% reduction)
- `--remove-comments` — strip comments (HTML/CSS/JS/TS/Vue/Svelte/Python/PHP/Ruby/C/C#/Java/Go/Rust/Swift/Kotlin/Dart/Shell/YAML)
- `--remove-empty-lines` — buang blank lines
- `--truncate-base64` — potong base64 string panjang

### 2.5 Code Compression (`--compress`)

Repomix menggunakan **tree-sitter** untuk extract essential code structure:

**Bahasa yang didukung** (`src/core/treeSitter/languageConfig.ts` — 16 language):
- JavaScript, TypeScript (termasuk JSX/TSX)
- Python, Go, Rust, Java, C#, Ruby, PHP
- Swift, C, C++, CSS, Solidity, Vue, Dart

**Yang di-extract:**
- Class definitions dengan signature
- Function definitions dengan parameter types
- Interface definitions
- Type definitions
- Import statements
- Variable declarations (top-level)

**Yang dibuang:**
- Implementation body
- Comments
- Empty lines

**Hasil:** ~70% token reduction dengan tetap preserve semantic meaning.

**Strategi parse** (`src/core/treeSitter/parseStrategies/`):
- `TypeScriptParseStrategy` — JS/TS/JSX/TSX
- `PythonParseStrategy` — Python
- `GoParseStrategy` — Go
- `CssParseStrategy` — CSS
- `VueParseStrategy` — Vue SFC
- `DefaultParseStrategy` — fallback untuk Rust/Java/C#/Ruby/PHP/Swift/C/C++/Solidity/Dart

### 2.6 Remote Repository Processing

**Fitur:** Pack remote GitHub repo tanpa manual clone.

**Cara kerja** (`src/core/git/`):
- `gitRemoteParse.ts` — parse URL atau shorthand `user/repo`
- `gitHubArchiveApi.ts` — fetch tarball via GitHub archive API (lebih cepat dari git clone)
- `gitHubArchive.ts` — download + extract archive
- `archiveEntryFilter.ts` — filter entry pada tar extraction
- `gitRepositoryHandle.ts` — manage temp directory lifecycle

**Input yang didukung:**
```bash
repomix --remote https://github.com/user/repo
repomix --remote user/repo                          # GitHub shorthand
repomix --remote https://github.com/user/repo/tree/main    # branch URL
repomix --remote https://github.com/user/repo/commit/abc   # commit URL
repomix --remote user/repo --remote-branch main            # explicit branch
repomix --remote user/repo --remote-branch abc123          # commit hash
```

**Security:** Config file (`repomix.config.*`) di remote repo **tidak di-load by default** — mencegah untrusted repo execute code via config. Override dengan `--remote-trust-config` atau `REPOMIX_REMOTE_TRUST_CONFIG=true`.

### 2.7 Security Check (Secretlint)

Repomix menggunakan [`@secretlint/secretlint-rule-preset-recommend`](https://github.com/secretlint/secretlint) — preset dengan ~20+ rule untuk deteksi:
- AWS access key / secret key
- Google API key / service account
- Slack token
- Stripe key
- GitHub token
- Private key (RSA, SSH, PGP)
- Database URL dengan password
- Generic high-entropy string
- dll.

**Fitur:**
- Default enabled (`security.enableSecurityCheck: true`)
- Run sebagai worker thread (`securityCheckWorker.ts`) untuk non-blocking
- Output: list suspicious file dengan warning
- `--no-security-check` untuk disable
- `filterOutUntrustedFiles.ts` — auto-exclude file yang mengandung secret dari output

**MCP tool `file_system_read_file`** juga punya security validation ini — mencegah AI agent membaca file yang mengandung secret.

### 2.8 MCP Server (8 Tools)

Repomix MCP server (`src/mcp/mcpServer.ts`) menggunakan `@modelcontextprotocol/sdk` v1.29.0:

| Tool | Peran |
|---|---|
| `pack_codebase` | Pack local directory ke XML untuk AI analysis. Params: `directory`, `compress`, `includePatterns`, `ignorePatterns`, `topFilesLength` |
| `pack_remote_repository` | Fetch + pack remote GitHub repo. Params sama + `remote` |
| `attach_packed_output` | Attach existing `repomix-output.xml` untuk analysis ulang |
| `read_repomix_output` | Read packed output dengan line range (`startLine`, `endLine`) — untuk partial reading file besar |
| `grep_repomix_output` | Grep packed output dengan JavaScript RegExp + context lines (`beforeLines`, `afterLines`, `ignoreCase`) |
| `file_system_read_file` | Read file dari local FS dengan Secretlint validation |
| `file_system_read_directory` | List directory contents dengan `[FILE]`/`[DIR]` indicator |
| `generate_skill` | Generate Claude Agent Skills dari codebase |

**MCP prompts:** `pack_remote_repository` — pre-built prompt untuk AI agent.

**MCP server instructions** ter-embed di `MCP_SERVER_INSTRUCTIONS` constant.

### 2.9 Agent Skills Generation (`--skill-generate`)

Repomix bisa generate **Claude Agent Skills format** dari codebase:

**Output structure:**
```text
.claude/skills/<skill-name>/
├── SKILL.md                 # Main skill metadata & documentation
└── references/
    ├── summary.md           # Purpose, format, statistics
    ├── project-structure.md # Directory tree dengan line counts
    ├── files.md             # All file contents (grep-friendly)
    └── tech-stacks.md       # Languages, frameworks, dependencies
```

**Fitur:**
- Pilih lokasi: Personal (`~/.claude/skills/`) atau Project (`.claude/skills/`)
- Auto-generate name jika tidak diberikan (`repomix-reference-src`, `repomix-reference-repo`, `custom-name`)
- `--skill-project-name "My Project"` — override project name
- `--skill-output ./path` — non-interactive output directory
- `--force` — skip confirmation prompts
- Tech stack auto-detect dari `package.json`, `requirements.txt`, `Cargo.toml`, dll.
- Statistics: file count, line count, token count per language

**Skill module** (`src/core/skill/`):
- `packSkill.ts` — orchestrator
- `skillSectionGenerators.ts` — generate summary/structure/files section
- `skillStatistics.ts` — calculate statistics
- `skillStyle.ts` — generate SKILL.md content
- `skillTechStack.ts` — detect tech stack
- `skillUtils.ts` — name validation, description generation
- `writeSkillOutput.ts` — write to disk

### 2.10 Watch Mode

```bash
repomix --watch
repomix -w --include "src/**/*.ts"
```

**Fitur:**
- Auto re-pack on file change
- Debounce 300ms (mencegah rebuild berlebihan saat rapid save)
- Timestamp logging per rebuild
- Stop dengan `Ctrl+C`
- Menggunakan `chokidar` v5 untuk file watching
- **Constraint:** Hanya local directory — tidak kompatibel dengan `--remote`, `--stdout`, `--stdin`, `--split-output`, `--skill-generate`, `--copy`

**Watch ignore** (`src/cli/actions/watch/watchIgnore.ts`): custom ignore logic terpisah dari main ignore.

### 2.11 Split Output (`--split-output`)

Untuk codebase besar yang melebihi context window LLM:

```bash
repomix --split-output 20mb        # split jadi multiple file max 20MB
repomix --split-output 500kb
repomix --split-output 1.5mb
```

**Output:** `repomix-output.1.xml`, `repomix-output.2.xml`, dst.

**Constraint:** File dikelompokkan per top-level directory untuk maintain context. Single file/directory tidak pernah di-split across multiple output files.

### 2.12 stdin Input (`--stdin`)

Pipe list file path dari command lain:

```bash
find src -name "*.ts" -type f | repomix --stdin
git ls-files "*.ts" | repomix --stdin
grep -l "TODO" **/*.ts | repomix --stdin
rg -l "TODO|FIXME" --type ts | repomix --stdin
rg --files --type ts | repomix --stdin
fd -e ts | repomix --stdin
fzf -m | repomix --stdin                                    # interactive selection
find . -name "*.ts" -type f | fzf -m | repomix --stdin     # interactive + filter
ls src/**/*.ts | repomix --stdin
cat file-list.txt | repomix --stdin
echo -e "src/index.ts\nsrc/utils.ts" | repomix --stdin
```

**Behavior:** File dari stdin ditambahkan ke include pattern. Normal include/ignore tetap berlaku — file yang match ignore pattern tetap di-exclude.

### 2.13 Configuration System

**Multi-format config** (priority order):
1. TypeScript: `repomix.config.ts`, `.mts`, `.cts`
2. JavaScript: `repomix.config.js`, `.mjs`, `.cjs`
3. JSON: `repomix.config.json5`, `.jsonc`, `.json`

**`defineConfig` helper** untuk type-safe config:
```typescript
import { defineConfig } from 'repomix';

export default defineConfig({
  output: { filePath: 'output.xml', style: 'xml', removeComments: true },
  ignore: { customPatterns: ['**/node_modules/**', '**/dist/**'] },
});
```

**Schema validation** menggunakan Valibot (`src/config/configSchema.ts`) dengan JSON Schema auto-generated untuk dokumentasi (`website/client/scripts/generateSchema.ts`).

**Global config:** `~/.repomix/config.json` via `--init --global`.

**Config versioning:** Schema versioning — `website/client/src/public/schemas/{1.4.0,1.5.0,...,1.14.1}/schema.json` (11 version tersimpan).

### 2.14 Distribusi & Integrasi

**Install channels:**
- `npx repomix@latest` (zero-install, butuh Node.js)
- `npm install -g repomix`
- `yarn global add repomix`
- `bun add -g repomix`
- `brew install repomix` (Homebrew macOS/Linux)
- Docker: `ghcr.io/yamadashy/repomix` (`docker run -v .:/app -it --rm ghcr.io/yamadashy/repomix`)
- Nix flake: `flake.nix` untuk NixOS
- Browser extension: Chrome Web Store + Firefox Add-ons
- VS Code extension: community-maintained `Repomix Runner` oleh massdo
- Web app: repomix.com (Cloudflare Turnstile + rate limit + zip upload)

**GitHub Action:** `yamadashy/repomix/.github/actions/repomix@main` — composite action dengan input:
- `directories`, `include`, `ignore`, `output`, `compress`, `style`, `additional-args`, `repomix-version`

**Claude Code Plugins** (3 plugin resmi):
- `repomix-mcp` — MCP server plugin (foundation)
- `repomix-commands` — slash commands (`/repomix-commands:pack-local`, `/repomix-commands:pack-remote`)
- `repomix-explorer` — AI analysis agent (`/repomix-explorer:explore-local`, `/repomix-explorer:explore-remote`)

Install: `/plugin marketplace add yamadashy/repomix` → `/plugin install repomix-mcp@repomix`

**Repomix Explorer Skill** (`skills/repomix-explorer/SKILL.md`):
- Install: `npx skills add yamadashy/repomix --skill repomix-explorer`
- Support: Claude Code, Codex, Cursor, OpenClaw, GitHub Copilot, Hermes Agent
- Natural language codebase exploration

**Library usage** (`src/index.ts` exports):
- `runCli()` — programmatic CLI invocation
- `pack()`, `collectFiles()`, `processFiles()`, `searchFiles()`, `TokenCounter`, `parseFile()`
- `runSecurityCheck()`, `runInitAction()`, `runDefaultAction()`, `runRemoteAction()`
- `loadFileConfig()`, `mergeConfigs()`, `defineConfig()`, `defaultIgnoreList`

### 2.15 Tree-sitter Language Support

Repomix menggunakan `web-tree-sitter` v0.26.9 + `@repomix/tree-sitter-wasms` v0.1.17 (WASM-based, bukan native).

**16 language** dengan dedicated query (`src/core/treeSitter/queries/`):
- `queryJavascript.ts`, `queryTypescript.ts`
- `queryPython.ts`, `queryGo.ts`, `queryRust.ts`
- `queryJava.ts`, `queryCSharp.ts`, `queryPhp.ts`, `queryRuby.ts`
- `querySwift.ts`, `queryC.ts`, `queryCpp.ts`
- `queryCss.ts`, `queryVue.ts`, `queryDart.ts`, `querySolidity.ts`

### 2.16 Performance & Architecture

- **Worker thread** via `tinypool` v2.1.0 — file processing dan security check di worker thread
- **Unified worker** (`src/shared/unifiedWorker.ts`) — single entry point untuk semua worker type
- **Process concurrency** (`src/shared/processConcurrency.ts`) — CPU-aware parallelism
- **Memory utils** (`src/shared/memoryUtils.ts`) — memory tracking
- **Async map** (`src/shared/asyncMap.ts`) — concurrent map dengan limit
- **Token count cache** (`src/core/metrics/tokenCountCache.ts`) — cache token count per file content hash
- **Benchmark:** `npm run bench` (hyperfine 10 runs), `npm run bench:cores` (multi-core benchmark), `npm run memory-check`
- **Bundling support** untuk Rolldown/esbuild dengan catatan: `tinypool` harus external, WASM files harus di-copy

### 2.17 Linting & Quality

Repomix menggunakan **multi-linter stack** (paling ketat yang pernah saya lihat di OSS TypeScript):
- **Biome** v2.5 (`biome check --write`) — formatter + linter
- **Oxlint** v1.70 (`oxlint --fix`) — alternative linter untuk catch different issues
- **TypeScript Native Preview** v7 (`tsgo --noEmit`) — faster type check
- **Secretlint** v13 (`secretlint "**/*" --secretlintignore .gitignore`) — secret detection di CI
- **typos.toml** — typo checker
- **pinact** — pin GitHub Actions versions

**Test:** Vitest v4.1 dengan coverage-v8. Test directory structure mirror src/ structure — comprehensive unit + integration test.

### 2.18 Browser Extension

Chrome + Firefox extension (`browser/` directory):
- Built dengan WXT v0.x framework
- 11 locale: en, ja, ko, zh_CN, zh_TW, de, fr, es, vi, pt_BR, hi, id
- Adds "Repomix" button ke GitHub repository pages
- One-click pack dari GitHub UI

### 2.19 Web App (repomix.com)

**Stack:**
- Client: Vue + Vite, 7 locale guide (en, ja, fr, zh-cn, tr, pt-br, hi)
- Server: Hono (Cloudflare Workers/Node.js), Cloudflare Turnstile (anti-bot), rate limit (daily + per-request), zip processor

**Fitur:**
- URL input (GitHub repo) atau file/folder upload
- Customizable output format (XML/Markdown/JSON/Plain)
- Token count estimation
- Pack options UI (`composables/usePackOptions.ts`)
- Result viewer (`components/utils/resultViewer.ts`)
- File upload handler (`composables/useFileUpload.ts`, `useZipProcessor.ts`)
- Bot detection (`utils/botDetect.ts`)

**Deployment:** Docker Compose (`compose.yml`, `compose.bundle.yml`) + Google Cloud Build (`cloudbuild.yaml`)

---

## 3. Matriks Komparasi Fitur Repomix vs CodeLens

| Kapabilitas | CodeLens | Repomix | Gap CodeLens |
|---|:---:|:---:|---|
| **Core purpose** | Code intelligence (analysis) | Codebase packing (context delivery) | different niche |
| **Tech stack** | Python (tree-sitter native + regex fallback) | TypeScript/Node.js (web-tree-sitter WASM) | — |
| **Command count** | 58 command | 1 main + 8 subcommand | — (different design) |
| **Code analysis depth** | ✅ deep (taint, dataflow, smell, complexity, dead-code, dll) | ❌ | — (CodeLens unggul) |
| **Pre-write safety check** | ✅ `query` + `guard` | ❌ | — (CodeLens unggul) |
| **Plugin system** | ✅ 4 type, 3-tier discovery | ❌ | — (CodeLens unggul) |
| **MCP server** | ✅ 49 tools | ✅ 8 tools | — (CodeLens lebih luas) |
| **VS Code extension** | ✅ native | ⚠️ community-maintained (Repomix Runner) | — (CodeLens unggul) |
| **Multi-format AI output** | ⚠️ `--format ai` (JSON) + SARIF | ✅ 4 style (XML/Markdown/JSON/Plain) | **besar** |
| **Token counting** | ⚠️ `--max-tokens N` (truncation only) | ✅ `gpt-tokenizer` dengan 4+ encoding | **besar** |
| **Token count tree** | ❌ | ✅ `--token-count-tree [threshold]` | sedang |
| **Token budget CI guard** | ❌ | ✅ `--token-budget N` (exit code) | sedang |
| **Code compression** | ❌ | ✅ `--compress` (tree-sitter, ~70% reduction) | **besar** |
| **Comment removal** | ❌ | ✅ `--remove-comments` (18 language) | sedang |
| **Empty line removal** | ❌ | ✅ `--remove-empty-lines` | kecil |
| **Base64 truncation** | ❌ | ✅ `--truncate-base64` | kecil |
| **Line numbers in output** | ❌ | ✅ `--output-show-line-numbers` | kecil |
| **Custom header text** | ❌ | ✅ `--header-text` | kecil |
| **Custom instruction file** | ❌ | ✅ `--instruction-file-path` | sedang |
| **Parsable style escape** | ❌ | ✅ `--parsable-style` | kecil |
| **Split output** | ❌ | ✅ `--split-output 20mb` | **besar** |
| **Remote repo processing** | ❌ | ✅ `--remote user/repo` | **besar** |
| **stdin input** | ❌ | ✅ `--stdin` (pipe dari find/fzf/rg/fd/git) | **besar** |
| **Watch mode** | ⚠️ `watch` command (no debounce info) | ✅ `-w` (300ms debounce + timestamp) | sedang |
| **Security check** | ⚠️ `secrets` engine (custom regex) | ✅ Secretlint preset-recommend (20+ rule) | sedang |
| **Secret auto-exclude** | ❌ | ✅ `filterOutUntrustedFiles` | sedang |
| **Git diff in output** | ❌ | ✅ `--include-diffs` | sedang |
| **Git log in output** | ❌ | ✅ `--include-logs --include-logs-count N` | sedang |
| **Git sort by changes** | ❌ | ✅ `--no-git-sort-by-changes` (default: most changed first) | sedang |
| **Agent Skills generation** | ❌ | ✅ `--skill-generate` (auto SKILL.md + references/) | **besar** |
| **Tech stack detection** | ⚠️ `detect` command (framework only) | ✅ dari dependency file (package.json/Cargo.toml/dll) | sedang |
| **Library usage (programmatic)** | ❌ (CLI only) | ✅ `import { pack, runCli } from 'repomix'` | **besar** |
| **Docker image** | ❌ | ✅ `ghcr.io/yamadashy/repomix` | sedang |
| **Nix flake** | ❌ | ✅ `flake.nix` | kecil |
| **Browser extension** | ❌ | ✅ Chrome + Firefox (11 locale) | sedang |
| **Web app** | ❌ | ✅ repomix.com (Vue + Hono + Turnstile) | sedang |
| **Claude Code plugin** | ❌ | ✅ 3 plugin (mcp/commands/explorer) | sedang |
| **Multi-linter CI** | ⚠️ ruff (Python) | ✅ Biome + Oxlint + tsgo + Secretlint + typos + pinact | sedang |
| **Config format** | JSON only (`.codelens/codelens.config.json`) | ✅ TS/JS/JSON/JSON5/JSONC | sedang |
| **Global config** | ❌ | ✅ `~/.repomix/config.json` via `--init --global` | kecil |
| **Config schema versioning** | ❌ | ✅ 11 version schema JSON | kecil |
| **Default ignore list** | ⚠️ basic | ✅ 164-line comprehensive (`defaultIgnore.ts`) | sedang |
| **GitHub Action** | ⚠️ `codelens-sarif.yml` (scan + upload SARIF) | ✅ composite action dengan input | setara |
| **File tree with line counts** | ❌ | ✅ di skill generation | kecil |
| **Copy to clipboard** | ❌ | ✅ `--copy` (via `tinyclip`) | kecil |
| **Taint analysis** | ✅ AST-based path-sensitive | ❌ | — (CodeLens unggul) |
| **Cross-file analysis** | ✅ call graph, impact, dependents | ❌ | — (CodeLens unggul) |
| **Code smell detection** | ✅ 10 category | ❌ | — (CodeLens unggul) |
| **Complexity scoring** | ✅ cyclomatic + cognitive | ❌ | — (CodeLens unggul) |
| **Dead code detection** | ✅ | ❌ | — (CodeLens unggul) |
| **A11y auditing** | ✅ WCAG 2.1 | ❌ | — (CodeLens unggul) |
| **CSS deep analysis** | ✅ unused vars, orphan keyframes, z-index abuse | ❌ | — (CodeLens unggul) |
| **CVE/vuln scanning** | ✅ OSV.dev | ❌ | — (CodeLens unggul) |
| **Benchmark regression** | ✅ `run_benchmarks.py` + `check_regression.py` | ⚠️ `npm run bench` (hyperfine) | setara |
| **Compliance rules** | ✅ HIPAA, PCI-DSS (53 rules) | ❌ | — (CodeLens unggul) |
| **OWASP Top 10** | ✅ 36 rules | ❌ | — (CodeLens unggul) |
| **Translation** | ❌ | ⚠️ web guide 7 locale + browser ext 11 locale | Repomix unggul |

---

## 4. Peningkatan yang Sudah Di-adjust di CodeLens

Berikut hal yang **sudah dimiliki CodeLens** dan **tidak perlu** diserap dari Repomix, atau bahkan lebih baik dari Repomix:

### 4.1 Code Analysis Depth (Core Differentiator)

- ✅ **AST taint analysis** (`ast_taint_engine.py` 3.756 LOC) dengan CFG, path-sensitive, inter-procedural intra-file
- ✅ **Cross-file taint engine** (`crossfile_taint_engine.py` 946 LOC) — workspace-wide call graph
- ✅ **Dataflow analysis** (`dataflow_engine.py` 1.097 LOC) dengan source→sink YAML rules
- ✅ **Code smell detection** (10 category: complexity, duplication, long method, large class, dead code, feature envy, god class, shotgun surgery, data class, primitive obsession)
- ✅ **Complexity scoring** (cyclomatic + cognitive)
- ✅ **Dead code detection** dengan reference tracking
- ✅ **CSS deep analysis** (unused variables, orphan keyframes, specificity wars, z-index abuse)
- ✅ **A11y auditing** (WCAG 2.1)
- ✅ **Performance hints** (N+1 queries, sync blocking, memory leaks, expensive renders)
- ✅ **Regex audit** (ReDoS detection)

Repomix sama sekali tidak punya code analysis — hanya packing.

### 4.2 Pre-Write Safety & Guard Hooks

- ✅ `query "name"` dengan status decision rules (CREATE/EXTEND/ASK/STOP)
- ✅ `guard --pre/--post` untuk AI agent workflow
- ✅ `refactor-safe` rename/move safety check
- ✅ `impact` change impact analysis dengan risk level

### 4.3 MCP Server (49 Tools vs 8 Tools)

- ✅ 49 MCP tools (semua CodeLens command ter-expose)
- ✅ MCP spec `2025-03-26` via JSON-RPC 2.0 over stdio
- ✅ In-memory registry caching, sub-millisecond query
- ✅ Mode `--watch` untuk live update
- ✅ HTTP/SSE transport opsional via `--port`
- ✅ Resource exposure: codebase registry sebagai MCP resources

Repomix hanya 8 MCP tools (packing-related).

### 4.4 Plugin System & Marketplace Foundation

- ✅ 4 plugin types (rule_pack/engine/formatter/command)
- ✅ 3-tier discovery (project/user/built-in) dengan priority ordering
- ✅ Plugin isolation (failure tidak crash)
- ✅ Built-in OWASP Top 10 (36 rules) + Compliance (HIPAA, PCI-DSS — 53 rules)

### 4.5 VS Code Extension (Native)

- ✅ Native VS Code extension dengan Diagnostics Provider, Code Actions, Guard hooks, Health status bar
- ✅ Repomix hanya community-maintained (Repomix Runner oleh massdo)

### 4.6 Wide Command Surface (58 command)

CodeLens punya command untuk setup, pre-write, navigation, architecture, security, quality, refactoring, frontend, advanced, utility — jauh lebih luas dari Repomix (1 main + 8 subcommand).

### 4.7 CVE/Vulnerability Scanning

- ✅ `vuln-scan` command dengan OSV.dev API + SQLite cache, 9 ecosystem
- ✅ Repomix tidak punya CVE scanning

### 4.8 Benchmark & Regression

- ✅ `benchmarks/run_benchmarks.py` + `check_regression.py`
- ✅ Fixture `vulnerable_app/` dengan `ground_truth.yaml` + `clean_app/`
- ✅ GitHub Actions `codelens-benchmark.yml`

Repomix hanya punya hyperfine benchmark tanpa regression checker.

### 4.9 AI-Native Output (Existing)

- ✅ `--format ai` normalized schema: `{stats, items[], truncated, recommendations}`
- ✅ `--lite` per-command tailored output (10+ command)
- ✅ `--top N` smart default 20, sort-aware truncation
- ✅ `--max-tokens N` (meski tidak seakurat Repomix — lihat Issue R2)
- ✅ `CODELENS_AI_MODE=1` env var
- ✅ Zero-config auto-init + auto-scan
- ✅ Workspace auto-detect (walk up 10 levels)

---

## 5. Daftar Issue untuk Next Upgrade (Serapan dari Repomix)

Berikut **issue-issue konkret** untuk diajukan ke repo CodeLens, dikelompokkan per tema. Setiap issue sudah disertai: motivasi (referensi Repomix), acceptance criteria, dan scope teknis.

### Tema R-A: Multi-Format AI-Friendly Output

---

#### Issue R1 — `pack` Command dengan 4 Output Style (XML/Markdown/JSON/Plain)

**Motivasi (Repomix):** Repomix punya 4 output style yang sudah teruji untuk LLM comprehension:
- XML (default — direkomendasikan untuk Claude/Anthropic, pakai tag `<file path="...">`)
- Markdown (human-friendly, code block per file)
- JSON (programmable, support `jq` post-processing)
- Plain text (universal, separator-based)

CodeLens saat ini hanya punya `--format ai` (JSON) dan SARIF. Tidak ada mode untuk "pack codebase jadi satu file untuk LLM".

**Acceptance Criteria:**
- [ ] Command baru: `codelens pack [workspace] [--style xml|markdown|json|plain]`
- [ ] Default style: `xml` (mengikuti best practice Anthropic untuk XML tags)
- [ ] Output structure mengikuti Repomix:
  ```
  <file_summary>...</file_summary>
  <directory_structure>...</directory_structure>
  <files>
    <file path="src/index.js">...</file>
  </files>
  <instruction>...</instruction>
  ```
- [ ] Markdown style: `## File: path/to/file` + code block dengan language hint
- [ ] JSON style: `{fileSummary, directoryStructure, files: {path: content}, instruction}`
- [ ] Plain style: `===` separator + `File: path` header
- [ ] Flag `--output <file>` / `-o` untuk write ke file (default: `codelens-output.xml`)
- [ ] Flag `--stdout` untuk write ke stdout (suppress logging)
- [ ] Flag `--no-file-summary`, `--no-directory-structure`, `--no-files` (metadata-only mode)
- [ ] Flag `--output-show-line-numbers` — prefix setiap line dengan line number
- [ ] Flag `--parsable-style` — escape special char untuk valid XML/Markdown
- [ ] Flag `--header-text <text>` — custom header di awal output
- [ ] Flag `--instruction-file-path <path>` — embed custom instruction di akhir output
- [ ] Default ignore: gunakan existing `DEFAULT_IGNORE_DIRS` dari `utils.py` + tambah 164-line list dari Repomix `defaultIgnore.ts`
- [ ] MCP tool baru: `pack_codebase` exposed via MCP server

**Scope teknis:**
- Buat direktori `scripts/commands/pack.py`
- Buat `scripts/pack_engine.py` dengan 4 output style generator (port dari Repomix `outputStyles/{markdown,xml,plain,json}Style.ts`)
- Tambah `scripts/formatters/{xml,markdown,json,plain}_packer.py`
- Integrasi dengan `registry.py` (reuse file collection) atau standalone file walker
- Update `mcp_server.py` untuk expose `pack_codebase` tool

**Estimasi effort:** 2-3 minggu

---

#### Issue R2 — Accurate Token Counting dengan Multiple Encoding

**Motivasi (Repomix):** Repomix menggunakan `gpt-tokenizer` npm package untuk token counting yang akurat per-model:
- `o200k_base` (GPT-4o, o1, o3 — default)
- `cl100k_base` (GPT-3.5-turbo, GPT-4)
- `p50k_base` (text-davinci-003, Codex — legacy)
- `r50k_base` / `gpt2` (legacy GPT-3)

CodeLens saat ini hanya punya `--max-tokens N` yang melakukan truncation kasar tanpa tokenizer sebenarnya. Token count tidak akurat → AI agent tidak bisa estimate context window usage dengan tepat.

**Acceptance Criteria:**
- [ ] Tambah dependency Python: `tiktoken` (official OpenAI tokenizer, pure Python, mendukung semua encoding di atas)
- [ ] Class baru: `TokenCounter` di `scripts/token_counter.py`
  - Constructor menerima `encoding_name` (default: `o200k_base`)
  - Method `count_tokens(text: str) -> int`
  - Method `count_tokens_with_cache(text: str, file_path: str) -> int` (cache per content hash)
  - Lazy load encoding (hanya load saat pertama dipakai)
- [ ] Flag `--token-count-encoding <encoding>` untuk command `pack`, `summary`, `analyze`
  - Supported: `o200k_base`, `cl100k_base`, `p50k_base`, `r50k_base`, `gpt2`
- [ ] Flag `--token-count-tree [threshold]` untuk `pack` dan `summary`
  - Tampilkan file tree dengan token count per file
  - Threshold: hanya tampilkan file dengan ≥N tokens
- [ ] Flag `--top-files-len <number>` (default: 5) — N file terbesar di summary
- [ ] Flag `--token-budget <number>` — exit dengan non-zero code jika output melebihi N tokens (untuk CI guard)
- [ ] Update `--max-tokens N` untuk menggunakan token counter sebenarnya (bukan character count estimation)
- [ ] Cache token count di `.codelens/token_cache.json` (key: content hash, value: token count)
- [ ] Output `pack` dan `summary` menyertakan: total tokens, tokens per file, tokens per language, tokens per directory
- [ ] MCP tool `pack_codebase` menyertakan token count di response

**Scope teknis:**
- `pip install tiktoken` (add to `pyproject.toml` dependencies)
- Implementasi `TokenCounter` class dengan lazy encoding load
- Cache implementation menggunakan `hashlib.sha256` untuk content hash
- Update semua command yang menggunakan `--max-tokens` untuk pakai `TokenCounter`
- Update `--format ai` schema untuk include `token_count` field

**Estimasi effort:** 1-2 minggu

---

#### Issue R3 — Code Compression via Tree-sitter (`--compress`)

**Motivasi (Repomix):** Repomix `--compress` menggunakan tree-sitter untuk extract essential code structure (class signature, function signature, interface, type, import, top-level variable) dan membuang implementation body → ~70% token reduction dengan tetap preserve semantic meaning. Didukung 16 bahasa.

CodeLens tidak punya ini. Untuk AI agent yang ingin quick overview codebase tanpa full implementation, ini very valuable.

**Acceptance Criteria:**
- [ ] Flag `--compress` untuk command `pack` (dan `outline` sebagai enhancement)
- [ ] Tree-sitter query untuk extract:
  - Class definition dengan signature (name, base class, decorators)
  - Function definition dengan parameter types dan return type
  - Interface / Protocol / ABC definition
  - Type alias
  - Import statements
  - Top-level variable declarations (constant, enum)
- [ ] Buang: implementation body, comments, empty lines
- [ ] Bahasa yang didukung (reuse existing tree-sitter parser di CodeLens):
  - Python (native tree-sitter — sudah ada)
  - JavaScript, TypeScript, TSX (native — sudah ada)
  - Rust (native — sudah ada)
  - HTML, CSS, SCSS (native — sudah ada)
  - Vue SFC, Svelte (native — sudah ada)
  - Tambah: Java, Go, C, C++, C#, Ruby, PHP, Swift, Dart (butuh grammar baru atau gunakan fallback regex)
- [ ] Output: signature-only code dengan placeholder `// ... implementation` untuk body yang dibuang
- [ ] Statistics: original tokens vs compressed tokens vs reduction percentage
- [ ] MCP tool `pack_codebase` menerima parameter `compress: boolean`

**Contoh input → output:**
```python
# Input
class UserService:
    def __init__(self, db):
        self.db = db
    
    def get_user(self, user_id: int) -> User:
        user = self.db.query(User).filter_by(id=user_id).first()
        if not user:
            raise NotFoundError(f"User {user_id} not found")
        return user

# Output (compressed)
class UserService:
    def __init__(self, db): ...
    def get_user(self, user_id: int) -> User: ...
```

**Scope teknis:**
- Buat `scripts/compress_engine.py` dengan tree-sitter query per language
- Reuse `grammar_loader.py` untuk lazy load grammar
- Tambah tree-sitter grammar untuk Java, Go, C, C++, C#, Ruby, PHP, Swift, Dart di `setup.sh`
- Atau: gunakan `@repomix/tree-sitter-wasms` (WASM-based, cross-platform) via Python binding

**Estimasi effort:** 2-3 minggu

---

#### Issue R4 — Split Output untuk Large Codebase

**Motivasi (Repomix):** Repomix `--split-output 20mb` membagi output menjadi multiple numbered files (`repomix-output.1.xml`, `repomix-output.2.xml`, dst) untuk codebase yang melebihi context window LLM. File dikelompokkan per top-level directory untuk maintain context.

CodeLens tidak punya ini. Untuk large monorepo, output `pack` bisa melebihi 200K tokens yang adalah context window limit banyak model.

**Acceptance Criteria:**
- [ ] Flag `--split-output <size>` untuk command `pack`
- [ ] Size format: `500kb`, `1mb`, `2mb`, `1.5mb` (support decimal)
- [ ] Output: `codelens-output.1.xml`, `codelens-output.2.xml`, dst.
- [ ] File dikelompokkan per top-level directory (single file/directory tidak pernah di-split across multiple output)
- [ ] Setiap output file punya self-contained header dengan metadata: part number, total parts, source directory
- [ ] Log di terminal: "Split into N files. Largest: codelens-output.3.xml (1.8MB)"
- [ ] Constraint: tidak kompatibel dengan `--stdout`, `--copy` (sesuai Repomix behavior)
- [ ] Support combined dengan `--compress` dan `--token-budget`

**Scope teknis:**
- Tambah `scripts/output_splitter.py`
- Grouping logic: collect files per top-level directory, hitung kumulatif size, split saat exceed threshold
- Size parser: port dari Repomix `src/shared/sizeParse.ts`

**Estimasi effort:** 3-5 hari

---

### Tema R-B: Input Flexibility

---

#### Issue R5 — Remote Repository Processing (`--remote`)

**Motivasi (Repomix):** Repomix `--remote user/repo` bisa pack remote GitHub repo tanpa manual `git clone`. Menggunakan GitHub archive API (lebih cepat dari git clone karena hanya download tarball, bukan history). Support branch, tag, commit hash, URL shorthand.

CodeLens tidak punya ini. User harus manual `git clone` dulu sebelum `codelens scan`. Untuk AI agent yang ingin analyze repo eksternal, ini extra step yang bisa dieliminasi.

**Acceptance Criteria:**
- [ ] Flag `--remote <url>` untuk command `pack` dan `scan`
- [ ] Input yang didukung:
  - Full URL: `https://github.com/user/repo`
  - Shorthand: `user/repo`
  - Branch URL: `https://github.com/user/repo/tree/main`
  - Commit URL: `https://github.com/user/repo/commit/abc123`
- [ ] Flag `--remote-branch <name>` — specific branch/tag/commit
- [ ] Flag `--remote-trust-config` — trust config file dari remote repo (default: false untuk security)
- [ ] Implementasi: download tarball via GitHub archive API (`https://api.github.com/repos/{owner}/{repo}/tarball/{ref}`)
- [ ] Extract ke temp directory (`/tmp/codelens-remote-{hash}/`)
- [ ] Run `pack` atau `scan` di temp directory
- [ ] Cleanup temp directory setelah selesai
- [ ] Support GitHub Enterprise via `GITHUB_API_URL` env var
- [ ] Rate limit handling: exponential backoff + retry
- [ ] Auth: support `GITHUB_TOKEN` env var untuk higher rate limit
- [ ] MCP tool baru: `pack_remote_repository` dengan params: `remote`, `compress`, `includePatterns`, `ignorePatterns`, `topFilesLength`

**Scope teknis:**
- Buat `scripts/remote_repo_handler.py` (port dari Repomix `src/core/git/`)
- Gunakan `requests` atau `urllib` untuk HTTP
- Gunakan `tarfile` stdlib untuk extract
- Git URL parse: port dari Repomix `gitRemoteParse.ts` (atau gunakan `git-url-parse` npm package equivalent di Python — `giturlparse`)

**Estimasi effort:** 1-2 minggu

---

#### Issue R6 — stdin Input (`--stdin`)

**Motivasi (Repomix):** Repomix `--stdin` memungkinkan pipe list file path dari command lain:
```bash
find src -name "*.ts" | repomix --stdin
git ls-files "*.ts" | repomix --stdin
rg -l "TODO|FIXME" | repomix --stdin
fzf -m | repomix --stdin
```

CodeLens `scan` dan `query` tidak punya ini. User harus specify `--include` glob pattern. Untuk AI agent yang ingin analyze file hasil grep/fzf, harus write ke temp file dulu.

**Acceptance Criteria:**
- [ ] Flag `--stdin` untuk command `pack`, `scan`, `query`, `search`
- [ ] Baca file paths dari stdin, satu per line
- [ ] Support relative dan absolute path
- [ ] Auto-resolve dan deduplicate
- [ ] File dari stdin ditambahkan ke include pattern (normal include/ignore tetap berlaku — file yang match ignore tetap di-exclude)
- [ ] Support kombinasi dengan `--include` dan `--ignore`
- [ ] Error handling: skip file yang tidak exist dengan warning
- [ ] Contoh penggunaan terdokumentasi di README:
    ```bash
    # Pipe dari find
    find src -name "*.py" -type f | codelens pack --stdin
    
    # Pipe dari git
    git ls-files "*.ts" | codelens scan --stdin
    
    # Pipe dari ripgrep (file dengan pattern tertentu)
    rg -l "TODO|FIXME" --type py | codelens pack --stdin --compress
    
    # Interactive selection dengan fzf
    find . -name "*.py" -type f | fzf -m | codelens pack --stdin
    
    # Dari file list
    cat file-list.txt | codelens pack --stdin
    ```

**Scope teknis:**
- Tambah `scripts/stdin_reader.py`
- Hook ke `pack_engine.py`, `registry.py` (untuk scan), `search_engine.py`
- Path resolution: `os.path.abspath()` relative ke cwd

**Estimasi effort:** 3-5 hari

---

### Tema R-C: Context Enrichment

---

#### Issue R7 — Git Diff & Git Log in Output

**Motivasi (Repomix):** Repomix menyertakan git context di output:
- `--include-diffs` — working tree + staged changes sebagai diff section
- `--include-logs` — commit history dengan messages dan changed files (default 50 commit)
- `--include-logs-count N` — specific commit count
- `--no-git-sort-by-changes` — default sort file by git change frequency (most changed first)

CodeLens tidak punya ini. Untuk AI agent yang analyze codebase, git context (recent changes, commit messages) sangat valuable untuk understand evolution dan current work-in-progress.

**Acceptance Criteria:**
- [ ] Flag `--include-diffs` untuk command `pack`
  - Output section: `<git_diffs>` (atau `## Git Diffs` di markdown)
  - Subsection: working tree diff + staged diff
- [ ] Flag `--include-logs` untuk command `pack`
  - Output section: `<git_logs>` (atau `## Git Logs` di markdown)
  - Format per commit: `commit_hash | date | author | message\n  changed_files: [file1, file2, ...]`
- [ ] Flag `--include-logs-count <N>` (default: 50)
- [ ] Flag `--no-git-sort-by-changes` — disable sort by git change frequency
- [ ] Default behavior: sort file by git change frequency (most changed first) — file yang sering berubah lebih penting untuk AI analyze
- [ ] `--include-logs-count 0` untuk disable logs
- [ ] Integrasi dengan `ownership_engine.py` yang sudah ada (git blame)

**Scope teknis:**
- Buat `scripts/git_context_engine.py` (atau extend `ownership_engine.py`)
- Subprocess `git diff`, `git diff --staged`, `git log --name-only --format=...`
- Sort logic: `git log --name-only --format=` → count per file → sort descending
- Update `pack_engine.py` untuk include git section

**Estimasi effort:** 1 minggu

---

#### Issue R8 — Agent Skills Generation (`--skill-generate`)

**Motivasi (Repomix):** Repomix `--skill-generate` menghasilkan Claude Agent Skills format dari codebase:
```text
.claude/skills/<skill-name>/
├── SKILL.md                 # Main skill metadata & documentation
└── references/
    ├── summary.md           # Purpose, format, statistics
    ├── project-structure.md # Directory tree dengan line counts
    ├── files.md             # All file contents (grep-friendly)
    └── tech-stacks.md       # Languages, frameworks, dependencies
```

CodeLens sudah punya `SKILL.md` dan `SKILL-QUICK.md` untuk skill statis sendiri, tapi tidak punya tool untuk **generate skill dari codebase lain**. Ini very valuable untuk AI agent yang ingin reference implementation dari repo eksternal.

**Acceptance Criteria:**
- [ ] Flag `--skill-generate [name]` untuk command `pack`
- [ ] Output structure:
  ```
  .claude/skills/<skill-name>/
  ├── SKILL.md
  └── references/
      ├── summary.md
      ├── project-structure.md
      ├── files.md
      └── tech-stacks.md
  ```
- [ ] `SKILL.md` content: skill metadata (name, description), file/line/token counts, overview, usage instructions
- [ ] `summary.md`: purpose, usage guidelines, statistics breakdown per file type dan language
- [ ] `project-structure.md`: directory tree dengan line counts per file
- [ ] `files.md`: all file contents dengan syntax highlighting headers, optimized for grep-friendly searching (file path sebagai header)
- [ ] `tech-stacks.md`: auto-detected tech stack per package dari dependency file (`package.json`, `requirements.txt`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `pom.xml`, `build.gradle`, `gemspec`, dll.)
- [ ] Pilih lokasi output:
  - Personal: `~/.claude/skills/`
  - Project: `.claude/skills/`
  - Custom: `--skill-output <path>`
- [ ] Auto-generate name jika tidak diberikan: `codelens-reference-{src|repo}` atau normalize custom name ke kebab-case
- [ ] Flag `--skill-project-name "My Project"` — override project name di description
- [ ] Flag `--force` / `-f` — skip overwrite confirmation
- [ ] Support combined dengan `--remote` (generate skill dari remote repo) dan `--compress` (compressed skill)
- [ ] Support combined dengan `--include` dan `--ignore`
- [ ] MCP tool baru: `generate_skill` dengan params: `directory`, `skillName`, `skillProjectName`, `compress`, `includePatterns`, `ignorePatterns`

**Scope teknis:**
- Buat `scripts/skill_generator.py` (port dari Repomix `src/core/skill/`)
- Tech stack detector: extend `framework_detect.py` yang sudah ada
- Skill name validator: kebab-case, no special char
- Statistics calculator: reuse `token_counter.py` (Issue R2)

**Estimasi effort:** 2 minggu

---

### Tema R-D: Security & Quality

---

#### Issue R9 — Secretlint Integration untuk Security Check

**Motivasi (Repomix):** Repomix menggunakan `@secretlint/secretlint-rule-preset-recommend` — preset dengan ~20+ rule untuk deteksi AWS key, Google API key, Slack token, Stripe key, GitHub token, private key, database URL dengan password, generic high-entropy string, dll. Lebih komprehensif dari regex-based secret detection.

CodeLens punya `secrets` engine sendiri (regex-based) tapi lebih sederhana. False positive di URI scheme sudah diperbaiki (CHANGELOG v6.3.2), tapi coverage rule masih terbatas.

**Acceptance Criteria:**
- [ ] Opsi 1: Tambah Python binding untuk Secretlint (via Node.js subprocess) — jika praktis
- [ ] Opsi 2: Port rule Secretlint preset-recommend ke Python regex/YAML rule di CodeLens
  - AWS: `AKIA[0-9A-Z]{16}`, `aws_secret_access_key`, dll.
  - Google: `AIza[0-9A-Za-z\-_]{35}`, `ya29.[0-9A-Za-z\-_]+`
  - Slack: `xox[baprs]-[0-9A-Za-z-]+`
  - Stripe: `sk_live_[0-9a-zA-Z]{24}`, `rk_live_[0-9a-zA-Z]{24}`
  - GitHub: `gh[pousr]_[A-Za-z0-9_]{36,255}`, `github_pat_[A-Za-z0-9_]{82}`
  - Private key: `-----BEGIN (RSA|EC|OPENSSH|PGP|DSA) PRIVATE KEY-----`
  - Database URL: `(postgres|mysql|mongodb)://[^:]+:[^@]+@`
  - Generic high-entropy: Shannon entropy > 4.5 untuk string >20 char
- [ ] Flag `--no-security-check` untuk disable
- [ ] Default: enabled
- [ ] Output: list suspicious file dengan warning
- [ ] Auto-exclude file yang mengandung secret dari `pack` output (`filter_out_untrusted_files` equivalent)
- [ ] Security check run sebagai background thread untuk non-blocking
- [ ] MCP tool `file_system_read_file` (Issue R10) juga punya security validation ini

**Scope teknis:**
- Extend `secrets_engine.py` dengan rule baru
- Atau: integrasi dengan `detect-secrets` (Python library dari Yelp) sebagai alternative
- Entropy calculator: `math.log2(len(set(char))) * len(string)` atau Shannon entropy
- Filter logic di `pack_engine.py` untuk exclude file dengan secret

**Estimasi effort:** 1-2 minggu

---

#### Issue R10 — File System MCP Tools (`file_system_read_file`, `file_system_read_directory`)

**Motivasi (Repomix):** Repomix MCP server punya 2 tool filesystem:
- `file_system_read_file` — read file dengan Secretlint validation (prevent baca file dengan secret)
- `file_system_read_directory` — list directory dengan `[FILE]`/`[DIR]` indicator

CodeLens MCP server (49 tools) tidak punya raw filesystem access — semua tool beroperasi pada registry (post-scan). Untuk AI agent yang ingin inspect file spesifik tanpa full scan, ini missing.

**Acceptance Criteria:**
- [ ] MCP tool baru: `file_system_read_file`
  - Params: `path` (absolute path)
  - Security: validate dengan Secretlint (Issue R9) — refuse baca file dengan secret
  - Path validation: refuse relative path, refuse path traversal (`..`)
  - Output: file content + metadata (size, line count, language detected)
- [ ] MCP tool baru: `file_system_read_directory`
  - Params: `path` (absolute path)
  - Output: list dengan `[FILE]` / `[DIR]` indicator, sorted (directory first, then file alphabetical)
  - Path validation: same as above
- [ ] Tambah ke `mcp_server.py` `_TOOL_DEFINITIONS`
- [ ] Dokumentasi: update `references/agent-integration.md` dengan 2 tool baru

**Scope teknis:**
- Tambah 2 entry di `_TOOL_DEFINITIONS` di `mcp_server.py`
- Handler function dengan security check (reuse `secrets_engine.py` Issue R9)
- Path validation: `os.path.isabs()`, `os.path.realpath()` resolve traversal

**Estimasi effort:** 3-5 hari

---

### Tema R-E: Distribution & DX

---

#### Issue R11 — Library Usage (Programmatic Python API)

**Motivasi (Repomix):** Repomix expose public API via `src/index.ts`:
```javascript
import { runCli, pack, collectFiles, processFiles, searchFiles, TokenCounter, parseFile } from 'repomix';
```

CodeLens saat ini CLI-only — `pyproject.toml` line 65-67 secara eksplisit mengatakan: *"Entry point removed — codelens is run directly via python3 codelens.py. The scripts/ directory uses sys.path-based imports, not a proper Python package."*

Ini sudah dibahas di analisis OpenTaint sebelumnya (Issue D2). Untuk Repomix-specific, setelah package refactor (Issue D2 OpenTaint analysis), perlu expose public API.

**Acceptance Criteria:**
- [ ] Setelah Issue D2 (Python package entry point) selesai, expose public API di `codelens/__init__.py`:
  ```python
  from codelens import (
      # Core
      pack, scan, query,
      # File
      collect_files, process_files, search_files,
      # Token
      TokenCounter,
      # Tree-sitter
      parse_file,
      # Config
      load_config, merge_configs, define_config, DEFAULT_IGNORE_LIST,
      # Security
      run_security_check,
      # CLI
      run_cli,
  )
  ```
- [ ] Type hints lengkap untuk semua public function
- [ ] Dokumentasi: `references/library-usage.md` dengan example
- [ ] Example usage:
  ```python
  from codelens import pack, TokenCounter
  
  # Pack codebase programmatically
  result = pack('/path/to/project', style='xml', compress=True)
  
  # Count tokens
  counter = TokenCounter('o200k_base')
  await counter.init()
  tokens = counter.count_tokens(result.content)
  ```
- [ ] Publish ke PyPI (sudah direncanakan di Issue D2 OpenTaint analysis)
- [ ] Semver guarantee: breaking change di public API = major version bump

**Scope teknis:**
- Subset dari Issue D2 (OpenTaint analysis)
- Tambah `codelens/__init__.py` dengan exports
- Tambah `codelens/py.typed` marker untuk PEP 561 (type information)
- Type stub generation jika perlu

**Estimasi effort:** 1 minggu (setelah Issue D2 OpenTaint analysis selesai)

---

#### Issue R12 — Docker Image & Nix Flake

**Motivasi (Repomix):** Repomix distribusi via:
- Docker: `ghcr.io/yamadashy/repomix` (`docker run -v .:/app -it --rm ghcr.io/yamadashy/repomix`)
- Nix flake: `flake.nix` untuk NixOS users

CodeLens tidak punya keduanya. Hanya `git clone` + `bash setup.sh`.

**Acceptance Criteria:**
- [ ] `Dockerfile` di root:
  ```dockerfile
  FROM python:3.11-slim
  WORKDIR /app
  COPY . /app
  RUN bash setup.sh
  ENTRYPOINT ["python3", "/app/scripts/codelens.py"]
  ```
- [ ] GitHub Actions workflow: `publish-docker.yaml`
  - Build image: `ghcr.io/wolfvin/codelens:latest`, `ghcr.io/wolfvin/codelens:v8.x.y`, `ghcr.io/wolfvin/codelens:v8`
  - Multi-arch: `linux/amd64`, `linux/arm64`
  - Trigger: push tag `v*.*.*`
- [ ] Dokumentasi Docker usage:
  ```bash
  # Scan current directory
  docker run --rm -v $(pwd):/workspace ghcr.io/wolfvin/codelens:latest scan /workspace
  
  # Pack dengan output
  docker run --rm -v $(pwd):/workspace -v $(pwd)/output:/output \
    ghcr.io/wolfvin/codelens:latest pack /workspace -o /output/codelens-output.xml
  ```
- [ ] `flake.nix` untuk NixOS:
  ```nix
  {
    description = "CodeLens - AI-native code intelligence";
    inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    outputs = { self, nixpkgs }: {
      packages.x86_64-linux.codelens = derivation { ... };
    };
  }
  ```
- [ ] Tambah ke README Installation section

**Scope teknis:**
- Buat `Dockerfile` (slim image based on `python:3.11-slim`)
- Setup GHCR dengan GitHub Actions
- Buat `flake.nix` (butuh Nix expertise — bisa minta kontribusi community)

**Estimasi effort:** 1 minggu

---

#### Issue R13 — Multi-Format Config File (TS/JS/JSON/JSON5/JSONC)

**Motivasi (Repomix):** Repomix support multi-format config (priority order):
1. TypeScript: `repomix.config.ts`, `.mts`, `.cts`
2. JavaScript: `repomix.config.js`, `.mjs`, `.cjs`
3. JSON: `repomix.config.json5`, `.jsonc`, `.json`

Plus `defineConfig` helper untuk type-safe config.

CodeLens hanya support JSON (`.codelens/codelens.config.json`).

**Acceptance Criteria:**
- [ ] Support config file di workspace root:
  - `codelens.config.json` (existing — backward compat)
  - `codelens.config.jsonc` (JSON with comments)
  - `codelens.config.json5` (JSON5 — unquoted keys, trailing comma, comment)
  - `codelens.config.toml` (TOML — Python-native, lebih idiomatic daripada JS/TS untuk Python project)
  - `codelens.config.py` (Python — dengan `define_config()` helper)
- [ ] Priority order: `.py` > `.toml` > `.json5` > `.jsonc` > `.json`
- [ ] `define_config()` helper di Python:
  ```python
  from codelens import define_config
  
  config = define_config(
      output={"style": "xml", "compress": True},
      ignore={"custom_patterns": ["**/node_modules/**"]},
  )
  ```
- [ ] `codelens init --format <format>` — pilih format saat init
- [ ] Config schema validation (reuse existing logic + tambah validation untuk TOML/Python)
- [ ] Global config: `~/.codelens/config.json` via `codelens init --global`
- [ ] Config schema versioning: embed `schema_version` field, migrasi otomatis jika version mismatch
- [ ] Dokumentasi: update `references/configuration.md` dengan semua format

**Scope teknis:**
- Tambah `tomllib` (Python 3.11+ stdlib) atau `tomli` untuk TOML parsing
- Tambah `json5` package untuk JSON5
- Tambah `pydantic` atau reuse existing validation untuk schema
- Python config: `importlib.util.spec_from_file_location()` untuk load `.py` config

**Estimasi effort:** 1-2 minggu

---

#### Issue R14 — Watch Mode Enhancement (Debounce + Timestamp)

**Motivasi (Repomix):** Repomix watch mode (`-w` / `--watch`):
- Debounce 300ms (mencegah rebuild berlebihan saat rapid save)
- Timestamp logging per rebuild
- Menggunakan `chokidar` v5
- Constraint: tidak kompatibel dengan `--remote`, `--stdout`, `--stdin`, `--split-output`, `--skill-generate`, `--copy`

CodeLens sudah punya `watch` command tapi:
- Tidak ada eksplisit debounce time di README atau code
- Tidak ada timestamp logging
- Tidak ada constraint documentation

**Acceptance Criteria:**
- [ ] Eksplisitkan debounce time: 300ms (configurable via `--debounce <ms>`)
- [ ] Timestamp logging per rebuild: `[2026-06-28 10:30:45] Rebuild triggered. Files changed: 3`
- [ ] Tambah flag `--watch-ignore <patterns>` untuk ignore pattern khusus watch (terpisah dari main ignore)
- [ ] Dokumentasi constraint: `watch` tidak kompatibel dengan `--remote`, `--stdout`, `--stdin`, `--split-output`, `--skill-generate`
- [ ] Update `watch` command untuk support multiple mode:
  - `codelens watch` — watch + auto re-scan (existing behavior)
  - `codelens watch --pack` — watch + auto re-pack (new, untuk live LLM context update)
  - `codelens watch --serve` — watch + MCP server (existing `serve --watch`)
- [ ] Performance: incremental scan hanya untuk changed file (sudah ada, pastikan berfungsi)
- [ ] Cleanup: stop watcher dengan `Ctrl+C` graceful shutdown

**Scope teknis:**
- Update `scripts/commands/watch.py`
- Tambah debounce logic dengan `threading.Timer` atau `asyncio`
- Tambah timestamp formatter
- Update `framework_detect.py` jika perlu

**Estimasi effort:** 3-5 hari

---

### Tema R-F: Output Polish

---

#### Issue R15 — Comment Removal & Empty Line Removal

**Motivasi (Repomix):** Repomix punya:
- `--remove-comments` — strip comments di 18 bahasa (HTML, CSS, JS, TS, Vue, Svelte, Python, PHP, Ruby, C, C#, Java, Go, Rust, Swift, Kotlin, Dart, Shell, YAML)
- `--remove-empty-lines` — buang blank lines

CodeLens tidak punya ini. Untuk AI agent dengan strict token budget, ini penting.

**Acceptance Criteria:**
- [ ] Flag `--remove-comments` untuk command `pack`
- [ ] Support 18 bahasa (port dari Repomix `@repomix/strip-comments` atau gunakan Python `strip-comments` library)
- [ ] Conservative removal (tidak hapus comment di tengah expression, hanya standalone comment)
- [ ] Flag `--remove-empty-lines` untuk command `pack`
- [ ] Combined dengan `--compress` (compress dulu, lalu remove comments/empty lines jika masih ada)
- [ ] Statistics: original tokens vs reduced tokens
- [ ] Test: pastikan tidak menghapus code yang valid

**Scope teknis:**
- Tambah `scripts/comment_remover.py` (port dari `@repomix/strip-comments`)
- Atau gunakan `libcst` untuk Python, regex untuk bahasa lain
- Hook ke `pack_engine.py` sebelum output generation

**Estimasi effort:** 1 minggu

---

#### Issue R16 — Copy to Clipboard & Convenience Flags

**Motivasi (Repomix):** Repomix punya convenience flags:
- `--copy` — copy output ke system clipboard via `tinyclip`
- `--truncate-base64` — truncate base64 string panjang
- `--include-empty-directories` — include folder kosong di directory structure
- `--include-full-directory-structure` — show full tree termasuk file yang tidak match `--include`

CodeLens tidak punya ini.

**Acceptance Criteria:**
- [ ] Flag `--copy` untuk command `pack` — copy output ke clipboard
  - Linux: `xclip` atau `xsel` subprocess
  - macOS: `pbcopy` subprocess
  - Windows: `clip` subprocess
  - Fallback: warning jika clipboard tidak tersedia
- [ ] Flag `--truncate-base64` — truncate base64 string >1000 char jadi `[base64 truncated, N chars total]`
- [ ] Flag `--include-empty-directories` — include folder kosong di directory tree
- [ ] Flag `--include-full-directory-structure` — show full tree termasuk file yang di-exclude
- [ ] Flag `--output-file-path-style <style>` — `target-relative` (default) atau `cwd-relative`

**Scope teknis:**
- Tambah `scripts/clipboard.py` dengan platform detection
- Tambah `scripts/base64_truncator.py`
- Update `file_tree_generate.py` untuk empty dir + full tree mode
- Update `pack_engine.py` untuk path style

**Estimasi effort:** 3-5 hari

---

## 6. Prioritas & Roadmap Eksekusi

Roadmap diurutkan berdasarkan **impact** dan **dependency**:

### Fase R-1 — Core Packing Capability (Q3 2026, ~5-7 minggu)

| Issue | Effort | Dependency | Impact |
|---|---|---|---|
| **R1** `pack` command dengan 4 output style | 2-3 minggu | — | **kritis** (foundation) |
| **R2** Accurate token counting | 1-2 minggu | — | **kritis** (enable R3, R4) |
| **R3** Code compression via tree-sitter | 2-3 minggu | R2 (soft) | tinggi |
| **R4** Split output | 3-5 hari | R1 | sedang |

### Fase R-2 — Input Flexibility (Q4 2026, ~2-3 minggu)

| Issue | Effort | Dependency | Impact |
|---|---|---|---|
| **R5** Remote repo processing | 1-2 minggu | R1 | tinggi |
| **R6** stdin input | 3-5 hari | R1 | sedang |

### Fase R-3 — Context Enrichment (Q4 2026, ~3 minggu)

| Issue | Effort | Dependency | Impact |
|---|---|---|---|
| **R7** Git diff & log in output | 1 minggu | R1 | sedang |
| **R8** Agent Skills generation | 2 minggu | R1, R2 | tinggi |

### Fase R-4 — Security & Quality (Q1 2027, ~2-3 minggu)

| Issue | Effort | Dependency | Impact |
|---|---|---|---|
| **R9** Secretlint integration | 1-2 minggu | — | sedang |
| **R10** File system MCP tools | 3-5 hari | R9 | sedang |

### Fase R-5 — Distribution & DX (Q1 2027, ~3-4 minggu)

| Issue | Effort | Dependency | Impact |
|---|---|---|---|
| **R11** Library usage (programmatic API) | 1 minggu | OpenTaint Issue D2 | tinggi |
| **R12** Docker image & Nix flake | 1 minggu | — | sedang |
| **R13** Multi-format config | 1-2 minggu | — | sedang |
| **R14** Watch mode enhancement | 3-5 hari | — | kecil |

### Fase R-6 — Output Polish (Q2 2027, ~2 minggu)

| Issue | Effort | Dependency | Impact |
|---|---|---|---|
| **R15** Comment & empty line removal | 1 minggu | R1 | kecil |
| **R16** Copy to clipboard & convenience | 3-5 hari | R1 | kecil |

### Total Estimasi: ~15-20 minggu (~4-5 bulan)

**Quick win pertama:** Issue R4 (split output) — 3-5 hari, dapat selesai paralel dengan R1.

**Highest impact:** Issue R1 (`pack` command) — ini foundation untuk semua issue Repomix-related lainnya. Setelah R1 selesai, R2-R16 bisa dikerjakan secara bertahap.

---

## 7. Catatan Teknis & Risiko

### 7.1 Risiko Teknis

1. **Tree-sitter grammar coverage** — Repomix menggunakan WASM-based `@repomix/tree-sitter-wasms` yang cross-platform. CodeLens saat ini pakai native Python tree-sitter binding. Untuk match 16 bahasa Repomix, perlu tambah grammar untuk Java, Go, C, C++, C#, Ruby, PHP, Swift, Dart, Solidity.
   - **Mitigasi:** Tambah grammar installation di `setup.sh`. Atau pertimbangkan pakai WASM-based tree-sitter via `tree-sitter-wasm` Python binding.

2. **Token counter accuracy** — `tiktoken` adalah library official OpenAI tapi hanya support GPT family. Untuk Claude/Gemini/Llama, tidak ada tokenizer yang official. Repomix juga hanya support GPT family.
   - **Mitigasi:** Document bahwa token count adalah estimate (GPT-4o baseline). Untuk model lain, deviation ~5-10%.

3. **Remote repo processing security** — Download tarball dari URL arbitrary ada risiko (zip bomb, malicious content).
   - **Mitigasi:** Hanya support github.com (dan GitHub Enterprise via `GITHUB_API_URL`). Validate URL. Size limit untuk tarball (default 100MB). Scan dengan Secretlint setelah download.

4. **Config file code execution** — Python config (`codelens.config.py`) bisa execute arbitrary code.
   - **Mitigasi:** Default: hanya load JSON/TOML/JSON5. Python config butuh `--trust-python-config` flag eksplisit (sama seperti Repomix `--remote-trust-config`).

5. **Compress false positive** — Tree-sitter compression bisa merusak code semantic jika query tidak akurat.
   - **Mitigasi:** Test extensively per bahasa. Conservative query (hanya extract yang pasti safe). Dokumentasi: `--compress` untuk overview, bukan untuk re-implementasi.

### 7.2 Risiko Non-Teknis

1. **Scope creep** — Repomix adalah tool sempit (packing). CodeLens adalah tool luas (analysis). Menambah `pack` command bisa blur positioning.
   - **Mitigasi:** Positioning: `pack` adalah output mode tambahan, bukan core. Core CodeLens tetap analysis. Tagline: "AI-native code intelligence with context delivery".

2. **Maintenance burden** — 16 issue Repomix-related + 16 issue OpenTaint-related = 32 issue total. Butuh prioritization yang jelas.
   - **Mitigasi:** Roadmap bertahap. Fokus pada foundation (R1, R2) dulu sebelum enhancement. Setiap issue dirilis sebagai minor version.

3. **Competitive overlap dengan Repomix** — Jika CodeLens `pack` command terlalu mirip Repomix, user bisa pilih salah satu.
   - **Mitigasi:** Differentiate: CodeLens `pack` terintegrasi dengan analysis (bisa pack hasil `dataflow`, `taint`, `smell` finding ke output). Repomix hanya pack raw code. Ini unique value proposition.

### 7.3 Yang TIDAK Perlu Diserap dari Repomix

Beberapa hal Repomix tidak relevant atau inferior untuk CodeLens:

1. **Browser extension** — Repomix punya Chrome/Firefox extension untuk one-click pack dari GitHub UI. CodeLens sebagai analysis tool tidak cocok untuk extension — user perlu install Python + tree-sitter grammars. Skip.

2. **Web app (repomix.com)** — Repomix punya web app full-stack (Vue + Hono + Turnstile + rate limit). CodeLens sebagai Python CLI tool tidak cocok untuk web app. Skip.

3. **Claude Code plugin** — Repomix punya 3 Claude Code plugin (`repomix-mcp`, `repomix-commands`, `repomix-explorer`). CodeLens sudah punya MCP server (49 tools) + `SKILL.md`. Skip — bisa add Claude Code plugin marketplace listing untuk CodeLens MCP server, tapi itu tugas terpisah.

4. **Multi-linter CI stack** — Repomix pakai Biome + Oxlint + tsgo + Secretlint + typos + pinact. CodeLens Python-based, sudah pakai ruff. Tambah Secretlint (Issue R9) cukup, skip linter lain.

5. **WXT browser extension framework** — Tidak relevant untuk Python CLI.

6. **repomix.com website 7-locale guide** — CodeLens documentation bisa translate, tapi tidak perlu se-extensive Repomix. Prioritas: Bahasa Indonesia, English, Mandarin, Spanyol.

### 7.4 Konvensi Penamaan yang Diadopsi dari Repomix

Berikut konvensi Repomix yang worth diadopsi di CodeLens:

- `codelens.config.{json,jsonc,json5,toml,py}` — multi-format config (Issue R13)
- `codelens-output.{xml,md,json,txt}` — output file naming convention (Issue R1)
- `codelens-output.{1,2,3}.xml` — split output naming (Issue R4)
- `~/.codelens/config.json` — global config (Issue R13)
- `.claude/skills/<name>/` — Agent Skills output directory (Issue R8)
- `--token-count-tree`, `--token-budget`, `--top-files-len` — token count flag naming (Issue R2)
- `--no-file-summary`, `--no-directory-structure`, `--no-files` — negative flag convention (Issue R1)
- `--output-file-path-style target-relative|cwd-relative` — path style flag (Issue R16)
- `--include-empty-directories`, `--include-full-directory-structure` — verbose flag naming (Issue R16)
- `--no-git-sort-by-changes` — git sort flag (Issue R7)
- `--include-diffs`, `--include-logs`, `--include-logs-count` — git context flag (Issue R7)
- `--remote`, `--remote-branch`, `--remote-trust-config` — remote repo flag (Issue R5)
- `--skill-generate`, `--skill-project-name`, `--skill-output` — skill generation flag (Issue R8)
- `--parsable-style` — escape special char flag (Issue R1)
- `--instruction-file-path` — embed instruction flag (Issue R1)
- `--header-text` — custom header flag (Issue R1)

### 7.5 Integrasi dengan Roadmap OpenTaint (Analisis Sebelumnya)

Dokumen ini adalah **pelengkap** dari analisis OpenTaint sebelumnya (`CodeLens_vs_OpenTaint_Upgrade_Analysis.md`). Keduanya saling melengkapi:

| Aspek | OpenTaint Analysis | Repomix Analysis |
|---|---|---|
| **Fokus** | Kedalaman analysis (taint, rule authoring, agent orchestration) | Context delivery (packing, token counting, output format) |
| **Issue count** | 16 issue (A1-A4, B1-B3, C1-C3, D1-D4, E1-E2, F1-F2) | 16 issue (R1-R16) |
| **Total issue** | 32 issue combined | |
| **Quick win** | D3 (versioning konsisten) — 3 hari | R4 (split output) — 3-5 hari |
| **Highest impact** | A1 (unified taint engine), A3 (approximation) | R1 (`pack` command), R2 (token counting) |
| **Strategic** | C1 (multi-skill orchestrator) | R8 (Agent Skills generation) |

**Rekomendasi eksekusi paralel:**
- Fase 1 OpenTaint (D3, F2, D2, A1, F1) dan Fase R-1 Repomix (R1, R2, R3, R4) bisa dikerjakan paralel — tidak ada dependency
- Fase R-5 Repomix (R11 library usage) butuh Fase 1 OpenTaint (D2 Python package entry point) selesai dulu
- Setelah R1 selesai, R8 (Agent Skills generation) bisa integrasi dengan C1 (multi-skill orchestrator) OpenTaint — CodeLens bisa generate skill dari codebase lalu langsung pakai di orchestrator

---

## Penutup

Dokumen ini adalah **analisis komprehensif** Repomix sebagai sumber upgrade untuk CodeLens. Berbeda dengan OpenTaint (yang fokus pada kedalaman analysis), Repomix fokus pada **context delivery** — keduanya saling melengkapi.

**Rekomendasi eksekusi:**
1. **Mulai dari Fase R-1** (R1 `pack` command + R2 token counting) — ini foundation yang membuka 14 issue lainnya.
2. **R1 adalah highest-impact item** — `pack` command mengubah CodeLens dari analysis-only tool menjadi dual-purpose (analysis + context delivery).
3. **Integrasi dengan roadmap OpenTaint** — 32 issue total, dikerjakan paralel per fase, rilis sebagai minor version (v8.2, v8.3, v9.0, v9.1, v9.2, v10.0).
4. **Differentiate dari Repomix** — CodeLens `pack` harus terintegrasi dengan analysis (bisa pack finding `dataflow`, `taint`, `smell` ke output). Ini unique value yang Repomix tidak punya.

**Repo referensi:** https://github.com/yamadashy/repomix.git (MIT License — kompatibel untuk inspiration/adaptasi dengan attribusi).
