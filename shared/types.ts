// ============================================================
// CodeLens — Shared Types for Main App & WebSocket Server
// ============================================================
// This module re-exports types from the main app so that
// the WebSocket server can import them without duplicating.
// ============================================================

export type {
  NodeType, NodeStatus, Domain,
  GraphNode, GraphEdge,
  EdgeType, EdgeStatus,
  Cluster,
  AnimationType, AnimationIntensity,
  GraphAnimation, RiskLevel, GraphEvent,
  NodeDetail, QuickAction,
  SidebarTab, CommandHistoryEntry, ResultTab,
  CommandDef, LODLevel,
} from '../src/types/neural'

export {
  NEURAL_COLORS, REGION_PATTERNS, LOD_THRESHOLDS,
  getNodeShape, CODELENS_COMMANDS,
} from '../src/types/neural'
