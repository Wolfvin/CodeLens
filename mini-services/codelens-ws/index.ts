// ============================================================
// CodeLens Neural Workspace — WebSocket Server
// ============================================================
// Port: 3030
// Protocol: socket.io with CORS enabled
// Maintains in-memory graph state, executes CodeLens CLI commands,
// normalizes results into GraphEvents, and streams to clients.
// ============================================================

import { createServer } from 'http'
import { Server } from 'socket.io'

// ─── Types (mirrored from src/types/neural.ts) ──────────────

type NodeType =
  | 'class' | 'id' | 'function' | 'component' | 'store'
  | 'file' | 'package' | 'route' | 'env_var' | 'variable'
  | 'secret' | 'vulnerability' | 'test' | 'import' | 'css_var' | 'keyframe'

type NodeStatus =
  | 'active' | 'dead' | 'vulnerable' | 'critical'
  | 'safe' | 'orphan' | 'warning' | 'duplicate_define' | 'collision'
  | 'impure' | 'untested' | 'unused'

type Domain = 'frontend' | 'backend'

interface GraphNode {
  id: string
  label: string
  type: NodeType
  domain: Domain
  status: NodeStatus
  file?: string
  line?: number
  clusterId?: string
  x?: number
  y?: number
  vx?: number
  vy?: number
  fx?: number | null
  fy?: number | null
  radius: number
  color: string
  data: Record<string, unknown>
}

type EdgeType =
  | 'references' | 'calls' | 'imports' | 'defines' | 'depends_on'
  | 'routes_to' | 'reads' | 'writes' | 'contains' | 'extends' | 'implements'
  | 'taints' | 'sanitizes' | 'tests' | 'imports_from'

type EdgeStatus = 'active' | 'dead' | 'warning' | 'danger'

interface GraphEdge {
  id: string
  source: string
  target: string
  type: EdgeType
  weight: number
  status: EdgeStatus
}

interface Cluster {
  id: string
  label: string
  icon: string
  tint: string
  nodeIds: string[]
  cohesion: number
  cx?: number
  cy?: number
}

type AnimationType = 'pulse' | 'flow' | 'ripple' | 'flash' | 'death' | 'alarm'
type AnimationIntensity = 'low' | 'medium' | 'high' | 'critical'

interface GraphAnimation {
  type: AnimationType
  targetNodeIds: string[]
  direction?: 'up' | 'down' | 'both'
  speed?: number
  intensity?: AnimationIntensity
}

type RiskLevel = 'safe' | 'low' | 'medium' | 'high' | 'critical'

interface GraphEvent {
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

interface NodeDetail {
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

// ─── Color Palette ──────────────────────────────────────────

const NEURAL_COLORS = {
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
  active: '#48bb78',
  dead: '#718096',
  vulnerable: '#ecc94b',
  critical: '#e53e3e',
  warning: '#ed8936',
  safe: '#48bb78',
  orphan: '#a0aec0',
  duplicate_define: '#ed8936',
  collision: '#e53e3e',
  impure: '#ed8936',
  untested: '#ecc94b',
  unused: '#718096',
} as const

// ─── Region Auto-Detect ─────────────────────────────────────

const REGION_PATTERNS: Array<{
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

function detectCluster(label: string, file?: string): { clusterId: string; label: string; icon: string; tint: string } | null {
  const text = `${label} ${file || ''}`
  for (const rp of REGION_PATTERNS) {
    if (rp.pattern.test(text)) {
      return { clusterId: rp.label.toLowerCase(), label: rp.label, icon: rp.icon, tint: rp.tint }
    }
  }
  return null
}

// ─── In-Memory Graph State ──────────────────────────────────

let graphNodes: GraphNode[] = []
let graphEdges: GraphEdge[] = []
let graphClusters: Cluster[] = []
let lastWorkspace: string | null = null

// ─── Node / Edge Helpers ────────────────────────────────────

let nodeIdCounter = 0
function nextNodeId(): string {
  return `n_${++nodeIdCounter}_${Date.now().toString(36)}`
}

let edgeIdCounter = 0
function nextEdgeId(): string {
  return `e_${++edgeIdCounter}_${Date.now().toString(36)}`
}

function makeNode(partial: Partial<GraphNode> & { id: string; label: string; type: NodeType; domain: Domain }): GraphNode {
  const clusterInfo = detectCluster(partial.label, partial.file)
  return {
    status: 'active',
    clusterId: clusterInfo?.clusterId,
    radius: partial.type === 'file' ? 12 : partial.type === 'function' ? 8 : 6,
    color: NEURAL_COLORS[partial.type] || '#718096',
    data: {},
    ...partial,
  }
}

function makeEdge(source: string, target: string, type: EdgeType, status: EdgeStatus = 'active', weight: number = 1): GraphEdge {
  return {
    id: nextEdgeId(),
    source,
    target,
    type,
    weight,
    status,
  }
}

function nodeColor(type: NodeType, status: NodeStatus): string {
  if (status !== 'active' && NEURAL_COLORS[status]) {
    return NEURAL_COLORS[status]
  }
  return NEURAL_COLORS[type] || '#718096'
}

// ─── CodeLens CLI Execution ─────────────────────────────────

const CODELENS_CLI = process.env.CODELENS_PYTHON || '/home/z/.venv/bin/python3'
const CODELENS_SCRIPT = '/home/z/my-project/skills/codelens/scripts/codelens.py'
const CLI_TIMEOUT_MS = 60_000

async function executeCodelens(command: string, args: string[]): Promise<{ success: boolean; data: any; error?: string }> {
  const fullArgs = [CODELENS_SCRIPT, command, ...args]
  console.log(`[CLI] Executing: ${CODELENS_CLI} ${fullArgs.join(' ')}`)

  try {
    const proc = Bun.spawn([CODELENS_CLI, ...fullArgs], {
      stdout: 'pipe',
      stderr: 'pipe',
    })

    const timeout = setTimeout(() => {
      try { proc.kill() } catch {}
    }, CLI_TIMEOUT_MS)

    const exitCode = await proc.exited
    clearTimeout(timeout)

    const stdout = await new Response(proc.stdout).text()
    const stderr = await new Response(proc.stderr).text()

    if (exitCode !== 0) {
      console.error(`[CLI] Exit code ${exitCode}: ${stderr.slice(0, 500)}`)
      return { success: false, data: null, error: stderr.slice(0, 1000) || `Process exited with code ${exitCode}` }
    }

    try {
      const data = JSON.parse(stdout)
      return { success: true, data }
    } catch (parseErr) {
      // Some commands may output non-JSON (e.g., watch)
      return { success: true, data: { raw: stdout.slice(0, 5000) } }
    }
  } catch (err: any) {
    console.error(`[CLI] Execution error:`, err)
    return { success: false, data: null, error: err.message || String(err) }
  }
}

// ─── Normalizers ────────────────────────────────────────────

/**
 * Normalize scan result into graph nodes/edges.
 * Scan returns: { frontend: { classes, ids }, backend: { nodes, edges } }
 */
function normalizeScan(result: any, workspace: string): { nodes: GraphNode[]; edges: GraphEdge[]; clusters: Cluster[] } {
  const nodes: GraphNode[] = []
  const edges: GraphEdge[] = []
  const clusterMap = new Map<string, Cluster>()

  // Helper to register cluster
  function ensureCluster(clusterId: string, label: string, icon: string, tint: string) {
    if (!clusterMap.has(clusterId)) {
      clusterMap.set(clusterId, {
        id: clusterId,
        label,
        icon,
        tint,
        nodeIds: [],
        cohesion: 0.8,
      })
    }
  }

  // ─── Frontend: classes ───
  const frontend = result.frontend || {}
  const classes = frontend.classes || []
  for (const cls of classes) {
    const node = makeNode({
      id: `fe_cls_${cls.name}`,
      label: `.${cls.name}`,
      type: 'class',
      domain: 'frontend',
      status: (cls.status as NodeStatus) || 'active',
      file: cls.css?.[0]?.path || cls.js?.[0]?.path,
      line: cls.css?.[0]?.line || cls.js?.[0]?.line,
      data: {
        refCount: cls.ref_count || 0,
        cssRefs: cls.css || [],
        jsRefs: cls.js || [],
      },
    })
    node.color = nodeColor('class', node.status)
    nodes.push(node)

    // Add cluster
    const ci = detectCluster(cls.name, node.file)
    if (ci) {
      ensureCluster(ci.clusterId, ci.label, ci.icon, ci.tint)
      clusterMap.get(ci.clusterId)!.nodeIds.push(node.id)
    }

    // Create edges from JS references to CSS definitions
    for (const jsRef of cls.js || []) {
      const jsFileNodeId = `fe_file_${jsRef.path}`
      // We'll create file nodes separately below
      edges.push(makeEdge(jsFileNodeId, node.id, 'references', 'active', 1))
    }
  }

  // ─── Frontend: ids ───
  const ids = frontend.ids || []
  for (const idEntry of ids) {
    const node = makeNode({
      id: `fe_id_${idEntry.name}`,
      label: `#${idEntry.name}`,
      type: 'id',
      domain: 'frontend',
      status: (idEntry.status as NodeStatus) || 'active',
      file: idEntry.defined_in_html?.[0]?.path || idEntry.css?.[0]?.path,
      line: idEntry.defined_in_html?.[0]?.line || idEntry.css?.[0]?.line,
      data: {
        refCount: idEntry.ref_count || 0,
        definedInHtml: idEntry.defined_in_html || [],
        cssRefs: idEntry.css || [],
        jsRefs: idEntry.js || [],
      },
    })
    node.color = nodeColor('id', node.status)
    nodes.push(node)

    const ci = detectCluster(idEntry.name, node.file)
    if (ci) {
      ensureCluster(ci.clusterId, ci.label, ci.icon, ci.tint)
      clusterMap.get(ci.clusterId)!.nodeIds.push(node.id)
    }
  }

  // ─── Backend: nodes ───
  const backend = result.backend || {}
  const beNodes = backend.nodes || []
  for (const bn of beNodes) {
    const node = makeNode({
      id: bn.id || `be_fn_${bn.fn}`,
      label: bn.fn,
      type: 'function',
      domain: 'backend',
      status: (bn.status as NodeStatus) || 'active',
      file: bn.file,
      line: bn.line,
      data: {
        refCount: bn.ref_count || 0,
        async: bn.async || false,
        component: bn.component || null,
        implFor: bn.impl_for || null,
        traitName: bn.trait_name || null,
        duplicateDefine: bn.duplicate_define || false,
      },
    })
    node.color = nodeColor('function', node.status)
    if (bn.component) {
      node.type = 'component'
      node.color = nodeColor('component', node.status)
    }
    nodes.push(node)

    const ci = detectCluster(bn.fn, bn.file)
    if (ci) {
      ensureCluster(ci.clusterId, ci.label, ci.icon, ci.tint)
      clusterMap.get(ci.clusterId)!.nodeIds.push(node.id)
    }

    // Create file node if not exists, and "defines" edge
    if (bn.file) {
      const fileNodeId = `be_file_${bn.file}`
      const existingFileNode = nodes.find(n => n.id === fileNodeId)
      if (!existingFileNode) {
        const fileNode = makeNode({
          id: fileNodeId,
          label: bn.file.split('/').pop() || bn.file,
          type: 'file',
          domain: 'backend',
          file: bn.file,
          data: {},
        })
        fileNode.color = nodeColor('file', 'active')
        nodes.push(fileNode)

        const fci = detectCluster(bn.file, bn.file)
        if (fci) {
          ensureCluster(fci.clusterId, fci.label, fci.icon, fci.tint)
          clusterMap.get(fci.clusterId)!.nodeIds.push(fileNode.id)
        }
      }
      edges.push(makeEdge(fileNodeId, node.id, 'defines', 'active', 2))
    }
  }

  // ─── Backend: edges ───
  const beEdges = backend.edges || []
  for (const be of beEdges) {
    edges.push(makeEdge(
      be.source,
      be.target,
      (be.type as EdgeType) || 'calls',
      (be.status as EdgeStatus) || 'active',
      be.weight || 1,
    ))
  }

  const clusters = Array.from(clusterMap.values())
  return { nodes, edges, clusters }
}

/**
 * Normalize query result into a GraphEvent.
 * Query returns: { found, type, domain, name, node?, callers?, callees?, ... }
 */
function normalizeQuery(command: string, result: any): GraphEvent {
  const targetNodeIds: string[] = []
  const nodes: GraphNode[] = []
  const edges: GraphEdge[] = []

  if (result.found) {
    if (result.domain === 'frontend') {
      const nodeId = result.type === 'class' ? `fe_cls_${result.name}` : `fe_id_${result.name}`
      targetNodeIds.push(nodeId)

      // Find existing node or create placeholder
      const existing = graphNodes.find(n => n.id === nodeId)
      if (existing) {
        nodes.push({ ...existing, status: 'active' })
      } else {
        nodes.push(makeNode({
          id: nodeId,
          label: result.type === 'class' ? `.${result.name}` : `#${result.name}`,
          type: result.type as NodeType,
          domain: 'frontend',
          status: 'active',
          data: { refCount: result.ref_count || 0 },
        }))
      }

      // Create edges for JS references
      const refs = result.js || result.css || []
      for (const ref of refs) {
        const refNodeId = `fe_file_${ref.path}`
        edges.push(makeEdge(refNodeId, nodeId, 'references', 'active', 1))
      }
    } else if (result.domain === 'backend' && result.node) {
      const nodeId = result.node.id
      targetNodeIds.push(nodeId)

      const existing = graphNodes.find(n => n.id === nodeId)
      if (existing) {
        nodes.push({ ...existing, status: 'active' })
      } else {
        nodes.push(makeNode({
          id: nodeId,
          label: result.node.fn,
          type: 'function',
          domain: 'backend',
          status: result.node.status || 'active',
          file: result.node.file,
          line: result.node.line,
          data: {},
        }))
      }

      // Caller edges
      for (const caller of result.callers || []) {
        const callerId = caller.id || `be_fn_${caller.fn}`
        targetNodeIds.push(callerId)
        edges.push(makeEdge(callerId, nodeId, 'calls', 'active', 2))
      }

      // Callee edges
      for (const callee of result.callees || []) {
        const calleeId = callee.id || `be_fn_${callee.fn}`
        targetNodeIds.push(calleeId)
        edges.push(makeEdge(nodeId, calleeId, 'calls', 'active', 2))
      }
    }
  }

  return {
    sourceCommand: command,
    timestamp: Date.now(),
    nodes,
    edges,
    animation: {
      type: 'pulse',
      targetNodeIds,
      intensity: 'medium',
    },
    metadata: {
      riskLevel: 'safe',
      category: result.type || 'query',
      summary: result.found
        ? `Found ${result.type} "${result.name}" in ${result.domain} domain`
        : `Symbol "${result.name}" not found`,
    },
  }
}

/**
 * Normalize trace result into a GraphEvent.
 * Trace returns: { root, chain: [{ node, direction, depth }, ...] }
 */
function normalizeTrace(command: string, result: any): GraphEvent {
  const targetNodeIds: string[] = []
  const nodes: GraphNode[] = []
  const edges: GraphEdge[] = []

  // Root node
  if (result.root) {
    const rootId = result.root.id || `be_fn_${result.root.fn}`
    targetNodeIds.push(rootId)

    const existing = graphNodes.find(n => n.id === rootId)
    if (existing) {
      nodes.push({ ...existing, status: 'active' })
    } else {
      nodes.push(makeNode({
        id: rootId,
        label: result.root.fn || result.root.name || 'root',
        type: 'function',
        domain: 'backend',
        status: 'active',
        file: result.root.file,
        line: result.root.line,
        data: {},
      }))
    }
  }

  // Chain
  let prevId = result.root?.id
  for (const step of result.chain || result.trace || []) {
    const stepId = step.id || step.node_id || `be_fn_${step.fn || step.name}`
    targetNodeIds.push(stepId)

    const existing = graphNodes.find(n => n.id === stepId)
    if (existing) {
      nodes.push({ ...existing, status: 'active' })
    } else {
      nodes.push(makeNode({
        id: stepId,
        label: step.fn || step.name || 'unknown',
        type: 'function',
        domain: 'backend',
        status: 'active',
        file: step.file,
        line: step.line,
        data: { depth: step.depth, direction: step.direction },
      }))
    }

    // Create edge from prev → current
    if (prevId && stepId !== prevId) {
      const direction = step.direction || 'up'
      if (direction === 'up') {
        edges.push(makeEdge(stepId, prevId, 'calls', 'active', 2))
      } else if (direction === 'down') {
        edges.push(makeEdge(prevId, stepId, 'calls', 'active', 2))
      } else {
        edges.push(makeEdge(prevId, stepId, 'calls', 'active', 2))
      }
    }
    prevId = stepId
  }

  return {
    sourceCommand: command,
    timestamp: Date.now(),
    nodes,
    edges,
    animation: {
      type: 'flow',
      targetNodeIds,
      direction: result.direction || 'both',
      speed: 1.5,
      intensity: 'high',
    },
    metadata: {
      riskLevel: 'low',
      category: 'trace',
      summary: `Traced ${targetNodeIds.length} nodes from "${result.root?.fn || result.root?.name || 'root'}"`,
    },
  }
}

/**
 * Normalize impact result into a GraphEvent.
 * Impact returns: { target, affected: [...], risk_level, ... }
 */
function normalizeImpact(command: string, result: any): GraphEvent {
  const targetNodeIds: string[] = []
  const nodes: GraphNode[] = []
  const edges: GraphEdge[] = []

  // Target node
  if (result.target || result.symbol) {
    const t = result.target || result.symbol
    const targetId = t.id || `be_fn_${t.fn || t.name}`
    targetNodeIds.push(targetId)

    const existing = graphNodes.find(n => n.id === targetId)
    if (existing) {
      nodes.push({ ...existing, status: 'critical' })
    } else {
      nodes.push(makeNode({
        id: targetId,
        label: t.fn || t.name || 'target',
        type: 'function',
        domain: 'backend',
        status: 'critical',
        file: t.file,
        line: t.line,
        data: {},
      }))
    }
  }

  // Affected nodes
  for (const aff of result.affected || result.impacted || []) {
    const affId = aff.id || `be_fn_${aff.fn || aff.name}`
    targetNodeIds.push(affId)

    const existing = graphNodes.find(n => n.id === affId)
    if (existing) {
      nodes.push({ ...existing, status: 'warning' })
    } else {
      nodes.push(makeNode({
        id: affId,
        label: aff.fn || aff.name || 'affected',
        type: 'function',
        domain: 'backend',
        status: 'warning',
        file: aff.file,
        line: aff.line,
        data: { impactType: aff.type || aff.impact_type || 'direct' },
      }))
    }

    // Edge from target to affected
    const targetId = result.target?.id || result.symbol?.id || targetNodeIds[0]
    if (targetId && affId !== targetId) {
      edges.push(makeEdge(targetId, affId, 'calls', 'warning', 2))
    }
  }

  const riskLevel = (result.risk_level || result.riskLevel || 'medium') as RiskLevel

  return {
    sourceCommand: command,
    timestamp: Date.now(),
    nodes,
    edges,
    animation: {
      type: riskLevel === 'critical' || riskLevel === 'high' ? 'alarm' : 'ripple',
      targetNodeIds,
      direction: 'down',
      speed: riskLevel === 'critical' ? 3 : 1.5,
      intensity: riskLevel === 'critical' ? 'critical' : riskLevel === 'high' ? 'high' : 'medium',
    },
    metadata: {
      riskLevel,
      category: 'impact',
      summary: `Impact analysis: ${targetNodeIds.length - 1} nodes affected, risk=${riskLevel}`,
    },
  }
}

/**
 * Generic normalizer for other commands.
 */
function normalizeGeneric(command: string, result: any): GraphEvent {
  const targetNodeIds: string[] = []
  const nodes: GraphNode[] = []
  const edges: GraphEdge[] = []

  // Try to extract results and create nodes
  const items = result.results ?? result.findings ?? result.issues ?? result.hints ?? []
  for (const item of Array.isArray(items) ? items : []) {
    const name = item.fn ?? item.name ?? item.symbol ?? item.package ?? item.file ?? 'unknown'
    const file = item.file ?? item.path
    const line = item.line
    const nodeType: NodeType = item.class ? 'class' : item.variable ? 'variable' : 'function'
    const severity = item.severity ?? 'info'
    const status: NodeStatus = severity === 'critical' ? 'critical' : severity === 'high' ? 'warning' : 'active'
    const nodeId = `gen_${command}_${name}_${file ?? ''}_${line ?? 0}`.replace(/[^a-zA-Z0-9_-]/g, '_')

    const node = makeNode({
      id: nodeId,
      label: name,
      type: nodeType,
      domain: file?.includes('.css') || file?.includes('.tsx') || file?.includes('.vue') ? 'frontend' : 'backend',
      status,
      file,
      line,
      data: { category: item.category ?? command, severity, message: item.message ?? item.description ?? '' },
    })
    node.color = nodeColor(nodeType, status)
    nodes.push(node)
    targetNodeIds.push(nodeId)
  }

  return {
    sourceCommand: command,
    timestamp: Date.now(),
    nodes,
    edges,
    animation: {
      type: targetNodeIds.length > 0 ? 'flash' : 'pulse',
      targetNodeIds,
      intensity: 'low',
    },
    metadata: {
      category: command,
      summary: items.length > 0
        ? `Command "${command}" found ${items.length} result(s)`
        : `Command "${command}" executed`,
    },
  }
}

/**
 * Main normalizer dispatcher.
 */
function normalizeCommand(command: string, cliResult: any): GraphEvent {
  switch (command) {
    case 'query':
    case 'symbols':
      return normalizeQuery(command, cliResult)
    case 'trace':
      return normalizeTrace(command, cliResult)
    case 'impact':
      return normalizeImpact(command, cliResult)
    default:
      return normalizeGeneric(command, cliResult)
  }
}

// ─── NodeDetail Computation ─────────────────────────────────

function computeNodeDetail(nodeId: string): NodeDetail | null {
  const node = graphNodes.find(n => n.id === nodeId)
  if (!node) return null

  const detail: NodeDetail = { node }

  // Find callers (edges pointing to this node with 'calls' type)
  const callers: Array<{ fn: string; file: string; line: number }> = []
  const callees: Array<{ fn: string; file: string; line: number }> = []
  const references: Array<{ file: string; line: number; source: string }> = []
  const definedIn: Array<{ file: string; line: number }> = []

  for (const edge of graphEdges) {
    const srcId = typeof edge.source === 'string' ? edge.source : (edge.source as GraphNode).id
    const tgtId = typeof edge.target === 'string' ? edge.target : (edge.target as GraphNode).id

    if (tgtId === nodeId && edge.type === 'calls') {
      const srcNode = graphNodes.find(n => n.id === srcId)
      if (srcNode) {
        callers.push({
          fn: srcNode.label,
          file: srcNode.file || '',
          line: srcNode.line || 0,
        })
      }
    }

    if (srcId === nodeId && edge.type === 'calls') {
      const tgtNode = graphNodes.find(n => n.id === tgtId)
      if (tgtNode) {
        callees.push({
          fn: tgtNode.label,
          file: tgtNode.file || '',
          line: tgtNode.line || 0,
        })
      }
    }

    if (tgtId === nodeId && edge.type === 'references') {
      const srcNode = graphNodes.find(n => n.id === srcId)
      if (srcNode) {
        references.push({
          file: srcNode.file || '',
          line: srcNode.line || 0,
          source: srcNode.label,
        })
      }
    }

    if (tgtId === nodeId && edge.type === 'defines') {
      const srcNode = graphNodes.find(n => n.id === srcId)
      if (srcNode) {
        definedIn.push({
          file: srcNode.file || '',
          line: srcNode.line || 0,
        })
      }
    }
  }

  if (callers.length > 0) detail.callers = callers
  if (callees.length > 0) detail.callees = callees
  if (references.length > 0) detail.references = references
  if (definedIn.length > 0) detail.definedIn = definedIn

  // Add data from node.data
  if (node.data.sideEffects) detail.sideEffects = node.data.sideEffects as string[]
  if (node.data.complexity) detail.complexity = node.data.complexity as number
  if (node.data.coverage !== undefined) detail.coverage = node.data.coverage as boolean
  if (node.data.purity !== undefined) detail.purity = node.data.purity as number
  if (node.data.issues) detail.issues = node.data.issues as Array<{ category: string; severity: string; message: string }>

  // Add definedIn from node data if frontend
  if (node.domain === 'frontend') {
    const data = node.data as any
    if (data.definedInHtml) {
      detail.definedIn = data.definedInHtml.map((d: any) => ({
        file: d.path || '',
        line: d.line || 0,
      }))
    }
    if (data.cssRefs) {
      detail.references = [
        ...(detail.references || []),
        ...data.cssRefs.map((r: any) => ({
          file: r.path || '',
          line: r.line || 0,
          source: 'css',
        })),
      ]
    }
    if (data.jsRefs) {
      detail.references = [
        ...(detail.references || []),
        ...data.jsRefs.map((r: any) => ({
          file: r.path || '',
          line: r.line || 0,
          source: 'js',
        })),
      ]
    }
  }

  return detail
}

// ─── Update In-Memory Graph ─────────────────────────────────

function updateGraphFromEvent(event: GraphEvent) {
  // Add/update nodes
  for (const node of event.nodes) {
    const idx = graphNodes.findIndex(n => n.id === node.id)
    if (idx >= 0) {
      // Merge: update status, keep position
      graphNodes[idx] = {
        ...graphNodes[idx],
        ...node,
        x: graphNodes[idx].x,
        y: graphNodes[idx].y,
        vx: graphNodes[idx].vx,
        vy: graphNodes[idx].vy,
      }
    } else {
      graphNodes.push(node)
    }
  }

  // Add/update edges (dedupe by source+target+type)
  for (const edge of event.edges) {
    const srcId = typeof edge.source === 'string' ? edge.source : (edge.source as GraphNode).id
    const tgtId = typeof edge.target === 'string' ? edge.target : (edge.target as GraphNode).id
    const exists = graphEdges.some(e => {
      const eSrc = typeof e.source === 'string' ? e.source : (e.source as GraphNode).id
      const eTgt = typeof e.target === 'string' ? e.target : (e.target as GraphNode).id
      return eSrc === srcId && eTgt === tgtId && e.type === edge.type
    })
    if (!exists) {
      graphEdges.push({ ...edge, source: srcId, target: tgtId })
    }
  }
}

function replaceGraphFromScan(nodes: GraphNode[], edges: GraphEdge[], clusters: Cluster[]) {
  graphNodes = nodes
  graphEdges = edges
  graphClusters = clusters
}

// ─── WebSocket Server ───────────────────────────────────────

const httpServer = createServer()
const io = new Server(httpServer, {
  path: '/',
  cors: {
    origin: process.env.CORS_ORIGIN || '*',
    methods: ['GET', 'POST'],
  },
  pingTimeout: 60000,
  pingInterval: 25000,
})

const commandTimestamps = new Map<string, number>()
const COMMAND_RATE_LIMIT_MS = 2000 // 2 seconds between commands

io.on('connection', (socket) => {
  console.log(`[WS] Client connected: ${socket.id}`)

  // Send existing graph data on connection
  if (graphNodes.length > 0) {
    socket.emit('graph_init', {
      nodes: graphNodes,
      edges: graphEdges,
    })
    console.log(`[WS] Sent graph_init with ${graphNodes.length} nodes, ${graphEdges.length} edges`)
  }

  // ─── Handle 'command' ──────────────────────────────────
  socket.on('command', async (data: { command: string; args: string[] }) => {
    const { command, args } = data
    console.log(`[WS] command: ${command} ${args.join(' ')}`)

    // Rate limiting
    const lastCmd = commandTimestamps.get(socket.id) ?? 0
    if (Date.now() - lastCmd < COMMAND_RATE_LIMIT_MS) {
      socket.emit('command_result', { command, result: { success: false, error: 'Rate limited. Please wait before sending another command.' } })
      return
    }
    commandTimestamps.set(socket.id, Date.now())

    try {
      const result = await executeCodelens(command, args)

      if (!result.success) {
        socket.emit('command_result', {
          command,
          result: { success: false, error: result.error },
        })
        return
      }

      // Emit raw command result
      socket.emit('command_result', {
        command,
        result: result.data,
      })

      // Handle scan specially: replace entire graph
      if (command === 'scan') {
        const normalized = normalizeScan(result.data, args[0] || '')
        replaceGraphFromScan(normalized.nodes, normalized.edges, normalized.clusters)

        // Store workspace for future commands
        lastWorkspace = args[0] || lastWorkspace

        // Emit graph_init with full graph (broadcast to all clients)
        io.emit('graph_init', {
          nodes: graphNodes,
          edges: graphEdges,
        })

        // Also emit a graph_event for the scan (broadcast to all clients)
        const scanEvent: GraphEvent = {
          sourceCommand: 'scan',
          timestamp: Date.now(),
          nodes: graphNodes,
          edges: graphEdges,
          animation: {
            type: 'pulse',
            targetNodeIds: graphNodes.map(n => n.id),
            intensity: 'low',
          },
          metadata: {
            riskLevel: 'safe',
            category: 'scan',
            summary: `Scanned workspace: ${graphNodes.length} nodes, ${graphEdges.length} edges`,
          },
        }
        io.emit('graph_event', { event: scanEvent })
        console.log(`[WS] Scan complete: ${graphNodes.length} nodes, ${graphEdges.length} edges, ${graphClusters.length} clusters`)
      } else {
        // Normalize other commands into GraphEvent
        const event = normalizeCommand(command, result.data)
        updateGraphFromEvent(event)
        io.emit('graph_event', { event })
        console.log(`[WS] Event emitted for "${command}": ${event.nodes.length} nodes, ${event.edges.length} edges`)
      }
    } catch (err: any) {
      console.error(`[WS] Error handling command "${command}":`, err)
      socket.emit('command_result', {
        command,
        result: { success: false, error: err.message || String(err) },
      })
    }
  })

  // ─── Handle 'select_node' ──────────────────────────────
  socket.on('select_node', (data: { node_id: string }) => {
    const { node_id } = data
    console.log(`[WS] select_node: ${node_id}`)

    const detail = computeNodeDetail(node_id)
    if (detail) {
      socket.emit('node_detail', { node_id, detail })
    } else {
      // Try to run a query command to get detail
      if (lastWorkspace) {
        // Extract name from node_id patterns
        let queryName = node_id
        if (node_id.startsWith('fe_cls_')) queryName = node_id.replace('fe_cls_', '')
        else if (node_id.startsWith('fe_id_')) queryName = node_id.replace('fe_id_', '')
        else if (node_id.startsWith('be_fn_')) queryName = node_id.replace('be_fn_', '')

        // Query for detail asynchronously
        executeCodelens('query', [queryName, lastWorkspace]).then(result => {
          if (result.success && result.data.found) {
            // Create or update the node from query result
            const qResult = result.data
            let node: GraphNode
            if (qResult.domain === 'backend' && qResult.node) {
              node = makeNode({
                id: qResult.node.id || node_id,
                label: qResult.node.fn || queryName,
                type: 'function',
                domain: 'backend',
                status: qResult.node.status || 'active',
                file: qResult.node.file,
                line: qResult.node.line,
                data: {},
              })
            } else {
              node = makeNode({
                id: node_id,
                label: queryName,
                type: (qResult.type as NodeType) || 'function',
                domain: (qResult.domain as Domain) || 'backend',
                status: 'active',
                data: {},
              })
            }

            const detail: NodeDetail = {
              node,
              callers: qResult.callers?.map((c: any) => ({
                fn: c.fn || c.name || 'unknown',
                file: c.file || '',
                line: c.line || 0,
              })),
              callees: qResult.callees?.map((c: any) => ({
                fn: c.fn || c.name || 'unknown',
                file: c.file || '',
                line: c.line || 0,
              })),
            }

            // Update graph
            const idx = graphNodes.findIndex(n => n.id === node_id)
            if (idx >= 0) {
              graphNodes[idx] = { ...graphNodes[idx], ...node }
            }

            socket.emit('node_detail', { node_id, detail })
          }
        }).catch(() => {
          // Silently ignore query errors for detail fetch
        })
      }
    }
  })

  // ─── Handle 'viewport' ─────────────────────────────────
  socket.on('viewport', (data: { bounds: { x: number; y: number; zoom: number } }) => {
    // Viewport tracking — could be used for LOD in the future
    // For now, just log at debug level
  })

  // ─── Disconnect ────────────────────────────────────────
  socket.on('disconnect', () => {
    console.log(`[WS] Client disconnected: ${socket.id}`)
  })

  socket.on('error', (error) => {
    console.error(`[WS] Socket error (${socket.id}):`, error)
  })
})

// ─── Start Server ──────────────────────────────────────────

const PORT = 3030
httpServer.listen(PORT, () => {
  console.log(`[CodeLens WS] WebSocket server running on port ${PORT}`)
  console.log(`[CodeLens WS] CLI path: ${CODELENS_CLI} ${CODELENS_SCRIPT}`)
  console.log(`[CodeLens WS] Timeout: ${CLI_TIMEOUT_MS}ms`)
})

// ─── Graceful Shutdown ──────────────────────────────────────

process.on('SIGTERM', () => {
  console.log('[CodeLens WS] Received SIGTERM, shutting down...')
  io.close()
  httpServer.close(() => {
    console.log('[CodeLens WS] Server closed')
    process.exit(0)
  })
})

process.on('SIGINT', () => {
  console.log('[CodeLens WS] Received SIGINT, shutting down...')
  io.close()
  httpServer.close(() => {
    console.log('[CodeLens WS] Server closed')
    process.exit(0)
  })
})
