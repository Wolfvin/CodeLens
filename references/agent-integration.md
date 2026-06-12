# Agent Integration Guide — CodeLens v5

Complete guide for integrating CodeLens into AI agent workflows.
Covers: CLI integration, programmatic Python API, JSON output schemas,
decision trees, auto-trigger mapping, error handling, and best practices.

---

## 0. Auto-Activation & Trigger Guide

CodeLens uses **passive integration** — the AI agent decides when to invoke tools
based on user intent. This section maps user intents to the correct CodeLens tools
so the AI can auto-select the right command without manual lookup.

### 0.1 Primary Activation Rules

The AI MUST activate CodeLens in these scenarios:

1. **BEFORE writing any new class/id/function** → Always run `query` first
2. **BEFORE deleting/renaming code** → Always run `refactor-safe` or `impact`
3. **AFTER writing/editing/deleting code** → Always run `scan --incremental`
4. **When user asks about codebase health/quality** → Run relevant analysis tools
5. **When user asks about security** → Run security chain

### 0.2 Intent-to-Tool Quick Map

This is the fastest way for an AI to pick the right tool:

#### Writing Code (MANDATORY — always trigger)

| User Intent | Tool Chain |
|-------------|------------|
| Create new class/id/function | `query` → if not found → write → `scan --incremental` |
| Edit existing code | `query` → `context` → edit → `scan --incremental` → `missing-refs` |
| Delete code | `impact` → delete → `scan --incremental` → `list --filter dead` |

#### Security & Compliance

| User Intent | Tool Chain |
|-------------|------------|
| "Is this secure?" / "security audit" | `secrets` → `dataflow` → `env-check` → `regex-audit` |
| "Find API keys/passwords" | `secrets` |
| "SQL injection?" / "taint analysis" | `dataflow --source user_input --sink db_query` |
| "XSS risk?" | `dataflow --source user_input --sink html_output` |
| "Check env vars" | `env-check` |
| "Regex safe?" / "ReDoS" | `regex-audit` |

#### Codebase Understanding

| User Intent | Tool Chain |
|-------------|------------|
| "How does this app work?" | `entrypoints` → `api-map` → `state-map` → `outline --all` |
| "What endpoints exist?" | `api-map` |
| "Where is global state?" | `state-map` |
| "Who calls this function?" | `trace --direction up` |
| "What does this function call?" | `trace --direction down` |
| "Tell me about this symbol" | `context` |

#### Quality & Production

| User Intent | Tool Chain |
|-------------|------------|
| "Production ready?" | `smell` → `complexity` → `debug-leak` → `dead-code` → `a11y` → `secrets` |
| "What to refactor?" | `smell` → `complexity --threshold 15` |
| "Find debug code" / "console.log" | `debug-leak` |
| "Dead code?" / "unused code" | `dead-code` + `list --filter dead` |
| "Accessible?" / "a11y" / "WCAG" | `a11y` |
| "Too complex" | `complexity` |

#### Refactoring

| User Intent | Tool Chain |
|-------------|------------|
| "Safe to rename?" | `refactor-safe` → `impact` → `test-map` |
| "Safe to delete?" | `impact` → `dead-code` |
| "What's the impact?" | `impact` |
| "Pure function?" | `side-effect` |
| "Who owns this?" | `ownership` |
| "Is it tested?" | `test-map` |

#### Pre-Deploy

| User Intent | Tool Chain |
|-------------|------------|
| "Ready to deploy?" / "pre-deploy check" | `secrets` → `debug-leak` → `env-check` → `config-drift` → `dead-code` |

### 0.3 Keyword Detection Matrix

When the AI detects these keywords in user messages, it should activate the
corresponding CodeLens tools:

| Keywords (EN) | Keywords (ID) | Tool |
|---------------|---------------|------|
| exists, already, check if, does this | sudah ada, apakah | `query` |
| who uses, who calls, references | siapa pakai, siapa panggil | `trace` / `query` |
| delete, remove, hapus | hapus, buang | `impact` + `dead-code` |
| rename, move, refactor | ubah nama, pindah | `refactor-safe` + `impact` |
| secure, security, vulnerability | aman, keamanan, celah | `secrets` + `dataflow` |
| API key, password, token, secret | kunci, sandi, rahasia | `secrets` |
| entry point, main, start | mulai, awal, titik masuk | `entrypoints` |
| endpoint, route, API | titik akhir, rute | `api-map` |
| state, Redux, Context, Zustand | keadaan, state global | `state-map` |
| env, environment variable, config | variabel lingkungan, konfigurasi | `env-check` |
| console.log, print, debugger, debug | debug, cetak | `debug-leak` |
| complex, complexity, cyclomatic | rumit, kompleks | `complexity` |
| regex, pattern, ReDoS | pola, regex | `regex-audit` |
| accessibility, a11y, WCAG, ARIA | aksesibilitas | `a11y` |
| smell, debt, quality | bau kode, kualitas | `smell` |
| test, coverage, untested | uji, cakupan, belum ditest | `test-map` |
| dead code, unused, zombie | kode mati, tidak dipakai | `dead-code` |
| deploy, production, release | terap, produksi, rilis | Full quality gate chain |
| slow, performance, bottleneck | lambat, kinerja | `complexity` + `side-effect` + `circular` + `state-map` |

### 0.4 Context-Aware Trigger Hints

The AI should automatically handle these scenarios without user intervention:

**Auto-Init Pattern**: If the user asks a codebase question and no `.codelens/` directory exists:
1. Run `init` → `scan` automatically (don't ask the user)
2. Then proceed with the requested tool
3. Inform the user: "Initialized CodeLens registry for this workspace"

**Re-Scan if Stale Pattern**: If the registry was last updated >24 hours ago:
1. Run `scan --incremental` automatically
2. Then proceed with the requested tool
3. Inform the user: "Registry was stale, re-scanned before analysis"

**Post-Write Auto-Scan Pattern**: After any code modification:
1. Always run `scan --incremental` to update the registry
2. Then optionally run `list --filter dead` to check for new dead code
3. This is NOT optional — stale registry = wrong analysis results

### 0.5 Colloquial Trigger Phrases

Users often express codebase concerns using informal language. Map these to CodeLens tools:

| Phrase (English) | Phrase (Indonesian) | Tool Chain |
|-------------------|---------------------|------------|
| "this is slow" / "why so slow" / "takes forever" | "kok lama ya" / "kenapa lama" | `perf-hint` → `complexity` → `circular` |
| "something's weird" / "this is broken" | "aneh nih" / "kok error" | `search` → `context` → `trace` → `missing-refs` |
| "help me check" / "give it a look" | "bantu cek" / "tolong cek" | `smell` → `dead-code` → `secrets` |
| "clean this up" / "tidy up" | "bersihkan" / "rapikan" | `debug-leak` → `dead-code` → `smell` |
| "is this safe?" / "can I deploy?" | "aman ga" / "bisa deploy ga" | `secrets` → `vuln-scan` → `debug-leak` → `env-check` |
| "make it faster" / "optimize" | "percepat" / "optimasi" | `perf-hint` → `complexity` → `circular` |
| "the CSS is messy" / "style issues" | "CSS berantakan" | `css-deep` → `missing-refs` → `list --filter duplicate_define` |
| "vulnerable?" / "CVE?" / "security hole?" | "rentan?" / "celah?" | `vuln-scan` → `secrets` → `dataflow` → `env-check` |

### 0.6 Negative Triggers — When NOT to Activate CodeLens

Do NOT activate CodeLens for these tasks:

| User Intent | Keywords | Action |
|-------------|----------|--------|
| Document generation | "generate PDF", "create report", "write document" | SKIP CodeLens entirely |
| Image/media generation | "generate image", "create artwork", "make logo" | SKIP CodeLens entirely |
| Web search | "search the web", "find online", "look up" | SKIP CodeLens entirely |
| Knowledge questions | "what is React", "explain SQL", "how does X work" | SKIP CodeLens entirely |
| Non-code file editing | "edit config", "write markdown", "update YAML" | SKIP CodeLens (unless checking existing code references) |
| UI/UX design | "design layout", "create mockup", "wireframe" | SKIP CodeLens (unless verifying existing component names) |

**Rule**: If the task does not involve reading, writing, editing, or analyzing source code in the workspace, CodeLens is not needed. Activating it unnecessarily wastes tokens and time.

### 0.7 Default Fallback Chains

When a user's request is vague and doesn't clearly map to a specific tool, use these default chains:

| Vague Request Pattern | Default Chain | Rationale |
|-----------------------|---------------|-----------|
| General "check" / "review" / "analyze" | `smell` → `dead-code` → `secrets` | Broad quality + security baseline |
| Security-adjacent ("safe?", "secure?", "risk?") | `secrets` → `dataflow` → `env-check` → `vuln-scan` | Full security audit |
| Quality-adjacent ("good?", "clean?", "ready?") | `complexity` → `debug-leak` → `a11y` → `smell` | Quality gate |
| Performance-adjacent ("slow?", "fast?", "optimize?") | `perf-hint` → `complexity` → `circular` | Performance bottleneck hunt |
| CSS-adjacent ("style?", "layout?", "CSS?") | `css-deep` → `missing-refs` → `list --filter duplicate_define` | CSS health check |
| Pre-deploy ("deploy?", "ship?", "release?") | `secrets` → `debug-leak` → `env-check` → `config-drift` → `vuln-scan` → `dead-code` | Full pre-deploy gate |

---

## 1. Integration Overview

CodeLens is designed for **passive integration** — the AI agent calls
CodeLens manually via CLI or Python API when needed.
No auto-triggers or hooks need to be registered.

### Integration Methods

| Method | Best For | Latency | Complexity |
|--------|----------|---------|------------|
| **CLI (subprocess)** | Generic AI agents, shell-based tools | ~200-500ms per call | Low |
| **Python API (import)** | Python-based agents, in-process | ~50-100ms per call | Medium |
| **JSON file read** | Read-only agents, dashboards | ~1ms (file read) | Very Low |

### When to Use Which

- **CLI**: When the agent runs in a separate process, or the agent is not Python-based
  (Node.js agents can call `child_process.exec`)
- **Python API**: When the agent runs in the same Python process,
  or needs fine-grained control over parsing
- **JSON file read**: When the agent only needs to read the registry without triggering a scan,
  for example for dashboard or report generation

---

## 2. CLI Integration

### 2.1 Basic Pattern

Every AI agent integrating CodeLens must follow this pattern:

```
1. SETUP:     codelens init <workspace>          (once only)
2. SCAN:      codelens scan <workspace>           (before starting work)
3. QUERY:     codelens query <name> <workspace>   (before create/edit/delete)
4. RE-SCAN:   codelens scan <workspace> --incremental  (after finishing edits)
5. AUDIT:     codelens list <workspace> --filter dead  (optional, for reporting)
```

### 2.2 Environment Setup

The agent must set the environment variable `CODELENS_DIR` before calling the CLI:

```bash
# In the agent's setup/init phase
export CODELENS_DIR="/path/to/codelens"
```

Or use the full path directly:

```bash
python3 /path/to/codelens/scripts/codelens.py <command> <args>
```

### 2.3 Calling from Agent Code

#### Python Agent

```python
import subprocess
import json

CODELENS_DIR = "/path/to/codelens"
CODELENS_CLI = f"{CODELENS_DIR}/scripts/codelens.py"

def codelens_scan(workspace: str, incremental: bool = False) -> dict:
    """Run CodeLens scan and return parsed JSON result."""
    cmd = ["python3", CODELENS_CLI, "scan", workspace]
    if incremental:
        cmd.append("--incremental")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return {"status": "error", "message": result.stderr}
    return json.loads(result.stdout)

def codelens_query(name: str, workspace: str, domain: str = None) -> dict:
    """Query a specific class/id/function."""
    cmd = ["python3", CODELENS_CLI, "query", name, workspace]
    if domain:
        cmd.extend(["--domain", domain])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return {"status": "error", "message": result.stderr}
    return json.loads(result.stdout)

def codelens_list(workspace: str, domain: str = "all", filter_type: str = "all") -> dict:
    """List entries with optional filter."""
    cmd = ["python3", CODELENS_CLI, "list", workspace,
           "--domain", domain, "--filter", filter_type]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return {"status": "error", "message": result.stderr}
    return json.loads(result.stdout)
```

#### Node.js Agent

```javascript
const { execSync } = require('child_process');

const CODELENS_DIR = '/path/to/codelens';
const CODELENS_CLI = `${CODELENS_DIR}/scripts/codelens.py`;

function codelensScan(workspace, incremental = false) {
  let cmd = `python3 ${CODELENS_CLI} scan ${workspace}`;
  if (incremental) cmd += ' --incremental';
  const output = execSync(cmd, { timeout: 60000, encoding: 'utf8' });
  return JSON.parse(output);
}

function codelensQuery(name, workspace, domain = null) {
  let cmd = `python3 ${CODELENS_CLI} query "${name}" ${workspace}`;
  if (domain) cmd += ` --domain ${domain}`;
  const output = execSync(cmd, { timeout: 30000, encoding: 'utf8' });
  return JSON.parse(output);
}

function codelensList(workspace, domain = 'all', filterType = 'all') {
  const cmd = `python3 ${CODELENS_CLI} list ${workspace} --domain ${domain} --filter ${filterType}`;
  const output = execSync(cmd, { timeout: 30000, encoding: 'utf8' });
  return JSON.parse(output);
}
```

### 2.4 Timeout Guidelines

| Command | Recommended Timeout | Max Timeout |
|---------|-------------------|-------------|
| `init` | 10s | 30s |
| `scan` (full) | 60s | 300s |
| `scan --incremental` | 15s | 60s |
| `query` | 10s | 30s |
| `list` | 10s | 30s |
| `detect` | 15s | 60s |

---

## 3. Python API Integration (Direct Import)

For Python-based agents, importing CodeLens modules directly is more efficient
than subprocess calls.

### 3.1 Setup

```python
import sys
import os

# Add CodeLens scripts to Python path
CODELENS_DIR = "/path/to/codelens"
sys.path.insert(0, os.path.join(CODELENS_DIR, "scripts"))

# Now import CodeLens modules
from registry import (
    load_config, save_config, ensure_codelens_dir,
    load_frontend_registry, load_backend_registry,
    build_frontend_registry, compute_frontend_status
)
from codelens import cmd_scan, cmd_query, cmd_list, cmd_init, cmd_detect
from edge_resolver import get_callers, get_callees
from framework_detect import detect_frameworks
```

### 3.2 Direct Command Calls

```python
# Initialize workspace (run once)
result = cmd_init("/path/to/workspace")
# result = {"status": "ok", "codelens_dir": "...", "config": {...}}

# Full scan
result = cmd_scan("/path/to/workspace")
# result = {"status": "ok", "files_scanned": {...}, "frontend": {...}, "backend": {...}}

# Incremental scan (only changed files)
result = cmd_scan("/path/to/workspace", incremental=True)

# Query before writing new code
result = cmd_query("btn-primary", "/path/to/workspace")
# result = {"found": true/false, "type": "class", ...}

# Query with domain filter
result = cmd_query("verify_token", "/path/to/workspace", domain="backend")

# List all dead code
result = cmd_list("/path/to/workspace", domain="all", filter_type="dead")
```

### 3.3 Low-Level Registry Access

For agents that need direct access to registry data without going through the command layer:

```python
from registry import load_frontend_registry, load_backend_registry

# Read frontend registry (no scan needed if already exists)
frontend = load_frontend_registry("/path/to/workspace")

# Access classes
for cls in frontend["classes"]:
    print(f"Class: {cls['name']}, Status: {cls['status']}, Refs: {cls['ref_count']}")

# Access IDs
for id_entry in frontend["ids"]:
    print(f"ID: {id_entry['name']}, Status: {id_entry['status']}")

# Read backend registry
backend = load_backend_registry("/path/to/workspace")

# Access function nodes
for node in backend["nodes"]:
    print(f"Function: {node['fn']}, Status: {node.get('status')}, File: {node.get('file')}")

# Access call graph edges
for edge in backend["edges"]:
    print(f"Edge: {edge.get('from')} -> {edge.get('to', edge.get('to_fn', '?'))}")
```

### 3.4 Custom Parsing (Advanced)

For agents that need to parse individual files without a full scan:

```python
from grammar_loader import get_grammar_loader

loader = get_grammar_loader()

# Parse a single HTML file
lang = loader.get_language('html')
parser = loader.get_parser('html')
if parser:
    from parsers.html_parser import HTMLParser
    html_parser = HTMLParser()
    with open('page.html', 'r') as f:
        content = f.read()
    refs = html_parser.extract_references(content, 'page.html')
    # refs = {"classes": [...], "ids": [...]}

# Parse a single Rust file
lang = loader.get_language('rust')
if lang:
    from parsers.rust_parser import RustParser
    rust_parser = RustParser()
    with open('main.rs', 'r') as f:
        content = f.read()
    refs = rust_parser.extract_references(content, 'main.rs')
    # refs = {"nodes": [...], "edges": [...]}
```

---

## 4. JSON Output Schemas

Complete output format documentation for each command, so the agent can
parse and make decisions programmatically.

### 4.1 `scan` Output

```json
{
  "status": "ok",
  "workspace": "/abs/path/to/workspace",
  "files_scanned": {
    "html": 5,
    "css": 3,
    "js_frontend": 4,
    "js_backend": 2,
    "tsx": 8,
    "rust": 3,
    "vue": 2,
    "svelte": 0
  },
  "frontend": {
    "classes": 24,
    "ids": 7
  },
  "backend": {
    "nodes": 31,
    "edges": 42
  },
  "frameworks": ["react", "tailwind"],
  "incremental": false
}
```

**Fields:**
- `status`: `"ok"` on success, `"error"` on failure
- `files_scanned`: count per file type
- `frontend.classes/ids`: total unique class/id entries in registry
- `backend.nodes/edges`: total function nodes and call edges
- `frameworks`: list of detected framework names
- `incremental`: whether this was an incremental scan

### 4.2 `query` Output — Frontend (found)

```json
{
  "found": true,
  "type": "class",
  "domain": "frontend",
  "name": "btn-primary",
  "ref_count": 3,
  "status": "active",
  "css": [
    {"path": "src/styles/buttons.css", "line": 42, "flag": null},
    {"path": "src/styles/buttons.css", "line": 78, "flag": "duplicate_define"}
  ],
  "js": [
    {"path": "src/components/Form.tsx", "line": 15, "flag": null, "source": "jsx_classname"}
  ]
}
```

**Frontend fields:**
- `type`: `"class"` or `"id"`
- `status`: `"active"`, `"dead"`, `"duplicate_ref"`, `"collision"`
- `css`: array of CSS file references (definition + usage)
- `js`: array of JS/TSX file references (usage via className, querySelector, etc.)
- Each ref has: `path`, `line`, `flag` (null or `"duplicate_define"`), optional `source`

### 4.3 `query` Output — Frontend ID (found)

```json
{
  "found": true,
  "type": "id",
  "domain": "frontend",
  "name": "modal-root",
  "ref_count": 2,
  "status": "active",
  "defined_in_html": [
    {"path": "src/index.html", "line": 12, "flag": null}
  ],
  "css": [
    {"path": "src/styles/modal.css", "line": 5, "flag": null}
  ],
  "js": [
    {"path": "src/hooks/useModal.ts", "line": 8, "flag": null}
  ]
}
```

**ID-specific fields:**
- `defined_in_html`: where the id is defined in HTML (the source of truth)
- If `defined_in_html` has >1 entry → `status: "collision"` (BUG)

### 4.4 `query` Output — Backend (found)

```json
{
  "found": true,
  "type": "function",
  "domain": "backend",
  "node": {
    "id": "src/utils/auth.rs:verify_token:15",
    "fn": "verify_token",
    "ref_count": 3,
    "status": "active",
    "file": "src/utils/auth.rs",
    "line": 15,
    "async": false,
    "impl_for": "AuthService",
    "duplicate_define": false
  },
  "callers": [
    {"from": "src/api/handlers.rs:login:42"},
    {"from": "src/api/handlers.rs:refresh:67"},
    {"from": "src/middleware/auth.rs:check:23"}
  ],
  "callees": [
    {"to": "src/utils/auth.rs:decode_jwt:30", "fn": "decode_jwt", "status": "active"}
  ]
}
```

**Backend fields:**
- `node.id`: unique identifier format `{file}:{fn}:{line}`
- `node.status`: `"active"` or `"dead"`
- `node.async`: whether function is async
- `node.impl_for`: Rust — which struct this method belongs to (if any)
- `node.trait_name`: Rust — which trait this implements (if any)
- `node.component`: TSX — whether this is a React component (PascalCase)
- `node.duplicate_define`: same fn name in multiple files
- `callers`: who calls this function (incoming edges)
- `callees`: what this function calls (outgoing edges)

### 4.5 `query` Output — Not Found

```json
{
  "found": false,
  "query": "new-feature-btn",
  "domain": "auto"
}
```

### 4.6 `list` Output

```json
{
  "domain": "all",
  "filter": "dead",
  "count": 7,
  "results": [
    {
      "type": "class",
      "name": "legacy-sidebar",
      "ref_count": 0,
      "status": "dead",
      "defined_in": "src/styles/layout.css:120"
    },
    {
      "type": "function",
      "name": "old_validator",
      "ref_count": 0,
      "status": "dead",
      "defined_in": "src/utils/validation.rs:45"
    }
  ]
}
```

### 4.7 `init` Output

```json
{
  "status": "ok",
  "workspace": "/abs/path/to/workspace",
  "codelens_dir": "/abs/path/to/workspace/.codelens",
  "config": {
    "frontend_paths": ["src/app/", "src/components/", ...],
    "backend_paths": ["app/api/", "src/server/", ...],
    "frameworks": ["react", "next.js", "tailwind"],
    "jsx_mode": true,
    "vue_mode": false,
    "svelte_mode": false,
    "tailwind_mode": true,
    "css_preprocessor": null,
    "ignore": ["node_modules/", "dist/", ".git/", ...]
  }
}
```

### 4.8 `detect` Output

```json
{
  "frameworks": ["react", "next.js", "tailwind"],
  "has_react": true,
  "has_vue": false,
  "has_svelte": false,
  "has_tailwind": true,
  "has_nextjs": true,
  "has_angular": false,
  "css_preprocessor": null,
  "module_system": "esm"
}
```

---

## 5. Agent Decision Trees

### 5.1 Pre-Write Decision Tree (Most Important)

Call **before** writing a new class/id/function:

```
codelens_query(name, workspace)
          │
          ▼
    found: false ──────────────► SAFE. Create new.
          │
    found: true
          │
          ├── status: "active"
          │       │
          │       ├── type: "class" ──► EXTEND existing. Don't overwrite.
          │       │                    Read css[] + js[] to understand
          │       │                    existing logic before editing.
          │       │
          │       ├── type: "id" ─────► EXTEND or REUSE. Read defined_in_html[]
          │       │                     to see where it's used.
          │       │
          │       └── type: "function" ──► LIST all callers[] first.
          │                              Changes impact multiple files.
          │
          ├── status: "dead"
          │       │
          │       └──► ASK USER: "This exists but is unused. Reuse or delete?"
          │           If reuse → extend carefully.
          │           If delete → remove, then create fresh.
          │
          ├── status: "duplicate_ref"
          │       │
          │       └──► WARNING: Used from multiple files.
          │           List all referrers to user before editing.
          │           Changes have wide impact.
          │
          └── status: "collision"
                  │
                  └──► STOP. This is an active bug.
                      Report to user immediately:
                      "ID '{name}' is used in {count} HTML elements.
                       This violates HTML spec. Fix first."
                      Do NOT proceed until fixed.
```

### 5.2 Post-Write Decision Tree

Call **after** writing/editing/deleting code:

```
codelens_scan(workspace, incremental=True)
          │
          ▼
    Check result.frontend.classes count changed?
          │
    Check result.backend.nodes count changed?
          │
          ▼
    codelens_list(workspace, domain="all", filter="dead")
          │
          ▼
    Any new dead code? ──► Report to user:
      "After your changes, these are now unused: ..."
      Suggest cleanup or flag for next sprint.
```

### 5.3 Refactoring Decision Tree

For agents performing refactoring:

```
1. codelens_list(workspace, "all", "dead")
   → Candidate list for removal

2. For each dead function:
   codelens_query(fn_name, workspace, domain="backend")
   → Confirm ref_count is still 0
   → Check if it's exported (might be used externally)

3. For each dead class/id:
   codelens_query(name, workspace, domain="frontend")
   → Check css[] and js[] to confirm no references
   → Check for dynamic references that tree-sitter might miss

4. After removal:
   codelens_scan(workspace, incremental=True)
   → Verify no new dead code introduced
   → Verify no collision introduced
```

---

## 6. Integration Patterns by Agent Type

### 6.1 Code Editor Agent (writes code)

**Trigger:** Every time the agent is about to write a new class, id, or function.

```python
class CodeEditorWithCodeLens:
    def __init__(self, workspace):
        self.workspace = workspace
        self._ensure_scanned()

    def _ensure_scanned(self):
        """Ensure registry exists before any operations."""
        import os
        codelens_dir = os.path.join(self.workspace, '.codelens')
        if not os.path.exists(os.path.join(codelens_dir, 'frontend.json')):
            cmd_init(self.workspace)
            cmd_scan(self.workspace)

    def before_write_class(self, class_name, content):
        """Check before writing a new CSS class."""
        result = cmd_query(class_name, self.workspace)
        if result["found"]:
            if result["status"] == "collision":
                raise CollisionError(f"ID collision: {class_name}")
            elif result["status"] == "active":
                print(f"[CodeLens] Class '{class_name}' already exists. Extending.")
                return "extend"
            elif result["status"] == "dead":
                print(f"[CodeLens] Class '{class_name}' exists but unused.")
                return "ask_user"
        return "create_new"

    def after_write(self):
        """Re-scan after modifications."""
        cmd_scan(self.workspace, incremental=True)
        # Check for new dead code
        dead = cmd_list(self.workspace, domain="all", filter_type="dead")
        if dead["count"] > 0:
            print(f"[CodeLens] Warning: {dead['count']} dead entries detected.")
```

### 6.2 Code Review Agent (reads code, suggests changes)

**Trigger:** When reviewing PRs or code changes.

```python
class CodeReviewerWithCodeLens:
    def __init__(self, workspace):
        self.workspace = workspace

    def review_changes(self, changed_files):
        """Review a set of changed files for CodeLens issues."""
        issues = []

        # Re-scan to get latest state
        cmd_scan(self.workspace, incremental=True)

        # Check for collisions
        collisions = cmd_list(self.workspace, domain="frontend", filter_type="collision")
        for item in collisions["results"]:
            issues.append({
                "severity": "critical",
                "type": "collision",
                "message": f"ID '{item['name']}' used in multiple HTML elements",
                "location": item.get("defined_in", "unknown")
            })

        # Check for new dead code
        dead = cmd_list(self.workspace, domain="all", filter_type="dead")
        for item in dead["results"]:
            issues.append({
                "severity": "warning",
                "type": "dead_code",
                "message": f"{item['type']} '{item['name']}' is unused (ref_count=0)",
                "location": item.get("defined_in", "unknown")
            })

        # Check for duplicate definitions
        dupes = cmd_list(self.workspace, domain="all", filter_type="duplicate_define")
        for item in dupes["results"]:
            issues.append({
                "severity": "warning",
                "type": "duplicate_define",
                "message": f"{item['type']} '{item['name']}' defined multiple times",
                "location": item.get("defined_in", "unknown")
            })

        return issues
```

### 6.3 Refactoring Agent (modifies existing code structure)

**Trigger:** When performing renames, moves, or deletions.

```python
class RefactoringWithCodeLens:
    def __init__(self, workspace):
        self.workspace = workspace

    def safe_rename_function(self, old_name, new_name):
        """Safely rename a function across the codebase."""
        # 1. Query the old name
        result = cmd_query(old_name, self.workspace, domain="backend")
        if not result["found"]:
            raise ValueError(f"Function '{old_name}' not found")

        # 2. Check if new name conflicts
        new_check = cmd_query(new_name, self.workspace, domain="backend")
        if new_check["found"]:
            raise ValueError(f"Name '{new_name}' already exists!")

        # 3. Get all callers — these need updating
        callers = result.get("callers", [])
        callees = result.get("callees", [])

        return {
            "action": "rename",
            "from": old_name,
            "to": new_name,
            "files_to_update": [c["from"].rsplit(":", 2)[0] for c in callers],
            "caller_count": len(callers),
            "is_async": result["node"].get("async", False)
        }

    def safe_delete_function(self, fn_name):
        """Safely delete a function (only if dead)."""
        result = cmd_query(fn_name, self.workspace, domain="backend")
        if not result["found"]:
            raise ValueError(f"Function '{fn_name}' not found")

        if result["node"]["status"] != "dead":
            callers = result.get("callers", [])
            if callers:
                raise ValueError(
                    f"Cannot delete '{fn_name}': still called from {len(callers)} locations"
                )

        return {
            "action": "delete",
            "target": fn_name,
            "safe": True,
            "file": result["node"]["file"],
            "line": result["node"]["line"]
        }

    def after_refactor(self):
        """Verify codebase health after refactoring."""
        cmd_scan(self.workspace, incremental=True)
        return {
            "dead_code": cmd_list(self.workspace, domain="all", filter_type="dead"),
            "collisions": cmd_list(self.workspace, domain="frontend", filter_type="collision"),
            "duplicates": cmd_list(self.workspace, domain="all", filter_type="duplicate_define")
        }
```

### 6.4 Documentation Agent (generates docs from code)

**Trigger:** When generating API docs, style guides, or architecture docs.

```python
class DocGeneratorWithCodeLens:
    def __init__(self, workspace):
        self.workspace = workspace

    def generate_css_docs(self):
        """Generate CSS class documentation from registry."""
        frontend = load_frontend_registry(self.workspace)

        docs = []
        for cls in frontend["classes"]:
            entry = {
                "name": cls["name"],
                "status": cls["status"],
                "defined_in": [f"{r['path']}:{r['line']}" for r in cls.get("css", [])],
                "used_in": [f"{r['path']}:{r['line']}" for r in cls.get("js", [])],
                "total_references": cls["ref_count"]
            }
            if cls["status"] == "dead":
                entry["note"] = "UNUSED — candidate for removal"
            docs.append(entry)

        return docs

    def generate_api_docs(self):
        """Generate function API documentation from registry."""
        backend = load_backend_registry(self.workspace)

        docs = []
        for node in backend["nodes"]:
            callers = get_callers(node["id"], backend["edges"])
            callees = get_callees(node["id"], backend["edges"], backend["nodes"])

            entry = {
                "name": node["fn"],
                "file": node.get("file", ""),
                "line": node.get("line", 0),
                "is_async": node.get("async", False),
                "status": node.get("status", "active"),
                "callers_count": len(callers),
                "callees": [c.get("fn", c.get("to_fn", "?")) for c in callees]
            }

            if node.get("impl_for"):
                entry["method_of"] = node["impl_for"]
            if node.get("trait_name"):
                entry["implements_trait"] = node["trait_name"]
            if node.get("component"):
                entry["is_react_component"] = True

            docs.append(entry)

        return docs
```

---

## 7. Error Handling Guide

### 7.1 Common Error Scenarios

| Error | Cause | Recovery |
|-------|-------|----------|
| Registry not found | No scan has been run | Run `cmd_init()` + `cmd_scan()` first |
| Grammar not available | tree-sitter-X package missing | Falls back to regex parser automatically |
| Subprocess timeout | Very large workspace | Use `--incremental` scan, increase timeout |
| JSON parse error | Corrupted registry file | Delete `.codelens/` directory, re-scan |
| ImportError | Module path not set | Add `scripts/` to `sys.path` |

### 7.2 Graceful Degradation

CodeLens is designed for graceful degradation — if a tree-sitter grammar
is not available, it automatically falls back to the regex parser. The agent does not need
to handle this manually.

```python
def safe_codelens_query(name, workspace):
    """Query with error handling and fallback."""
    try:
        result = cmd_query(name, workspace)
        return result
    except FileNotFoundError:
        # Registry doesn't exist yet — initialize and retry
        cmd_init(workspace)
        cmd_scan(workspace)
        return cmd_query(name, workspace)
    except Exception as e:
        # Unexpected error — log and continue without CodeLens
        print(f"[CodeLens] Warning: query failed: {e}")
        return {"found": False, "query": name, "error": str(e)}
```

### 7.3 Registry Staleness Detection

The agent can check whether the registry may be outdated:

```python
import os
from datetime import datetime, timezone, timedelta

def is_registry_stale(workspace, max_age_hours=24):
    """Check if registry hasn't been updated in a while."""
    frontend_path = os.path.join(workspace, '.codelens', 'frontend.json')
    if not os.path.exists(frontend_path):
        return True  # No registry at all

    mtime = os.path.getmtime(frontend_path)
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(mtime, timezone.utc)
    return age > timedelta(hours=max_age_hours)
```

---

## 8. Best Practices

### 8.1 Scan Frequency

- **Full scan**: Once per session start, or when workspace structure changes significantly
- **Incremental scan**: After every code modification
- **Never skip scan**: Before critical operations (query, list), ensure registry is fresh

### 8.2 Query Before Write — Always

```
❌ BAD:  Write new class "btn-primary" → Later discover it already exists
✅ GOOD: Query "btn-primary" → Found active → Extend instead of overwrite
```

### 8.3 Report Issues to User

The agent must always report CodeLens findings to the user, rather than silently skipping them:

```python
# ❌ BAD: silently ignore collision
if result["status"] == "collision":
    pass  # Skip silently

# ✅ GOOD: report to user
if result["status"] == "collision":
    return "BLOCKED: ID collision detected. Fix before proceeding."
```

### 8.4 Respect Domain Boundaries

- Frontend queries: `--domain frontend` for class/id checks
- Backend queries: `--domain backend` for function checks
- Omit domain only when unsure — auto-detect searches both

### 8.5 Handle Incremental Correctly

```python
# ❌ BAD: always full scan
cmd_scan(workspace)

# ✅ GOOD: incremental when possible
cmd_scan(workspace, incremental=True)

# ✅ GOOD: full scan when structure changes
if structure_changed:  # new files, deleted files, renamed directories
    cmd_scan(workspace, incremental=False)
else:
    cmd_scan(workspace, incremental=True)
```

### 8.6 Don't Over-Scan

Don't trigger scans too frequently. Recommended cadence:
- After init: 1 full scan
- After each edit batch: 1 incremental scan
- Before commit/PR: 1 incremental scan + list dead code
- Never: scan in a loop without changes

---

## 9. Workflow Integration Examples

### 9.1 Full Feature Development Workflow

```
Step 1: User asks to add a new "modal" feature
          │
          ▼
Step 2: codelens_query("modal", workspace)
          │
          ├── found: true + active ──► "Modal already exists. Extending..."
          │   Read existing css[] + js[] to understand current implementation
          │
          └── found: false ──► "Safe to create new modal component"
          │
          ▼
Step 3: Write the new modal code
          │
          ▼
Step 4: codelens_scan(workspace, incremental=True)
          │
          ▼
Step 5: codelens_query("modal", workspace)  ← verify registration
          │
          ▼
Step 6: codelens_list(workspace, "all", "dead")  ← check for orphans
          │
          ▼
Step 7: Report to user:
        "Modal feature added. Registry updated.
         0 new dead code entries detected."
```

### 9.2 Bug Fix Workflow (Collision)

```
Step 1: codelens_query("submit-btn", workspace)
          │
          ▼
Step 2: found: true + status: "collision"
          │
          ▼
Step 3: REPORT to user:
        "BUG DETECTED: ID 'submit-btn' is used in 2 HTML elements:
         - src/index.html:15
         - src/components/Form.html:8
         This violates HTML spec. Fix required."
          │
          ▼
Step 4: WAIT for user to confirm fix
          │
          ▼
Step 5: After fix → codelens_scan(workspace, incremental=True)
          │
          ▼
Step 6: codelens_query("submit-btn", workspace)
        Verify status changed from "collision" to "active"
```

### 9.3 Dead Code Cleanup Workflow

```
Step 1: codelens_list(workspace, "all", "dead")
          │
          ▼
Step 2: Present dead code list to user:
        "Found 5 unused entries:
         - class 'legacy-sidebar' (src/styles/layout.css:120)
         - function 'old_validator' (src/utils/validation.rs:45)
         - id 'deprecated-modal' (src/index.html:67)
         ..."
          │
          ▼
Step 3: User selects which to remove
          │
          ▼
Step 4: For each removal:
        a. codelens_query(name) → confirm still dead
        b. Remove the code
        c. codelens_scan(workspace, incremental=True)
          │
          ▼
Step 5: Final audit:
        codelens_list(workspace, "all", "dead")
        "After cleanup: 0 dead entries remaining."
```

---

## 10. Programmatic Registry File Access

For agents that only need to read data without running a scan:

### 10.1 File Locations

```
workspace/
  .codelens/
    codelens.config.json    ← Configuration
    frontend.json           ← Frontend registry (classes + ids)
    backend.json            ← Backend registry (nodes + edges)
    mtimes.json             ← File modification times cache
```

### 10.2 Direct File Read (Fastest, No Python Dependency)

```python
import json
import os

def read_registry_fast(workspace):
    """Read registry directly from JSON files. No scan, no imports."""
    result = {"frontend": None, "backend": None, "config": None}

    codelens_dir = os.path.join(workspace, '.codelens')

    frontend_path = os.path.join(codelens_dir, 'frontend.json')
    if os.path.exists(frontend_path):
        with open(frontend_path, 'r') as f:
            result["frontend"] = json.load(f)

    backend_path = os.path.join(codelens_dir, 'backend.json')
    if os.path.exists(backend_path):
        with open(backend_path, 'r') as f:
            result["backend"] = json.load(f)

    config_path = os.path.join(codelens_dir, 'codelens.config.json')
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            result["config"] = json.load(f)

    return result
```

### 10.3 Quick Lookup Without CLI

```python
def quick_lookup(workspace, name):
    """Look up a class/id/function directly from JSON. No CLI needed."""
    data = read_registry_fast(workspace)
    results = []

    # Search frontend
    if data["frontend"]:
        for cls in data["frontend"].get("classes", []):
            if cls["name"] == name:
                results.append({"domain": "frontend", "type": "class", **cls})
        for id_entry in data["frontend"].get("ids", []):
            if id_entry["name"] == name:
                results.append({"domain": "frontend", "type": "id", **id_entry})

    # Search backend
    if data["backend"]:
        for node in data["backend"].get("nodes", []):
            if node["fn"] == name:
                results.append({"domain": "backend", "type": "function", **node})

    return results
```

---

## 11. Multi-Agent Coordination

When multiple AI agents work in the same workspace:

### 11.1 Registry Locking

CodeLens does not have built-in locking. For multi-agent setups:
- Ensure only 1 agent runs `scan` at the same time
- Use file locking or a coordination mechanism if needed

### 11.2 Shared Registry

```
Agent A writes code → Agent A runs incremental scan → Registry updated
                                                     ↓
Agent B reads registry → Agent B sees Agent A's changes
```

### 11.3 Recommended Pattern

```python
import fcntl  # Unix file locking

def locked_scan(workspace, incremental=True):
    """Scan with file lock to prevent concurrent writes."""
    lock_path = os.path.join(workspace, '.codelens', '.scan.lock')
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)

    with open(lock_path, 'w') as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX)  # Exclusive lock
            result = cmd_scan(workspace, incremental=incremental)
            return result
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)  # Release lock
```

---

## 12. Integration Checklist

Before integrating CodeLens into an agent, ensure:

- [ ] **Setup**: `setup.sh` has been run, tree-sitter grammars are installed
- [ ] **Init**: `codelens init <workspace>` has been run once
- [ ] **Scan**: Full scan has been run at least once
- [ ] **Query before write**: Agent always queries before creating a new class/id/function
- [ ] **Post-write scan**: Agent runs an incremental scan after modifications
- [ ] **Collision handling**: Agent stops and reports when it finds a collision
- [ ] **Dead code reporting**: Agent reports dead code to the user, rather than silently ignoring
- [ ] **Error handling**: Agent handles ImportError and FileNotFoundError gracefully
- [ ] **Timeout**: Agent sets appropriate timeouts for each command
- [ ] **Domain awareness**: Agent uses the `--domain` filter when querying

---

## 13. Error Recovery Guide

When a CodeLens command fails, follow these recovery procedures:

| Failure Scenario | Symptoms | Recovery Procedure |
|-----------------|----------|-------------------|
| Registry not found | `FileNotFoundError` on query/list/trace | Auto-run `init` → `scan` → retry the command |
| Registry corrupt | `json.JSONDecodeError` on load | Delete `.codelens/` → `init` → `scan` → retry |
| Scan fails (file read) | `IOError` on specific files | Scan continues, skipping unreadable files. Report failed files to user. |
| Scan fails (grammar import) | `ImportError` for tree-sitter | Automatic fallback to regex parser. No action needed. |
| Query returns unexpected | Symbol exists but query says not found | Run `scan --incremental` first (registry may be stale), then retry `query` |
| Trace finds no edges | Empty call chain for known function | Run `scan` to rebuild edges, then retry `trace` |
| vuln-scan: npm audit not found | `FileNotFoundError` for npm | Skip native audit, use built-in CVE database + lock-file parsing |
| perf-hint: too many results | Overwhelming number of hints | Apply `--severity critical` or `--category` filter to narrow scope |
| css-deep: no CSS files found | Empty results | Check if CSS is in .vue/.svelte components (still scanned). Verify config ignore paths. |
| Timeout on large workspace | `subprocess.TimeoutExpired` | Use `--incremental` scan. For analysis tools, try per-file with `--file` flag. |

### Auto-Recovery Pattern

```python
def resilient_codelens_query(name, workspace, domain=None, max_retries=2):
    """Query with automatic error recovery."""
    for attempt in range(max_retries + 1):
        try:
            result = cmd_query(name, workspace, domain=domain)
            return result
        except FileNotFoundError:
            if attempt == 0:
                # Registry doesn't exist — auto-init
                cmd_init(workspace)
                cmd_scan(workspace)
                continue
            raise
        except json.JSONDecodeError:
            if attempt == 0:
                # Registry corrupt — rebuild
                import shutil
                shutil.rmtree(os.path.join(workspace, '.codelens'), ignore_errors=True)
                cmd_init(workspace)
                cmd_scan(workspace)
                continue
            raise
        except Exception as e:
            # Unexpected error — log and return safe default
            print(f"[CodeLens] Warning: query failed: {e}")
            return {"found": False, "query": name, "error": str(e)}
    return {"found": False, "query": name, "error": "Max retries exceeded"}
```

---

## 14. Parallel Execution Hints

Some CodeLens tools can be run in parallel (independent data sources), while others must be sequential (each depends on the previous result).

### Parallel-Safe Groups

These tools read independent data sources and can run simultaneously:

**Group A — Security Scan** (all read different sources, no dependencies):
- `secrets` ∥ `vuln-scan` ∥ `regex-audit` ∥ `env-check`

**Group B — Quality Audit** (all analyze different aspects independently):
- `complexity` ∥ `a11y` ∥ `css-deep` ∥ `perf-hint`

**Group C — Structure Discovery** (all map different structural aspects):
- `entrypoints` ∥ `api-map` ∥ `state-map` ∥ `circular`

**Group D — Dead Code Detection** (different detection strategies):
- `dead-code` ∥ `list --filter dead` ∥ `missing-refs`

**Group E — Ownership & History** (all git-based or mtime-based):
- `ownership` ∥ `diff` ∥ `config-drift`

### Sequential-Required Chains

These tools MUST run in sequence because each depends on the previous result:

1. **Write flow**: `query` → write code → `scan --incremental` → `missing-refs`
2. **Bug investigation**: `search` → `context` → `trace` → `missing-refs`
3. **Refactoring**: `refactor-safe` → `impact` → `test-map` → refactor → `scan --incremental`
4. **Security deep-dive**: `secrets` → `dataflow` → (if taint found) → `env-check` → `vuln-scan`
5. **Understanding**: `entrypoints` → `api-map` → `state-map` → `outline --all`

### Implementation with concurrent.futures

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def parallel_security_scan(workspace):
    """Run security tools in parallel for faster results."""
    tools = [
        ("secrets", lambda: cmd_secrets(workspace)),
        ("vuln-scan", lambda: scan_vulnerabilities(workspace)),
        ("regex-audit", lambda: audit_regex_patterns(workspace)),
        ("env-check", lambda: check_env_vars(workspace)),
    ]
    
    results = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(fn): name
            for name, fn in tools
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result(timeout=30)
            except Exception as e:
                results[name] = {"status": "error", "error": str(e)}
    
    return results
```

---

## 15. Edge Case Flows

### Empty Workspace
```
User: "Check this workspace" (but workspace has no source files)
          │
          ▼
1. codelens scan workspace
   → files_scanned: all zeros
          │
          ▼
2. Report: "No source files found. Check:
   - Is this the correct workspace path?
   - Are file extensions covered? (.html, .css, .js, .ts, .tsx, .py, .rs, .vue, .svelte)
   - Is the ignore list too aggressive? Check .codelens/codelens.config.json"
```

### No Git Available
```
User: "Who owns this code?" (but git is not installed)
          │
          ▼
1. codelens ownership workspace
   → Falls back to mtime-based analysis (file modification time)
          │
          ▼
2. Report: "Git not available. Using file modification time for ownership analysis.
   Results are less precise — install git for accurate blame data."
```

### Monorepo with Multiple Package.json
```
User: "Scan this monorepo"
          │
          ▼
1. codelens scan workspace
   → Scans all subdirectories (respects ignore list)
          │
          ▼
2. codelens vuln-scan workspace
   → Discovers ALL package.json/Cargo.toml/requirements.txt across subdirectories
   → Reports findings per-file with relative paths
          │
          ▼
3. codelens config-drift workspace
   → Checks each package.json against its local node_modules
```

### No package.json (Pure Frontend or Static Site)
```
User: "Check this static site" (no package.json)
          │
          ▼
1. codelens scan workspace
   → Frontend-only scan (HTML + CSS)
          │
          ▼
2. codelens css-deep workspace
   → Full CSS analysis still works
          │
          ▼
3. codelens missing-refs workspace
   → HTML/CSS mismatch detection still works
          │
          ▼
4. Report: "No backend/JS files detected. Analysis limited to HTML + CSS.
   Framework detection may be limited without package.json."
```

### TypeScript-Only Workspace
```
User: "Analyze this TypeScript project"
          │
          ▼
1. codelens scan workspace
   → .ts files routed based on frontend/backend paths
   → Frontend .ts → TSX parser, Backend .ts → JS backend parser
          │
          ▼
2. If all files go to wrong domain:
   Adjust .codelens/codelens.config.json:
   - Add frontend/backend paths correctly
   - Re-scan
```

---

## 16. Streaming/Real-Time Integration

### Watch Mode + Webhook Callback

For agents that need real-time codebase updates, use the watch mode with a webhook callback:

```python
import subprocess
import threading
import json
import requests

class CodeLensWatcher:
    """Watch workspace for changes and post results to a webhook."""
    
    def __init__(self, workspace, webhook_url):
        self.workspace = workspace
        self.webhook_url = webhook_url
        self.process = None
    
    def start(self):
        """Start watching in a background thread."""
        def _watch():
            # Use the built-in watch command
            self.process = subprocess.Popen(
                ["python3", CODELENS_CLI, "watch", self.workspace],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for line in self.process.stdout:
                if "Scan complete:" in line:
                    # Parse the JSON result
                    try:
                        json_start = line.index("{")
                        result = json.loads(line[json_start:])
                        self._notify_webhook(result)
                    except (ValueError, json.JSONDecodeError):
                        pass
        
        thread = threading.Thread(target=_watch, daemon=True)
        thread.start()
    
    def _notify_webhook(self, scan_result):
        """Post scan result to the webhook URL."""
        try:
            requests.post(
                self.webhook_url,
                json={
                    "event": "codelens_scan_complete",
                    "workspace": self.workspace,
                    "result": scan_result,
                },
                timeout=5,
            )
        except requests.RequestException:
            pass  # Webhook down — non-critical
    
    def stop(self):
        """Stop the watcher."""
        if self.process:
            self.process.terminate()
```

### Polling Alternative (No watchdog)

If `watchdog` is not installed, use polling:

```python
import time

class CodeLensPoller:
    """Poll for codebase changes at regular intervals."""
    
    def __init__(self, workspace, interval_seconds=30, callback=None):
        self.workspace = workspace
        self.interval = interval_seconds
        self.callback = callback
        self.running = False
    
    def start(self):
        """Start polling in a background thread."""
        self.running = True
        def _poll():
            while self.running:
                result = cmd_scan(self.workspace, incremental=True)
                if result.get("message") != "No changes detected. Registry is up to date.":
                    if self.callback:
                        self.callback(result)
                time.sleep(self.interval)
        
        thread = threading.Thread(target=_poll, daemon=True)
        thread.start()
    
    def stop(self):
        self.running = False
```

---

## 17. REST API Wrapper Pattern

For non-Python agents or microservice architectures, wrap CodeLens as an HTTP API:

### FastAPI Wrapper

```python
# server.py — FastAPI-based CodeLens API
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import os
import sys

# Add CodeLens to path
sys.path.insert(0, "/path/to/codelens/scripts")

from codelens import cmd_scan, cmd_query, cmd_list, cmd_init, cmd_detect

app = FastAPI(title="CodeLens API", version="5.0.0")

# In-memory workspace registry (for single-server deployments)
_active_workspaces = {}

@app.post("/init/{workspace:path}")
async def init_workspace(workspace: str):
    """Initialize CodeLens for a workspace."""
    abs_path = os.path.abspath(workspace)
    if not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail=f"Workspace not found: {workspace}")
    result = cmd_init(abs_path)
    _active_workspaces[abs_path] = True
    return result

@app.post("/scan/{workspace:path}")
async def scan_workspace(workspace: str, incremental: bool = False):
    """Scan workspace and build registry."""
    abs_path = os.path.abspath(workspace)
    result = cmd_scan(abs_path, incremental=incremental)
    return result

@app.get("/query/{name}/{workspace:path}")
async def query_symbol(name: str, workspace: str, domain: str = None):
    """Query a class/id/function."""
    abs_path = os.path.abspath(workspace)
    result = cmd_query(name, abs_path, domain=domain)
    return result

@app.get("/list/{workspace:path}")
async def list_entries(workspace: str, domain: str = "all", filter_type: str = "all"):
    """List entries with optional filter."""
    abs_path = os.path.abspath(workspace)
    result = cmd_list(abs_path, domain=domain, filter_type=filter_type)
    return result

# Add more endpoints for other commands...

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8901)
```

### Running the API Server

```bash
# Install dependencies
pip install fastapi uvicorn

# Start the server
python server.py

# Or with custom host/port
uvicorn server:app --host 0.0.0.0 --port 8901 --workers 2
```

### Usage from Any Agent

```bash
# Initialize
curl -X POST http://localhost:8901/init/path/to/workspace

# Scan
curl -X POST "http://localhost:8901/scan/path/to/workspace?incremental=true"

# Query
curl http://localhost:8901/query/btn-primary/path/to/workspace

# List dead code
curl "http://localhost:8901/list/path/to/workspace?domain=all&filter_type=dead"
```

### Security Considerations

- **Path traversal**: Validate workspace paths to prevent directory traversal attacks
- **Rate limiting**: Add rate limiting for scan endpoints (CPU-intensive)
- **Authentication**: Add API key authentication for production deployments
- **Sandboxing**: Consider running in a container with read-only workspace access
