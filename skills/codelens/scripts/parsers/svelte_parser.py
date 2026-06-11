"""
Svelte Parser for CodeLens
Parses Svelte components (.svelte files) to extract:
- class attributes (static)
- class directive: class:active={isActive}
- id attributes
- Scoped style references

Svelte component structure:
<script> ... </script>
<style> ... </style>  (scoped by default)
<main> ... </main>     (markup)
"""

import re
from typing import Dict, List, Any


def parse_svelte_component(content: str, file_path: str) -> Dict[str, Any]:
    """
    Parse a Svelte component file.
    Returns frontend references (classes, ids).
    """
    classes = []
    ids = []

    # Line offset is not needed when sections are replaced with newlines
    # to preserve line count — line numbers in markup directly correspond
    # to the original file.
    markup_start_line = 0

    # Extract style section (scoped by default in Svelte)
    style_match = re.search(r'<style([^>]*)>(.*?)</style>', content, re.DOTALL)
    if style_match:
        style_attrs = style_match.group(1)
        style_content = style_match.group(2)
        is_scoped = 'global' not in style_attrs  # Svelte scopes by default
        _parse_svelte_style(style_content, file_path, classes, ids, is_scoped)

    # Remove style and script sections for markup parsing
    # Preserve line count by replacing with newlines so line numbers stay correct
    markup = content
    markup = re.sub(r'<style[^>]*>.*?</style>', lambda m: '\n' * m.group(0).count('\n'), markup, flags=re.DOTALL)
    # Keep script for potential DOM queries
    script_match = re.search(r'<script[^>]*>(.*?)</script>', markup, re.DOTALL)
    script_content = script_match.group(1) if script_match else ""
    markup = re.sub(r'<script[^>]*>.*?</script>', lambda m: '\n' * m.group(0).count('\n'), markup, flags=re.DOTALL)

    # Parse markup for class and id
    _parse_svelte_markup(markup, file_path, classes, ids, markup_start_line)

    # Parse script for DOM selector references
    if script_content:
        _parse_svelte_script(script_content, file_path, classes, ids)

    return {
        "frontend": {
            "classes": classes,
            "ids": ids
        }
    }


def _parse_svelte_markup(markup: str, file_path: str,
                           classes: List[Dict], ids: List[Dict],
                           markup_start_line: int = 0):
    """Parse Svelte markup for class/id attributes and directives."""
    # Static class: class="xxx"
    for match in re.finditer(r'\bclass\s*=\s*["\']([^"\']+)["\']', markup):
        value = match.group(1)
        line_num = markup[:match.start()].count('\n') + 1 + markup_start_line
        for cls in value.split():
            cls = cls.strip()
            if cls:
                classes.append({
                    "name": cls,
                    "line": line_num,
                    "flag": None,
                    "path": file_path,
                    "source": "svelte_class"
                })

    # Svelte class directive: class:active={isActive} or class:active
    for match in re.finditer(r'\bclass:([a-zA-Z_][\w-]*)', markup):
        cls_name = match.group(1)
        line_num = markup[:match.start()].count('\n') + 1 + markup_start_line
        classes.append({
            "name": cls_name,
            "line": line_num,
            "flag": None,
            "path": file_path,
            "source": "svelte_directive"
        })

    # id attribute: id="xxx"
    for match in re.finditer(r'\bid\s*=\s*["\']([^"\']+)["\']', markup):
        value = match.group(1)
        line_num = markup[:match.start()].count('\n') + 1 + markup_start_line
        ids.append({
            "name": value.strip(),
            "line": line_num,
            "flag": None,
            "path": file_path,
            "source": "svelte_id"
        })


def _parse_svelte_style(style_content: str, file_path: str,
                         classes: List[Dict], ids: List[Dict],
                         is_scoped: bool):
    """Parse a Svelte <style> section."""
    for line_num, line in enumerate(style_content.split('\n'), 1):
        if line.strip().startswith('//') or line.strip().startswith('/*'):
            continue

        # Class selectors
        for match in re.finditer(r'\.([a-zA-Z_][\w-]*)', line):
            classes.append({
                "name": match.group(1),
                "line": line_num,
                "flag": None,
                "path": file_path,
                "source": "svelte_scoped_style" if is_scoped else "svelte_global_style"
            })

        # ID selectors
        for match in re.finditer(r'#([a-zA-Z_][\w-]*)', line):
            ids.append({
                "name": match.group(1),
                "line": line_num,
                "flag": None,
                "path": file_path,
                "source": "svelte_scoped_style" if is_scoped else "svelte_global_style"
            })

        # Svelte :global() modifier
        for match in re.finditer(r':global\(\s*\.([a-zA-Z_][\w-]*)\s*\)', line):
            classes.append({
                "name": match.group(1),
                "line": line_num,
                "flag": None,
                "path": file_path,
                "source": "svelte_global_modifier"
            })


def _parse_svelte_script(script_content: str, file_path: str,
                          classes: List[Dict], ids: List[Dict]):
    """Parse Svelte <script> section for DOM selector references."""
    # Same patterns as JS frontend parser
    patterns = [
        (r'getElementById\(\s*["\']([^"\']+)["\']\s*\)', 'id'),
        (r'querySelector\(\s*["\']([^"\']+)["\']\s*\)', 'selector'),
        (r'querySelectorAll\(\s*["\']([^"\']+)["\']\s*\)', 'selector'),
        (r'getElementsByClassName\(\s*["\']([^"\']+)["\']\s*\)', 'class'),
    ]

    for line_num, line in enumerate(script_content.split('\n'), 1):
        # Remove single-line comments
        line = re.sub(r'(?<!:)//.*$', '', line)

        for pattern, ptype in patterns:
            for match in re.finditer(pattern, line):
                value = match.group(1)
                if ptype == 'id':
                    ids.append({
                        "name": value,
                        "line": line_num,
                        "flag": None,
                        "path": file_path,
                        "source": "svelte_script"
                    })
                elif ptype == 'class':
                    classes.append({
                        "name": value,
                        "line": line_num,
                        "flag": None,
                        "path": file_path,
                        "source": "svelte_script"
                    })
                elif ptype == 'selector':
                    # Parse the CSS selector
                    for cls_match in re.finditer(r'\.([a-zA-Z_][\w-]*)', value):
                        classes.append({
                            "name": cls_match.group(1),
                            "line": line_num,
                            "flag": None,
                            "path": file_path,
                            "source": "svelte_script"
                        })
                    for id_match in re.finditer(r'#([a-zA-Z_][\w-]*)', value):
                        ids.append({
                            "name": id_match.group(1),
                            "line": line_num,
                            "flag": None,
                            "path": file_path,
                            "source": "svelte_script"
                        })
