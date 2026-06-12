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
    # Backend frameworks
    "express": {
        "packages": ["express"],
        "config_files": [],
        "indicators": ["app.listen", "app.get", "app.post", "express()"]
    },
    "nestjs": {
        "packages": ["@nestjs/core", "@nestjs/common"],
        "config_files": ["nest-cli.json"],
        "indicators": ["@Module", "@Controller", "@Injectable", "@Get", "@Post"]
    },
    "fastify": {
        "packages": ["fastify"],
        "config_files": [],
        "indicators": ["fastify.get", "fastify.post", "fastify.register"]
    },
    "koa": {
        "packages": ["koa", "@koa/router", "koa-router"],
        "config_files": [],
        "indicators": []
    },
    "hono": {
        "packages": ["hono"],
        "config_files": [],
        "indicators": ["new Hono", "app.get", "app.post"]
    },
    # ORM / Database
    "typeorm": {
        "packages": ["typeorm"],
        "config_files": ["ormconfig.json", "data-source.ts", "data-source.js"],
        "indicators": ["@Entity", "createConnection", "DataSource"]
    },
    "mikro-orm": {
        "packages": ["@mikro-orm/core"],
        "config_files": ["mikro-orm.config.ts", "mikro-orm.config.js"],
        "indicators": ["@Entity", "MikroORM", "EntityManager"]
    },
    "prisma": {
        "packages": ["@prisma/client"],
        "config_files": ["prisma/schema.prisma"],
        "indicators": ["prisma.", "PrismaClient"]
    },
    "sequelize": {
        "packages": ["sequelize"],
        "config_files": [".sequelizerc"],
        "indicators": ["Sequelize(", "DataTypes."]
    },
    "drizzle": {
        "packages": ["drizzle-orm"],
        "config_files": ["drizzle.config.ts", "drizzle.config.js"],
        "indicators": []
    },
    # Test frameworks
    "jest": {
        "packages": ["jest"],
        "config_files": ["jest.config.js", "jest.config.ts", "jest.config.mjs"],
        "indicators": ["describe(", "it(", "test("]
    },
    "vitest": {
        "packages": ["vitest"],
        "config_files": ["vitest.config.ts", "vitest.config.js"],
        "indicators": []
    },
    # Build tools
    "vite": {
        "packages": ["vite"],
        "config_files": ["vite.config.ts", "vite.config.js", "vite.config.mjs"],
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
    # Job queue
    "bullmq": {
        "packages": ["bullmq"],
        "config_files": [],
        "indicators": ["Queue(", "Worker("]
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

# Category classifiers for framework names
_BACKEND_FW_NAMES = ("express", "nestjs", "fastify", "koa", "hono", "fastapi", "flask", "django", "starlette")
_ORM_NAMES = ("typeorm", "mikro-orm", "prisma", "sequelize", "drizzle", "sqlalchemy")
_BUILD_TOOL_NAMES = ("vite", "webpack", "esbuild")
_TEST_FW_NAMES = ("jest", "vitest")


def _find_package_jsons(workspace: str, max_depth: int = 3) -> List[str]:
    """
    Find all package.json files in the workspace, including monorepo sub-packages.
    Uses os.walk recursively up to max_depth to find deeply nested packages
    (e.g., packages/modules/auth/package.json, packages/core/utils/package.json).
    """
    pkg_files = []
    root_pkg = os.path.join(workspace, "package.json")
    if os.path.exists(root_pkg):
        pkg_files.append(root_pkg)

    # Convert DEFAULT_IGNORE_DIRS to set for fast lookup
    ignore_set = set(DEFAULT_IGNORE_DIRS)

    # Walk the directory tree up to max_depth
    for root, dirs, files in os.walk(workspace):
        # Calculate depth relative to workspace
        rel_path = os.path.relpath(root, workspace)
        if rel_path == '.':
            depth = 0
        else:
            depth = rel_path.count(os.sep) + 1

        # Prune ignored directories (in-place modification of dirs)
        if depth >= max_depth:
            # Don't descend further, but still check files at this depth
            dirs.clear()
        else:
            dirs[:] = [d for d in dirs if d not in ignore_set and d != '.codelens' and d != 'node_modules']

        # Check if package.json exists in this directory
        if "package.json" in files and root != workspace:
            pkg_files.append(os.path.join(root, "package.json"))

    _logger.debug("Found %d package.json files (max_depth=%d)", len(pkg_files), max_depth)
    return pkg_files


def _detect_monorepo_tools(workspace: str) -> Dict[str, Any]:
    """
    Detect monorepo tooling (Turborepo, Yarn workspaces, pnpm workspaces, Nx, Lerna).
    Returns {"monorepo_tools": [...], "is_monorepo": bool}.
    """
    tools = []

    # Turborepo: turbo.json
    if os.path.isfile(os.path.join(workspace, "turbo.json")):
        tools.append("turborepo")
        _logger.debug("Detected monorepo tool: turborepo (turbo.json)")

    # pnpm workspaces: pnpm-workspace.yaml
    if os.path.isfile(os.path.join(workspace, "pnpm-workspace.yaml")):
        tools.append("pnpm-workspace")
        _logger.debug("Detected monorepo tool: pnpm-workspace (pnpm-workspace.yaml)")

    # Lerna: lerna.json
    if os.path.isfile(os.path.join(workspace, "lerna.json")):
        tools.append("lerna")
        _logger.debug("Detected monorepo tool: lerna (lerna.json)")

    # Nx: nx.json
    if os.path.isfile(os.path.join(workspace, "nx.json")):
        tools.append("nx")
        _logger.debug("Detected monorepo tool: nx (nx.json)")

    # Yarn workspaces: .yarnrc.yml + workspaces field in package.json
    yarnrc = os.path.isfile(os.path.join(workspace, ".yarnrc.yml"))
    root_pkg_path = os.path.join(workspace, "package.json")
    has_workspaces = False
    if os.path.isfile(root_pkg_path):
        try:
            with open(root_pkg_path, 'r', encoding='utf-8') as f:
                pkg = json.load(f)
            if "workspaces" in pkg:
                has_workspaces = True
                # Distinguish yarn vs npm workspaces
                if yarnrc:
                    tools.append("yarn-workspace")
                    _logger.debug("Detected monorepo tool: yarn-workspace (.yarnrc.yml + workspaces)")
                else:
                    tools.append("npm-workspace")
                    _logger.debug("Detected monorepo tool: npm-workspace (package.json workspaces)")
        except (json.JSONDecodeError, IOError):
            pass

    # Also check .yarnrc (classic yarn)
    if os.path.isfile(os.path.join(workspace, ".yarnrc")) and "yarn-workspace" not in tools:
        if has_workspaces:
            tools.append("yarn-workspace")
            _logger.debug("Detected monorepo tool: yarn-workspace (.yarnrc + workspaces)")

    is_monorepo = len(tools) > 0
    return {"monorepo_tools": tools, "is_monorepo": is_monorepo}


def _detect_build_tools(all_deps: Dict[str, str], workspace: str) -> List[str]:
    """
    Detect build tools from package dependencies and config files.
    Returns list of detected build tool names.
    """
    build_tools = []

    # Check from known build tool framework signatures
    for fw_name in _BUILD_TOOL_NAMES:
        sig = FRAMEWORK_SIGNATURES.get(fw_name, {})
        # Check package deps
        for pkg_name in sig.get("packages", []):
            if pkg_name in all_deps:
                build_tools.append(fw_name)
                _logger.debug("Detected build tool: %s (package: %s)", fw_name, pkg_name)
                break
        if fw_name in build_tools:
            continue
        # Check config files (root + subdirectories for monorepos)
        for cfg_file in sig.get("config_files", []):
            found = False
            # Root
            if os.path.exists(os.path.join(workspace, cfg_file)):
                build_tools.append(fw_name)
                _logger.debug("Detected build tool: %s (config: %s)", fw_name, cfg_file)
                break
            # Monorepo subdirectories
            for subdir in ('apps', 'packages', 'projects', 'services', 'libs'):
                subdir_path = os.path.join(workspace, subdir)
                if not os.path.isdir(subdir_path):
                    continue
                for root, dirs, files in os.walk(subdir_path):
                    rel = os.path.relpath(root, subdir_path)
                    if rel != '.' and rel.count(os.sep) >= 2:
                        dirs.clear()
                        continue
                    dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and d != 'node_modules']
                    if os.path.exists(os.path.join(root, cfg_file)):
                        build_tools.append(fw_name)
                        _logger.debug("Detected build tool: %s (config: %s in %s)", fw_name, cfg_file, root)
                        found = True
                        break
                if found:
                    break
            if found:
                break

    # Check for turbopack (via next.js config)
    if os.path.isfile(os.path.join(workspace, "next.config.js")) or \
       os.path.isfile(os.path.join(workspace, "next.config.mjs")) or \
       os.path.isfile(os.path.join(workspace, "next.config.ts")):
        # Turbopack is bundled with Next.js 13+, check for --turbo flag usage
        # It's hard to detect from files alone, but we note it as possible
        pass

    return build_tools


def _detect_test_frameworks(all_deps: Dict[str, str], workspace: str) -> List[str]:
    """
    Detect test frameworks from package dependencies and config files.
    Returns list of detected test framework names.
    """
    test_fws = []

    for fw_name in _TEST_FW_NAMES:
        sig = FRAMEWORK_SIGNATURES.get(fw_name, {})
        # Check package deps
        for pkg_name in sig.get("packages", []):
            if pkg_name in all_deps:
                test_fws.append(fw_name)
                _logger.debug("Detected test framework: %s (package: %s)", fw_name, pkg_name)
                break
        if fw_name in test_fws:
            continue
        # Check config files (root + subdirectories for monorepos)
        for cfg_file in sig.get("config_files", []):
            found = False
            if os.path.exists(os.path.join(workspace, cfg_file)):
                test_fws.append(fw_name)
                _logger.debug("Detected test framework: %s (config: %s)", fw_name, cfg_file)
                break
            for subdir in ('apps', 'packages', 'projects', 'services', 'libs'):
                subdir_path = os.path.join(workspace, subdir)
                if not os.path.isdir(subdir_path):
                    continue
                for root, dirs, files in os.walk(subdir_path):
                    rel = os.path.relpath(root, subdir_path)
                    if rel != '.' and rel.count(os.sep) >= 2:
                        dirs.clear()
                        continue
                    dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and d != 'node_modules']
                    if os.path.exists(os.path.join(root, cfg_file)):
                        test_fws.append(fw_name)
                        _logger.debug("Detected test framework: %s (config: %s in %s)", fw_name, cfg_file, root)
                        found = True
                        break
                if found:
                    break
            if found:
                break

    # Additional test frameworks without full signatures
    extra_test_sigs = {
        "mocha": (["mocha"], [".mocharc.yml", ".mocharc.json"]),
        "playwright": (["@playwright/test"], ["playwright.config.ts", "playwright.config.js"]),
        "cypress": (["cypress"], ["cypress.config.ts", "cypress.config.js"]),
    }
    for fw_name, (pkgs, cfgs) in extra_test_sigs.items():
        for pkg_name in pkgs:
            if pkg_name in all_deps:
                test_fws.append(fw_name)
                _logger.debug("Detected test framework: %s (package: %s)", fw_name, pkg_name)
                break
        if fw_name in test_fws:
            continue
        for cfg_file in cfgs:
            if os.path.exists(os.path.join(workspace, cfg_file)):
                test_fws.append(fw_name)
                _logger.debug("Detected test framework: %s (config: %s)", fw_name, cfg_file)
                break

    return test_fws


def detect_frameworks(workspace: str) -> Dict[str, Any]:
    """
    Detect frameworks used in a workspace.
    Returns dict with detected frameworks and their config.
    """
    workspace = os.path.abspath(workspace)
    detected = {
        "frameworks": [],
        # Frontend frameworks
        "has_react": False,
        "has_vue": False,
        "has_svelte": False,
        "has_tailwind": False,
        "has_nextjs": False,
        "has_angular": False,
        # Backend frameworks
        "has_express": False,
        "has_nestjs": False,
        "has_fastify": False,
        "has_koa": False,
        "has_hono": False,
        # Python frameworks
        "has_fastapi": False,
        "has_flask": False,
        "has_django": False,
        # Desktop frameworks
        "has_tauri": False,
        "has_electron": False,
        # Language presence
        "has_golang": False,
        "has_rust": False,
        # ORM / Database
        "has_typeorm": False,
        "has_mikro_orm": False,
        "has_prisma": False,
        "has_sequelize": False,
        "has_drizzle": False,
        # Test frameworks
        "has_jest": False,
        "has_vitest": False,
        # Build tools
        "has_vite": False,
        "has_webpack": False,
        "has_esbuild": False,
        # Job queue
        "has_bullmq": False,
        # Derived categories
        "orm_type": None,
        "build_tool": None,
        "test_framework": None,
        "backend_framework": None,
        # Monorepo
        "is_monorepo": False,
        "monorepo_tools": [],
        # Other
        "unsupported_langs": [],
        "css_preprocessor": None,
        "module_system": None,
    }

    # Helper to mark a framework detected and set has_* flags
    def _mark_detected(fw_name: str):
        if fw_name not in detected["frameworks"]:
            detected["frameworks"].append(fw_name)
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
            "nestjs": "has_nestjs",
            "fastify": "has_fastify",
            "koa": "has_koa",
            "hono": "has_hono",
            "fastapi": "has_fastapi",
            "flask": "has_flask",
            "django": "has_django",
            "typeorm": "has_typeorm",
            "mikro-orm": "has_mikro_orm",
            "prisma": "has_prisma",
            "sequelize": "has_sequelize",
            "drizzle": "has_drizzle",
            "jest": "has_jest",
            "vitest": "has_vitest",
            "vite": "has_vite",
            "webpack": "has_webpack",
            "esbuild": "has_esbuild",
            "bullmq": "has_bullmq",
        }
        flag = flag_map.get(fw_name)
        if flag:
            detected[flag] = True

    # ----------------------------------------------------------------
    # 1. Detect monorepo tools
    # ----------------------------------------------------------------
    mono_info = _detect_monorepo_tools(workspace)
    detected["is_monorepo"] = mono_info["is_monorepo"]
    detected["monorepo_tools"] = mono_info["monorepo_tools"]

    # ----------------------------------------------------------------
    # 2. Check package.json (root + monorepo sub-packages) for deps
    # ----------------------------------------------------------------
    all_deps = {}
    pkg_files = _find_package_jsons(workspace)

    # Track module system across all package.json files
    esm_count = 0
    cjs_count = 0

    for pkg_path in pkg_files:
        try:
            with open(pkg_path, 'r', encoding='utf-8') as f:
                pkg = json.load(f)
            all_deps.update(pkg.get("dependencies", {}))
            all_deps.update(pkg.get("devDependencies", {}))
            all_deps.update(pkg.get("peerDependencies", {}))

            # Detect module system from each package.json
            if "type" in pkg and pkg["type"] == "module":
                esm_count += 1
            else:
                cjs_count += 1
        except (json.JSONDecodeError, IOError):
            pass

    # Determine module system
    if esm_count > 0 and cjs_count <= 1:
        # Only root without "type": "module" or all have it
        detected["module_system"] = "esm"
    elif esm_count > 0 and cjs_count > 1:
        # Mix of ESM and CJS packages
        detected["module_system"] = "mixed"
    elif esm_count == 0 and cjs_count > 0:
        detected["module_system"] = "cjs"
    else:
        # No package.json found — try file-based heuristics
        has_mjs = False
        has_cjs_syntax = False
        has_esm_syntax = False
        for root, dirs, files in os.walk(workspace):
            # Skip ignored dirs
            skip = False
            for ignore in DEFAULT_IGNORE_DIRS:
                if ignore in root:
                    skip = True
                    break
            if skip or '.codelens' in root:
                continue
            for f in files:
                if f.endswith('.mjs'):
                    has_mjs = True
                    break
            if has_mjs:
                break

        # Check a sample of JS/TS files for import vs require
        sample_count = 0
        for root, dirs, files in os.walk(workspace):
            skip = False
            for ignore in DEFAULT_IGNORE_DIRS:
                if ignore in root:
                    skip = True
                    break
            if skip or '.codelens' in root:
                continue
            for f in files:
                if f.endswith(('.js', '.ts', '.mjs')) and not f.endswith('.d.ts'):
                    try:
                        with open(os.path.join(root, f), 'r', encoding='utf-8', errors='ignore') as fh:
                            content = fh.read(2048)
                            if re.search(r'\bimport\s+', content) or re.search(r'\bexport\s+', content):
                                has_esm_syntax = True
                            if re.search(r'\brequire\s*\(', content) or re.search(r'module\.exports\s*=', content):
                                has_cjs_syntax = True
                            sample_count += 1
                    except IOError:
                        pass
                    if sample_count >= 20:
                        break
            if sample_count >= 20:
                break

        if has_mjs or (has_esm_syntax and not has_cjs_syntax):
            detected["module_system"] = "esm"
        elif has_esm_syntax and has_cjs_syntax:
            detected["module_system"] = "mixed"
        else:
            detected["module_system"] = "cjs"

    _logger.debug("Module system detected: %s (esm_count=%d, cjs_count=%d)",
                  detected["module_system"], esm_count, cjs_count)

    # ----------------------------------------------------------------
    # 3. Match package dependencies against framework signatures
    # ----------------------------------------------------------------
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

    # ----------------------------------------------------------------
    # 4. Check config files (root + subdirectories for monorepos)
    # ----------------------------------------------------------------
    for fw_name, sig in FRAMEWORK_SIGNATURES.items():
        if fw_name in detected["frameworks"]:
            continue
        for cfg_file in sig.get("config_files", []):
            # Check root first
            if os.path.exists(os.path.join(workspace, cfg_file)):
                _mark_detected(fw_name)
                break
            # Check in monorepo subdirectories (recursively up to 3 levels)
            found_in_subdir = False
            for subdir in ('apps', 'packages', 'projects', 'services', 'libs', 'modules'):
                subdir_path = os.path.join(workspace, subdir)
                if not os.path.isdir(subdir_path):
                    continue
                for root, dirs, files in os.walk(subdir_path):
                    # Limit depth
                    rel = os.path.relpath(root, subdir_path)
                    if rel != '.' and rel.count(os.sep) >= 2:
                        dirs.clear()
                        continue
                    # Prune ignored dirs
                    dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and d != 'node_modules']
                    if os.path.exists(os.path.join(root, cfg_file)):
                        _mark_detected(fw_name)
                        found_in_subdir = True
                        break
                if found_in_subdir:
                    break
            if found_in_subdir:
                break

    # ----------------------------------------------------------------
    # 5. Check Python dependency files (requirements.txt, pyproject.toml, Pipfile)
    # ----------------------------------------------------------------
    pip_deps = set()

    # 5a. requirements.txt
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

    # 5b. pyproject.toml
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

    # 5c. Check pip deps against framework signatures
    for fw_name, sig in FRAMEWORK_SIGNATURES.items():
        if fw_name in detected["frameworks"]:
            continue
        pip_pkgs = sig.get("pip_packages", sig.get("packages", []))
        for pkg_name in pip_pkgs:
            if pkg_name.lower() in pip_deps:
                _mark_detected(fw_name)
                break

    # ----------------------------------------------------------------
    # 6. Check Rust/Cargo.toml for framework detection
    # ----------------------------------------------------------------
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

    # ----------------------------------------------------------------
    # 7. Check Tauri-specific config files (tauri.conf.json can be nested in src-tauri/)
    # ----------------------------------------------------------------
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

    # ----------------------------------------------------------------
    # 8. Check file patterns (for Vue, Svelte)
    # ----------------------------------------------------------------
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

    # ----------------------------------------------------------------
    # 8b. Check directory/file indicators (for Django, Flask, FastAPI source trees)
    # ----------------------------------------------------------------
    for fw_name, sig in FRAMEWORK_SIGNATURES.items():
        if fw_name in detected["frameworks"]:
            continue
        for indicator in sig.get("indicators", []):
            indicator_path = os.path.join(workspace, indicator)
            if os.path.exists(indicator_path):
                _mark_detected(fw_name)
                break

    # ----------------------------------------------------------------
    # 9. Detect Tailwind from CSS content
    # ----------------------------------------------------------------
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

    # ----------------------------------------------------------------
    # 10. Detect unsupported languages (Go, Java, C/C++, etc.)
    # ----------------------------------------------------------------
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

    # ----------------------------------------------------------------
    # 11. Detect build tools and test frameworks (dedicated functions)
    # ----------------------------------------------------------------
    detected["build_tools"] = _detect_build_tools(all_deps, workspace)
    detected["test_frameworks"] = _detect_test_frameworks(all_deps, workspace)

    # ----------------------------------------------------------------
    # 12. Set derived category fields
    # ----------------------------------------------------------------
    # orm_type: first detected ORM
    for orm in _ORM_NAMES:
        if detected.get(f"has_{orm.replace('-', '_')}"):
            detected["orm_type"] = orm
            break

    # build_tool: first detected build tool
    if detected.get("build_tools"):
        detected["build_tool"] = detected["build_tools"][0]

    # test_framework: first detected test framework
    if detected.get("test_frameworks"):
        detected["test_framework"] = detected["test_frameworks"][0]

    # backend_framework: first detected backend framework
    for fw in _BACKEND_FW_NAMES:
        flag = f"has_{fw}"
        if detected.get(flag):
            detected["backend_framework"] = fw
            break

    _logger.debug("Framework detection complete: %s", detected["frameworks"])
    _logger.debug("ORM: %s, Build: %s, Test: %s, Backend: %s",
                  detected["orm_type"], detected["build_tool"],
                  detected["test_framework"], detected["backend_framework"])
    _logger.debug("Monorepo: %s (%s)", detected["is_monorepo"], detected["monorepo_tools"])

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
        "tailwind_mode": False,
        "build_tools": fw.get("build_tools", []),
        "monorepo_tools": fw.get("monorepo_tools", []),
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

    # Backend framework path recommendations
    if fw.get("has_express"):
        config["backend_paths"].extend(["src/routes/", "src/middleware/", "routes/", "api/"])

    if fw.get("has_nestjs"):
        config["backend_paths"].extend(["src/modules/", "src/controllers/", "src/services/"])

    if fw.get("has_fastify"):
        config["backend_paths"].extend(["src/routes/", "src/plugins/"])

    # Monorepo path recommendations
    if fw.get("is_monorepo"):
        config["frontend_paths"].extend(["apps/web/", "apps/frontend/", "packages/frontend/"])
        config["backend_paths"].extend(["apps/api/", "apps/backend/", "packages/api/", "packages/backend/"])
        # Add workspace directories as backend paths
        for workspace_dir in ('packages', 'apps', 'services', 'modules', 'libs'):
            workspace_path = os.path.join(workspace, workspace_dir)
            if os.path.isdir(workspace_path):
                try:
                    for entry in os.listdir(workspace_path):
                        entry_path = os.path.join(workspace_path, entry)
                        if os.path.isdir(entry_path):
                            rel = os.path.relpath(entry_path, workspace)
                            config["backend_paths"].append(rel + "/src/")
                            config["backend_paths"].append(rel + "/")
                except OSError:
                    pass

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
