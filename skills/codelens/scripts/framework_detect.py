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
    # Go frameworks (detected by go.mod content, NOT just go.mod existence)
    "golang": {
        "packages": [],
        "config_files": ["go.mod"],
        "indicators": [".go"]
    },
    "gin": {
        "packages": [],
        "config_files": [],
        "indicators": ["gin-gonic/gin"]
    },
    "echo": {
        "packages": [],
        "config_files": [],
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
    # PHP frameworks
    "laravel": {
        "packages": [],
        "composer_packages": ["laravel/framework", "illuminate/support"],
        "config_files": ["artisan"],
        "indicators": ["app/Http/Kernel.php", "app/Console/Kernel.php"]
    },
    "symfony": {
        "packages": [],
        "composer_packages": ["symfony/framework-bundle", "symfony/flex"],
        "config_files": ["symfony.lock"],
        "indicators": ["config/bundles.php", "src/Kernel.php"]
    },
    "lumen": {
        "packages": [],
        "composer_packages": ["laravel/lumen-framework"],
        "config_files": [],
        "indicators": ["bootstrap/app.php"]
    },
    "slim": {
        "packages": [],
        "composer_packages": ["slim/slim", "slim/framework"],
        "config_files": [],
        "indicators": []
    },
    "codeigniter": {
        "packages": [],
        "composer_packages": ["codeigniter4/framework", "codeigniter/framework"],
        "config_files": [],
        "indicators": ["application/config/", "app/Config/"]
    },
    "yii": {
        "packages": [],
        "composer_packages": ["yiisoft/yii2"],
        "config_files": [],
        "indicators": []
    },
    "wordpress": {
        "packages": [],
        "composer_packages": [],
        "config_files": ["wp-config.php"],
        "indicators": ["wp-content/", "wp-includes/"]
    },
    "drupal": {
        "packages": [],
        "composer_packages": ["drupal/core"],
        "config_files": [],
        "indicators": ["sites/default/", "modules/", "themes/"]
    },
    # Backend frameworks (Node.js)
    "express": {
        "packages": ["express"],
        "config_files": [],
        "indicators": []
    },
    "fastify": {
        "packages": ["fastify"],
        "config_files": [],
        "indicators": []
    },
    "koa": {
        "packages": ["koa"],
        "config_files": [],
        "indicators": []
    },
    "hono": {
        "packages": ["hono"],
        "config_files": [],
        "indicators": []
    },
    "nestjs": {
        "packages": ["@nestjs/core"],
        "config_files": ["nest-cli.json"],
        "indicators": []
    },
    # API layer
    "trpc": {
        "packages": ["@trpc/server"],
        "config_files": [],
        "indicators": []
    },
    # Data fetching libraries
    "swr": {
        "packages": ["swr"],
        "config_files": [],
        "indicators": []
    },
    "react_query": {
        "packages": ["@tanstack/react-query", "react-query"],
        "config_files": [],
        "indicators": []
    },
    # State management
    "zustand": {
        "packages": ["zustand"],
        "config_files": [],
        "indicators": []
    },
    "jotai": {
        "packages": ["jotai"],
        "config_files": [],
        "indicators": []
    },
    "recoil": {
        "packages": ["recoil"],
        "config_files": [],
        "indicators": []
    },
    "pinia": {
        "packages": ["pinia"],
        "config_files": [],
        "indicators": []
    },
    # Build tools
    "vite": {
        "packages": ["vite"],
        "config_files": ["vite.config.ts", "vite.config.js", "vite.config.mjs"],
        "indicators": []
    },
    "esbuild": {
        "packages": ["esbuild"],
        "config_files": [],
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
        "dev_frameworks": [],
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
        "has_laravel": False,
        "has_symfony": False,
        "has_php": False,
        "has_express": False,
        "has_fastify": False,
        "has_nestjs": False,
        "has_swr": False,
        "has_react_query": False,
        "has_trpc": False,
        "has_zustand": False,
        "has_jotai": False,
        "has_recoil": False,
        "has_pinia": False,
        "has_vite": False,
        "unsupported_langs": [],
        "css_preprocessor": None,
        "module_system": None,
        "monorepo_tool": None,
    }

    # 1. Check package.json (root + monorepo sub-packages)
    runtime_deps = {}  # dependencies + peerDependencies (runtime)
    dev_deps = {}      # devDependencies only
    all_deps = {}      # all combined (for completeness)
    pkg_files = _find_package_jsons(workspace)
    root_pkg_data = None

    for pkg_path in pkg_files:
        try:
            with open(pkg_path, 'r', encoding='utf-8') as f:
                pkg = json.load(f)
            deps = pkg.get("dependencies", {})
            devDeps = pkg.get("devDependencies", {})
            peerDeps = pkg.get("peerDependencies", {})

            runtime_deps.update(deps)
            runtime_deps.update(peerDeps)
            dev_deps.update(devDeps)
            all_deps.update(deps)
            all_deps.update(devDeps)
            all_deps.update(peerDeps)

            # Save root package.json for module system detection
            if pkg_path == os.path.join(workspace, "package.json"):
                root_pkg_data = pkg
        except (json.JSONDecodeError, IOError):
            pass

    # Detect module system from root package.json
    if root_pkg_data is not None:
        if root_pkg_data.get("type") == "module":
            detected["module_system"] = "esm"
        elif "exports" in root_pkg_data and "main" in root_pkg_data:
            detected["module_system"] = "dual"
        else:
            detected["module_system"] = "cjs"

    def _set_framework_flag(detected: dict, fw_name: str) -> None:
        """Set the has_<framework> flag for a detected framework."""
        flag_map = {
            "react": "has_react",
            "next.js": "has_nextjs",
            "vue": "has_vue",
            "svelte": "has_svelte",
            "tailwind": "has_tailwind",
            "angular": "has_angular",
            "tauri": "has_tauri",
            "electron": "has_electron",
            "golang": "has_golang",
            "express": "has_express",
            "fastify": "has_fastify",
            "nestjs": "has_nestjs",
            "swr": "has_swr",
            "react_query": "has_react_query",
            "trpc": "has_trpc",
            "zustand": "has_zustand",
            "jotai": "has_jotai",
            "recoil": "has_recoil",
            "pinia": "has_pinia",
            "vite": "has_vite",
        }
        flag = flag_map.get(fw_name)
        if flag:
            detected[flag] = True

    if all_deps:
        for fw_name, sig in FRAMEWORK_SIGNATURES.items():
            for pkg_name in sig["packages"]:
                if pkg_name in runtime_deps:
                    # Framework found in runtime dependencies
                    detected["frameworks"].append(fw_name)
                    _set_framework_flag(detected, fw_name)
                    break
                elif pkg_name in dev_deps:
                    # Framework only in devDependencies — classify as dev_framework
                    detected["dev_frameworks"].append(fw_name)
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
                _set_framework_flag(detected, fw_name)
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
                            _set_framework_flag(detected, fw_name)
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

    # 3d. Check PHP/composer.json for framework detection
    composer_deps = set()
    composer_path = os.path.join(workspace, "composer.json")
    if os.path.exists(composer_path):
        detected["has_php"] = True
        if "php" not in detected["frameworks"]:
            detected["frameworks"].append("php")

        try:
            with open(composer_path, 'r', encoding='utf-8') as f:
                composer = json.load(f)
            # Collect require and require-dev packages
            composer_deps.update(composer.get("require", {}).keys())
            composer_deps.update(composer.get("require-dev", {}).keys())
        except (json.JSONDecodeError, IOError):
            pass

        # Match composer deps against framework signatures
        for fw_name, sig in FRAMEWORK_SIGNATURES.items():
            if fw_name in detected["frameworks"]:
                continue
            composer_pkgs = sig.get("composer_packages", [])
            for pkg_name in composer_pkgs:
                if pkg_name in composer_deps:
                    detected["frameworks"].append(fw_name)
                    if fw_name == "laravel":
                        detected["has_laravel"] = True
                    elif fw_name == "symfony":
                        detected["has_symfony"] = True
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
            elif f.endswith('.php') and not detected["has_php"]:
                if "php" not in detected["frameworks"]:
                    detected["frameworks"].append("php")
                detected["has_php"] = True

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
                _set_framework_flag(detected, fw_name)
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

    # 6b. Detect Go web frameworks from go.mod content
    # Only flag gin/echo/etc if the dependency actually appears in go.mod,
    # NOT just because go.mod exists (every Go project has go.mod).
    go_mod_path = os.path.join(workspace, "go.mod")
    if os.path.isfile(go_mod_path):
        try:
            with open(go_mod_path, 'r', encoding='utf-8') as f:
                go_mod_content = f.read()
            _GO_FRAMEWORK_INDICATORS = {
                "gin": "gin-gonic/gin",
                "echo": "labstack/echo",
                "fiber": "gofiber/fiber",
                "chi": "go-chi/chi",
                "mux": "gorilla/mux",
                "grpc": "google.golang.org/grpc",
                "protobuf": "google.golang.org/protobuf",
            }
            for fw_name, dep_string in _GO_FRAMEWORK_INDICATORS.items():
                if fw_name in detected["frameworks"]:
                    continue
                if dep_string in go_mod_content:
                    detected["frameworks"].append(fw_name)
        except IOError:
            pass

    # 7. Detect monorepo tools
    _MONOREPO_MARKERS = {
        "pnpm-workspace.yaml": "pnpm",
        "turbo.json": "turborepo",
        "lerna.json": "lerna",
        "nx.json": "nx",
    }
    monorepo_tools = []
    for marker_file, tool_name in _MONOREPO_MARKERS.items():
        if os.path.exists(os.path.join(workspace, marker_file)):
            monorepo_tools.append(tool_name)
    if monorepo_tools:
        detected["monorepo_tool"] = "+".join(monorepo_tools)

    # 8. Detect unsupported languages (Java, C/C++, etc.)
    # Note: Go was previously listed here but now has fallback parser support.
    # It is no longer listed as unsupported.
    UNSUPPORTED_MARKERS = {
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
                break

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
        "ignore": ["node_modules/", "dist/", ".git/", "build/", "target/", "__pycache__/", "vendor/"],
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

    # Laravel/PHP: add PHP-specific paths
    if fw.get("has_laravel") or fw.get("has_php"):
        config["backend_paths"].extend(["app/", "routes/", "database/", "config/"])
        config["frontend_paths"].extend(["resources/views/", "resources/js/", "resources/css/", "public/"])
        if fw.get("has_laravel"):
            config["backend_paths"].extend(["app/Http/Controllers/", "app/Http/Middleware/", "app/Models/"])
            config["frontend_paths"].extend(["resources/views/"])

    # Symfony: add Symfony-specific paths
    if fw.get("has_symfony"):
        config["backend_paths"].extend(["src/", "config/", "migrations/"])
        config["frontend_paths"].extend(["templates/", "assets/"])

    # Express/Fastify/Koa/Hono: add backend API paths
    if fw.get("has_express") or fw.get("has_fastify"):
        config["backend_paths"].extend(["src/routes/", "routes/", "src/middleware/"])

    # NestJS: add module-based paths
    if fw.get("has_nestjs"):
        config["backend_paths"].extend(["src/modules/", "src/controllers/", "src/services/"])

    # tRPC: add router paths
    if fw.get("has_trpc"):
        config["backend_paths"].extend(["src/trpc/", "src/server/routers/"])

    # Vite: note in config (no path changes needed)
    if fw.get("has_vite"):
        pass  # Vite is a build tool, path conventions vary

    # Deduplicate paths
    config["frontend_paths"] = list(dict.fromkeys(config["frontend_paths"]))
    config["backend_paths"] = list(dict.fromkeys(config["backend_paths"]))

    # Add dev_frameworks and monorepo_tool to config
    config["dev_frameworks"] = fw.get("dev_frameworks", [])
    config["monorepo_tool"] = fw.get("monorepo_tool")

    return config
