"""
Context Engine for CodeLens
Returns rich context around a symbol: definition code, nearby code,
callers, callees, imports, and file-level context.
Gives AI everything needed to understand a symbol without reading the whole file.
"""

import os
import re
from typing import Dict, List, Any, Optional
from utils import logger, safe_read_file


def _safe_extract_line(node_id: str) -> int:
    """Extract line number from a node ID, handling various formats.

    Node IDs can be:
      - 'path/to/file.rs:123'                  → 123
      - 'path/to/file.rs:123:function:Name'     → 123
      - 'path/to/file.rs:123:struct:Name'       → 123
      - 'path/to/file.rs:1:mod:reqwest'         → 1
    The line number is always the second-to-last numeric segment before
    any type:name suffix, or the last numeric segment if no suffix exists.
    """
    if not node_id or ':' not in node_id:
        return 0
    parts = node_id.split(':')
    # Try each part from right to left for a numeric value
    for part in reversed(parts):
        try:
            return int(part)
        except ValueError:
            continue
    return 0


def get_symbol_context(
    name: str,
    workspace: str,
    domain: str = "auto",
    context_lines: int = 5,
    include_code: bool = True
) -> Dict[str, Any]:
    """
    Get rich context for a symbol.

    Args:
        name: Symbol name (class, id, or function)
        workspace: Absolute path to workspace
        domain: "frontend", "backend", or "auto"
        context_lines: Lines of context around the symbol definition
        include_code: Whether to include actual source code

    Returns:
        Dict with definition, context, callers, callees, and file outline
    """
    workspace = os.path.abspath(workspace)
    context = {
        "symbol": name,
        "workspace": workspace,
        "definition": None,
        "nearby_symbols": [],
        "callers": [],
        "callees": [],
        "file_outline": None,
        "imports": [],
        "code_snippet": None
    }

    # ─── Frontend Context ───────────────────────────────
    if domain in ("frontend", "auto"):
        from registry import load_frontend_registry
        frontend = load_frontend_registry(workspace)

        for cls in frontend.get("classes", []):
            if cls["name"] == name:
                context["definition"] = {
                    "type": "class",
                    "name": cls["name"],
                    "status": cls["status"],
                    "ref_count": cls["ref_count"]
                }

                # Collect usage locations
                for js_ref in cls.get("js", []):
                    context["callers"].append({
                        "file": js_ref.get("path", ""),
                        "line": js_ref.get("line", 0),
                        "source": js_ref.get("source")
                    })
                for css_ref in cls.get("css", []):
                    context["callees"].append({
                        "file": css_ref.get("path", ""),
                        "line": css_ref.get("line", 0),
                        "type": "css_definition"
                    })

                # Get code snippet from first definition
                if include_code and cls.get("css"):
                    first_ref = cls["css"][0]
                    snippet = _read_code_around(
                        workspace, first_ref["path"],
                        first_ref["line"], context_lines
                    )
                    if snippet:
                        context["code_snippet"] = {
                            "file": first_ref["path"],
                            "center_line": first_ref["line"],
                            "lines": snippet
                        }

                # Get file outline
                if cls.get("css") or cls.get("js"):
                    ref_path = (cls.get("css") or cls.get("js"))[0].get("path", "")
                    if ref_path:
                        context["file_outline"] = _get_minimal_outline(workspace, ref_path)

                break

        for id_entry in frontend.get("ids", []):
            if id_entry["name"] == name:
                context["definition"] = {
                    "type": "id",
                    "name": id_entry["name"],
                    "status": id_entry["status"],
                    "ref_count": id_entry["ref_count"]
                }

                for js_ref in id_entry.get("js", []):
                    context["callers"].append({
                        "file": js_ref.get("path", ""),
                        "line": js_ref.get("line", 0),
                        "source": js_ref.get("source")
                    })
                for css_ref in id_entry.get("css", []):
                    context["callees"].append({
                        "file": css_ref.get("path", ""),
                        "line": css_ref.get("line", 0),
                        "type": "css_definition"
                    })

                # Code snippet from HTML definition
                if include_code and id_entry.get("defined_in_html"):
                    first_html = id_entry["defined_in_html"][0]
                    snippet = _read_code_around(
                        workspace, first_html["path"],
                        first_html["line"], context_lines
                    )
                    if snippet:
                        context["code_snippet"] = {
                            "file": first_html["path"],
                            "center_line": first_html["line"],
                            "lines": snippet
                        }

                break

    # ─── Backend Context ────────────────────────────────
    if domain in ("backend", "auto"):
        from registry import load_backend_registry
        from edge_resolver import get_callers, get_callees
        backend = load_backend_registry(workspace)
        nodes = backend.get("nodes", [])
        edges = backend.get("edges", [])

        # Build file index for O(1) nearby symbol lookup
        from collections import defaultdict
        file_to_nodes: Dict[str, List[Dict]] = defaultdict(list)
        for n in nodes:
            f = n.get("file", "")
            if f:
                file_to_nodes[f].append(n)

        # Exact match first
        exact_node = None
        for node in nodes:
            if node["fn"] == name:
                exact_node = node
                break

        # Fallback: substring/partial match (like trace does)
        fuzzy_node = None
        if exact_node is None:
            partial_matches = [n for n in nodes if name in n.get("fn", "")]
            if partial_matches:
                # Prefer shorter function names (closer to exact match)
                partial_matches.sort(key=lambda n: len(n.get("fn", "")))
                fuzzy_node = partial_matches[0]

        match_node = exact_node or fuzzy_node
        match_type = "exact" if exact_node else "fuzzy"

        if match_node is not None:
            node = match_node  # Always assign so subsequent code can reference it
            # If frontend already found this name (e.g. CSS class), note the overlap
            if context["definition"] is not None:
                context["definition"]["also_matched_in"] = "frontend"
            else:
                context["definition"] = {
                    "type": "function",
                    "name": node["fn"],
                    "status": node.get("status", "active"),
                    "ref_count": node.get("ref_count", 0),
                    "file": node.get("file", ""),
                    "line": node.get("line", 0),
                    "async": node.get("async", False),
                    "match_type": match_type
                }

            if match_type == "fuzzy":
                context["definition"]["query"] = name
                context["definition"]["note"] = f"No exact match for '{name}'. Showing '{node['fn']}' (substring match)."

            if node.get("impl_for"):
                context["definition"]["impl_for"] = node["impl_for"]
            if node.get("trait_name"):
                context["definition"]["trait_name"] = node["trait_name"]
            if node.get("component"):
                context["definition"]["component"] = True

            # Callers and callees
            callers = get_callers(node["id"], edges)
            callees = get_callees(node["id"], edges, nodes)

            context["callers"] = [
                {
                    "id": c["from"],
                    "file": c["from"].rsplit(":", 2)[0] if ":" in c["from"] else "",
                    "line": _safe_extract_line(c["from"])
                }
                for c in callers
            ]

            context["callees"] = [
                {
                    "fn": c.get("fn", c.get("to_fn", "unknown")),
                    "resolved": c.get("resolved", True),
                    "status": c.get("status", "unknown")
                }
                for c in callees
            ]

            # Code snippet
            if include_code and node.get("file"):
                snippet = _read_code_around(
                    workspace, node["file"],
                    node.get("line", 0), context_lines
                )
                if snippet:
                    context["code_snippet"] = {
                        "file": node["file"],
                        "center_line": node.get("line", 0),
                        "lines": snippet
                    }

            # File outline
            if node.get("file"):
                context["file_outline"] = _get_minimal_outline(workspace, node["file"])

            # File imports
            if node.get("file"):
                context["imports"] = _get_file_imports(workspace, node["file"])

            # Nearby symbols (other functions in same file)
            node_file = node.get("file", "")
            context["nearby_symbols"] = [
                {
                    "fn": n["fn"],
                    "line": n.get("line", 0),
                    "status": n.get("status", "active")
                }
                for n in file_to_nodes.get(node_file, [])
                if n["id"] != node["id"]
            ][:50]  # Cap at 50 nearby symbols to avoid output bloat

    found = context["definition"] is not None

    return {
        "status": "ok" if found else "not_found",
        "symbol": name,
        "workspace": workspace,
        "found": found,
        "context": context if found else None
    }


# ─── Helpers ─────────────────────────────────────────────

def _read_code_around(
    workspace: str,
    rel_path: str,
    center_line: int,
    context_lines: int
) -> Optional[List[Dict[str, Any]]]:
    """Read source code around a specific line number."""
    file_path = os.path.join(workspace, rel_path)

    if not os.path.exists(file_path):
        return None

    try:
        content = safe_read_file(file_path)
        if content is None:
            return None
        lines = content.splitlines()
    except (IOError, OSError):
        return None

    start = max(0, center_line - 1 - context_lines)
    end = min(len(lines), center_line + context_lines)

    result = []
    for i in range(start, end):
        result.append({
            "line": i + 1,
            "content": lines[i].rstrip('\n\r'),
            "is_target": (i + 1 == center_line)
        })

    return result


def _get_minimal_outline(workspace: str, rel_path: str) -> Optional[Dict]:
    """Get a minimal outline of the file containing the symbol."""
    file_path = os.path.join(workspace, rel_path)

    if not os.path.exists(file_path):
        return None

    try:
        from outline_engine import get_file_outline
        result = get_file_outline(file_path, workspace, detail_level="minimal")
        if result["status"] == "ok":
            return result["outline"]
    except Exception:
        logger.debug("Code snippet extraction failed", exc_info=True)

    return None


def _get_file_imports(workspace: str, rel_path: str) -> List[str]:
    """Extract import statements from a file."""
    file_path = os.path.join(workspace, rel_path)

    if not os.path.exists(file_path):
        return []

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except IOError:
        return []

    imports = []

    # ES imports
    for m in re.finditer(r'import\s+.*?from\s+["\']([^"\']+)["\']', content):
        imports.append(m.group(1))

    # CommonJS
    for m in re.finditer(r'require\s*\(\s*["\']([^"\']+)["\']\s*\)', content):
        imports.append(m.group(1))

    # Rust use
    if rel_path.endswith('.rs'):
        for m in re.finditer(r'use\s+([^;]+);', content):
            imports.append(m.group(1).strip())

    # Python import
    if rel_path.endswith('.py'):
        for line in content.split('\n'):
            stripped = line.strip()
            if stripped.startswith('import ') or stripped.startswith('from '):
                imports.append(stripped)

    # Go imports
    if rel_path.endswith('.go'):
        # Single import
        for m in re.finditer(r'import\s+"([^"]+)"', content):
            imports.append(m.group(1))
        # Import block
        import_block = re.search(r'import\s*\((.*?)\)', content, re.DOTALL)
        if import_block:
            for m in re.finditer(r'"([^"]+)"', import_block.group(1)):
                imports.append(m.group(1))
        return imports

    return imports
