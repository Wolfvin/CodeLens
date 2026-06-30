"""CodeLens memory package — Serena-style markdown memory system (issue #60).

Exposes the :mod:`memory_manager` module which implements CRUD for project
and global memory files plus ``mem:NAME`` reference validation.

Storage layout:
- Project memory: ``<workspace>/.codelens/memories/<topic>.md``
- Global memory:  ``~/.codelens/memories/global/<topic>.md`` (read-only via CLI)
"""

from . import memory_manager  # noqa: F401  (re-export for convenience)

__all__ = ["memory_manager"]
