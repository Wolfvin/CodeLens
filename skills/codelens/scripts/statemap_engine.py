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

STATE_TYPES = {"store", "context", "atom", "global", "machine", "derived_store"}


def map_state(
    workspace: str,
    store_name: Optional[str] = None,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Map all state management patterns across the workspace.

    Args:
        workspace: Absolute path to workspace
        store_name: Optional filter for a specific store name
        config: CodeLens config dict

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

    # ─── Svelte Stores (workspace-level detection) ───────────
    if _is_svelte_workspace(workspace):
        svelte_stores, svelte_flow = _detect_svelte_stores(workspace, config)
        if svelte_stores:
            frameworks_detected.add("svelte_stores")
            stores.extend(svelte_stores)
            state_flow.extend(svelte_flow)

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
            "by_type": dict(by_type),
            "files_scanned": files_scanned,
            "frameworks_detected": sorted(frameworks_detected),
        },
        "stores": stores,
        "state_flow": state_flow[:200],  # Cap flow entries
        "recommendations": recommendations,
    }


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
    """Extract React Context definitions and providers."""
    stores = []
    flow = []

    # createContext
    for m in re.finditer(
        r'(?:const|let|var)\s+(\w+Context)\s*=\s*createContext\s*\(',
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

    # useContext(ContextName)
    for m in re.finditer(r'useContext\s*\(\s*(\w+Context)\s*\)', content):
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
    for m in re.finditer(r'<(\w+Context)\.Provider\s+value\s*=\s*\{', content):
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

        # Actions
        actions = []
        action_section = re.search(r'actions\s*:\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}', store_body, re.DOTALL)
        if action_section:
            for action_m in re.finditer(r'(?:async\s+)?(\w+)\s*\(', action_section.group(1)):
                action_name = action_m.group(1)
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
        getter_section = re.search(r'getters\s*:\s*\{([^}]+)\}', store_body, re.DOTALL)
        if getter_section:
            for getter_m in re.finditer(r'(\w+)\s*[:=]\s*\(', getter_section.group(1)):
                getters.append(getter_m.group(1))

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
        mut_section = re.search(r'mutations\s*:\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}', store_body, re.DOTALL)
        if mut_section:
            for mut_m in re.finditer(r'(\w+)\s*\(', mut_section.group(1)):
                mutations.append(mut_m.group(1))
                flow.append({
                    "from": "component",
                    "action": f"commit('{mut_m.group(1)}')",
                    "to": "vuex_store",
                    "file": rel_path,
                    "type": "write",
                })

        # Actions
        actions = []
        act_section = re.search(r'actions\s*:\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}', store_body, re.DOTALL)
        if act_section:
            for act_m in re.finditer(r'(?:async\s+)?(\w+)\s*\(', act_section.group(1)):
                actions.append(act_m.group(1))
                flow.append({
                    "from": "component",
                    "action": f"dispatch('{act_m.group(1)}')",
                    "to": "vuex_store",
                    "file": rel_path,
                    "type": "write",
                })

        # Getters
        getters = []
        get_section = re.search(r'getters\s*:\s*\{([^}]+)\}', store_body, re.DOTALL)
        if get_section:
            for get_m in re.finditer(r'(\w+)\s*[:=]\s*\(', get_section.group(1)):
                getters.append(get_m.group(1))

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

    # v6: Expanded skip list for constants that are NOT mutable state.
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
    }

    lines = content.split('\n')
    for i, line in enumerate(lines):
        stripped = line.strip()

        # Module-level const/let/var with initial values (potential globals)
        m = re.match(r'^(?:export\s+)?(?:const|let|var)\s+([A-Z_]\w+)\s*=\s*(.*)', stripped)
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

            # v6: Skip React components — PascalCase + arrow function or function
            # A line like "const Logo = () =>" or "const Button = function" is NOT state.
            # Also handles: "const X: React.FC<Props> = () =>", "const X = forwardRef(...)",
            # "const X = memo(...)", "const X = styled.div(...)", etc.
            if value_part.startswith('((') or value_part.startswith('()') or value_part.startswith('function'):
                continue
            # Arrow functions with optional type annotation: "value =>", "() =>", "<T>(...) =>"
            if '=>' in value_part and not value_part.startswith('{'):
                continue
            # Skip forwardRef, memo, styled, createStyled, etc.
            if re.match(r'^(forwardRef|memo|styled|createStyled|withStyles|connect|compose)\s*\(', value_part):
                continue
            # Skip JSX components: "const X = <SomeComponent"
            if value_part.startswith('<'):
                continue

            # Skip Svelte store creators — they are detected by _detect_svelte_stores()
            if re.match(r'^(writable|readable|derived)\s*\(', value_part):
                continue

            # v6: Skip class instantiations of known non-state patterns
            # "const x = createSomething()" is a factory, not necessarily state
            # But "const x = createStore()" IS state
            if re.match(r'create(?!Store|Context|Slice|Reducer|State)', value_part):
                # Skip factories that are NOT state-related
                pass

            # Only classify as state if the value looks mutable
            # Mutable patterns: object literal {}, array [], Map, Set, new SomeClass
            is_mutable = bool(re.match(r'^(\{|\[|new\s|Map|Set|WeakMap|WeakSet)', value_part))
            # Immutable patterns: string, number, boolean, null, undefined, template literal
            is_immutable = bool(re.match(r'^([\'"`\d]|true|false|null|undefined|`)', value_part))

            if is_immutable:
                continue

            # For things that don't match either pattern, include them
            # (could be function calls that return mutable objects)
            store_type = "global"
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

    lines = content.split('\n')
    for i, line in enumerate(lines):
        stripped = line.strip()

        # Module-level assignments (not inside functions/classes)
        if not stripped.startswith((' ', '\t')):  # Top-level
            m = re.match(r'^([A-Z_]\w+)\s*=\s*', stripped)
            if m:
                var_name = m.group(1)
                skip = {'URL', 'API', 'PORT', 'HOST', 'ENV', 'VERSION', 'MAX', 'MIN', 'DEBUG', 'LOG'}
                if var_name in skip or len(var_name) <= 2:
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
    module_level = [s for s in stores if s.get("type") == "global"]
    if len(module_level) > 10:
        recommendations.append({
            "type": "architecture",
            "severity": "warning",
            "message": f"{len(module_level)} module-level global variables detected",
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
