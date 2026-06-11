"""
Environment Variable Check Engine for CodeLens — v3
Audits environment variables — what's referenced, what's required (no fallback),
what's undocumented, and what's misconfigured.

Answers: "What env vars does this project need? Which ones will crash if missing?
          Are secrets in .env files? Is .env in .gitignore?"

Detection Sources:
 1. JS/TS    — process.env.X, process.env['X'], import.meta.env.X,
               process.env.X ?? 'default', process.env.X || 'default'
 2. Python   — os.environ['X'], os.environ.get('X'), os.getenv('X'),
               dotenv patterns
 3. Rust     — std::env::var("X"), env!("X"), option_env!("X")
 4. Config   — .env, .env.local, .env.production, .env.development, .env.example

Per-variable extraction:
  - name, referenced_in: [{file, line, context}]
  - has_fallback, is_required, defined_in_env_file
  - is_in_gitignore, documentation

Additional detection:
  - Missing .env.example entries
  - Required vars without fallbacks (deployment risk)
  - Secrets in .env files that should use a secret manager
  - Inconsistent naming conventions
"""

import os
import re
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS


# ─── Configuration ─────────────────────────────────────────────

SOURCE_EXTENSIONS = {
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".py", ".rs", ".vue", ".svelte",
}

ENV_FILE_PATTERNS = {
    ".env", ".env.local", ".env.development", ".env.dev",
    ".env.production", ".env.prod", ".env.staging",
    ".env.test", ".env.ci", ".env.example", ".env.sample",
    ".env.template",
}

# Patterns that suggest a value is a secret
SECRET_KEYWORDS = {
    "secret", "password", "passwd", "token", "api_key", "apikey",
    "access_key", "private_key", "auth", "credential", "cert",
    "encryption", "decrypt", "signing_key", "webhook_secret",
}

# Known non-secret prefixes/suffixes to avoid false positives
NON_SECRET_PATTERNS = {
    "url", "host", "port", "path", "dir", "name", "title",
    "debug", "log", "level", "env", "mode", "version",
    "public", "frontend", "backend", "app", "max", "min",
    "timeout", "retry", "count", "size", "limit",
}


def check_env_vars(
    workspace: str,
    var_name: Optional[str] = None,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Audit all environment variable references in the workspace.

    Args:
        workspace: Absolute path to workspace
        var_name: Optional filter for a specific env var name
        config: CodeLens config dict

    Returns:
        Dict with stats, variables, missing_from_example,
        required_without_fallback, naming_inconsistencies,
        env_files, recommendations
    """
    workspace = os.path.abspath(workspace)

    # Collect all data
    env_vars: Dict[str, Dict[str, Any]] = {}  # var_name → info
    env_files: List[Dict[str, Any]] = []
    files_scanned = 0

    # Step 1: Scan source files for env var references
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            # ─── Source file scanning ─────────────────────
            if ext in SOURCE_EXTENSIONS:
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                except IOError:
                    continue

                files_scanned += 1

                if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                    _extract_js_env_refs(content, rel_path, env_vars)

                elif ext == ".py":
                    _extract_python_env_refs(content, rel_path, env_vars)

                elif ext == ".rs":
                    _extract_rust_env_refs(content, rel_path, env_vars)

            # ─── .env file scanning ───────────────────────
            elif filename in ENV_FILE_PATTERNS or filename.startswith('.env'):
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                except IOError:
                    continue

                env_file_info = _parse_env_file(content, rel_path, filename)
                env_files.append(env_file_info)

                # Register vars found in .env files
                for var_info in env_file_info["variables"]:
                    var_name_in_file = var_info["name"]
                    if var_name_in_file not in env_vars:
                        env_vars[var_name_in_file] = {
                            "name": var_name_in_file,
                            "referenced_in": [],
                            "has_fallback": True,  # In .env file counts as fallback
                            "is_required": False,
                            "defined_in_env_file": [],
                            "is_in_gitignore": False,
                            "documentation": None,
                            "is_secret": var_info.get("is_secret", False),
                        }
                    env_vars[var_name_in_file]["defined_in_env_file"].append({
                        "file": rel_path,
                        "has_value": var_info.get("has_value", False),
                        "is_commented": var_info.get("is_commented", False),
                    })

    # Step 2: Check .gitignore
    gitignore_patterns = _load_gitignore(workspace)
    env_gitignore_status = _check_env_gitignore(workspace, gitignore_patterns)
    for env_file in env_files:
        env_file["is_gitignored"] = env_file["path"] in env_gitignore_status or any(
            p in env_file["path"] for p in env_gitignore_status
        )

    # Step 3: Determine is_required for each var
    for var_info in env_vars.values():
        has_env_file = bool(var_info["defined_in_env_file"])
        has_fallback = var_info["has_fallback"]
        # Required if no fallback AND not defined in any .env file
        var_info["is_required"] = not has_fallback and not has_env_file

    # Step 4: Apply filter
    if var_name:
        env_vars = {
            k: v for k, v in env_vars.items()
            if var_name.upper() in k.upper()
        }

    # Step 5: Compute stats
    required_vars = [v for v in env_vars.values() if v["is_required"]]
    optional_vars = [v for v in env_vars.values() if not v["is_required"]]
    undocumented = _find_undocumented(env_vars, env_files)
    in_env_file = [v for v in env_vars.values() if v["defined_in_env_file"]]

    # Step 6: Missing from .env.example
    missing_from_example = _find_missing_from_example(env_vars, env_files)

    # Step 7: Required without fallback
    required_without_fallback = [
        {
            "name": v["name"],
            "referenced_in": v["referenced_in"][:5],
        }
        for v in required_vars
        if not v["has_fallback"]
    ]

    # Step 8: Naming inconsistencies
    naming_inconsistencies = _detect_naming_inconsistencies(env_vars)

    # Step 9: Secret detection
    secrets_in_env = _detect_secrets_in_env_files(env_files)

    # Step 10: Recommendations
    recommendations = _generate_recommendations(
        env_vars, required_vars, missing_from_example,
        required_without_fallback, naming_inconsistencies,
        secrets_in_env, env_files, env_gitignore_status
    )

    return {
        "status": "ok",
        "workspace": workspace,
        "stats": {
            "total_vars": len(env_vars),
            "required": len(required_vars),
            "optional": len(optional_vars),
            "undocumented": len(undocumented),
            "in_env_file": len(in_env_file),
            "files_scanned": files_scanned,
        },
        "variables": list(env_vars.values()),
        "missing_from_example": missing_from_example,
        "required_without_fallback": required_without_fallback,
        "naming_inconsistencies": naming_inconsistencies,
        "env_files": env_files,
        "recommendations": recommendations,
    }


# ─── JS/TS Env Var Extraction ─────────────────────────────────

def _extract_js_env_refs(
    content: str, rel_path: str, env_vars: Dict[str, Dict[str, Any]]
):
    """Extract environment variable references from JS/TS source files."""
    lines = content.split('\n')

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Skip comments
        if stripped.startswith('//') or stripped.startswith('/*') or stripped.startswith('*'):
            continue

        # process.env.X
        for m in re.finditer(r'process\.env\.([A-Za-z_]\w*)', line):
            _register_env_ref(
                env_vars, m.group(1), rel_path, i + 1, line.strip(),
                _detect_js_fallback(line, m.group(1))
            )

        # process.env['X'] or process.env["X"]
        for m in re.finditer(r"process\.env\[\s*['\"]([A-Za-z_]\w*)['\"]\s*\]", line):
            _register_env_ref(
                env_vars, m.group(1), rel_path, i + 1, line.strip(),
                _detect_js_fallback(line, m.group(1))
            )

        # import.meta.env.X (Vite, Astro, etc.)
        for m in re.finditer(r'import\.meta\.env\.([A-Za-z_]\w*)', line):
            _register_env_ref(
                env_vars, m.group(1), rel_path, i + 1, line.strip(),
                _detect_js_fallback(line, m.group(1))
            )

        # Destructured: const { X, Y } = process.env
        if re.search(r'\{\s*\w+.*\}\s*=\s*process\.env', line):
            for dm in re.finditer(r'\b([A-Z_][A-Z0-9_]*)\b', line):
                name = dm.group(1)
                if name not in {"ENV", "TRUE", "FALSE", "UNDEFINED", "NULL"}:
                    _register_env_ref(
                        env_vars, name, rel_path, i + 1, line.strip(), False
                    )


def _detect_js_fallback(line: str, var_name: str) -> bool:
    """Detect if a JS env var reference has a fallback value."""
    # ?? 'default' or || 'default'
    pattern = re.escape(var_name)
    if re.search(rf'process\.env\.{pattern}\s*\?\?\s*', line):
        return True
    if re.search(rf'process\.env\.{pattern}\s*\|\|\s*', line):
        return True
    # process.env['X'] ?? or ||
    if re.search(rf"process\.env\[\s*['\"]({pattern})['\"]\s*\]\s*\?\?", line):
        return True
    if re.search(rf"process\.env\[\s*['\"]({pattern})['\"]\s*\]\s*\|\|", line):
        return True
    # import.meta.env.X ?? or ||
    if re.search(rf'import\.meta\.env\.{pattern}\s*\?\?', line):
        return True
    if re.search(rf'import\.meta\.env\.{pattern}\s*\|\|', line):
        return True
    # Ternary with default
    if re.search(rf'process\.env\.{pattern}\s*\?\s*', line):
        return True
    return False


# ─── Python Env Var Extraction ─────────────────────────────────

def _extract_python_env_refs(
    content: str, rel_path: str, env_vars: Dict[str, Dict[str, Any]]
):
    """Extract environment variable references from Python source files."""
    lines = content.split('\n')

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Skip comments
        if stripped.startswith('#'):
            # But check for documentation comments above env var usage
            continue

        # os.environ['X'] — NO fallback (will raise KeyError)
        for m in re.finditer(r"os\.environ\[\s*['\"]([A-Za-z_]\w*)['\"]\s*\]", line):
            _register_env_ref(
                env_vars, m.group(1), rel_path, i + 1, line.strip(), False
            )

        # os.environ.get('X') or os.environ.get('X', 'default')
        for m in re.finditer(r"os\.environ\.get\s*\(\s*['\"]([A-Za-z_]\w*)['\"]", line):
            has_fallback = _detect_python_fallback(line, m.group(1))
            _register_env_ref(
                env_vars, m.group(1), rel_path, i + 1, line.strip(), has_fallback
            )

        # os.getenv('X') or os.getenv('X', 'default')
        for m in re.finditer(r"os\.getenv\s*\(\s*['\"]([A-Za-z_]\w*)['\"]", line):
            has_fallback = _detect_python_fallback(line, m.group(1))
            _register_env_ref(
                env_vars, m.group(1), rel_path, i + 1, line.strip(), has_fallback
            )

        # os.environ.get('X') with or fallback
        for m in re.finditer(
            r"os\.environ\.get\s*\(\s*['\"]([A-Za-z_]\w*)['\"]\s*\)\s*or\s+", line
        ):
            _register_env_ref(
                env_vars, m.group(1), rel_path, i + 1, line.strip(), True
            )

        # dotenv: load_dotenv(), find_dotenv()
        for m in re.finditer(r'load_dotenv\s*\(', line):
            # Just note that dotenv is used in this file
            pass


def _detect_python_fallback(line: str, var_name: str) -> bool:
    """Detect if a Python env var reference has a fallback value."""
    # os.environ.get('X', 'default') — second argument
    pattern = re.escape(var_name)
    if re.search(rf"os\.environ\.get\s*\(\s*['\"]({pattern})['\"]\s*,\s*\S", line):
        return True
    if re.search(rf"os\.getenv\s*\(\s*['\"]({pattern})['\"]\s*,\s*\S", line):
        return True
    # .get('X') or 'default'
    if re.search(rf"os\.environ\.get\s*\(\s*['\"]({pattern})['\"]\s*\)\s*or\s+", line):
        return True
    if re.search(rf"os\.getenv\s*\(\s*['\"]({pattern})['\"]\s*\)\s*or\s+", line):
        return True
    return False


# ─── Rust Env Var Extraction ───────────────────────────────────

def _extract_rust_env_refs(
    content: str, rel_path: str, env_vars: Dict[str, Dict[str, Any]]
):
    """Extract environment variable references from Rust source files."""
    lines = content.split('\n')

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Skip comments
        if stripped.startswith('//'):
            continue

        # std::env::var("X") — returns Result, may panic on unset
        for m in re.finditer(r'std::env::var\s*\(\s*"([A-Za-z_]\w*)"\s*\)', line):
            has_fallback = 'unwrap_or' in line or '.ok()' in line or 'unwrap_or_else' in line
            _register_env_ref(
                env_vars, m.group(1), rel_path, i + 1, line.strip(), has_fallback
            )

        # env!("X") — compile-time, required (will fail to compile if missing)
        for m in re.finditer(r'env!\s*\(\s*"([A-Za-z_]\w*)"\s*\)', line):
            _register_env_ref(
                env_vars, m.group(1), rel_path, i + 1, line.strip(), False
            )

        # option_env!("X") — compile-time, optional (returns Option)
        for m in re.finditer(r'option_env!\s*\(\s*"([A-Za-z_]\w*)"\s*\)', line):
            _register_env_ref(
                env_vars, m.group(1), rel_path, i + 1, line.strip(), True
            )


# ─── Env File Parsing ─────────────────────────────────────────

def _parse_env_file(content: str, rel_path: str, filename: str) -> Dict[str, Any]:
    """Parse a .env file and extract variable definitions."""
    variables = []
    lines = content.split('\n')

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Skip empty lines and comments
        if not stripped or stripped.startswith('#'):
            continue

        # KEY=VALUE or KEY="VALUE" or KEY='VALUE'
        m = re.match(r'^([A-Za-z_]\w*)\s*=\s*(.*)$', stripped)
        if m:
            var_name = m.group(1)
            raw_value = m.group(2).strip()

            # Remove surrounding quotes
            has_value = bool(raw_value)
            if (raw_value.startswith('"') and raw_value.endswith('"')) or \
               (raw_value.startswith("'") and raw_value.endswith("'")):
                raw_value = raw_value[1:-1]
                has_value = bool(raw_value)

            is_secret = _is_secret_var(var_name, raw_value)

            variables.append({
                "name": var_name,
                "has_value": has_value,
                "is_commented": False,
                "line": i + 1,
                "is_secret": is_secret,
                "value_preview": _mask_secret_value(var_name, raw_value) if is_secret else (raw_value[:30] if has_value else None),
            })

    # Determine env file type
    file_type = "unknown"
    if filename == ".env":
        file_type = "base"
    elif filename == ".env.example" or filename == ".env.sample" or filename == ".env.template":
        file_type = "example"
    elif ".local" in filename:
        file_type = "local"
    elif ".production" in filename or ".prod" in filename:
        file_type = "production"
    elif ".development" in filename or ".dev" in filename:
        file_type = "development"
    elif ".staging" in filename:
        file_type = "staging"
    elif ".test" in filename or ".ci" in filename:
        file_type = "test"

    return {
        "path": rel_path,
        "filename": filename,
        "type": file_type,
        "variable_count": len(variables),
        "variables": variables,
        "is_gitignored": False,  # Updated later
    }


def _is_secret_var(var_name: str, value: str) -> bool:
    """Determine if a variable is likely a secret based on name and value."""
    lower_name = var_name.lower()

    # Check name patterns
    for keyword in SECRET_KEYWORDS:
        if keyword in lower_name:
            # Exclude common non-secret patterns
            is_non_secret = any(ns in lower_name for ns in NON_SECRET_PATTERNS)
            if not is_non_secret:
                return True

    # Check value patterns (looks like a real secret)
    if value:
        # Long random-looking strings are likely secrets
        if len(value) >= 32 and re.match(r'^[A-Za-z0-9+/=_-]+$', value):
            return True
        # Looks like a private key
        if '-----BEGIN' in value:
            return True
        # Connection strings with passwords
        if re.search(r'://[^:]+:([^@]+)@', value):
            return True

    return False


def _mask_secret_value(var_name: str, value: str) -> str:
    """Mask a secret value, showing only the first and last chars."""
    if not value or len(value) < 8:
        return "***"
    return f"{value[:3]}...{value[-3:]}"


# ─── .gitignore Handling ───────────────────────────────────────

def _load_gitignore(workspace: str) -> List[str]:
    """Load .gitignore patterns from the workspace."""
    patterns = []
    gitignore_path = os.path.join(workspace, ".gitignore")

    if os.path.exists(gitignore_path):
        try:
            with open(gitignore_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith('#'):
                        patterns.append(stripped)
        except IOError:
            pass

    return patterns


def _check_env_gitignore(workspace: str, patterns: List[str]) -> Set[str]:
    """Check which .env-related paths are covered by .gitignore."""
    gitignored = set()

    # Common .gitignore patterns for env files
    env_patterns = {".env", ".env.local", ".env.*.local", ".env.production", ".env.development"}

    for pattern in patterns:
        # Direct match
        if pattern in env_patterns or pattern.startswith(".env"):
            gitignored.add(pattern)
        # Wildcard patterns
        if pattern == "*.env" or pattern == ".env*":
            gitignored.update(env_patterns)
        # .env.*.local
        if ".env" in pattern:
            gitignored.add(pattern)

    return gitignored


# ─── Helper: Register Env Var Reference ────────────────────────

def _register_env_ref(
    env_vars: Dict[str, Dict[str, Any]],
    name: str,
    rel_path: str,
    line_num: int,
    context: str,
    has_fallback: bool
):
    """Register an environment variable reference."""
    if name not in env_vars:
        env_vars[name] = {
            "name": name,
            "referenced_in": [],
            "has_fallback": has_fallback,
            "is_required": not has_fallback,
            "defined_in_env_file": [],
            "is_in_gitignore": False,
            "documentation": None,
            "is_secret": _is_secret_var(name, ""),
        }

    # Update fallback: if any reference has a fallback, mark it
    if has_fallback:
        env_vars[name]["has_fallback"] = True

    # Add reference
    env_vars[name]["referenced_in"].append({
        "file": rel_path,
        "line": line_num,
        "context": context[:150],
    })

    # Update secret status
    if _is_secret_var(name, ""):
        env_vars[name]["is_secret"] = True


# ─── Undocumented Vars ─────────────────────────────────────────

def _find_undocumented(
    env_vars: Dict[str, Dict[str, Any]],
    env_files: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Find env vars referenced in code but not documented in .env.example."""
    # Collect vars from .env.example files
    example_vars = set()
    for env_file in env_files:
        if env_file["type"] == "example":
            for var in env_file["variables"]:
                example_vars.add(var["name"])

    undocumented = []
    for name, info in env_vars.items():
        if name not in example_vars and not info["defined_in_env_file"]:
            # Only flag vars that are referenced in source code
            if info["referenced_in"]:
                undocumented.append({
                    "name": name,
                    "referenced_in": info["referenced_in"][:3],
                    "is_required": info["is_required"],
                })

    return undocumented


# ─── Missing from .env.example ─────────────────────────────────

def _find_missing_from_example(
    env_vars: Dict[str, Dict[str, Any]],
    env_files: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Find env vars referenced in code but missing from .env.example."""
    # Collect vars from .env.example
    example_vars = set()
    has_example = False
    for env_file in env_files:
        if env_file["type"] == "example":
            has_example = True
            for var in env_file["variables"]:
                example_vars.add(var["name"])

    if not has_example:
        return []  # No example file — skip this check

    missing = []
    for name, info in env_vars.items():
        if name not in example_vars and info["referenced_in"]:
            missing.append({
                "name": name,
                "is_required": info["is_required"],
                "referenced_in_count": len(info["referenced_in"]),
            })

    return sorted(missing, key=lambda x: (not x["is_required"], -x["referenced_in_count"]))


# ─── Naming Inconsistencies ────────────────────────────────────

def _detect_naming_inconsistencies(
    env_vars: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Detect inconsistent naming conventions across env vars."""
    if not env_vars:
        return []

    inconsistencies = []
    snake_case_vars = []
    camel_case_vars = []
    kebab_case_vars = []
    lower_case_vars = []

    for name in env_vars:
        if '_' in name and name.upper() == name:
            snake_case_vars.append(name)
        elif '-' in name:
            kebab_case_vars.append(name)
        elif re.search(r'[a-z]', name) and re.search(r'[A-Z]', name) and name.upper() != name:
            camel_case_vars.append(name)
        elif name.lower() == name and '_' not in name:
            lower_case_vars.append(name)

    # Convention conflicts
    conventions = {
        "SCREAMING_SNAKE_CASE": len(snake_case_vars),
        "camelCase": len(camel_case_vars),
        "kebab-case": len(kebab_case_vars),
        "lowercase": len(lower_case_vars),
    }

    active_conventions = {k: v for k, v in conventions.items() if v > 0}

    if len(active_conventions) > 1:
        dominant = max(active_conventions, key=active_conventions.get)
        for conv, count in active_conventions.items():
            if conv != dominant:
                example_vars = []
                if conv == "SCREAMING_SNAKE_CASE":
                    example_vars = snake_case_vars[:3]
                elif conv == "camelCase":
                    example_vars = camel_case_vars[:3]
                elif conv == "kebab-case":
                    example_vars = kebab_case_vars[:3]
                elif conv == "lowercase":
                    example_vars = lower_case_vars[:3]

                inconsistencies.append({
                    "type": "naming_mismatch",
                    "convention": conv,
                    "dominant_convention": dominant,
                    "count": count,
                    "examples": example_vars,
                    "severity": "info",
                    "message": f"{count} vars use {conv} but dominant style is {dominant}",
                    "suggestion": f"Rename to follow {dominant} convention for consistency.",
                })

    return inconsistencies


# ─── Secret Detection in .env Files ────────────────────────────

def _detect_secrets_in_env_files(
    env_files: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Detect secrets that are stored in .env files and should be in a secret manager."""
    secrets = []

    for env_file in env_files:
        # Skip example/template files
        if env_file["type"] in {"example", "template"}:
            continue

        for var in env_file["variables"]:
            if var.get("is_secret") and var.get("has_value"):
                secrets.append({
                    "name": var["name"],
                    "file": env_file["path"],
                    "file_type": env_file["type"],
                    "line": var.get("line", 0),
                    "severity": "critical" if env_file["type"] == "base" else "warning",
                    "message": f"Secret '{var['name']}' stored in {env_file['filename']}",
                    "suggestion": "Move to a secret manager (AWS Secrets Manager, Vault, etc.) or use sealed secrets.",
                })

    return secrets


# ─── Recommendations ──────────────────────────────────────────

def _generate_recommendations(
    env_vars: Dict[str, Dict[str, Any]],
    required_vars: List[Dict[str, Any]],
    missing_from_example: List[Dict[str, Any]],
    required_without_fallback: List[Dict[str, Any]],
    naming_inconsistencies: List[Dict[str, Any]],
    secrets_in_env: List[Dict[str, Any]],
    env_files: List[Dict[str, Any]],
    gitignore_status: Set[str],
) -> List[Dict[str, Any]]:
    """Generate actionable recommendations for env var management."""
    recommendations = []

    # Required vars without fallback (deployment risk)
    if required_without_fallback:
        recommendations.append({
            "type": "deployment_risk",
            "severity": "critical",
            "message": f"{len(required_without_fallback)} env vars have no fallback and will crash if missing",
            "affected": [v["name"] for v in required_without_fallback[:10]],
            "suggestion": "Add fallback values or document these as required in deployment docs and .env.example.",
        })

    # Missing .env.example
    has_example = any(ef["type"] == "example" for ef in env_files)
    if not has_example and env_vars:
        recommendations.append({
            "type": "documentation",
            "severity": "warning",
            "message": "No .env.example file found",
            "suggestion": "Create a .env.example file documenting all required env vars with placeholder values.",
        })

    # Missing from .env.example
    if missing_from_example:
        recommendations.append({
            "type": "documentation",
            "severity": "warning",
            "message": f"{len(missing_from_example)} env vars referenced in code but missing from .env.example",
            "affected": [v["name"] for v in missing_from_example[:10]],
            "suggestion": "Add missing vars to .env.example so new developers know what to configure.",
        })

    # Secrets in .env files
    if secrets_in_env:
        critical_secrets = [s for s in secrets_in_env if s["severity"] == "critical"]
        if critical_secrets:
            recommendations.append({
                "type": "security",
                "severity": "critical",
                "message": f"{len(critical_secrets)} secrets found in base .env files",
                "affected": [s["name"] for s in critical_secrets[:10]],
                "suggestion": "Move secrets to a secret manager. Use .env for non-secret config only.",
            })

    # .env files not gitignored
    unignored_env_files = [
        ef for ef in env_files
        if not ef.get("is_gitignored") and ef["type"] not in {"example", "template"}
    ]
    if unignored_env_files:
        recommendations.append({
            "type": "security",
            "severity": "critical",
            "message": f"{len(unignored_env_files)} .env file(s) may not be in .gitignore",
            "affected": [ef["filename"] for ef in unignored_env_files],
            "suggestion": "Add .env and .env.* to .gitignore to prevent committing secrets.",
        })

    # Naming inconsistencies
    if naming_inconsistencies:
        dominant = naming_inconsistencies[0].get("dominant_convention", "SCREAMING_SNAKE_CASE")
        recommendations.append({
            "type": "convention",
            "severity": "info",
            "message": f"Env var naming is inconsistent across the project",
            "affected": [ni["convention"] for ni in naming_inconsistencies],
            "suggestion": f"Standardize on {dominant} for all env var names.",
        })

    # Too many env vars (configuration complexity)
    if len(env_vars) > 50:
        recommendations.append({
            "type": "architecture",
            "severity": "warning",
            "message": f"{len(env_vars)} env vars detected — high configuration complexity",
            "suggestion": "Consider consolidating config into fewer, structured config files or a config service.",
        })

    # Duplicate definitions across .env files
    var_file_map: Dict[str, List[str]] = defaultdict(list)
    for ef in env_files:
        for var in ef["variables"]:
            var_file_map[var["name"]].append(ef["filename"])

    inconsistent_defs = {
        name: files for name, files in var_file_map.items()
        if len(files) > 2
    }
    if inconsistent_defs:
        recommendations.append({
            "type": "maintenance",
            "severity": "info",
            "message": f"{len(inconsistent_defs)} env vars defined in 3+ .env files",
            "affected": list(inconsistent_defs.keys())[:10],
            "suggestion": "Use a base .env with overrides per environment. Avoid duplicating vars across many files.",
        })

    # Python dotenv not detected
    py_files_with_env = [
        v for v in env_vars.values()
        if any(r["file"].endswith('.py') for r in v.get("referenced_in", []))
    ]
    if py_files_with_env:
        uses_dotenv = any(
            any('dotenv' in r.get("context", "").lower() or 'load_dotenv' in r.get("context", "")
                for r in v.get("referenced_in", []))
            for v in env_vars.values()
        )
        if not uses_dotenv:
            recommendations.append({
                "type": "best_practice",
                "severity": "info",
                "message": "Python files reference env vars but no dotenv usage detected",
                "suggestion": "Consider using python-dotenv to load .env files during development.",
            })

    return recommendations
