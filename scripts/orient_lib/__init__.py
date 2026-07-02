# @WHO:   scripts/orient_lib/__init__.py
# @WHAT:  Orient analyzers sub-package — repo orientation brief
# @PART:  orient_lib
# @ENTRY: (package marker only)

"""Orient analyzers sub-package: helpers for the ``codelens orient`` command.

Named ``orient_lib`` (not ``orient``) to avoid a Python import collision
with ``scripts/commands/orient.py`` — both would claim the top-level
``orient`` module name. See issue #160 PR description for details.

Modules:
    framework_db     — data-driven framework lookup table (ecosystem -> packages)
    manifest_parser  — run/build/test command extraction from manifest files
    file_ranker      — Start Here scoring logic for source files
"""

from .framework_db import detect_frameworks_brief, ECOSYSTEM_FRAMEWORKS
from .manifest_parser import extract_commands
from .file_ranker import rank_start_here_files

__all__ = [
    "detect_frameworks_brief",
    "ECOSYSTEM_FRAMEWORKS",
    "extract_commands",
    "rank_start_here_files",
]
