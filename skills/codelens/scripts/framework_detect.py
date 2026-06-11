"""
Framework Detector for CodeLens
Auto-detects frameworks from package.json, pyproject.toml, requirements.txt,
config files, and file patterns.

v5.8: Monorepo support — scans sub-package.json files (pnpm workspaces,
npm workspaces, Lerna, Turborepo). Detects React in monorepo sub-packages.
Also detects bun.lock/bun.lockb for lockfile-aware scanning.
"""

import json
import os
import re
from typing import Dict, List, Any, Optional, Set
from utils import DEFAULT_IGNORE_DIRS, should_ignore_dir


# Known framework signatures
FRAMEWORK_SIGNATURES = {
    "react": {
        "packages": ["react", "react-dom"],
        "config_files": [],
        "indicators": ["jsx", "tsx", "className"]
    },
    "next.js": {
        "packages": ["next"],
        "config_files": ["next.config.js", "next.config.mjs", "next.config.ts"],
        "indicators": []
    },
    "vue": {
        "packages": ["vue"],
        "config_files": ["vue.config.js", "vite.config.js"],
        "indicators": [".vue"]
    },
    "svelte": {
        "packages": ["svelte"],
        "config_files": ["svelte.config.js"],
        "indicators": [".svelte"]
    },
    "tailwind": {
        "packages": ["tailwindcss"],
        "config_files": ["tailwind.config.js", "tailwind.config.ts", "tailwind.config.mjs"],
        "indicators": []
    },
    "nuxt": {
        "packages": ["nuxt"],
        "config_files": ["nuxt.config.js", "nuxt.config.ts"],
        "indicators": []
    },
    "angular": {
        "packages": ["@angular/core"],
        "config_files": ["angular.json"],
        "indicators": [".component.ts"]
    },
    "sveltekit": {
        "packages": ["@sveltejs/kit"],
        "config_files": ["svelte.config.js"],
        "indicators": []
    },
    # Python frameworks
    "fastapi": {
        "packages": ["fastapi"],
        "pip_packages": ["fastapi"],
        "config_files": [],
        "indicators": []
    },
    "flask": {
        "packages": ["flask"],
        "pip_packages": ["flask"],
        "config_files": ["app.py", "wsgi.py"],
        "indicators": []
    },
    "django": {
        "packages": ["django"],
        "pip_packages": ["django"],
        "config_files": ["manage.py"],
        "indicators": []
    },
    "celery": {
        "packages": ["celery"],
        "pip_packages": ["celery"],
        "config_files": ["celery.py", "celeryconfig.py"],
        "indicators": []
    },
    "sqlalchemy": {
        "packages": ["sqlalchemy"],
        "pip_packages": ["sqlalchemy"],
        "config_files": [],
        "indicators": []
    },
    "starlette": {
        "packages": ["starlette"],
        "pip_packages": ["starlette"],
        "config_files": [],
        "indicators": []
    },
    "pydantic": {
        "packages": ["pydantic"],
        "pip_packages": ["pydantic"],
        "config_files": [],
        "indicators": []
    },
    # Rust / Tauri frameworks
    "tauri": {
        "packages": [],
        "cargo_packages": ["tauri"],
        "config_files": ["src-tauri/tauri.conf.json"],
        "indicators": []
    },
    "actix-web": {
        "packages": [],
        "cargo_packages": ["actix-web"],
        "config_files": [],
        "indicators": []
    },
    "axum": {
        "packages": [],
        "cargo_packages": ["axum"],
        "config_files": [],
        "indicators": []
    },
    "rocket": {
        "packages": [],
        "cargo_packages": ["rocket"],
        "config_files": [],
        "indicators": []
    },
    # RPC / API frameworks
    "trpc": {
        "packages": ["@trpc/server", "@trpc/client"],
        "config_files": [],
        "indicators": []
    },
    "orpc": {
        "packages": ["@orpc/server", "@orpc/client"],
        "config_files": [],
        "indicators": []
    },
    # State management
    "zustand": {
        "packages": ["zustand"],
        "config_files": [],
        "indicators": []
    },
    "redux": {
        "packages": ["@reduxjs/toolkit", "redux"],
        "config_files": [],
        "indicators": []
    },
    # Build tools
    "vite": {
        "packages": ["vite"],
        "config_files": ["vite.config.ts", "vite.config.js", "vite.config.mjs"],
        "indicators": []
    },
}


# ─── Monorepo Helpers ──────────────────────────────────────────

def _discover_workspace_package_jsons(workspace: str) -> List[str]:
    """
    Discover all package.json files in a monorepo workspace.

    Checks:
    1. pnpm-workspace.yaml → parse packages globs
    2. package.json workspaces field (npm/yarn/Lerna)
    3. Fallback: walk first 2 levels for apps/ and packages/ dirs

    Returns list of absolute paths to package.json files (including root).
    """
    workspace = os.path.abspath(workspace)
    pkg_jsons = []

    # Always include root
    root_pkg = os.path.join(workspace, "package.json")
    if os.path.exists(root_pkg):
        pkg_jsons.append(root_pkg)

    # 1. pnpm-workspace.yaml
    pnpm_ws = os.path.join(workspace, "pnpm-workspace.yaml")
    if os.path.exists(pnpm_ws):
        try:
            with open(pnpm_ws, 'r', encoding='utf-8') as f:
                content = f.read()
            # Extract packages list from YAML (simple regex — no yaml dep needed)
            for m in re.finditer(r"^\s*-\s*['\"]?([^'\"\n]+)['\"]?", content, re.MULTILINE):
                glob_pattern = m.group(1).strip()
                pkg_jsons.extend(_glob_package_jsons(workspace, glob_pattern))
        except IOError:
            pass

    # 2. npm/yarn workspaces in root package.json
    if os.path.exists(root_pkg):
        try:
            with open(root_pkg, 'r', encoding='utf-8') as f:
                root_data = json.load(f)
            workspaces = root_data.get("workspaces", [])
            if isinstance(workspaces, dict):
                workspaces = workspaces.get("packages", [])
            for glob_pattern in workspaces:
                pkg_jsons.extend(_glob_package_jsons(workspace, glob_pattern))
        except (json.JSONDecodeError, IOError):
            pass

    # 3. Fallback: look for apps/ and packages/ directories (common in Turborepo)
    if len(pkg_jsons) <= 1:
        for subdir in ("apps", "packages"):
            dir_path = os.path.join(workspace, subdir)
            if os.path.isdir(dir_path):
                for entry in os.listdir(dir_path):
                    entry_path = os.path.join(dir_path, entry)
                    pkg_path = os.path.join(entry_path, "package.json")
                    if os.path.isfile(pkg_path) and pkg_path not in pkg_jsons:
                        pkg_jsons.append(pkg_path)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for p in pkg_jsons:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _glob_package_jsons(workspace: str, glob_pattern: str) -> List[str]:
    """
    Resolve a workspace glob pattern like 'apps/*' or 'packages/*'
    to a list of package.json paths.
    """
    results = []
    # Strip trailing slash and /package.json if present
    pattern = glob_pattern.rstrip('/')
    if pattern.endswith('/package.json'):
        pattern = pattern[:-len('/package.json')]

    # Handle simple star glob: dir/*
    if '*' in pattern:
        base_dir = pattern.split('*')[0].rstrip('/')
        base_path = os.path.join(workspace, base_dir)
        if os.path.isdir(base_path):
            for entry in sorted(os.listdir(base_path)):
                entry_path = os.path.join(base_path, entry)
                if os.path.isdir(entry_path):
                    pkg_path = os.path.join(entry_path, "package.json")
                    if os.path.isfile(pkg_path):
                        results.append(pkg_path)
    else:
        # Direct path
        dir_path = os.path.join(workspace, pattern)
        pkg_path = os.path.join(dir_path, "package.json")
        if os.path.isfile(pkg_path):
            results.append(pkg_path)

    return results


def _collect_deps_from_package_jsons(pkg_json_paths: List[str]) -> Dict[str, Any]:
    """
    Collect all dependencies from multiple package.json files.

    Returns dict with:
    - all_deps: merged dependency dict
    - module_system: 'esm' if any package has type:module
    - css_preprocessor: detected from any package
    - is_monorepo: True if multiple package.json files found
    """
    all_deps = {}
    module_system = "cjs"
    css_preprocessor = None

    for pkg_path in pkg_json_paths:
        try:
            with open(pkg_path, 'r', encoding='utf-8') as f:
                pkg = json.load(f)
            all_deps.update(pkg.get("dependencies", {}))
            all_deps.update(pkg.get("devDependencies", {}))
            all_deps.update(pkg.get("peerDependencies", {}))

            # Module system — any ESM package counts
            if pkg.get("type") == "module":
                module_system = "esm"

            # CSS preprocessor
            deps = {}
            deps.update(pkg.get("dependencies", {}))
            deps.update(pkg.get("devDependencies", {}))
            if "sass" in deps or "node-sass" in deps:
                css_preprocessor = "scss"
            elif "less" in deps and css_preprocessor is None:
                css_preprocessor = "less"
            elif ("stylus" in deps or "styl" in deps) and css_preprocessor is None:
                css_preprocessor = "stylus"

        except (json.JSONDecodeError, IOError):
            pass

    return {
        "all_deps": all_deps,
        "module_system": module_system,
        "css_preprocessor": css_preprocessor,
        "is_monorepo": len(pkg_json_paths) > 1,
    }


def detect_frameworks(workspace: str) -> Dict[str, Any]:
    """
    Detect frameworks used in a workspace.
    Returns dict with detected frameworks and their config.

    v5.8: Now supports monorepo detection — scans all package.json files
    in workspace packages (pnpm, npm, yarn workspaces, Turborepo).
    """
    workspace = os.path.abspath(workspace)
    detected = {
        "frameworks": [],
        "has_react": False,
        "has_vue": False,
        "has_svelte": False,
        "has_tailwind": False,
        "has_nextjs": False,
        "has_angular": False,
        "has_fastapi": False,
        "has_flask": False,
        "has_django": False,
        "has_tauri": False,
        "has_rust_backend": False,
        "has_cpp": False,
        "has_go": False,
        "css_preprocessor": None,
        "module_system": None,
        "is_monorepo": False,
        "lockfile": None,
    }

    # Detect lockfile type
    for lockfile, name in [
        ("bun.lock", "bun"),
        ("bun.lockb", "bun"),
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("package-lock.json", "npm"),
    ]:
        if os.path.exists(os.path.join(workspace, lockfile)):
            detected["lockfile"] = name
            break

    # 1. Discover all package.json files (monorepo-aware)
    pkg_json_paths = _discover_workspace_package_jsons(workspace)
    pkg_info = _collect_deps_from_package_jsons(pkg_json_paths)
    all_deps = pkg_info["all_deps"]
    detected["module_system"] = pkg_info["module_system"]
    detected["css_preprocessor"] = pkg_info["css_preprocessor"]
    detected["is_monorepo"] = pkg_info["is_monorepo"]

    # Check all collected deps against framework signatures
    for fw_name, sig in FRAMEWORK_SIGNATURES.items():
        if fw_name in detected["frameworks"]:
            continue
        for pkg_name in sig["packages"]:
            if pkg_name in all_deps:
                detected["frameworks"].append(fw_name)
                if fw_name == "react":
                    detected["has_react"] = True
                elif fw_name == "next.js":
                    detected["has_nextjs"] = True
                elif fw_name == "vue":
                    detected["has_vue"] = True
                elif fw_name == "svelte":
                    detected["has_svelte"] = True
                elif fw_name == "tailwind":
                    detected["has_tailwind"] = True
                elif fw_name == "angular":
                    detected["has_angular"] = True
                break

    # 2. Check config files
    for fw_name, sig in FRAMEWORK_SIGNATURES.items():
        if fw_name in detected["frameworks"]:
            continue
        for cfg_file in sig.get("config_files", []):
            if os.path.exists(os.path.join(workspace, cfg_file)):
                detected["frameworks"].append(fw_name)
                if fw_name == "tailwind":
                    detected["has_tailwind"] = True
                elif fw_name == "next.js":
                    detected["has_nextjs"] = True
                elif fw_name == "fastapi":
                    detected["has_fastapi"] = True
                elif fw_name == "flask":
                    detected["has_flask"] = True
                elif fw_name == "django":
                    detected["has_django"] = True
                break

    # 3. Check Python dependency files (requirements.txt, pyproject.toml, Pipfile)
    pip_deps = set()

    # 3a. requirements.txt
    req_path = os.path.join(workspace, "requirements.txt")
    if os.path.exists(req_path):
        try:
            with open(req_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and not line.startswith('-'):
                        pkg_name = re.split(r'[><=!~\[]', line)[0].strip().lower()
                        if pkg_name:
                            pip_deps.add(pkg_name)
        except IOError:
            logger.debug("Failed to parse requirements.txt", exc_info=True)

    # 3b. pyproject.toml
    pyproject_path = os.path.join(workspace, "pyproject.toml")
    if os.path.exists(pyproject_path):
        try:
            with open(pyproject_path, 'r', encoding='utf-8') as f:
                content = f.read()
            # Find dependency lines in TOML: fastapi = "..." or "fastapi>=0.89"
            for m in re.finditer(r'^\s*([a-zA-Z0-9_-]+)\s*[=<>~!]+\s*["\']', content, re.MULTILINE):
                pip_deps.add(m.group(1).lower())
            # Also find list-style deps: "fastapi>=0.89"
            for m in re.finditer(r'["\']([a-zA-Z0-9_-]+)[><=!~]', content):
                pip_deps.add(m.group(1).lower())
        except IOError:
            logger.debug("Failed to parse pyproject.toml", exc_info=True)

    # 3c. Check pip deps against framework signatures
    for fw_name, sig in FRAMEWORK_SIGNATURES.items():
        if fw_name in detected["frameworks"]:
            continue
        pip_pkgs = sig.get("pip_packages", sig.get("packages", []))
        for pkg_name in pip_pkgs:
            if pkg_name.lower() in pip_deps:
                detected["frameworks"].append(fw_name)
                if fw_name == "fastapi":
                    detected["has_fastapi"] = True
                elif fw_name == "flask":
                    detected["has_flask"] = True
                elif fw_name == "django":
                    detected["has_django"] = True
                break

    # 4. Check Cargo.toml for Rust dependencies
    cargo_deps = set()
    cargo_paths = []

    # Check root Cargo.toml
    root_cargo = os.path.join(workspace, "Cargo.toml")
    if os.path.exists(root_cargo):
        cargo_paths.append(root_cargo)

    # Check src-tauri/Cargo.toml (Tauri project structure)
    tauri_cargo = os.path.join(workspace, "src-tauri", "Cargo.toml")
    if os.path.exists(tauri_cargo):
        cargo_paths.append(tauri_cargo)

    # Also scan for any Cargo.toml in subdirectories (Rust workspaces)
    for root, dirs, files in os.walk(workspace):
        rel_root = os.path.relpath(root, workspace)
        if should_ignore_dir(rel_root):
            dirs.clear()
            continue
        if 'Cargo.toml' in files:
            cpath = os.path.join(root, 'Cargo.toml')
            if cpath not in cargo_paths:
                cargo_paths.append(cpath)

    for cargo_path in cargo_paths:
        try:
            with open(cargo_path, 'r', encoding='utf-8') as f:
                content = f.read()
            # Parse [dependencies] section — extract crate names
            in_deps = False
            for line in content.splitlines():
                stripped = line.strip()
                if stripped == '[dependencies]' or stripped == '[dev-dependencies]':
                    in_deps = True
                    continue
                if stripped.startswith('[') and in_deps:
                    in_deps = False
                    continue
                if in_deps and '=' in stripped:
                    crate_name = stripped.split('=')[0].strip().lower()
                    if crate_name:
                        cargo_deps.add(crate_name)
                elif in_deps and stripped and not stripped.startswith('#'):
                    # Handle version shorthand: crate_name = "version"
                    parts = stripped.split('=')
                    if len(parts) >= 2:
                        crate_name = parts[0].strip().lower()
                        if crate_name:
                            cargo_deps.add(crate_name)
        except IOError:
            pass

    # Check cargo deps against framework signatures
    for fw_name, sig in FRAMEWORK_SIGNATURES.items():
        if fw_name in detected["frameworks"]:
            continue
        cargo_pkgs = sig.get("cargo_packages", [])
        for pkg_name in cargo_pkgs:
            if pkg_name.lower() in cargo_deps:
                detected["frameworks"].append(fw_name)
                if fw_name == "tauri":
                    detected["has_tauri"] = True
                    detected["has_rust_backend"] = True
                break

    # Also detect Tauri from config file presence (deep scan for monorepo)
    if not detected["has_tauri"]:
        # Check standard location first
        tauri_conf_paths = [
            os.path.join(workspace, "src-tauri", "tauri.conf.json"),
            os.path.join(workspace, "src-tauri", "tauri.conf.json5"),
        ]
        found = False
        for tpath in tauri_conf_paths:
            if os.path.exists(tpath):
                if "tauri" not in detected["frameworks"]:
                    detected["frameworks"].append("tauri")
                detected["has_tauri"] = True
                detected["has_rust_backend"] = True
                found = True
                break

        # Deep scan: look for tauri.conf.json anywhere in workspace
        if not found:
            for root, dirs, files in os.walk(workspace):
                rel_root = os.path.relpath(root, workspace)
                if should_ignore_dir(rel_root):
                    dirs.clear()
                    continue
                for f in files:
                    if f == "tauri.conf.json" or f == "tauri.conf.json5":
                        if "tauri" not in detected["frameworks"]:
                            detected["frameworks"].append("tauri")
                        detected["has_tauri"] = True
                        detected["has_rust_backend"] = True
                        found = True
                        break
                if found:
                    break

    # Detect any Rust project (even without Tauri)
    if not detected["has_rust_backend"] and cargo_deps:
        detected["has_rust_backend"] = True

    # 4b. Check for C++ / C / Go projects
    # CMakeLists.txt → C++ project
    cmake_path = os.path.join(workspace, "CMakeLists.txt")
    if os.path.exists(cmake_path):
        detected["has_cpp"] = True
        if "cmake" not in detected["frameworks"]:
            detected["frameworks"].append("cmake")

    # Makefile → C/C++ project
    makefile_path = os.path.join(workspace, "Makefile")
    if os.path.exists(makefile_path):
        detected["has_cpp"] = True
        if "make" not in detected["frameworks"]:
            detected["frameworks"].append("make")

    # go.mod / go.work → Go project
    go_mod_path = os.path.join(workspace, "go.mod")
    go_work_path = os.path.join(workspace, "go.work")
    if os.path.exists(go_mod_path) or os.path.exists(go_work_path):
        detected["has_go"] = True
        if "go" not in detected["frameworks"]:
            detected["frameworks"].append("go")
        # Scan go.mod for Go web frameworks
        if os.path.exists(go_mod_path):
            try:
                with open(go_mod_path, 'r', encoding='utf-8') as f:
                    go_mod_content = f.read()
                go_frameworks = {
                    "gin": "gin-gonic/gin",
                    "echo": "labstack/echo",
                    "fiber": "gofiber/fiber",
                    "chi": "go-chi/chi",
                    "mux": "gorilla/mux",
                }
                for fw_name, mod_path in go_frameworks.items():
                    if mod_path.lower() in go_mod_content.lower():
                        if fw_name not in detected["frameworks"]:
                            detected["frameworks"].append(fw_name)
            except IOError:
                pass

    # If no CMake/Makefile found yet, check for .cc/.cpp/.h files
    if not detected["has_cpp"]:
        for root, dirs, files in os.walk(workspace):
            rel_root = os.path.relpath(root, workspace)
            if should_ignore_dir(rel_root):
                dirs.clear()
                continue
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in ('.cc', '.cpp', '.cxx', '.c', '.h', '.hpp', '.hxx'):
                    detected["has_cpp"] = True
                    if "cpp" not in detected["frameworks"]:
                        detected["frameworks"].append("cpp")
                    break
            if detected["has_cpp"]:
                break

    # If no go.mod found yet, check for .go files
    if not detected["has_go"]:
        for root, dirs, files in os.walk(workspace):
            rel_root = os.path.relpath(root, workspace)
            if should_ignore_dir(rel_root):
                dirs.clear()
                continue
            for f in files:
                if f.endswith('.go'):
                    detected["has_go"] = True
                    if "go" not in detected["frameworks"]:
                        detected["frameworks"].append("go")
                    break
            if detected["has_go"]:
                break

    # 5. Check file patterns (for Vue, Svelte)
    for root, dirs, files in os.walk(workspace):
        rel_root = os.path.relpath(root, workspace)
        if should_ignore_dir(rel_root):
            dirs.clear()
            continue

        for f in files:
            if f.endswith('.vue') and not detected["has_vue"]:
                if "vue" not in detected["frameworks"]:
                    detected["frameworks"].append("vue")
                detected["has_vue"] = True
            elif f.endswith('.svelte') and not detected["has_svelte"]:
                if "svelte" not in detected["frameworks"]:
                    detected["frameworks"].append("svelte")
                detected["has_svelte"] = True

    # 6. Detect Tailwind from CSS content
    if not detected["has_tailwind"]:
        tailwind_indicators = ['@tailwind', '@apply']
        for root, dirs, files in os.walk(workspace):
            rel_root = os.path.relpath(root, workspace)
            if should_ignore_dir(rel_root):
                dirs.clear()
                continue
            for f in files:
                if f.endswith(('.css', '.scss', '.pcss')):
                    try:
                        fpath = os.path.join(root, f)
                        with open(fpath, 'r', encoding='utf-8', errors='ignore') as fh:
                            content = fh.read(4096)  # Read first 4KB
                            for indicator in tailwind_indicators:
                                if indicator in content:
                                    if "tailwind" not in detected["frameworks"]:
                                        detected["frameworks"].append("tailwind")
                                    detected["has_tailwind"] = True
                                    break
                            if detected["has_tailwind"]:
                                break
                    except IOError:
                        pass
            if detected["has_tailwind"]:
                break

    return detected


def get_recommended_config(workspace: str) -> Dict[str, Any]:
    """
    Based on detected frameworks, recommend codelens config.

    v5.8: Monorepo-aware — adjusts paths for pnpm/npm/yarn workspace
    structures. Properly handles Tauri+React monorepo setups.
    """
    fw = detect_frameworks(workspace)

    # Default config
    config = {
        "frontend_paths": ["src/client/", "public/", "frontend/", "static/", "templates/"],
        "backend_paths": ["src/server/", "src/api/", "src/"],
        "watch": True,
        "ignore": ["node_modules/", "dist/", ".git/", "build/", "target/", "__pycache__/"],
        "frameworks": fw["frameworks"],
        "css_preprocessor": fw.get("css_preprocessor"),
        "jsx_mode": False,
        "vue_mode": False,
        "svelte_mode": False,
        "tailwind_mode": False
    }

    is_monorepo = fw.get("is_monorepo", False)

    # Adjust paths based on framework
    # Tauri: src/ is frontend, src-tauri/src/ is Rust backend
    if fw.get("has_tauri"):
        # For Tauri projects, src/ is the web frontend, not backend
        # Remove src/ from backend_paths to prevent misclassification
        config["backend_paths"] = [p for p in config["backend_paths"] if p != "src/"]

        if is_monorepo:
            # Monorepo Tauri: apps/<name>/src/ is frontend, apps/<name>/src-tauri/src/ is backend
            # Auto-discover the app directory structure
            apps_dir = os.path.join(workspace, "apps")
            if os.path.isdir(apps_dir):
                for entry in sorted(os.listdir(apps_dir)):
                    entry_path = os.path.join(apps_dir, entry)
                    if os.path.isdir(entry_path):
                        # Check if this is the Tauri app
                        if os.path.exists(os.path.join(entry_path, "src-tauri")):
                            config["frontend_paths"].extend([
                                f"apps/{entry}/src/",
                                f"apps/{entry}/src/components/",
                                f"apps/{entry}/src/pages/",
                                f"apps/{entry}/src/views/",
                            ])
                            config["backend_paths"].extend([
                                f"apps/{entry}/src-tauri/src/",
                            ])
                            if f"apps/{entry}/src-tauri/target/" not in config.get("ignore", []):
                                config.setdefault("ignore", []).append(f"apps/{entry}/src-tauri/target/")
                        else:
                            # Non-Tauri app in monorepo (e.g., web-only package)
                            config["frontend_paths"].extend([
                                f"apps/{entry}/src/",
                            ])
        else:
            # Standard Tauri project
            config["frontend_paths"].extend(["src/", "src/components/", "src/pages/", "src/views/"])
            config["backend_paths"].extend(["src-tauri/src/"])
            if "src-tauri/target/" not in config.get("ignore", []):
                config.setdefault("ignore", []).append("src-tauri/target/")

        # Enable JSX mode if React is also present
        if fw.get("has_react"):
            config["jsx_mode"] = True
        # Always enable JSX for .tsx files in Tauri
        config["jsx_mode"] = True

    if fw["has_nextjs"]:
        config["frontend_paths"].extend(["app/", "src/app/", "pages/", "src/pages/"])
        config["backend_paths"].extend(["app/api/", "src/app/api/"])
        config["jsx_mode"] = True
        # Next.js app router — everything under app/ could be frontend
        config["frontend_paths"] = list(set(config["frontend_paths"]))

    if fw["has_react"] and not fw.get("has_tauri"):
        config["jsx_mode"] = True
        config["frontend_paths"].extend(["src/components/", "src/views/"])
        # Monorepo React app
        if is_monorepo:
            apps_dir = os.path.join(workspace, "apps")
            if os.path.isdir(apps_dir):
                for entry in sorted(os.listdir(apps_dir)):
                    entry_path = os.path.join(apps_dir, entry)
                    pkg_path = os.path.join(entry_path, "package.json")
                    if os.path.isfile(pkg_path):
                        try:
                            with open(pkg_path, 'r', encoding='utf-8') as f:
                                pkg = json.load(f)
                            deps = {}
                            deps.update(pkg.get("dependencies", {}))
                            deps.update(pkg.get("devDependencies", {}))
                            if "react" in deps and "tauri" not in deps:
                                config["frontend_paths"].extend([
                                    f"apps/{entry}/src/",
                                    f"apps/{entry}/src/components/",
                                ])
                        except (json.JSONDecodeError, IOError):
                            pass

    if fw["has_vue"]:
        config["vue_mode"] = True
        config["frontend_paths"].extend(["src/components/", "src/views/"])

    if fw["has_svelte"]:
        config["svelte_mode"] = True
        config["frontend_paths"].extend(["src/lib/", "src/routes/"])

    if fw["has_tailwind"]:
        config["tailwind_mode"] = True

    # C++ project paths
    if fw.get("has_cpp"):
        config["backend_paths"].extend(["src/", "src/core/", "src/lib/"])
        # Don't add src/ to frontend_paths for C++ projects
        config["frontend_paths"] = [p for p in config["frontend_paths"] if p != "src/"]

    # Go project paths
    if fw.get("has_go"):
        config["backend_paths"].extend(["cmd/", "internal/", "pkg/"])
        # Remove generic src/ from backend if Go project (Go uses cmd/internal/pkg)
        config["backend_paths"] = list(dict.fromkeys(config["backend_paths"]))

    # Deduplicate paths
    config["frontend_paths"] = list(dict.fromkeys(config["frontend_paths"]))
    config["backend_paths"] = list(dict.fromkeys(config["backend_paths"]))

    # Store monorepo info
    config["is_monorepo"] = is_monorepo
    config["lockfile"] = fw.get("lockfile")

    return config
