/**
 * SARIF v2.1.0 Parser for CodeLens VS Code Extension
 *
 * Parses SARIF (Static Analysis Results Interchange Format) output
 * from `codelens check --sarif` into structured diagnostic objects
 * ready for VS Code Diagnostic conversion.
 *
 * Handles:
 *  - Results with locations, messages, severity levels
 *  - Related locations (for taint paths)
 *  - Code flows (for data flow visualization)
 *  - Rule metadata extraction
 *
 * SARIF Spec: https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html
 */

const path = require('path');

// ─── Severity Mapping (SARIF level → CodeLens level) ────────────

const SARIF_LEVEL_MAP = {
  'error': 'error',
  'warning': 'warning',
  'note': 'note',
  'none': 'note',
};

// ─── Main Parser ────────────────────────────────────────────────

/**
 * Parse SARIF v2.1.0 output into flat diagnostic objects.
 *
 * @param {object|string} sarifData - SARIF JSON object or string
 * @param {string} workspaceRoot - Absolute workspace root path
 * @param {string} [filterFile] - If provided, only return diagnostics for this file
 * @returns {Array<object>} Array of diagnostic objects with:
 *   { filePath, line, column, endLine, endColumn, message, level, ruleId, category, taintPath, confidence, relatedLocations, codeFlows }
 */
function parseSARIF(sarifData, workspaceRoot, filterFile) {
  if (!sarifData) return [];

  // Parse string input
  let sarif;
  if (typeof sarifData === 'string') {
    try {
      sarif = JSON.parse(sarifData);
    } catch (e) {
      console.error('[CodeLens SARIF] Failed to parse JSON:', e.message);
      return [];
    }
  } else {
    sarif = sarifData;
  }

  // Handle nested sarif key (from check command output: { sarif: {...} })
  if (sarif.sarif && sarif.sarif.version) {
    sarif = sarif.sarif;
  }

  // Validate SARIF structure
  if (!sarif.runs || !Array.isArray(sarif.runs)) {
    return [];
  }

  const diagnostics = [];

  for (const run of sarif.runs) {
    // Extract rule definitions for metadata lookup
    const ruleMap = buildRuleMap(run.tool?.driver?.rules || []);

    // Parse originalUriBaseIds for URI resolution
    const uriBaseIds = run.originalUriBaseIds || {};
    const baseUri = resolveBaseUri(uriBaseIds, workspaceRoot);

    // Process results
    const results = run.results || [];
    for (const result of results) {
      const diag = parseResult(result, ruleMap, baseUri, workspaceRoot);
      if (diag) {
        // Filter by file if requested
        if (filterFile) {
          const diagAbs = path.isAbsolute(diag.filePath)
            ? diag.filePath
            : path.resolve(workspaceRoot, diag.filePath);
          const filterAbs = path.isAbsolute(filterFile)
            ? filterFile
            : path.resolve(workspaceRoot, filterFile);
          if (path.normalize(diagAbs) !== path.normalize(filterAbs)) {
            continue;
          }
        }
        diagnostics.push(diag);
      }
    }
  }

  return diagnostics;
}

// ─── Result Parser ──────────────────────────────────────────────

/**
 * Parse a single SARIF result object
 */
function parseResult(result, ruleMap, baseUri, workspaceRoot) {
  if (!result.locations || result.locations.length === 0) {
    return null;
  }

  // Extract primary location
  const primaryLocation = result.locations[0];
  const physLoc = primaryLocation?.physicalLocation;
  if (!physLoc) return null;

  // Resolve file path
  const artifactUri = physLoc.artifactLocation?.uri || '';
  const uriBaseId = physLoc.artifactLocation?.uriBaseId;
  let filePath = resolveFilePath(artifactUri, uriBaseId, baseUri, workspaceRoot);

  // Extract region (line/column)
  const region = physLoc.region || {};
  const line = region.startLine || 1;
  const column = region.startColumn || 1;
  const endLine = region.endLine || line;
  const endColumn = region.endColumn || column + 1;

  // Extract message
  const message = extractMessage(result.message) ||
    extractMessage(primaryLocation.message) ||
    'CodeLens finding';

  // Extract level
  const level = SARIF_LEVEL_MAP[result.level] || 'warning';

  // Extract rule ID
  const ruleId = result.ruleId ||
    (result.ruleIndex !== undefined && ruleMap[result.ruleIndex]?.id) ||
    'codelens/general';

  // Extract rule metadata
  const ruleInfo = findRuleById(ruleId, ruleMap);
  const category = ruleInfo?.shortDescription?.text ||
    result.properties?.category ||
    inferCategory(ruleId);

  // Extract taint path from properties
  const taintPath = result.properties?.taintPath || null;

  // Extract confidence from properties
  const confidence = result.properties?.confidence || null;

  // Parse related locations (taint sources, etc.)
  const relatedLocations = parseRelatedLocations(
    result.relatedLocations || [],
    baseUri,
    workspaceRoot
  );

  // Parse code flows (data flow visualization)
  const codeFlows = parseCodeFlows(
    result.codeFlows || [],
    baseUri,
    workspaceRoot
  );

  return {
    filePath,
    line,
    column,
    endLine,
    endColumn,
    message,
    level,
    ruleId,
    category,
    taintPath,
    confidence,
    relatedLocations,
    codeFlows,
  };
}

// ─── Related Locations Parser ───────────────────────────────────

/**
 * Parse SARIF relatedLocations array
 */
function parseRelatedLocations(locations, baseUri, workspaceRoot) {
  if (!locations || !Array.isArray(locations)) return [];

  return locations.map(loc => {
    const physLoc = loc.physicalLocation || {};
    const artifactUri = physLoc.artifactLocation?.uri || '';
    const region = physLoc.region || {};
    const msg = extractMessage(loc.message) || '';

    return {
      filePath: resolveFilePath(artifactUri, physLoc.artifactLocation?.uriBaseId, baseUri, workspaceRoot),
      line: region.startLine || 1,
      column: region.startColumn || 1,
      message: msg,
    };
  }).filter(loc => loc.filePath);
}

// ─── Code Flows Parser ──────────────────────────────────────────

/**
 * Parse SARIF codeFlows array for data flow visualization
 */
function parseCodeFlows(codeFlows, baseUri, workspaceRoot) {
  if (!codeFlows || !Array.isArray(codeFlows)) return [];

  const flows = [];

  for (const flow of codeFlows) {
    const threadFlows = flow.threadFlows || [];
    for (const tf of threadFlows) {
      const locations = (tf.locations || []).map(tfl => {
        const loc = tfl.location || {};
        const physLoc = loc.physicalLocation || {};
        const artifactUri = physLoc.artifactLocation?.uri || '';
        const region = physLoc.region || {};
        const msg = extractMessage(loc.message) || '';

        return {
          filePath: resolveFilePath(artifactUri, physLoc.artifactLocation?.uriBaseId, baseUri, workspaceRoot),
          line: region.startLine || 1,
          column: region.startColumn || 1,
          message: msg,
          nestingLevel: tfl.nestingLevel || 0,
        };
      });
      flows.push({ locations });
    }
  }

  return flows;
}

// ─── Helpers ────────────────────────────────────────────────────

/**
 * Build a map of rule index → rule definition
 */
function buildRuleMap(rules) {
  const map = {};
  for (let i = 0; i < rules.length; i++) {
    map[i] = rules[i];
  }
  return map;
}

/**
 * Find a rule by its ID in the rule map
 */
function findRuleById(ruleId, ruleMap) {
  for (const idx of Object.keys(ruleMap)) {
    if (ruleMap[idx].id === ruleId) {
      return ruleMap[idx];
    }
  }
  return null;
}

/**
 * Extract text from a SARIF message object
 */
function extractMessage(messageObj) {
  if (!messageObj) return '';
  if (typeof messageObj === 'string') return messageObj;
  if (messageObj.text) return messageObj.text;
  if (messageObj.markdown) return messageObj.markdown;
  return '';
}

/**
 * Resolve the base URI from originalUriBaseIds
 */
function resolveBaseUri(uriBaseIds, fallback) {
  if (!uriBaseIds) return fallback;

  // Try %SRCROOT% first (standard CodeLens SARIF output)
  const srcRoot = uriBaseIds['%SRCROOT%'];
  if (srcRoot?.uri) {
    const uri = srcRoot.uri;
    if (uri.startsWith('file://')) {
      return uri.replace('file://', '').replace(/\/$/, '');
    }
    return uri.replace(/\/$/, '');
  }

  return fallback;
}

/**
 * Resolve a file path from SARIF artifact URI
 */
function resolveFilePath(artifactUri, uriBaseId, baseUri, workspaceRoot) {
  if (!artifactUri) return '';

  // Already absolute
  if (path.isAbsolute(artifactUri)) return artifactUri;

  // file:// URI
  if (artifactUri.startsWith('file://')) {
    return artifactUri.replace('file://', '');
  }

  // Relative to base URI
  if (baseUri && uriBaseId) {
    return path.resolve(baseUri, artifactUri);
  }

  // Relative to workspace root
  return path.resolve(workspaceRoot || process.cwd(), artifactUri);
}

/**
 * Infer category from rule ID (e.g., "codelens/secrets/api-key" → "secrets")
 */
function inferCategory(ruleId) {
  if (!ruleId) return 'general';
  const parts = ruleId.split('/');
  if (parts.length >= 2) return parts[1];
  return 'general';
}

// ─── Exports ────────────────────────────────────────────────────

module.exports = { parseSARIF };
