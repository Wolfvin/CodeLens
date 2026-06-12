"""
Tailwind CSS Detector for CodeLens
Detects and tracks Tailwind CSS utility classes used in HTML/JSX/Vue/Svelte.

Tailwind classes are special because:
1. They're defined by the framework, not in CSS files
2. They can be purged — detecting "dead" tailwind classes requires
   comparing HTML usage vs tailwind.config.js content
3. Custom utilities defined via @apply or plugins
4. Dynamic classes: className={`text-${size}-${color}`} can't be fully tracked

This module:
- Identifies tailwind utility classes from HTML/JSX/Vue/Svelte
- Reads tailwind.config.js for custom theme values
- Flags dynamic class patterns that can't be statically analyzed
"""

import json
import os
import re
from typing import Dict, List, Any, Optional, Set
from utils import DEFAULT_IGNORE_DIRS, should_ignore_dir


# Common Tailwind utility prefixes (v3+)
TAILWIND_PREFIXES = [
    # Layout
    'container', 'mx-auto', 'box-border', 'box-content',
    # Display
    'block', 'inline-block', 'inline', 'flex', 'inline-flex', 'grid', 'inline-grid',
    'hidden', 'table', 'table-row', 'table-cell',
    # Position
    'static', 'fixed', 'absolute', 'relative', 'sticky',
    # Flexbox
    'flex-row', 'flex-col', 'flex-wrap', 'flex-nowrap', 'flex-1', 'flex-auto',
    'flex-initial', 'flex-none', 'grow', 'grow-0', 'shrink', 'shrink-0',
    'items-start', 'items-center', 'items-end', 'items-baseline', 'items-stretch',
    'justify-start', 'justify-center', 'justify-end', 'justify-between', 'justify-around', 'justify-evenly',
    # Spacing
    'p-', 'px-', 'py-', 'pt-', 'pr-', 'pb-', 'pl-',
    'm-', 'mx-', 'my-', 'mt-', 'mr-', 'mb-', 'ml-',
    'space-x-', 'space-y-',
    # Sizing
    'w-', 'h-', 'min-w-', 'min-h-', 'max-w-', 'max-h-',
    # Typography
    'text-', 'font-', 'leading-', 'tracking-', 'underline', 'line-through',
    'uppercase', 'lowercase', 'capitalize', 'normal-case',
    # Backgrounds
    'bg-', 'bg-gradient-',
    # Borders
    'border', 'border-', 'rounded', 'rounded-',
    # Effects
    'shadow', 'shadow-', 'opacity-',
    # Transitions
    'transition', 'duration-', 'ease-',
    # Transforms
    'scale-', 'rotate-', 'translate-', 'skew-',
    # Interactivity
    'cursor-', 'pointer-events-', 'select-',
    # Responsive prefixes
    'sm:', 'md:', 'lg:', 'xl:', '2xl:',
    # State prefixes
    'hover:', 'focus:', 'active:', 'disabled:', 'group-hover:', 'dark:',
]


def is_tailwind_class(name: str, config: Optional[Dict] = None) -> bool:
    """
    Check if a class name looks like a Tailwind utility class.
    Uses prefix matching against known Tailwind patterns.
    Handles Tailwind !important prefix (e.g., '!bg-red-500') and
    combined state+important prefixes (e.g., 'hover:!bg-red-500').
    Also detects UnoCSS utility patterns (e.g., 'all:font-mono', 'text-sm').
    """
    # Handle Tailwind !important prefix: !bg-red-500 → bg-red-500
    check_name = name.lstrip('!')
    if check_name != name:
        # Name had ! prefix — check the remainder
        return is_tailwind_class(check_name, config)

    # Check for UnoCSS utility patterns first
    if _is_unocss_class(check_name):
        return True

    # Check against known prefixes
    for prefix in TAILWIND_PREFIXES:
        if check_name.startswith(prefix) or check_name == prefix.rstrip('-'):
            return True

    # Check responsive/state prefixes: sm:flex, md:text-lg, hover:bg-red-500, dark:bg-gray-900
    state_prefixes = ['sm:', 'md:', 'lg:', 'xl:', '2xl:', 'hover:', 'focus:',
                      'active:', 'disabled:', 'group-hover:', 'dark:', 'first:',
                      'last:', 'odd:', 'even:', 'visited:', 'motion-safe:', 'motion-reduce:']
    for sp in state_prefixes:
        if check_name.startswith(sp):
            remainder = check_name[len(sp):]
            # Handle !important after state prefix: hover:!bg-red-500
            remainder = remainder.lstrip('!')
            for prefix in TAILWIND_PREFIXES:
                if remainder.startswith(prefix.rstrip('-')) or remainder == prefix.rstrip('-'):
                    return True

    # Check for negative values: -mt-4, -mx-2
    if check_name.startswith('-'):
        remainder = check_name[1:]
        for prefix in TAILWIND_PREFIXES:
            if remainder.startswith(prefix.rstrip('-')):
                return True

    # Check custom prefix from config
    if config and 'prefix' in config:
        custom_prefix = config['prefix']
        if check_name.startswith(custom_prefix):
            return True

    return False


# ─── UnoCSS Detection ──────────────────────────────────────────

# UnoCSS uses bare utility names without the tw- prefix.
# These overlap heavily with Tailwind but also include
# additional shortcuts and variants (e.g., "all:font-mono").
_UNOCSS_BARE_UTILITIES = {
    # Layout
    'flex', 'grid', 'block', 'inline', 'inline-block', 'inline-flex',
    'hidden', 'relative', 'absolute', 'fixed', 'sticky', 'static',
    # Flex/Grid alignment
    'items-center', 'items-start', 'items-end', 'items-baseline',
    'justify-center', 'justify-start', 'justify-end', 'justify-between',
    'flex-col', 'flex-row', 'flex-wrap', 'flex-1',
    'self-center', 'self-start', 'self-end', 'self-auto',
    # Spacing (with values like p-4, m-2, etc.)
    'p', 'px', 'py', 'pt', 'pr', 'pb', 'pl',
    'm', 'mx', 'my', 'mt', 'mr', 'mb', 'ml',
    # Sizing
    'w', 'h', 'min-w', 'min-h', 'max-w', 'max-h',
    # Typography
    'text', 'font', 'leading', 'tracking', 'underline', 'line-through',
    'uppercase', 'lowercase', 'capitalize',
    # Backgrounds
    'bg',
    # Borders
    'border', 'rounded',
    # Effects
    'shadow', 'opacity',
    # Transitions
    'transition', 'duration', 'ease',
    # Transforms
    'scale', 'rotate', 'translate',
    # Interactivity
    'cursor', 'pointer-events', 'select',
    # Overflow
    'overflow', 'overflow-auto', 'overflow-hidden', 'overflow-scroll',
    'overflow-x-auto', 'overflow-y-auto',
    # Position
    'top', 'right', 'bottom', 'left', 'inset',
    'z',
    # Misc
    'animate', 'appearance', 'outline', 'ring', 'divide',
    'gap', 'space', 'order', 'col', 'row',
}

# UnoCSS variant prefixes (e.g., "all:font-mono", "sm:text-red", "hover:bg-blue")
_UNOCSS_VARIANTS = {
    'all', 'sm', 'md', 'lg', 'xl', '2xl',
    'hover', 'focus', 'active', 'disabled', 'visited',
    'dark', 'light',
    'first', 'last', 'odd', 'even',
    'group-hover', 'group-focus',
    'peer-hover', 'peer-focus',
    'before', 'after',
    'placeholder',
    'selection',
    'marker',
    'scrollbar',
    'touch',
    'motion-safe', 'motion-reduce',
    'print',
    'landscape', 'portrait',
    'lt-sm', 'lt-md', 'lt-lg', 'lt-xl',
    'at-sm', 'at-md', 'at-lg', 'at-xl',
    'at-2xl',
}


def _is_unocss_class(name: str) -> bool:
    """Check if a class name looks like a UnoCSS utility class.

    UnoCSS uses variant:value syntax (e.g., "all:font-mono")
    and bare utility names (e.g., "p-4", "text-red-500").
    """
    # Check for UnoCSS variant:value syntax: "all:font-mono", "sm:text-red"
    if ':' in name:
        parts = name.split(':', 1)
        variant = parts[0]
        utility = parts[1]
        if variant in _UNOCSS_VARIANTS:
            # Check if the utility part is a known bare utility with optional value
            utility_prefix = re.match(r'^([a-z][a-z-]+)', utility)
            if utility_prefix:
                prefix = utility_prefix.group(1)
                if prefix in _UNOCSS_BARE_UTILITIES:
                    return True
            # Also check if it's a Tailwind-style utility after the variant
            for tw_prefix in TAILWIND_PREFIXES:
                tw_clean = tw_prefix.rstrip('-')
                if utility == tw_clean or utility.startswith(tw_clean + '-'):
                    return True
        return False

    # Check bare utility names with values: "p-4", "text-red-500", "bg-blue-200"
    # Extract the prefix (everything before the first digit or hyphen-value)
    utility_prefix = re.match(r'^([a-z][a-z-]+)', name)
    if utility_prefix:
        prefix = utility_prefix.group(1)
        # Match against known UnoCSS bare utilities
        if prefix in _UNOCSS_BARE_UTILITIES:
            return True
        # Match against Tailwind prefixes (UnoCSS supports most Tailwind classes)
        for tw_prefix in TAILWIND_PREFIXES:
            tw_clean = tw_prefix.rstrip('-')
            if prefix == tw_clean or name.startswith(tw_clean + '-'):
                return True

    return False


def is_dynamic_class(name: str) -> bool:
    """
    Check if a class name contains dynamic template patterns.
    e.g., text-${color}-500 → can't be statically analyzed
    """
    return '${' in name or '{' in name


def load_tailwind_config(workspace: str) -> Optional[Dict]:
    """Load tailwind.config.js/ts/mjs if it exists."""
    config_names = [
        'tailwind.config.js',
        'tailwind.config.ts',
        'tailwind.config.mjs',
        'tailwind.config.cjs',
    ]

    for name in config_names:
        config_path = os.path.join(workspace, name)
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                # Simple JS object parser — extract the config object
                # This is a best-effort parse since we can't execute JS
                return _parse_js_config(content)
            except (IOError, json.JSONDecodeError):
                pass

    return None


def analyze_tailwind_usage(
    workspace: str,
    class_entries: List[Dict]
) -> Dict[str, Any]:
    """
    Analyze Tailwind class usage across the workspace.

    Returns:
        {
            "tailwind_classes": [...],    # Classes identified as Tailwind
            "dynamic_classes": [...],     # Classes with dynamic patterns
            "custom_utilities": [...],    # @apply-defined custom classes
            "tailwind_found": bool,
            "config": {...}|null
        }
    """
    config = load_tailwind_config(workspace)

    tailwind_classes = []
    dynamic_classes = []

    for entry in class_entries:
        name = entry["name"]
        if is_dynamic_class(name):
            dynamic_classes.append({**entry, "source": "tailwind_dynamic"})
        elif is_tailwind_class(name, config):
            tailwind_classes.append({**entry, "source": "tailwind_utility"})

    # Scan for @apply custom utilities in CSS files
    custom_utilities = _find_custom_utilities(workspace)

    return {
        "tailwind_classes": tailwind_classes,
        "dynamic_classes": dynamic_classes,
        "custom_utilities": custom_utilities,
        "tailwind_found": len(tailwind_classes) > 0 or config is not None,
        "config": config
    }


def _parse_js_config(content: str) -> Optional[Dict]:
    """
    Best-effort parse of a tailwind.config.js file.
    Extracts key configuration values using regex.
    """
    config = {}

    # Extract prefix
    prefix_match = re.search(r'prefix\s*:\s*["\']([^"\']+)["\']', content)
    if prefix_match:
        config['prefix'] = prefix_match.group(1)

    # Extract content paths
    content_match = re.search(r'content\s*:\s*\[(.*?)\]', content, re.DOTALL)
    if content_match:
        paths = re.findall(r'["\']([^"\']+)["\']', content_match.group(1))
        config['content'] = paths

    # Extract darkMode
    dark_match = re.search(r'darkMode\s*:\s*["\']([^"\']+)["\']', content)
    if dark_match:
        config['darkMode'] = dark_match.group(1)

    return config if config else None


def _find_custom_utilities(workspace: str) -> List[Dict]:
    """Find @apply-defined custom CSS utilities in the workspace."""
    utilities = []

    for root, dirs, files in os.walk(workspace):
        # Use path-segment-aware check to avoid false positives
        # (e.g., workspace named "test-dist" shouldn't match "dist")
        rel_root = os.path.relpath(root, workspace)
        if should_ignore_dir(rel_root):
            dirs.clear()
            continue

        for f in files:
            if f.endswith(('.css', '.scss', '.pcss')):
                fpath = os.path.join(root, f)
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as fh:
                        for line_num, line in enumerate(fh, 1):
                            if '@apply' in line:
                                # Extract the class name being defined
                                selector_match = re.search(r'\.([a-zA-Z_][\w-]*)\s*\{', line)
                                if selector_match:
                                    utilities.append({
                                        "name": selector_match.group(1),
                                        "path": os.path.relpath(fpath, workspace),
                                        "line": line_num,
                                        "source": "tailwind_apply"
                                    })
                except IOError:
                    pass

    return utilities
