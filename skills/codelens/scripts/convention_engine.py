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
    conventions["patterns"]["error_handling"] = _detect_error_handling_basic(all_source_files, workspace)
    
    # File organization
    conventions["patterns"]["file_organization"] = _detect_file_organization(workspace)
    
    # Module system
    if js_files:
        conventions["patterns"]["module_system"] = _detect_module_system(js_files, workspace)
    
    # ─── Semantic Convention Detection ─────────────────────────
    
    conventions["semantic"] = {}
    
    sem_orm = _detect_orm_patterns(all_source_files, workspace)
    if sem_orm.get("orm"):
        conventions["semantic"]["orm"] = sem_orm
    
    sem_error = _detect_error_handling(all_source_files, workspace)
    if sem_error.get("style"):
        conventions["semantic"]["error_handling"] = sem_error
    
    sem_api = _detect_api_response_pattern(all_source_files, workspace)
    if sem_api.get("format"):
        conventions["semantic"]["api_response"] = sem_api
    
    sem_state = _detect_state_management(js_files, workspace)
    if sem_state.get("library"):
        conventions["semantic"]["state_management"] = sem_state
    
    sem_test = _detect_testing_framework(all_source_files, workspace)
    if sem_test.get("framework"):
        conventions["semantic"]["testing"] = sem_test
    
    sem_css = _detect_css_framework(all_source_files, workspace)
    if sem_css.get("framework"):
        conventions["semantic"]["css_framework"] = sem_css
    
    sem_auth = _detect_auth_pattern(all_source_files, workspace)
    if sem_auth.get("provider"):
        conventions["semantic"]["authentication"] = sem_auth
    
    sem_deploy = _detect_deployment_pattern(workspace)
    if sem_deploy.get("platform"):
        conventions["semantic"]["deployment"] = sem_deploy
    
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


def _detect_error_handling_basic(files: List[str], workspace: str) -> str:
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


# ─── Semantic Convention Detection Helpers ─────────────────────

def _detect_orm_patterns(all_source_files: List[str], workspace: str) -> Dict[str, Any]:
    """Detect ORM/database patterns in the codebase."""
    scores = {
        "prisma": 0,
        "sqlalchemy": 0,
        "typeorm": 0,
        "mongoose": 0,
        "drizzle": 0,
        "knex": 0,
    }

    # Check for schema.prisma file existence
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in {'node_modules', '.git', 'dist', 'build', '__pycache__', '.codelens', '.next', '.cache', 'venv', '.venv'} and not d.startswith('.')]
        for fn in filenames:
            if fn == 'schema.prisma':
                scores["prisma"] += 5

    sample = all_source_files[:30]
    for fpath in sample:
        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except IOError:
            continue

        # Prisma
        if re.search(r"from\s+['\"]@prisma/client['\"]" , content):
            scores["prisma"] += 3
        if re.search(r'prisma\.', content):
            scores["prisma"] += 2

        # SQLAlchemy
        if re.search(r'from\s+sqlalchemy', content):
            scores["sqlalchemy"] += 3
        if re.search(r'Base\s*=', content):
            scores["sqlalchemy"] += 2
        if re.search(r'Column\s*\(', content):
            scores["sqlalchemy"] += 2

        # TypeORM
        if re.search(r'@Entity', content):
            scores["typeorm"] += 3
        if re.search(r'@Column', content):
            scores["typeorm"] += 2
        if re.search(r'Repository\s*<', content):
            scores["typeorm"] += 2

        # Mongoose
        if re.search(r'mongoose\.model', content):
            scores["mongoose"] += 3
        if re.search(r'new\s+Schema', content):
            scores["mongoose"] += 3

        # Drizzle
        if re.search(r"drizzle-orm", content):
            scores["drizzle"] += 3
        if re.search(r'pgTable\s*\(', content):
            scores["drizzle"] += 3
        if re.search(r'sqliteTable\s*\(', content):
            scores["drizzle"] += 3

        # Knex
        if re.search(r'knex\s*\(', content):
            scores["knex"] += 3
        if re.search(r'\.table\s*\(', content):
            scores["knex"] += 1
        if re.search(r'\.raw\s*\(', content):
            scores["knex"] += 1

    best = max(scores, key=scores.get)
    best_score = scores[best]

    if best_score == 0:
        return {"orm": None, "confidence": "low", "style_hint": "No ORM patterns detected"}

    if best_score >= 5:
        confidence = "high"
    elif best_score >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    style_hints = {
        "prisma": "Generate models using schema.prisma style",
        "sqlalchemy": "Use SQLAlchemy declarative models with Base class",
        "typeorm": "Use TypeORM entities with @Entity and @Column decorators",
        "mongoose": "Use Mongoose schemas with new Schema() pattern",
        "drizzle": "Use Drizzle table definitions with pgTable/sqliteTable",
        "knex": "Use Knex migration and query builder patterns",
    }

    return {
        "orm": best,
        "confidence": confidence,
        "style_hint": style_hints.get(best, f"Use {best} patterns"),
    }


def _detect_error_handling(all_source_files: List[str], workspace: str) -> Dict[str, Any]:
    """Detect error handling style in the codebase (semantic version)."""
    styles = {
        "try_catch": 0,
        "result_type": 0,
        "either": 0,
        "custom_error_class": 0,
        "exception_hierarchy": 0,
    }

    sample = all_source_files[:30]
    for fpath in sample:
        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except IOError:
            continue

        # try-catch
        if re.search(r'\btry\s*:', content):  # Python
            styles["try_catch"] += 1
        if re.search(r'\btry\s*\{', content):  # JS/TS
            styles["try_catch"] += 1

        # Result type
        if re.search(r'Result\s*<', content):
            styles["result_type"] += 2
        if re.search(r'\bOk\s*\(', content):
            styles["result_type"] += 1
        if re.search(r'\bErr\s*\(', content):
            styles["result_type"] += 1
        if re.search(r'neverthrow', content):
            styles["result_type"] += 3

        # Either type
        if re.search(r'Either\s*<', content):
            styles["either"] += 2
        if re.search(r'\bLeft\s*\(', content):
            styles["either"] += 1
        if re.search(r'\bRight\s*\(', content):
            styles["either"] += 1

        # Custom error classes
        if re.search(r'class\s+\w+Error\s+extends', content):
            styles["custom_error_class"] += 2
        if re.search(r'class\s+\w+Error\s*\(', content):
            styles["custom_error_class"] += 2

        # Exception hierarchy
        if re.search(r'class\s+\w+Exception\s+extends\s+\w+Exception', content):
            styles["exception_hierarchy"] += 3

    # Find dominant style
    best = max(styles, key=styles.get)
    best_score = styles[best]

    if best_score == 0:
        return {"style": None, "styles_found": [], "confidence": "low", "hint": "No error handling patterns detected"}

    if best_score >= 4:
        confidence = "high"
    elif best_score >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    # Collect all styles that were found
    styles_found = [s for s, count in styles.items() if count > 0]

    hints = {
        "try_catch": "Use try-catch blocks for error handling",
        "result_type": "Use Result<T, E> pattern instead of throwing exceptions",
        "either": "Use Either monad for error handling",
        "custom_error_class": "Throw custom errors, don't use generic Error",
        "exception_hierarchy": "Use exception hierarchy with custom base exception class",
    }

    return {
        "style": best,
        "styles_found": styles_found,
        "confidence": confidence,
        "hint": hints.get(best, f"Use {best} pattern for errors"),
    }


def _detect_api_response_pattern(all_source_files: List[str], workspace: str) -> Dict[str, Any]:
    """Detect API response format pattern in the codebase."""
    scores = {
        "envelope": 0,
        "next_response": 0,
        "express": 0,
        "trpc": 0,
    }

    sample = all_source_files[:30]
    for fpath in sample:
        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except IOError:
            continue

        # Envelope pattern: {"success": true/false, "data": ..., "error": ...}
        if re.search(r'"success"\s*:', content) or re.search(r"'success'\s*:", content):
            scores["envelope"] += 2
        if re.search(r'"data"\s*:', content) and re.search(r'"error"\s*:', content):
            scores["envelope"] += 2
        if re.search(r'\{.*success.*data.*error.*\}', content, re.IGNORECASE):
            scores["envelope"] += 3

        # Next.js style
        if re.search(r'NextResponse\.json\s*\(', content):
            scores["next_response"] += 3
        if re.search(r'NextResponse', content):
            scores["next_response"] += 1

        # Express style
        if re.search(r'res\.status\s*\(.*\)\.json', content):
            scores["express"] += 3
        if re.search(r'res\.json\s*\(', content):
            scores["express"] += 1

        # tRPC
        if re.search(r't\.router', content):
            scores["trpc"] += 3
        if re.search(r'publicProcedure', content):
            scores["trpc"] += 3
        if re.search(r'protectedProcedure', content):
            scores["trpc"] += 2

    best = max(scores, key=scores.get)
    best_score = scores[best]

    if best_score == 0:
        return {"format": None, "confidence": "low", "hint": "No API response patterns detected"}

    if best_score >= 5:
        confidence = "high"
    elif best_score >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    hints = {
        "envelope": "Always wrap in {success, data, error}",
        "next_response": "Use NextResponse.json() for API responses",
        "express": "Use res.status().json() pattern for responses",
        "trpc": "Use tRPC procedures and routers for type-safe APIs",
    }

    return {
        "format": best,
        "confidence": confidence,
        "hint": hints.get(best, f"Use {best} API response pattern"),
    }


def _detect_state_management(js_files: List[str], workspace: str) -> Dict[str, Any]:
    """Detect state management library in JavaScript/TypeScript codebase."""
    scores = {
        "zustand": 0,
        "redux": 0,
        "mobx": 0,
        "recoil": 0,
        "jotai": 0,
        "pinia": 0,
        "context_api": 0,
    }

    sample = js_files[:30]
    for fpath in sample:
        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except IOError:
            continue

        # Zustand
        if re.search(r"from\s+['\"]zustand['\"]", content):
            scores["zustand"] += 3
        if re.search(r'\bcreate\s*\(', content) and re.search(r'zustand', content, re.IGNORECASE):
            scores["zustand"] += 2
        if re.search(r'useStore', content):
            scores["zustand"] += 1

        # Redux
        if re.search(r'createStore', content):
            scores["redux"] += 2
        if re.search(r'useSelector', content):
            scores["redux"] += 2
        if re.search(r'useDispatch', content):
            scores["redux"] += 2
        if re.search(r'createSlice', content):
            scores["redux"] += 3

        # MobX
        if re.search(r'\bobservable\b', content):
            scores["mobx"] += 2
        if re.search(r'\baction\b', content) and re.search(r'mobx', content, re.IGNORECASE):
            scores["mobx"] += 1
        if re.search(r'makeAutoObservable', content):
            scores["mobx"] += 3

        # Recoil
        if re.search(r'useRecoilState', content):
            scores["recoil"] += 3
        if re.search(r'\batom\s*\(', content) and re.search(r'recoil', content, re.IGNORECASE):
            scores["recoil"] += 2
        if re.search(r'\bselector\s*\(', content) and re.search(r'recoil', content, re.IGNORECASE):
            scores["recoil"] += 2

        # Jotai
        if re.search(r"from\s+['\"]jotai['\"]", content):
            scores["jotai"] += 3
        if re.search(r'\batom\s*\(', content) and re.search(r'jotai', content, re.IGNORECASE):
            scores["jotai"] += 2
        if re.search(r'useAtom', content):
            scores["jotai"] += 2

        # Pinia
        if re.search(r'defineStore', content):
            scores["pinia"] += 3
        if re.search(r'useStore', content) and re.search(r'pinia', content, re.IGNORECASE):
            scores["pinia"] += 2

        # Context API
        if re.search(r'createContext', content):
            scores["context_api"] += 2
        if re.search(r'useContext', content):
            scores["context_api"] += 1
        if re.search(r'useReducer', content):
            scores["context_api"] += 1

    best = max(scores, key=scores.get)
    best_score = scores[best]

    if best_score == 0:
        return {"library": None, "confidence": "low", "hint": "No state management patterns detected"}

    if best_score >= 5:
        confidence = "high"
    elif best_score >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    hints = {
        "zustand": "Use create() pattern for stores",
        "redux": "Use createSlice with Redux Toolkit patterns",
        "mobx": "Use makeAutoObservable for reactive stores",
        "recoil": "Use atom/selector pattern for state",
        "jotai": "Use atom() primitive for state management",
        "pinia": "Use defineStore() for Vue stores",
        "context_api": "Use React Context + useReducer for state",
    }

    return {
        "library": best,
        "confidence": confidence,
        "hint": hints.get(best, f"Use {best} for state management"),
    }


def _detect_testing_framework(all_source_files: List[str], workspace: str) -> Dict[str, Any]:
    """Detect testing framework in the codebase."""
    scores = {
        "jest": 0,
        "vitest": 0,
        "pytest": 0,
        "mocha": 0,
        "playwright": 0,
    }

    sample = all_source_files[:30]
    for fpath in sample:
        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except IOError:
            continue

        ext = os.path.splitext(fpath)[1].lower()

        # Jest
        if re.search(r'\bdescribe\s*\(', content) and ext in {'.js', '.jsx', '.ts', '.tsx'}:
            scores["jest"] += 1
        if re.search(r'\bit\s*\(', content) and ext in {'.js', '.jsx', '.ts', '.tsx'}:
            scores["jest"] += 1
        if re.search(r'\btest\s*\(', content) and ext in {'.js', '.jsx', '.ts', '.tsx'}:
            scores["jest"] += 1
        if re.search(r'\bexpect\s*\(', content) and ext in {'.js', '.jsx', '.ts', '.tsx'}:
            scores["jest"] += 1
        if re.search(r'\bjest\s*\.', content):
            scores["jest"] += 3

        # Vitest
        if re.search(r"from\s+['\"]vitest['\"]", content):
            scores["vitest"] += 4
        if re.search(r'\bdescribe\s*\(', content) and re.search(r'vitest', content, re.IGNORECASE):
            scores["vitest"] += 2
        if re.search(r'\bvi\s*\.', content):
            scores["vitest"] += 3

        # Pytest
        if ext == '.py':
            if re.search(r'def\s+test_', content):
                scores["pytest"] += 3
            if re.search(r'@pytest', content):
                scores["pytest"] += 3
            if re.search(r'\bassert\s+', content) and re.search(r'def\s+test_', content):
                scores["pytest"] += 1

        # Mocha
        if re.search(r'\bdescribe\s*\(', content) and re.search(r'\bbeforeEach\s*\(', content):
            scores["mocha"] += 2
        if re.search(r"from\s+['\"]mocha['\"]", content):
            scores["mocha"] += 4

        # Playwright
        if re.search(r'@test', content):
            scores["playwright"] += 3
        if re.search(r"from\s+['\"]@playwright/test['\"]", content):
            scores["playwright"] += 4
        if re.search(r'\bpage\.', content) and re.search(r'locator\s*\(', content):
            scores["playwright"] += 2

    # Deduct vitest score from jest (they share describe/it/expect patterns)
    if scores["vitest"] > 0:
        scores["jest"] = max(0, scores["jest"] - scores["vitest"])

    best = max(scores, key=scores.get)
    best_score = scores[best]

    if best_score == 0:
        return {"framework": None, "style": None, "confidence": "low", "hint": "No testing patterns detected"}

    if best_score >= 5:
        confidence = "high"
    elif best_score >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    style_map = {
        "jest": "describe/it",
        "vitest": "describe/it",
        "pytest": "def test_",
        "mocha": "describe/it",
        "playwright": "@test/page",
    }

    hints = {
        "jest": "Use describe/it blocks with expect() assertions",
        "vitest": "Use describe/it blocks with expect() from vitest",
        "pytest": "Use test_ function prefix with assert statements",
        "mocha": "Use describe/it blocks with beforeEach for setup",
        "playwright": "Use @test decorators with page.locator() for E2E",
    }

    return {
        "framework": best,
        "style": style_map.get(best),
        "confidence": confidence,
        "hint": hints.get(best, f"Use {best} testing patterns"),
    }


def _detect_css_framework(all_source_files: List[str], workspace: str) -> Dict[str, Any]:
    """Detect CSS framework in the codebase."""
    scores = {
        "tailwind": 0,
        "bootstrap": 0,
        "material_ui": 0,
        "chakra_ui": 0,
        "ant_design": 0,
        "bulma": 0,
    }

    # Check for config files
    config_files = {
        "tailwind.config.js": ("tailwind", 5),
        "tailwind.config.ts": ("tailwind", 5),
        "tailwind.config.mjs": ("tailwind", 5),
        "tailwind.config.cjs": ("tailwind", 5),
    }

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in {'node_modules', '.git', 'dist', 'build', '__pycache__', '.codelens', '.next', '.cache', 'venv', '.venv'} and not d.startswith('.')]
        for fn in filenames:
            if fn in config_files:
                framework, points = config_files[fn]
                scores[framework] += points

    # Check package.json for dependencies
    pkg_path = os.path.join(workspace, 'package.json')
    if os.path.isfile(pkg_path):
        try:
            import json
            with open(pkg_path, 'r', encoding='utf-8') as f:
                pkg = json.load(f)
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

            # Tailwind CSS
            if "tailwindcss" in deps:
                scores["tailwind"] += 5
            if "@tailwindcss" in str(deps.keys()):
                scores["tailwind"] += 3

            # Bootstrap
            if "bootstrap" in deps:
                scores["bootstrap"] += 5
            if "react-bootstrap" in deps:
                scores["bootstrap"] += 3

            # Material UI
            if "@mui/material" in deps:
                scores["material_ui"] += 5
            if "@mui" in str(deps.keys()):
                scores["material_ui"] += 3

            # Chakra UI
            if "@chakra-ui/react" in deps or "@chakra-ui/core" in deps:
                scores["chakra_ui"] += 5

            # Ant Design
            if "antd" in deps:
                scores["ant_design"] += 5

            # Bulma
            if "bulma" in deps:
                scores["bulma"] += 5
        except Exception:
            pass

    # Check source files for class name patterns and imports
    sample = all_source_files[:30]
    for fpath in sample:
        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except IOError:
            continue

        # Tailwind CSS — utility class patterns
        if re.search(r'className=["\'][^"\']*(?:flex|grid|bg-|text-|p-\d|m-\d|w-|h-|rounded|shadow)', content):
            scores["tailwind"] += 2
        if re.search(r"from\s+['\"]tailwindcss['\"]", content):
            scores["tailwind"] += 3
        if re.search(r'@tailwind\s+', content):
            scores["tailwind"] += 3
        if re.search(r'@apply\s+', content):
            scores["tailwind"] += 2

        # Bootstrap — container, row, col, btn, etc.
        if re.search(r'className=["\'][^"\']*(?:container|row|col-(?:sm|md|lg|xl)|btn(?:-primary|-secondary|-danger))', content):
            scores["bootstrap"] += 2
        if re.search(r"from\s+['\"]bootstrap['\"]", content):
            scores["bootstrap"] += 3

        # Material UI — MUI imports
        if re.search(r"from\s+['\"]@mui", content):
            scores["material_ui"] += 3
        if re.search(r'<(?:TextField|Button|Box|Stack|Grid|Paper|AppBar)', content):
            scores["material_ui"] += 2

        # Chakra UI
        if re.search(r"from\s+['\"]@chakra-ui", content):
            scores["chakra_ui"] += 3
        if re.search(r'<(?:Box|Flex|Stack|VStack|HStack|Button|Input|Text)\s', content) and re.search(r'chakra', content, re.IGNORECASE):
            scores["chakra_ui"] += 2

        # Ant Design
        if re.search(r"from\s+['\"]antd['\"]", content):
            scores["ant_design"] += 3
        if re.search(r'<(?:Table|Form|Input|Button|Modal|Select)\s', content) and re.search(r'antd', content, re.IGNORECASE):
            scores["ant_design"] += 2

        # Bulma
        if re.search(r'className=["\'][^"\']*(?:is-(?:primary|danger|warning|info|success)|has-text|column|section|hero)', content):
            scores["bulma"] += 2
        if re.search(r"from\s+['\"]bulma['\"]", content):
            scores["bulma"] += 3

    best = max(scores, key=scores.get)
    best_score = scores[best]

    if best_score == 0:
        return {"framework": None, "confidence": "low", "hint": "No CSS framework patterns detected"}

    if best_score >= 5:
        confidence = "high"
    elif best_score >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    hints = {
        "tailwind": "Use Tailwind utility classes",
        "bootstrap": "Use Bootstrap grid and component classes",
        "material_ui": "Use MUI components with sx prop or styled API",
        "chakra_ui": "Use Chakra UI components with style props",
        "ant_design": "Use Ant Design components with Form.Item pattern",
        "bulma": "Use Bulma modifier and helper classes",
    }

    return {
        "framework": best,
        "confidence": confidence,
        "hint": hints.get(best, f"Use {best} for styling"),
    }


def _detect_auth_pattern(all_source_files: List[str], workspace: str) -> Dict[str, Any]:
    """Detect authentication pattern in the codebase."""
    scores = {
        "nextauth": 0,
        "passport": 0,
        "jwt": 0,
        "oauth": 0,
        "firebase_auth": 0,
        "supabase_auth": 0,
        "clerk": 0,
    }

    # Check package.json for auth dependencies
    pkg_path = os.path.join(workspace, 'package.json')
    if os.path.isfile(pkg_path):
        try:
            import json
            with open(pkg_path, 'r', encoding='utf-8') as f:
                pkg = json.load(f)
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

            if "next-auth" in deps:
                scores["nextauth"] += 5
            if "passport" in deps:
                scores["passport"] += 5
            if "jsonwebtoken" in deps or "jose" in deps:
                scores["jwt"] += 4
            if "firebase" in deps:
                scores["firebase_auth"] += 5
            if "@supabase/supabase-js" in deps or "@supabase/auth" in deps:
                scores["supabase_auth"] += 5
            if "@clerk/nextjs" in deps or "@clerk/clerk-js" in deps:
                scores["clerk"] += 5
        except Exception:
            pass

    # Check Python dependencies
    req_path = os.path.join(workspace, 'requirements.txt')
    if os.path.isfile(req_path):
        try:
            with open(req_path, 'r', encoding='utf-8') as f:
                req_content = f.read().lower()
            if 'pyjwt' in req_content or 'python-jose' in req_content:
                scores["jwt"] += 4
            if 'authlib' in req_content or 'python-social-auth' in req_content:
                scores["oauth"] += 4
            if 'firebase-admin' in req_content:
                scores["firebase_auth"] += 4
            if 'supabase' in req_content:
                scores["supabase_auth"] += 4
            if 'flask-login' in req_content or 'django' in req_content:
                scores["jwt"] += 1  # Generic session-based auth
        except Exception:
            pass

    # Check source files for import patterns and middleware
    sample = all_source_files[:30]
    for fpath in sample:
        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except IOError:
            continue

        # NextAuth
        if re.search(r"from\s+['\"]next-auth['\"]", content):
            scores["nextauth"] += 3
        if re.search(r'NextAuth\s*\(', content):
            scores["nextauth"] += 3
        if re.search(r'useSession\s*\(', content):
            scores["nextauth"] += 2
        if re.search(r'getServerSession\s*\(', content):
            scores["nextauth"] += 2
        if re.search(r'SessionProvider', content):
            scores["nextauth"] += 2
        if re.search(r'\[...nextauth\]', content):
            scores["nextauth"] += 3

        # Passport.js
        if re.search(r"from\s+['\"]passport['\"]", content):
            scores["passport"] += 3
        if re.search(r'passport\.use\s*\(', content):
            scores["passport"] += 3
        if re.search(r'passport\.authenticate\s*\(', content):
            scores["passport"] += 2
        if re.search(r'passport-strategy', content):
            scores["passport"] += 2

        # JWT
        if re.search(r"from\s+['\"]jsonwebtoken['\"]", content):
            scores["jwt"] += 3
        if re.search(r'jwt\.sign\s*\(', content):
            scores["jwt"] += 3
        if re.search(r'jwt\.verify\s*\(', content):
            scores["jwt"] += 3
        if re.search(r'Bearer\s+[\w-]+\.[\w-]+', content):
            scores["jwt"] += 2
        if re.search(r'Authorization.*Bearer', content):
            scores["jwt"] += 2

        # OAuth
        if re.search(r'oauth', content, re.IGNORECASE):
            scores["oauth"] += 1
        if re.search(r'client_id|client_secret|redirect_uri|authorization_code', content):
            scores["oauth"] += 2
        if re.search(r'/auth/(?:google|github|twitter|facebook|apple)', content):
            scores["oauth"] += 3

        # Firebase Auth
        if re.search(r"from\s+['\"]firebase/auth['\"]", content):
            scores["firebase_auth"] += 3
        if re.search(r'createUserWithEmailAndPassword|signInWithEmailAndPassword', content):
            scores["firebase_auth"] += 3
        if re.search(r'auth\.currentUser', content):
            scores["firebase_auth"] += 2

        # Supabase Auth
        if re.search(r"from\s+['\"]@supabase", content) and re.search(r'auth', content):
            scores["supabase_auth"] += 3
        if re.search(r'supabase\.auth\.', content):
            scores["supabase_auth"] += 3
        if re.search(r'signUp|signInWithPassword', content) and re.search(r'supabase', content, re.IGNORECASE):
            scores["supabase_auth"] += 2

        # Clerk
        if re.search(r"from\s+['\"]@clerk", content):
            scores["clerk"] += 3
        if re.search(r'useUser\s*\(\s*\)|useAuth\s*\(\s*\)', content):
            scores["clerk"] += 2
        if re.search(r'SignedIn|SignedOut|SignInButton|UserButton', content):
            scores["clerk"] += 3

        # Session handling patterns (generic)
        if re.search(r'getSession|session\.user|req\.session', content):
            scores["nextauth"] += 1

        # Middleware auth pattern
        if re.search(r'middleware.*auth|withAuth|requireAuth|authenticate\s*\(', content):
            scores["jwt"] += 1

    best = max(scores, key=scores.get)
    best_score = scores[best]

    if best_score == 0:
        return {"provider": None, "confidence": "low", "hint": "No authentication patterns detected"}

    if best_score >= 5:
        confidence = "high"
    elif best_score >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    # Determine auth style
    style_map = {
        "nextauth": "session_based",
        "passport": "session_based",
        "jwt": "token_based",
        "oauth": "delegated",
        "firebase_auth": "token_based",
        "supabase_auth": "token_based",
        "clerk": "session_based",
    }

    hints = {
        "nextauth": "Use NextAuth session providers and useSession hook",
        "passport": "Use Passport.js strategies for authentication",
        "jwt": "Use JWT tokens with Bearer authorization header",
        "oauth": "Use OAuth2 authorization code flow with PKCE",
        "firebase_auth": "Use Firebase Auth with onAuthStateChanged listener",
        "supabase_auth": "Use Supabase Auth with signIn/signUp methods",
        "clerk": "Use Clerk components and hooks (useUser, useAuth)",
    }

    return {
        "provider": best,
        "style": style_map.get(best, "unknown"),
        "confidence": confidence,
        "hint": hints.get(best, f"Use {best} for authentication"),
    }


def _detect_deployment_pattern(workspace: str) -> Dict[str, Any]:
    """Detect deployment platform from config files in the workspace."""
    deployment_files = {
        "vercel.json": "vercel",
        ".vercel/project.json": "vercel",
        "netlify.toml": "netlify",
        ".netlify/state.json": "netlify",
        "Dockerfile": "docker",
        "docker-compose.yml": "docker",
        "docker-compose.yaml": "docker",
        "fly.toml": "fly_io",
        "railway.json": "railway",
        "railway.toml": "railway",
        "render.yaml": "render",
        "heroku.yml": "heroku",
        "Procfile": "heroku",
        "app.yaml": "gcp",
        ".cloudrun.yaml": "gcp",
        "serverless.yml": "aws_lambda",
        "serverless.yaml": "aws_lambda",
        "template.yaml": "aws_sam",
        "terraform": "terraform",
        "main.tf": "terraform",
        "cdk.json": "aws_cdk",
    }

    found_platforms: Dict[str, List[str]] = {}
    config_files_found = []

    for rel_path, platform in deployment_files.items():
        full_path = os.path.join(workspace, rel_path)
        if os.path.isfile(full_path):
            config_files_found.append(rel_path)
            if platform not in found_platforms:
                found_platforms[platform] = []
            found_platforms[platform].append(rel_path)

    # Check package.json for deployment hints
    pkg_path = os.path.join(workspace, 'package.json')
    if os.path.isfile(pkg_path):
        try:
            import json
            with open(pkg_path, 'r', encoding='utf-8') as f:
                pkg = json.load(f)
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

            if "vercel" in deps or "@vercel" in str(deps.keys()):
                if "vercel" not in found_platforms:
                    found_platforms["vercel"] = []
                found_platforms["vercel"].append("package.json (vercel dependency)")
            if "@netlify" in str(deps.keys()):
                if "netlify" not in found_platforms:
                    found_platforms["netlify"] = []
                found_platforms["netlify"].append("package.json (netlify dependency)")
        except Exception:
            pass

    # Check for .github/workflows (CI/CD but hints at deployment)
    github_workflows = os.path.join(workspace, '.github', 'workflows')
    if os.path.isdir(github_workflows):
        try:
            for wf_file in os.listdir(github_workflows):
                wf_path = os.path.join(github_workflows, wf_file)
                if os.path.isfile(wf_path):
                    try:
                        with open(wf_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read().lower()
                        if 'vercel' in content:
                            if "vercel" not in found_platforms:
                                found_platforms["vercel"] = []
                            found_platforms["vercel"].append(f".github/workflows/{wf_file}")
                        if 'netlify' in content:
                            if "netlify" not in found_platforms:
                                found_platforms["netlify"] = []
                            found_platforms["netlify"].append(f".github/workflows/{wf_file}")
                        if 'docker' in content:
                            if "docker" not in found_platforms:
                                found_platforms["docker"] = []
                            found_platforms["docker"].append(f".github/workflows/{wf_file}")
                        if 'aws' in content or 'amazonaws' in content:
                            if "aws_lambda" not in found_platforms:
                                found_platforms["aws_lambda"] = []
                            found_platforms["aws_lambda"].append(f".github/workflows/{wf_file}")
                    except IOError:
                        pass
        except OSError:
            pass

    if not found_platforms:
        return {"platform": None, "confidence": "low", "hint": "No deployment platform detected"}

    # Find the best platform (most evidence)
    best_platform = max(found_platforms, key=lambda p: len(found_platforms[p]))
    platform_files = found_platforms[best_platform]

    # Determine confidence
    if len(platform_files) >= 2:
        confidence = "high"
    elif len(platform_files) == 1:
        confidence = "medium"
    else:
        confidence = "low"

    hints = {
        "vercel": "Use Vercel deployment patterns (serverless functions, edge middleware)",
        "netlify": "Use Netlify deployment patterns (Netlify Functions, redirects)",
        "docker": "Use Docker deployment patterns (multi-stage builds, health checks)",
        "fly_io": "Use Fly.io deployment patterns (fly.toml config, regions)",
        "railway": "Use Railway deployment patterns (railway.json config)",
        "render": "Use Render deployment patterns (render.yaml Blueprint)",
        "heroku": "Use Heroku deployment patterns (Procfile, buildpacks)",
        "gcp": "Use Google Cloud deployment patterns (Cloud Run, App Engine)",
        "aws_lambda": "Use AWS Lambda deployment patterns (serverless framework)",
        "aws_sam": "Use AWS SAM deployment patterns (template.yaml)",
        "aws_cdk": "Use AWS CDK deployment patterns (constructs, stacks)",
        "terraform": "Use Terraform deployment patterns (IaC, state management)",
    }

    return {
        "platform": best_platform,
        "config_files": platform_files,
        "confidence": confidence,
        "hint": hints.get(best_platform, f"Use {best_platform} deployment patterns"),
    }
