/**
 * CodeLens — AI-Native Code Intelligence — VS Code Extension
 *
 * Provides:
 *  a) Diagnostics Provider — SARIF → VS Code Diagnostics on save/open
 *  b) Code Actions Provider — Quick fixes via `codelens fix`
 *  c) Guard Integration — Pre-save safety checks
 *  d) Commands — scan, fix, guard, dashboard
 *  e) Status Bar — Health score + issue count
 *  f) Configuration — All settings wired to VS Code config
 */

const vscode = require('vscode');
const path = require('path');
const fs = require('fs');
const { parseSARIF } = require('./src/sarif_parser');
const { CodeLensClient } = require('./src/codelens_client');
const { HealthProvider } = require('./src/health_provider');

// ─── Globals ────────────────────────────────────────────────────
let client = null;
let healthProvider = null;
let diagnosticCollection = null;
let debounceTimer = null;
let lastScanTime = 0;

const CODELENS_DIAGNOSTIC_SOURCE = 'CodeLens';

// Supported language IDs
const SUPPORTED_LANGUAGES = new Set([
  'python', 'javascript', 'typescript', 'javascriptreact', 'typescriptreact'
]);

// Severity mapping: CodeLens → VS Code
const SEVERITY_MAP = {
  'error': vscode.DiagnosticSeverity.Error,
  'warning': vscode.DiagnosticSeverity.Warning,
  'note': vscode.DiagnosticSeverity.Information,
};

// ─── Activation ─────────────────────────────────────────────────

/**
 * @param {vscode.ExtensionContext} context
 */
function activate(context) {
  // Initialize client
  client = new CodeLensClient();

  // Initialize health provider (status bar)
  healthProvider = new HealthProvider();

  // Create diagnostic collection
  diagnosticCollection = vscode.languages.createDiagnosticCollection('codelens');
  context.subscriptions.push(diagnosticCollection);

  // ─── Register Providers ─────────────────────────────────────

  // Diagnostics on save/open
  const supportedDocSelector = [
    { scheme: 'file', language: 'python' },
    { scheme: 'file', language: 'javascript' },
    { scheme: 'file', language: 'typescript' },
    { scheme: 'file', language: 'javascriptreact' },
    { scheme: 'file', language: 'typescriptreact' },
  ];

  // Code Actions Provider
  context.subscriptions.push(
    vscode.languages.registerCodeActionsProvider(
      supportedDocSelector,
      new CodeLensCodeActionProvider(),
      { providedCodeActionKinds: CodeLensCodeActionProvider.providedCodeActionKinds }
    )
  );

  // ─── Register Commands ──────────────────────────────────────

  context.subscriptions.push(
    vscode.commands.registerCommand('codelens.scan', cmdScanWorkspace)
  );
  context.subscriptions.push(
    vscode.commands.registerCommand('codelens.fix', cmdFixIssues)
  );
  context.subscriptions.push(
    vscode.commands.registerCommand('codelens.guard', cmdGuardCheck)
  );
  context.subscriptions.push(
    vscode.commands.registerCommand('codelens.dashboard', cmdOpenDashboard)
  );

  // ─── File Event Listeners ──────────────────────────────────

  // Auto-scan on save
  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument(doc => {
      if (shouldScanDocument(doc) && getConfig('autoScan')) {
        debouncedScanFile(doc);
      }
    })
  );

  // Auto-scan on open
  context.subscriptions.push(
    vscode.workspace.onDidOpenTextDocument(doc => {
      if (shouldScanDocument(doc) && getConfig('autoScan')) {
        debouncedScanFile(doc);
      }
    })
  );

  // Guard: pre-save hook via will-save listener
  context.subscriptions.push(
    vscode.workspace.onWillSaveTextDocument(async event => {
      if (getConfig('enableGuard') && shouldScanDocument(event.document)) {
        await guardPreSave(event);
      }
    })
  );

  // Clean up diagnostics on close
  context.subscriptions.push(
    vscode.workspace.onDidCloseTextDocument(doc => {
      diagnosticCollection.delete(doc.uri);
    })
  );

  // Configuration change listener
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration(e => {
      if (e.affectsSection('codelens')) {
        client.invalidateCache();
        healthProvider.updateIdle();
      }
    })
  );

  // ─── Initial Scan ───────────────────────────────────────────
  const activeEditor = vscode.window.activeTextEditor;
  if (activeEditor && shouldScanDocument(activeEditor.document)) {
    debouncedScanFile(activeEditor.document);
  }

  vscode.window.showInformationMessage('CodeLens extension activated.', 'Scan Now')
    .then(choice => {
      if (choice === 'Scan Now') {
        vscode.commands.executeCommand('codelens.scan');
      }
    });
}

// ─── Deactivation ───────────────────────────────────────────────

function deactivate() {
  if (debounceTimer) {
    clearTimeout(debounceTimer);
    debounceTimer = null;
  }
  if (client) {
    client.dispose();
  }
  if (healthProvider) {
    healthProvider.dispose();
  }
  if (diagnosticCollection) {
    diagnosticCollection.dispose();
  }
}

// ─── Helpers ────────────────────────────────────────────────────

/**
 * Get a configuration value
 */
function getConfig(key, defaultValue) {
  const cfg = vscode.workspace.getConfiguration('codelens');
  return cfg.get(key, defaultValue !== undefined ? defaultValue : undefined);
}

/**
 * Check if a document should be scanned
 */
function shouldScanDocument(doc) {
  if (doc.uri.scheme !== 'file') return false;
  return SUPPORTED_LANGUAGES.has(doc.languageId);
}

/**
 * Debounced file scan — don't re-scan within the debounce window
 */
function debouncedScanFile(doc) {
  const debounceMs = getConfig('debounceMs', 2000);
  const now = Date.now();

  if (now - lastScanTime < debounceMs) {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      scanFile(doc);
      lastScanTime = Date.now();
    }, debounceMs);
    return;
  }

  scanFile(doc);
  lastScanTime = Date.now();
}

/**
 * Scan a single file and publish diagnostics
 */
async function scanFile(doc) {
  const filePath = doc.uri.fsPath;
  const workspaceFolder = vscode.workspace.getWorkspaceFolder(doc.uri);

  if (!workspaceFolder) return;

  const commands = getConfig('scanCommands', 'dead-code,secrets,smell,complexity');
  const minSeverity = getConfig('minSeverity', 'medium');
  const maxFindings = getConfig('maxFindings', 100);

  try {
    const result = await client.runSARIF(
      commands.split(',').map(c => c.trim()),
      workspaceFolder.uri.fsPath,
      minSeverity,
      maxFindings
    );

    // Parse SARIF into diagnostics
    const diagnostics = parseSARIF(result, workspaceFolder.uri.fsPath, filePath);

    // Filter to only diagnostics for this file
    const fileDiagnostics = diagnostics.filter(d => {
      const diagPath = d.filePath;
      return path.resolve(diagPath) === path.resolve(filePath);
    });

    // Map to VS Code Diagnostics
    const vscodeDiagnostics = fileDiagnostics.map(d => {
      const range = new vscode.Range(
        Math.max(0, d.line - 1),
        Math.max(0, d.column - 1),
        Math.max(0, d.endLine - 1),
        Math.max(0, d.endColumn - 1)
      );
      const diagnostic = new vscode.Diagnostic(
        range,
        d.message,
        SEVERITY_MAP[d.level] || vscode.DiagnosticSeverity.Warning
      );
      diagnostic.source = CODELENS_DIAGNOSTIC_SOURCE;
      diagnostic.code = d.ruleId || 'codelens';
      if (d.category) {
        diagnostic.relatedInformation = [];
      }
      // Store metadata for code actions
      diagnostic.data = {
        category: d.category,
        taintPath: d.taintPath,
        confidence: d.confidence,
        relatedLocations: d.relatedLocations,
        codeFlows: d.codeFlows,
      };
      return diagnostic;
    });

    // Limit to maxFindings
    const limited = vscodeDiagnostics.slice(0, maxFindings);
    diagnosticCollection.set(doc.uri, limited);

    // Update health provider
    healthProvider.updateFromDiagnostics(limited);

  } catch (err) {
    console.error('[CodeLens] scanFile error:', err.message);
    // Don't show error on every save — just log it
  }
}

/**
 * Full workspace scan
 */
async function cmdScanWorkspace() {
  const workspaceFolders = vscode.workspace.workspaceFolders;
  if (!workspaceFolders || workspaceFolders.length === 0) {
    vscode.window.showWarningMessage('No workspace folder open.');
    return;
  }

  const workspacePath = workspaceFolders[0].uri.fsPath;
  const commands = getConfig('scanCommands', 'dead-code,secrets,smell,complexity');
  const minSeverity = getConfig('minSeverity', 'medium');
  const maxFindings = getConfig('maxFindings', 100);

  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: 'CodeLens: Scanning workspace...',
      cancellable: true,
    },
    async (progress, token) => {
      progress.report({ message: `Running: ${commands}` });

      try {
        const result = await client.runSARIF(
          commands.split(',').map(c => c.trim()),
          workspacePath,
          minSeverity,
          maxFindings,
          { onProgress: (msg) => progress.report({ message: msg }), token }
        );

        if (token.isCancellationRequested) return;

        // Parse SARIF
        const allDiagnostics = parseSARIF(result, workspacePath);

        // Group diagnostics by file
        const byFile = new Map();
        for (const d of allDiagnostics) {
          const absPath = path.isAbsolute(d.filePath)
            ? d.filePath
            : path.join(workspacePath, d.filePath);
          if (!byFile.has(absPath)) byFile.set(absPath, []);
          byFile.get(absPath).push(d);
        }

        // Clear old diagnostics
        diagnosticCollection.clear();

        // Set new diagnostics
        let totalDiags = 0;
        for (const [filePath, diags] of byFile) {
          const uri = vscode.Uri.file(filePath);
          const vscodeDiagnostics = diags.slice(0, maxFindings).map(d => {
            const range = new vscode.Range(
              Math.max(0, d.line - 1),
              Math.max(0, d.column - 1),
              Math.max(0, d.endLine - 1),
              Math.max(0, d.endColumn - 1)
            );
            const diagnostic = new vscode.Diagnostic(
              range,
              d.message,
              SEVERITY_MAP[d.level] || vscode.DiagnosticSeverity.Warning
            );
            diagnostic.source = CODELENS_DIAGNOSTIC_SOURCE;
            diagnostic.code = d.ruleId || 'codelens';
            diagnostic.data = {
              category: d.category,
              taintPath: d.taintPath,
              confidence: d.confidence,
              relatedLocations: d.relatedLocations,
              codeFlows: d.codeFlows,
            };
            return diagnostic;
          });
          diagnosticCollection.set(uri, vscodeDiagnostics);
          totalDiags += vscodeDiagnostics.length;
        }

        // Update health provider
        const errors = allDiagnostics.filter(d => d.level === 'error').length;
        const warnings = allDiagnostics.filter(d => d.level === 'warning').length;
        const notes = allDiagnostics.filter(d => d.level === 'note').length;
        healthProvider.update(errors, warnings, notes, result);

        // Show summary
        const summary = `Found ${totalDiags} issue${totalDiags !== 1 ? 's' : ''} (${errors} errors, ${warnings} warnings, ${notes} notes)`;
        if (totalDiags > 0) {
          vscode.window.showWarningMessage(`CodeLens: ${summary}`, 'Show Problems')
            .then(choice => {
              if (choice === 'Show Problems') {
                vscode.commands.executeCommand('workbench.panel.markers.view.focus');
              }
            });
        } else {
          vscode.window.showInformationMessage(`CodeLens: ${summary}`);
        }

      } catch (err) {
        vscode.window.showErrorMessage(`CodeLens scan failed: ${err.message}`);
        healthProvider.updateError(err.message);
      }
    }
  );
}

/**
 * Fix issues command
 */
async function cmdFixIssues() {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showWarningMessage('No active editor.');
    return;
  }

  const doc = editor.document;
  if (!shouldScanDocument(doc)) {
    vscode.window.showWarningMessage('CodeLens fixes are not available for this file type.');
    return;
  }

  const workspaceFolder = vscode.workspace.getWorkspaceFolder(doc.uri);
  if (!workspaceFolder) return;

  // Get diagnostics for current file
  const currentDiags = diagnosticCollection.get(doc.uri) || [];
  if (currentDiags.length === 0) {
    vscode.window.showInformationMessage('CodeLens: No issues found in this file.');
    return;
  }

  // Group by category
  const byCategory = new Map();
  for (const diag of currentDiags) {
    const cat = diag.data?.category || 'general';
    if (!byCategory.has(cat)) byCategory.set(cat, []);
    byCategory.get(cat).push(diag);
  }

  // Offer quick pick of categories
  const items = [];
  for (const [cat, diags] of byCategory) {
    items.push({
      label: `${cat} (${diags.length} issue${diags.length !== 1 ? 's' : ''})`,
      description: diags.map(d => d.message).slice(0, 2).join(', '),
      category: cat,
    });
  }
  items.push({
    label: 'Fix All',
    description: `Fix all ${currentDiags.length} issues`,
    category: '__all__',
  });

  const selected = await vscode.window.showQuickPick(items, {
    placeHolder: 'Select issues to fix...',
    title: 'CodeLens: Auto-Fix',
  });

  if (!selected) return;

  const confidence = getConfig('fixMinConfidence', 0.8);
  const categories = selected.category === '__all__'
    ? Array.from(byCategory.keys())
    : [selected.category];

  try {
    const result = await client.runFix(
      doc.uri.fsPath,
      categories,
      confidence,
      workspaceFolder.uri.fsPath
    );

    if (!result || !result.fixes || result.fixes.length === 0) {
      vscode.window.showInformationMessage('CodeLens: No auto-fixes available for the selected issues.');
      return;
    }

    // Show diff preview before applying
    const fixItems = result.fixes.map((fix, i) => ({
      label: fix.description || `Fix #${i + 1}`,
      description: `Confidence: ${(fix.confidence * 100).toFixed(0)}%`,
      detail: fix.diff || fix.new_content || '',
      fix,
    }));

    const selectedFixes = await vscode.window.showQuickPick(fixItems, {
      placeHolder: 'Select fixes to apply...',
      title: 'CodeLens: Review Fixes',
      canPickMany: true,
    });

    if (!selectedFixes || selectedFixes.length === 0) return;

    // Apply fixes
    let applied = 0;
    for (const item of selectedFixes) {
      const fix = item.fix;
      try {
        if (fix.file && fix.new_content) {
          // Write the fixed content
          const edit = new vscode.WorkspaceEdit();
          const fileUri = vscode.Uri.file(fix.file);
          const originalDoc = await vscode.workspace.openTextDocument(fileUri);

          // Replace entire file content with fixed version
          edit.replace(
            fileUri,
            new vscode.Range(0, 0, originalDoc.lineCount, 0),
            fix.new_content
          );
          await vscode.workspace.applyEdit(edit);
          applied++;
        } else if (fix.file && fix.diff) {
          // Apply diff-based fix
          const applyResult = await client.applyFix(fix.id || fix.fix_id);
          if (applyResult && applyResult.applied) {
            applied++;
          }
        }
      } catch (fixErr) {
        console.error('[CodeLens] Fix apply error:', fixErr.message);
      }
    }

    vscode.window.showInformationMessage(
      `CodeLens: Applied ${applied} fix${applied !== 1 ? 'es' : ''}.`
    );

    // Re-scan the file
    await scanFile(doc);

  } catch (err) {
    vscode.window.showErrorMessage(`CodeLens fix failed: ${err.message}`);
  }
}

/**
 * Guard check command
 */
async function cmdGuardCheck() {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showWarningMessage('No active editor.');
    return;
  }

  const doc = editor.document;
  const workspaceFolder = vscode.workspace.getWorkspaceFolder(doc.uri);
  if (!workspaceFolder) return;

  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: 'CodeLens: Running guard check...',
      cancellable: false,
    },
    async () => {
      try {
        const result = await client.guardPre(
          doc.uri.fsPath,
          null,
          workspaceFolder.uri.fsPath
        );

        if (!result) {
          vscode.window.showInformationMessage('CodeLens Guard: No issues detected.');
          return;
        }

        const issues = result.issues || [];
        const warnings = result.warnings || [];
        const safe = result.safe !== false;

        if (safe && issues.length === 0 && warnings.length === 0) {
          vscode.window.showInformationMessage('CodeLens Guard: File looks clean — safe to modify.');
        } else if (issues.length > 0) {
          const msg = `CodeLens Guard: ${issues.length} critical issue${issues.length !== 1 ? 's' : ''} found!`;
          vscode.window.showErrorMessage(msg, 'Show Details')
            .then(choice => {
              if (choice === 'Show Details') {
                showGuardDetails(result);
              }
            });
        } else {
          const msg = `CodeLens Guard: ${warnings.length} warning${warnings.length !== 1 ? 's' : ''} found.`;
          vscode.window.showWarningMessage(msg, 'Show Details')
            .then(choice => {
              if (choice === 'Show Details') {
                showGuardDetails(result);
              }
            });
        }
      } catch (err) {
        vscode.window.showErrorMessage(`CodeLens guard failed: ${err.message}`);
      }
    }
  );
}

/**
 * Guard pre-save hook
 */
async function guardPreSave(event) {
  const doc = event.document;
  const workspaceFolder = vscode.workspace.getWorkspaceFolder(doc.uri);
  if (!workspaceFolder) return;

  try {
    const result = await client.guardPre(
      doc.uri.fsPath,
      null,
      workspaceFolder.uri.fsPath
    );

    if (!result) return;

    const issues = result.issues || [];
    const criticalIssues = issues.filter(i =>
      i.severity === 'critical' || i.severity === 'high'
    );

    if (criticalIssues.length > 0) {
      // Show warning — but don't block the save (VS Code doesn't allow that)
      const msg = `CodeLens Guard: ${criticalIssues.length} critical issue${criticalIssues.length !== 1 ? 's' : ''} detected before save.`;
      const choice = await vscode.window.showWarningMessage(
        msg,
        { modal: false },
        'Show Details',
        'Dismiss'
      );
      if (choice === 'Show Details') {
        showGuardDetails(result);
      }
    }
  } catch (err) {
    // Don't block save on guard errors
    console.error('[CodeLens] guardPreSave error:', err.message);
  }
}

/**
 * Show guard details in output channel
 */
function showGuardDetails(result) {
  const outputChannel = vscode.window.createOutputChannel('CodeLens Guard');
  outputChannel.clear();

  outputChannel.appendLine('═'.repeat(60));
  outputChannel.appendLine('CodeLens Guard Report');
  outputChannel.appendLine('═'.repeat(60));
  outputChannel.appendLine('');

  if (result.file) {
    outputChannel.appendLine(`File: ${result.file}`);
  }
  if (result.risk_level) {
    outputChannel.appendLine(`Risk Level: ${result.risk_level.toUpperCase()}`);
  }
  outputChannel.appendLine('');

  if (result.issues && result.issues.length > 0) {
    outputChannel.appendLine('❌ CRITICAL ISSUES:');
    for (const issue of result.issues) {
      outputChannel.appendLine(`  • [${issue.severity || '??'}] ${issue.message}`);
    }
    outputChannel.appendLine('');
  }

  if (result.warnings && result.warnings.length > 0) {
    outputChannel.appendLine('⚠️  WARNINGS:');
    for (const warn of result.warnings) {
      outputChannel.appendLine(`  • [${warn.severity || '??'}] ${warn.message}`);
    }
    outputChannel.appendLine('');
  }

  if (result.recommendations && result.recommendations.length > 0) {
    outputChannel.appendLine('📋 RECOMMENDATIONS:');
    for (const rec of result.recommendations) {
      outputChannel.appendLine(`  → ${rec}`);
    }
  }

  outputChannel.show(true);
}

/**
 * Open dashboard command
 */
async function cmdOpenDashboard() {
  const workspaceFolders = vscode.workspace.workspaceFolders;
  if (!workspaceFolders || workspaceFolders.length === 0) {
    vscode.window.showWarningMessage('No workspace folder open.');
    return;
  }

  const workspacePath = workspaceFolders[0].uri.fsPath;

  try {
    // Generate dashboard via CLI
    const result = await client.runCommand('dashboard', [workspacePath, '--open'], workspacePath);

    // Also try to open the generated file
    const dashboardPath = path.join(workspacePath, '.codelens', 'dashboard.html');
    if (fs.existsSync(dashboardPath)) {
      const uri = vscode.Uri.file(dashboardPath);
      // Open in external browser
      vscode.env.openExternal(uri);
      vscode.window.showInformationMessage('CodeLens: Dashboard opened in browser.');
    } else {
      vscode.window.showInformationMessage('CodeLens: Dashboard generated. Check .codelens/dashboard.html');
    }
  } catch (err) {
    vscode.window.showErrorMessage(`CodeLens dashboard failed: ${err.message}`);
  }
}

// ─── Code Actions Provider ──────────────────────────────────────

class CodeLensCodeActionProvider {
  static providedCodeActionKinds = [
    vscode.CodeActionKind.QuickFix,
    vscode.CodeActionKind.QuickFix.append('codelens'),
  ];

  /**
   * @param {vscode.TextDocument} document
   * @param {vscode.Range | vscode.Selection} range
   * @param {vscode.CancellationToken} token
   * @returns {vscode.CodeAction[]}
   */
  provideCodeActions(document, range, context, token) {
    const diagnostics = context.diagnostics || [];
    const codeActions = [];

    for (const diagnostic of diagnostics) {
      if (diagnostic.source !== CODELENS_DIAGNOSTIC_SOURCE) continue;
      if (!diagnostic.range.contains(range)) continue;

      // Individual fix action
      const fixAction = new vscode.CodeAction(
        `Auto-fix with CodeLens (${diagnostic.data?.category || 'general'})`,
        vscode.CodeActionKind.QuickFix.append('codelens')
      );
      fixAction.diagnostics = [diagnostic];
      fixAction.isPreferred = true;
      fixAction.command = {
        command: 'codelens.fix',
        title: 'Auto-fix with CodeLens',
        arguments: [],
      };
      codeActions.push(fixAction);

      // Guard check action
      const guardAction = new vscode.CodeAction(
        'CodeLens Guard: Check before modifying',
        vscode.CodeActionKind.QuickFix.append('codelens.guard')
      );
      guardAction.diagnostics = [diagnostic];
      guardAction.command = {
        command: 'codelens.guard',
        title: 'Guard Check',
      };
      codeActions.push(guardAction);

      // Show taint path action (if applicable)
      if (diagnostic.data?.taintPath) {
        const taintAction = new vscode.CodeAction(
          `Show taint path: ${diagnostic.data.taintPath}`,
          vscode.CodeActionKind.QuickFix.append('codelens.taint')
        );
        taintAction.diagnostics = [diagnostic];
        taintAction.command = {
          command: 'codelens.guard',
          title: 'Show Taint Path',
        };
        codeActions.push(taintAction);
      }
    }

    // Fix All action — if multiple diagnostics exist
    const codelensDiags = diagnostics.filter(d => d.source === CODELENS_DIAGNOSTIC_SOURCE);
    if (codelensDiags.length > 1) {
      const fixAllAction = new vscode.CodeAction(
        `Fix All CodeLens Issues (${codelensDiags.length})`,
        vscode.CodeActionKind.QuickFix.append('codelens.fixAll')
      );
      fixAllAction.diagnostics = codelensDiags;
      fixAllAction.command = {
        command: 'codelens.fix',
        title: 'Fix All CodeLens Issues',
      };
      codeActions.push(fixAllAction);
    }

    return codeActions;
  }
}

// ─── Exports ────────────────────────────────────────────────────

module.exports = { activate, deactivate };
