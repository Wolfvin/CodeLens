"""Binary artifact scan command for CodeLens.

Merges the former ``artifact-scan`` capabilities (issue #98) so that
``binary-scan`` is now a strict superset of what ``artifact-scan`` used to
do. Nothing the old ``artifact-scan`` returned is lost.

Capabilities (post-#98 merge):
  - Binary detection by known extension (.exe, .dll, .so, .wasm, .pyc, …)
    with descriptive reverse-engineering type labels
    (``wasm_binary``, ``shared_library_linux``, …).
  - Binary detection by MIME signature (ELF, PE, Mach-O, ZIP, GZIP, WASM)
    for extensionless / unknown files — the capability that was unique to
    the pre-#98 ``binary-scan``.
  - Minified / bundled file detection (``.min.js``, ``.bundle.js``, …)
    with ``has_source_map``, ``source_file``, ``line_count``,
    ``avg_line_length``, ``obfuscation_hint`` metadata.
  - Source map detection + (in ``--deep`` mode) JSON parsing that extracts
    ``sources``, ``names``, ``version``, ``sourceRoot`` and
    ``x_google_ignoreList``.
  - Built output directory detection (``dist/``, ``build/``, ``out/``, …).
  - WASM deep analysis (``--deep``): section scan + export/import name
    extraction, with bounds-checked seeking so even a 100 MB module is
    handled in constant time.
  - Tauri / Electron reverse-engineering hook (when the optional
    ``scan_tauri_artifacts`` helper is available).
  - Results persisted to ``.codelens/artifacts.json``.

Backward compatibility:
  - The pre-#98 output keys are all preserved (``findings``,
    ``stats.files_scanned``, ``stats.total_artifacts``,
    ``stats.total_size_bytes``, ``stats.by_category``, ``recommendations``).
  - The pre-#98 CLI argument (positional ``workspace``) is unchanged.
  - ``--deep`` is a new *optional* flag; existing invocations without it
    behave exactly as before.
  - The former ``artifact-scan`` command still works — it now prints a
    deprecation warning and delegates to this handler (see
    ``scripts/commands/artifact_scan.py``).

v5.9: Enhanced with Tauri reverse engineering capabilities:
- Tauri IPC command/handler mapping from Rust source
- Tauri capabilities/permissions security audit
- Sidecar binary analysis
- Updater configuration analysis
- WebView security audit (CSP, asset protocol)
- Deep-link scheme analysis
- Build configuration security analysis
- Electron app detection
"""

import os
import re
import json
import struct
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from commands import register_command
from utils import logger


# ─── Constants (ported from artifact_scan.py, issue #98) ──────────────

# Binary file extensions → descriptive reverse-engineering type label.
# This is the granular typing that the old artifact-scan produced and that
# callers may depend on. (The coarser ``by_category`` grouping uses
# ``_binary_category`` below, preserving the pre-#98 binary-scan shape.)
BINARY_EXTENSIONS: Dict[str, str] = {
    '.wasm': 'wasm_binary',
    '.so': 'shared_library_linux',
    '.dll': 'shared_library_windows',
    '.dylib': 'shared_library_macos',
    '.exe': 'executable_windows',
    '.pyc': 'python_bytecode',
    '.pyo': 'python_bytecode',
    '.pyd': 'python_extension',
    '.o': 'object_file',
    '.obj': 'object_file',
    '.a': 'static_library',
    '.lib': 'static_library_windows',
    '.gch': 'precompiled_header',
    '.pch': 'precompiled_header',
    '.class': 'java_bytecode',
    '.jar': 'java_archive',
    '.nexe': 'nacl_executable',
}

# Minified/built file patterns → descriptive type label.
MINIFIED_PATTERNS: Dict[str, str] = {
    '.min.js': 'minified_javascript',
    '.min.css': 'minified_css',
    '.bundle.js': 'bundled_javascript',
    '.chunk.js': 'chunked_javascript',
    '.vendor.js': 'vendor_bundle',
    '.runtime.js': 'runtime_bundle',
}

# Built output directories (where compilers typically emit artifacts).
# Reverse-engineering mode intentionally scans INTO these — unlike a normal
# scan which skips them.
BUILT_OUTPUT_DIRS = {
    'dist', 'build', 'out', '.next', '.nuxt', 'bin', 'target',
    'output', 'release', 'pkg', 'compiled', 'bundle',
}

# Max source map file size to parse (5 MB).
MAX_SOURCE_MAP_SIZE = 5 * 1024 * 1024

# Directories that even reverse-engineering mode must never descend into
# (VCS internals, dependency trees, caches).
_RE_SKIP_DIRS = {'.codelens', '.git', 'node_modules', '__pycache__'}

# Well-known WASM section IDs.
_WASM_SECTION_NAMES = {
    0: "custom", 1: "type", 2: "import", 3: "function",
    4: "table", 5: "memory", 6: "global", 7: "export",
    8: "start", 9: "element", 10: "code", 11: "data",
    12: "datacount",
}

# MIME magic signatures for extensionless binary detection
# (preserved from the pre-#98 binary-scan via utils.BINARY_MIME_SIGNATURES).
# Imported lazily so this module stays importable even if utils is partial.
_BINARY_MIME_SIGNATURES: Dict[bytes, str] = {
    b'\x7fELF': 'elf_binary',
    b'MZ': 'pe_binary',
    b'\xfe\xed\xfa': 'macho_binary',
    b'\xcf\xfa\xed\xfe': 'macho_binary',
    b'\xce\xfa\xed\xfe': 'macho_binary',
    b'PK\x03\x04': 'zip_archive',
    b'\x1f\x8b': 'gzip_archive',
    b'BZh': 'bzip2_archive',
    b'\xfd7zXZ': 'xz_archive',
    b'\x89PNG': 'png_image',
    b'\xff\xd8\xff': 'jpeg_image',
    b'GIF8': 'gif_image',
    b'RIFF': 'riff_media',
    b'\x00asm': 'wasm_binary',
}

# Source extensions that should never be probed by MIME signature
# (avoids false positives on text files with a binary-ish first byte).
_SOURCE_EXTENSIONS = {
    '.py', '.js', '.ts', '.tsx', '.jsx', '.rs', '.html',
    '.css', '.vue', '.svelte', '.json', '.md', '.yaml', '.yml',
    '.toml', '.cfg', '.ini', '.txt', '.sh', '.bash', '.zsh',
    '.gitignore', '.env', '.lock', '.map', '.d.ts',
}


def add_args(parser):
    """Register binary-scan CLI arguments.

    ``workspace`` is unchanged from pre-#98 (positional, optional,
    auto-detected). ``--deep`` is new in #98 — it is optional and only
    enables enhanced reverse-engineering analysis (source-map JSON parsing,
    WASM export/import extraction, sourceMappingURL discovery). Existing
    invocations without ``--deep`` behave exactly as before.
    """
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Workspace path (auto-detected if omitted)")
    parser.add_argument("--deep", action="store_true",
                        help="Deep scan: parse source maps and extract WASM exports/imports")


def execute(args, workspace):
    """Scan workspace for binary/compiled artifacts with RE analysis."""
    deep = getattr(args, 'deep', False)
    return cmd_binary_scan(workspace, deep=deep)


def cmd_binary_scan(workspace: str, deep: bool = False) -> Dict[str, Any]:
    """Run the merged binary + artifact reverse-engineering scan.

    This is a strict superset of the former ``artifact-scan`` output. The
    pre-#98 ``binary-scan`` keys (``findings``, ``stats.files_scanned``,
    ``stats.total_artifacts``, ``stats.total_size_bytes``,
    ``stats.by_category``, ``recommendations``) are all preserved; the
    artifact-scan keys (``binaries``, ``minified_files``, ``source_maps``,
    ``wasm_modules``, ``built_dirs``, ``reverse_engineering_mode``,
    ``deep_scan``) are added alongside them.
    """
    workspace = os.path.abspath(workspace)

    findings: List[Dict[str, Any]] = []
    binaries: List[Dict[str, Any]] = []
    minified_files: List[Dict[str, Any]] = []
    source_maps: List[Dict[str, Any]] = []
    wasm_modules: List[Dict[str, Any]] = []
    built_dirs = set()
    by_category: Dict[str, int] = {}
    files_scanned = 0

    for root, dirs, filenames in os.walk(workspace):
        rel_root = os.path.relpath(root, workspace)

        # Even in RE mode we never descend into VCS / deps / caches.
        dirs[:] = [d for d in dirs if d not in _RE_SKIP_DIRS]

        # Track built output directories we descend into.
        for part in rel_root.replace('\\', '/').split('/'):
            if part.lower() in BUILT_OUTPUT_DIRS:
                built_dirs.add(rel_root.replace('\\', '/'))
                break

        for filename in filenames:
            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace).replace('\\', '/')
            files_scanned += 1

            try:
                file_size = os.path.getsize(file_path)
            except OSError:
                continue

            ext = os.path.splitext(filename)[1].lower()
            filename_lower = filename.lower()

            # ── 1. Known binary extension ──────────────────────────
            if ext in BINARY_EXTENSIONS:
                re_type = BINARY_EXTENSIONS[ext]
                category = _binary_category(ext)
                entry = {
                    "path": rel_path,
                    "size_bytes": file_size,
                    "type": re_type,
                    "extension": ext,
                }
                # WASM deep analysis
                if ext == '.wasm':
                    wasm_info = _analyze_wasm(file_path, file_size, deep)
                    entry.update(wasm_info)
                    if wasm_info.get("is_valid_wasm"):
                        wasm_modules.append(entry)

                binaries.append(entry)

                # binary-scan-style finding (preserves pre-#98 shape)
                findings.append({
                    "path": rel_path,
                    "category": category,
                    "extension": ext,
                    "size_bytes": file_size,
                    "detection_method": "extension",
                    "type": re_type,
                })
                by_category[category] = by_category.get(category, 0) + 1
                continue

            # ── 2. Minified / bundled file patterns ────────────────
            matched_min = False
            for pattern, artifact_type in MINIFIED_PATTERNS.items():
                if filename_lower.endswith(pattern):
                    m_entry = {
                        "path": rel_path,
                        "size_bytes": file_size,
                        "type": artifact_type,
                        "has_source_map": os.path.exists(file_path + '.map'),
                    }
                    # Try to detect the unminified source file.
                    source_path = filename_lower.replace('.min.js', '.js').replace('.min.css', '.css')
                    if source_path != filename_lower:
                        source_candidate = os.path.join(root, source_path)
                        if os.path.exists(source_candidate):
                            m_entry["source_file"] = os.path.relpath(
                                source_candidate, workspace).replace('\\', '/')

                    # Estimate complexity / obfuscation hint.
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            lines = content.count('\n') + 1
                            m_entry["line_count"] = lines
                            m_entry["avg_line_length"] = len(content) / max(lines, 1)
                            if m_entry["avg_line_length"] > 500:
                                m_entry["obfuscation_hint"] = (
                                    "Very long lines suggest minification or obfuscation"
                                )
                            # Deep mode: find sourceMappingURL in last 5 lines.
                            if deep:
                                for line in content.split('\n')[-5:]:
                                    if 'sourceMappingURL' in line:
                                        sm = re.search(r'sourceMappingURL=(\S+)', line)
                                        if sm:
                                            m_entry["source_mapping_url"] = (
                                                sm.group(1).rstrip('*/').strip()
                                            )
                                            break
                    except IOError:
                        pass

                    minified_files.append(m_entry)
                    findings.append({
                        "path": rel_path,
                        "category": "minified_file",
                        "extension": ext,
                        "size_bytes": file_size,
                        "detection_method": "pattern",
                        "type": artifact_type,
                    })
                    by_category["minified_file"] = by_category.get("minified_file", 0) + 1
                    matched_min = True
                    break

            if matched_min:
                continue

            # ── 3. Source maps ──────────────────────────────────────
            if (filename_lower.endswith('.map')
                    or filename_lower.endswith('.js.map')
                    or filename_lower.endswith('.css.map')):
                sm_entry = {
                    "path": rel_path,
                    "size_bytes": file_size,
                }
                if deep and file_size < MAX_SOURCE_MAP_SIZE:
                    parsed = _parse_source_map(file_path)
                    if parsed:
                        sm_entry.update(parsed)
                source_maps.append(sm_entry)
                findings.append({
                    "path": rel_path,
                    "category": "source_map",
                    "extension": ext,
                    "size_bytes": file_size,
                    "detection_method": "extension",
                })
                by_category["source_map"] = by_category.get("source_map", 0) + 1
                continue

            # ── 4. MIME signature detection (pre-#98 binary-scan) ───
            # Probe files that are not known source types for binary magic
            # bytes. This catches extensionless binaries (e.g. a Linux
            # `python` executable with no extension) and is the capability
            # that was unique to the old binary-scan.
            if ext not in _SOURCE_EXTENSIONS:
                sig = _read_file_signature(file_path)
                if sig:
                    sig_type = _identify_signature(sig)
                    if sig_type:
                        findings.append({
                            "path": rel_path,
                            "category": sig_type,
                            "extension": ext,
                            "size_bytes": file_size,
                            "detection_method": "signature",
                        })
                        by_category[sig_type] = by_category.get(sig_type, 0) + 1

    # ─── Aggregate stats ───────────────────────────────────────────
    total_artifacts = len(findings)
    total_size = sum(f.get("size_bytes", 0) for f in findings)

    # ─── Recommendations (merged from both legacy commands) ────────
    recommendations = _generate_recommendations(
        binaries, minified_files, source_maps, built_dirs, by_category, total_size
    )

    result: Dict[str, Any] = {
        "status": "ok",
        "workspace": workspace,
        "reverse_engineering_mode": True,
        "deep_scan": deep,
        "stats": {
            # pre-#98 binary-scan keys (preserved)
            "files_scanned": files_scanned,
            "total_artifacts": total_artifacts,
            "total_size_bytes": total_size,
            "by_category": by_category,
            # artifact-scan keys (added in #98)
            "binaries": len(binaries),
            "minified_files": len(minified_files),
            "source_maps": len(source_maps),
            "wasm_modules": len(wasm_modules),
            "built_output_dirs": len(built_dirs),
        },
        # pre-#98 binary-scan key (preserved)
        "findings": findings[:50],
        # artifact-scan keys (added in #98)
        "built_dirs": sorted(built_dirs),
        "binaries": binaries[:100],
        "minified_files": minified_files[:100],
        "source_maps": source_maps[:50],
        "wasm_modules": wasm_modules[:20],
        "recommendations": recommendations,
    }

    # ─── Tauri / Electron analysis (optional, pre-#98 hook) ────────
    try:
        from utils import scan_tauri_artifacts  # type: ignore
        tauri_result = scan_tauri_artifacts(workspace)
        if tauri_result:
            result["tauri_analysis"] = tauri_result
    except ImportError:
        # scan_tauri_artifacts not available — skip Tauri analysis
        pass

    # ─── Persist to .codelens/artifacts.json (ported from artifact-scan)
    try:
        codelens_dir = os.path.join(workspace, '.codelens')
        os.makedirs(codelens_dir, exist_ok=True)
        artifact_path = os.path.join(codelens_dir, 'artifacts.json')
        with open(artifact_path, 'w', encoding='utf-8') as f:
            json.dump({
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "workspace": workspace,
                "artifacts": result,
            }, f, indent=2, ensure_ascii=False)
    except (IOError, OSError):
        logger.warning("Failed to write .codelens/artifacts.json", exc_info=True)

    return result


# ─── Categorisation helper (pre-#98 binary-scan semantics) ────────────

def _binary_category(ext: str) -> str:
    """Map a binary extension to the coarse pre-#98 ``by_category`` bucket.

    Kept identical to ``utils._binary_category`` so ``stats.by_category``
    stays backward-compatible with callers that parsed the old binary-scan
    output.
    """
    if ext in {'.exe', '.dll', '.so', '.dylib', '.a', '.lib', '.o', '.obj',
               '.bundle', '.ko', '.wasm'}:
        return "compiled_binary"
    if ext in {'.pyc', '.pyo', '.class'}:
        return "python_bytecode"
    if ext in {'.jar', '.war', '.nupkg', '.whl', '.egg'}:
        return "package_archive"
    if ext in {'.tar.gz', '.zip', '.7z', '.gz', '.rpm', '.deb', '.msi', '.dmg', '.pkg'}:
        return "archive"
    if ext in {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.svg', '.bmp'}:
        return "image"
    return "other_binary"


# ─── MIME signature helpers (mirror utils._read_file_signature / _identify_signature)

def _read_file_signature(file_path: str) -> Optional[bytes]:
    """Read the first 16 bytes of a file for magic-byte detection."""
    try:
        fsize = os.path.getsize(file_path)
        if fsize == 0 or fsize > 100 * 1024 * 1024:  # skip empty or >100 MB
            return None
        with open(file_path, 'rb') as f:
            return f.read(16)
    except (IOError, OSError):
        return None


def _identify_signature(sig: bytes) -> Optional[str]:
    """Identify a file type from its binary magic signature."""
    for magic, file_type in _BINARY_MIME_SIGNATURES.items():
        if sig.startswith(magic):
            return file_type
    return None


# ─── WASM analysis helpers (ported verbatim from artifact_scan.py) ────

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
                sections: Dict[str, Any] = {}
                export_names: List[str] = []
                import_entries: List[str] = []

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
                    section_name = _WASM_SECTION_NAMES.get(section_id, f"unknown_{section_id}")

                    # Position at start of section payload
                    payload_start = f.tell()

                    # Bounds check: if section_size claims more bytes than
                    # remain in the file, the WASM is malformed/truncated.
                    # Clamp to remaining bytes to avoid seeking past EOF.
                    bytes_remaining = file_size - payload_start
                    if section_size > bytes_remaining:
                        # Truncated or malformed — still record the section
                        current = sections.get(section_name, 0)
                        if isinstance(current, list):
                            sections[f"{section_name}_count"] = sections.get(
                                f"{section_name}_count", len(current)) + 1
                        else:
                            sections[section_name] = current + 1
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
                                    # Ensure "custom" is a list, not an int
                                    if "custom" not in sections or not isinstance(sections["custom"], list):
                                        sections["custom"] = []
                                    sections["custom"].append(name)
                        except (IOError, ValueError):
                            pass
                        # Skip to end of section
                        section_end = payload_start + section_size
                        f.seek(section_end)
                        continue

                    # If this section key is already a list (e.g., "custom" with names),
                    # increment a separate counter instead of overwriting
                    current = sections.get(section_name, 0)
                    if isinstance(current, list):
                        sections[f"{section_name}_count"] = sections.get(
                            f"{section_name}_count", len(current)) + 1
                    else:
                        sections[section_name] = current + 1

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
    names: List[str] = []
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
    imports: List[str] = []
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


# ─── Source map parser (ported verbatim from artifact_scan.py) ────────

def _parse_source_map(file_path: str) -> Optional[Dict[str, Any]]:
    """Parse a source map file and extract key information.

    Source maps are JSON files with version, sources, names, and mappings
    that allow reconstructing the original source from minified output.
    """
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            data = json.load(f)

        result: Dict[str, Any] = {}

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


# ─── Recommendations (merged from both legacy commands) ───────────────

def _generate_recommendations(
    binaries: List[Dict[str, Any]],
    minified_files: List[Dict[str, Any]],
    source_maps: List[Dict[str, Any]],
    built_dirs: set,
    by_category: Dict[str, int],
    total_size: int,
) -> List[str]:
    """Generate recommendations, merging the pre-#98 binary-scan advice
    with the artifact-scan reverse-engineering advice.
    """
    recs: List[str] = []

    # ── artifact-scan (reverse-engineering) recommendations ──────
    if binaries:
        wasm_count = sum(1 for b in binaries if b.get("type") == "wasm_binary")
        if wasm_count:
            recs.append(
                f"Found {wasm_count} WebAssembly module(s). Use `wasm-objdump` or "
                f"`wasm2wat` for deeper analysis."
            )
        so_count = sum(
            1 for b in binaries
            if b.get("type") in ('shared_library_linux', 'shared_library_windows', 'shared_library_macos')
        )
        if so_count:
            recs.append(
                f"Found {so_count} shared library/libraries. Use `nm` or `objdump` to "
                f"inspect exported symbols."
            )

    if minified_files:
        without_maps = [m for m in minified_files if not m.get("has_source_map")]
        if without_maps:
            recs.append(
                f"Found {len(without_maps)} minified file(s) without source maps. "
                f"Reverse engineering will be harder without .map files."
            )
        with_sources = [m for m in minified_files if m.get("source_file")]
        if with_sources:
            recs.append(
                f"Found {len(with_sources)} minified file(s) with corresponding source "
                f"files. Source mapping is possible."
            )

    if source_maps:
        recs.append(
            f"Found {len(source_maps)} source map(s). These can be used to reconstruct "
            f"original source structure."
        )

    if built_dirs:
        recs.append(
            f"Found {len(built_dirs)} built output directory/directories: "
            f"{', '.join(sorted(built_dirs)[:5])}. These contain compiled artifacts."
        )

    # ── pre-#98 binary-scan recommendations ──────────────────────
    if by_category.get("compiled_binary", 0) > 0:
        recs.append(
            "Found compiled binaries in the workspace. Consider adding them to "
            ".gitignore and using a build pipeline instead."
        )
    if by_category.get("python_bytecode", 0) > 0:
        recs.append(
            "Found Python bytecode files (.pyc/.pyo). Add '**/__pycache__/' and "
            "'*.pyc' to .gitignore."
        )
    if by_category.get("archive", 0) > 5:
        recs.append(
            "Found many archive files. Consider storing large assets externally "
            "(S3, CDN) instead of in the repository."
        )
    if by_category.get("image", 0) > 10:
        recs.append(
            "Found many image files. Consider optimizing or moving to an asset CDN "
            "to reduce repo size."
        )
    if total_size > 50 * 1024 * 1024:
        recs.append(
            f"Binary artifacts total {total_size / (1024 * 1024):.1f}MB. Consider "
            f"using Git LFS for large files."
        )

    if not recs:
        recs.append("No compiled artifacts detected. This appears to be a source-only project.")

    return recs


register_command(
    "binary-scan",
    "Scan for binary/compiled artifacts with reverse-engineering analysis (superset of artifact-scan)",
    add_args,
    execute
)
