"""
CSS Parser for CodeLens
Extracts all selectors that reference class (.xxx) or id (#xxx).

Rules:
- .btn-primary { ... } → reference to class `btn-primary`
- #sidebar-nav { ... } → reference to id `sidebar-nav`
- Compound selectors: .modal .btn-primary → references BOTH
- Same selector appearing 2+ times → flag `duplicate_define`
- Ignore: selectors inside comments /* */
- Ignore: selectors inside @keyframes
- Pseudo-class stripped for matching: .btn-primary:hover → match to class `btn-primary`
"""

import re
from typing import Dict, List, Any


def strip_css_comments(content: str) -> str:
    """Remove CSS comments before parsing."""
    return re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)


def strip_keyframes(content: str) -> str:
    """Remove @keyframes blocks before parsing."""
    return re.sub(r'@keyframes\s+[^{]+\{[^}]*(?:\{[^}]*\}[^}]*)*\}', '', content, flags=re.DOTALL)


def extract_class_names(selector: str) -> List[str]:
    """Extract class names from a selector string."""
    # Match .classname (not just .digit)
    matches = re.findall(r'\.([a-zA-Z_][\w-]*)', selector)
    return matches


def extract_id_names(selector: str) -> List[str]:
    """Extract id names from a selector string."""
    matches = re.findall(r'#([a-zA-Z_][\w-]*)', selector)
    return matches


def extract_css_references(content: str, file_path: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Extract class and id references from CSS content.

    Returns:
        {
            "classes": [{"name": str, "line": int, "flag": str|None, "path": str}],
            "ids": [{"name": str, "line": int, "flag": str|None, "path": str}]
        }
    """
    cleaned = strip_css_comments(content)
    cleaned = strip_keyframes(cleaned)
    lines = cleaned.split('\n')

    classes = []
    ids = []

    # Track selectors across the file to detect duplicate_define
    selector_locations: Dict[str, List[int]] = {}  # selector_name → [line_numbers]

    for line_num, line in enumerate(lines, 1):
        # Find all CSS rule blocks by looking for selectors before {
        # This handles single-line and multi-line rules
        line_stripped = line.strip()

        # Skip empty lines, @media, @import, @font-face, property-only lines
        if not line_stripped or line_stripped.startswith('@') or line_stripped.startswith('}') or ':' in line_stripped.split('{')[0] == '' and '{' not in line_stripped:
            pass

        # Extract selectors from lines that contain { or are part of a selector
        if '{' in line_stripped or (not any(c in line_stripped for c in [':', ';']) and line_stripped and not line_stripped.startswith('}')):
            # Get the selector part (before {)
            selector_part = line_stripped.split('{')[0].strip() if '{' in line_stripped else line_stripped

            if not selector_part or selector_part.startswith('@'):
                continue

            # Split compound selectors (comma-separated)
            individual_selectors = [s.strip() for s in selector_part.split(',')]

            for sel in individual_selectors:
                if not sel:
                    continue

                # Extract class references
                class_names = extract_class_names(sel)
                for cls_name in class_names:
                    # Strip pseudo-classes from the name (already handled by regex)
                    entry = {
                        "name": cls_name,
                        "line": line_num,
                        "flag": None,
                        "path": file_path
                    }
                    classes.append(entry)

                    key = f"class:{cls_name}"
                    if key not in selector_locations:
                        selector_locations[key] = []
                    selector_locations[key].append(line_num)

                # Extract id references
                id_names = extract_id_names(sel)
                for id_name in id_names:
                    entry = {
                        "name": id_name,
                        "line": line_num,
                        "flag": None,
                        "path": file_path
                    }
                    ids.append(entry)

                    key = f"id:{id_name}"
                    if key not in selector_locations:
                        selector_locations[key] = []
                    selector_locations[key].append(line_num)

    # Flag duplicate_define: same selector defined more than once in this file
    for entry in classes:
        key = f"class:{entry['name']}"
        if len(selector_locations.get(key, [])) > 1:
            # Only flag subsequent definitions, not the first
            locs = selector_locations[key]
            if entry['line'] != locs[0]:
                entry['flag'] = 'duplicate_define'

    for entry in ids:
        key = f"id:{entry['name']}"
        if len(selector_locations.get(key, [])) > 1:
            locs = selector_locations[key]
            if entry['line'] != locs[0]:
                entry['flag'] = 'duplicate_define'

    return {"classes": classes, "ids": ids}
