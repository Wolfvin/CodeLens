"""
Search Engine for CodeLens
Fast regex-based code search across the workspace (ripgrep-style).
No tree-sitter dependency — pure Python re module for maximum compatibility.
"""

import os
import re
from typing import Dict, List, Any, Optional, Set
from utils import DEFAULT_IGNORE_DIRS


def _is_redos_risky(pattern: str) -> bool:
    """Heuristic check for potentially catastrophic backtracking patterns."""
    # Nested quantifiers like (a+)+ or (a*)* are classic ReDoS patterns
    nested_quantifier = re.search(r'(\([^)]*[+*][^)]*\))[+*{]', pattern)
    return nested_quantifier is not None

# File type to extension mapping
TYPE_EXTENSIONS = {
    "html": {".html", ".htm"},
    "css": {".css", ".scss", ".less", ".sass"},
    "js": {".js", ".mjs", ".cjs"},
    "ts": {".ts"},
    "tsx": {".tsx", ".jsx"},
    "rust": {".rs"},
    "python": {".py"},
    "vue": {".vue"},
    "svelte": {".svelte"},
    "json": {".json"},
    "yaml": {".yaml", ".yml"},
    "toml": {".toml"},
    "markdown": {".md", ".mdx"},
    "config": {".config.js", ".config.ts", ".config.mjs"},
}

# Default ignore patterns

DEFAULT_IGNORE_FILES = {
    ".DS_Store", "package-lock.json", "yarn.lock",
    "pnpm-lock.yaml", ".env", ".env.local",
}

def search_workspace(
    workspace: str,
    pattern: str,
    file_type: Optional[str] = None,
    file_filter: Optional[str] = None,
    max_results: int = 200,
    context_lines: int = 0,
    case_sensitive: bool = True,
    whole_word: bool = False,
    include_pattern: Optional[str] = None,
    exclude_pattern: Optional[str] = None,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Search for a regex pattern across all source files in the workspace.

    Args:
        workspace: Absolute path to workspace root
        pattern: Regex pattern to search for
        file_type: Filter by file type (html, css, js, ts, tsx, rust, python, vue, svelte)
        file_filter: Filter by file path substring (e.g., "src/components/")
        max_results: Maximum number of matches to return
        context_lines: Number of context lines before/after each match
        case_sensitive: Case-sensitive search (default True)
        whole_word: Match whole words only
        include_pattern: Additional glob pattern to include (e.g., "*.test.ts")
        exclude_pattern: Additional glob pattern to exclude (e.g., "*.spec.ts")
        config: CodeLens config (for ignore patterns)

    Returns:
        Dict with matches, stats, and any errors
    """
    workspace = os.path.abspath(workspace)

    # Guard against ReDoS - reject patterns with nested quantifiers
    if _is_redos_risky(pattern):
        return {
            "status": "error",
            "message": "Pattern appears to contain nested quantifiers that could cause catastrophic backtracking (ReDoS). Please simplify the pattern.",
            "matches": [],
            "stats": {"files_searched": 0, "files_matched": 0, "total_matches": 0}
        }

    # Compile the regex
    try:
        flags = 0 if case_sensitive else re.IGNORECASE
        if whole_word:
            pattern = r'\b' + pattern + r'\b'
        regex = re.compile(pattern, flags)
    except re.error as e:
        return {
            "status": "error",
            "message": f"Invalid regex pattern: {e}",
            "matches": [],
            "stats": {"files_searched": 0, "files_matched": 0, "total_matches": 0}
        }

    # Determine which extensions to search
    if file_type and file_type in TYPE_EXTENSIONS:
        target_extensions = TYPE_EXTENSIONS[file_type]
    elif file_type == "all" or file_type is None:
        # All known source extensions
        target_extensions = set()
        for exts in TYPE_EXTENSIONS.values():
            target_extensions.update(exts)
    else:
        # Treat file_type as a custom extension
        target_extensions = {file_type if file_type.startswith('.') else f'.{file_type}'}

    # Build ignore set from config
    ignore_dirs = set(DEFAULT_IGNORE_DIRS)
    ignore_files = DEFAULT_IGNORE_FILES.copy()
    if config:
        for pattern_str in config.get("ignore", []):
            clean = pattern_str.rstrip("/")
            ignore_dirs.add(clean)
            ignore_files.add(clean)

    # Compile include/exclude regexes once before the walk loop
    inc_regex = re.compile(include_pattern) if include_pattern else None
    exc_regex = re.compile(exclude_pattern) if exclude_pattern else None

    # Search
    matches = []
    files_searched = 0
    files_matched = 0
    errors = []

    for root, dirs, filenames in os.walk(workspace):
        # Filter out ignored directories (in-place modification of dirs)
        dirs[:] = [
            d for d in dirs
            if d not in ignore_dirs and not d.startswith('.')
        ]

        # Also skip .codelens specifically
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            if filename in ignore_files:
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            # Extension filter
            ext = os.path.splitext(filename)[1].lower()
            if ext not in target_extensions:
                # Check compound extensions like .config.js
                matched_compound = False
                for target_ext in target_extensions:
                    if filename.endswith(target_ext):
                        matched_compound = True
                        break
                if not matched_compound:
                    continue

            # File path filter
            if file_filter and file_filter not in rel_path:
                continue

            # Include/exclude patterns (pre-compiled)
            if inc_regex and not inc_regex.search(rel_path):
                continue
            if exc_regex and exc_regex.search(rel_path):
                continue

            # Read and search file
            files_searched += 1
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()

                file_had_match = False
                for line_num, line in enumerate(lines, 1):
                    line_stripped = line.rstrip('\n\r')

                    # Skip inside comments for more accurate results
                    # (basic heuristic — tree-sitter handles this better for parsers,
                    # but for search we keep it simple and fast)
                    match = regex.search(line_stripped)
                    if match:
                        if not file_had_match:
                            files_matched += 1
                            file_had_match = True

                        result_entry = {
                            "file": rel_path,
                            "line": line_num,
                            "match": line_stripped.strip(),
                            "start_col": match.start(),
                            "end_col": match.end()
                        }

                        # Add context lines
                        if context_lines > 0:
                            before = []
                            for i in range(max(0, line_num - 1 - context_lines), line_num - 1):
                                before.append(lines[i].rstrip('\n\r').strip())
                            result_entry["before"] = before

                            after = []
                            for i in range(line_num, min(len(lines), line_num + context_lines)):
                                after.append(lines[i].rstrip('\n\r').strip())
                            result_entry["after"] = after

                        matches.append(result_entry)

                        if len(matches) >= max_results:
                            return {
                                "status": "ok",
                                "pattern": pattern,
                                "workspace": workspace,
                                "matches": matches,
                                "stats": {
                                    "files_searched": files_searched,
                                    "files_matched": files_matched,
                                    "total_matches": len(matches),
                                    "truncated": True
                                }
                            }

            except (IOError, OSError) as e:
                errors.append({"file": rel_path, "error": str(e)})
                continue

    return {
        "status": "ok",
        "pattern": pattern,
        "workspace": workspace,
        "matches": matches,
        "stats": {
            "files_searched": files_searched,
            "files_matched": files_matched,
            "total_matches": len(matches),
            "truncated": False
        },
        "errors": errors if errors else None
    }

def search_symbols(
    workspace: str,
    name: str,
    domain: str = "all",
    fuzzy: bool = False,
    max_results: int = 50
) -> Dict[str, Any]:
    """
    Search for symbols (classes, ids, functions) by name.
    Uses the CodeLens registry instead of file scanning.

    Args:
        workspace: Absolute path to workspace
        name: Symbol name to search for
        domain: "frontend", "backend", or "all"
        fuzzy: Allow partial/fuzzy matching
        max_results: Maximum results

    Returns:
        Dict with matching symbols from registry
    """
    workspace = os.path.abspath(workspace)
    results = []

    if domain in ("frontend", "all"):
        from registry import load_frontend_registry
        frontend = load_frontend_registry(workspace)

        if fuzzy:
            pattern = re.compile(re.escape(name), re.IGNORECASE)
        else:
            pattern = None

        for cls in frontend.get("classes", []):
            if cls["name"] == name or (fuzzy and pattern and pattern.search(cls["name"])):
                results.append({
                    "domain": "frontend",
                    "type": "class",
                    "name": cls["name"],
                    "status": cls["status"],
                    "ref_count": cls["ref_count"],
                    "locations": [
                        f"{r.get('path', '')}:{r.get('line', 0)}"
                        for r in cls.get("css", []) + cls.get("js", [])
                    ]
                })

        for id_entry in frontend.get("ids", []):
            if id_entry["name"] == name or (fuzzy and pattern and pattern.search(id_entry["name"])):
                results.append({
                    "domain": "frontend",
                    "type": "id",
                    "name": id_entry["name"],
                    "status": id_entry["status"],
                    "ref_count": id_entry["ref_count"],
                    "locations": [
                        f"{r.get('path', '')}:{r.get('line', 0)}"
                        for r in id_entry.get("defined_in_html", []) +
                                  id_entry.get("css", []) +
                                  id_entry.get("js", [])
                    ]
                })

    if domain in ("backend", "all"):
        from registry import load_backend_registry
        backend = load_backend_registry(workspace)

        if fuzzy:
            if not pattern:
                pattern = re.compile(re.escape(name), re.IGNORECASE)
        else:
            pattern = None

        for node in backend.get("nodes", []):
            if node["fn"] == name or (fuzzy and pattern and pattern.search(node["fn"])):
                results.append({
                    "domain": "backend",
                    "type": "function",
                    "name": node["fn"],
                    "status": node.get("status", "active"),
                    "ref_count": node.get("ref_count", 0),
                    "location": f"{node.get('file', '')}:{node.get('line', 0)}",
                    "async": node.get("async", False),
                    "impl_for": node.get("impl_for"),
                    "component": node.get("component", False)
                })

    return {
        "status": "ok",
        "query": name,
        "domain": domain,
        "fuzzy": fuzzy,
        "count": len(results),
        "results": results[:max_results]
    }
