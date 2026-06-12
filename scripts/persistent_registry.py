"""
Persistent Registry for CodeLens — SQLite-backed storage with incremental scanning.

Design Goals:
- O(1) symbol lookup via SQLite indexes (vs O(n) JSON scan)
- True incremental (delta) scanning: only re-scan changed files
- Analysis result caching keyed by (command, file_set_hash)
- Graceful fallback to JSON mode if SQLite is unavailable
- Automatic migration from existing .codelens/ JSON files

Schema:
- symbols: name, kind, file_path, line_start, line_end, language, signature, hash
- refs: source_symbol, target_symbol, reference_type
- files: file_path, language, last_modified, content_hash, last_scanned
- analysis_cache: command, file_path, result_hash, result_json, timestamp
- scan_metadata: workspace, scan_timestamp, total_files, version

v1.0: Initial implementation for feature/persistent-registry
"""

import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from utils import logger


# ─── Schema Version ────────────────────────────────────────────

SCHEMA_VERSION = 1
DB_FILENAME = "codelens.db"

# ─── SQL Statements ────────────────────────────────────────────

_CREATE_SYMBOLS = """
CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'function',
    file_path TEXT NOT NULL,
    line_start INTEGER,
    line_end INTEGER,
    language TEXT,
    signature TEXT,
    hash TEXT,
    extra_json TEXT
)
"""

_CREATE_REFS = """
CREATE TABLE IF NOT EXISTS refs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_symbol TEXT NOT NULL,
    target_symbol TEXT NOT NULL,
    reference_type TEXT NOT NULL DEFAULT 'call',
    source_file TEXT,
    extra_json TEXT
)
"""

_CREATE_FILES = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,
    language TEXT,
    last_modified REAL NOT NULL DEFAULT 0,
    content_hash TEXT,
    last_scanned REAL NOT NULL DEFAULT 0
)
"""

_CREATE_ANALYSIS_CACHE = """
CREATE TABLE IF NOT EXISTS analysis_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command TEXT NOT NULL,
    file_set_hash TEXT NOT NULL,
    result_hash TEXT NOT NULL,
    result_json TEXT NOT NULL,
    timestamp REAL NOT NULL DEFAULT 0
)
"""

_CREATE_SCAN_METADATA = """
CREATE TABLE IF NOT EXISTS scan_metadata (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    workspace TEXT,
    scan_timestamp REAL NOT NULL DEFAULT 0,
    total_files INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 1
)
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name)",
    "CREATE INDEX IF NOT EXISTS idx_symbols_file_path ON symbols(file_path)",
    "CREATE INDEX IF NOT EXISTS idx_symbols_kind ON symbols(kind)",
    "CREATE INDEX IF NOT EXISTS idx_symbols_name_kind ON symbols(name, kind)",
    "CREATE INDEX IF NOT EXISTS idx_files_content_hash ON files(content_hash)",
    "CREATE INDEX IF NOT EXISTS idx_files_last_modified ON files(last_modified)",
    "CREATE INDEX IF NOT EXISTS idx_files_file_path ON files(file_path)",
    "CREATE INDEX IF NOT EXISTS idx_refs_source ON refs(source_symbol)",
    "CREATE INDEX IF NOT EXISTS idx_refs_target ON refs(target_symbol)",
    "CREATE INDEX IF NOT EXISTS idx_analysis_cache_command ON analysis_cache(command)",
    "CREATE INDEX IF NOT EXISTS idx_analysis_cache_file_set ON analysis_cache(file_set_hash)",
]


class PersistentRegistry:
    """SQLite-backed persistent registry for CodeLens.

    Provides:
    - Fast O(1) symbol lookups via indexed queries
    - Delta scanning via content_hash and last_modified comparison
    - Analysis result caching with automatic invalidation
    - Transaction-based batch operations for performance
    """

    def __init__(self, workspace: str, db_path: Optional[str] = None):
        """Initialize the persistent registry.

        Args:
            workspace: Absolute path to the workspace root
            db_path: Optional custom path for the SQLite database.
                     Defaults to .codelens/codelens.db
        """
        self.workspace = workspace
        self._db_path = db_path or os.path.join(
            workspace, ".codelens", DB_FILENAME
        )
        self._conn: Optional[sqlite3.Connection] = None
        self._initialized = False

    # ─── Connection Management ──────────────────────────────

    @property
    def db_path(self) -> str:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        """Get or create a database connection."""
        if self._conn is None:
            os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
            self._conn = sqlite3.connect(self._db_path, timeout=10.0)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
            self._conn.execute("PRAGMA temp_store=MEMORY")
        if not self._initialized:
            self._init_schema()
            self._initialized = True
        return self._conn

    def _init_schema(self) -> None:
        """Initialize the database schema."""
        conn = self._connect_raw()
        try:
            conn.executescript(_CREATE_SYMBOLS)
            conn.executescript(_CREATE_REFS)
            conn.executescript(_CREATE_FILES)
            conn.executescript(_CREATE_ANALYSIS_CACHE)
            conn.executescript(_CREATE_SCAN_METADATA)
            for idx_sql in _CREATE_INDEXES:
                conn.execute(idx_sql)
            conn.commit()
        except sqlite3.Error as e:
            logger.warning(f"Schema init error: {e}")

    def _connect_raw(self) -> sqlite3.Connection:
        """Get raw connection without auto-init (for init itself)."""
        if self._conn is None:
            os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
            self._conn = sqlite3.connect(self._db_path, timeout=10.0)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA cache_size=-64000")
            self._conn.execute("PRAGMA temp_store=MEMORY")
        return self._conn

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
            self._initialized = False

    def __enter__(self):
        self._connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ─── Schema Introspection ───────────────────────────────

    def schema_exists(self) -> bool:
        """Check if the database has the expected schema tables."""
        if not os.path.exists(self._db_path):
            return False
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='symbols'"
            )
            result = cursor.fetchone()
            conn.close()
            return result is not None
        except sqlite3.Error:
            return False

    # ─── File Tracking & Delta Detection ────────────────────

    @staticmethod
    def compute_content_hash(file_path: str) -> str:
        """Compute SHA256 hash of file content."""
        h = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
        except (IOError, OSError):
            return ""
        return h.hexdigest()

    def get_file_info(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Get stored file info by path. Returns dict or None."""
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM files WHERE file_path = ?", (file_path,)
        ).fetchone()
        if row:
            return dict(row)
        return None

    def detect_changed_files(
        self, all_files: List[str]
    ) -> Tuple[List[str], List[str], List[str]]:
        """Detect changed, new, and deleted files compared to the DB.

        Uses both mtime (fast) and content_hash (accurate) for detection.

        Args:
            all_files: List of absolute file paths currently in the workspace

        Returns:
            Tuple of (changed_files, new_files, deleted_files) as absolute paths
        """
        conn = self._connect()

        # Get all known files from DB
        db_rows = conn.execute("SELECT file_path, last_modified, content_hash FROM files").fetchall()
        db_files = {}
        for row in db_rows:
            rel_path = row["file_path"]
            db_files[rel_path] = {
                "last_modified": row["last_modified"],
                "content_hash": row["content_hash"],
            }

        current_files = {}
        for abs_path in all_files:
            rel_path = os.path.relpath(abs_path, self.workspace)
            try:
                mtime = os.path.getmtime(abs_path)
            except OSError:
                continue
            current_files[rel_path] = abs_path

        current_rel_paths = set(current_files.keys())
        db_rel_paths = set(db_files.keys())

        # New files: in current but not in DB
        new_files = []
        for rel_path in current_rel_paths - db_rel_paths:
            new_files.append(current_files[rel_path])

        # Deleted files: in DB but not in current
        deleted_files = list(db_rel_paths - current_rel_paths)

        # Changed files: in both, but mtime or content_hash differs
        changed_files = []
        for rel_path in current_rel_paths & db_rel_paths:
            abs_path = current_files[rel_path]
            db_info = db_files[rel_path]
            try:
                current_mtime = os.path.getmtime(abs_path)
            except OSError:
                continue

            # Fast check: mtime unchanged → file unchanged
            if abs(current_mtime - db_info["last_modified"]) < 0.001:
                continue

            # Mtime changed → verify with content hash
            current_hash = self.compute_content_hash(abs_path)
            if current_hash != db_info["content_hash"]:
                changed_files.append(abs_path)

        return changed_files, new_files, deleted_files

    def upsert_file(self, file_path: str, language: str = None) -> None:
        """Insert or update a file entry in the DB."""
        conn = self._connect()
        abs_path = os.path.join(self.workspace, file_path) if not os.path.isabs(file_path) else file_path
        rel_path = os.path.relpath(abs_path, self.workspace)

        try:
            mtime = os.path.getmtime(abs_path)
            content_hash = self.compute_content_hash(abs_path)
        except OSError:
            mtime = 0
            content_hash = ""

        now = time.time()
        conn.execute(
            """INSERT INTO files (file_path, language, last_modified, content_hash, last_scanned)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(file_path) DO UPDATE SET
                   language = excluded.language,
                   last_modified = excluded.last_modified,
                   content_hash = excluded.content_hash,
                   last_scanned = excluded.last_scanned
            """,
            (rel_path, language, mtime, content_hash, now),
        )
        conn.commit()

    def upsert_files_batch(self, file_entries: List[Dict[str, Any]]) -> None:
        """Batch insert/update file entries using a transaction.

        Args:
            file_entries: List of dicts with keys: file_path, language
        """
        conn = self._connect()
        now = time.time()
        rows = []
        for entry in file_entries:
            file_path = entry["file_path"]
            abs_path = os.path.join(self.workspace, file_path) if not os.path.isabs(file_path) else file_path
            rel_path = os.path.relpath(abs_path, self.workspace)
            language = entry.get("language", "")

            try:
                mtime = os.path.getmtime(abs_path)
                content_hash = self.compute_content_hash(abs_path)
            except OSError:
                mtime = 0
                content_hash = ""

            rows.append((rel_path, language, mtime, content_hash, now))

        conn.executemany(
            """INSERT INTO files (file_path, language, last_modified, content_hash, last_scanned)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(file_path) DO UPDATE SET
                   language = excluded.language,
                   last_modified = excluded.last_modified,
                   content_hash = excluded.content_hash,
                   last_scanned = excluded.last_scanned
            """,
            rows,
        )
        conn.commit()

    def delete_files(self, rel_paths: List[str]) -> None:
        """Delete file entries and associated symbols from the DB."""
        conn = self._connect()
        for rel_path in rel_paths:
            conn.execute("DELETE FROM symbols WHERE file_path = ?", (rel_path,))
            conn.execute("DELETE FROM refs WHERE source_file = ?", (rel_path,))
            conn.execute("DELETE FROM files WHERE file_path = ?", (rel_path,))
        conn.commit()

    def delete_changed_file_data(self, rel_paths: List[str]) -> None:
        """Delete data associated with changed files (for delta re-scan)."""
        self.delete_files(rel_paths)

    # ─── Symbol Operations ──────────────────────────────────

    def insert_symbols_batch(self, symbols: List[Dict[str, Any]]) -> None:
        """Batch insert symbol entries using a transaction."""
        if not symbols:
            return
        conn = self._connect()
        rows = []
        for sym in symbols:
            rows.append((
                sym.get("name", ""),
                sym.get("kind", "function"),
                sym.get("file_path", ""),
                sym.get("line_start"),
                sym.get("line_end"),
                sym.get("language", ""),
                sym.get("signature", ""),
                sym.get("hash", ""),
                sym.get("extra_json", ""),
            ))
        conn.executemany(
            """INSERT INTO symbols (name, kind, file_path, line_start, line_end,
               language, signature, hash, extra_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()

    def lookup_symbol(self, name: str, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        """Look up symbols by name (and optionally kind). O(1) via index."""
        conn = self._connect()
        if kind:
            rows = conn.execute(
                "SELECT * FROM symbols WHERE name = ? AND kind = ?",
                (name, kind),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM symbols WHERE name = ?",
                (name,),
            ).fetchall()
        return [dict(r) for r in rows]

    def lookup_symbols_by_file(self, file_path: str) -> List[Dict[str, Any]]:
        """Look up all symbols in a specific file. O(1) via index."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM symbols WHERE file_path = ?",
            (file_path,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_symbols(self, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all symbols, optionally filtered by kind."""
        conn = self._connect()
        if kind:
            rows = conn.execute(
                "SELECT * FROM symbols WHERE kind = ?", (kind,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM symbols").fetchall()
        return [dict(r) for r in rows]

    def delete_symbols_for_file(self, file_path: str) -> int:
        """Delete all symbols associated with a file. Returns count deleted."""
        conn = self._connect()
        cursor = conn.execute(
            "DELETE FROM symbols WHERE file_path = ?", (file_path,)
        )
        conn.commit()
        return cursor.rowcount

    # ─── Reference Operations ───────────────────────────────

    def insert_references_batch(self, references: List[Dict[str, Any]]) -> None:
        """Batch insert reference entries using a transaction."""
        if not references:
            return
        conn = self._connect()
        rows = []
        for ref in references:
            rows.append((
                ref.get("source_symbol", ""),
                ref.get("target_symbol", ""),
                ref.get("reference_type", "call"),
                ref.get("source_file", ""),
                ref.get("extra_json", ""),
            ))
        conn.executemany(
            """INSERT INTO refs (source_symbol, target_symbol, reference_type,
               source_file, extra_json)
               VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()

    def lookup_references_to(self, symbol_name: str) -> List[Dict[str, Any]]:
        """Find all references pointing TO a symbol. O(1) via index."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM refs WHERE target_symbol = ?",
            (symbol_name,),
        ).fetchall()
        return [dict(r) for r in rows]

    def lookup_references_from(self, symbol_name: str) -> List[Dict[str, Any]]:
        """Find all references FROM a symbol. O(1) via index."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM refs WHERE source_symbol = ?",
            (symbol_name,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ─── Analysis Cache ─────────────────────────────────────

    def _compute_file_set_hash(self, file_paths: List[str]) -> str:
        """Compute a hash representing a set of files and their content hashes."""
        conn = self._connect()
        if not file_paths:
            return ""

        placeholders = ",".join("?" * len(file_paths))
        rows = conn.execute(
            f"SELECT file_path, content_hash FROM files WHERE file_path IN ({placeholders})",
            file_paths,
        ).fetchall()

        entries = sorted([(r["file_path"], r["content_hash"]) for r in rows])
        combined = "|".join(f"{fp}:{ch}" for fp, ch in entries)
        return hashlib.sha256(combined.encode()).hexdigest()

    def get_cached_result(
        self, command: str, file_paths: List[str]
    ) -> Optional[Dict[str, Any]]:
        """Try to retrieve a cached analysis result."""
        file_set_hash = self._compute_file_set_hash(file_paths)
        if not file_set_hash:
            return None

        conn = self._connect()
        row = conn.execute(
            """SELECT result_json FROM analysis_cache
               WHERE command = ? AND file_set_hash = ?
               ORDER BY timestamp DESC LIMIT 1
            """,
            (command, file_set_hash),
        ).fetchone()

        if row:
            try:
                return json.loads(row["result_json"])
            except (json.JSONDecodeError, TypeError):
                return None
        return None

    def set_cached_result(
        self,
        command: str,
        file_paths: List[str],
        result: Dict[str, Any],
    ) -> None:
        """Store an analysis result in the cache."""
        file_set_hash = self._compute_file_set_hash(file_paths)
        if not file_set_hash:
            return

        result_json = json.dumps(result, ensure_ascii=False, default=str)
        result_hash = hashlib.sha256(result_json.encode()).hexdigest()
        now = time.time()

        conn = self._connect()
        conn.execute(
            """INSERT INTO analysis_cache (command, file_set_hash, result_hash, result_json, timestamp)
               VALUES (?, ?, ?, ?, ?)
            """,
            (command, file_set_hash, result_hash, result_json, now),
        )
        conn.commit()

    def invalidate_cache(self, file_path: Optional[str] = None) -> int:
        """Invalidate cached analysis results. Returns count removed."""
        conn = self._connect()
        cursor = conn.execute("DELETE FROM analysis_cache")
        conn.commit()
        return cursor.rowcount

    def invalidate_cache_for_files(self, rel_paths: List[str]) -> int:
        """Invalidate cache entries affected by changed files.

        Conservative approach: invalidate all cached results when any file
        changes. This is correct (no stale results) and still fast
        (cache hits are instant when nothing changed).
        """
        if not rel_paths:
            return 0
        return self.invalidate_cache()

    # ─── Scan Metadata ──────────────────────────────────────

    def update_scan_metadata(self, total_files: int) -> None:
        """Update the scan metadata after a scan."""
        conn = self._connect()
        now = time.time()
        conn.execute(
            """INSERT INTO scan_metadata (id, workspace, scan_timestamp, total_files, version)
               VALUES (1, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   workspace = excluded.workspace,
                   scan_timestamp = excluded.scan_timestamp,
                   total_files = excluded.total_files,
                   version = excluded.version
            """,
            (self.workspace, now, total_files, SCHEMA_VERSION),
        )
        conn.commit()

    def get_scan_metadata(self) -> Optional[Dict[str, Any]]:
        """Get the current scan metadata."""
        conn = self._connect()
        row = conn.execute("SELECT * FROM scan_metadata WHERE id = 1").fetchone()
        return dict(row) if row else None

    # ─── Frontend/Backend Registry Storage ──────────────────

    def store_frontend_registry(self, registry_data: Dict[str, Any]) -> None:
        """Store the frontend registry as a special analysis cache entry."""
        self.set_cached_result(
            "__frontend_registry__",
            ["__all__"],
            registry_data,
        )

    def load_frontend_registry(self) -> Optional[Dict[str, Any]]:
        """Load the frontend registry from the cache."""
        return self.get_cached_result("__frontend_registry__", ["__all__"])

    def store_backend_registry(self, registry_data: Dict[str, Any]) -> None:
        """Store the backend registry as a special analysis cache entry."""
        self.set_cached_result(
            "__backend_registry__",
            ["__all__"],
            registry_data,
        )

    def load_backend_registry(self) -> Optional[Dict[str, Any]]:
        """Load the backend registry from the cache."""
        return self.get_cached_result("__backend_registry__", ["__all__"])

    # ─── Migration ──────────────────────────────────────────

    def migrate_from_json(self) -> Dict[str, Any]:
        """Migrate data from existing .codelens/ JSON files to SQLite."""
        from registry import load_frontend_registry, load_backend_registry, get_codelens_dir

        result = {
            "status": "ok",
            "frontend_classes": 0,
            "frontend_ids": 0,
            "backend_nodes": 0,
            "backend_edges": 0,
            "files_migrated": 0,
        }

        conn = self._connect()

        # ── Migrate frontend registry ──
        frontend = load_frontend_registry(self.workspace)
        if frontend:
            class_symbols = []
            for cls in frontend.get("classes", []):
                class_symbols.append({
                    "name": cls.get("name", ""),
                    "kind": "class",
                    "file_path": "",
                    "language": "css",
                    "extra_json": json.dumps({
                        "ref_count": cls.get("ref_count", 0),
                        "status": cls.get("status", ""),
                        "html": cls.get("html", []),
                        "css": cls.get("css", []),
                        "js": cls.get("js", []),
                    }, ensure_ascii=False),
                })
            self.insert_symbols_batch(class_symbols)
            result["frontend_classes"] = len(class_symbols)

            id_symbols = []
            for id_entry in frontend.get("ids", []):
                id_symbols.append({
                    "name": id_entry.get("name", ""),
                    "kind": "id",
                    "file_path": "",
                    "language": "html",
                    "extra_json": json.dumps({
                        "ref_count": id_entry.get("ref_count", 0),
                        "status": id_entry.get("status", ""),
                        "defined_in_html": id_entry.get("defined_in_html", []),
                        "css": id_entry.get("css", []),
                        "js": id_entry.get("js", []),
                    }, ensure_ascii=False),
                })
            self.insert_symbols_batch(id_symbols)
            result["frontend_ids"] = len(id_symbols)

            self.store_frontend_registry(frontend)

        # ── Migrate backend registry ──
        backend = load_backend_registry(self.workspace)
        if backend:
            node_symbols = []
            node_refs = []
            for node in backend.get("nodes", []):
                node_symbols.append({
                    "name": node.get("fn", node.get("name", "")),
                    "kind": "function",
                    "file_path": node.get("file", ""),
                    "line_start": node.get("line"),
                    "language": node.get("lang", ""),
                    "signature": node.get("signature", ""),
                    "extra_json": json.dumps({
                        "id": node.get("id", ""),
                        "ref_count": node.get("ref_count", 0),
                        "status": node.get("status", ""),
                        "exported": node.get("exported", False),
                        "component": node.get("component", False),
                        "pub": node.get("pub", False),
                    }, ensure_ascii=False),
                })

            self.insert_symbols_batch(node_symbols)
            result["backend_nodes"] = len(node_symbols)

            for edge in backend.get("edges", []):
                node_refs.append({
                    "source_symbol": edge.get("from", ""),
                    "target_symbol": edge.get("to", ""),
                    "reference_type": edge.get("type", "call"),
                    "extra_json": json.dumps({
                        "resolved": edge.get("resolved", True),
                    }, ensure_ascii=False),
                })
            self.insert_references_batch(node_refs)
            result["backend_edges"] = len(node_refs)

            self.store_backend_registry(backend)

        # ── Migrate file mtimes ──
        try:
            mtimes_path = os.path.join(get_codelens_dir(self.workspace), "mtimes.json")
            if os.path.exists(mtimes_path):
                with open(mtimes_path, "r", encoding="utf-8") as f:
                    mtimes = json.load(f)
                file_entries = []
                for rel_path, mtime in mtimes.items():
                    abs_path = os.path.join(self.workspace, rel_path)
                    file_entries.append({
                        "file_path": abs_path,
                        "language": "",
                    })
                if file_entries:
                    self.upsert_files_batch(file_entries)
                    result["files_migrated"] = len(file_entries)
                    for rel_path, mtime in mtimes.items():
                        conn.execute(
                            "UPDATE files SET last_modified = ? WHERE file_path = ?",
                            (mtime, rel_path),
                        )
                    conn.commit()
        except Exception as e:
            logger.warning(f"Failed to migrate mtimes: {e}")

        total = result["frontend_classes"] + result["frontend_ids"] + result["backend_nodes"]
        self.update_scan_metadata(total)

        return result

    # ─── Stats ──────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        conn = self._connect()
        stats = {}

        try:
            stats["symbols"] = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        except sqlite3.Error:
            stats["symbols"] = 0

        try:
            stats["references"] = conn.execute("SELECT COUNT(*) FROM refs").fetchone()[0]
        except sqlite3.Error:
            stats["references"] = 0

        try:
            stats["files"] = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        except sqlite3.Error:
            stats["files"] = 0

        try:
            stats["cache_entries"] = conn.execute("SELECT COUNT(*) FROM analysis_cache").fetchone()[0]
        except sqlite3.Error:
            stats["cache_entries"] = 0

        try:
            db_size = os.path.getsize(self._db_path)
            stats["db_size_bytes"] = db_size
            stats["db_size_human"] = f"{db_size / 1024:.1f} KB"
        except OSError:
            stats["db_size_bytes"] = 0
            stats["db_size_human"] = "0 KB"

        return stats

    def vacuum(self) -> None:
        """Compact the database to reclaim space."""
        conn = self._connect()
        conn.execute("VACUUM")
        conn.commit()


# ─── Module-level Helpers ──────────────────────────────────────

def db_exists(workspace: str, db_path: Optional[str] = None) -> bool:
    """Check if a CodeLens SQLite database exists for the workspace."""
    path = db_path or os.path.join(workspace, ".codelens", DB_FILENAME)
    return os.path.exists(path)


def get_registry(workspace: str, db_path: Optional[str] = None) -> PersistentRegistry:
    """Get a PersistentRegistry instance for the workspace."""
    return PersistentRegistry(workspace, db_path)


def is_sqlite_available() -> bool:
    """Check if SQLite is available (should always be True in Python 3)."""
    try:
        import sqlite3
        return True
    except ImportError:
        return False
