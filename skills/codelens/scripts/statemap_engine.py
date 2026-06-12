"""
State Map Engine for CodeLens — v3
Tracks global state management across the workspace.
Answers: "What reads/writes each state slice? Where is state defined and consumed?"

State Management Frameworks Detected:
 1. Redux         — createStore, configureStore, slice reducers, actions, selectors
 2. React Context — createContext, useContext, Provider components
 3. Zustand       — create(), useStore, set/get patterns
 4. MobX          — observable, action, computed, makeAutoObservable
 5. Pinia         — defineStore, useStore
 6. Vuex          — new Vuex.Store, state/getters/mutations/actions
 7. Recoil        — atom, selector, useRecoilState
 8. Jotai         — atom, useAtom
 9. XState        — createMachine, StateMachine
10. Svelte Stores — writable(), readable(), derived() from svelte/store
11. Module-level  — global variables, singletons, module.exports of stateful objects

Per-state-slice extraction: name, type (store/context/atom/global),
    defined_in, consumers, actions/mutations that modify it
"""

import os
import re
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS


# ─── Configuration ─────────────────────────────────────────────

SOURCE_EXTENSIONS = {
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".py", ".rs", ".vue", ".svelte",
}

STATE_TYPES = {"store", "context", "atom", "global", "machine", "derived_store", "module_constant"}

# ─── JS/TS Keywords & Built-ins (false-positive filter) ────────

_JS_KEYWORDS = frozenset({
    'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'default',
    'try', 'catch', 'finally', 'throw', 'new', 'return', 'break',
    'continue', 'typeof', 'instanceof', 'in', 'of', 'delete', 'void',
    'yield', 'await', 'async', 'function', 'class', 'const', 'let',
    'var', 'import', 'export', 'from', 'as', 'extends', 'super',
    'this', 'constructor', 'static', 'get', 'set',
})

_JS_BUILTIN_METHODS = frozenset({
    'push', 'pop', 'shift', 'unshift', 'splice', 'slice', 'concat',
    'join', 'reverse', 'sort', 'filter', 'map', 'reduce', 'forEach',
    'find', 'findIndex', 'some', 'every', 'includes', 'indexOf',
    'lastIndexOf', 'flat', 'flatMap', 'fill', 'copyWithin', 'entries',
    'keys', 'values', 'toString', 'valueOf', 'hasOwnProperty',
    'isPrototypeOf', 'propertyIsEnumerable', 'toLocaleString',
    'charAt', 'charCodeAt', 'codePointAt', 'startsWith', 'endsWith',
    'repeat', 'trim', 'trimStart', 'trimEnd', 'padStart', 'padEnd',
    'toUpperCase', 'toLowerCase', 'localeCompare', 'match', 'matchAll',
    'replace', 'replaceAll', 'search', 'split', 'substring', 'substr',
    'assign', 'create', 'defineProperty', 'defineProperties', 'freeze',
    'getPrototypeOf', 'setPrototypeOf', 'keys', 'values', 'entries',
    'parse', 'stringify', 'resolve', 'reject', 'then', 'catch',
    'finally', 'all', 'race', 'allSettled', 'any',
    'addEventListener', 'removeEventListener', 'querySelector',
    'querySelectorAll', 'getElementById', 'getElementsByClassName',
    'getElementsByTagName', 'createElement', 'appendChild',
    'removeChild', 'insertBefore', 'replaceChild', 'cloneNode',
    'setTimeout', 'setInterval', 'clearTimeout', 'clearInterval',
    'requestAnimationFrame', 'cancelAnimationFrame',
    'fetch', 'json', 'text', 'blob', 'arrayBuffer', 'formData',
    'log', 'warn', 'error', 'info', 'debug', 'dir', 'table',
    'assert', 'count', 'countReset', 'group', 'groupEnd', 'time',
    'timeEnd', 'trace', 'clear',
})


_TS_TYPE_SUFFIXES = (
    'Payload', 'Params', 'Request', 'Response', 'Result',
    'Input', 'Output', 'DTO', 'Args', 'Var', 'Ref',
)


def _is_js_keyword_or_builtin(name: str) -> bool:
    """Check if a name is a JS/TS keyword or built-in method.

    Used to filter false-positive action/getter detections in state
    management extractors (Pinia, Vuex, etc.).
    """
    return name in _JS_KEYWORDS or name in _JS_BUILTIN_METHODS


def _is_typescript_type_definition(content: str, var_name: str, line_idx: int) -> bool:
    """Check if a variable is actually a TypeScript type/interface/enum definition.

    Examines the source content around the given line to detect if the name
    is a type definition rather than a runtime value (state store).

    Args:
        content: Full file content
        var_name: The variable name to check
        line_idx: 0-based line index in the content

    Returns:
        True if this appears to be a type definition, not a runtime value.
    """
    lines = content.split('\n')

    # Check nearby lines (current and 2 before) for type/interface/enum keywords
    for offset in range(3):
        check_idx = line_idx - offset
        if check_idx < 0 or check_idx >= len(lines):
            continue
        check_line = lines[check_idx].strip()

        # Direct type/interface/enum declarations
        if re.match(r'^(?:export\s+)?(?:interface|type|enum)\s+', check_line):
            return True

        # const enum declarations
        if re.match(r'^(?:export\s+)?const\s+enum\s+', check_line):
            return True

    # Check current line for type annotation patterns
    if line_idx < len(lines):
        current_line = lines[line_idx]

        # TypeScript type annotation: const X: SomeType = ...
        # These are often type/schema definitions, not mutable state
        if re.search(r':\s*(?:Readonly|Partial|Record|Pick|Omit|Required)\b', current_line):
            return True

        # const X = { ... } as const — immutable by definition
        if re.search(r'\bas\s+const\b', current_line):
            return True

        # Zod/schema library patterns: const X = z.object({...})
        if re.search(r'\bz\.(object|string|number|boolean|array|tuple|enum|union|intersection)\b', current_line):
            return True

        # Yup schema patterns: const X = yup.object().shape({...})
        if re.search(r'\byup\.(object|string|number|boolean|array)\b', current_line):
            return True

        # Joi schema patterns: const X = Joi.object({...})
        if re.search(r'\bJoi\.(object|string|number|boolean|array)\b', current_line):
            return True

    # Check if the name itself suggests it's a type definition
    # TypeScript type names often end with Payload, Params, Request, etc.
    if var_name.endswith(_TS_TYPE_SUFFIXES):
        return True

    return False


def _is_simple_constant(value_part: str) -> bool:
    """Check if a value is a simple literal constant (not mutable state).

    Simple constants like const X = "value", const X = 42, const X = { a: 1 }
    with only literal values are immutable by convention, not state stores.
    """
    value = value_part.strip()

    # String literal
    if re.match(r'^["\'`]', value):
        return True

    # Numeric literal
    if re.match(r'^\d+(?:\.\d+)?$', value):
        return True

    # Boolean/null/undefined
    if re.match(r'^(?:true|false|null|undefined)$', value):
        return True

    # Object with only literal values: { key: "value", num: 42 }
    # This is a simple constant object, not mutable state
    if re.match(r'^\{\s*\}', value):  # Empty object
        return True

    # as const — immutable assertion
    if re.search(r'\bas\s+const\s*;?\s*$', value):
        return True

    return False


def _extract_section(body: str, section_name: str) -> Optional[str]:
    """Extract a named section (actions, getters, mutations) from a store body.

    Uses brace-matching to properly extract nested content, avoiding
    the regex issues that caused false-positive detections.

    Args:
        body: The store definition body (after the opening brace).
        section_name: The section to extract (e.g., 'actions', 'getters').

    Returns:
        The section body as a string, or None if not found.
    """
    pattern = re.compile(
        rf'{section_name}\s*:\s*\{{',
        re.MULTILINE
    )
    m = pattern.search(body)
    if not m:
        return None

    # Find the matching closing brace
    start = m.end()
    depth = 1
    pos = start
    while pos < len(body) and depth > 0:
        if body[pos] == '{':
            depth += 1
        elif body[pos] == '}':
            depth -= 1
        elif body[pos] in ('"', "'", '`'):
            # Skip string literals to avoid counting braces inside strings
            quote = body[pos]
            pos += 1
            while pos < len(body) and body[pos] != quote:
                if body[pos] == '\\':
                    pos += 1  # Skip escaped character
                pos += 1
        pos += 1

    return body[start:pos - 1]


def map_state(
    workspace: str,
    store_name: Optional[str] = None,
    config: Optional[Dict] = None,
    max_stores: int = 100
) -> Dict[str, Any]:
    """
    Map all state management patterns across the workspace.

    Args:
        workspace: Absolute path to workspace
        store_name: Optional filter for a specific store name
        config: CodeLens config dict
        max_stores: Maximum number of stores to return (default 100)

    Returns:
        Dict with stats, stores, state_flow, recommendations
    """
    workspace = os.path.abspath(workspace)

    stores: List[Dict[str, Any]] = []
    state_flow: List[Dict[str, Any]] = []
    files_scanned = 0
    frameworks_detected: Set[str] = set()

    # Cross-file tracking
    all_imports_by_file: Dict[str, Set[str]] = defaultdict(set)
    all_exports_by_file: Dict[str, List[Dict]] = defaultdict(list)
    all_consumers: Dict[str, List[Dict]] = defaultdict(list)

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

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            files_scanned += 1

            # Collect imports for cross-file analysis
            if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                _collect_js_imports(content, rel_path, all_imports_by_file)
                _collect_js_exports(content, rel_path, all_exports_by_file)

            elif ext == ".py":
                _collect_py_imports(content, rel_path, all_imports_by_file)

            # ─── Redux ────────────────────────────────────────
            if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                redux_results = _extract_redux_state(content, rel_path)
                if redux_results["stores"]:
                    frameworks_detected.add("redux")
                    stores.extend(redux_results["stores"])
                    state_flow.extend(redux_results["flow"])

            # ─── React Context ────────────────────────────────
            if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                ctx_results = _extract_react_context(content, rel_path)
                if ctx_results["stores"]:
                    frameworks_detected.add("react_context")
                    stores.extend(ctx_results["stores"])
                    state_flow.extend(ctx_results["flow"])

            # ─── Zustand ──────────────────────────────────────
            if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                zustand_results = _extract_zustand_state(content, rel_path)
                if zustand_results["stores"]:
                    frameworks_detected.add("zustand")
                    stores.extend(zustand_results["stores"])
                    state_flow.extend(zustand_results["flow"])

            # ─── MobX ─────────────────────────────────────────
            if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                mobx_results = _extract_mobx_state(content, rel_path)
                if mobx_results["stores"]:
                    frameworks_detected.add("mobx")
                    stores.extend(mobx_results["stores"])
                    state_flow.extend(mobx_results["flow"])

            # ─── Pinia / Vuex ─────────────────────────────────
            if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue"}:
                pinia_results = _extract_pinia_state(content, rel_path)
                if pinia_results["stores"]:
                    frameworks_detected.add("pinia")
                    stores.extend(pinia_results["stores"])
                    state_flow.extend(pinia_results["flow"])

                vuex_results = _extract_vuex_state(content, rel_path)
                if vuex_results["stores"]:
                    frameworks_detected.add("vuex")
                    stores.extend(vuex_results["stores"])
                    state_flow.extend(vuex_results["flow"])

            # ─── Recoil / Jotai ───────────────────────────────
            if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                recoil_results = _extract_recoil_state(content, rel_path)
                if recoil_results["stores"]:
                    frameworks_detected.add("recoil")
                    stores.extend(recoil_results["stores"])
                    state_flow.extend(recoil_results["flow"])

                jotai_results = _extract_jotai_state(content, rel_path)
                if jotai_results["stores"]:
                    frameworks_detected.add("jotai")
                    stores.extend(jotai_results["stores"])
                    state_flow.extend(jotai_results["flow"])

            # ─── XState ───────────────────────────────────────
            if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                xstate_results = _extract_xstate_state(content, rel_path)
                if xstate_results["stores"]:
                    frameworks_detected.add("xstate")
                    stores.extend(xstate_results["stores"])
                    state_flow.extend(xstate_results["flow"])

            # ─── Module-level State ────────────────────────────
            if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                global_results = _extract_js_global_state(content, rel_path)
                if global_results["stores"]:
                    frameworks_detected.add("module_level_js")
                    stores.extend(global_results["stores"])
                    state_flow.extend(global_results["flow"])

            if ext == ".py":
                py_global_results = _extract_python_global_state(content, rel_path)
                if py_global_results["stores"]:
                    frameworks_detected.add("module_level_py")
                    stores.extend(py_global_results["stores"])
                    state_flow.extend(py_global_results["flow"])

            # ─── Rust State Management ──────────────────────────
            if ext == ".rs":
                rust_state_results = _extract_rust_state(content, rel_path)
                if rust_state_results["stores"]:
                    frameworks_detected.add("rust_state")
                    stores.extend(rust_state_results["stores"])
                    state_flow.extend(rust_state_results["flow"])

    # ─── Svelte Stores (workspace-level detection) ───────────
    if _is_svelte_workspace(workspace):
        svelte_stores, svelte_flow = _detect_svelte_stores(workspace, config)
        if svelte_stores:
            frameworks_detected.add("svelte_stores")
            stores.extend(svelte_stores)
            state_flow.extend(svelte_flow)

    # ─── Deduplicate stores ────────────────────────────────────
    # When the same store name appears in multiple files (e.g. a Python
    # constant like SECRET_KEY defined in several modules), merge the
    # entries instead of creating duplicates.
    stores = _deduplicate_stores(stores)

    # ─── Post-processing: Resolve consumers ──────────────────

    # For each store, find files that import it
    for store in stores:
        defined_in = store.get("defined_in", "")
        store_name_val = store.get("name", "")

        # Find consumers by checking imports
        for file_path, imported_names in all_imports_by_file.items():
            if file_path == defined_in:
                continue
            # Check if this file imports the store name or its file
            store_file_base = os.path.splitext(os.path.basename(defined_in))[0]
            if store_name_val in imported_names or store_file_base in imported_names:
                store.setdefault("consumers", []).append({
                    "file": file_path,
                    "type": "import",
                })
                # Add flow entry for reading the store
                state_flow.append({
                    "from": file_path,
                    "action": f"use({store_name_val})",
                    "to": store_name_val,
                    "file": file_path,
                    "type": "read",
                })

    # ─── Apply filters ────────────────────────────────────────

    # v5.8.1: Post-filter false positives that slip through per-extraction skip lists.
    # Some engines (e.g., XState, MobX, module-level) may emit items whose names
    # are Node.js globals, common CLI constants, or dunder attributes.
    _POST_FILTER_SKIP_NAMES = {
        # Node.js / browser globals
        '__dirname', '__filename', '__proto__', 'process', 'global', 'globalThis',
        'Buffer', 'console', 'module', 'exports', 'require',
        'window', 'document', 'navigator', 'location', 'history',
        'localStorage', 'sessionStorage', 'fetch', 'XMLHttpRequest',
        # Common framework/CLI constants that are not mutable state
        'CLI', 'ROOT', 'HOME', 'CWD', 'PWD', 'VERBOSE', 'DEBUG', 'CHECK', 'PRUNE',
        'SRC', 'DIST', 'BUILD', 'OUT', 'OUTPUT', 'PUBLIC', 'STATIC', 'ASSETS',
        'ENV', 'CONFIG', 'CONF', 'OPTS', 'ARGS', 'ARGV',
        # Common import aliases that get misclassified
        'APP', 'SERVER', 'ROUTER', 'DB', 'CLIENT', 'HANDLER',
        # Python dunder attributes
        '__name__', '__file__', '__doc__', '__package__', '__all__',
        '__builtins__', '__path__', '__spec__', '__loader__', '__cached__',
        # JS/TS runtime binding helpers (found in deno, Node polyfills)
        '__default', '__createBinding', '__exportStar', '__importDefault',
        '__reexport', '__importStar', '__buffer', '__default_export__',
        '__telemetry', '__esModule', '__webpack_require__', '__webpack_modules__',
        '__non_webpack_require__', '__callGSB', '__extends', '__assign',
        '__rest', '__decorate', '__param', '__metadata', '__awaiter',
        '__generator', '__values', '__read', '__spread', '__spreadArrays',
        # Python typing generics that get misclassified as state stores
        'MapEntry', 'DictEntry', 'ListEntry', 'SetEntry', 'TupleEntry',
        'Optional', 'Union', 'Literal', 'TypedDict', 'NamedTuple',
        # Common Python dataclass/type aliases
        'TypeVar', 'Generic', 'Protocol', 'Callable', 'Final',
    }
    stores = [s for s in stores if s.get("name", "") not in _POST_FILTER_SKIP_NAMES]

    # v5.8: Also filter any name starting with __ that looks like a runtime helper.
    # These are typically TypeScript/__esModule interop helpers, not state stores.
    def _is_dunder_runtime_helper(name: str) -> bool:
        """Check if a __dunder__ name is a runtime/interop helper, not state."""
        if not name.startswith('__'):
            return False
        # Common patterns: __XxxYyy (PascalCase after __) = TS/JS helper
        # __lowercase = Node.js/polyfill internal
        # Only skip if it's clearly a helper (starts with __ but is not a known state pattern)
        known_state_prefixes = ('__store', '__state', '__context', '__atom', '__slice')
        if any(name.startswith(p) for p in known_state_prefixes):
            return False
        return True

    stores = [s for s in stores if not _is_dunder_runtime_helper(s.get("name", ""))]

    # v5.8.1: Also filter stores where the name is ALL_CAPS with no underscore
    # and looks like a simple constant (3+ uppercase letters only = config constant).
    # e.g., "ROOT", "CLI", "LOG" — not state, just module-level constants.
    # IMPORTANT: Do NOT filter Rust state stores — Rust convention is SCREAMING_SNAKE_CASE
    # for statics with interior mutability (AtomicBool, OnceLock, etc.), which ARE state.
    def _is_likely_constant(name: str, framework: str = "") -> bool:
        """Check if a name looks like a simple constant, not state."""
        if not name:
            return False
        # Rust state stores use SCREAMING_SNAKE_CASE by convention — never filter them
        if framework.startswith('rust_'):
            return False
        # Pure uppercase with no underscore and length >= 3 → likely constant
        if name == name.upper() and len(name) >= 3 and name.isalpha():
            return True
        # ALL_CAPS with underscores → definitely a constant (for JS/TS)
        if name == name.upper() and '_' in name:
            return True
        return False

    stores = [s for s in stores if not _is_likely_constant(s.get("name", ""), s.get("framework", ""))]

    # v5.8.1: Filter likely React components — PascalCase names that end with
    # common component suffixes. These are UI components, not state stores.
    # e.g., "CompanionShell", "ApprovalQueue", "TransactionHistory"
    _COMPONENT_SUFFIXES = (
        'Button', 'Card', 'Modal', 'Dialog', 'Panel', 'Form', 'Input',
        'List', 'Table', 'Grid', 'Menu', 'Tab', 'Page', 'View', 'Screen',
        'Layout', 'Header', 'Footer', 'Sidebar', 'Navbar', 'Toolbar',
        'Badge', 'Chip', 'Tag', 'Tooltip', 'Popover', 'Dropdown',
        'Overlay', 'Alert', 'Toast', 'Notification', 'Banner',
        'Icon', 'Logo', 'Avatar', 'Image', 'Thumbnail',
        'Loader', 'Spinner', 'Skeleton', 'Progress',
        'Shell', 'Wrapper', 'Container', 'Provider', 'Consumer',
        'Widget', 'Block', 'Section', 'Divider', 'Separator',
        'Handler', 'Controller', 'Manager', 'Service', 'Client',
        'Queue', 'History', 'Settings', 'Config', 'Profile',
        'Monitor', 'Tracker', 'Watcher', 'Listener',
        'Store', 'Reducer', 'Action',  # But NOT if framework is redux/mobx
    )

    def _is_likely_react_component(name: str, framework: str) -> bool:
        """Check if a name looks like a React component, not a state store."""
        if not name:
            return False
        # Skip if this came from a known state management framework (including Rust)
        if framework in ('redux', 'mobx', 'zustand', 'recoil', 'jotai', 'pinia', 'vuex', 'xstate') or framework.startswith('rust_'):
            return False
        # PascalCase name that ends with a common component suffix
        if name[0].isupper() and any(name.endswith(s) for s in _COMPONENT_SUFFIXES):
            return True
        # Multi-word PascalCase with 3+ uppercase letters — very likely a component
        # e.g., "CodingAgentControlChip" has 4 uppercase chars
        upper_count = sum(1 for c in name if c.isupper())
        if upper_count >= 3 and len(name) >= 10:
            return True
        return False

    stores = [s for s in stores if not _is_likely_react_component(
        s.get("name", ""), s.get("framework", ""))]

    # v5.8.1: Filter stores with missing/empty defined_in — these are usually
    # artifacts from cross-file resolution that couldn't find a source.
    stores = [s for s in stores if s.get("defined_in", "")]

    # ─── Post-processing: Reclassify global stores without mutations ──
    # A "global" store with no actions/mutations is not really mutable state —
    # it's a module-level constant. Reclassify as module_constant.
    # IMPORTANT: Skip Rust state stores — Rust statics with interior mutability
    # (AtomicBool, OnceLock, etc.) ARE mutable state even without tracked actions,
    # because Rust's interior mutability pattern allows mutation through &self.
    for store in stores:
        if store.get("type") == "global" and not store.get("framework", "").startswith("rust_"):
            actions = store.get("actions", [])
            has_mutations = len(actions) > 0
            if not has_mutations:
                store["type"] = "module_constant"

    # ─── Post-processing: Filter module_constant without consumers ──
    # Module-level constants that nobody imports are dead code, not interesting state.
    # IMPORTANT: Skip Rust frameworks — Rust uses `use` statements, not JS imports,
    # so cross-file consumer resolution doesn't work for Rust state yet.
    stores = [
        s for s in stores
        if s.get("type") != "module_constant"
        or s.get("consumers")
        or s.get("framework", "").startswith("rust_")
    ]

    # ─── Post-processing: Validate file paths ────────────────────
    # Ensure all store entries have proper defined_in paths (not empty, ?, or malformed)
    stores = [
        s for s in stores
        if s.get("defined_in", "") and not s.get("defined_in", "").startswith("?")
    ]

    # ─── Validate flow entry file paths ──────────────────────────
    state_flow = [
        f for f in state_flow
        if f.get("file", "") and not f.get("file", "").startswith("?")
    ]

    if store_name:
        stores = [s for s in stores if store_name.lower() in s.get("name", "").lower()]
        state_flow = [
            f for f in state_flow
            if store_name.lower() in f.get("to", "").lower()
            or store_name.lower() in f.get("from", "").lower()
            or store_name.lower() in f.get("action", "").lower()
        ]

    # ─── Stats ────────────────────────────────────────────────

    by_type: Dict[str, int] = defaultdict(int)
    for s in stores:
        by_type[s.get("type", "unknown")] += 1

    total_slices = sum(len(s.get("slices", [])) for s in stores)

    # ─── Truncate if exceeding max_stores ─────────────────────
    truncated = False
    total_before_truncation = len(stores)
    if len(stores) > max_stores:
        truncated = True
        # Sort by interest: stores with most consumers/actions first
        def _store_interest_score(s: Dict) -> int:
            consumers = len(s.get("consumers", []))
            actions = len(s.get("actions", []))
            slices = len(s.get("slices", []))
            # Framework stores are more interesting than module_constant
            type_bonus = 0 if s.get("type") == "module_constant" else 10
            return consumers * 3 + actions * 2 + slices + type_bonus

        stores.sort(key=_store_interest_score, reverse=True)
        stores = stores[:max_stores]

        # Also filter state_flow to only include entries for kept stores
        kept_store_names = {s.get("name", "") for s in stores}
        state_flow = [
            f for f in state_flow
            if f.get("to", "") in kept_store_names
            or f.get("from", "") in kept_store_names
        ]

    # ─── Recommendations ──────────────────────────────────────

    recommendations = _generate_state_recommendations(
        stores, frameworks_detected, state_flow
    )

    return {
        "status": "ok",
        "workspace": workspace,
        "stats": {
            "total_stores": len(stores),
            "total_slices": total_slices,
            "total_before_truncation": total_before_truncation,
            "truncated": truncated,
            "by_type": dict(by_type),
            "files_scanned": files_scanned,
            "frameworks_detected": sorted(frameworks_detected),
        },
        "stores": stores,
        "state_flow": state_flow[:200],  # Cap flow entries
        "recommendations": recommendations,
    }


# ─── Deduplication ─────────────────────────────────────────────

def _deduplicate_stores(stores: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate stores that share the same name and framework.

    When the same logical state (e.g. a Python constant like SECRET_KEY)
    is defined in multiple files, the per-file extraction creates separate
    store entries.  This function merges them by keeping the first
    occurrence as the primary and recording additional definition sites in
    ``also_defined_in``.

    Args:
        stores: Raw list of store dicts (may contain duplicates).

    Returns:
        Deduplicated list of store dicts.
    """
    # Key: (name, framework)  →  index in the output list
    seen: Dict[tuple, int] = {}
    deduped: List[Dict[str, Any]] = []

    for store in stores:
        name = store.get("name", "")
        framework = store.get("framework", "")
        key = (name, framework)

        if key not in seen:
            seen[key] = len(deduped)
            deduped.append(store)
        else:
            # Merge into the existing entry
            existing = deduped[seen[key]]
            existing_file = existing.get("defined_in", "")
            new_file = store.get("defined_in", "")

            # Add the new definition site
            if new_file and new_file != existing_file:
                also = existing.setdefault("also_defined_in", [])
                if new_file not in also:
                    also.append(new_file)

            # Merge slices
            for sl in store.get("slices", []):
                existing_slices = existing.setdefault("slices", [])
                sl_name = sl.get("name", "")
                if sl_name and not any(s.get("name") == sl_name for s in existing_slices):
                    existing_slices.append(sl)

            # Merge actions
            for act in store.get("actions", []):
                existing_actions = existing.setdefault("actions", [])
                act_name = act.get("name", "") if isinstance(act, dict) else str(act)
                if act_name and not any(
                    (a.get("name", "") if isinstance(a, dict) else str(a)) == act_name
                    for a in existing_actions
                ):
                    existing_actions.append(act)

            # Merge consumers
            for con in store.get("consumers", []):
                existing_consumers = existing.setdefault("consumers", [])
                con_file = con.get("file", "")
                if con_file and not any(c.get("file") == con_file for c in existing_consumers):
                    existing_consumers.append(con)

    return deduped


# ─── Redux ─────────────────────────────────────────────────────

def _extract_redux_state(content: str, rel_path: str) -> Dict[str, Any]:
    """Extract Redux store definitions, slices, actions, and selectors."""
    stores = []
    flow = []

    # Check for Redux imports
    has_redux = bool(re.search(
        r'(?:from\s+[\'"]@reduxjs/toolkit[\'"]|from\s+[\'"]redux[\'"]|import\s+.*redux)',
        content
    ))
    if not has_redux and not re.search(r'createSlice|configureStore|createStore', content):
        return {"stores": [], "flow": []}

    # configureStore({ reducer: { ... } })
    for m in re.finditer(
        r'configureStore\s*\(\s*\{[^}]*reducer\s*:\s*\{([^}]+)\}',
        content,
        re.DOTALL
    ):
        reducer_section = m.group(1)
        line_num = content[:m.start()].count('\n') + 1

        slices = []
        for rm in re.finditer(r'(\w+)\s*:\s*(\w+Reducer|\w+)', reducer_section):
            slice_name = rm.group(1)
            slice_import = rm.group(2)
            slices.append({
                "name": slice_name,
                "reducer": slice_import,
            })
            flow.append({
                "from": rel_path,
                "action": f"configureStore({slice_name})",
                "to": slice_name,
                "file": rel_path,
                "type": "register",
            })

        stores.append({
            "name": "rootStore",
            "type": "store",
            "framework": "redux",
            "defined_in": rel_path,
            "line": line_num,
            "slices": slices,
            "actions": [],
            "consumers": [],
        })

    # createSlice({ name: 'sliceName', initialState, reducers: { ... } })
    for m in re.finditer(
        r'createSlice\s*\(\s*\{[^}]*name\s*:\s*[\'"](\w+)[\'"][^}]*reducers\s*:\s*\{([^}]+)\}',
        content,
        re.DOTALL
    ):
        slice_name = m.group(1)
        reducers_section = m.group(2)
        line_num = content[:m.start()].count('\n') + 1

        actions = []
        for rm in re.finditer(r'(\w+)\s*:', reducers_section):
            action_name = rm.group(1)
            if not _is_js_keyword_or_builtin(action_name):
                actions.append(action_name)
                flow.append({
                    "from": "dispatcher",
                    "action": f"dispatch({slice_name}/{action_name})",
                    "to": slice_name,
                    "file": rel_path,
                    "type": "write",
                })

        # Extract initialState
        initial_state = _extract_initial_state(content, m.start())

        stores.append({
            "name": slice_name,
            "type": "store",
            "framework": "redux",
            "defined_in": rel_path,
            "line": line_num,
            "slices": [],
            "actions": actions,
            "initial_state": initial_state,
            "consumers": [],
        })

    # useSelector(state => state.sliceName)
    for m in re.finditer(
        r'useSelector\s*\([^)]*state\s*(?:\.\s*(\w+)|\[([\'"]\w+[\'"])\])',
        content
    ):
        slice_name = m.group(1) or (m.group(2).strip("'\"") if m.group(2) else None)
        if slice_name:
            line_num = content[:m.start()].count('\n') + 1
            flow.append({
                "from": rel_path,
                "action": f"useSelector(state.{slice_name})",
                "to": slice_name,
                "file": rel_path,
                "type": "read",
            })

    # useDispatch
    for m in re.finditer(r'useDispatch\s*\(\s*\)', content):
        line_num = content[:m.start()].count('\n') + 1
        flow.append({
            "from": rel_path,
            "action": "useDispatch()",
            "to": "store",
            "file": rel_path,
            "type": "write_access",
        })

    return {"stores": stores, "flow": flow}


def _extract_initial_state(content: str, offset: int) -> Optional[str]:
    """Try to extract the initialState shape from a createSlice call."""
    snippet = content[offset:offset + 1500]
    m = re.search(r'initialState\s*:\s*\{([^}]+)\}', snippet)
    if m:
        return m.group(1).strip()[:200]
    return None


# ─── React Context ─────────────────────────────────────────────

def _extract_react_context(content: str, rel_path: str) -> Dict[str, Any]:
    """Extract React Context definitions and providers.

    Handles:
    - createContext (named: const FooContext = createContext())
    - createContext (anonymous: const [provider, useFoo] = createContext())
    - useContext(ContextName) consumption
    - <ContextName.Provider value={...}> provision
    - Custom hook wrappers: const useFoo = () => useContext(FooContext)
    - Variable exports matching *Context naming convention
    """
    stores = []
    flow = []

    # createContext — named pattern: const FooContext = createContext()
    # v6.2: Also handles generic type params: const FooContext = createContext<Type>(null)
    for m in re.finditer(
        r'(?:const|let|var)\s+(\w+Context)\s*=\s*createContext\s*(?:<[^>]*>)?\s*\(',
        content
    ):
        ctx_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1

        stores.append({
            "name": ctx_name,
            "type": "context",
            "framework": "react_context",
            "defined_in": rel_path,
            "line": line_num,
            "slices": [],
            "actions": [],
            "consumers": [],
        })
        flow.append({
            "from": rel_path,
            "action": f"createContext({ctx_name})",
            "to": ctx_name,
            "file": rel_path,
            "type": "define",
        })

    # createContext — variable assignment without "Context" suffix
    # e.g., const ProxiesContext = createContext()
    # v6.2: Also handles generic type params: const Foo = createContext<Type>(null)
    for m in re.finditer(
        r'(?:const|let|var)\s+(\w+)\s*=\s*createContext\s*(?:<[^>]*>)?\s*\(',
        content
    ):
        ctx_name = m.group(1)
        # Skip if already captured by the Context-suffix pattern above
        if ctx_name.endswith('Context') or ctx_name.endswith('Provider'):
            continue
        line_num = content[:m.start()].count('\n') + 1

        stores.append({
            "name": ctx_name,
            "type": "context",
            "framework": "react_context",
            "defined_in": rel_path,
            "line": line_num,
            "slices": [],
            "actions": [],
            "consumers": [],
        })
        flow.append({
            "from": rel_path,
            "action": f"createContext({ctx_name})",
            "to": ctx_name,
            "file": rel_path,
            "type": "define",
        })

    # useContext(ContextName) or useContext(Name)
    for m in re.finditer(r'useContext\s*\(\s*(\w+)\s*\)', content):
        ctx_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        flow.append({
            "from": rel_path,
            "action": f"useContext({ctx_name})",
            "to": ctx_name,
            "file": rel_path,
            "type": "read",
        })

    # <ContextName.Provider value={...}>
    for m in re.finditer(r'<(\w+(?:Context)?)\.Provider\s+value\s*=\s*\{', content):
        ctx_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        flow.append({
            "from": rel_path,
            "action": f"<{ctx_name}.Provider>",
            "to": ctx_name,
            "file": rel_path,
            "type": "provide",
        })

    return {"stores": stores, "flow": flow}


# ─── Zustand ───────────────────────────────────────────────────

def _extract_zustand_state(content: str, rel_path: str) -> Dict[str, Any]:
    """Extract Zustand store definitions."""
    stores = []
    flow = []

    has_zustand = bool(re.search(
        r'(?:from\s+[\'"]zustand[\'"]|import\s+.*zustand)',
        content
    ))
    if not has_zustand and not re.search(r'create\s*<\s*\w+\s*>\s*\(', content):
        return {"stores": [], "flow": []}

    # const useStore = create((set, get) => ({ ... }))
    for m in re.finditer(
        r'(?:const|let|var)\s+(use\w+Store)\s*=\s*create\s*(?:<[^>]+>)?\s*\(',
        content
    ):
        store_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1

        # Extract state slices and actions from the store body
        slices, actions = _extract_zustand_slices(content, m.end())

        stores.append({
            "name": store_name,
            "type": "store",
            "framework": "zustand",
            "defined_in": rel_path,
            "line": line_num,
            "slices": slices,
            "actions": actions,
            "consumers": [],
        })

        for action in actions:
            flow.append({
                "from": "component",
                "action": f"{store_name}.{action}",
                "to": store_name,
                "file": rel_path,
                "type": "write",
            })

    # useStore(state => state.prop)
    for m in re.finditer(r'(use\w+Store)\s*\(\s*(?:state|s)\s*=>\s*(?:state|s)\.(\w+)', content):
        store_name = m.group(1)
        prop_name = m.group(2)
        line_num = content[:m.start()].count('\n') + 1
        flow.append({
            "from": rel_path,
            "action": f"{store_name}(state.{prop_name})",
            "to": store_name,
            "file": rel_path,
            "type": "read",
        })

    return {"stores": stores, "flow": flow}


def _extract_zustand_slices(content: str, offset: int) -> tuple:
    """Extract state slices and actions from a Zustand store body."""
    slices = []
    actions = []

    # Look at the store body
    snippet = content[offset:offset + 2000]

    # Find the arrow function body
    brace_start = snippet.find('{')
    if brace_start < 0:
        return slices, actions

    # Find matching close brace
    depth = 0
    pos = brace_start
    while pos < len(snippet) and depth >= 0:
        if snippet[pos] == '{':
            depth += 1
        elif snippet[pos] == '}':
            depth -= 1
        pos += 1

    body = snippet[brace_start:pos]

    # Extract property definitions: key: value (state slices) or key: (args) => set(...) (actions)
    for m in re.finditer(r'(\w+)\s*:\s*', body):
        prop_name = m.group(1)
        # Check if this is an action (calls set)
        after = body[m.end():m.end() + 100]
        if re.search(r'\(.*?\)\s*=>', after) or 'set(' in after[:80]:
            actions.append(prop_name)
        else:
            # It's a state slice
            value_match = re.match(r'^([^,\n}]+)', after.strip())
            slices.append({
                "name": prop_name,
                "initial_value": value_match.group(1).strip()[:50] if value_match else None,
            })

    return slices, actions


# ─── MobX ──────────────────────────────────────────────────────

def _extract_mobx_state(content: str, rel_path: str) -> Dict[str, Any]:
    """Extract MobX observable stores and actions."""
    stores = []
    flow = []

    has_mobx = bool(re.search(
        r'(?:from\s+[\'"]mobx[\'"]|import\s+.*mobx)',
        content
    ))
    if not has_mobx and not re.search(r'makeAutoObservable|makeObservable|observable', content):
        return {"stores": [], "flow": []}

    # class Store { constructor() { makeAutoObservable(this) } }
    for m in re.finditer(
        r'class\s+(\w+Store)\s*(?:extends\s+\w+\s*)?\{',
        content
    ):
        store_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1

        # Extract observable properties and actions from class body
        class_body = content[m.end():m.end() + 5000]
        class_end = _find_matching_brace(class_body)
        class_body = class_body[:class_end]

        observables = []
        actions = []
        computed = []

        for prop_m in re.finditer(r'(\w+)\s*=\s*', class_body):
            prop_name = prop_m.group(1)
            if not prop_name.startswith('_'):
                observables.append(prop_name)

        for fn_m in re.finditer(r'(?:async\s+)?(\w+)\s*\(', class_body):
            fn_name = fn_m.group(1)
            if fn_name not in {"constructor", "super", "this"} and not fn_name.startswith('_'):
                if re.search(r'get\s+' + re.escape(fn_name), class_body):
                    computed.append(fn_name)
                else:
                    actions.append(fn_name)
                    flow.append({
                        "from": "component",
                        "action": f"{store_name}.{fn_name}()",
                        "to": store_name,
                        "file": rel_path,
                        "type": "write",
                    })

        stores.append({
            "name": store_name,
            "type": "store",
            "framework": "mobx",
            "defined_in": rel_path,
            "line": line_num,
            "slices": [{"name": o, "type": "observable"} for o in observables],
            "actions": actions,
            "computed": computed,
            "consumers": [],
        })

    # makeAutoObservable(this, { ... })
    for m in re.finditer(r'makeAutoObservable\s*\(\s*this', content):
        line_num = content[:m.start()].count('\n') + 1
        flow.append({
            "from": rel_path,
            "action": "makeAutoObservable(this)",
            "to": "class_instance",
            "file": rel_path,
            "type": "make_observable",
        })

    return {"stores": stores, "flow": flow}


def _find_matching_brace(text: str) -> int:
    """Find the position of the matching closing brace."""
    depth = 1
    pos = 0
    while pos < len(text) and depth > 0:
        if text[pos] == '{':
            depth += 1
        elif text[pos] == '}':
            depth -= 1
        pos += 1
    return pos - 1


# ─── Pinia ─────────────────────────────────────────────────────

def _extract_pinia_state(content: str, rel_path: str) -> Dict[str, Any]:
    """Extract Pinia store definitions."""
    stores = []
    flow = []

    has_pinia = bool(re.search(
        r'(?:from\s+[\'"]pinia[\'"]|import\s+.*pinia)',
        content
    ))
    if not has_pinia and not re.search(r'defineStore', content):
        return {"stores": [], "flow": []}

    # defineStore('storeName', { state, getters, actions })
    for m in re.finditer(
        r'defineStore\s*\(\s*[\'"](\w+)[\'"]\s*,\s*\{',
        content
    ):
        store_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1

        # Extract state, getters, and actions from the store body
        store_body = content[m.end():m.end() + 5000]
        store_end = _find_matching_brace(store_body)
        store_body = store_body[:store_end]

        # State properties
        slices = []
        state_match = re.search(r'state\s*:\s*\(\s*\)\s*=>\s*\{([^}]+)\}', store_body, re.DOTALL)
        if state_match:
            for prop_m in re.finditer(r'(\w+)\s*:', state_match.group(1)):
                prop_name = prop_m.group(1)
                if not prop_name.startswith('_'):
                    slices.append({"name": prop_name})

        # Actions — extract only top-level method definitions in the actions block
        actions = []
        action_section = _extract_section(store_body, 'actions')
        if action_section:
            for action_m in re.finditer(r'(?:async\s+)?(\w+)\s*\s*\(', action_section):
                action_name = action_m.group(1)
                if not _is_js_keyword_or_builtin(action_name):
                    actions.append(action_name)
                    flow.append({
                        "from": "component",
                        "action": f"{store_name}/{action_name}()",
                        "to": store_name,
                        "file": rel_path,
                        "type": "write",
                    })

        # Getters
        getters = []
        getter_section = _extract_section(store_body, 'getters')
        if getter_section:
            for getter_m in re.finditer(r'(\w+)\s*[:=]\s*\(', getter_section):
                getter_name = getter_m.group(1)
                if not _is_js_keyword_or_builtin(getter_name):
                    getters.append(getter_name)

        stores.append({
            "name": store_name,
            "type": "store",
            "framework": "pinia",
            "defined_in": rel_path,
            "line": line_num,
            "slices": slices,
            "actions": actions,
            "getters": getters,
            "consumers": [],
        })

    # useStoreName()
    for m in re.finditer(r'(use\w+Store)\s*\(\s*\)', content):
        store_hook = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        flow.append({
            "from": rel_path,
            "action": f"{store_hook}()",
            "to": store_hook,
            "file": rel_path,
            "type": "read",
        })

    return {"stores": stores, "flow": flow}


# ─── Vuex ──────────────────────────────────────────────────────

def _extract_vuex_state(content: str, rel_path: str) -> Dict[str, Any]:
    """Extract Vuex store definitions."""
    stores = []
    flow = []

    has_vuex = bool(re.search(
        r'(?:from\s+[\'"]vuex[\'"]|import\s+.*vuex|Vuex\.Store)',
        content
    ))
    if not has_vuex:
        return {"stores": [], "flow": []}

    # new Vuex.Store({ state, getters, mutations, actions })
    for m in re.finditer(
        r'(?:new\s+Vuex\.Store|createStore)\s*\(\s*\{',
        content
    ):
        line_num = content[:m.start()].count('\n') + 1

        store_body = content[m.end():m.end() + 5000]
        store_end = _find_matching_brace(store_body)
        store_body = store_body[:store_end]

        # State properties
        slices = []
        state_match = re.search(r'state\s*:\s*\{([^}]+)\}', store_body, re.DOTALL)
        if state_match:
            for prop_m in re.finditer(r'(\w+)\s*:', state_match.group(1)):
                slices.append({"name": prop_m.group(1)})

        # Mutations
        mutations = []
        mut_section = _extract_section(store_body, 'mutations')
        if mut_section:
            for mut_m in re.finditer(r'(\w+)\s*\(', mut_section):
                mut_name = mut_m.group(1)
                if not _is_js_keyword_or_builtin(mut_name):
                    mutations.append(mut_name)
                    flow.append({
                        "from": "component",
                        "action": f"commit('{mut_name}')",
                        "to": "vuex_store",
                        "file": rel_path,
                        "type": "write",
                    })

        # Actions
        actions = []
        act_section = _extract_section(store_body, 'actions')
        if act_section:
            for act_m in re.finditer(r'(?:async\s+)?(\w+)\s*\(', act_section):
                act_name = act_m.group(1)
                if not _is_js_keyword_or_builtin(act_name):
                    actions.append(act_name)
                    flow.append({
                        "from": "component",
                        "action": f"dispatch('{act_name}')",
                        "to": "vuex_store",
                        "file": rel_path,
                        "type": "write",
                    })

        # Getters
        getters = []
        get_section = _extract_section(store_body, 'getters')
        if get_section:
            for get_m in re.finditer(r'(\w+)\s*[:=]\s*\(', get_section):
                getter_name = get_m.group(1)
                if not _is_js_keyword_or_builtin(getter_name):
                    getters.append(getter_name)

        stores.append({
            "name": "vuexStore",
            "type": "store",
            "framework": "vuex",
            "defined_in": rel_path,
            "line": line_num,
            "slices": slices,
            "actions": actions,
            "mutations": mutations,
            "getters": getters,
            "consumers": [],
        })

    # mapState, mapGetters, mapActions, mapMutations
    for m in re.finditer(r'map(State|Getters|Actions|Mutations)\s*\(\s*\[([^\]]+)\]', content):
        vuex_type = m.group(1)
        names = [n.strip().strip("'\"") for n in m.group(2).split(',')]
        for name in names:
            flow.append({
                "from": rel_path,
                "action": f"map{vuex_type}({name})",
                "to": "vuex_store",
                "file": rel_path,
                "type": "read" if vuex_type in {"State", "Getters"} else "write",
            })

    return {"stores": stores, "flow": flow}


# ─── Recoil ────────────────────────────────────────────────────

def _extract_recoil_state(content: str, rel_path: str) -> Dict[str, Any]:
    """Extract Recoil atom and selector definitions."""
    stores = []
    flow = []

    has_recoil = bool(re.search(
        r'(?:from\s+[\'"]recoil[\'"]|import\s+.*recoil)',
        content
    ))
    if not has_recoil and not re.search(r'\batom\s*\(|selector\s*\(', content):
        return {"stores": [], "flow": []}

    # atom({ key: 'name', default: ... })
    for m in re.finditer(
        r'(?:const|let|var)\s+(\w+)\s*=\s*atom\s*\(\s*\{[^}]*key\s*:\s*[\'"](\w+)[\'"]',
        content
    ):
        var_name = m.group(1)
        atom_key = m.group(2)
        line_num = content[:m.start()].count('\n') + 1

        # Try to extract default value
        default_val = None
        nearby = content[m.start():m.start() + 500]
        dm = re.search(r'default\s*:\s*([^,}]+)', nearby)
        if dm:
            default_val = dm.group(1).strip()[:100]

        stores.append({
            "name": atom_key,
            "type": "atom",
            "framework": "recoil",
            "defined_in": rel_path,
            "line": line_num,
            "var_name": var_name,
            "default": default_val,
            "slices": [],
            "actions": [],
            "consumers": [],
        })

    # selector({ key: 'name', get: ... })
    for m in re.finditer(
        r'(?:const|let|var)\s+(\w+)\s*=\s*selector\s*\(\s*\{[^}]*key\s*:\s*[\'"](\w+)[\'"]',
        content
    ):
        var_name = m.group(1)
        selector_key = m.group(2)
        line_num = content[:m.start()].count('\n') + 1

        stores.append({
            "name": selector_key,
            "type": "atom",
            "framework": "recoil",
            "defined_in": rel_path,
            "line": line_num,
            "var_name": var_name,
            "is_derived": True,
            "slices": [],
            "actions": [],
            "consumers": [],
        })

    # useRecoilState, useRecoilValue, useSetRecoilState
    for m in re.finditer(
        r'use(RecoilState|RecoilValue|SetRecoilState)\s*\(\s*(\w+)\s*\)',
        content
    ):
        hook_type = m.group(1)
        atom_name = m.group(2)
        line_num = content[:m.start()].count('\n') + 1
        flow_type = "read" if hook_type == "RecoilValue" else "write" if hook_type == "SetRecoilState" else "read_write"
        flow.append({
            "from": rel_path,
            "action": f"use{hook_type}({atom_name})",
            "to": atom_name,
            "file": rel_path,
            "type": flow_type,
        })

    return {"stores": stores, "flow": flow}


# ─── Jotai ─────────────────────────────────────────────────────

def _extract_jotai_state(content: str, rel_path: str) -> Dict[str, Any]:
    """Extract Jotai atom definitions."""
    stores = []
    flow = []

    has_jotai = bool(re.search(
        r'(?:from\s+[\'"]jotai[\'"]|import\s+.*jotai)',
        content
    ))
    if not has_jotai:
        return {"stores": [], "flow": []}

    # const countAtom = atom(0) or atom((get) => ...)
    for m in re.finditer(
        r'(?:const|let|var)\s+(\w+Atom)\s*=\s*atom\s*\(',
        content
    ):
        atom_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1

        # Determine if it's a derived atom or primitive
        after = content[m.end():m.end() + 100]
        is_derived = after.strip().startswith('(') or 'get(' in after

        stores.append({
            "name": atom_name,
            "type": "atom",
            "framework": "jotai",
            "defined_in": rel_path,
            "line": line_num,
            "is_derived": is_derived,
            "slices": [],
            "actions": [],
            "consumers": [],
        })

    # useAtom(atomName)
    for m in re.finditer(r'useAtom\s*\(\s*(\w+Atom)\s*\)', content):
        atom_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        flow.append({
            "from": rel_path,
            "action": f"useAtom({atom_name})",
            "to": atom_name,
            "file": rel_path,
            "type": "read_write",
        })

    return {"stores": stores, "flow": flow}


# ─── XState ────────────────────────────────────────────────────

def _extract_xstate_state(content: str, rel_path: str) -> Dict[str, Any]:
    """Extract XState machine definitions."""
    stores = []
    flow = []

    has_xstate = bool(re.search(
        r'(?:from\s+[\'"]xstate[\'"]|import\s+.*xstate)',
        content
    ))
    if not has_xstate and not re.search(r'createMachine|StateMachine', content):
        return {"stores": [], "flow": []}

    # createMachine({ id: 'name', initial: 'state', states: { ... } })
    for m in re.finditer(
        r'(?:const|let|var)\s+(\w+)\s*=\s*createMachine\s*\(\s*\{[^}]*id\s*:\s*[\'"](\w+)[\'"]',
        content
    ):
        var_name = m.group(1)
        machine_id = m.group(2)
        line_num = content[:m.start()].count('\n') + 1

        # Extract states from the machine
        machine_body = content[m.end():m.end() + 5000]
        states = []
        for state_m in re.finditer(r'(\w+)\s*:\s*\{', machine_body[:2000]):
            state_name = state_m.group(1)
            if state_name not in {"on", "entry", "exit", "invoke", "meta", "tags", "type", "always", "after"}:
                states.append(state_name)

        stores.append({
            "name": machine_id,
            "type": "machine",
            "framework": "xstate",
            "defined_in": rel_path,
            "line": line_num,
            "var_name": var_name,
            "states": states,
            "slices": [],
            "actions": [],
            "consumers": [],
        })

    # useMachine(machineName)
    for m in re.finditer(r'useMachine\s*\(\s*(\w+)\s*\)', content):
        machine_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        flow.append({
            "from": rel_path,
            "action": f"useMachine({machine_name})",
            "to": machine_name,
            "file": rel_path,
            "type": "read_write",
        })

    return {"stores": stores, "flow": flow}


# ─── Module-level State (JS) ───────────────────────────────────

def _extract_js_global_state(content: str, rel_path: str) -> Dict[str, Any]:
    """Extract module-level global variables and singletons in JS/TS."""
    stores = []
    flow = []

    # Skip obvious config files and test files
    if any(x in rel_path for x in ['.test.', '.spec.', '.config.', 'jest.', 'webpack.']):
        return {"stores": [], "flow": []}

    # v6→v5.8: Expanded skip list for constants that are NOT mutable state.
    # ALL_CAPS patterns are immutable constants, not state stores.
    # PascalCase patterns that are React components or class instantiations
    # are also not state.
    CONSTANT_SKIP_PATTERNS = {
        # Common environment/config constants
        'URL', 'API', 'PORT', 'HOST', 'ENV', 'VERSION', 'MAX', 'MIN',
        'DEFAULT', 'NULL', 'UNDEFINED', 'TRUE', 'FALSE', 'PI',
        # Common application constants that are not state
        'LOGO', 'ICON', 'COLOR', 'COLOUR', 'THEME', 'NAME', 'TITLE',
        'PATH', 'KEY', 'ID', 'TOKEN', 'SECRET', 'TYPE', 'STATUS',
        'LABEL', 'TEXT', 'DESC', 'DESCRIPTION', 'VALUE', 'DATA',
        'TIMEOUT', 'DELAY', 'INTERVAL', 'LIMIT', 'SIZE', 'LENGTH',
        'WIDTH', 'HEIGHT', 'DEPTH', 'OFFSET', 'INDEX', 'COUNT',
        'PREFIX', 'SUFFIX', 'SEPARATOR', 'DELIMITER', 'FORMAT',
        'PATTERN', 'REGEX', 'MASK', 'TEMPLATE', 'SCHEMA',
        # v5.8: Node.js globals and built-in aliases
        'ROOT', 'HOME', 'DIR', 'DIRNAME', 'FILENAME', 'BASENAME',
        'EXTNAME', 'JOIN', 'RESOLVE', 'NORMALIZE', 'RELATIVE',
        'CLI', 'VERBOSE', 'CHECK', 'PRUNE', 'DEBUG', 'LOG',
        'WARN', 'ERROR', 'INFO', 'TRACE', 'FATAL',
        # v5.8: Common path/config constants that are just aliases
        'CWD', 'PWD', 'TMP', 'TEMP', 'CACHE', 'CONFIG', 'CONF',
        'OPT', 'OPTS', 'ARGS', 'ARGV', 'ENV_PATH',
        'SRC', 'DIST', 'BUILD', 'OUT', 'OUTPUT', 'PUBLIC',
        'STATIC', 'ASSETS', 'LIB', 'VENDOR', 'PKG',
        # v5.8: Import aliases and re-exports
        'APP', 'SERVER', 'ROUTER', 'DB', 'CLIENT', 'HANDLER',
        'MIDDLEWARE', 'SERVICE', 'CONTROLLER', 'MODEL', 'SCHEMA_OBJ',
        'VALIDATOR', 'PARSER', 'RENDERER', 'PROVIDER',
    }

    # v5.8: Node.js global names that should never be classified as state stores.
    # These are built-in globals (__dirname, __filename, process, etc.)
    # and common CLI/framework constants that are just references, not state.
    NODEJS_GLOBAL_SKIP = {
        '__dirname', '__filename', '__proto__', '__defineGetter__',
        '__defineSetter__', '__lookupGetter__', '__lookupSetter__',
        'process', 'global', 'globalThis', 'Buffer', 'console',
        'module', 'exports', 'require', 'arguments', 'this',
        'window', 'document', 'navigator', 'location', 'history',
        'localStorage', 'sessionStorage', 'fetch', 'XMLHttpRequest',
        'Promise', 'Symbol', 'Map', 'Set', 'WeakMap', 'WeakSet',
        'Proxy', 'Reflect', 'Array', 'Object', 'String', 'Number',
        'Boolean', 'Function', 'Date', 'RegExp', 'Error',
        'EvalError', 'RangeError', 'ReferenceError', 'SyntaxError',
        'TypeError', 'URIError', 'ArrayBuffer', 'DataView',
        'Float32Array', 'Float64Array', 'Int8Array', 'Int16Array',
        'Int32Array', 'Uint8Array', 'Uint16Array', 'Uint32Array',
        'Uint8ClampedArray', 'BigInt', 'BigInt64Array', 'BigUint64Array',
    }

    # v5.8: Skip variables whose value is a path.resolve/path.join call
    # or a simple environment variable reference — these are config, not state.
    VALUE_SKIP_PATTERNS = [
        r'^path\.(resolve|join|normalize|dirname|basename|extname|relative)\s*\(',
        r'^process\.env\.',
        r'^import\.meta\.',
        r'^require\.(resolve|cache|main)',
        r'^os\.(homedir|tmpdir|platform|arch|cpus|networkInterfaces)',
        r'^__dirname',
        r'^__filename',
        r'^process\.cwd\s*\(\)',
        r'^fileURLToPath',
        r'^dirname\s*\(',
        r'^basename\s*\(',
        r'^extname\s*\(',
    ]

    lines = content.split('\n')
    for i, line in enumerate(lines):
        stripped = line.strip()

        # Module-level const/let/var with initial values (potential globals)
        # Only match if the line is NOT indented (module-level, not inside a function/class)
        if not line[0].isspace() if line else True:
            m = re.match(r'^(?:export\s+)?(?:const|let|var)\s+([A-Z_]\w+)\s*=\s*(.*)', stripped)
        else:
            m = None
        if m:
            var_name = m.group(1)
            value_part = m.group(2).strip() if m.group(2) else ""

            # v6: Skip ALL_CAPS constants — they are immutable, not state.
            # A name like MAX_FILES, FETCH_TIMEOUT_MS is a constant.
            if var_name == var_name.upper() and '_' in var_name:
                continue

            # Skip common non-state constants
            if var_name in CONSTANT_SKIP_PATTERNS or len(var_name) <= 2:
                continue

            # v5.8: Skip Node.js built-in globals
            if var_name in NODEJS_GLOBAL_SKIP:
                continue

            # v5.8: Skip ALL_CAPS constants even without underscore
            # (e.g., VERBOSE, CLI, ROOT are all-caps single-word constants)
            if var_name == var_name.upper() and len(var_name) >= 3:
                continue

            # Skip TypeScript type/interface/enum definitions
            if _is_typescript_type_definition(content, var_name, i):
                continue

            # Skip const enum declarations (TypeScript)
            if re.match(r'^const\s+enum\s+', stripped):
                continue

            # v5.8: Skip variables whose value is a path/env reference
            # (e.g., ROOT = path.resolve(...), PORT = process.env.PORT)
            is_path_or_env = False
            for pat in VALUE_SKIP_PATTERNS:
                if re.match(pat, value_part):
                    is_path_or_env = True
                    break
            if is_path_or_env:
                continue

            # v5.8: Skip import-like assignments
            # (e.g., const Router = express.Router(), const db = mongoose.connection)
            if re.match(r'^[a-zA-Z]+\.[A-Z]', value_part):
                # Like express.Router(), mongoose.connection — not state
                continue

            # v6: Skip React components — PascalCase + arrow function or function
            # A line like "const Logo = () =>" or "const Button = function" is NOT state.
            # Also handles: "const X: React.FC<Props> = () =>", "const X = forwardRef(...)",
            # "const X = memo(...)", "const X = styled.div(...)", etc.
            if value_part.startswith('((') or value_part.startswith('()') or value_part.startswith('function'):
                continue
            # Arrow functions with destructured props: "const X = ({ prop1, prop2 })" or
            # "const X = ({ prop1 }: Props)" — React component pattern.
            # Even without '=>' on the same line, ({...}) is destructured props.
            if value_part.startswith('({'):
                continue
            # Arrow functions with optional type annotation: "value =>", "() =>", "<T>(...) =>"
            if '=>' in value_part and not value_part.startswith('{'):
                continue
            # Skip forwardRef, memo, styled, createStyled, etc.
            # Handle generic type params: forwardRef<T>(...), memo<T>(...)
            if re.match(r'^(forwardRef|memo|styled|createStyled|withStyles|connect|compose)\b', value_part):
                continue
            # Skip JSX components: "const X = <SomeComponent"
            if value_part.startswith('<'):
                continue
            # Skip known UI component library patterns (Radix, Headless UI, etc.)
            # e.g., "const DropdownMenu = Root" or "const X = SomeLibrary.X"
            if re.match(r'^[A-Z]\w*\.\w+', value_part):
                continue
            # Skip re-exports from UI libraries: "const X = Primitive"
            # where Primitive is a PascalCase import (likely a component)
            if re.match(r'^[A-Z]\w*$', value_part) and var_name[0].isupper() and '_' not in var_name:
                # Heuristic: if both the variable name and value are PascalCase single words,
                # this is likely a component alias, not state.
                continue

            # Skip Svelte store creators — they are detected by _detect_svelte_stores()
            if re.match(r'^(writable|readable|derived)\s*\(', value_part):
                continue

            # v6.2: Skip React Context patterns — they are detected by _extract_react_context().
            # Variables ending in "Context" that are assigned createContext() are
            # React Context objects, not generic module-level state.
            if var_name.endswith('Context'):
                continue
            # Also skip if value is createContext(...)
            if re.match(r'^createContext\s*\(', value_part):
                continue

            # v6: Skip class instantiations of known non-state patterns
            # "const x = createSomething()" is a factory, not necessarily state
            # But "const x = createStore()" IS state
            if re.match(r'create(?!Store|Context|Slice|Reducer|State)', value_part):
                # Skip factories that are NOT state-related
                pass

            # Skip export const X: SomeType = ... that are just type exports
            # (e.g., export const MySchema: SomeType = { ... } where the type annotation
            # indicates this is a schema/definition, not mutable state)
            if re.match(r'^(?:export\s+)?(?:const|let|var)\s+\w+\s*:\s*(?:Readonly|Partial|Record|Pick|Omit|Required|z\.)', stripped):
                continue

            # Only classify as state if the value looks mutable
            # Mutable patterns: object literal {}, array [], Map, Set, new SomeClass
            is_mutable = bool(re.match(r'^(\{|\[|new\s|Map|Set|WeakMap|WeakSet)', value_part))
            # Immutable patterns: string, number, boolean, null, undefined, template literal
            is_immutable = bool(re.match(r'^([\'"`\d]|true|false|null|undefined|`)', value_part))

            if is_immutable:
                continue

            # Classify as module_constant if it's a simple constant or has no mutations
            # module_constant = immutable constant, global = mutable state
            is_simple_const = _is_simple_constant(value_part)
            store_type = "module_constant" if (is_simple_const or not is_mutable) else "global"
            framework = "module_level_js"

            stores.append({
                "name": var_name,
                "type": store_type,
                "framework": framework,
                "defined_in": rel_path,
                "line": i + 1,
                "slices": [],
                "actions": [],
                "consumers": [],
                "mutable": is_mutable,
            })

    # Singleton patterns: const instance = new ClassName()
    for m in re.finditer(
        r'(?:const|let|var)\s+(\w+Instance|\w+Singleton|\w+Manager)\s*=\s*new\s+(\w+)',
        content
    ):
        var_name = m.group(1)
        class_name = m.group(2)
        line_num = content[:m.start()].count('\n') + 1
        stores.append({
            "name": var_name,
            "type": "global",
            "framework": "module_level_js",
            "defined_in": rel_path,
            "line": line_num,
            "class": class_name,
            "slices": [],
            "actions": [],
            "consumers": [],
        })

    # v6: Skip module.exports scanning — it produces massive false positives.
    # Every exported utility function gets classified as a "state store",
    # which is incorrect. Module exports are API surfaces, not state.
    # Only track stateful singletons (already handled above).

    return {"stores": stores, "flow": flow}


# ─── Module-level State (Python) ───────────────────────────────

def _extract_python_global_state(content: str, rel_path: str) -> Dict[str, Any]:
    """Extract module-level global variables and singletons in Python."""
    stores = []
    flow = []

    # Skip test and config files
    if any(x in rel_path for x in ['test_', 'conftest', 'settings.py', 'config.py']):
        return {"stores": [], "flow": []}

    # v5.8: Expanded skip list for Python constants that are NOT mutable state.
    PY_CONSTANT_SKIP = {
        'URL', 'API', 'PORT', 'HOST', 'ENV', 'VERSION', 'MAX', 'MIN', 'DEBUG', 'LOG',
        'ROOT', 'HOME', 'BASE_DIR', 'BASE_PATH', 'PROJECT_ROOT', 'SRC_DIR',
        'CLI', 'VERBOSE', 'CHECK', 'PRUNE', 'INFO', 'WARN', 'ERROR', 'TRACE',
        'CWD', 'PWD', 'TMP', 'TEMP', 'CACHE', 'CONFIG', 'CONF',
        'APP', 'SERVER', 'DB', 'CLIENT', 'NAME', 'TITLE', 'PATH',
        'KEY', 'ID', 'TOKEN', 'SECRET', 'TYPE', 'STATUS', 'DEFAULT',
        'PREFIX', 'SUFFIX', 'SEPARATOR', 'DELIMITER', 'FORMAT',
        'PATTERN', 'REGEX', 'SCHEMA', 'TIMEOUT', 'DELAY', 'LIMIT',
    }

    # v5.8: Python builtins and common stdlib aliases
    PY_BUILTIN_SKIP = {
        'True', 'False', 'None', 'NotImplemented', 'Ellipsis',
        '__name__', '__file__', '__doc__', '__package__',
        '__builtins__', '__all__', '__path__', '__spec__',
        '__loader__', '__cached__', '__version__',
    }

    # v5.9: Python type alias patterns — these are type definitions, NOT state.
    # Matches: X: TypeAlias = ..., X = TypeAlias, X: Type[...], X = Union[...],
    # X: Optional[...] = None, X = Callable[..., ...], etc.
    # Also matches prefixed forms: t.Union, t.Optional, typing.Union, etc.
    PY_TYPE_ALIAS_VALUE_PATTERNS = re.compile(
        r'^(?:TypeAlias|Type\[|Union\[|Optional\[|Callable\[|Literal\['
        r'|Annotated\[|Final\[|ClassVar\[|Sequence\[|Mapping\['
        r'|Iterable\[|Iterator\[|Awaitable\[|AsyncIterator\['
        r'|Protocol\[|TypedDict|NamedTuple|Enum\('
        r'|typing\.|collections\.abc\.'
        r'|t\.Union|t\.Optional|t\.Callable|t\.Literal|t\.Annotated'
        r'|t\.Final|t\.ClassVar|t\.Sequence|t\.Mapping|t\.Iterable'
        r'|t\.Iterator|t\.Awaitable|t\.Protocol|t\.Type'
        r'|cabc\.|c\.Union|c\.Optional'
        r'|str\s*\||int\s*\||float\s*\||bool\s*\||bytes\s*\||None\s*\|'
        r')'
    )

    # v5.9: Names that start with underscore (private) and are NOT state.
    # Single-underscore-prefixed names are private module variables.
    PY_PRIVATE_SKIP = {
        '_external', '_anchor', '_sentinel', '_app_option', '_debug_option',
        '_env_file_option', '_internal', '_default', '_fallback', '_proxy',
        '_wrapper', '_cache', '_instance', '_registry', '_lock', '_handler',
    }

    lines = content.split('\n')
    for i, line in enumerate(lines):
        stripped = line.strip()

        # Module-level assignments (not inside functions/classes)
        if not stripped.startswith((' ', '\t')):  # Top-level
            m = re.match(r'^([A-Z_]\w+)\s*=\s*(.*)', stripped)
            if m:
                var_name = m.group(1)
                value_part = m.group(2).strip() if m.group(2) else ""

                if var_name in PY_CONSTANT_SKIP or len(var_name) <= 2:
                    continue

                # v5.8: Skip Python builtins and dunder attributes
                if var_name in PY_BUILTIN_SKIP:
                    continue

                # v5.8: Skip ALL_CAPS constants
                # (e.g., VERBOSE, CLI, ROOT are all-caps single-word constants)
                if var_name == var_name.upper() and len(var_name) >= 3:
                    continue

                # v5.9: Skip Python type aliases (TypeAlias, Type[...], Union[...], etc.)
                # These are type definitions, not runtime state.
                if PY_TYPE_ALIAS_VALUE_PATTERNS.search(value_part):
                    continue

                # v5.9: Multi-line type alias detection.
                # Many type aliases use multi-line assignment:
                #   X = (
                #       t.Union[...]
                #   )
                # The value_part is just '(' for these. Look ahead a few lines
                # to check if the continuation contains type alias patterns.
                if value_part == '(' and i + 1 < len(lines):
                    is_multiline_type_alias = False
                    for peek_idx in range(i + 1, min(i + 5, len(lines))):
                        peek_line = lines[peek_idx].strip()
                        if not peek_line or peek_line == ')':
                            continue
                        if PY_TYPE_ALIAS_VALUE_PATTERNS.search(peek_line):
                            is_multiline_type_alias = True
                            break
                    if is_multiline_type_alias:
                        continue

                # v5.9: Also detect type aliases in annotation form:
                # X: TypeAlias = ...  or  X: SomeType = ...
                type_annotation_match = re.match(
                    r'^([A-Z_]\w+)\s*:\s*(?:TypeAlias|Type\[|Union\[|Optional\[|Callable\[|'
                    r'Literal\[|Annotated\[|Final\[|ClassVar\[|Sequence\[|Mapping\['
                    r')',
                    stripped
                )
                if type_annotation_match:
                    continue

                # v5.9: Skip private module-level variables (underscore-prefixed).
                # These are internal implementation details, not global state.
                if var_name.startswith('_') and not var_name.startswith('__'):
                    # Only skip if the name is in our known private name set
                    # or if it looks like a private helper (single underscore + lowercase)
                    if var_name in PY_PRIVATE_SKIP or (len(var_name) > 1 and var_name[1:].islower()):
                        continue

                # v5.9: Skip Python TypeVar conventions (T_ prefix).
                # Names like T_shell_context_processor, T_teardown are type variables.
                if var_name.startswith('T_') and var_name[2:].isidentifier():
                    continue

                # v5.8: Skip path references and env var lookups
                if re.match(r'^(os\.path|Path|pathlib|os\.getenv|os\.environ)', value_part):
                    continue

                stores.append({
                    "name": var_name,
                    "type": "global",
                    "framework": "module_level_py",
                    "defined_in": rel_path,
                    "line": i + 1,
                    "slices": [],
                    "actions": [],
                    "consumers": [],
                })

    # Singleton pattern: instance = ClassName()
    for m in re.finditer(
        r'^(\w+(?:Instance|Singleton|Manager|Registry|Cache|Pool))\s*=\s*(\w+)\s*\(',
        content,
        re.MULTILINE
    ):
        var_name = m.group(1)
        class_name = m.group(2)
        line_num = content[:m.start()].count('\n') + 1
        stores.append({
            "name": var_name,
            "type": "global",
            "framework": "module_level_py",
            "defined_in": rel_path,
            "line": line_num,
            "class": class_name,
            "slices": [],
            "actions": [],
            "consumers": [],
        })

    return {"stores": stores, "flow": flow}


# ─── Rust State Management ──────────────────────────────────────

def _extract_rust_state(content: str, rel_path: str) -> Dict[str, Any]:
    """Extract Rust state management patterns.

    Detects:
    - Static/const items with interior mutability (AtomicX, Mutex, RwLock, OnceCell/Lock)
    - actix-web Data<T> (app state shared via web::Data)
    - Tauri State<T> (managed state)
    - Global static instances (lazy_static!, once_cell::sync::Lazy)
    - Arc<Mutex<T>> / Arc<RwLock<T>> shared state patterns
    - struct fields that are state containers
    """
    stores = []
    flow = []

    # Skip test files (too many false positives)
    if any(x in rel_path for x in ['/tests/', '/test_', '/benches/', '/examples/']):
        return {"stores": [], "flow": []}

    # Common Rust names to skip (false positive filter)
    RUST_SKIP = {
        'Ok', 'Err', 'Some', 'None', 'True', 'False',
        'MAX', 'MIN', 'LEN', 'SIZE', 'VERSION', 'NAME',
        'DEFAULT', 'NEW', 'INIT', 'START', 'END',
        'BUF', 'CAP', 'LEN', 'TAG',
    }

    # ─── Static items with interior mutability ────────────────
    # pub static COUNTER: AtomicUsize = AtomicUsize::new(0);
    # static METRICS: Lazy<Mutex<Metrics>> = Lazy::new(|| Mutex::new(Metrics::default()));
    # Also matches statics inside fn bodies (with leading whitespace)
    for m in re.finditer(
        r'(?:pub\s+)?static\s+(\w+)\s*:\s*([^=;{]+)',
        content
    ):
        var_name = m.group(1)
        type_expr = m.group(2).strip()
        line_num = content[:m.start()].count('\n') + 1

        if var_name in RUST_SKIP or len(var_name) <= 2:
            continue
        # Only skip ALL_CAPS single-word if the type is clearly immutable
        # (AtomicBool, AtomicUsize, OnceLock, etc. are ALWAYS stateful regardless of name)

        # Check for interior mutability or shared state patterns
        is_stateful = any(pattern in type_expr for pattern in [
            'Atomic', 'Mutex', 'RwLock', 'OnceCell', 'OnceLock',
            'Lazy', 'LazyLock', 'lazy_static', 'Arc', 'RefCell', 'Cell',
            'Data<', 'State<', 'Jemalloc',
        ])

        if is_stateful:
            stores.append({
                "name": var_name,
                "type": "global",
                "framework": "rust_state",
                "defined_in": rel_path,
                "line": line_num,
                "rust_type": type_expr[:100],
                "slices": [],
                "actions": [],
                "consumers": [],
            })
            # Track write access: store_name.store(...), store_name.fetch_add(...)
            for write_m in re.finditer(
                rf'\b{re.escape(var_name)}\s*\.\s*(store|fetch_add|fetch_sub|fetch_and|fetch_or|replace|swap|set|lock|write|get_mut)\s*\(',
                content
            ):
                write_line = content[:write_m.start()].count('\n') + 1
                flow.append({
                    "from": rel_path,
                    "action": f"write({var_name}.{write_m.group(1)})",
                    "to": var_name,
                    "file": rel_path,
                    "line": write_line,
                    "type": "write",
                })
            # Track read access: store_name.load(...), store_name.read(), store_name.get()
            for read_m in re.finditer(
                rf'\b{re.escape(var_name)}\s*\.\s*(load|read|get|lock)\s*\(',
                content
            ):
                read_line = content[:read_m.start()].count('\n') + 1
                flow.append({
                    "from": rel_path,
                    "action": f"read({var_name}.{read_m.group(1)})",
                    "to": var_name,
                    "file": rel_path,
                    "line": read_line,
                    "type": "read",
                })

    # ─── actix-web Data<T> app state ─────────────────────────
    # Only match Data<T> in function parameter context (actual state extraction)
    # Pattern: param: Data<Type> or param: web::Data<Type>
    # Skip trait bounds, generic impl blocks, and type aliases
    for m in re.finditer(
        r'(\w+)\s*:\s*(?:web::)?Data\s*<\s*(\w+)\s*>',
        content
    ):
        param_name = m.group(1)
        type_name = m.group(2)
        line_num = content[:m.start()].count('\n') + 1

        # Skip single-letter names (generic type parameters like T, U, D)
        if len(type_name) <= 1:
            continue
        # Skip common non-state types and Rust builtins
        if type_name in RUST_SKIP or type_name in ('Box', 'Rc', 'Arc', 'Vec', 'String', 'Option', 'Result', 'From', 'Into', 'AsRef', 'AsMut', 'Sized', 'Clone', 'Copy', 'Default', 'Debug', 'Display', 'Iterator', 'ExactSizeIterator', 'Send', 'Sync', 'BoundCodec', 'Method', 'Strategy', 'Error'):
            continue

        # Only create store if we haven't seen this type yet in this file
        already_found = any(s['name'] == type_name and s['framework'] == 'actix_web_data' for s in stores)
        if not already_found:
            stores.append({
                "name": type_name,
                "type": "store",
                "framework": "actix_web_data",
                "defined_in": rel_path,
                "line": line_num,
                "slices": [],
                "actions": [],
                "consumers": [],
            })
            # Track Data extraction: app_data: Data<Type>
            for extract_m in re.finditer(
                rf'(\w+)\s*:\s*(?:web::)?Data\s*<\s*{re.escape(type_name)}\s*>',
                content
            ):
                handler = extract_m.group(1)
                extract_line = content[:extract_m.start()].count('\n') + 1
                flow.append({
                    "from": rel_path,
                    "action": f"extract(Data<{type_name}>)",
                    "to": type_name,
                    "file": rel_path,
                    "line": extract_line,
                    "type": "read",
                })

    # ─── Tauri State<T> managed state ────────────────────────
    for m in re.finditer(
        r'tauri::State\s*<\s*[\'"]?(\w+)[\'"]?\s*>',
        content
    ):
        type_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1

        # Skip single-letter generic params
        if len(type_name) <= 1 or type_name in RUST_SKIP:
            continue

        already_found = any(s['name'] == type_name and s['framework'] == 'tauri_state' for s in stores)
        if not already_found:
            stores.append({
                "name": type_name,
                "type": "store",
                "framework": "tauri_state",
                "defined_in": rel_path,
                "line": line_num,
                "slices": [],
                "actions": [],
                "consumers": [],
            })

    # ─── lazy_static! and once_cell::sync::Lazy ──────────────
    # lazy_static! { static ref NAME: Type = ...; }
    for m in re.finditer(
        r'lazy_static!\s*\{[^}]*static\s+ref\s+(\w+)\s*:\s*([^=;]+)',
        content,
        re.DOTALL
    ):
        var_name = m.group(1)
        type_expr = m.group(2).strip()
        line_num = content[:m.start()].count('\n') + 1

        if var_name in RUST_SKIP:
            continue

        stores.append({
            "name": var_name,
            "type": "global",
            "framework": "rust_lazy_static",
            "defined_in": rel_path,
            "line": line_num,
            "rust_type": type_expr[:100],
            "slices": [],
            "actions": [],
            "consumers": [],
        })

    # ─── Arc<Mutex<T>> / Arc<RwLock<T>> shared state structs ─
    # struct AppState { db: Arc<Mutex<Database>>, cache: Arc<RwLock<Cache>> }
    for m in re.finditer(
        r'(?:pub\s+)?struct\s+(\w+State|\w+Ctx|\w+Context|\w+Env|\w+Config)\s*\{',
        content
    ):
        struct_name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1

        stores.append({
            "name": struct_name,
            "type": "store",
            "framework": "rust_struct_state",
            "defined_in": rel_path,
            "line": line_num,
            "slices": [],
            "actions": [],
            "consumers": [],
        })

    return {"stores": stores, "flow": flow}


# ─── Svelte Stores ─────────────────────────────────────────────

def _detect_svelte_stores(
    workspace: str, config: Optional[Dict] = None
) -> tuple:
    """
    Detect Svelte stores (writable, readable, derived) across the workspace.

    Two-pass approach:
      1. Scan all .svelte/.js/.ts files for store definitions
         (writable(), readable(), derived() from 'svelte/store').
      2. Scan for consumers — files that import a store and use
         $storeName, storeName.subscribe(), storeName.set(), or
         storeName.update().

    Returns:
        (stores_list, flow_list)
    """
    stores: List[Dict[str, Any]] = []
    flow: List[Dict[str, Any]] = []

    # ── Pass 1: find store definitions ──────────────────────────
    # store_name -> { file, line, store_type }
    store_defs: Dict[str, Dict[str, Any]] = {}

    svelte_extensions = {".svelte", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in svelte_extensions:
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            # Only process files that import from svelte/store
            has_svelte_store = bool(re.search(
                r'(?:from\s+[\'"]svelte/store[\'"]|import\s+.*svelte[\'"]\/store[\'"])',
                content
            ))
            if not has_svelte_store:
                continue

            # Detect writable() calls
            for m in re.finditer(
                r'(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*writable\s*\(',
                content
            ):
                store_name = m.group(1)
                line_num = content[:m.start()].count('\n') + 1
                store_defs[store_name] = {
                    "file": rel_path,
                    "line": line_num,
                    "store_type": "writable",
                }

            # Detect readable() calls
            for m in re.finditer(
                r'(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*readable\s*\(',
                content
            ):
                store_name = m.group(1)
                line_num = content[:m.start()].count('\n') + 1
                store_defs[store_name] = {
                    "file": rel_path,
                    "line": line_num,
                    "store_type": "readable",
                }

            # Detect derived() calls
            for m in re.finditer(
                r'(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*derived\s*\(',
                content
            ):
                store_name = m.group(1)
                line_num = content[:m.start()].count('\n') + 1
                store_defs[store_name] = {
                    "file": rel_path,
                    "line": line_num,
                    "store_type": "derived",
                }

    # ── Build store dicts from definitions ──────────────────────
    for store_name, info in store_defs.items():
        is_derived = info["store_type"] == "derived"
        store_type = "derived_store" if is_derived else "store"
        actions = ["set", "update"] if info["store_type"] == "writable" else []

        stores.append({
            "name": store_name,
            "type": store_type,
            "framework": "svelte_stores",
            "defined_in": info["file"],
            "line": info["line"],
            "store_type": info["store_type"],
            "slices": [],
            "actions": actions,
            "consumers": [],
        })

        flow.append({
            "from": info["file"],
            "action": f"{info['store_type']}({store_name})",
            "to": store_name,
            "file": info["file"],
            "type": "define",
        })

    # ── Pass 2: find consumers ──────────────────────────────────
    # Consumers are files that import a store and then use it via:
    #   $storeName            (Svelte auto-subscription, read)
    #   storeName.subscribe() (manual subscription, read)
    #   storeName.set()       (write)
    #   storeName.update()    (write)
    all_consumer_info: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in svelte_extensions:
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            for store_name, info in store_defs.items():
                # Skip the definition file for consumer detection
                if info["file"] == rel_path:
                    continue

                # Check if this file imports the store name
                imports_store = bool(re.search(
                    r'import\s+(?:\{[^}]*\b' + re.escape(store_name) + r'\b[^}]*\}|\*\s+as\s+\w+)\s+from',
                    content
                )) or bool(re.search(
                    r'(?:const|let|var)\s+\{[^}]*\b' + re.escape(store_name) + r'\b[^}]*\}\s*=\s*require\s*\(',
                    content
                ))

                if not imports_store:
                    continue

                # Detect $storeName usage (Svelte auto-subscription)
                dollar_pattern = r'\$' + re.escape(store_name) + r'\b'
                if re.search(dollar_pattern, content):
                    all_consumer_info[store_name].append({
                        "file": rel_path,
                        "access": "read",
                        "pattern": f"${store_name}",
                    })
                    flow.append({
                        "from": rel_path,
                        "action": f"${store_name}",
                        "to": store_name,
                        "file": rel_path,
                        "type": "read",
                    })

                # Detect storeName.subscribe()
                if re.search(re.escape(store_name) + r'\.subscribe\s*\(', content):
                    all_consumer_info[store_name].append({
                        "file": rel_path,
                        "access": "read",
                        "pattern": f"{store_name}.subscribe",
                    })
                    flow.append({
                        "from": rel_path,
                        "action": f"{store_name}.subscribe()",
                        "to": store_name,
                        "file": rel_path,
                        "type": "read",
                    })

                # Detect storeName.set()
                if re.search(re.escape(store_name) + r'\.set\s*\(', content):
                    all_consumer_info[store_name].append({
                        "file": rel_path,
                        "access": "write",
                        "pattern": f"{store_name}.set",
                    })
                    flow.append({
                        "from": rel_path,
                        "action": f"{store_name}.set()",
                        "to": store_name,
                        "file": rel_path,
                        "type": "write",
                    })

                # Detect storeName.update()
                if re.search(re.escape(store_name) + r'\.update\s*\(', content):
                    all_consumer_info[store_name].append({
                        "file": rel_path,
                        "access": "write",
                        "pattern": f"{store_name}.update",
                    })
                    flow.append({
                        "from": rel_path,
                        "action": f"{store_name}.update()",
                        "to": store_name,
                        "file": rel_path,
                        "type": "write",
                    })

    # ── Merge consumers into stores ─────────────────────────────
    for store in stores:
        sname = store["name"]
        if sname in all_consumer_info:
            store["consumers"] = all_consumer_info[sname]

    return stores, flow


def _is_svelte_workspace(workspace: str) -> bool:
    """Check whether the workspace uses Svelte/SvelteKit."""
    # Check for any .svelte files
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue
        for filename in filenames:
            if filename.endswith('.svelte'):
                return True

    # Check package.json for svelte dependency
    pkg_path = os.path.join(workspace, 'package.json')
    if os.path.isfile(pkg_path):
        try:
            with open(pkg_path, 'r', encoding='utf-8', errors='ignore') as f:
                pkg = f.read()
            if '"svelte"' in pkg:
                return True
        except IOError:
            pass

    return False


# ─── Import/Export Collection ──────────────────────────────────

def _collect_js_imports(
    content: str, rel_path: str, imports: Dict[str, Set[str]]
):
    """Collect JS/TS import statements for cross-file analysis."""
    for m in re.finditer(
        r'import\s+(?:\{([^}]+)\}|\*\s+as\s+(\w+)|(\w+))\s+from',
        content
    ):
        if m.group(1):
            names = [n.strip().split(' as ')[0].strip() for n in m.group(1).split(',')]
            for name in names:
                if name:
                    imports[rel_path].add(name)
        elif m.group(2):
            imports[rel_path].add(m.group(2))
        elif m.group(3):
            imports[rel_path].add(m.group(3))

    # CommonJS require
    for m in re.finditer(
        r'(?:const|let|var)\s+(?:\{([^}]+)\}|(\w+))\s*=\s*require\s*\(',
        content
    ):
        if m.group(1):
            names = [n.strip().split(':')[0].strip() for n in m.group(1).split(',')]
            for name in names:
                if name:
                    imports[rel_path].add(name)
        elif m.group(2):
            imports[rel_path].add(m.group(2))


def _collect_js_exports(
    content: str, rel_path: str, exports: Dict[str, List[Dict]]
):
    """Collect JS/TS export statements."""
    for m in re.finditer(
        r'export\s+(?:const|let|var|function|class|async\s+function)\s+(\w+)',
        content
    ):
        exports[rel_path].append({
            "name": m.group(1),
            "line": content[:m.start()].count('\n') + 1,
        })


def _collect_py_imports(
    content: str, rel_path: str, imports: Dict[str, Set[str]]
):
    """Collect Python import statements."""
    for line in content.split('\n'):
        stripped = line.strip()
        m = re.match(r'from\s+[\w.]+\s+import\s+(.+)', stripped)
        if m:
            names = [n.strip().split(' as ')[0].strip() for n in m.group(1).split(',')]
            for name in names:
                if name:
                    imports[rel_path].add(name)
        m = re.match(r'import\s+(.+)', stripped)
        if m:
            names = [n.strip().split(' as ')[0].strip() for n in m.group(1).split(',')]
            for name in names:
                if name:
                    imports[rel_path].add(name)


# ─── Recommendations ──────────────────────────────────────────

def _generate_state_recommendations(
    stores: List[Dict[str, Any]],
    frameworks: Set[str],
    flow: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Generate recommendations for state management improvements."""
    recommendations = []

    # Too many state management frameworks
    state_frameworks = {f for f in frameworks if f not in {"module_level_js", "module_level_py"}}
    if len(state_frameworks) > 2:
        recommendations.append({
            "type": "architecture",
            "severity": "warning",
            "message": f"Multiple state management frameworks detected: {', '.join(sorted(state_frameworks))}",
            "suggestion": "Standardize on one state management approach to reduce complexity and improve developer experience.",
        })

    # Module-level state without framework
    module_level = [s for s in stores if s.get("type") in ("global", "module_constant")]
    if len(module_level) > 10:
        recommendations.append({
            "type": "architecture",
            "severity": "warning",
            "message": f"{len(module_level)} module-level global variables/constants detected",
            "suggestion": "Consider using a proper state management library instead of scattered global variables.",
        })

    # Stores with no consumers
    no_consumers = [s for s in stores if not s.get("consumers")]
    if no_consumers:
        recommendations.append({
            "type": "dead_code",
            "severity": "info",
            "message": f"{len(no_consumers)} state definitions have no detected consumers",
            "affected": [s["name"] for s in no_consumers[:10]],
            "suggestion": "Review if these stores/atoms are actually used or can be removed.",
        })

    # Very large stores (many actions)
    large_stores = [s for s in stores if len(s.get("actions", [])) > 15]
    if large_stores:
        recommendations.append({
            "type": "architecture",
            "severity": "warning",
            "message": f"{len(large_stores)} stores have more than 15 actions (god stores)",
            "affected": [f"{s['name']} ({len(s['actions'])} actions)" for s in large_stores],
            "suggestion": "Split large stores into smaller, domain-focused slices.",
        })

    # Redux without Redux Toolkit
    if "redux" in frameworks:
        has_rtk = any(s.get("framework") == "redux" and "createSlice" in str(s) for s in stores)
        if not has_rtk:
            recommendations.append({
                "type": "modernization",
                "severity": "info",
                "message": "Redux detected but not using Redux Toolkit",
                "suggestion": "Consider migrating to Redux Toolkit for simpler, more maintainable state management.",
            })

    # Flow imbalance: too many writes, few reads (or vice versa)
    write_count = sum(1 for f in flow if f.get("type") in {"write", "write_access"})
    read_count = sum(1 for f in flow if f.get("type") in {"read", "read_write"})
    if write_count > 5 and read_count == 0:
        recommendations.append({
            "type": "correctness",
            "severity": "warning",
            "message": "State is written to but never read — potential dead state",
            "suggestion": "Verify that state updates are consumed by components.",
        })

    # Mixed Pinia and Vuex
    if "pinia" in frameworks and "vuex" in frameworks:
        recommendations.append({
            "type": "migration",
            "severity": "warning",
            "message": "Both Pinia and Vuex detected — mixing Vue state management",
            "suggestion": "Migrate fully to Pinia (the recommended Vue 3 state management).",
        })

    # Mixed Recoil and Jotai
    if "recoil" in frameworks and "jotai" in frameworks:
        recommendations.append({
            "type": "architecture",
            "severity": "info",
            "message": "Both Recoil and Jotai detected — choose one atomic state library",
            "suggestion": "Standardize on one atomic state management library for consistency.",
        })

    # Svelte stores with no $-prefix consumers
    svelte_stores = [s for s in stores if s.get("framework") == "svelte_stores"]
    svelte_no_auto_sub = [
        s for s in svelte_stores
        if not any(c.get("pattern", "").startswith("$") for c in s.get("consumers", []))
    ]
    if svelte_no_auto_sub:
        recommendations.append({
            "type": "pattern",
            "severity": "info",
            "message": f"{len(svelte_no_auto_sub)} Svelte store(s) not consumed via $ auto-subscription",
            "affected": [s["name"] for s in svelte_no_auto_sub[:10]],
            "suggestion": "Using the $storeName prefix in .svelte files enables reactive auto-subscription. "
                          "Consider using it instead of manual .subscribe() calls for simpler code.",
        })

    return recommendations
