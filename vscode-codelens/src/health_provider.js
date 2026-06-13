/**
 * Health Provider — Status Bar Health Indicator
 *
 * Shows CodeLens health score and issue count in the VS Code status bar.
 * Color-coded:
 *  - Green:  No errors, no warnings
 *  - Yellow: Warnings but no errors
 *  - Red:    Errors present
 *
 * Click opens the Problems panel.
 */

const vscode = require('vscode');

// ─── Health Provider ────────────────────────────────────────────

class HealthProvider {
  constructor() {
    // Create status bar item
    this._statusBarItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Left,
      50 // Priority — left side, after language indicator
    );

    this._statusBarItem.command = 'workbench.panel.markers.view.focus';
    this._statusBarItem.name = 'CodeLens Health';

    // Initial state
    this._errors = 0;
    this._warnings = 0;
    this._notes = 0;
    this._healthScore = null;

    this.updateIdle();
    this._statusBarItem.show();
  }

  /**
   * Update from a full scan result
   * @param {number} errors
   * @param {number} warnings
   * @param {number} notes
   * @param {object} [sarifResult] - Full SARIF result for health score extraction
   */
  update(errors, warnings, notes, sarifResult) {
    this._errors = errors || 0;
    this._warnings = warnings || 0;
    this._notes = notes || 0;

    // Try to extract health score from SARIF result
    if (sarifResult && sarifResult.health_score !== undefined) {
      this._healthScore = sarifResult.health_score;
    } else if (sarifResult && sarifResult.sarif) {
      // Nested format
      this._healthScore = sarifResult.health_score;
    }

    this._render();
  }

  /**
   * Update from VS Code diagnostic array
   * @param {vscode.Diagnostic[]} diagnostics
   */
  updateFromDiagnostics(diagnostics) {
    let errors = 0, warnings = 0, notes = 0;

    for (const diag of diagnostics) {
      switch (diag.severity) {
        case vscode.DiagnosticSeverity.Error:
          errors++;
          break;
        case vscode.DiagnosticSeverity.Warning:
          warnings++;
          break;
        case vscode.DiagnosticSeverity.Information:
        case vscode.DiagnosticSeverity.Hint:
          notes++;
          break;
      }
    }

    this._errors = errors;
    this._warnings = warnings;
    this._notes = notes;
    this._render();
  }

  /**
   * Set idle state (extension loaded, no scan yet)
   */
  updateIdle() {
    this._statusBarItem.text = '$(search) CodeLens';
    this._statusBarItem.tooltip = 'CodeLens — Click to run a scan';
    this._statusBarItem.backgroundColor = undefined;
  }

  /**
   * Set error state
   * @param {string} message
   */
  updateError(message) {
    this._statusBarItem.text = '$(error) CodeLens';
    this._statusBarItem.tooltip = `CodeLens Error: ${message}`;
    this._statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
  }

  /**
   * Dispose the status bar item
   */
  dispose() {
    this._statusBarItem.dispose();
  }

  // ─── Private ───────────────────────────────────────────────

  _render() {
    const total = this._errors + this._warnings + this._notes;
    const parts = [];

    // Health score badge
    if (this._healthScore !== null) {
      const score = Math.round(this._healthScore);
      parts.push(`♥ ${score}`);
    }

    // Issue counts
    if (this._errors > 0) parts.push(`$(error) ${this._errors}`);
    if (this._warnings > 0) parts.push(`$(warning) ${this._warnings}`);
    if (this._notes > 0) parts.push(`$(info) ${this._notes}`);

    if (total === 0) {
      this._statusBarItem.text = '$(check) CodeLens: Clean';
      this._statusBarItem.tooltip = 'CodeLens — No issues found ✓';
      this._statusBarItem.backgroundColor = undefined;
    } else {
      this._statusBarItem.text = parts.join(' ');
      this._statusBarItem.tooltip = this._buildTooltip();
    }

    // Color coding
    if (this._errors > 0) {
      this._statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
    } else if (this._warnings > 0) {
      this._statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
    } else {
      this._statusBarItem.backgroundColor = undefined;
    }
  }

  _buildTooltip() {
    const lines = ['CodeLens Health Report', '─'.repeat(30)];

    if (this._healthScore !== null) {
      lines.push(`Health Score: ${Math.round(this._healthScore)}/100`);
    }

    lines.push('');
    lines.push(`  Errors:   ${this._errors}`);
    lines.push(`  Warnings: ${this._warnings}`);
    lines.push(`  Notes:    ${this._notes}`);
    lines.push('');
    lines.push('Click to open Problems panel');

    return lines.join('\n');
  }
}

// ─── Exports ────────────────────────────────────────────────────

module.exports = { HealthProvider };
