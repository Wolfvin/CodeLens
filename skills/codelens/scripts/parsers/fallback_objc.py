"""
Fallback Objective-C Parser for CodeLens — regex-based extraction.
Extracts classes, protocols, categories, extensions, methods, properties,
and function call relationships for edge resolution.
Supports: @interface, @implementation, @protocol, @class, category, extension,
          instance/class methods, properties, #import, @selector, blocks, etc.
"""

import re
from typing import Dict, List, Any


def parse_objc_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse Objective-C source using regex — extracts classes, methods, and call edges.

    Args:
        content: File content as string.
        rel_path: Relative file path from workspace root.

    Returns:
        Dict with 'nodes' and 'edges' keys.
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # Collect definitions for edge resolution
    fn_defs: Dict[str, str] = {}      # fn_name → node_id
    type_defs: Dict[str, str] = {}    # type_name → node_id

    # ─── Imports ────────────────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*#import\s+[<"]([^>"]+)[>"]', line)
        if m:
            import_path = m.group(1)
            edges.append({"from": rel_path, "to": import_path, "type": "import", "weight": 1})
            continue
        m = re.match(r'\s*#include\s+[<"]([^>"]+)[>"]', line)
        if m:
            edges.append({"from": rel_path, "to": m.group(1), "type": "include", "weight": 1})

    # ─── @class forward declarations ────────────────────────────────
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*@class\s+([\w\s,]+)\s*;', line)
        if m:
            for cls_name in re.findall(r'(\w+)', m.group(1)):
                if cls_name[0].isupper():
                    edges.append({"from": rel_path, "to_fn": cls_name, "type": "forward_decl", "weight": 1})

    # ─── @interface declarations ────────────────────────────────────
    # @interface ClassName : SuperClass <Protocol1, Protocol2>
    # @interface ClassName (Category)
    # @interface ClassName () // Extension
    for i, line in enumerate(lines, 1):
        # Category: @interface ClassName (CategoryName)
        m = re.match(r'\s*@interface\s+(\w+)\s*\((\w*)\)', line)
        if m:
            cls_name = m.group(1)
            cat_name = m.group(2)
            node_id = f"{rel_path}:{i}:{cls_name}({cat_name})" if cat_name else f"{rel_path}:{i}:{cls_name}()"
            ntype = "category" if cat_name else "extension"
            display_name = f"{cls_name}({cat_name})" if cat_name else f"{cls_name}()"
            nodes.append({
                "id": node_id, "type": ntype,
                "name": display_name, "fn": cls_name,
                "file": rel_path, "line": i, "domain": "backend",
                "class": cls_name,
            })
            if cls_name not in type_defs:
                type_defs[cls_name] = node_id
            continue

        # Regular @interface
        m = re.match(r'\s*@interface\s+(\w+)\s*:\s*(\w+)?', line)
        if m:
            cls_name = m.group(1)
            super_class = m.group(2)
            node_id = f"{rel_path}:{i}:{cls_name}"
            ntype = "class"
            # Detect common UIKit/AppKit classes
            if super_class in ('UIViewController', 'UIView', 'UITableViewCell', 'UINavigationController',
                               'UITabBarController', 'UIWindow', 'NSViewController', 'NSView',
                               'NSWindow', 'SKView', 'SCNView', 'WKWebView'):
                ntype = "ui_class"
            elif super_class in ('NSObject',):
                ntype = "class"
            nodes.append({
                "id": node_id, "type": ntype,
                "name": cls_name, "fn": cls_name,
                "file": rel_path, "line": i, "domain": "backend",
            })
            type_defs[cls_name] = node_id
            if super_class and super_class[0].isupper():
                edges.append({"from": node_id, "to_fn": super_class, "type": "inherits", "weight": 1})
            # Check for protocols in angle brackets
            proto_match = re.search(r'<\s*([\w\s,]+)\s*>', line)
            if proto_match:
                for proto in re.findall(r'(\w+)', proto_match.group(1)):
                    if proto[0].isupper() and proto not in ('NSObject',):
                        edges.append({"from": node_id, "to_fn": proto, "type": "conforms_to", "weight": 1})
            continue

    # ─── @protocol declarations ─────────────────────────────────────
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*@protocol\s+(\w+)', line)
        if m:
            proto_name = m.group(1)
            node_id = f"{rel_path}:{i}:{proto_name}"
            nodes.append({
                "id": node_id, "type": "protocol",
                "name": proto_name, "fn": proto_name,
                "file": rel_path, "line": i, "domain": "backend",
            })
            type_defs[proto_name] = node_id

    # ─── @implementation ────────────────────────────────────────────
    current_impl_class = None
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*@implementation\s+(\w+)(?:\s*\((\w*)\))?', line)
        if m:
            cls_name = m.group(1)
            cat_name = m.group(2)
            current_impl_class = cls_name
            # If we didn't find an @interface, add the class from @implementation
            if cls_name not in type_defs:
                node_id = f"{rel_path}:{i}:{cls_name}"
                nodes.append({
                    "id": node_id, "type": "class",
                    "name": cls_name, "fn": cls_name,
                    "file": rel_path, "line": i, "domain": "backend",
                })
                type_defs[cls_name] = node_id
            continue
        if re.match(r'\s*@end', line):
            current_impl_class = None
            continue

    # ─── Methods ────────────────────────────────────────────────────
    # Instance method: - (returnType)methodName:(type)param1 name2:(type)param2
    # Class method: + (returnType)methodName
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*([+-])\s*\([^)]*\)\s*(\w+)', line)
        if m:
            method_type = m.group(1)  # + or -
            method_name = m.group(2)
            # Skip common false positives
            if method_name in ('if', 'else', 'while', 'for', 'switch', 'return',
                               'case', 'break', 'continue', 'do', 'try', 'catch',
                               'throw', 'new', 'self', 'super', 'nil', 'YES', 'NO'):
                continue
            node_id = f"{rel_path}:{i}:{method_name}"
            ntype = "class_method" if method_type == '+' else "instance_method"
            # Try to get full selector name (methodName:name2:name3:)
            full_selector = method_name
            sel_match = re.match(r'\s*[+-]\s*\([^)]*\)\s*(\w+(?::\s*\([^)]*\)\s*\w+)*)', line)
            if sel_match:
                # Build selector from all parts
                parts = re.findall(r'(\w+)\s*:', line)
                if parts:
                    full_selector = ':'.join(parts) + ':'
                    method_name = full_selector

            node = {
                "id": node_id, "type": ntype,
                "name": method_name, "fn": method_name,
                "file": rel_path, "line": i, "domain": "backend",
            }
            if current_impl_class:
                node["class"] = current_impl_class
            nodes.append(node)
            fn_defs[method_name] = node_id

    # ─── Properties ─────────────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*@property\s*\([^)]*\)\s*[\w<*>\s]+\s*(\w+)\s*;', line)
        if m:
            prop_name = m.group(1)
            node_id = f"{rel_path}:{i}:{prop_name}"
            nodes.append({
                "id": node_id, "type": "property",
                "name": prop_name, "fn": prop_name,
                "file": rel_path, "line": i, "domain": "backend",
            })

    # ─── C functions (ObjC files can contain plain C) ───────────────
    for i, line in enumerate(lines, 1):
        # Match: returnType functionName(
        m = re.match(r'\s*(?:static\s+)?(?:[\w*<>]+\s+)+(\w+)\s*\(', line)
        if m:
            fn_name = m.group(1)
            # Skip keywords and ObjC-specific tokens
            if fn_name in ('if', 'else', 'while', 'for', 'switch', 'return', 'case',
                           'break', 'continue', 'do', 'try', 'catch', 'throw', 'new',
                           'self', 'super', 'nil', 'YES', 'NO', 'void', 'id', 'Class',
                           'SEL', 'IMP', 'BOOL', 'NSInteger', 'NSUInteger', 'CGFloat',
                           'IBAction', 'IBOutlet', 'instancetype'):
                continue
            # Skip if already defined as method
            if fn_name in fn_defs:
                continue
            node_id = f"{rel_path}:{i}:{fn_name}"
            ntype = "function"
            if fn_name == "main":
                ntype = "entry_point"
            nodes.append({
                "id": node_id, "type": ntype,
                "name": fn_name, "fn": fn_name,
                "file": rel_path, "line": i, "domain": "backend",
            })
            fn_defs[fn_name] = node_id

    # ─── Method call edges ──────────────────────────────────────────
    _OBJC_KEYWORDS = frozenset({
        'if', 'else', 'while', 'for', 'switch', 'return', 'case', 'break',
        'continue', 'do', 'try', 'catch', 'throw', 'new', 'self', 'super',
        'nil', 'YES', 'NO', 'void', 'id', 'Class', 'SEL', 'IMP', 'BOOL',
        'NSInteger', 'NSUInteger', 'CGFloat', 'NSString', 'NSArray',
        'NSDictionary', 'NSSet', 'NSNumber', 'NSData', 'NSDate',
        'NSObject', 'UIApplication', 'UIViewController', 'UIView',
        'NSLog', 'printf', 'malloc', 'free', 'calloc', 'realloc',
        'CGRectMake', 'CGPointMake', 'CGSizeMake', 'NSMakeRange',
        'IBAction', 'IBOutlet', 'instancetype', 'copy', 'strong',
        'weak', 'assign', 'retain', 'nonatomic', 'atomic', 'readonly',
        'readwrite', 'getter', 'setter', 'nullable', 'nonnull',
        'init', 'dealloc', 'alloc', 'autorelease', 'release', 'retain',
    })

    # Build function→body range map (brace-tracking)
    fn_ranges = []
    current_fn = None
    fn_start = 0
    brace_count = 0

    for i, line in enumerate(lines, 1):
        for node in nodes:
            if (node.get("line") == i and
                node.get("type") in ("instance_method", "class_method", "function",
                                     "entry_point")):
                if current_fn:
                    fn_ranges.append((current_fn, fn_start, i - 1))
                current_fn = node["id"]
                fn_start = i
                brace_count = 0
                break

        if current_fn:
            stripped = line.strip()
            brace_count += stripped.count('{') - stripped.count('}')
            if brace_count <= 0 and i > fn_start:
                fn_ranges.append((current_fn, fn_start, i))
                current_fn = None

    if current_fn:
        fn_ranges.append((current_fn, fn_start, len(lines)))

    # Extract calls from each method body
    # ObjC method calls: [target method:] or [target method:arg name:arg]
    bracket_call = re.compile(r'\[\s*(\w+)\s+([\w:]+)')
    dot_call = re.compile(r'([\w]+)\.([\w]+)\s*\(')
    simple_call = re.compile(r'(?<!\[)(?<!\.)([\w]+)\s*\(')

    for fn_id, start_line, end_line in fn_ranges:
        body = '\n'.join(lines[start_line:end_line])

        # ObjC bracket calls: [obj method]
        for m in bracket_call.finditer(body):
            target = m.group(1)
            method = m.group(2).rstrip(':')
            if target in _OBJC_KEYWORDS or method in _OBJC_KEYWORDS:
                continue
            if method in fn_defs:
                edges.append({
                    "from": fn_id,
                    "to": fn_defs[method],
                    "to_fn": method,
                    "type": "call",
                    "weight": 1,
                })
            else:
                full_name = f"{target}.{method}"
                edges.append({
                    "from": fn_id,
                    "to_fn": full_name,
                    "type": "call",
                    "weight": 1,
                })

        # Dot-notation calls: obj.method()
        for m in dot_call.finditer(body):
            obj = m.group(1)
            method = m.group(2)
            if obj in _OBJC_KEYWORDS or method in _OBJC_KEYWORDS:
                continue
            if method in fn_defs:
                edges.append({
                    "from": fn_id,
                    "to": fn_defs[method],
                    "to_fn": method,
                    "type": "call",
                    "weight": 1,
                })

        # Simple C function calls
        for m in simple_call.finditer(body):
            fn_name = m.group(1)
            if fn_name in _OBJC_KEYWORDS:
                continue
            if fn_name in fn_defs:
                edges.append({
                    "from": fn_id,
                    "to": fn_defs[fn_name],
                    "to_fn": fn_name,
                    "type": "call",
                    "weight": 1,
                })

    return {"nodes": nodes, "edges": edges}
