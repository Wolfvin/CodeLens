"""
Framework Detector for CodeLens
Auto-detects frameworks from package.json, config files, and file patterns.
"""

import json
import os
from typing import Dict, List, Any, Optional
from utils import logger, DEFAULT_IGNORE_DIRS


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
            logger.debug("Failed to parse package file", exc_info=True)

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
                break

    # 3. Check file patterns (for Vue, Svelte)
    for root, dirs, files in os.walk(workspace):
        # Skip ignored dirs — use centralized list
        skip = False
        for ignore in DEFAULT_IGNORE_DIRS:
            if ignore in root.split(os.sep):
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

    # 4. Detect Tailwind from CSS content
    if not detected["has_tailwind"]:
        tailwind_indicators = ['@tailwind', '@apply', 'tw-', 'tailwind']
        for root, dirs, files in os.walk(workspace):
            skip = False
            for ignore in DEFAULT_IGNORE_DIRS:
                if ignore in root.split(os.sep):
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
                        logger.debug("Failed to parse package file", exc_info=True)
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

    # Deduplicate paths
    config["frontend_paths"] = list(dict.fromkeys(config["frontend_paths"]))
    config["backend_paths"] = list(dict.fromkeys(config["backend_paths"]))

    return config
