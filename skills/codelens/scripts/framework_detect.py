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
    # Mobile/native frameworks
    "nativescript": {
        "packages": ["@nativescript/core"],
        "config_files": ["nativescript.config.ts", "nativescript.config.js"],
        "indicators": ["tns_modules"]
    },
    "capacitor": {
        "packages": ["@capacitor/core"],
        "config_files": ["capacitor.config.ts", "capacitor.config.json"],
        "indicators": []
    },
    "cordova": {
        "packages": ["cordova"],
        "config_files": ["config.xml"],
        "indicators": ["www"]
    },
    "expo": {
        "packages": ["expo"],
        "config_files": ["app.json", "app.config.js", "app.config.ts"],
        "indicators": []
    },
    "react-native": {
        "packages": ["react-native"],
        "config_files": [],
        "indicators": []
    },
    "ionic": {
        "packages": ["@ionic/react", "@ionic/angular", "@ionic/vue"],
        "config_files": ["ionic.config.json"],
        "indicators": []
    },
    # Monorepo tools
    "nx": {
        "packages": ["nx"],
        "config_files": ["nx.json"],
        "indicators": []
    },
    "turborepo": {
        "packages": ["turbo"],
        "config_files": ["turbo.json"],
        "indicators": []
    },
    # Desktop frameworks
    "tauri": {
        "packages": ["@tauri-apps/api"],
        "config_files": ["src-tauri/tauri.conf.json"],
        "indicators": []
    },
    "electron": {
        "packages": ["electron"],
        "config_files": ["electron-builder.yml", "electron-builder.json"],
        "indicators": []
    },
    # PHP frameworks
    "laravel": {
        "packages": [],
        "composer_packages": ["laravel/framework"],
        "config_files": ["artisan"],
        "indicators": ["blade.php"]
    },
    "symfony": {
        "packages": [],
        "composer_packages": ["symfony/framework-bundle", "symfony/symfony"],
        "config_files": ["symfony.lock"],
        "indicators": []
    },
    "wordpress": {
        "packages": [],
        "composer_packages": ["johnpbloch/wordpress"],
        "config_files": ["wp-config.php", "wp-settings.php"],
        "indicators": []
    },
    "drupal": {
        "packages": [],
        "composer_packages": ["drupal/core"],
        "config_files": ["drush.services.yml"],
        "indicators": []
    },
    "codeigniter": {
        "packages": [],
        "composer_packages": ["codeigniter4/framework", "codeigniter/framework"],
        "config_files": [],
        "indicators": []
    },
    # Go frameworks
    "gin": {
        "packages": [],
        "go_modules": ["github.com/gin-gonic/gin"],
        "config_files": [],
        "indicators": []
    },
    "echo": {
        "packages": [],
        "go_modules": ["github.com/labstack/echo"],
        "config_files": [],
        "indicators": []
    },
    "fiber": {
        "packages": [],
        "go_modules": ["github.com/gofiber/fiber"],
        "config_files": [],
        "indicators": []
    },
    "chi": {
        "packages": [],
        "go_modules": ["github.com/go-chi/chi"],
        "config_files": [],
        "indicators": []
    },
    "mux": {
        "packages": [],
        "go_modules": ["github.com/gorilla/mux"],
        "config_files": [],
        "indicators": []
    },
    "beego": {
        "packages": [],
        "go_modules": ["github.com/beego/beego"],
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
        "has_react": False,
        "has_vue": False,
        "has_svelte": False,
        "has_tailwind": False,
        "has_nextjs": False,
        "has_angular": False,
        "has_fastapi": False,
        "has_flask": False,
        "has_django": False,
        "has_nativescript": False,
        "has_capacitor": False,
        "has_expo": False,
        "has_react_native": False,
        "has_nx": False,
        "has_tauri": False,
        "has_electron": False,
        "has_rust_backend": False,
        "has_laravel": False,
        "has_go_backend": False,
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

    # 1b. Better module system detection — check multiple signals
    if detected["module_system"] is None or detected["module_system"] == "cjs":
        # Check if any sub-package.json has "type": "module"
        for pkg_path in pkg_files:
            try:
                with open(pkg_path, 'r', encoding='utf-8') as f:
                    pkg = json.load(f)
                if pkg.get("type") == "module":
                    detected["module_system"] = "esm"
                    break
            except (json.JSONDecodeError, IOError):
                pass
        # Check for .mjs files as ESM indicator
        if detected["module_system"] != "esm":
            mjs_count = 0
            cjs_count = 0
            for root, dirs, filenames in os.walk(workspace):
                dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
                if '.codelens' in root:
                    dirs.clear()
                    continue
                for fn in filenames:
                    if fn.endswith('.mjs'):
                        mjs_count += 1
                    elif fn.endswith('.cjs'):
                        cjs_count += 1
                if mjs_count + cjs_count > 20:
                    break
            if mjs_count > cjs_count:
                detected["module_system"] = "esm"
            elif mjs_count > 0 and cjs_count == 0:
                detected["module_system"] = "esm"
        # Check for pnpm-workspace.yaml (monorepos often use ESM)
        if detected["module_system"] == "cjs" and os.path.isfile(os.path.join(workspace, "pnpm-workspace.yaml")):
            # Check if .mjs files exist
            for root, dirs, filenames in os.walk(workspace):
                dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
                if '.codelens' in root:
                    dirs.clear()
                    continue
                if any(fn.endswith('.mjs') for fn in filenames):
                    detected["module_system"] = "esm"
                    break

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
                    elif fw_name == "nativescript":
                        detected["has_nativescript"] = True
                    elif fw_name == "capacitor":
                        detected["has_capacitor"] = True
                    elif fw_name == "expo":
                        detected["has_expo"] = True
                    elif fw_name == "react-native":
                        detected["has_react_native"] = True
                    elif fw_name == "nx":
                        detected["has_nx"] = True
                    elif fw_name == "tauri":
                        detected["has_tauri"] = True
                    elif fw_name == "electron":
                        detected["has_electron"] = True
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
                elif fw_name == "tauri":
                    detected["has_tauri"] = True
                elif fw_name == "electron":
                    detected["has_electron"] = True
                break
            # Check one level deep for monorepo (apps/*, packages/*, src-tauri/*)
            found_in_subdir = False
            for subdir in ('apps', 'packages', 'projects', 'services', 'src-tauri'):
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

    # 3d. Check Cargo.toml for Rust dependencies (Tauri, Axum, Actix, etc.)
    cargo_deps = set()
    _find_cargo_toml = lambda ws: [
        os.path.join(ws, "Cargo.toml"),
        os.path.join(ws, "src-tauri", "Cargo.toml"),
    ]

    for cargo_path in _find_cargo_toml(workspace):
        if not os.path.exists(cargo_path):
            continue
        try:
            with open(cargo_path, 'r', encoding='utf-8') as f:
                cargo_content = f.read()
            # Parse [package] section — extract package name (for repos that ARE the framework)
            in_package = False
            for line in cargo_content.split('\n'):
                stripped = line.strip()
                if stripped == '[package]':
                    in_package = True
                    continue
                if stripped.startswith('[') and in_package:
                    in_package = False
                    continue
                if in_package and stripped.startswith('name'):
                    pkg_name_match = re.match(r'name\s*=\s*["\']?([^"\'\s]+)', stripped)
                    if pkg_name_match:
                        pkg_name = pkg_name_match.group(1).lower()
                        cargo_deps.add(pkg_name)
            # Parse [dependencies] section — extract crate names
            in_deps = False
            for line in cargo_content.split('\n'):
                stripped = line.strip()
                if stripped == '[dependencies]':
                    in_deps = True
                    continue
                if stripped.startswith('[') and in_deps:
                    break  # End of [dependencies] section
                if in_deps and '=' in stripped:
                    crate_name = stripped.split('=')[0].strip().lower()
                    if crate_name:
                        cargo_deps.add(crate_name)
            # Also check [workspace.dependencies] for monorepos
            in_workspace_deps = False
            for line in cargo_content.split('\n'):
                stripped = line.strip()
                if stripped == '[workspace.dependencies]':
                    in_workspace_deps = True
                    continue
                if stripped.startswith('[') and in_workspace_deps:
                    break
                if in_workspace_deps and '=' in stripped:
                    crate_name = stripped.split('=')[0].strip().lower()
                    if crate_name:
                        cargo_deps.add(crate_name)
            # Parse [workspace] section — extract members (for workspace repos)
            in_workspace = False
            in_members = False
            for line in cargo_content.split('\n'):
                stripped = line.strip()
                if stripped == '[workspace]':
                    in_workspace = True
                    continue
                if stripped.startswith('[') and in_workspace:
                    in_workspace = False
                    continue
                if in_workspace:
                    # Parse members = [...] list
                    if stripped.startswith('members'):
                        in_members = True
                    if in_members:
                        # Extract member names (may span multiple lines)
                        for member_match in re.finditer(r'"([^"]+)"', stripped):
                            member_name = member_match.group(1).lower()
                            cargo_deps.add(member_name)
                        if ']' in stripped:
                            in_members = False
        except IOError:
            logger.debug("Failed to parse Cargo.toml", exc_info=True)

    if cargo_deps:
        detected["has_rust_backend"] = True
        # Detect Tauri from Cargo dependency
        if "tauri" in cargo_deps:
            if "tauri" not in detected["frameworks"]:
                detected["frameworks"].append("tauri")
            detected["has_tauri"] = True
        # Detect other Rust frameworks
        rust_framework_map = {
            "axum": "axum",
            "actix-web": "actix",
            "rocket": "rocket",
            "warp": "warp",
        }
        for crate, fw_name in rust_framework_map.items():
            if crate in cargo_deps and fw_name not in detected["frameworks"]:
                detected["frameworks"].append(fw_name)

    # 4. Check composer.json for PHP framework dependencies
    composer_deps = set()
    composer_path = os.path.join(workspace, "composer.json")
    if os.path.exists(composer_path):
        try:
            with open(composer_path, 'r', encoding='utf-8') as f:
                composer_data = json.load(f)
            # Extract from "require" and "require-dev"
            for section in ("require", "require-dev"):
                deps = composer_data.get(section, {})
                for pkg_name in deps:
                    composer_deps.add(pkg_name.lower())
        except (json.JSONDecodeError, IOError):
            _logger.debug("Failed to parse composer.json", exc_info=True)

    if composer_deps:
        # Check PHP framework signatures against composer deps
        for fw_name, sig in FRAMEWORK_SIGNATURES.items():
            if fw_name in detected["frameworks"]:
                continue
            composer_pkgs = sig.get("composer_packages", [])
            for pkg_name in composer_pkgs:
                if pkg_name.lower() in composer_deps:
                    detected["frameworks"].append(fw_name)
                    if fw_name == "laravel":
                        detected["has_laravel"] = True
                    break

    # 5. Check go.mod for Go framework dependencies
    go_deps = set()
    go_module = ""
    go_mod_path = os.path.join(workspace, "go.mod")
    if os.path.exists(go_mod_path):
        detected["has_go_backend"] = True
        try:
            with open(go_mod_path, 'r', encoding='utf-8') as f:
                go_mod_content = f.read()
            # Parse module line: module github.com/gin-gonic/gin
            module_match = re.search(r'^module\s+(\S+)', go_mod_content, re.MULTILINE)
            if module_match:
                go_module = module_match.group(1).lower()
                go_deps.add(go_module)
                # Also add just the package name (last segment)
                parts = go_module.split('/')
                if len(parts) >= 3:
                    go_deps.add(parts[-1])
            # Parse require block: require ( ... ) or require pkg vN
            in_require = False
            for line in go_mod_content.split('\n'):
                stripped = line.strip()
                if stripped.startswith('require ('):
                    in_require = True
                    continue
                if stripped == ')' and in_require:
                    in_require = False
                    continue
                if in_require or stripped.startswith('require '):
                    # Extract module path: "github.com/gin-gonic/gin v1.9.1"
                    match = re.match(r'(?:require\s+)?(\S+)', stripped)
                    if match:
                        mod_path = match.group(1).lower()
                        go_deps.add(mod_path)
                        # Also add just the package name for matching
                        parts = mod_path.split('/')
                        if len(parts) >= 3:
                            go_deps.add(parts[-1])  # e.g., "gin"
        except IOError:
            _logger.debug("Failed to parse go.mod", exc_info=True)

    if go_deps:
        # Check Go framework signatures against go.mod deps
        for fw_name, sig in FRAMEWORK_SIGNATURES.items():
            if fw_name in detected["frameworks"]:
                continue
            go_modules = sig.get("go_modules", [])
            for mod_path in go_modules:
                if mod_path.lower() in go_deps:
                    detected["frameworks"].append(fw_name)
                    break

    # 6. Check file patterns (for Vue, Svelte) + Tailwind CSS in one walk
    need_file_scan = (not detected["has_vue"]) or (not detected["has_svelte"]) or (not detected["has_tailwind"])
    if need_file_scan:
        for root, dirs, files in os.walk(workspace):
            # Skip ignored dirs
            dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
            skip = False
            for ignore in DEFAULT_IGNORE_DIRS:
                if ignore in root:
                    skip = True
                    break
            if skip:
                continue

            # Check Vue/Svelte file patterns
            for f in files:
                if f.endswith('.vue') and not detected["has_vue"]:
                    if "vue" not in detected["frameworks"]:
                        detected["frameworks"].append("vue")
                    detected["has_vue"] = True
                elif f.endswith('.svelte') and not detected["has_svelte"]:
                    if "svelte" not in detected["frameworks"]:
                        detected["frameworks"].append("svelte")
                    detected["has_svelte"] = True

            # Check Tailwind from CSS content
            if not detected["has_tailwind"]:
                for f in files:
                    if f.endswith(('.css', '.scss', '.pcss')):
                        try:
                            fpath = os.path.join(root, f)
                            with open(fpath, 'r', encoding='utf-8', errors='ignore') as fh:
                                content = fh.read(4096)  # Read first 4KB
                                if '@tailwind' in content or '@apply' in content:
                                    if "tailwind" not in detected["frameworks"]:
                                        detected["frameworks"].append("tailwind")
                                    detected["has_tailwind"] = True
                                    break
                        except IOError:
                            pass
                if detected["has_tailwind"]:
                    pass  # Continue walking for Vue/Svelte if not found yet

            # Early exit if all targets found
            if detected["has_vue"] and detected["has_svelte"] and detected["has_tailwind"]:
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

    if fw.get("has_tauri"):
        config["frontend_paths"].extend(["src/", "src-tauri/"])
        config["backend_paths"].extend(["src-tauri/src/"])
        # Remove generic src/ from backend_paths since it's frontend in Tauri
        if "src/" in config["backend_paths"]:
            config["backend_paths"].remove("src/")

    if fw.get("has_nativescript"):
        config["frontend_paths"].extend(["app/", "src/app/"])
        config["backend_paths"].extend(["src/"])

    if fw.get("has_capacitor"):
        config["frontend_paths"].extend(["src/", "www/"])
        config["backend_paths"].extend(["android/", "ios/"])

    # Laravel-specific paths
    if fw.get("has_laravel"):
        config["frontend_paths"].extend(["resources/views/", "resources/js/", "resources/css/", "public/"])
        config["backend_paths"].extend(["app/", "routes/", "app/Http/Controllers/", "app/Models/"])
        config["ignore"].extend(["storage/", "bootstrap/cache/"])

    # Go-specific paths
    if fw.get("has_go_backend"):
        config["backend_paths"].extend(["cmd/", "internal/", "pkg/", "api/"])
        config["ignore"].extend(["vendor/"])

    # Deduplicate paths
    config["frontend_paths"] = list(dict.fromkeys(config["frontend_paths"]))
    config["backend_paths"] = list(dict.fromkeys(config["backend_paths"]))

    return config
