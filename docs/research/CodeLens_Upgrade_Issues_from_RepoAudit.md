# CodeLens — Upgrade Issues (Serapan Fitur dari RepoAudit)

> **Repo target:** `https://github.com/Wolfvin/CodeLens.git` (branch `main`)
> **Repo referensi:** `https://github.com/PurCL/RepoAudit.git` (branch `main`, ICML 2025 paper)
> **Tanggal analisa:** 2026-06-28
> **Tujuan:** menyediakan daftar issue siap-pakai untuk upgrade CodeLens berikutnya, dengan menyerap pola/arsitektur/fitur dari RepoAudit — tool *LLM-agent for repository-level code auditing* yang memadukan tree-sitter parsing dengan multi-agent LLM inference untuk bug detection.

> Dokumen ini melengkapi:
> - `CodeLens_Upgrade_Issues_from_Semgrep.md` (22 issue CL-001 s/d CL-022)
> - `CodeLens_Upgrade_Issues_from_Emerge.md` (13 issue CL-023 s/d CL-035)
>
> Issue di sini menggunakan nomor lanjutan **CL-036 s/d CL-045**.

---

## Daftar Isi

1. [Ringkasan Eksekutif](#1-ringkasan-eksekutif)
2. [Snapshot RepoAudit — Fitur Referensi](#2-snapshot-repoaudit--fitur-referensi)
3. [Gap Analysis CodeLens vs RepoAudit](#3-gap-analysis-codelens-vs-repoaudit)
4. [Daftar Issue untuk Upgrade (CL-036 s/d CL-045)](#4-daftar-issue-untuk-upgrade-cl-036-s-d-cl-045)
5. [Roadmap & Sinergi dengan Issue Sebelumnya](#5-roadmap--sinergi-dengan-issue-sebelumnya)
6. [Appendix — Peta File RepoAudit ke Topik Issue](#6-appendix--peta-file-repoaudit-ke-topik-issue)

---

## 1. Ringkasan Eksekutif

RepoAudit adalah **multi-agent LLM framework untuk repository-level code auditing** yang diterima di ICML 2025. Positioning-nya unik:

- **Semgrep** = static analysis rule engine (pattern matching murni, no LLM)
- **Emerge** = codebase visualization & architecture metrics (no LLM, no security)
- **RepoAudit** = **LLM-driven bug detection** — gunakan tree-sitter untuk parsing, lalu LLM untuk semantic analysis (dataflow, path feasibility)
- **CodeLens** = AI-native code intelligence (MCP, guard hooks) — saat ini **belum punya LLM-driven analysis internal**

RepoAudit membuka kategori baru yang CodeLens belum sentuh: **gunakan LLM untuk semantic analysis yang tidak bisa dilakukan AST matcher murni**. Contoh:

- "Apakah path ini feasible?" → LLM evaluate branch conditions
- "Apakah variable X bisa mencapai sink Y melalui function call?" → LLM trace dataflow
- "Apakah bug report ini true positive atau false positive?" → LLM justify dengan reasoning

CodeLens sudah punya positioning AI-native, tapi AI-nya berada di **luar** CodeLens (AI agent eksternal yang panggil tool CodeLens). RepoAudit menunjukkan pola di mana **LLM di-dalam** tool, sebagai bagian dari analysis pipeline — yang bisa jadi diferensiasi lebih dalam.

**10 issue kandidat** (CL-036 s/d CL-045) terbagi dalam 4 tema:

| Tema | Jumlah Issue | Prioritas dominan |
|------|:---:|:---:|
| J. LLM-Driven Analysis Pipeline | 4 | P1–P2 |
| K. Dataflow Bug Detection (NPD/MLK/UAF) | 2 | P1–P2 |
| L. Memory Architecture & Caching | 2 | P1 |
| M. Bug Report UX & Triage | 2 | P1–P2 |

**⚠️ Catatan lisensi krusial:** RepoAudit berlisensi **Purdue Non-Commercial Open Source License** — *bukan* MIT/Apache. Ini berarti:

- ❌ **TIDAK boleh copy-paste kode** RepoAudit ke CodeLens (CodeLens MIT, komersial)
- ❌ **TIDAK boleh port algoritma literal** dari RepoAudit
- ✅ **Boleh adaptasi konsep dan arsitektur** — implementasi ulang dari nol
- ✅ **Boleh sitasi paper** ICML 2025 untuk attribution konsep

Semua issue di bawah **mengharuskan reimplementasi dari nol** di CodeLens, dengan referensi ke paper RepoAudit untuk konsep, bukan ke source code.

---

## 2. Snapshot RepoAudit — Fitur Referensi

### 2.1 Identitas Repo

| Atribut | Nilai |
|---|---|
| Nama | RepoAudit |
| Tagline | "Automated Code Auditing with Multi-Agent LLM Framework" |
| Branch default | `main` |
| Lisensi | **Purdue Non-Commercial Open Source License** (BUKAN MIT) |
| Bahasa implementasi | Python 3.13 |
| Parser engine | tree-sitter (sama dengan CodeLens!) |
| Entry point | `python3 src/repoaudit.py --scan-type {metascan,dfbscan} --language {Cpp,Go,Java,Python} --project-path <path>` |
| Jumlah file Python | ~30 file (5081 LOC total) |
| Subcommand | 2 scan type (`metascan`, `dfbscan`) — bukan subcommand CLI, tapi flag |
| Akademik | ICML 2025 paper + arXiv preprint untuk rfcscan extension |
| LLM provider | OpenAI (GPT-3.5/4/4o/o3-mini), Anthropic (Claude 3.5/3.7), Google (Gemini), DeepSeek, AWS Bedrock |
| Bahasa didukung | 4 (C/C++, Java, Python, Go) — sangat fokus, bukan broad |
| Bug type didukung | 3 (NPD, MLK, UAF) |

### 2.2 Arsitektur (Ringkas)

```
RepoAudit/
├── src/
│   ├── repoaudit.py              # Main entry (210 LOC, argparser + dispatch)
│   ├── run_repoaudit.sh          # Helper script bash
│   ├── agent/                    # Multi-agent framework
│   │   ├── agent.py              # Agent ABC (17 LOC — minimal interface)
│   │   ├── metascan.py           # MetaScanAgent: parsing-only, demo (180 LOC)
│   │   └── dfbscan.py            # DFBScanAgent: dataflow bug detection (711 LOC) ⭐
│   ├── tstool/                   # Tree-sitter tools (parsing-based)
│   │   ├── analyzer/
│   │   │   ├── TS_analyzer.py    # Base TSAnalyzer (817 LOC) — call graph, CFL-reachability
│   │   │   ├── Cpp_TS_analyzer.py    # C/C++ (418 LOC)
│   │   │   ├── Go_TS_analyzer.py     # Go (351 LOC)
│   │   │   ├── Java_TS_analyzer.py   # Java (363 LOC)
│   │   │   └── Python_TS_analyzer.py # Python (285 LOC)
│   │   └── dfbscan_extractor/    # Source/sink extractor per language per bug
│   │       ├── dfbscan_extractor.py  # ABC (80 LOC)
│   │       ├── Cpp/{Cpp_MLK,Cpp_NPD,Cpp_UAF}_extractor.py
│   │       ├── Java/Java_NPD_extractor.py
│   │       ├── Python/Python_NPD_extractor.py
│   │       └── Go/Go_NPD_extractor.py
│   ├── llmtool/                  # LLM-driven analysis tools
│   │   ├── LLM_tool.py           # LLMTool ABC (106 LOC) — invoke + cache + retry
│   │   ├── LLM_utils.py          # LLM provider abstraction (368 LOC)
│   │   └── dfbscan/
│   │       ├── intra_dataflow_analyzer.py  # Explorer (232 LOC) ⭐
│   │       └── path_validator.py            # Validator (110 LOC) ⭐
│   ├── memory/                   # 3-tier memory architecture
│   │   ├── syntactic/            # AST-derived facts
│   │   │   ├── function.py       # Function class (100 LOC)
│   │   │   ├── value.py          # Value class with ValueLabel enum (118 LOC)
│   │   │   └── api.py            # API call info (30 LOC)
│   │   ├── semantic/             # Agent intermediate state
│   │   │   ├── state.py          # State ABC (6 LOC)
│   │   │   ├── metascan_state.py # MetaScan state (23 LOC)
│   │   │   └── dfbscan_state.py  # DFBScan state (202 LOC) — thread-safe with locks
│   │   └── report/
│   │       └── bug_report.py     # BugReport class (66 LOC)
│   ├── prompt/                   # JSON prompt templates per language
│   │   ├── Cpp/dfbscan/{intra_dataflow_analyzer,path_validator}.json
│   │   ├── Go/dfbscan/{...}.json
│   │   ├── Java/dfbscan/{...}.json
│   │   └── Python/dfbscan/{...}.json
│   └── ui/
│       ├── logger.py             # Custom logger (73 LOC)
│       └── web_ui.py             # Streamlit web UI (267 LOC) — TP/FP triage
├── benchmark/                    # Toy test cases + real-world submodule
│   ├── Cpp/toy/{NPD,MLK,UAF}/*.cpp
│   ├── Go/toy/{bof,nil}/*.go
│   ├── Java/toy/NPD/*.java
│   └── Python/toy/NPD/*.py
├── docs/{architecture,guide,extension}.md
├── lib/build.py                  # Build tree-sitter language bindings
├── requirements.txt              # tree-sitter, openai, anthropic, google-generativeai, boto3, streamlit, tiktoken, transformers, torch
└── .github/workflows/{black,mypy}.yml
```

### 2.3 Fitur Unggulan RepoAudit yang Relevan untuk CodeLens

#### A. Multi-Agent Framework dengan Abstract Agent Interface

`Agent` ABC sederhana (17 LOC):

```python
class Agent(ABC):
    @abstractmethod
    def start_scan(self) -> None: pass

    @abstractmethod
    def get_agent_state(self) -> State: pass
```

Setiap agent punya state sendiri, bisa invoke agent lain (multi-agent composition). Saat ini ada 2 agent:

- **MetaScanAgent** — parsing-only, gunakan TSAnalyzer langsung
- **DFBScanAgent** — dataflow bug detection dengan LLM tools

CodeLens punya 40+ engine tapi **tidak punya agent abstraction** — engine saling independent, tidak ada orchestrator yang bisa compose engine + LLM.

#### B. LLM-Driven Analysis Tools (LLMTool ABC)

`LLMTool` ABC (106 LOC) mendefinisikan pattern untuk LLM-driven analysis:

```python
class LLMTool(ABC):
    def __init__(self, model_name, temperature, language, max_query_num, logger):
        self.model = LLM(model_name, ...)
        self.cache: Dict[LLMToolInput, LLMToolOutput] = {}
        self.input_token_cost = 0
        self.output_token_cost = 0
        self.total_query_num = 0

    def invoke(self, input: LLMToolInput, cls: Type[T]) -> Optional[T]:
        # 1. Check cache (key = hash of input)
        # 2. If miss: build prompt from template + input
        # 3. Call LLM with retry (up to max_query_num)
        # 4. Parse response to LLMToolOutput subclass
        # 5. Cache result
        # 6. Track token cost

    @abstractmethod
    def _get_prompt(self, input) -> str: pass

    @abstractmethod
    def _parse_response(self, response, input) -> Optional[LLMToolOutput]: pass
```

Pola yang sangat clean: input → prompt → LLM → output, dengan caching dan cost tracking bawaan.

#### C. DFBScan Workflow: Explorer + Validator (Two-LLM-Tool Pipeline)

Ini adalah **konsep inti** RepoAudit — bug detection dengan 2 LLM tool yang berperan berbeda:

1. **IntraDataFlowAnalyzer** (Explorer, 232 LOC) — untuk setiap function dengan source value, LLM analyze:
   - "Ke mana SRC propagate di function ini?"
   - Output: reachable values per execution path (path-sensitive)
   - 4 propagation locations: function call args, return statements, parameter assignments, sink variables

2. **PathValidator** (Validator, 110 LOC) — untuk setiap candidate buggy path, LLM validate:
   - "Apakah path ini feasible? Apakah branch conditions konflik?"
   - Output: `is_reachable: bool` + explanation string
   - Mengurangi false positive dramatis (e.g., NPD yang di-guard oleh `if obj is not None`)

Pipeline lengkap (di `dfbscan.py:__process_src_value`):

```
for each source value:
    worklist = [(src_value, src_function, CallContext())]
    while worklist not empty:
        (value, function, context) = worklist.pop()
        if context.depth > call_depth: continue
        
        # Step 1: Extract sinks in this function
        sinks = extractor.extract_sinks(function)
        
        # Step 2: Ask LLM - where does value propagate in this function?
        df_output = intra_dfa.invoke(IntraDataFlowAnalyzerInput(...))
        
        # Step 3: For each path, update worklist with new (value, function, context)
        for path in df_output.reachable_values:
            delta = update_worklist(df_output, context, path)
            worklist.extend(delta)
    
    # Step 4: Collect candidate buggy paths (src -> sink)
    collect_potential_buggy_paths(src_value, ...)
    
    # Step 5: For each candidate, ask LLM - is path feasible?
    for path in potential_buggy_paths:
        pv_output = path_validator.invoke(PathValidatorInput(...))
        if pv_output.is_reachable:
            bug_reports.append(BugReport(...))
```

#### D. CallContext with CFL-Reachability (Context-Sensitive Analysis)

`CallContext` class (di `TS_analyzer.py`) track calling context sebagai stack of `ContextLabel`:

- Setiap call site menambahkan `LEFT_PAR` (call masuk) atau `RIGHT_PAR` (call keluar)
- CFL-reachability check: jika `LEFT_PAR` dan `RIGHT_PAR` tidak match (different file/line/function), path dianggap **tidak reachable**
- Mencegah false positive dari context-mismatched path (e.g., function A call B yang return None, lalu function C yang juga call B tapi expect non-None — tanpa CFL, A's None akan propagate ke C)

CodeLens `callgraph_engine.py` dan `crossfile_taint_engine.py` tidak punya context-sensitivity se sophisticated ini.

#### E. 3-Tier Memory Architecture

RepoAudit explicitly separate memory:

1. **Syntactic Memory** — AST-derived facts (Function, Value, API)
   - `Function`: function_id, name, code, line range, parameters, return values, if_statements, loop_statements, call_sites
   - `Value`: name, line, label (SRC/SINK/PARA/RET/ARG/OUT/BUF_ACCESS/LOCAL/GLOBAL), file, index
   - `API`: library API call info

2. **Semantic Memory** — agent intermediate state
   - `DFBScanState` (thread-safe dengan per-field locks): reachable_values_per_path, external_value_match, potential_buggy_paths, bug_reports
   - Persistent across agent invocations

3. **Report Memory** — final output
   - `BugReport`: bug_type, buggy_value, relevant_functions, explanation, is_human_confirmed_true

CodeLens `registry.py` hanya punya satu tier (symbol registry) — tidak ada pemisahan antara syntactic facts, analysis state, dan final report.

#### F. Per-Language Per-Bug-Type Extractor Plugin Pattern

Struktur direktori `dfbscan_extractor/<Language>/<Language>_<BugType>_extractor.py`:

```
dfbscan_extractor/
├── Cpp/
│   ├── Cpp_NPD_extractor.py    # Extract NULL sources, pointer deref sinks
│   ├── Cpp_MLK_extractor.py    # Extract malloc sources, missing-free sinks
│   └── Cpp_UAF_extractor.py    # Extract free sinks, post-free-use sinks
├── Java/Java_NPD_extractor.py
├── Python/Python_NPD_extractor.py
└── Go/Go_NPD_extractor.py
```

Setiap extractor adalah subclass `DFBScanExtractor` dengan 2 abstract method: `extract_sources(function)` dan `extract_sinks(function)`. Untuk add bug type baru (e.g., SQL Injection), tinggal buat `<Language>_SQLi_extractor.py` — tidak perlu modify core engine.

CodeLens `rules/python_security.yaml` dan `javascript_security.yaml` punya sources/sinks/sanitizers list, tapi **tidak punya per-bug-type extractor pattern** — semua rule tercampur di satu file YAML per language.

#### G. Prompt Template sebagai JSON (Per-Language Per-Tool)

```
prompt/
├── Python/dfbscan/
│   ├── intra_dataflow_analyzer.json  # system_role + task + rules + examples + answer_format
│   └── path_validator.json
├── Java/dfbscan/...
├── Cpp/dfbscan/...
└── Go/dfbscan/...
```

Setiap JSON berisi:

- `model_role_name`, `user_role_name`, `system_role`
- `task` — instruksi utama
- `analysis_rules` — array of strings (step-by-step guidelines)
- `analysis_examples` — few-shot examples (User/System dialog)
- `question_template` — placeholder `<SRC>`, `<L1>`, `<PATH>`, `<BUG_TYPE>`
- `answer_format_cot` — chain-of-thought format

Pisahkan prompt dari code → mudah iterate prompt tanpa redeploy.

#### H. Multi-Provider LLM Abstraction

`LLM_utils.py:LLM` class (368 LOC) abstraksi 5 provider:

- `infer_with_openai_model()` — GPT-3.5/4/4o
- `infer_with_o3_mini_model()` — OpenAI o3-mini (reasoning model)
- `infer_with_claude_key()` — Claude 3.5/3.7 via Anthropic API
- `infer_with_claude_aws_bedrock()` — Claude via AWS Bedrock
- `infer_with_deepseek_model()` — DeepSeek V3/R1
- `infer_with_gemini()` — Google Gemini

Dispatch berdasarkan `model_name` string (e.g., `"gpt-4o"`, `"claude-3.7"`, `"gemini-1.5-pro"`, `"deepseek-chat"`).

Token cost tracking via `tiktoken` (untuk OpenAI encoding) — input_token_cost + output_token_cost per call.

#### I. Thread-Safe Parallel Bug Detection

`DFBScanAgent.start_scan()` (di `dfbscan.py`):

```python
with ThreadPoolExecutor(max_workers=self.max_neural_workers) as executor:
    futures = [
        executor.submit(self.__process_src_value, src_value)
        for src_value in self.src_values
    ]
    for future in as_completed(futures):
        future.result()
```

Default `--max-neural-workers 30` — 30 LLM call concurrent. State (`DFBScanState`) thread-safe dengan per-field `threading.Lock()`. Progress bar via `tqdm`.

CodeLens tidak punya parallel LLM call — semua command sequential.

#### J. Bug Report dengan LLM Explanation + Triage UI

`BugReport` class:

```python
class BugReport:
    bug_type: str                    # "NPD", "MLK", "UAF"
    buggy_value: Value               # Source value yang trigger bug
    relevant_functions: Dict[id, Function]  # Function trace
    explanation: str                 # LLM-generated reasoning (CoT)
    is_human_confirmed_true: bool    # TP/FP label, default False
```

Streamlit Web UI (`web_ui.py`, 267 LOC):

- Browse bug reports by language/scanner/model/bug_type/project/timestamp
- Click each bug → show function code with line numbers
- Read LLM explanation
- Radio button: TP / FP / Unknown
- Save label back to `detect_info.json`
- Download results as JSON

#### K. Call Depth Limiting untuk Scalability

Flag `--call-depth 3` (default) — batasi inter-procedural analysis ke 3 level callee:

- src di function A → propagate ke B (depth 1) → C (depth 2) → D (depth 3) → stop
- Mencegah explosion pada recursive call chain atau deep call stack
- Trade-off: mungkin miss bug di depth > 3, tapi praktis untuk repo besar

CodeLens `trace_engine.py` punya `--depth` flag tapi untuk display, bukan untuk limit analysis.

#### L. Compilation-Free Analysis

RepoAudit explicitly tidak require build/compile:

- Pure tree-sitter parsing (no symbol resolution, no type info)
- LLM mengisi gap semantic yang biasanya butuh compilation (e.g., "apakah `x` di sini adalah pointer?" → LLM infer dari context)
- Bisa analyze repo C/C++ tanpa CMake/Make, Java tanpa Maven/Gradle, Go tanpa `go build`

CodeLens juga compilation-free, jadi ini bukan gap baru — tapi konfirmasi bahwa pendekatan ini viable untuk deep analysis.

---

## 3. Gap Analysis CodeLens vs RepoAudit

| # | Topik | CodeLens | RepoAudit | Sudah di Semgrep/Emerge? | Status |
|---|---|---|---|---|---|
| 36 | Agent abstraction (orchestrator) | ❌ Engine independent | ✅ Agent ABC + composition | ❌ | **Perlu serap** |
| 37 | LLM-driven analysis tool pattern | ❌ Tidak ada | ✅ LLMTool ABC + cache + cost | ❌ | **Perlu serap** |
| 38 | LLM dataflow explorer (intra-procedural) | ❌ Tidak ada | ✅ IntraDataFlowAnalyzer | ❌ | **Perlu serap** |
| 39 | LLM path validator (feasibility check) | ❌ Tidak ada | ✅ PathValidator | ❌ | **Perlu serap** |
| 40 | NPD/MLK/UAF bug detection | ⚠️ `ast_taint_engine.py` generic, tidak spesifik | ✅ Per-bug extractor | ⚠️ Semgrep punya, generic | **Perlu serap** |
| 41 | 3-tier memory (syntactic/semantic/report) | ⚠️ 1-tier registry | ✅ Explicit separation | ❌ | **Perlu serap** |
| 42 | LLM response cache + token cost tracking | ❌ Tidak ada | ✅ Per-tool cache + cost | ❌ | **Perlu serap** |
| 43 | Multi-provider LLM abstraction | ❌ Tidak ada | ✅ 5 provider (OpenAI/Claude/Gemini/DeepSeek/Bedrock) | ❌ | **Perlu serap** |
| 44 | Bug report dengan LLM explanation | ⚠️ Finding tanpa explanation | ✅ CoT explanation + relevant_functions | ⚠️ Semgrep Assistant (proprietary) | **Perlu serap** |
| 45 | Triage UI (TP/FP labeling) | ❌ Tidak ada | ✅ Streamlit web UI | ❌ | **Perlu serap** |

**Highlight:** Hampir semua fitur RepoAudit adalah **net new** untuk CodeLens — tidak overlap dengan Semgrep atau Emerge. Ini karena RepoAudit adalah satu-satunya dari tiga referensi yang **mengintegrasikan LLM ke dalam analysis pipeline** (bukan hanya sebagai external agent).

---

## 4. Daftar Issue untuk Upgrade (CL-036 s/d CL-045)

Setiap issue ditulis dalam format siap-pakai sebagai GitHub issue body. Tinggal copy-paste ke `https://github.com/Wolfvin/CodeLens/issues/new`.

> Konvensi label: `priority:P0` (blocker), `priority:P1` (next release), `priority:P2` (backlog). Topik baru: `topic:llm-agent`, `topic:bug-detection`, `topic:memory`, `topic:triage`.

> ⚠️ **Lisensi reminder:** RepoAudit = Purdue Non-Commercial License. Semua issue di bawah **wajib reimplementasi dari nol** di CodeLens. Boleh sitasi paper ICML 2025 untuk konsep, **TIDAK boleh** copy-paste kode.

---

### Issue #CL-036 — Agent Abstraction untuk Engine Orchestration

**Priority:** P1
**Topic:** llm-agent, architecture
**Estimasi:** 1-2 minggu
**Referensi RepoAudit:** `src/agent/agent.py` (17 LOC, Agent ABC), `src/agent/dfbscan.py` (711 LOC, composition pattern), paper ICML 2025 Section 3.2

#### Motivasi

CodeLens punya 40+ engine (`a11y_engine.py`, `ast_taint_engine.py`, `complexity_engine.py`, dst) yang **saling independent**. Tidak ada orchestrator yang bisa:

1. **Compose engine** — jalankan `secrets` → `dataflow` → `vuln-scan` dalam satu pipeline dengan shared state
2. **Mix engine + LLM** — gunakan `ast_taint_engine.py` untuk candidate finding, lalu LLM untuk validate
3. **Multi-agent composition** — Agent A invoke Agent B (e.g., DFBScanAgent invoke MetaScanAgent untuk metadata)

RepoAudit menunjukkan pattern minimal: `Agent` ABC dengan `start_scan()` dan `get_agent_state()`. Setiap agent punya state sendiri, bisa invoke agent lain.

#### Acceptance Criteria

- [ ] Abstract class `CodeLensAgent` di `scripts/agents/base_agent.py` dengan method:
  - `start_scan(self) -> None` — entry point
  - `get_agent_state(self) -> AgentState` — return state object
  - `get_report(self) -> AgentReport` — return final report
- [ ] Agent state class `AgentState` dengan thread-safe fields (jika parallel)
- [ ] 2 agent konkrit sebagai proof-of-concept:
  - `StaticAnalysisAgent` — wrap existing engines (smell + complexity + dead-code) jadi satu pipeline
  - `LLMAuditAgent` — invoke `secrets_engine.py` untuk candidate, lalu LLM untuk validate (lint ke #CL-037, #CL-038)
- [ ] CLI command baru: `codelens agent-run <agent-name> [workspace] [--params ...]`
- [ ] CLI command baru: `codelens agent-list` — list semua agent yang terdaftar
- [ ] Plugin pattern: agent bisa di-register via `plugin.yaml` dengan `type: agent`
- [ ] Documentasi: `references/agent-framework.md` dengan diagram pipeline
- [ ] Test: `tests/test_agent_framework.py`

#### Langkah Implementasi

1. Definisi `CodeLensAgent` ABC di `scripts/agents/base_agent.py`
2. Definisi `AgentState` dan `AgentReport` dataclass
3. Refactor `scripts/commands/analyze.py` (dari Issue #CL-023) untuk pakai agent pattern
4. Tulis 2 agent konkrit
5. Tambah agent registry di `scripts/agents/__init__.py`
6. Update plugin system (Issue #CL-013 di Semgrep doc) untuk support `type: agent`
7. Test dengan fixture `vulnerable_app/`

#### Dependency

- Blocked by: #CL-023 (YAML config untuk agent params)
- Blocks: #CL-037 (LLM tool butuh agent context), #CL-038 (Explorer butuh agent state), #CL-041 (memory tier butuh agent)

---

### Issue #CL-037 — LLM-Driven Analysis Tool Pattern (LLMTool ABC)

**Priority:** P1
**Topic:** llm-agent
**Estimasi:** 1-2 minggu
**Referensi RepoAudit:** `src/llmtool/LLM_tool.py` (106 LOC), `src/llmtool/LLM_utils.py` (368 LOC), paper ICML 2025 Section 3.3

#### Motivasi

CodeLens saat ini tidak punya LLM integration internal. Semua AI interaction terjadi via MCP (AI agent eksternal panggil tool CodeLens). RepoAudit menunjukkan pattern di mana **LLM adalah tool internal** — dipanggil oleh engine/agent untuk semantic analysis yang tidak bisa dilakukan AST matcher.

Use case di CodeLens:

- Taint validation: `ast_taint_engine.py` menemukan candidate source→sink, LLM validate "apakah path feasible?"
- Secret false positive: `secrets_engine.py` flag string sebagai API key, LLM check "apakah ini benar-benar secret atau placeholder?"
- Smell justification: `smell_engine.py` flag function sebagai god class, LLM explain "kenapa ini god class dan apa saran refactor?"
- Dead code reason: `deadcode_engine.py` flag function unused, LLM suggest "apakah aman dihapus, atau ada dynamic usage?"

#### Acceptance Criteria

- [ ] Abstract class `LLMTool` di `scripts/llm/base_tool.py`:
  - `__init__(model_name, temperature, max_query_num, logger)`
  - `invoke(input: LLMToolInput, output_cls: Type[T]) -> Optional[T]` — main entry
  - `_get_prompt(input) -> str` (abstract)
  - `_parse_response(response, input) -> Optional[LLMToolOutput]` (abstract)
  - Built-in caching (key = hash of input)
  - Built-in retry (up to `max_query_num`)
  - Token cost tracking (input + output)
- [ ] `LLMToolInput` dan `LLMToolOutput` ABC dengan `__hash__` dan `__eq__` untuk caching
- [ ] LLM provider abstraction di `scripts/llm/provider.py`:
  - OpenAI (GPT-4o, GPT-4-turbo, GPT-4o-mini, o3-mini)
  - Anthropic (Claude 3.5, Claude 3.7) — direct API + AWS Bedrock
  - Google (Gemini 1.5 Pro/Flash)
  - DeepSeek (V3, R1)
  - **Z.ai GLM** (tambahkan — CodeLens already uses z-ai-web-dev-sdk in other contexts)
  - Dispatch berdasarkan `model_name` string prefix
- [ ] Config via env vars: `CODELENS_LLM_PROVIDER`, `CODELENS_LLM_MODEL`, `CODELENS_LLM_API_KEY`
- [ ] Config via `codelens.yaml` (lint ke #CL-023): `llm: {provider, model, temperature, max_query_num, max_concurrent}`
- [ ] Token cost report di output: `{llm_cost: {input_tokens, output_tokens, total_calls, cache_hits, cache_misses}}`
- [ ] Documentasi: `references/llm-integration.md` dengan config examples
- [ ] Test: `tests/test_llm_tool.py` dengan mock provider

#### Langkah Implementasi

1. Definisi ABC di `scripts/llm/base_tool.py`
2. Tulis `scripts/llm/provider.py` — adaptasi konsep dari RepoAudit `LLM_utils.py` (reimplementasi dari nol, jangan copy)
3. Implementasi 5 provider + Z.ai GLM
4. Tulis mock provider untuk testing
5. Tambah dependency `openai`, `anthropic`, `google-generativeai`, `tiktoken` ke `requirements.txt` (optional, lazy import)
6. Documentasi

#### Dependency

- Blocked by: #CL-036 (Agent framework untuk host LLM tool)
- Blocks: #CL-038 (Explorer), #CL-039 (Validator), #CL-044 (Bug explanation)

---

### Issue #CL-038 — LLM Dataflow Explorer (Intra-Procedural Path Analysis)

**Priority:** P1
**Topic:** llm-agent, bug-detection
**Estimasi:** 2-3 minggu
**Referensi RepoAudit:** `src/llmtool/dfbscan/intra_dataflow_analyzer.py` (232 LOC), `src/prompt/Python/dfbscan/intra_dataflow_analyzer.json`, paper ICML 2025 Section 3.3 (Explorer)

#### Motivasi

CodeLens `ast_taint_engine.py` (3755 LOC) sudah punya taint analysis, tapi **tidak path-sensitive** — dia track "apakah source bisa reach sink?" tanpa pertimbangkan branch conditions. Akibatnya banyak false positive:

- Source di-set di `if` branch, sink di `else` branch → false positive (path tidak feasible)
- Source di-null-check sebelum sink → false positive (guard condition)
- Source di-set di early return, sink setelah return → false positive (dead path)

RepoAudit menunjukkan pola: gunakan LLM untuk trace dataflow per-path di single function. LLM bisa reason tentang:

- Branch conditions (if/elif/else)
- Loop iterations (first iteration expansion)
- Exception handling
- Alias tracking (a = b, b = c, c adalah SRC → a juga SRC)

#### Acceptance Criteria

- [ ] Concrete class `IntraDataflowExplorer` extends `LLMTool` (dari #CL-037)
- [ ] Input: `IntraDataflowInput(function, source_value, sink_values, call_statements, return_values)`
- [ ] Output: `IntraDataflowOutput(reachable_values_per_path: List[Set[Value]])` — path-sensitive
- [ ] Prompt template JSON per-bahasa: Python, JS, TS, Java, Go (5 awal)
- [ ] Prompt berisi: system_role, task, analysis_rules (step-by-step), analysis_examples (few-shot), answer_format_cot
- [ ] Output parsing: parse LLM response menjadi List of path, each path = Set of Value
- [ ] Integrate dengan `ast_taint_engine.py`:
  - `ast_taint_engine.py` find candidate source→sink (existing logic)
  - `IntraDataflowExplorer` refine dengan path analysis
  - Filter candidate yang path-nya tidak feasible
- [ ] CLI command baru: `codelens llm-dataflow <function-name> [--source VAR] [--sink SINK]` — debug tool untuk lihat LLM analysis
- [ ] Performance: 1 function analysis dalam <10 detik (single LLM call, 3 retry max)
- [ ] Documentasi: `references/llm-dataflow.md` dengan example output
- [ ] Test: `tests/test_llm_dataflow.py` dengan 10 fixture function (5 feasible path, 5 infeasible)

#### Langkah Implementasi

1. Definisi `IntraDataflowInput`/`Output` dataclass
2. Tulis prompt template JSON untuk 5 bahasa (reimplementasi dari konsep RepoAudit, bukan copy)
3. Implementasi `_get_prompt()` dan `_parse_response()`
4. Integrate dengan `ast_taint_engine.py` sebagai post-filter
5. Tambah CLI command
6. Test dengan fixture

#### Dependency

- Blocked by: #CL-036 (Agent), #CL-037 (LLMTool)
- Blocks: #CL-039 (Validator butuh Explorer output), #CL-040 (NPD/MLK/UAF butuh Explorer)

---

### Issue #CL-039 — LLM Path Validator (Inter-Procedural Feasibility Check)

**Priority:** P1
**Topic:** llm-agent, bug-detection
**Estimasi:** 1-2 minggu
**Referensi RepoAudit:** `src/llmtool/dfbscan/path_validator.py` (110 LOC), `src/prompt/Python/dfbscan/path_validator.json`, paper ICML 2025 Section 3.3 (Validator)

#### Motivasi

Setelah #CL-038 (Explorer) menghasilkan candidate buggy path (src → ... → sink), perlu validate:

1. **Branch condition conflict** — `if x > 0` di function A konflik dengan `if x <= 0` di function B di path yang sama
2. **Guard condition** — `if obj is not None: obj.method()` → NPD tidak mungkin
3. **Early return** — function exit sebelum sink di-reach
4. **Variable value constraint** — `x = 5; if x > 10: ...` → branch tidak mungkin diambil

Ini adalah **inter-procedural** analysis (lintas function), lebih kompleks dari Explorer yang intra-procedural. LLM cocok karena bisa reason tentang multi-function flow tanpa full program slicing.

#### Acceptance Criteria

- [ ] Concrete class `PathValidator` extends `LLMTool`
- [ ] Input: `PathValidatorInput(bug_type, values: List[Value], values_to_functions: Dict[Value, Function])`
- [ ] Output: `PathValidatorOutput(is_reachable: bool, explanation_str: str)`
- [ ] Prompt template JSON per-bahasa (5 awal, sama dengan #CL-038)
- [ ] Integrate dengan `ast_taint_engine.py`:
  - Setelah Explorer (#CL-038) produce candidate path
  - Validator check feasibility
  - Hanya path yang `is_reachable: True` yang di-report sebagai finding
- [ ] Output finding menyertakan `explanation` field (LLM-generated CoT reasoning)
- [ ] CLI command baru: `codelens llm-validate <finding-id>` — re-validate finding dengan LLM
- [ ] Performance: 1 path validation dalam <5 detik
- [ ] False positive reduction target: 50%+ reduction vs `ast_taint_engine.py` tanpa validator (benchmark di `vulnerable_app/`)
- [ ] Documentasi: `references/llm-validator.md`
- [ ] Test: `tests/test_path_validator.py`

#### Langkah Implementasi

1. Definisi input/output dataclass
2. Tulis prompt template JSON (reimplementasi konsep)
3. Implementasi `_get_prompt()` dan `_parse_response()`
4. Integrate dengan `ast_taint_engine.py`
5. Benchmark: run sebelum/sesudah validator, compare finding count + TP/FP rate
6. Tambah CLI command
7. Test

#### Dependency

- Blocked by: #CL-037 (LLMTool), #CL-038 (Explorer untuk produce candidate)
- Blocks: #CL-040 (NPD/MLK/UAF butuh Validator)

---

### Issue #CL-040 — Bug Type-Specific Detector (NPD, MLK, UAF, SQLi, XSS)

**Priority:** P2
**Topic:** bug-detection
**Estimasi:** 3-4 minggu
**Referensi RepoAudit:** `src/tstool/dfbscan_extractor/` (7 extractor files), paper ICML 2025 Section 3.4

#### Motivasi

CodeLens `scripts/rules/python_security.yaml` dan `javascript_security.yaml` punya sources/sinks/sanitizers list, tapi:

1. **Tidak per-bug-type** — semua rule tercampur (SQLi, command injection, path traversal, SSRF di satu file)
2. **Tidak ada extractor pattern** — tidak ada class yang khusus extract "NULL sources" atau "malloc sources"
3. **Tidak ada bug type label di finding** — finding hanya punya `rule_id`, tidak ada `bug_type` field

RepoAudit punya pattern: `<Language>_<BugType>_Extractor` class dengan `extract_sources()` dan `extract_sinks()`. Untuk add bug type baru, tinggal buat extractor baru.

#### Acceptance Criteria

- [ ] Abstract class `BugDetector` di `scripts/bug_detectors/base_detector.py`:
  - `extract_sources(function) -> List[Value]` (abstract)
  - `extract_sinks(function) -> List[Value]` (abstract)
  - `detect(workspace) -> List[BugReport]` — orchestrate Explorer + Validator
- [ ] 5 bug detector konkrit (per-bahasa, mulai dari Python + JS):
  - `NPD_Detector` — Null Pointer Dereference (Python: `None`, JS: `null`/`undefined`)
  - `SQLi_Detector` — SQL Injection (existing sources/sinks dari `python_security.yaml`)
  - `XSS_Detector` — Cross-Site Scripting (JS/TS only)
  - `CommandInjection_Detector` — OS command injection
  - `PathTraversal_Detector` — file path traversal
- [ ] Setiap detector return `BugReport` dengan: `bug_type`, `buggy_value`, `relevant_functions`, `explanation` (LLM-generated)
- [ ] CLI command baru: `codelens detect-bugs [workspace] [--bug-type NPD|SQLi|XSS|CMD|PATH|all] [--language py|js|ts|...]`
- [ ] CLI command baru: `codelens list-bug-types` — list semua bug type yang didukung
- [ ] Plugin pattern: detector bisa di-register via `plugin.yaml` dengan `type: bug_detector`
- [ ] Output finding compatible dengan SARIF (lint ke Issue #CL-007 di Semgrep doc — formatter SARIF)
- [ ] Documentasi: `references/bug-detectors.md` dengan cara write detector baru
- [ ] Test: `tests/test_bug_detectors.py` per detector

#### Langkah Implementasi

1. Definisi `BugDetector` ABC
2. Refactor existing `python_security.yaml` rules menjadi per-bug-type Python class
3. Implementasi 5 detector
4. Integrate dengan #CL-038 (Explorer) dan #CL-039 (Validator)
5. Tambah CLI command
6. Update plugin system untuk `type: bug_detector`
7. Test dengan fixture `vulnerable_app/`

#### Dependency

- Blocked by: #CL-036 (Agent), #CL-038 (Explorer), #CL-039 (Validator)
- Blocks: #CL-044 (Bug explanation butuh BugReport dari detector)

---

### Issue #CL-041 — 3-Tier Memory Architecture (Syntactic / Semantic / Report)

**Priority:** P1
**Topic:** memory, architecture
**Estimasi:** 2-3 minggu
**Referensi RepoAudit:** `src/memory/syntactic/`, `src/memory/semantic/`, `src/memory/report/`, paper ICML 2025 Section 3.4

#### Motivasi

CodeLens `registry.py` (440 LOC) menyimpan semua symbol di satu tier — functions, classes, call edges, references, semua bercampur. Tidak ada pemisahan:

1. **Syntactic facts** (AST-derived, immutable) — function signature, parameters, return values
2. **Semantic state** (analysis intermediate, mutable) — taint propagation, dataflow facts, candidate paths
3. **Final report** (output, immutable setelah di-generate) — bug report, finding, recommendation

Akibatnya:

- Hard cache invalidation: ubah 1 file → seluruh registry invalidate (tidak granular)
- Tidak bisa share semantic state antar engine: `ast_taint_engine.py` dan `crossfile_taint_engine.py` masing-masing maintain state sendiri
- Tidak bisa parallel: thread-safe issue karena semua engine akses registry yang sama

RepoAudit explicit separate 3 tier dengan thread-safe semantic state.

#### Acceptance Criteria

- [ ] `scripts/memory/syntactic.py` — `SyntacticMemory` class:
  - `functions: Dict[int, Function]` — function_id → Function (immutable setelah parse)
  - `values: Dict[int, Value]` — value_id → Value
  - `apis: Dict[int, API]` — API call info
  - `add_function(func)`, `get_function(id)`, `query_functions(predicate)`
  - Persisted di `.codelens/memory/syntactic.pkl` (disk cache)
- [ ] `scripts/memory/semantic.py` — `SemanticMemory` class:
  - `agent_states: Dict[str, AgentState]` — per-agent state
  - Thread-safe dengan `threading.RLock()` per-field
  - `update_state(agent_id, key, value)`, `get_state(agent_id, key)`
  - Ephemeral (in-memory only, tidak persisted)
- [ ] `scripts/memory/report.py` — `ReportMemory` class:
  - `findings: List[Finding]` — immutable append-only
  - `bug_reports: Dict[int, BugReport]`
  - `add_finding(finding)`, `get_findings(filter)`
  - Persisted di `.codelens/memory/report.json` (human-readable)
- [ ] Refactor `registry.py` untuk delegate ke `SyntacticMemory` (backward compatible API)
- [ ] Refactor `ast_taint_engine.py`, `dataflow_engine.py`, `crossfile_taint_engine.py` untuk gunakan `SemanticMemory`
- [ ] Refactor output formatter untuk consume `ReportMemory`
- [ ] Documentasi: `references/memory-architecture.md` dengan diagram
- [ ] Migration script: `codelens migrate-memory` — convert old `.codelens/registry.json` ke 3-tier format
- [ ] Test: `tests/test_memory_architecture.py`

#### Langkah Implementasi

1. Definisi 3 memory class
2. Implementasi `SyntacticMemory` (refactor dari `registry.py`)
3. Implementasi `SemanticMemory` (baru)
4. Implementasi `ReportMemory` (refactor dari output formatter)
5. Update engine untuk gunakan memory tier
6. Migration script
7. Test
8. Performance benchmark: pastikan tidak ada regression vs old registry

#### Dependency

- Blocked by: #CL-036 (Agent butuh memory tier)
- Blocks: #CL-042 (Cache butuh syntactic memory), #CL-044 (Bug report butuh report memory)

---

### Issue #CL-042 — LLM Response Cache + Token Cost Tracking

**Priority:** P1
**Topic:** llm-agent, performance
**Estimasi:** 1 minggu
**Referensi RepoAudit:** `src/llmtool/LLM_tool.py:LLMTool.cache` (dict-based, in-memory), `input_token_cost`/`output_token_cost`/`total_query_num` fields

#### Motivasi

LLM call mahal (uang + latency). Tanpa caching:

- Run `codelens detect-bugs` → 100 LLM call → $5
- Run lagi (file sedikit berubah) → 100 LLM call lagi → $5 lagi (sebagian besar redundant)
- Tidak ada visibility ke cost → user tidak tahu berapa yang dihabiskan

RepoAudit punya in-memory cache per-tool (key = hash of input). Tapi in-memory tidak persist antar session. CodeLens perlu **disk cache** supaya bisa reuse across runs.

#### Acceptance Criteria

- [ ] Disk cache di `~/.codelens/llm_cache/` dengan struktur `<tool_name>/<input_hash>.json`
- [ ] Cache key: SHA-256 dari `(tool_name, model_name, input_hash)` — invalidasi jika model ganti
- [ ] Cache value: `{output, input_token_cost, output_token_cost, timestamp, model_name}`
- [ ] Cache hit ratio terekspos di output: `{cache: {hits: 87, misses: 13, hit_ratio: 0.87}}`
- [ ] Token cost report di output:
  ```json
  {
    "llm_cost": {
      "input_tokens": 45230,
      "output_tokens": 8721,
      "total_calls": 100,
      "cache_hits": 87,
      "cache_misses": 13,
      "estimated_cost_usd": 0.85
    }
  }
  ```
- [ ] Cost estimation per model (config di `scripts/llm/pricing.json`):
  - GPT-4o: $0.0025/1K input, $0.01/1K output
  - Claude 3.7: $0.003/1K input, $0.015/1K output
  - Gemini 1.5 Pro: $0.00125/1K input, $0.005/1K output
  - DeepSeek V3: $0.00014/1K input, $0.00028/1K output
  - Z.ai GLM-4: (update sesuai pricing terbaru)
- [ ] CLI command `codelens llm-cache stats` — show cache statistics
- [ ] CLI command `codelens llm-cache clear` — purge cache
- [ ] Flag `--no-cache` di command yang gunakan LLM (untuk benchmark/debug)
- [ ] Flag `--max-cost-usd N` — abort jika estimated cost melebihi N
- [ ] Auto-evict cache entry >30 hari
- [ ] Thread-safe (multiple agent bisa baca cache bersamaan)
- [ ] Documentasi: `references/llm-cache.md`

#### Langkah Implementasi

1. Definisi cache schema di `scripts/llm/cache.py`
2. Implementasi disk cache dengan file lock
3. Update `LLMTool.invoke()` (dari #CL-037) untuk check cache sebelum call LLM
4. Tulis `pricing.json` dengan cost per model
5. Tambah cost tracking di `LLMTool`
6. Tambah CLI command
7. Test dengan mock LLM

#### Dependency

- Blocked by: #CL-037 (LLMTool)
- Blocks: tidak ada

---

### Issue #CL-043 — Multi-Provider LLM Abstraction (5 Provider + Z.ai GLM)

**Priority:** P1
**Topic:** llm-agent
**Estimasi:** 1 minggu
**Referensi RepoAudit:** `src/llmtool/LLM_utils.py` (368 LOC, 5 provider)

#### Motivasi

Issue #CL-037 menyebutkan multi-provider abstraction sebagai bagian dari `LLMTool`, tapi detailnya cukup kompleks untuk dijadikan issue terpisah. RepoAudit support 5 provider:

- OpenAI (GPT-3.5/4/4o/o3-mini)
- Anthropic direct (Claude 3.5/3.7)
- AWS Bedrock (Claude via Bedrock)
- Google (Gemini)
- DeepSeek (V3/R1)

CodeLens harus support minimal 5 provider ini + **Z.ai GLM** (karena CodeLens already uses z-ai-web-dev-sdk in other contexts, ini konsisten).

#### Acceptance Criteria

- [ ] `scripts/llm/provider.py` dengan `LLMProvider` ABC:
  - `infer(prompt: str, system_role: str) -> Tuple[str, int, int]` — return (output, input_tokens, output_tokens)
  - `validate_api_key() -> bool`
  - `estimate_cost(input_tokens, output_tokens) -> float`
- [ ] 6 concrete provider:
  - `OpenAIProvider` (GPT-4o, GPT-4-turbo, GPT-4o-mini, o3-mini)
  - `AnthropicProvider` (Claude 3.5, Claude 3.7) — direct API
  - `BedrockProvider` (Claude via AWS Bedrock) — untuk enterprise yang pakai AWS
  - `GoogleProvider` (Gemini 1.5 Pro/Flash, Gemini 2.0)
  - `DeepSeekProvider` (V3, R1)
  - `ZaiProvider` (GLM-4, GLM-4-Plus) — via z-ai-web-dev-sdk atau direct API
- [ ] Dispatch berdasarkan `model_name` string prefix:
  - `"gpt-*"` → OpenAI
  - `"claude-*"` → Anthropic (atau Bedrock jika `CODELENS_LLM_USE_BEDROCK=true`)
  - `"gemini-*"` → Google
  - `"deepseek-*"` → DeepSeek
  - `"glm-*"` → Z.ai
- [ ] Lazy import: provider module hanya di-import jika dipakai (avoid heavy deps jika user hanya pakai 1 provider)
- [ ] Timeout handling: 60s default, configurable via `CODELENS_LLM_TIMEOUT`
- [ ] Retry with exponential backoff: 3 retry, 1s/2s/4s
- [ ] Rate limit handling: respect `Retry-After` header
- [ ] API key dari env var: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `DEEPSEEK_API_KEY`, `ZAI_API_KEY`
- [ ] Documentasi: `references/llm-providers.md` dengan setup per provider

#### Langkah Implementasi

1. Definisi `LLMProvider` ABC
2. Implementasi 6 provider (reimplementasi dari konsep RepoAudit, jangan copy)
3. Tambah dispatch logic
4. Tambah lazy import
5. Test dengan mock provider (real API test optional, butuh API key)
6. Documentasi

#### Dependency

- Blocked by: #CL-037 (LLMTool ABC)
- Blocks: #CL-038 (Explorer butuh provider), #CL-039 (Validator butuh provider)

---

### Issue #CL-044 — Bug Report dengan LLM-Generated Explanation (Chain-of-Thought)

**Priority:** P1
**Topic:** bug-detection, triage
**Estimasi:** 1-2 minggu
**Referensi RepoAudit:** `src/memory/report/bug_report.py` (66 LOC, `explanation` field), paper ICML 2025 Section 3.5

#### Motivasi

CodeLens finding saat ini hanya berisi:

```json
{
  "rule_id": "py/sql-injection",
  "file": "src/api.py",
  "line": 42,
  "severity": "critical",
  "message": "User input flows into SQL query without parameterization"
}
```

Tidak ada **explanation** kenapa ini bug, apa impact-nya, bagaimana fix-nya. Developer yang menerima finding harus trace manual ke code untuk paham.

RepoAudit `BugReport` punya `explanation` field berisi LLM-generated chain-of-thought:

```
Explanation:
Step 1: In function get_user(user_id) at line 12, parameter user_id is sourced from flask.request.args (line 10), making it user-controlled.
Step 2: At line 14, user_id is passed directly to cursor.execute() without sanitization.
Step 3: An attacker could inject SQL like "1; DROP TABLE users; --" via the user_id parameter, which would be executed by the database.
Step 4: The fix is to use parameterized queries: cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,)).
```

Ini jauh lebih actionable daripada generic message.

#### Acceptance Criteria

- [ ] Extend `BugReport` class (dari #CL-040 atau #CL-041) dengan field:
  - `explanation: str` — LLM-generated CoT reasoning (multi-step)
  - `fix_suggestion: str` — LLM-suggested fix (code snippet)
  - `confidence: float` — 0.0-1.0, LLM self-reported confidence
  - `relevant_functions: Dict[int, Function]` — function trace untuk context
- [ ] Setelah #CL-039 (Validator) confirm `is_reachable: True`, generate explanation:
  - Input: bug_type, buggy_value, relevant_functions, path
  - LLM prompt: "Explain step-by-step why this is a bug and suggest a fix"
  - Output: explanation + fix_suggestion + confidence
- [ ] Output finding (JSON, SARIF, Markdown) menyertakan explanation
- [ ] CLI command `codelens explain <finding-id>` — re-generate explanation untuk finding existing
- [ ] Tambah ke MCP server: `codelens_explain_finding` tool
- [ ] Markdown formatter render explanation sebagai blockquote
- [ ] SARIF formatter put explanation di `result.message.text` (lebih panjang dari generic message)
- [ ] Performance: explanation generation dalam <10 detik per finding
- [ ] Documentasi: `references/bug-explanation.md` dengan example
- [ ] Test: 20 finding dari `vulnerable_app/` fixture, manual review explanation quality

#### Langkah Implementasi

1. Extend `BugReport` dataclass
2. Tulis `ExplanationGenerator` LLM tool (subclass `LLMTool`)
3. Prompt template: "You are a security expert. Given the following bug report, explain step-by-step why it's a bug and suggest a fix
  - Output: explanation + fix_suggestion + confidence
- [ ] Output finding (JSON, SARIF, Markdown) menyertakan explanation
- [ ] CLI command `codelens explain <finding-id>` — re-generate explanation untuk finding existing
- [ ] Tambah ke MCP server: `codelens_explain_finding` tool
- [ ] Markdown formatter render explanation sebagai blockquote
- [ ] SARIF formatter put explanation di `result.message.text`
- [ ] Documentasi: `references/bug-explanation.md`
- [ ] Test: `tests/test_bug_explanation.py`

#### Langkah Implementasi

1. Extend `BugReport` dataclass
2. Tulis explanation generator (LLMTool subclass)
3. Integrate dengan #CL-039 (Validator) — after validation, generate explanation
4. Update formatter (JSON, SARIF, Markdown)
5. Tambah CLI command dan MCP tool
6. Test

#### Dependency

- Blocked by: #CL-039 (Validator), #CL-040 (BugDetector), #CL-041 (ReportMemory)
- Blocks: #CL-045 (Triage UI butuh explanation untuk display)

---

### Issue #CL-045 — Triage UI untuk TP/FP Labeling (Streamlit Web App)

**Priority:** P2
**Topic:** triage, ui
**Estimasi:** 1-2 minggu
**Referensi RepoAudit:** `src/ui/web_ui.py` (267 LOC, Streamlit-based)

#### Motivasi

CodeLens `dashboard_engine.py` hanya output JSON untuk dashboard eksternal. Issue #CL-031 (dari Emerge doc) akan tambahkan interactive D3 graph visualization. Tapi **tidak ada UI khusus untuk triage bug report** — developer yang menerima 50 finding harus manually classify TP/FP di spreadsheet.

RepoAudit punya Streamlit web UI sederhana (267 LOC) untuk:

- Browse bug reports by filter (language, scanner, model, bug_type, project, timestamp)
- Click each bug → show function code with line numbers
- Read LLM explanation (dari #CL-044)
- Radio button: TP / FP / Unknown
- Save label back to `detect_info.json`
- Download labeled results as JSON

Streamlit cocok karena:

- Pure Python, tidak butuh frontend build
- Quick to iterate
- Bisa deploy local atau cloud
- Sudah ada di `requirements.txt` RepoAudit, kompatibel dengan Python 3.8+

#### Acceptance Criteria

- [ ] CLI command baru: `codelens triage [workspace] [--port 8501]`
- [ ] Launch Streamlit web UI di `http://localhost:8501`
- [ ] Sidebar navigation: Home, Findings, Statistics
- [ ] **Findings page**:
  - Filter by: severity (critical/high/medium/low), bug_type, file, status (unlabeled/TP/FP)
  - Sortable table: finding_id, rule_id, file:line, severity, status
  - Click row → detail view:
    - Function code with line numbers (highlight buggy line)
    - LLM explanation (dari #CL-044)
    - Fix suggestion (jika ada)
    - Radio: True Positive / False Positive / Unknown
    - Text area for reviewer notes
    - Save button → persist label to `.codelens/triage_labels.json`
- [ ] **Statistics page**:
  - Total findings, TP count, FP count, unlabeled count
  - Per-bug-type breakdown
  - Per-file heatmap (file dengan most findings)
  - Precision chart (TP / (TP + FP)) per rule_id
- [ ] **Home page**: welcome + quick start guide + link to docs
- [ ] Bisa export labeled results as CSV/JSON
- [ ] Multi-user support: labels di-share via git-committed `.codelens/triage_labels.json`
- [ ] Dark mode (Streamlit built-in)
- [ ] Documentasi: `references/triage-ui.md` dengan screenshot
- [ ] Test: `tests/test_triage_ui.py` (Streamlit testing framework)

#### Langkah Implementasi

1. Tambah `streamlit` ke `requirements.txt` (optional dependency)
2. Tulis `scripts/ui/triage_app.py` — Streamlit app
3. Tambah CLI command `codelens triage` yang run `streamlit run scripts/ui/triage_app.py`
4. Implementasi 3 page (Home, Findings, Statistics)
5. Implementasi label persistence
6. Implementasi export
7. Test dengan fixture `vulnerable_app/` + mock findings
8. Documentasi dengan screenshot

#### Dependency

- Blocked by: #CL-041 (ReportMemory untuk finding source), #CL-044 (Explanation untuk display)
- Blocks: tidak ada

---

## 5. Roadmap & Sinergi dengan Issue Sebelumnya

### 5.1 Matriks Prioritas (lanjutan dari dokumen Semgrep + Emerge)

| Issue | Priority | Effort | Dependency | Tema |
|---|:---:|:---:|---|---|
| #CL-036 Agent Abstraction | P1 | 1-2w | #CL-023 | llm-agent, architecture |
| #CL-037 LLMTool ABC | P1 | 1-2w | #CL-036 | llm-agent |
| #CL-041 3-Tier Memory | P1 | 2-3w | #CL-036 | memory, architecture |
| #CL-042 LLM Cache + Cost | P1 | 1w | #CL-037 | llm-agent, performance |
| #CL-043 Multi-Provider LLM | P1 | 1w | #CL-037 | llm-agent |
| #CL-038 LLM Dataflow Explorer | P1 | 2-3w | #CL-036, #CL-037 | llm-agent, bug-detection |
| #CL-039 LLM Path Validator | P1 | 1-2w | #CL-037, #CL-038 | llm-agent, bug-detection |
| #CL-044 Bug Explanation (CoT) | P1 | 1-2w | #CL-039, #CL-040, #CL-041 | bug-detection, triage |
| #CL-040 Bug Type Detector | P2 | 3-4w | #CL-036, #CL-038, #CL-039 | bug-detection |
| #CL-045 Triage UI | P2 | 1-2w | #CL-041, #CL-044 | triage, ui |

### 5.2 Sinergi dengan Issue Semgrep (CL-001 s/d CL-022)

| Issue RepoAudit | Sinergi dengan Issue Semgrep |
|---|---|
| #CL-036 Agent Abstraction | Bisa jadi orchestrator untuk #CL-001 (Pattern Rule Language) — agent compose rule matching + LLM validation |
| #CL-037 LLMTool ABC | Bisa enhance #CL-013 (MCP Hooks) — hook invoke LLM tool untuk validate file yang baru di-write AI agent |
| #CL-038 LLM Explorer | Bisa enhance #CL-003 (Taint Propagator) — Explorer replace/augment static taint analysis dengan LLM path analysis |
| #CL-039 LLM Validator | Bisa reduce false positive dari #CL-001 (Pattern Rule Language) — setelah pattern match, LLM validate |
| #CL-040 Bug Type Detector | Bisa consume rule dari #CL-001 (Pattern Rule Language) — rule define sources/sinks, detector orchestrate Explorer + Validator |
| #CL-041 3-Tier Memory | Bisa enhance #CL-020 (Disk Cache AST) — SyntacticMemory di-cache di disk, SemanticMemory ephemeral, ReportMemory persisted |
| #CL-042 LLM Cache | Bisa enhance #CL-015 (MCP scan_with_custom_rule) — cache result rule ad-hoc untuk reuse |
| #CL-044 Bug Explanation | Bisa enhance #CL-007 (Output Formatter) — semua formatter (SARIF, JSON, Markdown) include explanation field |
| #CL-045 Triage UI | Bisa enhance #CL-031 (Interactive Dashboard dari Emerge) — integrate triage panel ke dashboard |

### 5.3 Sinergi dengan Issue Emerge (CL-023 s/d CL-035)

| Issue RepoAudit | Sinergi dengan Issue Emerge |
|---|---|
| #CL-036 Agent Abstraction | Bisa jadi orchestrator untuk #CL-024 (Louvain Modularity) — agent compose architecture analysis + LLM reasoning |
| #CL-038 LLM Explorer | Bisa enhance #CL-029 (Change Coupling) — LLM analyze "kenapa file-file ini coupled secara logika?" |
| #CL-041 3-Tier Memory | Bisa enhance #CL-023 (YAML Config) — config define memory tier policy (e.g., "syntactic cache TTL: 7 days") |
| #CL-044 Bug Explanation | Bisa enhance #CL-031 (Dashboard) — finding node di graph menampilkan explanation sebagai tooltip |
| #CL-045 Triage UI | Bisa integrate dengan #CL-031 (Dashboard) — triage panel di sidebar dashboard |

### 5.4 Quick Wins (bisa mulai minggu ini, tanpa dependency)

Issue-issue ini bisa langsung dikerjakan tanpa menunggu fondasi besar:

1. **#CL-042 LLM Cache + Cost** — 1 minggu, isolasi di `scripts/llm/cache.py`, tidak butuh agent framework
2. **#CL-043 Multi-Provider LLM** — 1 minggu, implementasi 6 provider, dispatch logic
3. **#CL-045 Triage UI** — 1-2 minggu, Streamlit app, bisa mock finding source (tidak butuh #CL-041 selesai)

Total ~3-4 minggu untuk 3 quick win yang akan membuka jalan untuk issue lain.

### 5.5 3-Sprint Roadmap Tambahan (lanjutan dari dokumen Semgrep + Emerge)

Jika ditambahkan ke roadmap yang sudah ada (Sprint 1-6 di Semgrep + Emerge):

#### Sprint 7 — LLM Foundation
Fokus: infrastruktur LLM yang reusable.

- #CL-036 Agent Abstraction (1-2w)
- #CL-037 LLMTool ABC (1-2w, setelah #CL-036)
- #CL-043 Multi-Provider LLM (1w, paralel dengan #CL-037)
- #CL-042 LLM Cache + Cost (1w, setelah #CL-037)
- #CL-041 3-Tier Memory (2-3w, paralel)

#### Sprint 8 — LLM-Driven Bug Detection
Fokus: gunakan LLM untuk bug detection yang tidak bisa dilakukan AST matcher murni.

- #CL-038 LLM Dataflow Explorer (2-3w)
- #CL-039 LLM Path Validator (1-2w, setelah #CL-038)
- #CL-040 Bug Type Detector (3-4w, paralel — bisa mulai dengan 1 bug type dulu)
- #CL-044 Bug Explanation (1-2w, setelah #CL-039)

#### Sprint 9 — Triage & UX
Fokus: UX untuk developer yang menerima finding.

- #CL-045 Triage UI (1-2w)
- Integrate #CL-044 (Explanation) ke #CL-031 (Dashboard dari Emerge)
- Integrate #CL-045 (Triage) ke #CL-031 (Dashboard)

### 5.6 Total Estimasi Effort Tambahan

- **P1 (Sprint 7-9):** ~12-18 minggu
- **P2 (backlog):** ~4-6 minggu
- **Total jika satu developer:** ~16-24 minggu (4-6 bulan)
- **Total jika 3 developer paralel:** ~6-8 minggu (1.5-2 bulan)

### 5.7 Pertimbangan Strategis

**Kenapa issue RepoAudit penting meskipun CodeLens sudah punya positioning AI-native?**

1. **LLM di-dalam vs di-luar** — CodeLens saat ini LLM-nya di-luar (AI agent eksternal panggil MCP tool). RepoAudit menunjukkan LLM di-dalam (engine invoke LLM untuk analysis). Keduanya komplementer, bukan eksklusif.
2. **False positive reduction** — Validator (#CL-039) bisa reduce FP 50%+ vs pure AST matching. Ini langsung improve user experience.
3. **Actionable finding** — Explanation (#CL-044) membuat finding jadi self-documenting. Developer tidak perlu trace manual.
4. **Triage workflow** — UI (#CL-045) formalisasi workflow yang sekarang ad-hoc di spreadsheet.
5. **Academic credibility** — sitasi ICML 2025 paper di README CodeLens meningkatkan authority.

**Yang TIDAK perlu diserap dari RepoAudit:**

1. **C/C++ focus** — RepoAudit heavy di C/C++ (NPD/MLK/UAF adalah bug type C-family). CodeLens lebih broad (web, frontend, Python, JS). Prioritaskan bug type yang relevan: SQLi, XSS, Command Injection, Path Traversal.
2. **PyDriller** — RepoAudit tidak pakai PyDriller (beda dengan Emerge). Skip.
3. **Streamlit dependency** — jika Streamlit terlalu heavy, pertimbangkan alternatif: Gradio, Flask + HTMX, atau pure HTML.
4. **AWS Bedrock provider** — terlalu enterprise-specific. Implementasikan hanya jika ada user request.
5. **torch + transformers** — RepoAudit list dependency ini tapi tidak jelas dipakai untuk apa (mungkin untuk future local LLM). Skip dulu.

### 5.8 Quick Comparison: CodeLens vs RepoAudit vs Semgrep vs Emerge

| Dimensi | CodeLens | RepoAudit | Semgrep | Emerge |
|---|---|---|---|---|
| **Positioning** | AI-native code intelligence | LLM-agent code auditing | Static analysis rule engine | Codebase visualization |
| **Parser engine** | tree-sitter (9+ bahasa) | tree-sitter (4 bahasa: C/C++, Java, Python, Go) | tree-sitter + pfff (40+ bahasa) | pyparsing (12 bahasa) |
| **LLM integration** | ❌ (external via MCP) | ✅ (internal, multi-agent) | ⚠️ (external via Assistant, proprietary) | ❌ |
| **Bug detection** | ⚠️ Generic taint | ✅ NPD/MLK/UAF dengan LLM validate | ✅ Pattern-based, broad | ❌ |
| **False positive handling** | ❌ | ✅ LLM path validator | ⚠️ User-suppress dengan `nosemgrep` | ❌ |
| **Bug explanation** | ❌ | ✅ LLM CoT reasoning | ⚠️ Assistant (proprietary) | ❌ |
| **Triage UI** | ❌ | ✅ Streamlit | ⚠️ Web platform (proprietary) | ❌ |
| **Memory architecture** | ⚠️ 1-tier registry | ✅ 3-tier (syntactic/semantic/report) | ❌ | ⚠️ 2-tier (results + stats) |
| **Parallel execution** | ⚠️ Incremental only | ✅ ThreadPoolExecutor (30 workers) | ✅ Parmap | ⚠️ Sequential |
| **MCP integration** | ✅ (49 tools) | ❌ | ✅ (9 tools + hooks) | ❌ |
| **Visualization** | ❌ | ⚠️ Streamlit (basic) | ⚠️ Web playground | ✅ D3 force-directed |
| **Architecture metrics** | ⚠️ Callgraph, circular | ❌ | ❌ | ✅ Louvain, fan-in/out, TF-IDF |
| **License** | MIT | Purdue Non-Commercial | LGPL-2.1 | MIT |

**Insight strategis:** CodeLens + RepoAudit feature set = **AI-native code auditing** — CodeLens jadi orchestrator (MCP + guard + query-before-write), RepoAudit-style LLM engine jadi analyzer internal. Ini kombinasikan kekuatan external AI agent (flexibility) dengan internal LLM (determinism, cost control).

---

## 6. Appendix — Peta File RepoAudit ke Topik Issue

| Issue | File Referensi RepoAudit (untuk konsep, BUKAN copy) |
|---|---|
| #CL-036 | `src/agent/agent.py` (17 LOC, Agent ABC), `src/agent/dfbscan.py` (711 LOC, composition), `docs/architecture.md` |
| #CL-037 | `src/llmtool/LLM_tool.py` (106 LOC, LLMTool ABC), `src/llmtool/LLM_utils.py:LLM` class |
| #CL-038 | `src/llmtool/dfbscan/intra_dataflow_analyzer.py` (232 LOC), `src/prompt/{Python,Java,Cpp,Go}/dfbscan/intra_dataflow_analyzer.json` |
| #CL-039 | `src/llmtool/dfbscan/path_validator.py` (110 LOC), `src/prompt/{Python,Java,Cpp,Go}/dfbscan/path_validator.json` |
| #CL-040 | `src/tstool/dfbscan_extractor/dfbscan_extractor.py` (80 LOC, ABC), `src/tstool/dfbscan_extractor/{Cpp,Java,Python,Go}/*_extractor.py` (7 files) |
| #CL-041 | `src/memory/syntactic/{function,value,api}.py`, `src/memory/semantic/{state,dfbscan_state,metascan_state}.py`, `src/memory/report/bug_report.py` |
| #CL-042 | `src/llmtool/LLM_tool.py` (cache dict + `input_token_cost`/`output_token_cost`/`total_query_num` fields), `src/llmtool/LLM_utils.py` (tiktoken usage) |
| #CL-043 | `src/llmtool/LLM_utils.py` (368 LOC, 5 provider: `infer_with_openai_model`, `infer_with_claude_key`, `infer_with_claude_aws_bedrock`, `infer_with_gemini`, `infer_with_deepseek_model`) |
| #CL-044 | `src/memory/report/bug_report.py` (66 LOC, `explanation` field + `relevant_functions`), `src/llmtool/dfbscan/path_validator.py:PathValidatorOutput.explanation_str` |
| #CL-045 | `src/ui/web_ui.py` (267 LOC, Streamlit app dengan TP/FP radio + Save + Download) |

---

## 7. Catatan Akhir

### 7.1 ⚠️ Aturan Lisensi — SANGAT PENTING

RepoAudit berlisensi **Purdue Non-Commercial Open Source License**. Ini BUKAN OSI-approved open source license. Key restrictions:

1. **Non-commercial use only** — "It may not be used indirectly for commercial use, such as on a website that accepts advertising money for content."
2. **Same license for derivative works** — "Derivative Works must be released under this same license when distributing."
3. **Attribution required** — "You must cause the source code for any Derivative Works that You create to carry a prominent Attribution Notice."

**Implikasi untuk CodeLens (yang MIT licensed):**

- ❌ **DILARANG copy-paste kode** RepoAudit ke CodeLens source
- ❌ **DILARANG port algoritma literal** (e.g., jangan copy `CallContext.add_and_check_context()` logic verbatim)
- ❌ **DILARANG bundle** file RepoAudit (e.g., prompt JSON) ke CodeLens distribution
- ✅ **BOLEH adaptasi konsep** — reimplementasi dari nol dengan design sendiri
- ✅ **BOLEH sitasi paper** ICML 2025 untuk academic attribution
- ✅ **BOLEH baca source code** untuk inspirasi (fair use untuk understanding)

Semua issue di atas sudah didesain dengan asumsi **reimplementasi dari nol**. Jika ada kontributor yang copy-paste kode RepoAudit, itu akan menjadi **license violation** yang bisa menyebabkan:

- CodeLens ter-contaminate dengan non-commercial restriction
- MIT license CodeLens menjadi invalid
- User komersial CodeLens terkena legal risk

**Mitigation:** Tambahkan checklist di PR template:

> - [ ] Saya tidak copy-paste kode dari RepoAudit (Purdue Non-Commercial License)
> - [ ] Saya hanya adaptasi konsep, reimplementasi dari nol
> - [ ] Saya sitasi paper RepoAudit ICML 2025 jika relevan

### 7.2 Quick Comparison: CodeLens vs RepoAudit (Positioning)

CodeLens dan RepoAudit sebenarnya **bisa saling melengkapi** jika diposisikan dengan benar:

- **RepoAudit** = research-grade bug detector untuk C/C++/Java/Python/Go, fokus NPD/MLK/UAF, non-commercial
- **CodeLens** = production-grade code intelligence untuk AI agent workflow, broad language, MIT licensed

CodeLens bisa **adopt konsep RepoAudit** (LLM-driven analysis) tanpa adopt license-nya. Hasilnya adalah tool yang:

- Punya AI-native positioning (sudah ada)
- Plus LLM-driven bug detection (dari RepoAudit konsep)
- Plus interactive visualization (dari Emerge)
- Plus mature rule engine (dari Semgrep konsep)
- Dengan MIT license (komersial-friendly)

Ini adalah ** diferensiasi yang sulit ditiru** — tidak ada tool lain yang combine keempat aspek ini.

### 7.3 Urutan Rekomendasi Eksekusi

Jika harus memilih **3 issue pertama** untuk mulai minggu depan (quick win + foundation):

1. **#CL-042 LLM Cache + Cost** (1 minggu) — quick win, isolasi di `scripts/llm/cache.py`, tidak butuh agent framework. Foundation untuk semua LLM feature lain.
2. **#CL-043 Multi-Provider LLM** (1 minggu) — quick win, 6 provider, dispatch logic. Bisa test dengan real LLM API.
3. **#CL-045 Triage UI** (1-2 minggu) — quick win, Streamlit, bisa mock finding source. User-facing, langsung visible value.

Setelah 3 quick win, prioritaskan **#CL-036 Agent Abstraction** (1-2 minggu) sebagai foundation untuk semua LLM-driven analysis berikutnya.

Setelah itu, baru masuk ke **#CL-038 Explorer + #CL-039 Validator** (3-5 minggu) yang adalah inti dari RepoAudit-style analysis.

---

**Dokumen ini disusun dari analisa langsung terhadap:**
- `https://github.com/Wolfvin/CodeLens.git` (branch `main`, checkout 2026-06-28)
- `https://github.com/PurCL/RepoAudit.git` (branch `main`, checkout 2026-06-28)
- Paper RepoAudit ICML 2025: "RepoAudit: Automated Code Auditing with Multi-Agent LLM Framework"
- Melengkapi `CodeLens_Upgrade_Issues_from_Semgrep.md` (22 issue) dan `CodeLens_Upgrade_Issues_from_Emerge.md` (13 issue)
