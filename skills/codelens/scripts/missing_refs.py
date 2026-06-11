"""
Missing References Detector for CodeLens
Cross-validates frontend registry entries to find mismatches:
- HTML/JSX classes with no CSS definition
- CSS selectors with no HTML/JSX usage
- IDs referenced in JS but not defined in HTML
- Possible typos (similar names that differ by 1-2 chars)
"""

import os
import re
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict


def detect_missing_refs(workspace: str) -> Dict[str, Any]:
    """
    Detect all missing reference issues in the workspace.

    Returns categorized issues:
    - css_no_html: CSS class defined but never used in HTML/JSX
    - html_no_css: HTML/JSX class used but never defined in CSS
    - js_id_no_html: JS references an ID not defined in HTML
    - possible_typos: Similar names that might be typos
    - css_id_no_html: CSS styles an ID not defined in HTML
    """
    workspace = os.path.abspath(workspace)

    from registry import load_frontend_registry
    frontend = load_frontend_registry(workspace)

    issues = {
        "css_no_html": [],      # CSS class defined, no HTML usage
        "html_no_css": [],      # HTML class used, no CSS definition
        "css_id_no_html": [],   # CSS styles ID, no HTML definition
        "js_id_no_html": [],    # JS references ID, no HTML definition
        "possible_typos": [],   # Similar names (likely typos)
    }

    # Build lookup sets
    html_classes = set()
    css_classes = set()
    js_classes = set()
    html_ids = set()
    css_ids = set()
    js_ids = set()

    # Class analysis
    for cls in frontend.get("classes", []):
        name = cls["name"]

        has_css = len(cls.get("css", [])) > 0
        has_js = len(cls.get("js", [])) > 0

        # Track which "domain" references this class
        for css_ref in cls.get("css", []):
            css_classes.add(name)
        for js_ref in cls.get("js", []):
            js_classes.add(name)
            # Also track as HTML usage if source is jsx_classname or similar
            src = js_ref.get("source", "")
            if src in ("jsx_classname", "jsx_template", "vue_class", "vue_binding",
                       "svelte_class", "svelte_directive", "html_class"):
                html_classes.add(name)

        # CSS class with no HTML/JSX usage
        if has_css and not has_js and cls["status"] == "dead":
            css_locs = [f"{r['path']}:{r['line']}" for r in cls.get("css", [])]
            issues["css_no_html"].append({
                "name": name,
                "status": cls["status"],
                "css_locations": css_locs,
                "message": f"Class '.{name}' defined in CSS but never used in HTML/JS"
            })

        # HTML/JSX class with no CSS definition
        if has_js and not has_css:
            js_locs = [f"{r['path']}:{r['line']}" for r in cls.get("js", [])]
            sources = set(r.get("source", "") for r in cls.get("js", []))
            # Only flag if it looks like a CSS class (not Tailwind utility)
            is_tailwind = _is_likely_tailwind(name)
            if not is_tailwind:
                issues["html_no_css"].append({
                    "name": name,
                    "status": cls["status"],
                    "js_locations": js_locs,
                    "sources": list(sources),
                    "message": f"Class '{name}' used in HTML/JSX but has no CSS definition"
                })

    # ID analysis
    for id_entry in frontend.get("ids", []):
        name = id_entry["name"]

        has_html = len(id_entry.get("defined_in_html", [])) > 0
        has_css = len(id_entry.get("css", [])) > 0
        has_js = len(id_entry.get("js", [])) > 0

        if has_html:
            html_ids.add(name)
        if has_css:
            css_ids.add(name)
        if has_js:
            js_ids.add(name)

        # CSS styles an ID not defined in HTML
        if has_css and not has_html:
            css_locs = [f"{r['path']}:{r['line']}" for r in id_entry.get("css", [])]
            issues["css_id_no_html"].append({
                "name": name,
                "status": id_entry["status"],
                "css_locations": css_locs,
                "message": f"ID '#{name}' styled in CSS but not defined in HTML"
            })

        # JS references an ID not defined in HTML
        if has_js and not has_html:
            js_locs = [f"{r['path']}:{r['line']}" for r in id_entry.get("js", [])]
            issues["js_id_no_html"].append({
                "name": name,
                "status": id_entry["status"],
                "js_locations": js_locs,
                "message": f"ID '#{name}' referenced in JS but not defined in HTML"
            })

    # ─── Typo Detection ─────────────────────────────────
    all_class_names = set()
    for cls in frontend.get("classes", []):
        all_class_names.add(cls["name"])

    dead_classes = {cls["name"] for cls in frontend.get("classes", []) if cls["status"] == "dead"}
    active_classes = all_class_names - dead_classes

    # Check if a dead class is similar to an active class (likely typo)
    for dead_name in dead_classes:
        for active_name in active_classes:
            distance = _levenshtein_distance(dead_name, active_name)
            if 0 < distance <= 2 and len(dead_name) > 3 and len(active_name) > 3:
                # Also check prefix similarity
                if dead_name[:3] == active_name[:3] or dead_name[-3:] == active_name[-3:]:
                    dead_cls = next(c for c in frontend.get("classes", []) if c["name"] == dead_name)
                    active_cls = next(c for c in frontend.get("classes", []) if c["name"] == active_name)
                    issues["possible_typos"].append({
                        "dead_name": dead_name,
                        "active_name": active_name,
                        "distance": distance,
                        "dead_locations": [f"{r['path']}:{r['line']}" for r in dead_cls.get("css", []) + dead_cls.get("js", [])],
                        "active_locations": [f"{r['path']}:{r['line']}" for r in active_cls.get("css", []) + active_cls.get("js", [])],
                        "message": f"'{dead_name}' (dead) might be a typo of '{active_name}' (active)"
                    })

    # Total counts
    total_issues = sum(len(v) for v in issues.values())

    return {
        "status": "ok",
        "workspace": workspace,
        "total_issues": total_issues,
        "issues": issues,
        "stats": {
            "css_no_html": len(issues["css_no_html"]),
            "html_no_css": len(issues["html_no_css"]),
            "css_id_no_html": len(issues["css_id_no_html"]),
            "js_id_no_html": len(issues["js_id_no_html"]),
            "possible_typos": len(issues["possible_typos"])
        }
    }


def _is_likely_tailwind(class_name: str) -> bool:
    """Heuristic to detect Tailwind utility classes.

    Covers:
    - Standard utility prefixes (w-, h-, p-, m-, text-, bg-, etc.)
    - Important modifier prefix (!)
    - Negative value prefix (-)
    - Responsive prefixes (sm:, md:, lg:, xl:, 2xl:)
    - State variants (hover:, focus:, active:, dark:, etc.)
    - Arbitrary value syntax ([...])
    - Fractional values (w-1/2, w-1/3)
    - Tailwind v4: container queries (@sm:, @md:, @2xl/name:)
    - Tailwind v4: star wildcard (*:, **:)
    - Tailwind v4: arbitrary variants ([&_:])
    - Tailwind v4: data attribute variants (data-[slot=]:)
    - Tailwind v4: group/peer named variants (group-hover/name:)
    """
    # Strip leading ! (important modifier) and - (negative value)
    stripped = class_name.lstrip('!')

    # ─── Tailwind v4: Container query prefix (@) ───────────
    # Matches: @sm:, @md:, @lg:, @xl:, @2xl:, @3xl:, @4xl:
    # Also: @2xl/name: (named container queries)
    # Also: @container, @container/name (standalone container utility)
    if re.match(r'^(?:!)?@[a-z0-9]+(?:/[a-zA-Z0-9_-]+)?:', class_name):
        remaining = re.sub(r'^(?:!)?@[a-z0-9]+(?:/[a-zA-Z0-9_-]+)?:', '', class_name)
        if remaining:
            return _is_likely_tailwind(remaining) or _is_utility_base(remaining)
        return True

    # Standalone @container utility: @container, @container/name
    if re.match(r'^(?:!)?@container(?:/[a-zA-Z0-9_-]+)?$', stripped):
        return True

    # ─── Tailwind v4: Arbitrary variants with nested brackets ─
    # Matches: [&_[data-slot=x]:nth-child(even)]:hidden
    # More permissive pattern allowing : inside brackets
    if re.match(r'^(?:!)?\[&[^]]+\]:', class_name):
        remaining = re.sub(r'^(?:!)?\[&[^]]+\]:', '', class_name)
        if remaining:
            return _is_likely_tailwind(remaining) or _is_utility_base(remaining)
        return True

    # ─── Tailwind v4: Star wildcard (*:, **:) ──────────────
    # Matches: *:basis-1/4, **:hover:flex, *:first:mt-0
    if re.match(r'^(?:!)?\*{1,2}:', class_name):
        remaining = re.sub(r'^(?:!)?\*{1,2}:', '', class_name)
        if remaining:
            return _is_likely_tailwind(remaining) or _is_utility_base(remaining)
        return True

    # ─── Tailwind v4: Arbitrary variants ([&...]) ──────────
    # Matches: [&_li]:flex, [&>*]:block, [@media(...)]:hidden
    if re.match(r'^(?:!)?\[&[^]]*\]:', class_name):
        remaining = re.sub(r'^(?:!)?\[&[^]]*\]:', '', class_name)
        if remaining:
            return _is_likely_tailwind(remaining) or _is_utility_base(remaining)
        return True

    # ─── Tailwind v4: Data attribute variants ─────────────
    # Matches: data-[slot=icon]:flex, data-[state=open]:block
    if re.match(r'^(?:!)?data-\[[^]]+\]:', class_name):
        remaining = re.sub(r'^(?:!)?data-\[[^]]+\]:', '', class_name)
        if remaining:
            return _is_likely_tailwind(remaining) or _is_utility_base(remaining)
        return True

    tailwind_prefixes = [
        # Layout
        'flex', 'grid', 'block', 'inline', 'hidden', 'visible',
        'table', 'flow-root', 'contents', 'list-',
        # Spacing
        'w-', 'h-', 'min-w-', 'min-h-', 'max-w-', 'max-h-',
        'p-', 'm-', 'mt-', 'mb-', 'ml-', 'mr-', 'mx-', 'my-',
        'pt-', 'pb-', 'pl-', 'pr-', 'px-', 'py-',
        # Typography
        'text-', 'font-', 'tracking-', 'leading-', 'whitespace-',
        'break-', 'truncate', 'overflow-ellipsis', 'overflow-clip',
        'underline', 'overline', 'line-through', 'no-underline',
        'uppercase', 'lowercase', 'capitalize', 'normal-case',
        # Colors & backgrounds
        'bg-', 'from-', 'via-', 'to-', 'bg-gradient-',
        # Border
        'border-', 'rounded-', 'ring-', 'outline-', 'divide-',
        # Effects
        'shadow-', 'opacity-', 'blur-', 'brightness-', 'contrast-',
        'drop-shadow-', 'grayscale-', 'hue-rotate-', 'invert-', 'saturate-', 'sepia-',
        # Flexbox & Grid
        'gap-', 'space-', 'justify-', 'items-', 'self-', 'place-',
        'flex-', 'grid-', 'order-', 'col-', 'row-',
        # Positioning
        'absolute', 'relative', 'fixed', 'sticky',
        'top-', 'bottom-', 'left-', 'right-', 'inset-',
        'z-',
        # Overflow
        'overflow-', 'overscroll-',
        # Transitions & Animation
        'transition-', 'duration-', 'ease-', 'animate-',
        'delay-',
        # Transform
        'scale-', 'rotate-', 'translate-', 'skew-', 'origin-',
        '-scale-', '-rotate-', '-translate-', '-skew-',
        # Interactivity
        'cursor-', 'select-', 'pointer-', 'resize-', 'appearance-',
        'accent-',
        # SVG
        'fill-', 'stroke-',
        # Accessibility
        'sr-only', 'not-sr-only',
        # Typography plugin (@tailwindcss/typography)
        'prose', 'prose-',
    ]

    for prefix in tailwind_prefixes:
        if stripped.startswith(prefix) or stripped == prefix.rstrip('-'):
            return True

    # Responsive/state variants: sm:, md:, lg:, xl:, 2xl:, hover:, focus:, etc.
    variant_pattern = re.compile(
        r'^(?:!)?'  # optional important modifier
        r'(?:'
        r'sm:|md:|lg:|xl:|2xl:|3xl:|4xl:'  # responsive
        r'|hover:|focus:|active:|visited:|focus-within:|focus-visible:'
        r'|disabled:|checked:|selected:|default:|optional:|required:'
        r'|invalid:|valid:|in-range:|out-of-range:'
        r'|dark:|light:|motion-safe:|motion-reduce:'
        r'|first:|last:|odd:|even:|only:'
        r'|group-hover:|group-focus:|group-active:|group-dark:'
        r'|peer-hover:|peer-focus:|peer-active:|peer-dark:'
        r')'
    )
    if variant_pattern.match(class_name):
        # After stripping the variant, check if remaining is a utility
        remaining = variant_pattern.sub('', class_name)
        if remaining:
            return _is_likely_tailwind(remaining)

    # Arbitrary value syntax: w-[100px], bg-[#fff], etc.
    if re.search(r'\[.+\]', stripped):
        return True

    # Negative values: -mb-4, -mt-8, etc.
    if stripped.startswith('-') and any(stripped[1:].startswith(p) for p in ['m', 'p', 'w', 'h', 'inset', 'top', 'bottom', 'left', 'right', 'z', 'space', 'gap', 'rotate', 'translate', 'skew']):
        return True

    # Pure number patterns like "w4", "h8"
    if re.match(r'^[whmp][\d]+$', stripped):
        return True

    # Fractional values: w-1/2, w-1/3, h-2/3
    if re.match(r'^[wh]\d+/\d+$', stripped):
        return True

    return False


def _is_utility_base(name: str) -> bool:
    """Quick check if a stripped class name matches a common Tailwind utility base.

    Used after stripping Tailwind v4 variant prefixes (container queries, star
    wildcards, arbitrary variants, data attributes) to verify the remaining
    part is a real utility class like 'flex', 'basis-1/4', 'mt-0', etc.
    """
    if not name:
        return True  # Empty remaining = just a variant with no base = still Tailwind

    # Common standalone utilities
    STANDALONE = {
        'flex', 'grid', 'block', 'inline', 'inline-block', 'inline-flex',
        'hidden', 'visible', 'invisible', 'contents', 'flow-root',
        'static', 'fixed', 'absolute', 'relative', 'sticky',
        'truncate', 'sr-only', 'not-sr-only', 'isolate', 'isolation-auto',
        'container', 'aspect-auto', 'aspect-square', 'aspect-video',
        'inset-auto', 'inset-full',
        'underline', 'overline', 'line-through', 'no-underline',
        'uppercase', 'lowercase', 'capitalize', 'normal-case',
        'antialiased', 'subpixel-antialiased',
        'list-none', 'list-disc', 'list-decimal', 'list-inside', 'list-outside',
        'text-left', 'text-center', 'text-right', 'text-justify', 'text-start', 'text-end',
        'border', 'border-0', 'border-2', 'border-4', 'border-8',
        'rounded', 'rounded-none', 'rounded-sm', 'rounded-md', 'rounded-lg', 'rounded-xl',
        'rounded-2xl', 'rounded-3xl', 'rounded-full',
        'shadow', 'shadow-none', 'shadow-sm', 'shadow-md', 'shadow-lg', 'shadow-xl',
        'shadow-2xl', 'shadow-inner',
        'ring', 'ring-0', 'ring-1', 'ring-2', 'ring-offset',
        'animate-none', 'animate-spin', 'animate-ping', 'animate-pulse', 'animate-bounce',
        'transition', 'transition-none', 'transition-all', 'transition-colors',
        'transition-opacity', 'transition-shadow', 'transition-transform',
        'ease-linear', 'ease-in', 'ease-out', 'ease-in-out',
        'cursor-auto', 'cursor-default', 'cursor-pointer', 'cursor-wait', 'cursor-text',
        'cursor-move', 'cursor-not-allowed', 'cursor-grab', 'cursor-grabbing',
        'select-none', 'select-text', 'select-all', 'select-auto',
        'resize', 'resize-none', 'resize-y', 'resize-x',
        'appearance-none',
    }
    if name in STANDALONE:
        return True

    # Prefix-based utilities
    PREFIXES = [
        'w-', 'h-', 'min-w-', 'min-h-', 'max-w-', 'max-h-',
        'p-', 'm-', 'mt-', 'mb-', 'ml-', 'mr-', 'mx-', 'my-',
        'pt-', 'pb-', 'pl-', 'pr-', 'px-', 'py-',
        'text-', 'font-', 'tracking-', 'leading-', 'whitespace-',
        'bg-', 'from-', 'via-', 'to-',
        'border-', 'rounded-', 'ring-', 'outline-', 'divide-',
        'shadow-', 'opacity-', 'blur-', 'brightness-', 'contrast-',
        'gap-', 'space-', 'justify-', 'items-', 'self-', 'place-',
        'flex-', 'grid-', 'order-', 'col-', 'row-',
        'top-', 'bottom-', 'left-', 'right-', 'inset-',
        'z-', 'overflow-', 'overscroll-',
        'scale-', 'rotate-', 'translate-', 'skew-', 'origin-',
        'duration-', 'delay-', 'ease-',
        'fill-', 'stroke-', 'accent-',
        'basis-', 'grow', 'shrink',
        'prose',
    ]
    for prefix in PREFIXES:
        if name.startswith(prefix) or name == prefix.rstrip('-'):
            return True

    # Arbitrary value syntax: [100px], [#fff], [var(--x)]
    if re.search(r'\[.+\]', name):
        return True

    # Fractional values: 1/2, 1/3, 2/3, 1/4, 3/4
    if re.match(r'^\d+/\d+$', name):
        return True

    # Numeric suffixes: basis-1/4, mt-0, p-4, etc.
    if re.match(r'^[a-z]+-\d+', name):
        return True

    return False


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]
