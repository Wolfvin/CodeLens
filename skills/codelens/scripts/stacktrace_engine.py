"""
Stack Trace Engine for CodeLens — v3
Simulates error propagation: "If function X throws, what's the full call stack?"

This helps AI answer: "If this fails, what breaks?"
Combines the call graph with error handling information to show:
1. Which callers will receive the error
2. Which callers have try/catch (handled)
3. Which callers DON'T have try/catch (unhandled → crash)
4. The full error propagation path to the top of the call stack

Critical for debugging and assessing error handling coverage.
"""

import os
import re
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict, deque


def trace_error_propagation(
    name: str,
    workspace: str,
    error_type: Optional[str] = None,
    max_depth: int = 20,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Simulate error propagation from a function.

    If this function throws, trace the error up the call stack to show:
    - Which functions will receive the error
    - Which have error handling (try/catch, .catch())
    - Which DON'T (unhandled → potential crash)
    - The full propagation path

    Args:
        name: Function name that might throw
        workspace: Absolute path to workspace
        error_type: Optional error type (e.g., "TypeError", "NetworkError")
        max_depth: Maximum trace depth
        config: CodeLens config

    Returns:
        Dict with propagation chain, handled/unhandled classification
    """
    workspace = os.path.abspath(workspace)

    # Load backend registry for call graph
    try:
        from registry import load_backend_registry
        backend = load_backend_registry(workspace)
        nodes = backend.get("nodes", [])
        edges = backend.get("edges", [])
    except Exception:
        return {
            "status": "error",
            "message": "No backend registry found. Run 'codelens scan' first.",
            "workspace": workspace
        }

    # Build call graph
    callers_map: Dict[str, List[Dict]] = defaultdict(list)
    node_by_id: Dict[str, Dict] = {}
    node_by_fn: Dict[str, List[Dict]] = defaultdict(list)

    for node in nodes:
        node_by_id[node["id"]] = node
        node_by_fn[node["fn"]].append(node)

    for edge in edges:
        from_id = edge.get("from", "")
        to_id = edge.get("to", "")
        if to_id and from_id:
            callers_map[to_id].append({
                "caller_id": from_id,
                "edge": edge
            })

    # Find starting nodes
    start_nodes = node_by_fn.get(name, [])
    if not start_nodes:
        return {
            "status": "not_found",
            "message": f"Function '{name}' not found in registry",
            "workspace": workspace
        }

    # Trace error propagation for each start node
    all_chains = []
    for start_node in start_nodes:
        chain = _trace_error_chain(
            start_node, callers_map, node_by_id,
            workspace, max_depth
        )
        all_chains.append(chain)

    # Analyze error handling coverage
    analysis = _analyze_error_handling(all_chains, workspace)

    # Build crash risk assessment
    crash_risk = _assess_crash_risk(analysis)

    # Merge chains into a unified result
    total_handled = sum(1 for c in analysis if c["handling"] == "handled")
    total_unhandled = sum(1 for c in analysis if c["handling"] == "unhandled")
    total_partial = sum(1 for c in analysis if c["handling"] == "partial")

    return {
        "status": "ok",
        "function": name,
        "workspace": workspace,
        "error_type": error_type,
        "chains": all_chains,
        "propagation": analysis,
        "crash_risk": crash_risk,
        "stats": {
            "total_paths": len(analysis),
            "handled": total_handled,
            "unhandled": total_unhandled,
            "partially_handled": total_partial,
            "max_depth_reached": max(c.get("depth", 0) for c in analysis) if analysis else 0
        },
        "recommendations": _generate_stack_recommendations(analysis, crash_risk, name)
    }


def _trace_error_chain(
    start_node: Dict,
    callers_map: Dict[str, List[Dict]],
    node_by_id: Dict[str, Dict],
    workspace: str,
    max_depth: int,
    max_chain_entries: int = 500,
    lazy_error_check: bool = True
) -> Dict[str, Any]:
    """BFS trace of error propagation up the call stack.

    Args:
        start_node: The node where the error originates.
        callers_map: Map from node_id to list of caller info dicts.
        node_by_id: Map from node_id to node dict.
        workspace: Absolute path to workspace.
        max_depth: Maximum BFS depth.
        max_chain_entries: Maximum number of chain entries before truncation.
            Prevents OOM/hang on repos with millions of edges. Default 500.
        lazy_error_check: If True, defer _check_error_handling to a
            post-processing step. This makes the BFS phase O(V+E) instead
            of O(V+E) * file_read_cost, which is critical for large repos.
    """
    start_id = start_node["id"]

    chain = [{
        "depth": 0,
        "node_id": start_id,
        "fn": start_node.get("fn", ""),
        "file": start_node.get("file", ""),
        "line": start_node.get("line", 0),
        "is_origin": True
    }]

    visited = {start_id}
    queue = deque([(start_id, 1)])
    truncated = False

    # Track which chain entries need deferred error-handling check
    entries_needing_check = []

    while queue and not truncated:
        current_id, depth = queue.popleft()

        if depth > max_depth:
            chain.append({
                "depth": depth,
                "node_id": "...",
                "fn": "(max depth reached)",
                "note": "Call stack may continue deeper"
            })
            continue

        callers = callers_map.get(current_id, [])

        # Deduplicate callers by caller_id — a function may call another
        # function multiple times (different call sites), creating multiple
        # edges with the same from_id. Only process each unique caller once.
        seen_callers_at_depth = set()
        unique_callers = []
        for caller_info in callers:
            caller_id = caller_info["caller_id"]
            if caller_id not in seen_callers_at_depth:
                seen_callers_at_depth.add(caller_id)
                unique_callers.append(caller_info)

        # Limit breadth at each level to prevent explosion on high-fanout nodes
        for caller_info in unique_callers[:50]:
            caller_id = caller_info["caller_id"]

            # Check total chain entries limit
            if len(chain) >= max_chain_entries:
                truncated = True
                break

            if caller_id in visited:
                # Cyclic reference — add a single marker, not one per edge
                if caller_id in node_by_id:
                    n = node_by_id[caller_id]
                    chain.append({
                        "depth": depth,
                        "node_id": caller_id,
                        "fn": n.get("fn", ""),
                        "file": n.get("file", ""),
                        "line": n.get("line", 0),
                        "cyclic": True
                    })
                continue

            visited.add(caller_id)

            if caller_id in node_by_id:
                n = node_by_id[caller_id]

                if lazy_error_check:
                    # Defer expensive file-reading check to post-processing
                    # For BFS traversal, assume no error handling so we
                    # continue tracing all paths (safe over-approximation)
                    chain_entry = {
                        "depth": depth,
                        "node_id": caller_id,
                        "fn": n.get("fn", ""),
                        "file": n.get("file", ""),
                        "line": n.get("line", 0),
                        "async": n.get("async", False),
                        "has_error_handling": None,  # deferred
                        "handling_type": None,         # deferred
                    }
                    chain.append(chain_entry)
                    entries_needing_check.append(chain_entry)
                    queue.append((caller_id, depth + 1))
                else:
                    # Original behavior: check error handling immediately
                    has_handling = _check_error_handling(n, workspace)
                    chain_entry = {
                        "depth": depth,
                        "node_id": caller_id,
                        "fn": n.get("fn", ""),
                        "file": n.get("file", ""),
                        "line": n.get("line", 0),
                        "async": n.get("async", False),
                        "has_error_handling": has_handling["has_handling"],
                        "handling_type": has_handling["type"]
                    }
                    chain.append(chain_entry)

                    # Only continue tracing if no error handling (error propagates further)
                    if not has_handling["has_handling"]:
                        queue.append((caller_id, depth + 1))

    # Deferred error-handling check: only check top entries to limit I/O
    if lazy_error_check and entries_needing_check:
        # Check at most 100 entries (prioritize shallow depth)
        entries_to_check = sorted(entries_needing_check, key=lambda e: e.get("depth", 0))[:100]
        for entry in entries_to_check:
            node = node_by_id.get(entry["node_id"])
            if node:
                has_handling = _check_error_handling(node, workspace)
                entry["has_error_handling"] = has_handling["has_handling"]
                entry["handling_type"] = has_handling["type"]
        # Mark remaining deferred entries
        for entry in entries_needing_check:
            if entry["has_error_handling"] is None:
                entry["has_error_handling"] = False
                entry["handling_type"] = "unchecked"

    result = {
        "origin": {
            "fn": start_node.get("fn", ""),
            "file": start_node.get("file", ""),
            "line": start_node.get("line", 0)
        },
        "chain": chain,
        "chain_length": len(chain)
    }

    if truncated:
        result["truncated"] = True
        result["truncation_note"] = f"Chain truncated at {max_chain_entries} entries (increase max_chain_entries for deeper analysis)"

    return result


def _check_error_handling(node: Dict, workspace: str) -> Dict[str, Any]:
    """Check if a function has error handling (try/catch, .catch(), etc.)."""
    file_path = os.path.join(workspace, node.get("file", ""))
    if not os.path.exists(file_path):
        return {"has_handling": False, "type": "unknown", "confidence": "low"}

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except IOError:
        return {"has_handling": False, "type": "unknown", "confidence": "low"}

    fn_line = node.get("line", 0)
    ext = os.path.splitext(file_path)[1].lower()

    # Get function body
    fn_body = _get_function_body_from_line(content, fn_line, ext)
    if not fn_body:
        return {"has_handling": False, "type": "none", "confidence": "medium"}

    # Check for various error handling patterns
    if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
        if re.search(r'\btry\s*\{', fn_body):
            if re.search(r'\bcatch\b', fn_body):
                return {"has_handling": True, "type": "try_catch", "confidence": "high"}
            if re.search(r'\.catch\s*\(', fn_body):
                return {"has_handling": True, "type": "promise_catch", "confidence": "high"}

        if re.search(r'\.catch\s*\(', fn_body):
            return {"has_handling": True, "type": "promise_catch", "confidence": "high"}

        if re.search(r'\.then\s*\(', fn_body) and re.search(r'\.catch\s*\(', fn_body):
            return {"has_handling": True, "type": "then_catch", "confidence": "high"}

        if re.search(r'await\s+', fn_body) and not re.search(r'\btry\b', fn_body):
            return {"has_handling": False, "type": "unhandled_await", "confidence": "high"}

    elif ext == ".py":
        if re.search(r'\btry\s*:', fn_body):
            if re.search(r'\bexcept\b', fn_body):
                return {"has_handling": True, "type": "try_except", "confidence": "high"}

        if re.search(r'\.catch\s*\(', fn_body):
            return {"has_handling": True, "type": "promise_catch", "confidence": "medium"}

    elif ext == ".rs":
        if 'match' in fn_body and 'Err' in fn_body:
            return {"has_handling": True, "type": "result_match", "confidence": "high"}
        if '?' in fn_body:
            return {"has_handling": True, "type": "try_operator", "confidence": "high"}
        if 'unwrap()' in fn_body or 'expect(' in fn_body:
            return {"has_handling": False, "type": "unwrap_panics", "confidence": "high"}

    return {"has_handling": False, "type": "none", "confidence": "medium"}


def _get_function_body_from_line(content: str, start_line: int, ext: str) -> Optional[str]:
    """Get function body starting from a specific line."""
    lines = content.split('\n')
    if start_line < 1 or start_line > len(lines):
        return None

    if ext == ".py":
        base_indent = len(lines[start_line - 1]) - len(lines[start_line - 1].lstrip())
        body_lines = []
        for i in range(start_line - 1, len(lines)):
            line = lines[i]
            if i > start_line - 1 and line.strip() and (len(line) - len(line.lstrip())) <= base_indent:
                break
            body_lines.append(line)
        return '\n'.join(body_lines)
    else:
        brace_count = 0
        started = False
        body_lines = []
        for i in range(start_line - 1, min(start_line + 200, len(lines))):
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
        return '\n'.join(body_lines) if body_lines else None


def _analyze_error_handling(chains: List[Dict], workspace: str) -> List[Dict]:
    """Analyze error handling coverage across all propagation chains."""
    analysis = []

    for chain_data in chains:
        chain = chain_data.get("chain", [])

        # Find the first handler (if any)
        first_handler = None
        unhandled_depth = 0

        for entry in chain:
            if entry.get("is_origin"):
                continue

            if entry.get("has_error_handling"):
                first_handler = entry
                break
            else:
                unhandled_depth += 1

        # Classify the path
        if first_handler:
            handling = "handled"
        elif unhandled_depth > 3:
            handling = "unhandled"
        else:
            handling = "partial"

        # Build path description
        path_fns = [e.get("fn", "?") for e in chain if not e.get("is_origin") and e.get("fn")]
        path_str = " → ".join(path_fns[:10])

        analysis.append({
            "origin_fn": chain_data["origin"]["fn"],
            "origin_file": chain_data["origin"]["file"],
            "handling": handling,
            "first_handler": first_handler,
            "unhandled_depth": unhandled_depth,
            "path": path_str,
            "depth": len(chain) - 1  # Exclude origin
        })

    return analysis


def _assess_crash_risk(analysis: List[Dict]) -> str:
    """Assess overall crash risk based on error propagation analysis."""
    if not analysis:
        return "unknown"

    unhandled = sum(1 for a in analysis if a["handling"] == "unhandled")
    total = len(analysis)

    if unhandled == 0:
        return "low"
    elif unhandled / total > 0.5:
        return "critical"
    elif unhandled / total > 0.2:
        return "high"
    else:
        return "medium"


def _generate_stack_recommendations(
    analysis: List[Dict], crash_risk: str, fn_name: str
) -> List[str]:
    """Generate recommendations based on error propagation analysis."""
    recs = []

    if crash_risk == "critical":
        recs.append(
            f"CRITICAL: '{fn_name}' errors are mostly unhandled. "
            f"Add try/catch at entry points."
        )
    elif crash_risk == "high":
        recs.append(
            f"HIGH RISK: Many paths from '{fn_name}' lack error handling. "
            f"Review unhandled call chains."
        )
    elif crash_risk == "medium":
        recs.append(
            f"Some paths from '{fn_name}' lack error handling. "
            f"Consider adding catch blocks."
        )

    # Specific recommendations
    unhandled_paths = [a for a in analysis if a["handling"] == "unhandled"]
    for path in unhandled_paths[:3]:
        recs.append(
            f"Unhandled path: {path['path'][:80]} — "
            f"add error handling at '{path['origin_fn']}' or its callers"
        )

    # Check for async without try/catch
    async_unhandled = [
        a for a in analysis
        if a["handling"] in ("unhandled", "partial")
    ]
    if async_unhandled:
        recs.append(
            f"{len(async_unhandled)} path(s) with async functions — "
            f"unhandled promise rejections may crash the process."
        )

    if not recs:
        recs.append(f"Error handling looks good for '{fn_name}'.")

    return recs
