"""Fallback JS frontend parser (when tree-sitter grammars unavailable)."""

import re


def parse_js_frontend_fallback(content, file_path):
    """Basic regex JS frontend parser fallback."""
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    content = re.sub(r'(?<!:)//.*$', '', content, flags=re.MULTILINE)
    classes, ids = [], []
    for line_num, line in enumerate(content.split('\n'), 1):
        for m in re.finditer(r'getElementById\(\s*["\']([^"\']+)["\']\s*\)', line):
            ids.append({"name": m.group(1), "line": line_num, "flag": None, "path": file_path})
        for m in re.finditer(r'querySelector(?:All)?\(\s*["\']([^"\']+)["\']\s*\)', line):
            for cm in re.finditer(r'\.([a-zA-Z_][\w-]*)', m.group(1)):
                classes.append({"name": cm.group(1), "line": line_num, "flag": None, "path": file_path})
            for im in re.finditer(r'#([a-zA-Z_][\w-]*)', m.group(1)):
                ids.append({"name": im.group(1), "line": line_num, "flag": None, "path": file_path})
        for m in re.finditer(r'getElementsByClassName\(\s*["\']([^"\']+)["\']\s*\)', line):
            classes.append({"name": m.group(1), "line": line_num, "flag": None, "path": file_path})
    return {"classes": classes, "ids": ids}
