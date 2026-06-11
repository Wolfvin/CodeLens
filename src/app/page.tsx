'use client'

import { useState, useEffect, useCallback } from 'react'

// ============================================================
// CodeLens Dashboard — Landing Page
// Shows server status, workspace scanner, and command runner
// ============================================================

interface ApiStatus {
  name: string
  version: string
  status: string
  commands: number
  endpoints: Record<string, string>
  websocket: string
}

interface GraphData {
  nodes: Array<{
    id: string
    label: string
    type: string
    domain: string
    status: string
    file?: string
    line?: number
    clusterId?: string
    radius: number
    color: string
    data: Record<string, unknown>
  }>
  edges: Array<{
    id: string
    source: string
    target: string
    type: string
    weight: number
    status: string
  }>
  clusters: Array<{
    id: string
    label: string
    icon: string
    tint: string
    nodeIds: string[]
    cohesion: number
  }>
  healthScore: {
    overall: number
    grade: string
    quality: number
    security: number
    coverage: number
    dependency: number
    architecture: number
    maintainability: number
    recommendations: Array<{
      category: string
      priority: string
      message: string
      impact: number
    }>
  }
}

const NODE_TYPE_COLORS: Record<string, string> = {
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

const STATUS_COLORS: Record<string, string> = {
  active: '#48bb78',
  dead: '#718096',
  vulnerable: '#ecc94b',
  critical: '#e53e3e',
  warning: '#ed8936',
  safe: '#48bb78',
  orphan: '#a0aec0',
  untested: '#ecc94b',
  unused: '#718096',
}

export default function Dashboard() {
  const [apiStatus, setApiStatus] = useState<ApiStatus | null>(null)
  const [workspace, setWorkspace] = useState('')
  const [graphData, setGraphData] = useState<GraphData | null>(null)
  const [scanning, setScanning] = useState(false)
  const [command, setCommand] = useState('')
  const [commandArgs, setCommandArgs] = useState('')
  const [commandResult, setCommandResult] = useState<unknown>(null)
  const [commandRunning, setCommandRunning] = useState(false)
  const [activeTab, setActiveTab] = useState<'overview' | 'graph' | 'commands' | 'health'>('overview')
  const [error, setError] = useState<string | null>(null)

  // Fetch API status on mount
  useEffect(() => {
    fetch('/api')
      .then(r => r.json())
      .then(data => setApiStatus(data))
      .catch(() => setError('Failed to connect to CodeLens API'))
  }, [])

  // Scan workspace
  const handleScan = useCallback(async () => {
    if (!workspace.trim()) return
    setScanning(true)
    setError(null)
    try {
      const res = await fetch(`/api/graph?workspace=${encodeURIComponent(workspace)}`)
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.error ?? `HTTP ${res.status}`)
      }
      const data = await res.json()
      setGraphData(data)
      setActiveTab('graph')
    } catch (err) {
      setError(String(err))
    } finally {
      setScanning(false)
    }
  }, [workspace])

  // Run command
  const handleRunCommand = useCallback(async () => {
    if (!command.trim() || !workspace.trim()) return
    setCommandRunning(true)
    setError(null)
    try {
      const args = commandArgs.trim() ? commandArgs.trim().split(/\s+/) : []
      const res = await fetch('/api/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command, args, workspace }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.error ?? `HTTP ${res.status}`)
      }
      const data = await res.json()
      setCommandResult(data)
    } catch (err) {
      setError(String(err))
    } finally {
      setCommandRunning(false)
    }
  }, [command, commandArgs, workspace])

  // Grade color
  const gradeColor = (grade: string) => {
    if (grade.startsWith('A')) return '#48bb78'
    if (grade === 'B') return '#63b3ed'
    if (grade === 'C') return '#ecc94b'
    if (grade === 'D') return '#ed8936'
    return '#e53e3e'
  }

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="border-b border-gray-800 bg-[#0d0d14] px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-sm font-bold">
            CL
          </div>
          <div>
            <h1 className="text-lg font-semibold text-white">CodeLens</h1>
            <p className="text-xs text-gray-500">Live Codebase Reference Intelligence</p>
          </div>
        </div>
        {apiStatus && (
          <div className="flex items-center gap-4 text-xs text-gray-500">
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
              API v{apiStatus.version}
            </span>
            <span>{apiStatus.commands} commands</span>
          </div>
        )}
      </header>

      {/* Workspace Input */}
      <div className="border-b border-gray-800 bg-[#0d0d14] px-6 py-3 flex items-center gap-3">
        <label className="text-sm text-gray-400 whitespace-nowrap">Workspace:</label>
        <input
          type="text"
          value={workspace}
          onChange={e => setWorkspace(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleScan()}
          placeholder="/path/to/your/project"
          className="flex-1 bg-[#1a1a2e] border border-gray-700 rounded-md px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500"
        />
        <button
          onClick={handleScan}
          disabled={scanning || !workspace.trim()}
          className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm font-medium rounded-md transition-colors"
        >
          {scanning ? 'Scanning...' : 'Scan'}
        </button>
      </div>

      {/* Error bar */}
      {error && (
        <div className="bg-red-900/30 border-b border-red-800 px-6 py-2 text-sm text-red-300 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-200">✕</button>
        </div>
      )}

      {/* Tab bar */}
      <div className="border-b border-gray-800 bg-[#0d0d14] px-6 flex gap-1">
        {(['overview', 'graph', 'commands', 'health'] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-gray-500 hover:text-gray-300'
            }`}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {/* Main content */}
      <main className="flex-1 overflow-auto p-6">
        {/* Overview Tab */}
        {activeTab === 'overview' && (
          <div className="max-w-4xl mx-auto space-y-6">
            <section className="bg-[#1a1a2e] rounded-xl border border-gray-800 p-6">
              <h2 className="text-lg font-semibold text-white mb-4">Welcome to CodeLens</h2>
              <p className="text-gray-400 text-sm leading-relaxed mb-4">
                CodeLens is a backend developer tool that scans your codebase using tree-sitter AST parsing
                and exposes structured JSON data via a REST API and WebSocket interface. It provides 41 analysis
                commands covering code search, call tracing, impact analysis, security auditing, quality scoring,
                and refactoring safety.
              </p>
              <div className="grid grid-cols-3 gap-4">
                <div className="bg-[#0d0d14] rounded-lg p-4 border border-gray-800">
                  <div className="text-2xl font-bold text-blue-400">41</div>
                  <div className="text-xs text-gray-500 mt-1">Analysis Commands</div>
                </div>
                <div className="bg-[#0d0d14] rounded-lg p-4 border border-gray-800">
                  <div className="text-2xl font-bold text-purple-400">10</div>
                  <div className="text-xs text-gray-500 mt-1">Language Parsers</div>
                </div>
                <div className="bg-[#0d0d14] rounded-lg p-4 border border-gray-800">
                  <div className="text-2xl font-bold text-green-400">6</div>
                  <div className="text-xs text-gray-500 mt-1">Health Dimensions</div>
                </div>
              </div>
            </section>

            <section className="bg-[#1a1a2e] rounded-xl border border-gray-800 p-6">
              <h2 className="text-lg font-semibold text-white mb-4">Quick Start</h2>
              <ol className="space-y-3 text-sm text-gray-400">
                <li className="flex gap-3">
                  <span className="w-6 h-6 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs font-bold shrink-0">1</span>
                  <span>Enter your project path in the workspace input above</span>
                </li>
                <li className="flex gap-3">
                  <span className="w-6 h-6 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs font-bold shrink-0">2</span>
                  <span>Click <strong className="text-white">Scan</strong> to analyze the codebase and build the graph</span>
                </li>
                <li className="flex gap-3">
                  <span className="w-6 h-6 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs font-bold shrink-0">3</span>
                  <span>Explore the <strong className="text-white">Graph</strong> tab for nodes, edges, and clusters</span>
                </li>
                <li className="flex gap-3">
                  <span className="w-6 h-6 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs font-bold shrink-0">4</span>
                  <span>Run specific commands in the <strong className="text-white">Commands</strong> tab</span>
                </li>
              </ol>
            </section>

            {apiStatus && (
              <section className="bg-[#1a1a2e] rounded-xl border border-gray-800 p-6">
                <h2 className="text-lg font-semibold text-white mb-4">API Endpoints</h2>
                <div className="space-y-2">
                  {Object.entries(apiStatus.endpoints).map(([key, desc]) => (
                    <div key={key} className="flex items-start gap-3 text-sm">
                      <span className="px-2 py-0.5 bg-green-900/50 text-green-400 text-xs rounded font-mono">{key}</span>
                      <span className="text-gray-400">{desc}</span>
                    </div>
                  ))}
                  <div className="flex items-start gap-3 text-sm">
                    <span className="px-2 py-0.5 bg-purple-900/50 text-purple-400 text-xs rounded font-mono">ws</span>
                    <span className="text-gray-400">{apiStatus.websocket}</span>
                  </div>
                </div>
              </section>
            )}
          </div>
        )}

        {/* Graph Tab */}
        {activeTab === 'graph' && graphData && (
          <div className="max-w-6xl mx-auto space-y-6">
            {/* Stats bar */}
            <div className="grid grid-cols-4 gap-4">
              <div className="bg-[#1a1a2e] rounded-lg p-4 border border-gray-800">
                <div className="text-2xl font-bold text-blue-400">{graphData.nodes.length}</div>
                <div className="text-xs text-gray-500 mt-1">Nodes</div>
              </div>
              <div className="bg-[#1a1a2e] rounded-lg p-4 border border-gray-800">
                <div className="text-2xl font-bold text-purple-400">{graphData.edges.length}</div>
                <div className="text-xs text-gray-500 mt-1">Edges</div>
              </div>
              <div className="bg-[#1a1a2e] rounded-lg p-4 border border-gray-800">
                <div className="text-2xl font-bold text-green-400">{graphData.clusters.length}</div>
                <div className="text-xs text-gray-500 mt-1">Clusters</div>
              </div>
              <div className="bg-[#1a1a2e] rounded-lg p-4 border border-gray-800">
                <div className="text-2xl font-bold" style={{ color: gradeColor(graphData.healthScore.grade) }}>
                  {graphData.healthScore.grade}
                </div>
                <div className="text-xs text-gray-500 mt-1">Health Grade ({graphData.healthScore.overall})</div>
              </div>
            </div>

            {/* Node type breakdown */}
            <section className="bg-[#1a1a2e] rounded-xl border border-gray-800 p-6">
              <h2 className="text-lg font-semibold text-white mb-4">Node Types</h2>
              <div className="grid grid-cols-4 gap-2">
                {Object.entries(
                  graphData.nodes.reduce<Record<string, number>>((acc, n) => {
                    acc[n.type] = (acc[n.type] ?? 0) + 1
                    return acc
                  }, {})
                ).sort((a, b) => b[1] - a[1]).map(([type, count]) => (
                  <div key={type} className="flex items-center gap-2 text-sm bg-[#0d0d14] rounded-lg p-2 border border-gray-800">
                    <span className="w-3 h-3 rounded-full" style={{ backgroundColor: NODE_TYPE_COLORS[type] ?? '#718096' }} />
                    <span className="text-gray-300 flex-1">{type}</span>
                    <span className="text-gray-500">{count}</span>
                  </div>
                ))}
              </div>
            </section>

            {/* Clusters */}
            <section className="bg-[#1a1a2e] rounded-xl border border-gray-800 p-6">
              <h2 className="text-lg font-semibold text-white mb-4">Clusters</h2>
              <div className="space-y-2">
                {graphData.clusters.slice(0, 20).map(cluster => (
                  <div key={cluster.id} className="flex items-center gap-3 bg-[#0d0d14] rounded-lg p-3 border border-gray-800">
                    <span className="text-lg">{cluster.icon}</span>
                    <span className="text-gray-200 font-medium flex-1">{cluster.label}</span>
                    <span className="text-xs text-gray-500">{cluster.nodeIds.length} nodes</span>
                    <span className="text-xs" style={{ color: cluster.tint }}>
                      {(cluster.cohesion * 100).toFixed(0)}% cohesion
                    </span>
                  </div>
                ))}
              </div>
            </section>

            {/* Recent Nodes */}
            <section className="bg-[#1a1a2e] rounded-xl border border-gray-800 p-6">
              <h2 className="text-lg font-semibold text-white mb-4">Nodes (top 50)</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-gray-500 text-left border-b border-gray-800">
                      <th className="pb-2 pr-4">Label</th>
                      <th className="pb-2 pr-4">Type</th>
                      <th className="pb-2 pr-4">Domain</th>
                      <th className="pb-2 pr-4">Status</th>
                      <th className="pb-2">File</th>
                    </tr>
                  </thead>
                  <tbody>
                    {graphData.nodes.slice(0, 50).map(node => (
                      <tr key={node.id} className="border-b border-gray-800/50 hover:bg-[#0d0d14]">
                        <td className="py-2 pr-4 text-gray-200 font-mono text-xs">{node.label}</td>
                        <td className="py-2 pr-4">
                          <span className="px-1.5 py-0.5 rounded text-xs" style={{ backgroundColor: (NODE_TYPE_COLORS[node.type] ?? '#718096') + '30', color: NODE_TYPE_COLORS[node.type] }}>
                            {node.type}
                          </span>
                        </td>
                        <td className="py-2 pr-4 text-gray-400">{node.domain}</td>
                        <td className="py-2 pr-4">
                          <span className="px-1.5 py-0.5 rounded text-xs" style={{ backgroundColor: (STATUS_COLORS[node.status] ?? '#718096') + '30', color: STATUS_COLORS[node.status] ?? '#718096' }}>
                            {node.status}
                          </span>
                        </td>
                        <td className="py-2 text-gray-500 font-mono text-xs truncate max-w-[200px]">{node.file ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        )}

        {activeTab === 'graph' && !graphData && (
          <div className="flex items-center justify-center h-64 text-gray-600">
            Enter a workspace path and click Scan to see graph data
          </div>
        )}

        {/* Commands Tab */}
        {activeTab === 'commands' && (
          <div className="max-w-4xl mx-auto space-y-6">
            <section className="bg-[#1a1a2e] rounded-xl border border-gray-800 p-6">
              <h2 className="text-lg font-semibold text-white mb-4">Run Command</h2>
              <div className="space-y-3">
                <div className="flex gap-3">
                  <input
                    type="text"
                    value={command}
                    onChange={e => setCommand(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleRunCommand()}
                    placeholder="Command (e.g. smell, secrets, vuln-scan)"
                    className="flex-1 bg-[#0d0d14] border border-gray-700 rounded-md px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500 font-mono"
                  />
                  <input
                    type="text"
                    value={commandArgs}
                    onChange={e => setCommandArgs(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleRunCommand()}
                    placeholder="Args (e.g. --severity critical)"
                    className="flex-1 bg-[#0d0d14] border border-gray-700 rounded-md px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500 font-mono"
                  />
                  <button
                    onClick={handleRunCommand}
                    disabled={commandRunning || !command.trim() || !workspace.trim()}
                    className="px-6 py-2 bg-purple-600 hover:bg-purple-700 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm font-medium rounded-md transition-colors"
                  >
                    {commandRunning ? 'Running...' : 'Run'}
                  </button>
                </div>
                {!workspace.trim() && (
                  <p className="text-xs text-yellow-500">Set a workspace path above first</p>
                )}
              </div>
            </section>

            {/* Command result */}
            {commandResult !== null && (
              <section className="bg-[#1a1a2e] rounded-xl border border-gray-800 p-6">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-lg font-semibold text-white">Result</h2>
                  <button
                    onClick={() => setCommandResult(null)}
                    className="text-gray-500 hover:text-gray-300 text-sm"
                  >
                    Clear
                  </button>
                </div>
                <pre className="bg-[#0d0d14] rounded-lg p-4 overflow-auto max-h-96 text-xs text-gray-300 font-mono border border-gray-800">
                  {typeof commandResult === 'string' ? commandResult : String(JSON.stringify(commandResult, null, 2))}
                </pre>
              </section>
            )}

            {/* Quick commands */}
            <section className="bg-[#1a1a2e] rounded-xl border border-gray-800 p-6">
              <h2 className="text-lg font-semibold text-white mb-4">Quick Commands</h2>
              <div className="grid grid-cols-3 gap-2">
                {[
                  { cmd: 'smell', label: 'Code Smells', icon: '👃' },
                  { cmd: 'secrets', label: 'Find Secrets', icon: '🔑' },
                  { cmd: 'vuln-scan', label: 'Vulnerability Scan', icon: '🛡️' },
                  { cmd: 'dead-code', label: 'Dead Code', icon: '💀' },
                  { cmd: 'complexity', label: 'Complexity', icon: '🧮' },
                  { cmd: 'perf-hint', label: 'Performance', icon: '⚡' },
                  { cmd: 'css-deep', label: 'CSS Analysis', icon: '🎨' },
                  { cmd: 'a11y', label: 'Accessibility', icon: '♿' },
                  { cmd: 'handbook', label: 'Handbook', icon: '📖' },
                ].map(({ cmd, label, icon }) => (
                  <button
                    key={cmd}
                    onClick={() => { setCommand(cmd); setCommandArgs('') }}
                    disabled={!workspace.trim()}
                    className="flex items-center gap-2 bg-[#0d0d14] border border-gray-800 rounded-lg p-3 text-sm text-gray-300 hover:border-blue-600 hover:text-blue-400 transition-colors disabled:opacity-50"
                  >
                    <span>{icon}</span>
                    <span>{label}</span>
                  </button>
                ))}
              </div>
            </section>
          </div>
        )}

        {/* Health Tab */}
        {activeTab === 'health' && graphData && (
          <div className="max-w-4xl mx-auto space-y-6">
            {/* Health score cards */}
            <div className="grid grid-cols-3 gap-4">
              {[
                { label: 'Quality', value: graphData.healthScore.quality, color: '#63b3ed' },
                { label: 'Security', value: graphData.healthScore.security, color: '#e53e3e' },
                { label: 'Coverage', value: graphData.healthScore.coverage, color: '#48bb78' },
                { label: 'Dependency', value: graphData.healthScore.dependency, color: '#f6ad55' },
                { label: 'Architecture', value: graphData.healthScore.architecture, color: '#b794f4' },
                { label: 'Maintainability', value: graphData.healthScore.maintainability, color: '#4fd1c5' },
              ].map(({ label, value, color }) => (
                <div key={label} className="bg-[#1a1a2e] rounded-lg p-4 border border-gray-800">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm text-gray-400">{label}</span>
                    <span className="text-lg font-bold" style={{ color }}>{value}</span>
                  </div>
                  <div className="w-full h-2 bg-[#0d0d14] rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all"
                      style={{ width: `${value}%`, backgroundColor: color }}
                    />
                  </div>
                </div>
              ))}
            </div>

            {/* Recommendations */}
            {graphData.healthScore.recommendations.length > 0 && (
              <section className="bg-[#1a1a2e] rounded-xl border border-gray-800 p-6">
                <h2 className="text-lg font-semibold text-white mb-4">Recommendations</h2>
                <div className="space-y-2">
                  {graphData.healthScore.recommendations.map((rec, i) => (
                    <div key={i} className="flex items-start gap-3 bg-[#0d0d14] rounded-lg p-3 border border-gray-800">
                      <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                        rec.priority === 'critical' ? 'bg-red-900/50 text-red-400' :
                        rec.priority === 'high' ? 'bg-orange-900/50 text-orange-400' :
                        rec.priority === 'medium' ? 'bg-yellow-900/50 text-yellow-400' :
                        'bg-gray-800 text-gray-400'
                      }`}>
                        {rec.priority}
                      </span>
                      <div className="flex-1">
                        <span className="text-sm text-gray-300">{rec.message}</span>
                        <span className="text-xs text-gray-600 ml-2">+{rec.impact} pts</span>
                      </div>
                      <span className="text-xs text-gray-600">{rec.category}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </div>
        )}

        {activeTab === 'health' && !graphData && (
          <div className="flex items-center justify-center h-64 text-gray-600">
            Scan a workspace first to see health metrics
          </div>
        )}
      </main>
    </div>
  )
}
