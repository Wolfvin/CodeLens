"""
Deep CSS Analysis Engine for CodeLens — v5
Detects CSS-specific issues: unused variables, orphan keyframes, specificity wars,
duplicate properties, unused media queries, and z-index abuse.

Answers: "Are there CSS custom properties declared but never used?"
Answers: "Are there @keyframes animations with no references?"
Answers: "Do we have specificity wars, !important overuse, or z-index chaos?"
Answers: "Are there duplicate property declarations within the same rule block?"
Answers: "Are there @media queries that don't match our breakpoint system?"

Architecture:
- Regex + CSS-aware parsing for declaration / reference extraction
- File discovery via os.walk, scanning .css/.scss/.less/.sass/.vue/.svelte files
- Cross-reference CSS variables with usage in HTML/JS files
- Count @keyframes declarations vs animation references
- Analyze selector specificity by counting ID/class/element combinator counts
- Detect !important usage frequency
- Track z-index values across all files
- Detect duplicate properties within the same rule block
- Validate @media queries against configured breakpoint system

CSS Issue Categories (by severity):
- high:   orphan_keyframes, unused_vars, z_index_abuse (excessive values)
- medium: specificity_wars, duplicate_props, unused_media
- low:    z_index_abuse (too many values), specificity_wars (mild)
"""

import os
import re
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS


# ─── Configuration ─────────────────────────────────────────────

CSS_EXTENSIONS = {".css", ".scss", ".less", ".sass"}
COMPONENT_EXTENSIONS = {".vue", ".svelte"}
ALL_STYLE_EXTENSIONS = CSS_EXTENSIONS | COMPONENT_EXTENSIONS

HTML_JS_EXTENSIONS = {
    ".html", ".htm", ".jsx", ".tsx", ".js", ".mjs", ".cjs", ".ts",
}

# Performance limits
MAX_FILE_SIZE = 200 * 1024  # 200KB — skip files larger than this
MAX_FINDINGS = 500           # Cap total findings

# ─── Thresholds ────────────────────────────────────────────────

SPECIFICITY_DEPTH_THRESHOLD = 4       # Number of combinators to flag
SPECIFICITY_DEPTH_CRITICAL = 6        # Deep nesting critical
IMPORTANT_PER_FILE_THRESHOLD = 5      # !important uses per file to flag
IMPORTANT_PER_FILE_CRITICAL = 10      # !important uses per file critical
Z_INDEX_EXCESSIVE = 9999              # z-index above this is abuse
Z_INDEX_TOO_MANY_UNIQUE = 15          # Too many distinct z-index values
DUPLICATE_PROPS_SEVERITY_THRESHOLD = 3  # Duplicate props in same file to escalate

# ─── Default Breakpoint System ─────────────────────────────────
# Common breakpoint values (in px). @media queries using these values
# (or close approximations) are considered "valid". Queries using
# values not in this set are flagged as potentially unused.

DEFAULT_BREAKPOINTS = {
    320, 375, 425, 480,               # Mobile
    576, 600, 640,                     # Small tablets
    768,                               # Tablets
    896, 900, 960,                     # Large tablets
    1024, 1080,                        # Laptops
    1152, 1200, 1280,                  # Desktops
    1366, 1440,                        # Large desktops
    1536, 1600, 1920,                  # Full HD+
}

BREAKPOINT_TOLERANCE = 5  # Allow ±5px variance from known breakpoints


# ─── Main Analysis Function ────────────────────────────────────

def analyze_css_deep(
    workspace: str,
    severity: Optional[str] = None,
    category: Optional[str] = None,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Deep CSS analysis: detect unused variables, orphan keyframes, specificity wars,
    duplicate properties, unused media queries, and z-index abuse.

    Args:
        workspace: Absolute path to workspace
        severity: Optional filter: "high", "medium", "low"
        category: Optional filter: "unused_vars", "orphan_keyframes",
                  "specificity_wars", "duplicate_props", "unused_media",
                  "z_index_abuse"
        config: CodeLens config dict (may contain "breakpoints" list,
                "ignore_dirs" set, or custom thresholds)

    Returns:
        Dict with findings, stats, and recommendations
    """
    workspace = os.path.abspath(workspace)

    # Merge config overrides
    cfg = config or {}
    ignore_dirs = DEFAULT_IGNORE_DIRS | set(cfg.get("ignore_dirs", []))
    breakpoints = _resolve_breakpoints(cfg.get("breakpoints"))

    valid_categories = {
        "unused_vars", "orphan_keyframes", "specificity_wars",
        "duplicate_props", "unused_media", "z_index_abuse",
    }
    active_categories = {category} if category and category in valid_categories else valid_categories

    # ─── Collection containers ────────────────────────────────
    findings: List[Dict[str, Any]] = []

    # Cross-file tracking
    css_var_declarations: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    css_var_references: Set[str] = set()

    keyframes_declarations: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    keyframes_references: Set[str] = set()

    z_index_values: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    important_usage: Dict[str, int] = defaultdict(int)

    css_files_scanned = 0
    html_js_files_scanned = 0

    # ─── Phase 1: Scan CSS / style files ──────────────────────
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in ALL_STYLE_EXTENSIONS:
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            try:
                file_size = os.path.getsize(file_path)
                if file_size > MAX_FILE_SIZE:
                    css_files_scanned += 1
                    continue
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            css_files_scanned += 1

            # Extract style blocks from component files (.vue / .svelte)
            style_content = _extract_style_block(content, ext)
            if style_content is None:
                style_content = content
            if not style_content.strip():
                continue

            # --- CSS custom properties ---
            if "unused_vars" in active_categories:
                decls, refs = _extract_css_vars(style_content, rel_path)
                for var_name, info_list in decls.items():
                    css_var_declarations[var_name].extend(info_list)
                css_var_references.update(refs)

            # --- @keyframes ---
            if "orphan_keyframes" in active_categories:
                k_decls, k_refs = _extract_keyframes(style_content, rel_path)
                for kf_name, info_list in k_decls.items():
                    keyframes_declarations[kf_name].extend(info_list)
                keyframes_references.update(k_refs)

            # --- Specificity wars ---
            if "specificity_wars" in active_categories:
                spec_findings = _detect_specificity_wars(style_content, rel_path)
                findings.extend(spec_findings)

            # --- Duplicate properties ---
            if "duplicate_props" in active_categories:
                dup_findings = _detect_duplicate_props(style_content, rel_path)
                findings.extend(dup_findings)

            # --- @media queries ---
            if "unused_media" in active_categories:
                media_findings = _detect_unused_media(style_content, rel_path, breakpoints)
                findings.extend(media_findings)

            # --- z-index tracking ---
            if "z_index_abuse" in active_categories:
                z_vals, imp_count = _extract_z_index_and_important(style_content, rel_path)
                for z_val, info_list in z_vals.items():
                    z_index_values[z_val].extend(info_list)
                important_usage[rel_path] += imp_count

    # ─── Phase 2: Scan HTML / JS files for var() references ──
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in HTML_JS_EXTENSIONS:
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            try:
                file_size = os.path.getsize(file_path)
                if file_size > MAX_FILE_SIZE:
                    html_js_files_scanned += 1
                    continue
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            html_js_files_scanned += 1

            # Cross-reference CSS variables
            if "unused_vars" in active_categories:
                refs = _find_var_references_in_html_js(content)
                css_var_references.update(refs)

            # Cross-reference keyframes
            if "orphan_keyframes" in active_categories:
                refs = _find_keyframe_references_in_html_js(content)
                keyframes_references.update(refs)

    # ─── Phase 3: Compute cross-file findings ─────────────────

    # Unused CSS variables
    if "unused_vars" in active_categories:
        for var_name, info_list in css_var_declarations.items():
            if var_name not in css_var_references:
                for info in info_list:
                    findings.append({
                        "type": "css_issue",
                        "category": "unused_vars",
                        "severity": "medium",
                        "file": info["file"],
                        "line": info["line"],
                        "detail": f"CSS custom property '{var_name}' declared but never used via var()",
                        "name": var_name,
                        "fix_suggestion": f"Remove unused variable or reference it via var({var_name})",
                    })

    # Orphan keyframes
    if "orphan_keyframes" in active_categories:
        for kf_name, info_list in keyframes_declarations.items():
            if kf_name not in keyframes_references:
                for info in info_list:
                    findings.append({
                        "type": "css_issue",
                        "category": "orphan_keyframes",
                        "severity": "high",
                        "file": info["file"],
                        "line": info["line"],
                        "detail": f"@keyframes '{kf_name}' declared but never referenced by animation/animation-name",
                        "name": kf_name,
                        "fix_suggestion": f"Remove orphan @keyframes {kf_name} or reference it via animation-name: {kf_name}",
                    })

    # z-index abuse
    if "z_index_abuse" in active_categories:
        # Excessive z-index values
        for z_val, info_list in z_index_values.items():
            try:
                numeric_val = int(z_val)
            except ValueError:
                continue
            if numeric_val > Z_INDEX_EXCESSIVE:
                for info in info_list:
                    findings.append({
                        "type": "css_issue",
                        "category": "z_index_abuse",
                        "severity": "high",
                        "file": info["file"],
                        "line": info["line"],
                        "detail": f"Excessive z-index value ({z_val}) — above {Z_INDEX_EXCESSIVE} indicates layout problems",
                        "name": f"z-index:{z_val}",
                        "fix_suggestion": "Rethink stacking context instead of escalating z-index values. Use isolated stacking contexts.",
                    })

        # Too many unique z-index values
        unique_z_values = set()
        for z_val, info_list in z_index_values.items():
            unique_z_values.add(z_val)
        if len(unique_z_values) > Z_INDEX_TOO_MANY_UNIQUE:
            findings.append({
                "type": "css_issue",
                "category": "z_index_abuse",
                "severity": "medium",
                "file": "(workspace-wide)",
                "line": 0,
                "detail": f"{len(unique_z_values)} distinct z-index values found — indicates unmanaged stacking contexts",
                "name": f"z-index-count:{len(unique_z_values)}",
                "fix_suggestion": (
                    "Create a z-index scale (e.g., z-10, z-20, z-30, z-40, z-50) "
                    "and limit values to that scale. Use CSS custom properties for the scale."
                ),
            })

    # !important overuse
    if "specificity_wars" in active_categories:
        for rel_path, imp_count in important_usage.items():
            if imp_count >= IMPORTANT_PER_FILE_CRITICAL:
                findings.append({
                    "type": "css_issue",
                    "category": "specificity_wars",
                    "severity": "high",
                    "file": rel_path,
                    "line": 0,
                    "detail": f"{imp_count} !important declarations in this file — indicates specificity conflicts",
                    "name": f"!important-overuse:{imp_count}",
                    "fix_suggestion": (
                        "Refactor selectors to increase specificity naturally instead of using !important. "
                        "Consider using CSS layers or more specific selectors."
                    ),
                })
            elif imp_count >= IMPORTANT_PER_FILE_THRESHOLD:
                findings.append({
                    "type": "css_issue",
                    "category": "specificity_wars",
                    "severity": "medium",
                    "file": rel_path,
                    "line": 0,
                    "detail": f"{imp_count} !important declarations in this file — may indicate specificity issues",
                    "name": f"!important-overuse:{imp_count}",
                    "fix_suggestion": (
                        "Review !important usage. Each use typically masks a specificity problem. "
                        "Prefer more specific selectors or restructuring CSS."
                    ),
                })

    # ─── Apply filters ────────────────────────────────────────
    if severity:
        findings = [f for f in findings if f.get("severity") == severity]
    if category and category in valid_categories:
        findings = [f for f in findings if f.get("category") == category]

    # ─── Deduplicate findings ─────────────────────────────────
    findings = _deduplicate_findings(findings)

    # ─── Compute stats ────────────────────────────────────────
    stats = _compute_stats(findings, css_files_scanned, html_js_files_scanned)

    # ─── Generate recommendations ─────────────────────────────
    recommendations = _generate_recommendations(findings, stats)

    return {
        "status": "ok",
        "workspace": workspace,
        "severity_filter": severity,
        "stats": stats,
        "findings": findings[:200],  # Cap to avoid explosion
        "recommendations": recommendations,
    }


# ─── CSS Custom Property Extraction ───────────────────────────

def _extract_css_vars(
    content: str, rel_path: str
) -> Tuple[Dict[str, List[Dict[str, Any]]], Set[str]]:
    """
    Extract CSS custom property declarations (--var-name) and references (var(--var-name)).

    Returns:
        Tuple of (declarations dict, reference set)
    """
    declarations: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    references: Set[str] = set()

    lines = content.split('\n')

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Skip comments
        if stripped.startswith('/*') or stripped.startswith('//') or stripped.startswith('*'):
            continue

        # Detect declarations: --var-name:
        for m in re.finditer(r'(--[\w-]+)\s*:', line):
            var_name = m.group(1)
            declarations[var_name].append({
                "file": rel_path,
                "line": i + 1,
            })

        # Detect references: var(--var-name)
        for m in re.finditer(r'var\(\s*(--[\w-]+)', line):
            var_name = m.group(1)
            references.add(var_name)

    return declarations, references


# ─── @keyframes Extraction ────────────────────────────────────

def _extract_keyframes(
    content: str, rel_path: str
) -> Tuple[Dict[str, List[Dict[str, Any]]], Set[str]]:
    """
    Extract @keyframes declarations and animation/animation-name references.

    Returns:
        Tuple of (declarations dict, reference set)
    """
    declarations: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    references: Set[str] = set()

    lines = content.split('\n')

    for i, line in enumerate(lines):
        stripped = line.strip()

        # @keyframes declaration
        m = re.match(r'@keyframes\s+([\w-]+)', stripped)
        if m:
            kf_name = m.group(1)
            declarations[kf_name].append({
                "file": rel_path,
                "line": i + 1,
            })
            continue

        # animation: <duration> <timing> <delay> <iteration> <direction> <fill> <play-state> <name>
        # animation-name: <name>
        # Both can reference keyframes by name

        # animation-name: <name> (use search to find within multi-property lines)
        m = re.search(r'animation-name\s*:\s*([\w-]+)', stripped)
        if m:
            references.add(m.group(1))
            continue

        # animation: ... <name> (name is the last identifier that isn't a keyword)
        m = re.search(r'animation\s*:\s*(.+?)(?:;|$)', stripped)
        if m:
            value = m.group(1).rstrip(';').strip()
            # Extract the animation name from the shorthand.
            # CSS animation keywords to exclude
            css_keywords = {
                'ease', 'ease-in', 'ease-out', 'ease-in-out', 'linear',
                'step-start', 'step-end', 'cubic-bezier',
                'normal', 'reverse', 'alternate', 'alternate-reverse',
                'none', 'forwards', 'backwards', 'both',
                'running', 'paused', 'infinite',
                'initial', 'inherit', 'unset',
            }
            tokens = re.split(r'\s+', value)
            for token in tokens:
                # Skip pure numbers (durations, delays), keywords, and functional notations
                if re.match(r'^[\d.]+', token):
                    continue
                if token.startswith('cubic-bezier') or token.startswith('steps('):
                    continue
                if token.lower() in css_keywords:
                    continue
                # The remaining token is likely the animation name
                references.add(token)
                break  # Only one name per animation shorthand

    return declarations, references


# ─── Specificity Wars Detection ────────────────────────────────

def _detect_specificity_wars(content: str, rel_path: str) -> List[Dict[str, Any]]:
    """
    Detect selectors with excessively high specificity.

    Flags:
    - Deeply nested selectors (e.g., .a .b .c .d .e)
    - Overly qualified selectors (e.g., div#id.class)
    - Individual !important usage (aggregated per-file in Phase 3)

    v6: Tracks brace depth to distinguish CSS rule selectors from property
    values that happen to contain braces (rgba(), var(), calc(), etc.).
    Only extracts selectors at brace depth 0 (top-level rules).
    """
    findings: List[Dict[str, Any]] = []

    # v6: State machine approach — track brace depth so we only
    # extract selectors from the top level of the CSS file.
    # This prevents false positives from CSS property values like
    # "rgba(0, 0, 0, 0.1)" or "var(--ds-gray-alpha-600)".
    lines = content.split('\n')
    brace_depth = 0

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Skip comments
        if not stripped or stripped.startswith('/*') or stripped.startswith('//'):
            continue

        # Track brace depth for this line
        # We need to process opening and closing braces carefully
        # to distinguish rule-level braces from value-level braces.

        # v6: Check if this line is a CSS declaration (property: value) at the current depth.
        # A declaration has a colon BEFORE any opening brace at this level.
        # e.g., "  color: rgba(0, 0, 0, 0.1);" — the { inside rgba() is not a rule start.
        is_declaration = False
        if brace_depth > 0:
            # Check if line looks like a CSS property declaration
            decl_match = re.match(r'^[\s-]*[\w-]+\s*:', stripped)
            if decl_match:
                is_declaration = True

        # Only process lines at brace depth 0 (top-level) as potential selectors.
        # Lines at depth > 0 are inside rule bodies and can't be selectors.
        if brace_depth == 0 and not is_declaration:
            if not stripped.startswith('@') and '{' in stripped:
                # This might be a selector — extract the part before {
                # But first, count braces in this line to update depth
                opening = stripped.count('{')
                closing = stripped.count('}')
                brace_depth += opening - closing

                # Extract the selector part (before the FIRST {)
                selector_part = stripped.split('{')[0].strip()
                if not selector_part:
                    continue

                # v6: Validate that this is actually a selector, not a property value.
                # Real CSS selectors should:
                # 1. Not start with a digit (property values often start with 0, 1px, etc.)
                # 2. Not contain CSS value functions like rgba(), var(), calc()
                # 3. Not be a bare value like "0px 1px 1px"
                if re.match(r'^[\d]', selector_part):
                    continue  # Starts with a digit — not a selector
                if re.match(r'^(from|to)\s', selector_part, re.IGNORECASE):
                    continue  # Keyframe from/to — not a selector
                if re.search(r'\b(rgba?|hsla?|var|calc|clamp|min|max|env|url|linear-gradient|radial-gradient|conic-gradient)\s*\(', selector_part):
                    continue  # Contains CSS value functions — not a selector
                # Skip if the "selector" looks like a CSS value with units
                if re.match(r'^[\d.]+\s*(px|em|rem|%|vh|vw|deg|s|ms)', selector_part):
                    continue

                # Handle multiple selectors separated by comma
                selectors = [s.strip() for s in selector_part.split(',')]

                for selector in selectors:
                    if not selector:
                        continue

                    # Count combinator depth (spaces between selectors indicate nesting)
                    parts = re.split(r'\s+[>+~]?\s*', selector)
                    parts = [p.strip() for p in parts if p.strip()]

                    depth = len(parts)

                    # Count IDs, classes, and element selectors
                    id_count = selector.count('#')
                    class_count = selector.count('.')

                    # Detect overly qualified: element + id + class like div#id.class
                    has_element = bool(re.match(r'^[a-zA-Z][\w-]*', parts[0]) if parts else False)
                    is_overqualified = has_element and id_count > 0 and class_count > 0

                    if depth >= SPECIFICITY_DEPTH_CRITICAL:
                        findings.append({
                            "type": "css_issue",
                            "category": "specificity_wars",
                            "severity": "high",
                            "file": rel_path,
                            "line": i + 1,
                            "detail": f"Excessively deep selector nesting ({depth} levels): '{selector}'",
                            "name": selector[:80],
                            "fix_suggestion": (
                                "Reduce nesting depth. Use BEM methodology or CSS modules "
                                "to flatten selector specificity."
                            ),
                        })
                    elif depth >= SPECIFICITY_DEPTH_THRESHOLD:
                        findings.append({
                            "type": "css_issue",
                            "category": "specificity_wars",
                            "severity": "medium",
                            "file": rel_path,
                            "line": i + 1,
                            "detail": f"Deeply nested selector ({depth} levels): '{selector}'",
                            "name": selector[:80],
                            "fix_suggestion": (
                                "Consider flattening this selector. Prefer single-class selectors "
                                "or BEM naming (e.g., .block__element--modifier)."
                            ),
                        })

                    if is_overqualified:
                        findings.append({
                            "type": "css_issue",
                            "category": "specificity_wars",
                            "severity": "medium",
                            "file": rel_path,
                            "line": i + 1,
                    "detail": f"Overly qualified selector: '{selector}' — combines element, ID, and class",
                    "name": selector[:80],
                    "fix_suggestion": (
                        "Avoid qualifying class/ID selectors with element types. "
                        "Use just the class or ID selector alone."
                    ),
                })
        else:
            # v6: Track brace depth even for lines that aren't selectors
            # so we know when we're inside a rule body vs at top level
            opening = stripped.count('{')
            closing = stripped.count('}')
            brace_depth += opening - closing
            if brace_depth < 0:
                brace_depth = 0

    return findings


# ─── Duplicate Properties Detection ───────────────────────────

def _detect_duplicate_props(content: str, rel_path: str) -> List[Dict[str, Any]]:
    """
    Detect CSS rule blocks that declare the same property twice.

    Example:
        .btn { color: red; color: blue; }  ← duplicate 'color'

    Handles both single-line rules (.btn { color: red; color: blue; })
    and multi-line rules where properties span multiple lines.
    """
    findings: List[Dict[str, Any]] = []

    lines = content.split('\n')
    current_block_props: Dict[str, List[int]] = {}  # prop_name -> [line_numbers]
    current_selector: str = ""
    brace_depth = 0
    selector_pending: Optional[str] = None  # Selector found before {

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Skip comments
        if stripped.startswith('/*') or stripped.startswith('//') or stripped.startswith('*'):
            continue

        # Check if this line looks like a selector (no { yet, but could be one)
        if brace_depth == 0 and '{' not in stripped and not stripped.endswith(','):
            # Might be a multi-line selector — track it
            potential_selector = stripped.rstrip(',').strip()
            if potential_selector and not potential_selector.startswith('@'):
                selector_pending = potential_selector
            continue

        # Process the line character-by-character for braces, collecting
        # property declarations as we go within brace_depth == 1.
        col = 0
        while col < len(stripped):
            ch = stripped[col]

            if ch == '{':
                brace_depth += 1
                if brace_depth == 1:
                    # Starting a new rule block
                    current_block_props = {}
                    # Extract selector from everything before this { on this line
                    before_brace = stripped[:col].strip()
                    # Also consider pending selector from prior lines
                    if before_brace:
                        current_selector = before_brace
                    elif selector_pending:
                        current_selector = selector_pending
                    selector_pending = None
                    # Extract properties after { on the same line
                    after_brace = stripped[col + 1:]
                    _collect_props_from_fragment(after_brace, i + 1, current_block_props)

            elif ch == '}':
                brace_depth -= 1
                if brace_depth == 0:
                    # Exiting a rule block — check for duplicates
                    for prop_name, line_nums in current_block_props.items():
                        if len(line_nums) > 1:
                            findings.append({
                                "type": "css_issue",
                                "category": "duplicate_props",
                                "severity": "medium",
                                "file": rel_path,
                                "line": line_nums[1],  # Report the second (overriding) occurrence
                                "detail": (
                                    f"Duplicate property '{prop_name}' in rule "
                                    f"'{_truncate_selector(current_selector)}' "
                                    f"(declared on lines {line_nums[0]} and {line_nums[1]})"
                                ),
                                "name": prop_name,
                                "fix_suggestion": (
                                    f"Remove the duplicate '{prop_name}' declaration. "
                                    f"The second declaration (line {line_nums[1]}) overrides the first "
                                    f"(line {line_nums[0]}). If intentional, consider adding a comment."
                                ),
                            })
                    current_block_props = {}
                    current_selector = ""
                elif brace_depth > 0:
                    # Exiting a nested block (e.g., @media inner) — no action
                    pass

            elif brace_depth == 1 and ch not in ('{', '}'):
                # Inside a top-level rule block — just advance; we'll
                # pick up properties below for the full line.
                pass

            col += 1

        # Inside a rule block (brace_depth == 1), extract property declarations
        # from the entire line content (handles multi-line properties).
        if brace_depth == 1:
            _collect_props_from_fragment(stripped, i + 1, current_block_props)

    return findings


def _collect_props_from_fragment(
    fragment: str,
    line_num: int,
    block_props: Dict[str, List[int]],
) -> None:
    """
    Extract CSS property declarations from a text fragment and add them to block_props.

    Handles semicolon-separated properties on a single line/fragment:
        "color: red; color: blue; margin: 0"
    """
    # Split by semicolons to get individual declarations
    declarations = fragment.split(';')
    for decl in declarations:
        decl = decl.strip()
        if not decl or decl == '}':
            continue
        m = re.match(r'^([\w-]+)\s*:', decl)
        if m:
            prop_name = m.group(1).lower()
            # Skip CSS custom properties (handled separately in unused_vars)
            if prop_name.startswith('--'):
                continue
            if prop_name not in block_props:
                block_props[prop_name] = []
            block_props[prop_name].append(line_num)


# ─── Unused @media Detection ──────────────────────────────────

def _detect_unused_media(
    content: str, rel_path: str, breakpoints: Set[int]
) -> List[Dict[str, Any]]:
    """
    Detect @media queries that target breakpoints not matching the configured system.

    Only flags queries using pixel-based width conditions (min-width, max-width)
    that don't match any known breakpoint within a tolerance.
    """
    findings: List[Dict[str, Any]] = []

    lines = content.split('\n')

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Match @media queries
        m = re.match(r'@media\s+(.+)', stripped)
        if not m:
            continue

        media_condition = m.group(1).strip().rstrip('{').strip()

        # Extract pixel values from min-width / max-width conditions
        pixel_values = re.findall(r'(?:min-width|max-width)\s*:\s*(\d+)px', media_condition)

        if not pixel_values:
            # No pixel-based width queries — skip (could be print, screen, etc.)
            continue

        # Check each pixel value against breakpoints
        for px_str in pixel_values:
            try:
                px_val = int(px_str)
            except ValueError:
                continue

            # Check if this value is close to any known breakpoint
            is_known = any(
                abs(px_val - bp) <= BREAKPOINT_TOLERANCE
                for bp in breakpoints
            )

            if not is_known:
                findings.append({
                    "type": "css_issue",
                    "category": "unused_media",
                    "severity": "low",
                    "file": rel_path,
                    "line": i + 1,
                    "detail": (
                        f"@media query targets {px_val}px which doesn't match "
                        f"any configured breakpoint"
                    ),
                    "name": f"media-{px_val}px",
                    "fix_suggestion": (
                        f"Align this breakpoint ({px_val}px) with your design system. "
                        f"Common breakpoints: 576, 768, 1024, 1280, 1536px. "
                        f"Or add {px_val}px to your breakpoints config."
                    ),
                })

    return findings


# ─── z-index and !important Extraction ────────────────────────

def _extract_z_index_and_important(
    content: str, rel_path: str
) -> Tuple[Dict[str, List[Dict[str, Any]]], int]:
    """
    Extract z-index values and count !important declarations.

    Returns:
        Tuple of (z_index_values dict, !important count)
    """
    z_values: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    important_count = 0

    lines = content.split('\n')

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Skip comments
        if stripped.startswith('/*') or stripped.startswith('//') or stripped.startswith('*'):
            continue

        # Extract z-index values
        m = re.search(r'z-index\s*:\s*(-?\d+)', stripped)
        if m:
            z_val = m.group(1)
            z_values[z_val].append({
                "file": rel_path,
                "line": i + 1,
            })

        # Count !important
        if '!important' in stripped:
            important_count += 1

    return z_values, important_count


# ─── HTML/JS Cross-reference Scanners ─────────────────────────

def _find_var_references_in_html_js(content: str) -> Set[str]:
    """
    Find CSS custom property references (var(--name)) in HTML/JS files.

    Covers:
    - Inline style attributes: style="color: var(--accent)"
    - JS style manipulation: el.style.setProperty('--var', value)
    - JS getComputedStyle: getComputedStyle(el).getPropertyValue('--var')
    - CSS-in-JS template literals
    """
    references: Set[str] = set()

    # var(--var-name) in inline styles and CSS-in-JS
    for m in re.finditer(r'var\(\s*(--[\w-]+)', content):
        references.add(m.group(1))

    # style.setProperty('--var-name', ...)
    for m in re.finditer(r"setProperty\(\s*['\"](--[\w-]+)['\"]", content):
        references.add(m.group(1))

    # getPropertyValue('--var-name')
    for m in re.finditer(r"getPropertyValue\(\s*['\"](--[\w-]+)['\"]", content):
        references.add(m.group(1))

    return references


def _find_keyframe_references_in_html_js(content: str) -> Set[str]:
    """
    Find @keyframes references in HTML/JS files.

    Covers:
    - Inline style: style="animation: name 1s ease"
    - Element.style.animation = "name 1s"
    - Element.style.animationName = "name"
    - Web Animations API: element.animate({...}, { name: "..." })
    """
    references: Set[str] = set()

    # animation-name: <name> in inline styles or CSS-in-JS
    for m in re.finditer(r'animation-name\s*:\s*([\w-]+)', content):
        references.add(m.group(1))

    # animation: ... <name> (shorthand)
    for m in re.finditer(r'animation\s*:\s*(.+?)(?:[;"\'])', content):
        value = m.group(1).strip()
        css_keywords = {
            'ease', 'ease-in', 'ease-out', 'ease-in-out', 'linear',
            'step-start', 'step-end', 'cubic-bezier',
            'normal', 'reverse', 'alternate', 'alternate-reverse',
            'none', 'forwards', 'backwards', 'both',
            'running', 'paused', 'infinite',
            'initial', 'inherit', 'unset',
        }
        tokens = re.split(r'\s+', value)
        for token in tokens:
            if re.match(r'^[\d.]+', token):
                continue
            if token.startswith('cubic-bezier') or token.startswith('steps('):
                continue
            if token.lower() in css_keywords:
                continue
            references.add(token)
            break

    # JS: .animationName = "name"
    for m in re.finditer(r'\.animationName\s*=\s*["\']([\w-]+)["\']', content):
        references.add(m.group(1))

    # JS: .style.animation = "name ..."
    for m in re.finditer(r'\.style\.animation\s*=\s*["\']([\w-]+)', content):
        references.add(m.group(1))

    return references


# ─── Helper Functions ──────────────────────────────────────────

def _extract_style_block(content: str, ext: str) -> Optional[str]:
    """
    Extract <style> block content from .vue or .svelte component files.

    Returns None for regular CSS files (use entire content).
    Returns empty string if no style block found.
    """
    if ext == ".vue":
        # Vue SFC: <style ...>...</style>
        m = re.search(r'<style[^>]*>([\s\S]{0,50000}?)</style>', content)
        if m:
            return m.group(1)
        return ""

    if ext == ".svelte":
        # Svelte: <style>...</style>
        m = re.search(r'<style[^>]*>([\s\S]{0,50000}?)</style>', content)
        if m:
            return m.group(1)
        return ""

    return None  # Not a component file


def _truncate_selector(selector: str, max_len: int = 50) -> str:
    """Truncate a selector string for display, adding ellipsis if needed."""
    if len(selector) <= max_len:
        return selector
    return selector[:max_len - 3] + "..."


def _resolve_breakpoints(config_breakpoints: Any) -> Set[int]:
    """
    Resolve breakpoints from config, falling back to defaults.

    Config can provide a list of integers or a dict with "values" key.
    """
    if not config_breakpoints:
        return DEFAULT_BREAKPOINTS

    if isinstance(config_breakpoints, (list, tuple)):
        try:
            return {int(b) for b in config_breakpoints}
        except (ValueError, TypeError):
            return DEFAULT_BREAKPOINTS

    if isinstance(config_breakpoints, dict):
        values = config_breakpoints.get("values", [])
        tolerance = config_breakpoints.get("tolerance")
        if tolerance and isinstance(tolerance, int):
            global BREAKPOINT_TOLERANCE
            BREAKPOINT_TOLERANCE = tolerance
        try:
            return {int(b) for b in values}
        except (ValueError, TypeError):
            return DEFAULT_BREAKPOINTS

    return DEFAULT_BREAKPOINTS


def _deduplicate_findings(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate findings (same file, line, category, name)."""
    seen: Set[Tuple[str, int, str, str]] = set()
    unique = []

    for finding in findings:
        key = (
            finding.get("file", ""),
            finding.get("line", 0),
            finding.get("category", ""),
            finding.get("name", ""),
        )
        if key not in seen:
            seen.add(key)
            unique.append(finding)

    return unique


# ─── Stats Computation ─────────────────────────────────────────

def _compute_stats(
    findings: List[Dict[str, Any]],
    css_files_scanned: int,
    html_js_files_scanned: int,
) -> Dict[str, Any]:
    """Compute statistics from findings."""
    by_category: Dict[str, int] = defaultdict(int)
    by_severity: Dict[str, int] = defaultdict(int)

    for f in findings:
        by_category[f.get("category", "unknown")] += 1
        by_severity[f.get("severity", "unknown")] += 1

    return {
        "total_issues": len(findings),
        "by_category": dict(by_category),
        "by_severity": dict(by_severity),
        "css_files_scanned": css_files_scanned,
        "html_js_files_scanned": html_js_files_scanned,
    }


# ─── Recommendations ───────────────────────────────────────────

def _generate_recommendations(
    findings: List[Dict[str, Any]],
    stats: Dict[str, Any],
) -> List[str]:
    """Generate actionable recommendations based on findings."""
    recs = []

    if not findings:
        recs.append(
            "No CSS deep analysis issues detected. Your stylesheets look clean!"
        )
        return recs

    by_category = stats.get("by_category", {})

    # Unused CSS variables
    unused_count = by_category.get("unused_vars", 0)
    if unused_count > 0:
        recs.append(
            f"UNUSED VARIABLES: Found {unused_count} CSS custom property/properties "
            f"declared but never referenced via var(). Remove dead CSS variables to "
            f"reduce stylesheet bloat and improve maintainability."
        )

    # Orphan keyframes
    orphan_count = by_category.get("orphan_keyframes", 0)
    if orphan_count > 0:
        recs.append(
            f"ORPHAN KEYFRAMES: Found {orphan_count} @keyframes animation(s) "
            f"with no animation/animation-name reference. Remove unused animations "
            f"or connect them to selectors."
        )

    # Specificity wars
    spec_count = by_category.get("specificity_wars", 0)
    if spec_count > 0:
        recs.append(
            f"SPECIFICITY WARS: Found {spec_count} specificity issue(s) — "
            f"deep nesting, overqualified selectors, or !important overuse. "
            f"Consider adopting BEM, ITCSS, or CSS Modules to manage specificity."
        )

    # Duplicate properties
    dup_count = by_category.get("duplicate_props", 0)
    if dup_count > 0:
        recs.append(
            f"DUPLICATE PROPERTIES: Found {dup_count} rule block(s) with "
            f"duplicate property declarations. The later declaration silently "
            f"overrides the earlier one — this is often a bug. Review each case."
        )

    # Unused media queries
    media_count = by_category.get("unused_media", 0)
    if media_count > 0:
        recs.append(
            f"UNUSED MEDIA QUERIES: Found {media_count} @media query/queries "
            f"targeting breakpoints outside your design system. Standardize on a "
            f"consistent breakpoint scale and document it in your project config."
        )

    # z-index abuse
    zindex_count = by_category.get("z_index_abuse", 0)
    if zindex_count > 0:
        recs.append(
            f"Z-INDEX ABUSE: Found {zindex_count} z-index issue(s) — excessive "
            f"values or too many unique values. Create a z-index scale as CSS "
            f"custom properties (e.g., --z-dropdown: 100, --z-modal: 200, "
            f"--z-tooltip: 300) and enforce it project-wide."
        )

    # General advice
    high_count = stats.get("by_severity", {}).get("high", 0)
    if high_count >= 3:
        recs.append(
            "PRIORITY: Multiple high-severity CSS issues detected. Address these "
            "first as they indicate patterns that make stylesheets hard to maintain "
            "and prone to regressions."
        )

    recs.append(
        "TIP: Consider adding a CSS linter (stylelint) with a consistent config "
        "to catch these issues during development before they accumulate."
    )

    return recs
