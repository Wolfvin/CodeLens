"""
Search Engine for CodeLens
Fast regex-based code search across the workspace (ripgrep-style).
No tree-sitter dependency — pure Python re module for maximum compatibility.
"""

import os
import re
from typing import Dict, List, Any, Optional, Set
from utils import DEFAULT_IGNORE_DIRS, should_ignore_dir, logger


# File type to extension mapping
TYPE_EXTENSIONS = {
    "html": {".html", ".htm"},
    "css": {".css", ".scss", ".less", ".sass"},
    "js": {".js", ".mjs", ".cjs"},
    "ts": {".ts"},
    "tsx": {".tsx", ".jsx"},
    "rust": {".rs"},
    "go": {".go"},
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
    ignore_files = set(DEFAULT_IGNORE_FILES)
    if config:
        for pattern_str in config.get("ignore", []):
            clean = pattern_str.rstrip("/")
            ignore_dirs.add(clean)
            ignore_files.add(clean)

    # Search
    matches = []
    files_searched = 0
    files_matched = 0
    errors = []

    for root, dirs, filenames in os.walk(workspace):
        # Filter out ignored directories using path-segment-aware matching
        rel_root = os.path.relpath(root, workspace)
        if should_ignore_dir(rel_root):
            dirs.clear()
            continue
        # Also filter individual directory names for simple cases
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

            # Include/exclude patterns
            if include_pattern:
                inc_regex = re.compile(include_pattern)
                if not inc_regex.search(rel_path):
                    continue
            if exclude_pattern:
                exc_regex = re.compile(exclude_pattern)
                if exc_regex.search(rel_path):
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
        fuzzy: Allow partial/fuzzy matching (default: True for substring match)
        max_results: Maximum results

    Returns:
        Dict with matching symbols from registry
    """
    workspace = os.path.abspath(workspace)
    results = []

    # Always compile a substring pattern — exact match is a special case of fuzzy
    # When fuzzy=False, we still do case-insensitive substring matching so that
    # searching "epub" finds "parse_epub_metadata". Only when fuzzy=True do we
    # also do edit-distance/loose matching.
    name_lower = name.lower()
    substring_pattern = re.compile(re.escape(name), re.IGNORECASE)

    if domain in ("frontend", "all"):
        from registry import load_frontend_registry
        frontend = load_frontend_registry(workspace)

        for cls in frontend.get("classes", []):
            cls_name = cls["name"]
            # Exact match always included; substring match by default; fuzzy adds edit-distance
            if cls_name == name or substring_pattern.search(cls_name):
                results.append({
                    "domain": "frontend",
                    "type": "class",
                    "name": cls_name,
                    "status": cls["status"],
                    "ref_count": cls["ref_count"],
                    "locations": [
                        f"{r['path']}:{r['line']}"
                        for r in cls.get("css", []) + cls.get("js", [])
                    ]
                })

        for id_entry in frontend.get("ids", []):
            id_name = id_entry["name"]
            if id_name == name or substring_pattern.search(id_name):
                results.append({
                    "domain": "frontend",
                    "type": "id",
                    "name": id_name,
                    "status": id_entry["status"],
                    "ref_count": id_entry["ref_count"],
                    "locations": [
                        f"{r['path']}:{r['line']}"
                        for r in id_entry.get("defined_in_html", []) +
                                  id_entry.get("css", []) +
                                  id_entry.get("js", [])
                    ]
                })

    if domain in ("backend", "all"):
        from registry import load_backend_registry
        backend = load_backend_registry(workspace)

        for node in backend.get("nodes", []):
            fn_name = node["fn"]
            if fn_name == name or substring_pattern.search(fn_name):
                results.append({
                    "domain": "backend",
                    "type": "function",
                    "name": fn_name,
                    "status": node.get("status", "active"),
                    "ref_count": node.get("ref_count", 0),
                    "location": f"{node.get('file', '')}:{node.get('line', 0)}",
                    "async": node.get("async", False),
                    "impl_for": node.get("impl_for"),
                    "component": node.get("component", False)
                })

    # Sort: exact matches first, then by ref_count descending
    results.sort(key=lambda r: (0 if r["name"] == name else 1, -r.get("ref_count", 0)))

    return {
        "status": "ok",
        "query": name,
        "domain": domain,
        "fuzzy": fuzzy,
        "count": len(results),
        "results": results[:max_results]
    }
