"""
Vue SFC Parser for CodeLens — v2
Parses Vue Single File Components (.vue files) to extract:
- :class bindings (dynamic and static)
- class attributes (static)
- id attributes (static and dynamic)
- Scoped style references
- Script section: component methods, data refs, composables, imports
- <script setup>: Composition API support (defineProps, defineEmits, ref, reactive, computed, watch)
- Backend nodes: function declarations, imports, exports from script sections
- Template refs: ref="xxx" attribute tracking

Vue SFC structure:
<template> ... </template>
<script setup> ... </script>   ← Composition API (Vue 3)
<script> ... </script>         ← Options API or mixed
<style scoped> ... </style>

v2 changes:
- <script setup> parsing with defineProps/defineEmits/ref/reactive/computed/watch
- Backend node extraction (functions, imports, exports) from script sections
- Template ref="xxx" attribute tracking
- Multi-script block support (<script setup> + <script> for Options API config)
- TypeScript <script lang="ts"> support
- Composable auto-import detection (ref, reactive, computed, watch, etc.)
"""

import re
import os
from typing import Dict, List, Any, Optional


def parse_vue_sfc(content: str, file_path: str) -> Dict[str, Any]:
    """
    Parse a Vue SFC file.
    Returns frontend references (classes, ids), style info, and backend data.
    """
    classes = []
    ids = []
    scoped_styles = []
    backend_nodes = []
    backend_edges = []

    # ─── Extract template section ────────────────────────────
    # Use greedy match (.*) to capture the entire template including nested
    # <template v-slot:...> elements. Non-greedy (.*?) would truncate at the
    # first inner </template>, silently dropping most of the template content.
    # Also allow attributes on <template> like <template lang="pug">.
    template_match = re.search(r'<template([^>]*)>(.*)</template>', content, re.DOTALL)
    template_content = template_match.group(2) if template_match else ""

    # ─── Extract script sections (may have <script setup> + <script>) ───
    script_sections = _extract_script_sections(content)
    script_setup_content = ""
    script_options_content = ""
    is_setup = False
    is_ts = False

    for section in script_sections:
        if section["setup"]:
            script_setup_content = section["content"]
            is_setup = True
            if section["lang"] in ("ts", "typescript"):
                is_ts = True
        else:
            script_options_content = section["content"]
            if section["lang"] in ("ts", "typescript"):
                is_ts = True

    # Combined script content for backend parsing
    combined_script = script_setup_content or script_options_content

    # ─── Extract style sections ──────────────────────────────
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
        elif 'lang="stylus"' in style_attrs or "lang='stylus'" in style_attrs:
            lang = 'stylus'
        elif 'lang="postcss"' in style_attrs or "lang='postcss'" in style_attrs:
            lang = 'postcss'

        scoped_styles.append({
            "content": style_content,
            "scoped": is_scoped,
            "lang": lang
        })

    # ─── Parse template for classes, ids, and refs ───────────
    if template_content:
        _parse_vue_template(template_content, file_path, classes, ids)

    # ─── Parse scoped styles ─────────────────────────────────
    for style_info in scoped_styles:
        _parse_style_section(style_info["content"], file_path, classes, ids,
                             style_info["scoped"], style_info["lang"])

    # ─── Parse script sections for backend data ──────────────
    if combined_script:
        # Determine line offset from the script section that matched
        line_offset = 0
        for section in script_sections:
            s_content = section["content"]
            if s_content == combined_script:
                line_offset = section.get("line_offset", 0)
                break
        _parse_script_section(
            combined_script, file_path,
            backend_nodes, backend_edges,
            is_setup=is_setup, is_ts=is_ts, line_offset=line_offset
        )

    result = {
        "frontend": {
            "classes": classes,
            "ids": ids
        },
        "scoped_styles": scoped_styles
    }

    # Include backend data if we found anything
    if backend_nodes or backend_edges:
        result["backend"] = {
            "nodes": backend_nodes,
            "edges": backend_edges
        }

    return result


def _extract_script_sections(content: str) -> List[Dict[str, Any]]:
    """Extract all <script> blocks, distinguishing <script setup> from regular <script>.
    
    Vue 3 SFCs may have both:
      <script setup>  — Composition API (runs for every component instance)
      <script>        — Options API config (e.g., inheritAttrs, name, custom options)
    """
    sections = []
    for match in re.finditer(r'<script([^>]*)>(.*?)</script>', content, re.DOTALL):
        attrs = match.group(1)
        script_content = match.group(2)
        is_setup = 'setup' in attrs
        lang = 'js'
        if 'lang="ts"' in attrs or "lang='ts'" in attrs:
            lang = 'ts'
        elif 'lang="typescript"' in attrs or "lang='typescript'" in attrs:
            lang = 'typescript'
        sections.append({
            "content": script_content,
            "setup": is_setup,
            "lang": lang,
            "line_offset": content[:match.start()].count('\n') + 1,
        })
    return sections


def _parse_vue_template(template: str, file_path: str,
                         classes: List[Dict], ids: List[Dict]):
    """Parse Vue template section for class and id references."""
    # Static class attribute: class="xxx"
    for match in re.finditer(r'\bclass\s*=\s*["\']([^"\']+)["\']', template):
        value = match.group(1)
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

    # Template ref attribute: ref="xxx" (used for accessing DOM elements / components)
    # These are important for backend reference tracking
    for match in re.finditer(r'\bref\s*=\s*["\']([^"\']+)["\']', template):
        value = match.group(1)
        line_num = _find_line_in_content(template, match.start())
        ids.append({
            "name": value.strip(),
            "line": line_num,
            "flag": None,
            "path": file_path,
            "source": "vue_template_ref"
        })

    # v-for directive tracking (produces iteration context)
    # Not a class/id but useful for complexity analysis
    # We track these as frontend references for pattern detection


def _extract_classes_from_binding(binding_expr: str, line_num: int,
                                   file_path: str, classes: List[Dict]):
    """
    Extract class names from a Vue :class binding expression.
    Handles:
    - :class="'modal active'" → "modal", "active"
    - :class="['modal', isActive ? 'active' : '']" → "modal", "active"
    - :class="{ 'modal': isOpen }" → "modal"
    - :class="classes.wrapper" → "wrapper" (as dynamic ref)
    - :class="[condition ? 'active' : 'inactive']" → "active", "inactive"
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
        if name not in ('length', 'push', 'pop', 'split', 'join', 'filter', 'map',
                        'reduce', 'find', 'findIndex', 'some', 'every', 'includes',
                        'forEach', 'sort', 'reverse', 'flat', 'flatMap', 'concat',
                        'slice', 'splice', 'keys', 'values', 'entries'):
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
    in_block_comment = False
    brace_depth = 0

    for line_num, line in enumerate(style_content.split('\n'), 1):
        stripped = line.strip()

        # Track block comments
        if '/*' in stripped and '*/' not in stripped:
            in_block_comment = True
            continue
        if in_block_comment:
            if '*/' in stripped:
                in_block_comment = False
            continue
        if stripped.startswith('/*') and '*/' in stripped:
            continue

        # Skip single-line comments
        if stripped.startswith('//'):
            continue

        # Track brace depth to distinguish selectors from property values
        brace_depth += line.count('{') - line.count('}')

        # Only extract selectors when we're at the selector level (before opening brace)
        # or at the top level (brace_depth <= 0 after processing)
        # Check if this line looks like it contains a selector (preceding a {)
        is_selector_line = '{' in line or brace_depth <= 0

        if is_selector_line or brace_depth <= 1:
            # Extract class selectors — only at selector position (before {)
            # Avoid matching inside property values like rgba(), var(), url()
            selector_part = line.split('{')[0] if '{' in line else line
            for match in re.finditer(r'\.([a-zA-Z_][\w-]*)', selector_part):
                name = match.group(1)
                # Skip CSS property values that look like class names
                if name not in ('important',):
                    classes.append({
                        "name": name,
                        "line": line_num,
                        "flag": None,
                        "path": file_path,
                        "source": "vue_scoped_style" if is_scoped else "vue_style"
                    })

            # Extract id selectors — only at selector position
            for match in re.finditer(r'#([a-zA-Z_][\w-]*)', selector_part):
                name = match.group(1)
                # Skip color hex values
                if len(name) <= 6 and all(c in '0123456789abcdefABCDEF' for c in name):
                    continue
                ids.append({
                    "name": name,
                    "line": line_num,
                    "flag": None,
                    "path": file_path,
                    "source": "vue_scoped_style" if is_scoped else "vue_style"
                })


def _parse_script_section(script_content: str, file_path: str,
                           nodes: List[Dict], edges: List[Dict],
                           is_setup: bool = False, is_ts: bool = False,
                           line_offset: int = 0):
    """Parse <script> or <script setup> section for backend nodes and edges.
    
    Extracts:
    - Function declarations and arrow functions
    - Import statements → edges
    - Export statements
    - ref/reactive/computed/watch declarations (Composition API)
    - defineProps/defineEmits (script setup)
    - Options API methods (if non-setup)
    
    Args:
        line_offset: Line number offset of the <script> tag within the .vue file.
                     Used to compute correct absolute line numbers for nodes.
    """
    lines = script_content.split('\n')

    # Track reactive variables (Composition API)
    _COMPOSITION_REACTIVE_FNS = {
        'ref', 'reactive', 'computed', 'watch', 'watchEffect',
        'shallowRef', 'shallowReactive', 'readonly', 'toRef', 'toRefs',
        'customRef', 'triggerRef',
    }

    # ─── Parse imports ────────────────────────────────────
    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()

        # Import statement: import X from 'Y' or import { X } from 'Y'
        import_match = re.match(
            r'import\s+(?:(?:\{[^}]*\}|\*\s+as\s+\w+|\w+)\s*,?\s*)'
            r'(?:from\s+)?["\']([^"\']+)["\']',
            stripped
        )
        if import_match:
            source = import_match.group(1)
            # Extract imported names
            names = re.findall(r'(?:import\s+)(\w+)', stripped)
            named_imports = re.findall(r'\{([^}]+)\}', stripped)
            if named_imports:
                for group in named_imports:
                    for name in group.split(','):
                        name = name.strip().split(' as ')[0].strip()
                        if name:
                            edges.append({
                                "from": f"{file_path}:{line_num}",
                                "to": source,
                                "type": "import",
                                "label": name,
                            })

    # ─── Parse function declarations ──────────────────────
    for line_num, line in enumerate(lines, 1):
        abs_line = line_num + line_offset  # Absolute line in .vue file
        stripped = line.strip()

        # Regular function: function name(...) or export function name(...)
        fn_match = re.match(
            r'(?:export\s+)?(?:async\s+)?function\s+(\w+)',
            stripped
        )
        if fn_match:
            fn_name = fn_match.group(1)
            node_id = f"{file_path}:{abs_line}"
            nodes.append({
                "id": node_id,
                "fn": fn_name,
                "file": file_path,
                "line": abs_line,
                "type": "function",
                "async": "async" in stripped,
            })
            # Check for function calls inside
            _extract_calls_from_line(stripped, fn_name, node_id, file_path, abs_line, edges)
            continue

        # Arrow function: const name = (...) => or export const name = (...) =>
        arrow_match = re.match(
            r'(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[^=])\s*=>',
            stripped
        )
        if arrow_match:
            fn_name = arrow_match.group(1)
            node_id = f"{file_path}:{abs_line}"
            nodes.append({
                "id": node_id,
                "fn": fn_name,
                "file": file_path,
                "line": abs_line,
                "type": "function",
                "async": "async" in stripped,
            })
            continue

        # Composition API: const x = ref(...) / const x = reactive(...) / const x = computed(...)
        comp_match = re.match(
            r'(?:export\s+)?(?:const|let)\s+(\w+)\s*=\s*'
            r'(ref|reactive|computed|shallowRef|shallowReactive|readonly|customRef)\s*\(',
            stripped
        )
        if comp_match:
            var_name = comp_match.group(1)
            reactive_type = comp_match.group(2)
            node_id = f"{file_path}:{abs_line}"
            nodes.append({
                "id": node_id,
                "fn": var_name,
                "file": file_path,
                "line": abs_line,
                "type": "reactive_var",
                "reactive_type": reactive_type,
            })
            # Edge to the reactive constructor
            edges.append({
                "from": node_id,
                "to": reactive_type,
                "type": "composition_api",
                "label": f"{reactive_type}()",
            })
            continue

        # Pinia store: const useXxxStore = defineStore('name', ...)
        pinia_match = re.match(
            r'(?:export\s+)?(?:const|let)\s+(\w+)\s*=\s*defineStore\s*\(',
            stripped
        )
        if pinia_match:
            store_var = pinia_match.group(1)
            node_id = f"{file_path}:{abs_line}"
            nodes.append({
                "id": node_id,
                "fn": store_var,
                "file": file_path,
                "line": abs_line,
                "type": "pinia_store",
            })
            # Extract store name from defineStore('name', ...)
            name_match = re.search(r'defineStore\s*\(\s*[\'"](\w+)[\'"]', stripped)
            if name_match:
                edges.append({
                    "from": node_id,
                    "to": "defineStore",
                    "type": "pinia_define",
                    "label": name_match.group(1),
                })
            # Scan next few lines for store body calls (useXxxStore, etc.)
            _extract_calls_from_line(stripped, store_var, node_id, file_path, abs_line, edges)
            continue

        # defineProps / defineEmits (script setup macros)
        define_match = re.match(
            r'(?:const\s+)?(\w+)?\s*=?\s*(defineProps|defineEmits|defineExpose|defineOptions|defineSlots|defineModel)\s*\(',
            stripped
        )
        if define_match:
            var_name = define_match.group(1) or define_match.group(2)
            macro_name = define_match.group(2)
            node_id = f"{file_path}:{abs_line}"
            nodes.append({
                "id": node_id,
                "fn": var_name,
                "file": file_path,
                "line": abs_line,
                "type": "setup_macro",
                "macro": macro_name,
            })
            continue

        # Options API methods (for non-setup scripts)
        if not is_setup:
            # method_name() { or method_name: function() {
            method_match = re.match(
                r'(\w+)\s*(?:\(|:\s*(?:async\s+)?function\s*\()',
                stripped
            )
            if method_match:
                fn_name = method_match.group(1)
                # Skip common non-method keywords
                if fn_name not in ('data', 'computed', 'watch', 'methods', 'props',
                                    'mounted', 'created', 'beforeCreate', 'beforeMount',
                                    'beforeUpdate', 'updated', 'beforeDestroy', 'destroyed',
                                    'beforeUnmount', 'unmounted', 'activated', 'deactivated',
                                    'if', 'for', 'while', 'switch', 'catch', 'return',
                                    'import', 'export', 'const', 'let', 'var', 'class',
                                    'new', 'typeof', 'instanceof', 'void', 'delete', 'throw'):
                    node_id = f"{file_path}:{abs_line}"
                    nodes.append({
                        "id": node_id,
                        "fn": fn_name,
                        "file": file_path,
                        "line": abs_line,
                        "type": "method",
                    })

    # ─── Parse function calls in body (edges) ─────────────
    # This is a simplified approach — for each node, scan surrounding lines for calls
    for node in list(nodes):
        _extract_calls_from_body(node, lines, file_path, edges)


def _extract_calls_from_line(line: str, fn_name: str, node_id: str,
                               file_path: str, line_num: int, edges: List[Dict]):
    """Extract function calls from a single line and create edges."""
    # Find function calls: name(...)
    for match in re.finditer(r'(\w+)\s*\(', line):
        called_fn = match.group(1)
        # Skip the function itself and keywords
        if called_fn != fn_name and called_fn not in (
            'if', 'for', 'while', 'switch', 'catch', 'return', 'new',
            'typeof', 'instanceof', 'import', 'export', 'const', 'let', 'var',
            'function', 'class', 'async', 'await', 'throw', 'delete',
        ):
            edges.append({
                "from": node_id,
                "to": called_fn,
                "type": "call",
                "file": file_path,
                "line": line_num,
            })


def _extract_calls_from_body(node: Dict, lines: List[str],
                               file_path: str, edges: List[Dict]):
    """Extract function calls from the body of a node (simplified)."""
    node_line = node.get("line", 0)
    fn_name = node.get("fn", "")
    node_id = node.get("id", "")

    # Scan a few lines after the node declaration for calls
    max_scan = min(node_line + 15, len(lines))
    for i in range(node_line, max_scan):
        if i >= len(lines):
            break
        line = lines[i]
        for match in re.finditer(r'(\w+)\s*\(', line):
            called_fn = match.group(1)
            if called_fn != fn_name and called_fn not in (
                'if', 'for', 'while', 'switch', 'catch', 'return', 'new',
                'typeof', 'instanceof', 'import', 'export', 'const', 'let', 'var',
                'function', 'class', 'async', 'await', 'throw', 'delete',
                'console', 'Math', 'JSON', 'Object', 'Array', 'String', 'Number',
                'Boolean', 'Date', 'Promise', 'Map', 'Set', 'Symbol', 'Error',
                'parseInt', 'parseFloat', 'isNaN', 'isFinite', 'encodeURI',
                'decodeURI', 'encodeURIComponent', 'decodeURIComponent',
            ):
                edges.append({
                    "from": node_id,
                    "to": called_fn,
                    "type": "call",
                    "file": file_path,
                    "line": i + 1,
                })


def _find_line_in_content(content: str, pos: int) -> int:
    """Convert a character position to a 1-based line number."""
    return content[:pos].count('\n') + 1
