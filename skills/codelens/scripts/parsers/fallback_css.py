"""Fallback CSS parser (when tree-sitter grammars unavailable)."""

import re


def parse_css_fallback(content, file_path):
    """Basic regex CSS parser fallback."""
    content = re.sub(r'/\*.*?\*/', lambda m: '\n' * m.group(0).count('\n'), content, flags=re.DOTALL)
    content = re.sub(r'@keyframes\s+[^{]+\{[^}]*(?:\{[^}]*\}[^}]*)*\}', lambda m: '\n' * m.group(0).count('\n'), content, flags=re.DOTALL)
    classes, ids = [], []
    for line_num, line in enumerate(content.split('\n'), 1):
        for m in re.finditer(r'\.([a-zA-Z_][\w-]*)', line):
            classes.append({"name": m.group(1), "line": line_num, "flag": None, "path": file_path})
        # Match # as CSS ID selector only at selector positions (start of line or after whitespace/comma/combinator)
        for m in re.finditer(r'(?:^|[\s,{>+~])#([a-zA-Z_][\w-]*)', line):
            ids.append({"name": m.group(1), "line": line_num, "flag": None, "path": file_path})
    return {"classes": classes, "ids": ids}
