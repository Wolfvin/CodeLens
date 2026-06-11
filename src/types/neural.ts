// ============================================================
// CodeLens Neural Workspace — Unified Type System
// ============================================================

// ---- Node Types ----
export type NodeType =
  | 'class'       // CSS class
  | 'id'          // HTML ID
  | 'function'    // JS/TS/Rust/Python function
  | 'component'   // React/Vue/Svelte component
  | 'store'       // State management store
  | 'file'        // File container
  | 'package'     // External dependency
  | 'route'       // API route
  | 'env_var'     // Environment variable
  | 'variable'    // CSS variable / JS variable
  | 'secret'      // Hardcoded secret / API key
  | 'vulnerability' // CVE / security vulnerability
  | 'test'        // Test file / test function
  | 'import'      // Import statement
  | 'css_var'     // CSS custom property
  | 'keyframe'    // CSS keyframe animation

export type NodeStatus =
  | 'active'
  | 'dead'
  | 'vulnerable'
  | 'critical'
  | 'safe'
  | 'orphan'
  | 'warning'
  | 'duplicate_define'
  | 'collision'
  | 'impure'
  | 'untested'
  | 'unused'

export type Domain = 'frontend' | 'backend'

export interface GraphNode {
  id: string
  label: string
  type: NodeType
  domain: Domain
  status: NodeStatus
  file?: string
  line?: number
  clusterId?: string
  // Position (managed by D3 force)
  x?: number
  y?: number
  vx?: number
  vy?: number
  fx?: number | null
  fy?: number | null
  // Visual
  radius: number
  color: string
  // Extra data per type
  data: Record<string, unknown>
}

// ---- Edge Types ----
export type EdgeType =
  | 'references'     // CSS/JS references a class/id
  | 'calls'          // function calls function
  | 'imports'        // file imports file
  | 'defines'        // file defines symbol
  | 'depends_on'     // package dependency
  | 'routes_to'      // route maps to handler
  | 'reads'          // reads from store
  | 'writes'         // writes to store
  | 'contains'       // file contains symbol
  | 'extends'        // class extends class
  | 'implements'     // implements interface/trait
  | 'taints'         // tainted data flow
  | 'sanitizes'      // sanitizes tainted data
  | 'tests'          // test covers symbol
  | 'imports_from'   // module imports from module

export type EdgeStatus = 'active' | 'dead' | 'warning' | 'danger'

export interface GraphEdge {
  id: string
  source: string   // Always string node ID
  target: string   // Always string node ID
  type: EdgeType
  weight: number
  status: EdgeStatus
}

// ---- Cluster / Brain Region ----
export interface Cluster {
  id: string
  label: string
  icon: string
  tint: string           // hex color
  nodeIds: string[]
  cohesion: number       // 0-1 how strongly bonded
  // Computed position (center of mass)
  cx?: number
  cy?: number
}

// ---- GraphEvent — unified output from all commands ----
export type AnimationType =
  | 'pulse'
  | 'flow'
  | 'ripple'
  | 'flash'
  | 'death'
  | 'alarm'

export type AnimationIntensity = 'low' | 'medium' | 'high' | 'critical'

export interface GraphAnimation {
  type: AnimationType
  targetNodeIds: string[]
  direction?: 'up' | 'down' | 'both'
  speed?: number
  intensity?: AnimationIntensity
}

export type RiskLevel = 'safe' | 'low' | 'medium' | 'high' | 'critical'

export interface GraphEvent {
  sourceCommand: string
  timestamp: number
  nodes: GraphNode[]
  edges: GraphEdge[]
  animation: GraphAnimation
  metadata: {
    riskLevel?: RiskLevel
    category?: string
    summary?: string
  }
}

// ---- Slide-in Panel Detail ----
export interface NodeDetail {
  node: GraphNode
  code?: string
  callers?: Array<{ fn: string; file: string; line: number }>
  callees?: Array<{ fn: string; file: string; line: number }>
  references?: Array<{ file: string; line: number; source: string }>
  definedIn?: Array<{ file: string; line: number }>
  tests?: Array<{ file: string; line: number }>
  sideEffects?: string[]
  complexity?: number
  coverage?: boolean
  purity?: number
  issues?: Array<{ category: string; severity: string; message: string }>
}

// ---- Quick Action ----
export interface QuickAction {
  label: string
  command: string
  args: string[]
  icon: string
  variant: 'default' | 'warning' | 'danger'
}

// ---- Color Palette ----
export const NEURAL_COLORS = {
  // Node type colors
  class: '#f6ad55',
  id: '#fc8181',
  function: '#63b3ed',
  component: '#b794f4',
  store: '#fbd38d',
  file: '#4fd1c5',
  package: '#f687b3',
  route: '#63b3ed',
  env_var: '#fbd38d',
  variable: '#68d391',
  secret: '#e53e3e',
  vulnerability: '#fc8181',
  test: '#68d391',
  import: '#63b3ed',
  css_var: '#f687b3',
  keyframe: '#b794f4',
  // Status colors
  active: '#48bb78',
  dead: '#718096',
  vulnerable: '#ecc94b',
  critical: '#e53e3e',
  warning: '#ed8936',
  safe: '#48bb78',
  orphan: '#a0aec0',
  impure: '#ed8936',
  untested: '#ecc94b',
  unused: '#718096',
  // Edge colors
  edgeActive: '#4a5568',
  edgeDead: '#2d3748',
  edgeWarning: '#ecc94b',
  edgeDanger: '#f56565',
  // Canvas colors (dark)
  darkBg: '#0a0a0f',
  darkGrid: '#1a1a2e',
  darkDormant: '#2d3748',
  darkDormantEdge: '#1a202c',
  darkPanelBg: '#1a1a2e',
  // Canvas colors (light)
  lightBg: '#f7fafc',
  lightGrid: '#e2e8f0',
  lightDormant: '#cbd5e0',
  lightDormantEdge: '#e2e8f0',
  lightPanelBg: '#ffffff',
} as const

// ---- Region auto-detect config ----
export const REGION_PATTERNS: Array<{
  pattern: RegExp
  icon: string
  label: string
  tint: string
}> = [
  { pattern: /(auth|login|security|passport|jwt|token|session)/i, icon: '🔐', label: 'Auth', tint: '#f6ad55' },
  { pattern: /(component|ui|views|widget|modal|dialog|button|card|form|input|nav|header|footer|sidebar)/i, icon: '🎨', label: 'UI', tint: '#b794f4' },
  { pattern: /(api|route|handler|controller|endpoint|middleware|express|fastify|koa)/i, icon: '📡', label: 'API', tint: '#63b3ed' },
  { pattern: /(store|state|redux|zustand|mobX|recoil|slice|action|reducer|context)/i, icon: '💾', label: 'State', tint: '#fbd38d' },
  { pattern: /(util|helper|lib|shared|common|tools)/i, icon: '🔧', label: 'Utils', tint: '#4fd1c5' },
  { pattern: /(test|spec|__test__|mock|fixture)/i, icon: '🧪', label: 'Tests', tint: '#68d391' },
  { pattern: /(style|css|theme|design|token|scss|sass|tailwind)/i, icon: '🎨', label: 'Styles', tint: '#f687b3' },
  { pattern: /(config|setup|env|constant)/i, icon: '⚙️', label: 'Config', tint: '#a0aec0' },
  { pattern: /(db|model|migration|schema|prisma|sequelize|typeorm|entity)/i, icon: '🗄️', label: 'Data', tint: '#ed8936' },
  { pattern: /(hook|composable|use[A-Z])/i, icon: '🪝', label: 'Hooks', tint: '#38b2ac' },
  { pattern: /(service|worker|job|queue|cron|task)/i, icon: '⚡', label: 'Services', tint: '#9f7aea' },
]

// ---- WebSocket Protocol ----
export type ClientMessage =
  | { type: 'command'; command: string; args: string[] }
  | { type: 'select_node'; node_id: string }
  | { type: 'viewport'; bounds: { x: number; y: number; zoom: number } }

export type ServerMessage =
  | { type: 'graph_init'; nodes: GraphNode[]; edges: GraphEdge[] }
  | { type: 'graph_event'; event: GraphEvent }
  | { type: 'node_detail'; node_id: string; detail: NodeDetail }
  | { type: 'command_result'; command: string; result: unknown }

// ---- LOD Levels ----
export type LODLevel = 'cluster' | 'file' | 'symbol'

export const LOD_THRESHOLDS = {
  cluster: 0.3,   // zoom < 0.3 → show clusters only
  file: 0.7,      // zoom < 0.7 → show file-level
  symbol: Infinity // zoom >= 0.7 → show all symbols
}

// ---- Shape paths for Canvas2D ----
export function getNodeShape(type: NodeType): 'circle' | 'hexagon' | 'diamond' | 'triangle' | 'star' | 'square' | 'ring' {
  switch (type) {
    case 'class': return 'diamond'
    case 'id': return 'circle'
    case 'function': return 'hexagon'
    case 'component': return 'triangle'
    case 'store': return 'star'
    case 'file': return 'square'
    case 'package': return 'ring'
    case 'route': return 'hexagon'
    case 'env_var': return 'diamond'
    case 'variable': return 'circle'
    case 'secret': return 'diamond'
    case 'vulnerability': return 'hexagon'
    case 'test': return 'circle'
    case 'import': return 'square'
    case 'css_var': return 'diamond'
    case 'keyframe': return 'triangle'
    default: return 'circle'
  }
}

// ---- Analysis Result Types ----
export interface CommandDef {
  name: string
  description: string
  category: string
  icon: string
  args: Array<{ name: string; required: boolean; description: string }>
}

export type SidebarTab = 'commands' | 'workspace' | 'security' | 'quality' | 'performance' | 'css' | 'p1' | 'p2p3' | 'refactoring' | 'watch'

export interface CommandHistoryEntry {
  command: string
  args: string[]
  timestamp: number
  status: 'running' | 'success' | 'error'
  result?: unknown
}

export interface ResultTab {
  id: string
  command: string
  timestamp: number
  content: unknown
}

// ---- CodeLens Command Definitions ----
export const CODELENS_COMMANDS: CommandDef[] = [
  // Core
  { name: 'init', description: 'Initialize .codelens config', category: 'Core', icon: '🏗️', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'scan', description: 'Scan workspace and build registry', category: 'Core', icon: '🔍', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'query', description: 'Query a specific symbol by name', category: 'Core', icon: '🔎', args: [{ name: 'name', required: true, description: 'Symbol name' }, { name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'list', description: 'List entries with optional filter', category: 'Core', icon: '📋', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  // P1: Search & Trace
  { name: 'search', description: 'Search code pattern across workspace', category: 'P1', icon: '🔎', args: [{ name: 'pattern', required: true, description: 'Search pattern' }, { name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'symbols', description: 'Search symbols in registry by name', category: 'P1', icon: '🔣', args: [{ name: 'name', required: true, description: 'Symbol name' }, { name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'trace', description: 'Trace a symbol\'s call chain', category: 'P1', icon: '🔗', args: [{ name: 'name', required: true, description: 'Symbol name' }, { name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'impact', description: 'Analyze change impact for a symbol', category: 'P1', icon: '💥', args: [{ name: 'name', required: true, description: 'Symbol name' }, { name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'dependents', description: 'Module-level import tracking', category: 'P1', icon: '📦', args: [{ name: 'file', required: true, description: 'File path' }, { name: 'workspace', required: true, description: 'Workspace path' }] },
  // P2: Outline & Diff
  { name: 'outline', description: 'Get file structure outline', category: 'P2', icon: '📑', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'missing-refs', description: 'Detect CSS/HTML mismatches', category: 'P2', icon: '🔗', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'diff', description: 'Compare registry snapshots', category: 'P2', icon: '📊', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'circular', description: 'Detect circular dependencies', category: 'P2', icon: '🔄', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  // P3: Context
  { name: 'context', description: 'Get rich symbol context', category: 'P3', icon: '📝', args: [{ name: 'name', required: true, description: 'Symbol name' }, { name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'validate', description: 'Validate registry vs file system', category: 'P3', icon: '✅', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'detect', description: 'Detect frameworks in workspace', category: 'Core', icon: '🏗️', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  // Security
  { name: 'secrets', description: 'Detect hardcoded secrets/API keys', category: 'Security', icon: '🔑', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'vuln-scan', description: 'Scan dependencies for known CVEs', category: 'Security', icon: '🛡️', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'dataflow', description: 'Trace data flow source→sink', category: 'Security', icon: '🌊', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'env-check', description: 'Audit environment variables', category: 'Security', icon: '🌍', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  // Quality
  { name: 'smell', description: 'Detect code smells', category: 'Quality', icon: '👃', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'complexity', description: 'Compute cyclomatic/cognitive complexity', category: 'Quality', icon: '🧮', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'debug-leak', description: 'Detect leftover debug code', category: 'Quality', icon: '🐛', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'dead-code', description: 'Enhanced dead code detection', category: 'Quality', icon: '💀', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'a11y', description: 'Detect accessibility issues', category: 'Quality', icon: '♿', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  // Performance
  { name: 'perf-hint', description: 'Detect performance anti-patterns', category: 'Performance', icon: '⚡', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  // CSS
  { name: 'css-deep', description: 'Deep CSS analysis', category: 'CSS', icon: '🎨', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  // Refactoring
  { name: 'refactor-safe', description: 'Pre-flight rename/move check', category: 'Refactoring', icon: '🔨', args: [{ name: 'name', required: true, description: 'Symbol name' }, { name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'side-effect', description: 'Analyze function side effects', category: 'Refactoring', icon: '💥', args: [{ name: 'name', required: true, description: 'Symbol name' }, { name: 'workspace', required: true, description: 'Workspace path' }] },
  // Extra
  { name: 'stack-trace', description: 'Error propagation simulation', category: 'P1', icon: '📚', args: [{ name: 'name', required: true, description: 'Symbol name' }, { name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'test-map', description: 'Test coverage mapping', category: 'P3', icon: '🗺️', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'config-drift', description: 'Dependency drift detection', category: 'P3', icon: '📈', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'type-infer', description: 'Lightweight type inference', category: 'P3', icon: '🔮', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'ownership', description: 'Git blame code ownership', category: 'P3', icon: '👤', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'entrypoints', description: 'Map execution entry points', category: 'P3', icon: '🚪', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'api-map', description: 'Map REST/GraphQL routes to handlers', category: 'P3', icon: '🗺️', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'state-map', description: 'Track global state management', category: 'P3', icon: '💾', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'regex-audit', description: 'Audit regex for ReDoS and issues', category: 'Security', icon: '🔐', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'watch', description: 'Start file watcher for live updates', category: 'Core', icon: '👁️', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'handbook', description: 'Project handbook for AI agents', category: 'Core', icon: '📖', args: [{ name: 'workspace', required: true, description: 'Workspace path' }] },
  { name: 'ask', description: 'Natural language query router', category: 'Core', icon: '❓', args: [{ name: 'question', required: true, description: 'Natural language question' }, { name: 'workspace', required: false, description: 'Workspace path' }] },
]
