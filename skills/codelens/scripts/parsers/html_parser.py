"""
HTML Parser for CodeLens
Extracts all `id` and `class` attributes from HTML elements.

Rules:
- id="xxx" → register as type `id`
- class="a b c" → split by space, register each as type `class`
- If same id found in >1 element → flag `collision`
- Ignore: ids/classes inside comments <!-- -->
- Ignore: template literals like id="{{ variable }}"
"""

import re
from typing import Dict, List, Any, Tuple


def strip_html_comments(content: str) -> str:
    """Remove HTML comments before parsing."""
    return re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)


def extract_html_references(content: str, file_path: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Extract id and class references from HTML content.

    Returns:
        {
            "ids": [{"name": str, "line": int, "flag": str|None}],
            "classes": [{"name": str, "line": int, "flag": str|None}]
        }
    """
    cleaned = strip_html_comments(content)
    lines = cleaned.split('\n')

    ids = []
    classes = []

    # Pattern to match HTML elements with id or class attributes
    # We process line by line to track line numbers
    for line_num, line in enumerate(lines, 1):
        # Extract id attributes
        # Match id="..." or id='...'
        id_matches = re.finditer(r'\bid\s*=\s*["\']([^"\']+)["\']', line)
        for match in id_matches:
            id_value = match.group(1).strip()
            # Skip template literals
            if '{{' in id_value or '}}' in id_value or '{' in id_value:
                continue
            ids.append({
                "name": id_value,
                "line": line_num,
                "flag": None,
                "path": file_path
            })

        # Extract class attributes
        class_matches = re.finditer(r'\bclass\s*=\s*["\']([^"\']+)["\']', line)
        for match in class_matches:
            class_value = match.group(1).strip()
            # Skip template literals
            if '{{' in class_value or '}}' in class_value:
                continue
            # Split by whitespace to get individual classes
            for cls in class_value.split():
                cls = cls.strip()
                if cls:
                    classes.append({
                        "name": cls,
                        "line": line_num,
                        "flag": None,
                        "path": file_path
                    })

    return {"ids": ids, "classes": classes}


def detect_id_collisions(id_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Detect IDs that appear in more than 1 HTML element.
    Sets flag 'collision' on duplicate entries.
    """
    from collections import Counter

    # Count occurrences of each id name
    id_counts = Counter(entry["name"] for entry in id_entries)

    # Flag entries where count > 1
    for entry in id_entries:
        if id_counts[entry["name"]] > 1:
            entry["flag"] = "collision"

    return id_entries
