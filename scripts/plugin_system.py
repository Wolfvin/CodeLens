"""
CodeLens Plugin System & Rule Marketplace Foundation

Supports four plugin types:
  - rule_pack: A collection of YAML rules (like Semgrep rules)
  - engine: A custom analysis engine (Python module)
  - formatter: A custom output formatter
  - command: A custom CLI command

Plugin discovery searches:
  1. Local: .codelens/plugins/ (project-specific, highest priority)
  2. User: ~/.codelens/plugins/ (user-wide)
  3. Built-in: scripts/plugins/ (shipped with CodeLens, lowest priority)

Each plugin has a plugin.yaml manifest describing its metadata, type,
and entry points.

Plugin isolation: each plugin runs in its own namespace; exceptions are
caught so a failing plugin never crashes CodeLens.
"""

import os
import sys
import yaml
import json
import shutil
import zipfile
import tempfile
import importlib
import hashlib
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, field

from utils import logger


# ─── Constants ────────────────────────────────────────────────

PLUGIN_MANIFEST = "plugin.yaml"
LOCAL_PLUGIN_DIR = ".codelens/plugins"
USER_PLUGIN_DIR = os.path.join(os.path.expanduser("~"), ".codelens", "plugins")
BUILTIN_PLUGIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugins")

VALID_PLUGIN_TYPES = {"rule_pack", "engine", "formatter", "command"}
MANIFEST_REQUIRED_FIELDS = {"name", "version", "type", "description"}
MANIFEST_OPTIONAL_FIELDS = {
    "author", "rules_dir", "engines", "dependencies", "tags",
    "homepage", "license", "min_codelens_version", "entrypoint",
    "formatter_module", "command_module",
}

# Priority ordering: higher number = higher priority
_PRIORITY_MAP = {
    "local": 30,
    "user": 20,
    "builtin": 10,
}

# Registry index URL (future marketplace)
REGISTRY_INDEX_URL = "https://registry.codelens.dev/api/v1/plugins"
REGISTRY_CACHE_TTL = 3600  # 1 hour


# ─── Data Classes ─────────────────────────────────────────────

@dataclass
class PluginManifest:
    """Represents a parsed plugin.yaml manifest."""
    name: str
    version: str
    type: str
    description: str
    author: str = "unknown"
    rules_dir: Optional[str] = None
    engines: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    homepage: Optional[str] = None
    license: Optional[str] = None
    min_codelens_version: Optional[str] = None
    entrypoint: Optional[str] = None
    formatter_module: Optional[str] = None
    command_module: Optional[str] = None
    source_path: str = ""  # absolute path to plugin directory
    source_type: str = "builtin"  # local, user, builtin

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "type": self.type,
            "description": self.description,
            "author": self.author,
            "rules_dir": self.rules_dir,
            "engines": self.engines,
            "dependencies": self.dependencies,
            "tags": self.tags,
            "homepage": self.homepage,
            "license": self.license,
            "min_codelens_version": self.min_codelens_version,
            "entrypoint": self.entrypoint,
            "source_path": self.source_path,
            "source_type": self.source_type,
        }


@dataclass
class PluginRule:
    """A single rule loaded from a plugin rule_pack."""
    id: str
    name: str
    severity: str
    language: Optional[str] = None
    cwe: Optional[str] = None
    owasp: Optional[str] = None
    framework: Optional[str] = None
    requirement: Optional[str] = None
    message: str = ""
    sources: List[str] = field(default_factory=list)
    sinks: List[str] = field(default_factory=list)
    sanitizers: List[str] = field(default_factory=list)
    plugin_name: str = ""
    file_path: str = ""  # source YAML file

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "name": self.name,
            "severity": self.severity,
            "message": self.message,
            "plugin_name": self.plugin_name,
        }
        if self.language:
            d["language"] = self.language
        if self.cwe:
            d["cwe"] = self.cwe
        if self.owasp:
            d["owasp"] = self.owasp
        if self.framework:
            d["framework"] = self.framework
        if self.requirement:
            d["requirement"] = self.requirement
        if self.sources:
            d["sources"] = self.sources
        if self.sinks:
            d["sinks"] = self.sinks
        if self.sanitizers:
            d["sanitizers"] = self.sanitizers
        return d


@dataclass
class PluginValidationResult:
    """Result of validating a plugin manifest."""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }


# ─── Manifest Parsing & Validation ───────────────────────────

def parse_manifest(plugin_dir: str) -> Optional[PluginManifest]:
    """Parse a plugin.yaml manifest from a plugin directory.

    Args:
        plugin_dir: Absolute path to the plugin directory.

    Returns:
        PluginManifest if valid, None on error.
    """
    manifest_path = os.path.join(plugin_dir, PLUGIN_MANIFEST)
    if not os.path.isfile(manifest_path):
        logger.warning(f"No {PLUGIN_MANIFEST} found in {plugin_dir}")
        return None

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        logger.error(f"Invalid YAML in {manifest_path}: {e}")
        return None
    except IOError as e:
        logger.error(f"Cannot read {manifest_path}: {e}")
        return None

    if not isinstance(data, dict):
        logger.error(f"Manifest {manifest_path} is not a mapping")
        return None

    # Check required fields
    for req_field in MANIFEST_REQUIRED_FIELDS:
        if req_field not in data:
            logger.error(f"Missing required field '{req_field}' in {manifest_path}")
            return None

    # Validate type
    plugin_type = data["type"]
    if plugin_type not in VALID_PLUGIN_TYPES:
        logger.error(
            f"Invalid plugin type '{plugin_type}' in {manifest_path}. "
            f"Must be one of: {', '.join(sorted(VALID_PLUGIN_TYPES))}"
        )
        return None

    # Determine source type from path
    source_type = _determine_source_type(plugin_dir)

    return PluginManifest(
        name=str(data["name"]),
        version=str(data["version"]),
        type=plugin_type,
        description=str(data["description"]),
        author=str(data.get("author", "unknown")),
        rules_dir=data.get("rules_dir"),
        engines=data.get("engines", []),
        dependencies=data.get("dependencies", []),
        tags=data.get("tags", []),
        homepage=data.get("homepage"),
        license=data.get("license"),
        min_codelens_version=data.get("min_codelens_version"),
        entrypoint=data.get("entrypoint"),
        formatter_module=data.get("formatter_module"),
        command_module=data.get("command_module"),
        source_path=os.path.abspath(plugin_dir),
        source_type=source_type,
    )


def validate_manifest(plugin_dir: str) -> PluginValidationResult:
    """Validate a plugin directory and its manifest thoroughly.

    Checks:
    - plugin.yaml exists and is valid YAML
    - Required fields are present
    - Plugin type is valid
    - rules_dir exists (for rule_pack plugins)
    - entrypoint exists (for engine/formatter/command plugins)
    - Dependencies are specified correctly

    Args:
        plugin_dir: Path to the plugin directory.

    Returns:
        PluginValidationResult with errors and warnings.
    """
    errors = []
    warnings = []

    manifest_path = os.path.join(plugin_dir, PLUGIN_MANIFEST)

    # Check manifest exists
    if not os.path.isfile(manifest_path):
        return PluginValidationResult(
            valid=False,
            errors=[f"No {PLUGIN_MANIFEST} found in {plugin_dir}"],
        )

    # Parse YAML
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return PluginValidationResult(
            valid=False,
            errors=[f"Invalid YAML in {PLUGIN_MANIFEST}: {e}"],
        )

    if not isinstance(data, dict):
        return PluginValidationResult(
            valid=False,
            errors=[f"{PLUGIN_MANIFEST} must be a YAML mapping, got {type(data).__name__}"],
        )

    # Check required fields
    for req_field in MANIFEST_REQUIRED_FIELDS:
        if req_field not in data or not data[req_field]:
            errors.append(f"Missing required field: {req_field}")

    if errors:
        return PluginValidationResult(valid=False, errors=errors)

    # Validate name (alphanumeric, hyphens, underscores)
    name = str(data["name"])
    if not all(c.isalnum() or c in "-_" for c in name):
        errors.append(f"Plugin name '{name}' contains invalid characters (use alphanumeric, hyphens, underscores)")

    # Validate version format (semver-like)
    version = str(data["version"])
    parts = version.split(".")
    if len(parts) < 2 or not all(p.isdigit() for p in parts[:2]):
        warnings.append(f"Version '{version}' doesn't follow semver (e.g., 1.0.0)")

    # Validate type
    plugin_type = data["type"]
    if plugin_type not in VALID_PLUGIN_TYPES:
        errors.append(
            f"Invalid plugin type '{plugin_type}'. "
            f"Must be one of: {', '.join(sorted(VALID_PLUGIN_TYPES))}"
        )

    # Type-specific validation
    if plugin_type == "rule_pack":
        rules_dir = data.get("rules_dir")
        if rules_dir:
            abs_rules_dir = os.path.join(plugin_dir, rules_dir)
            if not os.path.isdir(abs_rules_dir):
                errors.append(f"rules_dir '{rules_dir}' does not exist")
            else:
                # Check for YAML files
                yaml_files = [f for f in os.listdir(abs_rules_dir) if f.endswith((".yaml", ".yml"))]
                if not yaml_files:
                    warnings.append(f"rules_dir '{rules_dir}' contains no YAML rule files")
        else:
            warnings.append("rule_pack plugin has no rules_dir specified — no rules will be loaded")

    elif plugin_type == "engine":
        entrypoint = data.get("entrypoint")
        if not entrypoint:
            errors.append("engine plugin requires 'entrypoint' field (Python module path)")
        else:
            entry_path = os.path.join(plugin_dir, entrypoint)
            if not os.path.isfile(entry_path):
                errors.append(f"Engine entrypoint '{entrypoint}' does not exist")

    elif plugin_type == "formatter":
        formatter_module = data.get("formatter_module")
        if not formatter_module:
            errors.append("formatter plugin requires 'formatter_module' field")
        else:
            mod_path = os.path.join(plugin_dir, formatter_module)
            if not os.path.isfile(mod_path):
                errors.append(f"Formatter module '{formatter_module}' does not exist")

    elif plugin_type == "command":
        command_module = data.get("command_module")
        if not command_module:
            errors.append("command plugin requires 'command_module' field")
        else:
            mod_path = os.path.join(plugin_dir, command_module)
            if not os.path.isfile(mod_path):
                errors.append(f"Command module '{command_module}' does not exist")

    # Check dependencies format
    deps = data.get("dependencies", [])
    if not isinstance(deps, list):
        errors.append("'dependencies' must be a list of strings")
    else:
        for dep in deps:
            if not isinstance(dep, str):
                errors.append(f"Dependency '{dep}' must be a string (pip package specification)")

    # Check tags format
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        errors.append("'tags' must be a list of strings")

    # Check min_codelens_version compatibility
    min_ver = data.get("min_codelens_version")
    if min_ver:
        try:
            from utils import CODELENS_VERSION
            if not _version_compatible(min_ver, CODELENS_VERSION):
                errors.append(
                    f"Plugin requires CodeLens >= {min_ver}, but current version is {CODELENS_VERSION}"
                )
        except ImportError:
            pass

    return PluginValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


def _determine_source_type(plugin_dir: str) -> str:
    """Determine whether a plugin path is local, user, or builtin."""
    abs_dir = os.path.abspath(plugin_dir)
    if LOCAL_PLUGIN_DIR in abs_dir:
        # Check if it's inside the workspace's .codelens/plugins/
        # Heuristic: if the path contains .codelens/plugins but NOT ~/.codelens/plugins
        user_plugin_abs = os.path.abspath(USER_PLUGIN_DIR)
        if abs_dir.startswith(user_plugin_abs):
            return "user"
        return "local"
    if abs_dir.startswith(os.path.abspath(USER_PLUGIN_DIR)):
        return "user"
    if abs_dir.startswith(os.path.abspath(BUILTIN_PLUGIN_DIR)):
        return "builtin"
    return "local"


def _version_compatible(min_version: str, current_version: str) -> bool:
    """Check if current_version >= min_version (simple semver comparison)."""
    def _parse_ver(v):
        parts = []
        for p in v.split("."):
            try:
                parts.append(int(p))
            except ValueError:
                parts.append(0)
        return tuple(parts)

    try:
        return _parse_ver(current_version) >= _parse_ver(min_version)
    except (ValueError, TypeError):
        return True  # assume compatible if can't parse


# ─── Rule Loading ─────────────────────────────────────────────

def load_rules_from_dir(rules_dir: str, plugin_name: str = "") -> List[PluginRule]:
    """Load all YAML rule files from a directory.

    Supports both:
    - Semgrep-style: list of rules under a 'rules' key
    - Flat style: individual rule dicts

    Args:
        rules_dir: Absolute path to the rules directory.
        plugin_name: Name of the parent plugin (for traceability).

    Returns:
        List of PluginRule objects.
    """
    rules = []
    if not os.path.isdir(rules_dir):
        logger.warning(f"Rules directory does not exist: {rules_dir}")
        return rules

    for fname in sorted(os.listdir(rules_dir)):
        if not fname.endswith((".yaml", ".yml")):
            continue

        fpath = os.path.join(rules_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML in rule file {fpath}: {e}")
            continue
        except IOError as e:
            logger.error(f"Cannot read rule file {fpath}: {e}")
            continue

        if data is None:
            continue

        # Semgrep-style: top-level 'rules' key
        if isinstance(data, dict) and "rules" in data:
            rule_list = data["rules"]
        elif isinstance(data, list):
            rule_list = data
        elif isinstance(data, dict):
            # Single rule or compliance-style mapping
            rule_list = _extract_rules_from_compliance_yaml(data)
        else:
            logger.warning(f"Unexpected format in {fpath}: {type(data).__name__}")
            continue

        if not isinstance(rule_list, list):
            logger.warning(f"Rules not a list in {fpath}")
            continue

        for rule_data in rule_list:
            if not isinstance(rule_data, dict):
                continue
            rule = _parse_single_rule(rule_data, plugin_name, fpath)
            if rule:
                rules.append(rule)

    return rules


def _extract_rules_from_compliance_yaml(data: Dict) -> List[Dict]:
    """Extract rules from compliance-style YAML that may have category groupings.

    Handles formats like:
      rules:
        - category: ...
          entries:
            - id: ...
    Or flat:
      - id: pci-dss/req-6.5.1
        ...
    """
    # If 'rules' key exists, use it
    if "rules" in data and isinstance(data["rules"], list):
        return data["rules"]

    # If the data itself looks like a list of rules
    if "id" in data:
        return [data]

    # If it has category groupings
    all_rules = []
    for key, value in data.items():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and "id" in item:
                    all_rules.append(item)
                elif isinstance(item, dict) and "entries" in item:
                    all_rules.extend(item["entries"])
    return all_rules


def _parse_single_rule(data: Dict, plugin_name: str, file_path: str) -> Optional[PluginRule]:
    """Parse a single rule dict into a PluginRule."""
    rule_id = data.get("id", "")
    if not rule_id:
        logger.debug(f"Skipping rule without id in {file_path}")
        return None

    rule = PluginRule(
        id=str(rule_id),
        name=str(data.get("name", rule_id)),
        severity=str(data.get("severity", "info")),
        language=data.get("language"),
        cwe=data.get("cwe"),
        owasp=data.get("owasp"),
        framework=data.get("framework"),
        requirement=data.get("requirement"),
        message=str(data.get("message", "")),
        sources=data.get("sources", []),
        sinks=data.get("sinks", []),
        sanitizers=data.get("sanitizers", []),
        plugin_name=plugin_name,
        file_path=file_path,
    )
    return rule


# ─── Plugin Manager ──────────────────────────────────────────

class PluginManager:
    """Central manager for CodeLens plugins.

    Handles discovery, loading, installation, and lifecycle management
    of all plugin types (rule_pack, engine, formatter, command).
    """

    def __init__(self, workspace: Optional[str] = None):
        """Initialize the PluginManager.

        Args:
            workspace: Optional workspace root path. If provided, local
                       plugins from .codelens/plugins/ will be discovered.
        """
        self.workspace = workspace
        self._plugins: Dict[str, PluginManifest] = {}
        self._rules: List[PluginRule] = []
        self._loaded_engines: Dict[str, Any] = {}
        self._loaded_formatters: Dict[str, Any] = {}
        self._loaded_commands: Dict[str, Any] = {}
        self._discovered = False

    # ─── Discovery ────────────────────────────────────────

    def discover_plugins(self) -> Dict[str, PluginManifest]:
        """Find all installed plugins across all search paths.

        Search order (later overrides earlier for same name):
        1. Built-in: scripts/plugins/
        2. User: ~/.codelens/plugins/
        3. Local: .codelens/plugins/ (workspace-specific, highest priority)

        Returns:
            Dict mapping plugin name -> PluginManifest.
        """
        self._plugins = {}

        # Discover in priority order (builtin first, then user, then local)
        search_paths = [
            (BUILTIN_PLUGIN_DIR, "builtin"),
            (USER_PLUGIN_DIR, "user"),
        ]

        # Add local workspace plugins
        if self.workspace:
            local_path = os.path.join(self.workspace, LOCAL_PLUGIN_DIR)
            search_paths.append((local_path, "local"))

        for base_path, source_type in search_paths:
            if not os.path.isdir(base_path):
                continue

            for entry in sorted(os.listdir(base_path)):
                entry_path = os.path.join(base_path, entry)
                if not os.path.isdir(entry_path):
                    continue

                manifest = parse_manifest(entry_path)
                if manifest is None:
                    continue

                # Override lower-priority plugins with same name
                existing = self._plugins.get(manifest.name)
                if existing:
                    existing_priority = _PRIORITY_MAP.get(existing.source_type, 0)
                    new_priority = _PRIORITY_MAP.get(source_type, 0)
                    if new_priority <= existing_priority:
                        continue  # keep higher-priority version

                self._plugins[manifest.name] = manifest

        self._discovered = True
        return self._plugins

    # ─── Loading ───────────────────────────────────────────

    def load_plugin(self, name: str) -> Optional[PluginManifest]:
        """Load and validate a specific plugin by name.

        For rule_pack plugins, loads all rules.
        For engine/formatter/command plugins, imports the Python module.

        Args:
            name: Plugin name as specified in plugin.yaml.

        Returns:
            PluginManifest if loaded successfully, None otherwise.
        """
        if not self._discovered:
            self.discover_plugins()

        manifest = self._plugins.get(name)
        if manifest is None:
            logger.error(f"Plugin '{name}' not found")
            return None

        try:
            if manifest.type == "rule_pack":
                return self._load_rule_pack(manifest)
            elif manifest.type == "engine":
                return self._load_engine(manifest)
            elif manifest.type == "formatter":
                return self._load_formatter(manifest)
            elif manifest.type == "command":
                return self._load_command(manifest)
        except Exception as e:
            logger.error(f"Failed to load plugin '{name}': {e}")
            return None

        return manifest

    def _load_rule_pack(self, manifest: PluginManifest) -> PluginManifest:
        """Load rules from a rule_pack plugin."""
        if not manifest.rules_dir:
            logger.warning(f"Rule pack '{manifest.name}' has no rules_dir")
            return manifest

        rules_path = os.path.join(manifest.source_path, manifest.rules_dir)
        new_rules = load_rules_from_dir(rules_path, manifest.name)
        self._rules.extend(new_rules)
        logger.debug(f"Loaded {len(new_rules)} rules from '{manifest.name}'")
        return manifest

    def _load_engine(self, manifest: PluginManifest) -> PluginManifest:
        """Load an engine plugin's Python module."""
        if not manifest.entrypoint:
            logger.error(f"Engine plugin '{manifest.name}' has no entrypoint")
            return manifest

        entry_path = os.path.join(manifest.source_path, manifest.entrypoint)
        module = self._safe_import_module(manifest.name, entry_path)
        if module is None:
            return manifest

        self._loaded_engines[manifest.name] = {
            "manifest": manifest,
            "module": module,
        }
        return manifest

    def _load_formatter(self, manifest: PluginManifest) -> PluginManifest:
        """Load a formatter plugin's Python module."""
        if not manifest.formatter_module:
            logger.error(f"Formatter plugin '{manifest.name}' has no formatter_module")
            return manifest

        mod_path = os.path.join(manifest.source_path, manifest.formatter_module)
        module = self._safe_import_module(manifest.name, mod_path)
        if module is None:
            return manifest

        self._loaded_formatters[manifest.name] = {
            "manifest": manifest,
            "module": module,
        }
        return manifest

    def _load_command(self, manifest: PluginManifest) -> PluginManifest:
        """Load a command plugin's Python module."""
        if not manifest.command_module:
            logger.error(f"Command plugin '{manifest.name}' has no command_module")
            return manifest

        mod_path = os.path.join(manifest.source_path, manifest.command_module)
        module = self._safe_import_module(manifest.name, mod_path)
        if module is None:
            return manifest

        self._loaded_commands[manifest.name] = {
            "manifest": manifest,
            "module": module,
        }

        # Auto-register command if the module has register_command function
        try:
            if hasattr(module, "register_plugin_command"):
                module.register_plugin_command()
        except Exception as e:
            logger.error(f"Command plugin '{manifest.name}' registration failed: {e}")

        return manifest

    def _safe_import_module(self, plugin_name: str, module_path: str) -> Optional[Any]:
        """Safely import a Python module from a file path.

        Each plugin module is loaded in an isolated namespace to prevent
        crashes from propagating to the core CodeLens system.

        Args:
            plugin_name: Plugin name (used as module name).
            module_path: Absolute path to the .py file.

        Returns:
            Imported module, or None on failure.
        """
        if not os.path.isfile(module_path):
            logger.error(f"Module not found: {module_path}")
            return None

        try:
            # Create a unique module name to avoid collisions
            module_name = f"codelens_plugin_{plugin_name.replace('-', '_')}"

            # Add plugin directory to sys.path temporarily
            plugin_dir = os.path.dirname(module_path)
            if plugin_dir not in sys.path:
                sys.path.insert(0, plugin_dir)

            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if spec is None or spec.loader is None:
                logger.error(f"Cannot create module spec for {module_path}")
                return None

            module = importlib.util.module_from_spec(spec)

            # Execute module in isolated try/except
            try:
                spec.loader.exec_module(module)
            except Exception as e:
                logger.error(
                    f"Plugin '{plugin_name}' module execution failed: {e}. "
                    f"The plugin is disabled but CodeLens will continue."
                )
                return None

            return module

        except Exception as e:
            logger.error(f"Failed to import plugin module '{plugin_name}': {e}")
            return None

    def load_all_plugins(self) -> Dict[str, PluginManifest]:
        """Load all discovered plugins.

        Returns:
            Dict of plugin name -> loaded PluginManifest.
        """
        if not self._discovered:
            self.discover_plugins()

        loaded = {}
        for name in list(self._plugins.keys()):
            try:
                result = self.load_plugin(name)
                if result:
                    loaded[name] = result
            except Exception as e:
                logger.error(f"Error loading plugin '{name}': {e}")

        return loaded

    # ─── Installation ──────────────────────────────────────

    def install_plugin(self, source: str, target: str = "user") -> Dict[str, Any]:
        """Install a plugin from a URL, local path, or registry name.

        Args:
            source: One of:
                - URL to a .zip archive (GitHub release, etc.)
                - Local path to a plugin directory
                - Plugin name for registry lookup (future)
            target: Where to install: "local" (workspace), "user" (home dir)

        Returns:
            Dict with status and details.
        """
        # Determine target directory
        if target == "local":
            if not self.workspace:
                return {"status": "error", "error": "No workspace set for local plugin installation"}
            install_dir = os.path.join(self.workspace, LOCAL_PLUGIN_DIR)
        else:
            install_dir = USER_PLUGIN_DIR

        os.makedirs(install_dir, exist_ok=True)

        # Route to appropriate installer
        if source.startswith(("http://", "https://")):
            return self._install_from_url(source, install_dir)
        elif os.path.isdir(source):
            return self._install_from_local(source, install_dir)
        elif os.path.isfile(source) and source.endswith(".zip"):
            return self._install_from_zip(source, install_dir)
        else:
            # Try registry lookup
            return self._install_from_registry(source, install_dir)

    def _install_from_url(self, url: str, install_dir: str) -> Dict[str, Any]:
        """Install a plugin from a URL (downloads and extracts)."""
        try:
            import urllib.request
        except ImportError:
            return {"status": "error", "error": "urllib not available for downloading plugins"}

        # Download to temp directory
        tmp_dir = tempfile.mkdtemp(prefix="codelens_plugin_")
        try:
            zip_path = os.path.join(tmp_dir, "plugin.zip")
            logger.info(f"Downloading plugin from {url}...")

            try:
                urllib.request.urlretrieve(url, zip_path)
            except Exception as e:
                return {"status": "error", "error": f"Download failed: {e}"}

            result = self._install_from_zip(zip_path, install_dir)
            return result

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _install_from_zip(self, zip_path: str, install_dir: str) -> Dict[str, Any]:
        """Install a plugin from a ZIP archive."""
        tmp_dir = tempfile.mkdtemp(prefix="codelens_plugin_extract_")
        try:
            # Extract
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(tmp_dir)
            except zipfile.BadZipFile as e:
                return {"status": "error", "error": f"Invalid ZIP file: {e}"}

            # Find the plugin directory (may be nested under archive-main/ etc.)
            plugin_dir = self._find_plugin_dir_in_extracted(tmp_dir)
            if plugin_dir is None:
                return {"status": "error", "error": "No valid plugin found in archive (missing plugin.yaml)"}

            return self._install_from_local(plugin_dir, install_dir)

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _install_from_local(self, source_dir: str, install_dir: str) -> Dict[str, Any]:
        """Install a plugin from a local directory."""
        # Validate the source
        source_dir = os.path.abspath(source_dir)
        if not os.path.isdir(source_dir):
            return {"status": "error", "error": f"Source directory does not exist: {source_dir}"}

        manifest_path = os.path.join(source_dir, PLUGIN_MANIFEST)
        if not os.path.isfile(manifest_path):
            return {"status": "error", "error": f"No {PLUGIN_MANIFEST} found in {source_dir}"}

        # Validate manifest
        validation = validate_manifest(source_dir)
        if not validation.valid:
            return {
                "status": "error",
                "error": "Plugin validation failed",
                "validation_errors": validation.errors,
            }

        # Parse to get plugin name
        manifest = parse_manifest(source_dir)
        if manifest is None:
            return {"status": "error", "error": "Failed to parse plugin manifest"}

        plugin_name = manifest.name
        dest_dir = os.path.join(install_dir, plugin_name)

        # Check if already installed
        if os.path.exists(dest_dir):
            # Compare versions
            existing = parse_manifest(dest_dir)
            if existing and existing.version == manifest.version:
                return {
                    "status": "already_installed",
                    "name": plugin_name,
                    "version": manifest.version,
                    "message": f"Plugin '{plugin_name}' v{manifest.version} is already installed",
                }

        # Install dependencies
        if manifest.dependencies:
            dep_result = self._install_dependencies(manifest.dependencies)
            if dep_result.get("status") == "error":
                return {
                    "status": "error",
                    "error": "Failed to install plugin dependencies",
                    "dependency_errors": dep_result.get("errors", []),
                }

        # Copy plugin to install directory
        try:
            if os.path.exists(dest_dir):
                shutil.rmtree(dest_dir)
            shutil.copytree(source_dir, dest_dir)
        except (IOError, OSError) as e:
            return {"status": "error", "error": f"Failed to copy plugin: {e}"}

        # Re-discover to pick up new plugin
        self._discovered = False
        self.discover_plugins()

        return {
            "status": "ok",
            "name": plugin_name,
            "version": manifest.version,
            "type": manifest.type,
            "install_path": dest_dir,
            "warnings": validation.warnings if validation.warnings else None,
        }

    def _install_from_registry(self, name: str, install_dir: str) -> Dict[str, Any]:
        """Install a plugin from the CodeLens registry (future marketplace).

        Currently returns a placeholder response. The registry will be
        available at https://registry.codelens.dev in the future.
        """
        # For now, return a helpful message
        return {
            "status": "error",
            "error": f"Plugin registry is not yet available. Cannot find '{name}'.",
            "hint": "Install from a URL or local path instead. "
                    "Example: codelens plugin install https://github.com/user/plugin/archive/main.zip",
            "registry_url": REGISTRY_INDEX_URL,
        }

    def _find_plugin_dir_in_extracted(self, extract_dir: str) -> Optional[str]:
        """Find the plugin directory within an extracted archive.

        Handles common patterns:
        - Root of archive contains plugin.yaml
        - Archive has a single subdirectory (e.g., plugin-main/)
        - Nested under src/ or similar

        Returns:
            Absolute path to plugin directory, or None.
        """
        # Check root
        if os.path.isfile(os.path.join(extract_dir, PLUGIN_MANIFEST)):
            return extract_dir

        # Check one level deep (common for GitHub archives)
        for entry in os.listdir(extract_dir):
            entry_path = os.path.join(extract_dir, entry)
            if os.path.isdir(entry_path):
                if os.path.isfile(os.path.join(entry_path, PLUGIN_MANIFEST)):
                    return entry_path

        # Check two levels deep
        for entry in os.listdir(extract_dir):
            entry_path = os.path.join(extract_dir, entry)
            if os.path.isdir(entry_path):
                for sub_entry in os.listdir(entry_path):
                    sub_path = os.path.join(entry_path, sub_entry)
                    if os.path.isdir(sub_path):
                        if os.path.isfile(os.path.join(sub_path, PLUGIN_MANIFEST)):
                            return sub_path

        return None

    def _install_dependencies(self, dependencies: List[str]) -> Dict[str, Any]:
        """Install pip dependencies for a plugin.

        Args:
            dependencies: List of pip package specifications.

        Returns:
            Dict with status and any errors.
        """
        errors = []
        for dep in dependencies:
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", dep],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode != 0:
                    errors.append(f"Failed to install {dep}: {result.stderr.strip()}")
            except subprocess.TimeoutExpired:
                errors.append(f"Timeout installing {dep}")
            except Exception as e:
                errors.append(f"Error installing {dep}: {e}")

        if errors:
            return {"status": "error", "errors": errors}
        return {"status": "ok"}

    # ─── Uninstallation ────────────────────────────────────

    def uninstall_plugin(self, name: str) -> Dict[str, Any]:
        """Uninstall a plugin by name.

        Cannot uninstall built-in plugins.

        Args:
            name: Plugin name to uninstall.

        Returns:
            Dict with status.
        """
        if not self._discovered:
            self.discover_plugins()

        manifest = self._plugins.get(name)
        if manifest is None:
            return {"status": "error", "error": f"Plugin '{name}' not found"}

        if manifest.source_type == "builtin":
            return {
                "status": "error",
                "error": f"Cannot uninstall built-in plugin '{name}'",
                "hint": "Built-in plugins ship with CodeLens and cannot be removed.",
            }

        plugin_path = manifest.source_path
        if not os.path.isdir(plugin_path):
            return {"status": "error", "error": f"Plugin directory not found: {plugin_path}"}

        try:
            shutil.rmtree(plugin_path)
        except (IOError, OSError) as e:
            return {"status": "error", "error": f"Failed to remove plugin directory: {e}"}

        # Clean up loaded state
        self._plugins.pop(name, None)
        self._rules = [r for r in self._rules if r.plugin_name != name]
        self._loaded_engines.pop(name, None)
        self._loaded_formatters.pop(name, None)
        self._loaded_commands.pop(name, None)

        # Re-discover
        self._discovered = False
        self.discover_plugins()

        return {
            "status": "ok",
            "name": name,
            "removed_path": plugin_path,
        }

    # ─── Listing & Info ────────────────────────────────────

    def list_plugins(self) -> List[Dict[str, Any]]:
        """List all available plugins with metadata.

        Returns:
            List of plugin info dicts.
        """
        if not self._discovered:
            self.discover_plugins()

        result = []
        for name, manifest in sorted(self._plugins.items()):
            info = manifest.to_dict()
            # Add rule count if rule_pack
            if manifest.type == "rule_pack":
                rule_count = len([r for r in self._rules if r.plugin_name == name])
                info["rule_count"] = rule_count
            result.append(info)

        return result

    def get_plugin_info(self, name: str) -> Optional[Dict[str, Any]]:
        """Get detailed info about a specific plugin.

        Args:
            name: Plugin name.

        Returns:
            Detailed plugin info dict, or None if not found.
        """
        if not self._discovered:
            self.discover_plugins()

        manifest = self._plugins.get(name)
        if manifest is None:
            return None

        info = manifest.to_dict()

        # Add type-specific details
        if manifest.type == "rule_pack":
            # Auto-load rules if not yet loaded
            if not any(r.plugin_name == name for r in self._rules):
                self.load_plugin(name)
            plugin_rules = [r for r in self._rules if r.plugin_name == name]
            info["rule_count"] = len(plugin_rules)
            info["rules"] = [r.to_dict() for r in plugin_rules[:20]]  # First 20
            if len(plugin_rules) > 20:
                info["rules_total"] = len(plugin_rules)
                info["rules_truncated"] = True

            # Severity distribution
            severity_dist = {}
            for r in plugin_rules:
                sev = r.severity
                severity_dist[sev] = severity_dist.get(sev, 0) + 1
            info["severity_distribution"] = severity_dist

        elif manifest.type == "engine" and name in self._loaded_engines:
            info["loaded"] = True
            info["module_functions"] = [
                f for f in dir(self._loaded_engines[name]["module"])
                if not f.startswith("_")
            ][:20]

        elif manifest.type == "formatter" and name in self._loaded_formatters:
            info["loaded"] = True

        elif manifest.type == "command" and name in self._loaded_commands:
            info["loaded"] = True

        return info

    # ─── Rule & Engine Accessors ───────────────────────────

    def get_rules(self, tags: Optional[List[str]] = None) -> List[PluginRule]:
        """Get all rules from loaded rule_pack plugins.

        Args:
            tags: Optional filter — only return rules from plugins with these tags.

        Returns:
            List of PluginRule objects.
        """
        if not self._discovered:
            self.discover_plugins()

        # Auto-load any undiscovered rule packs
        for name, manifest in self._plugins.items():
            if manifest.type == "rule_pack":
                # Check if already loaded
                already_loaded = any(r.plugin_name == name for r in self._rules)
                if not already_loaded:
                    self.load_plugin(name)

        if tags:
            tag_set = set(tags)
            # Filter by plugin tags
            filtered = []
            for rule in self._rules:
                manifest = self._plugins.get(rule.plugin_name)
                if manifest and tag_set.intersection(manifest.tags):
                    filtered.append(rule)
            return filtered

        return list(self._rules)

    def get_rules_yaml(self, tags: Optional[List[str]] = None) -> Dict[str, Any]:
        """Get all plugin rules in Semgrep-compatible YAML format.

        Args:
            tags: Optional filter by plugin tags.

        Returns:
            Dict with 'rules' key containing list of rule dicts.
        """
        rules = self.get_rules(tags)
        rule_dicts = []
        for r in rules:
            rd = {
                "id": r.id,
                "name": r.name,
                "severity": r.severity,
                "message": r.message or f"Violation of {r.id}",
            }
            if r.language:
                rd["language"] = r.language
            if r.cwe:
                rd["cwe"] = r.cwe
            if r.owasp:
                rd["owasp"] = r.owasp
            if r.framework:
                rd["framework"] = r.framework
            if r.requirement:
                rd["requirement"] = r.requirement
            if r.sources:
                rd["sources"] = r.sources
            if r.sinks:
                rd["sinks"] = r.sinks
            if r.sanitizers:
                rd["sanitizers"] = r.sanitizers
            rule_dicts.append(rd)

        return {"rules": rule_dicts}

    def get_engines(self) -> Dict[str, Any]:
        """Get all loaded engine plugins.

        Returns:
            Dict mapping engine name -> {manifest, module}.
        """
        if not self._discovered:
            self.discover_plugins()

        for name, manifest in self._plugins.items():
            if manifest.type == "engine" and name not in self._loaded_engines:
                self.load_plugin(name)

        return dict(self._loaded_engines)

    def get_formatters(self) -> Dict[str, Any]:
        """Get all loaded formatter plugins.

        Returns:
            Dict mapping formatter name -> {manifest, module}.
        """
        if not self._discovered:
            self.discover_plugins()

        for name, manifest in self._plugins.items():
            if manifest.type == "formatter" and name not in self._loaded_formatters:
                self.load_plugin(name)

        return dict(self._loaded_formatters)

    # ─── Search ────────────────────────────────────────────

    def search_plugins(self, query: str) -> List[Dict[str, Any]]:
        """Search for plugins matching a query.

        Searches plugin name, description, and tags.
        In the future, this will also query the remote registry.

        Args:
            query: Search query string.

        Returns:
            List of matching plugin info dicts.
        """
        if not self._discovered:
            self.discover_plugins()

        query_lower = query.lower()
        results = []

        for name, manifest in self._plugins.items():
            score = 0
            # Name match (highest weight)
            if query_lower in name.lower():
                score += 10
            # Tag match
            for tag in manifest.tags:
                if query_lower in tag.lower():
                    score += 5
            # Description match
            if query_lower in manifest.description.lower():
                score += 3
            # Author match
            if query_lower in manifest.author.lower():
                score += 1

            if score > 0:
                info = manifest.to_dict()
                info["search_score"] = score
                results.append(info)

        # Sort by score descending
        results.sort(key=lambda x: x.get("search_score", 0), reverse=True)
        return results

    # ─── Update ────────────────────────────────────────────

    def update_plugin(self, name: str) -> Dict[str, Any]:
        """Check for and apply updates to a plugin.

        For URL-installed plugins, re-downloads and installs if newer.
        For registry plugins, queries the registry.

        Args:
            name: Plugin name to update.

        Returns:
            Dict with update status.
        """
        if not self._discovered:
            self.discover_plugins()

        manifest = self._plugins.get(name)
        if manifest is None:
            return {"status": "error", "error": f"Plugin '{name}' not found"}

        if manifest.source_type == "builtin":
            return {
                "status": "up_to_date",
                "name": name,
                "message": "Built-in plugins are updated with CodeLens releases.",
            }

        # For user/local plugins, we can't auto-update without knowing the source
        # In the future, the registry will provide update information
        return {
            "status": "info",
            "name": name,
            "current_version": manifest.version,
            "message": "Automatic updates are not yet supported. "
                       "Re-install the plugin with 'codelens plugin install' to update.",
        }

    def update_all_plugins(self) -> List[Dict[str, Any]]:
        """Check for updates to all installed plugins.

        Returns:
            List of update results for each plugin.
        """
        if not self._discovered:
            self.discover_plugins()

        results = []
        for name in list(self._plugins.keys()):
            result = self.update_plugin(name)
            results.append(result)

        return results

    # ─── Utility ───────────────────────────────────────────

    def validate_plugin_path(self, path: str) -> PluginValidationResult:
        """Validate a plugin at a given path.

        Args:
            path: Path to the plugin directory.

        Returns:
            PluginValidationResult.
        """
        abs_path = os.path.abspath(path)
        if not os.path.isdir(abs_path):
            return PluginValidationResult(
                valid=False,
                errors=[f"Path does not exist or is not a directory: {path}"],
            )
        return validate_manifest(abs_path)

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the plugin system.

        Returns:
            Dict with plugin counts, rule counts, etc.
        """
        if not self._discovered:
            self.discover_plugins()

        by_type = {}
        for manifest in self._plugins.values():
            by_type[manifest.type] = by_type.get(manifest.type, 0) + 1

        by_source = {}
        for manifest in self._plugins.values():
            by_source[manifest.source_type] = by_source.get(manifest.source_type, 0) + 1

        return {
            "total_plugins": len(self._plugins),
            "by_type": by_type,
            "by_source": by_source,
            "total_rules": len(self._rules),
            "loaded_engines": len(self._loaded_engines),
            "loaded_formatters": len(self._loaded_formatters),
            "loaded_commands": len(self._loaded_commands),
            "search_paths": {
                "local": os.path.join(self.workspace, LOCAL_PLUGIN_DIR) if self.workspace else None,
                "user": USER_PLUGIN_DIR,
                "builtin": BUILTIN_PLUGIN_DIR,
            },
        }


# ─── Module-Level Convenience Functions ──────────────────────

_default_manager: Optional[PluginManager] = None


def get_plugin_manager(workspace: Optional[str] = None) -> PluginManager:
    """Get or create the default PluginManager instance.

    Args:
        workspace: Optional workspace path. If provided and different
                   from the current manager's workspace, creates a new one.

    Returns:
        PluginManager singleton.
    """
    global _default_manager
    if _default_manager is None or (workspace and _default_manager.workspace != workspace):
        _default_manager = PluginManager(workspace=workspace)
    return _default_manager


def get_plugin_rules(workspace: Optional[str] = None, tags: Optional[List[str]] = None) -> List[PluginRule]:
    """Quick access to all plugin rules.

    Args:
        workspace: Optional workspace path.
        tags: Optional tag filter.

    Returns:
        List of PluginRule objects.
    """
    mgr = get_plugin_manager(workspace)
    return mgr.get_rules(tags)


def install_plugin(source: str, workspace: Optional[str] = None, target: str = "user") -> Dict[str, Any]:
    """Quick access to install a plugin.

    Args:
        source: URL, path, or registry name.
        workspace: Optional workspace path.
        target: "local" or "user".

    Returns:
        Installation result dict.
    """
    mgr = get_plugin_manager(workspace)
    return mgr.install_plugin(source, target)


def list_plugins(workspace: Optional[str] = None) -> List[Dict[str, Any]]:
    """Quick access to list all plugins.

    Args:
        workspace: Optional workspace path.

    Returns:
        List of plugin info dicts.
    """
    mgr = get_plugin_manager(workspace)
    return mgr.list_plugins()
