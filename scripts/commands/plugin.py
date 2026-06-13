"""Plugin command — Manage CodeLens plugins (install, list, search, etc.)."""

import os
import sys
import json
from typing import Dict, Any, Optional

from utils import logger
from commands import register_command


def add_args(parser):
    """Add plugin-specific arguments to the parser."""
    subparsers = parser.add_subparsers(dest="plugin_action", help="Plugin actions")

    # plugin list
    list_parser = subparsers.add_parser("list", help="List installed plugins")
    list_parser.add_argument("--type", choices=["rule_pack", "engine", "formatter", "command"],
                             default=None, help="Filter by plugin type")
    list_parser.add_argument("--tags", nargs="*", default=None,
                             help="Filter by tags (match any)")
    list_parser.add_argument("--verbose", "-v", action="store_true", default=False,
                             help="Show detailed plugin info")

    # plugin install
    install_parser = subparsers.add_parser("install", help="Install a plugin")
    install_parser.add_argument("source", help="Plugin source: URL, local path, or registry name")
    install_parser.add_argument("--target", choices=["local", "user"], default="user",
                                help="Install target: 'local' (workspace) or 'user' (home dir)")
    install_parser.add_argument("--force", action="store_true", default=False,
                                help="Force reinstall even if already installed")

    # plugin uninstall
    uninstall_parser = subparsers.add_parser("uninstall", help="Uninstall a plugin")
    uninstall_parser.add_argument("name", help="Plugin name to uninstall")
    uninstall_parser.add_argument("--force", action="store_true", default=False,
                                  help="Skip confirmation")

    # plugin search
    search_parser = subparsers.add_parser("search", help="Search available plugins")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--type", choices=["rule_pack", "engine", "formatter", "command"],
                               default=None, help="Filter by plugin type")

    # plugin update
    update_parser = subparsers.add_parser("update", help="Update plugin(s)")
    update_parser.add_argument("name", nargs="?", default=None,
                               help="Plugin name to update (updates all if omitted)")

    # plugin info
    info_parser = subparsers.add_parser("info", help="Show plugin details")
    info_parser.add_argument("name", help="Plugin name")

    # plugin validate
    validate_parser = subparsers.add_parser("validate", help="Validate a plugin manifest")
    validate_parser.add_argument("path", help="Path to plugin directory to validate")


def execute(args, workspace):
    """Execute the plugin command."""
    action = getattr(args, "plugin_action", None)
    if not action:
        return {
            "status": "error",
            "error": "No plugin action specified. Use: list, install, uninstall, search, update, info, validate",
            "usage": "codelens plugin <action> [options]",
        }

    # Lazy import to avoid circular dependencies
    from plugin_system import get_plugin_manager, validate_manifest

    mgr = get_plugin_manager(workspace)

    if action == "list":
        return _cmd_list(mgr, args)
    elif action == "install":
        return _cmd_install(mgr, args, workspace)
    elif action == "uninstall":
        return _cmd_uninstall(mgr, args)
    elif action == "search":
        return _cmd_search(mgr, args)
    elif action == "update":
        return _cmd_update(mgr, args)
    elif action == "info":
        return _cmd_info(mgr, args)
    elif action == "validate":
        return _cmd_validate(args)
    else:
        return {
            "status": "error",
            "error": f"Unknown plugin action: {action}",
            "available_actions": ["list", "install", "uninstall", "search", "update", "info", "validate"],
        }


def _cmd_list(mgr, args) -> Dict[str, Any]:
    """Handle 'plugin list' command."""
    plugins = mgr.list_plugins()

    # Filter by type
    filter_type = getattr(args, "type", None)
    if filter_type:
        plugins = [p for p in plugins if p["type"] == filter_type]

    # Filter by tags
    filter_tags = getattr(args, "tags", None)
    if filter_tags:
        tag_set = set(filter_tags)
        plugins = [p for p in plugins if tag_set.intersection(set(p.get("tags", [])))]

    verbose = getattr(args, "verbose", False)

    result_plugins = []
    for p in plugins:
        if verbose:
            result_plugins.append(p)
        else:
            # Compact view
            result_plugins.append({
                "name": p["name"],
                "version": p["version"],
                "type": p["type"],
                "description": p["description"],
                "source": p.get("source_type", "builtin"),
            })

    return {
        "status": "ok",
        "total": len(result_plugins),
        "plugins": result_plugins,
    }


def _cmd_install(mgr, args, workspace) -> Dict[str, Any]:
    """Handle 'plugin install' command."""
    source = args.source
    target = args.target
    force = getattr(args, "force", False)

    # Check if already installed (unless --force)
    if not force:
        plugins = mgr.list_plugins()
        plugin_name = _extract_plugin_name_from_source(source)
        if plugin_name:
            existing = [p for p in plugins if p["name"] == plugin_name]
            if existing:
                return {
                    "status": "already_installed",
                    "name": plugin_name,
                    "version": existing[0]["version"],
                    "message": f"Plugin '{plugin_name}' is already installed. Use --force to reinstall.",
                }

    result = mgr.install_plugin(source, target)

    # Add helpful context
    if result.get("status") == "ok":
        result["message"] = (
            f"Plugin '{result.get('name')}' v{result.get('version')} installed successfully. "
            f"Run 'codelens plugin list' to see all installed plugins."
        )
    elif result.get("status") == "error":
        # Check if it's a registry request and add helpful hint
        if "registry" in result.get("error", "").lower():
            result["hint"] = (
                "The CodeLens plugin registry is coming soon! "
                "For now, install from a URL or local path:\n"
                "  codelens plugin install https://github.com/user/plugin/archive/main.zip\n"
                "  codelens plugin install ./my-plugin/"
            )

    return result


def _cmd_uninstall(mgr, args) -> Dict[str, Any]:
    """Handle 'plugin uninstall' command."""
    name = args.name

    result = mgr.uninstall_plugin(name)

    if result.get("status") == "ok":
        result["message"] = f"Plugin '{name}' has been uninstalled."
    elif result.get("status") == "error" and "Cannot uninstall built-in" in result.get("error", ""):
        result["hint"] = "Built-in plugins ship with CodeLens. To disable them, remove or rename the plugin directory."

    return result


def _cmd_search(mgr, args) -> Dict[str, Any]:
    """Handle 'plugin search' command."""
    query = args.query
    filter_type = getattr(args, "type", None)

    results = mgr.search_plugins(query)

    # Filter by type
    if filter_type:
        results = [r for r in results if r["type"] == filter_type]

    if not results:
        return {
            "status": "ok",
            "query": query,
            "total": 0,
            "results": [],
            "message": f"No plugins found matching '{query}'. Try a different query or browse the registry at https://registry.codelens.dev",
        }

    # Clean up for display
    display_results = []
    for r in results:
        display_results.append({
            "name": r["name"],
            "version": r["version"],
            "type": r["type"],
            "description": r["description"],
            "tags": r.get("tags", []),
            "source": r.get("source_type", "builtin"),
            "search_score": r.get("search_score", 0),
        })

    return {
        "status": "ok",
        "query": query,
        "total": len(display_results),
        "results": display_results,
    }


def _cmd_update(mgr, args) -> Dict[str, Any]:
    """Handle 'plugin update' command."""
    name = getattr(args, "name", None)

    if name:
        result = mgr.update_plugin(name)
        return result
    else:
        results = mgr.update_all_plugins()
        return {
            "status": "ok",
            "updates": results,
            "total": len(results),
        }


def _cmd_info(mgr, args) -> Dict[str, Any]:
    """Handle 'plugin info' command."""
    name = args.name

    info = mgr.get_plugin_info(name)
    if info is None:
        return {
            "status": "error",
            "error": f"Plugin '{name}' not found. Run 'codelens plugin list' to see available plugins.",
        }

    return {
        "status": "ok",
        "plugin": info,
    }


def _cmd_validate(args) -> Dict[str, Any]:
    """Handle 'plugin validate' command."""
    from plugin_system import validate_manifest as validate_fn

    path = args.path

    if not os.path.isdir(path):
        return {
            "status": "error",
            "error": f"Path does not exist or is not a directory: {path}",
        }

    result = validate_fn(path)

    output = {
        "status": "ok" if result.valid else "invalid",
        "valid": result.valid,
        "path": os.path.abspath(path),
    }

    if result.errors:
        output["errors"] = result.errors
    if result.warnings:
        output["warnings"] = result.warnings

    if result.valid and not result.warnings:
        output["message"] = "Plugin manifest is valid with no warnings."
    elif result.valid:
        output["message"] = "Plugin manifest is valid but has warnings."

    return output


def _extract_plugin_name_from_source(source: str) -> Optional[str]:
    """Try to extract a plugin name from a source string.

    Handles:
    - Local paths: /path/to/my-plugin/ -> my-plugin
    - URLs: https://github.com/user/codelens-owasp-rules/archive/main.zip -> owasp-rules
    - Registry names: owasp-top10 -> owasp-top10
    """
    if not source.startswith(("http://", "https://")):
        # Local path
        if os.path.isdir(source):
            return os.path.basename(os.path.abspath(source))
        # Plain name
        if "/" not in source and "\\" not in source:
            return source
        return os.path.basename(os.path.abspath(source))

    # URL — try to extract from path
    # e.g., https://github.com/user/codelens-owasp-rules/archive/main.zip
    from urllib.parse import urlparse
    parsed = urlparse(source)
    path_parts = parsed.path.strip("/").split("/")

    if len(path_parts) >= 2:
        repo_name = path_parts[1]
        # Remove common prefixes/suffixes
        for prefix in ("codelens-", "codelens_"):
            if repo_name.startswith(prefix):
                repo_name = repo_name[len(prefix):]
                break
        # Remove -main, -master, .zip suffixes
        for suffix in ("-main", "-master", ".zip", ".tar.gz"):
            if repo_name.endswith(suffix):
                repo_name = repo_name[:-len(suffix)]
                break
        return repo_name or None

    return None


register_command(
    "plugin",
    "Manage CodeLens plugins (install, list, search, update, info, validate)",
    add_args,
    execute,
)
