"""Output formatting for CodeLens CLI."""

import json
from typing import Any
from formatters.markdown import to_markdown


def format_output(data: Any, format_type: str = "json", command: str = "") -> str:
    """Format output data as JSON or Markdown."""
    if format_type == "markdown":
        return to_markdown(data, command)
    # Default: JSON
    return json.dumps(data, indent=2, ensure_ascii=False)
