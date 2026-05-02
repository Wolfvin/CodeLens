'use client'

import React, { useState, useCallback, useEffect, useRef, useMemo } from 'react'
import { io, Socket } from 'socket.io-client'
import { ThemeProvider, useTheme } from '@/components/shared/ThemeProvider'
import { TopBar } from '@/components/topbar/TopBar'
import NeuralCanvas from '@/components/canvas/NeuralCanvas'
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
} from '@/types/neural'

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

  // Assign cluster IDs back to nodes
  for (const cluster of clusters) {
    for (const nodeId of cluster.nodeIds) {
      const node = nodes.find((n) => n.id === nodeId)
      if (node) {
        node.clusterId = cluster.id
      }
    }
  }

  return { nodes, edges, clusters }
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

  // ---- Refs ----
  const socketRef = useRef<Socket | null>(null)
  const initializedRef = useRef(false)

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

    const demo = generateDemoData()
    setNodes(demo.nodes)
    setEdges(demo.edges)
    setClusters(demo.clusters)

    graphStore.loadGraph(demo.nodes, demo.edges)
    analysisStore.loadDemoData()

    const storeStats = graphStore.getStats()
    analysisStore.setRegistryStats({ byType: storeStats.byType, byStatus: storeStats.byStatus })

    tryConnectWebSocket()
    tryFetchRealData()
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
      const socket = io('/?XTransformPort=3030', {
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
        for (const cluster of computedClusters) {
          for (const nodeId of cluster.nodeIds) {
            const node = data.nodes.find((n) => n.id === nodeId)
            if (node) node.clusterId = cluster.id
          }
        }
        setNodes(data.nodes)
        setEdges(data.edges)
        setClusters(computedClusters)
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
      })

      socket.on('node_detail', (data: { node_id: string; detail: NodeDetail }) => {
        if (data.node_id === selectedNodeId) {
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
    }
  }, [selectedNodeId])

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
        }
      }
    } catch {
      // Demo data already loaded
    }
  }, [analysisStore.workspace])

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
          args: action.args,
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
    [selectedNodeId]
  )

  // ---- Search ----
  const handleSearch = useCallback(
    (query: string) => {
      setSearchQuery(query)
      if (!query.trim()) {
        setSearchResults([])
        return
      }
      try {
        const results = graphStore.searchNodes(query)
        setSearchResults(results.slice(0, 15))
      } catch {
        setSearchResults([])
      }
    },
    []
  )

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
    (format: 'png2x' | 'png4x' | 'svg' | 'current') => {
      const canvas = document.querySelector('canvas') as HTMLCanvasElement | null
      if (!canvas) return

      let dataUrl: string

      switch (format) {
        case 'png2x': {
          const exportCanvas = document.createElement('canvas')
          exportCanvas.width = canvas.width * 2
          exportCanvas.height = canvas.height * 2
          const ctx = exportCanvas.getContext('2d')
          if (ctx) {
            ctx.scale(2, 2)
            ctx.drawImage(canvas, 0, 0)
          }
          dataUrl = exportCanvas.toDataURL('image/png')
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
          dataUrl = exportCanvas.toDataURL('image/png')
          break
        }
        default:
          dataUrl = canvas.toDataURL('image/png')
          break
      }

      const link = document.createElement('a')
      link.download = `codelens-neural-${format}-${Date.now()}.png`
      link.href = dataUrl
      link.click()
    },
    []
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
  }, [analysisStore.workspace])

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
      <TopBar
        theme={theme}
        onThemeToggle={toggleTheme}
        onSearch={handleSearch}
        searchResults={searchResults}
        onSearchResultSelect={handleSearchResultSelect}
        onExport={handleExport}
        onRescan={handleRescan}
        stats={stats}
        isScanning={isScanning}
      />

      {/* Main area: Sidebar + Canvas + Panel — pt-14 accounts for fixed TopBar */}
      <div className="flex-1 flex overflow-hidden min-h-0 pt-14">
        {/* Left Sidebar */}
        <LeftSidebar theme={theme} />

        {/* Center: Canvas + Bottom Panel */}
        <div className="flex-1 flex flex-col overflow-hidden min-h-0" style={{ position: 'relative' }}>
          {/* Neural Canvas — explicit h-full to guarantee ResizeObserver gets dimensions */}
          <div className="flex-1 min-h-0" style={{ position: 'relative', overflow: 'hidden' }}>
            <NeuralCanvas
              theme={theme}
              nodes={nodes}
              edges={edges}
              clusters={clusters}
              onNodeSelect={handleNodeSelect}
              selectedNodeId={selectedNodeId}
              activeAnimation={activeAnimation}
            />

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
          <ResultPanel theme={theme} />
        </div>
      </div>

      {/* Command Palette Overlay */}
      <CommandPalette theme={theme} />
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
