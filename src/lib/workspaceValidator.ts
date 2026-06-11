// ============================================================
// Workspace Path Validator
// ============================================================
// DEPRECATED: This module is kept for backward compatibility.
// The canonical implementation is now in @/lib/constants.ts
// which consolidates both the return-based and throw-based APIs.
//
// This file re-exports the consolidated validateWorkspace and
// provides validateWorkspaceOrThrow for routes that prefer
// exception-based control flow.
// ============================================================

export { validateWorkspace, validateWorkspaceOrThrow, FORBIDDEN_PATHS, type ValidationResult } from './constants'
