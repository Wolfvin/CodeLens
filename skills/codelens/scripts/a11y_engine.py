"""
Accessibility Audit Engine for CodeLens — v3
Detects accessibility (a11y) issues across the workspace — missing alt text,
ARIA problems, keyboard navigation gaps, form labeling issues, semantic HTML
violations, heading order problems, and more.

Categories:
1. missing_alt       — Images without alt text
2. missing_label     — Form inputs without associated labels
3. aria_issues       — Invalid ARIA attributes, missing roles, wrong role values
4. keyboard_nav      — Click handlers without keyboard equivalents
5. semantic_html     — Non-semantic elements where semantic ones should be used
6. color_contrast    — Inline styles with potentially poor contrast
7. heading_order     — Skipped heading levels
8. link_text         — Vague link text ("click here", "read more")
9. focus_management  — Missing focus traps in modals, auto-focus issues

For HTML, JSX/TSX, Vue, and Svelte templates.
Maps findings to WCAG 2.1 criteria.
"""

import os
import re
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict


# ─── Configuration ─────────────────────────────────────────────

DEFAULT_IGNORE_DIRS = {
    "node_modules", ".git", "dist", "build", "target",
    "__pycache__", ".codelens", ".next", ".nuxt",
    "coverage", ".cache", "vendor", "bin", "obj",
    ".terraform", ".venv", "venv", "env",
}

TEMPLATE_EXTENSIONS = {
    ".html", ".htm", ".jsx", ".tsx", ".js", ".ts",
    ".vue", ".svelte",
}

# WCAG 2.1 mapping for each category
WCAG_MAPPING = {
    "missing_alt": {
        "criterion": "1.1.1",
        "level": "A",
        "title": "Non-text Content",
        "url": "https://www.w3.org/WAI/WCAG21/Understanding/non-text-content.html",
    },
    "missing_label": {
        "criterion": "1.3.1",
        "level": "A",
        "title": "Info and Relationships",
        "url": "https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html",
    },
    "aria_issues": {
        "criterion": "4.1.2",
        "level": "A",
        "title": "Name, Role, Value",
        "url": "https://www.w3.org/WAI/WCAG21/Understanding/name-role-value.html",
    },
    "keyboard_nav": {
        "criterion": "2.1.1",
        "level": "A",
        "title": "Keyboard",
        "url": "https://www.w3.org/WAI/WCAG21/Understanding/keyboard.html",
    },
    "semantic_html": {
        "criterion": "1.3.1",
        "level": "A",
        "title": "Info and Relationships",
        "url": "https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html",
    },
    "color_contrast": {
        "criterion": "1.4.3",
        "level": "AA",
        "title": "Contrast (Minimum)",
        "url": "https://www.w3.org/WAI/WCAG21/Understanding/contrast-minimum.html",
    },
    "heading_order": {
        "criterion": "1.3.1",
        "level": "A",
        "title": "Info and Relationships",
        "url": "https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html",
    },
    "link_text": {
        "criterion": "2.4.4",
        "level": "A",
        "title": "Link Purpose (In Context)",
        "url": "https://www.w3.org/WAI/WCAG21/Understanding/link-purpose-in-context.html",
    },
    "focus_management": {
        "criterion": "2.4.7",
        "level": "AA",
        "title": "Focus Visible",
        "url": "https://www.w3.org/WAI/WCAG21/Understanding/focus-visible.html",
    },
}

# Valid ARIA role values
VALID_ROLES = {
    "alert", "alertdialog", "application", "article", "banner",
    "button", "cell", "checkbox", "columnheader", "combobox",
    "complementary", "contentinfo", "definition", "dialog", "directory",
    "document", "feed", "figure", "form", "grid", "gridcell",
    "group", "heading", "img", "link", "list", "listbox",
    "listitem", "log", "main", "marquee", "math", "menu",
    "menubar", "menuitem", "menuitemcheckbox", "menuitemradio",
    "navigation", "none", "note", "option", "presentation",
    "progressbar", "radio", "radiogroup", "region", "row",
    "rowgroup", "rowheader", "scrollbar", "search", "searchbox",
    "separator", "slider", "spinbutton", "status", "switch",
    "tab", "table", "tablist", "tabpanel", "term", "textbox",
    "timer", "toolbar", "tooltip", "tree", "treegrid", "treeitem",
}

# Valid ARIA attributes
VALID_ARIA_ATTRS = {
    "aria-activedescendant", "aria-atomic", "aria-autocomplete",
    "aria-busy", "aria-checked", "aria-colcount", "aria-colindex",
    "aria-colspan", "aria-controls", "aria-current", "aria-describedby",
    "aria-details", "aria-disabled", "aria-dropeffect", "aria-errormessage",
    "aria-expanded", "aria-flowto", "aria-grabbed", "aria-haspopup",
    "aria-hidden", "aria-invalid", "aria-keyshortcuts", "aria-label",
    "aria-labelledby", "aria-level", "aria-live", "aria-modal",
    "aria-multiline", "aria-multiselectable", "aria-orientation",
    "aria-owns", "aria-placeholder", "aria-posinset", "aria-pressed",
    "aria-readonly", "aria-relevant", "aria-required", "aria-roledescription",
    "aria-rowcount", "aria-rowindex", "aria-rowspan", "aria-selected",
    "aria-setsize", "aria-sort", "aria-valuemax", "aria-valuemin",
    "aria-valuenow", "aria-valuetext",
    "role",  # role is technically not aria-* but is ARIA-related
}

# Vague link text patterns
VAGUE_LINK_TEXT = {
    "click here", "here", "read more", "more", "learn more",
    "link", "this", "go", "continue", "see more", "view more",
    "click", "download", "open", "details",
}

# Semantic element replacements
SEMANTIC_REPLACEMENTS = {
    "div": {
        "nav": "when used for navigation",
        "header": "when used for page/header section",
        "footer": "when used for page/footer section",
        "main": "when used for main content",
        "article": "when used for self-contained content",
        "section": "when used for thematic grouping",
        "aside": "when used for side content",
    },
    "span": {
        "strong": "when text needs strong emphasis",
        "em": "when text needs emphasis",
        "time": "when representing a date/time",
        "mark": "when highlighting text",
        "abbr": "when text is an abbreviation",
    },
    "b": {"strong": "for important text with semantic meaning"},
    "i": {"em": "for text with emphasis, or cite for titles"},
    "u": {"ins": "for inserted text, or style differently"},
}


# ─── Main Entry Point ──────────────────────────────────────────

def audit_accessibility(
    workspace: str,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Audit the workspace for accessibility issues.

    Args:
        workspace: Absolute path to workspace root
        category: Optional category filter — one of:
                  missing_alt, missing_label, aria_issues, keyboard_nav,
                  semantic_html, color_contrast, heading_order,
                  link_text, focus_management
        severity: Optional severity filter ("high", "medium", "low")
        config: CodeLens configuration dict

    Returns:
        Dict with status, stats, issues, WCAG mapping, and recommendations
    """
    workspace = os.path.abspath(workspace)

    valid_categories = {
        "missing_alt", "missing_label", "aria_issues", "keyboard_nav",
        "semantic_html", "color_contrast", "heading_order",
        "link_text", "focus_management"
    }

    valid_severities = {"high", "medium", "low"}

    if category and category not in valid_categories:
        return {
            "status": "error",
            "message": f"Invalid category '{category}'. Valid: {sorted(valid_categories)}"
        }

    if severity and severity not in valid_severities:
        return {
            "status": "error",
            "message": f"Invalid severity '{severity}'. Valid: {sorted(valid_severities)}"
        }

    categories = {category} if category else valid_categories

    issues: List[Dict] = []
    files_scanned = 0

    # Track headings across all files for heading order analysis
    all_headings: List[Dict] = []

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in TEMPLATE_EXTENSIONS:
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            files_scanned += 1
            lines = content.split('\n')

            # Determine template type
            template_type = _detect_template_type(content, ext)

            # ─── Missing Alt ─────────────────────────────
            if "missing_alt" in categories:
                _check_missing_alt(content, lines, rel_path, template_type, issues)

            # ─── Missing Label ───────────────────────────
            if "missing_label" in categories:
                _check_missing_label(content, lines, rel_path, template_type, issues)

            # ─── ARIA Issues ─────────────────────────────
            if "aria_issues" in categories:
                _check_aria_issues(content, lines, rel_path, template_type, issues)

            # ─── Keyboard Navigation ─────────────────────
            if "keyboard_nav" in categories:
                _check_keyboard_nav(content, lines, rel_path, template_type, issues)

            # ─── Semantic HTML ───────────────────────────
            if "semantic_html" in categories:
                _check_semantic_html(content, lines, rel_path, template_type, issues)

            # ─── Color Contrast ──────────────────────────
            if "color_contrast" in categories:
                _check_color_contrast(content, lines, rel_path, template_type, issues)

            # ─── Heading Order (collect for later) ───────
            if "heading_order" in categories:
                file_headings = _collect_headings(content, lines, rel_path, template_type)
                all_headings.extend(file_headings)

            # ─── Link Text ───────────────────────────────
            if "link_text" in categories:
                _check_link_text(content, lines, rel_path, template_type, issues)

            # ─── Focus Management ────────────────────────
            if "focus_management" in categories:
                _check_focus_management(content, lines, rel_path, template_type, issues)

    # ─── Heading Order Analysis (cross-file) ─────────────
    if "heading_order" in categories and all_headings:
        _analyze_heading_order(all_headings, issues)

    # Apply severity filter
    if severity:
        issues = [i for i in issues if i["severity"] == severity]

    # ─── Aggregate Stats ──────────────────────────────────
    by_category = defaultdict(int)
    by_severity = defaultdict(int)
    for issue in issues:
        by_category[issue["category"]] += 1
        by_severity[issue["severity"]] += 1

    # Build WCAG mapping for categories that have issues
    wcag_map = {}
    for cat in by_category:
        if cat in WCAG_MAPPING:
            wcag_map[cat] = WCAG_MAPPING[cat]

    # ─── Recommendations ──────────────────────────────────
    recommendations = _generate_recommendations(issues, dict(by_category), dict(by_severity))

    return {
        "status": "ok",
        "workspace": workspace,
        "stats": {
            "total_issues": len(issues),
            "files_scanned": files_scanned,
            "by_category": dict(by_category),
            "by_severity": dict(by_severity),
        },
        "issues": issues,
        "wcag_mapping": wcag_map,
        "recommendations": recommendations,
    }


# ─── Template Type Detection ───────────────────────────────────

def _detect_template_type(content: str, ext: str) -> str:
    """Detect what template system is being used."""
    if ext == ".vue":
        return "vue"
    elif ext == ".svelte":
        return "svelte"
    elif ext in {".jsx", ".tsx"}:
        return "jsx"
    elif ext in {".js", ".ts"}:
        # Could be JSX in .js file
        if re.search(r'<\w+[^>]*>', content):
            return "jsx"
        return "js"
    else:
        return "html"


# ─── 1. Missing Alt Text ───────────────────────────────────────

def _check_missing_alt(
    content: str, lines: List[str], rel_path: str,
    template_type: str, issues: List[Dict]
) -> None:
    """Detect images without alt text."""
    # Pattern for <img> tags (HTML/JSX/Vue/Svelte)
    img_patterns = [
        # <img ...> or <img .../> (HTML/JSX)
        r'<img\s+([^>]*?)/?>',
    ]

    for pattern in img_patterns:
        for m in re.finditer(pattern, content, re.DOTALL):
            attrs_str = m.group(1)
            line_num = content[:m.start()].count('\n') + 1

            # Check for alt attribute
            has_alt = bool(re.search(r'\balt\s*=\s*["\']', attrs_str))

            # Check for aria-label (acceptable alternative)
            has_aria_label = bool(re.search(r'\baria-label\s*=\s*["\']', attrs_str))

            # Check for aria-labelledby
            has_aria_labelledby = bool(re.search(r'\baria-labelledby\s*=\s*["\']', attrs_str))

            # Check for role="presentation" or role="none" (decorative)
            is_decorative = bool(re.search(r'role\s*=\s*["\'](?:presentation|none)["\']', attrs_str))

            if is_decorative:
                continue  # Decorative images don't need alt text

            if has_aria_label or has_aria_labelledby:
                continue  # Has accessible name via ARIA

            if not has_alt:
                issues.append({
                    "category": "missing_alt",
                    "file": rel_path,
                    "line": line_num,
                    "element": "img",
                    "severity": "high",
                    "message": "Image missing alt attribute",
                    "suggestion": "Add alt='description' for informative images or alt='' for decorative images.",
                })
            else:
                # Check if alt text is empty but not decorative
                alt_match = re.search(r'\balt\s*=\s*["\']([^"\']*)["\']', attrs_str)
                if alt_match and alt_match.group(1).strip() == '':
                    # Empty alt is OK for decorative, but check if it has other
                    # indicators of being meaningful
                    src_match = re.search(r'\bsrc\s*=\s*["\']([^"\']+)["\']', attrs_str)
                    if src_match:
                        src = src_match.group(1).lower()
                        # Skip icon/logo sprites which are often decorative
                        if any(x in src for x in ['icon', 'logo', 'spacer', 'pixel', 'blank']):
                            continue
                    # Image with empty alt — flag as medium if it might be meaningful
                    issues.append({
                        "category": "missing_alt",
                        "file": rel_path,
                        "line": line_num,
                        "element": "img",
                        "severity": "low",
                        "message": "Image has empty alt text — confirm it's decorative",
                        "suggestion": "If image is decorative, add role='presentation'. If meaningful, provide descriptive alt text.",
                    })

    # Check for role="img" elements without accessible name
    for m in re.finditer(r'<(\w+)\s+([^>]*?)role\s*=\s*["\']img["\']([^>]*?)>', content):
        attrs = m.group(2) + m.group(3)
        line_num = content[:m.start()].count('\n') + 1

        has_accessible_name = bool(
            re.search(r'\b(alt|aria-label|aria-labelledby)\s*=\s*["\']', attrs)
        )
        if not has_accessible_name:
            issues.append({
                "category": "missing_alt",
                "file": rel_path,
                "line": line_num,
                "element": m.group(1) + '[role="img"]',
                "severity": "high",
                "message": "Element with role='img' has no accessible name",
                "suggestion": "Add aria-label or aria-labelledby to provide accessible name.",
            })


# ─── 2. Missing Labels ────────────────────────────────────────

def _check_missing_label(
    content: str, lines: List[str], rel_path: str,
    template_type: str, issues: List[Dict]
) -> None:
    """Detect form inputs without associated labels."""
    # Input types that need labels
    input_types_needing_label = {
        'text', 'search', 'url', 'tel', 'email', 'password',
        'number', 'date', 'time', 'datetime-local', 'month',
        'week', 'color', 'range', 'file',
    }

    # Hidden, submit, reset, button, image don't need labels
    skip_types = {'hidden', 'submit', 'reset', 'button', 'image'}

    for m in re.finditer(r'<input\s+([^>]*?)/?>', content, re.DOTALL):
        attrs = m.group(1)
        line_num = content[:m.start()].count('\n') + 1

        # Get type attribute
        type_match = re.search(r'\btype\s*=\s*["\'](\w+)["\']', attrs)
        input_type = type_match.group(1) if type_match else 'text'

        if input_type.lower() in skip_types:
            continue

        # Check for label association
        has_label = _has_label_association(attrs, content, m)

        if not has_label:
            # Get id for context
            id_match = re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', attrs)
            id_info = f" id='{id_match.group(1)}'" if id_match else ""

            issues.append({
                "category": "missing_label",
                "file": rel_path,
                "line": line_num,
                "element": f"input[type={input_type}]{id_info}",
                "severity": "high",
                "message": f"Input (type={input_type}) has no associated label",
                "suggestion": "Add a <label> element with htmlFor/id, or use aria-label/aria-labelledby.",
            })

    # Check <textarea> without labels
    for m in re.finditer(r'<textarea\s+([^>]*?)>', content):
        attrs = m.group(1)
        line_num = content[:m.start()].count('\n') + 1

        has_label = _has_label_association(attrs, content, m)
        if not has_label:
            issues.append({
                "category": "missing_label",
                "file": rel_path,
                "line": line_num,
                "element": "textarea",
                "severity": "high",
                "message": "Textarea has no associated label",
                "suggestion": "Add a <label> element or aria-label attribute.",
            })

    # Check <select> without labels
    for m in re.finditer(r'<select\s+([^>]*?)>', content):
        attrs = m.group(1)
        line_num = content[:m.start()].count('\n') + 1

        has_label = _has_label_association(attrs, content, m)
        if not has_label:
            issues.append({
                "category": "missing_label",
                "file": rel_path,
                "line": line_num,
                "element": "select",
                "severity": "high",
                "message": "Select has no associated label",
                "suggestion": "Add a <label> element or aria-label attribute.",
            })


def _has_label_association(attrs: str, content: str, m: re.Match) -> bool:
    """Check if an input element has an associated label."""
    # Check for aria-label
    if re.search(r'\baria-label\s*=\s*["\']', attrs):
        return True

    # Check for aria-labelledby
    if re.search(r'\baria-labelledby\s*=\s*["\']', attrs):
        return True

    # Check for title attribute (acceptable as implicit label)
    if re.search(r'\btitle\s*=\s*["\']', attrs):
        return True

    # Check for id — look for corresponding <label htmlFor="id">
    id_match = re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', attrs)
    if id_match:
        element_id = id_match.group(1)
        # Search for label with matching htmlFor
        # In JSX: htmlFor, in HTML: for
        label_pattern = (
            r'<label\s+[^>]*(?:for|htmlFor)\s*=\s*["\']'
            + re.escape(element_id) + r'["\']'
        )
        if re.search(label_pattern, content):
            return True

    # Check if the input is wrapped in a <label>
    # Find the position and look backward for an open <label>
    pos = m.start()
    preceding = content[max(0, pos - 500):pos]
    # Check for unclosed <label> before this input
    open_labels = len(re.findall(r'<label[\s>]', preceding))
    close_labels = len(re.findall(r'</label>', preceding))
    if open_labels > close_labels:
        return True

    return False


# ─── 3. ARIA Issues ────────────────────────────────────────────

def _check_aria_issues(
    content: str, lines: List[str], rel_path: str,
    template_type: str, issues: List[Dict]
) -> None:
    """Detect ARIA attribute and role issues."""
    # Find all elements with ARIA attributes or role
    for m in re.finditer(r'<(\w+)\s+([^>]*?)>', content):
        tag = m.group(1)
        attrs = m.group(2)
        line_num = content[:m.start()].count('\n') + 1

        # Skip closing tags and non-element patterns
        if tag.startswith('/') or tag in ('!--', '!DOCTYPE'):
            continue

        # ─── Invalid role values ─────────────────────
        role_match = re.search(r'\brole\s*=\s*["\']([^"\']+)["\']', attrs)
        if role_match:
            role_value = role_match.group(1).strip()
            if role_value not in VALID_ROLES:
                issues.append({
                    "category": "aria_issues",
                    "file": rel_path,
                    "line": line_num,
                    "element": f"<{tag}>",
                    "severity": "high",
                    "message": f"Invalid ARIA role '{role_value}'",
                    "suggestion": f"Valid roles include: {', '.join(sorted(list(VALID_ROLES)[:15]))}...",
                })

        # ─── Invalid ARIA attributes ─────────────────
        aria_attrs = re.findall(r'(aria-\w+)\s*=', attrs)
        for aria_attr in aria_attrs:
            if aria_attr not in VALID_ARIA_ATTRS:
                issues.append({
                    "category": "aria_issues",
                    "file": rel_path,
                    "line": line_num,
                    "element": f"<{tag}>",
                    "severity": "medium",
                    "message": f"Unknown ARIA attribute '{aria_attr}'",
                    "suggestion": f"Check ARIA spec for valid attributes. Did you mean a similar attribute?",
                })

        # ─── aria-hidden on focusable elements ────────
        if re.search(r'\baria-hidden\s*=\s*["\']true["\']', attrs):
            # Check if element is focusable
            is_focusable = (
                tag in ('a', 'button', 'input', 'select', 'textarea', 'details') or
                re.search(r'\btabindex\s*=\s*["\'][^"-]', attrs) or  # tabindex >= 0
                re.search(r'\bonclick\s*=', attrs)
            )
            if is_focusable:
                issues.append({
                    "category": "aria_issues",
                    "file": rel_path,
                    "line": line_num,
                    "element": f"<{tag}>",
                    "severity": "high",
                    "message": "aria-hidden='true' on focusable element — screen readers can still focus it",
                    "suggestion": "Remove aria-hidden or make element truly non-interactive (tabindex='-1', remove handlers).",
                })

        # ─── Missing required ARIA attributes ────────
        # Certain roles require specific ARIA attributes
        if role_match:
            role_value = role_match.group(1).strip()
            required = _get_required_aria_for_role(role_value)
            for req_attr in required:
                if not re.search(r'\b' + re.escape(req_attr) + r'\s*=', attrs):
                    issues.append({
                        "category": "aria_issues",
                        "file": rel_path,
                        "line": line_num,
                        "element": f"<{tag} role='{role_value}'>",
                        "severity": "high",
                        "message": f"Role '{role_value}' requires '{req_attr}' attribute",
                        "suggestion": f"Add {req_attr} to support the '{role_value}' role.",
                    })


def _get_required_aria_for_role(role: str) -> List[str]:
    """Get required ARIA attributes for a given role."""
    requirements = {
        "checkbox": ["aria-checked"],
        "combobox": ["aria-expanded"],
        "heading": ["aria-level"],
        "menuitemcheckbox": ["aria-checked"],
        "menuitemradio": ["aria-checked"],
        "option": ["aria-selected"],
        "radio": ["aria-checked"],
        "radiogroup": ["aria-required"],
        "slider": ["aria-valuemax", "aria-valuemin", "aria-valuenow"],
        "spinbutton": ["aria-valuemax", "aria-valuemin", "aria-valuenow"],
        "switch": ["aria-checked"],
        "tab": ["aria-selected"],
        "textbox": ["aria-label", "aria-labelledby"],
    }
    return requirements.get(role, [])


# ─── 4. Keyboard Navigation ───────────────────────────────────

def _check_keyboard_nav(
    content: str, lines: List[str], rel_path: str,
    template_type: str, issues: List[Dict]
) -> None:
    """Detect click handlers without keyboard equivalents."""
    # Find elements with onClick but no onKeyDown
    for m in re.finditer(r'<(\w+)\s+([^>]*?)>', content):
        tag = m.group(1)
        attrs = m.group(2)
        line_num = content[:m.start()].count('\n') + 1

        has_click = bool(re.search(r'\bon(?:Click|click)\s*=', attrs))
        has_keydown = bool(re.search(r'\bon(?:KeyDown|keydown|keypress|KeyPress)\s*=', attrs))

        if has_click and not has_keydown:
            # Skip native interactive elements that already handle keyboard
            native_interactive = {'a', 'button', 'input', 'select', 'textarea', 'summary', 'details'}
            if tag.lower() in native_interactive:
                continue

            # Skip elements with role that implies keyboard handling
            role_match = re.search(r'\brole\s*=\s*["\']([^"\']+)["\']', attrs)
            if role_match and role_match.group(1) in ('button', 'link', 'tab', 'menuitem'):
                # These roles should have keyboard handling but are at least
                # semantically keyboard-interactive. Still flag.
                issues.append({
                    "category": "keyboard_nav",
                    "file": rel_path,
                    "line": line_num,
                    "element": f"<{tag} role='{role_match.group(1)}'>",
                    "severity": "medium",
                    "message": f"Element with role='{role_match.group(1)}' has onClick but no onKeyDown handler",
                    "suggestion": f"Add onKeyDown handler for Enter and Space keys.",
                })
            else:
                # Non-semantic element with click handler — definitely needs keyboard support
                issues.append({
                    "category": "keyboard_nav",
                    "file": rel_path,
                    "line": line_num,
                    "element": f"<{tag}>",
                    "severity": "high",
                    "message": f"Non-interactive <{tag}> has onClick but no keyboard handler",
                    "suggestion": f"Use a <button> instead, or add onKeyDown handler and tabIndex=0.",
                })

    # Check for tabIndex issues
    for m in re.finditer(r'\btabIndex\s*=\s*["\'](\d+)["\']', content):
        tab_value = int(m.group(1))
        line_num = content[:m.start()].count('\n') + 1

        if tab_value > 0:
            issues.append({
                "category": "keyboard_nav",
                "file": rel_path,
                "line": line_num,
                "element": "tabIndex",
                "severity": "medium",
                "message": f"tabIndex={tab_value} disrupts natural tab order",
                "suggestion": "Use tabIndex=0 to add to natural tab order, or -1 to make programmatically focusable.",
            })

    # Check for div/span with onClick but no role or tabIndex (button confusion)
    for m in re.finditer(r'<(div|span)\s+([^>]*?)>', content):
        tag = m.group(1)
        attrs = m.group(2)
        line_num = content[:m.start()].count('\n') + 1

        has_click = bool(re.search(r'\bon(?:Click|click)\s*=', attrs))
        if not has_click:
            continue

        has_role = bool(re.search(r'\brole\s*=', attrs))
        has_tabindex = bool(re.search(r'\btabIndex\s*=', attrs))

        if not has_role and not has_tabindex:
            issues.append({
                "category": "keyboard_nav",
                "file": rel_path,
                "line": line_num,
                "element": f"<{tag}>",
                "severity": "high",
                "message": f"<{tag}> with click handler is not keyboard accessible",
                "suggestion": f"Use <button> instead, or add role='button' and tabIndex=0.",
            })


# ─── 5. Semantic HTML ─────────────────────────────────────────

def _check_semantic_html(
    content: str, lines: List[str], rel_path: str,
    template_type: str, issues: List[Dict]
) -> None:
    """Detect non-semantic elements where semantic ones should be used."""
    # Check for <b> and <i> tags
    for m in re.finditer(r'<(b|i|u)>(.*?)</\1>', content, re.DOTALL):
        tag = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        text = m.group(2).strip()[:50]

        replacements = SEMANTIC_REPLACEMENTS.get(tag, {})
        if replacements:
            replacement_text = ", ".join(
                f"<{k}> {v}" for k, v in list(replacements.items())[:2]
            )
            issues.append({
                "category": "semantic_html",
                "file": rel_path,
                "line": line_num,
                "element": f"<{tag}>",
                "severity": "low",
                "message": f"Non-semantic <{tag}> tag — consider semantic alternative",
                "suggestion": f"Replace with {replacement_text}",
            })

    # Check for div elements that should be semantic landmarks
    # Heuristic: div with id or className suggesting landmark purpose
    landmark_hints = {
        'nav': 'navigation', 'header': 'banner', 'footer': 'contentinfo',
        'sidebar': 'complementary', 'main': 'main', 'content': 'main',
        'menu': 'navigation',
    }

    for m in re.finditer(r'<div\s+([^>]*?)>', content):
        attrs = m.group(1)
        line_num = content[:m.start()].count('\n') + 1

        # Check id and className for landmark hints
        id_match = re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', attrs)
        class_match = re.search(r'\bclass(?:Name)?\s*=\s*["\']([^"\']+)["\']', attrs)

        # Already has a role — skip
        if re.search(r'\brole\s*=', attrs):
            continue

        identifier = ""
        if id_match:
            identifier = id_match.group(1).lower()
        if class_match:
            identifier += " " + class_match.group(1).lower()

        for hint, role in landmark_hints.items():
            if hint in identifier:
                semantic_tag = hint if hint in ('nav', 'header', 'footer', 'main') else 'aside'
                issues.append({
                    "category": "semantic_html",
                    "file": rel_path,
                    "line": line_num,
                    "element": f"<div> (id/class contains '{hint}')",
                    "severity": "low",
                    "message": f"Div used for {role} — use <{semantic_tag}> instead",
                    "suggestion": f"Replace <div> with <{semantic_tag}> for better semantics and accessibility.",
                })
                break


# ─── 6. Color Contrast ────────────────────────────────────────

def _check_color_contrast(
    content: str, lines: List[str], rel_path: str,
    template_type: str, issues: List[Dict]
) -> None:
    """Basic check for inline styles with color/background-color that may have poor contrast."""
    # Find inline style attributes with color properties
    for m in re.finditer(r'style\s*=\s*["\']([^"\']+)["\']', content):
        style_value = m.group(1)
        line_num = content[:m.start()].count('\n') + 1

        has_color = bool(re.search(r'(?<!-)\bcolor\s*:', style_value))
        has_bg = bool(re.search(r'background(?:-color)?\s*:', style_value))

        if has_color and not has_bg:
            issues.append({
                "category": "color_contrast",
                "file": rel_path,
                "line": line_num,
                "element": "inline style",
                "severity": "low",
                "message": "Inline color without matching background-color — potential contrast issue",
                "suggestion": "Verify the text color has sufficient contrast (4.5:1 for normal text) against the background.",
            })
        elif has_bg and not has_color:
            issues.append({
                "category": "color_contrast",
                "file": rel_path,
                "line": line_num,
                "element": "inline style",
                "severity": "low",
                "message": "Inline background-color without matching text color — potential contrast issue",
                "suggestion": "Verify the text color against this background has sufficient contrast (4.5:1).",
            })

    # Check for very light gray text (common contrast mistake)
    for m in re.finditer(r'color\s*:\s*["\']?(#[0-9a-fA-F]{3,8}|rgb\([^)]+\))', content):
        color_value = m.group(1)
        line_num = content[:m.start()].count('\n') + 1

        # Basic heuristic for very light colors
        if _is_likely_light_color(color_value):
            issues.append({
                "category": "color_contrast",
                "file": rel_path,
                "line": line_num,
                "element": "color style",
                "severity": "medium",
                "message": f"Potentially low-contrast text color: {color_value}",
                "suggestion": "Verify contrast ratio meets WCAG AA (4.5:1 for normal text, 3:1 for large text).",
            })


def _is_likely_light_color(color: str) -> bool:
    """Heuristic check if a color is likely too light for text."""
    # Parse hex colors
    hex_match = re.match(r'#([0-9a-fA-F]{3,8})', color)
    if hex_match:
        hex_val = hex_match.group(1)
        if len(hex_val) == 3:
            r, g, b = int(hex_val[0]*2, 16), int(hex_val[1]*2, 16), int(hex_val[2]*2, 16)
        elif len(hex_val) >= 6:
            r, g, b = int(hex_val[0:2], 16), int(hex_val[2:4], 16), int(hex_val[4:6], 16)
        else:
            return False

        # Luminance approximation
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return luminance > 0.7  # Likely too light

    # Parse rgb()
    rgb_match = re.match(r'rgb\((\d+),\s*(\d+),\s*(\d+)\)', color)
    if rgb_match:
        r, g, b = int(rgb_match.group(1)), int(rgb_match.group(2)), int(rgb_match.group(3))
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return luminance > 0.7

    return False


# ─── 7. Heading Order ─────────────────────────────────────────

def _collect_headings(
    content: str, lines: List[str], rel_path: str, template_type: str
) -> List[Dict]:
    """Collect all headings in a file for order analysis."""
    headings = []

    # HTML/JSX headings: <h1>, <h2>, etc.
    for m in re.finditer(r'<h([1-6])[^>]*>', content):
        level = int(m.group(1))
        line_num = content[:m.start()].count('\n') + 1
        headings.append({
            "file": rel_path,
            "line": line_num,
            "level": level,
        })

    # ARIA role="heading" with aria-level
    for m in re.finditer(r'role\s*=\s*["\']heading["\'][^>]*aria-level\s*=\s*["\'](\d+)["\']', content):
        level = int(m.group(1))
        line_num = content[:m.start()].count('\n') + 1
        headings.append({
            "file": rel_path,
            "line": line_num,
            "level": level,
        })

    return headings


def _analyze_heading_order(all_headings: List[Dict], issues: List[Dict]) -> None:
    """Analyze heading order across files for skipped levels."""
    # Group by file and check order within each file
    by_file = defaultdict(list)
    for h in all_headings:
        by_file[h["file"]].append(h)

    for file_path, headings in by_file.items():
        # Sort by line number
        headings.sort(key=lambda x: x["line"])

        prev_level = 0
        for h in headings:
            level = h["level"]

            # First heading should ideally be h1
            if prev_level == 0 and level > 1:
                # This is informational — not necessarily an error
                pass

            # Check for skipped levels (e.g., h1 → h3 without h2)
            if prev_level > 0 and level > prev_level + 1:
                issues.append({
                    "category": "heading_order",
                    "file": h["file"],
                    "line": h["line"],
                    "element": f"h{level}",
                    "severity": "medium",
                    "message": f"Heading level skipped: h{prev_level} → h{level} (missing h{prev_level + 1})",
                    "suggestion": f"Use h{prev_level + 1} before h{level} to maintain proper heading hierarchy.",
                })

            prev_level = level

    # Check if any file has multiple h1 tags
    for file_path, headings in by_file.items():
        h1_count = sum(1 for h in headings if h["level"] == 1)
        if h1_count > 1:
            first_h1 = next(h for h in headings if h["level"] == 1)
            issues.append({
                "category": "heading_order",
                "file": file_path,
                "line": first_h1["line"],
                "element": "h1",
                "severity": "low",
                "message": f"Multiple h1 headings found ({h1_count}) — should have only one per page",
                "suggestion": "Use a single h1 per page. Use h2-h6 for subsections.",
            })


# ─── 8. Link Text ─────────────────────────────────────────────

def _check_link_text(
    content: str, lines: List[str], rel_path: str,
    template_type: str, issues: List[Dict]
) -> None:
    """Detect vague or uninformative link text."""
    # Find <a> tags with text content
    for m in re.finditer(r'<a\s+([^>]*?)>(.*?)</a>', content, re.DOTALL):
        attrs = m.group(1)
        text = m.group(2).strip()
        line_num = content[:m.start()].count('\n') + 1

        # Remove HTML tags from link text
        clean_text = re.sub(r'<[^>]+>', '', text).strip().lower()

        # Check if link has aria-label (acceptable even with vague text)
        if re.search(r'\baria-label\s*=\s*["\']', attrs):
            continue

        # Check if link has aria-labelledby
        if re.search(r'\baria-labelledby\s*=\s*["\']', attrs):
            continue

        # Check for title attribute (acceptable but not ideal)
        has_title = bool(re.search(r'\btitle\s*=\s*["\']', attrs))

        # Check for vague link text
        if clean_text in VAGUE_LINK_TEXT:
            severity = "high" if clean_text in ("click here", "here", "link") else "medium"
            suggestion = "Use descriptive link text that makes sense out of context."
            if has_title:
                suggestion += " The title attribute helps but is not a replacement for descriptive link text."
            issues.append({
                "category": "link_text",
                "file": rel_path,
                "line": line_num,
                "element": f"<a>{clean_text}</a>",
                "severity": severity,
                "message": f"Vague link text: '{clean_text}'",
                "suggestion": suggestion,
            })

        # Check for very short link text (< 4 chars) that might not be vague but is uninformative
        elif len(clean_text) < 4 and clean_text and clean_text not in {'api', 'faq', 'css', 'svg', 'npm'}:
            if not has_title:
                issues.append({
                    "category": "link_text",
                    "file": rel_path,
                    "line": line_num,
                    "element": f"<a>{clean_text}</a>",
                    "severity": "low",
                    "message": f"Short link text: '{clean_text}' — may not be descriptive enough",
                    "suggestion": "Use more descriptive link text or add aria-label.",
                })

        # Check for link text that's just a URL
        elif re.match(r'https?://', clean_text):
            issues.append({
                "category": "link_text",
                "file": rel_path,
                "line": line_num,
                "element": f"<a>{clean_text[:50]}</a>",
                "severity": "medium",
                "message": "Link text is a raw URL — not descriptive for screen readers",
                "suggestion": "Use descriptive text instead of the URL. If the URL is needed, use it as a visible note after descriptive text.",
            })


# ─── 9. Focus Management ──────────────────────────────────────

def _check_focus_management(
    content: str, lines: List[str], rel_path: str,
    template_type: str, issues: List[Dict]
) -> None:
    """Check for focus management issues — modals without traps, auto-focus problems."""
    # Find modal/dialog patterns
    modal_patterns = [
        (r'role\s*=\s*["\']dialog["\']', "dialog_role"),
        (r'role\s*=\s*["\']alertdialog["\']', "alertdialog_role"),
        (r'class(?:Name)?\s*=\s*["\'][^"\']*modal[^"\']*["\']', "modal_class"),
        (r'class(?:Name)?\s*=\s*["\'][^"\']*dialog[^"\']*["\']', "dialog_class"),
    ]

    for pattern, modal_type in modal_patterns:
        for m in re.finditer(pattern, content):
            line_num = content[:m.start()].count('\n') + 1

            # Check for focus trap
            has_focus_trap = bool(re.search(
                r'(?:FocusTrap|focus-trap|FocusLock|focusLock|trapFocus|aria-modal)',
                content
            ))

            if not has_focus_trap:
                issues.append({
                    "category": "focus_management",
                    "file": rel_path,
                    "line": line_num,
                    "element": modal_type,
                    "severity": "high",
                    "message": "Modal/dialog without focus trap — keyboard users can tab out",
                    "suggestion": "Add a focus trap component or implement focus cycling within the modal.",
                })

    # Check for auto-focus attributes
    for m in re.finditer(r'\bautoFocus(?:\s*=\s*["\']?(?:true|{true})["\']?)?', content):
        line_num = content[:m.start()].count('\n') + 1

        issues.append({
            "category": "focus_management",
            "file": rel_path,
            "line": line_num,
            "element": "autoFocus",
            "severity": "medium",
            "message": "autoFocus can disorient users, especially on page load",
            "suggestion": "Avoid autoFocus on page load. Use it only in response to user actions (e.g., opening a modal).",
        })

    # Check for removed focus outlines (a11y anti-pattern)
    outline_patterns = [
        r'outline\s*:\s*(?:none|0)',
        r'outline-width\s*:\s*0',
        r'outline-style\s*:\s*none',
    ]
    for pattern in outline_patterns:
        for m in re.finditer(pattern, content):
            line_num = content[:m.start()].count('\n') + 1

            # Check if there's a :focus-visible or :focus alternative
            context_start = max(0, m.start() - 200)
            context = content[context_start:m.end()]
            has_focus_style = bool(re.search(
                r':focus-visible|:focus-ring|outline.*:focus|box-shadow.*:focus',
                context
            ))

            if not has_focus_style:
                issues.append({
                    "category": "focus_management",
                    "file": rel_path,
                    "line": line_num,
                    "element": "outline: none",
                    "severity": "high",
                    "message": "Focus outline removed without alternative — keyboard users can't see focus",
                    "suggestion": "Don't remove outlines. If needed, provide a custom :focus-visible style instead.",
                })


# ─── Recommendations ───────────────────────────────────────────

def _generate_recommendations(
    issues: List[Dict],
    by_category: Dict[str, int],
    by_severity: Dict[str, int]
) -> List[str]:
    """Generate actionable recommendations."""
    recs = []

    high_count = by_severity.get("high", 0)
    if high_count > 0:
        recs.append(
            f"CRITICAL: {high_count} high-severity accessibility issues found. "
            f"These block users with disabilities from using the application. Fix immediately."
        )

    missing_alt = by_category.get("missing_alt", 0)
    if missing_alt > 0:
        recs.append(
            f"Found {missing_alt} images without alt text. Add descriptive alt attributes "
            f"for meaningful images or alt='' for decorative ones."
        )

    missing_label = by_category.get("missing_label", 0)
    if missing_label > 0:
        recs.append(
            f"Found {missing_label} form inputs without labels. Every input needs an associated "
            f"<label> element or aria-label/aria-labelledby attribute."
        )

    keyboard = by_category.get("keyboard_nav", 0)
    if keyboard > 0:
        recs.append(
            f"Found {keyboard} keyboard navigation issues. Interactive elements must be "
            f"reachable and operable via keyboard alone. Replace <div onClick> with <button>."
        )

    aria = by_category.get("aria_issues", 0)
    if aria > 0:
        recs.append(
            f"Found {aria} ARIA issues. Remember: no ARIA is better than bad ARIA. "
            f"Use native HTML elements first, then add ARIA for custom components."
        )

    semantic = by_category.get("semantic_html", 0)
    if semantic > 0:
        recs.append(
            f"Found {semantic} semantic HTML issues. Use <nav>, <main>, <header>, <footer>, "
            f"<article>, <section> instead of generic <div> elements."
        )

    heading = by_category.get("heading_order", 0)
    if heading > 0:
        recs.append(
            f"Found {heading} heading order issues. Maintain a logical heading hierarchy "
            f"(h1 → h2 → h3) without skipping levels."
        )

    link = by_category.get("link_text", 0)
    if link > 0:
        recs.append(
            f"Found {link} vague link text issues. Link text should be descriptive and "
            f"make sense out of context (avoid 'click here', 'read more')."
        )

    focus = by_category.get("focus_management", 0)
    if focus > 0:
        recs.append(
            f"Found {focus} focus management issues. Modals need focus traps, "
            f"and focus outlines should never be removed without alternatives."
        )

    contrast = by_category.get("color_contrast", 0)
    if contrast > 0:
        recs.append(
            f"Found {contrast} potential color contrast issues. Use a contrast checker tool "
            f"to verify WCAG AA compliance (4.5:1 for normal text, 3:1 for large text)."
        )

    if not issues:
        recs.append("No accessibility issues detected. Keep up the good work!")

    # General best practice
    total = sum(by_category.values())
    if total > 10:
        recs.append(
            f"Total of {total} a11y issues found. Consider integrating automated "
            f"a11y testing (axe-core, eslint-plugin-jsx-a11y) into your CI pipeline."
        )

    return recs
