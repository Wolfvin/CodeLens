// ============================================================
// CodeLens Neural Workspace — Command Runner
// Executes CodeLens CLI commands and returns parsed JSON
// ============================================================

import { execFile } from 'child_process'
import { promisify } from 'util'
import path from 'path'
import {
  ALLOWED_COMMANDS,
  COMMAND_TIMEOUT,
  MAX_BUFFER,
  MAX_ARG_LENGTH,
} from '@/lib/constants'

const execFileAsync = promisify(execFile)

// ---- Lazy Initialization for Environment Variables ----
// Instead of throwing on module load (which breaks tests and
// development), we resolve paths lazily on first execution.
// This allows the module to be imported without setting env vars,
// and gives a clear error only when a CLI command is actually run.

let _pythonPath: string | null = null
let _scriptPath: string | null = null
let _initialized = false

function ensureInitialized(): void {
  if (_initialized) return

  _pythonPath = process.env.CODELENS_PYTHON ?? null
  _scriptPath = process.env.CODELENS_SCRIPT
    ? path.resolve(process.env.CODELENS_SCRIPT)
    : null

  _initialized = true
}

function getPythonPath(): string {
  ensureInitialized()
  if (!_pythonPath) {
    throw new Error(
      '[CodeLens] CODELENS_PYTHON env var is not set. ' +
      'Set it to the path of your Python 3 interpreter (the one with tree-sitter installed). ' +
      'Example: CODELENS_PYTHON=/home/you/.venv/bin/python3'
    )
  }
  return _pythonPath
}

function getScriptPath(): string {
  ensureInitialized()
  if (!_scriptPath) {
    throw new Error(
      '[CodeLens] CODELENS_SCRIPT env var is not set. ' +
      'Set it to the path of the CodeLens CLI script (codelens.py). ' +
      'Example: CODELENS_SCRIPT=./skills/codelens/scripts/codelens.py'
    )
  }
  return _scriptPath
}

/**
 * Sanitize arguments — strip potentially dangerous characters.
 * Prevents shell injection even though we use execFile (not exec).
 */
function sanitizeArgs(args: string[]): string[] {
  return args.map(arg => {
    // Strip null bytes and control characters
    let cleaned = arg.replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, '')
    // Limit argument length to prevent buffer overflow attempts
    if (cleaned.length > MAX_ARG_LENGTH) {
      cleaned = cleaned.substring(0, MAX_ARG_LENGTH)
    }
    return cleaned
  })
}

class CommandRunner {
  // ─── Core Execution ──────────────────────────────────────────

  /**
   * Execute a codelens CLI command and return parsed JSON.
   *
   * @param command - CLI sub-command name (e.g. "scan", "query", "trace")
   * @param args - Positional and flag arguments
   * @returns Parsed JSON output from the CLI, or error object
   */
  async execute(command: string, args: string[] = []): Promise<Record<string, any>> {
    // Guard: reject 'watch' command — it runs indefinitely and will hang the API
    if (command === 'watch') {
      return {
        status: 'error',
        command,
        error: "The 'watch' command is not allowed via the API because it has a 60-second timeout and will hang the process. Use 'scan --incremental' instead.",
        exitCode: 'rejected',
      }
    }

    // Guard: whitelist validation — prevent command injection
    if (!ALLOWED_COMMANDS.has(command)) {
      return {
        status: 'error',
        command,
        error: `Command '${command}' is not recognized. Allowed commands: ${[...ALLOWED_COMMANDS].sort().join(', ')}`,
        exitCode: 'rejected',
      }
    }

    // Sanitize arguments — strip dangerous characters
    const safeArgs = sanitizeArgs(args)

    try {
      const pythonPath = getPythonPath()
      const scriptPath = getScriptPath()

      const { stdout, stderr } = await execFileAsync(pythonPath, [scriptPath, command, ...safeArgs], {
        timeout: COMMAND_TIMEOUT,
        maxBuffer: MAX_BUFFER,
      })

      // CLI outputs JSON to stdout
      if (!stdout || !stdout.trim()) {
        return {
          status: 'ok',
          command,
          message: 'Command completed with no output.',
        }
      }

      try {
        const parsed = JSON.parse(stdout)
        return parsed as Record<string, any>
      } catch {
        // If stdout is not valid JSON, return raw text
        return {
          status: 'ok',
          command,
          rawOutput: stdout.trim(),
        }
      }
    } catch (err: any) {
      // execFileAsync throws on non-zero exit codes
      const stderr = err.stderr ?? ''
      const stdout = err.stdout ?? ''
      const exitCode = err.code ?? 'unknown'

      // Some commands (like npm audit) exit with non-zero when findings exist
      // Try to parse stdout anyway
      if (stdout && stdout.trim()) {
        try {
          const parsed = JSON.parse(stdout)
          // If we got valid JSON back, it's probably a real result, not an error
          if (parsed && typeof parsed === 'object') {
            return parsed as Record<string, any>
          }
        } catch {
          // Fall through to error return
        }
      }

      return {
        status: 'error',
        command,
        error: typeof stderr === 'string' ? stderr.trim() : String(stderr),
        exitCode,
      }
    }
  }

  // ─── Full Graph ───────────────────────────────────────────────

  /**
   * Get full graph by running the scan command.
   * This returns all nodes and edges from the workspace registry.
   */
  async getFullGraph(workspace: string): Promise<{ nodes: any; edges: any }> {
    const result = await this.execute('scan', [workspace])

    // The scan command returns { frontend: { classes, ids }, backend: { nodes, edges } }
    // Return the raw structure so the normalizer can process it
    return {
      nodes: {
        frontend: result.frontend ?? { classes: [], ids: [] },
        backend: result.backend ?? { nodes: [], edges: [] },
      },
      edges: result.backend?.edges ?? [],
    }
  }

  // ─── Quick Command Wrappers ───────────────────────────────────

  /** Query a specific symbol by name */
  async query(name: string, workspace: string, domain?: string, fileFilter?: string): Promise<any> {
    const args = [name, workspace]
    if (domain) args.push('--domain', domain)
    if (fileFilter) args.push('--file', fileFilter)
    return this.execute('query', args)
  }

  /** Trace a symbol's call chain */
  async trace(name: string, workspace: string, direction?: string, depth?: number, domain?: string): Promise<any> {
    const args = [name, workspace]
    if (direction) args.push('--direction', direction)
    if (depth !== undefined) args.push('--depth', String(depth))
    if (domain) args.push('--domain', domain)
    return this.execute('trace', args)
  }

  /** Analyze change impact for a symbol */
  async impact(name: string, workspace: string, action?: string, domain?: string, depth?: number): Promise<any> {
    const args = [name, workspace]
    if (action) args.push('--action', action)
    if (domain) args.push('--domain', domain)
    if (depth !== undefined) args.push('--depth', String(depth))
    return this.execute('impact', args)
  }

  /** Scan workspace and build registry */
  async scan(workspace: string, incremental: boolean = false): Promise<any> {
    const args = [workspace]
    if (incremental) args.push('--incremental')
    return this.execute('scan', args)
  }

  /** List entries with optional filter */
  async list(workspace: string, domain?: string, filterType?: string): Promise<any> {
    const args = [workspace]
    if (domain) args.push('--domain', domain)
    if (filterType) args.push('--filter', filterType)
    return this.execute('list', args)
  }

  /** Search code pattern across workspace */
  async search(pattern: string, workspace: string, options?: {
    fileType?: string
    file?: string
    maxResults?: number
    ignoreCase?: boolean
    wholeWord?: boolean
  }): Promise<any> {
    const args = [pattern, workspace]
    if (options?.fileType) args.push('--type', options.fileType)
    if (options?.file) args.push('--file', options.file)
    if (options?.maxResults) args.push('--max-results', String(options.maxResults))
    if (options?.ignoreCase) args.push('--ignore-case')
    if (options?.wholeWord) args.push('--whole-word')
    return this.execute('search', args)
  }

  /** Search symbols in registry by name */
  async symbols(name: string, workspace: string, domain?: string, fuzzy?: boolean): Promise<any> {
    const args = [name, workspace]
    if (domain) args.push('--domain', domain)
    if (fuzzy) args.push('--fuzzy')
    return this.execute('symbols', args)
  }

  /** Detect circular dependencies */
  async circular(workspace: string): Promise<any> {
    return this.execute('circular', [workspace])
  }

  /** Trace data flow source→sink */
  async dataflow(workspace: string): Promise<any> {
    return this.execute('dataflow', [workspace])
  }

  /** Detect code smells */
  async smell(workspace: string, categories?: string[], severityFilter?: string): Promise<any> {
    const args = [workspace]
    if (categories?.length) args.push('--categories', categories.join(','))
    if (severityFilter) args.push('--severity', severityFilter)
    return this.execute('smell', args)
  }

  /** Analyze function side effects */
  async sideEffect(name: string, workspace: string): Promise<any> {
    return this.execute('side-effect', [name, workspace])
  }

  /** Pre-flight rename/move check */
  async refactorSafe(name: string, workspace: string): Promise<any> {
    return this.execute('refactor-safe', [name, workspace])
  }

  /** Enhanced dead code detection */
  async deadCode(workspace: string, categories?: string[]): Promise<any> {
    const args = [workspace]
    if (categories?.length) args.push('--categories', categories.join(','))
    return this.execute('dead-code', args)
  }

  /** Error propagation simulation */
  async stackTrace(name: string, workspace: string): Promise<any> {
    return this.execute('stack-trace', [name, workspace])
  }

  /** Test coverage mapping */
  async testMap(workspace: string): Promise<any> {
    return this.execute('test-map', [workspace])
  }

  /** Dependency drift detection */
  async configDrift(workspace: string): Promise<any> {
    return this.execute('config-drift', [workspace])
  }

  /** Lightweight type inference */
  async typeInfer(workspace: string, functionName?: string, fileFilter?: string): Promise<any> {
    const args = [workspace]
    if (functionName) args.push('--function', functionName)
    if (fileFilter) args.push('--file', fileFilter)
    return this.execute('type-infer', args)
  }

  /** Git blame code ownership */
  async ownership(workspace: string): Promise<any> {
    return this.execute('ownership', [workspace])
  }

  /** Detect hardcoded secrets/API keys */
  async secrets(workspace: string, severity?: string): Promise<any> {
    const args = [workspace]
    if (severity) args.push('--severity', severity)
    return this.execute('secrets', args)
  }

  /** Map execution entry points */
  async entrypoints(workspace: string): Promise<any> {
    return this.execute('entrypoints', [workspace])
  }

  /** Map REST/GraphQL routes to handlers */
  async apiMap(workspace: string): Promise<any> {
    return this.execute('api-map', [workspace])
  }

  /** Track global state management */
  async stateMap(workspace: string): Promise<any> {
    return this.execute('state-map', [workspace])
  }

  /** Audit environment variables */
  async envCheck(workspace: string): Promise<any> {
    return this.execute('env-check', [workspace])
  }

  /** Detect leftover debug code */
  async debugLeak(workspace: string): Promise<any> {
    return this.execute('debug-leak', [workspace])
  }

  /** Compute cyclomatic/cognitive complexity */
  async complexity(workspace: string, functionName?: string, fileFilter?: string, threshold?: number): Promise<any> {
    const args = [workspace]
    if (functionName) args.push('--function', functionName)
    if (fileFilter) args.push('--file', fileFilter)
    if (threshold !== undefined) args.push('--threshold', String(threshold))
    return this.execute('complexity', args)
  }

  /** Audit regex for ReDoS and issues */
  async regexAudit(workspace: string): Promise<any> {
    return this.execute('regex-audit', [workspace])
  }

  /** Detect accessibility issues */
  async a11y(workspace: string): Promise<any> {
    return this.execute('a11y', [workspace])
  }

  /** Scan dependencies for known CVEs */
  async vulnScan(workspace: string, severity?: string): Promise<any> {
    const args = [workspace]
    if (severity) args.push('--severity', severity)
    return this.execute('vuln-scan', args)
  }

  /** Detect performance anti-patterns */
  async perfHint(workspace: string): Promise<any> {
    return this.execute('perf-hint', [workspace])
  }

  /** Deep CSS analysis */
  async cssDeep(workspace: string): Promise<any> {
    return this.execute('css-deep', [workspace])
  }

  /** Validate registry vs file system */
  async validate(workspace: string): Promise<any> {
    return this.execute('validate', [workspace])
  }

  /** Compare registry snapshots */
  async diff(workspace: string): Promise<any> {
    return this.execute('diff', [workspace])
  }

  /** Module-level import tracking */
  async dependents(file: string, workspace: string): Promise<any> {
    return this.execute('dependents', [file, workspace])
  }

  /** Get rich symbol context */
  async context(name: string, workspace: string, domain?: string): Promise<any> {
    const args = [name, workspace]
    if (domain) args.push('--domain', domain)
    return this.execute('context', args)
  }

  /** Get file structure outline */
  async outline(workspace: string, file?: string): Promise<any> {
    const args = [workspace]
    if (file) args.push('--file', file)
    return this.execute('outline', args)
  }

  /** Detect CSS/HTML mismatches */
  async missingRefs(workspace: string): Promise<any> {
    return this.execute('missing-refs', [workspace])
  }

  /** Initialize .codelens config */
  async init(workspace: string): Promise<any> {
    return this.execute('init', [workspace])
  }

  /** Detect frameworks in workspace */
  async detect(workspace: string): Promise<any> {
    return this.execute('detect', [workspace])
  }

  /** Project handbook for AI agents */
  async handbook(workspace: string, format?: string): Promise<any> {
    const args = [workspace]
    if (format) args.push('--format', format)
    return this.execute('handbook', args)
  }

  /** Natural language query */
  async ask(question: string, workspace?: string): Promise<any> {
    const args = [question]
    if (workspace) args.push(workspace)
    return this.execute('ask', args)
  }
}

export const commandRunner = new CommandRunner()
