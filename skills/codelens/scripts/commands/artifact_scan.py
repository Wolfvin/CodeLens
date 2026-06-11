"""Artifact-scan command — Scan for compiled/built artifacts (reverse engineering mode)."""

import os
import json
import struct
from datetime import datetime, timezone
from typing import Dict, List, Any

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


def add_args(parser):
    """Add artifact-scan-specific arguments."""
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--deep", action="store_true",
                        help="Deep scan: attempt to extract symbols from .wasm text format")


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
                    except IOError:
                        pass

                    minified_files.append(entry)
                    matched_min = True
                    break

            if matched_min:
                continue

            # Check for source maps
            if filename_lower.endswith('.map') or filename_lower.endswith('.js.map') or filename_lower.endswith('.css.map'):
                source_maps.append({
                    "path": rel_path,
                    "size_bytes": file_size,
                })

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


def _analyze_wasm(file_path: str, file_size: int, deep: bool = False) -> Dict[str, Any]:
    """Analyze a .wasm file for metadata.
    
    Reads only the WASM header and section headers — never reads the full
    binary content into memory. Uses seek() to skip over section payloads,
    so even a 100MB .wasm file is handled in constant time.
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
                for _ in range(50):
                    section_id_byte = f.read(1)
                    if not section_id_byte:
                        break

                    section_id = section_id_byte[0]
                    section_size = _read_leb128(f)
                    section_name = WASM_SECTION_NAMES.get(section_id, f"unknown_{section_id}")

                    if section_id == 0 and section_size > 0 and section_size < 10000:
                        # Custom section — read the name (first bytes are name_len + name)
                        try:
                            name_len_byte = f.read(1)
                            if name_len_byte:
                                name_len = name_len_byte[0]
                                name = f.read(name_len).decode('utf-8', errors='replace')
                                sections.setdefault("custom", []).append(name)
                                # Skip rest of custom section payload
                                remaining = section_size - 1 - name_len
                                if remaining > 0:
                                    f.seek(remaining, 1)
                                continue
                        except (IOError, ValueError):
                            pass
                    else:
                        sections[section_name] = sections.get(section_name, 0) + 1

                    # Skip section payload using seek (constant time, no memory use)
                    if section_size > 0:
                        f.seek(section_size, 1)

                if sections:
                    info["sections"] = sections

    except (IOError, OSError):
        pass

    return info


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
