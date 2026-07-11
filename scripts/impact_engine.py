"""
Impact Analysis Engine for CodeLens
Predicts what will be affected if a symbol is modified or deleted.
Combines frontend + backend tracing with risk assessment.
"""

import os
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict

# Re-use the std lib methods list from edge_resolver to filter out
# built-in JS/TS/Rust/Python methods from impact analysis.
try:
    from edge_resolver import _STD_LIB_METHODS
except ImportError:
    _STD_LIB_METHODS = frozenset()


def analyze_impact(
    name: str,
    workspace: str,
    action: str = "modify",
    domain: str = "auto",
    depth: int = 5
) -> Dict[str, Any]:
    """
    Analyze the impact of modifying or deleting a symbol.

    Args:
        name: Symbol name to analyze
        workspace: Absolute path to workspace
        action: "modify" or "delete"
        domain: "frontend", "backend", or "auto"
        depth: Maximum trace depth

    Returns:
        Dict with affected items, risk assessment, and recommendations
    """
    workspace = os.path.abspath(workspace)
    node_by_fn = None  # Will be set in backend block
    affected = {
        "direct": [],       # Direct dependents (1 hop)
        "indirect": [],     # Indirect dependents (2+ hops)
        "files": [],        # Affected files
        "tests": [],        # Likely test files affected
    }
    risk = "low"
    recommendations = []

    # ─── Backend Impact ─────────────────────────────────
    if domain in ("backend", "auto"):
        from registry import load_backend_registry
        backend = load_backend_registry(workspace)
        nodes = backend.get("nodes", [])
        edges = backend.get("edges", [])

        # Build adjacency: who calls whom
        callers_map: Dict[str, List[Dict]] = defaultdict(list)
        callees_map: Dict[str, List[Dict]] = defaultdict(list)
        node_by_id: Dict[str, Dict] = {}
        node_by_fn: Dict[str, List[Dict]] = defaultdict(list)

        for node in nodes:
            node_by_id[node["id"]] = node
            node_by_fn[node["fn"]].append(node)

        for edge in edges:
            from_id = edge.get("from", "")
            to_id = edge.get("to", "")
            if to_id:
                callers_map[to_id].append(edge)
            if from_id:
                callees_map[from_id].append(edge)

        # Find target nodes
        target_nodes = node_by_fn.get(name, [])

        # v6.1: Fuzzy matching fallback — try substring/prefix match if exact match fails
        if not target_nodes:
            name_lower = name.lower()
            # Try prefix match first (e.g., "create" matches "createDocument")
            prefix_matches = [n for fn, nodes in node_by_fn.items()
                              if fn.lower().startswith(name_lower) for n in nodes]
            if prefix_matches:
                target_nodes = prefix_matches
            else:
                # Try substring match (e.g., "sign" matches "signDocument")
                substring_matches = [n for fn, nodes in node_by_fn.items()
                                     if name_lower in fn.lower() for n in nodes]
                # Limit fuzzy results to avoid overwhelming output
                if substring_matches:
                    target_nodes = substring_matches[:20]

        for target_node in target_nodes:
            target_id = target_node["id"]

            # Direct callers (1 hop)
            direct_caller_edges = callers_map.get(target_id, [])
            for edge in direct_caller_edges:
                from_id = edge.get("from", "")
                caller_node = node_by_id.get(from_id)
                if caller_node:
                    affected["direct"].append({
                        "type": caller_node.get("type", "function"),
                        "name": caller_node["fn"],
                        "file": caller_node.get("file", ""),
                        "line": caller_node.get("line", 0),
                        "relation": "calls " + name,
                        "domain": "backend"
                    })

            # Direct callees (1 hop)
            direct_callee_edges = callees_map.get(target_id, [])
            for edge in direct_callee_edges:
                to_id = edge.get("to", "")
                to_fn = edge.get("to_fn", "")
                callee_node = node_by_id.get(to_id)
                if callee_node:
                    affected["direct"].append({
                        "type": callee_node.get("type", "function"),
                        "name": callee_node["fn"],
                        "file": callee_node.get("file", ""),
                        "line": callee_node.get("line", 0),
                        "relation": "called by " + name,
                        "domain": "backend"
                    })
                elif to_fn:
                    # Skip built-in std lib methods (setTimeout, then, get, etc.)
                    # These are not project-defined functions and should not
                    # appear in impact analysis.
                    if to_fn in _STD_LIB_METHODS:
                        continue
                    affected["direct"].append({
                        "type": "function",  # Unresolved node, fallback to function
                        "name": to_fn,
                        "file": "",
                        "line": 0,
                        "relation": "called by " + name,
                        "resolved": False,
                        "domain": "backend"
                    })

            # Indirect callers (2+ hops) via BFS
            visited = {target_id}
            queue = [(target_id, 1)]

            while queue:
                current_id, current_depth = queue.pop(0)
                if current_depth >= depth:
                    continue

                for edge in callers_map.get(current_id, []):
                    from_id = edge.get("from", "")
                    if from_id and from_id not in visited:
                        visited.add(from_id)
                        caller_node = node_by_id.get(from_id)
                        if caller_node and current_depth >= 1:
                            affected["indirect"].append({
                                "type": caller_node.get("type", "function"),
                                "name": caller_node["fn"],
                                "file": caller_node.get("file", ""),
                                "line": caller_node.get("line", 0),
                                "relation": f"{current_depth + 1} hops from {name}",
                                "depth": current_depth + 1,
                                "domain": "backend"
                            })
                            queue.append((from_id, current_depth + 1))

            # If deleting, all callees that are only called by this function become at-risk
            if action == "delete":
                for edge in direct_callee_edges:
                    to_id = edge.get("to", "")
                    if to_id:
                        callee_node = node_by_id.get(to_id)
                        if callee_node:
                            # Check if this callee has other callers besides the target
                            other_callers = [
                                e for e in callers_map.get(to_id, [])
                                if e.get("from", "") != target_id
                            ]
                            if not other_callers:
                                affected["indirect"].append({
                                    "type": callee_node.get("type", "function"),
                                    "name": callee_node["fn"],
                                    "file": callee_node.get("file", ""),
                                    "line": callee_node.get("line", 0),
                                    "relation": f"will become dead code (only called by {name})",
                                    "risk": "high",
                                    "domain": "backend"
                                })

            # Check for impl block siblings
            if target_node.get("impl_for"):
                impl_siblings = [
                    n for n in nodes
                    if n.get("impl_for") == target_node["impl_for"]
                    and n["id"] != target_id
                ]
                for sibling in impl_siblings:
                    affected["direct"].append({
                        "type": sibling.get("type", "function"),
                        "name": sibling["fn"],
                        "file": sibling.get("file", ""),
                        "line": sibling.get("line", 0),
                        "relation": f"same impl block ({target_node['impl_for']})",
                        "domain": "backend"
                    })

    # ─── Frontend Impact ────────────────────────────────
    if domain in ("frontend", "auto"):
        from registry import load_frontend_registry
        frontend = load_frontend_registry(workspace)

        name_lower = name.lower()
        for cls in frontend.get("classes", []):
            # v6.1: Also try fuzzy match on class names
            if cls["name"] == name or name_lower in cls["name"].lower() or cls["name"].lower().startswith(name_lower):
                # Who uses this class in JS/TSX
                for js_ref in cls.get("js", []):
                    affected["direct"].append({
                        "type": "class_usage",
                        "name": name,
                        "file": js_ref.get("path", ""),
                        "line": js_ref.get("line", 0),
                        "relation": "uses class " + name,
                        "source": js_ref.get("source"),
                        "domain": "frontend"
                    })

                # Where is it defined in CSS
                for css_ref in cls.get("css", []):
                    affected["direct"].append({
                        "type": "css_definition",
                        "name": name,
                        "file": css_ref.get("path", ""),
                        "line": css_ref.get("line", 0),
                        "relation": "defines class " + name,
                        "domain": "frontend"
                    })

                # If deleting a CSS class, check for Tailwind implications
                if action == "delete" and cls.get("status") == "active":
                    affected["indirect"].append({
                        "type": "visual_impact",
                        "name": name,
                        "relation": f"visual styling will break in {cls['ref_count']} location(s)",
                        "risk": "high",
                        "domain": "frontend"
                    })

        for id_entry in frontend.get("ids", []):
            if id_entry["name"] == name:
                for js_ref in id_entry.get("js", []):
                    affected["direct"].append({
                        "type": "id_usage",
                        "name": name,
                        "file": js_ref.get("path", ""),
                        "line": js_ref.get("line", 0),
                        "relation": "references ID " + name,
                        "domain": "frontend"
                    })

                for css_ref in id_entry.get("css", []):
                    affected["direct"].append({
                        "type": "css_definition",
                        "name": name,
                        "file": css_ref.get("path", ""),
                        "line": css_ref.get("line", 0),
                        "relation": "styles ID " + name,
                        "domain": "frontend"
                    })

                if id_entry.get("status") == "collision":
                    affected["direct"].append({
                        "type": "collision",
                        "name": name,
                        "relation": "ID collision — multiple HTML elements share this ID",
                        "risk": "critical",
                        "domain": "frontend"
                    })

    # ─── Compute affected files ────────────────────────
    all_affected = affected["direct"] + affected["indirect"]
    file_set = set()
    for item in all_affected:
        f = item.get("file", "")
        if f:
            file_set.add(f)
    affected["files"] = sorted(file_set)

    # ─── Detect likely test files ──────────────────────
    test_files = set()
    for f in affected["files"]:
        # Common test file patterns
        base = f.rsplit(".", 1)[0] if "." in f else f
        test_patterns = [
            f"{base}.test.ts", f"{base}.test.js", f"{base}.spec.ts", f"{base}.spec.js",
            f"{base}.test.tsx", f"{base}.spec.tsx",
        ]
        # Rust/Python "_test" suffix convention — only applicable to files of
        # that extension. Bug: str.replace() is a no-op when the extension
        # doesn't match (e.g. a .ts file has no ".rs"/".py" substring), so the
        # "pattern" silently degenerated into the original filename `f` itself
        # — which trivially exists on disk, causing EVERY affected file to be
        # misclassified as its own test file (found via real-codebase
        # validation: impact --name signInWithGoogle listed calculator_widget.ts,
        # errors.ts, sidepanel.ts as "tests", none of which are test files).
        if f.endswith(".rs"):
            test_patterns.append(f[:-3] + "_test.rs")
        elif f.endswith(".py"):
            test_patterns.append(f[:-3] + "_test.py")
        for tf in test_patterns:
            full_path = os.path.join(workspace, tf)
            if os.path.exists(full_path):
                test_files.add(tf)

        # Also check __tests__ directories
        parts = f.split("/")
        if len(parts) > 1:
            test_dir = "/".join(parts[:-1]) + "/__tests__/" + parts[-1]
            for ext in [".test.ts", ".test.js", ".spec.ts", ".spec.js"]:
                full_path = os.path.join(workspace, test_dir.rsplit(".", 1)[0] + ext)
                if os.path.exists(full_path):
                    test_files.add(test_dir.rsplit(".", 1)[0] + ext)

    affected["tests"] = sorted(test_files)

    # ─── Risk Assessment ────────────────────────────────
    # ─── Deduplicate affected items ─────────────────────
    # Multiple target nodes (e.g., same-named functions in different files) can
    # share callers, producing duplicate entries. Deduplicate by (name, file, line).
    for key in ("direct", "indirect"):
        seen = set()
        deduped = []
        for item in affected[key]:
            identity = (item.get("name", ""), item.get("file", ""), item.get("line", 0))
            if identity not in seen:
                seen.add(identity)
                deduped.append(item)
        affected[key] = deduped

    direct_count = len(affected["direct"])
    indirect_count = len(affected["indirect"])
    file_count = len(affected["files"])

    has_critical = any(
        item.get("risk") == "critical" for item in all_affected
    )
    has_high = any(
        item.get("risk") == "high" for item in all_affected
    )

    if has_critical or (action == "delete" and direct_count > 5):
        risk = "critical"
    elif has_high or direct_count > 3 or file_count > 5:
        risk = "high"
    elif direct_count > 1 or file_count > 2:
        risk = "medium"
    else:
        risk = "low"

    # ─── Recommendations ────────────────────────────────
    if has_critical:
        recommendations.append("STOP: Critical issue detected. Fix before proceeding.")

    if action == "delete":
        dead_downstream = [
            item for item in affected["indirect"]
            if "will become dead code" in item.get("relation", "")
        ]
        if dead_downstream:
            recommendations.append(
                f"Deleting '{name}' will create {len(dead_downstream)} dead function(s). "
                f"Consider removing them too: " +
                ", ".join(item["name"] for item in dead_downstream)
            )

        if direct_count > 0:
            recommendations.append(
                f"'{name}' is still actively called from {direct_count} location(s). "
                f"Delete the callers first or refactor them."
            )

    if action == "modify":
        if direct_count > 3:
            recommendations.append(
                f"'{name}' has {direct_count} direct dependent(s). "
                f"Consider backward-compatible changes or version the API."
            )

        if indirect_count > 5:
            recommendations.append(
                f"Changes to '{name}' may cascade through {indirect_count} indirect dependent(s). "
                f"Run full test suite after modification."
            )

    if affected["tests"]:
        recommendations.append(
            f"Check test files: {', '.join(affected['tests'][:5])}"
            + (f" and {len(affected['tests']) - 5} more" if len(affected["tests"]) > 5 else "")
        )

    if not recommendations:
        recommendations.append("Low risk. Proceed with changes.")

    return {
        "status": "ok",
        "symbol": name,
        "workspace": workspace,
        "action": action,
        "risk": risk,
        "affected": affected,
        "fuzzy_match": name not in node_by_fn if node_by_fn is not None else False,
        "stats": {
            "direct_dependents": direct_count,
            "indirect_dependents": indirect_count,
            "affected_files": file_count,
            "test_files_found": len(affected["tests"])
        },
        "recommendations": recommendations
    }
