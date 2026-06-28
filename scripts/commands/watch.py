"""Watch command — Start file watcher for real-time registry updates."""

import os
import sys
import time
import json
import threading
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from registry import load_config, load_frontend_registry, load_backend_registry
from diff_engine import save_snapshot
from outline_engine import get_workspace_outline
from utils import write_output_files, compute_summary, DEFAULT_IGNORE_DIRS, logger
from commands import register_command
from commands.scan import cmd_scan


# Extensions that trigger a rescan
_WATCH_EXTENSIONS = frozenset({
    '.html', '.htm', '.css', '.scss', '.less', '.sass',
    '.js', '.jsx', '.ts', '.tsx', '.rs', '.py', '.vue', '.svelte',
})


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--debounce", "-d", type=float, default=0.5,
                        help="Debounce interval in seconds (default: 0.5)")
    parser.add_argument("--git-mode", action="store_true",
                        help="Use git-diff polling instead of watchdog file events. "
                             "Checks 'git diff --name-only' every --interval seconds and "
                             "re-indexes only the files git knows changed. Falls back to "
                             "watchdog if git is unavailable or the workspace is not a "
                             "git repo. Default: watchdog (real-time file events).")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="Polling interval in seconds for --git-mode (default: 2.0)")


def execute(args, workspace):
    """Execute the watch command. This is a long-running command that doesn't return a dict."""
    git_mode = getattr(args, 'git_mode', False)
    interval = getattr(args, 'interval', 2.0)
    cmd_watch(workspace, debounce=args.debounce, git_mode=git_mode, interval=interval)
    return {"status": "stopped"}


def cmd_watch(workspace: str, debounce: float = 0.5,
              git_mode: bool = False, interval: float = 2.0) -> None:
    """
    Start file watcher for real-time registry updates.
    Uses debounce to coalesce rapid file changes, prints a clean
    one-line summary, and writes outline.json + summary.json to .codelens/.

    Two modes (issue #14):
    - Default (watchdog): real-time file events via the watchdog library.
    - --git-mode: polls 'git diff --name-only' every `interval` seconds
      and re-indexes only the files git knows changed. Useful when
      watchdog is unavailable or when the agent wants git-aware delta
      instead of mtime-based change detection.
    """
    import threading as _threading
    workspace = os.path.abspath(workspace)

    if git_mode:
        _watch_git_mode(workspace, interval=interval, debounce=debounce)
        return

    # ─── Debounce state ────────────────────────────────────
    _timer: Optional[_threading.Timer] = None
    _lock = _threading.Lock()
    _changed_files: set = set()

    def _on_file_change(filepath: str) -> None:
        """Called when a source file changes. Debounces rapid events."""
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in _WATCH_EXTENSIONS:
            return
        # Ignore changes inside .codelens output directory
        if '.codelens' in filepath:
            return

        nonlocal _timer
        with _lock:
            _changed_files.add(filepath)
            if _timer:
                _timer.cancel()
            _timer = _threading.Timer(debounce, _do_rescan)
            _timer.daemon = True
            _timer.start()

    def _do_rescan() -> None:
        """Perform the actual rescan after the debounce period."""
        with _lock:
            changed = _changed_files.copy()
            _changed_files.clear()

        if not changed:
            return

        changed_rel = [os.path.relpath(f, workspace) for f in changed]
        for rel in changed_rel:
            print(f'  Changed: {rel}')

        # Run incremental scan
        scan_result = cmd_scan(workspace, incremental=True)

        # Auto-save snapshot
        try:
            frontend = load_frontend_registry(workspace)
            backend = load_backend_registry(workspace)
            save_snapshot(workspace, frontend, backend)
        except Exception:
            logger.debug("Failed to save snapshot after rescan", exc_info=True)

        # Generate outline.json + summary.json
        summary = write_output_files(workspace, scan_result)
        print(_format_watch_summary(summary, changed_count=len(changed)))

    # ─── Initial scan ──────────────────────────────────────
    print(f'[CodeLens] Scanning {workspace}...')
    scan_result = cmd_scan(workspace)

    # Auto-save snapshot
    try:
        frontend = load_frontend_registry(workspace)
        backend = load_backend_registry(workspace)
        save_snapshot(workspace, frontend, backend)
    except Exception:
        logger.debug("Failed to save initial snapshot", exc_info=True)

    # Generate outline.json + summary.json
    summary = write_output_files(workspace, scan_result)
    print(_format_watch_summary(summary))

    # ─── Start watcher ─────────────────────────────────────
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        print('[CodeLens] watchdog not installed. Install with: pip install watchdog')
        print(f'[CodeLens] Falling back to polling mode (every 2s, debounce: {debounce}s)...')
        _watch_polling(workspace, debounce, _on_file_change)
        return

    class CodeLensHandler(FileSystemEventHandler):
        def on_modified(self, event):
            if not event.is_directory:
                _on_file_change(event.src_path)

        def on_created(self, event):
            if not event.is_directory:
                _on_file_change(event.src_path)

        def on_deleted(self, event):
            if not event.is_directory:
                _on_file_change(event.src_path)

    observer = Observer()
    handler = CodeLensHandler()
    observer.schedule(handler, workspace, recursive=True)
    observer.start()

    print(f'[CodeLens] Watching {workspace} (debounce: {debounce}s) — Press Ctrl+C to stop')
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print('[CodeLens] Stopped.')
    observer.join()


def _watch_polling(
    workspace: str,
    debounce: float = 0.5,
    on_change_callback=None
) -> None:
    """
    Fallback polling-based watcher with debounce support.
    Checks for file modifications every 2 seconds.
    """
    import threading as _threading

    if on_change_callback is None:
        _lock = _threading.Lock()
        _timer = None
        _pending: set = set()

        def _poll_rescan():
            nonlocal _timer
            with _lock:
                changed = _pending.copy()
                _pending.clear()
            if not changed:
                return
            scan_result = cmd_scan(workspace, incremental=True)
            try:
                frontend = load_frontend_registry(workspace)
                backend = load_backend_registry(workspace)
                save_snapshot(workspace, frontend, backend)
            except Exception:
                logger.debug("Failed to save snapshot in polling mode", exc_info=True)
            summary = write_output_files(workspace, scan_result)
            print(_format_watch_summary(summary, changed_count=len(changed)))

        def on_change_callback(filepath):
            nonlocal _timer
            ext = os.path.splitext(filepath)[1].lower()
            if ext not in _WATCH_EXTENSIONS:
                return
            if '.codelens' in filepath:
                return
            with _lock:
                _pending.add(filepath)
                if _timer:
                    _timer.cancel()
                _timer = _threading.Timer(debounce, _poll_rescan)
                _timer.daemon = True
                _timer.start()

    # Track file mtimes
    last_mtimes: Dict[str, float] = {}
    ignore_dirs = set(DEFAULT_IGNORE_DIRS)

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith('.')]
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext in _WATCH_EXTENSIONS:
                filepath = os.path.join(root, filename)
                try:
                    last_mtimes[filepath] = os.path.getmtime(filepath)
                except OSError:
                    logger.debug(f"Failed to get mtime for: {filepath}")

    print(f'[CodeLens] Polling {workspace} every 2s (debounce: {debounce}s) — Press Ctrl+C to stop')
    try:
        while True:
            time.sleep(2)

            # Check for modified/deleted files
            for filepath in list(last_mtimes.keys()):
                try:
                    current = os.path.getmtime(filepath)
                    if current != last_mtimes[filepath]:
                        last_mtimes[filepath] = current
                        on_change_callback(filepath)
                except OSError:
                    del last_mtimes[filepath]
                    on_change_callback(filepath)

            # Check for new files
            for root, dirs, filenames in os.walk(workspace):
                dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith('.')]
                for filename in filenames:
                    ext = os.path.splitext(filename)[1].lower()
                    if ext in _WATCH_EXTENSIONS:
                        filepath = os.path.join(root, filename)
                        if filepath not in last_mtimes:
                            try:
                                last_mtimes[filepath] = os.path.getmtime(filepath)
                                on_change_callback(filepath)
                            except OSError:
                                logger.debug(f"Failed to get mtime for new file: {filepath}")

    except KeyboardInterrupt:
        print('[CodeLens] Stopped.')


def _watch_git_mode(
    workspace: str,
    interval: float = 2.0,
    debounce: float = 0.5,
) -> None:
    """Polling watcher that uses git-diff to detect changes (issue #14).

    Every ``interval`` seconds, runs ``git diff --name-only`` (working
    tree vs HEAD) + ``git ls-files --others`` (untracked) to enumerate
    the files git knows changed since the last poll. If the set is
    non-empty, runs an incremental scan and prints a one-line summary.

    Falls back to ``_watch_polling`` (mtime-based) when git is
    unavailable or the workspace is not a git repo — the user requested
    git-mode but git isn't usable, so we degrade to the next-best
    available watcher instead of refusing to start.
    """
    try:
        from git_aware import get_current_sha, get_changed_files, get_untracked_files
    except ImportError:
        print('[CodeLens] git_aware module not available; falling back to mtime polling')
        _watch_polling(workspace, debounce=debounce)
        return

    if not get_current_sha(workspace):
        print('[CodeLens] workspace is not a git repo; falling back to mtime polling')
        _watch_polling(workspace, debounce=debounce)
        return

    print(f'[CodeLens] Git-mode watching {workspace} (poll: {interval}s, debounce: {debounce}s) — Press Ctrl+C to stop')

    import threading as _threading
    last_seen: set = set()
    _timer: Optional[_threading.Timer] = None
    _lock = _threading.Lock()
    _pending: set = set()

    def _do_rescan():
        nonlocal _timer
        with _lock:
            changed = _pending.copy()
            _pending.clear()
        if not changed:
            return
        changed_rel = sorted(os.path.relpath(f, workspace) for f in changed)
        for rel in changed_rel:
            print(f'  Changed: {rel}')
        scan_result = cmd_scan(workspace, incremental=True)
        try:
            frontend = load_frontend_registry(workspace)
            backend = load_backend_registry(workspace)
            save_snapshot(workspace, frontend, backend)
        except Exception:
            logger.debug("Failed to save snapshot in git-mode", exc_info=True)
        summary = write_output_files(workspace, scan_result)
        print(_format_watch_summary(summary, changed_count=len(changed)))

    def _schedule_rescan(filepath: str) -> None:
        nonlocal _timer
        with _lock:
            _pending.add(filepath)
            if _timer:
                _timer.cancel()
            _timer = _threading.Timer(debounce, _do_rescan)
            _timer.daemon = True
            _timer.start()

    try:
        while True:
            time.sleep(interval)
            # Combine tracked changes (vs HEAD) + untracked new files.
            rel_paths = set(get_changed_files(workspace, since_sha=None))
            rel_paths |= set(get_untracked_files(workspace))
            abs_paths = {
                os.path.join(workspace, rel)
                for rel in rel_paths
                if os.path.splitext(rel)[1].lower() in _WATCH_EXTENSIONS
                and '.codelens' not in rel
            }
            new_changes = abs_paths - last_seen
            if new_changes:
                last_seen = abs_paths
                for fp in new_changes:
                    _schedule_rescan(fp)
            else:
                last_seen = abs_paths
    except KeyboardInterrupt:
        print('[CodeLens] Stopped.')


def _format_watch_summary(summary: Dict[str, Any], changed_count: int = 0) -> str:
    """Format a one-line summary for terminal output."""
    now = datetime.now().strftime('%H:%M:%S')
    files = summary.get('files', 0)
    funcs = summary.get('functions', 0)
    classes = summary.get('classes', 0)
    nodes = summary.get('backend_nodes', 0)
    edges = summary.get('backend_edges', 0)

    parts = [f'{files} files', f'{funcs} funcs', f'{classes} classes']
    if nodes:
        parts.append(f'{nodes} nodes')
    if edges:
        parts.append(f'{edges} edges')
    if changed_count:
        parts.append(f'{changed_count} changed')

    return f'[{now}] \u2713 {" | ".join(parts)}'


register_command("watch", "Start file watcher with debounce", add_args, execute)
