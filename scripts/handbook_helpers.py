"""Project identity helper (issue #195 consolidation).

Extracted from the deprecated ``commands/handbook.py`` module so that
``summary`` and ``analyze`` can keep using :func:`_extract_project_identity`
after ``handbook`` is dropped as a standalone command.
"""

import os
import json
import re
from typing import Dict, Any, List, Optional

from utils import DEFAULT_IGNORE_DIRS


def _extract_project_identity(workspace: str) -> Dict[str, Any]:
    """Extract project identity from package.json, pyproject.toml, or README.

    v6: Removed unknown-type guard on Cargo.toml, added combined/polyglot type
    detection, sub-directory package.json scanning, and monorepo-specific types.
    """
    identity = {
        "name": os.path.basename(workspace),
        "description": "",
        "version": "0.0.0",
        "type": "unknown",
        "languages": [],
        "frameworks": [],
        # v6: monorepo & sub-dir info
        "is_monorepo": False,
        "monorepo_tools": [],
        "subdir_frameworks": {},
    }

    has_package_json = False
    has_cargo_toml = False
    has_pyproject = False
    js_type = None  # v6: track JS-derived type separately for polyglot detection
    python_type = None  # v6: track Python-derived type separately
    rust_type = None  # v6: track Rust-derived type separately
    elixir_type = None  # v6.5: track Elixir-derived type separately
    detected_languages = []  # v6.5: track all detected languages

    # v6: Check monorepo indicators first
    _MONOREPO_INDICATORS = {
        "turbo.json": "turborepo",
        "pnpm-workspace.yaml": "pnpm-workspace",
        "lerna.json": "lerna",
        "nx.json": "nx",
    }
    for indicator_file, tool_name in _MONOREPO_INDICATORS.items():
        if os.path.isfile(os.path.join(workspace, indicator_file)):
            identity["is_monorepo"] = True
            if tool_name not in identity["monorepo_tools"]:
                identity["monorepo_tools"].append(tool_name)

    # v5.8: Check for Rust/Cargo workspace monorepo
    cargo_toml_path = os.path.join(workspace, 'Cargo.toml')
    if os.path.isfile(cargo_toml_path):
        try:
            with open(cargo_toml_path, 'r', encoding='utf-8') as f:
                cargo_content = f.read()
            # Check for [workspace] section with members
            if '[workspace]' in cargo_content:
                identity["is_monorepo"] = True
                if "cargo-workspace" not in identity["monorepo_tools"]:
                    identity["monorepo_tools"].append("cargo-workspace")
        except Exception:
            pass

    # v5.8: Check for crates/ or ext/ directories with Cargo.toml (Rust monorepo pattern)
    for crate_dir_name in ('crates', 'ext'):
        crate_dir = os.path.join(workspace, crate_dir_name)
        if os.path.isdir(crate_dir):
            sub_crates = 0
            try:
                for entry in os.listdir(crate_dir):
                    sub_cargo = os.path.join(crate_dir, entry, 'Cargo.toml')
                    if os.path.isfile(sub_cargo):
                        sub_crates += 1
            except OSError:
                pass
            if sub_crates >= 2:
                identity["is_monorepo"] = True
                if "cargo-workspace" not in identity["monorepo_tools"]:
                    identity["monorepo_tools"].append("cargo-workspace")

    # Try package.json
    pkg_path = os.path.join(workspace, 'package.json')
    if os.path.isfile(pkg_path):
        has_package_json = True
        try:
            with open(pkg_path, 'r', encoding='utf-8') as f:
                pkg = json.load(f)
            identity["name"] = pkg.get("name", identity["name"])
            identity["version"] = pkg.get("version", identity["version"])
            identity["description"] = pkg.get("description", "")
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            # v6.1: Detect library vs application from package.json fields
            # Libraries have: main, module, types, files, sideEffects
            # and typically no "scripts.start" or "scripts.dev"
            is_library = (
                "main" in pkg or "module" in pkg or "exports" in pkg
            ) and (
                "files" in pkg or "sideEffects" in pkg
                or "typings" in pkg or "types" in pkg
            )
            # Also check: if there's no "start" or "dev" script, it's likely a library
            scripts = pkg.get("scripts", {})
            # v6.1: Consider script purpose — "start": "yarn storybook" is NOT an app script
            start_script = scripts.get("start", "")
            has_app_script = (
                ("start" in scripts and "storybook" not in start_script.lower())
                or "dev" in scripts
                or "serve" in scripts
            )

            if "next" in deps:
                js_type = "fullstack-web-app"
            elif "express" in deps or "fastify" in deps or "koa" in deps:
                js_type = "backend-api"
            elif is_library and not has_app_script:
                js_type = "frontend-library"
            elif "react" in deps or "vue" in deps or "svelte" in deps:
                js_type = "frontend-app"
            else:
                js_type = "node-project"
        except Exception:
            logger.warning("package.json parsing failed", exc_info=True)

    # v6: Walk sub-directories for nested package.json (apps/*, packages/*)
    _MONOREPO_SUBDIRS = ["apps", "packages", "services"]
    _monorepo_subdir_count = 0  # track how many sub-packages found
    for subdir in _MONOREPO_SUBDIRS:
        subdir_path = os.path.join(workspace, subdir)
        if not os.path.isdir(subdir_path):
            continue
        try:
            for entry in sorted(os.listdir(subdir_path)):
                entry_pkg = os.path.join(subdir_path, entry, "package.json")
                if not os.path.isfile(entry_pkg):
                    continue
                _monorepo_subdir_count += 1
                try:
                    with open(entry_pkg, 'r', encoding='utf-8') as f:
                        pkg = json.load(f)
                    sub_deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                    rel_subdir = os.path.join(subdir, entry)
                    subdir_fws = []
                    # v6: Detect frameworks from sub-directory deps
                    if "next" in sub_deps:
                        subdir_fws.append("next.js")
                        if js_type is None:
                            js_type = "fullstack-web-app"
                    if "react" in sub_deps:
                        subdir_fws.append("react")
                        if js_type is None:
                            js_type = "frontend-app"
                    if "vue" in sub_deps:
                        subdir_fws.append("vue")
                        if js_type is None:
                            js_type = "frontend-app"
                    if "svelte" in sub_deps:
                        subdir_fws.append("svelte")
                        if js_type is None:
                            js_type = "frontend-app"
                    if "express" in sub_deps or "fastify" in sub_deps:
                        subdir_fws.append("express")
                        if js_type is None:
                            js_type = "backend-api"
                    if subdir_fws:
                        identity["subdir_frameworks"][rel_subdir] = subdir_fws
                except Exception:
                    pass
        except OSError:
            pass

    # v6.3: If we found 2+ sub-packages in apps/packages/services, mark as monorepo
    if _monorepo_subdir_count >= 2 and not identity["is_monorepo"]:
        identity["is_monorepo"] = True
        if "yarn-workspace" not in identity["monorepo_tools"]:
            identity["monorepo_tools"].append("yarn-workspace")

    # v6.3: Also check root package.json for "workspaces" field (npm/yarn workspaces)
    if has_package_json and not identity["is_monorepo"]:
        try:
            with open(pkg_path, 'r', encoding='utf-8') as f:
                pkg = json.load(f)
            workspaces = pkg.get("workspaces")
            if workspaces:
                identity["is_monorepo"] = True
                if "npm-workspaces" not in identity["monorepo_tools"]:
                    identity["monorepo_tools"].append("npm-workspaces")
        except Exception:
            pass

    # Try pyproject.toml
    pyproject_path = os.path.join(workspace, 'pyproject.toml')
    if os.path.isfile(pyproject_path):
        has_pyproject = True
        try:
            with open(pyproject_path, 'r', encoding='utf-8') as f:
                content = f.read()
            name_match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
            ver_match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
            if name_match:
                identity["name"] = name_match.group(1)
            if ver_match:
                identity["version"] = ver_match.group(1)
            if "fastapi" in content or "flask" in content or "django" in content:
                python_type = "backend-api"
            elif "pytest" in content:
                python_type = "python-library"
            else:
                python_type = "python-project"
        except Exception:
            logger.warning("pyproject.toml parsing failed", exc_info=True)

    # v6: Try Cargo.toml — always check (removed identity["type"] == "unknown" guard)
    cargo_path = os.path.join(workspace, 'Cargo.toml')
    if os.path.isfile(cargo_path):
        has_cargo_toml = True
        try:
            with open(cargo_path, 'r', encoding='utf-8') as f:
                content = f.read()
            name_match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
            ver_match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
            if name_match:
                identity["name"] = name_match.group(1)
            if ver_match:
                identity["version"] = ver_match.group(1)
            rust_type = "rust-project"
        except Exception:
            logger.warning("Cargo.toml parsing failed", exc_info=True)

    # v5.8.1: Try go.mod — detect Go projects
    go_type = None
    go_mod_path = os.path.join(workspace, 'go.mod')
    if os.path.isfile(go_mod_path):
        try:
            with open(go_mod_path, 'r', encoding='utf-8') as f:
                go_mod_content = f.read()
            # Extract module name and Go version
            module_match = re.search(r'^module\s+(\S+)', go_mod_content, re.MULTILINE)
            go_ver_match = re.search(r'^go\s+(\S+)', go_mod_content, re.MULTILINE)
            if module_match:
                mod_name = module_match.group(1)
                # Use last segment of module path as project name
                identity["name"] = mod_name.split('/')[-1]
            if go_ver_match:
                identity["version"] = go_ver_match.group(1)
            # Classify Go project type based on dependencies and module name
            mod_name_lower = mod_name.lower() if module_match else ""
            # v6.5: Extract direct deps (exclude // indirect) for more accurate classification
            direct_deps_lines = []
            in_require = False
            for line in go_mod_content.splitlines():
                stripped = line.strip()
                if stripped.startswith('require ('):
                    in_require = True
                    continue
                if in_require:
                    if stripped == ')':
                        in_require = False
                        continue
                    if '//' in stripped and 'indirect' in stripped:
                        continue
                    direct_deps_lines.append(stripped)
                elif stripped.startswith('require '):
                    # Single-line require: require "pkg" v1.0
                    if '//' in stripped and 'indirect' in stripped:
                        continue
                    direct_deps_lines.append(stripped)
            direct_deps_str = ' '.join(direct_deps_lines)

            # v6.5: Check for well-known Go project types by module name first
            if any(kw in mod_name_lower for kw in ('hugo', 'jekyll', 'gatsby', 'zola', 'hugoio')):
                go_type = "go-static-site-generator"
            elif any(kw in mod_name_lower for kw in ('cockroachdb', 'postgres', 'mysql', 'sqlite', 'mongodb', 'redis', 'etcd', 'database', 'db/')):
                go_type = "go-database"
            elif 'database/sql' in direct_deps_str:
                go_type = "go-database"
            elif 'gin-gonic' in go_mod_content or 'labstack/echo' in go_mod_content or 'gofiber/fiber' in go_mod_content:
                go_type = "go-web-service"
            elif any(kw in mod_name_lower for kw in ('cobra', 'urfave/cli', 'alecthomas/kong')) or 'spf13/cobra' in go_mod_content or 'urfave/cli' in go_mod_content:
                go_type = "go-cli-tool"
            elif 'k8s.io/' in go_mod_content or 'kubernetes' in go_mod_content:
                go_type = "go-infrastructure"
            elif 'google.golang.org/grpc' in direct_deps_str:
                go_type = "go-grpc-service"
            elif 'net/http' in go_mod_content:
                go_type = "go-web-service"
            else:
                go_type = "go-project"
        except Exception:
            logger.warning("go.mod parsing failed", exc_info=True)

    # v6.4: Detect PHP projects via composer.json
    php_type = None
    composer_path = os.path.join(workspace, 'composer.json')
    if os.path.isfile(composer_path):
        try:
            with open(composer_path, 'r', encoding='utf-8') as f:
                composer_data = json.load(f)
            php_name = composer_data.get('name', '')
            if php_name:
                identity["name"] = php_name.split('/')[-1]
            php_version = composer_data.get('version', '')
            if php_version:
                identity["version"] = php_version
            # Detect PHP framework from require dependencies
            php_req = composer_data.get('require', {})
            php_req_str = ' '.join(php_req.keys()).lower()
            if 'laravel/framework' in php_req or 'laravel/laravel' in php_req:
                php_type = "laravel-app"
            elif 'symfony/symfony' in php_req or 'symfony/framework-bundle' in php_req:
                php_type = "symfony-app"
            elif 'slim/slim' in php_req:
                php_type = "slim-app"
            elif 'laravel/lumen' in php_req:
                php_type = "lumen-app"
            elif 'cakephp/cakephp' in php_req:
                php_type = "cakephp-app"
            elif 'drupal/core' in php_req or 'drupal/drupal' in php_req:
                php_type = "drupal-app"
            elif 'wordpress' in php_req_str or os.path.isfile(os.path.join(workspace, 'wp-config.php')):
                php_type = "wordpress-app"
            else:
                php_type = "php-project"
        except Exception:
            logger.warning("composer.json parsing failed", exc_info=True)

    # v6.4: Detect C/C++ projects
    c_cpp_type = None
    cmake_path = os.path.join(workspace, 'CMakeLists.txt')
    makefile_path = os.path.join(workspace, 'Makefile')
    gnu_makefile_path = os.path.join(workspace, 'GNUmakefile')
    configure_ac_path = os.path.join(workspace, 'configure.ac')

    # Check for CMake project
    if os.path.isfile(cmake_path):
        try:
            with open(cmake_path, 'r', encoding='utf-8') as f:
                cmake_content = f.read()
            # Extract project name and version from cmake
            proj_match = re.search(r'project\s*\(\s*(\w+)', cmake_content)
            ver_match = re.search(r'project\s*\(\s*\w+\s+VERSION\s+(\S+)', cmake_content)
            if proj_match:
                identity["name"] = proj_match.group(1)
            if ver_match:
                identity["version"] = ver_match.group(1)
            c_cpp_type = "cmake-project"
        except Exception:
            pass

    # Check for autotools/autoconf project (nginx-style)
    if not c_cpp_type and os.path.isfile(configure_ac_path):
        try:
            with open(configure_ac_path, 'r', encoding='utf-8') as f:
                configure_content = f.read()
            # Extract project name from AC_INIT
            ac_init = re.search(r'AC_INIT\s*\(\s*\[?(\w+)', configure_content)
            ver_init = re.search(r'AC_INIT\s*\(\s*\[?\w+\]?\s*,\s*\[?(\S+?)\]?\s*[,)]', configure_content)
            if ac_init:
                identity["name"] = ac_init.group(1)
            if ver_init:
                identity["version"] = ver_init.group(1)
            # v6.5: Determine if C or C++ based on source files
            c_only_count = 0
            cpp_count = 0
            for root, dirs, walk_files in os.walk(workspace):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in DEFAULT_IGNORE_DIRS]
                for wf in walk_files:
                    if wf.endswith(('.c', '.h')):
                        c_only_count += 1
                    elif wf.endswith(('.cpp', '.cc', '.cxx', '.hpp')):
                        cpp_count += 1
            # Check configure.ac for project description clues
            configure_lower = configure_content.lower()
            if cpp_count > 0:
                c_cpp_type = "cpp-project"
            elif c_only_count > 0:
                c_cpp_type = "c-project"
            else:
                c_cpp_type = "c-project"
        except Exception:
            pass

    # Check for Makefile-based C/C++ project
    if not c_cpp_type and (os.path.isfile(makefile_path) or os.path.isfile(gnu_makefile_path)):
        # Heuristic: if there are .c/.cpp files and a Makefile, it's a C/C++ project
        c_files = 0
        for root, dirs, files in os.walk(workspace):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in DEFAULT_IGNORE_DIRS]
            for f in files:
                if f.endswith(('.c', '.cpp', '.cc', '.cxx', '.h', '.hpp')):
                    c_files += 1
                    if c_files >= 3:
                        break
            if c_files >= 3:
                break
        if c_files >= 3:
            # v6.5: Distinguish C from C++
            _c_cnt = sum(1 for root, dirs, fns in os.walk(workspace)
                        for fn in fns if fn.endswith(('.c', '.h')))
            _cpp_cnt = sum(1 for root, dirs, fns in os.walk(workspace)
                          for fn in fns if fn.endswith(('.cpp', '.cc', '.cxx', '.hpp')))
            if _cpp_cnt > 0:
                c_cpp_type = "cpp-project"
            else:
                c_cpp_type = "c-project"

    # Check for C/C++ project with many source files but no build system file
    if not c_cpp_type:
        c_file_count = 0
        for root, dirs, files in os.walk(workspace):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in DEFAULT_IGNORE_DIRS]
            for f in files:
                if f.endswith(('.c', '.cpp', '.cc', '.cxx', '.h', '.hpp')):
                    c_file_count += 1
        if c_file_count >= 10:
            # v6.5: Distinguish C from C++
            _c_cnt2 = sum(1 for root, dirs, fns in os.walk(workspace)
                         for fn in fns if fn.endswith(('.c', '.h')))
            _cpp_cnt2 = sum(1 for root, dirs, fns in os.walk(workspace)
                           for fn in fns if fn.endswith(('.cpp', '.cc', '.cxx', '.hpp')))
            if _cpp_cnt2 > 0:
                c_cpp_type = "cpp-project"
            else:
                c_cpp_type = "c-project"

    # v6.4: Detect Lua projects
    lua_type = None
    rockspec_files = [f for f in os.listdir(workspace) if f.endswith('.rockspec')] if os.path.isdir(workspace) else []
    if rockspec_files:
        lua_type = "lua-rockspec-project"
    elif os.path.isfile(os.path.join(workspace, 'init.lua')):
        # Check if it's a Neovim plugin (has lua/ directory with init.lua at root)
        lua_dir = os.path.join(workspace, 'lua')
        if os.path.isdir(lua_dir):
            lua_type = "neovim-plugin"
        else:
            lua_type = "lua-project"

    # v6.5: Detect Elixir projects via mix.exs
    mix_exs_path = os.path.join(workspace, 'mix.exs')
    if os.path.isfile(mix_exs_path):
        try:
            with open(mix_exs_path, 'r', encoding='utf-8') as f:
                mix_content = f.read()
            # Extract project name from defmodule or app:
            app_match = re.search(r'app:\s*:(\w+)', mix_content)
            if app_match:
                identity["name"] = app_match.group(1)
            # Extract version
            ver_match = re.search(r'@version\s+["\']([^"\']+)["\']', mix_content)
            if ver_match:
                identity["version"] = ver_match.group(1)
            else:
                ver_match2 = re.search(r'version:\s*["\']([^"\']+)["\']', mix_content)
                if ver_match2:
                    identity["version"] = ver_match2.group(1)
            # Detect Elixir framework from deps
            mix_lower = mix_content.lower()
            if 'phoenix' in mix_content:
                elixir_type = "phoenix-web-framework"
                identity["frameworks"].append("phoenix")
                if 'ecto' in mix_content:
                    identity["frameworks"].append("ecto")
                if 'plug' in mix_content:
                    identity["frameworks"].append("plug")
                if 'live_view' in mix_content or 'phoenix_live_view' in mix_content:
                    identity["frameworks"].append("phoenix-live-view")
            elif 'ecto' in mix_content:
                elixir_type = "elixir-data-app"
                identity["frameworks"].append("ecto")
            elif 'nerves' in mix_content:
                elixir_type = "nerves-embedded-app"
                identity["frameworks"].append("nerves")
            elif 'oban' in mix_content:
                elixir_type = "elixir-background-job-app"
                identity["frameworks"].append("oban")
            else:
                elixir_type = "elixir-project"
        except Exception:
            logger.warning("mix.exs parsing failed", exc_info=True)

    # v6.5: Also detect Ruby projects via Gemfile
    ruby_type = None
    gemfile_path = os.path.join(workspace, 'Gemfile')
    if os.path.isfile(gemfile_path):
        try:
            with open(gemfile_path, 'r', encoding='utf-8') as f:
                gemfile_content = f.read()
            if 'rails' in gemfile_content:
                ruby_type = "rails-app"
                identity["frameworks"].append("rails")
            elif 'sinatra' in gemfile_content:
                ruby_type = "sinatra-app"
                identity["frameworks"].append("sinatra")
            else:
                ruby_type = "ruby-project"
        except Exception:
            logger.warning("Gemfile parsing failed", exc_info=True)

    # v6.5: Combined type detection — handle polyglot projects with primary-language awareness
    active_types = [t for t in [js_type, python_type, rust_type, go_type, php_type, c_cpp_type, lua_type, elixir_type, ruby_type] if t is not None]

    # v6.5: Determine "specific" types (framework-level like phoenix-web-framework, laravel-app)
    # vs "generic" types (like elixir-project, php-project, node-project).
    # Specific types should take priority over polyglot combination.
    _SPECIFIC_TYPES = {
        'phoenix-web-framework', 'elixir-data-app', 'nerves-embedded-app', 'elixir-background-job-app',
        'laravel-app', 'symfony-app', 'slim-app', 'lumen-app', 'cakephp-app', 'drupal-app', 'wordpress-app',
        'rails-app', 'sinatra-app',
        'go-static-site-generator', 'go-web-service', 'go-grpc-service', 'go-cli-tool', 'go-database', 'go-infrastructure',
        'fullstack-web-app', 'backend-api', 'frontend-app', 'frontend-library',
    }

    if len(active_types) >= 2:
        # v6.5: If there's a specific framework type, use it as the primary type
        # and note the secondary language in the type string
        specific_type = None
        for t in [elixir_type, ruby_type, go_type, php_type, python_type, rust_type, js_type, c_cpp_type, lua_type]:
            if t and t in _SPECIFIC_TYPES:
                specific_type = t
                break
        if specific_type:
            identity["type"] = specific_type
        else:
            # Polyglot project — build a combined type string
            type_parts = []
            if rust_type:
                type_parts.append("rust")
            if go_type:
                type_parts.append("go")
            if js_type:
                type_parts.append("typescript" if "typescript" in (js_type or "") else "js")
            if python_type:
                type_parts.append("python")
            if php_type:
                type_parts.append("php")
            if c_cpp_type:
                type_parts.append("c-cpp")
            if lua_type:
                type_parts.append("lua")
            if elixir_type:
                type_parts.append("elixir")
            if ruby_type:
                type_parts.append("ruby")
            identity["type"] = "-".join(type_parts) + "-monorepo" if identity["is_monorepo"] else "-".join(type_parts) + "-polyglot"
    elif len(active_types) == 1:
        identity["type"] = active_types[0]
        # v6: If monorepo indicators found, append -monorepo suffix
        if identity["is_monorepo"]:
            identity["type"] = active_types[0] + "-monorepo"
    # If no type detected, remains "unknown"

    # v6: When frameworks are found in subdirectory package.json files,
    #     update the identity type if it's still generic
    if identity["subdir_frameworks"] and identity["type"] in ("node-project", "unknown"):
        all_fws = set()
        for fws in identity["subdir_frameworks"].values():
            all_fws.update(fws)
        if "next.js" in all_fws:
            identity["type"] = "fullstack-web-app"
        elif "react" in all_fws or "vue" in all_fws or "svelte" in all_fws:
            identity["type"] = "frontend-app"
        if identity["is_monorepo"] and not identity["type"].endswith("-monorepo"):
            identity["type"] += "-monorepo"

    # v6.5: Build languages list from detected types
    if go_type is not None and 'go' not in detected_languages:
        detected_languages.append('go')
    if rust_type is not None and 'rust' not in detected_languages:
        detected_languages.append('rust')
    if python_type is not None and 'python' not in detected_languages:
        detected_languages.append('python')
    if php_type is not None and 'php' not in detected_languages:
        detected_languages.append('php')
    if lua_type is not None and 'lua' not in detected_languages:
        detected_languages.append('lua')
    if elixir_type is not None and 'elixir' not in detected_languages:
        detected_languages.append('elixir')
    if ruby_type is not None and 'ruby' not in detected_languages:
        detected_languages.append('ruby')

    # C/C++ language detection — distinguish C from C++
    if c_cpp_type is not None:
        c_count = 0
        cpp_count = 0
        for root, dirs, walk_files in os.walk(workspace):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in DEFAULT_IGNORE_DIRS]
            for wf in walk_files:
                if wf.endswith(('.c', '.h')):
                    c_count += 1
                elif wf.endswith(('.cpp', '.cc', '.cxx', '.hpp')):
                    cpp_count += 1
        if cpp_count > 0 and 'c++' not in detected_languages:
            detected_languages.append('c++')
        if c_count > 0 and 'c' not in detected_languages:
            detected_languages.append('c')
        # If only headers and no .c or .cpp files, add both
        if c_count == 0 and cpp_count == 0 and 'c' not in detected_languages:
            detected_languages.append('c')

    # JS/TS language detection
    if has_package_json:
        # Check for TypeScript
        tsconfig_path = os.path.join(workspace, 'tsconfig.json')
        has_ts_files = False
        for root, dirs, walk_files in os.walk(workspace):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in DEFAULT_IGNORE_DIRS]
            for wf in walk_files:
                if wf.endswith(('.ts', '.tsx')):
                    has_ts_files = True
                    break
            if has_ts_files:
                break
        if os.path.isfile(tsconfig_path) or has_ts_files:
            if 'typescript' not in detected_languages:
                detected_languages.append('typescript')
        if 'javascript' not in detected_languages:
            detected_languages.append('javascript')

    # v6.5: Quick file-extension scan for languages not detected by config files
    _LANG_EXTENSIONS = {
        '.ex': 'elixir', '.exs': 'elixir',
        '.erl': 'erlang',
        '.swift': 'swift',
        '.kt': 'kotlin', '.kts': 'kotlin',
        '.scala': 'scala',
        '.java': 'java',
        '.dart': 'dart',
        '.cs': 'c#',
        '.rb': 'ruby',
        '.rs': 'rust',
        '.go': 'go',
        '.py': 'python',
        '.lua': 'lua',
        '.php': 'php',
        '.sh': 'shell', '.bash': 'shell', '.zsh': 'shell',
        '.r': 'r', '.R': 'r',
        '.m': 'objective-c',
        '.zig': 'zig',
        '.nim': 'nim',
        '.gd': 'gdscript',
    }
    _ext_lang_count = {}
    for root, dirs, walk_files in os.walk(workspace):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in DEFAULT_IGNORE_DIRS]
        for wf in walk_files:
            ext = os.path.splitext(wf)[1].lower()
            lang = _LANG_EXTENSIONS.get(ext)
            if lang:
                _ext_lang_count[lang] = _ext_lang_count.get(lang, 0) + 1
    # Add languages with 5+ files that weren't already detected
    for lang, count in sorted(_ext_lang_count.items(), key=lambda x: -x[1]):
        if count >= 5 and lang not in detected_languages:
            detected_languages.append(lang)
        # Also add secondary languages with 2+ files if they're not already there
        elif count >= 2 and lang not in detected_languages and len(detected_languages) < 6:
            detected_languages.append(lang)

    identity["languages"] = detected_languages

    # v6.5: Add framework info from detected types
    if go_type == "go-static-site-generator" and "hugo" not in identity["frameworks"]:
        identity["frameworks"].append("hugo")
    if go_type == "go-web-service" and os.path.isfile(go_mod_path):
        try:
            go_mod_check = go_mod_content  # already loaded above
            if 'gin-gonic' in go_mod_check:
                identity["frameworks"].append("gin")
            elif 'labstack/echo' in go_mod_check:
                identity["frameworks"].append("echo")
            elif 'gofiber/fiber' in go_mod_check:
                identity["frameworks"].append("fiber")
        except Exception:
            pass
    if go_type == "go-cli-tool" and "cobra" not in identity["frameworks"]:
        identity["frameworks"].append("cobra")
    if php_type and php_type != "php-project":
        fw_name = php_type.replace('-app', '')
        if fw_name not in identity["frameworks"]:
            identity["frameworks"].append(fw_name)

    # Deduplicate frameworks
    identity["frameworks"] = list(dict.fromkeys(identity["frameworks"]))

    return identity


