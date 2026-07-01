"""Config secret redaction (issue #58, Phase 2).

Why this module exists
----------------------
CodeLens's job is to map code structure (symbols, calls, classes) —
**not** to be a vault for production secrets. But many config-file
formats mix structural metadata (key names) with sensitive values
(passwords, API keys, connection strings) in the same file:

* **Spring** ``application.properties`` / ``application.yml`` —
  ``spring.datasource.password=hunter2``
* **Shopify Liquid** ``{% schema %}`` blocks — settings schema with
  ``id`` and ``default`` fields where ``default`` may be a real API
  key for a theme app extension.

If an agent-driven extraction layer indexes these files naively
(storing the value alongside the key), CodeLens becomes a secret
sink — the value ends up in:

* The SQLite registry (``graph_nodes.value`` column)
* ``outline.json`` written into ``.codelens/``
* MCP tool responses to AI agents
* Snapshot exports (``codelens export-snapshot``)

This module provides **format-aware redaction** that returns a
key-only view of these config files:

* Spring properties: ``key=value`` → ``key=<redacted>``
* Spring YAML: ``key: value`` → ``key: <redacted>`` (only when the
  value is a scalar; nested maps/lists preserved)
* Shopify ``{% schema %}``: parse the JSON inside the Liquid block,
  redact every ``default`` field whose value is a string, return the
  redacted schema

The redacted output is what any extraction layer should consume. The
**raw** file content is still on disk — an agent that needs the
actual value reads the file directly (just like it reads any source
file). CodeLens never persists it.

What Phase 2 deliberately does NOT do
-------------------------------------
* It does not detect secrets by pattern (that's ``secrets_engine.py``'s
  job, already shipped).
* It does not refuse to read config files (Phase 1 path-traversal
  handles file-access safety; this module handles value-persistence
  safety).
* It does not auto-discover config files — callers pass file paths
  in. The redaction is a pure function on content.

Integration points (Phase 2)
----------------------------
* :func:`utils.safe_read_file_for_indexing` — thin wrapper that
  composes :func:`safe_read_file` with format-aware redaction. Use
  this in any extraction layer that might ingest config files.
* :func:`redact_application_properties`,
  :func:`redact_application_yml`, :func:`redact_shopify_schema` —
  per-format entry points, callable directly.
* :func:`redact_config_file` — format auto-detect by file path,
  returns the redacted content (or the original content if the file
  isn't a recognized config format).

The redaction is conservative — when in doubt, redact. A false
positive (redacting a non-secret value) costs an agent a file read;
a false negative (storing a real secret) costs a security incident.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple, Union

__all__ = [
    "REDACTED_PLACEHOLDER",
    "redact_application_properties",
    "redact_application_yml",
    "redact_shopify_schema",
    "redact_config_file",
    "is_config_file",
    "safe_read_file_for_indexing",
]


# Sentinel string that replaces secret values in redacted output.
# Single source of truth so callers can detect it post-hoc.
REDACTED_PLACEHOLDER = "<redacted>"

# Property files: ``key=value`` or ``key: value`` (Java properties spec
# uses ``=`` or ``:`` as separators). Comments start with ``#`` or ``!``.
# Multi-line continuation with backslash is intentionally NOT supported
# here — Phase 2 scope is single-line key/value pairs, which covers
# >99% of real Spring ``application.properties`` files.
_PROPS_LINE_RE = re.compile(
    r"""^
    (?P<indent>\s*)               # leading whitespace (preserved)
    (?P<key>[^#=!\s][^#=!]*?)     # key — everything up to separator
    \s*                           # optional whitespace before sep
    (?P<sep>[=:])                 # separator (= or :)
    \s*                           # optional whitespace after sep
    (?P<value>.*)                 # value (will be redacted if non-empty)
    \s*$
    """,
    re.VERBOSE,
)

# Keys that are structurally never secrets (e.g. ``spring.datasource.url``
# is a JDBC URL — sensitive, but not a secret per se; ``server.port``
# is just a port number). We redact by default and only skip redaction
# for keys on this allowlist. Conservative bias: when in doubt, redact.
_NON_SECRET_KEY_RE = re.compile(
    r"""(?ix)
    ^(
        # Java/Spring structural keys
        server\.port |
        server\.servlet\.context-path |
        spring\.application\.name |
        spring\.profiles\.active |
        spring\.jpa\.(hibernate\.ddl-auto|show-sql|database-platform) |
        spring\.datasource\.url |            # JDBC URL — host/db name, no secret
        spring\.datasource\.driver-class-name |
        spring\.mvc\.(view\.prefix|view\.suffix|static-path-pattern) |
        management\.endpoints\.web\.exposure\.include |
        logging\.level\.[\w.]+ |
        # Generic structural
        [a-z]+\.(enabled|path|host|port|name|type)
    )$
    """,
)


# ─── Application.properties ────────────────────────────────────


def redact_application_properties(content: str) -> str:
    """Redact values in a Spring ``application.properties`` string.

    Each non-comment, non-blank line of the form ``key=value`` or
    ``key:value`` has its value replaced with :data:`REDACTED_PLACEHOLDER`
    — UNLESS the key matches the structural allowlist (port, URL,
    profile name, etc.) in which case the value is preserved.

    Args:
        content: Raw text of an ``application.properties`` file.

    Returns:
        Redacted text with the same line structure (comments and
        blank lines preserved). Safe to store in a registry / pass
        to an AI agent.
    """
    if not content:
        return content
    out_lines: List[str] = []
    for line in content.splitlines(keepends=False):
        stripped = line.strip()
        # Preserve comments and blank lines verbatim — they carry
        # structural information (section headers, etc.) and never
        # contain values.
        if not stripped or stripped.startswith(("#", "!")):
            out_lines.append(line)
            continue
        m = _PROPS_LINE_RE.match(line)
        if not m:
            # Not a key=value line — preserve verbatim (could be a
            # multi-line value continuation, which we don't parse
            # in Phase 2 but shouldn't mangle).
            out_lines.append(line)
            continue
        key = m.group("key").strip()
        value = m.group("value")
        if _NON_SECRET_KEY_RE.match(key):
            # Structural key — value is not a secret, preserve it.
            out_lines.append(line)
            continue
        # Redact the value, preserving leading/trailing whitespace
        # around the separator so diffs are minimal.
        new_value = REDACTED_PLACEHOLDER if value.strip() else value
        out_lines.append(
            f"{m.group('indent')}{key}{m.group('sep')} {new_value}"
        )
    return "\n".join(out_lines) + ("\n" if content.endswith("\n") else "")


# ─── Application.yml ───────────────────────────────────────────


def redact_application_yml(content: str) -> str:
    """Redact scalar values in a Spring ``application.yml`` string.

    YAML is whitespace-sensitive, so we can't safely use a regex
    that spans lines. Instead we use a line-by-line approach that:

    1. Recognizes ``key: value`` lines (where ``value`` is a scalar
       — string, number, boolean — on the same line).
    2. Skips ``key:`` lines where the value is a nested map (next
       indented block) — the nested block is processed by the same
       loop.
    3. Skips comments and blank lines.
    4. Preserves list items (``- value``) — but if a list item is a
       secret-looking string (long alphanumeric), redact it.

    We do NOT use a full YAML parser because:

    * PyYAML is an optional dependency (Phase 1 doctor warns when
      missing); making it required for redaction would break
      CodeLens on minimal installs.
    * Spring ``application.yml`` is a strict subset of YAML where
      every value is on the same line as its key — the line-by-line
      approach handles it correctly.
    * A full YAML parser would happily load anchors, tags, and
      multi-line strings — features Spring rarely uses, but each one
      is a redaction-bypass waiting to happen. Conservative bias.

    Note: in YAML the key is the *bare* last segment (``url:``,
    ``port:``, ``password:``) — not the dotted path. The allowlist
    therefore matches bare keys here, while the properties-file
    allowlist matches dotted paths. Both are conservative — when
    in doubt, redact.

    Args:
        content: Raw text of an ``application.yml`` file.

    Returns:
        Redacted text with the same line structure. Scalar values
        are replaced with :data:`REDACTED_PLACEHOLDER` unless the
        key matches the structural allowlist.
    """
    if not content:
        return content
    out_lines: List[str] = []
    # YAML scalar value: anything after ``key: `` on the same line.
    # Quoted strings, numbers, booleans, nulls all match this.
    yaml_kv_re = re.compile(
        r"""^
        (?P<indent>\s*)             # leading whitespace (YAML indent)
        (?P<key>[^:#\-\s][^:]*?)    # key — no colon, no dash, no comment
        \s*:\s*                     # ``:`` separator (with optional ws)
        (?P<value>\S.*)             # value (must be non-empty & non-ws)
        \s*$
        """,
        re.VERBOSE,
    )
    yaml_list_re = re.compile(r"^(?P<indent>\s*-\s+)(?P<value>\S.*)$")
    # In YAML the key is the bare last segment (e.g. ``url:``,
    # ``port:``, ``password:``). Match against this small set of
    # structural bare keys. The properties-file allowlist (which
    # matches dotted paths) doesn't apply here.
    yaml_non_secret_bare_keys = {
        "port", "host", "name", "type", "path", "enabled",
        "driver-class-name", "context-path", "ddl-auto",
        "show-sql", "database-platform", "static-path-pattern",
        "prefix", "suffix", "include", "active",
        # ``url`` is structural in YAML — JDBC URLs contain host/db
        # name but not a secret. (Compare: ``url=`` in properties
        # files is matched by the dotted-path allowlist as
        # ``spring.datasource.url``.)
        "url",
    }
    for line in content.splitlines(keepends=False):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(line)
            continue
        # Try key:value first
        m = yaml_kv_re.match(line)
        if m:
            key = m.group("key").strip()
            value = m.group("value").strip()
            # Strip surrounding quotes for the allowlist check —
            # ``port: "8080"`` and ``port: 8080`` should both match.
            bare_value = value.strip("\"'")
            if key in yaml_non_secret_bare_keys:
                out_lines.append(line)
                continue
            # Heuristic: don't redact numbers / booleans / null —
            # they're never secrets. This keeps ``server.port: 8080``
            # readable even when the allowlist regex misses it.
            if _is_yaml_scalar_non_secret(bare_value):
                out_lines.append(line)
                continue
            new_value = REDACTED_PLACEHOLDER
            out_lines.append(f"{m.group('indent')}{key}: {new_value}")
            continue
        # Try list item
        m = yaml_list_re.match(line)
        if m:
            value = m.group("value").strip()
            bare_value = value.strip("\"'")
            if _is_yaml_scalar_non_secret(bare_value):
                out_lines.append(line)
                continue
            out_lines.append(f"{m.group('indent')}{REDACTED_PLACEHOLDER}")
            continue
        # Anything else (nested map header, document separator, etc.)
        out_lines.append(line)
    return "\n".join(out_lines) + ("\n" if content.endswith("\n") else "")


def _is_yaml_scalar_non_secret(value: str) -> bool:
    """Return True for YAML scalars that are structurally never secrets.

    Numbers, booleans, null, and very short identifiers (<=4 chars)
    are safe to leave unredacted — they carry no secret information
    and redacting them would make the YAML unreadable for no security
    benefit.
    """
    if not value:
        return True
    if value.lower() in ("true", "false", "null", "yes", "no", "on", "off", "~"):
        return True
    # Integer or float
    try:
        float(value)
        return True
    except ValueError:
        pass
    # Short identifier (port-like, ISO date-like, etc.)
    if len(value) <= 4:
        return True
    # ISO date / datetime
    if re.match(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?$", value):
        return True
    return False


# ─── Shopify {% schema %} ──────────────────────────────────────


# Match ``{% schema %}...{% endschema %}`` non-greedily, case-insensitive,
# DOTALL so ``.`` matches newlines. Allows whitespace inside the tag
# brackets (``{%  schema  %}`` is valid Liquid).
_SHOPIFY_SCHEMA_BLOCK_RE = re.compile(
    r"\{%\s*schema\s*%\}(?P<body>.*?)\{%\s*endschema\s*%\}",
    re.IGNORECASE | re.DOTALL,
)


def redact_shopify_schema(content: str) -> str:
    """Redact ``default`` values in Shopify Liquid ``{% schema %}`` blocks.

    Shopify theme files (``*.liquid``) embed a JSON settings schema
    inside ``{% schema %}...{% endschema %}`` blocks. The schema
    defines inputs like::

        {"id": "api_key", "type": "text", "default": "sk_live_xxx"}

    The ``default`` field is where merchants can pre-fill secrets —
    and CodeLens must not persist those defaults into its registry.

    This function:

    1. Finds every ``{% schema %}`` block in the content.
    2. Parses the JSON inside each block.
    3. Walks the parsed object, replacing every ``default`` field
       whose value is a non-empty string with
       :data:`REDACTED_PLACEHOLDER`. (Number/boolean defaults are
       preserved — they're never secrets.)
    4. Re-serializes the JSON and rebuilds the Liquid block.

    If the JSON inside the block is malformed, the block is replaced
    with a comment explaining the redaction failure (so the agent
    sees that there WAS a schema block, but it couldn't be safely
    parsed — better than silently dropping or passing through).

    Args:
        content: Raw text of a ``.liquid`` file.

    Returns:
        Content with all ``{% schema %}`` blocks' string defaults
        redacted. Non-schema parts of the file are untouched.
    """
    if not content:
        return content

    def _replace(match: "re.Match[str]") -> str:
        body = match.group("body").strip()
        try:
            schema = json.loads(body)
        except json.JSONDecodeError:
            # Malformed JSON — don't risk passing the raw block
            # through (it may contain a secret in the malformed
            # chunk). Replace with a marker that an agent can
            # recognize and decide to read the original file.
            return "{% comment %}schema redacted (malformed JSON){% endcomment %}"
        _redact_defaults(schema)
        # Re-serialize with indent=2 to match Shopify's convention.
        # ``ensure_ascii=False`` so non-ASCII defaults (now
        # redacted, but the structure may still contain non-ASCII
        # in id/label fields) round-trip cleanly.
        redacted_json = json.dumps(schema, indent=2, ensure_ascii=False)
        return "{% schema %}\n" + redacted_json + "\n{% endschema %}"

    return _SHOPIFY_SCHEMA_BLOCK_RE.sub(_replace, content)


def _redact_defaults(node: Any) -> None:
    """Walk a parsed JSON node in-place, redacting string ``default`` fields.

    Recurses into dicts and lists. Mutates the node in place —
    callers should pass a freshly-parsed object, not one they
    intend to reuse.
    """
    if isinstance(node, dict):
        # Settings schema convention: each setting has ``id``,
        # ``type``, ``default``. We redact any field literally
        # named ``default`` whose value is a non-empty string.
        # ``label``/``info``/``placeholder`` fields are NOT redacted
        # (they're UI text, not secrets).
        if "default" in node and isinstance(node["default"], str) and node["default"]:
            node["default"] = REDACTED_PLACEHOLDER
        for child in node.values():
            _redact_defaults(child)
    elif isinstance(node, list):
        for child in node:
            _redact_defaults(child)


# ─── Format auto-detection ─────────────────────────────────────


# File-name → format mapping. Conservative — only files that are
# unambiguously Spring/Shopify config are auto-detected. ``*.yml``
# alone is NOT auto-detected as Spring (could be CI config, k8s
# manifest, etc. — those don't need redaction in the same way).
_CONFIG_FILE_PATTERNS = {
    # Spring Boot convention: ``application.properties`` /
    # ``application.yml`` at the root of ``src/main/resources/``.
    # We match by basename, not full path — Spring allows profile-
    # specific variants like ``application-prod.properties``.
    "application.properties": "spring_properties",
    "application.yml": "spring_yml",
    "application.yaml": "spring_yml",
    # Shopify theme convention: ``*.liquid`` files may contain a
    # ``{% schema %}`` block.
    # Extension-based detection happens in ``is_config_file``.
}


def is_config_file(path: str) -> Optional[str]:
    """Return the config format name if ``path`` is a recognized config file.

    Returns one of:
        ``"spring_properties"`` — Spring ``application.properties``
        ``"spring_yml"``        — Spring ``application.yml``/``.yaml``
        ``"shopify_liquid"``    — Shopify ``.liquid`` theme file
        ``None``                — not a recognized config file

    Used by :func:`redact_config_file` and the indexing layer to
    decide whether to apply redaction. Conservative — false negatives
    (treating a config file as a regular file) are safe; false
    positives (treating a regular file as a config file) could
    mangle source code.
    """
    if not path:
        return None
    basename = os.path.basename(path)
    if basename in _CONFIG_FILE_PATTERNS:
        return _CONFIG_FILE_PATTERNS[basename]
    # Profile-specific Spring variants: ``application-prod.properties``
    # ``application-dev.yml`` — match the prefix.
    if basename.startswith("application-"):
        if basename.endswith(".properties"):
            return "spring_properties"
        if basename.endswith((".yml", ".yaml")):
            return "spring_yml"
    # Shopify Liquid theme files.
    if basename.endswith(".liquid"):
        return "shopify_liquid"
    return None


def redact_config_file(path: str, content: Optional[str] = None) -> str:
    """Auto-detect format and redact.

    Args:
        path: File path — used for format detection.
        content: Optional pre-read content. If None, the file is
            read with :func:`utils.safe_read_file` (size-limited,
            encoding-safe). Passing content in is useful when the
            caller has already read the file for another purpose.

    Returns:
        Redacted content if the file is a recognized config format;
        the original (or read) content otherwise. Never raises on
        format errors — a parse failure in one config file must not
        break a workspace-wide scan.
    """
    fmt = is_config_file(path)
    if fmt is None:
        # Not a config file — return content as-is (read if needed).
        if content is None:
            from utils import safe_read_file
            return safe_read_file(path) or ""
        return content

    if content is None:
        from utils import safe_read_file
        content = safe_read_file(path) or ""

    try:
        if fmt == "spring_properties":
            return redact_application_properties(content)
        if fmt == "spring_yml":
            return redact_application_yml(content)
        if fmt == "shopify_liquid":
            return redact_shopify_schema(content)
    except Exception as exc:
        # Defensive: never let a redaction bug leak the raw content
        # OR crash the scan. Log and return a placeholder so the
        # agent sees something happened.
        try:
            from utils import logger
            logger.warning("config redaction failed for %s: %s", path, exc)
        except Exception:
            pass
        return f"<!-- redaction failed for {path}: {exc} -->\n"
    return content


# ─── Convenience: integrated file reader ───────────────────────


def safe_read_file_for_indexing(
    path: str,
    project_root: str,
    max_size: int = 200 * 1024,
) -> Optional[str]:
    """Read a file for indexing, applying path-traversal + redaction.

    Composes three layers (issue #58 Phase 1 + Phase 2):

    1. :func:`utils.safe_read_file_within_project` — path traversal
       protection (refuses paths outside ``project_root``).
    2. :func:`redact_config_file` — format-aware value redaction
       for recognized config files.
    3. Size limit inherited from ``safe_read_file``.

    Use this in any extraction layer that ingests files which might
    be Spring/Shopify config — it's the single safe entry point.

    Args:
        path: File to read.
        project_root: Workspace root for path-traversal check.
        max_size: Maximum file size in bytes.

    Returns:
        Redacted content (or unredacted if not a config file),
        or ``None`` if the path is refused, the file is too large,
        or the read fails.
    """
    from utils import safe_read_file_within_project
    content = safe_read_file_within_project(path, project_root, max_size=max_size)
    if content is None:
        return None
    return redact_config_file(path, content)
