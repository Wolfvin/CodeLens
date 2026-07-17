# @WHO:   scripts/commands/tags.py
# @WHAT:  Thin CLI wrapper for the doc-tag audit — delegates to tag_audit_engine
# @PART:  command (sub-check of `context`)
# @ENTRY: execute()
"""`context --check tags` — audit the @FLOW/@ENTRY/@PART doc-tag convention.

Inventories named flows, measures header coverage, and lists untagged /
partially-tagged files, all from the tags already present in the source. Pure
read-only scan (issue #305). The real work lives in ``tag_audit_engine``.
"""

from typing import Any, Dict

from tag_audit_engine import audit_tags


def add_args(parser):
    """Register CLI arguments (workspace is carried by the umbrella)."""
    parser.add_argument(
        "workspace", nargs="?", default=None,
        help="Path to workspace root (auto-detected if omitted)",
    )


def execute(args, workspace) -> Dict[str, Any]:
    """Run the tag audit for ``workspace``.

    @FLOW:    TAG_AUDIT
    @CALLS:   tag_audit_engine.audit_tags() -> dict
    @MUTATES: nothing (read-only)
    """
    return audit_tags(workspace)
