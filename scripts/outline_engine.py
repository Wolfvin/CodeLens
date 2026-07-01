"""
Outline Engine for CodeLens
Extracts file structure outline (functions, classes, imports, exports)
using tree-sitter for accurate AST-based extraction.
"""

import os
from typing import Dict, List, Any, Optional
from utils import DEFAULT_IGNORE_DIRS, logger, safe_read_file


def get_file_outline(
    file_path: str,
    workspace: str = None,
    detail_level: str = "normal"
) -> Dict[str, Any]:
    """
    Get a structural outline of a source file.

    Args:
        file_path: Path to the source file (absolute or relative to workspace)
        workspace: Workspace root (for relative path display)
        detail_level: "minimal" (names only), "normal" (names + lines), "full" (names + lines + signatures)

    Returns:
        Dict with outline sections: imports, functions, classes, exports, variables
    """
    if not os.path.isabs(file_path):
        if workspace:
            file_path = os.path.join(workspace, file_path)
        else:
            file_path = os.path.abspath(file_path)

    if not os.path.exists(file_path):
        return {
            "status": "error",
            "message": f"File not found: {file_path}",
            "outline": None
        }

    ext = os.path.splitext(file_path)[1].lower()
    rel_path = os.path.relpath(file_path, workspace) if workspace else file_path

    try:
        content = safe_read_file(file_path)
        if content is None:
            return {
                "status": "error",
                "message": f"Cannot read file or file too large: {file_path}",
                "outline": None
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Cannot read file: {e}",
            "outline": None
        }

    # Route to appropriate parser
    if ext in ('.js', '.mjs', '.cjs'):
        outline = _outline_javascript(content, detail_level)
    elif ext == '.ts':
        outline = _outline_typescript(content, detail_level)
    elif ext in ('.tsx', '.jsx'):
        outline = _outline_tsx(content, detail_level)
    elif ext == '.rs':
        outline = _outline_rust(content, detail_level)
    elif ext == '.py':
        outline = _outline_python(content, detail_level)
    elif ext in ('.html', '.htm'):
        outline = _outline_html(content, detail_level)
    elif ext in ('.css', '.scss', '.less', '.sass'):
        outline = _outline_css(content, detail_level)
    elif ext == '.vue':
        outline = _outline_vue(content, detail_level)
    elif ext == '.svelte':
        outline = _outline_svelte(content, detail_level)
    elif ext == '.go':
        outline = _outline_go(content, detail_level)
    elif ext in ('.c', '.h', '.cpp', '.cc', '.cxx', '.hpp', '.hxx'):
        outline = _outline_c_cpp(content, detail_level, ext)
    elif ext == '.lua':
        outline = _outline_lua(content, detail_level)
    elif ext == '.php':
        outline = _outline_php(content, detail_level)
    elif ext == '.rb':
        outline = _outline_ruby(content, detail_level)
    elif ext in ('.ex', '.exs'):
        outline = _outline_elixir(content, detail_level)
    elif ext == '.dart':
        outline = _outline_dart(content, detail_level)
    elif ext == '.swift':
        outline = _outline_swift(content, detail_level)
    elif ext in ('.scala', '.sc'):
        outline = _outline_scala(content, detail_level)
    elif ext in ('.sh', '.bash', '.zsh'):
        outline = _outline_shell(content, detail_level)
    elif ext in ('.m', '.mm'):
        outline = _outline_objc(content, detail_level)
    else:
        outline = _outline_generic(content, detail_level)

    outline["file"] = rel_path
    outline["language"] = _detect_language(ext)
    outline["line_count"] = content.count('\n') + 1

    return {
        "status": "ok",
        "file": rel_path,
        "language": outline.get("language", "unknown"),
        "line_count": outline.get("line_count", 0),
        "outline": outline
    }


def get_workspace_outline(
    workspace: str,
    file_filter: Optional[str] = None,
    config: Optional[Dict] = None,
    max_files: int = 3000
) -> Dict[str, Any]:
    """
    Get outline for all source files in workspace.

    Args:
        workspace: Absolute path to workspace root
        file_filter: Optional substring filter for file paths
        config: CodeLens config dict
        max_files: Maximum number of files to outline (default 3000).
                   Use 0 for unlimited. Prevents timeout on huge repos.

    Returns a summary-level outline (not per-function detail).
    """
    workspace = os.path.abspath(workspace)
    ignore_dirs = set(DEFAULT_IGNORE_DIRS)
    if config:
        for p in config.get("ignore", []):
            ignore_dirs.add(p.rstrip("/"))

    source_extensions = {
        '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.rs', '.py', '.go',
        '.html', '.htm', '.css', '.scss', '.less', '.vue', '.svelte', '.php',
        '.gd', '.kt',
        # v6.4: Added C/C++, Lua, Ruby, Elixir, Dart, Swift, Scala, Shell, Java, C#, R, Haskell, Nim
        '.c', '.h', '.cpp', '.cc', '.cxx', '.hpp', '.hxx',
        '.lua', '.rb', '.ex', '.exs', '.dart', '.swift',
        '.scala', '.sc', '.sh', '.bash', '.zsh',
        '.java', '.cs',
        '.R', '.r', '.hs', '.lhs', '.nim', '.nims',
    }

    outlines = []
    errors = []
    file_count = 0
    total_lines = 0

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            # Honor max_files limit
            if max_files and max_files > 0 and file_count >= max_files:
                break

            ext = os.path.splitext(filename)[1].lower()
            if ext not in source_extensions:
                continue

            # Skip TypeScript declaration files (auto-generated, no runtime code)
            if filename.endswith('.d.ts') or filename.endswith('.d.tsx'):
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            if file_filter and file_filter not in rel_path:
                continue

            # Count lines before outlining
            content = safe_read_file(file_path)
            if content is not None:
                total_lines += len(content.split('\n'))

            result = get_file_outline(file_path, workspace, detail_level="minimal")
            file_count += 1
            if result["status"] == "ok":
                outlines.append(result)
            else:
                errors.append({"file": rel_path, "error": result.get("message", "unknown")})

    return {
        "status": "ok",
        "workspace": workspace,
        "files_outlined": len(outlines),
        "total_lines": total_lines,
        "outlines": outlines,
        "errors": errors if errors else None,
        "truncated": max_files > 0 and file_count >= max_files
    }


# ─── Language-Specific Outline Parsers ────────────────────

def _outline_javascript(content: str, detail: str) -> Dict:
    """Outline for JavaScript files."""
    outline = {"imports": [], "functions": [], "classes": [], "exports": [], "variables": []}

    # Workaround for issue #116: tree-sitter-javascript 0.25 segfaults
    # on files with deeply nested callbacks. Use regex fallback for
    # files over 100 lines.
    line_count = content.count('\n') + 1
    if line_count > 100:
        _extract_js_outline_regex(content, outline, detail)
        return outline

    try:
        from grammar_loader import get_grammar_loader
        loader = get_grammar_loader()
        lang = loader.get_language('javascript')
        if lang:
            from base_parser import BaseParser
            parser = BaseParser(lang)
            tree = parser.parse(content.encode('utf-8'))
            source = content.encode('utf-8')
            _extract_js_outline(parser, tree, source, outline, detail)
            return outline
    except Exception:
        logger.debug("JS tree-sitter outline failed, falling back to regex", exc_info=True)

    # Regex fallback
    _extract_js_outline_regex(content, outline, detail)
    return outline


def _outline_typescript(content: str, detail: str) -> Dict:
    """Outline for TypeScript files."""
    outline = {"imports": [], "functions": [], "classes": [], "exports": [], "variables": [], "interfaces": [], "types": []}

    try:
        from grammar_loader import get_grammar_loader
        loader = get_grammar_loader()
        lang = loader.get_language('typescript')
        if lang:
            from base_parser import BaseParser
            parser = BaseParser(lang)
            tree = parser.parse(content.encode('utf-8'))
            source = content.encode('utf-8')
            _extract_ts_outline(parser, tree, source, outline, detail)
            return outline
    except Exception:
        logger.debug("TypeScript tree-sitter outline failed, falling back to regex", exc_info=True)

    _extract_ts_outline_regex(content, outline, detail)
    return outline


def _outline_tsx(content: str, detail: str) -> Dict:
    """Outline for TSX/JSX files."""
    outline = {"imports": [], "functions": [], "classes": [], "exports": [], "variables": [], "interfaces": [], "types": [], "components": []}

    try:
        from grammar_loader import get_grammar_loader
        loader = get_grammar_loader()
        lang = loader.get_language('tsx')
        if lang:
            from base_parser import BaseParser
            parser = BaseParser(lang)
            tree = parser.parse(content.encode('utf-8'))
            source = content.encode('utf-8')
            _extract_tsx_outline(parser, tree, source, outline, detail)
            return outline
    except Exception:
        logger.debug("TSX tree-sitter outline failed, falling back to regex", exc_info=True)

    _extract_tsx_outline_regex(content, outline, detail)
    return outline


def _outline_rust(content: str, detail: str) -> Dict:
    """Outline for Rust files."""
    outline = {"imports": [], "functions": [], "structs": [], "enums": [], "traits": [], "impls": []}

    try:
        from grammar_loader import get_grammar_loader
        loader = get_grammar_loader()
        lang = loader.get_language('rust')
        if lang:
            from base_parser import BaseParser
            parser = BaseParser(lang)
            tree = parser.parse(content.encode('utf-8'))
            source = content.encode('utf-8')
            _extract_rust_outline(parser, tree, source, outline, detail)
            return outline
    except Exception:
        logger.debug("Rust tree-sitter outline failed, falling back to regex", exc_info=True)

    _extract_rust_outline_regex(content, outline, detail)
    return outline


def _outline_python(content: str, detail: str) -> Dict:
    """Outline for Python files."""
    outline = {"imports": [], "functions": [], "classes": [], "variables": []}

    # Workaround for issue #116: tree-sitter-python 0.25 segfaults on
    # large files. Use regex fallback for files over 200 lines.
    line_count = content.count('\n') + 1
    if line_count > 200:
        _extract_python_outline_regex(content, outline, detail)
        return outline

    try:
        from grammar_loader import get_grammar_loader
        loader = get_grammar_loader()
        lang = loader.get_language('python')
        if lang:
            from base_parser import BaseParser
            parser = BaseParser(lang)
            tree = parser.parse(content.encode('utf-8'))
            source = content.encode('utf-8')
            _extract_python_outline(parser, tree, source, outline, detail)
            return outline
    except Exception:
        logger.debug("Python tree-sitter outline failed, falling back to regex", exc_info=True)

    _extract_python_outline_regex(content, outline, detail)
    return outline


def _outline_html(content: str, detail: str) -> Dict:
    """Outline for HTML files."""
    import re
    outline = {"ids": [], "classes": [], "scripts": [], "links": []}

    for line_num, line in enumerate(content.split('\n'), 1):
        for m in re.finditer(r'\bid\s*=\s*["\']([^"\']+)["\']', line):
            outline["ids"].append({"name": m.group(1), "line": line_num})
        for m in re.finditer(r'\bclass\s*=\s*["\']([^"\']+)["\']', line):
            for cls in m.group(1).split():
                if cls.strip():
                    outline["classes"].append({"name": cls.strip(), "line": line_num})
        if '<script' in line:
            src_match = re.search(r'src\s*=\s*["\']([^"\']+)["\']', line)
            outline["scripts"].append({
                "src": src_match.group(1) if src_match else "inline",
                "line": line_num
            })
        if '<link' in line:
            href_match = re.search(r'href\s*=\s*["\']([^"\']+)["\']', line)
            if href_match:
                outline["links"].append({"href": href_match.group(1), "line": line_num})

    return outline


def _outline_css(content: str, detail: str) -> Dict:
    """Outline for CSS/SCSS/Less files."""
    import re
    outline = {"selectors": [], "variables": [], "mixins": [], "keyframes": []}

    # Remove comments
    clean = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)

    for line_num, line in enumerate(clean.split('\n'), 1):
        stripped = line.strip()
        # Class selectors
        for m in re.finditer(r'^(\.[a-zA-Z_][\w-]*)', stripped):
            outline["selectors"].append({"name": m.group(1), "type": "class", "line": line_num})
        # ID selectors
        for m in re.finditer(r'^(#[a-zA-Z_][\w-]*)', stripped):
            outline["selectors"].append({"name": m.group(1), "type": "id", "line": line_num})
        # CSS variables
        for m in re.finditer(r'(--[\w-]+)\s*:', stripped):
            outline["variables"].append({"name": m.group(1), "line": line_num})
        # SCSS variables
        for m in re.finditer(r'(\$[\w-]+)\s*:', stripped):
            outline["variables"].append({"name": m.group(1), "line": line_num})
        # SCSS mixins
        if stripped.startswith('@mixin'):
            m = re.search(r'@mixin\s+([\w-]+)', stripped)
            if m:
                outline["mixins"].append({"name": m.group(1), "line": line_num})
        # Keyframes
        if '@keyframes' in stripped:
            m = re.search(r'@keyframes\s+([\w-]+)', stripped)
            if m:
                outline["keyframes"].append({"name": m.group(1), "line": line_num})

    return outline


def _outline_vue(content: str, detail: str) -> Dict:
    """Outline for Vue SFC files."""
    import re
    outline = {"template": {"ids": [], "classes": []}, "script": {"imports": [], "functions": [], "classes": [], "exports": []}, "style": {"selectors": []}}

    # Split sections
    template_match = re.search(r'<template>(.*?)</template>', content, re.DOTALL)
    script_match = re.search(r'<script[^>]*>(.*?)</script>', content, re.DOTALL)
    style_match = re.search(r'<style[^>]*>(.*?)</style>', content, re.DOTALL)

    if template_match:
        tmpl = template_match.group(1)
        for line_num_offset, line in enumerate(tmpl.split('\n'), 1):
            for m in re.finditer(r'\bid\s*=\s*["\']([^"\']+)["\']', line):
                outline["template"]["ids"].append({"name": m.group(1)})
            for m in re.finditer(r'\bclass\s*=\s*["\']([^"\']+)["\']', line):
                for cls in m.group(1).split():
                    if cls.strip():
                        outline["template"]["classes"].append({"name": cls.strip()})

    if script_match:
        scr = script_match.group(1)
        _extract_js_outline_regex(scr, outline["script"], detail)

    if style_match:
        sty = style_match.group(1)
        css_outline = _outline_css(sty, detail)
        outline["style"]["selectors"] = css_outline.get("selectors", [])

    return outline


def _outline_svelte(content: str, detail: str) -> Dict:
    """Outline for Svelte component files."""
    import re
    outline = {"markup": {"ids": [], "classes": []}, "script": {"imports": [], "functions": [], "classes": [], "exports": []}, "style": {"selectors": []}}

    script_match = re.search(r'<script[^>]*>(.*?)</script>', content, re.DOTALL)
    style_match = re.search(r'<style[^>]*>(.*?)</style>', content, re.DOTALL)

    # Markup (everything outside script/style)
    markup = content
    if script_match:
        markup = markup.replace(script_match.group(0), '')
    if style_match:
        markup = markup.replace(style_match.group(0), '')

    for m in re.finditer(r'\bid\s*=\s*["\']([^"\']+)["\']', markup):
        outline["markup"]["ids"].append({"name": m.group(1)})
    for m in re.finditer(r'\bclass\s*=\s*["\']([^"\']+)["\']', markup):
        for cls in m.group(1).split():
            if cls.strip():
                outline["markup"]["classes"].append({"name": cls.strip()})
    for m in re.finditer(r'class:(\w+)', markup):
        outline["markup"]["classes"].append({"name": m.group(1), "directive": True})

    if script_match:
        _extract_js_outline_regex(script_match.group(1), outline["script"], detail)
    if style_match:
        css_outline = _outline_css(style_match.group(1), detail)
        outline["style"]["selectors"] = css_outline.get("selectors", [])

    return outline


def _outline_go(content: str, detail: str) -> Dict:
    """Outline for Go source files."""
    import re
    outline = {
        "functions": [],
        "classes": [],
        "interfaces": [],
        "types": [],
        "imports": [],
        "exports": [],
        "variables": [],
    }

    # Package detection
    pkg_match = re.search(r'^package\s+(\w+)', content, re.MULTILINE)
    if pkg_match:
        outline["package"] = pkg_match.group(1)

    # Import extraction (both single and block imports)
    import_block = re.search(r'import\s*\((.*?)\)', content, re.DOTALL)
    if import_block:
        for m in re.finditer(r'"([^"]+)"', import_block.group(1)):
            outline["imports"].append({"text": m.group(1)})
    else:
        single_import = re.search(r'import\s+"([^"]+)"', content)
        if single_import:
            outline["imports"].append({"text": single_import.group(1)})

    lines = content.split('\n')
    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()

        # Function declarations (with optional receiver)
        m = re.match(r'^func\s+(?:\([^)]*\)\s+)?(\w+)\s*\(', stripped)
        if m:
            fn_name = m.group(1)
            is_method = bool(re.match(r'^func\s+\(', stripped))
            receiver = None
            if is_method:
                recv_match = re.match(r'^func\s+\(\s*\w+\s+(?:\*?)(\w+)\s*\)', stripped)
                if recv_match:
                    receiver = recv_match.group(1)
            
            # Check if exported (starts with uppercase)
            is_exported = fn_name[0].isupper() if fn_name else False
            
            entry = {"name": fn_name, "line": line_num, "method": is_method}
            if receiver:
                entry["receiver"] = receiver
            outline["functions"].append(entry)
            
            if is_exported:
                outline["exports"].append({"name": fn_name, "line": line_num, "kind": "function"})
            continue

        # Struct declarations
        m = re.match(r'^type\s+(\w+)\s+struct\s*\{', stripped)
        if m:
            type_name = m.group(1)
            is_exported = type_name[0].isupper() if type_name else False
            outline["classes"].append({"name": type_name, "line": line_num})
            if is_exported:
                outline["exports"].append({"name": type_name, "line": line_num, "kind": "struct"})
            continue

        # Interface declarations
        m = re.match(r'^type\s+(\w+)\s+interface\s*\{', stripped)
        if m:
            type_name = m.group(1)
            is_exported = type_name[0].isupper() if type_name else False
            outline["interfaces"].append({"name": type_name, "line": line_num})
            if is_exported:
                outline["exports"].append({"name": type_name, "line": line_num, "kind": "interface"})
            continue

        # Type aliases
        m = re.match(r'^type\s+(\w+)\s+(?!struct\b|interface\b)(\w[\w.]*)\s*$', stripped)
        if m:
            type_name = m.group(1)
            alias_of = m.group(2)
            is_exported = type_name[0].isupper() if type_name else False
            outline["types"].append({"name": type_name, "alias_of": alias_of, "line": line_num})
            if is_exported:
                outline["exports"].append({"name": type_name, "line": line_num, "kind": "type"})
            continue

        # Package-level var declarations
        m = re.match(r'^var\s+(\w+)', stripped)
        if m:
            var_name = m.group(1)
            is_exported = var_name[0].isupper() if var_name else False
            outline["variables"].append({"name": var_name, "line": line_num})
            if is_exported:
                outline["exports"].append({"name": var_name, "line": line_num, "kind": "var"})
            continue

        # Package-level const declarations
        m = re.match(r'^const\s+(\w+)', stripped)
        if m:
            const_name = m.group(1)
            is_exported = const_name[0].isupper() if const_name else False
            outline["variables"].append({"name": const_name, "line": line_num, "const": True})
            if is_exported:
                outline["exports"].append({"name": const_name, "line": line_num, "kind": "const"})

    return outline


def _outline_c_cpp(content: str, detail: str, ext: str) -> Dict:
    """Extract outline from C/C++ source files.

    v6.5: Support multi-line function definitions where the return type
    is on a separate line from the function name (common in nginx, Linux
    kernel, and many C projects):

        static void
        ngx_master_process_cycle(ngx_cycle_t *cycle)
        {
    """
    import re
    outline = {
        "imports": [],
        "functions": [],
        "classes": [],
        "variables": [],
        "exports": []
    }

    lines = content.split('\n')
    is_header = ext in {'.h', '.hpp', '.hxx'}

    # v6.5: Track previous line's return type for multi-line function definitions
    prev_return_type = None

    for i, line in enumerate(lines):
        stripped = line.strip()

        # #include directives
        if stripped.startswith('#include'):
            m = re.match(r'#include\s+[<"]([^>"]+)[>"]', stripped)
            if m:
                outline["imports"].append({
                    "name": m.group(1),
                    "line": i + 1
                })

        # Skip preprocessor directives and comments
        if stripped.startswith('#') or stripped.startswith('//') or stripped.startswith('/*'):
            prev_return_type = None
            continue

        # v6.5: Detect return type on its own line (nginx/Linux kernel style)
        # Matches: "static void", "ngx_int_t", "char *", "static ngx_int_t", etc.
        if not stripped.endswith(';') and not stripped.endswith('{') and not stripped.endswith(','):
            # Check if this line is just a return type (no function name, no params)
            # Pattern: optional qualifiers + type name + optional pointer
            return_type_match = re.match(
                r'^(?:(?:static|inline|extern|const|unsigned|signed|volatile|struct|enum)\s+)*'
                r'(?:\w+(?:\s+\w+)*\s*\**)\s*$',
                stripped
            )
            if return_type_match and re.match(r'^[a-zA-Z_]', stripped):
                # This looks like a standalone return type line
                prev_return_type = stripped
                continue

        # Struct/union/enum declarations
        struct_match = re.match(
            r'(?:typedef\s+)?(?:struct|union|enum|class)\s+(\w+)',
            stripped
        )
        if struct_match and not re.match(r'(?:typedef\s+)?(?:struct|union|enum|class)\s+\w+\s*\w+\s*;', stripped):
            outline["classes"].append({
                "name": struct_match.group(1),
                "line": i + 1
            })
            prev_return_type = None
            continue

        # Function definitions: type name(params) {
        # Also support: name(params) { when preceded by a return type line
        fn_match = re.match(
            r'(?:static\s+|inline\s+|extern\s+)*(?:const\s+)?(?:\w+[\s*]+)+(\w+)\s*\([^)]*\)\s*(?:\{|$)',
            stripped
        )
        if not fn_match and prev_return_type:
            # v6.5: Multi-line style: return type on previous line
            # name(params) { or name(params)
            fn_match = re.match(
                r'(\w+)\s*\([^)]*\)\s*(?:\{|$)',
                stripped
            )
        if fn_match:
            fn_name = fn_match.group(1)
            if fn_name not in ('if', 'for', 'while', 'switch', 'return', 'sizeof',
                              'include', 'define', 'ifdef', 'ifndef', 'elif', 'pragma'):
                # Check if this is a definition (has body) or declaration (ends with ;)
                if not stripped.endswith(';'):
                    outline["functions"].append({
                        "name": fn_name,
                        "line": i + 1
                    })
                elif detail == "full" and is_header:
                    # In headers, include declarations in full detail mode
                    outline["functions"].append({
                        "name": fn_name,
                        "line": i + 1,
                        "declaration": True
                    })
            prev_return_type = None
            continue

        # Typedef declarations
        typedef_match = re.match(r'typedef\s+.*\s+(\w+)\s*;', stripped)
        if typedef_match:
            name = typedef_match.group(1)
            if name not in ('struct', 'union', 'enum'):
                outline["variables"].append({
                    "name": name,
                    "line": i + 1,
                    "type": "typedef"
                })
            prev_return_type = None
            continue

        # Reset prev_return_type if line doesn't continue the pattern
        if stripped and not stripped.startswith('//'):
            prev_return_type = None

    if detail != "full":
        outline["imports"] = outline["imports"][:50]
        outline["functions"] = outline["functions"][:100]
        outline["classes"] = outline["classes"][:50]

    return outline


def _outline_lua(content: str, detail: str) -> Dict:
    """Extract outline from Lua source files."""
    import re
    outline = {
        "imports": [],
        "functions": [],
        "classes": [],
        "variables": [],
        "exports": []
    }

    lines = content.split('\n')

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Skip comments
        if stripped.startswith('--'):
            continue

        # require() calls
        req_match = re.match(r'local\s+(\w+)\s*=\s*require\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)', stripped)
        if req_match:
            outline["imports"].append({
                "name": req_match.group(2),
                "alias": req_match.group(1),
                "line": i + 1
            })
            continue

        # Function definitions: function name(), local function name()
        fn_match = re.match(r'(?:local\s+)?function\s+([\w.:]+)', stripped)
        if fn_match:
            outline["functions"].append({
                "name": fn_match.group(1),
                "line": i + 1
            })
            continue

        # Module assignments: M.name = function(...)
        mod_match = re.match(r'(\w+)\.(\w+)\s*=\s*function', stripped)
        if mod_match:
            outline["functions"].append({
                "name": f"{mod_match.group(1)}.{mod_match.group(2)}",
                "line": i + 1
            })
            continue

        # Table definitions: local name = {}
        table_match = re.match(r'local\s+(\w+)\s*=\s*\{', stripped)
        if table_match:
            outline["variables"].append({
                "name": table_match.group(1),
                "line": i + 1,
                "type": "table"
            })
            continue

        # vim.api/vim.keymap/vim.opt calls (Neovim-specific)
        if detail == "full" and stripped.startswith('vim.'):
            vim_match = re.match(r'vim\.(keymap|opt|api|cmd)', stripped)
            if vim_match:
                outline["variables"].append({
                    "name": f"vim.{vim_match.group(1)}",
                    "line": i + 1,
                    "type": "vim_api"
                })

    if detail != "full":
        outline["imports"] = outline["imports"][:30]
        outline["functions"] = outline["functions"][:50]

    return outline


def _outline_php(content: str, detail: str) -> Dict:
    """Outline for PHP source files."""
    import re
    outline = {
        "functions": [],
        "classes": [],
        "interfaces": [],
        "traits": [],
        "enums": [],
        "imports": [],
        "variables": [],
        "constants": [],
    }

    # Namespace detection
    ns_match = re.search(r'namespace\s+([\w\\]+)\s*;', content)
    if ns_match:
        outline["namespace"] = ns_match.group(1).strip('\\')

    # Use statements (imports)
    for m in re.finditer(r'use\s+(?:function\s+|const\s+)?([\w\\]+)(?:\s+as\s+(\w+))?\s*;', content):
        import_path = m.group(1)
        alias = m.group(2) or import_path.rsplit('\\', 1)[-1]
        outline["imports"].append({"text": import_path, "alias": alias})

    # Group use statements (PHP 7+)
    for m in re.finditer(r'use\s+([\w\\]+)\\{([^}]+)}\s*;', content):
        base_ns = m.group(1)
        for item in re.finditer(r'([\w\\]+)(?:\s+as\s+(\w+))?', m.group(2)):
            import_path = base_ns + '\\' + item.group(1)
            alias = item.group(2) or item.group(1).rsplit('\\', 1)[-1]
            outline["imports"].append({"text": import_path, "alias": alias})

    lines = content.split('\n')
    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()

        # Class declarations
        m = re.match(r'(?:abstract\s+|final\s+)*class\s+(\w+)', stripped)
        if m:
            class_name = m.group(1)
            entry = {"name": class_name, "line": line_num}
            # Detect class modifiers
            prefix = stripped[:stripped.index('class')].strip()
            if 'abstract' in prefix:
                entry["abstract"] = True
            if 'final' in prefix:
                entry["final"] = True
            # Detect extends/implements on same line
            ext_match = re.search(r'extends\s+([\w\\]+)', stripped)
            if ext_match:
                entry["extends"] = ext_match.group(1).strip('\\')
            impl_match = re.search(r'implements\s+([\w\\,\s]+)', stripped)
            if impl_match:
                entry["implements"] = [i.strip().strip('\\') for i in impl_match.group(1).split(',')]
            outline["classes"].append(entry)
            continue

        # Interface declarations
        m = re.match(r'interface\s+(\w+)', stripped)
        if m:
            iface_name = m.group(1)
            entry = {"name": iface_name, "line": line_num}
            ext_match = re.search(r'extends\s+([\w\\,\s]+)', stripped)
            if ext_match:
                entry["extends"] = [i.strip().strip('\\') for i in ext_match.group(1).split(',')]
            outline["interfaces"].append(entry)
            continue

        # Trait declarations
        m = re.match(r'trait\s+(\w+)', stripped)
        if m:
            outline["traits"].append({"name": m.group(1), "line": line_num})
            continue

        # Enum declarations (PHP 8.1+)
        m = re.match(r'enum\s+(\w+)(?::\s*(\w+))?', stripped)
        if m:
            entry = {"name": m.group(1), "line": line_num}
            if m.group(2):
                entry["backing_type"] = m.group(2)
            outline["enums"].append(entry)
            continue

        # Function declarations (both standalone and class methods)
        m = re.match(r'(?:public\s+|private\s+|protected\s+|static\s+|abstract\s+|final\s+)*function\s+(\w+)\s*\(', stripped)
        if m:
            fn_name = m.group(1)
            indent = len(line) - len(line.lstrip())
            if indent == 0:
                # Standalone function (not a method)
                outline["functions"].append({"name": fn_name, "line": line_num})
            else:
                # Class method
                entry = {"name": fn_name, "line": line_num, "type": "method"}
                # Detect visibility
                if 'public' in stripped[:stripped.index('function')]:
                    entry["visibility"] = "public"
                elif 'private' in stripped[:stripped.index('function')]:
                    entry["visibility"] = "private"
                elif 'protected' in stripped[:stripped.index('function')]:
                    entry["visibility"] = "protected"
                if 'static' in stripped[:stripped.index('function')]:
                    entry["static"] = True
                outline["functions"].append(entry)
            continue

        # Class constants
        m = re.match(r'const\s+(\w+)\s*=', stripped)
        if m:
            outline["constants"].append({"name": m.group(1), "line": line_num})

    return outline


def _outline_generic(content: str, detail: str) -> Dict:
    """Generic outline for unsupported file types."""
    import re
    outline = {"functions": [], "variables": []}
    # Basic function-like pattern detection
    for line_num, line in enumerate(content.split('\n'), 1):
        stripped = line.strip()
        for m in re.finditer(r'(?:function|def|fn)\s+(\w+)', stripped):
            outline["functions"].append({"name": m.group(1), "line": line_num})
    return outline


# ─── Tree-sitter Outline Extractors ───────────────────────

def _extract_js_outline(parser, tree, source, outline, detail):
    """Extract JS outline using tree-sitter AST."""
    import re

    def visitor(node, src, depth):
        nt = node.type

        # Import declarations
        if nt == 'import_statement':
            text = parser.get_text(node, src)
            outline["imports"].append({
                "text": text.strip(),
                "line": parser.get_line(node)
            })

        # Function declarations
        elif nt in ('function_declaration', 'generator_function_declaration'):
            name = _find_child_text(node, 'identifier', src, parser)
            if name:
                entry = {"name": name, "line": parser.get_line(node), "async": False, "generator": 'generator' in nt}
                # Check for async keyword before function
                if detail == "full":
                    for child in node.children:
                        if child.type == 'async':
                            entry["async"] = True
                outline["functions"].append(entry)

        # Arrow functions / variable declarators with function
        elif nt == 'variable_declarator':
            name_node = _find_child(node, 'identifier')
            fn_child = _find_child_types(node, {'arrow_function', 'function_expression'})
            if name_node and fn_child:
                name = parser.get_text(name_node, src)
                entry = {"name": name, "line": parser.get_line(node), "async": False, "arrow": fn_child.type == 'arrow_function'}
                if detail == "full":
                    for child in fn_child.children:
                        if child.type == 'async':
                            entry["async"] = True
                outline["functions"].append(entry)
            elif name_node and detail != "minimal":
                name = parser.get_text(name_node, src)
                outline["variables"].append({"name": name, "line": parser.get_line(name_node)})

        # Class declarations
        elif nt == 'class_declaration':
            name = _find_child_text(node, 'identifier', src, parser)
            if name:
                entry = {"name": name, "line": parser.get_line(node), "methods": []}
                # Extract methods
                body = _find_child(node, 'class_body')
                if body:
                    for child in body.children:
                        if child.type == 'method_definition':
                            method_name = _find_child_text(child, 'property_identifier', src, parser)
                            if method_name:
                                entry["methods"].append({"name": method_name, "line": parser.get_line(child)})
                outline["classes"].append(entry)

        # Export statements
        elif nt in ('export_statement', 'export_default_declaration'):
            text = parser.get_text(node, src)
            # Find what's being exported
            for child in node.children:
                if child.type in ('function_declaration', 'class_declaration', 'identifier'):
                    exp_name = _find_child_text(child, 'identifier', src, parser) or parser.get_text(child, src)[:50]
                    outline["exports"].append({"name": exp_name, "line": parser.get_line(node), "default": 'default' in nt})

        return True

    parser.walk_tree(tree, source, visitor)


def _extract_ts_outline(parser, tree, source, outline, detail):
    """Extract TypeScript outline using tree-sitter AST."""
    _extract_js_outline(parser, tree, source, outline, detail)

    def visitor(node, src, depth):
        nt = node.type
        if nt == 'interface_declaration':
            name = _find_child_text(node, 'type_identifier', src, parser)
            if name:
                outline["interfaces"].append({"name": name, "line": parser.get_line(node)})
        elif nt == 'type_alias_declaration':
            name = _find_child_text(node, 'type_identifier', src, parser)
            if name:
                outline["types"].append({"name": name, "line": parser.get_line(node)})
        return True

    parser.walk_tree(tree, source, visitor)


def _extract_tsx_outline(parser, tree, source, outline, detail):
    """Extract TSX outline — same as TS plus component detection."""
    _extract_ts_outline(parser, tree, source, outline, detail)

    # Detect React components (PascalCase function that returns JSX)
    for fn in outline.get("functions", []):
        if fn["name"][0].isupper():
            fn["component"] = True
            outline["components"].append({"name": fn["name"], "line": fn["line"]})


def _extract_rust_outline(parser, tree, source, outline, detail):
    """Extract Rust outline using tree-sitter AST."""

    def visitor(node, src, depth):
        nt = node.type

        if nt == 'use_declaration':
            text = parser.get_text(node, src)
            outline["imports"].append({"text": text.strip(), "line": parser.get_line(node)})

        elif nt == 'function_item':
            name = _find_child_text(node, 'identifier', src, parser)
            if name:
                entry = {"name": name, "line": parser.get_line(node), "async": False, "pub": False}
                for child in node.children:
                    if child.type == 'async':
                        entry["async"] = True
                    if child.type == 'visibility_modifier':
                        entry["pub"] = True
                outline["functions"].append(entry)

        elif nt == 'struct_item':
            name = _find_child_text(node, 'type_identifier', src, parser)
            if name:
                outline["structs"].append({"name": name, "line": parser.get_line(node)})

        elif nt == 'enum_item':
            name = _find_child_text(node, 'type_identifier', src, parser)
            if name:
                outline["enums"].append({"name": name, "line": parser.get_line(node)})

        elif nt == 'trait_item':
            name = _find_child_text(node, 'type_identifier', src, parser)
            if name:
                outline["traits"].append({"name": name, "line": parser.get_line(node)})

        elif nt == 'impl_item':
            impl_type = _find_child_text(node, 'type_identifier', src, parser)
            trait_name = None
            for child in node.children:
                if child.type == 'trait_clause':
                    trait_id = _find_child(child, 'type_identifier')
                    if trait_id:
                        trait_name = parser.get_text(trait_id, src)
            if impl_type:
                entry = {"name": impl_type, "line": parser.get_line(node), "methods": []}
                if trait_name:
                    entry["trait"] = trait_name
                # Extract methods
                for child in node.children:
                    if child.type == 'function_item':
                        method_name = _find_child_text(child, 'identifier', src, parser)
                        if method_name:
                            entry["methods"].append({"name": method_name, "line": parser.get_line(child)})
                outline["impls"].append(entry)

        return True

    parser.walk_tree(tree, source, visitor)


def _extract_python_outline(parser, tree, source, outline, detail):
    """Extract Python outline using tree-sitter AST."""

    def visitor(node, src, depth):
        nt = node.type

        if nt in ('import_statement', 'import_from_statement'):
            text = parser.get_text(node, src)
            outline["imports"].append({"text": text.strip(), "line": parser.get_line(node)})

        elif nt == 'function_definition':
            name = _find_child_text(node, 'identifier', src, parser)
            if name:
                entry = {"name": name, "line": parser.get_line(node), "async": False}
                for child in node.children:
                    if child.type == 'async':
                        entry["async"] = True
                outline["functions"].append(entry)

        elif nt == 'class_definition':
            name = _find_child_text(node, 'identifier', src, parser)
            if name:
                entry = {"name": name, "line": parser.get_line(node), "methods": []}
                for child in node.children:
                    if child.type == 'function_definition':
                        method_name = _find_child_text(child, 'identifier', src, parser)
                        if method_name:
                            entry["methods"].append({"name": method_name, "line": parser.get_line(child)})
                outline["classes"].append(entry)

        return True

    parser.walk_tree(tree, source, visitor)


# ─── Regex Fallback Outline Extractors ────────────────────

def _extract_js_outline_regex(content, outline, detail):
    """Regex-based JS outline fallback."""
    import re
    content_clean = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    content_clean = re.sub(r'(?<!:)//.*$', '', content_clean, flags=re.MULTILINE)

    for line_num, line in enumerate(content_clean.split('\n'), 1):
        stripped = line.strip()

        # Imports
        if stripped.startswith('import '):
            outline["imports"].append({"text": stripped, "line": line_num})

        # Function declarations
        m = re.match(r'(?:async\s+)?function\s+(\w+)', stripped)
        if m:
            outline["functions"].append({"name": m.group(1), "line": line_num})
            continue

        # Arrow functions / const functions
        m = re.match(r'(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[^=])\s*=>', stripped)
        if m:
            outline["functions"].append({"name": m.group(1), "line": line_num, "arrow": True})
            continue

        # Class declarations
        m = re.match(r'(?:export\s+)?class\s+(\w+)', stripped)
        if m:
            outline["classes"].append({"name": m.group(1), "line": line_num})
            continue

        # Exports
        if stripped.startswith('export '):
            name = re.search(r'export\s+(?:default\s+)?(?:function\s+|class\s+|const\s+|let\s+|var\s+)?(\w+)', stripped)
            if name:
                outline["exports"].append({"name": name.group(1), "line": line_num})


def _extract_ts_outline_regex(content, outline, detail):
    """Regex-based TypeScript outline fallback."""
    import re
    _extract_js_outline_regex(content, outline, detail)

    for line_num, line in enumerate(content.split('\n'), 1):
        stripped = line.strip()
        m = re.match(r'(?:export\s+)?interface\s+(\w+)', stripped)
        if m:
            outline["interfaces"].append({"name": m.group(1), "line": line_num})

        m = re.match(r'(?:export\s+)?type\s+(\w+)', stripped)
        if m:
            outline["types"].append({"name": m.group(1), "line": line_num})


def _extract_tsx_outline_regex(content, outline, detail):
    """Regex-based TSX outline fallback."""
    import re
    _extract_ts_outline_regex(content, outline, detail)

    # Component detection (PascalCase functions)
    for fn in outline.get("functions", []):
        if fn["name"][0].isupper():
            fn["component"] = True
            outline["components"].append({"name": fn["name"], "line": fn["line"]})


def _extract_rust_outline_regex(content, outline, detail):
    """Regex-based Rust outline fallback."""
    import re

    for line_num, line in enumerate(content.split('\n'), 1):
        stripped = line.strip()

        # Use declarations
        m = re.match(r'use\s+(.+?);', stripped)
        if m:
            outline["imports"].append({"text": f"use {m.group(1)};", "line": line_num})
            continue

        # Function declarations
        m = re.match(r'(?:pub\s+)?(?:async\s+)?fn\s+(\w+)', stripped)
        if m:
            entry = {"name": m.group(1), "line": line_num}
            if 'pub ' in stripped:
                entry["pub"] = True
            if 'async ' in stripped:
                entry["async"] = True
            outline["functions"].append(entry)
            continue

        # Struct declarations
        m = re.match(r'(?:pub\s+)?struct\s+(\w+)', stripped)
        if m:
            outline["structs"].append({"name": m.group(1), "line": line_num})
            continue

        # Enum declarations
        m = re.match(r'(?:pub\s+)?enum\s+(\w+)', stripped)
        if m:
            outline["enums"].append({"name": m.group(1), "line": line_num})
            continue

        # Trait declarations
        m = re.match(r'(?:pub\s+)?trait\s+(\w+)', stripped)
        if m:
            outline["traits"].append({"name": m.group(1), "line": line_num})
            continue

        # Impl blocks
        m = re.match(r'impl\s+(?:(\w+)\s+for\s+)?(\w+)', stripped)
        if m:
            trait_name, impl_type = m.groups()
            entry = {"name": impl_type, "line": line_num, "methods": []}
            if trait_name:
                entry["trait"] = trait_name
            outline["impls"].append(entry)


def _extract_python_outline_regex(content, outline, detail):
    """Regex-based Python outline fallback."""
    import re

    for line_num, line in enumerate(content.split('\n'), 1):
        stripped = line.strip()

        # Imports
        if stripped.startswith('import ') or stripped.startswith('from '):
            outline["imports"].append({"text": stripped, "line": line_num})
            continue

        # Function definitions
        m = re.match(r'(?:async\s+)?def\s+(\w+)', stripped)
        if m:
            outline["functions"].append({"name": m.group(1), "line": line_num})
            continue

        # Class definitions
        m = re.match(r'class\s+(\w+)', stripped)
        if m:
            outline["classes"].append({"name": m.group(1), "line": line_num})


# ─── Helpers ──────────────────────────────────────────────

def _find_child(node, child_type: str):
    """Find first child of a specific type."""
    for child in node.children:
        if child.type == child_type:
            return child
    return None


def _find_child_types(node, child_types: set):
    """Find first child matching any of the given types."""
    for child in node.children:
        if child.type in child_types:
            return child
    return None


def _find_child_text(node, child_type, source, parser):
    """Find child and return its text content."""
    child = _find_child(node, child_type)
    if child:
        return parser.get_text(child, source)
    return None


# ─── Regex-based outline helpers for new languages ────────────────

import re as _re

def _outline_ruby(content: str, detail_level: str) -> Dict[str, Any]:
    """Outline Ruby source: classes, modules, methods."""
    outline = {"functions": [], "classes": [], "interfaces": [], "types": [],
               "exports": [], "components": [], "imports": []}
    for i, line in enumerate(content.split('\n'), 1):
        m = _re.match(r'\s*module\s+([\w:]+)', line)
        if m:
            outline["interfaces"].append({"name": m.group(1), "line": i, "type": "module"})
            continue
        m = _re.match(r'\s*class\s+([\w:]+)', line)
        if m:
            outline["classes"].append({"name": m.group(1), "line": i, "type": "class"})
            continue
        m = _re.match(r'\s*def\s+self\.([\w?!]+)', line)
        if m:
            outline["functions"].append({"name": f"self.{m.group(1)}", "line": i, "type": "class_method"})
            continue
        m = _re.match(r'\s*def\s+([\w?!]+)', line)
        if m and m.group(1) not in ('if', 'unless', 'while', 'until', 'for', 'case', 'begin'):
            outline["functions"].append({"name": m.group(1), "line": i, "type": "method"})
            continue
        m = _re.match(r'\s*require\s+[\'"]([^\'"]+)[\'"]', line)
        if m:
            outline["imports"].append({"name": m.group(1), "line": i})
    return outline


def _outline_elixir(content: str, detail_level: str) -> Dict[str, Any]:
    """Outline Elixir source: modules, functions, macros."""
    outline = {"functions": [], "classes": [], "interfaces": [], "types": [],
               "exports": [], "components": [], "imports": []}
    for i, line in enumerate(content.split('\n'), 1):
        m = _re.match(r'\s*defmodule\s+([\w.]+)', line)
        if m:
            outline["classes"].append({"name": m.group(1), "line": i, "type": "module"})
            continue
        m = _re.match(r'\s*defmacro\s+([\w!?]+)', line)
        if m:
            outline["functions"].append({"name": m.group(1), "line": i, "type": "macro"})
            continue
        m = _re.match(r'\s*defp?\s+([\w!?]+)', line)
        if m:
            outline["functions"].append({"name": m.group(1), "line": i, "type": "function"})
            continue
        m = _re.match(r'\s*(?:use|import|alias|require)\s+([\w.]+)', line)
        if m:
            outline["imports"].append({"name": m.group(1), "line": i})
    return outline


def _outline_dart(content: str, detail_level: str) -> Dict[str, Any]:
    """Outline Dart source: classes, functions, enums."""
    outline = {"functions": [], "classes": [], "interfaces": [], "types": [],
               "exports": [], "components": [], "imports": []}
    for i, line in enumerate(content.split('\n'), 1):
        m = _re.match(r'\s*class\s+(\w+)', line)
        if m:
            t = "class"
            if 'StatefulWidget' in line:
                t = "stateful_widget"
            elif 'StatelessWidget' in line:
                t = "stateless_widget"
            outline["classes"].append({"name": m.group(1), "line": i, "type": t})
            continue
        m = _re.match(r'\s*mixin\s+(\w+)', line)
        if m:
            outline["interfaces"].append({"name": m.group(1), "line": i, "type": "mixin"})
            continue
        m = _re.match(r'\s*enum\s+(\w+)', line)
        if m:
            outline["types"].append({"name": m.group(1), "line": i, "type": "enum"})
            continue
        m = _re.match(r'\s*extension\s+(\w+)', line)
        if m:
            outline["types"].append({"name": m.group(1), "line": i, "type": "extension"})
            continue
        m = _re.match(r'\s*(?:static\s+)?(?:async\s+)?(?:[\w<>\[\]?]+\s+)?(\w+)\s*\(', line)
        if m and m.group(1) not in ('if', 'else', 'while', 'for', 'switch', 'return',
                                     'class', 'abstract', 'mixin', 'extension', 'enum',
                                     'import', 'export', 'part', 'void', 'var', 'final', 'const'):
            outline["functions"].append({"name": m.group(1), "line": i, "type": "function"})
            continue
        m = _re.match(r"\s*import\s+['\"]([^'\"]+)['\"]", line)
        if m:
            outline["imports"].append({"name": m.group(1), "line": i})
    return outline


def _outline_swift(content: str, detail_level: str) -> Dict[str, Any]:
    """Outline Swift source: classes, structs, protocols, functions."""
    outline = {"functions": [], "classes": [], "interfaces": [], "types": [],
               "exports": [], "components": [], "imports": []}
    for i, line in enumerate(content.split('\n'), 1):
        m = _re.match(r'\s*(?:final\s+|open\s+|public\s+)*class\s+(\w+)', line)
        if m:
            outline["classes"].append({"name": m.group(1), "line": i, "type": "class"})
            continue
        m = _re.match(r'\s*(?:public\s+)*struct\s+(\w+)', line)
        if m:
            outline["classes"].append({"name": m.group(1), "line": i, "type": "struct"})
            continue
        m = _re.match(r'\s*(?:public\s+)*protocol\s+(\w+)', line)
        if m:
            outline["interfaces"].append({"name": m.group(1), "line": i, "type": "protocol"})
            continue
        m = _re.match(r'\s*extension\s+(\w+)', line)
        if m:
            outline["types"].append({"name": m.group(1), "line": i, "type": "extension"})
            continue
        m = _re.match(r'\s*enum\s+(\w+)', line)
        if m:
            outline["types"].append({"name": m.group(1), "line": i, "type": "enum"})
            continue
        m = _re.match(r'\s*(?:static\s+|class\s+|override\s+|public\s+|private\s+)*(?:func)\s+(\w+)', line)
        if m:
            outline["functions"].append({"name": m.group(1), "line": i, "type": "function"})
            continue
        m = _re.match(r'\s*import\s+(\w+)', line)
        if m:
            outline["imports"].append({"name": m.group(1), "line": i})
    return outline


def _outline_scala(content: str, detail_level: str) -> Dict[str, Any]:
    """Outline Scala source: classes, objects, traits, functions."""
    outline = {"functions": [], "classes": [], "interfaces": [], "types": [],
               "exports": [], "components": [], "imports": []}
    for i, line in enumerate(content.split('\n'), 1):
        m = _re.match(r'\s*case\s+class\s+(\w+)', line)
        if m:
            outline["classes"].append({"name": m.group(1), "line": i, "type": "case_class"})
            continue
        m = _re.match(r'\s*(?:abstract\s+)?class\s+(\w+)', line)
        if m:
            outline["classes"].append({"name": m.group(1), "line": i, "type": "class"})
            continue
        m = _re.match(r'\s*(?:sealed\s+)?trait\s+(\w+)', line)
        if m:
            outline["interfaces"].append({"name": m.group(1), "line": i, "type": "trait"})
            continue
        m = _re.match(r'\s*object\s+(\w+)', line)
        if m:
            outline["classes"].append({"name": m.group(1), "line": i, "type": "object"})
            continue
        m = _re.match(r'\s*enum\s+(\w+)', line)
        if m:
            outline["types"].append({"name": m.group(1), "line": i, "type": "enum"})
            continue
        m = _re.match(r'\s*(?:private\s+|protected\s+|override\s+|implicit\s+)*def\s+(\w+)', line)
        if m:
            outline["functions"].append({"name": m.group(1), "line": i, "type": "function"})
            continue
        m = _re.match(r'\s*import\s+([\w.{*}]+)', line)
        if m:
            outline["imports"].append({"name": m.group(1), "line": i})
    return outline


def _outline_shell(content: str, detail_level: str) -> Dict[str, Any]:
    """Outline Shell/Bash source: functions, exports, Dockerfile patterns."""
    outline = {"functions": [], "classes": [], "interfaces": [], "types": [],
               "exports": [], "components": [], "imports": []}
    for i, line in enumerate(content.split('\n'), 1):
        m = _re.match(r'\s*function\s+(\w+)\s*\(?', line)
        if m:
            outline["functions"].append({"name": m.group(1), "line": i, "type": "function"})
            continue
        m = _re.match(r'\s*(\w+)\s*\(\)\s*\{?', line)
        if m and m.group(1) not in ('if', 'then', 'else', 'elif', 'fi', 'for', 'while',
                                     'until', 'do', 'done', 'case', 'esac', 'in', 'function',
                                     'return', 'exit', 'echo', 'printf'):
            outline["functions"].append({"name": m.group(1), "line": i, "type": "function"})
            continue
        m = _re.match(r'\s*export\s+([\w_]+)', line)
        if m:
            outline["exports"].append({"name": m.group(1), "line": i})
            continue
        m = _re.match(r'\s*FROM\s+([\w:./-]+)', line, _re.IGNORECASE)
        if m:
            outline["imports"].append({"name": m.group(1), "line": i, "type": "docker_from"})
    return outline


def _outline_objc(content: str, detail_level: str = "normal") -> Dict[str, Any]:
    """Extract outline from Objective-C source code."""
    import re as _re
    outline = {"functions": [], "classes": [], "interfaces": [], "types": [],
               "exports": [], "components": [], "imports": []}

    lines = content.split('\n')

    for i, line in enumerate(lines, 1):
        # #import / #include
        m = _re.match(r'\s*#(?:import|include)\s+[<"]([^>"]+)[>"]', line)
        if m:
            outline["imports"].append({"name": m.group(1), "line": i, "type": "import"})
            continue

        # @interface ClassName : SuperClass
        m = _re.match(r'\s*@interface\s+(\w+)\s*(?:\(|:\s*(\w+))?', line)
        if m:
            cls_name = m.group(1)
            super_cls = m.group(2)
            entry = {"name": cls_name, "line": i, "type": "class"}
            if super_cls:
                entry["extends"] = super_cls
            outline["classes"].append(entry)
            continue

        # @interface ClassName (Category)
        m = _re.match(r'\s*@interface\s+(\w+)\s*\((\w*)\)', line)
        if m:
            cls_name = m.group(1)
            cat_name = m.group(2)
            entry = {"name": f"{cls_name}({cat_name})", "line": i,
                     "type": "category" if cat_name else "extension"}
            outline["classes"].append(entry)
            continue

        # @protocol ProtocolName
        m = _re.match(r'\s*@protocol\s+(\w+)', line)
        if m:
            outline["interfaces"].append({"name": m.group(1), "line": i, "type": "protocol"})
            continue

        # Instance/class methods: - (type)name or + (type)name
        m = _re.match(r'\s*([+-])\s*\([^)]*\)\s*(\w+)', line)
        if m:
            method_type = "class_method" if m.group(1) == '+' else "instance_method"
            method_name = m.group(2)
            # Get full selector
            parts = _re.findall(r'(\w+)\s*:', line)
            full_selector = ':'.join(parts) + ':' if parts else method_name
            outline["functions"].append({"name": full_selector, "line": i, "type": method_type})
            continue

        # C functions
        m = _re.match(r'\s*(?:static\s+)?(?:[\w*<>]+\s+)+(\w+)\s*\(', line)
        if m:
            fn_name = m.group(1)
            if fn_name not in ('if', 'else', 'while', 'for', 'switch', 'return', 'void',
                               'id', 'Class', 'SEL', 'IMP', 'BOOL', 'NSInteger'):
                ntype = "entry_point" if fn_name == "main" else "function"
                outline["functions"].append({"name": fn_name, "line": i, "type": ntype})
                continue

        # @property
        m = _re.match(r'\s*@property\s*\([^)]*\)\s*[\w<*>\s]+\s*(\w+)\s*;', line)
        if m:
            outline["exports"].append({"name": m.group(1), "line": i, "type": "property"})

    return outline


def _detect_language(ext: str) -> str:
    """Detect language from file extension."""
    mapping = {
        '.js': 'javascript', '.mjs': 'javascript', '.cjs': 'javascript',
        '.ts': 'typescript', '.tsx': 'tsx', '.jsx': 'tsx',
        '.rs': 'rust', '.py': 'python', '.go': 'go', '.php': 'php',
        '.html': 'html', '.htm': 'html',
        '.css': 'css', '.scss': 'scss', '.less': 'less',
        '.vue': 'vue', '.svelte': 'svelte',
        '.rb': 'ruby', '.ex': 'elixir', '.exs': 'elixir',
        '.dart': 'dart', '.swift': 'swift',
        '.scala': 'scala', '.sc': 'scala',
        '.sh': 'shell', '.bash': 'shell', '.zsh': 'shell', '.zsh-theme': 'shell',
        '.java': 'java', '.kt': 'kotlin', '.kts': 'kotlin',
        '.c': 'c', '.cpp': 'cpp', '.cc': 'cpp', '.cxx': 'cpp',
        '.h': 'c', '.hpp': 'cpp', '.hxx': 'cpp',
        '.cs': 'csharp', '.lua': 'lua',
        '.R': 'r', '.r': 'r',
        '.hs': 'haskell', '.lhs': 'haskell',
        '.nim': 'nim', '.nims': 'nim',
        '.gd': 'gdscript',
        '.zig': 'zig', '.wgsl': 'wgsl',
        '.m': 'objective-c', '.mm': 'objective-c++',
    }
    return mapping.get(ext, 'unknown')
