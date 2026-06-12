"""
Framework Detector for CodeLens
Auto-detects frameworks from package.json, pyproject.toml, requirements.txt,
config files, and file patterns.
"""

import json
import os
import re
from typing import Dict, List, Any, Optional
import logging
_logger = logging.getLogger("codelens.framework_detect")
from utils import DEFAULT_IGNORE_DIRS


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
        "indicators": ["use client", "use server", "getServerSideProps", "getStaticProps"]
    },
    "remix": {
        "packages": ["@remix-run/react"],
        "config_files": ["remix.config.js"],
        "indicators": []
    },
    "astro": {
        "packages": ["astro"],
        "config_files": ["astro.config.mjs", "astro.config.ts"],
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
        "indicators": ["django/__init__.py", "django/apps/", "django/conf/", "django/contrib/", "django/core/"]
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
    # Desktop app frameworks
    "tauri": {
        "packages": ["@tauri-apps/api", "@tauri-apps/cli"],
        "config_files": ["tauri.conf.json", "Tauri.toml"],
        "indicators": ["src-tauri"]
    },
    "electron": {
        "packages": ["electron"],
        "config_files": ["electron-builder.yml", "electron-builder.json"],
        "indicators": ["main.js", "BrowserWindow"]
    },
    # Go frameworks (detected by config files / source presence)
    "golang": {
        "packages": [],
        "config_files": ["go.mod"],
        "indicators": [".go"]
    },
    "gin": {
        "packages": [],
        "config_files": ["go.mod"],
        "indicators": ["gin-gonic/gin"]
    },
    "echo": {
        "packages": [],
        "config_files": ["go.mod"],
        "indicators": ["labstack/echo"]
    },
    # Java/Kotlin frameworks
    "spring": {
        "packages": [],
        "config_files": ["pom.xml", "build.gradle", "build.gradle.kts"],
        "indicators": ["spring-boot"]
    },
    # C/C++ frameworks
    "cmake": {
        "packages": [],
        "config_files": ["CMakeLists.txt"],
        "indicators": []
    },
    # Rust frameworks
    "rust": {
        "packages": [],
        "config_files": ["Cargo.toml"],
        "indicators": []
    },
    "tokio": {
        "packages": [],
        "config_files": [],
        "cargo_crates": ["tokio"],
        "indicators": []
    },
    "actix-web": {
        "packages": [],
        "config_files": [],
        "cargo_crates": ["actix-web", "actix_web"],
        "indicators": []
    },
    "axum": {
        "packages": [],
        "config_files": [],
        "cargo_crates": ["axum"],
        "indicators": []
    },
    "deno_core": {
        "packages": [],
        "config_files": [],
        "cargo_crates": ["deno_core", "deno_core_impl"],
        "indicators": []
    },
    "warp": {
        "packages": [],
        "config_files": [],
        "cargo_crates": ["warp"],
        "indicators": []
    },
    "rocket": {
        "packages": [],
        "config_files": [],
        "cargo_crates": ["rocket"],
        "indicators": []
    },
}


def _find_package_jsons(workspace: str, max_depth: int = 3) -> List[str]:
    """
    Find all package.json files in the workspace, including monorepo sub-packages.
    Limits depth to avoid scanning deeply nested node_modules.
    """
    pkg_files = []
    root_pkg = os.path.join(workspace, "package.json")
    if os.path.exists(root_pkg):
        pkg_files.append(root_pkg)

    # Scan monorepo directories (apps/*, packages/*, etc.) up to max_depth
    monorepo_dirs = ('apps', 'packages', 'projects', 'services', 'libs', 'modules')
    for subdir in monorepo_dirs:
        subdir_path = os.path.join(workspace, subdir)
        if not os.path.isdir(subdir_path):
            continue
        try:
            for entry in os.listdir(subdir_path):
                entry_path = os.path.join(subdir_path, entry)
                pkg_path = os.path.join(entry_path, "package.json")
                if os.path.isfile(pkg_path):
                    pkg_files.append(pkg_path)
        except OSError:
            pass

    return pkg_files


def detect_frameworks(workspace: str) -> Dict[str, Any]:
    """
    Detect frameworks used in a workspace.
    Returns dict with detected frameworks and their config.
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
        "has_electron": False,
        "has_golang": False,
        "has_rust": False,
        "unsupported_langs": [],
        "css_preprocessor": None,
        "module_system": None
    }

    # 1. Check package.json (root + monorepo sub-packages)
    all_deps = {}
    pkg_files = _find_package_jsons(workspace)

    for pkg_path in pkg_files:
        try:
            with open(pkg_path, 'r', encoding='utf-8') as f:
                pkg = json.load(f)
            all_deps.update(pkg.get("dependencies", {}))
            all_deps.update(pkg.get("devDependencies", {}))
            all_deps.update(pkg.get("peerDependencies", {}))

            # Detect module system from root package.json only
            if pkg_path == os.path.join(workspace, "package.json"):
                if "type" in pkg and pkg["type"] == "module":
                    detected["module_system"] = "esm"
                else:
                    detected["module_system"] = "cjs"
        except (json.JSONDecodeError, IOError):
            pass

    if all_deps:
        for fw_name, sig in FRAMEWORK_SIGNATURES.items():
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
                    elif fw_name == "tauri":
                        detected["has_tauri"] = True
                    elif fw_name == "electron":
                        detected["has_electron"] = True
                    elif fw_name == "golang":
                        detected["has_golang"] = True
                    break

        # Detect CSS preprocessor
        if "sass" in all_deps or "node-sass" in all_deps:
            detected["css_preprocessor"] = "scss"
        elif "less" in all_deps:
            detected["css_preprocessor"] = "less"
        elif "stylus" in all_deps or "styl" in all_deps:
            detected["css_preprocessor"] = "stylus"

    # 2. Check config files (root + subdirectories for monorepos)
    for fw_name, sig in FRAMEWORK_SIGNATURES.items():
        if fw_name in detected["frameworks"]:
            continue
        for cfg_file in sig.get("config_files", []):
            # Check root first
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
                elif fw_name == "golang":
                    detected["has_golang"] = True
                break
            # Check one level deep for monorepo (apps/*, packages/*)
            found_in_subdir = False
            for subdir in ('apps', 'packages', 'projects', 'services'):
                subdir_path = os.path.join(workspace, subdir)
                if not os.path.isdir(subdir_path):
                    continue
                try:
                    for entry in os.listdir(subdir_path):
                        entry_path = os.path.join(subdir_path, entry)
                        if os.path.isdir(entry_path) and os.path.exists(os.path.join(entry_path, cfg_file)):
                            detected["frameworks"].append(fw_name)
                            if fw_name == "tailwind":
                                detected["has_tailwind"] = True
                            elif fw_name == "next.js":
                                detected["has_nextjs"] = True
                            elif fw_name == "react":
                                detected["has_react"] = True
                            found_in_subdir = True
                            break
                except OSError:
                    pass
                if found_in_subdir:
                    break
            if found_in_subdir:
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

    # 4. Check Rust/Cargo.toml for framework detection
    cargo_deps = set()
    cargo_path = os.path.join(workspace, "Cargo.toml")
    if os.path.exists(cargo_path):
        if "rust" not in detected["frameworks"]:
            detected["frameworks"].append("rust")
        detected["has_rust"] = True

        # Parse root Cargo.toml for dependencies
        try:
            with open(cargo_path, 'r', encoding='utf-8') as f:
                cargo_content = f.read()
            # Extract dependency names from [dependencies] and [dev-dependencies] sections
            in_deps = False
            for line in cargo_content.split('\n'):
                stripped = line.strip()
                if stripped.startswith('['):
                    section = stripped.strip('[]').strip()
                    in_deps = section in ('dependencies', 'dev-dependencies')
                    continue
                if in_deps and '=' in stripped:
                    dep_name = stripped.split('=')[0].strip().lower()
                    if dep_name and not dep_name.startswith('#'):
                        cargo_deps.add(dep_name)
                elif in_deps and stripped and not stripped.startswith('#') and not stripped.startswith('['):
                    # Handle inline table: dep = { version = "..." }
                    dep_name = stripped.split('=')[0].strip().lower()
                    if dep_name:
                        cargo_deps.add(dep_name)
        except IOError:
            pass

        # Also parse workspace members' Cargo.toml
        for crate_dir_name in ('crates', 'ext', 'libs', 'packages'):
            crate_dir = os.path.join(workspace, crate_dir_name)
            if os.path.isdir(crate_dir):
                try:
                    for entry in os.listdir(crate_dir):
                        sub_cargo = os.path.join(crate_dir, entry, "Cargo.toml")
                        if os.path.isfile(sub_cargo):
                            try:
                                with open(sub_cargo, 'r', encoding='utf-8') as f:
                                    sub_content = f.read()
                                in_deps = False
                                for line in sub_content.split('\n'):
                                    stripped = line.strip()
                                    if stripped.startswith('['):
                                        section = stripped.strip('[]').strip()
                                        in_deps = section in ('dependencies', 'dev-dependencies')
                                        continue
                                    if in_deps and '=' in stripped:
                                        dep_name = stripped.split('=')[0].strip().lower()
                                        if dep_name and not dep_name.startswith('#'):
                                            cargo_deps.add(dep_name)
                            except IOError:
                                pass
                except OSError:
                    pass

        # Match cargo deps against framework signatures
        for fw_name, sig in FRAMEWORK_SIGNATURES.items():
            if fw_name in detected["frameworks"]:
                continue
            cargo_crates = sig.get("cargo_crates", [])
            for crate_name in cargo_crates:
                if crate_name.lower() in cargo_deps:
                    detected["frameworks"].append(fw_name)
                    break

    # 5. Check Tauri-specific config files (tauri.conf.json can be nested in src-tauri/)
    if not detected["has_tauri"]:
        tauri_markers = ['tauri.conf.json', 'Tauri.toml']
        for root, dirs, files in os.walk(workspace):
            skip = False
            for ignore in DEFAULT_IGNORE_DIRS:
                if ignore in root:
                    skip = True
                    break
            if skip or '.codelens' in root:
                continue
            for f in files:
                if f in tauri_markers:
                    if "tauri" not in detected["frameworks"]:
                        detected["frameworks"].append("tauri")
                    detected["has_tauri"] = True
                    break
            if detected["has_tauri"]:
                break

        # Also check for src-tauri directory
        if not detected["has_tauri"]:
            for root, dirs, files in os.walk(workspace):
                skip = False
                for ignore in DEFAULT_IGNORE_DIRS:
                    if ignore in root:
                        skip = True
                        break
                if skip or '.codelens' in root:
                    continue
                if 'src-tauri' in dirs:
                    if "tauri" not in detected["frameworks"]:
                        detected["frameworks"].append("tauri")
                    detected["has_tauri"] = True
                    break

    # 5. Check file patterns (for Vue, Svelte)
    for root, dirs, files in os.walk(workspace):
        # Skip ignored dirs
        skip = False
        for ignore in DEFAULT_IGNORE_DIRS:
            if ignore in root:
                skip = True
                break
        if skip:
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

    # 5b. Check directory/file indicators (for Django, Flask, FastAPI source trees)
    # Some frameworks have distinctive directory structures even when they're the
    # framework source itself (not a project using the framework).
    for fw_name, sig in FRAMEWORK_SIGNATURES.items():
        if fw_name in detected["frameworks"]:
            continue
        for indicator in sig.get("indicators", []):
            indicator_path = os.path.join(workspace, indicator)
            if os.path.exists(indicator_path):
                detected["frameworks"].append(fw_name)
                if fw_name == "django":
                    detected["has_django"] = True
                elif fw_name == "fastapi":
                    detected["has_fastapi"] = True
                elif fw_name == "flask":
                    detected["has_flask"] = True
                break

    # 6. Detect Tailwind from CSS content
    if not detected["has_tailwind"]:
        tailwind_indicators = ['@tailwind', '@apply']
        for root, dirs, files in os.walk(workspace):
            skip = False
            for ignore in DEFAULT_IGNORE_DIRS:
                if ignore in root:
                    skip = True
                    break
            if skip:
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

    # 7. Detect unsupported languages (Go, Java, C/C++, etc.)
    # These languages are detected but not parsed by tree-sitter.
    # Note: fallback parsers exist for C/C++, Go, Java, Lua, C# — they ARE parsed, just not via tree-sitter.
    UNSUPPORTED_MARKERS = {
        "go": ["go.mod", "go.sum"],
        "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
        "kotlin": ["build.gradle.kts"],
        "c": ["CMakeLists.txt", "Makefile"],
        "cpp": ["CMakeLists.txt", "Makefile"],
        "csharp": [".csproj", ".sln"],
        "swift": ["Package.swift", "Package.resolved"],
        "ruby": ["Gemfile", "Rakefile"],
    }
    for lang, markers in UNSUPPORTED_MARKERS.items():
        for marker in markers:
            if os.path.exists(os.path.join(workspace, marker)):
                if lang not in detected["unsupported_langs"]:
                    detected["unsupported_langs"].append(lang)
                if lang == "go" and "golang" not in detected["frameworks"]:
                    detected["frameworks"].append("golang")
                    detected["has_golang"] = True
                break

    # 8. Detect additional languages and build systems from file extensions
    _lang_file_counts = {
        "c": 0, "cpp": 0, "lua": 0, "java": 0, "go": 0,
        "csharp": 0, "php": 0, "zig": 0, "python": 0,
        "rust": 0, "javascript": 0, "typescript": 0,
    }
    _lang_extensions = {
        ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp",
        ".cc": "cpp", ".cxx": "cpp", ".hh": "cpp", ".hxx": "cpp",
        ".lua": "lua",
        ".java": "java",
        ".go": "go",
        ".cs": "csharp",
        ".php": "php",
        ".zig": "zig",
        ".py": "python",
        ".rs": "rust",
        ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
        ".ts": "typescript", ".tsx": "typescript",
    }
    for root, dirs, files in os.walk(workspace):
        skip = False
        for ignore in DEFAULT_IGNORE_DIRS:
            if ignore in root:
                skip = True
                break
        if skip or '.codelens' in root:
            continue
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            lang = _lang_extensions.get(ext)
            if lang:
                _lang_file_counts[lang] = _lang_file_counts.get(lang, 0) + 1

    # Add language frameworks if files exist
    if _lang_file_counts.get("c", 0) > 0 and "c" not in detected["frameworks"]:
        detected["frameworks"].append("c")
    if _lang_file_counts.get("cpp", 0) > 0 and "cpp" not in detected["frameworks"]:
        detected["frameworks"].append("cpp")
    if _lang_file_counts.get("lua", 0) > 0 and "lua" not in detected["frameworks"]:
        detected["frameworks"].append("lua")
    if _lang_file_counts.get("java", 0) > 0 and "java" not in detected["frameworks"]:
        detected["frameworks"].append("java")
    if _lang_file_counts.get("go", 0) > 0 and "golang" not in detected["frameworks"]:
        detected["frameworks"].append("golang")
        detected["has_golang"] = True
    if _lang_file_counts.get("csharp", 0) > 0 and "csharp" not in detected["frameworks"]:
        detected["frameworks"].append("csharp")
    if _lang_file_counts.get("php", 0) > 0 and "php" not in detected["frameworks"]:
        detected["frameworks"].append("php")
    if _lang_file_counts.get("zig", 0) > 0 and "zig" not in detected["frameworks"]:
        detected["frameworks"].append("zig")

    # 9. Detect CMake build system
    if os.path.exists(os.path.join(workspace, "CMakeLists.txt")) and "cmake" not in detected["frameworks"]:
        detected["frameworks"].append("cmake")

    # 10. Detect Zig build system
    if os.path.exists(os.path.join(workspace, "build.zig")) and "zig-build" not in detected["frameworks"]:
        detected["frameworks"].append("zig-build")

    # Store language file counts for downstream use
    detected["language_file_counts"] = {k: v for k, v in _lang_file_counts.items() if v > 0}

    # Determine polyglot project type
    active_langs = [k for k, v in _lang_file_counts.items() if v > 0]
    if len(active_langs) > 1:
        detected["is_polyglot"] = True
        detected["project_type"] = "-".join(sorted(active_langs)) + "-polyglot"
    else:
        detected["is_polyglot"] = False

    return detected


def get_recommended_config(workspace: str) -> Dict[str, Any]:
    """
    Based on detected frameworks, recommend codelens config.
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

    # Adjust paths based on framework
    if fw["has_nextjs"]:
        config["frontend_paths"].extend(["app/", "src/app/", "pages/", "src/pages/"])
        config["backend_paths"].extend(["app/api/", "src/app/api/"])
        config["jsx_mode"] = True
        # Next.js app router — everything under app/ could be frontend
        config["frontend_paths"] = list(set(config["frontend_paths"]))

    if fw["has_react"]:
        config["jsx_mode"] = True
        config["frontend_paths"].extend(["src/components/", "src/views/"])

    if fw["has_vue"]:
        config["vue_mode"] = True
        config["frontend_paths"].extend(["src/components/", "src/views/"])

    if fw["has_svelte"]:
        config["svelte_mode"] = True
        config["frontend_paths"].extend(["src/lib/", "src/routes/"])

    if fw["has_tailwind"]:
        config["tailwind_mode"] = True

    # Rust: add Rust-specific paths
    if fw.get("has_rust"):
        config["backend_paths"].extend(["src/", "crates/", "ext/"])
        # Check for Cargo workspace subdirectories
        for crate_dir_name in ('crates', 'ext', 'libs'):
            crate_dir = os.path.join(workspace, crate_dir_name)
            if os.path.isdir(crate_dir):
                try:
                    for entry in os.listdir(crate_dir):
                        entry_path = os.path.join(crate_dir, entry)
                        if os.path.isdir(entry_path):
                            rel = os.path.relpath(entry_path, workspace)
                            config["backend_paths"].append(rel + "/src/")
                except OSError:
                    pass

    # Tauri: add Rust backend paths and src-tauri
    if fw.get("has_tauri"):
        config["backend_paths"].extend(["src-tauri/src/", "src-tauri/"])
        config["frontend_paths"].append("src/")
        # Find and add app-specific src-tauri paths
        for app_dir in ('apps', 'packages'):
            app_path = os.path.join(workspace, app_dir)
            if os.path.isdir(app_path):
                try:
                    for entry in os.listdir(app_path):
                        tauri_src = os.path.join(app_path, entry, "src-tauri", "src")
                        if os.path.isdir(tauri_src):
                            rel = os.path.relpath(tauri_src, workspace)
                            config["backend_paths"].append(rel + "/")
                except OSError:
                    pass

    # Deduplicate paths
    config["frontend_paths"] = list(dict.fromkeys(config["frontend_paths"]))
    config["backend_paths"] = list(dict.fromkeys(config["backend_paths"]))

    return config
