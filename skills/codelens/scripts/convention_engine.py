"""
convention_engine.py — Coding Convention Detection for CodeLens v5

Detects and reports coding conventions from the codebase including:
- Naming conventions (variables, functions, classes, files)
- File organization patterns
- Import styles
- Component patterns
- Error handling patterns
- State management patterns
"""

import os
import re
from typing import Dict, Any, List, Optional, Tuple


def detect_conventions(workspace: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Detect coding conventions from the codebase.
    
    Args:
        workspace: Path to the workspace root
        config: Optional workspace config dict
        
    Returns:
        Dict with status, conventions (naming, patterns), and metadata
    """
    workspace = os.path.abspath(workspace)
    
    conventions = {
        "naming": {},
        "patterns": {}
    }
    
    # Collect source files by language
    js_files = []  # .js, .jsx, .ts, .tsx
    py_files = []  # .py
    rs_files = []  # .rs
    vue_files = []  # .vue
    svelte_files = []  # .svelte
    all_source_files = []
    
    ignore_dirs = {
        'node_modules', '.git', 'dist', 'build', 'target',
        '__pycache__', '.codelens', '.next', '.cache',
        'vendor', '.venv', 'venv', 'env', '_archive',
        'coverage', '.pytest_cache', '.tox', '.idea', '.vscode',
    }
    
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith('.')]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            full_path = os.path.join(root, fn)
            if ext in {'.js', '.jsx', '.ts', '.tsx'}:
                js_files.append(full_path)
                all_source_files.append(full_path)
            elif ext == '.py':
                py_files.append(full_path)
                all_source_files.append(full_path)
            elif ext == '.rs':
                rs_files.append(full_path)
                all_source_files.append(full_path)
            elif ext == '.vue':
                vue_files.append(full_path)
            elif ext == '.svelte':
                svelte_files.append(full_path)
    
    # ─── Naming Conventions ──────────────────────────────────
    
    # File naming
    conventions["naming"]["files"] = _detect_file_naming(all_source_files, workspace)
    
    # JavaScript/TypeScript naming
    if js_files:
        js_naming = _detect_js_naming(js_files, workspace)
        if js_naming:
            conventions["naming"]["javascript"] = js_naming
    
    # Python naming
    if py_files:
        py_naming = _detect_python_naming(py_files, workspace)
        if py_naming:
            conventions["naming"]["python"] = py_naming
    
    # Rust naming
    if rs_files:
        rs_naming = _detect_rust_naming(rs_files, workspace)
        if rs_naming:
            conventions["naming"]["rust"] = rs_naming
    
    # ─── Pattern Detection ───────────────────────────────────
    
    # Import style
    if js_files:
        conventions["patterns"]["import_style"] = _detect_js_import_style(js_files, workspace)
    
    # Component pattern (React)
    if js_files:
        component_pattern = _detect_component_pattern(js_files, workspace)
        if component_pattern:
            conventions["patterns"]["components"] = component_pattern
    
    # Error handling
    conventions["patterns"]["error_handling"] = _detect_error_handling(all_source_files, workspace)
    
    # File organization
    conventions["patterns"]["file_organization"] = _detect_file_organization(workspace)
    
    # Module system
    if js_files:
        conventions["patterns"]["module_system"] = _detect_module_system(js_files, workspace)
    
    return {
        "status": "ok",
        "workspace": workspace,
        "files_analyzed": len(all_source_files),
        "conventions": conventions
    }


# ─── Naming Convention Helpers ────────────────────────────────

def _classify_case(name: str) -> str:
    """Classify the case style of a name."""
    if not name:
        return "unknown"
    if '_' in name and name == name.lower():
        return "snake_case"
    if '-' in name and name == name.lower():
        return "kebab-case"
    if name[0].isupper():
        return "PascalCase"
    if re.match(r'^[a-z]+[A-Z]', name):
        return "camelCase"
    if name == name.upper() and '_' in name:
        return "UPPER_SNAKE_CASE"
    return "unknown"


def _detect_file_naming(files: List[str], workspace: str) -> Dict[str, str]:
    """Detect file naming convention."""
    if not files:
        return {"convention": "unknown"}
    
    styles = {"snake_case": 0, "kebab-case": 0, "camelCase": 0, "PascalCase": 0}
    for f in files:
        basename = os.path.splitext(os.path.basename(f))[0]
        if not basename:
            continue
        case = _classify_case(basename)
        if case in styles:
            styles[case] += 1
    
    total = sum(styles.values())
    if total == 0:
        return {"convention": "unknown"}
    
    dominant = max(styles, key=styles.get)
    confidence = styles[dominant] / total
    
    result = {"convention": dominant}
    if confidence < 0.5:
        result["note"] = f"mixed conventions (dominant: {dominant} at {confidence:.0%})"
    else:
        result["confidence"] = f"{confidence:.0%}"
    
    return result


def _detect_js_naming(files: List[str], workspace: str) -> Dict[str, str]:
    """Detect JavaScript/TypeScript naming conventions by sampling files."""
    naming = {}
    
    # Analyze variable/function names from a sample
    var_styles = {"camelCase": 0, "snake_case": 0, "PascalCase": 0}
    func_styles = {"camelCase": 0, "snake_case": 0, "PascalCase": 0}
    const_styles = {"UPPER_SNAKE_CASE": 0, "camelCase": 0, "snake_case": 0}
    component_count = 0
    
    sample = files[:50]  # Sample up to 50 files
    
    for fpath in sample:
        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except IOError:
            continue
        
        # Variable declarations: const/let/var name
        for match in re.finditer(r'(?:const|let|var)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)', content):
            name = match.group(1)
            case = _classify_case(name)
            if case in var_styles:
                var_styles[case] += 1
            # Check for constants (UPPER_CASE)
            if name == name.upper() and len(name) > 1:
                const_styles["UPPER_SNAKE_CASE"] += 1
            elif case in const_styles:
                const_styles[case] += 1
        
        # Function declarations
        for match in re.finditer(r'function\s+([a-zA-Z_$][a-zA-Z0-9_$]*)', content):
            name = match.group(1)
            case = _classify_case(name)
            if case in func_styles:
                func_styles[case] += 1
            if name[0].isupper():
                component_count += 1
        
        # Arrow functions assigned to variables
        for match in re.finditer(r'(?:const|let)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*=\s*(?:async\s+)?\(', content):
            name = match.group(1)
            case = _classify_case(name)
            if case in func_styles:
                func_styles[case] += 1
            if name[0].isupper():
                component_count += 1
    
    # Determine dominant styles
    if sum(var_styles.values()) > 0:
        naming["variables"] = max(var_styles, key=var_styles.get)
    if sum(func_styles.values()) > 0:
        naming["functions"] = max(func_styles, key=func_styles.get)
    if sum(const_styles.values()) > 0:
        naming["constants"] = max(const_styles, key=const_styles.get)
    
    # Component naming
    if component_count > 3:
        naming["components"] = "PascalCase"
    
    return naming


def _detect_python_naming(files: List[str], workspace: str) -> Dict[str, str]:
    """Detect Python naming conventions by sampling files."""
    naming = {}
    
    func_styles = {"snake_case": 0, "camelCase": 0}
    class_styles = {"PascalCase": 0, "snake_case": 0}
    var_styles = {"snake_case": 0, "camelCase": 0}
    const_styles = {"UPPER_SNAKE_CASE": 0, "snake_case": 0}
    
    sample = files[:50]
    
    for fpath in sample:
        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except IOError:
            continue
        
        # def function_name
        for match in re.finditer(r'def\s+([a-zA-Z_][a-zA-Z0-9_]*)', content):
            name = match.group(1)
            case = _classify_case(name)
            if case in func_styles:
                func_styles[case] += 1
        
        # class ClassName
        for match in re.finditer(r'class\s+([a-zA-Z_][a-zA-Z0-9_]*)', content):
            name = match.group(1)
            case = _classify_case(name)
            if case in class_styles:
                class_styles[case] += 1
        
        # Variable assignments (simple)
        for match in re.finditer(r'^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*', content, re.MULTILINE):
            name = match.group(1)
            if name.startswith('_') or name in {'self', 'cls', 'if', 'for', 'while', 'return', 'import', 'from', 'with', 'try', 'except', 'raise', 'class', 'def', 'True', 'False', 'None'}:
                continue
            case = _classify_case(name)
            if name == name.upper() and len(name) > 1:
                const_styles["UPPER_SNAKE_CASE"] += 1
            elif case in var_styles:
                var_styles[case] += 1
    
    if sum(func_styles.values()) > 0:
        naming["functions"] = max(func_styles, key=func_styles.get)
    if sum(class_styles.values()) > 0:
        naming["classes"] = max(class_styles, key=class_styles.get)
    if sum(var_styles.values()) > 0:
        naming["variables"] = max(var_styles, key=var_styles.get)
    if sum(const_styles.values()) > 0:
        naming["constants"] = max(const_styles, key=const_styles.get)
    
    return naming


def _detect_rust_naming(files: List[str], workspace: str) -> Dict[str, str]:
    """Detect Rust naming conventions by sampling files."""
    # Rust has strong conventions: snake_case functions, PascalCase types
    naming = {
        "functions": "snake_case",
        "structs": "PascalCase",
        "enums": "PascalCase",
        "traits": "PascalCase",
        "constants": "UPPER_SNAKE_CASE",
        "modules": "snake_case"
    }
    
    # Verify by sampling
    func_styles = {"snake_case": 0, "other": 0}
    type_styles = {"PascalCase": 0, "other": 0}
    
    sample = files[:30]
    for fpath in sample:
        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except IOError:
            continue
        
        for match in re.finditer(r'fn\s+([a-zA-Z_][a-zA-Z0-9_]*)', content):
            name = match.group(1)
            case = _classify_case(name)
            if case == "snake_case":
                func_styles["snake_case"] += 1
            else:
                func_styles["other"] += 1
        
        for match in re.finditer(r'(?:struct|enum|trait)\s+([a-zA-Z_][a-zA-Z0-9_]*)', content):
            name = match.group(1)
            case = _classify_case(name)
            if case == "PascalCase":
                type_styles["PascalCase"] += 1
            else:
                type_styles["other"] += 1
    
    # Override if evidence contradicts Rust conventions
    if func_styles["other"] > func_styles["snake_case"] * 2:
        naming["functions"] = "non-standard"
    if type_styles["other"] > type_styles["PascalCase"] * 2:
        naming["structs"] = "non-standard"
    
    return naming


# ─── Pattern Detection Helpers ────────────────────────────────

def _detect_js_import_style(files: List[str], workspace: str) -> str:
    """Detect JavaScript import style."""
    esm_count = 0
    cjs_count = 0
    alias_count = 0
    
    sample = files[:30]
    for fpath in sample:
        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except IOError:
            continue
        
        # ESM: import ... from
        esm_count += len(re.findall(r'^\s*import\s+', content, re.MULTILINE))
        # CJS: require(...)
        cjs_count += len(re.findall(r'require\s*\(', content))
        # Aliases: @/ or ~/ or @src/
        alias_count += len(re.findall(r'''['"](?:@|~|@src)/[^'"]+['"]''', content))
    
    if esm_count == 0 and cjs_count == 0:
        return "unknown"
    
    style = "ES modules" if esm_count > cjs_count else "CommonJS"
    if alias_count > esm_count * 0.3:
        style += " with path aliases"
    
    return style


def _detect_component_pattern(files: List[str], workspace: str) -> str:
    """Detect React component pattern."""
    functional = 0
    class_comp = 0
    hooks_count = 0
    
    sample = files[:40]
    for fpath in sample:
        ext = os.path.splitext(fpath)[1].lower()
        if ext not in {'.js', '.jsx', '.ts', '.tsx'}:
            continue
        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except IOError:
            continue
        
        # Class components
        class_comp += len(re.findall(r'class\s+\w+\s+extends\s+(?:React\.)?Component', content))
        # Functional components (arrow functions returning JSX)
        functional += len(re.findall(r'(?:const|function)\s+[A-Z]\w*\s*(?:=\s*(?:\([^)]*\)|[a-zA-Z]*)\s*=>|[^=])', content))
        # Hooks
        hooks_count += len(re.findall(r'use[A-Z]\w*\(', content))
    
    if functional == 0 and class_comp == 0:
        return ""
    
    if functional > class_comp:
        pattern = "functional"
    else:
        pattern = "class-based"
    
    if hooks_count > functional * 0.5:
        pattern += " with hooks"
    
    return pattern


def _detect_error_handling(files: List[str], workspace: str) -> str:
    """Detect dominant error handling pattern."""
    try_catch = 0
    result_type = 0
    exception_class = 0
    error_callback = 0
    
    sample = files[:30]
    for fpath in sample:
        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except IOError:
            continue
        
        ext = os.path.splitext(fpath)[1].lower()
        
        # try-catch
        try_catch += len(re.findall(r'\btry\s*:', content))  # Python
        try_catch += len(re.findall(r'\btry\s*\{', content))  # JS/TS
        
        # Result type (Rust, or JS libraries like neverthrow)
        result_type += len(re.findall(r'Result<|Ok\(|Err\(', content))  # Rust
        result_type += len(re.findall(r'Result\s*<|ok\(|err\(|okl\(|errl\(', content, re.IGNORECASE))  # JS
        
        # Custom exception classes
        exception_class += len(re.findall(r'class\s+\w*Error\w*\s*(?:\(|:)', content))
        exception_class += len(re.findall(r'class\s+\w*Exception\w*', content))
        
        # Error callbacks (.catch, onError, etc)
        error_callback += len(re.findall(r'\.catch\s*\(|onError|on_error|handleError|handle_error', content))
    
    patterns = {
        "try-catch": try_catch,
        "result-type": result_type,
        "custom-exceptions": exception_class,
        "error-callbacks": error_callback
    }
    
    if sum(patterns.values()) == 0:
        return "unknown"
    
    dominant = max(patterns, key=patterns.get)
    return dominant


def _detect_file_organization(workspace: str) -> str:
    """Detect project file organization pattern."""
    # Check for common patterns
    has_src = os.path.isdir(os.path.join(workspace, 'src'))
    has_app = os.path.isdir(os.path.join(workspace, 'src', 'app')) if has_src else False
    has_components = os.path.isdir(os.path.join(workspace, 'src', 'components')) if has_src else False
    has_pages = os.path.isdir(os.path.join(workspace, 'src', 'pages')) if has_src else False
    has_lib = os.path.isdir(os.path.join(workspace, 'src', 'lib')) if has_src else False
    has_routes = os.path.isdir(os.path.join(workspace, 'src', 'routes')) if has_src else False
    has_api = os.path.isdir(os.path.join(workspace, 'src', 'api')) if has_src else False
    has_features = os.path.isdir(os.path.join(workspace, 'src', 'features')) if has_src else False
    has_modules = os.path.isdir(os.path.join(workspace, 'src', 'modules')) if has_src else False
    
    # Feature-based
    if has_features:
        return "feature-based"
    
    # Next.js App Router
    if has_app and has_lib:
        return "app-router (Next.js)"
    
    # Pages Router
    if has_pages and has_api:
        return "pages-router (Next.js)"
    
    # Route-based
    if has_routes:
        return "route-based"
    
    # Module-based
    if has_modules:
        return "module-based"
    
    # Component-based
    if has_components:
        return "component-based"
    
    # Flat
    if not has_src:
        return "flat"
    
    # Layer-based default
    if has_src:
        return "layer-based"
    
    return "unknown"


def _detect_module_system(files: List[str], workspace: str) -> str:
    """Detect module system from package.json or file analysis."""
    # Check package.json first
    pkg_path = os.path.join(workspace, 'package.json')
    if os.path.isfile(pkg_path):
        try:
            import json
            with open(pkg_path, 'r', encoding='utf-8') as f:
                pkg = json.load(f)
            mtype = pkg.get("type", "")
            if mtype == "module":
                return "ESM"
            elif mtype == "commonjs":
                return "CommonJS"
        except Exception:
            pass
    
    # Fallback: analyze imports
    esm = 0
    cjs = 0
    sample = files[:20]
    for fpath in sample:
        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except IOError:
            continue
        
        esm += len(re.findall(r'^\s*import\s+', content, re.MULTILINE))
        esm += len(re.findall(r'^\s*export\s+', content, re.MULTILINE))
        cjs += len(re.findall(r'require\s*\(', content))
        cjs += len(re.findall(r'module\.exports\s*=', content))
    
    if esm > cjs:
        return "ESM"
    elif cjs > esm:
        return "CommonJS"
    return "mixed"
