#!/usr/bin/env python3
"""
CodeLens Watch — File watcher that auto-generates codelens/outline.json

Monitors a project folder for changes, re-scans on file events,
and writes structured code outline to codelens/outline.json and
codelens/summary.json.

Usage:
    python3 codelens-watch.py <watch-folder> [--debounce 0.5] [--output-dir codelens]

Example:
    python3 codelens-watch.py smart-tax-assistance/app
    python3 codelens-watch.py ./src --debounce 1.0 --output-dir .codelens
"""

import sys
import os
import re
import json
import time
import argparse
import threading
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Set

# ─── Constants ────────────────────────────────────────────────────

SOURCE_EXTENSIONS: Set[str] = {
    '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx',
    '.py', '.rs', '.html', '.htm',
    '.css', '.scss', '.less', '.sass',
    '.vue', '.svelte',
}

IGNORE_DIRS: Set[str] = {
    'node_modules', '.git', 'dist', 'build', 'target',
    '__pycache__', '.codelens', '.next', '.cache',
    'vendor', '.venv', 'venv', 'env', '.env',
    'coverage', '.nyc_output', '.turbo',
}

# ─── Multi-Language Regex Outline Extractor ───────────────────────

# JS/TS skip names (keywords + builtins)
_JS_SKIP = {
    'if', 'else', 'for', 'while', 'switch', 'catch', 'return', 'throw',
    'const', 'let', 'var', 'function', 'class', 'new', 'typeof', 'instanceof',
    'async', 'await', 'yield', 'import', 'export', 'from', 'default',
    'try', 'finally', 'break', 'continue', 'do', 'in', 'of',
    'true', 'false', 'null', 'undefined', 'void', 'delete',
    'console', 'require', 'module', 'exports', 'process', 'global',
    'String', 'Number', 'Boolean', 'Array', 'Object', 'Map', 'Set',
    'Promise', 'Error', 'TypeError', 'parseInt', 'parseFloat',
    'JSON', 'Date', 'RegExp', 'Math', 'Buffer',
    'setTimeout', 'setInterval', 'clearTimeout', 'clearInterval',
    'document', 'window', 'navigator', 'fetch', 'Response', 'Request',
    'Headers', 'URL', 'URLSearchParams', 'FormData',
}

_PY_SKIP = {
    'if', 'else', 'elif', 'for', 'while', 'with', 'try', 'except', 'finally',
    'return', 'yield', 'raise', 'break', 'continue', 'pass', 'import', 'from',
    'class', 'def', 'async', 'await', 'lambda', 'global', 'nonlocal',
    'True', 'False', 'None',
    'print', 'len', 'range', 'int', 'str', 'float', 'bool', 'list', 'dict',
    'set', 'tuple', 'type', 'isinstance', 'super', 'property',
    'enumerate', 'zip', 'map', 'filter', 'sorted', 'reversed',
    'iter', 'next', 'abs', 'min', 'max', 'sum', 'any', 'all',
    'self', 'cls',
}

_RS_SKIP = {
    'if', 'else', 'for', 'while', 'loop', 'match', 'return', 'break',
    'continue', 'let', 'mut', 'pub', 'fn', 'struct', 'enum', 'impl',
    'trait', 'use', 'mod', 'crate', 'super', 'self', 'Self',
    'true', 'false', 'as', 'in', 'ref', 'move', 'dyn', 'async', 'await',
    'Some', 'None', 'Ok', 'Err', 'new', 'default',
}


def _strip_comments(content: str, ext: str) -> str:
    """Remove comments based on file type."""
    if ext in ('.py',):
        content = re.sub(r'#.*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'""".*?"""', '', content, flags=re.DOTALL)
        content = re.sub(r"'''.*?'''", '', content, flags=re.DOTALL)
    elif ext in ('.rs',):
        content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    elif ext in ('.html', '.htm', '.vue', '.svelte'):
        content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        content = re.sub(r'(?<!:)//.*$', '', content, flags=re.MULTILINE)
    else:
        # JS/TS/CSS and similar
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        content = re.sub(r'(?<!:)//.*$', '', content, flags=re.MULTILINE)
    return content


def extract_outline(filepath: str, workspace: str) -> Optional[Dict[str, Any]]:
    """
    Extract a structural outline from a single source file.
    Uses regex-based extraction — works for all supported languages
    without needing tree-sitter installed.
    """
    ext = os.path.splitext(filepath)[1].lower()
    if ext not in SOURCE_EXTENSIONS:
        return None

    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except IOError:
        return None

    rel_path = os.path.relpath(filepath, workspace)
    line_count = content.count('\n') + 1
    clean = _strip_comments(content, ext)

    outline: Dict[str, Any] = {
        'file': rel_path,
        'language': _detect_lang(ext),
        'line_count': line_count,
        'imports': [],
        'functions': [],
        'classes': [],
        'interfaces': [],
        'types': [],
        'variables': [],
        'exports': [],
        'components': [],
    }

    if ext in ('.js', '.mjs', '.cjs'):
        _extract_js(clean, outline)
    elif ext == '.ts':
        _extract_ts(clean, outline)
    elif ext in ('.tsx', '.jsx'):
        _extract_tsx(clean, outline)
    elif ext == '.py':
        _extract_python(clean, outline)
    elif ext == '.rs':
        _extract_rust(clean, outline)
    elif ext in ('.html', '.htm'):
        _extract_html(clean, outline)
    elif ext in ('.css', '.scss', '.less', '.sass'):
        _extract_css(clean, outline)
    elif ext == '.vue':
        _extract_vue(content, outline)  # pass raw content for section splitting
    elif ext == '.svelte':
        _extract_svelte(content, outline)
    else:
        _extract_generic(clean, outline)

    # Remove empty sections to keep JSON compact
    outline = {k: v for k, v in outline.items() if v or k in ('file', 'language', 'line_count')}
    return outline


# ─── Language-specific extractors ─────────────────────────────────

def _extract_js(content: str, outline: Dict) -> None:
    for line_num, line in enumerate(content.split('\n'), 1):
        stripped = line.strip()
        # Imports
        if stripped.startswith('import '):
            outline['imports'].append({'text': stripped, 'line': line_num})
        # Function declarations
        m = re.match(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)', stripped)
        if m and m.group(1) not in _JS_SKIP:
            outline['functions'].append({'name': m.group(1), 'line': line_num})
            if stripped.startswith('export '):
                outline['exports'].append({'name': m.group(1), 'line': line_num})
            continue
        # Arrow / const functions
        m = re.match(r'(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[^=])\s*=>', stripped)
        if m and m.group(1) not in _JS_SKIP:
            outline['functions'].append({'name': m.group(1), 'line': line_num, 'arrow': True})
            if stripped.startswith('export '):
                outline['exports'].append({'name': m.group(1), 'line': line_num})
            continue
        # Class declarations
        m = re.match(r'(?:export\s+)?(?:default\s+)?class\s+(\w+)', stripped)
        if m and m.group(1) not in _JS_SKIP:
            outline['classes'].append({'name': m.group(1), 'line': line_num})
            if stripped.startswith('export '):
                outline['exports'].append({'name': m.group(1), 'line': line_num})
            continue
        # Other exports
        if stripped.startswith('export '):
            name = re.search(r'export\s+(?:default\s+)?(?:function\s+|class\s+|const\s+|let\s+|var\s+)?(\w+)', stripped)
            if name and name.group(1) not in _JS_SKIP:
                outline['exports'].append({'name': name.group(1), 'line': line_num})


def _extract_ts(content: str, outline: Dict) -> None:
    _extract_js(content, outline)
    for line_num, line in enumerate(content.split('\n'), 1):
        stripped = line.strip()
        m = re.match(r'(?:export\s+)?interface\s+(\w+)', stripped)
        if m and m.group(1) not in _JS_SKIP:
            outline['interfaces'].append({'name': m.group(1), 'line': line_num})
        m = re.match(r'(?:export\s+)?type\s+(\w+)', stripped)
        if m and m.group(1) not in _JS_SKIP:
            outline['types'].append({'name': m.group(1), 'line': line_num})


def _extract_tsx(content: str, outline: Dict) -> None:
    _extract_ts(content, outline)
    # Detect React components (PascalCase functions)
    for fn in outline.get('functions', []):
        if fn['name'][0].isupper():
            fn['component'] = True
            outline['components'].append({'name': fn['name'], 'line': fn['line']})


def _extract_python(content: str, outline: Dict) -> None:
    current_class = None
    class_indent = 0
    for line_num, line in enumerate(content.split('\n'), 1):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())

        # Track class scope
        if stripped.startswith('class '):
            m = re.match(r'class\s+(\w+)', stripped)
            if m and m.group(1) not in _PY_SKIP:
                current_class = m.group(1)
                class_indent = indent
                methods = []
                outline['classes'].append({'name': current_class, 'line': line_num, 'methods': methods})
            continue

        # Detect dedent from class
        if current_class and indent <= class_indent and stripped and not stripped.startswith('#'):
            current_class = None

        # Function definitions
        m = re.match(r'(?:async\s+)?def\s+(\w+)', stripped)
        if m and m.group(1) not in _PY_SKIP:
            fn_entry = {'name': m.group(1), 'line': line_num}
            if current_class:
                # Add as method to the last class
                for cls in reversed(outline['classes']):
                    if cls['name'] == current_class:
                        cls.setdefault('methods', []).append({'name': m.group(1), 'line': line_num})
                        break
            else:
                outline['functions'].append(fn_entry)
            continue

        # Imports
        if stripped.startswith('import ') or stripped.startswith('from '):
            outline['imports'].append({'text': stripped, 'line': line_num})
            continue

        # Module-level variables (heuristic: top-level assignment)
        if indent == 0 and '=' in stripped and not stripped.startswith('#'):
            m = re.match(r'^(\w+)\s*=', stripped)
            if m and m.group(1) not in _PY_SKIP and m.group(1)[0].isupper() or (m and m.group(1) not in _PY_SKIP and m.group(1)[0].islower()):
                pass  # Python variables are too noisy; skip for now


def _extract_rust(content: str, outline: Dict) -> None:
    current_impl = None
    for line_num, line in enumerate(content.split('\n'), 1):
        stripped = line.strip()

        # Use declarations
        m = re.match(r'use\s+(.+?);', stripped)
        if m:
            outline['imports'].append({'text': f'use {m.group(1)};', 'line': line_num})
            continue

        # impl blocks
        m = re.match(r'impl\s+(?:(\w+)\s+for\s+)?(\w+)', stripped)
        if m:
            trait_name, impl_type = m.groups()
            current_impl = impl_type
            entry = {'name': impl_type, 'line': line_num, 'methods': []}
            if trait_name:
                entry['trait'] = trait_name
            outline.setdefault('impls', []).append(entry)
            continue

        # Function declarations
        m = re.match(r'(?:pub\s+)?(?:async\s+)?fn\s+(\w+)', stripped)
        if m and m.group(1) not in _RS_SKIP:
            entry = {'name': m.group(1), 'line': line_num}
            if 'pub ' in stripped:
                entry['pub'] = True
            if 'async ' in stripped:
                entry['async'] = True
            if current_impl:
                # Add to last impl
                for impl in reversed(outline.get('impls', [])):
                    if impl['name'] == current_impl:
                        impl['methods'].append({'name': m.group(1), 'line': line_num})
                        break
            else:
                outline['functions'].append(entry)
            continue

        # Struct
        m = re.match(r'(?:pub\s+)?struct\s+(\w+)', stripped)
        if m and m.group(1) not in _RS_SKIP:
            outline.setdefault('structs', []).append({'name': m.group(1), 'line': line_num})
            continue

        # Enum
        m = re.match(r'(?:pub\s+)?enum\s+(\w+)', stripped)
        if m and m.group(1) not in _RS_SKIP:
            outline.setdefault('enums', []).append({'name': m.group(1), 'line': line_num})
            continue

        # Trait
        m = re.match(r'(?:pub\s+)?trait\s+(\w+)', stripped)
        if m and m.group(1) not in _RS_SKIP:
            outline.setdefault('traits', []).append({'name': m.group(1), 'line': line_num})


def _extract_html(content: str, outline: Dict) -> None:
    outline.pop('functions', None)
    outline.pop('classes', None)
    outline.pop('interfaces', None)
    outline.pop('types', None)
    outline.pop('variables', None)
    outline.pop('exports', None)
    outline.pop('components', None)
    result: Dict[str, Any] = {
        'file': outline['file'],
        'language': outline['language'],
        'line_count': outline['line_count'],
        'ids': [],
        'classes': [],
        'scripts': [],
        'links': [],
    }
    for line_num, line in enumerate(content.split('\n'), 1):
        for m in re.finditer(r'\bid\s*=\s*["\']([^"\']+)["\']', line):
            result['ids'].append({'name': m.group(1), 'line': line_num})
        for m in re.finditer(r'\bclass\s*=\s*["\']([^"\']+)["\']', line):
            for cls in m.group(1).split():
                if cls.strip():
                    result['classes'].append({'name': cls.strip(), 'line': line_num})
        if '<script' in line:
            src = re.search(r'src\s*=\s*["\']([^"\']+)["\']', line)
            result['scripts'].append({'src': src.group(1) if src else 'inline', 'line': line_num})
        if '<link' in line:
            href = re.search(r'href\s*=\s*["\']([^"\']+)["\']', line)
            if href:
                result['links'].append({'href': href.group(1), 'line': line_num})
    outline.clear()
    outline.update(result)


def _extract_css(content: str, outline: Dict) -> None:
    outline.pop('functions', None)
    outline.pop('classes', None)
    outline.pop('interfaces', None)
    outline.pop('types', None)
    outline.pop('variables', None)
    outline.pop('exports', None)
    outline.pop('components', None)
    outline.pop('imports', None)
    result: Dict[str, Any] = {
        'file': outline['file'],
        'language': outline['language'],
        'line_count': outline['line_count'],
        'selectors': [],
        'variables': [],
        'keyframes': [],
    }
    for line_num, line in enumerate(content.split('\n'), 1):
        stripped = line.strip()
        for m in re.finditer(r'^(\.[a-zA-Z_][\w-]*)', stripped):
            result['selectors'].append({'name': m.group(1), 'type': 'class', 'line': line_num})
        for m in re.finditer(r'^(#[a-zA-Z_][\w-]*)', stripped):
            result['selectors'].append({'name': m.group(1), 'type': 'id', 'line': line_num})
        for m in re.finditer(r'(--[\w-]+)\s*:', stripped):
            result['variables'].append({'name': m.group(1), 'line': line_num})
        for m in re.finditer(r'(\$[\w-]+)\s*:', stripped):
            result['variables'].append({'name': m.group(1), 'line': line_num})
        if '@keyframes' in stripped:
            m = re.search(r'@keyframes\s+([\w-]+)', stripped)
            if m:
                result['keyframes'].append({'name': m.group(1), 'line': line_num})
    outline.clear()
    outline.update(result)


def _extract_vue(content: str, outline: Dict) -> None:
    """Parse Vue SFC — split into template, script, style sections."""
    template_match = re.search(r'<template>(.*?)</template>', content, re.DOTALL)
    script_match = re.search(r'<script[^>]*>(.*?)</script>', content, re.DOTALL)
    style_match = re.search(r'<style[^>]*>(.*?)</style>', content, re.DOTALL)

    template_section = {'ids': [], 'classes': []}
    if template_match:
        for line_num, line in enumerate(template_match.group(1).split('\n'), 1):
            for m in re.finditer(r'\bid\s*=\s*["\']([^"\']+)["\']', line):
                template_section['ids'].append({'name': m.group(1), 'line': line_num})
            for m in re.finditer(r'\bclass\s*=\s*["\']([^"\']+)["\']', line):
                for cls in m.group(1).split():
                    if cls.strip():
                        template_section['classes'].append({'name': cls.strip(), 'line': line_num})

    script_section = {'imports': [], 'functions': [], 'classes': [], 'exports': []}
    if script_match:
        _extract_js(script_match.group(1), script_section)

    style_section = {'selectors': [], 'variables': []}
    if style_match:
        _extract_css(style_match.group(1), style_section)

    outline.pop('functions', None)
    outline.pop('classes', None)
    outline.pop('interfaces', None)
    outline.pop('types', None)
    outline.pop('variables', None)
    outline.pop('exports', None)
    outline.pop('components', None)
    outline.pop('imports', None)

    result = {
        'file': outline['file'],
        'language': outline['language'],
        'line_count': outline['line_count'],
        'template': template_section,
        'script': script_section,
        'style': style_section,
    }
    outline.clear()
    outline.update(result)


def _extract_svelte(content: str, outline: Dict) -> None:
    """Parse Svelte component — split into markup, script, style sections."""
    script_match = re.search(r'<script[^>]*>(.*?)</script>', content, re.DOTALL)
    style_match = re.search(r'<style[^>]*>(.*?)</style>', content, re.DOTALL)

    markup = content
    if script_match:
        markup = markup.replace(script_match.group(0), '')
    if style_match:
        markup = markup.replace(style_match.group(0), '')

    markup_section = {'ids': [], 'classes': []}
    for m in re.finditer(r'\bid\s*=\s*["\']([^"\']+)["\']', markup):
        markup_section['ids'].append({'name': m.group(1)})
    for m in re.finditer(r'\bclass\s*=\s*["\']([^"\']+)["\']', markup):
        for cls in m.group(1).split():
            if cls.strip():
                markup_section['classes'].append({'name': cls.strip()})
    for m in re.finditer(r'class:(\w+)', markup):
        markup_section['classes'].append({'name': m.group(1), 'directive': True})

    script_section = {'imports': [], 'functions': [], 'classes': [], 'exports': []}
    if script_match:
        _extract_js(script_match.group(1), script_section)

    style_section = {'selectors': [], 'variables': []}
    if style_match:
        _extract_css(style_match.group(1), style_section)

    outline.pop('functions', None)
    outline.pop('classes', None)
    outline.pop('interfaces', None)
    outline.pop('types', None)
    outline.pop('variables', None)
    outline.pop('exports', None)
    outline.pop('components', None)
    outline.pop('imports', None)

    result = {
        'file': outline['file'],
        'language': outline['language'],
        'line_count': outline['line_count'],
        'markup': markup_section,
        'script': script_section,
        'style': style_section,
    }
    outline.clear()
    outline.update(result)


def _extract_generic(content: str, outline: Dict) -> None:
    """Fallback for unknown file types."""
    for line_num, line in enumerate(content.split('\n'), 1):
        stripped = line.strip()
        for m in re.finditer(r'(?:function|def|fn)\s+(\w+)', stripped):
            if m.group(1) not in _JS_SKIP:
                outline['functions'].append({'name': m.group(1), 'line': line_num})


def _detect_lang(ext: str) -> str:
    mapping = {
        '.js': 'javascript', '.mjs': 'javascript', '.cjs': 'javascript',
        '.ts': 'typescript', '.tsx': 'tsx', '.jsx': 'tsx',
        '.rs': 'rust', '.py': 'python',
        '.html': 'html', '.htm': 'html',
        '.css': 'css', '.scss': 'scss', '.less': 'less', '.sass': 'sass',
        '.vue': 'vue', '.svelte': 'svelte',
    }
    return mapping.get(ext, 'unknown')


# ─── Scanner ──────────────────────────────────────────────────────

def scan_workspace(workspace: str) -> Dict[str, Any]:
    """
    Scan all source files in the workspace and return outline data.
    """
    workspace = os.path.abspath(workspace)
    outlines: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    total_lines = 0

    for root, dirs, filenames in os.walk(workspace):
        # Filter out ignored directories
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')]

        # Don't descend into output directory
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in SOURCE_EXTENSIONS:
                continue

            filepath = os.path.join(root, filename)
            try:
                result = extract_outline(filepath, workspace)
                if result:
                    outlines.append(result)
                    total_lines += result.get('line_count', 0)
            except Exception as e:
                errors.append({'file': os.path.relpath(filepath, workspace), 'error': str(e)})

    return {
        'status': 'ok',
        'workspace': workspace,
        'files_outlined': len(outlines),
        'total_lines': total_lines,
        'outlines': outlines,
        'errors': errors if errors else None,
    }


def compute_summary(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute aggregate summary from outline data.
    """
    total_functions = 0
    total_classes = 0
    total_interfaces = 0
    total_types = 0
    total_variables = 0
    total_exports = 0
    total_components = 0
    total_imports = 0
    total_lines = data.get('total_lines', 0)
    files_by_lang: Dict[str, int] = {}

    for outline in data.get('outlines', []):
        lang = outline.get('language', 'unknown')
        files_by_lang[lang] = files_by_lang.get(lang, 0) + 1

        total_functions += len(outline.get('functions', []))
        total_classes += len(outline.get('classes', []))
        total_interfaces += len(outline.get('interfaces', []))
        total_types += len(outline.get('types', []))
        total_variables += len(outline.get('variables', []))
        total_exports += len(outline.get('exports', []))
        total_components += len(outline.get('components', []))
        total_imports += len(outline.get('imports', []))

        # Count class methods
        for cls in outline.get('classes', []):
            total_functions += len(cls.get('methods', []))

    return {
        'workspace': data.get('workspace', ''),
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'files': data.get('files_outlined', 0),
        'total_lines': total_lines,
        'functions': total_functions,
        'classes': total_classes,
        'interfaces': total_interfaces,
        'types': total_types,
        'variables': total_variables,
        'exports': total_exports,
        'components': total_components,
        'imports': total_imports,
        'files_by_language': files_by_lang,
    }


def write_output(workspace: str, data: Dict[str, Any], output_dir: str) -> None:
    """
    Write outline.json and summary.json to the output directory
    inside the watched folder.
    """
    out_path = os.path.join(workspace, output_dir)
    os.makedirs(out_path, exist_ok=True)

    # outline.json — full detail per file
    outline_path = os.path.join(out_path, 'outline.json')
    with open(outline_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # summary.json — aggregate totals
    summary = compute_summary(data)
    summary_path = os.path.join(out_path, 'summary.json')
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return summary


# ─── Watcher ──────────────────────────────────────────────────────

class DebouncedWatcher:
    """
    File watcher with debounce support.
    Uses watchdog for event-driven watching, falls back to polling.
    """

    def __init__(self, workspace: str, debounce: float = 0.5, output_dir: str = 'codelens'):
        self.workspace = os.path.abspath(workspace)
        self.debounce = debounce
        self.output_dir = output_dir
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._changed_files: Set[str] = set()
        self._running = True

    def _on_change(self, filepath: str) -> None:
        """Called when a file change is detected. Debounces rapid events."""
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in SOURCE_EXTENSIONS:
            return

        # Ignore changes in our own output directory
        if self.output_dir in filepath:
            return

        with self._lock:
            self._changed_files.add(filepath)
            # Reset the debounce timer
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce, self._do_rescan)
            self._timer.daemon = True
            self._timer.start()

    def _do_rescan(self) -> None:
        """Perform the actual rescan after debounce period."""
        with self._lock:
            changed = self._changed_files.copy()
            self._changed_files.clear()

        if not changed:
            return

        now = datetime.now().strftime('%H:%M:%S')
        changed_rel = [os.path.relpath(f, self.workspace) for f in changed]
        print(f'[CodeLens Watch] Changed: {", ".join(changed_rel)}')

        data = scan_workspace(self.workspace)
        summary = write_output(self.workspace, data, self.output_dir)

        funcs = summary.get('functions', 0)
        classes = summary.get('classes', 0)
        interfaces = summary.get('interfaces', 0)
        types = summary.get('types', 0)
        files = summary.get('files', 0)
        print(f'[{now}] \u2713 {files} files | {funcs} funcs | {classes} classes | {interfaces} interfaces | {types} types')

    def initial_scan(self) -> None:
        """Run the initial scan and write output files."""
        print(f'[CodeLens Watch] Scanning {self.workspace}...')
        data = scan_workspace(self.workspace)
        summary = write_output(self.workspace, data, self.output_dir)

        funcs = summary.get('functions', 0)
        classes = summary.get('classes', 0)
        interfaces = summary.get('interfaces', 0)
        types = summary.get('types', 0)
        files = summary.get('files', 0)
        now = datetime.now().strftime('%H:%M:%S')
        print(f'[{now}] \u2713 {files} files | {funcs} funcs | {classes} classes | {interfaces} interfaces | {types} types')

    def start_watchdog(self) -> None:
        """Start watching using watchdog library."""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            print('[CodeLens Watch] watchdog not installed. Install with: pip install watchdog')
            print('[CodeLens Watch] Falling back to polling mode (every 2 seconds)...')
            self.start_polling()
            return

        watcher = self

        class Handler(FileSystemEventHandler):
            def on_modified(self, event):
                if not event.is_directory:
                    watcher._on_change(event.src_path)

            def on_created(self, event):
                if not event.is_directory:
                    watcher._on_change(event.src_path)

            def on_deleted(self, event):
                if not event.is_directory:
                    watcher._on_change(event.src_path)

        observer = Observer()
        handler = Handler()
        observer.schedule(handler, self.workspace, recursive=True)
        observer.start()

        print(f'[CodeLens Watch] Watching {self.workspace} (debounce: {self.debounce}s)')
        print('[CodeLens Watch] Press Ctrl+C to stop')

        try:
            while self._running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            observer.stop()
            observer.join()
            print('[CodeLens Watch] Stopped.')

    def start_polling(self, interval: float = 2.0) -> None:
        """Fallback: poll for changes every `interval` seconds."""
        print(f'[CodeLens Watch] Polling {self.workspace} every {interval}s')
        print('[CodeLens Watch] Press Ctrl+C to stop')

        last_mtimes: Dict[str, float] = {}

        # Initial mtimes
        for root, dirs, filenames in os.walk(self.workspace):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')]
            for filename in filenames:
                ext = os.path.splitext(filename)[1].lower()
                if ext in SOURCE_EXTENSIONS:
                    filepath = os.path.join(root, filename)
                    try:
                        last_mtimes[filepath] = os.path.getmtime(filepath)
                    except OSError:
                        pass

        try:
            while self._running:
                time.sleep(interval)
                changed = False
                for filepath in list(last_mtimes.keys()):
                    try:
                        current = os.path.getmtime(filepath)
                        if current != last_mtimes[filepath]:
                            last_mtimes[filepath] = current
                            self._on_change(filepath)
                            changed = True
                    except OSError:
                        # File was deleted
                        del last_mtimes[filepath]
                        self._on_change(filepath)
                        changed = True

                # Check for new files
                for root, dirs, filenames in os.walk(self.workspace):
                    dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')]
                    for filename in filenames:
                        ext = os.path.splitext(filename)[1].lower()
                        if ext in SOURCE_EXTENSIONS:
                            filepath = os.path.join(root, filename)
                            if filepath not in last_mtimes:
                                try:
                                    last_mtimes[filepath] = os.path.getmtime(filepath)
                                    self._on_change(filepath)
                                    changed = True
                                except OSError:
                                    pass

        except KeyboardInterrupt:
            pass
        finally:
            print('[CodeLens Watch] Stopped.')

    def run(self) -> None:
        """Main entry: initial scan + start watching."""
        self.initial_scan()
        self.start_watchdog()


# ─── CLI ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='CodeLens Watch — Auto-generate codelens/outline.json on file changes'
    )
    parser.add_argument(
        'folder',
        help='Folder to watch (e.g. smart-tax-assistance/app)'
    )
    parser.add_argument(
        '--debounce', '-d',
        type=float,
        default=0.5,
        help='Debounce interval in seconds (default: 0.5)'
    )
    parser.add_argument(
        '--output-dir', '-o',
        default='codelens',
        help='Output directory name inside the watched folder (default: codelens)'
    )
    parser.add_argument(
        '--once',
        action='store_true',
        help='Scan once and exit (no watcher)'
    )

    args = parser.parse_args()

    if not os.path.isdir(args.folder):
        print(f'[CodeLens Watch] Error: {args.folder} is not a directory')
        sys.exit(1)

    if args.once:
        # Single scan mode
        data = scan_workspace(args.folder)
        summary = write_output(args.folder, data, args.output_dir)
        funcs = summary.get('functions', 0)
        classes = summary.get('classes', 0)
        interfaces = summary.get('interfaces', 0)
        types = summary.get('types', 0)
        files = summary.get('files', 0)
        print(f'\u2713 {files} files | {funcs} funcs | {classes} classes | {interfaces} interfaces | {types} types')
        print(f'\u2713 Output: {os.path.join(args.folder, args.output_dir)}/')
        return

    watcher = DebouncedWatcher(
        workspace=args.folder,
        debounce=args.debounce,
        output_dir=args.output_dir,
    )
    watcher.run()


if __name__ == '__main__':
    main()
