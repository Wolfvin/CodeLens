"""
Framework Detector for CodeLens
Auto-detects frameworks from package.json, pyproject.toml, requirements.txt,
config files, and file patterns.  Also detects monorepo tools and build tools.
"""

import json
import os
import re
from typing import Dict, List, Any, Optional
import logging
_logger = logging.getLogger("codelens.framework_detect")
from utils import DEFAULT_IGNORE_DIRS

# ─── YAML parsing helper ──────────────────────────────────────

def _parse_pnpm_workspace_yaml(workspace: str) -> List[str]:
    """Parse pnpm-workspace.yaml and return a list of glob patterns for packages."""
    yaml_path = os.path.join(workspace, "pnpm-workspace.yaml")
    if not os.path.isfile(yaml_path):
        return []
    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # Very small YAML – just extract the 'packages:' list
        patterns = []
        in_packages = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            if stripped == 'packages:':
                in_packages = True
                continue
            if in_packages:
                # Stop when we hit a non-list line at the same or lower indent
                if stripped.startswith('- '):
                    val = stripped[2:].strip().strip('"').strip("'")
                    patterns.append(val)
                elif stripped and not stripped.startswith('#'):
                    # Hit catalog: or another top-level key – stop
                    if not line.startswith(' ') and not line.startswith('\t'):
                        break
        return patterns
    except (IOError, OSError):
        _logger.debug("Failed to parse pnpm-workspace.yaml", exc_info=True)
        return []


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
    # ── Backend / server frameworks ──────────────────────────────
    "express": {
        "packages": ["express"],
        "config_files": [],
        "indicators": ["app.get", "app.post", "router.get"]
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
        "indicators": ["@Module", "@Controller"]
    },
    "trpc": {
        "packages": ["@trpc/server"],
        "config_files": [],
        "indicators": []
    },
    # ── ORM / database ───────────────────────────────────────────
    "prisma": {
        "packages": ["prisma", "@prisma/client"],
        "config_files": ["prisma/schema.prisma"],
        "indicators": []
    },
    "drizzle": {
        "packages": ["drizzle-orm"],
        "config_files": ["drizzle.config.ts", "drizzle.config.js"],
        "indicators": []
    },
    "mongoose": {
        "packages": ["mongoose"],
        "config_files": [],
        "indicators": []
    },
    "typeorm": {
        "packages": ["typeorm"],
        "config_files": [],
        "indicators": []
    },
    # ── Build tools ──────────────────────────────────────────────
    "vite": {
        "packages": ["vite"],
        "config_files": ["vite.config.ts", "vite.config.js", "vite.config.mts"],
        "indicators": []
    },
    "webpack": {
        "packages": ["webpack"],
        "config_files": ["webpack.config.js", "webpack.config.ts"],
        "indicators": []
    },
    "esbuild": {
        "packages": ["esbuild"],
        "config_files": [],
        "indicators": []
    },
    "rollup": {
        "packages": ["rollup"],
        "config_files": ["rollup.config.js", "rollup.config.ts"],
        "indicators": []
    },
    # ── State management ─────────────────────────────────────────
    "pinia": {
        "packages": ["pinia"],
        "config_files": [],
        "indicators": []
    },
    "vuex": {
        "packages": ["vuex"],
        "config_files": [],
        "indicators": []
    },
    "redux": {
        "packages": ["@reduxjs/toolkit", "redux"],
        "config_files": [],
        "indicators": []
    },
    "zustand": {
        "packages": ["zustand"],
        "config_files": [],
        "indicators": []
    },
    # ── Real-time ────────────────────────────────────────────────
    "socket.io": {
        "packages": ["socket.io"],
        "config_files": [],
        "indicators": []
    }
}


def _find_package_jsons(workspace: str, max_depth: int = 4) -> List[str]:
    """
    Find all package.json files in the workspace, including monorepo sub-packages.
    Scans recursively up to *max_depth* levels inside known monorepo directories
    and pnpm-workspace.yaml patterns.  Skips node_modules and other ignored dirs.
    """
    pkg_files = []
    root_pkg = os.path.join(workspace, "package.json")
    if os.path.exists(root_pkg):
        pkg_files.append(root_pkg)

    # Directories that typically hold monorepo sub-packages
    monorepo_dirs = ('apps', 'packages', 'projects', 'services', 'libs', 'modules')

    # Dirs to skip during recursion (superset of DEFAULT_IGNORE_DIRS for speed)
    _skip_dirs = set(DEFAULT_IGNORE_DIRS) | {
        '.cache', '.temp', '.tmp', 'out', 'output', 'storybook-static',
    }

    # --- 1. Scan monorepo directories recursively ---
    for subdir in monorepo_dirs:
        subdir_path = os.path.join(workspace, subdir)
        if not os.path.isdir(subdir_path):
            continue
        for root, dirs, files in os.walk(subdir_path):
            # Compute depth relative to the monorepo dir
            rel = os.path.relpath(root, subdir_path)
            depth = 0 if rel == '.' else rel.count(os.sep) + 1
            if depth >= max_depth:
                dirs.clear()  # don't recurse deeper
                continue
            # Prune ignored directories from traversal
            dirs[:] = [d for d in dirs if d not in _skip_dirs and not d.startswith('.')]
            if 'package.json' in files:
                pkg_path = os.path.join(root, 'package.json')
                if pkg_path not in pkg_files:
                    pkg_files.append(pkg_path)

    # --- 2. Discover packages from pnpm-workspace.yaml patterns ---
    pnpm_patterns = _parse_pnpm_workspace_yaml(workspace)
    import glob as glob_mod
    for pattern in pnpm_patterns:
        # pnpm patterns like "packages/*" or "packages/frontend/**"
        full_pattern = os.path.join(workspace, pattern, 'package.json')
        for match in glob_mod.glob(full_pattern, recursive=True):
            abs_match = os.path.abspath(match)
            if abs_match not in pkg_files:
                pkg_files.append(abs_match)

    return pkg_files


# ─── Categories for classification ─────────────────────────────

_BUILD_TOOL_NAMES = frozenset({"vite", "webpack", "esbuild", "rollup"})


def detect_monorepo_tools(workspace: str) -> Dict[str, Any]:
    """
    Detect monorepo tooling in the workspace.
    Returns {"monorepo_tools": [...], "is_monorepo": bool}.
    """
    workspace = os.path.abspath(workspace)
    tools = []

    if os.path.isfile(os.path.join(workspace, "turbo.json")):
        tools.append("turborepo")
    if os.path.isfile(os.path.join(workspace, "pnpm-workspace.yaml")):
        tools.append("pnpm-workspace")
    if os.path.isfile(os.path.join(workspace, "lerna.json")):
        tools.append("lerna")
    if os.path.isfile(os.path.join(workspace, "nx.json")):
        tools.append("nx")

    return {
        "monorepo_tools": tools,
        "is_monorepo": len(tools) > 0,
    }


def detect_frameworks(workspace: str) -> Dict[str, Any]:
    """
    Detect frameworks used in a workspace.
    Returns dict with detected frameworks, build tools, monorepo tools,
    and per-framework booleans.
    """
    workspace = os.path.abspath(workspace)

    # ── Initialise result dict with all has_* booleans ────────────
    detected = {
        "frameworks": [],
        "build_tools": [],
        "monorepo_tools": [],
        # Frontend
        "has_react": False,
        "has_vue": False,
        "has_svelte": False,
        "has_tailwind": False,
        "has_nextjs": False,
        "has_angular": False,
        # Backend
        "has_express": False,
        "has_fastify": False,
        "has_koa": False,
        "has_hono": False,
        "has_nestjs": False,
        "has_trpc": False,
        # ORM / DB
        "has_prisma": False,
        "has_drizzle": False,
        "has_mongoose": False,
        "has_typeorm": False,
        # Python
        "has_fastapi": False,
        "has_flask": False,
        "has_django": False,
        # State management
        "has_pinia": False,
        "has_vuex": False,
        "has_redux": False,
        "has_zustand": False,
        # Real-time
        "has_socketio": False,
        # Build tools
        "has_vite": False,
        "has_webpack": False,
        "has_esbuild": False,
        "has_rollup": False,
        # Other
        "css_preprocessor": None,
        "module_system": None,
        "is_monorepo": False,
    }

    # ── Helper: set the has_* flag for a framework name ───────────
    _FW_TO_FLAG = {
        "react": "has_react",
        "next.js": "has_nextjs",
        "vue": "has_vue",
        "svelte": "has_svelte",
        "tailwind": "has_tailwind",
        "angular": "has_angular",
        "express": "has_express",
        "fastify": "has_fastify",
        "koa": "has_koa",
        "hono": "has_hono",
        "nestjs": "has_nestjs",
        "trpc": "has_trpc",
        "prisma": "has_prisma",
        "drizzle": "has_drizzle",
        "mongoose": "has_mongoose",
        "typeorm": "has_typeorm",
        "fastapi": "has_fastapi",
        "flask": "has_flask",
        "django": "has_django",
        "pinia": "has_pinia",
        "vuex": "has_vuex",
        "redux": "has_redux",
        "zustand": "has_zustand",
        "socket.io": "has_socketio",
        "vite": "has_vite",
        "webpack": "has_webpack",
        "esbuild": "has_esbuild",
        "rollup": "has_rollup",
    }

    def _mark_detected(fw_name: str):
        """Record a detected framework: append to list, set flag, classify build tools."""
        if fw_name in _BUILD_TOOL_NAMES:
            if fw_name not in detected["build_tools"]:
                detected["build_tools"].append(fw_name)
        else:
            if fw_name not in detected["frameworks"]:
                detected["frameworks"].append(fw_name)
        flag = _FW_TO_FLAG.get(fw_name)
        if flag:
            detected[flag] = True

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
                    _mark_detected(fw_name)
                    break

        # Detect CSS preprocessor
        if "sass" in all_deps or "node-sass" in all_deps or "sass-embedded" in all_deps:
            detected["css_preprocessor"] = "scss"
        elif "less" in all_deps:
            detected["css_preprocessor"] = "less"
        elif "stylus" in all_deps or "styl" in all_deps:
            detected["css_preprocessor"] = "stylus"

    # 2. Check config files (root + subdirectories for monorepos)
    for fw_name, sig in FRAMEWORK_SIGNATURES.items():
        if fw_name in detected["frameworks"] or fw_name in detected["build_tools"]:
            continue
        for cfg_file in sig.get("config_files", []):
            # Check root first
            if os.path.exists(os.path.join(workspace, cfg_file)):
                _mark_detected(fw_name)
                break
            # Check recursively in monorepo subdirs
            found_in_subdir = False
            for subdir in ('apps', 'packages', 'projects', 'services', 'libs', 'modules'):
                subdir_path = os.path.join(workspace, subdir)
                if not os.path.isdir(subdir_path):
                    continue
                for root, dirs, files in os.walk(subdir_path):
                    if os.path.exists(os.path.join(root, cfg_file)):
                        _mark_detected(fw_name)
                        found_in_subdir = True
                        break
                    # Only go 2 levels deep for config search
                    rel = os.path.relpath(root, subdir_path)
                    depth = 0 if rel == '.' else rel.count(os.sep) + 1
                    if depth >= 2:
                        dirs.clear()
                    dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
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
            _logger.debug("Failed to parse requirements.txt", exc_info=True)

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
            _logger.debug("Failed to parse pyproject.toml", exc_info=True)

    # 3c. Check pip deps against framework signatures
    for fw_name, sig in FRAMEWORK_SIGNATURES.items():
        if fw_name in detected["frameworks"] or fw_name in detected["build_tools"]:
            continue
        pip_pkgs = sig.get("pip_packages", sig.get("packages", []))
        for pkg_name in pip_pkgs:
            if pkg_name.lower() in pip_deps:
                _mark_detected(fw_name)
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
                _mark_detected("vue")
            elif f.endswith('.svelte') and not detected["has_svelte"]:
                _mark_detected("svelte")

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
                                    _mark_detected("tailwind")
                                    break
                            if detected["has_tailwind"]:
                                break
                    except IOError:
                        pass
            if detected["has_tailwind"]:
                break

    # 6. Detect monorepo tools
    monorepo_info = detect_monorepo_tools(workspace)
    detected["monorepo_tools"] = monorepo_info["monorepo_tools"]
    detected["is_monorepo"] = monorepo_info["is_monorepo"]

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
        "build_tools": fw.get("build_tools", []),
        "monorepo_tools": fw.get("monorepo_tools", []),
        "css_preprocessor": fw.get("css_preprocessor"),
        "jsx_mode": False,
        "vue_mode": False,
        "svelte_mode": False,
        "tailwind_mode": False,
        "is_monorepo": fw.get("is_monorepo", False),
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

    if fw["has_nestjs"]:
        config["backend_paths"].extend(["src/modules/", "src/controllers/", "src/services/"])

    if fw["has_express"]:
        config["backend_paths"].extend(["src/routes/", "routes/", "src/middleware/"])

    if fw.get("is_monorepo"):
        config["frontend_paths"].extend(["packages/frontend/", "apps/web/", "apps/client/"])
        config["backend_paths"].extend(["packages/backend/", "packages/cli/", "apps/api/", "apps/server/"])

    # Deduplicate paths
    config["frontend_paths"] = list(dict.fromkeys(config["frontend_paths"]))
    config["backend_paths"] = list(dict.fromkeys(config["backend_paths"]))

    return config
