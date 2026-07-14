# CodeLens ↔ Serena — Analisis Fitur & Rencana Upgrade (Issue Tracker)

> **Repo yang dianalisis sebagai sumber upgrade:** `oraios/serena` — https://github.com/oraios/serena.git
> **Repo target upgrade:** `Wolfvin/CodeLens` (https://github.com/Wolfvin/CodeLens)
> **Tanggal analisis:** 2026-06-28
> **Versi Serena saat ini:** v1.5.4.dev0 (`pyproject.toml`) — distribusi via `uv tool install serena-agent`
> **Versi CodeLens saat ini:** v8.1 (README) / v7.2.0 (`skill.json`, `pyproject.toml`)

---

## Daftar Isi

1. [Ringkasan Eksekutif](#1-ringkasan-eksekutif)
2. [Analisis Fitur Serena (Repo Referensi)](#2-analisis-fitur-serena-repo-referensi)
3. [Matriks Komparasi Fitur Serena vs CodeLens](#3-matriks-komparasi-fitur-serena-vs-codelens)
4. [Peningkatan yang Sudah Di-adjust di CodeLens](#4-peningkatan-yang-sudah-di-adjust-di-codelens)
5. [Daftar Issue untuk Next Upgrade (Serapan dari Serena)](#5-daftar-issue-untuk-next-upgrade-serapan-dari-serena)
6. [Prioritas & Roadmap Eksekusi](#6-prioritas--roadmap-eksekusi)
7. [Catatan Teknis & Risiko](#7-catatan-teknis--risiko)
8. [Integrasi dengan Roadmap OpenTaint, Repomix, Understand-Anything](#8-integrasi-dengan-roadmap-opentaint-repomix-understand-anything)

---

## 1. Ringkasan Eksekutif

Serena adalah **MCP toolkit untuk coding** yang menyediakan **semantic code retrieval, editing, refactoring, dan debugging tools** berbasis Language Server Protocol (LSP). Dibuat oleh Oraios AI, dirilis sebagai open-source (MIT). Tagline: *"The IDE for Your Coding Agent"*.

**Filosofi Serena:** *agent-first tool design* — operasi di level simbol (bukan line number atau regex), mengejar kualitas dan efisiensi tinggi untuk AI agent di codebase besar. Lawan dengan CodeLens yang *analysis-focused* (taint, security, quality) dan Repomix yang *context-packing-focused*.

**Posisi strategis:** Serena dan CodeLens **sangat complementary**:
- CodeLens unggul di **analysis depth** (taint, security, quality, compliance, CVE) — answering "apa yang salah di kode ini?"
- Serena unggul di **semantic code operations** (find symbol, find references, rename, replace symbol body) — answering "bagaimana cara menavigasi dan mengedit kode ini secara presisi?"
- CodeLens output adalah **finding/JSON/SARIF**; Serena output adalah **tool yang dipanggil agent** untuk membaca/mengedit simbol

Serapan Serena ke CodeLens akan menutup **gap terbesar CodeLens**: tidak ada semantic symbol operation. Saat ini CodeLens `query` command hanya cek name collision — tidak bisa "find all references to function X" atau "rename symbol Y across file" dengan presisi LSP. Penyerapan Serena akan mengubah CodeLens dari **analysis-only tool** menjadi **analysis + semantic code operation tool**.

**Top 10 kapabilitas Serena yang berguna untuk CodeLens:**

1. **LSP-based semantic code intelligence** — support 40+ bahasa via 50+ language server (Pyright, TypeScript LS, gopls, rust-analyzer, clangd, jdtls, eclipse JDT, OmniSharp, dll). CodeLens hanya pakai tree-sitter (10 native + 20+ regex fallback) — tidak ada LSP.
2. **Symbol-level tools** (`find_symbol`, `get_symbols_overview`, `find_referencing_symbols`, `find_defining_symbol`, `find_implementations`) — agent bisa query simbol seperti di IDE. CodeLens `symbols` dan `trace` ada tapi tree-sitter-based, bukan LSP — akurasi rendah.
3. **Symbolic editing tools** (`replace_symbol_body`, `insert_after_symbol`, `insert_before_symbol`, `delete_lines`, `replace_lines`, `insert_at_line`) — agent edit simbol tanpa salah line number. CodeLens `fix` command ada tapi terbatas.
4. **Refactoring tools** via JetBrains plugin (`rename`, `move`, `inline`, `propagate deletions`, `safe delete`) — refactor atomik cross-file. CodeLens `refactor-safe` hanya pre-flight check, tidak ada eksekusi.
5. **Memory system** (`.serena/memories/`) dengan `mem:NAME` reference convention, referential integrity check, `serena memories check` CLI — long-lived agent workflow dengan knowledge yang persistent dan human-readable. CodeLens tidak punya memory system.
6. **Multi-layered configuration** (global + CLI + per-project + context-specific + composable modes) — composable YAML fragment untuk adapt ke client (Claude Code, Codex, Cursor, JetBrains, dll). CodeLens config flat JSON di `.codelens/`.
7. **Modes system** (onboarding, editing, planning, interactive, one-shot, no-memories, no-onboarding, query-projects) — predefined tool subset + prompt per use case. CodeLens tidak punya.
8. **Contexts system** (14 context: claude-code, codex, cursor, vscode, ide, copilot-cli, chatgpt, jb-copilot-plugin, dll) — adapt tool set + prompt per AI client. CodeLens hanya MCP generic.
9. **Project-based workflow** (project create → activate → onboard → work) dengan `.serena/project.yml`, `project.local.yml` override, additional workspace folder untuk monorepo. CodeLens `init` ada tapi lebih sederhana.
10. **Onboarding process** — first-time Serena run auto-onboarding, write memories about project structure/convention. CodeLens `handbook` ada tapi tidak auto-onboarding.

**Rekomendasi tingkat tinggi:** Serap Serena sebagai **semantic code operation layer** CodeLens. Tambah command `codelens symbol`, `codelens references`, `codelens rename`, `codelens replace-symbol`. Integrasi LSP via Python LSP client (reuse Serena's `solidlsp` module sebagai dependency, atau port ke CodeLens). Tambah memory system di `.codelens/memories/`. Tambah modes + contexts system. Ini akan menutup gap terbesar CodeLens dan membuatnya jadi **analysis + semantic operation platform**.

---

## 2. Analisis Fitur Serena (Repo Referensi)

### 2.1 Arsitektur Umum

Serena adalah **Python monorepo** (uv-managed) dengan struktur:

| Komponen | Lokasi | Peran |
|---|---|---|
| `src/serena/` | Core | MCP server, agent, tools, memories, config, dashboard, project, hooks |
| `src/serena/tools/` | Tools | 9 tool module: `symbol_tools.py` (716 LOC), `file_tools.py` (424 LOC), `jetbrains_tools.py` (674 LOC), `memory_tools.py` (122 LOC), `cmd_tools.py` (52 LOC), `config_tools.py` (66 LOC), `query_project_tools.py` (77 LOC), `workflow_tools.py` (63 LOC), `tools_base.py` (669 LOC) |
| `src/serena/memories/` | Memory system | `memory_manager.py` (407 LOC), `memory_reference_analysis.py` (780 LOC) |
| `src/serena/resources/config/modes/` | Modes | 9 mode YAML: onboarding, editing, planning, interactive, one-shot, no-memories, no-onboarding, query-projects, mode.template |
| `src/serena/resources/config/contexts/` | Contexts | 14 context YAML: claude-code, codex, cursor, vscode, ide, copilot-cli, chatgpt, antigravity, jb-ai-assistant, jb-copilot-plugin, junie, agent, oaicompat-agent, desktop-app, context.template |
| `src/serena/resources/config/prompt_templates/` | Prompt template | `system_prompt.yml`, `info_prompts.yml`, `simple_tool_outputs.yml` |
| `src/solidlsp/` | LSP layer | LSP abstraction: `ls.py`, `ls_types.py`, `ls_config.py`, `ls_request.py`, `ls_process.py`, `ls_exceptions.py`, `lsp_protocol_handler/` (server, requests, types, constants), `language_servers/` (50+ language server module), `util/` (cache, subprocess, zip, metals_db_utils) |
| `src/solidlsp/language_servers/` | Language servers | 50+ LS module: pyright, typescript, gopls, rust_analyzer, clangd, eclipse_jdtls, omnisharp, jedi, ruby_lsp, intelephense, phpactor, kotlin, scala, haskell, swift, sourcekit_lsp, dart, lua, luau, vue, svelte, angular, solargraph, bash, powershell, perl, elixir, erlang, clojure, fsharp, haxe, julia, lean4, fortran, ada, ocaml, pascal, crystal, regal, zls, nixd, marksman, texlab, matlab, msl, bsl, al, ansible, solidity, systemverilog, hlsl, taplo, json, yaml, vscode_html, some_sass, vue, vts |
| `src/interprompt/` | Prompt library | `prompt_factory.py`, `multilang_prompt.py`, `jinja_template.py` — Jinja2-based prompt templating |
| `src/serena/jetbrains/` | JetBrains integration | `jetbrains_types.py`, `jetbrains_plugin_client.py` — JetBrains plugin backend |
| `src/serena/resources/dashboard/` | Dashboard | `index.html`, `dashboard.js`, `dashboard.css`, `jquery.min.js` — web dashboard for managing Serena |
| `scripts/` | Scripts | `mcp_server.py`, `agno_agent.py`, `gen_prompt_factory.py`, `print_language_list.py`, `print_tool_overview.py`, `demo_*.py`, `bump_version.py`, `profile_tool_call.py` |
| `test/solidlsp/` | LSP test | Per-language test (40+ language), test fixture repos di `test/resources/repos/` |
| `docs/` | Documentation | 4 section: `01-about/`, `02-usage/`, `03-special-guides/`, `04-evaluation/` — Sphinx + jupyter-book |
| `news/` | Release notes | 9 HTML news file (2026-01 to 2026-05) |

### 2.2 MCP Server

Serena adalah **MCP server** (`src/serena/mcp.py`, 419 LOC) menggunakan `mcp==1.27.0` package:

**Tech:**
- `FastMCP` dari `mcp.server.fastmcp`
- Transport: stdio (default) atau streamable HTTP (`--transport http`)
- Tool registration via `SerenaFastMCPTool` (wrap Serena `Tool` class)
- OpenAI tool compatibility mode (`openai_tool_compatible: bool`) — sanitize schema untuk Codex (integer → number, dll)
- Structured tool output toggle (Claude Code has bug → disabled by default)
- Tool description override per context
- `ToolAnnotations` untuk hint (readOnlyHint, destructiveHint, idempotentHint, openWorldHint)

**Lifecycle:**
- `SerenaMCPRequestContext` dataclass — hold `SerenaAgent` instance
- Lifespan context untuk initialize agent di startup
- `MemoryLogHandler` — capture log untuk dashboard

### 2.3 Tool Categories

#### Retrieval Tools (Symbol-level)

| Tool | Peran |
|---|---|
| `find_symbol` | Global/local search symbol by name path pattern. Support: `foo` (any symbol named foo), `foo/bar` (bar within foo), `/foo/bar` (top-level foo/bar). Params: `name_path_pattern`, `depth`, `relative_path`, `include_body`, `include_info`, `include_kinds`, `exclude_kinds`, `substring_matching`, `max_matches`, `max_answer_chars` |
| `get_symbols_overview` | Top-level symbol di file, grouped by kind. First tool to call when understanding new file. Params: `relative_path`, `depth`, `max_answer_chars` |
| `find_referencing_symbols` | Find all reference to symbol (cross-file). Menampilkan code snippet around reference + symbolic info |
| `find_defining_symbol` | Find declaration site. Tidak bekerja untuk external dependency declaration |
| `find_implementations` | Find implementation of interface/abstract. Limited by language server capability |

#### Refactoring Tools (JetBrains plugin only)

| Tool | Peran |
|---|---|
| `jet_brains_rename` | Rename symbol, file, atau directory (atomic cross-file) |
| `jet_brains_move` | Move symbol, file, atau directory |
| `jet_brains_inline` | Inline symbol (function → call site, variable → value) |
| `jet_brains_propagate_deletions` | Remove unused code yang result dari deletion |
| `jet_brains_safe_delete` | Safe delete dengan reference check |

#### Symbolic Editing Tools

| Tool | Peran |
|---|---|
| `replace_symbol_body` | Replace entire symbol body (function, class, method). Atomik, precise |
| `insert_after_symbol` | Insert code setelah symbol tertentu (untuk add new symbol di akhir file) |
| `insert_before_symbol` | Insert code sebelum symbol tertentu (untuk add new symbol di awal file) |

#### File-based Editing Tools

| Tool | Peran |
|---|---|
| `replace_content` | Regex-based atau literal text replacement. Agent-optimized dengan wildcard support |
| `replace_lines` | Replace line range dengan new content |
| `insert_at_line` | Insert content di line tertentu |
| `delete_lines` | Delete line range |
| `create_text_file` | Create new file dengan content |

#### File Operations

| Tool | Peran |
|---|---|
| `read_file` | Read file atau file chunk |
| `list_dir` | Directory listing |
| `find_file` | File search |
| `search_for_pattern` | Regex search across codebase (DOTALL matching) |

#### Shell

| Tool | Peran |
|---|---|
| `execute_shell_command` | Run shell command (build, test, linter) |

#### Memory Tools

| Tool | Peran |
|---|---|
| `write_memory` | Write memory file (markdown) |
| `read_memory` | Read memory file |
| `edit_memory` | Edit existing memory |
| `delete_memory` | Delete memory |
| `rename_memory` | Rename memory (update reference) |
| `list_memories` | List all memory, filter by topic |

#### Workflow Tools

| Tool | Peran |
|---|---|
| `onboarding` | Trigger onboarding process untuk new project |
| `initial_instructions` | Get initial instruction untuk current context |
| `activate_project` | Switch active project (multi-project mode) |
| `query_project` | Query inactive project (read-only) |
| `list_queryable_projects` | List queryable project |
| `restart_language_server` | Restart LS jika hang |

#### Diagnostics

| Tool | Peran |
|---|---|
| `get_diagnostics` | Get LSP diagnostics untuk file (error, warning, info) |

### 2.4 LSP Layer (`src/solidlsp/`)

**SolidLSP** adalah abstraction layer untuk LSP integration:

**Supported language** (40+):
Ada/SPARK, AL, Angular, Ansible, Bash, BSL, C#, C/C++, Clojure, Crystal, CUE, Dart, Elixir, Elm, Erlang, Fortran, F#, GDScript, GLSL, Go, Groovy, Haskell, Haxe, HLSL, HTML, Java, JavaScript, JSON, Julia, Kotlin, LaTeX, Lean 4, Lua, Luau, Markdown, MATLAB, mSL, Nix, OCaml, Perl, PHP, PowerShell, Python, R, Ruby, Rust, Scala, SCSS/Sass/CSS, Solidity, Svelte, Swift, TOML, TypeScript, WGSL, YAML, Zig

**Language server** (50+ file di `language_servers/`):
- Python: pyright, jedi
- TypeScript/JavaScript: typescript_language_server, vts_language_server, angular_language_server, vue_language_server, svelte_language_server
- Go: gopls
- Rust: rust_analyzer
- C/C++: clangd, ccls
- Java: eclipse_jdtls
- C#: omnisharp, csharp_language_server
- Ruby: ruby_lsp, solargraph
- PHP: intelephense, phpactor
- Kotlin: kotlin_language_server
- Scala: scala_language_server
- Haskell: haskell_language_server
- Swift: sourcekit_lsp
- Dart: dart_language_server
- Lua: lua_ls
- Luau: luau_lsp
- Elixir: elixir_tools
- Erlang: erlang_language_server
- Clojure: clojure_lsp
- F#: fsharp_language_server
- Haxe: haxe_language_server
- Julia: julia_server
- Lean 4: lean4_language_server
- Fortran: fortran_language_server
- Ada: ada_language_server
- OCaml: ocaml_lsp_server
- Pascal: pascal_server
- Crystal: crystal_language_server
- Rego: regal_server
- Zig: zls
- Nix: nixd_ls
- Markdown: marksman
- LaTeX: texlab_language_server
- MATLAB: matlab_language_server
- mSL: msl_language_server, msl_lsp_server
- BSL: bsl_language_server
- AL: al_language_server
- Ansible: ansible_language_server
- Solidity: solidity_language_server
- SystemVerilog: systemverilog_server
- HLSL: hlsl_language_server
- TOML: taplo_server
- JSON: json_language_server
- YAML: yaml_language_server
- HTML: vscode_html_language_server
- SCSS/Sass: some_sass_language_server

**LSP protocol handler** (`lsp_protocol_handler/`):
- `server.py` — LSP server implementation (JSON-RPC over stdio)
- `lsp_requests.py` — request method
- `lsp_types.py` — LSP type
- `lsp_constants.py` — constant

**SolidLSP feature:**
- Symbol retrieval (workspace symbol, document symbol)
- Reference finding
- Definition finding
- Implementation finding
- Diagnostics (publishDiagnostics)
- Hover info
- Rename (LSP-level)
- Cross-file reference (dengan `additional_workspace_folders`)
- File watching + auto-reindex
- Subprocess management untuk language server
- Caching (`util/cache.py`)

### 2.5 Memory System (`src/serena/memories/`)

**Design philosophy** (7 criteria):
1. **Human-readable and editable** — Markdown file, bisa di-edit di text editor
2. **Versionable with the project** — `.serena/memories/` commit ke git, review di PR
3. **Progressive disclosure** — agent terima full name list up front, baca detail on-demand
4. **Prefer references to search** — explicit `mem:NAME` reference, deterministic (no false positive/negative)
5. **Prefer deliberate reads to triggers** — agent decide what to read; harness tidak inject content
6. **Framework-agnostic** — plain Markdown, hanya `mem:` prefix yang Serena-specific
7. **Configurable and composable** — per-project + global scope, regex pattern untuk read-only/ignore

**Memory type:**
- **Project-specific** — `.serena/memories/` di project folder
- **Global** — `~/.serena/memories/global/`

**Memory organization:**
- Topic via `/` in name (e.g., `modules/frontend`)
- File system mapping: topic = subdirectory
- `list_memories` filter by topic

**Reference convention:**
- `` `mem:NAME` `` — reference ke memory lain
- Contoh: `` `mem:auth/login` ``, `` `mem:suggested_commands` ``
- Reference kept in sync across rename
- `serena memories check` — report stale reference

**Memory manager feature** (`memory_manager.py`, 407 LOC):
- `write_memory(name, content)` — write memory
- `read_memory(name)` — read memory
- `edit_memory(name, content)` — edit existing
- `delete_memory(name)` — delete
- `rename_memory(old_name, new_name)` — rename + update reference
- `list_memories(topic=None)` — list, filter by topic
- `_sanitize_name(name)` — handle common LLM mistake (`mem:` prefix, `.md` suffix, OS-specific separator)
- Read-only pattern (`read_only_memory_patterns`) — global memory write protection
- Ignored pattern (`ignored_memory_patterns`) — completely exclude from listing/reading/writing

**Memory reference analysis** (`memory_reference_analysis.py`, 780 LOC):
- `MemoryReferenceAnalyzer` — parse `` `mem:NAME` `` reference
- `ReferentialIntegrityReport` — report stale reference
- `AutofixReport` — auto-fix broken reference
- Reference rename propagation

**Onboarding process:**
- First-time Serena run di project → auto-onboarding
- Seed `memory_maintenance` memory — describe convention (style, reference) yang subsequent memory harus ikuti
- Agent instructed to read `memory_maintenance` sebelum write project-specific memory
- Write memory tentang: project structure, convention, key module, dll.

### 2.6 Modes System (`src/serena/resources/config/modes/`)

**9 mode** (composable YAML fragment):

| Mode | Description | Excluded Tools |
|---|---|---|
| `onboarding` | First-time project analysis. Read-only, collect info, write memory | `create_text_file`, `replace_symbol_body`, `insert_after_symbol`, `insert_before_symbol`, `delete_lines`, `replace_lines`, `insert_at_line`, `execute_shell_command` |
| `editing` | All tools, detailed instruction for code editing | `replace_lines`, `insert_at_line`, `delete_lines` |
| `planning` | Read-only, analyze + plan (no code write) | `create_text_file`, `replace_symbol_body`, `insert_after_symbol`, `insert_before_symbol`, `delete_lines`, `replace_lines`, `insert_at_line`, `execute_shell_command`, `replace_content` |
| `interactive` | Step-by-step work with user clarification | (none) |
| `one-shot` | Autonomous task completion, no interaction | (none) |
| `no-memories` | Disable memory tool + onboarding | `write_memory`, `read_memory`, `delete_memory`, `edit_memory`, `rename_memory`, `list_memories`, `onboarding` |
| `no-onboarding` | Skip onboarding (memories may exist externally) | `onboarding` |
| `query-projects` | Enable query ke inactive project | (none, but include `list_queryable_projects`, `query_project`) |
| `mode.template` | Template untuk custom mode | — |

**Mode structure:**
```yaml
description: Description of the mode (meta-information only)
prompt: |
  Provide a prompt that will form part of the instructions sent to the model when this mode is activated.
excluded_tools: []
included_optional_tools: []
```

### 2.7 Contexts System (`src/serena/resources/config/contexts/`)

**14 context** (per-AI-client configuration):

| Context | Description |
|---|---|
| `claude-code` | Claude Code CLI — file ops sudah covered, single project mode, structured output disabled (Claude Code bug) |
| `codex` | Codex — non-symbolic editing + shell excluded |
| `cursor` | Cursor IDE |
| `vscode` | VS Code + Copilot |
| `ide` | Generic IDE assistant |
| `copilot-cli` | GitHub Copilot CLI |
| `chatgpt` | ChatGPT desktop — 30 tool limit, short description, tool description override |
| `antigravity` | Antigravity |
| `jb-ai-assistant` | JetBrains AI Assistant |
| `jb-copilot-plugin` | JetBrains Copilot plugin |
| `junie` | JetBrains Junie |
| `agent` | Generic agent |
| `oaicompat-agent` | OpenAI-compatible agent |
| `desktop-app` | Serena desktop app |
| `context.template` | Template |

**Context structure:**
```yaml
description: ...
prompt: |
  ...
excluded_tools: []
included_optional_tools: []
tool_description_overrides: {}
single_project: true  # jika true, disable activate_project
structured_tool_output: false  # Claude Code bug
```

**Context-specific prompt example** (`claude-code.yml`):
```yaml
prompt: |
  You are running in a CLI coding agent context where file operations, basic (line-based) edits and reads 
  as well as shell commands are handled by your own, internal tools.
  
  You have access to Serena's code intelligence tools that exploit the symbolic 
  structure of the code and are much more efficient than your own tools for most coding scenarios.
  If you are working on any coding task and if Serena's tools are deferred, you
  should load them all immediately, before performing any read, grep or bash commands.
  ...
  For any code files:
  - Read           -> FORBIDDEN for discovery. Use get_symbols_overview, then find_symbol with include_body.
  - Glob (by name) -> Allowed for discovery only.
  - Grep (content) -> Allowed for discovery only; follow up reads or reference searches must be Serena.
  - Edit           -> FORBIDDEN. Use replace_symbol_body / insert_*_symbol / replace_content.
```

### 2.8 Project Workflow

**4-step workflow:**
1. **Project creation** — `serena project create [options] [project-dir]`
   - Auto-detect language dari source file
   - Generate `.serena/project.yml`
   - Optional `--index` untuk pre-cache symbol
2. **Project activation** — `--project <path|name>` atau "activate project" via LLM
3. **Onboarding** — first-time Serena auto-onboard, write memory
4. **Coding task** — use Serena tool via MCP

**Project config** (`.serena/project.yml`):
- Project name
- Programming language (untuk spawn language server)
- Language backend (`lsp` atau `jetbrains`)
- File encoding
- Ignore rule
- Write access
- Additional workspace folder (cross-package reference untuk monorepo)
- Initial prompt
- Tool + mode set
- Lain-lain

**Local override** (`.serena/project.local.yml`, gitignored) — override project.yml setting.

**Additional workspace folder** (TypeScript only saat ini):
```yaml
additional_workspace_folders:
  - ../shared-lib
  - ../api-client
  - /absolute/path/to/another-package
```

Setiap folder di-register sebagai LSP workspace folder → cross-package reference discovery.

### 2.9 JetBrains Plugin Backend

**Serena JetBrains Plugin** (paid, free trial):
- Leverage JetBrains IDE code analysis capability
- Support semua bahasa yang didukung JetBrains IDE (IntelliJ, PyCharm, Android Studio, WebStorm, PhpStorb, RubyMine, GoLand; tidak Rider/CLion)
- Fitur eksklusif: `move`, `inline`, `propagate deletions`, type hierarchy, search in project dependencies, interactive debugging (breakpoint, variable inspection, expression evaluation, execution control via REPL)

**JetBrains tool** (`jetbrains_tools.py`, 674 LOC):
- `jet_brains_rename` — rename symbol/file/directory
- `jet_brains_move` — move symbol/file/directory
- `jet_brains_inline` — inline symbol
- `jet_brains_propagate_deletions` — remove unused code
- `jet_brains_safe_delete` — safe delete
- `jet_brains_debug_*` — debugging tool

### 2.10 Configuration System

**Multi-layered config:**
1. **Global config** — `~/.serena/serena_config.yml`
2. **MCP launch command (CLI) config** — CLI flag override
3. **Per-project config** — `.serena/project.yml`
4. **Local override** — `.serena/project.local.yml` (gitignored)
5. **Execution context config** — per-AI-client (14 context)
6. **Composable mode fragment** — 9 mode

**Config composition:** Global → CLI → project → local → context → mode (later override earlier).

**Config content:**
- Active tool set
- Tool description
- Prompt
- Language backend detail
- Ignore rule
- Read-only memory pattern
- Ignored memory pattern
- Lain-lain

### 2.11 Dashboard

**Web dashboard** (`src/serena/resources/dashboard/`, `src/serena/dashboard.py`):
- HTML + CSS + jQuery (lightweight, no build step)
- Start: `serena dashboard` atau auto-start dengan MCP server
- Fitur:
  - View active project, language, mode, context
  - Manage language server (start/stop/restart)
  - View log (real-time)
  - Manage memory (list, read, edit, delete)
  - Manage project (activate, switch)
  - Tool overview (list all tool, description)
- Tray icon (macOS via `pystray`)
- `pywebview` untuk native window

### 2.12 Distribution & Installation

**Install via uv:**
```bash
uv tool install -p 3.13 serena-agent
```

**Command:**
- `serena` / `serena-agent` — start MCP server (stdio atau HTTP)
- `serena init` — initialize Serena (setup config, verify install)
- `serena project create [options] [dir]` — create project
- `serena project index` — pre-cache symbol
- `serena start-project-server` — start project server untuk multi-agent access
- `serena memories check` — validate memory reference
- `serena hooks` — hook command (pre-commit, dll.)

**Docker:**
- `Dockerfile` (minimal)
- `Dockerfile.maximal` (semua language server)
- `compose.yaml` + `docker_build_and_run.sh`

**Nix flake** (`flake.nix`, `flake.lock`).

**Prerequisite:** `uv` (Python package manager).

### 2.13 Client Configuration

**14 client supported** (via context):
- Claude Code (CLI)
- Codex (CLI)
- Cursor (IDE)
- VS Code + Copilot
- Generic IDE
- Copilot CLI
- ChatGPT desktop
- Antigravity
- JetBrains AI Assistant
- JetBrains Copilot plugin
- JetBrains Junie
- Generic agent
- OpenAI-compatible agent
- Serena desktop app

**Connection mode:**
1. **Stdio** — client start MCP server via launch command
2. **Streamable HTTP** — start Serena di HTTP mode, client connect via URL

### 2.14 Documentation & Evaluation

**Documentation** (`docs/`, Sphinx + jupyter-book):
- `01-about/` — intro, programming language, serena-in-action, acknowledgement
- `02-usage/` — installation, running, jetbrains plugin, clients, workflow, configuration, memories, dashboard, logs, security, additional usage
- `03-special-guides/` — cpp setup, custom agent, serena on chatgpt, ocaml/scala/groovy/godot/unreal setup
- `04-evaluation/` — evaluation intro, methodology, prompt, result (Claude Code on tianshou, Codex on JB plugin, Copilot CLI on ente, GLM on tianshou, Junie plugin on tianshou)

**Evaluation result** (testimonial dari agent):
- **Opus 4.6 in Claude Code (large Python):** "single most impactful addition – cross-file renames, moves, reference lookups yang butuh 8-12 careful step collapse jadi 1 atomic call"
- **GPT 5.4 in Codex CLI (Java):** "missing IDE-level understanding of symbols, references, refactorings, turning fragile text surgery into calmer, faster, more confident code changes"
- **GPT 5.4 in Copilot CLI (multi-language monorepo):** "noticeably sharper on real code – symbol-aware navigation, cross-file refactors, monorepo dependency jumps"

### 2.15 Testing

**Test structure:**
- `test/solidlsp/` — per-language LSP test (40+ language, integration test dengan real language server)
- `test/serena/` — Serena core test (MCP, memories, symbol editing, dashboard, hooks, CLI, agent, config)
- `test/resources/repos/` — test fixture repos per language
- `test/serena/__snapshots__/` — snapshot test (syrupy)

**Test marker** (40+ marker di `pyproject.toml`):
- Per-language: `python`, `typescript`, `go`, `java`, `kotlin`, `rust`, `ruby`, `php`, `csharp`, `elixir`, `vue`, `svelte`, `angular`, `scala`, `groovy`, `swift`, `bash`, `r`, `zig`, `lua`, `luau`, `nix`, `dart`, `erlang`, `ocaml`, `al`, `fsharp`, `rego`, `markdown`, `latex`, `julia`, `fortran`, `haskell`, `haxe`, `yaml`, `json`, `powershell`, `pascal`, `cpp`, `toml`, `matlab`, `systemverilog`, `hlsl`, `lean4`, `solidity`, `ansible`, `msl`, `bsl`, `html`, `scss`, `clojure`, `crystal`, `cue`, `perl`, `terraform`, `ada`
- `slow` — test yang butuh Expert instance (60-90s startup)
- `snapshot` — snapshot test

**Tooling:**
- pytest + pytest-xdist (parallel) + pytest-timeout
- ruff (lint + format)
- mypy (type check, strict)
- syrupy (snapshot test)
- codespell (typo check)
- poethepoet (task runner)

### 2.16 Hooks System

**Hooks** (`src/serena/hooks.py`):
- `serena-hooks` CLI entry point
- `hook_commands` function
- Pre-commit hook, post-commit hook, dll.
- Hook triggered oleh git event → run Serena tool

### 2.17 Agent & AGNO Integration

**Serena agent** (`src/serena/agent.py`):
- `SerenaAgent` class — orchestrator
- `SerenaConfig` — config dataclass
- Manage language server, project, memory, tool

**AGNO integration** (`src/serena/agno.py`, `scripts/agno_agent.py`):
- AGNO framework integration (agent framework)
- Optional dependency (`agno` extra)

### 2.18 Project Server

**Project server** (`src/serena/project_server.py`):
- Untuk multi-agent access ke single Serena instance
- Start: `serena start-project-server`
- Spawn language server untuk project yang di-query
- Enable `query_project` tool untuk inactive project

### 2.19 Analytics & Profiling

**Analytics** (`src/serena/analytics.py`):
- Tool call tracking
- Performance metric

**Profiling** (`scripts/profile_tool_call.py`):
- Profile tool call execution
- `pyinstrument` untuk flamegraph

### 2.20 Code Editor Integration

**Code editor** (`src/serena/code_editor.py`):
- Integrasi dengan external code editor (VS Code, JetBrains)
- Show edit result di editor

### 2.21 GUI Log Viewer

**GUI log viewer** (`src/serena/gui_log_viewer.py`):
- `pywebview`-based log viewer
- Real-time log streaming

### 2.22 Language Support Detail

**Per-language setup guide** (`docs/03-special-guides/`):
- `cpp_setup.md` — C/C++ setup (clangd, compile_commands.json)
- `ocaml_setup_guide_for_serena.md`
- `scala_setup_guide_for_serena.md`
- `groovy_setup_guide_for_serena.md`
- `godot_gdscript_setup_guide_for_serena.md`
- `unreal_engine_setup_guide_for_serena.md`
- `serena_on_chatgpt.md` — ChatGPT integration
- `custom_agent.md` — custom agent integration

### 2.23 News & Release

**News** (`news/`):
- 9 HTML news file (2026-01 to 2026-05)
- `scripts/build_news_json.py` — build news JSON

### 2.24 Security

**Security doc** (`docs/02-usage/070_security.md`):
- MCP server security consideration
- Project isolation
- Memory access control
- Shell command execution risk

---

## 3. Matriks Komparasi Fitur Serena vs CodeLens

| Kapabilitas | CodeLens | Serena | Gap CodeLens |
|---|:---:|:---:|---|
| **Core purpose** | Code intelligence (analysis) | Semantic code operation (IDE-like) | different niche |
| **Tech stack** | Python (tree-sitter + regex) | Python (LSP via solidlsp) | — |
| **Language support** | 30+ (10 native tree-sitter + 20+ regex fallback) | 40+ (via 50+ language server) | sedang (Serena lebih luas) |
| **Symbol retrieval** | ⚠️ `symbols` (tree-sitter), `search` (regex) | ✅ LSP-based (`find_symbol`, `get_symbols_overview`) | **besar** |
| **Reference finding** | ⚠️ `trace` (tree-sitter call graph) | ✅ `find_referencing_symbols` (LSP, cross-file) | **besar** |
| **Definition finding** | ❌ | ✅ `find_defining_symbol` | **besar** |
| **Implementation finding** | ❌ | ✅ `find_implementations` | sedang |
| **Symbolic editing** | ⚠️ `fix` (limited) | ✅ `replace_symbol_body`, `insert_after/before_symbol` | **besar** |
| **Refactoring (rename)** | ❌ (hanya `refactor-safe` pre-check) | ✅ LSP rename + JetBrains rename | **besar** |
| **Refactoring (move/inline)** | ❌ | ✅ JetBrains plugin only | sedang |
| **Safe delete** | ❌ | ✅ | sedang |
| **Diagnostics** | ❌ | ✅ LSP diagnostics | sedang |
| **Taint analysis** | ✅ AST-based path-sensitive | ❌ | — (CodeLens unggul) |
| **Security audit** | ✅ `secrets`, `vuln-scan`, `env-check` | ❌ | — (CodeLens unggul) |
| **Code smell** | ✅ 10 category | ❌ | — (CodeLens unggul) |
| **Complexity** | ✅ cyclomatic + cognitive | ❌ | — (CodeLens unggul) |
| **Dead code** | ✅ | ❌ | — (CodeLens unggul) |
| **A11y** | ✅ WCAG 2.1 | ❌ | — (CodeLens unggul) |
| **CSS deep** | ✅ | ❌ | — (CodeLens unggul) |
| **CVE scanning** | ✅ OSV.dev | ❌ | — (CodeLens unggul) |
| **Compliance** | ✅ HIPAA, PCI-DSS | ❌ | — (CodeLens unggul) |
| **OWASP Top 10** | ✅ 36 rules | ❌ | — (CodeLens unggul) |
| **Pre-write safety** | ✅ `query` + `guard` | ❌ | — (CodeLens unggul) |
| **Memory system** | ❌ | ✅ `.serena/memories/` dengan `mem:` reference | **besar** |
| **Modes system** | ❌ | ✅ 9 mode (onboarding, editing, planning, dll.) | **besar** |
| **Contexts system** | ❌ | ✅ 14 context (per-AI-client) | **besar** |
| **Multi-layered config** | ⚠️ flat JSON | ✅ global + CLI + project + local + context + mode | sedang |
| **Project workflow** | ⚠️ `init` (basic) | ✅ project create → activate → onboard → work | sedang |
| **Onboarding** | ⚠️ `handbook` (manual) | ✅ auto-onboarding + memory write | sedang |
| **MCP server** | ✅ 49 tools | ✅ ~20 tool | setara (different focus) |
| **VS Code extension** | ✅ native | ⚠️ via client plugin | — (CodeLens unggul) |
| **Plugin system** | ✅ 4 type, 3-tier | ❌ | — (CodeLens unggul) |
| **Dashboard** | ❌ | ✅ lightweight HTML+jQuery | sedang |
| **JetBrains plugin** | ❌ | ✅ paid plugin (refactor + debug) | sedang |
| **Docker** | ❌ | ✅ minimal + maximal image | kecil |
| **Nix flake** | ❌ | ✅ | kecil |
| **Benchmark** | ✅ `run_benchmarks.py` + regression | ⚠️ evaluation testimonial | — (CodeLens unggul) |
| **AI-optimized output** | ✅ `--format ai`, `--lite`, `--top N` | ❌ | — (CodeLens unggul) |
| **Token counting** | ⚠️ `--max-tokens N` (basic) | ✅ `tiktoken` dependency | sedang |
| **Translation** | ❌ | ❌ | setara (both weak) |
| **Cross-package reference** | ⚠️ `crossfile_taint_engine` (terbatas) | ✅ `additional_workspace_folders` (TypeScript) | sedang |
| **Hooks system** | ⚠️ `pre_commit_hook.py` | ✅ `serena-hooks` CLI | kecil |
| **Memory reference integrity** | ❌ | ✅ `mem:` convention + `serena memories check` | **besar** |
| **Progressive disclosure** | ❌ | ✅ agent terima name list, read on-demand | sedang |
| **Test coverage** | ⚠️ `pytest.ini` + `tests/` | ✅ 40+ language integration test + snapshot | Serena unggul |
| **Documentation** | ⚠️ 5 reference file | ✅ 4 section Sphinx docs + evaluation | Serena unggul |

---

## 4. Peningkatan yang Sudah Di-adjust di CodeLens

Berikut hal yang **sudah dimiliki CodeLens** dan **tidak perlu** diserap dari Serena:

### 4.1 Analysis Depth (Core Differentiator)

- ✅ **AST taint analysis** dengan CFG, path-sensitive, inter-procedural
- ✅ **Cross-file taint engine**
- ✅ **Dataflow analysis** dengan source→sink YAML rules
- ✅ **Code smell detection** (10 category)
- ✅ **Complexity scoring** (cyclomatic + cognitive)
- ✅ **Dead code detection**
- ✅ **CSS deep analysis**
- ✅ **A11y auditing** (WCAG 2.1)
- ✅ **Performance hints**
- ✅ **Regex audit** (ReDoS)
- ✅ **Secret detection**
- ✅ **CVE/vuln scanning** (OSV.dev)

Serena sama sekali tidak punya analysis mendalam — hanya semantic code operation.

### 4.2 Pre-Write Safety & Guard Hooks

- ✅ `query "name"` dengan status decision rules (CREATE/EXTEND/ASK/STOP)
- ✅ `guard --pre/--post` untuk AI agent workflow
- ✅ `refactor-safe` rename/move safety check
- ✅ `impact` change impact analysis dengan risk level

### 4.3 MCP Server (49 Tools vs ~20)

- ✅ 49 MCP tools (semua CodeLens command ter-expose)
- ✅ MCP spec via JSON-RPC 2.0 over stdio
- ✅ HTTP/SSE transport opsional
- ✅ In-memory registry caching, sub-millisecond query

### 4.4 Plugin System (4 Type vs 0)

- ✅ 4 plugin types (rule_pack/engine/formatter/command)
- ✅ 3-tier discovery
- ✅ Built-in OWASP Top 10 (36 rules) + Compliance (HIPAA, PCI-DSS — 53 rules)

### 4.5 Wide Command Surface (58 vs ~20)

CodeLens punya 58 command vs Serena ~20 tool. CodeLens jauh lebih luas untuk analysis task.

### 4.6 AI-Native Output

- ✅ `--format ai` normalized schema
- ✅ `--lite` per-command tailored output
- ✅ `--top N` smart default
- ✅ `--max-tokens N`
- ✅ `CODELENS_AI_MODE=1` env var
- ✅ Zero-config auto-init + auto-scan

### 4.7 Benchmark & Regression

- ✅ `benchmarks/run_benchmarks.py` + `check_regression.py`
- ✅ Fixture `vulnerable_app/` dengan `ground_truth.yaml`

### 4.8 Compliance & Security Rules

- ✅ OWASP Top 10 (36 rules dengan CWE + OWASP metadata)
- ✅ HIPAA + PCI-DSS (53 rules)

### 4.9 VS Code Extension (Native)

- ✅ Native VS Code extension dengan Diagnostics Provider, Code Actions, Guard hooks, Health status bar
- ✅ Serena hanya via client plugin

---

## 5. Daftar Issue untuk Next Upgrade (Serapan dari Serena)

Berikut **issue-issue konkret** untuk diajukan ke repo CodeLens, dikelompokkan per tema. Setiap issue sudah disertai: motivasi (referensi Serena), acceptance criteria, dan scope teknis.

### Tema S-A: LSP Integration & Semantic Code Operation

---

#### Issue S1 — LSP Client Integration via `solidlsp`

**Motivasi (Serena):** Serena punya `src/solidlsp/` — abstraction layer untuk LSP integration dengan 50+ language server module (Pyright, TypeScript LS, gopls, rust-analyzer, clangd, jdtls, OmniSharp, dll). Support 40+ bahasa dengan akurasi IDE-level (bukan tree-sitter approximation).

CodeLens saat ini hanya pakai tree-sitter (10 native + 20+ regex fallback). Akurasi `symbols`, `trace`, `search` terbatas — tidak bisa find reference cross-file dengan presisi, tidak bisa find definition, tidak bisa find implementation. Untuk AI agent yang butuh IDE-level code operation, CodeLens tidak memadai.

**Acceptance Criteria:**
- [ ] Vendor `solidlsp` module ke CodeLens (atau jadikan dependency: `pip install solidlsp` jika dipublish ke PyPI, atau git submodule)
- [ ] Buat `scripts/lsp_manager.py` (port dari Serena `src/serena/ls_manager.py`) — manage language server lifecycle (start, stop, restart, health check)
- [ ] Auto-detect language dari project file (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, dll.) → spawn language server yang sesuai
- [ ] Language server start lazy (hanya saat tool pertama butuh)
- [ ] Caching di `.codelens/lsp_cache/` untuk symbol retrieval result
- [ ] File watcher untuk auto-reindex saat file berubah
- [ ] Graceful shutdown saat CodeLens exit
- [ ] Dokumentasi: `references/lsp-setup.md` dengan prerequisite per bahasa (e.g., Python butuh `pyright`, TypeScript butuh `typescript-language-server`, Rust butuh `rust-analyzer`)
- [ ] Fallback: jika LSP tidak tersedia, fallback ke existing tree-sitter/regex parser dengan warning

**Scope teknis:**
- Vendor `src/solidlsp/` ke `scripts/solidlsp/` (atau add sebagai git submodule)
- Buat `scripts/lsp_manager.py`
- Update `base_parser.py` untuk check LSP availability pertama, fallback ke tree-sitter
- Tambah dependency: `pygls`, `lsprotocol` (untuk LSP protocol)
- Test: per-language integration test (port dari Serena `test/solidlsp/`)

**Estimasi effort:** 3-4 minggu (high complexity, LSP integration)

---

#### Issue S2 — Symbol-Level Retrieval Tools

**Motivasi (Serena):** Serena punya 5 symbol retrieval tool LSP-based:
- `find_symbol` — global/local search by name path pattern (`foo`, `foo/bar`, `/foo/bar`)
- `get_symbols_overview` — top-level symbol di file, grouped by kind
- `find_referencing_symbols` — cross-file reference finding dengan code snippet
- `find_defining_symbol` — find declaration site
- `find_implementations` — find implementation of interface/abstract

CodeLens `symbols` (fuzzy name search) dan `trace` (call graph) ada tapi tree-sitter-based — akurasi rendah, tidak cross-file dengan presisi.

**Acceptance Criteria:**
- [ ] Command baru: `codelens symbol <name> [--path PATTERN] [--include-body] [--depth N] [--kinds KINDS]`
  - LSP `workspace/symbol` untuk global search
  - Support name path pattern: `foo` (any), `foo/bar` (within), `/foo/bar` (top-level)
  - Filter by `SymbolKind` (Function, Class, Method, Interface, dll.)
  - `--include-body` untuk include symbol body
  - `--depth N` untuk include children
- [ ] Command baru: `codelens symbols-overview <file> [--depth N]`
  - LSP `textDocument/documentSymbol` untuk file outline
  - Grouped by kind (compact format)
  - First tool to call when understanding new file
- [ ] Command baru: `codelens references <symbol> [--file FILE]`
  - LSP `textDocument/references` untuk find all reference
  - Return code snippet around each reference
  - Cross-file (workspace-wide)
- [ ] Command baru: `codelens definition <symbol> [--file FILE]`
  - LSP `textDocument/definition` untuk find declaration
- [ ] Command baru: `codelens implementations <symbol> [--file FILE]`
  - LSP `textDocument/implementation` untuk find implementation
- [ ] Output format: `--format ai` → `{stats, items[], truncated, recommendations}`
- [ ] MCP tool: expose semua 5 command sebagai MCP tool
- [ ] Integrasi dengan existing `symbols` dan `trace` command — jika LSP available, use LSP; else fallback ke tree-sitter

**Scope teknis:**
- Tambah `scripts/commands/symbol.py`, `symbols_overview.py`, `references.py`, `definition.py`, `implementations.py`
- Reuse `lsp_manager.py` (Issue S1)
- Update `mcp_server.py` untuk expose 5 tool baru

**Estimasi effort:** 2-3 minggu (setelah Issue S1)

---

#### Issue S3 — Symbolic Editing Tools

**Motivasi (Serena):** Serena punya 3 symbolic editing tool:
- `replace_symbol_body` — replace entire symbol body (function, class, method). Atomik, precise
- `insert_after_symbol` — insert code setelah symbol tertentu
- `insert_before_symbol` — insert code sebelum symbol tertentu

CodeLens `fix` command ada tapi terbatas (autofix untuk specific pattern). Tidak ada generic symbolic editing.

**Acceptance Criteria:**
- [ ] Command baru: `codelens replace-symbol <symbol> <new-body> [--file FILE]`
  - Replace entire symbol body
  - Symbol identified by name path (`foo/bar`)
  - Auto-detect indentation
  - Return diff preview
- [ ] Command baru: `codelens insert-after-symbol <symbol> <new-code> [--file FILE]`
  - Insert new code setelah symbol tertentu
  - Useful untuk add new symbol di akhir file
- [ ] Command baru: `codelens insert-before-symbol <symbol> <new-code> [--file FILE]`
  - Insert new code sebelum symbol tertentu
  - Useful untuk add new symbol di awal file
- [ ] Safety: `--dry-run` flag untuk preview tanpa apply
- [ ] Safety: backup original file ke `.codelens/backup/` sebelum edit
- [ ] Integrasi dengan `guard --pre` (Issue existing) — pre-write check sebelum symbolic edit
- [ ] MCP tool: expose 3 command sebagai MCP tool
- [ ] Output: diff preview + applied change confirmation

**Scope teknis:**
- Tambah `scripts/commands/replace_symbol.py`, `insert_after_symbol.py`, `insert_before_symbol.py`
- Reuse `lsp_manager.py` (Issue S1) untuk locate symbol
- Update `guard` command untuk respect symbolic edit

**Estimasi effort:** 2 minggu

---

#### Issue S4 — LSP-Based Rename Refactoring

**Motivasi (Serena):** Serena support rename via:
- LSP `textDocument/rename` (language server backend) — rename symbol only
- JetBrains plugin `jet_brains_rename` — rename symbol, file, directory (atomic cross-file)

CodeLens `refactor-safe` hanya pre-flight check (apakah safe untuk rename), tidak ada eksekusi rename. User harus rename manual.

**Acceptance Criteria:**
- [ ] Command baru: `codelens rename <old-name> <new-name> [--file FILE] [--dry-run]`
  - LSP `textDocument/rename` untuk rename symbol cross-file
  - Return preview semua perubahan (file, line, old text, new text)
  - `--dry-run` untuk preview tanpa apply
  - Apply: write semua perubahan atomik
- [ ] Command baru: `codelens rename-file <old-path> <new-path> [--dry-run]`
  - Rename file + update semua import reference
  - LSP `workspace/willRenameFiles` + `workspace/didRenameFiles`
- [ ] Safety: backup original file sebelum apply
- [ ] Safety: `--force` flag untuk skip confirmation
- [ ] Integrasi dengan `refactor-safe` — run pre-check sebelum rename
- [ ] MCP tool: expose `rename` dan `rename_file` sebagai MCP tool
- [ ] Output format: `{status, preview: [{file, line, old_text, new_text}], applied: bool}`

**Scope teknis:**
- Tambah `scripts/commands/rename.py`, `rename_file.py`
- Reuse `lsp_manager.py` (Issue S1)
- Update `refactor_safe_engine.py` untuk integrate dengan rename

**Estimasi effort:** 2-3 minggu

---

### Tema S-B: Memory System

---

#### Issue S5 — Memory System dengan `mem:` Reference Convention

**Motivasi (Serena):** Serena punya memory system (`src/serena/memories/`):
- Project-specific memory di `.serena/memories/`
- Global memory di `~/.serena/memories/global/`
- `mem:NAME` reference convention — `` `mem:auth/login` `` reference ke memory lain
- Progressive disclosure — agent terima name list up front, read on-demand
- Referential integrity check via `serena memories check`
- Reference rename propagation
- Read-only pattern untuk global memory protection
- Ignored pattern untuk completely exclude memory
- 7 design criteria: human-readable, versionable, progressive disclosure, prefer references to search, prefer deliberate reads, framework-agnostic, configurable

CodeLens tidak punya memory system. Agent harus re-discover project context setiap session.

**Acceptance Criteria:**
- [ ] Direktori `.codelens/memories/` untuk project-specific memory
- [ ] Direktori `~/.codelens/memories/global/` untuk global memory
- [ ] Memory file format: Markdown (human-readable, versionable)
- [ ] Memory organization: topic via `/` in name (e.g., `modules/frontend`) → subdirectory mapping
- [ ] `mem:NAME` reference convention — `` `mem:auth/login` `` di memory content
- [ ] Command baru: `codelens memory write <name> <content>`
- [ ] Command baru: `codelens memory read <name>`
- [ ] Command baru: `codelens memory edit <name> <content>`
- [ ] Command baru: `codelens memory delete <name>`
- [ ] Command baru: `codelens memory rename <old-name> <new-name>` — rename + update reference
- [ ] Command baru: `codelens memory list [--topic TOPIC]` — list, filter by topic
- [ ] Command baru: `codelens memory check` — validate referential integrity, report stale reference
- [ ] Auto-fix: `codelens memory check --fix` — auto-fix broken reference jika possible
- [ ] Read-only pattern: config field `read_only_memory_patterns` (regex) — protect global memory dari write
- [ ] Ignored pattern: config field `ignored_memory_patterns` (regex) — completely exclude dari listing/reading/writing
- [ ] Name sanitization: handle common LLM mistake (`mem:` prefix, `.md` suffix, OS separator)
- [ ] Seed `memory_maintenance` memory saat first run — describe convention (style, reference)
- [ ] MCP tool: expose 6 memory command sebagai MCP tool
- [ ] Dokumentasi: `references/memories.md` dengan design rationale + usage guide

**Scope teknis:**
- Buat `scripts/memories/memory_manager.py` (port dari Serena `memory_manager.py`)
- Buat `scripts/memories/memory_reference_analysis.py` (port dari Serena `memory_reference_analysis.py`)
- Tambah `scripts/commands/memory.py`
- Update `init` command untuk create `.codelens/memories/` + seed `memory_maintenance`

**Estimasi effort:** 2-3 minggu

---

#### Issue S6 — Onboarding Process dengan Memory Write

**Motivasi (Serena):** Serena auto-onboarding saat first-time run di project:
1. Detect first-time (no `.serena/memories/` exist)
2. Trigger `onboarding` mode (read-only, collect info)
3. Write memory tentang: project structure, convention, key module, language, framework
4. Seed `memory_maintenance` memory — describe convention
5. Agent instructed to read `memory_maintenance` sebelum write project-specific memory

CodeLens `handbook` command ada tapi manual — user harus invoke explicitly. Tidak ada auto-onboarding.

**Acceptance Criteria:**
- [ ] Detect first-time run: jika `.codelens/memories/` kosong, trigger onboarding
- [ ] Onboarding mode: read-only (disable edit command), collect project info
- [ ] Auto-generate memory:
  - `project_overview.md` — project name, description, language, framework (reuse `detect` command)
  - `project_structure.md` — directory tree dengan description (reuse `outline` command)
  - `key_modules.md` — key module + summary (reuse `entrypoints` + `api-map`)
  - `conventions.md` — coding convention (reuse `smell` + `complexity` finding)
  - `suggested_commands.md` — useful CodeLens command untuk this project
- [ ] Seed `memory_maintenance.md` — describe memory convention (style, reference, when to write)
- [ ] Flag `--skip-onboarding` untuk skip
- [ ] Flag `--re-onboard` untuk force re-onboarding
- [ ] MCP tool: `onboarding` untuk trigger via MCP
- [ ] Integrasi dengan `init` command — `codelens init` auto-trigger onboarding

**Scope teknis:**
- Buat `scripts/onboarding_engine.py`
- Tambah `scripts/commands/onboarding.py`
- Reuse existing engine: `detect`, `outline`, `entrypoints`, `apimap_engine`, `smell_engine`, `complexity_engine`
- Update `init` command untuk auto-trigger onboarding

**Estimasi effort:** 1-2 minggu (setelah Issue S5)

---

### Tema S-C: Modes & Contexts System

---

#### Issue S7 — Modes System (Composable YAML Fragment)

**Motivasi (Serena):** Serena punya 9 mode (composable YAML fragment):
- `onboarding` — read-only, collect info
- `editing` — all tools, editing instruction
- `planning` — read-only, analyze + plan
- `interactive` — step-by-step with user clarification
- `one-shot` — autonomous, no interaction
- `no-memories` — disable memory + onboarding
- `no-onboarding` — skip onboarding
- `query-projects` — enable cross-project query
- `mode.template` — template

Setiap mode punya: `description`, `prompt`, `excluded_tools`, `included_optional_tools`. Mode composable — bisa combine multiple mode.

CodeLens tidak punya modes — semua command always available. Tidak ada way untuk adapt ke use case.

**Acceptance Criteria:**
- [ ] Direktori `scripts/modes/` dengan 9 mode YAML:
  - `onboarding.yml`, `editing.yml`, `planning.yml`, `interactive.yml`, `one-shot.yml`, `no-memories.yml`, `no-onboarding.yml`, `query-projects.yml`, `mode.template.yml`
- [ ] Mode structure:
  ```yaml
  description: ...
  prompt: |
    ...
  excluded_commands: []
  included_optional_commands: []
  ```
- [ ] Command baru: `codelens mode <mode-name>` — activate mode
- [ ] Command baru: `codelens mode list` — list all available mode
- [ ] Command baru: `codelens mode show <mode-name>` — show mode detail
- [ ] Composable: `codelens mode onboarding,interactive` — combine multiple mode
- [ ] Config field `active_modes` di `.codelens/config.json`
- [ ] Mode affect: command availability (excluded command disabled), system prompt (mode prompt injected)
- [ ] MCP tool: `set_mode`, `list_modes`, `get_mode` untuk MCP client
- [ ] Custom mode: user bisa create `.codelens/modes/custom.yml`
- [ ] Dokumentasi: `references/modes.md`

**Scope teknis:**
- Buat `scripts/modes/` directory dengan 9 YAML file
- Buat `scripts/mode_manager.py`
- Tambah `scripts/commands/mode.py`
- Update `mcp_server.py` untuk respect active mode (filter tool)

**Estimasi effort:** 1-2 minggu

---

#### Issue S8 — Contexts System (Per-AI-Client Configuration)

**Motivasi (Serena):** Serena punya 14 context (per-AI-client):
- `claude-code` — single project, structured output disabled (bug), tool override
- `codex` — non-symbolic editing + shell excluded
- `cursor`, `vscode`, `ide` — generic IDE
- `copilot-cli`, `chatgpt`, `antigravity`, `jb-ai-assistant`, `jb-copilot-plugin`, `junie`, `agent`, `oaicompat-agent`, `desktop-app`

Setiap context punya: `description`, `prompt`, `excluded_tools`, `included_optional_tools`, `tool_description_overrides`, `single_project`, `structured_tool_output`. Context adapt tool set + prompt per AI client.

CodeLens tidak punya contexts — satu konfigurasi untuk semua client.

**Acceptance Criteria:**
- [ ] Direktori `scripts/contexts/` dengan 14 context YAML:
  - `claude-code.yml`, `codex.yml`, `cursor.yml`, `vscode.yml`, `ide.yml`, `copilot-cli.yml`, `chatgpt.yml`, `antigravity.yml`, `jb-ai-assistant.yml`, `jb-copilot-plugin.yml`, `junie.yml`, `agent.yml`, `oaicompat-agent.yml`, `desktop-app.yml`, `context.template.yml`
- [ ] Context structure:
  ```yaml
  description: ...
  prompt: |
    ...
  excluded_commands: []
  included_optional_commands: []
  command_description_overrides: {}
  single_project: true
  structured_tool_output: false
  ```
- [ ] Command baru: `codelens context <context-name>` — set active context
- [ ] Command baru: `codelens context list` — list all context
- [ ] Auto-detect context dari environment variable:
  - `CLAUDE_CODE=true` → `claude-code`
  - `CURSOR=true` → `cursor`
  - `VSCODE=true` → `vscode`
  - `CODEX=true` → `codex`
  - dll.
- [ ] Config field `active_context` di `.codelens/config.json`
- [ ] Context affect: command availability, system prompt, command description, output format
- [ ] MCP tool: `set_context`, `list_contexts`, `get_context`
- [ ] Custom context: user bisa create `.codelens/contexts/custom.yml`
- [ ] Dokumentasi: `references/contexts.md`

**Scope teknis:**
- Buat `scripts/contexts/` directory dengan 14 YAML file
- Buat `scripts/context_manager.py`
- Tambah `scripts/commands/context.py`
- Update `mcp_server.py` untuk respect active context

**Estimasi effort:** 2 minggu

---

### Tema S-D: Multi-Layered Configuration

---

#### Issue S9 — Multi-Layered Configuration System

**Motivasi (Serena):** Serena punya 6-layer config:
1. Global config — `~/.serena/serena_config.yml`
2. CLI config — flag override
3. Per-project config — `.serena/project.yml`
4. Local override — `.serena/project.local.yml` (gitignored)
5. Context config — per-AI-client (14 context)
6. Mode config — composable mode fragment (9 mode)

Composition: Global → CLI → project → local → context → mode (later override earlier).

CodeLens config flat JSON di `.codelens/codelens.config.json`. Tidak ada layering, tidak ada local override, tidak ada context/mode composition.

**Acceptance Criteria:**
- [ ] 6-layer config:
  1. Global: `~/.codelens/config.yml`
  2. CLI: flag override
  3. Project: `.codelens/project.yml`
  4. Local: `.codelens/project.local.yml` (gitignored)
  5. Context: per-AI-client (Issue S8)
  6. Mode: composable fragment (Issue S7)
- [ ] Config format: YAML (bukan JSON) — support comment, multi-line string
- [ ] Config composition: merge dengan priority order
- [ ] Config validation: schema validation dengan default value
- [ ] Command: `codelens config show` — show effective config (after merge)
- [ ] Command: `codelens config show --source` — show config source per key
- [ ] Command: `codelens config init` — generate `.codelens/project.yml` template
- [ ] Command: `codelens config init --global` — generate `~/.codelens/config.yml`
- [ ] Backward compat: existing `.codelens/codelens.config.json` tetap berfungsi (auto-migrate ke `.codelens/project.yml`)
- [ ] Dokumentasi: `references/configuration.md` dengan all layer + priority

**Scope teknis:**
- Buat `scripts/config/serena_config.py` (port dari Serena config system)
- Update `init` command untuk generate new config format
- Auto-migrate dari old JSON config

**Estimasi effort:** 2 minggu

---

#### Issue S10 — Project Workflow dengan Additional Workspace Folders

**Motivasi (Serena):** Serena project workflow:
1. Project creation: `serena project create [options] [dir]` — auto-detect language, generate `.serena/project.yml`, optional `--index`
2. Project activation: `--project <path|name>` atau "activate project" via LLM
3. Onboarding: auto-onboard, write memory
4. Coding task: use Serena tool via MCP

Additional workspace folder untuk monorepo cross-package reference:
```yaml
additional_workspace_folders:
  - ../shared-lib
  - ../api-client
  - /absolute/path/to/another-package
```

CodeLens `init` ada tapi basic — tidak ada project activation, tidak ada additional workspace folder.

**Acceptance Criteria:**
- [ ] Command: `codelens project create [options] [dir]`
  - Auto-detect language dari source file
  - Generate `.codelens/project.yml`
  - Optional `--index` untuk pre-cache symbol (Issue S1)
  - Optional `--language <lang>` untuk explicit language
  - Optional `--name <name>` untuk custom project name
- [ ] Command: `codelens project activate <path|name>` — switch active project
- [ ] Command: `codelens project list` — list all known project
- [ ] Command: `codelens project index` — pre-cache symbol
- [ ] Additional workspace folder di `.codelens/project.yml`:
  ```yaml
  additional_workspace_folders:
    - ../shared-lib
    - ../api-client
    - /absolute/path/to/another-package
  ```
- [ ] Cross-package reference: LSP workspace folder registration (Issue S1)
- [ ] Multi-project: `codelens project activate <name>` untuk switch
- [ ] Project server: `codelens start-project-server` untuk multi-agent access ke single instance
- [ ] MCP tool: `activate_project`, `list_projects`, `query_project` (read-only query inactive project)
- [ ] Dokumentasi: `references/project-workflow.md`

**Scope teknis:**
- Buat `scripts/project_manager.py`
- Tambah `scripts/commands/project.py`
- Update `init` command untuk delegate ke `project create`

**Estimasi effort:** 2-3 minggu

---

### Tema S-E: Dashboard & DX

---

#### Issue S11 — Web Dashboard untuk Manage CodeLens

**Motivasi (Serena):** Serena punya web dashboard (`src/serena/resources/dashboard/`, `src/serena/dashboard.py`):
- HTML + CSS + jQuery (lightweight, no build step)
- Start: `serena dashboard` atau auto-start dengan MCP server
- Fitur: view active project, manage language server, view log, manage memory, manage project, tool overview
- Tray icon (macOS via `pystray`)
- `pywebview` untuk native window

CodeLens tidak punya dashboard. (Tapi Understand-Anything Issue U3 akan buat interactive knowledge graph dashboard — berbeda fokus.)

**Acceptance Criteria:**
- [ ] Command: `codelens dashboard [--port 8080] [--no-browser]`
- [ ] Spin up local web server (Flask)
- [ ] Auto-open browser ke `http://localhost:8080`
- [ ] Dashboard tech: HTML + CSS + vanilla JavaScript (lightweight, no build step)
- [ ] Dashboard page:
  - **Overview** — active project, language, mode, context, CodeLens version
  - **Language Server** — list active LS, start/stop/restart, status, log
  - **Memories** — list, read, edit, delete (Issue S5)
  - **Projects** — list, activate, switch (Issue S10)
  - **Commands** — list all command, description, availability per mode/context
  - **Logs** — real-time log streaming
  - **Config** — view effective config (Issue S9)
- [ ] Tray icon (macOS/Linux via `pystray`) — quick access menu
- [ ] `pywebview` untuk native window (opsional)
- [ ] Bind ke `127.0.0.1` only (security)
- [ ] Authentication: optional token via `--token` flag
- [ ] Dokumentasi: `references/dashboard.md`

**Scope teknis:**
- Buat `scripts/dashboard/` directory dengan HTML/CSS/JS
- Buat `scripts/dashboard_backend.py` (Flask server)
- Tambah `scripts/commands/dashboard.py`
- Tambah dependency: `flask`, `pystray` (optional), `pywebview` (optional)

**Estimasi effort:** 2-3 minggu

---

#### Issue S12 — Hook System (Pre-commit, Post-commit)

**Motivasi (Serena):** Serena punya `src/serena/hooks.py` dengan `serena-hooks` CLI entry point:
- Pre-commit hook — run sebelum commit (e.g., check memory reference, run analysis)
- Post-commit hook — run setelah commit (e.g., update memory, trigger re-scan)
- Hook triggered oleh git event → run Serena tool

CodeLens `pre_commit_hook.py` ada tapi terbatas (hanya pre-commit, hanya specific check).

**Acceptance Criteria:**
- [ ] Command: `codelens hooks install` — install git hook
- [ ] Command: `codelens hooks uninstall` — uninstall git hook
- [ ] Command: `codelens hooks list` — list installed hook
- [ ] Command: `codelens hooks run <hook-name>` — run hook manually
- [ ] Hook type:
  - `pre-commit` — run sebelum commit (e.g., `codelens check`, `codelens secrets`)
  - `post-commit` — run setelah commit (e.g., `codelens scan --incremental`, update memory)
  - `pre-push` — run sebelum push (e.g., full security audit)
  - `commit-msg` — validate commit message
- [ ] Hook config di `.codelens/hooks.yml`:
  ```yaml
  hooks:
    pre-commit:
      - codelens check --severity critical
      - codelens secrets
    post-commit:
      - codelens scan --incremental --quiet
      - codelens memory update project_structure
  ```
- [ ] Hook exit code: non-zero = block git operation
- [ ] Hook output: formatted untuk git hook (ke stderr, dengan `::error::` prefix untuk GitHub Actions)
- [ ] Dokumentasi: `references/hooks.md`

**Scope teknis:**
- Buat `scripts/hooks_manager.py`
- Tambah `scripts/commands/hooks.py`
- Generate hook script ke `.git/hooks/`

**Estimasi effort:** 1 minggu

---

### Tema S-F: Diagnostics & Quality

---

#### Issue S13 — LSP Diagnostics Integration

**Motivasi (Serena):** Serena pakai LSP diagnostics (`get_diagnostics` tool) — error, warning, info dari language server. Real-time, accurate, cross-file.

CodeLens `check` command ada tapi pakai engine sendiri (smell, complexity, dll) — tidak ada LSP diagnostics. Tidak bisa detect type error, syntax error, undefined reference dengan akurasi IDE.

**Acceptance Criteria:**
- [ ] Command baru: `codelens diagnostics [workspace] [--file FILE] [--severity error|warning|info]`
  - LSP `textDocument/publishDiagnostics` untuk get diagnostic
  - Filter by severity
  - Filter by file
  - Cross-file (workspace-wide)
- [ ] Integrasi dengan `check` command — tambah LSP diagnostic ke `check` output
- [ ] Integrasi dengan `smell` command — LSP diagnostic sebagai additional finding
- [ ] Integrasi dengan VS Code extension — push LSP diagnostic ke VS Code Problems panel
- [ ] MCP tool: `get_diagnostics` exposed via MCP
- [ ] Output format: `{status, stats: {error, warning, info}, items: [{file, line, column, severity, message, source}]}`

**Scope teknis:**
- Buat `scripts/diagnostics_engine.py`
- Tambah `scripts/commands/diagnostics.py`
- Reuse `lsp_manager.py` (Issue S1)
- Update `check` dan `smell` command untuk include LSP diagnostic

**Estimasi effort:** 1-2 minggu (setelah Issue S1)

---

#### Issue S14 — Cross-Package Reference untuk Monorepo

**Motivasi (Serena):** Serena `additional_workspace_folders` (TypeScript only saat ini) — register sibling package sebagai LSP workspace folder → cross-package reference discovery. Misal: `find_referencing_symbols` bisa discover usage di `../shared-lib` dan `../api-client`.

CodeLens `crossfile_taint_engine` ada tapi terbatas pada taint analysis intra-repo. Tidak bisa cross-package reference dengan presisi LSP.

**Acceptance Criteria:**
- [ ] Config field `additional_workspace_folders` di `.codelens/project.yml` (Issue S10):
  ```yaml
  additional_workspace_folders:
    - ../shared-lib
    - ../api-client
    - /absolute/path/to/another-package
  ```
- [ ] LSP workspace folder registration untuk semua listed folder
- [ ] Cross-package `find_referencing_symbols` (Issue S2) — discover reference di sibling package
- [ ] Cross-package `find_symbol` (Issue S2) — search symbol di sibling package
- [ ] Cross-package `rename` (Issue S4) — rename symbol di sibling package
- [ ] Performance: lazy index sibling package (hanya saat di-query)
- [ ] Currently supported: TypeScript (port dari Serena); add Python, Go, Rust, Java setelah LSP support matang
- [ ] Dokumentasi: `references/cross-package-reference.md`

**Scope teknis:**
- Update `lsp_manager.py` (Issue S1) untuk support multi-workspace folder
- Update `symbol_tools.py` (Issue S2) untuk search across all workspace folder
- Test: monorepo fixture dengan sibling package

**Estimasi effort:** 2 minggu (setelah Issue S1, S2)

---

### Tema S-G: Distribution & DX

---

#### Issue S15 — Multi-Client MCP Configuration Guide

**Motivasi (Serena):** Serena support 14 AI client dengan context-specific config (Issue S8). Dokumentasi per client di `docs/02-usage/030_clients.md` dengan install instruction.

CodeLens MCP server ada tapi dokumentasi client configuration terbatas (hanya `mcp_config.json` untuk Claude Desktop).

**Acceptance Criteria:**
- [ ] Dokumentasi: `references/clients.md` dengan install instruction untuk:
  - Claude Code (CLI)
  - Claude Desktop
  - Cursor
  - VS Code + Copilot
  - Codex
  - Codex CLI
  - Gemini CLI
  - OpenCode
  - OpenClaw
  - Antigravity
  - JetBrains AI Assistant
  - JetBrains Copilot plugin
  - JetBrains Junie
  - ChatGPT desktop
  - Generic OpenAI-compatible client
- [ ] Per-client config snippet:
  ```json
  // Claude Desktop - claude_desktop_config.json
  {
    "mcpServers": {
      "codelens": {
        "command": "python3",
        "args": ["/path/to/codelens/scripts/codelens.py", "serve"]
      }
    }
  }
  ```
- [ ] Per-client context auto-detection (Issue S8)
- [ ] Per-client tool subset (Issue S8)
- [ ] Verify: test setiap client configuration end-to-end
- [ ] Quick start: `codelens install-client <client-name>` — auto-generate config file di lokasi yang benar

**Scope teknis:**
- Buat `references/clients.md`
- Buat `scripts/commands/install_client.py` — auto-generate config
- Test dengan setiap client (jika feasible)

**Estimasi effort:** 1-2 minggu

---

#### Issue S16 — Docker Image (Minimal + Maximal)

**Motivasi (Serena):** Serena punya 2 Docker image:
- `Dockerfile` (minimal) — core only, user install language server on-demand
- `Dockerfile.maximal` — semua language server pre-installed
- `compose.yaml` + `docker_build_and_run.sh` untuk easy build & run

CodeLens tidak punya Docker image. (Tapi Repomix Issue R12 akan buat Docker — bisa combine.)

**Acceptance Criteria:**
- [ ] `Dockerfile` (minimal) — Python 3.11-slim + CodeLens core + tree-sitter grammar
- [ ] `Dockerfile.maximal` — minimal + semua LSP server (Pyright, TypeScript LS, gopls, rust-analyzer, clangd, jdtls, OmniSharp, dll)
- [ ] `compose.yaml` untuk easy run
- [ ] `docker_build_and_run.sh` helper script
- [ ] GitHub Actions: `publish-docker.yaml`
  - Build `ghcr.io/wolfvin/codelens:latest`, `:v8.x.y`, `:v8`
  - Build `ghcr.io/wolfvin/codelens:maximal-latest`, `:maximal-v8.x.y`
  - Multi-arch: `linux/amd64`, `linux/arm64`
- [ ] Docker usage:
  ```bash
  # Minimal
  docker run --rm -v $(pwd):/workspace ghcr.io/wolfvin/codelens:latest scan /workspace
  
  # Maximal (with all LSP)
  docker run --rm -v $(pwd):/workspace ghcr.io/wolfvin/codelens:maximal-latest symbol "main" /workspace
  ```
- [ ] Tambah ke README Installation section
- [ ] Combine dengan Repomix Issue R12 (Docker image untuk pack command) — satu image, semua fitur

**Scope teknis:**
- Buat `Dockerfile` + `Dockerfile.maximal`
- Buat `compose.yaml`
- Setup GHCR dengan GitHub Actions

**Estimasi effort:** 1 minggu

---

## 6. Prioritas & Roadmap Eksekusi

Roadmap diurutkan berdasarkan **impact** dan **dependency**:

### Fase S-1 — LSP Foundation (Q3 2026, ~5-7 minggu)

| Issue | Effort | Dependency | Impact |
|---|---|---|---|
| **S1** LSP client integration via solidlsp | 3-4 minggu | — | **kritis** (foundation untuk S2, S3, S4, S13, S14) |
| **S2** Symbol-level retrieval tools | 2-3 minggu | S1 | **kritis** |
| **S13** LSP diagnostics integration | 1-2 minggu | S1 | tinggi |

### Fase S-2 — Semantic Editing (Q4 2026, ~4-5 minggu)

| Issue | Effort | Dependency | Impact |
|---|---|---|---|
| **S3** Symbolic editing tools | 2 minggu | S1, S2 | tinggi |
| **S4** LSP-based rename refactoring | 2-3 minggu | S1, S2 | tinggi |
| **S14** Cross-package reference untuk monorepo | 2 minggu | S1, S2 | sedang |

### Fase S-3 — Memory & Onboarding (Q4 2026, ~3-5 minggu)

| Issue | Effort | Dependency | Impact |
|---|---|---|---|
| **S5** Memory system dengan `mem:` reference | 2-3 minggu | — | **kritis** |
| **S6** Onboarding process dengan memory write | 1-2 minggu | S5 | tinggi |

### Fase S-4 — Modes & Contexts (Q1 2027, ~3-4 minggu)

| Issue | Effort | Dependency | Impact |
|---|---|---|---|
| **S7** Modes system | 1-2 minggu | — | tinggi |
| **S8** Contexts system | 2 minggu | — | tinggi |
| **S9** Multi-layered configuration | 2 minggu | S7, S8 | sedang |

### Fase S-5 — Project & Workflow (Q1 2027, ~3-4 minggu)

| Issue | Effort | Dependency | Impact |
|---|---|---|---|
| **S10** Project workflow dengan workspace folder | 2-3 minggu | S1, S9 | sedang |
| **S12** Hook system | 1 minggu | — | sedang |

### Fase S-6 — Dashboard & Distribution (Q2 2027, ~4-5 minggu)

| Issue | Effort | Dependency | Impact |
|---|---|---|---|
| **S11** Web dashboard | 2-3 minggu | S5, S10 | sedang |
| **S15** Multi-client MCP configuration guide | 1-2 minggu | S8 | sedang |
| **S16** Docker image (minimal + maximal) | 1 minggu | — | sedang |

### Total Estimasi: ~22-30 minggu (~6-8 bulan)

**Quick win pertama:** Issue S5 (memory system) — 2-3 minggu, no dependency (selain S6 yang depend on-nya). Bisa dikerjakan paralel dengan Fase S-1.

**Highest impact:** Issue S1 (LSP integration) — ini foundation untuk 7 issue lainnya (S2, S3, S4, S13, S14, S10, S11). Tanpa LSP, semantic code operation tidak mungkin.

**Strategic:** Issue S5 + S6 (memory + onboarding) — ini mengubah CodeLens dari analysis tool menjadi **agent knowledge platform**. Agent bisa build up knowledge tentang project overtime, share dengan team, persist across session.

---

## 7. Catatan Teknis & Risiko

### 7.1 Risiko Teknis

1. **LSP integration complexity** — SolidLSP Serena adalah 50+ language server module dengan masing-masing config/quirk. Vendor ke CodeLens bukan trivial — butuh test per language.
   - **Mitigasi:** Mulai dengan 5 bahasa utama (Python, TypeScript, Go, Rust, Java). Tambah bahasa lain iteratif. Port test fixture dari Serena `test/solidlsp/`.

2. **Language server prerequisite** — User butuh install language server (Pyright, TypeScript LS, dll) separately. Ini barrier to entry.
   - **Mitigasi:** Auto-install via `codelens install-lsp <language>` command. Atau pakai Docker maximal image (Issue S16) yang pre-install semua LSP. Fallback ke tree-sitter jika LSP tidak ada.

3. **Memory system adoption** — Memory system butuh agent cooperation. Jika agent tidak baca/tulis memory, sistem tidak berguna.
   - **Mitigasi:** Strong system prompt yang instruct agent untuk baca `memory_maintenance` di awal session. MCP tool `list_memories` auto-return memory list di startup. Integrasi dengan onboarding (Issue S6) untuk seed initial memory.

4. **Modes/Contexts complexity** — 9 mode × 14 context = 126 kombinasi. Maintenance burden besar.
   - **Mitigasi:** Mulai dengan 3 mode utama (onboarding, editing, planning) dan 3 context utama (claude-code, vscode, generic). Tambah sisanya berdasarkan demand. Test matrix: tidak perlu test semua kombinasi, hanya test mode dan context secara independent.

5. **Performance impact** — LSP startup bisa 5-30 detik per language server. Untuk multi-language project, startup bisa lambat.
   - **Mitigasi:** Lazy start (hanya saat tool butuh). Background indexing. Cache symbol di `.codelens/lsp_cache/`. Dashboard (Issue S11) untuk monitor LSP status.

6. **SolidLSP license** — Serena MIT license, solidlsp juga MIT. Tapi perlu verify tidak ada GPL dependency transitif.
   - **Mitigasi:** License audit sebelum vendor. Document attribution.

### 7.2 Risiko Non-Teknis

1. **Scope creep** — 16 issue Serena-related + 16 OpenTaint + 16 Repomix + 16 Understand-Anything = 64 issue total. Butuh prioritization yang jelas.
   - **Mitigasi:** Roadmap bertahap. Fokus pada LSP foundation (S1, S2) dulu. Setiap issue dirilis sebagai minor version.

2. **Positioning blur** — CodeLens sebagai "analysis" + Serena sebagai "semantic operation" bisa blur. User bingung apa bedanya.
   - **Mitigasi:** Differentiate: CodeLens = analysis (taint, security, quality) + semantic operation (LSP-based). Serena = semantic operation only. CodeLens adalah superset.

3. **Competitive overlap dengan Serena** — Jika CodeLens `symbol` command terlalu mirip Serena, user bisa pilih salah satu.
   - **Mitigasi:** Differentiate: CodeLens symbol operation terintegrasi dengan analysis (bisa find symbol yang punya taint finding, complexity hotspot, dll — fitur yang Serena tidak punya).

4. **Maintenance burden untuk 50+ language server** — Setiap language server punya update cycle sendiri. Bug fix di upstream butuh update di CodeLens.
   - **Mitigasi:** Track upstream via dependabot. Community contribution untuk language-specific issue. Test matrix per language.

### 7.3 Yang TIDAK Perlu Diserap dari Serena

Beberapa hal Serena tidak relevant atau inferior untuk CodeLens:

1. **JetBrains plugin** — Serena JetBrains plugin adalah paid product. CodeLens open-source — tidak masuk model paid. Skip. Fokus ke LSP backend saja.

2. **Interactive debugging (JetBrains only)** — Breakpoint, variable inspection, expression evaluation. Terlalu kompleks untuk CodeLens CLI. Skip.

3. **AGNO integration** — Serena agno.py untuk AGNO framework. CodeLens tidak pakai AGNO. Skip.

4. **`agno` extra dependency** — Tidak relevan untuk CodeLens.

5. **`google-genai` extra** — Tidak relevan untuk CodeLens.

6. **Type hierarchy (JetBrains only)** — Skip (LSP juga limited support).

7. **Search in project dependencies (JetBrains only)** — Skip (LSP juga limited support).

### 7.4 Konvensi Penamaan yang Diadopsi dari Serena

Berikut konvensi Serena yang worth diadopsi di CodeLens:

- `.codelens/memories/` — project-specific memory (vs Serena `.serena/memories/`)
- `~/.codelens/memories/global/` — global memory
- `.codelens/project.yml` — project config (vs `.serena/project.yml`)
- `.codelens/project.local.yml` — local override (gitignored)
- `~/.codelens/config.yml` — global config
- `.codelens/modes/` — mode YAML fragment
- `.codelens/contexts/` — context YAML fragment
- `.codelens/hooks.yml` — hook config
- `.codelens/lsp_cache/` — LSP symbol cache
- `mem:NAME` reference convention
- `codelens memory write/read/edit/delete/rename/list/check` — memory command
- `codelens mode <name>` — mode command
- `codelens context <name>` — context command
- `codelens project create/activate/list/index` — project command
- `codelens hooks install/uninstall/list/run` — hooks command
- `codelens symbol/symbols-overview/references/definition/implementations` — symbol command
- `codelens replace-symbol/insert-after-symbol/insert-before-symbol` — symbolic edit command
- `codelens rename/rename-file` — refactor command
- `codelens diagnostics` — LSP diagnostics command
- `additional_workspace_folders` — config field untuk monorepo
- `read_only_memory_patterns` / `ignored_memory_patterns` — config field

---

## 8. Integrasi dengan Roadmap OpenTaint, Repomix, Understand-Anything

Dokumen ini adalah **pelengkap** dari analisis OpenTaint, Repomix, dan Understand-Anything sebelumnya. Keempatnya saling melengkapi:

| Aspek | OpenTaint | Repomix | Understand-Anything | Serena |
|---|---|---|---|---|
| **Fokus** | Kedalaman analysis (taint, rule) | Context delivery (packing) | Visual exploration (graph) | Semantic operation (LSP) |
| **Issue count** | 16 (A1-A4, B1-B3, C1-C3, D1-D4, E1-E2, F1-F2) | 16 (R1-R16) | 16 (U1-U16) | 16 (S1-S16) |
| **Total issue** | 64 issue combined | | | |
| **Quick win** | D3 (versioning) — 3 hari | R4 (split output) — 3-5 hari | U2 (layer detection) — 1 minggu | S5 (memory system) — 2-3 minggu |
| **Highest impact** | A1 (unified taint), A3 (approximation) | R1 (`pack` command), R2 (token counting) | U1 (schema), U3 (dashboard) | S1 (LSP integration), S2 (symbol tools) |
| **Strategic** | C1 (multi-skill orchestrator) | R8 (Agent Skills generation) | U5 (multi-agent pipeline) | S5+S6 (memory + onboarding) |

### 8.1 Cross-Issue Dependency

Beberapa issue saling bergantung antar-tema:

1. **Serena S1 (LSP integration)** ↔ **Understand-Anything U1 (knowledge graph schema)** — LSP symbol bisa jadi node di knowledge graph
   - Implementasi: `codelens symbol` (S2) return symbol → add sebagai `function`/`class` node di knowledge-graph.json (U1)

2. **Serena S2 (symbol tools)** ↔ **OpenTaint A4 (debug-trace taint)** — taint path bisa trace via LSP reference
   - Implementasi: debug-trace (A4) use `find_referencing_symbols` (S2) untuk trace taint propagation

3. **Serena S5 (memory system)** ↔ **Understand-Anything U5 (multi-agent pipeline)** — agent bisa share memory
   - Implementasi: orchestrator (U5) dispatch agent dengan memory context dari S5

4. **Serena S7 (modes) + S8 (contexts)** ↔ **OpenTaint C1 (multi-skill orchestrator)** — mode/context untuk workflow
   - Implementasi: orchestrator (C1) set mode `planning` untuk analysis phase, mode `editing` untuk fix phase

5. **Serena S10 (project workflow)** ↔ **Repomix R5 (remote repo processing)** — remote repo bisa jadi project
   - Implementasi: `codelens project create --remote <url>` (combine S10 + R5)

6. **Serena S11 (dashboard)** ↔ **Understand-Anything U3 (dashboard)** — bisa combine jadi satu dashboard
   - Implementasi: dashboard CodeLens (U3 untuk knowledge graph + S11 untuk manage LSP/memory/project)

7. **Serena S13 (LSP diagnostics)** ↔ **CodeLens existing `check`/`smell`** — combine jadi unified quality gate
   - Implementasi: `codelens check` run both LSP diagnostics (S13) + existing smell/complexity/dead-code

### 8.2 Rekomendasi Eksekusi Paralel

**Q3 2026 (Fase 1 semua tema):**
- OpenTaint Fase 1: D3, F2, D2, A1, F1
- Repomix Fase R-1: R1, R2, R3, R4
- Understand-Anything Fase U-1: U1, U9, U2
- Serena Fase S-1: S1, S2, S13

**Q4 2026 (Fase 2 semua tema):**
- OpenTaint Fase 2: A3, A4, B1, B2, E1
- Repomix Fase R-2: R5, R6
- Understand-Anything Fase U-2 + U-3: U3, U4, U5, U6
- Serena Fase S-2 + S-3: S3, S4, S14, S5, S6

**Q1 2027 (Fase 3 semua tema):**
- OpenTaint Fase 3: C2, C3, C1, A2, B3
- Repomix Fase R-3 + R-4: R7, R8, R9, R10
- Understand-Anything Fase U-4 + U-5: U7, U8, U10, U11, U12
- Serena Fase S-4 + S-5: S7, S8, S9, S10, S12

**Q2 2027 (Fase 4 semua tema):**
- OpenTaint Fase 4: D1, D4, E2
- Repomix Fase R-5 + R-6: R11, R12, R13, R14, R15, R16
- Understand-Anything Fase U-6: U13, U14, U15, U16
- Serena Fase S-6: S11, S15, S16

### 8.3 Total Roadmap

- **Total issue:** 64 (16 OpenTaint + 16 Repomix + 16 Understand-Anything + 16 Serena)
- **Total estimasi:** ~77-100 minggu (~18-25 bulan)
- **Rilis target:** v8.2 (Q3 2026) → v8.3 (Q4 2026) → v9.0 (Q1 2027) → v9.1 (Q2 2027) → v10.0 (Q3 2027) → v11.0 (Q4 2027)

**Versioning:**
- v8.x — OpenTaint Fase 1 + Repomix Fase R-1 + UA Fase U-1 + Serena Fase S-1
- v9.0 — Dashboard release (UA U3) + multi-agent pipeline (UA U5 + OpenTaint C1) + LSP integration (Serena S1+S2)
- v9.x — Domain graph, knowledge base, semantic search, memory system, modes/contexts
- v10.0 — Multi-platform plugin + homepage + final polish
- v11.0 — Final integration + polish

---

## Penutup

Dokumen ini adalah **analisis komprehensif** Serena sebagai sumber upgrade untuk CodeLens. Berbeda dengan OpenTaint (analysis depth), Repomix (context delivery), dan Understand-Anything (visual exploration), Serena fokus pada **semantic code operation** — keempatnya saling melengkapi.

**Rekomendasi eksekusi:**
1. **Mulai dari Fase S-1** (S1 LSP integration + S2 symbol tools + S13 diagnostics) — foundation yang membuka 10 issue lainnya.
2. **S1 (LSP integration) adalah highest-impact item** — menutup gap terbesar CodeLens (tidak ada semantic code operation). Tanpa LSP, CodeLens tidak bisa compete di semantic operation space.
3. **S5+S6 (memory + onboarding) adalah strategic** — mengubah CodeLens dari analysis tool jadi agent knowledge platform. Bisa dikerjakan paralel dengan Fase S-1 (no dependency).
4. **Differentiate dari Serena** — CodeLens semantic operation terintegrasi dengan analysis (bisa find symbol yang punya taint finding, complexity hotspot, security issue — fitur yang Serena tidak punya).
5. **64 issue total** (OpenTaint + Repomix + UA + Serena) dikerjakan paralel per fase, rilis sebagai minor version selama 18-25 bulan.

**Repo referensi:** https://github.com/oraios/serena.git (MIT License — kompatibel untuk inspiration/adaptasi/vendor dengan attribusi).
