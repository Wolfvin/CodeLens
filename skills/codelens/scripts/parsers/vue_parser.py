"""
Vue SFC Parser for CodeLens
Parses Vue Single File Components (.vue files) to extract:
- :class bindings (dynamic and static)
- class attributes (static)
- id attributes (static and dynamic)
- Scoped style references
- Script section: component methods and data refs

Vue SFC structure:
<template> ... </template>
<script> ... </script>
<style scoped> ... </style>
"""

import re
import os
from typing import Dict, List, Any, Optional


def parse_vue_sfc(content: str, file_path: str) -> Dict[str, Any]:
    """
    Parse a Vue SFC file.
    Returns frontend references (classes, ids) and style info.
    """
    classes = []
    ids = []
    scoped_styles = []

    # Extract template section
    template_match = re.search(r'<template>(.*?)</template>', content, re.DOTALL)
    template_content = template_match.group(1) if template_match else ""

    # Extract script section
    script_match = re.search(r'<script[^>]*>(.*?)</script>', content, re.DOTALL)
    script_content = script_match.group(1) if script_match else ""

    # Extract style sections (may have multiple)
    style_matches = re.finditer(r'<style([^>]*)>(.*?)</style>', content, re.DOTALL)
    for style_match in style_matches:
        style_attrs = style_match.group(1)
        style_content = style_match.group(2)
        is_scoped = 'scoped' in style_attrs
        lang = 'css'
        if 'lang="scss"' in style_attrs or "lang='scss'" in style_attrs:
            lang = 'scss'
        elif 'lang="less"' in style_attrs or "lang='less'" in style_attrs:
            lang = 'less'
        elif 'lang="sass"' in style_attrs or "lang='sass'" in style_attrs:
            lang = 'sass'

        scoped_styles.append({
            "content": style_content,
            "scoped": is_scoped,
            "lang": lang
        })

    # Parse template for classes and ids
    if template_content:
        _parse_vue_template(template_content, file_path, classes, ids)

    # Parse scoped styles
    for style_info in scoped_styles:
        _parse_style_section(style_info["content"], file_path, classes, ids,
                              style_info["scoped"], style_info["lang"])

    return {
        "frontend": {
            "classes": classes,
            "ids": ids
        },
        "scoped_styles": scoped_styles
    }


def _parse_vue_template(template: str, file_path: str,
                         classes: List[Dict], ids: List[Dict]):
    """Parse Vue template section for class and id references."""
    # Static class attribute: class="xxx"
    for match in re.finditer(r'\bclass\s*=\s*["\']([^"\']+)["\']', template):
        value = match.group(1)
        # Find the line number in original content
        line_num = _find_line_in_content(template, match.start())
        for cls in value.split():
            cls = cls.strip()
            if cls:
                classes.append({
                    "name": cls,
                    "line": line_num,
                    "flag": None,
                    "path": file_path,
                    "source": "vue_class"
                })

    # Dynamic :class binding: :class="xxx" or v-bind:class="xxx"
    # Try to extract literal strings from the binding expression
    for match in re.finditer(r'(?:v-bind:|:)class\s*=\s*["\']([^"\']+)["\']', template):
        value = match.group(1)
        line_num = _find_line_in_content(template, match.start())
        _extract_classes_from_binding(value, line_num, file_path, classes)

    # Static id attribute: id="xxx"
    for match in re.finditer(r'\bid\s*=\s*["\']([^"\']+)["\']', template):
        value = match.group(1)
        line_num = _find_line_in_content(template, match.start())
        ids.append({
            "name": value.strip(),
            "line": line_num,
            "flag": None,
            "path": file_path,
            "source": "vue_id"
        })

    # Dynamic :id binding: :id="xxx"
    for match in re.finditer(r'(?:v-bind:|:)id\s*=\s*["\']([^"\']+)["\']', template):
        value = match.group(1)
        line_num = _find_line_in_content(template, match.start())
        # Only track if it's a static string inside the binding
        if "'" in value or '"' in value:
            inner = re.search(r'["\']([^"\']+)["\']', value)
            if inner:
                ids.append({
                    "name": inner.group(1).strip(),
                    "line": line_num,
                    "flag": None,
                    "path": file_path,
                    "source": "vue_dynamic_id"
                })


def _extract_classes_from_binding(binding_expr: str, line_num: int,
                                   file_path: str, classes: List[Dict]):
    """
    Extract class names from a Vue :class binding expression.
    Handles:
    - :class="'modal active'" → "modal", "active"
    - :class="['modal', isActive ? 'active' : '']" → "modal", "active"
    - :class="{ 'modal': isOpen }" → "modal"
    - :class="classes.wrapper" → "wrapper" (as dynamic ref)
    """
    # Extract all string literals from the binding expression
    for str_match in re.finditer(r'["\']([^"\']+)["\']', binding_expr):
        value = str_match.group(1)
        for cls in value.split():
            cls = cls.strip()
            if cls and re.match(r'^[a-zA-Z_][\w-]*$', cls):
                classes.append({
                    "name": cls,
                    "line": line_num,
                    "flag": None,
                    "path": file_path,
                    "source": "vue_binding"
                })

    # Extract dot-accessed names: classes.wrapper → "wrapper"
    for dot_match in re.finditer(r'\.([a-zA-Z_]\w*)', binding_expr):
        name = dot_match.group(1)
        if name not in ('length', 'push', 'pop', 'split', 'join', 'filter', 'map'):
            classes.append({
                "name": name,
                "line": line_num,
                "flag": None,
                "path": file_path,
                "source": "vue_dot_ref"
            })


def _parse_style_section(style_content: str, file_path: str,
                          classes: List[Dict], ids: List[Dict],
                          is_scoped: bool, lang: str):
    """Parse a <style> section from a Vue SFC."""
    for line_num, line in enumerate(style_content.split('\n'), 1):
        # Skip comments
        if line.strip().startswith('//') or line.strip().startswith('/*'):
            continue

        # Extract class selectors
        for match in re.finditer(r'\.([a-zA-Z_][\w-]*)', line):
            classes.append({
                "name": match.group(1),
                "line": line_num,
                "flag": None,
                "path": file_path,
                "source": "vue_scoped_style" if is_scoped else "vue_style"
            })

        # Extract id selectors
        for match in re.finditer(r'#([a-zA-Z_][\w-]*)', line):
            ids.append({
                "name": match.group(1),
                "line": line_num,
                "flag": None,
                "path": file_path,
                "source": "vue_scoped_style" if is_scoped else "vue_style"
            })


def _find_line_in_content(content: str, pos: int) -> int:
    """Convert a character position to a 1-based line number."""
    return content[:pos].count('\n') + 1
