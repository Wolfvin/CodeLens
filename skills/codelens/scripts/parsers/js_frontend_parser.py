"""
JS Frontend Parser for CodeLens
Extracts all references to class or id via DOM selectors.

Detected patterns:
- document.getElementById("xxx")
- document.querySelector("#xxx") or document.querySelector(".xxx")
- document.querySelectorAll("#xxx") or document.querySelectorAll(".xxx")
- document.getElementsByClassName("xxx")
- $(".xxx") or $("#xxx")  (jQuery)

Rules:
- Only string literals counted — variable references ignored (querySelector(myVar) skipped)
- Same reference from 2+ files → status becomes `duplicate_ref`
- classList.add/toggle/remove → IGNORED (dynamic, not direct reference)
"""

import re
from typing import Dict, List, Any


def strip_js_comments(content: str) -> str:
    """Remove JS single-line and multi-line comments."""
    # Remove multi-line comments
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    # Remove single-line comments (but not URLs with //)
    content = re.sub(r'(?<!:)//.*$', '', content, flags=re.MULTILINE)
    return content


def extract_js_frontend_references(content: str, file_path: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Extract class and id references from frontend JS content.

    Returns:
        {
            "classes": [{"name": str, "line": int, "flag": str|None, "path": str}],
            "ids": [{"name": str, "line": int, "flag": str|None, "path": str}]
        }
    """
    cleaned = strip_js_comments(content)
    lines = cleaned.split('\n')

    classes = []
    ids = []

    for line_num, line in enumerate(lines, 1):
        # Pattern 1: document.getElementById("xxx")
        match = re.search(r'getElementById\(\s*["\']([^"\']+)["\']\s*\)', line)
        if match:
            ids.append({
                "name": match.group(1),
                "line": line_num,
                "flag": None,
                "path": file_path
            })

        # Pattern 2: document.querySelector("#xxx" or ".xxx")
        for match in re.finditer(r'querySelector(?:All)?\(\s*["\']([^"\']+)["\']\s*\)', line):
            selector = match.group(1).strip()
            # Parse the selector to extract class/id names
            id_names = re.findall(r'#([a-zA-Z_][\w-]*)', selector)
            class_names = re.findall(r'\.([a-zA-Z_][\w-]*)', selector)

            for id_name in id_names:
                ids.append({
                    "name": id_name,
                    "line": line_num,
                    "flag": None,
                    "path": file_path
                })

            for cls_name in class_names:
                classes.append({
                    "name": cls_name,
                    "line": line_num,
                    "flag": None,
                    "path": file_path
                })

        # Pattern 3: document.getElementsByClassName("xxx")
        match = re.search(r'getElementsByClassName\(\s*["\']([^"\']+)["\']\s*\)', line)
        if match:
            classes.append({
                "name": match.group(1),
                "line": line_num,
                "flag": None,
                "path": file_path
            })

        # Pattern 4: jQuery $(".xxx") or $("#xxx")
        for match in re.finditer(r'\$\(\s*["\']([^"\']+)["\']\s*\)', line):
            selector = match.group(1).strip()
            id_names = re.findall(r'#([a-zA-Z_][\w-]*)', selector)
            class_names = re.findall(r'\.([a-zA-Z_][\w-]*)', selector)

            for id_name in id_names:
                ids.append({
                    "name": id_name,
                    "line": line_num,
                    "flag": None,
                    "path": file_path
                })

            for cls_name in class_names:
                classes.append({
                    "name": cls_name,
                    "line": line_num,
                    "flag": None,
                    "path": file_path
                })

    return {"classes": classes, "ids": ids}
