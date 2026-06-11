"""Fallback HTML parser (when tree-sitter grammars unavailable)."""

import re


def parse_html_fallback(content, file_path):
    """Basic regex HTML parser fallback."""
    content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
    ids, classes = [], []
    for line_num, line in enumerate(content.split('\n'), 1):
        for m in re.finditer(r'\bid\s*=\s*["\']([^"\']+)["\']', line):
            v = m.group(1).strip()
            if '{{' not in v:
                ids.append({"name": v, "line": line_num, "flag": None, "path": file_path})
        for m in re.finditer(r'\bclass\s*=\s*["\']([^"\']+)["\']', line):
            for cls in m.group(1).split():
                if cls.strip() and '{{' not in cls:
                    classes.append({"name": cls.strip(), "line": line_num, "flag": None, "path": file_path})
    return {"ids": ids, "classes": classes}
