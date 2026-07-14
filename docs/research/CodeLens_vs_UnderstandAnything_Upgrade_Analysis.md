# CodeLens ↔ Understand-Anything — Analisis Fitur & Rencana Upgrade (Issue Tracker)

> **Repo yang dianalisis sebagai sumber upgrade:** `Lum1104/Understand-Anything` (sekarang `Egonex-AI/Understand-Anything`) — https://github.com/Lum1104/Understand-Anything
> **Repo target upgrade:** `Wolfvin/CodeLens` (https://github.com/Wolfvin/CodeLens)
> **Tanggal analisis:** 2026-06-28
> **Versi Understand-Anything saat ini:** Multi-package monorepo (pnpm workspace) — `understand-anything-plugin`, `packages/core`, `packages/dashboard`, `homepage`
> **Versi CodeLens saat ini:** v8.1 (README) / v7.2.0 (`skill.json`, `pyproject.toml`)

---

## Daftar Isi

1. [Ringkasan Eksekutif](#1-ringkasan-eksekutif)
2. [Analisis Fitur Understand-Anything (Repo Referensi)](#2-analisis-fitur-understand-anything-repo-referensi)
3. [Matriks Komparasi Fitur Understand-Anything vs CodeLens](#3-matriks-komparasi-fitur-understand-anything-vs-codelens)
4. [Peningkatan yang Sudah Di-adjust di CodeLens](#4-peningkatan-yang-sudah-di-adjust-di-codelens)
5. [Daftar Issue untuk Next Upgrade (Serapan dari Understand-Anything)](#5-daftar-issue-untuk-next-upgrade-serapan-dari-understand-anything)
6. [Prioritas & Roadmap Eksekusi](#6-prioritas--roadmap-eksekusi)
7. [Catatan Teknis & Risiko](#7-catatan-teknis--risiko)
8. [Integrasi dengan Roadmap OpenTaint & Repomix](#8-integrasi-dengan-roadmap-opentaint--repomix)

---

## 1. Ringkasan Eksekutif

Understand-Anything adalah **Claude Code Plugin** yang mengubah codebase menjadi **interactive knowledge graph** — setiap file, function, class, dependency jadi node yang bisa di-click, di-search, dan di-explore di dashboard web interaktif. Dibuat oleh Yuxiang Lin (Lum1104), sekarang di bawah Egonex-AI.

**Filosofi Understand-Anything:** *visual code understanding* — fokus pada **knowledge graph + dashboard visualisasi**, bukan analysis mendalam (taint, security, complexity). Lawan dengan CodeLens yang fokus pada *command-line analysis* (58 command) dan Repomix yang fokus pada *context packing*.

**Posisi strategis:** Understand-Anything dan CodeLens **sangat complementary**:
- CodeLens unggul di **analysis depth** (taint, security, quality, compliance)
- Understand-Anything unggul di **visual exploration** (knowledge graph, dashboard, guided tour)
- CodeLens output adalah **JSON/SARIF text**; Understand-Anything output adalah **interactive web dashboard**

Serapan Understand-Anything ke CodeLens akan mengubah CodeLens dari **text-only CLI tool** menjadi **visual code intelligence platform** — user bisa dapat analysis mendalam (existing 58 command) **dan** visual exploration (new knowledge graph + dashboard).

**Top 10 kapabilitas Understand-Anything yang berguna untuk CodeLens:**

1. **Knowledge Graph Schema** dengan 35+ edge type across 8 category (Structural, Behavioral, Data Flow, Dependencies, Semantic, Infrastructure, Schema/Data, Domain, Knowledge) — lebih kaya dari CodeLens call graph yang hanya `imports`/`calls`/`contains`
2. **Multi-Agent Pipeline** (5-6 specialized agent: project-scanner, file-analyzer, architecture-analyzer, tour-builder, graph-reviewer, domain-analyzer, article-analyzer) dengan intermediate file-based state — pola orkestrasi yang lebih matang dari CodeLens single-skill
3. **Interactive Dashboard** (React + React Flow + Zustand + TailwindCSS v4) dengan graph visualization, node info panel, file explorer, search, layer legend — CodeLens tidak punya UI sama sekali
4. **Architectural Layer Detection** otomatis (API/Service/Data/UI/Middleware/External/Background/Utility/Test) dengan color-coded legend — CodeLens `entrypoints` dan `api-map` ada tapi tidak group per layer
5. **Guided Tour Generation** — auto-generate walkthrough berurutan berdasarkan dependency flow, untuk onboarding — CodeLens `handbook` ada tapi tidak terstruktur sebagai tour
6. **Domain Graph** (business domain → flow → step) — map code ke business process — CodeLens tidak punya ini
7. **Knowledge Base Analysis** (Karpathy-pattern LLM wiki) — parse wiki markdown jadi knowledge graph dengan entity extraction — CodeLens tidak punya
8. **Diff Impact Analysis dengan visual overlay** — `diff-overlay.json` untuk highlight changed + affected node di dashboard — CodeLens `diff` dan `impact` ada tapi tidak visual
9. **Persona-Adaptive UI** (junior dev / PM / power user) — dashboard adjust detail level — CodeLens tidak punya
10. **Layered Agent Output Validation** dengan alias normalization (NODE_TYPE_ALIASES, EDGE_TYPE_ALIASES, COMPLEXITY_ALIASES, DIRECTION_ALIASES) + autoFixGraph — robust error handling untuk LLM output — CodeLens tidak punya

**Rekomendasi tingkat tinggi:** Serap Understand-Anything sebagai **visualization layer** CodeLens. Buat `codelens dashboard` command yang spin up local web server dengan knowledge graph visualization. Tambah `codelens graph` command untuk generate knowledge-graph.json (reuse existing analysis engine). Tambah `codelens tour` untuk guided onboarding. Tambah `codelens domain` untuk business domain extraction. Ini akan mengubah CodeLens jadi **dual-mode tool**: CLI analysis + web dashboard.

---

## 2. Analisis Fitur Understand-Anything (Repo Referensi)

### 2.1 Arsitektur Umum

Understand-Anything adalah **monorepo TypeScript/Node.js** dengan pnpm workspaces:

| Komponen | Teknologi | Peran |
|---|---|---|
| `understand-anything-plugin/` | TypeScript | Claude Code Plugin container — semua source code |
| `understand-anything-plugin/packages/core/` | TypeScript | Shared analysis engine: types, persistence, tree-sitter, search, schema, tours, plugins, agents, languages, analyzers |
| `understand-anything-plugin/packages/dashboard/` | React + TypeScript + Vite | Web dashboard: React Flow (graph viz), Zustand (state), TailwindCSS v4, ELK layout, Louvain community detection |
| `understand-anything-plugin/src/` | TypeScript | Skill source untuk `/understand-chat`, `/understand-diff`, `/understand-explain`, `/understand-onboard` |
| `understand-anything-plugin/skills/` | Markdown | 8 skill definitions: understand, understand-chat, understand-diff, understand-explain, understand-onboard, understand-dashboard, understand-domain, understand-knowledge |
| `understand-anything-plugin/agents/` | Markdown | 9 agent definitions: project-scanner, file-analyzer, architecture-analyzer, tour-builder, graph-reviewer, domain-analyzer, article-analyzer, knowledge-graph-guide, assemble-reviewer |
| `understand-anything-plugin/packages/core/src/languages/` | TypeScript | 30+ language config (Python, JS, TS, Go, Rust, Java, C#, C, C++, PHP, Ruby, Swift, Kotlin, Dart, HTML, CSS, SQL, GraphQL, Protobuf, YAML, TOML, JSON, Markdown, Dockerfile, Makefile, Shell, Batch, PowerShell, Terraform, Kubernetes, etc.) + 10 framework config (React, Vue, Next, Express, Flask, Django, FastAPI, Spring, Gin, Rails) |
| `understand-anything-plugin/packages/core/src/plugins/` | TypeScript | Tree-sitter plugin system: registry, discovery, extractors (12 language: Python, TS, Go, Rust, Java, C#, C++, PHP, Ruby, Kotlin, Dart), parsers (Dockerfile, Makefile, Protobuf, GraphQL, TOML, JSON, Shell, YAML, Env, SQL, Markdown, Terraform) |
| `understand-anything-plugin/hooks/` | Markdown + JSON | `auto-update-prompt.md` — post-commit hook untuk auto-incremental update graph |
| `homepage/` | Astro + TypeScript | Marketing website (understand-anything.com) dengan live demo |
| `docs/superpowers/specs/` | Markdown | 14 design docs (design + implementation plan per fitur) |
| `tests/` | TypeScript + Python + MJS | Test suite (vitest) dengan fixture scan-result |

### 2.2 Skill Command Surface (8 Skills)

| Skill | Trigger | Peran |
|---|---|---|
| `/understand` | `understand [path] [--full\|--auto-update\|--no-auto-update\|--review\|--language <lang>]` | **Main skill** — analisa codebase, bangun knowledge graph ke `.understand-anything/knowledge-graph.json`. Multi-agent pipeline (5-6 agent). Auto-trigger `/understand-dashboard` setelah selesai |
| `/understand-dashboard` | `understand-dashboard` | Buka interactive web dashboard. Graph visualization, node info, file explorer, search, layer legend, persona selector |
| `/understand-chat` | `understand-chat [query]` | Q&A tentang codebase menggunakan knowledge graph. Grep graph untuk keyword, follow edge 1-hop, jawab dengan subgraph context |
| `/understand-diff` | `understand-diff` | Analyze git diff vs knowledge graph. Identify changed + affected node. Write `diff-overlay.json` untuk visualisasi di dashboard |
| `/understand-explain` | `understand-explain [file-path]` | Deep-dive explanation 1 file/function/class. Find node → find edges → read connected node → read source → explain in context |
| `/understand-onboard` | `understand-onboard` | Generate onboarding guide markdown dari knowledge graph. Section: Project Overview, Architecture Layers, Key Concepts, Guided Tour, File Map, Complexity Hotspots |
| `/understand-domain` | `understand-domain [--full]` | Extract business domain knowledge (domain → flow → step). Derive dari existing graph ATAU lightweight scan. Domain graph horizontal flow |
| `/understand-knowledge` | `understand-knowledge [wiki-directory]` | Analyze Karpathy-pattern LLM wiki. Deterministic parser extract wikilink/category + LLM agent extract entity/claim/implicit relationship. Force-directed graph dengan community clustering |

### 2.3 Multi-Agent Pipeline (`/understand`)

Pipeline `/understand` orchestrate 5-6 specialized agent:

| Agent | Role | Output |
|---|---|---|
| `project-scanner` | Discover files, detect languages and frameworks, pre-resolve import map | `scan-result.json` dengan file list, language detection, framework detection, `importMap` (pre-resolved import per file) |
| `file-analyzer` | Extract functions, classes, imports; produce graph nodes and edges. **Two-phase**: (1) structural extraction script (tree-sitter), (2) LLM semantic analysis (summary, tags, complexity, semantic edges) | `analysis-batch-{N}.json` per batch (5-10 file per batch, up to 20-30 file per batch, up to 5 concurrent batch) |
| `architecture-analyzer` | Identify architectural layers (API/Service/Data/UI/Middleware/External/Background/Utility/Test) berdasarkan directory pattern + LLM judgment | Layer assignment ke node |
| `tour-builder` | Generate guided learning tour. Tour step ordered by dependency flow (entry point → high-level → supporting utility) | `tour[]` array dengan `{order, title, description, nodeIds[], languageLesson?}` |
| `graph-reviewer` | Validate graph completeness and referential integrity. **Inline deterministic** by default (fast, free); `--review` flag untuk full LLM review | Validation report dengan issue list |
| `domain-analyzer` | Extract business domains, flows, process steps (hanya untuk `/understand-domain`) | Domain graph dengan `domain`/`flow`/`step` node type |
| `article-analyzer` | Extract entities, claims, implicit relationships dari wiki article (hanya untuk `/understand-knowledge`) | Analysis batch dengan `entity`/`claim`/`source` node + `cites`/`contradicts`/`builds_on` edge |
| `assemble-reviewer` | Merge batch graph, normalize via alias map, validate | Assembled `knowledge-graph.json` |
| `knowledge-graph-guide` | (Implicit) Guide dashboard interaction | — |

**Key design pattern:**
- Agent tulis intermediate result ke `.understand-anything/intermediate/` di disk (bukan ke context) — avoid context pollution
- Agent `model` field omitted dari frontmatter — fallback ke platform default (perbaikan issue #167: `inherit` keyword Claude Code-only, ditolak opencode)
- File analyzer run parallel (up to 5 concurrent, 20-30 file per batch)
- Incremental update: hanya re-analyze file yang changed sejak last run (fingerprint-based change detection)
- Intermediate file di-cleanup setelah graph assembly

### 2.4 Knowledge Graph Schema (`packages/core/src/schema.ts`)

**Node type** (canonical + alias):

| Category | Canonical Type | Alias |
|---|---|---|
| Code | `file`, `function`, `class`, `module`, `concept` | `func`, `fn`, `method`, `interface`, `struct`, `mod`, `pkg`, `package` |
| Non-code | `config`, `document`, `service`, `table`, `endpoint`, `pipeline`, `schema`, `resource` | `container`, `deployment`, `pod`, `doc`, `readme`, `docs`, `job`, `ci`, `route`, `api`, `query`, `mutation`, `setting`, `env`, `configuration`, `infra`, `infrastructure`, `terraform`, `migration`, `database`, `db`, `view`, `proto`, `protobuf`, `definition`, `typedef` |
| Domain | `domain`, `flow`, `step` | `business_domain`, `business_flow`, `business_process`, `task`, `business_step` |
| Knowledge | `article`, `entity`, `topic`, `claim`, `source` | `note`, `page`, `wiki_page`, `person`, `actor`, `organization`, `tag`, `category`, `theme`, `assertion`, `decision`, `thesis`, `reference`, `raw`, `paper` |

**Edge type** (35 value across 8 category):

| Category | Edge Type |
|---|---|
| Structural | `imports`, `exports`, `contains`, `inherits`, `implements` |
| Behavioral | `calls`, `subscribes`, `publishes`, `middleware` |
| Data flow | `reads_from`, `writes_to`, `transforms`, `validates` |
| Dependencies | `depends_on`, `tested_by`, `configures` |
| Semantic | `related`, `similar_to` |
| Infrastructure | `deploys`, `serves`, `provisions`, `triggers` |
| Schema/Data | `migrates`, `documents`, `routes`, `defines_schema` |
| Domain | `contains_flow`, `flow_step`, `cross_domain` |
| Knowledge | `cites`, `contradicts`, `builds_on`, `exemplifies`, `categorized_under`, `authored_by` |

**Edge alias** (40+ mapping): `extends`→`inherits`, `invokes`→`calls`, `uses`→`depends_on`, `relates_to`→`related`, `import`→`imports`, `publish`→`publishes`, `describes`→`documents`, `creates`→`provisions`, `exposes`→`serves`, `deploys_to`→`deploys`, `routes_to`→`routes`, `has_flow`→`contains_flow`, `next_step`→`flow_step`, `references`→`cites`, `conflicts_with`→`contradicts`, `refines`→`builds_on`, `instance_of`→`exemplifies`, `belongs_to`→`categorized_under`, `written_by`→`authored_by`, dll.

**Complexity alias:** `low`/`easy`→`simple`, `medium`/`intermediate`→`moderate`, `high`/`hard`/`difficult`→`complex`

**Direction alias:** `to`/`outbound`→`forward`, `from`/`inbound`→`backward`, `both`/`mutual`→`bidirectional`

**Auto-fix function** (`autoFixGraph`):
- Missing `type` → default `file` (auto-corrected warning)
- Missing `complexity` → default `moderate`
- Missing `tags` → default `[]`
- Missing `summary` → default ke `name`
- Missing `direction` → default `forward`
- Missing `weight` → default `0.5`
- String `weight` → coerce ke number
- Alias normalization untuk semua field

### 2.5 Tree-sitter + LLM Hybrid Approach

**Tree-sitter (deterministic):**
- Parse source ke concrete syntax tree
- Extract structural fact: imports, exports, function/class definition, call site, inheritance
- Pre-resolve ke `importMap` di scan phase → file-analyzer tidak perlu re-derive import dari source
- Same input → same output, every run (reproducible structural side)
- Power fingerprint-based change detection untuk incremental update

**LLM (semantic):**
- Read parsed structure + original source
- Produce apa yang parser tidak bisa: plain-English summary, tags, architectural layer assignment, business-domain mapping, guided tour, language concept callout
- Capture intent (apa file *untuk*, bukan hanya apa file *import*)

**Split rationale:** Structural reproducible (same code → same edge), semantic capture intent. Hybrid = best of both.

### 2.6 Language & Framework Support

**Language config** (`packages/core/src/languages/configs/` — 30+ file):
- Code: Python, JavaScript, TypeScript, Go, Rust, Java, C#, C, C++, PHP, Ruby, Swift, Kotlin, Dart, Lua
- Markup: HTML, CSS, XML, Markdown, reStructuredText
- Data/Config: JSON, JSON Schema, JSON5, YAML, TOML, CSV, Env, SQL, GraphQL, Protobuf, OpenAPI
- Infra: Dockerfile, Docker Compose, Makefile, Shell, Batch, PowerShell, Terraform, Kubernetes, Jenkinsfile, GitHub Actions

**Framework config** (`packages/core/src/languages/frameworks/` — 10 file):
- Frontend: React, Vue, Next.js
- Backend: Express, Flask, Django, FastAPI, Spring, Gin, Rails

**Tree-sitter extractor** (`packages/core/src/plugins/extractors/` — 12 file):
- Python, TypeScript, Go, Rust, Java, C#, C++, PHP, Ruby, Kotlin, Dart
- Plus base extractor untuk shared logic

**Custom parser** (`packages/core/src/plugins/parsers/` — 12 file):
- Dockerfile, Makefile, Protobuf, GraphQL, TOML, JSON, Shell, YAML, Env, SQL, Markdown, Terraform

**Language lesson** (`packages/core/src/analyzer/language-lesson.ts`):
- Auto-detect 12 programming pattern di code: Generics, Closures, Decorators, Async/Await, Interfaces, Inheritance, Higher-Order Functions, Pattern Matching, Traits/Mixins, Error Handling, Type Inference, Macros
- Generate `languageNotes` dan `languageLesson` field di node + tour step
- Explain pattern in context wherever they appear

### 2.7 Interactive Dashboard (`packages/dashboard/`)

**Tech stack:**
- React + TypeScript + Vite
- React Flow (graph visualization — node/edge rendering, pan/zoom, minimap)
- Zustand (state management)
- TailwindCSS v4 (styling)
- ELK layout (Euclidean Layout Kernel — automatic graph layout)
- Louvain algorithm (community detection untuk node clustering)
- prism-react-renderer (code viewer dengan syntax highlighting)

**Layout:**
- Graph-first: 75% graph + 360px right sidebar
- Dark luxury theme: deep black `#0a0a0a`, gold/amber accent `#d4a574`, DM Serif Display typography
- Mobile responsive (MobileLayout, MobileBottomNav, MobileDrawer)

**Sidebar tab:**
- `Info` — ProjectOverview (default) → NodeInfo (saat node dipilih) → LearnPanel (Learn persona, composing)
- `Files` — FileExplorer tree dari structural graph

**Component list (25+ component):**
- `GraphView` — main graph canvas (React Flow)
- `DomainGraphView` — horizontal flow graph untuk domain view
- `KnowledgeGraphView` — force-directed graph untuk knowledge base
- `CustomNode`, `FlowNode`, `PortalNode`, `ContainerNode`, `LayerClusterNode`, `DomainClusterNode`, `StepNode` — berbagai node type renderer
- `NodeInfo`, `NodeTooltip` — node detail panel
- `FileExplorer`, `CodeViewer` — file browser + code display
- `SearchBar` — fuzzy + semantic search
- `FilterPanel` — filter by layer/type/complexity
- `LayerLegend` — color-coded layer indicator
- `PathFinderModal` — find path antara 2 node
- `Breadcrumb` — navigation history
- `ExportMenu` — export graph as PNG/SVG/JSON
- `PersonaSelector` — switch persona (junior dev / PM / power user)
- `ThemePicker` — switch theme
- `OnboardingOverlay` — first-time user guide
- `LearnPanel` — language concept lesson
- `WarningBanner`, `TokenGate`, `DiffToggle`, `KeyboardShortcutsHelp`, `MobileBottomNav`, `MobileDrawer`

**Theme system** (`packages/dashboard/src/themes/`):
- Theme engine dengan preset
- ThemeContext untuk React context
- Custom theme support

**I18n** (`packages/dashboard/src/locales/`):
- 6 language: English, Korean, Chinese (Simplified), Chinese (Traditional), Japanese, Russian

**Layout engine** (`packages/dashboard/src/utils/`):
- `elk-layout.ts` — ELK layout integration
- `louvain.ts` — community detection
- `layout.worker.ts` — web worker untuk non-blocking layout computation
- `layout.ts` — layout orchestration
- `edgeAggregation.ts` — aggregate edge antara cluster
- `layerStats.ts` — statistic per layer
- `filters.ts` — filter logic
- `containers.ts` — container/group logic

### 2.8 Architectural Layer Detection (`packages/core/src/analyzer/layer-detector.ts`)

**9 layer** dengan directory pattern heuristic:

| Layer | Pattern | Description |
|---|---|---|
| API Layer | `routes`, `controller`, `handler`, `endpoint`, `api` | HTTP endpoint, route handler, API controller |
| Service Layer | `service`, `usecase`, `use-case`, `business` | Business logic, application service |
| Data Layer | `model`, `entity`, `schema`, `database`, `db`, `migration`, `repository`, `repo` | Data model, database access, persistence |
| UI Layer | `component`, `view`, `page`, `screen`, `layout`, `widget`, `ui` | User interface component |
| Middleware Layer | `middleware`, `interceptor`, `guard`, `filter`, `pipe` | Request/response middleware |
| External Services | `client`, `integration`, `external`, `sdk`, `vendor`, `adapter` | External service integration, SDK |
| Background Tasks | `worker`, `job`, `queue`, `cron`, `consumer`, `processor`, `scheduler`, `background` | Background worker, job processor |
| Utility Layer | `util`, `helper`, `lib`, `common`, `shared` | Shared utility, helper |
| Test Layer | `test`, `spec`, `__test__`, `__spec__`, `__tests__`, `__specs__` | Test file |

**Detection strategy:** First-match-wins (order matters). LLM dapat override dengan judgment.

### 2.9 Guided Tour Generation (`packages/core/src/analyzer/tour-generator.ts`)

**LLM prompt** untuk generate tour:
```
You are a software architecture educator. Generate a guided tour of the following project...

Create a logical tour that:
1. Starts with entry points or high-level overview files
2. Follows the natural dependency flow
3. Groups related files together
4. Ends with supporting utilities or concepts

Return a JSON object with a "steps" array. Each step must have:
- "order": sequential number starting from 1
- "title": a short descriptive title
- "description": 2-3 sentences explaining what the reader will learn
- "nodeIds": array of node IDs to highlight
- "languageLesson" (optional): brief note about language-specific patterns
```

**Tour step structure:**
```json
{
  "order": 1,
  "title": "Entry Point: main.ts",
  "description": "The application starts here. This file bootstrap the Express server and wire up all route handler.",
  "nodeIds": ["file:src/main.ts", "function:src/main.ts:startServer"],
  "languageLesson": "Notice the use of async/await for asynchronous server startup — this is a TypeScript pattern for handling Promise-based initialization."
}
```

### 2.10 Diff Impact Analysis (`/understand-diff`)

**Workflow:**
1. Check `knowledge-graph.json` exist
2. Get changed file list via `git diff --name-only` (uncommitted) atau `git diff main...HEAD --name-only` (feature branch)
3. Read project metadata only (efficient — tidak load full graph ke context)
4. **Grep graph** untuk match changed file path ke node `filePath`
5. **Grep edge** untuk find 1-hop connection (upstream caller + downstream dependency)
6. Identify affected layer
7. Structured analysis output:
   - Changed Components (directly modified, with summary)
   - Affected Components (1-hop, might break)
   - Affected Layers (which layer touched, cross-layer concern)
   - Risk Assessment (based on complexity, cross-layer edge count, blast radius)
8. Write `diff-overlay.json` untuk dashboard visualization:
   ```json
   {
     "version": "1.0.0",
     "baseBranch": "main",
     "generatedAt": "2026-06-28T10:30:45Z",
     "changedFiles": ["src/auth/login.ts"],
     "changedNodeIds": ["file:src/auth/login.ts", "function:src/auth/login.ts:verifyToken"],
     "affectedNodeIds": ["file:src/middleware/auth.ts", "file:src/routes/user.ts"]
   }
   ```

### 2.11 Domain Graph (`/understand-domain`)

**Business domain extraction:**
- **Domain** — high-level business area (e.g., "Authentication", "Payment", "Order Management")
- **Flow** — business process within domain (e.g., "User Login Flow", "Checkout Flow")
- **Step** — individual step dalam flow (e.g., "Validate Credentials", "Generate Token", "Set Session")

**Two path:**
1. **Derive from existing graph** (cheap) — jika `knowledge-graph.json` exist, LLM analyze graph untuk extract domain/flow/step
2. **Lightweight scan** (fallback) — file tree + entry point detection + sampled file → domain-analyzer agent

**Output:** `domain-graph.json` dengan horizontal flow visualization (domain → flow → step, left-to-right)

**Edge type:** `contains_flow` (domain → flow), `flow_step` (flow → step), `cross_domain` (cross-domain interaction)

### 2.12 Knowledge Base Analysis (`/understand-knowledge`)

**Karpathy-pattern LLM wiki** (https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f):
- **Raw sources** — immutable source document (article, paper, data file) di `raw/`
- **Wiki** — LLM-generated markdown file dengan wikilink (`[[target]]` syntax)
- **Schema** — `CLAUDE.md`, `AGENTS.md`, atau similar config file
- **index.md** — content catalog organized by category
- **log.md** — chronological operation log

**Detection signal:** has `index.md` + multiple `.md` file dengan wikilink

**Pipeline:**
1. **DETECT** — `parse-knowledge-base.py` detect format, output `scan-manifest.json`
2. **SCAN** (sudah di Phase 1) — deterministic extraction: article node, source node, topic node, `related` edge (wikilink), `categorized_under` edge (index.md section)
3. **ANALYZE** — dispatch `article-analyzer` subagent per batch (10-15 article per batch, up to 3 concurrent), extract implicit knowledge: entity, claim, source node + `cites`/`contradicts`/`builds_on`/`exemplifies`/`authored_by` edge
4. **MERGE** — `merge-knowledge-graph.py` combine scan-manifest + analysis-batch, deduplicate entity (case-insensitive name matching), normalize via alias map, build layer dari index.md category, build tour dari index.md section ordering
5. **SAVE** — validate (every edge source/target must reference existing node), save `knowledge-graph.json` + `meta.json`, cleanup intermediate
6. **Launch dashboard** — force-directed layout (bukan hierarchical dagre) untuk knowledge graph

### 2.13 Token Reduction Strategy (`docs/superpowers/specs/2026-03-27-token-reduction-design.md`)

**Problem:** 500-file TypeScript+React project → ~529,000 input tokens. Breakdown:
- `allProjectFiles` list × 67 batch = ~167,000 tokens (50%)
- `file-analyzer-prompt.md` × 67 batch = ~134,000 tokens (40%)
- Language/framework addendum × 67 batch = ~68,000 tokens (20%)
- Tour builder payload = ~80,000 tokens (24%)
- Graph reviewer = ~58,000 tokens (17%)
- Architecture analyzer = ~22,000 tokens (7%)

**Root cause:** Phase 2 run 67 batch (5-10 file per batch), setiap batch terima full 500-file list untuk import resolution. Redundant.

**5 change (C1-C5) untuk 85-90% reduction:**
- **C1** — Pre-resolve import di project scanner. `scan-result.json` gain `importMap` field. File-analyzer batch terima hanya batch's pre-resolved import, bukan full file list
- **C2** — Prompt compression (streamline file-analyzer prompt)
- **C3** — Language/framework addendum lazy load (hanya inject jika relevant)
- **C4** — Tour builder incremental (hanya re-generate tour step untuk changed node)
- **C5** — Graph reviewer inline deterministic by default (free, fast), `--review` flag untuk full LLM review

### 2.14 Incremental Update & Auto-Update Hook

**Incremental update:**
- Fingerprint-based change detection (file content hash)
- Hanya re-analyze file yang changed sejak last run
- Subsequent run jauh lebih murah dari initial run

**Auto-update via post-commit hook** (`/understand --auto-update`):
- Write `autoUpdate: true` ke `.understand-anything/config.json`
- `hooks/auto-update-prompt.md` — prompt untuk post-commit hook
- Setiap commit trigger incremental graph patch → graph selalu sync dengan code

**Worktree redirect:**
- Jika `PROJECT_ROOT` di git worktree (bukan main checkout), redirect output ke main repo root
- Worktree Claude Code ephemeral → `.understand-anything/` di worktree di-destroy saat session end
- Detect via `git rev-parse --git-dir` vs `git rev-parse --git-common-dir`
- Override dengan `UNDERSTAND_NO_WORKTREE_REDIRECT=1`

### 2.15 Multi-Platform Distribution

**17 platform support:**

| Platform | Install Method |
|---|---|
| Claude Code | `/plugin marketplace add Egonex-AI/Understand-Anything` → `/plugin install understand-anything` |
| Cursor | Auto-discovery via `.cursor-plugin/plugin.json` |
| VS Code + GitHub Copilot | Auto-discovery via `.copilot-plugin/plugin.json` (Copilot v1.108+) |
| Copilot CLI | `copilot plugin install Egonex-AI/Understand-Anything:understand-anything-plugin` |
| Codex | `install.sh codex` |
| OpenCode | `install.sh opencode` |
| OpenClaw | `install.sh openclaw` |
| Antigravity | `install.sh antigravity` |
| Gemini CLI | `install.sh gemini` |
| Pi Agent | `install.sh pi` |
| Vibe CLI | `install.sh vibe` |
| VS Code (personal skill) | `install.sh vscode` |
| Hermes | `install.sh hermes` |
| Cline | `install.sh cline` |
| KIMI CLI | `install.sh kimi` |
| Trae | `install.sh trae` |
| Nanobot | `install.sh nanobot` |
| Kiro CLI / IDE | `install.sh kiro` |

**Installer:** `install.sh` (macOS/Linux) + `install.ps1` (Windows PowerShell). Clone repo ke `~/.understand-anything/repo`, create symlink per platform.

**Update:** `./install.sh --update`
**Uninstall:** `./install.sh --uninstall <platform>`

### 2.16 Graph Sharing & Git LFS

**Share graph dengan team:**
- Graph adalah JSON — commit sekali, teammate skip pipeline
- Good for onboarding, PR review, docs-as-code

**What to commit:** semua di `.understand-anything/` kecuali `intermediate/` dan `diff-overlay.json` (local scratch)

```gitignore
.understand-anything/intermediate/
.understand-anything/diff-overlay.json
```

**Large graph (10 MB+):** track dengan git-lfs
```bash
git lfs install
git lfs track ".understand-anything/*.json"
git add .gitattributes .understand-anything/
```

### 2.17 Documentation & Design Process

**14 design doc** di `docs/superpowers/specs/`:
- `2026-03-14-understand-anything-design.md` — Initial design
- `2026-03-15-homepage-design.md` — Homepage design
- `2026-03-18-multi-platform-simple-design.md` — Multi-platform install
- `2026-03-21-language-agnostic-design.md` — Language-agnostic extractor
- `2026-03-26-theme-system-design.md` — Theme system
- `2026-03-27-token-reduction-design.md` — Token reduction (85-90%)
- `2026-03-28-understand-anything-extension-design.md` — Browser extension
- `2026-03-29-homepage-update-design.md` — Homepage update
- `2026-04-01-business-domain-knowledge-design.md` — Domain graph
- `2026-04-09-understand-knowledge-design.md` — Knowledge base analysis
- `2026-04-10-understandignore-design.md` — `.understandignore` file
- `2026-05-03-graph-layout-scaling-design.md` — Large graph layout
- `2026-05-24-semantic-batching-and-output-chunking-design.md` — Semantic batching
- `2026-06-03-language-auto-detection-design.md` — Language auto-detection

**20 implementation plan** di `docs/superpowers/plans/` — detailed step-by-step plan per fitur (phase1-4, homepage, multi-platform, language-agnostic, dashboard-robustness, theme-system, token-reduction, extension, homepage-update, business-domain-knowledge, understand-knowledge, understandignore, language-extractors, graph-layout-scaling, semantic-batching, language-auto-detection).

**Pattern:** Setiap fitur punya `design.md` (spec) + `impl.md` (implementation plan) — rigorous engineering process.

### 2.18 Testing & Quality

- **Vitest** untuk test (skill test di `tests/skill/`, core test di `packages/core/src/__tests__/` dan `packages/core/src/plugins/extractors/__tests__/`)
- **Fixture-based test** — `tests/skill/understand/fixtures/scan-result-*.json` untuk test merge logic
- **TypeScript strict mode** everywhere
- **ESLint** v9 dengan `typescript-eslint`
- **Test coverage:** extractor per language, parser per format, schema validation, ignore filter, fingerprint, search, normalize-graph, layer-detector, tour-generator, staleness, domain-normalize, plugin-discovery, framework-registry, language-registry, embedding-search

### 2.19 Embedding Search (`packages/core/src/embedding-search.ts`)

**Semantic search** untuk find node by meaning, bukan hanya by name:
- "which parts handle auth?" → return relevant node across graph
- Embedding-based search (bukan hanya fuzzy string match)
- Complement dengan fuzzy search (name-based)

### 2.20 Staleness Detection (`packages/core/src/staleness.ts`)

**Track graph staleness:**
- Compare `gitCommitHash` di `meta.json` vs current `git rev-parse HEAD`
- Compare file fingerprint vs current file content hash
- Flag node sebagai `stale` jika underlying file berubah sejak last analysis
- Trigger re-analysis untuk stale node only (incremental update)

### 2.21 Ignore System (`packages/core/src/ignore-filter.ts` + `ignore-generator.ts`)

**Multi-source ignore:**
- `.gitignore` (git standard)
- `.understandignore` (Understand-Anything specific — pattern sama dengan `.gitignore`)
- Built-in default (node_modules, .git, build dir, dll.)
- Custom pattern dari config

**Ignore generator:** auto-generate `.understandignore` berdasarkan detected framework (e.g., Next.js → ignore `.next/`, Vue → ignore `dist/`).

### 2.22 Plugin System (`packages/core/src/plugins/`)

**Tree-sitter plugin system:**
- `registry.ts` — plugin registry
- `discovery.ts` — auto-discover plugin di node_modules / local
- `tree-sitter-plugin.ts` — plugin base class
- `extractors/` — 12 language extractor (Python, TS, Go, Rust, Java, C#, C++, PHP, Ruby, Kotlin, Dart)
- `parsers/` — 12 custom parser (Dockerfile, Makefile, Protobuf, GraphQL, TOML, JSON, Shell, YAML, Env, SQL, Markdown, Terraform)

**Plugin discovery:** auto-detect tree-sitter grammar package di `node_modules`, register extractor/parser sesuai grammar.

---

## 3. Matriks Komparasi Fitur Understand-Anything vs CodeLens

| Kapabilitas | CodeLens | Understand-Anything | Gap CodeLens |
|---|:---:|:---:|---|
| **Core purpose** | Code intelligence (analysis) | Code understanding (visualization) | different niche |
| **Tech stack** | Python (tree-sitter native + regex) | TypeScript/Node.js (web-tree-sitter WASM) | — |
| **Command count** | 58 command | 8 skill | — (CodeLens lebih luas) |
| **Output format** | JSON, SARIF, text | Interactive web dashboard + JSON | **besar** |
| **Knowledge graph schema** | ⚠️ basic (nodes/edges call graph) | ✅ 35+ edge type, 8 category, 25+ node type dengan alias | **besar** |
| **Multi-agent pipeline** | ❌ (single skill) | ✅ 5-6 specialized agent dengan intermediate file | **besar** |
| **Interactive dashboard** | ❌ | ✅ React + React Flow + ELK + Louvain | **besar (kritis)** |
| **Architectural layer detection** | ⚠️ `entrypoints`, `api-map` (basic) | ✅ 9 layer dengan pattern + LLM | sedang |
| **Guided tour generation** | ⚠️ `handbook` (basic) | ✅ ordered tour dengan languageLesson | sedang |
| **Domain graph (business logic)** | ❌ | ✅ domain → flow → step | **besar** |
| **Knowledge base analysis** | ❌ | ✅ Karpathy-pattern LLM wiki | sedang |
| **Diff impact dengan visual overlay** | ⚠️ `diff`, `impact` (text only) | ✅ `diff-overlay.json` untuk dashboard | sedang |
| **Persona-adaptive UI** | ❌ | ✅ junior dev / PM / power user | kecil |
| **Layer visualization** | ❌ | ✅ color-coded legend, layer cluster | sedang |
| **Language concept lesson** | ❌ | ✅ 12 pattern (generics, closures, decorator, dll.) | sedang |
| **Embedding/semantic search** | ⚠️ `search` (regex), `symbols` (fuzzy) | ✅ embedding + fuzzy hybrid | sedang |
| **Staleness detection** | ❌ | ✅ gitCommitHash + fingerprint | kecil |
| **Auto-update via post-commit hook** | ❌ | ✅ `--auto-update` flag | sedang |
| **Incremental update** | ✅ `scan --incremental` | ✅ fingerprint-based | setara |
| **Multi-platform support** | ⚠️ CLI only (Python) | ✅ 17 AI platform (Claude Code, Cursor, Copilot, Codex, dll.) | besar |
| **Plugin system** | ✅ 4 type, 3-tier | ✅ tree-sitter plugin (extractor/parser) | setara (different focus) |
| **MCP server** | ✅ 49 tools | ❌ (plugin-based, bukan MCP) | — (CodeLens unggul) |
| **VS Code extension** | ✅ native | ⚠️ via platform plugin | — (CodeLens unggul) |
| **Pre-write safety check** | ✅ `query` + `guard` | ❌ | — (CodeLens unggul) |
| **Taint analysis** | ✅ AST-based path-sensitive | ❌ | — (CodeLens unggul) |
| **Cross-file analysis** | ✅ call graph, impact, dependents | ⚠️ via edge di graph | setara |
| **Code smell detection** | ✅ 10 category | ❌ | — (CodeLens unggul) |
| **Complexity scoring** | ✅ cyclomatic + cognitive | ⚠️ `complexity` field (simple/moderate/complex) | — (CodeLens lebih dalam) |
| **Dead code detection** | ✅ | ❌ | — (CodeLens unggul) |
| **A11y auditing** | ✅ WCAG 2.1 | ❌ | — (CodeLens unggul) |
| **CSS deep analysis** | ✅ | ❌ | — (CodeLens unggul) |
| **CVE/vuln scanning** | ✅ OSV.dev | ❌ | — (CodeLens unggul) |
| **Secret detection** | ✅ `secrets` engine | ❌ | — (CodeLens unggul) |
| **Compliance rules** | ✅ HIPAA, PCI-DSS | ❌ | — (CodeLens unggul) |
| **OWASP Top 10** | ✅ 36 rules | ❌ | — (CodeLens unggul) |
| **Benchmark regression** | ✅ `run_benchmarks.py` | ⚠️ `scripts/generate-large-graph.mjs` (perf test) | — (CodeLens unggul) |
| **Token counting** | ⚠️ `--max-tokens N` (basic) | ⚠️ token reduction design doc | setara (both weak) |
| **AI-optimized output** | ✅ `--format ai`, `--lite`, `--top N` | ❌ | — (CodeLens unggul) |
| **Multi-language support** | 30+ (10 native + 20+ fallback) | 30+ (12 tree-sitter + custom parser) | setara |
| **Framework detection** | ✅ React/Vue/Svelte/Tailwind/Express/dll. | ✅ React/Vue/Next/Express/Flask/Django/FastAPI/Spring/Gin/Rails | setara |
| **Translation** | ❌ | ✅ 6 language (en, ko, zh, zh-TW, ja, ru) + 8 README translation | Understand-Anything unggul |
| **Auto-update hook** | ❌ | ✅ post-commit hook | sedang |
| **Graph sharing** | ⚠️ registry `.codelens/` | ✅ commit `knowledge-graph.json` + git-lfs | sedang |
| **Worktree redirect** | ❌ | ✅ auto-redirect ke main repo | kecil |
| **Schema validation + auto-fix** | ❌ | ✅ alias normalization + autoFixGraph | **besar** |
| **Design doc rigor** | ⚠️ CHANGELOG + references | ✅ 14 spec + 20 implementation plan | Understand-Anything unggul |
| **Homepage + live demo** | ❌ | ✅ understand-anything.com dengan live demo | Understand-Anything unggul |

---

## 4. Peningkatan yang Sudah Di-adjust di CodeLens

Berikut hal yang **sudah dimiliki CodeLens** dan **tidak perlu** diserap dari Understand-Anything:

### 4.1 Analysis Depth (Core Differentiator)

- ✅ **AST taint analysis** dengan CFG, path-sensitive, inter-procedural
- ✅ **Cross-file taint engine** dengan workspace-wide call graph
- ✅ **Dataflow analysis** dengan source→sink YAML rules
- ✅ **Code smell detection** (10 category)
- ✅ **Complexity scoring** (cyclomatic + cognitive — lebih dalam dari UA's simple/moderate/complex)
- ✅ **Dead code detection** dengan reference tracking
- ✅ **CSS deep analysis** (unused variables, orphan keyframes, specificity wars, z-index abuse)
- ✅ **A11y auditing** (WCAG 2.1)
- ✅ **Performance hints** (N+1 queries, sync blocking, memory leaks)
- ✅ **Regex audit** (ReDoS detection)
- ✅ **Secret detection** (`secrets` engine)
- ✅ **CVE/vuln scanning** (OSV.dev)

Understand-Anything sama sekali tidak punya analysis mendalam — hanya structural extraction + LLM summary.

### 4.2 Pre-Write Safety & Guard Hooks

- ✅ `query "name"` dengan status decision rules (CREATE/EXTEND/ASK/STOP)
- ✅ `guard --pre/--post` untuk AI agent workflow
- ✅ `refactor-safe` rename/move safety check
- ✅ `impact` change impact analysis dengan risk level

### 4.3 MCP Server (49 Tools vs 0)

- ✅ 49 MCP tools (semua CodeLens command ter-expose)
- ✅ MCP spec `2025-03-26` via JSON-RPC 2.0 over stdio
- ✅ In-memory registry caching, sub-millisecond query
- ✅ HTTP/SSE transport opsional

Understand-Anything tidak punya MCP server — hanya Claude Code plugin.

### 4.4 Plugin System (4 Type vs 1 Type)

- ✅ 4 plugin types (rule_pack/engine/formatter/command)
- ✅ 3-tier discovery (project/user/built-in)
- ✅ Plugin isolation
- ✅ Built-in OWASP Top 10 (36 rules) + Compliance (HIPAA, PCI-DSS — 53 rules)

Understand-Anything hanya punya tree-sitter plugin (extractor/parser).

### 4.5 Wide Command Surface (58 vs 8)

CodeLens punya 58 command vs Understand-Anything's 8 skill. CodeLens jauh lebih luas untuk analysis task.

### 4.6 AI-Native Output

- ✅ `--format ai` normalized schema
- ✅ `--lite` per-command tailored output
- ✅ `--top N` smart default
- ✅ `--max-tokens N` (basic, akan di-enhance di Issue R2 Repomix analysis)
- ✅ `CODELENS_AI_MODE=1` env var
- ✅ Zero-config auto-init + auto-scan

### 4.7 Benchmark & Regression

- ✅ `benchmarks/run_benchmarks.py` + `check_regression.py`
- ✅ Fixture `vulnerable_app/` dengan `ground_truth.yaml`

Understand-Anything hanya punya `generate-large-graph.mjs` untuk perf test, tanpa regression checker.

### 4.8 Compliance & Security Rules

- ✅ OWASP Top 10 (36 rules dengan CWE + OWASP metadata)
- ✅ HIPAA + PCI-DSS (53 rules)
- ✅ Tag-based plugin discovery

---

## 5. Daftar Issue untuk Next Upgrade (Serapan dari Understand-Anything)

Berikut **issue-issue konkret** untuk diajukan ke repo CodeLens, dikelompokkan per tema. Setiap issue sudah disertai: motivasi (referensi Understand-Anything), acceptance criteria, dan scope teknis.

### Tema U-A: Knowledge Graph Schema

---

#### Issue U1 — Rich Knowledge Graph Schema dengan 35+ Edge Type

**Motivasi (Understand-Anything):** UA punya schema (`packages/core/src/schema.ts`) dengan:
- 25+ node type (code: file/function/class/module/concept; non-code: config/document/service/table/endpoint/pipeline/schema/resource; domain: domain/flow/step; knowledge: article/entity/topic/claim/source)
- 35+ edge type across 8 category (Structural, Behavioral, Data Flow, Dependencies, Semantic, Infrastructure, Schema/Data, Domain, Knowledge)
- Alias normalization (NODE_TYPE_ALIASES, EDGE_TYPE_ALIASES, COMPLEXITY_ALIASES, DIRECTION_ALIASES) — handle LLM output variation
- autoFixGraph function — auto-correct missing field dengan default value + warning

CodeLens call graph hanya punya basic `imports`/`calls`/`contains` edge. Tidak ada data flow edge (`reads_from`/`writes_to`/`transforms`/`validates`), tidak ada infrastructure edge (`deploys`/`serves`/`provisions`/`triggers`), tidak ada semantic edge (`related`/`similar_to`).

**Acceptance Criteria:**
- [ ] Buat `scripts/knowledge_graph_schema.py` dengan:
  - `NodeType` enum (25+ value)
  - `EdgeType` enum (35+ value across 8 category)
  - `NODE_TYPE_ALIASES` dict (40+ mapping)
  - `EDGE_TYPE_ALIASES` dict (40+ mapping)
  - `COMPLEXITY_ALIASES` dict
  - `DIRECTION_ALIASES` dict
  - `sanitize_graph(data)` function — null → empty array, null → undefined, lowercase enum
  - `auto_fix_graph(data)` function — auto-correct missing field dengan default + issue list
  - `validate_graph(data)` function — check referential integrity (every edge source/target must reference existing node)
- [ ] Update `registry.py` untuk use new schema
- [ ] Update `dataflow_engine.py` untuk emit `reads_from`/`writes_to`/`transforms`/`validates` edge
- [ ] Update `apimap_engine.py` untuk emit `routes`/`serves` edge
- [ ] Update `entrypoints_engine.py` untuk emit `triggers` edge
- [ ] Update `impact_engine.py` untuk respect new edge type (1-hop traversal dengan filter)
- [ ] Output `knowledge-graph.json` dengan schema:
  ```json
  {
    "project": {"name", "description", "languages", "frameworks", "analyzedAt", "gitCommitHash"},
    "nodes": [{"id", "type", "name", "filePath", "summary", "tags", "complexity", "languageNotes"}],
    "edges": [{"source", "target", "type", "direction", "weight", "description"}],
    "layers": [{"id", "name", "description", "nodeIds"}],
    "tour": [{"order", "title", "description", "nodeIds", "languageLesson"}]
  }
  ```
- [ ] Dokumentasi: `references/knowledge-graph-schema.md` dengan semua type + alias + example

**Scope teknis:**
- Buat `scripts/knowledge_graph_schema.py` (port dari UA `schema.ts` + `types.ts`)
- Update semua engine yang emit edge untuk use new EdgeType enum
- Update `formatters/json.py` (atau buat `formatters/knowledge_graph.py`) untuk output new schema
- Test: fixture dengan various LLM output variation, verify autoFixGraph handle semua

**Estimasi effort:** 2-3 minggu

---

#### Issue U2 — Architectural Layer Detection Otomatis

**Motivasi (Understand-Anything):** UA `packages/core/src/analyzer/layer-detector.ts` punya 9 layer dengan directory pattern heuristic (API, Service, Data, UI, Middleware, External, Background, Utility, Test). First-match-wins, LLM dapat override.

CodeLens `entrypoints` dan `api-map` ada tapi tidak group per layer. User tidak bisa lihat "API Layer ada file apa saja" atau "Service Layer complexity hotspot di mana".

**Acceptance Criteria:**
- [ ] Buat `scripts/layer_detector.py` dengan 9 layer pattern:
  - API Layer: `routes`, `controller`, `handler`, `endpoint`, `api`
  - Service Layer: `service`, `usecase`, `use-case`, `business`
  - Data Layer: `model`, `entity`, `schema`, `database`, `db`, `migration`, `repository`, `repo`
  - UI Layer: `component`, `view`, `page`, `screen`, `layout`, `widget`, `ui`
  - Middleware Layer: `middleware`, `interceptor`, `guard`, `filter`, `pipe`
  - External Services: `client`, `integration`, `external`, `sdk`, `vendor`, `adapter`
  - Background Tasks: `worker`, `job`, `queue`, `cron`, `consumer`, `processor`, `scheduler`, `background`
  - Utility Layer: `util`, `helper`, `lib`, `common`, `shared`
  - Test Layer: `test`, `spec`, `__test__`, `__spec__`, `__tests__`, `__specs__`
- [ ] Detection: first-match-wins (order matters), check directory path component
- [ ] Command baru: `codelens layers [workspace]`
  - Output: list layer dengan node count, complexity hotspot, key file
  - Format: `--format ai` → `{stats, items[], truncated, recommendations}`
- [ ] Update `summary` command untuk include layer breakdown
- [ ] Update `impact` command untuk show affected layer
- [ ] Update `knowledge-graph.json` output (Issue U1) untuk include `layers[]` field
- [ ] Visualization: layer legend di dashboard (Issue U5)

**Scope teknis:**
- Buat `scripts/layer_detector.py` (port dari UA `layer-detector.ts`)
- Tambah `scripts/commands/layers.py`
- Update `summary_engine.py` dan `impact_engine.py` untuk respect layer

**Estimasi effort:** 1 minggu

---

### Tema U-B: Interactive Dashboard

---

#### Issue U3 — `dashboard` Command dengan Web UI

**Motivasi (Understand-Anything):** UA punya interactive web dashboard (`packages/dashboard/`):
- React + React Flow + Zustand + TailwindCSS v4
- Graph visualization dengan pan/zoom/minimap
- Node info panel (klik node → lihat detail)
- File explorer tree
- Search (fuzzy + semantic)
- Filter panel (by layer/type/complexity)
- Layer legend
- Path finder (find path antara 2 node)
- Export menu (PNG/SVG/JSON)
- Persona selector (junior dev / PM / power user)
- Theme picker
- Code viewer (prism-react-renderer)
- Mobile responsive

CodeLens tidak punya UI sama sekali — semua output text/JSON. User harus visualize graph manual atau pakai tool eksternal.

**Acceptance Criteria:**
- [ ] Command baru: `codelens dashboard [workspace] [--port 8080] [--no-browser]`
- [ ] Spin up local web server (Flask atau FastAPI)
- [ ] Auto-open browser ke `http://localhost:8080`
- [ ] Dashboard tech stack:
  - Backend: Flask/FastAPI serve static + REST API untuk graph data
  - Frontend: React (atau Vue/Svelte) + React Flow + TailwindCSS
  - State: Zustand atau Redux Toolkit
  - Build: Vite (frontend) + Python (backend)
- [ ] Layout: graph-first (75% graph + 360px right sidebar)
- [ ] Dark theme default (deep black `#0a0a0a` + gold accent `#d4a574`) + light theme toggle
- [ ] Component minimum:
  - `GraphView` — main graph canvas dengan pan/zoom/minimap
  - `NodeInfo` — node detail panel (klik node → lihat summary, tags, complexity, edge)
  - `FileExplorer` — file tree dari structural graph
  - `SearchBar` — fuzzy + semantic search (Issue U9)
  - `FilterPanel` — filter by layer/type/complexity
  - `LayerLegend` — color-coded layer indicator (Issue U2)
  - `CodeViewer` — code display dengan syntax highlighting (Pygments atau prism)
  - `ExportMenu` — export graph as PNG/SVG/JSON
- [ ] REST API endpoint:
  - `GET /api/graph` — return full knowledge-graph.json
  - `GET /api/node/<id>` — return node detail + 1-hop edge
  - `GET /api/file?path=<path>` — return file content
  - `GET /api/search?q=<query>` — return search result
  - `GET /api/layers` — return layer breakdown
- [ ] Auto-update: jika `codelens scan --incremental` run, dashboard auto-refresh via WebSocket atau polling
- [ ] Mobile responsive (graph + bottom nav)
- [ ] Dokumentasi: `references/dashboard.md` dengan screenshot + usage guide

**Scope teknis:**
- Buat `scripts/dashboard/` directory:
  - `backend.py` — Flask/FastAPI server
  - `frontend/` — React app (Vite + TypeScript)
- Tambah `scripts/commands/dashboard.py`
- Tambah dependency: `flask` atau `fastapi` + `uvicorn`
- Build frontend ke `scripts/dashboard/static/` (committed atau built on-install)
- Update `mcp_server.py` untuk expose `open_dashboard` tool

**Estimasi effort:** 4-6 minggu (high complexity, full-stack)

---

#### Issue U4 — Diff Impact Visual Overlay

**Motivasi (Understand-Anything):** UA `/understand-diff` write `diff-overlay.json`:
```json
{
  "version": "1.0.0",
  "baseBranch": "main",
  "generatedAt": "2026-06-28T10:30:45Z",
  "changedFiles": ["src/auth/login.ts"],
  "changedNodeIds": ["file:src/auth/login.ts", "function:src/auth/login.ts:verifyToken"],
  "affectedNodeIds": ["file:src/middleware/auth.ts", "file:src/routes/user.ts"]
}
```

Dashboard visualize changed node (red highlight) + affected node (yellow highlight) di graph.

CodeLens `diff` dan `impact` command ada tapi output text/JSON only — tidak visual.

**Acceptance Criteria:**
- [ ] Update `diff` command untuk write `diff-overlay.json` ke `.codelens/diff-overlay.json`:
  ```json
  {
    "version": "1.0.0",
    "baseBranch": "main",
    "generatedAt": "<ISO timestamp>",
    "changedFiles": ["..."],
    "changedNodeIds": ["..."],
    "affectedNodeIds": ["..."]
  }
  ```
- [ ] Update `impact` command untuk same output format
- [ ] Dashboard (Issue U3) read `diff-overlay.json` dan visualize:
  - Changed node: red border + red glow
  - Affected node: yellow border + yellow glow
  - Unchanged node: default style
- [ ] Toggle button: "Show diff overlay" on/off
- [ ] Risk assessment panel: complexity of changed node, blast radius (affected count), cross-layer edge count
- [ ] Command: `codelens diff --visual` → auto-open dashboard dengan diff overlay active

**Scope teknis:**
- Update `scripts/commands/diff.py` dan `scripts/commands/impact.py`
- Update dashboard frontend untuk read + render diff overlay
- Tambah toggle di dashboard UI

**Estimasi effort:** 1 minggu (setelah Issue U3 selesai)

---

### Tema U-C: Multi-Agent Pipeline & Orchestration

---

#### Issue U5 — Multi-Agent Pipeline untuk Deep Analysis

**Motivasi (Understand-Anything):** UA `/understand` orchestrate 5-6 specialized agent:
1. `project-scanner` — discover file, detect language/framework, pre-resolve import map
2. `file-analyzer` — extract structure (tree-sitter) + semantic (LLM summary/tag/complexity)
3. `architecture-analyzer` — identify layer
4. `tour-builder` — generate guided tour
5. `graph-reviewer` — validate graph (inline deterministic by default, `--review` untuk full LLM)
6. `domain-analyzer` (opsional) — extract business domain

Agent tulis intermediate result ke disk (bukan context) — avoid context pollution. Run parallel (up to 5 concurrent batch).

CodeLens tidak punya multi-agent pipeline — semua command run single-pass. Untuk analysis mendalam yang butuh LLM (summary, tag, layer assignment), CodeLens harus dispatch manual.

**Acceptance Criteria:**
- [ ] Command baru: `codelens analyze-deep [workspace] [--full] [--review]`
- [ ] Pipeline 5 phase (sequential via artifact):
  1. **Scan phase** — reuse existing `scan` command, output `scan-result.json` + `importMap`
  2. **Analyze phase** — dispatch `file-analyzer` subagent per batch (5-10 file per batch, up to 5 concurrent), output `analysis-batch-{N}.json`
  3. **Layer phase** — dispatch `architecture-analyzer` subagent, output `layer-assignment.json`
  4. **Tour phase** — dispatch `tour-builder` subagent, output `tour.json`
  5. **Review phase** — inline deterministic validation by default (free); `--review` flag untuk full LLM review
- [ ] Intermediate file di `.codelens/intermediate/` (cleanup setelah assembly)
- [ ] Final output: `.codelens/knowledge-graph.json` (Issue U1 schema)
- [ ] State tracking: `.codelens/tracking/state.yaml`:
  ```yaml
  phases:
    scan: done
    analyze: in_progress
    layer: pending
    tour: pending
    review: pending
  ```
- [ ] Resumption: skip phase yang artifact-nya sudah exist
- [ ] Resource limit: global cap 5 subagent concurrent
- [ ] Token budget: pre-resolve import di scan phase (C1 dari UA token reduction), inject hanya relevant addendum (C3)
- [ ] Integrasi dengan OpenTaint Issue C1 (multi-skill orchestrator) — sama pattern, bisa share infrastructure

**Scope teknis:**
- Buat `scripts/agents/` directory dengan agent definition (markdown prompt):
  - `file_analyzer.md` — extract structure + semantic
  - `architecture_analyzer.md` — identify layer
  - `tour_builder.md` — generate tour
  - `graph_reviewer.md` — validate graph
- Buat `scripts/orchestrator.py` untuk dispatch + state tracking
- Tambah `scripts/commands/analyze_deep.py`
- Reuse `ast_taint_engine.py` + `crossfile_taint_engine.py` untuk structural extraction

**Estimasi effort:** 3-4 minggu

---

#### Issue U6 — Guided Tour Generation

**Motivasi (Understand-Anything):** UA `tour-generator.ts` generate guided tour:
- Ordered by dependency flow (entry point → high-level → supporting utility)
- Setiap step: `{order, title, description, nodeIds, languageLesson?}`
- `languageLesson` — note about language-specific pattern (generics, closures, decorator, dll.)

CodeLens `handbook` command ada tapi output static document — tidak terstruktur sebagai tour dengan order + node reference.

**Acceptance Criteria:**
- [ ] Command baru: `codelens tour [workspace] [--format json|markdown]`
- [ ] Tour generation strategy:
  1. Identify entry point (reuse `entrypoints` command)
  2. Follow dependency flow (call graph traversal)
  3. Group related file together
  4. End with supporting utility
- [ ] Output `tour.json`:
  ```json
  {
    "steps": [
      {
        "order": 1,
        "title": "Entry Point: main.py",
        "description": "The application starts here. This file bootstrap the Flask server and wire up all route handler.",
        "nodeIds": ["file:src/main.py", "function:src/main.py:start_server"],
        "languageLesson": "Notice the use of @app.route decorator — this is a Flask pattern for registering URL handler."
      }
    ]
  }
  ```
- [ ] Output `tour.md` (markdown format):
  ```markdown
  # Codebase Tour: MyProject
  
  ## Step 1: Entry Point — main.py
  The application starts here...
  
  **Language Lesson:** Notice the use of @app.route decorator...
  
  ## Step 2: Route Handler — routes/user.py
  ...
  ```
- [ ] Include di `knowledge-graph.json` (Issue U1) sebagai `tour[]` field
- [ ] Dashboard (Issue U3) render tour sebagai clickable step list — klik step → highlight node di graph + show description
- [ ] `languageLesson` auto-detect 12 pattern: Generics, Closures, Decorators, Async/Await, Interfaces, Inheritance, Higher-Order Functions, Pattern Matching, Traits/Mixins, Error Handling, Type Inference, Macros

**Scope teknis:**
- Buat `scripts/tour_generator.py` (port dari UA `tour-generator.ts`)
- Buat `scripts/language_lesson.py` — detect 12 pattern per bahasa
- Tambah `scripts/commands/tour.py`
- Update `knowledge-graph.json` schema untuk include `tour[]`
- Update dashboard untuk render tour

**Estimasi effort:** 2 minggu

---

### Tema U-D: Domain & Knowledge Base

---

#### Issue U7 — Business Domain Graph Extraction

**Motivasi (Understand-Anything):** UA `/understand-domain` extract business domain knowledge:
- **Domain** — high-level business area (Authentication, Payment, Order Management)
- **Flow** — business process within domain (User Login Flow, Checkout Flow)
- **Step** — individual step dalam flow (Validate Credentials, Generate Token, Set Session)

Two path: (1) derive from existing knowledge graph (cheap), (2) lightweight scan (fallback). Output `domain-graph.json` dengan horizontal flow visualization.

CodeLens tidak punya ini — tidak ada cara untuk map code ke business process.

**Acceptance Criteria:**
- [ ] Command baru: `codelens domain [workspace] [--full]`
- [ ] Two path:
  1. **Derive from existing graph** — jika `knowledge-graph.json` exist, LLM analyze graph untuk extract domain/flow/step
  2. **Lightweight scan** — jika tidak exist, file tree + entry point detection + sampled file → LLM extract domain
- [ ] `--full` flag — force fresh scan even if graph exist
- [ ] Domain extraction via LLM prompt:
  - Identify business domain dari node name + summary + tag
  - Group flow within domain
  - Order step within flow
- [ ] Output `.codelens/domain-graph.json`:
  ```json
  {
    "domains": [
      {
        "id": "domain:authentication",
        "name": "Authentication",
        "summary": "User authentication and session management",
        "flows": [
          {
            "id": "flow:login",
            "name": "User Login Flow",
            "summary": "Standard username/password login",
            "steps": [
              {"id": "step:validate-credentials", "name": "Validate Credentials", "nodeIds": ["function:src/auth/login.py:verify_password"]},
              {"id": "step:generate-token", "name": "Generate Token", "nodeIds": ["function:src/auth/token.py:create_jwt"]},
              {"id": "step:set-session", "name": "Set Session", "nodeIds": ["function:src/auth/session.py:set_session"]}
            ]
          }
        ]
      }
    ]
  }
  ```
- [ ] Edge type: `contains_flow` (domain → flow), `flow_step` (flow → step), `cross_domain` (cross-domain interaction)
- [ ] Dashboard (Issue U3) render domain graph sebagai horizontal flow (left-to-right: domain → flow → step)
- [ ] Integrasi dengan `entrypoints` dan `api-map` command untuk identify business entry point

**Scope teknis:**
- Buat `scripts/domain_extractor.py`
- Tambah `scripts/commands/domain.py`
- Tambah `domain`/`flow`/`step` ke NodeType enum (Issue U1)
- Tambah `contains_flow`/`flow_step`/`cross_domain` ke EdgeType enum (Issue U1)
- Update dashboard untuk render domain view

**Estimasi effort:** 2-3 minggu

---

#### Issue U8 — Knowledge Base Analysis (Karpathy-pattern Wiki)

**Motivasi (Understand-Anything):** UA `/understand-knowledge` analyze Karpathy-pattern LLM wiki:
- **Raw sources** — immutable source document di `raw/`
- **Wiki** — LLM-generated markdown dengan wikilink (`[[target]]`)
- **Schema** — `CLAUDE.md`, `AGENTS.md`, atau similar
- **index.md** — content catalog by category
- **log.md** — chronological operation log

Pipeline: DETECT (format detection) → SCAN (deterministic: article/source/topic node + wikilink/category edge) → ANALYZE (LLM: entity/claim/source node + cites/contradicts/builds_on edge) → MERGE (deduplicate + normalize + build layer/tour) → SAVE (validate + meta.json)

CodeLens tidak punya ini — tidak ada way untuk analyze knowledge base markdown.

**Acceptance Criteria:**
- [ ] Command baru: `codelens knowledge [wiki-directory]`
- [ ] Detection: check for `index.md` + multiple `.md` file dengan `[[wikilink]]` syntax
- [ ] Phase 1 — DETECT: parse-knowledge-base script, output `scan-manifest.json`
- [ ] Phase 2 — SCAN (sudah di Phase 1): deterministic extraction:
  - Article node (1 per wiki .md file) dengan wikilink, heading, frontmatter
  - Source node (1 per `raw/` file)
  - Topic node (dari index.md section heading)
  - `related` edge (dari wikilink)
  - `categorized_under` edge (dari index.md section)
- [ ] Phase 3 — ANALYZE: dispatch `article-analyzer` subagent per batch (10-15 article, up to 3 concurrent), extract:
  - Entity node (person, organization, concept)
  - Claim node (assertion, decision, thesis)
  - Source node (reference, paper)
  - `cites` edge, `contradicts` edge, `builds_on` edge, `exemplifies` edge, `authored_by` edge
- [ ] Phase 4 — MERGE: combine scan-manifest + analysis-batch, deduplicate entity (case-insensitive), normalize via alias map, build layer dari index.md category, build tour dari index.md section ordering
- [ ] Phase 5 — SAVE: validate (every edge source/target must reference existing node), save `knowledge-graph.json` + `meta.json`, cleanup intermediate
- [ ] Output graph dengan `kind: "knowledge"` → dashboard use force-directed layout (bukan hierarchical dagre)
- [ ] Tambah `article`/`entity`/`topic`/`claim`/`source` ke NodeType enum (Issue U1)
- [ ] Tambah `cites`/`contradicts`/`builds_on`/`exemplifies`/`categorized_under`/`authored_by` ke EdgeType enum (Issue U1)

**Scope teknis:**
- Buat `scripts/knowledge_base_parser.py` (port dari UA `parse-knowledge-base.py`)
- Buat `scripts/knowledge_graph_merger.py` (port dari UA `merge-knowledge-graph.py`)
- Buat `scripts/agents/article_analyzer.md` — agent prompt untuk extract entity/claim
- Tambah `scripts/commands/knowledge.py`
- Update dashboard untuk render force-directed knowledge graph

**Estimasi effort:** 3-4 minggu

---

### Tema U-E: Robustness & Quality

---

#### Issue U9 — Schema Validation & Auto-Fix untuk LLM Output

**Motivasi (Understand-Anything):** UA `schema.ts` punya:
- `sanitizeGraph(data)` — null → empty array, null → undefined, lowercase enum
- `autoFixGraph(data)` — auto-correct missing field dengan default value + issue list:
  - Missing `type` → default `file` (auto-corrected warning)
  - Missing `complexity` → default `moderate`
  - Missing `tags` → default `[]`
  - Missing `summary` → default ke `name`
  - Missing `direction` → default `forward`
  - Missing `weight` → default `0.5`
  - String `weight` → coerce ke number
  - Alias normalization untuk semua field (NODE_TYPE_ALIASES, EDGE_TYPE_ALIASES, COMPLEXITY_ALIASES, DIRECTION_ALIASES)

CodeLens tidak punya ini — LLM output (jika ada) langsung dipakai tanpa validation. Jika LLM return `func` alih-alih `function`, atau `low` alih-alih `simple`, akan break.

**Acceptance Criteria:**
- [ ] Implementasi di `scripts/knowledge_graph_schema.py` (Issue U1):
  - `sanitize_graph(data)` — null handling, lowercase enum
  - `auto_fix_graph(data)` — auto-correct + issue list
  - `validate_graph(data)` — referential integrity check
- [ ] Issue level: `auto-corrected` (warning), `error` (must fix), `fatal` (cannot proceed)
- [ ] Issue category: `missing-field`, `alias`, `type-coercion`, `dangling-reference`, `invalid-enum`
- [ ] Issue format:
  ```json
  {
    "level": "auto-corrected",
    "category": "missing-field",
    "message": "nodes[0] (\"main.py\"): missing \"type\" — defaulted to \"file\"",
    "path": "nodes[0].type"
  }
  ```
- [ ] Validation report di output:
  ```json
  {
    "status": "ok",
    "stats": {"nodes": 150, "edges": 320, "layers": 5, "tour_steps": 12},
    "issues": [{"level": "auto-corrected", "category": "alias", "message": "...", "path": "..."}],
    "recommendations": ["Review 3 auto-corrected alias in nodes[5], nodes[12], edges[8]"]
  }
  ```
- [ ] Test: fixture dengan various LLM output variation (alias, missing field, wrong type, dangling reference)

**Scope teknis:**
- Implementasi di `scripts/knowledge_graph_schema.py` (Issue U1)
- Test fixture di `tests/fixtures/llm-output-variation/`
- Update semua command yang consume LLM output untuk run validation

**Estimasi effort:** 1 minggu (setelah Issue U1)

---

#### Issue U10 — Staleness Detection & Auto-Update Hook

**Motivasi (Understand-Anything):** UA punya:
- `staleness.ts` — compare `gitCommitHash` di `meta.json` vs current `git rev-parse HEAD`, compare file fingerprint vs current content hash, flag node sebagai `stale`
- `--auto-update` flag — write `autoUpdate: true` ke config, post-commit hook trigger incremental graph patch
- `hooks/auto-update-prompt.md` — prompt untuk post-commit hook
- Worktree redirect — jika di git worktree, redirect output ke main repo root

CodeLens `scan --incremental` ada tapi tidak track staleness per node, tidak punya auto-update hook.

**Acceptance Criteria:**
- [ ] Tambah `staleness` field ke node di `knowledge-graph.json`:
  ```json
  {
    "id": "file:src/main.py",
    "stale": false,
    "lastAnalyzedAt": "2026-06-28T10:30:45Z",
    "fingerprint": "sha256:abc123..."
  }
  ```
- [ ] Tambah `meta.json` di `.codelens/`:
  ```json
  {
    "lastAnalyzedAt": "2026-06-28T10:30:45Z",
    "gitCommitHash": "abc1234",
    "version": "1.0.0",
    "analyzedFiles": 150
  }
  ```
- [ ] Command baru: `codelens staleness [workspace]` — list stale node
- [ ] Flag `--auto-update` untuk `scan` command — write `autoUpdate: true` ke `.codelens/config.json`
- [ ] Post-commit hook script: `scripts/hooks/post-commit.sh`:
  ```bash
  #!/bin/bash
  if [ -f .codelens/config.json ] && jq -e '.autoUpdate == true' .codelens/config.json > /dev/null 2>&1; then
    python3 /path/to/codelens/scripts/codelens.py scan --incremental --quiet
  fi
  ```
- [ ] Install hook: `codelens install-hook` command
- [ ] Worktree redirect: detect git worktree, redirect output ke main repo root (override dengan `CODELENS_NO_WORKTREE_REDIRECT=1`)
- [ ] Dashboard (Issue U3) show staleness indicator (yellow border untuk stale node)

**Scope teknis:**
- Buat `scripts/staleness_tracker.py` (port dari UA `staleness.ts`)
- Buat `scripts/commands/staleness.py`
- Buat `scripts/hooks/post-commit.sh`
- Buat `scripts/commands/install_hook.py`
- Update `scan` command untuk respect `autoUpdate` config

**Estimasi effort:** 1-2 minggu

---

### Tema U-F: Search & UX

---

#### Issue U11 — Embedding-Based Semantic Search

**Motivasi (Understand-Anything):** UA `embedding-search.ts` punya semantic search:
- "which parts handle auth?" → return relevant node across graph
- Embedding-based (bukan hanya fuzzy string match)
- Complement dengan fuzzy search (name-based)

CodeLens `search` command hanya regex, `symbols` command hanya fuzzy name match. Tidak ada semantic search — user tidak bisa cari by meaning.

**Acceptance Criteria:**
- [ ] Command baru: `codelens semantic-search "<query>" [workspace] [--top N]`
- [ ] Embedding model: gunakan `sentence-transformers` Python library (model: `all-MiniLM-L6-v2` — fast, lightweight, 384-dim)
- [ ] Index: pre-compute embedding untuk setiap node `name + summary + tags` di `scan` phase, store di `.codelens/embeddings.npy`
- [ ] Query: embed query → cosine similarity vs all node embedding → return top N
- [ ] Output format:
  ```json
  {
    "status": "ok",
    "query": "which parts handle auth?",
    "results": [
      {"nodeId": "function:src/auth/login.py:verify_password", "name": "verify_password", "summary": "...", "score": 0.87},
      {"nodeId": "file:src/middleware/auth.py", "name": "auth.py", "summary": "...", "score": 0.82}
    ]
  }
  ```
- [ ] Integrasi dengan `search` command: tambah flag `--semantic` untuk enable semantic search
- [ ] Integrasi dengan `ask` command: use semantic search untuk find relevant node sebelum LLM answer
- [ ] MCP tool: `semantic_search` exposed via MCP server
- [ ] Dashboard (Issue U3) SearchBar support semantic search

**Scope teknis:**
- Tambah dependency: `sentence-transformers`, `numpy`
- Buat `scripts/embedding_search.py` (port dari UA `embedding-search.ts`)
- Tambah `scripts/commands/semantic_search.py`
- Update `scan` command untuk pre-compute embedding
- Update `search` dan `ask` command untuk support `--semantic` flag

**Estimasi effort:** 1-2 minggu

---

#### Issue U12 — Persona-Adaptive Output

**Motivasi (Understand-Anything):** UA dashboard punya PersonaSelector:
- Junior dev — verbose explanation, more context, simpler language
- PM — high-level summary, business impact, less technical detail
- Power user — concise, technical, assume prior knowledge

CodeLens output satu style untuk semua user. Tidak adapt ke audience.

**Acceptance Criteria:**
- [ ] Flag `--persona <junior-dev|pm|power-user>` untuk command `summary`, `handbook`, `tour`, `explain`
- [ ] Junior dev persona:
  - Verbose explanation (3-5 sentence per section)
  - More context (background, why it matter)
  - Simpler language (avoid jargon, explain technical term)
  - Include languageLesson
- [ ] PM persona:
  - High-level summary (1-2 sentence per section)
  - Business impact focus
  - Less technical detail (skip implementation, focus on what + why)
  - Include domain mapping (Issue U7)
- [ ] Power user persona:
  - Concise (1 sentence per section)
  - Technical (assume prior knowledge)
  - Include complexity score, edge count, blast radius
- [ ] Config: `.codelens/config.json` field `persona` untuk default
- [ ] MCP tool: expose `persona` parameter

**Scope teknis:**
- Tambah `--persona` flag ke relevant command
- Update `summary_engine.py`, `handbook` command, `tour_generator.py` (Issue U6) untuk respect persona
- Persona-specific prompt template di `scripts/prompts/`

**Estimasi effort:** 1 minggu

---

### Tema U-G: Distribution & DX

---

#### Issue U13 — Multi-Platform Plugin Distribution (Claude Code, Cursor, Copilot, dll.)

**Motivasi (Understand-Anything):** UA support 17 AI platform:
- Claude Code (native plugin marketplace)
- Cursor (auto-discovery via `.cursor-plugin/plugin.json`)
- VS Code + GitHub Copilot (auto-discovery via `.copilot-plugin/plugin.json`)
- Codex, OpenCode, Gemini CLI, dll. (via `install.sh <platform>`)

CodeLens hanya CLI Python — tidak ter-integrate dengan AI coding platform.

**Acceptance Criteria:**
- [ ] Buat `.claude-plugin/plugin.json` untuk Claude Code marketplace:
  ```json
  {
    "name": "codelens",
    "version": "8.2.0",
    "description": "AI-native code intelligence with 58 command + MCP server + interactive dashboard",
    "skills": ["skills/"]
  }
  ```
- [ ] Buat `.cursor-plugin/plugin.json` untuk Cursor auto-discovery
- [ ] Buat `.copilot-plugin/plugin.json` untuk VS Code Copilot auto-discovery
- [ ] Buat `install.sh` (macOS/Linux) + `install.ps1` (Windows):
  - Clone repo ke `~/.codelens/repo`
  - Create symlink per platform
  - Support: `claude`, `cursor`, `vscode`, `codex`, `opencode`, `gemini`, `copilot-cli`
- [ ] Buat skill definition di `skills/` untuk AI platform:
  - `skills/codelens-analyze/SKILL.md` — analyze codebase
  - `skills/codelens-query/SKILL.md` — pre-write check
  - `skills/codelens-dashboard/SKILL.md` — open dashboard
  - `skills/codelens-tour/SKILL.md` — guided tour
- [ ] Publish ke Claude Code marketplace: `/plugin marketplace add Wolfvin/CodeLens`
- [ ] Dokumentasi: `references/multi-platform-install.md`

**Scope teknis:**
- Buat `.claude-plugin/`, `.cursor-plugin/`, `.copilot-plugin/` directory
- Buat `install.sh` + `install.ps1` (port dari UA installer)
- Buat skill definition markdown
- Setup marketplace listing

**Estimasi effort:** 2 minggu

---

#### Issue U14 — Graph Sharing via Git + Git LFS Support

**Motivasi (Understand-Anything):** UA recommend commit `.understand-anything/` (kecuali `intermediate/` dan `diff-overlay.json`) ke git untuk share dengan team. Large graph (10 MB+) track dengan git-lfs.

CodeLens `.codelens/` saat ini di-gitignore (line 16: `.codelens/`). Tidak ada way untuk share registry dengan team.

**Acceptance Criteria:**
- [ ] Update `.gitignore` untuk allow commit `.codelens/knowledge-graph.json` + `.codelens/meta.json` + `.codelens/config.json`:
  ```gitignore
  # CodeLens Registry Cache (auto-generated, NOT committed)
  .codelens/intermediate/
  .codelens/embeddings.npy
  .codelens/diff-overlay.json
  .codelens/token_cache.json
  
  # CodeLens Knowledge Graph (commit untuk share dengan team)
  # .codelens/knowledge-graph.json
  # .codelens/meta.json
  # .codelens/config.json
  ```
- [ ] Dokumentasi: "What to commit" vs "What to gitignore"
- [ ] Git LFS support untuk large graph:
  ```bash
  git lfs install
  git lfs track ".codelens/knowledge-graph.json"
  git lfs track ".codelens/embeddings.npy"
  git add .gitattributes .codelens/
  ```
- [ ] Tambah `.gitattributes` template:
  ```
  .codelens/knowledge-graph.json filter=lfs diff=lfs merge=lfs -text
  .codelens/embeddings.npy filter=lfs diff=lfs merge=lfs -text
  ```
- [ ] Command: `codelens init --shareable` — setup git-lfs + .gitattributes + commit template
- [ ] Dokumentasi: `references/graph-sharing.md` dengan workflow

**Scope teknis:**
- Update `.gitignore`
- Buat `references/graph-sharing.md`
- Tambah `--shareable` flag ke `init` command

**Estimasi effort:** 3-5 hari

---

### Tema U-H: Documentation & Process

---

#### Issue U15 — Design Doc + Implementation Plan per Fitur

**Motivasi (Understand-Anything):** UA punya 14 design doc + 20 implementation plan di `docs/superpowers/`:
- Setiap fitur punya `design.md` (spec: problem, goal, changes, trade-off) + `impl.md` (step-by-step plan)
- Pattern: spec dulu, plan kedua, implementasi ketiga
- Rigorous engineering process

CodeLens hanya punya `CHANGELOG.md` (76 KB, retrospective) + 5 reference file. Tidak ada forward-looking design doc.

**Acceptance Criteria:**
- [ ] Buat `docs/design/` directory untuk design doc
- [ ] Buat `docs/plans/` directory untuk implementation plan
- [ ] Template:
  - `docs/design/template.md`:
    ```markdown
    # [Feature Name] Design
    
    **Date:** YYYY-MM-DD
    **Status:** Draft | Reviewed | Approved | Implemented
    **Goal:** [one sentence]
    
    ## Problem
    [Why this feature is needed]
    
    ## Goals
    - [Goal 1]
    - [Goal 2]
    
    ## Changes
    [Detailed design — C1, C2, C3...]
    
    ## Trade-offs
    [What we considered and rejected, and why]
    
    ## Open Questions
    - [Question 1]
    ```
  - `docs/plans/template.md`:
    ```markdown
    # [Feature Name] Implementation Plan
    
    **Date:** YYYY-MM-DD
    **Design:** [link to design doc]
    
    ## Phase 1: [Name]
    - [ ] Step 1
    - [ ] Step 2
    
    ## Phase 2: [Name]
    - [ ] Step 1
    ```
- [ ] Backfill design doc untuk existing feature (jika feasible): taint engine, MCP server, plugin system, dll.
- [ ] Going forward: setiap new fitur (dari issue tracker) harus punya design doc + impl plan sebelum coding
- [ ] CI check: PR yang add new fitur harus include design doc + impl plan

**Scope teknis:**
- Buat `docs/design/` + `docs/plans/` directory
- Buat template
- Backfill untuk key existing feature (optional, low priority)

**Estimasi effort:** ongoing (1-2 hari per fitur baru)

---

#### Issue U16 — Homepage + Live Demo

**Motivasi (Understand-Anything):** UA punya `homepage/` (Astro + TypeScript) dengan:
- Hero section dengan tagline
- Features section
- Showcase (screenshot + GIF)
- Install instruction
- Live demo (interactive dashboard di browser)

CodeLens tidak punya homepage — hanya GitHub README.

**Acceptance Criteria:**
- [ ] Buat `homepage/` directory dengan static site generator (Astro, Next.js, atau VitePress)
- [ ] Domain: `codelens.dev` (atau `wolfvin.github.io/CodeLens`)
- [ ] Section:
  - Hero: tagline + CTA button (Quick Start, Live Demo)
  - Features: 58 command, MCP server, dashboard, taint analysis, dll.
  - Showcase: screenshot + GIF dari dashboard (Issue U3) + CLI output
  - Install: multi-platform instruction (Issue U13)
  - Live Demo: interactive dashboard dengan sample project (e.g., analyze `Wolfvin/CodeLens` itself)
  - Documentation link
  - Community (Discord, GitHub Discussions)
- [ ] SEO: meta tag, Open Graph, sitemap
- [ ] Analytics: privacy-friendly (Plausible atau self-hosted)
- [ ] Deploy: GitHub Pages atau Cloudflare Pages

**Scope teknis:**
- Pilih static site generator (rekomendasi: VitePress — Vue-based, code-focused, built-in search)
- Buat homepage dengan content dari README + screenshot
- Setup CI untuk auto-deploy on push to main
- Build live demo dengan sample project

**Estimasi effort:** 2-3 minggu (mostly content + design)

---

## 6. Prioritas & Roadmap Eksekusi

Roadmap diurutkan berdasarkan **impact** dan **dependency**:

### Fase U-1 — Knowledge Graph Foundation (Q3 2026, ~4-5 minggu)

| Issue | Effort | Dependency | Impact |
|---|---|---|---|
| **U1** Rich knowledge graph schema | 2-3 minggu | — | **kritis** (foundation untuk semua) |
| **U9** Schema validation & auto-fix | 1 minggu | U1 | tinggi |
| **U2** Architectural layer detection | 1 minggu | U1 | tinggi |

### Fase U-2 — Visualization (Q4 2026, ~5-7 minggu)

| Issue | Effort | Dependency | Impact |
|---|---|---|---|
| **U3** Dashboard command dengan web UI | 4-6 minggu | U1 | **kritis** (game-changer) |
| **U4** Diff impact visual overlay | 1 minggu | U3 | sedang |

### Fase U-3 — Multi-Agent & Tour (Q4 2026, ~5-6 minggu)

| Issue | Effort | Dependency | Impact |
|---|---|---|---|
| **U5** Multi-agent pipeline | 3-4 minggu | U1, OpenTaint C1 | tinggi |
| **U6** Guided tour generation | 2 minggu | U1, U5 | sedang |

### Fase U-4 — Domain & Knowledge (Q1 2027, ~5-7 minggu)

| Issue | Effort | Dependency | Impact |
|---|---|---|---|
| **U7** Business domain graph | 2-3 minggu | U1, U5 | tinggi |
| **U8** Knowledge base analysis | 3-4 minggu | U1, U5 | sedang |

### Fase U-5 — Robustness & Search (Q1 2027, ~3-4 minggu)

| Issue | Effort | Dependency | Impact |
|---|---|---|---|
| **U10** Staleness & auto-update hook | 1-2 minggu | U1 | sedang |
| **U11** Embedding semantic search | 1-2 minggu | U1 | tinggi |
| **U12** Persona-adaptive output | 1 minggu | — | kecil |

### Fase U-6 — Distribution & DX (Q2 2027, ~4-5 minggu)

| Issue | Effort | Dependency | Impact |
|---|---|---|---|
| **U13** Multi-platform plugin | 2 minggu | — | tinggi |
| **U14** Graph sharing + git-lfs | 3-5 hari | U1 | sedang |
| **U15** Design doc process | ongoing | — | sedang |
| **U16** Homepage + live demo | 2-3 minggu | U3 | sedang |

### Total Estimasi: ~26-34 minggu (~7-9 bulan)

**Quick win pertama:** Issue U2 (layer detection) — 1 minggu, no dependency, visible improvement ke `summary` command.

**Highest impact:** Issue U3 (dashboard) — ini game-changer yang mengubah CodeLens dari text-only tool jadi visual platform. Setelah U3 selesai, U4-U12 bisa dikerjakan secara bertahap.

**Strategic:** Issue U5 (multi-agent pipeline) — ini align dengan OpenTaint Issue C1 (multi-skill orchestrator). Bisa share infrastructure, dispatch pattern, state tracking.

---

## 7. Catatan Teknis & Risiko

### 7.1 Risiko Teknis

1. **Dashboard tech stack choice** — UA pakai React + React Flow. CodeLens Python-based, perlu pilih: (a) React frontend + Python backend (Flask/FastAPI), (b) Python-native web framework (Streamlit, Dash, Gradio), (c) static HTML + JavaScript.
   - **Mitigasi:** Rekomendasi opsi (a) — React + Flask. React Flow adalah gold standard untuk graph visualization. Python backend reuse existing engine. Build frontend ke static file, serve dari Python.

2. **Multi-agent pipeline token cost** — UA token reduction design doc (85-90% reduction) menunjukkan naive implementation bisa sangat mahat. 500-file project → 529K tokens tanpa optimization.
   - **Mitigasi:** Implementasi 5 change dari UA token reduction design (C1-C5): pre-resolve import, prompt compression, lazy addendum, incremental tour, inline deterministic review.

3. **Embedding search dependency** — `sentence-transformers` menambah ~500MB dependency (PyTorch + model weight). Bukan default install.
   - **Mitigasi:** Jadikan optional dependency (`pip install codelens[semantic]`). Fallback ke fuzzy search jika tidak ter-install.

4. **Schema migration** — Perubahan schema (Issue U1) akan break existing `.codelens/` registry. User harus re-scan.
   - **Mitigasi:** Schema versioning di `meta.json` (`schemaVersion: 2.0`). Auto-detect old schema → migration script atau re-scan warning.

5. **Dashboard security** — Local web server di `localhost:8080` bisa diakses dari network jika tidak di-bind ke `127.0.0.1`.
   - **Mitigasi:** Hardcode bind ke `127.0.0.1` (bukan `0.0.0.0`). Warning jika user pakai `--host 0.0.0.0`.

6. **Multi-platform plugin maintenance** — Support 17 platform (seperti UA) adalah maintenance burden besar. Setiap platform punya plugin format berbeda.
   - **Mitigasi:** Mulai dengan 3 platform utama: Claude Code, Cursor, VS Code Copilot. Tambah platform lain berdasarkan demand.

### 7.2 Risiko Non-Teknis

1. **Scope creep** — 16 issue Understand-Anything-related + 16 OpenTaint + 16 Repomix = 48 issue total. Butuh prioritization yang jelas.
   - **Mitigasi:** Roadmap bertahap. Fokus pada foundation (U1, U2, U9) dulu sebelum visualization (U3). Setiap issue dirilis sebagai minor version.

2. **Positioning blur** — CodeLens sebagai "AI-native code intelligence" + Understand-Anything sebagai "code understanding" bisa blur. User bingung apa bedanya.
   - **Mitigasi:** Differentiate: CodeLens = analysis depth (taint, security, quality, compliance) + visual exploration (new). UA = visual exploration only. CodeLens adalah superset.

3. **Competitive overlap dengan Understand-Anything** — Jika CodeLens `dashboard` terlalu mirip UA, user bisa pilih salah satu.
   - **Mitigasi:** Differentiate: CodeLens dashboard terintegrasi dengan analysis (bisa show taint path, security finding, complexity hotspot di graph — fitur yang UA tidak punya).

### 7.3 Yang TIDAK Perlu Diserap dari Understand-Anything

Beberapa hal UA tidak relevant atau inferior untuk CodeLens:

1. **Astro homepage** — UA pakai Astro. CodeLens bisa pakai VitePress (Vue-based, lebih code-focused) atau Next.js. Skip Astro.

2. **Tree-sitter WASM** — UA pakai `web-tree-sitter` WASM karena native binding fail di darwin/arm64 + Node 24. CodeLens Python-based, native tree-sitter Python binding stabil. Skip WASM.

3. **17 platform support** — Mulai dengan 3 platform utama (Claude Code, Cursor, VS Code Copilot). Tambah platform lain berdasarkan demand, jangan langsung 17.

4. **Knowledge base analysis (Karpathy wiki)** — Issue U8 adalah niche feature. Hanya relevant untuk user yang punya LLM wiki. Prioritas rendah — bisa skip di Fase 1-3, implementasi di Fase 4 jika ada demand.

5. **Persona-adaptive UI** — Issue U12 adalah nice-to-have tapi tidak kritis. Bisa skip di Fase awal.

### 7.4 Konvensi Penamaan yang Diadopsi dari Understand-Anything

Berikut konvensi UA yang worth diadopsi di CodeLens:

- `.codelens/knowledge-graph.json` — knowledge graph output (vs UA `.understand-anything/knowledge-graph.json`)
- `.codelens/domain-graph.json` — domain graph output
- `.codelens/diff-overlay.json` — diff visualization data
- `.codelens/meta.json` — analysis metadata (gitCommitHash, lastAnalyzedAt, version)
- `.codelens/config.json` — config (autoUpdate, persona, language)
- `.codelens/intermediate/` — intermediate file (gitignored)
- `.codelens/embeddings.npy` — embedding index (gitignored, large)
- `.codelens/tracking/state.yaml` — orchestrator state
- Node ID format: `type:path` atau `type:path:name` (e.g., `file:src/main.py`, `function:src/main.py:start_server`)
- Edge direction: `forward` / `backward` / `bidirectional`
- Complexity: `simple` / `moderate` / `complex`
- `--auto-update` flag untuk post-commit hook
- `--full` flag untuk force rebuild
- `--review` flag untuk full LLM review (vs inline deterministic default)
- `--language <lang>` flag untuk localized output

---

## 8. Integrasi dengan Roadmap OpenTaint & Repomix

Dokumen ini adalah **pelengkap** dari analisis OpenTaint dan Repomix sebelumnya. Ketiganya saling melengkapi:

| Aspek | OpenTaint Analysis | Repomix Analysis | Understand-Anything Analysis |
|---|---|---|---|
| **Fokus** | Kedalaman analysis (taint, rule authoring, agent orchestration) | Context delivery (packing, token counting, output format) | Visual exploration (knowledge graph, dashboard, tour) |
| **Issue count** | 16 issue (A1-A4, B1-B3, C1-C3, D1-D4, E1-E2, F1-F2) | 16 issue (R1-R16) | 16 issue (U1-U16) |
| **Total issue** | 48 issue combined | | |
| **Quick win** | D3 (versioning) — 3 hari | R4 (split output) — 3-5 hari | U2 (layer detection) — 1 minggu |
| **Highest impact** | A1 (unified taint), A3 (approximation) | R1 (`pack` command), R2 (token counting) | U1 (schema), U3 (dashboard) |
| **Strategic** | C1 (multi-skill orchestrator) | R8 (Agent Skills generation) | U5 (multi-agent pipeline) |

### 8.1 Cross-Issue Dependency

Beberapa issue saling bergantung antar-tema:

1. **OpenTaint C1 (multi-skill orchestrator)** ↔ **Understand-Anything U5 (multi-agent pipeline)** — sama pattern, bisa share infrastructure
   - Implementasi: buat `scripts/orchestrator.py` generic yang bisa dipakai untuk both security workflow (OpenTaint C1) dan analysis workflow (UA U5)

2. **Repomix R8 (Agent Skills generation)** ↔ **Understand-Anything U13 (multi-platform plugin)** — same goal (distribute ke AI platform), different approach
   - Implementasi: R8 generate skill dari codebase, U13 distribute skill ke platform. Bisa digabung: `codelens pack --skill-generate --platform claude`

3. **Repomix R1 (`pack` command)** ↔ **Understand-Anything U1 (knowledge graph schema)** — pack bisa include knowledge graph
   - Implementasi: `codelens pack --include-graph` untuk embed `knowledge-graph.json` di output

4. **OpenTaint A4 (debug-trace taint)** ↔ **Understand-Anything U3 (dashboard)** — debug trace bisa visualize di dashboard
   - Implementasi: taint path dari debug-trace render sebagai highlighted edge di dashboard graph

5. **Repomix R2 (token counting)** ↔ **Understand-Anything U5 (multi-agent pipeline)** — token counting penting untuk pipeline budget
   - Implementasi: orchestrator (U5) use TokenCounter (R2) untuk track dan limit token per agent

### 8.2 Rekomendasi Eksekusi Paralel

**Q3 2026 (Fase 1 semua tema):**
- OpenTaint Fase 1: D3, F2, D2, A1, F1
- Repomix Fase R-1: R1, R2, R3, R4
- Understand-Anything Fase U-1: U1, U9, U2

**Q4 2026 (Fase 2 semua tema):**
- OpenTaint Fase 2: A3, A4, B1, B2, E1
- Repomix Fase R-2: R5, R6
- Understand-Anything Fase U-2 + U-3: U3, U4, U5, U6

**Q1 2027 (Fase 3 semua tema):**
- OpenTaint Fase 3: C2, C3, C1, A2, B3
- Repomix Fase R-3 + R-4: R7, R8, R9, R10
- Understand-Anything Fase U-4 + U-5: U7, U8, U10, U11, U12

**Q2 2027 (Fase 4 semua tema):**
- OpenTaint Fase 4: D1, D4, E2
- Repomix Fase R-5 + R-6: R11, R12, R13, R14, R15, R16
- Understand-Anything Fase U-6: U13, U14, U15, U16

### 8.3 Total Roadmap

- **Total issue:** 48 (16 OpenTaint + 16 Repomix + 16 Understand-Anything)
- **Total estimasi:** ~55-70 minggu (~14-18 bulan)
- **Rilis target:** v8.2 (Q3 2026) → v8.3 (Q4 2026) → v9.0 (Q1 2027) → v9.1 (Q2 2027) → v10.0 (Q3 2027)

**Versioning:**
- v8.x — OpenTaint Fase 1 + Repomix Fase R-1 + UA Fase U-1
- v9.0 — Dashboard release (UA U3) + multi-agent pipeline (UA U5 + OpenTaint C1)
- v9.x — Domain graph, knowledge base, semantic search
- v10.0 — Multi-platform plugin + homepage + final polish

---

## Penutup

Dokumen ini adalah **analisis komprehensif** Understand-Anything sebagai sumber upgrade untuk CodeLens. Berbeda dengan OpenTaint (analysis depth) dan Repomix (context delivery), Understand-Anything fokus pada **visual exploration** — ketiganya saling melengkapi.

**Rekomendasi eksekusi:**
1. **Mulai dari Fase U-1** (U1 schema + U9 validation + U2 layer detection) — foundation yang membuka 13 issue lainnya.
2. **U3 (dashboard) adalah game-changer** — mengubah CodeLens dari text-only tool jadi visual platform. Prioritaskan resource terbaik.
3. **U5 (multi-agent pipeline) align dengan OpenTaint C1** — share infrastructure, dispatch pattern, state tracking.
4. **Differentiate dari Understand-Anything** — CodeLens dashboard harus terintegrasi dengan analysis (bisa show taint path, security finding, complexity hotspot di graph — fitur yang UA tidak punya).
5. **48 issue total** (OpenTaint + Repomix + UA) dikerjakan paralel per fase, rilis sebagai minor version selama 14-18 bulan.

**Repo referensi:** https://github.com/Lum1104/Understand-Anything (MIT License — kompatibel untuk inspiration/adaptasi dengan attribusi).
