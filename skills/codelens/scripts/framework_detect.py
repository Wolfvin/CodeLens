"""
Framework Detector for CodeLens
Auto-detects frameworks from package.json, pyproject.toml, requirements.txt,
config files, and file patterns.

v6: Added monorepo detection, sub-directory package.json scanning,
Rust/Cargo detection, and build tool detection.
"""

import json
import os
import re
from typing import Dict, List, Any, Optional
from utils import DEFAULT_IGNORE_DIRS


# v6: Monorepo indicator files
MONOREPO_INDICATORS = {
    "turbo.json": "turborepo",
    "pnpm-workspace.yaml": "pnpm-workspace",
    "lerna.json": "lerna",
    "nx.json": "nx",
}

# v6: Build tool config files
BUILD_TOOL_CONFIGS = {
    "vite.config.js": "vite",
    "vite.config.mjs": "vite",
    "vite.config.ts": "vite",
    "webpack.config.js": "webpack",
    "webpack.config.mjs": "webpack",
    "webpack.config.ts": "webpack",
    "rollup.config.js": "rollup",
    "rollup.config.mjs": "rollup",
    "rollup.config.ts": "rollup",
    "esbuild.config.js": "esbuild",
    "gulpfile.js": "gulp",
    "Gruntfile.js": "grunt",
    "tsconfig.json": "typescript",
}

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
    }
}


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
        "css_preprocessor": None,
        "module_system": None,
        # v6: monorepo and build tool awareness
        "is_monorepo": False,
        "monorepo_tools": [],
        "build_tools": [],
        "has_rust": False,
        "subdir_frameworks": {},   # subdir path → list of frameworks
    }

    # v6: 0. Check monorepo indicators at workspace root
    for indicator_file, tool_name in MONOREPO_INDICATORS.items():
        indicator_path = os.path.join(workspace, indicator_file)
        if os.path.isfile(indicator_path):
            detected["is_monorepo"] = True
            if tool_name not in detected["monorepo_tools"]:
                detected["monorepo_tools"].append(tool_name)
            if tool_name not in detected["frameworks"]:
                detected["frameworks"].append(tool_name)

    # v6: 0b. Check build tool configs at workspace root
    for cfg_file, tool_name in BUILD_TOOL_CONFIGS.items():
        cfg_path = os.path.join(workspace, cfg_file)
        if os.path.isfile(cfg_path):
            if tool_name not in detected["build_tools"]:
                detected["build_tools"].append(tool_name)
            if tool_name not in detected["frameworks"]:
                detected["frameworks"].append(tool_name)

    # v6: 0c. Rust/Cargo detection at root and crates/*
    cargo_path = os.path.join(workspace, "Cargo.toml")
    if os.path.isfile(cargo_path):
        detected["has_rust"] = True
        if "rust" not in detected["frameworks"]:
            detected["frameworks"].append("rust")
    # Check crates/* sub-directories for nested Cargo.toml
    crates_dir = os.path.join(workspace, "crates")
    if os.path.isdir(crates_dir):
        try:
            for entry in os.listdir(crates_dir):
                entry_cargo = os.path.join(crates_dir, entry, "Cargo.toml")
                if os.path.isfile(entry_cargo):
                    detected["has_rust"] = True
                    if "rust" not in detected["frameworks"]:
                        detected["frameworks"].append("rust")
        except OSError:
            pass

    # 1. Check package.json
    pkg_path = os.path.join(workspace, "package.json")
    if os.path.exists(pkg_path):
        try:
            with open(pkg_path, 'r', encoding='utf-8') as f:
                pkg = json.load(f)
            all_deps = {}
            all_deps.update(pkg.get("dependencies", {}))
            all_deps.update(pkg.get("devDependencies", {}))
            all_deps.update(pkg.get("peerDependencies", {}))

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
                        break

            # Detect CSS preprocessor
            if "sass" in all_deps or "node-sass" in all_deps:
                detected["css_preprocessor"] = "scss"
            elif "less" in all_deps:
                detected["css_preprocessor"] = "less"
            elif "stylus" in all_deps or "styl" in all_deps:
                detected["css_preprocessor"] = "stylus"

            # Detect module system
            if "type" in pkg and pkg["type"] == "module":
                detected["module_system"] = "esm"
            else:
                detected["module_system"] = "cjs"

        except (json.JSONDecodeError, IOError):
            pass

    # v6: 1b. Walk sub-directory package.json files (1-2 levels into apps/*, packages/*)
    #       to find frameworks used in workspace packages, not just the root package.json.
    _MONOREPO_SUBDIRS = ["apps", "packages", "services"]
    for subdir in _MONOREPO_SUBDIRS:
        subdir_path = os.path.join(workspace, subdir)
        if not os.path.isdir(subdir_path):
            continue
        try:
            for entry in sorted(os.listdir(subdir_path)):
                entry_pkg = os.path.join(subdir_path, entry, "package.json")
                if not os.path.isfile(entry_pkg):
                    continue
                try:
                    with open(entry_pkg, 'r', encoding='utf-8') as f:
                        pkg = json.load(f)
                    sub_deps = {}
                    sub_deps.update(pkg.get("dependencies", {}))
                    sub_deps.update(pkg.get("devDependencies", {}))
                    sub_deps.update(pkg.get("peerDependencies", {}))

                    rel_subdir = os.path.join(subdir, entry)
                    subdir_fws = []
                    for fw_name, sig in FRAMEWORK_SIGNATURES.items():
                        for pkg_name in sig["packages"]:
                            if pkg_name in sub_deps:
                                subdir_fws.append(fw_name)
                                # Also update top-level flags
                                if fw_name not in detected["frameworks"]:
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
                    if subdir_fws:
                        detected["subdir_frameworks"][rel_subdir] = subdir_fws
                except (json.JSONDecodeError, IOError):
                    pass
        except OSError:
            pass

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

    # 4. Check file patterns (for Vue, Svelte)
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

    # v6: 4b. Detect build tools via glob patterns (vite.config.*, webpack.config.*, etc.)
    #     Already checked exact names above; here we catch extensions we may have missed.
    for root, dirs, files in os.walk(workspace):
        # Only check workspace root level (depth 0) for build configs
        depth = os.path.relpath(root, workspace).count(os.sep) if root != workspace else 0
        if depth > 0:
            break
        for f in files:
            for prefix, tool_name in [("vite.config.", "vite"), ("webpack.config.", "webpack"), ("rollup.config.", "rollup"), ("esbuild.config.", "esbuild")]:
                if f.startswith(prefix):
                    if tool_name not in detected["build_tools"]:
                        detected["build_tools"].append(tool_name)
                    if tool_name not in detected["frameworks"]:
                        detected["frameworks"].append(tool_name)

    # 5. Detect Tailwind from CSS content
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

    return detected


def _check_subdir_package_jsons(workspace: str, subdir_name: str, detected: Dict[str, Any]) -> None:
    """v6: Helper to scan a monorepo sub-directory for package.json files."""
    subdir_path = os.path.join(workspace, subdir_name)
    if not os.path.isdir(subdir_path):
        return
    try:
        for entry in sorted(os.listdir(subdir_path)):
            entry_pkg = os.path.join(subdir_path, entry, "package.json")
            if not os.path.isfile(entry_pkg):
                continue
            try:
                with open(entry_pkg, 'r', encoding='utf-8') as f:
                    pkg = json.load(f)
                sub_deps = {}
                sub_deps.update(pkg.get("dependencies", {}))
                sub_deps.update(pkg.get("devDependencies", {}))
                sub_deps.update(pkg.get("peerDependencies", {}))

                rel_subdir = os.path.join(subdir_name, entry)
                subdir_fws = []
                for fw_name, sig in FRAMEWORK_SIGNATURES.items():
                    for pkg_name in sig["packages"]:
                        if pkg_name in sub_deps:
                            subdir_fws.append(fw_name)
                            if fw_name not in detected["frameworks"]:
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
                if subdir_fws:
                    detected["subdir_frameworks"][rel_subdir] = subdir_fws
            except (json.JSONDecodeError, IOError):
                pass
    except OSError:
        pass


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

    # v6: When monorepo is detected, add appropriate frontend/backend paths
    if fw.get("is_monorepo"):
        config["frontend_paths"].extend(["apps/*/", "packages/*/"])
        config["backend_paths"].extend(["apps/*/api/", "apps/*/server/", "services/*/"])
    if fw.get("has_rust"):
        config["backend_paths"].extend(["crates/*/"])
        if "target/" not in config["ignore"]:
            config["ignore"].append("target/")  # Rust build output

    # Deduplicate paths
    config["frontend_paths"] = list(dict.fromkeys(config["frontend_paths"]))
    config["backend_paths"] = list(dict.fromkeys(config["backend_paths"]))

    # v6: Carry monorepo/build tool info into config
    config["is_monorepo"] = fw.get("is_monorepo", False)
    config["monorepo_tools"] = fw.get("monorepo_tools", [])
    config["build_tools"] = fw.get("build_tools", [])
    config["subdir_frameworks"] = fw.get("subdir_frameworks", {})

    return config
