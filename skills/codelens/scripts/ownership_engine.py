"""
Ownership Engine for CodeLens — v3
Git blame-based code ownership analysis.

Answers:
- "Who last touched this code?"
- "How old is this function? (stale vs fresh)"
- "Who should I ask before changing this?"
- "Is this legacy nobody wants to touch?"

Uses git blame for line-level ownership data.
Falls back gracefully if git is not available.
"""

import os
import re
import subprocess
import json
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict
from datetime import datetime, timezone
from utils import DEFAULT_IGNORE_DIRS, logger

SOURCE_EXTENSIONS = {
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".py", ".rs", ".vue", ".svelte",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hxx", ".go",
}


def analyze_ownership(
    workspace: str,
    file_path: Optional[str] = None,
    function_name: Optional[str] = None,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Analyze code ownership using git blame.

    Args:
        workspace: Absolute path to workspace
        file_path: Optional specific file to analyze
        function_name: Optional specific function to analyze
        config: CodeLens config

    Returns:
        Dict with ownership data, age analysis, and recommendations
    """
    workspace = os.path.abspath(workspace)

    # Check if git is available
    if not _is_git_repo(workspace):
        return {
            "status": "no_git",
            "workspace": workspace,
            "message": "Not a git repository. Git blame analysis requires a git repo.",
            "fallback": _analyze_without_git(workspace, file_path, function_name)
        }

    # ─── Specific function analysis ─────────────────────
    if function_name:
        return _analyze_function_ownership(workspace, function_name, file_path)

    # ─── Specific file analysis ─────────────────────────
    if file_path:
        return _analyze_file_ownership(workspace, file_path)

    # ─── Full workspace analysis ────────────────────────
    return _analyze_workspace_ownership(workspace)


def _is_git_repo(workspace: str) -> bool:
    """Check if workspace is a git repository."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--is-inside-work-tree'],
            cwd=workspace, capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def _run_git_blame(workspace: str, file_path: str) -> Optional[List[Dict]]:
    """Run git blame on a file and return per-line data."""
    try:
        result = subprocess.run(
            ['git', 'blame', '--line-porcelain', file_path],
            cwd=workspace, capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return None
    except (subprocess.SubprocessError, FileNotFoundError):
        return None

    lines_data = []
    current = {}

    for line in result.stdout.split('\n'):
        if line.startswith('\t'):
            # This is the actual content line
            current["content"] = line[1:]
            if current.get("author") and current.get("author_mail"):
                lines_data.append(current)
            current = {}
        elif line.startswith('author '):
            current["author"] = line[7:].strip()
        elif line.startswith('author-mail '):
            current["author_mail"] = line[12:].strip()
        elif line.startswith('author-time '):
            try:
                ts = int(line[11:].strip())
                current["author_time"] = ts
                current["author_date"] = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            except (ValueError, OSError):
                pass
        elif line.startswith('summary '):
            current["summary"] = line[8:].strip()
        elif line.startswith('commit '):
            current["commit"] = line[7:].strip()

    return lines_data


def _analyze_file_ownership(workspace: str, file_path: str) -> Dict[str, Any]:
    """Analyze ownership for a specific file."""
    rel_path = file_path
    if os.path.isabs(file_path):
        rel_path = os.path.relpath(file_path, workspace)

    blame_data = _run_git_blame(workspace, rel_path)
    if not blame_data:
        return {
            "status": "error",
            "file": rel_path,
            "message": f"Could not run git blame on '{rel_path}'"
        }

    # Aggregate by author
    author_lines: Dict[str, List[Dict]] = defaultdict(list)
    for i, line_data in enumerate(blame_data):
        author = line_data.get("author", "unknown")
        author_lines[author].append({
            "line": i + 1,
            "date": line_data.get("author_date", ""),
            "commit": line_data.get("commit", ""),
            "content": line_data.get("content", "")[:100]
        })

    # Calculate ownership percentages
    total_lines = len(blame_data)
    ownership = []
    for author, lines in sorted(author_lines.items(), key=lambda x: -len(x[1])):
        ownership.append({
            "author": author,
            "lines": len(lines),
            "percentage": round(len(lines) / total_lines * 100, 1) if total_lines > 0 else 0,
            "first_commit": min(l.get("date", "") for l in lines) if lines else "",
            "last_commit": max(l.get("date", "") for l in lines) if lines else ""
        })

    # Find stale lines (not changed in > 6 months)
    stale_lines = _find_stale_lines(blame_data, months=6)

    # Find hotspots (frequently changed areas)
    hotspots = _find_hotspots(blame_data)

    # Age analysis
    age_analysis = _compute_age_analysis(blame_data)

    return {
        "status": "ok",
        "file": rel_path,
        "workspace": workspace,
        "total_lines": total_lines,
        "ownership": ownership,
        "age": age_analysis,
        "stale_lines": len(stale_lines),
        "stale_percentage": round(len(stale_lines) / total_lines * 100, 1) if total_lines > 0 else 0,
        "hotspots": hotspots[:5],
        "stale_details": stale_lines[:20]
    }


def _analyze_function_ownership(
    workspace: str,
    function_name: str,
    file_path: Optional[str] = None
) -> Dict[str, Any]:
    """Analyze ownership for a specific function."""
    # Find the function in the registry or by scanning
    function_info = _find_function(workspace, function_name, file_path)

    if not function_info:
        return {
            "status": "not_found",
            "function": function_name,
            "message": f"Function '{function_name}' not found"
        }

    fn_file = function_info["file"]
    fn_line = function_info["line"]

    # Run git blame on the file
    blame_data = _run_git_blame(workspace, fn_file)
    if not blame_data:
        return {
            "status": "error",
            "function": function_name,
            "message": f"Could not run git blame on '{fn_file}'"
        }

    # Find function extent in blame data
    fn_end_line = _find_function_end(blame_data, fn_line)
    fn_blame = blame_data[fn_line - 1:fn_end_line]

    # Analyze function ownership
    author_lines: Dict[str, int] = defaultdict(int)
    dates = []

    for line_data in fn_blame:
        author = line_data.get("author", "unknown")
        author_lines[author] += 1
        if line_data.get("author_time"):
            dates.append(line_data["author_time"])

    total_fn_lines = len(fn_blame)
    ownership = []
    for author, line_count in sorted(author_lines.items(), key=lambda x: -x[1]):
        ownership.append({
            "author": author,
            "lines": line_count,
            "percentage": round(line_count / total_fn_lines * 100, 1) if total_fn_lines > 0 else 0
        })

    # Age analysis
    age_info = {}
    if dates:
        now = datetime.now(tz=timezone.utc).timestamp()
        oldest = min(dates)
        newest = max(dates)
        age_days = int((now - oldest) / 86400)
        last_touched_days = int((now - newest) / 86400)

        age_info = {
            "age_days": age_days,
            "last_touched_days": last_touched_days,
            "oldest_commit_date": datetime.fromtimestamp(oldest, tz=timezone.utc).isoformat(),
            "newest_commit_date": datetime.fromtimestamp(newest, tz=timezone.utc).isoformat(),
            "freshness": "stale" if last_touched_days > 180 else "aging" if last_touched_days > 60 else "fresh"
        }

    # Primary owner
    primary_owner = ownership[0]["author"] if ownership else "unknown"

    return {
        "status": "ok",
        "function": function_name,
        "file": fn_file,
        "line": fn_line,
        "end_line": fn_end_line,
        "total_lines": total_fn_lines,
        "primary_owner": primary_owner,
        "ownership": ownership,
        "age": age_info,
        "recommendations": _generate_ownership_recommendations(
            function_name, ownership, age_info, primary_owner
        )
    }


def _analyze_workspace_ownership(workspace: str) -> Dict[str, Any]:
    """Analyze ownership across the entire workspace."""
    # Get overall git log stats
    author_stats: Dict[str, Dict] = defaultdict(lambda: {"commits": 0, "files": set(), "lines": 0})

    try:
        # Get commit count per author
        result = subprocess.run(
            ['git', 'shortlog', '-sn', '--all'],
            cwd=workspace, capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                parts = line.strip().split('\t')
                if len(parts) >= 2:
                    commits = int(parts[0])
                    author = parts[1]
                    author_stats[author]["commits"] = commits
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    # Sample some key files for blame analysis
    sample_files = _find_key_files(workspace)
    file_ownerships = {}

    for rel_path in sample_files[:20]:  # Cap at 20 files for performance
        blame = _run_git_blame(workspace, rel_path)
        if blame:
            for line_data in blame:
                author = line_data.get("author", "unknown")
                author_stats[author]["lines"] += 1
                author_stats[author]["files"].add(rel_path)

            # Determine primary owner
            author_counts = defaultdict(int)
            for ld in blame:
                author_counts[ld.get("author", "unknown")] += 1
            primary = max(author_counts, key=author_counts.get) if author_counts else "unknown"
            file_ownerships[rel_path] = primary

    # Build ownership summary
    ownership_summary = []
    for author, stats in sorted(author_stats.items(), key=lambda x: -x[1]["commits"]):
        ownership_summary.append({
            "author": author,
            "commits": stats["commits"],
            "lines_owned": stats["lines"],
            "files_owned": len(stats["files"])
        })

    # Find orphan files (no recent changes)
    orphan_files = []
    for rel_path in sample_files:
        try:
            result = subprocess.run(
                ['git', 'log', '-1', '--format=%ct', '--', rel_path],
                cwd=workspace, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                ts = int(result.stdout.strip())
                days_since = int((datetime.now(tz=timezone.utc).timestamp() - ts) / 86400)
                if days_since > 365:
                    orphan_files.append({
                        "file": rel_path,
                        "days_since_last_commit": days_since,
                        "severity": "stale" if days_since > 730 else "aging"
                    })
        except (subprocess.SubprocessError, ValueError):
            pass

    return {
        "status": "ok",
        "workspace": workspace,
        "ownership_summary": ownership_summary,
        "file_ownerships": file_ownerships,
        "orphan_files": orphan_files[:20],
        "stats": {
            "contributors": len(author_stats),
            "files_analyzed": len(file_ownerships),
            "stale_files": len(orphan_files)
        }
    }


def _analyze_without_git(
    workspace: str,
    file_path: Optional[str] = None,
    function_name: Optional[str] = None
) -> Dict[str, Any]:
    """Fallback analysis when git is not available — use file modification times."""
    # Use file mtime as a proxy for last modification
    file_info = []

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in SOURCE_EXTENSIONS:
                continue

            fp = os.path.join(root, filename)
            rel_path = os.path.relpath(fp, workspace)

            try:
                mtime = os.path.getmtime(fp)
                now = datetime.now(tz=timezone.utc).timestamp()
                age_days = int((now - mtime) / 86400)

                file_info.append({
                    "file": rel_path,
                    "last_modified_days_ago": age_days,
                    "freshness": "stale" if age_days > 180 else "aging" if age_days > 30 else "fresh"
                })
            except OSError:
                pass

    return {
        "method": "mtime_fallback",
        "message": "Git not available — using file modification times as proxy",
        "files": sorted(file_info, key=lambda x: x["last_modified_days_ago"], reverse=True)[:30],
        "stale_count": sum(1 for f in file_info if f["freshness"] == "stale")
    }


def _find_function(workspace: str, function_name: str, file_path: Optional[str] = None) -> Optional[Dict]:
    """Find a function in the workspace."""
    # Try registry first
    try:
        from registry import load_backend_registry
        backend = load_backend_registry(workspace)
        for node in backend.get("nodes", []):
            if node["fn"] == function_name:
                if file_path and file_path not in node.get("file", ""):
                    continue
                return {"file": node.get("file", ""), "line": node.get("line", 0)}
    except Exception:
        logger.debug("Failed to load backend registry for function lookup", exc_info=True)

    # Scan files
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in SOURCE_EXTENSIONS:
                continue

            fp = os.path.join(root, filename)
            rel_path = os.path.relpath(fp, workspace)

            if file_path and file_path not in rel_path:
                continue

            try:
                with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            for m in re.finditer(
                r'(?:function\s+' + re.escape(function_name) +
                r'|(?:const|let|var)\s+' + re.escape(function_name) +
                r'\s*=|def\s+' + re.escape(function_name) +
                r'|(?:pub\s+)?fn\s+' + re.escape(function_name) + r')\s*[\(=]',
                content
            ):
                line_num = content[:m.start()].count('\n') + 1
                return {"file": rel_path, "line": line_num}

    return None


def _find_function_end(blame_data: List[Dict], start_line: int) -> int:
    """Estimate function end line from blame data."""
    # Simple heuristic: look for decrease in indentation or empty line
    for i in range(start_line, min(start_line + 100, len(blame_data))):
        content = blame_data[i].get("content", "")
        # Check for closing brace at base level or function-level return
        if content.strip() == '}' or (content.strip() and not content.startswith(' ') and not content.startswith('\t')):
            return i + 1
    return min(start_line + 50, len(blame_data))


def _find_stale_lines(blame_data: List[Dict], months: int = 6) -> List[Dict]:
    """Find lines not changed in more than N months."""
    now = datetime.now(tz=timezone.utc).timestamp()
    threshold = now - (months * 30 * 86400)

    stale = []
    for i, line_data in enumerate(blame_data):
        ts = line_data.get("author_time", 0)
        if ts and ts < threshold:
            stale.append({
                "line": i + 1,
                "age_days": int((now - ts) / 86400),
                "author": line_data.get("author", ""),
                "content": line_data.get("content", "")[:80]
            })

    return stale


def _find_hotspots(blame_data: List[Dict]) -> List[Dict]:
    """Find areas with many different authors (hotspots / conflict zones)."""
    # Group lines into chunks of 10
    chunks = []
    chunk_size = 10

    for i in range(0, len(blame_data), chunk_size):
        chunk = blame_data[i:i + chunk_size]
        authors = set(ld.get("author", "") for ld in chunk)
        if len(authors) >= 3:
            chunks.append({
                "start_line": i + 1,
                "end_line": i + len(chunk),
                "authors": len(authors),
                "author_list": list(authors),
                "severity": "high" if len(authors) >= 5 else "medium"
            })

    return sorted(chunks, key=lambda x: -x["authors"])


def _compute_age_analysis(blame_data: List[Dict]) -> Dict[str, Any]:
    """Compute age distribution of lines in a file."""
    if not blame_data:
        return {"average_age_days": 0, "median_age_days": 0, "freshness": "unknown"}

    now = datetime.now(tz=timezone.utc).timestamp()
    ages = []

    for ld in blame_data:
        ts = ld.get("author_time", 0)
        if ts:
            ages.append(int((now - ts) / 86400))

    if not ages:
        return {"average_age_days": 0, "median_age_days": 0, "freshness": "unknown"}

    ages.sort()
    avg = sum(ages) / len(ages)
    median = ages[len(ages) // 2]

    return {
        "average_age_days": int(avg),
        "median_age_days": median,
        "oldest_line_days": max(ages),
        "newest_line_days": min(ages),
        "freshness": "stale" if median > 180 else "aging" if median > 60 else "fresh"
    }


def _find_key_files(workspace: str) -> List[str]:
    """Find key source files in the workspace for sampling."""
    key_files = []
    priorities = {".py": 1, ".rs": 1, ".ts": 2, ".tsx": 2, ".js": 3, ".jsx": 3}

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext in SOURCE_EXTENSIONS:
                fp = os.path.join(root, filename)
                rel_path = os.path.relpath(fp, workspace)
                priority = priorities.get(ext, 4)
                key_files.append((priority, rel_path))

    key_files.sort(key=lambda x: x[0])
    return [f[1] for f in key_files]


def _generate_ownership_recommendations(
    function_name: str,
    ownership: List[Dict],
    age_info: Dict,
    primary_owner: str
) -> List[str]:
    """Generate ownership-based recommendations."""
    recs = []

    if not ownership:
        return recs

    # Multiple owners = potential coordination needed
    if len(ownership) > 3:
        recs.append(
            f"Function '{function_name}' has {len(ownership)} contributors — "
            f"coordinate with team before changing. Primary owner: {primary_owner}."
        )

    # Stale code warning
    freshness = age_info.get("freshness", "unknown")
    last_touched = age_info.get("last_touched_days", 0)

    if freshness == "stale":
        recs.append(
            f"Function '{function_name}' is STALE (last touched {last_touched} days ago). "
            f"May contain outdated patterns or assumptions."
        )
    elif freshness == "aging":
        recs.append(
            f"Function '{function_name}' is aging (last touched {last_touched} days ago). "
            f"Review before modifying."
        )

    # High bus factor (single owner)
    if len(ownership) == 1:
        recs.append(
            f"Only '{primary_owner}' has modified this function. "
            f"Consider pair programming or knowledge sharing."
        )

    return recs
