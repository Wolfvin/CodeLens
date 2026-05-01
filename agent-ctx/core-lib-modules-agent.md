# Task: Create normalizer.ts and commandRunner.ts for CodeLens Neural Workspace

## Summary
Created two core library modules that bridge the CodeLens CLI output to the neural graph visualization layer.

## Files Created

### 1. `/home/z/my-project/src/lib/normalizer.ts`
- **Class**: `Normalizer` (exported as singleton `normalizer`)
- **Main entry**: `normalize(commandName, rawOutput)` → `GraphEvent`
- **37 per-command normalizers**, all fully implemented (15-80+ lines each):
  - `scan`: Creates ALL frontend (class/id) and backend (function) nodes + edges from registry. `ripple` animation, `medium` intensity.
  - `query`: Highlights existing nodes with `pulse` animation. Handles frontend (css[]/js[] refs as edges) and backend (callers[]/callees[] as edges).
  - `trace`: Call chain with `flow` animation, direction based on trace direction. BFS chain edges.
  - `impact`: Affected nodes with `alarm` animation. Direct = `high` intensity, indirect = `medium`. Risk from output drives intensity.
  - `vuln-scan`: Package nodes for vulnerable packages, `alarm` animation at `critical` intensity. `vulnerable` status per finding.
  - `secrets`: env_var nodes with `critical` status, `alarm` animation. Exposed .env files as critical nodes.
  - Badge overlays (smell, complexity, a11y, etc.): Return existing nodes with updated status. `pulse` animation.
  - Search/symbols: Matching nodes with `flash` animation, no edges.
  - All others: Properly mapped with appropriate node types, statuses, edges, and animations.
- **Helper methods**:
  - `makeNodeId(type, name, file?, line?)`: Format like `"file:FnName:line"` or `"class:btn-primary"` or `"id:modal"`
  - `makeEdgeId(source, target, type)`: Format `"source→target:type"`
  - `statusToNodeStatus(status)`: Maps CLI status strings → `NodeStatus`
  - `mapNodeType(type, domain)`: Maps CLI type strings → `NodeType`
  - `inferDomain(filePath)`: Infers frontend/backend from file path
  - `mapRiskLevel(risk)`: Maps CLI risk strings → `RiskLevel`

### 2. `/home/z/my-project/src/lib/commandRunner.ts`
- **Class**: `CommandRunner` (exported as singleton `commandRunner`)
- **Core**: `execute(command, args)` — builds command string, runs with `execAsync`, parses JSON stdout, handles errors
- **Full graph**: `getFullGraph(workspace)` — runs scan, returns structured result
- **35+ quick methods**: One per CLI command with proper argument ordering and optional flags
- **Error handling**: Non-zero exit codes that still produce JSON are returned; genuine failures return `{ status: 'error', command, error, exitCode }`
- **Shell escaping**: `escapeShellArg()` prevents injection

## Type Dependencies
Both files import from `@/types/neural.ts` which defines:
- `GraphNode`, `GraphEdge`, `GraphEvent`, `GraphAnimation`
- `NodeType`, `NodeStatus`, `Domain`, `EdgeType`, `EdgeStatus`, `RiskLevel`
- `NEURAL_COLORS` constant, `AnimationIntensity`

## Lint Status
✅ Passes `bun run lint` cleanly with zero errors or warnings.
