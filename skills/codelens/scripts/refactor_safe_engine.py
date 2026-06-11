"""
Refactor-Safe Engine for CodeLens — v3
Pre-flight check before renaming or moving symbols.
Answers: "Is it safe to rename/move this? What will break that I can't see?"

Detects:
1. String references — "processOrder" as a string literal (dynamic access, reflection)
2. Dynamic property access — obj[name], window[fnName], this[method]
3. eval / Function constructor — can reference symbols dynamically
4. Meta-programming — decorators, annotations, reflection
5. Test references — describe("X"), it("should X"), test("X")
6. Config files — references in package.json, tsconfig, .env, etc.
7. Documentation — mentions in README, comments, JSDoc
8. Import/require paths — will moving the file break imports?

This eliminates the "fear of unknown breakage" that makes AI agents cautious.
"""

import os
import re
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS, logger

ALL_EXTENSIONS = {
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".py", ".rs", ".html", ".css", ".scss", ".less",
    ".vue", ".svelte",
    ".json", ".yaml", ".yml", ".toml", ".env", ".env.local",
    ".md", ".mdx", ".txt",
    ".config.js", ".config.ts"
}

def check_refactor_safety(
    name: str,
    workspace: str,
    action: str = "rename",
    new_name: Optional[str] = None,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Pre-flight check before renaming or moving a symbol.

    Args:
        name: Symbol name to rename/move
        workspace: Absolute path to workspace
        action: "rename" or "move"
        new_name: New name (for rename action), or new path (for move action)
        config: CodeLens config

    Returns:
        Dict with safety assessment, risks, and things that WILL break
    """
    workspace = os.path.abspath(workspace)

    risks = {
        "string_refs": [],       # Symbol name appears in strings
        "dynamic_access": [],    # obj[name] style dynamic access
        "eval_refs": [],         # eval/Function that might reference it
        "meta_refs": [],         # Decorators, annotations
        "test_refs": [],         # Test descriptions mentioning it
        "config_refs": [],       # Config file references
        "doc_refs": [],          # Documentation references
        "import_refs": [],       # Import paths that would break
        "css_refs": [],          # CSS class/ID references in stylesheets
    }

    safe_refs = []  # References that CAN be safely updated
    files_to_update = set()

    # Get registry data for the symbol
    registry_refs = _get_registry_refs(name, workspace)

    # Scan all files for different types of references
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)
            ext = os.path.splitext(filename)[1].lower()

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            # ─── String References ────────────────────────
            # Symbol name inside string literals
            string_refs = _find_string_refs(content, name, ext, rel_path)
            for ref in string_refs:
                risks["string_refs"].append(ref)
                files_to_update.add(rel_path)

            # ─── Dynamic Access ──────────────────────────
            dynamic_refs = _find_dynamic_access(content, name, ext, rel_path)
            for ref in dynamic_refs:
                risks["dynamic_access"].append(ref)
                files_to_update.add(rel_path)

            # ─── eval/Function References ────────────────
            eval_refs = _find_eval_refs(content, name, ext, rel_path)
            for ref in eval_refs:
                risks["eval_refs"].append(ref)
                files_to_update.add(rel_path)

            # ─── Meta-programming ───────────────────────
            meta_refs = _find_meta_refs(content, name, ext, rel_path)
            for ref in meta_refs:
                risks["meta_refs"].append(ref)
                files_to_update.add(rel_path)

            # ─── Test References ────────────────────────
            test_refs = _find_test_refs(content, name, ext, rel_path)
            for ref in test_refs:
                risks["test_refs"].append(ref)
                files_to_update.add(rel_path)

            # ─── Config References ──────────────────────
            config_refs = _find_config_refs(content, name, ext, rel_path)
            for ref in config_refs:
                risks["config_refs"].append(ref)
                files_to_update.add(rel_path)

            # ─── Documentation References ───────────────
            doc_refs = _find_doc_refs(content, name, ext, rel_path)
            for ref in doc_refs:
                risks["doc_refs"].append(ref)
                files_to_update.add(rel_path)

    # ─── Import path analysis (for move action) ─────────
    if action == "move":
        import_refs = _find_import_breaks(name, workspace, new_name)
        risks["import_refs"] = import_refs
        for ref in import_refs:
            files_to_update.add(ref.get("file", ""))

    # ─── CSS class/ID references ────────────────────────
    if action == "rename":
        css_refs = _find_css_refs(name, workspace)
        risks["css_refs"] = css_refs
        for ref in css_refs:
            files_to_update.add(ref.get("file", ""))

    # ─── Compute safety level ──────────────────────────
    total_risks = sum(len(v) for v in risks.values())
    has_dynamic = bool(risks["dynamic_access"])
    has_eval = bool(risks["eval_refs"])
    has_string = bool(risks["string_refs"])
    has_config = bool(risks["config_refs"])

    if has_dynamic or has_eval:
        safety = "dangerous"
    elif has_string or has_config:
        safety = "risky"
    elif total_risks > 10:
        safety = "cautious"
    elif total_risks > 0:
        safety = "mostly_safe"
    else:
        safety = "safe"

    # ─── Generate checklist ─────────────────────────────
    checklist = _generate_checklist(risks, action, name, new_name, safety)

    # ─── Safe references from registry ─────────────────
    safe_refs = registry_refs

    return {
        "status": "ok",
        "symbol": name,
        "workspace": workspace,
        "action": action,
        "new_name": new_name,
        "safety": safety,
        "risks": {k: v for k, v in risks.items() if v},  # Only non-empty
        "safe_references": safe_refs,
        "files_to_update": sorted(files_to_update),
        "stats": {
            "total_risks": total_risks,
            "string_refs": len(risks["string_refs"]),
            "dynamic_access": len(risks["dynamic_access"]),
            "eval_refs": len(risks["eval_refs"]),
            "meta_refs": len(risks["meta_refs"]),
            "test_refs": len(risks["test_refs"]),
            "config_refs": len(risks["config_refs"]),
            "doc_refs": len(risks["doc_refs"]),
            "files_affected": len(files_to_update)
        },
        "checklist": checklist
    }

def _get_registry_refs(name: str, workspace: str) -> List[Dict]:
    """Get known references from CodeLens registry."""
    refs = []

    try:
        from registry import load_frontend_registry, load_backend_registry

        # Frontend
        frontend = load_frontend_registry(workspace)
        for cls in frontend.get("classes", []):
            if cls["name"] == name:
                for ref in cls.get("js", []) + cls.get("css", []):
                    refs.append({
                        "file": ref.get("path", ""),
                        "line": ref.get("line", 0),
                        "type": "safe_rename",
                        "source": "registry"
                    })

        for id_entry in frontend.get("ids", []):
            if id_entry["name"] == name:
                for ref in id_entry.get("defined_in_html", []) + id_entry.get("css", []) + id_entry.get("js", []):
                    refs.append({
                        "file": ref.get("path", ""),
                        "line": ref.get("line", 0),
                        "type": "safe_rename",
                        "source": "registry"
                    })

        # Backend
        backend = load_backend_registry(workspace)
        for node in backend.get("nodes", []):
            if node["fn"] == name:
                refs.append({
                    "file": node.get("file", ""),
                    "line": node.get("line", 0),
                    "type": "safe_rename",
                    "source": "registry"
                })

        for edge in backend.get("edges", []):
            if edge.get("to_fn") == name:
                refs.append({
                    "file": edge.get("from", "").rsplit(":", 1)[0] if ":" in edge.get("from", "") else "",
                    "type": "safe_rename",
                    "source": "registry_edge"
                })

    except Exception:
        logger.debug("Safety check failed", exc_info=True)

    return refs

def _find_string_refs(content: str, name: str, ext: str, rel_path: str) -> List[Dict]:
    """Find the symbol name inside string literals."""
    refs = []
    lines = content.split('\n')

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Skip imports/exports (these are safe)
        if stripped.startswith('import ') or stripped.startswith('export '):
            continue

        # Look for name inside quotes
        for m in re.finditer(r'["\']([^"\']*' + re.escape(name) + r'[^"\']*)["\']', stripped):
            string_content = m.group(1)

            # Skip if it's a normal import path
            if string_content.startswith('./') or string_content.startswith('../') or string_content.startswith('@/'):
                continue

            # Skip if it's a URL
            if string_content.startswith('http://') or string_content.startswith('https://'):
                continue

            # This is a string reference — potentially dangerous
            risk = "medium"
            if any(kw in stripped for kw in ['eval', 'Function', 'exec', 'window[', 'global[']):
                risk = "high"

            refs.append({
                "file": rel_path,
                "line": i + 1,
                "string": string_content[:100],
                "risk": risk,
                "message": f"Symbol '{name}' appears in string literal"
            })

    return refs

def _find_dynamic_access(content: str, name: str, ext: str, rel_path: str) -> List[Dict]:
    """Find dynamic property access patterns that might reference the symbol."""
    refs = []
    lines = content.split('\n')

    patterns = [
        r'(?:window|global|globalThis|this)\s*\[\s*["\']' + re.escape(name) + r'["\']\s*\]',
        r'\w+\s*\[\s*["\']' + re.escape(name) + r'["\']\s*\]',
        r'Object\.keys\s*\(',
        r'Object\.values\s*\(',
        r'Object\.entries\s*\(',
        r'for\s*\(\s*(?:const|let|var)\s+\w+\s+in\s+',
        r'Reflect\.(?:get|set|has|ownKeys)',
        r'getattr\s*\(',
        r'hasattr\s*\(',
    ]

    for i, line in enumerate(lines):
        for pattern in patterns:
            if re.search(pattern, line):
                # Only flag if the name could be dynamically accessed
                if name in line or 'keys' in line or 'entries' in line or 'ownKeys' in line:
                    refs.append({
                        "file": rel_path,
                        "line": i + 1,
                        "risk": "high",
                        "message": f"Dynamic access pattern that may reference '{name}'"
                    })
                    break

    return refs

def _find_eval_refs(content: str, name: str, ext: str, rel_path: str) -> List[Dict]:
    """Find eval/Function calls that could reference the symbol."""
    refs = []
    lines = content.split('\n')

    eval_patterns = [
        r'eval\s*\(',
        r'new\s+Function\s*\(',
        r'setTimeout\s*\(\s*["\']',
        r'setInterval\s*\(\s*["\']',
        r'exec(?:Sync)?\s*\(',
        r'subprocess\.(?:call|run|Popen)',
        r'os\.system\s*\(',
    ]

    for i, line in enumerate(lines):
        for pattern in eval_patterns:
            if re.search(pattern, line):
                refs.append({
                    "file": rel_path,
                    "line": i + 1,
                    "risk": "critical",
                    "message": f"eval/exec that may dynamically reference '{name}'"
                })
                break

    return refs

def _find_meta_refs(content: str, name: str, ext: str, rel_path: str) -> List[Dict]:
    """Find meta-programming references (decorators, annotations)."""
    refs = []
    lines = content.split('\n')

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Python decorators
        if ext == ".py" and stripped.startswith('@') and name in stripped:
            refs.append({
                "file": rel_path,
                "line": i + 1,
                "risk": "high",
                "message": f"Decorator references '{name}'"
            })

        # Java/TS decorators
        if ext in {".ts", ".tsx"} and stripped.startswith('@') and name in stripped:
            refs.append({
                "file": rel_path,
                "line": i + 1,
                "risk": "high",
                "message": f"Decorator/annotation references '{name}'"
            })

        # Reflect metadata
        if 'Reflect.metadata' in stripped and name in stripped:
            refs.append({
                "file": rel_path,
                "line": i + 1,
                "risk": "high",
                "message": f"Reflect metadata references '{name}'"
            })

    return refs

def _find_test_refs(content: str, name: str, ext: str, rel_path: str) -> List[Dict]:
    """Find test descriptions and assertions mentioning the symbol."""
    refs = []
    lines = content.split('\n')

    # Only check test files
    is_test = any(x in rel_path for x in ['.test.', '.spec.', '_test.', '__tests__', 'tests/'])

    if not is_test:
        return refs

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Test descriptions
        if re.match(r'(?:describe|it|test|context)\s*\(\s*["\']', stripped):
            if name in stripped:
                refs.append({
                    "file": rel_path,
                    "line": i + 1,
                    "risk": "low",
                    "message": f"Test description mentions '{name}' — update test name too"
                })

    return refs

def _find_config_refs(content: str, name: str, ext: str, rel_path: str) -> List[Dict]:
    """Find references in config files."""
    refs = []

    config_extensions = {".json", ".yaml", ".yml", ".toml", ".env", ".env.local"}
    if ext not in config_extensions:
        return refs

    if name in content:
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if name in line:
                refs.append({
                    "file": rel_path,
                    "line": i + 1,
                    "risk": "medium",
                    "message": f"Config file references '{name}' — update config too"
                })
                break  # One ref per config file is enough

    return refs

def _find_doc_refs(content: str, name: str, ext: str, rel_path: str) -> List[Dict]:
    """Find references in documentation."""
    refs = []

    doc_extensions = {".md", ".mdx", ".txt"}
    if ext not in doc_extensions:
        return refs

    if name in content:
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if name in line:
                refs.append({
                    "file": rel_path,
                    "line": i + 1,
                    "risk": "low",
                    "message": f"Documentation mentions '{name}' — update docs too"
                })

    return refs[:5]  # Cap doc refs

def _find_import_breaks(file_path: str, workspace: str, new_path: Optional[str] = None) -> List[Dict]:
    """Find import statements that would break if a file is moved."""
    refs = []

    if not new_path:
        return refs

    # Find all files that import this file
    rel_target = file_path if not os.path.isabs(file_path) else os.path.relpath(file_path, workspace)
    base_name = os.path.splitext(os.path.basename(rel_target))[0]

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py", ".rs"}:
                continue

            fp = os.path.join(root, filename)
            rp = os.path.relpath(fp, workspace)

            try:
                with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            # Check imports that reference the file
            for m in re.finditer(r'(?:import|require)\s*.*?from\s*["\']([^"\']+)["\']', content):
                import_path = m.group(1)
                if base_name in import_path or rel_target.replace('\\', '/') in import_path:
                    line_num = content[:m.start()].count('\n') + 1
                    refs.append({
                        "file": rp,
                        "line": line_num,
                        "import_path": import_path,
                        "risk": "high",
                        "message": f"Import would break: '{import_path}' → needs update to new path"
                    })

    return refs

def _find_css_refs(name: str, workspace: str) -> List[Dict]:
    """Find CSS class/ID references that would break on rename."""
    refs = []

    try:
        from registry import load_frontend_registry
        frontend = load_frontend_registry(workspace)

        for cls in frontend.get("classes", []):
            if cls["name"] == name:
                for css_ref in cls.get("css", []):
                    refs.append({
                        "file": css_ref.get("path", ""),
                        "line": css_ref.get("line", 0),
                        "risk": "medium",
                        "message": f"CSS selector .{name} must be renamed too"
                    })

        for id_entry in frontend.get("ids", []):
            if id_entry["name"] == name:
                for css_ref in id_entry.get("css", []):
                    refs.append({
                        "file": css_ref.get("path", ""),
                        "line": css_ref.get("line", 0),
                        "risk": "medium",
                        "message": f"CSS selector #{name} must be renamed too"
                    })

    except Exception:
        logger.debug("Safety check failed", exc_info=True)

    return refs

def _generate_checklist(
    risks: Dict[str, List[Dict]],
    action: str,
    name: str,
    new_name: Optional[str],
    safety: str
) -> List[str]:
    """Generate a pre-refactor checklist."""
    items = []

    if safety == "dangerous":
        items.append(f"STOP: Dynamic access or eval references to '{name}' found. Rename is DANGEROUS.")
        items.append("Consider: Can you deprecate the old name and add the new name instead?")

    if safety == "risky":
        items.append(f"CAUTION: String references to '{name}' found. Some references may not update automatically.")

    if risks["string_refs"]:
        items.append(f"Update {len(risks['string_refs'])} string reference(s) containing '{name}'")

    if risks["dynamic_access"]:
        items.append(f"Check {len(risks['dynamic_access'])} dynamic access pattern(s) — cannot auto-update")

    if risks["eval_refs"]:
        items.append(f"Review {len(risks['eval_refs'])} eval/exec call(s) — may reference '{name}' dynamically")

    if risks["config_refs"]:
        items.append(f"Update {len(risks['config_refs'])} config file reference(s)")

    if risks["test_refs"]:
        items.append(f"Update {len(risks['test_refs'])} test description(s)")

    if risks["doc_refs"]:
        items.append(f"Update {len(risks['doc_refs'])} documentation reference(s)")

    if risks["css_refs"]:
        items.append(f"Update {len(risks['css_refs'])} CSS selector(s)")

    if risks["import_refs"]:
        items.append(f"Update {len(risks['import_refs'])} import path(s)")

    if action == "rename" and new_name:
        items.append(f"Find & replace: '{name}' → '{new_name}' across all affected files")

    if action == "move":
        items.append("Update all import/require paths that reference the old file location")

    if not items:
        items.append(f"No hidden risks found. Safe to {action} '{name}'.")

    return items
