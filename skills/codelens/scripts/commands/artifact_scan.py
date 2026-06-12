"""Artifact-scan command — Scan for compiled/built artifacts (reverse engineering mode)."""

import os
import json
import struct
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from utils import logger, DEFAULT_IGNORE_DIRS
from commands import register_command


# Binary file extensions to detect
BINARY_EXTENSIONS = {
    '.wasm': 'wasm_binary',
    '.so': 'shared_library_linux',
    '.dll': 'shared_library_windows',
    '.dylib': 'shared_library_macos',
    '.exe': 'executable_windows',
    '.pyc': 'python_bytecode',
    '.pyd': 'python_extension',
    '.o': 'object_file',
    '.a': 'static_library',
    '.lib': 'static_library_windows',
    '.gch': 'precompiled_header',
    '.pch': 'precompiled_header',
    '.class': 'java_bytecode',
    '.jar': 'java_archive',
    '.nexe': 'nacl_executable',
}

# Minified/built file patterns
MINIFIED_PATTERNS = {
    '.min.js': 'minified_javascript',
    '.min.css': 'minified_css',
    '.bundle.js': 'bundled_javascript',
    '.chunk.js': 'chunked_javascript',
    '.vendor.js': 'vendor_bundle',
    '.runtime.js': 'runtime_bundle',
}

# Source map patterns
SOURCE_MAP_EXTENSIONS = {'.map', '.js.map', '.css.map'}

# Built output directories (where compilers typically output)
BUILT_OUTPUT_DIRS = {
    'dist', 'build', 'out', '.next', '.nuxt', 'bin', 'target',
    'output', 'release', 'pkg', 'compiled', 'bundle',
}

# Max source map file size to parse (5MB)
MAX_SOURCE_MAP_SIZE = 5 * 1024 * 1024


def add_args(parser):
    """Add artifact-scan-specific arguments."""
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--deep", action="store_true",
                        help="Deep scan: parse source maps and extract WASM exports")


def execute(args, workspace):
    """Execute the artifact-scan command."""
    deep = getattr(args, 'deep', False)
    return cmd_artifact_scan(workspace, deep=deep)


def cmd_artifact_scan(workspace: str, deep: bool = False) -> Dict[str, Any]:
    """
    Scan for compiled/built artifacts in the workspace.
    Unlike regular scan which ignores dist/, build/, .min.js etc.,
    this command specifically targets those files for reverse engineering analysis.
    """
    workspace = os.path.abspath(workspace)

    binaries = []
    minified_files = []
    source_maps = []
    built_dirs = set()
    wasm_modules = []

    for root, dirs, filenames in os.walk(workspace):
        rel_root = os.path.relpath(root, workspace)

        # Skip .codelens, .git, node_modules
        skip_dirs = {'.codelens', '.git', 'node_modules', '__pycache__'}
        dirs[:] = [d for d in dirs if d not in skip_dirs]

        # Check if we're in a built output directory
        for part in rel_root.replace('\\', '/').split('/'):
            if part.lower() in BUILT_OUTPUT_DIRS:
                built_dirs.add(rel_root.replace('\\', '/'))
                break

        for filename in filenames:
            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace).replace('\\', '/')

            try:
                file_size = os.path.getsize(file_path)
            except OSError:
                continue

            # Check for binary files
            ext = os.path.splitext(filename)[1].lower()

            if ext in BINARY_EXTENSIONS:
                entry = {
                    "path": rel_path,
                    "size_bytes": file_size,
                    "type": BINARY_EXTENSIONS[ext],
                    "extension": ext,
                }

                # WASM-specific analysis
                if ext == '.wasm':
                    wasm_info = _analyze_wasm(file_path, file_size, deep)
                    entry.update(wasm_info)
                    if wasm_info.get("is_valid_wasm"):
                        wasm_modules.append(entry)

                binaries.append(entry)
                continue

            # Check for minified file patterns (check compound extensions first)
            filename_lower = filename.lower()
            matched_min = False
            for pattern, artifact_type in MINIFIED_PATTERNS.items():
                if filename_lower.endswith(pattern):
                    entry = {
                        "path": rel_path,
                        "size_bytes": file_size,
                        "type": artifact_type,
                        "has_source_map": os.path.exists(file_path + '.map'),
                    }
                    # Try to detect the source file
                    source_path = filename_lower.replace('.min.js', '.js').replace('.min.css', '.css')
                    if source_path != filename_lower:
                        source_candidate = os.path.join(root, source_path)
                        if os.path.exists(source_candidate):
                            entry["source_file"] = os.path.relpath(source_candidate, workspace).replace('\\', '/')
                    
                    # Estimate complexity (lines of code for minified file)
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            lines = content.count('\n') + 1
                            entry["line_count"] = lines
                            entry["avg_line_length"] = len(content) / max(lines, 1)
                            if entry["avg_line_length"] > 500:
                                entry["obfuscation_hint"] = "Very long lines suggest minification or obfuscation"
                            # In deep mode, try to find sourceMappingURL
                            if deep:
                                sourcemap_match = None
                                for line in content.split('\n')[-5:]:  # Check last 5 lines
                                    if 'sourceMappingURL' in line:
                                        import re
                                        sm = re.search(r'sourceMappingURL=(\S+)', line)
                                        if sm:
                                            sourcemap_match = sm.group(1).rstrip('*/').strip()
                                            break
                                if sourcemap_match:
                                    entry["source_mapping_url"] = sourcemap_match
                    except IOError:
                        pass

                    minified_files.append(entry)
                    matched_min = True
                    break

            if matched_min:
                continue

            # Check for source maps
            if filename_lower.endswith('.map') or filename_lower.endswith('.js.map') or filename_lower.endswith('.css.map'):
                sm_entry = {
                    "path": rel_path,
                    "size_bytes": file_size,
                }
                # In deep mode, parse the source map JSON
                if deep and file_size < MAX_SOURCE_MAP_SIZE:
                    parsed = _parse_source_map(file_path)
                    if parsed:
                        sm_entry.update(parsed)
                source_maps.append(sm_entry)

    # Summary
    total_artifacts = len(binaries) + len(minified_files) + len(source_maps)
    
    result = {
        "status": "ok",
        "workspace": workspace,
        "reverse_engineering_mode": True,
        "deep_scan": deep,
        "stats": {
            "total_artifacts": total_artifacts,
            "binaries": len(binaries),
            "minified_files": len(minified_files),
            "source_maps": len(source_maps),
            "wasm_modules": len(wasm_modules),
            "built_output_dirs": len(built_dirs),
        },
        "built_dirs": sorted(built_dirs),
        "binaries": binaries[:100],
        "minified_files": minified_files[:100],
        "source_maps": source_maps[:50],
        "wasm_modules": wasm_modules[:20],
        "recommendations": _generate_recommendations(binaries, minified_files, source_maps, built_dirs),
    }

    # Save to .codelens/artifacts.json
    codelens_dir = os.path.join(workspace, '.codelens')
    os.makedirs(codelens_dir, exist_ok=True)
    artifact_path = os.path.join(codelens_dir, 'artifacts.json')
    with open(artifact_path, 'w', encoding='utf-8') as f:
        json.dump({
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "workspace": workspace,
            "artifacts": result
        }, f, indent=2, ensure_ascii=False)

    return result


def _parse_source_map(file_path: str) -> Optional[Dict[str, Any]]:
    """Parse a source map file and extract key information.
    
    Source maps are JSON files with version, sources, names, and mappings
    that allow reconstructing the original source from minified output.
    """
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            data = json.load(f)
        
        result = {}
        
        # Extract source file references
        sources = data.get('sources', [])
        if sources:
            result["sources"] = sources[:50]  # Cap at 50
            result["source_count"] = len(sources)
        
        # Extract names (original identifiers before minification)
        names = data.get('names', [])
        if names:
            result["names_count"] = len(names)
            result["names_sample"] = names[:20]  # Show first 20 original names
        
        # Source map version
        version = data.get('version', None)
        if version:
            result["version"] = version
        
        # Source root
        source_root = data.get('sourceRoot', None)
        if source_root:
            result["source_root"] = source_root
        
        # Check for x_google_ignoreList (Chrome DevTools feature)
        ignore_list = data.get('x_google_ignoreList', [])
        if ignore_list:
            result["ignored_sources"] = len(ignore_list)
        
        return result
    except (json.JSONDecodeError, IOError, ValueError):
        return None


def _analyze_wasm(file_path: str, file_size: int, deep: bool = False) -> Dict[str, Any]:
    """Analyze a .wasm file for metadata.
    
    Reads only the WASM header and section headers — never reads the full
    binary content into memory. Uses seek() to skip over section payloads,
    so even a 100MB .wasm file is handled in constant time.
    
    In deep mode, also extracts export names from the export section (7)
    and import entries from the import section (2).
    
    Safety guarantees:
    - Capped at 50 section iterations to prevent infinite loops
    - Every seek is bounds-checked against file_size to avoid hang on
      malformed/truncated WASM files
    - Progress check: if the file pointer does not advance between
      iterations, we break immediately
    """
    info = {
        "is_valid_wasm": False,
        "size_bytes": file_size,
    }

    # Well-known WASM section IDs
    WASM_SECTION_NAMES = {
        0: "custom", 1: "type", 2: "import", 3: "function",
        4: "table", 5: "memory", 6: "global", 7: "export",
        8: "start", 9: "element", 10: "code", 11: "data",
        12: "datacount",
    }

    try:
        with open(file_path, 'rb') as f:
            header = f.read(8)

            # Check WASM magic number: \0asm
            if header[:4] == b'\x00asm':
                info["is_valid_wasm"] = True
                version = struct.unpack('<I', header[4:8])[0]
                info["wasm_version"] = version

                # Scan section headers — cap at 50 sections to avoid
                # pathological inputs and guarantee termination
                sections = {}
                export_names = []
                import_entries = []

                for _ in range(50):
                    # Record position before reading section header
                    pos_before = f.tell()
                    
                    section_id_byte = f.read(1)
                    if not section_id_byte:
                        break

                    # EOF check: if we've reached/passed file_size, stop
                    if f.tell() > file_size:
                        break

                    section_id = section_id_byte[0]
                    section_size = _read_leb128(f)
                    section_name = WASM_SECTION_NAMES.get(section_id, f"unknown_{section_id}")

                    # Position at start of section payload
                    payload_start = f.tell()

                    # Bounds check: if section_size claims more bytes than
                    # remain in the file, the WASM is malformed/truncated.
                    # Clamp to remaining bytes to avoid seeking past EOF.
                    bytes_remaining = file_size - payload_start
                    if section_size > bytes_remaining:
                        # Truncated or malformed — still record the section
                        sections[section_name] = sections.get(section_name, 0) + 1
                        info["truncated"] = True
                        break

                    if section_id == 0 and section_size > 0 and section_size < 100000:
                        # Custom section — read the name using LEB128 for proper decoding
                        try:
                            name_len = _read_leb128(f)
                            if 0 < name_len < 10000 and name_len <= section_size:
                                name_bytes = f.read(name_len)
                                if name_bytes:
                                    name = name_bytes.decode('utf-8', errors='replace')
                                    sections.setdefault("custom", []).append(name)
                        except (IOError, ValueError):
                            pass
                        # Skip to end of section
                        section_end = payload_start + section_size
                        f.seek(section_end)
                        continue
                    
                    sections[section_name] = sections.get(section_name, 0) + 1

                    # Deep mode: extract export names from export section (id=7)
                    if deep and section_id == 7 and section_size < 1000000:
                        try:
                            export_names = _read_wasm_exports(f, section_size)
                        except (IOError, ValueError, struct.error):
                            pass
                    
                    # Deep mode: extract import entries from import section (id=2)
                    if deep and section_id == 2 and section_size < 1000000:
                        try:
                            import_entries = _read_wasm_imports(f, section_size)
                        except (IOError, ValueError, struct.error):
                            pass

                    # Skip section payload using seek (constant time, no memory use)
                    section_end = payload_start + section_size
                    f.seek(section_end)

                    # Progress check: if file pointer didn't advance past
                    # pos_before, we're stuck — break immediately.
                    # This prevents infinite loops on malformed WASM where
                    # section_size is 0 and we keep re-reading the same byte.
                    if f.tell() <= pos_before:
                        break

                if sections:
                    info["sections"] = sections
                
                if export_names:
                    info["exports"] = export_names
                    info["export_count"] = len(export_names)
                
                if import_entries:
                    info["imports"] = import_entries
                    info["import_count"] = len(import_entries)

    except (IOError, OSError):
        pass

    return info


def _read_wasm_exports(f, section_size: int) -> List[str]:
    """Read export names from a WASM export section.
    
    Export section format:
    - count (LEB128): number of exports
    - For each export:
      - name_len (LEB128): length of export name
      - name (bytes): export name
      - kind (1 byte): 0=func, 1=table, 2=memory, 3=global
      - index (LEB128): index of the exported item
    """
    names = []
    count = _read_leb128(f)
    # Cap to prevent pathological cases
    count = min(count, 500)
    
    for _ in range(count):
        name_len = _read_leb128(f)
        if name_len > 0 and name_len < 1000:
            name_bytes = f.read(name_len)
            if name_bytes:
                name = name_bytes.decode('utf-8', errors='replace')
                kind = f.read(1)
                index = _read_leb128(f)
                kind_names = {0: 'function', 1: 'table', 2: 'memory', 3: 'global'}
                kind_name = kind_names.get(kind[0] if kind else -1, 'unknown') if kind else 'unknown'
                names.append(f"{name} ({kind_name})")
        else:
            # Skip malformed entry
            break
    
    return names


def _read_wasm_imports(f, section_size: int) -> List[str]:
    """Read import entries from a WASM import section.
    
    Import section format:
    - count (LEB128): number of imports
    - For each import:
      - module_len (LEB128): length of module name
      - module (bytes): module name
      - name_len (LEB128): length of field name
      - name (bytes): field name
      - desc (1 byte + optional LEB128): import descriptor
    """
    imports = []
    count = _read_leb128(f)
    count = min(count, 500)
    
    for _ in range(count):
        module_len = _read_leb128(f)
        if module_len > 0 and module_len < 1000:
            module_name = f.read(module_len).decode('utf-8', errors='replace')
        else:
            break
        
        name_len = _read_leb128(f)
        if name_len > 0 and name_len < 1000:
            field_name = f.read(name_len).decode('utf-8', errors='replace')
        else:
            break
        
        # Read import descriptor kind (1 byte)
        kind_byte = f.read(1)
        if kind_byte:
            kind = kind_byte[0]
            kind_names = {0: 'function', 1: 'table', 2: 'memory', 3: 'global'}
            kind_name = kind_names.get(kind, 'unknown')
            
            # Read remaining descriptor bytes
            if kind == 0:  # function: index (LEB128)
                _read_leb128(f)
            elif kind == 1:  # table: elem_type(1) + limits
                f.read(1)
                _read_limits(f)
            elif kind == 2:  # memory: limits
                _read_limits(f)
            elif kind == 3:  # global: type(1) + mutability(1)
                f.read(2)
            
            imports.append(f"{module_name}.{field_name} ({kind_name})")
        else:
            break
    
    return imports


def _read_limits(f) -> None:
    """Read WASM limits (min+optional max) from import descriptor."""
    flags_byte = f.read(1)
    if flags_byte:
        _read_leb128(f)  # min
        if flags_byte[0] & 1:  # has max
            _read_leb128(f)  # max


def _read_leb128(f) -> int:
    """Read an unsigned LEB128 value from a file."""
    result = 0
    shift = 0
    for _ in range(5):  # Max 5 bytes for 32-bit
        byte = f.read(1)
        if not byte:
            break
        b = byte[0]
        result |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            break
        shift += 7
    return result


def _generate_recommendations(binaries, minified_files, source_maps, built_dirs) -> List[str]:
    """Generate recommendations based on found artifacts."""
    recs = []
    
    if binaries:
        wasm_count = sum(1 for b in binaries if b.get("type") == "wasm_binary")
        if wasm_count:
            recs.append(f"Found {wasm_count} WebAssembly module(s). Use `wasm-objdump` or `wasm2wat` for deeper analysis.")
        so_count = sum(1 for b in binaries if b.get("type") in ('shared_library_linux', 'shared_library_windows', 'shared_library_macos'))
        if so_count:
            recs.append(f"Found {so_count} shared library/libraries. Use `nm` or `objdump` to inspect exported symbols.")
    
    if minified_files:
        without_maps = [m for m in minified_files if not m.get("has_source_map")]
        if without_maps:
            recs.append(f"Found {len(without_maps)} minified file(s) without source maps. Reverse engineering will be harder without .map files.")
        with_sources = [m for m in minified_files if m.get("source_file")]
        if with_sources:
            recs.append(f"Found {len(with_sources)} minified file(s) with corresponding source files. Source mapping is possible.")
    
    if source_maps:
        recs.append(f"Found {len(source_maps)} source map(s). These can be used to reconstruct original source structure.")
    
    if built_dirs:
        recs.append(f"Found {len(built_dirs)} built output directory/directories: {', '.join(sorted(built_dirs)[:5])}. These contain compiled artifacts.")
    
    if not recs:
        recs.append("No compiled artifacts detected. This appears to be a source-only project.")
    
    return recs


register_command("artifact-scan", "Scan for compiled/built artifacts (reverse engineering mode)", add_args, execute)
