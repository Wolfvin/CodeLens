"""CodeLens security hardening modules (issue #58).

This package groups together the security-related helpers that protect
CodeLens — and the AI agents driving it — from untrusted input:

* :mod:`scripts.security.path_traversal` — symlink-aware path
  confinement to the project root (Phase 1 of issue #58).
* :mod:`scripts.security.config_secret_redaction` — format-aware
  redaction of Spring ``application.properties`` / ``application.yml``
  and Shopify Liquid ``{% schema %}`` defaults (Phase 2 of issue #58).

Future phases will add git safety guard, Secretlint integration,
file system MCP tools, and LLM output schema validation.
"""

# Phase 1 — always available (no optional deps).
from .path_traversal import (
    PathRefusalError,
    is_path_within_project,
    resolve_path_within_project,
    safe_resolve_path,
)

# Phase 2 — always available (no optional deps; uses stdlib json/re only).
from .config_secret_redaction import (
    REDACTED_PLACEHOLDER,
    redact_application_properties,
    redact_application_yml,
    redact_shopify_schema,
    redact_config_file,
    is_config_file,
    safe_read_file_for_indexing,
)

__all__ = [
    # Phase 1 — path traversal
    "PathRefusalError",
    "is_path_within_project",
    "resolve_path_within_project",
    "safe_resolve_path",
    # Phase 2 — config secret redaction
    "REDACTED_PLACEHOLDER",
    "redact_application_properties",
    "redact_application_yml",
    "redact_shopify_schema",
    "redact_config_file",
    "is_config_file",
    "safe_read_file_for_indexing",
]
