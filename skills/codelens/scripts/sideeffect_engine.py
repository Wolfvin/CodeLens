"""
Side-Effect Engine for CodeLens — v3
Tags functions as pure vs side-effecting.
Knowing what's pure tells AI: "This is safe to reorder/remove/call multiple times."
Knowing what's impure tells AI: "This touches state, DOM, network, or filesystem — be careful."

Side-effect categories:
- DOM: Modifies DOM (innerHTML, createElement, append, remove)
- State: Modifies state (setState, store.dispatch, global variables)
- Network: Makes HTTP requests (fetch, axios, http.get)
- IO: File system or console I/O
- Timer: setTimeout, setInterval, requestAnimationFrame
- Random: Math.random, crypto.randomBytes
- External: External service calls (database, queue, cache)

A function is PURE if it has no side effects and its output depends only on its inputs.
A function is IMPURE if it has any side effect.
A function is CONDITIONALLY_PURE if it's pure for some call patterns but not others.
"""

import os
import re
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS, logger

SOURCE_EXTENSIONS = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py", ".rs", ".go"}

# ─── Side-Effect Signatures ───────────────────────────────────

SIDE_EFFECT_PATTERNS = {
    "dom": {
        "patterns": [
            r"\.innerHTML\s*=",
            r"\.outerHTML\s*=",
            r"\.textContent\s*=",
            r"\.innerText\s*=",
            r"document\.(?:createElement|createTextNode|write|writeln)",
            r"\.appendChild\s*\(",
            r"\.removeChild\s*\(",
            r"\.insertBefore\s*\(",
            r"\.replaceChild\s*\(",
            r"\.setAttribute\s*\(",
            r"\.classList\.(?:add|remove|toggle)",
            r"\.style\.\w+\s*=",
            r"ReactDOM\.render",
            r"createRoot\s*\(",
        ],
        "label": "dom_mutation",
        "severity": "medium"
    },
    "state": {
        "patterns": [
            r"setState\s*\(",
            r"useState\s*\(",
            r"useReducer\s*\(",
            r"store\.dispatch\s*\(",
            r"commit\s*\(",       # Vuex
            r"dispatch\s*\(",     # Redux/Vuex
            r"mutate\s*\(",       # Vuex
            r"\.value\s*=",       # Vue ref
            r"ref\(\s*\)",        # Vue ref
            r"reactive\s*\(",     # Vue reactive
            r"this\.\w+\s*=(?!=)", # Class property assignment
            r"global\.\w+\s*=",
            r"window\.\w+\s*=",
        ],
        "label": "state_mutation",
        "severity": "medium"
    },
    "network": {
        "patterns": [
            r"(?:fetch|axios|http|https|request)\s*\.\s*(?:get|post|put|delete|patch|head|options)\s*\(",
            r"fetch\s*\(",
            r"axios\s*\.\s*\w+\s*\(",
            r"XMLHttpRequest",
            r"WebSocket\s*\(",
            r"io\s*\.\s*(?:emit|on)\s*\(",  # Socket.io
            r"reqwest::",
            r"ureq::",
            # ── Rust network side effects ──
            r"hyper::",
            r"warp::",
            r"actix_web::",
            r"tonic::",
            # ── Go network side effects ──
            r"http\.(?:Get|Post|Head|Do|NewRequest)",
            r"net/http\.",
            r"httputil\.",
            r"json\.NewDecoder\(.*resp\.Body",
            r"io\.ReadAll\(.*Body\)",
        ],
        "label": "network_request",
        "severity": "high"
    },
    "io": {
        "patterns": [
            r"console\.\w+\s*\(",
            r"fs\.\w+\s*\(",
            r"readFile|writeFile|appendFile",
            r"std::fs::",
            r"std::io::",
            r"print\s*\(",
            r"open\s*\(",
            r"with\s+open",
            r"logging\.",
            r"log::",
            # ── Rust IO side effects ──
            r"println!",
            r"eprintln!",
            r"dbg!",
            r"std::process::Command",
            r"process::Command",
            r"fs::(?:read|write|create|remove|rename|copy|canonicalize|metadata|File)",
            r"tokio::fs::",
            r"tokio::io::",
            # ── Go IO side effects ──
            r"os\.(?:Create|Open|OpenFile|ReadFile|WriteFile|Remove|Rename|Mkdir|ReadDir)",
            r"fmt\.(?:Print|Fprint|Sprint|Fprintf|Printf|Println|Fprintln)",
            r"log\.(?:Print|Fatal|Panic|Printf|Fatalf|Panicf)",
            r"io\.(?:Copy|ReadAll|ReadFile|WriteFile|Pipe|CopyBuffer)",
            r"ioutil\.",
            r"os/exec\.",
            r"exec\.Command",
        ],
        "label": "io_operation",
        "severity": "low"
    },
    "timer": {
        "patterns": [
            r"setTimeout\s*\(",
            r"setInterval\s*\(",
            r"requestAnimationFrame\s*\(",
            r"clearTimeout\s*\(",
            r"clearInterval\s*\(",
        ],
        "label": "timer",
        "severity": "low"
    },
    "random": {
        "patterns": [
            r"Math\.random\s*\(",
            r"crypto\.randomBytes\s*\(",
            r"uuid\.(?:v4|v1)\s*\(",
            r"nanoid\s*\(",
            r"rand::",
            r"rand::Rng",
            # ── Go random side effects ──
            r"math/rand\.",
            r"crypto/rand\.",
            r"rand\.(?:Int|Float|Shuffle|Perm|Read|Seed)",
        ],
        "label": "non_deterministic",
        "severity": "low"
    },
    "external": {
        "patterns": [
            r"(?:redis|mongo|postgres|mysql|knex|sequelize|prisma)\.\w+",
            r"pool\.(?:query|execute)",
            r"db\.\w+",
            r"connection\.\w+",
            r"client\.\w+",
            r"\.query\s*\(",
            r"\.execute\s*\(",
            r"\.run\s*\(",
            # ── Rust external side effects ──
            r"app_handle",
            r"tauri::api::",
            r"tokio::spawn",
            r"std::thread::spawn",
            r"\.await",
            # ── Go external side effects ──
            r"go\s+\w+\(",  # goroutine launch
            r"database/sql\.",
            r"sql\.(?:Open|Query|Exec|Prepare|Begin)",
            r"redis\.",
            r"mongo\.",
            r"grpc\.",
        ],
        "label": "external_service",
        "severity": "high"
    },
    # ── VSCode Extension API ──────────────────────────────────────
    # The `vscode` module is an ambient API provided at runtime by the
    # extension host. Calls to vscode.window.*, vscode.commands.*, etc.
    # are all side-effecting (register providers, show UI, write output).
    "vscode_api": {
        "patterns": [
            r"vscode\.window\.(?:createOutputChannel|showInformationMessage|showWarningMessage|showErrorMessage|showInputBox|showQuickPick|createTerminal|createWebviewPanel|showTextDocument|activeTextEditor|createStatusBarItem)",
            r"vscode\.commands\.(?:registerCommand|registerTextEditorCommand|executeCommand)",
            r"vscode\.workspace\.(?:registerFileSystemProvider|registerTextDocumentContentProvider|registerTaskProvider|createFileSystemWatcher|findFiles|openTextDocument)",
            r"vscode\.languages\.(?:registerCompletionItemProvider|registerHoverProvider|registerDefinitionProvider|registerReferenceProvider|registerCodeLensProvider|registerCodeActionsProvider|registerDocumentSymbolProvider|registerWorkspaceSymbolProvider|registerDocumentFormattingEditProvider|registerDocumentRangeFormattingEditProvider|registerOnTypeFormattingEditProvider|registerRenameProvider|registerDocumentLinkProvider|registerColorProvider|registerFoldingRangeProvider|registerImplementationProvider|registerTypeDefinitionProvider|registerSignatureHelpProvider|registerDocumentHighlightProvider|setLanguageConfiguration)",
            r"vscode\.debug\.(?:registerDebugConfigurationProvider|registerDebugAdapterTrackerFactory|startDebugging)",
            r"vscode\.extensions\.(?:createStatusBarItem|registerTreeDataProvider)",
            r"vscode\.treeDataProvider",
            r"vscode\. notebooks\.",
            r"vscode\.tests\.(?:createTestController|registerTestProvider)",
            # Webview IPC: postMessage is side-effecting (sends data to host)
            r"(?:vsCodeApi|vscodePostMessage)\.postMessage\s*\(",
            r"acquireVsCodeApi\s*\(",  # acquiring the API object itself is side-effecting
        ],
        "label": "vscode_extension_api",
        "severity": "high"
    },
}


def analyze_side_effects(
    workspace: str,
    function_name: Optional[str] = None,
    file_filter: Optional[str] = None,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Analyze functions for side effects across the workspace.

    If function_name is specified, analyze only that function.
    If file_filter is specified, analyze only matching files.
    Otherwise, analyze the entire workspace.

    Args:
        workspace: Absolute path to workspace
        function_name: Optional specific function to analyze
        file_filter: Optional file path filter
        config: CodeLens config

    Returns:
        Dict with function classifications (pure/impure) and side-effect details
    """
    workspace = os.path.abspath(workspace)

    function_analyses = []

    # First, try backend registry for function definitions
    try:
        from registry import load_backend_registry
        backend = load_backend_registry(workspace)
        registry_nodes = backend.get("nodes", [])
    except Exception:
        logger.warning("Failed to load backend registry", exc_info=True)
        registry_nodes = []

    # If specific function requested, find it
    if function_name:
        target_nodes = [n for n in registry_nodes if n["fn"] == function_name]
        if target_nodes:
            for node in target_nodes:
                analysis = _analyze_single_function(workspace, node)
                if analysis:
                    function_analyses.append(analysis)
            return {
                "status": "ok",
                "workspace": workspace,
                "function": function_name,
                "analyses": function_analyses,
                "count": len(function_analyses)
            }
        else:
            # Not in registry — try to find it via file scan
            result = _scan_for_function(workspace, function_name, file_filter)
            return result

    # Full workspace analysis
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in SOURCE_EXTENSIONS:
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            if file_filter and file_filter not in rel_path:
                continue

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            # Find all functions in this file
            functions = _extract_functions(content, ext, rel_path)

            for fn_info in functions:
                # Get the function body
                fn_body = _get_function_body(content, fn_info, ext)

                # Analyze for side effects
                effects = _detect_effects(fn_body, ext)

                classification = "pure" if not effects else "impure"

                function_analyses.append({
                    "name": fn_info["name"],
                    "file": rel_path,
                    "line": fn_info["line"],
                    "classification": classification,
                    "side_effects": effects,
                    "effect_count": len(effects),
                    "is_async": fn_info.get("async", False)
                })

    # Summary statistics
    pure_count = sum(1 for a in function_analyses if a["classification"] == "pure")
    impure_count = sum(1 for a in function_analyses if a["classification"] == "impure")
    total = len(function_analyses)

    # Group by side-effect type
    effect_summary = defaultdict(int)
    for a in function_analyses:
        for e in a.get("side_effects", []):
            effect_summary[e["type"]] += 1

    return {
        "status": "ok",
        "workspace": workspace,
        "stats": {
            "total_functions": total,
            "pure": pure_count,
            "impure": impure_count,
            "purity_ratio": round(pure_count / total, 2) if total > 0 else 1.0,
            "effect_summary": dict(effect_summary)
        },
        "functions": function_analyses,
        "count": total
    }


def _analyze_single_function(workspace: str, node: Dict) -> Optional[Dict]:
    """Analyze a single function from registry node."""
    file_path = os.path.join(workspace, node.get("file", ""))
    if not os.path.exists(file_path):
        return None

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except IOError:
        return None

    ext = os.path.splitext(file_path)[1].lower()
    fn_name = node["fn"]
    fn_line = node.get("line", 0)

    # Find function body
    lines = content.split('\n')
    if fn_line < 1 or fn_line > len(lines):
        return None

    # Extract function body from line
    fn_body_lines = []
    if ext == ".py":
        base_indent = len(lines[fn_line - 1]) - len(lines[fn_line - 1].lstrip())
        for i in range(fn_line, len(lines)):
            line = lines[i]
            if line.strip() and (len(line) - len(line.lstrip())) <= base_indent:
                break
            fn_body_lines.append(line)
    else:
        brace_count = 0
        started = False
        for i in range(fn_line - 1, min(fn_line + 200, len(lines))):
            line = lines[i]
            for ch in line:
                if ch == '{':
                    brace_count += 1
                    started = True
                elif ch == '}':
                    brace_count -= 1
                    if started and brace_count == 0:
                        fn_body_lines.append(line)
                        break
            else:
                # Only append if we didn't break (closing brace line already appended)
                fn_body_lines.append(line)
            if started and brace_count == 0:
                break

    fn_body = '\n'.join(fn_body_lines)

    # Detect effects
    effects = _detect_effects(fn_body, ext)
    classification = "pure" if not effects else "impure"

    return {
        "name": fn_name,
        "file": node.get("file", ""),
        "line": fn_line,
        "classification": classification,
        "side_effects": effects,
        "effect_count": len(effects),
        "is_async": node.get("async", False)
    }


def _scan_for_function(workspace: str, function_name: str, file_filter: Optional[str] = None) -> Dict:
    """Scan workspace for a function not in registry."""
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in SOURCE_EXTENSIONS:
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            if file_filter and file_filter not in rel_path:
                continue

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            # Check if function exists in this file
            if re.search(r'(?:function\s+' + re.escape(function_name) +
                         r'|(?:const|let|var)\s+' + re.escape(function_name) +
                         r'\s*=|def\s+' + re.escape(function_name) +
                         r'|(?:pub\s+)?fn\s+' + re.escape(function_name) + r')\s*[\(=]', content):
                lines = content.split('\n')
                for i, line in enumerate(lines):
                    if function_name in line and re.search(
                        r'(?:function |const |let |var |def |fn )' + re.escape(function_name),
                        line
                    ):
                        effects = _detect_effects(content[max(0, i-5):min(len(content), i+500)], ext)
                        return {
                            "status": "ok",
                            "workspace": workspace,
                            "function": function_name,
                            "analyses": [{
                                "name": function_name,
                                "file": rel_path,
                                "line": i + 1,
                                "classification": "pure" if not effects else "impure",
                                "side_effects": effects,
                                "effect_count": len(effects)
                            }],
                            "count": 1
                        }

    return {
        "status": "not_found",
        "workspace": workspace,
        "function": function_name,
        "message": f"Function '{function_name}' not found in workspace"
    }


def _extract_functions(content: str, ext: str, rel_path: str) -> List[Dict]:
    """Extract function definitions from file."""
    functions = []
    lines = content.split('\n')

    if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
        for i, line in enumerate(lines):
            stripped = line.strip()
            m = re.match(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)', stripped)
            if m:
                functions.append({"name": m.group(1), "line": i + 1, "async": "async" in stripped[:m.end()]})
                continue
            m = re.match(r'(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(', stripped)
            if m:
                functions.append({"name": m.group(1), "line": i + 1, "async": "async" in stripped})

    elif ext == ".py":
        for i, line in enumerate(lines):
            m = re.match(r'(?:async\s+)?def\s+(\w+)', line.strip())
            if m:
                functions.append({"name": m.group(1), "line": i + 1, "async": line.strip().startswith("async")})

    elif ext == ".rs":
        for i, line in enumerate(lines):
            m = re.match(r'\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)', line)
            if m:
                functions.append({"name": m.group(1), "line": i + 1, "async": "async" in line})

    elif ext == ".go":
        for i, line in enumerate(lines):
            # Match Go function: func (r *Receiver) Name(...) or func Name(...)
            m = re.match(r'\s*func\s+(?:\([^)]+\)\s+)?(\w+)', line)
            if m:
                fn_name = m.group(1)
                # Skip init() and main() — they're entry points, not regular functions
                if fn_name not in ('init', 'main'):
                    functions.append({"name": fn_name, "line": i + 1, "async": False})

    return functions


def _get_function_body(content: str, fn_info: Dict, ext: str) -> str:
    """Get the body of a function."""
    lines = content.split('\n')
    start = fn_info["line"] - 1

    if start >= len(lines):
        return ""

    if ext == ".py":
        base_indent = len(lines[start]) - len(lines[start].lstrip())
        body_lines = [lines[start]]
        for i in range(start + 1, len(lines)):
            line = lines[i]
            if line.strip() and (len(line) - len(line.lstrip())) <= base_indent:
                break
            body_lines.append(line)
        return '\n'.join(body_lines)
    else:
        # Find opening brace and count to closing
        brace_count = 0
        started = False
        body_lines = []
        for i in range(start, min(start + 200, len(lines))):
            line = lines[i]
            body_lines.append(line)
            for ch in line:
                if ch == '{':
                    brace_count += 1
                    started = True
                elif ch == '}':
                    brace_count -= 1
                    if started and brace_count == 0:
                        return '\n'.join(body_lines)
        return '\n'.join(body_lines)


def _detect_effects(fn_body: str, ext: str) -> List[Dict]:
    """Detect side effects in a function body."""
    effects = []

    for effect_key, effect_def in SIDE_EFFECT_PATTERNS.items():
        for pattern in effect_def["patterns"]:
            matches = list(re.finditer(pattern, fn_body))
            if matches:
                effects.append({
                    "type": effect_key,
                    "label": effect_def["label"],
                    "severity": effect_def["severity"],
                    "occurrences": len(matches),
                    "example": matches[0].group(0)[:80]
                })
                break  # One detection per effect type is enough

    return effects
