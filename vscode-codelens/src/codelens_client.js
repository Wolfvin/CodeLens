/**
 * CodeLens Client — CLI & MCP Communication Layer
 *
 * Provides methods to execute CodeLens CLI commands and parse results.
 * Handles:
 *  - Auto-detection of codelens.py path
 *  - SARIF-formatted check output
 *  - Fix suggestions and application
 *  - Guard pre/post checks
 *  - Result caching with TTL
 *  - Spawned process management
 */

const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

// ─── Constants ──────────────────────────────────────────────────

const CACHE_TTL_MS = 60_000; // 1 minute default TTL
const SPAWN_TIMEOUT_MS = 120_000; // 2 minute timeout for CLI commands

// ─── CodeLens Client ────────────────────────────────────────────

class CodeLensClient {
  constructor() {
    this._cache = new Map(); // key → { data, timestamp }
    this._codelensPath = null;
    this._runningProcesses = new Set();
  }

  // ─── Public API ────────────────────────────────────────────

  /**
   * Run a generic CodeLens CLI command
   * @param {string} command - CLI subcommand (e.g., 'check', 'scan', 'dashboard')
   * @param {string[]} args - Additional CLI arguments
   * @param {string} workspace - Workspace root path
   * @returns {Promise<object>} Parsed JSON output
   */
  async runCommand(command, args = [], workspace) {
    const cliPath = await this._getCodelensPath();
    if (!cliPath) {
      throw new Error('CodeLens CLI not found. Set codelens.path in settings or install CodeLens.');
    }

    const allArgs = [cliPath, command, ...args, '--format', 'json'];
    if (workspace) {
      allArgs.push(workspace);
    }

    return this._execute(allArgs);
  }

  /**
   * Run SARIF-formatted check on workspace
   * @param {string[]} commands - Commands to run (e.g., ['secrets', 'dead-code'])
   * @param {string} workspace - Workspace root path
   * @param {string} [minSeverity='medium'] - Minimum severity threshold
   * @param {number} [maxFindings=100] - Max findings limit
   * @param {object} [options] - Additional options
   * @returns {Promise<object>} SARIF output
   */
  async runSARIF(commands, workspace, minSeverity = 'medium', maxFindings = 100, options = {}) {
    const cacheKey = `sarif:${workspace}:${commands.join(',')}:${minSeverity}:${maxFindings}`;
    const cached = this._getCache(cacheKey);
    if (cached) return cached;

    const cliPath = await this._getCodelensPath();
    if (!cliPath) {
      throw new Error('CodeLens CLI not found. Set codelens.path in settings or install CodeLens.');
    }

    const args = [
      cliPath,
      'check',
      '--sarif',
      '--severity', minSeverity,
      '--max-findings', String(maxFindings),
      '--commands', ...commands,
      workspace,
    ];

    const result = await this._execute(args, options);
    this._setCache(cacheKey, result);
    return result;
  }

  /**
   * Get fix suggestions for a file
   * @param {string} filePath - File to fix
   * @param {string[]} categories - Fix categories
   * @param {number} confidence - Min confidence (0-1)
   * @param {string} workspace - Workspace root path
   * @returns {Promise<object>} Fix suggestions with diffs
   */
  async runFix(filePath, categories, confidence, workspace) {
    const cliPath = await this._getCodelensPath();
    if (!cliPath) {
      throw new Error('CodeLens CLI not found.');
    }

    const args = [
      cliPath,
      'fix',
      '--categories', ...categories,
      '--min-confidence', String(confidence),
      '--apply',
      workspace || path.dirname(filePath),
    ];

    return this._execute(args);
  }

  /**
   * Apply a specific fix by ID
   * @param {string} fixId - Fix identifier
   * @returns {Promise<object>} Apply result
   */
  async applyFix(fixId) {
    const cliPath = await this._getCodelensPath();
    if (!cliPath) {
      throw new Error('CodeLens CLI not found.');
    }

    const args = [cliPath, 'fix', '--apply-fix', fixId];

    return this._execute(args);
  }

  /**
   * Pre-write guard check
   * @param {string} filePath - File being modified
   * @param {string|null} symbol - Symbol being modified (optional)
   * @param {string} workspace - Workspace root path
   * @returns {Promise<object>} Guard result with issues/warnings
   */
  async guardPre(filePath, symbol, workspace) {
    const cacheKey = `guard:pre:${filePath}:${symbol || ''}`;
    // Short TTL for guard checks (10s) — more real-time
    const cached = this._getCache(cacheKey, 10_000);
    if (cached) return cached;

    const cliPath = await this._getCodelensPath();
    if (!cliPath) {
      throw new Error('CodeLens CLI not found.');
    }

    const args = [
      cliPath,
      'guard', 'pre',
      '--file', filePath,
    ];
    if (symbol) {
      args.push('--symbol', symbol);
    }

    // Guard commands take workspace as positional arg
    if (workspace) {
      args.push(workspace);
    }

    const result = await this._execute(args);
    this._setCache(cacheKey, result, 10_000);
    return result;
  }

  /**
   * Post-write guard check
   * @param {string} filePath - File that was modified
   * @param {string} workspace - Workspace root path
   * @returns {Promise<object>} Guard result with new/resolved issues
   */
  async guardPost(filePath, workspace) {
    const cliPath = await this._getCodelensPath();
    if (!cliPath) {
      throw new Error('CodeLens CLI not found.');
    }

    const args = [
      cliPath,
      'guard', 'post',
      '--file', filePath,
    ];
    if (workspace) {
      args.push(workspace);
    }

    return this._execute(args);
  }

  /**
   * Invalidate the entire cache
   */
  invalidateCache() {
    this._cache.clear();
  }

  /**
   * Kill all running processes and clean up
   */
  dispose() {
    for (const proc of this._runningProcesses) {
      try { proc.kill(); } catch (e) { /* ignore */ }
    }
    this._runningProcesses.clear();
    this._cache.clear();
    this._codelensPath = null;
  }

  // ─── Private ───────────────────────────────────────────────

  /**
   * Auto-detect codelens.py path
   * Priority: config setting → workspace .codelens → home dir → PATH
   */
  async _getCodelensPath() {
    if (this._codelensPath) return this._codelensPath;

    // 1. Check VS Code configuration
    try {
      const vscode = require('vscode');
      const config = vscode.workspace.getConfiguration('codelens');
      const configPath = config.get('path', '');
      if (configPath && fs.existsSync(configPath)) {
        this._codelensPath = configPath;
        return this._codelensPath;
      }
    } catch (e) { /* not in VS Code context */ }

    // 2. Check workspace for codelens.py
    const workspacePaths = this._getWorkspacePaths();
    for (const wsPath of workspacePaths) {
      const candidates = [
        path.join(wsPath, 'codelens.py'),
        path.join(wsPath, 'scripts', 'codelens.py'),
        path.join(wsPath, '.codelens', 'codelens.py'),
      ];
      for (const candidate of candidates) {
        if (fs.existsSync(candidate)) {
          this._codelensPath = candidate;
          return this._codelensPath;
        }
      }
    }

    // 3. Check home directory
    const homeCandidates = [
      path.join(os.homedir(), '.codelens', 'codelens.py'),
      path.join(os.homedir(), '.local', 'bin', 'codelens.py'),
    ];
    for (const candidate of homeCandidates) {
      if (fs.existsSync(candidate)) {
        this._codelensPath = candidate;
        return this._codelensPath;
      }
    }

    // 4. Check if 'codelens' is on PATH (as executable)
    try {
      const result = await this._execute(['which', 'codelens'], { timeout: 3000 });
      if (result && result.trim()) {
        this._codelensPath = result.trim();
        return this._codelensPath;
      }
    } catch (e) { /* not on PATH */ }

    // Also try python3 -m codelens
    try {
      const result = await this._execute(
        ['python3', '-c', 'import codelens; print(codelens.__file__)'],
        { timeout: 5000 }
      );
      if (result) {
        // Found as Python module — use python3 -m approach
        this._codelensPath = '__module__'; // Special marker
        return this._codelensPath;
      }
    } catch (e) { /* not installed as module */ }

    return null;
  }

  /**
   * Get workspace folder paths
   */
  _getWorkspacePaths() {
    const paths = [];
    try {
      const vscode = require('vscode');
      const folders = vscode.workspace.workspaceFolders;
      if (folders) {
        for (const folder of folders) {
          paths.push(folder.uri.fsPath);
        }
      }
    } catch (e) { /* ignore */ }
    return paths;
  }

  /**
   * Execute a command and return parsed JSON output
   * @param {string[]} commandAndArgs - First element is the executable, rest are args
   * @param {object} [options] - { timeout, onProgress, token }
   * @returns {Promise<object|string>} Parsed JSON or raw string
   */
  _execute(commandAndArgs, options = {}) {
    const timeout = options.timeout || SPAWN_TIMEOUT_MS;
    const onProgress = options.onProgress;
    const token = options.token;

    return new Promise((resolve, reject) => {
      const executable = commandAndArgs[0];
      const args = commandAndArgs.slice(1);

      // Handle __module__ special case
      let cmd, cmdArgs;
      if (executable === '__module__') {
        cmd = 'python3';
        cmdArgs = ['-m', 'codelens', ...args];
      } else {
        cmd = executable;
        cmdArgs = args;
      }

      // If executable is a .py file, prepend python3
      if (cmd.endsWith('.py')) {
        cmdArgs = [cmd, ...cmdArgs];
        cmd = 'python3';
      }

      const proc = spawn(cmd, cmdArgs, {
        cwd: options.cwd || process.cwd(),
        env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' },
        stdio: ['ignore', 'pipe', 'pipe'],
        shell: false,
      });

      this._runningProcesses.add(proc);

      let stdout = '';
      let stderr = '';

      proc.stdout.on('data', (data) => {
        stdout += data.toString();
      });

      proc.stderr.on('data', (data) => {
        const text = data.toString();
        stderr += text;
        // Report progress from stderr (CodeLens outputs progress there)
        if (onProgress && text.includes('Scanning')) {
          onProgress(text.trim());
        }
      });

      // Handle cancellation
      if (token) {
        token.onCancellationRequested(() => {
          try { proc.kill(); } catch (e) { /* ignore */ }
          reject(new Error('Cancelled'));
        });
      }

      // Handle timeout
      const timer = setTimeout(() => {
        try { proc.kill(); } catch (e) { /* ignore */ }
        reject(new Error(`Command timed out after ${timeout}ms`));
      }, timeout);

      proc.on('close', (code) => {
        clearTimeout(timer);
        this._runningProcesses.delete(proc);

        if (code !== 0 && !stdout) {
          // Command failed with no stdout — try to parse error from stderr
          const errMsg = stderr.trim() || `Process exited with code ${code}`;
          reject(new Error(errMsg));
          return;
        }

        // Try to parse JSON
        const trimmed = stdout.trim();
        if (!trimmed) {
          resolve({});
          return;
        }

        try {
          resolve(JSON.parse(trimmed));
        } catch (e) {
          // Not JSON — return raw string (some commands output plain text)
          resolve(trimmed);
        }
      });

      proc.on('error', (err) => {
        clearTimeout(timer);
        this._runningProcesses.delete(proc);
        reject(new Error(`Failed to execute command: ${err.message}`));
      });
    });
  }

  // ─── Cache ─────────────────────────────────────────────────

  _getCache(key, ttlMs) {
    const entry = this._cache.get(key);
    if (!entry) return null;

    const ttl = ttlMs || CACHE_TTL_MS;
    if (Date.now() - entry.timestamp > ttl) {
      this._cache.delete(key);
      return null;
    }

    return entry.data;
  }

  _setCache(key, data, ttlMs) {
    this._cache.set(key, {
      data,
      timestamp: Date.now(),
      ttl: ttlMs || CACHE_TTL_MS,
    });

    // Prune old entries (keep cache under 100 entries)
    if (this._cache.size > 100) {
      const oldest = [...this._cache.entries()]
        .sort((a, b) => a[1].timestamp - b[1].timestamp);
      for (let i = 0; i < 20; i++) {
        this._cache.delete(oldest[i][0]);
      }
    }
  }
}

// ─── Exports ────────────────────────────────────────────────────

module.exports = { CodeLensClient };
