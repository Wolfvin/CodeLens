"""
Framework Detector for CodeLens
Auto-detects frameworks from package.json, pyproject.toml, requirements.txt,
config files, and file patterns.
"""

import json
import os
import re
from typing import Dict, List, Any, Optional
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
        "has_tauri": False,
        "has_rust_backend": False,
        "css_preprocessor": None,
        "module_system": None
    }

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

    # Also detect Tauri from config file presence
    if not detected["has_tauri"]:
        tauri_conf_paths = [
            os.path.join(workspace, "src-tauri", "tauri.conf.json"),
            os.path.join(workspace, "src-tauri", "tauri.conf.json5"),
        ]
        for tpath in tauri_conf_paths:
            if os.path.exists(tpath):
                if "tauri" not in detected["frameworks"]:
                    detected["frameworks"].append("tauri")
                detected["has_tauri"] = True
                detected["has_rust_backend"] = True
                break

    # Detect any Rust project (even without Tauri)
    if not detected["has_rust_backend"] and cargo_deps:
        detected["has_rust_backend"] = True

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
    # Tauri: src/ is frontend, src-tauri/src/ is Rust backend
    if fw.get("has_tauri"):
        # For Tauri projects, src/ is the web frontend, not backend
        # Remove src/ from backend_paths to prevent misclassification
        config["backend_paths"] = [p for p in config["backend_paths"] if p != "src/"]
        # Add Tauri-specific paths
        config["frontend_paths"].extend(["src/", "src/components/", "src/pages/", "src/views/"])
        config["backend_paths"].extend(["src-tauri/src/"])
        config["jsx_mode"] = True
        # Add src-tauri/target to ignore (Rust build artifacts)
        if "src-tauri/target/" not in config.get("ignore", []):
            config.setdefault("ignore", []).append("src-tauri/target/")

    if fw["has_nextjs"]:
        config["frontend_paths"].extend(["app/", "src/app/", "pages/", "src/pages/"])
        config["backend_paths"].extend(["app/api/", "src/app/api/"])
        config["jsx_mode"] = True
        # Next.js app router — everything under app/ could be frontend
        config["frontend_paths"] = list(set(config["frontend_paths"]))

    if fw["has_react"] and not fw.get("has_tauri"):
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

    # Deduplicate paths
    config["frontend_paths"] = list(dict.fromkeys(config["frontend_paths"]))
    config["backend_paths"] = list(dict.fromkeys(config["backend_paths"]))

    return config
