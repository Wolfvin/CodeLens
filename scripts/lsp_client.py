"""
Generic LSP Client for CodeLens — Communicates with language servers via stdio.

Supports:
- pyright / pylsp (Python)
- typescript-language-server (JS/TS)
- rust-analyzer (Rust)
- clangd (C/C++)
- gopls (Go)

Design:
- Spawns each LSP server as a subprocess (stdio transport)
- Implements a minimal LSP protocol (initialize, shutdown, exit)
- Provides high-level methods: go_to_definition, find_references, get_type_info
- Auto-detects which LSP servers are available on the system
- Graceful fallback: all methods return empty results on failure
"""

import os
import sys
import json
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

# ─── LSP Server Configuration ────────────────────────────────────

LSP_SERVERS = {
    "pyright": {
        "command": ["pyright-langserver", "--stdio"],
        "languages": ["python"],
        "extensions": {".py", ".pyi", ".pyx"},
        "install_hint": "npm install -g pyright",
        "project_markers": ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile"],
    },
    "pylsp": {
        "command": ["pylsp"],
        "languages": ["python"],
        "extensions": {".py", ".pyi", ".pyx"},
        "install_hint": "pip install python-lsp-server",
        "project_markers": ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile"],
    },
    "typescript-language-server": {
        "command": ["typescript-language-server", "--stdio"],
        "languages": ["typescript", "javascript"],
        "extensions": {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"},
        "install_hint": "npm install -g typescript-language-server typescript",
        "project_markers": ["tsconfig.json", "package.json", "jsconfig.json"],
    },
    "rust-analyzer": {
        "command": ["rust-analyzer"],
        "languages": ["rust"],
        "extensions": {".rs"},
        "install_hint": "See https://rust-analyzer.github.io/manual.html#installation",
        "project_markers": ["Cargo.toml", "Cargo.lock"],
    },
    "clangd": {
        "command": ["clangd"],
        "languages": ["c", "cpp"],
        "extensions": {".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hxx"},
        "install_hint": "See https://clangd.llvm.org/installation.html",
        "project_markers": ["compile_commands.json", "CMakeLists.txt", "Makefile"],
    },
    "gopls": {
        "command": ["gopls"],
        "languages": ["go"],
        "extensions": {".go"},
        "install_hint": "go install golang.org/x/tools/gopls@latest",
        "project_markers": ["go.mod", "go.sum"],
    },
}


def _which(command: str) -> Optional[str]:
    """Check if a command exists on PATH."""
    try:
        result = subprocess.run(
            ["which", command], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None


def detect_available_servers() -> Dict[str, Dict[str, Any]]:
    """Auto-detect which LSP servers are available on the system.

    ``extensions`` is sorted so the payload is deterministic across Python
    invocations (``config["extensions"]`` is a set, and ``list(set)`` order
    depends on hash randomization). Required by issue #33 so that
    ``codelens --lsp-status`` and ``codelens lsp-status`` produce byte-identical
    JSON, not just structurally-equal JSON.
    """
    results = {}
    for name, config in LSP_SERVERS.items():
        cmd = config["command"][0]
        path = _which(cmd)
        results[name] = {
            "available": path is not None,
            "path": path,
            "languages": config["languages"],
            "extensions": sorted(config["extensions"]),
            "install_hint": config["install_hint"],
        }
    return results


def get_server_for_file(file_path: str) -> Optional[Tuple[str, Dict]]:
    """Find the best available LSP server for a given file."""
    ext = os.path.splitext(file_path)[1].lower()
    available = detect_available_servers()
    _PRIORITY = ["pyright", "typescript-language-server", "rust-analyzer", "clangd", "gopls", "pylsp"]
    for server_name in _PRIORITY:
        config = LSP_SERVERS.get(server_name)
        if not config:
            continue
        if ext in config["extensions"]:
            if available.get(server_name, {}).get("available"):
                return (server_name, config)
    for name, info in available.items():
        if info["available"] and ext in info.get("extensions", []):
            return (name, LSP_SERVERS[name])
    return None


def get_server_for_workspace(workspace: str) -> Optional[Tuple[str, Dict]]:
    """Find the best available LSP server based on workspace project markers."""
    available = detect_available_servers()
    _PRIORITY = ["pyright", "typescript-language-server", "rust-analyzer", "clangd", "gopls", "pylsp"]
    for server_name in _PRIORITY:
        config = LSP_SERVERS.get(server_name)
        if not config:
            continue
        if not available.get(server_name, {}).get("available"):
            continue
        for marker in config.get("project_markers", []):
            if os.path.exists(os.path.join(workspace, marker)):
                return (server_name, config)
    return None


# ─── LSP Protocol Implementation ─────────────────────────────────

class LSPClient:
    """Generic LSP client that communicates with a language server via stdio."""

    def __init__(self, server_name: str, workspace_root: str, timeout: float = 30.0):
        self.server_name = server_name
        self.config = LSP_SERVERS[server_name]
        self.workspace_root = os.path.abspath(workspace_root)
        self.timeout = timeout
        self._process: Optional[subprocess.Popen] = None
        self._msg_id = 0
        self._initialized = False
        self._lock = threading.Lock()
        self._response_map: Dict[int, Dict] = {}
        self._notification_list: List[Dict] = []
        self._reader_thread: Optional[threading.Thread] = None
        self._reader_stopped = threading.Event()

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def _send_request(self, method: str, params: Dict) -> int:
        msg_id = self._next_id()
        message = {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}
        body = json.dumps(message)
        header = f"Content-Length: {len(body)}\r\n\r\n"
        try:
            self._process.stdin.write(header.encode("utf-8"))
            self._process.stdin.write(body.encode("utf-8"))
            self._process.stdin.flush()
        except Exception:
            pass
        return msg_id

    def _send_notification(self, method: str, params: Dict) -> None:
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        body = json.dumps(message)
        header = f"Content-Length: {len(body)}\r\n\r\n"
        try:
            self._process.stdin.write(header.encode("utf-8"))
            self._process.stdin.write(body.encode("utf-8"))
            self._process.stdin.flush()
        except Exception:
            pass

    def _read_messages(self) -> None:
        buffer = b""
        while not self._reader_stopped.is_set():
            try:
                while b"\r\n\r\n" not in buffer:
                    chunk = self._process.stdout.read(1)
                    if not chunk:
                        return
                    buffer += chunk
                header_end = buffer.index(b"\r\n\r\n")
                header = buffer[:header_end].decode("utf-8")
                buffer = buffer[header_end + 4:]
                content_length = 0
                for line in header.split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        content_length = int(line.split(":", 1)[1].strip())
                        break
                if content_length == 0:
                    continue
                while len(buffer) < content_length:
                    chunk = self._process.stdout.read(content_length - len(buffer))
                    if not chunk:
                        return
                    buffer += chunk
                body = buffer[:content_length]
                buffer = buffer[content_length:]
                msg = json.loads(body.decode("utf-8"))
                if "id" in msg:
                    with self._lock:
                        self._response_map[msg["id"]] = msg
                else:
                    # Notifications (no id) — e.g. textDocument/publishDiagnostics.
                    # Append under the same lock the diagnostics reader uses to
                    # filter this list (issue #253), so a concurrent filter can't
                    # race a mutation mid-iteration.
                    with self._lock:
                        self._notification_list.append(msg)
            except Exception:
                return

    def _wait_for_response(self, msg_id: int, timeout: float = None) -> Optional[Dict]:
        if timeout is None:
            timeout = self.timeout
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if msg_id in self._response_map:
                    return self._response_map.pop(msg_id)
            time.sleep(0.05)
        return None

    def initialize(self) -> bool:
        try:
            cmd = self.config["command"]
            self._process = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, cwd=self.workspace_root,
            )
            self._reader_thread = threading.Thread(target=self._read_messages, daemon=True)
            self._reader_thread.start()
            init_params = {
                "processId": os.getpid(),
                "rootUri": _path_to_uri(self.workspace_root),
                "rootPath": self.workspace_root,
                "capabilities": {
                    "textDocument": {
                        "definition": {"dynamicRegistration": False, "linkSupport": True},
                        "references": {"dynamicRegistration": False},
                        "hover": {"dynamicRegistration": False, "contentFormat": ["markdown", "plaintext"]},
                        "publishDiagnostics": {"relatedInformation": True},
                    },
                    "workspace": {"symbol": {"dynamicRegistration": False}},
                },
                "trace": "off",
            }
            msg_id = self._send_request("initialize", init_params)
            response = self._wait_for_response(msg_id, timeout=20.0)
            if not response or "error" in response:
                return False
            self._send_notification("initialized", {})
            self._initialized = True
            return True
        except Exception:
            self._initialized = False
            return False

    def shutdown(self) -> None:
        if not self._process:
            return
        try:
            if self._initialized:
                msg_id = self._send_request("shutdown", {})
                self._wait_for_response(msg_id, timeout=5.0)
                self._send_notification("exit", {})
        except Exception:
            pass
        finally:
            self._reader_stopped.set()
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
            self._initialized = False

    def open_file(self, file_path: str) -> None:
        if not self._initialized:
            return
        try:
            abs_path = os.path.abspath(file_path)
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            language_id = self._get_language_id(abs_path)
            self._send_notification("textDocument/didOpen", {
                "textDocument": {"uri": _path_to_uri(abs_path), "languageId": language_id, "version": 1, "text": text}
            })
            time.sleep(0.3)
        except Exception:
            pass

    def close_file(self, file_path: str) -> None:
        if not self._initialized:
            return
        try:
            abs_path = os.path.abspath(file_path)
            self._send_notification("textDocument/didClose", {"textDocument": {"uri": _path_to_uri(abs_path)}})
        except Exception:
            pass

    def go_to_definition(self, file_path: str, line: int, character: int) -> List[Dict]:
        if not self._initialized:
            return []
        try:
            abs_path = os.path.abspath(file_path)
            msg_id = self._send_request("textDocument/definition", {
                "textDocument": {"uri": _path_to_uri(abs_path)},
                "position": {"line": line, "character": character},
            })
            response = self._wait_for_response(msg_id, timeout=10.0)
            if not response or "error" in response:
                return []
            result = response.get("result")
            if result is None:
                return []
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                if "targetUri" in result:
                    return [{"uri": result["targetUri"], "range": result.get("targetRange", {})}]
                return [result]
            return []
        except Exception:
            return []

    def find_references(self, file_path: str, line: int, character: int,
                        include_declaration: bool = True) -> List[Dict]:
        if not self._initialized:
            return []
        try:
            abs_path = os.path.abspath(file_path)
            msg_id = self._send_request("textDocument/references", {
                "textDocument": {"uri": _path_to_uri(abs_path)},
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": include_declaration},
            })
            response = self._wait_for_response(msg_id, timeout=15.0)
            if not response or "error" in response:
                return []
            result = response.get("result")
            if isinstance(result, list):
                return result
            return []
        except Exception:
            return []

    def get_hover(self, file_path: str, line: int, character: int) -> Optional[Dict]:
        if not self._initialized:
            return None
        try:
            abs_path = os.path.abspath(file_path)
            msg_id = self._send_request("textDocument/hover", {
                "textDocument": {"uri": _path_to_uri(abs_path)},
                "position": {"line": line, "character": character},
            })
            response = self._wait_for_response(msg_id, timeout=10.0)
            if not response or "error" in response:
                return None
            return response.get("result")
        except Exception:
            return None

    def get_type_info(self, file_path: str, line: int, character: int) -> Optional[str]:
        hover = self.get_hover(file_path, line, character)
        if not hover:
            return None
        contents = hover.get("contents", {})
        if isinstance(contents, dict):
            return contents.get("value", "")
        if isinstance(contents, list):
            parts = []
            for item in contents:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(item.get("value", ""))
            return "\n".join(parts)
        if isinstance(contents, str):
            return contents
        return None

    def get_diagnostics(self, file_path: str, wait_timeout: float = 3.0) -> List[Dict]:
        """Return LSP diagnostics (lint/errors/warnings) for ``file_path`` (issue #253).

        Diagnostics are pushed by the language server as
        ``textDocument/publishDiagnostics`` NOTIFICATIONS (not responses to a
        request) after the file is opened — the reader loop already collects
        every notification into ``_notification_list``. This method opens the
        file (triggering server analysis), waits up to ``wait_timeout`` for a
        matching publishDiagnostics notification to arrive, and returns the
        latest one's ``diagnostics`` array.

        Each diagnostic follows the LSP shape:
        ``{range, severity (1=Error 2=Warning 3=Info 4=Hint), message,
        source, code}``.

        Returns ``[]`` if LSP isn't initialized, the server pushes nothing
        within the timeout (many servers only diagnose on change, or the
        file is clean), or on any error — never raises.
        """
        if not self._initialized:
            return []
        try:
            abs_path = os.path.abspath(file_path)
            target_uri = _path_to_uri(abs_path)
            # Opening (or re-opening) the file triggers the server to analyze
            # and push publishDiagnostics. Note we deliberately do NOT drop
            # any already-collected diagnostics for this URI first: many
            # servers only push on *change*, not on re-open, so dropping and
            # waiting for a fresh push would return empty for a file that was
            # already analyzed this session. If a fresh push does arrive it's
            # appended later and "last wins" below picks it up.
            self.open_file(abs_path)
            # publishDiagnostics is async server-push — poll _notification_list
            # until one arrives for this URI or the timeout expires. If one is
            # already present (prior open), the first poll returns immediately.
            deadline = time.time() + wait_timeout
            latest: List[Dict] = []
            found = False
            while time.time() < deadline:
                with self._lock:
                    matches = [
                        n for n in self._notification_list
                        if n.get("method") == "textDocument/publishDiagnostics"
                        and n.get("params", {}).get("uri") == target_uri
                    ]
                if matches:
                    # Last one wins (server may push progressively).
                    latest = matches[-1].get("params", {}).get("diagnostics", [])
                    found = True
                    break
                time.sleep(0.1)
            return latest if found else []
        except Exception:
            return []

    def _get_language_id(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        _LANGUAGE_MAP = {
            ".py": "python", ".pyi": "python", ".pyx": "python",
            ".ts": "typescript", ".tsx": "typescriptreact",
            ".js": "javascript", ".jsx": "javascriptreact",
            ".mjs": "javascript", ".cjs": "javascript",
            ".rs": "rust", ".c": "c", ".h": "c",
            ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
            ".hpp": "cpp", ".hxx": "cpp", ".go": "go",
        }
        return _LANGUAGE_MAP.get(ext, "plaintext")


# ─── URI Utilities ────────────────────────────────────────────────

def _path_to_uri(path: str) -> str:
    abs_path = os.path.abspath(path).replace("\\", "/")
    if not abs_path.startswith("/"):
        abs_path = "/" + abs_path
    return f"file://{abs_path}"


def _uri_to_path(uri: str) -> str:
    if uri.startswith("file://"):
        uri = uri[7:]
    if len(uri) > 2 and uri[0] == "/" and uri[2] == ":":
        uri = uri[1:]
    return uri


# ─── Connection Pool ─────────────────────────────────────────────

class LSPConnectionPool:
    """Manages LSP client instances per workspace/language."""

    def __init__(self):
        self._clients: Dict[str, LSPClient] = {}
        self._lock = threading.Lock()

    def get_client(self, workspace: str, server_name: str) -> Optional[LSPClient]:
        key = f"{workspace}::{server_name}"
        with self._lock:
            if key in self._clients:
                client = self._clients[key]
                if client._initialized and client._process and client._process.poll() is None:
                    return client
                try:
                    client.shutdown()
                except Exception:
                    pass
                del self._clients[key]
        client = LSPClient(server_name, workspace)
        if client.initialize():
            with self._lock:
                self._clients[key] = client
            return client
        return None

    def get_client_for_file(self, workspace: str, file_path: str) -> Optional[LSPClient]:
        match = get_server_for_file(file_path)
        if not match:
            return None
        server_name, _ = match
        return self.get_client(workspace, server_name)

    def shutdown_all(self) -> None:
        with self._lock:
            for client in self._clients.values():
                try:
                    client.shutdown()
                except Exception:
                    pass
            self._clients.clear()


_connection_pool: Optional[LSPConnectionPool] = None


def get_connection_pool() -> LSPConnectionPool:
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = LSPConnectionPool()
    return _connection_pool


def shutdown_pool() -> None:
    global _connection_pool
    if _connection_pool is not None:
        _connection_pool.shutdown_all()
        _connection_pool = None
