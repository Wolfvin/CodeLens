"""
Laravel Blade Template Parser for CodeLens
Parses .blade.php files for CSS classes, IDs, Blade directives,
component usage, and section/yield patterns.

Blade templates are Laravel's templating engine. They mix HTML with
Blade directives like @extends, @section, @yield, @include, @component,
@foreach, @if, etc. They also use {{ }} and {!! !!} for PHP expressions.

This parser extracts:
- HTML classes and IDs (for frontend registry)
- Blade directives (for understanding template structure)
- Component usage (for Laravel components)
- Section/yield relationships (for template inheritance)
- PHP expressions in Blade context
"""

import re
from typing import Dict, List, Any, Optional


def parse_blade_template(content: str, rel_path: str) -> Dict[str, Any]:
    """
    Parse a Laravel Blade template file.

    Args:
        content: Blade template source code
        rel_path: Relative path from workspace root

    Returns:
        Dict with keys:
        - frontend: { classes: [], ids: [] }
        - blade: { directives, sections, includes, components, extends }
    """
    frontend_classes: List[Dict] = []
    frontend_ids: List[Dict] = []

    # ─── Extract HTML classes and IDs ────────────────────────
    # Standard HTML class/id attributes
    _extract_html_attrs(content, rel_path, frontend_classes, frontend_ids)

    # Blade-specific: @class directive (Laravel 9+)
    # @class(['px-4', 'bg-white' => $active])
    for m in re.finditer(r'@class\s*\(\s*\[([^\]]+)\]', content):
        line = content[:m.start()].count('\n') + 1
        class_str = m.group(1)
        for cls in re.findall(r"['\"]([\w][\w-]*)['\"]", class_str):
            frontend_classes.append({
                "name": cls,
                "path": rel_path,
                "line": line,
                "source": "blade_class_directive",
            })

    # Blade @style directive (Laravel 9+)
    # Not common but handle it
    for m in re.finditer(r'@style\s*\(\s*\[([^\]]+)\]', content):
        line = content[:m.start()].count('\n') + 1
        style_str = m.group(1)
        for cls in re.findall(r"['\"]([\w][\w-]*)['\"]", style_str):
            frontend_classes.append({
                "name": cls,
                "path": rel_path,
                "line": line,
                "source": "blade_style_directive",
            })

    # ─── Blade Directives ───────────────────────────────────
    directives: List[Dict[str, Any]] = []
    directive_pattern = re.compile(r'@(\w+)(?:\s*\(([^)]*)\))?')

    directive_types = {
        'if', 'elseif', 'else', 'endif', 'unless', 'endunless',
        'foreach', 'endforeach', 'for', 'endfor', 'while', 'endwhile',
        'switch', 'case', 'endswitch',
        'isset', 'endisset', 'empty', 'endempty',
        'auth', 'endauth', 'guest', 'endguest',
        'production', 'endproduction', 'env',
        'can', 'endcan', 'cannot', 'endcannot',
        'section', 'endsection', 'yield', 'show',
        'extends', 'include', 'includeIf', 'includeWhen', 'includeUnless',
        'each', 'once', 'endonce',
        'push', 'endpush', 'prepend', 'endprepend', 'stack',
        'component', 'endcomponent', 'slot', 'endslot',
        'csrf', 'method', 'error', 'enderror',
        'json', 'dd', 'dump', 'break', 'continue',
        'php', 'endphp', 'verbatim', 'endverbatim',
        'props', 'aware',
    }

    for m in directive_pattern.finditer(content):
        name = m.group(1)
        if name not in directive_types and not name.startswith('end'):
            continue
        line = content[:m.start()].count('\n') + 1
        args = m.group(2) or ""
        directives.append({
            "name": name,
            "line": line,
            "args": args.strip()[:200],  # Truncate long args
        })

    # ─── Template Inheritance ────────────────────────────────
    extends_template = None
    for m in re.finditer(r"@extends\s*\(\s*['\"]([^'\"]+)['\"]", content):
        extends_template = m.group(1)

    # ─── Sections ────────────────────────────────────────────
    sections_defined: List[Dict] = []
    sections_yielded: List[Dict] = []

    # @section('name') ... @endsection / @show
    for m in re.finditer(r"@section\s*\(\s*['\"](\w+)['\"]", content):
        line = content[:m.start()].count('\n') + 1
        sections_defined.append({
            "name": m.group(1),
            "line": line,
            "path": rel_path,
        })

    # @yield('name')
    for m in re.finditer(r"@yield\s*\(\s*['\"](\w+)['\"]", content):
        line = content[:m.start()].count('\n') + 1
        sections_yielded.append({
            "name": m.group(1),
            "line": line,
            "path": rel_path,
        })

    # ─── Includes ────────────────────────────────────────────
    includes: List[Dict] = []
    include_patterns = [
        (r"@include\s*\(\s*['\"]([^'\"]+)['\"]", "include"),
        (r"@includeIf\s*\(\s*['\"]([^'\"]+)['\"]", "include_if"),
        (r"@includeWhen\s*\([^,]+,\s*['\"]([^'\"]+)['\"]", "include_when"),
        (r"@includeUnless\s*\([^,]+,\s*['\"]([^'\"]+)['\"]", "include_unless"),
        (r"@each\s*\(\s*['\"]([^'\"]+)['\"]", "each"),
    ]
    for pattern, include_type in include_patterns:
        for m in re.finditer(pattern, content):
            line = content[:m.start()].count('\n') + 1
            includes.append({
                "template": m.group(1),
                "type": include_type,
                "line": line,
                "path": rel_path,
            })

    # ─── Components ──────────────────────────────────────────
    components: List[Dict] = []
    # <x-component-name /> or <x-component-name ...>
    # Also <x:namespace.component />
    for m in re.finditer(r'<(x[-:][\w.-]+)', content):
        line = content[:m.start()].count('\n') + 1
        component_name = m.group(1).replace(':', '.').replace('-', '.')
        components.append({
            "name": component_name,
            "line": line,
            "path": rel_path,
        })

    # @component('component.name')
    for m in re.finditer(r"@component\s*\(\s*['\"]([^'\"]+)['\"]", content):
        line = content[:m.start()].count('\n') + 1
        components.append({
            "name": m.group(1),
            "line": line,
            "path": rel_path,
            "directive": True,
        })

    # ─── Stack / Push ────────────────────────────────────────
    stacks: List[Dict] = []
    for m in re.finditer(r"@stack\s*\(\s*['\"](\w+)['\"]", content):
        line = content[:m.start()].count('\n') + 1
        stacks.append({"name": m.group(1), "line": line, "type": "stack"})

    for m in re.finditer(r"@push\s*\(\s*['\"](\w+)['\"]", content):
        line = content[:m.start()].count('\n') + 1
        stacks.append({"name": m.group(1), "line": line, "type": "push"})

    for m in re.finditer(r"@prepend\s*\(\s*['\"](\w+)['\"]", content):
        line = content[:m.start()].count('\n') + 1
        stacks.append({"name": m.group(1), "line": line, "type": "prepend"})

    blade_info: Dict[str, Any] = {}
    if directives:
        blade_info["directives"] = directives
    if extends_template:
        blade_info["extends"] = extends_template
    if sections_defined:
        blade_info["sections_defined"] = sections_defined
    if sections_yielded:
        blade_info["sections_yielded"] = sections_yielded
    if includes:
        blade_info["includes"] = includes
    if components:
        blade_info["components"] = components
    if stacks:
        blade_info["stacks"] = stacks

    return {
        "frontend": {
            "classes": frontend_classes,
            "ids": frontend_ids,
        },
        "blade": blade_info if blade_info else None,
    }


def _extract_html_attrs(content: str, rel_path: str,
                        classes: List[Dict], ids: List[Dict]) -> None:
    """Extract HTML class and id attributes from Blade template content."""
    # class="..." or class='...'
    for m in re.finditer(r'class\s*=\s*["\']([^"\']+)["\']', content):
        line = content[:m.start()].count('\n') + 1
        class_str = m.group(1)
        for cls in class_str.split():
            if cls and re.match(r'^[\w-]+$', cls):
                classes.append({
                    "name": cls,
                    "path": rel_path,
                    "line": line,
                    "source": "blade_html_class",
                })

    # id="..." or id='...'
    for m in re.finditer(r'\bid\s*=\s*["\']([^"\']+)["\']', content):
        line = content[:m.start()].count('\n') + 1
        id_val = m.group(1).strip()
        if id_val and re.match(r'^[\w-]+$', id_val):
            ids.append({
                "name": id_val,
                "path": rel_path,
                "line": line,
                "source": "blade_html_id",
            })

    # Dynamic class bindings: :class="..." or v-bind:class (unlikely in Blade but handle)
    # Alpine.js x-bind:class
    for m in re.finditer(r'(?:x-bind:|:)(?:class)\s*=\s*["\']([^"\']+)["\']', content):
        line = content[:m.start()].count('\n') + 1
        class_str = m.group(1)
        # Extract static class names from the binding expression
        for cls in re.findall(r"['\"]([\w][\w-]*)['\"]", class_str):
            classes.append({
                "name": cls,
                "path": rel_path,
                "line": line,
                "source": "blade_dynamic_class",
            })
