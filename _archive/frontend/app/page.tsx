'use client'

import React, { useState, useCallback, useEffect, useRef, useMemo } from 'react'
import { io, Socket } from 'socket.io-client'
import { ThemeProvider, useTheme } from '@/components/shared/ThemeProvider'
import { TopBar } from '@/components/topbar/TopBar'
import NeuralCanvas from '@/components/canvas/NeuralCanvas'
import { CanvasSkeleton } from '@/components/canvas/CanvasSkeleton'
import { NodeContextMenu } from '@/components/canvas/NodeContextMenu'
import { SlideInPanel } from '@/components/panel/SlideInPanel'
import { LeftSidebar } from '@/components/sidebar/LeftSidebar'
import { CommandPalette } from '@/components/sidebar/CommandPalette'
import { ResultPanel } from '@/components/bottom/ResultPanel'
import { graphStore } from '@/lib/graphStore'
import { clusterEngine } from '@/lib/clusterEngine'
import { useAnalysisStore } from '@/lib/analysisStore'
import { ErrorBoundary } from '@/components/shared/ErrorBoundary'
import type {
  GraphNode,
  GraphEdge,
  Cluster,
  GraphAnimation,
  NodeDetail,
  QuickAction,
  GraphEvent,
  NodeType,
} from '@/types/neural'
import { getNodeShape } from '@/types/neural'

// ============================================================
// Demo Data Generator
// ============================================================

function generateDemoData(): { nodes: GraphNode[]; edges: GraphEdge[]; clusters: Cluster[] } {
  const NC = {
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
  }

  // Spread positions across canvas
  const cx = 600
  const cy = 400
  const spread = 350

  // Helper to position nodes in a region
  function regionPos(regionCx: number, regionCy: number, count: number, idx: number) {
    const angle = (2 * Math.PI * idx) / count + Math.random() * 0.3
    const r = 60 + Math.random() * 80
    return {
      x: regionCx + Math.cos(angle) * r,
      y: regionCy + Math.sin(angle) * r,
    }
  }

  // Cluster centers
  const authCenter = { x: cx - spread * 1.1, y: cy - spread * 0.4 }
  const uiCenter = { x: cx, y: cy - spread * 0.7 }
  const apiCenter = { x: cx + spread * 0.5, y: cy - spread * 0.1 }
  const stateCenter = { x: cx + spread * 1.1, y: cy + spread * 0.3 }
  const configCenter = { x: cx - spread * 0.3, y: cy + spread * 0.6 }

  const nodes: GraphNode[] = []

  // --- Auth region ---
  const authNodes = [
    { id: 'fn-verify_token', label: 'verify_token', type: 'function' as const, domain: 'backend' as const, status: 'active' as const, file: 'src/auth/jwt.ts', line: 12, radius: 12 },
    { id: 'fn-handleLogin', label: 'handleLogin', type: 'function' as const, domain: 'backend' as const, status: 'active' as const, file: 'src/auth/handler.ts', line: 8, radius: 14 },
    { id: 'fn-validateInput', label: 'validateInput', type: 'function' as const, domain: 'backend' as const, status: 'warning' as const, file: 'src/auth/validation.ts', line: 3, radius: 10 },
    { id: 'file-auth', label: 'auth.ts', type: 'file' as const, domain: 'backend' as const, status: 'active' as const, file: 'src/auth/index.ts', line: 1, radius: 9 },
    { id: 'route-login', label: 'POST /api/login', type: 'route' as const, domain: 'backend' as const, status: 'active' as const, file: 'src/auth/routes.ts', line: 22, radius: 11 },
    { id: 'env-DATABASE_URL', label: 'DATABASE_URL', type: 'env_var' as const, domain: 'backend' as const, status: 'safe' as const, file: '.env', line: 1, radius: 10 },
  ]
  authNodes.forEach((n, i) => {
    const pos = regionPos(authCenter.x, authCenter.y, authNodes.length, i)
    nodes.push({ ...n, x: pos.x, y: pos.y, color: NC[n.type], data: {} })
  })

  // --- UI region ---
  const uiNodes = [
    { id: 'cls-btn-primary', label: '.btn-primary', type: 'class' as const, domain: 'frontend' as const, status: 'active' as const, file: 'src/styles/buttons.css', line: 15, radius: 10 },
    { id: 'cls-card-shadow', label: '.card-shadow', type: 'class' as const, domain: 'frontend' as const, status: 'active' as const, file: 'src/styles/cards.css', line: 5, radius: 9 },
    { id: 'cls-modal-overlay', label: '.modal-overlay', type: 'class' as const, domain: 'frontend' as const, status: 'warning' as const, file: 'src/styles/modal.css', line: 1, radius: 10 },
    { id: 'cls-nav-item', label: '.nav-item', type: 'class' as const, domain: 'frontend' as const, status: 'active' as const, file: 'src/styles/nav.css', line: 8, radius: 8 },
    { id: 'cls-input-field', label: '.input-field', type: 'class' as const, domain: 'frontend' as const, status: 'active' as const, file: 'src/styles/forms.css', line: 20, radius: 8 },
    { id: 'id-login-form', label: '#login-form', type: 'id' as const, domain: 'frontend' as const, status: 'active' as const, file: 'src/pages/Login.tsx', line: 12, radius: 9 },
    { id: 'id-main-content', label: '#main-content', type: 'id' as const, domain: 'frontend' as const, status: 'active' as const, file: 'src/pages/Dashboard.tsx', line: 8, radius: 9 },
    { id: 'id-user-profile', label: '#user-profile', type: 'id' as const, domain: 'frontend' as const, status: 'collision' as const, file: 'src/pages/Profile.tsx', line: 5, radius: 10 },
    { id: 'cmp-Button', label: 'Button', type: 'component' as const, domain: 'frontend' as const, status: 'active' as const, file: 'src/components/ui/Button.tsx', line: 1, radius: 13 },
    { id: 'cmp-Modal', label: 'Modal', type: 'component' as const, domain: 'frontend' as const, status: 'active' as const, file: 'src/components/ui/Modal.tsx', line: 1, radius: 12 },
    { id: 'cmp-Dashboard', label: 'Dashboard', type: 'component' as const, domain: 'frontend' as const, status: 'active' as const, file: 'src/pages/Dashboard.tsx', line: 1, radius: 14 },
    { id: 'cmp-Navbar', label: 'Navbar', type: 'component' as const, domain: 'frontend' as const, status: 'active' as const, file: 'src/components/layout/Navbar.tsx', line: 1, radius: 11 },
  ]
  uiNodes.forEach((n, i) => {
    const pos = regionPos(uiCenter.x, uiCenter.y, uiNodes.length, i)
    nodes.push({ ...n, x: pos.x, y: pos.y, color: NC[n.type], data: {} })
  })

  // --- API region ---
  const apiNodes = [
    { id: 'fn-getData', label: 'getData', type: 'function' as const, domain: 'backend' as const, status: 'active' as const, file: 'src/api/data.ts', line: 5, radius: 12 },
    { id: 'fn-processPayment', label: 'processPayment', type: 'function' as const, domain: 'backend' as const, status: 'critical' as const, file: 'src/api/payment.ts', line: 10, radius: 14 },
    { id: 'fn-calculateTotal', label: 'calculateTotal', type: 'function' as const, domain: 'backend' as const, status: 'active' as const, file: 'src/api/cart.ts', line: 3, radius: 10 },
    { id: 'fn-formatCurrency', label: 'formatCurrency', type: 'function' as const, domain: 'backend' as const, status: 'active' as const, file: 'src/utils/format.ts', line: 1, radius: 8 },
    { id: 'file-api', label: 'api.ts', type: 'file' as const, domain: 'backend' as const, status: 'active' as const, file: 'src/api/index.ts', line: 1, radius: 9 },
    { id: 'route-users', label: 'GET /api/users', type: 'route' as const, domain: 'backend' as const, status: 'active' as const, file: 'src/api/routes.ts', line: 15, radius: 11 },
    { id: 'pkg-express', label: 'express', type: 'package' as const, domain: 'backend' as const, status: 'vulnerable' as const, file: 'package.json', line: 1, radius: 12 },
    { id: 'pkg-lodash', label: 'lodash', type: 'package' as const, domain: 'backend' as const, status: 'dead' as const, file: 'package.json', line: 2, radius: 10 },
  ]
  apiNodes.forEach((n, i) => {
    const pos = regionPos(apiCenter.x, apiCenter.y, apiNodes.length, i)
    nodes.push({ ...n, x: pos.x, y: pos.y, color: NC[n.type], data: {} })
  })

  // --- State region ---
  const stateNodes = [
    { id: 'store-userStore', label: 'userStore', type: 'store' as const, domain: 'frontend' as const, status: 'active' as const, file: 'src/stores/userStore.ts', line: 1, radius: 13 },
    { id: 'store-cartStore', label: 'cartStore', type: 'store' as const, domain: 'frontend' as const, status: 'active' as const, file: 'src/stores/cartStore.ts', line: 1, radius: 12 },
    { id: 'fn-renderDashboard', label: 'renderDashboard', type: 'function' as const, domain: 'frontend' as const, status: 'active' as const, file: 'src/pages/Dashboard.tsx', line: 20, radius: 11 },
    { id: 'file-styles', label: 'styles.css', type: 'file' as const, domain: 'frontend' as const, status: 'active' as const, file: 'src/styles/global.css', line: 1, radius: 8 },
  ]
  stateNodes.forEach((n, i) => {
    const pos = regionPos(stateCenter.x, stateCenter.y, stateNodes.length, i)
    nodes.push({ ...n, x: pos.x, y: pos.y, color: NC[n.type], data: {} })
  })

  // Build edges
  const edges: GraphEdge[] = [
    { id: 'e1', source: 'route-login', target: 'fn-handleLogin', type: 'routes_to', weight: 2, status: 'active' },
    { id: 'e2', source: 'fn-handleLogin', target: 'fn-verify_token', type: 'calls', weight: 2, status: 'active' },
    { id: 'e3', source: 'fn-handleLogin', target: 'fn-validateInput', type: 'calls', weight: 1, status: 'active' },
    { id: 'e4', source: 'file-auth', target: 'fn-verify_token', type: 'contains', weight: 1, status: 'active' },
    { id: 'e5', source: 'file-auth', target: 'fn-handleLogin', type: 'contains', weight: 1, status: 'active' },
    { id: 'e6', source: 'fn-verify_token', target: 'env-DATABASE_URL', type: 'reads', weight: 1, status: 'active' },
    { id: 'e7', source: 'cmp-Button', target: 'cls-btn-primary', type: 'references', weight: 1, status: 'active' },
    { id: 'e8', source: 'cmp-Modal', target: 'cls-modal-overlay', type: 'references', weight: 1, status: 'warning' },
    { id: 'e9', source: 'cmp-Navbar', target: 'cls-nav-item', type: 'references', weight: 1, status: 'active' },
    { id: 'e10', source: 'cmp-Dashboard', target: 'cmp-Button', type: 'references', weight: 1, status: 'active' },
    { id: 'e11', source: 'cmp-Dashboard', target: 'cmp-Modal', type: 'references', weight: 1, status: 'active' },
    { id: 'e12', source: 'cmp-Dashboard', target: 'id-main-content', type: 'references', weight: 1, status: 'active' },
    { id: 'e13', source: 'cmp-Navbar', target: 'cmp-Dashboard', type: 'references', weight: 1, status: 'active' },
    { id: 'e14', source: 'id-login-form', target: 'cls-input-field', type: 'references', weight: 1, status: 'active' },
    { id: 'e15', source: 'id-login-form', target: 'cls-btn-primary', type: 'references', weight: 1, status: 'active' },
    { id: 'e16', source: 'id-user-profile', target: 'cmp-Modal', type: 'references', weight: 1, status: 'danger' },
    { id: 'e17', source: 'cmp-Dashboard', target: 'cls-card-shadow', type: 'references', weight: 1, status: 'active' },
    { id: 'e18', source: 'route-users', target: 'fn-getData', type: 'routes_to', weight: 2, status: 'active' },
    { id: 'e19', source: 'fn-getData', target: 'fn-formatCurrency', type: 'calls', weight: 1, status: 'active' },
    { id: 'e20', source: 'fn-processPayment', target: 'fn-calculateTotal', type: 'calls', weight: 2, status: 'danger' },
    { id: 'e21', source: 'fn-calculateTotal', target: 'fn-formatCurrency', type: 'calls', weight: 1, status: 'active' },
    { id: 'e22', source: 'file-api', target: 'fn-getData', type: 'contains', weight: 1, status: 'active' },
    { id: 'e23', source: 'file-api', target: 'fn-processPayment', type: 'contains', weight: 1, status: 'active' },
    { id: 'e24', source: 'fn-getData', target: 'pkg-express', type: 'depends_on', weight: 1, status: 'warning' },
    { id: 'e25', source: 'fn-processPayment', target: 'pkg-express', type: 'depends_on', weight: 1, status: 'warning' },
    { id: 'e26', source: 'fn-calculateTotal', target: 'pkg-lodash', type: 'depends_on', weight: 1, status: 'dead' },
    { id: 'e27', source: 'fn-verify_token', target: 'fn-getData', type: 'calls', weight: 1, status: 'active' },
    { id: 'e28', source: 'fn-handleLogin', target: 'store-userStore', type: 'writes', weight: 1, status: 'active' },
    { id: 'e29', source: 'store-userStore', target: 'cmp-Navbar', type: 'reads', weight: 1, status: 'active' },
    { id: 'e30', source: 'store-userStore', target: 'fn-renderDashboard', type: 'reads', weight: 1, status: 'active' },
    { id: 'e31', source: 'store-cartStore', target: 'fn-calculateTotal', type: 'reads', weight: 1, status: 'active' },
    { id: 'e32', source: 'fn-renderDashboard', target: 'store-cartStore', type: 'reads', weight: 1, status: 'active' },
    { id: 'e33', source: 'fn-renderDashboard', target: 'cmp-Dashboard', type: 'references', weight: 2, status: 'active' },
    { id: 'e34', source: 'store-userStore', target: 'id-user-profile', type: 'reads', weight: 1, status: 'active' },
    { id: 'e35', source: 'cmp-Dashboard', target: 'store-cartStore', type: 'references', weight: 1, status: 'active' },
    { id: 'e36', source: 'id-login-form', target: 'fn-handleLogin', type: 'calls', weight: 2, status: 'active' },
    { id: 'e37', source: 'cmp-Button', target: 'id-login-form', type: 'references', weight: 1, status: 'active' },
    { id: 'e38', source: 'file-styles', target: 'cls-modal-overlay', type: 'defines', weight: 1, status: 'active' },
    { id: 'e39', source: 'file-styles', target: 'cls-card-shadow', type: 'defines', weight: 1, status: 'active' },
    { id: 'e40', source: 'file-styles', target: 'cls-btn-primary', type: 'defines', weight: 1, status: 'active' },
  ]

  // Compute clusters
  graphStore.loadGraph(nodes, edges)
  const clusters = clusterEngine.computeClusters(nodes, edges)

  // Clone nodes before assigning cluster IDs (avoid mutating original objects)
  const clonedNodes = nodes.map(n => ({ ...n }))
  for (const cluster of clusters) {
    for (const nodeId of cluster.nodeIds) {
      const node = clonedNodes.find((n) => n.id === nodeId)
      if (node) {
        node.clusterId = cluster.id
      }
    }
  }

  return { nodes: clonedNodes, edges, clusters }
}

// ============================================================
// Inner App Component
// ============================================================

function NeuralWorkspaceApp() {
  const { theme, toggleTheme } = useTheme()
  const analysisStore = useAnalysisStore()

  // ---- State ----
  const [nodes, setNodes] = useState<GraphNode[]>([])
  const [edges, setEdges] = useState<GraphEdge[]>([])
  const [clusters, setClusters] = useState<Cluster[]>([])
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [activeAnimation, setActiveAnimation] = useState<GraphAnimation | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<GraphNode[]>([])
  const [isScanning, setIsScanning] = useState(false)
  const [nodeDetail, setNodeDetail] = useState<NodeDetail | null>(null)
  const [isCanvasReady, setIsCanvasReady] = useState(false)
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; nodeId: string } | null>(null)

  // ---- Refs ----
  const socketRef = useRef<Socket | null>(null)
  const initializedRef = useRef(false)
  const selectedNodeIdRef = useRef<string | null>(null)
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ---- Centralized graph persistence ----
  const persistGraph = useCallback(() => {
    try {
      localStorage.setItem('codelens-graph', graphStore.serialize())
    } catch { /* ignore */ }
  }, [])

  // Keep selectedNodeIdRef in sync with selectedNodeId
  useEffect(() => { selectedNodeIdRef.current = selectedNodeId }, [selectedNodeId])

  // Auto-save graph changes (debounced 2s)
  useEffect(() => {
    const timer = setTimeout(persistGraph, 2000)
    return () => clearTimeout(timer)
  }, [nodes, edges, clusters, persistGraph])

  // ---- Computed ----
  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedNodeId) ?? null,
    [nodes, selectedNodeId]
  )

  const quickActions = useMemo(() => {
    if (!selectedNodeId) return []
    try {
      return graphStore.getQuickActions(selectedNodeId)
    } catch {
      return []
    }
  }, [selectedNodeId, nodes, edges])

  const stats = useMemo(
    () => ({ totalNodes: nodes.length, totalEdges: edges.length }),
    [nodes, edges]
  )

  // ---- Initialize with demo data ----
  useEffect(() => {
    if (initializedRef.current) return
    initializedRef.current = true

    // Try restoring graph from localStorage first
    let restored = false
    try {
      const saved = localStorage.getItem('codelens-graph')
      if (saved) {
        restored = graphStore.loadFromJSON(saved)
        if (restored) {
          const restoredNodes = Array.from(graphStore.nodes.values())
          const restoredEdges = Array.from(graphStore.edges.values())
          if (restoredNodes.length > 0) {
            const computedClusters = clusterEngine.computeClusters(restoredNodes, restoredEdges)
            const clonedRestoredNodes = restoredNodes.map(n => ({ ...n }))
            for (const cluster of computedClusters) {
              for (const nodeId of cluster.nodeIds) {
                const node = clonedRestoredNodes.find(n => n.id === nodeId)
                if (node) node.clusterId = cluster.id
              }
            }
            setNodes(clonedRestoredNodes)
            setEdges(restoredEdges)
            setClusters(computedClusters)
          }
        }
      }
    } catch {
      // Ignore localStorage errors
    }

    if (!restored) {
      const demo = generateDemoData()
      setNodes(demo.nodes)
      setEdges(demo.edges)
      setClusters(demo.clusters)

      graphStore.loadGraph(demo.nodes, demo.edges)
    }

    analysisStore.loadDemoData()

    const storeStats = graphStore.getStats()
    analysisStore.setRegistryStats({ byType: storeStats.byType, byStatus: storeStats.byStatus })

    // Persist graph to localStorage
    persistGraph()

    // Connect WebSocket and capture cleanup
    const wsCleanup = tryConnectWebSocket()
    tryFetchRealData()

    return () => {
      // Cleanup WebSocket on unmount
      if (wsCleanup) wsCleanup()
    }
  }, [])

  // ---- Keyboard shortcut ----
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        analysisStore.toggleCommandPalette()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [analysisStore])

  // ---- WebSocket ----
  const tryConnectWebSocket = useCallback(() => {
    try {
      const socket = io(process.env.NEXT_PUBLIC_WS_URL || '/?XTransformPort=3030', {
        transports: ['websocket'],
        reconnection: true,
        reconnectionAttempts: 5,
        reconnectionDelay: 2000,
        timeout: 5000,
      })

      socket.on('connect', () => {
        console.log('[WS] Connected to codelens-ws service')
      })

      socket.on('graph_init', (data: { nodes: GraphNode[]; edges: GraphEdge[] }) => {
        graphStore.loadGraph(data.nodes, data.edges)
        const computedClusters = clusterEngine.computeClusters(data.nodes, data.edges)
        const clonedNodes = data.nodes.map(n => ({ ...n }))
        for (const cluster of computedClusters) {
          for (const nodeId of cluster.nodeIds) {
            const node = clonedNodes.find((n) => n.id === nodeId)
            if (node) node.clusterId = cluster.id
          }
        }
        setNodes(clonedNodes)
        setEdges(data.edges)
        setClusters(computedClusters)
        // Persist graph to localStorage
        persistGraph()
      })

      socket.on('graph_event', (eventData: { event: GraphEvent }) => {
        const event = eventData.event
        graphStore.applyEvent(event)
        setNodes(Array.from(graphStore.nodes.values()))
        setEdges(Array.from(graphStore.edges.values()))
        const computedClusters = clusterEngine.computeClusters(
          Array.from(graphStore.nodes.values()),
          Array.from(graphStore.edges.values())
        )
        setClusters(computedClusters)
        setActiveAnimation(event.animation)
        // Persist graph to localStorage
        persistGraph()
      })

      socket.on('node_detail', (data: { node_id: string; detail: NodeDetail }) => {
        if (data.node_id === selectedNodeIdRef.current) {
          setNodeDetail(data.detail)
        }
      })

      socket.on('command_result', (data: { command: string; result: unknown }) => {
        console.log('[WS] Command result:', data.command, data.result)
      })

      socket.on('connect_error', (err: Error) => {
        console.log('[WS] Connection error (using demo data):', err.message)
      })

      socketRef.current = socket

      return () => {
        socket.disconnect()
      }
    } catch (err) {
      console.log('[WS] Failed to connect (using demo data):', err)
      return () => {}
    }
  }, [])

  // ---- Fetch real data ----
  const tryFetchRealData = useCallback(async () => {
    try {
      const ws = analysisStore.workspace
      const res = await fetch(`/api/graph?workspace=${encodeURIComponent(ws)}`)
      if (res.ok) {
        const data = await res.json()
        if (data.nodes && data.nodes.length > 0) {
          graphStore.loadGraph(data.nodes, data.edges)
          setNodes(data.nodes)
          setEdges(data.edges)
          if (data.clusters) setClusters(data.clusters)
          // Persist graph to localStorage
          persistGraph()
        }
      }
    } catch {
      // Demo data already loaded
    }
  }, [analysisStore.workspace, persistGraph])

  // ---- Node Selection ----
  const handleNodeSelect = useCallback(
    (nodeId: string | null) => {
      setSelectedNodeId(nodeId)
      setSearchQuery('')
      setSearchResults([])

      if (nodeId) {
        try {
          const detail = graphStore.getNodeDetail(nodeId)
          setNodeDetail(detail)
        } catch {
          setNodeDetail(null)
        }
        socketRef.current?.emit('select_node', { node_id: nodeId })
      } else {
        setNodeDetail(null)
      }
    },
    []
  )

  // ---- Quick Action ----
  const handleQuickAction = useCallback(
    (action: QuickAction) => {
      const socket = socketRef.current
      if (socket?.connected) {
        socket.emit('command', {
          command: action.command,
          args: [...action.args, analysisStore.workspace],
        })
      } else {
        const targetIds = [selectedNodeId ?? '']
        setActiveAnimation({
          type: action.variant === 'danger' ? 'alarm' : action.variant === 'warning' ? 'pulse' : 'flow',
          targetNodeIds: targetIds.filter(Boolean),
          intensity: action.variant === 'danger' ? 'high' : 'medium',
          direction: 'both',
        })
        setTimeout(() => setActiveAnimation(null), 2500)
      }
    },
    [selectedNodeId, analysisStore.workspace]
  )

  // ---- Search ----
  const handleSearch = useCallback(
    (query: string) => {
      setSearchQuery(query)

      // Debounce actual search
      if (searchTimerRef.current) {
        clearTimeout(searchTimerRef.current)
      }

      if (!query.trim()) {
        setSearchResults([])
        return
      }

      searchTimerRef.current = setTimeout(() => {
        try {
          const results = graphStore.searchNodes(query)
          setSearchResults(results.slice(0, 15))
        } catch {
          setSearchResults([])
        }
      }, 150) // 150ms debounce
    },
    []
  )

  // ---- Fit to View ----
  const handleFitToView = useCallback(() => {
    // Dispatch a custom event that NeuralCanvas listens for
    window.dispatchEvent(new CustomEvent('codelens:fit-to-view'))
  }, [])

  // ---- Node Filtering ----
  const [nodeFilters, setNodeFilters] = useState<Set<NodeType>>(new Set())

  const filteredNodes = useMemo(() => {
    if (nodeFilters.size === 0) return nodes
    return nodes.filter(n => !nodeFilters.has(n.type))
  }, [nodes, nodeFilters])

  const filteredEdges = useMemo(() => {
    if (nodeFilters.size === 0) return edges
    const nodeIds = new Set(filteredNodes.map(n => n.id))
    return edges.filter(e => {
      const srcId = typeof e.source === 'string' ? e.source : e.source.id
      const tgtId = typeof e.target === 'string' ? e.target : e.target.id
      return nodeIds.has(srcId) && nodeIds.has(tgtId)
    })
  }, [edges, filteredNodes])

  const handleToggleNodeFilter = useCallback(
    (type: NodeType) => {
      setNodeFilters(prev => {
        const next = new Set(prev)
        if (next.has(type)) next.delete(type)
        else next.add(type)
        return next
      })
    },
    []
  )

  // ---- Context Menu ----
  const contextMenuNode = useMemo(() => {
    if (!contextMenu) return null
    return nodes.find(n => n.id === contextMenu.nodeId) ?? null
  }, [contextMenu, nodes])

  const contextMenuActions = useMemo(() => {
    if (!contextMenu?.nodeId) return []
    try {
      return graphStore.getQuickActions(contextMenu.nodeId)
    } catch {
      return []
    }
  }, [contextMenu])

  const handleSearchResultSelect = useCallback(
    (nodeId: string) => {
      setSelectedNodeId(nodeId)
      setSearchQuery('')
      setSearchResults([])
      try {
        const detail = graphStore.getNodeDetail(nodeId)
        setNodeDetail(detail)
      } catch {
        setNodeDetail(null)
      }
      socketRef.current?.emit('select_node', { node_id: nodeId })
    },
    []
  )

  // ---- Export ----
  const handleExport = useCallback(
    (format: 'png2x' | 'png4x' | 'svg' | 'current' | 'json') => {
      const canvas = document.querySelector('canvas') as HTMLCanvasElement | null
      if (!canvas) return

      switch (format) {
        case 'svg': {
          // Calculate bounds
          let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
          for (const n of nodes) {
            const x = n.x ?? 0, y = n.y ?? 0
            const r = n.radius ?? 8
            minX = Math.min(minX, x - r - 20)
            minY = Math.min(minY, y - r - 20)
            maxX = Math.max(maxX, x + r + 20)
            maxY = Math.max(maxY, y + r + 20)
          }
          const pad = 80
          const w = maxX - minX + pad * 2
          const h = maxY - minY + pad * 2

          // SVG header
          let svg = `<?xml version="1.0" encoding="UTF-8"?>\n`
          svg += `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${minX - pad} ${minY - pad} ${w} ${h}" width="${w}" height="${h}">\n`

          // Background
          svg += `<rect x="${minX - pad}" y="${minY - pad}" width="${w}" height="${h}" fill="${theme === 'dark' ? '#0d0d18' : '#ffffff'}"/>\n`

          // Clusters as rounded rectangles
          for (const cluster of clusters) {
            const clusterNodes = cluster.nodeIds.map(id => nodes.find(n => n.id === id)).filter(Boolean) as GraphNode[]
            if (clusterNodes.length === 0) continue
            let cxMin = Infinity, cyMin = Infinity, cxMax = -Infinity, cyMax = -Infinity
            for (const cn of clusterNodes) {
              const cx = cn.x ?? 0, cy = cn.y ?? 0, cr = cn.radius ?? 8
              cxMin = Math.min(cxMin, cx - cr - 10)
              cyMin = Math.min(cyMin, cy - cr - 10)
              cxMax = Math.max(cxMax, cx + cr + 10)
              cyMax = Math.max(cyMax, cy + cr + 10)
            }
            svg += `<rect x="${cxMin}" y="${cyMin}" width="${cxMax - cxMin}" height="${cyMax - cyMin}" rx="12" ry="12" fill="${cluster.tint}08" stroke="${cluster.tint}30" stroke-width="1" stroke-dasharray="4 2"/>\n`
            svg += `<text x="${cxMin + 8}" y="${cyMin + 14}" fill="${cluster.tint}" font-size="10" font-family="system-ui" opacity="0.7">${cluster.label}</text>\n`
          }

          // Edges with arrows
          for (const e of edges) {
            const src = nodes.find(n => n.id === (typeof e.source === 'string' ? e.source : e.source.id))
            const tgt = nodes.find(n => n.id === (typeof e.target === 'string' ? e.target : e.target.id))
            if (src?.x != null && src?.y != null && tgt?.x != null && tgt?.y != null) {
              const edgeColor = e.status === 'danger' ? '#f56565' : e.status === 'warning' ? '#ecc94b' : e.status === 'dead' ? '#2d3748' : '#4a5568'
              const opacity = e.status === 'dead' ? 0.15 : 0.35
              svg += `<line x1="${src.x}" y1="${src.y}" x2="${tgt.x}" y2="${tgt.y}" stroke="${edgeColor}" stroke-width="${e.weight ?? 1}" opacity="${opacity}"/>\n`
              // Arrow marker
              const dx = tgt.x - src.x, dy = tgt.y - src.y
              const len = Math.sqrt(dx * dx + dy * dy)
              if (len > 0) {
                const tr = tgt.radius ?? 8
                const ax = tgt.x - (dx / len) * (tr + 3)
                const ay = tgt.y - (dy / len) * (tr + 3)
                const arrowSize = 4
                const nx = -dy / len, ny = dx / len
                svg += `<polygon points="${ax + (dx / len) * arrowSize},${ay + (dy / len) * arrowSize} ${ax + nx * arrowSize * 0.5},${ay + ny * arrowSize * 0.5} ${ax - nx * arrowSize * 0.5},${ay - ny * arrowSize * 0.5}" fill="${edgeColor}" opacity="${opacity}"/>\n`
              }
            }
          }

          // Nodes with shape variants
          for (const n of nodes) {
            const x = n.x ?? 0, y = n.y ?? 0, r = n.radius ?? 8
            const shape = getNodeShape(n.type)

            // Draw shape based on type
            switch (shape) {
              case 'diamond': {
                const s = r * 1.3
                svg += `<polygon points="${x},${y - s} ${x + s},${y} ${x},${y + s} ${x - s},${y}" fill="${n.color}" opacity="0.9"/>\n`
                break
              }
              case 'hexagon': {
                const s = r
                const pts = Array.from({ length: 6 }, (_, i) => {
                  const angle = (Math.PI / 3) * i - Math.PI / 6
                  return `${x + s * Math.cos(angle)},${y + s * Math.sin(angle)}`
                }).join(' ')
                svg += `<polygon points="${pts}" fill="${n.color}" opacity="0.9"/>\n`
                break
              }
              case 'triangle': {
                const s = r * 1.3
                svg += `<polygon points="${x},${y - s} ${x + s},${y + s * 0.7} ${x - s},${y + s * 0.7}" fill="${n.color}" opacity="0.9"/>\n`
                break
              }
              case 'star': {
                const outer = r * 1.2, inner = r * 0.5
                const pts = Array.from({ length: 10 }, (_, i) => {
                  const rad = i % 2 === 0 ? outer : inner
                  const angle = (Math.PI / 5) * i - Math.PI / 2
                  return `${x + rad * Math.cos(angle)},${y + rad * Math.sin(angle)}`
                }).join(' ')
                svg += `<polygon points="${pts}" fill="${n.color}" opacity="0.9"/>\n`
                break
              }
              case 'square': {
                const s = r * 0.9
                svg += `<rect x="${x - s}" y="${y - s}" width="${s * 2}" height="${s * 2}" rx="2" fill="${n.color}" opacity="0.9"/>\n`
                break
              }
              case 'ring': {
                svg += `<circle cx="${x}" cy="${y}" r="${r}" fill="none" stroke="${n.color}" stroke-width="3" opacity="0.9"/>\n`
                svg += `<circle cx="${x}" cy="${y}" r="${r * 0.5}" fill="${n.color}" opacity="0.6"/>\n`
                break
              }
              default: { // circle
                svg += `<circle cx="${x}" cy="${y}" r="${r}" fill="${n.color}" opacity="0.9"/>\n`
                break
              }
            }

            // Label below node
            svg += `<text x="${x}" y="${y + r + 12}" text-anchor="middle" fill="${theme === 'dark' ? '#e2e8f0' : '#2d3748'}" font-size="9" font-family="system-ui">${n.label}</text>\n`
          }

          svg += `</svg>`

          const blob = new Blob([svg], { type: 'image/svg+xml' })
          const url = URL.createObjectURL(blob)
          const a = document.createElement('a')
          a.href = url
          a.download = `codelens-graph-${Date.now()}.svg`
          a.click()
          URL.revokeObjectURL(url)
          break
        }
        case 'png2x': {
          const exportCanvas = document.createElement('canvas')
          exportCanvas.width = canvas.width * 2
          exportCanvas.height = canvas.height * 2
          const ctx = exportCanvas.getContext('2d')
          if (ctx) {
            ctx.scale(2, 2)
            ctx.drawImage(canvas, 0, 0)
          }
          const dataUrl2x = exportCanvas.toDataURL('image/png')
          const link2x = document.createElement('a')
          link2x.download = `codelens-neural-png2x-${Date.now()}.png`
          link2x.href = dataUrl2x
          link2x.click()
          break
        }
        case 'png4x': {
          const exportCanvas = document.createElement('canvas')
          exportCanvas.width = canvas.width * 4
          exportCanvas.height = canvas.height * 4
          const ctx = exportCanvas.getContext('2d')
          if (ctx) {
            ctx.scale(4, 4)
            ctx.drawImage(canvas, 0, 0)
          }
          const dataUrl4x = exportCanvas.toDataURL('image/png')
          const link4x = document.createElement('a')
          link4x.download = `codelens-neural-png4x-${Date.now()}.png`
          link4x.href = dataUrl4x
          link4x.click()
          break
        }
        case 'json': {
          const exportData = {
            nodes: nodes.map(n => ({
              id: n.id, label: n.label, type: n.type, domain: n.domain,
              status: n.status, file: n.file, line: n.line, data: n.data,
            })),
            edges: edges.map(e => ({
              id: e.id,
              source: typeof e.source === 'string' ? e.source : e.source.id,
              target: typeof e.target === 'string' ? e.target : e.target.id,
              type: e.type, weight: e.weight, status: e.status,
            })),
            clusters,
            exportedAt: new Date().toISOString(),
            version: '5.0.0',
          }
          const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' })
          const url = URL.createObjectURL(blob)
          const a = document.createElement('a')
          a.href = url
          a.download = `codelens-graph-${Date.now()}.json`
          a.click()
          URL.revokeObjectURL(url)
          break
        }
        default: {
          const dataUrl = canvas.toDataURL('image/png')
          const link = document.createElement('a')
          link.download = `codelens-neural-current-${Date.now()}.png`
          link.href = dataUrl
          link.click()
          break
        }
      }
    },
    [nodes, edges, clusters, theme]
  )

  // ---- Rescan ----
  const handleRescan = useCallback(async () => {
    setIsScanning(true)
    try {
      const ws = analysisStore.workspace
      const res = await fetch(`/api/graph?workspace=${encodeURIComponent(ws)}`)
      if (res.ok) {
        const data = await res.json()
        if (data.nodes && data.nodes.length > 0) {
          graphStore.loadGraph(data.nodes, data.edges)
          setNodes(data.nodes)
          setEdges(data.edges)
          if (data.clusters) setClusters(data.clusters)
          // Persist graph to localStorage
          persistGraph()

          setActiveAnimation({
            type: 'ripple',
            targetNodeIds: data.nodes.map((n: GraphNode) => n.id).slice(0, 20),
            intensity: 'medium',
          })
          setTimeout(() => setActiveAnimation(null), 2500)
        }
      }
    } catch {
      // Silently fail
    } finally {
      setIsScanning(false)
    }
  }, [analysisStore.workspace, persistGraph])

  // ---- Panel close ----
  const handlePanelClose = useCallback(() => {
    setSelectedNodeId(null)
    setNodeDetail(null)
  }, [])

  const dark = theme === 'dark'

  return (
    <div
      className="h-screen w-screen flex flex-col overflow-hidden transition-colors duration-500"
      style={{
        backgroundColor: dark ? '#0a0a0f' : '#f7fafc',
        backgroundImage: dark
          ? 'radial-gradient(ellipse 80% 60% at 20% 30%, rgba(139,92,246,0.04), transparent), radial-gradient(ellipse 60% 50% at 80% 70%, rgba(99,179,237,0.03), transparent)'
          : 'radial-gradient(ellipse 80% 60% at 20% 30%, rgba(139,92,246,0.03), transparent), radial-gradient(ellipse 60% 50% at 80% 70%, rgba(99,179,237,0.02), transparent)',
      }}
    >
      {/* TopBar */}
      <ErrorBoundary fallback={<div className="h-14 bg-background border-b" />}>
        <TopBar
          theme={theme}
          onThemeToggle={toggleTheme}
          onSearch={handleSearch}
          searchResults={searchResults}
          onSearchResultSelect={handleSearchResultSelect}
          onExport={handleExport}
          onRescan={handleRescan}
          onFitToView={handleFitToView}
          stats={stats}
          isScanning={isScanning}
          nodeFilters={nodeFilters}
          onToggleNodeFilter={handleToggleNodeFilter}
        />
      </ErrorBoundary>

      {/* Main area: Sidebar + Canvas + Panel — pt-14 accounts for fixed TopBar */}
      <div className="flex-1 flex overflow-hidden min-h-0 pt-14">
        {/* Left Sidebar */}
        <ErrorBoundary fallback={<div className="w-64 bg-background" />}>
          <LeftSidebar theme={theme} />
        </ErrorBoundary>

        {/* Center: Canvas + Bottom Panel */}
        <div className="flex-1 flex flex-col overflow-hidden min-h-0" style={{ position: 'relative' }}>
          {/* Neural Canvas — explicit h-full to guarantee ResizeObserver gets dimensions */}
          <div className="flex-1 min-h-0" style={{ position: 'relative', overflow: 'hidden' }}>
            {!isCanvasReady && <CanvasSkeleton theme={theme} />}
            <ErrorBoundary fallback={<div className="flex items-center justify-center h-full text-muted-foreground">Canvas unavailable</div>}>
              <NeuralCanvas
                theme={theme}
                nodes={filteredNodes}
                edges={filteredEdges}
                clusters={clusters}
                onNodeSelect={handleNodeSelect}
                selectedNodeId={selectedNodeId}
                activeAnimation={activeAnimation}
                onCanvasReady={() => setIsCanvasReady(true)}
                onContextMenu={setContextMenu}
              />
            </ErrorBoundary>

            {/* Slide-in panel */}
            <SlideInPanel
              theme={theme}
              node={selectedNode}
              detail={nodeDetail}
              quickActions={quickActions}
              onAction={handleQuickAction}
              onClose={handlePanelClose}
            />
          </div>

          {/* Bottom Result Panel */}
          <ErrorBoundary fallback={<div className="h-8 bg-background border-t" />}>
            <ResultPanel theme={theme} />
          </ErrorBoundary>
        </div>
      </div>

      {/* Command Palette Overlay */}
      <CommandPalette theme={theme} />

      {/* Right-click Context Menu */}
      {contextMenu && contextMenuNode && (
        <NodeContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          node={contextMenuNode}
          actions={contextMenuActions}
          onAction={handleQuickAction}
          onClose={() => setContextMenu(null)}
          theme={theme}
        />
      )}
    </div>
  )
}

// ============================================================
// Main Page
// ============================================================

export default function Home() {
  return (
    <ThemeProvider>
      <ErrorBoundary>
        <NeuralWorkspaceApp />
      </ErrorBoundary>
    </ThemeProvider>
  )
}
