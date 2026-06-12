"""
Base Engine for CodeLens — shared workspace walking and result formatting.

Every analysis engine (smell, complexity, secrets, etc.) repeats the same
os.walk + should_ignore_dir + safe_read_file boilerplate.  This module
extracts that into a reusable base class so engine authors only write
the actual analysis logic.

Usage:
    class MyEngine(BaseEngine):
        FILE_EXTENSIONS = {'.py', '.js'}

        def _analyze_file(self, rel_path, content, ext):
            # ... your analysis logic ...
            return [findings]

    result = MyEngine().run(workspace)
"""

import os
import time
from typing import Dict, List, Any, Optional, Set

from utils import (
    DEFAULT_IGNORE_DIRS,
    MAX_FILE_SIZE,
    GLOBAL_TIMEOUT_SEC,
    logger,
    safe_read_file,
    should_ignore_dir,
    time_budget_expired,
)


class BaseEngine:
    """Base class for CodeLens analysis engines.

    Subclasses must define:
        - FILE_EXTENSIONS: set of file extensions to scan (e.g., {'.py', '.js'})
        - _analyze_file(): method that processes a single file and returns findings

    Optionally override:
        - _build_result(): to customize the result structure
        - TIMEOUT_SEC: to change the default timeout
    """

    # Subclasses MUST override these
    FILE_EXTENSIONS: Set[str] = set()

    # Default timeout — can be overridden per-engine
    TIMEOUT_SEC: float = GLOBAL_TIMEOUT_SEC

    def __init__(self):
        self._start_time: float = 0.0
        self._files_scanned: int = 0
        self._findings: List[Dict[str, Any]] = []

    def run(self, workspace: str, **kwargs) -> Dict[str, Any]:
        """Main entry point — walk the workspace and analyze files.

        Args:
            workspace: Absolute path to the workspace root.
            **kwargs: Additional engine-specific parameters.

        Returns:
            Dict with status, stats, findings, etc.
        """
        workspace = os.path.abspath(workspace)
        self._start_time = time.time()
        self._files_scanned = 0
        self._findings = []

        # Allow subclasses to do pre-scan setup
        self._pre_scan(workspace, **kwargs)

        for root, dirs, filenames in os.walk(workspace):
            # Filter ignored directories in-place
            dirs[:] = [d for d in dirs
                       if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]

            rel_root = os.path.relpath(root, workspace)
            if should_ignore_dir(rel_root):
                dirs.clear()
                continue

            # Skip .codelens internal directory
            if '.codelens' in root:
                dirs.clear()
                continue

            for filename in filenames:
                ext = os.path.splitext(filename)[1].lower()
                if ext not in self.FILE_EXTENSIONS:
                    continue

                file_path = os.path.join(root, filename)
                rel_path = os.path.relpath(file_path, workspace)

                content = safe_read_file(file_path)
                if content is None:
                    continue

                self._files_scanned += 1

                try:
                    file_findings = self._analyze_file(rel_path, content, ext, file_path)
                    if file_findings:
                        self._findings.extend(file_findings)
                except Exception:
                    logger.warning(f"Error analyzing {rel_path}", exc_info=True)

                # Check time budget periodically (every 50 files)
                if self._files_scanned % 50 == 0:
                    if time_budget_expired(self._start_time, self.TIMEOUT_SEC):
                        logger.warning(
                            f"Time budget expired after {self._files_scanned} files"
                        )
                        break
            else:
                # Only continue outer loop if inner loop wasn't broken
                continue
            break

        return self._build_result(workspace)

    def _pre_scan(self, workspace: str, **kwargs) -> None:
        """Hook for subclasses to do setup before scanning.

        Override this to read config, initialize data structures, etc.
        """
        pass

    def _analyze_file(self, rel_path: str, content: str, ext: str,
                      abs_path: str) -> List[Dict[str, Any]]:
        """Analyze a single file. Subclasses MUST override this.

        Args:
            rel_path: Path relative to workspace root.
            content: File content as string.
            ext: File extension (e.g., '.py').
            abs_path: Absolute file path.

        Returns:
            List of finding dicts.
        """
        raise NotImplementedError("Subclasses must implement _analyze_file()")

    def _build_result(self, workspace: str) -> Dict[str, Any]:
        """Build the result dict. Subclasses can override for custom structure."""
        elapsed = time.time() - self._start_time
        return {
            "status": "ok",
            "workspace": workspace,
            "files_scanned": self._files_scanned,
            "total_findings": len(self._findings),
            "findings": self._findings,
            "elapsed_seconds": round(elapsed, 2),
        }
