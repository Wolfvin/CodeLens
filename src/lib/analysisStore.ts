'use client'

import { create } from 'zustand'
import type { SidebarTab, CommandHistoryEntry, ResultTab } from '@/types/neural'
import { DEMO_SECURITY, DEMO_QUALITY, DEMO_PERFORMANCE, DEMO_CSS, DEMO_P1, DEMO_P2P3, DEMO_REFACTORING } from './demoData'

// ---- Store Interface ----
interface AnalysisState {
  // Workspace
  workspace: string
  isScanning: boolean
  lastScanTime: number | null
  frameworks: string[]
  registryStats: { byType: Record<string, number>; byStatus: Record<string, number> } | null

  // Command execution
  runningCommands: string[]
  commandHistory: CommandHistoryEntry[]
  recentCommands: string[]

  // Analysis results
  securityResults: {
    secrets: typeof DEMO_SECURITY.secrets | null
    vulnerabilities: typeof DEMO_SECURITY.vulnerabilities | null
    dataflow: typeof DEMO_SECURITY.dataflow | null
    envCheck: typeof DEMO_SECURITY.envCheck | null
    regexAudit: typeof DEMO_SECURITY.regexAudit | null
  }
  qualityResults: {
    smells: typeof DEMO_QUALITY.smells | null
    complexity: typeof DEMO_QUALITY.complexity | null
    debugLeaks: typeof DEMO_QUALITY.debugLeaks | null
    deadCode: typeof DEMO_QUALITY.deadCode | null
    a11y: typeof DEMO_QUALITY.a11y | null
  }
  performanceResults: {
    perfHints: typeof DEMO_PERFORMANCE.perfHints | null
    circular: typeof DEMO_PERFORMANCE.circular | null
  }
  cssResults: {
    cssDeep: typeof DEMO_CSS.cssDeep | null
    missingRefs: typeof DEMO_CSS.missingRefs | null
  }
  p1Results: {
    search: typeof DEMO_P1.search | null
    symbols: typeof DEMO_P1.symbols | null
    trace: typeof DEMO_P1.trace | null
    impact: typeof DEMO_P1.impact | null
    dependents: typeof DEMO_P1.dependents | null
    stackTrace: typeof DEMO_P1.stackTrace | null
    query: typeof DEMO_P1.query | null
    list: typeof DEMO_P1.list | null
  }
  p2p3Results: {
    outline: typeof DEMO_P2P3.outline | null
    diff: typeof DEMO_P2P3.diff | null
    context: typeof DEMO_P2P3.context | null
    testMap: typeof DEMO_P2P3.testMap | null
    configDrift: typeof DEMO_P2P3.configDrift | null
    typeInfer: typeof DEMO_P2P3.typeInfer | null
    ownership: typeof DEMO_P2P3.ownership | null
    entrypoints: typeof DEMO_P2P3.entrypoints | null
    apiMap: typeof DEMO_P2P3.apiMap | null
    stateMap: typeof DEMO_P2P3.stateMap | null
  }
  refactoringResults: {
    refactorSafe: typeof DEMO_REFACTORING.refactorSafe | null
    sideEffect: typeof DEMO_REFACTORING.sideEffect | null
  }

  // Watch mode
  isWatchMode: boolean

  // Result panel
  resultTabs: ResultTab[]
  activeResultTab: string | null

  // UI state
  sidebarTab: SidebarTab
  sidebarOpen: boolean
  bottomPanelOpen: boolean
  commandPaletteOpen: boolean

  // Actions
  runCommand: (command: string, args: string[]) => Promise<unknown>
  runChain: (commands: Array<{ command: string; args: string[] }>) => Promise<void>
  setSidebarTab: (tab: SidebarTab) => void
  toggleSidebar: () => void
  setSidebarOpen: (open: boolean) => void
  toggleBottomPanel: () => void
  setBottomPanelOpen: (open: boolean) => void
  toggleCommandPalette: () => void
  setCommandPaletteOpen: (open: boolean) => void
  setWorkspace: (ws: string) => void
  setIsScanning: (val: boolean) => void
  setLastScanTime: (time: number) => void
  setFrameworks: (fw: string[]) => void
  setRegistryStats: (stats: { byType: Record<string, number>; byStatus: Record<string, number> } | null) => void
  addResultTab: (tab: ResultTab) => void
  removeResultTab: (id: string) => void
  setActiveResultTab: (id: string | null) => void
  clearResultTabs: () => void
  clearResults: () => void
  setWatchMode: (val: boolean) => void
  loadDemoData: () => void
}

// ---- Data-Driven Command → State Mapping ----
// Replaces the large switch statement with a declarative map.
// Each entry maps a CLI command to the state category and field name.
// Special commands (scan, init, detect, watch, handbook, ask, validate)
// are handled separately with custom logic.

interface CommandMapping {
  category: keyof Pick<AnalysisState, 'securityResults' | 'qualityResults' | 'performanceResults' | 'cssResults' | 'p1Results' | 'p2p3Results' | 'refactoringResults'>
  field: string
}

const COMMAND_TO_STATE: Record<string, CommandMapping> = {
  // Security
  secrets: { category: 'securityResults', field: 'secrets' },
  'vuln-scan': { category: 'securityResults', field: 'vulnerabilities' },
  dataflow: { category: 'securityResults', field: 'dataflow' },
  'env-check': { category: 'securityResults', field: 'envCheck' },
  'regex-audit': { category: 'securityResults', field: 'regexAudit' },
  // Quality
  smell: { category: 'qualityResults', field: 'smells' },
  complexity: { category: 'qualityResults', field: 'complexity' },
  'debug-leak': { category: 'qualityResults', field: 'debugLeaks' },
  'dead-code': { category: 'qualityResults', field: 'deadCode' },
  a11y: { category: 'qualityResults', field: 'a11y' },
  // Performance
  'perf-hint': { category: 'performanceResults', field: 'perfHints' },
  circular: { category: 'performanceResults', field: 'circular' },
  // CSS
  'css-deep': { category: 'cssResults', field: 'cssDeep' },
  'missing-refs': { category: 'cssResults', field: 'missingRefs' },
  // P1: Search & Trace
  search: { category: 'p1Results', field: 'search' },
  symbols: { category: 'p1Results', field: 'symbols' },
  trace: { category: 'p1Results', field: 'trace' },
  impact: { category: 'p1Results', field: 'impact' },
  dependents: { category: 'p1Results', field: 'dependents' },
  'stack-trace': { category: 'p1Results', field: 'stackTrace' },
  query: { category: 'p1Results', field: 'query' },
  list: { category: 'p1Results', field: 'list' },
  // P2/P3: Outline & Analysis
  outline: { category: 'p2p3Results', field: 'outline' },
  diff: { category: 'p2p3Results', field: 'diff' },
  context: { category: 'p2p3Results', field: 'context' },
  'test-map': { category: 'p2p3Results', field: 'testMap' },
  'config-drift': { category: 'p2p3Results', field: 'configDrift' },
  'type-infer': { category: 'p2p3Results', field: 'typeInfer' },
  ownership: { category: 'p2p3Results', field: 'ownership' },
  entrypoints: { category: 'p2p3Results', field: 'entrypoints' },
  'api-map': { category: 'p2p3Results', field: 'apiMap' },
  'state-map': { category: 'p2p3Results', field: 'stateMap' },
  // Refactoring
  'refactor-safe': { category: 'refactoringResults', field: 'refactorSafe' },
  'side-effect': { category: 'refactoringResults', field: 'sideEffect' },
}

/**
 * Apply a command result to the appropriate state category using the data-driven mapping.
 * Returns a partial state update object, or null if the command has no mapped state field.
 */
function applyCommandToState(command: string, data: unknown, currentState: AnalysisState): Partial<AnalysisState> | null {
  const mapping = COMMAND_TO_STATE[command]
  if (!mapping) return null

  const resultData = (data as Record<string, unknown>)?.raw ?? data
  const category = currentState[mapping.category] as Record<string, unknown>
  return {
    [mapping.category]: { ...category, [mapping.field]: resultData },
  } as Partial<AnalysisState>
}

export const useAnalysisStore = create<AnalysisState>((set, get) => ({
  // Workspace
  workspace: '',
  isScanning: false,
  lastScanTime: null,
  frameworks: [],
  registryStats: null,

  // Commands
  runningCommands: [],
  commandHistory: [],
  recentCommands: [],

  // Analysis results
  securityResults: { secrets: null, vulnerabilities: null, dataflow: null, envCheck: null, regexAudit: null },
  qualityResults: { smells: null, complexity: null, debugLeaks: null, deadCode: null, a11y: null },
  performanceResults: { perfHints: null, circular: null },
  cssResults: { cssDeep: null, missingRefs: null },
  p1Results: { search: null, symbols: null, trace: null, impact: null, dependents: null, stackTrace: null, query: null, list: null },
  p2p3Results: { outline: null, diff: null, context: null, testMap: null, configDrift: null, typeInfer: null, ownership: null, entrypoints: null, apiMap: null, stateMap: null },
  refactoringResults: { refactorSafe: null, sideEffect: null },

  // Watch mode
  isWatchMode: false,

  // Result panel
  resultTabs: [],
  activeResultTab: null,

  // UI
  sidebarTab: 'commands',
  sidebarOpen: true,
  bottomPanelOpen: false,
  commandPaletteOpen: false,

  // Actions
  runCommand: async (command: string, args: string[]) => {
    const entry: CommandHistoryEntry = {
      command,
      args,
      timestamp: Date.now(),
      status: 'running',
    }

    set(state => ({
      runningCommands: [...state.runningCommands, command],
      commandHistory: [entry, ...state.commandHistory].slice(0, 50),
      recentCommands: [command, ...state.recentCommands.filter(c => c !== command)].slice(0, 5),
    }))

    try {
      const res = await fetch('/api/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command, args, workspace: get().workspace }),
      })

      if (!res.ok) {
        throw new Error(`API error: ${res.status} ${res.statusText}`)
      }

      const data = await res.json()

      // Add result tab
      const tabId = `${command}-${Date.now()}`
      const tab: ResultTab = {
        id: tabId,
        command,
        timestamp: Date.now(),
        content: data,
      }

      // Update specific analysis result based on command (data-driven)
      const updates: Partial<AnalysisState> = {}

      // Use data-driven mapping for standard commands
      const mappedUpdate = applyCommandToState(command, data, get())
      if (mappedUpdate) {
        Object.assign(updates, mappedUpdate)
      }

      // Handle special commands with custom logic
      switch (command) {
        case 'scan':
          updates.lastScanTime = Date.now()
          updates.isScanning = false
          break
        case 'init':
          updates.lastScanTime = Date.now()
          if (data?.config) updates.frameworks = data.config.frameworks ?? get().frameworks
          break
        case 'detect':
          if (data?.frameworks) updates.frameworks = data.frameworks
          break
        case 'watch':
          updates.isWatchMode = !get().isWatchMode
          break
        // validate, handbook, ask — results go to result panel only
      }

      set(state => ({
        runningCommands: state.runningCommands.filter(c => c !== command),
        commandHistory: state.commandHistory.map(h =>
          h.timestamp === entry.timestamp ? { ...h, status: 'success', result: data } : h
        ),
        resultTabs: [...state.resultTabs, tab],
        activeResultTab: tabId,
        bottomPanelOpen: true,
        ...updates,
      }))

      return data
    } catch (err) {
      const errorTabId = `error-${command}-${Date.now()}`
      set(state => ({
        runningCommands: state.runningCommands.filter(c => c !== command),
        commandHistory: state.commandHistory.map(h =>
          h.timestamp === entry.timestamp ? { ...h, status: 'error', result: String(err) } : h
        ),
        resultTabs: [...state.resultTabs, {
          id: errorTabId,
          command: `error:${command}`,
          timestamp: Date.now(),
          content: { error: true, command, message: String(err) },
        }],
        activeResultTab: errorTabId,
        bottomPanelOpen: true,
      }))
      return { error: String(err) }
    }
  },

  runChain: async (commands) => {
    for (const { command, args } of commands) {
      await get().runCommand(command, args)
    }
  },

  setSidebarTab: (tab) => set({ sidebarTab: tab }),
  toggleSidebar: () => set(state => ({ sidebarOpen: !state.sidebarOpen })),
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  toggleBottomPanel: () => set(state => ({ bottomPanelOpen: !state.bottomPanelOpen })),
  setBottomPanelOpen: (open) => set({ bottomPanelOpen: open }),
  toggleCommandPalette: () => set(state => ({ commandPaletteOpen: !state.commandPaletteOpen })),
  setCommandPaletteOpen: (open) => set({ commandPaletteOpen: open }),
  setWorkspace: (ws) => set({ workspace: ws }),
  setIsScanning: (val) => set({ isScanning: val }),
  setLastScanTime: (time) => set({ lastScanTime: time }),
  setFrameworks: (fw) => set({ frameworks: fw }),
  setRegistryStats: (stats) => set({ registryStats: stats }),
  setWatchMode: (val) => set({ isWatchMode: val }),

  addResultTab: (tab) => set(state => ({
    resultTabs: [...state.resultTabs, tab],
    activeResultTab: tab.id,
    bottomPanelOpen: true,
  })),

  removeResultTab: (id) => set(state => {
    const tabs = state.resultTabs.filter(t => t.id !== id)
    return {
      resultTabs: tabs,
      activeResultTab: state.activeResultTab === id ? (tabs[tabs.length - 1]?.id ?? null) : state.activeResultTab,
    }
  }),

  setActiveResultTab: (id) => set({ activeResultTab: id }),
  clearResultTabs: () => set({ resultTabs: [], activeResultTab: null }),

  clearResults: () => set({
    securityResults: { secrets: null, vulnerabilities: null, dataflow: null, envCheck: null, regexAudit: null },
    qualityResults: { smells: null, complexity: null, debugLeaks: null, deadCode: null, a11y: null },
    performanceResults: { perfHints: null, circular: null },
    cssResults: { cssDeep: null, missingRefs: null },
    p1Results: { search: null, symbols: null, trace: null, impact: null, dependents: null, stackTrace: null, query: null, list: null },
    p2p3Results: { outline: null, diff: null, context: null, testMap: null, configDrift: null, typeInfer: null, ownership: null, entrypoints: null, apiMap: null, stateMap: null },
    refactoringResults: { refactorSafe: null, sideEffect: null },
    resultTabs: [],
    activeResultTab: null,
  }),

  loadDemoData: () => set({
    securityResults: {
      secrets: DEMO_SECURITY.secrets,
      vulnerabilities: DEMO_SECURITY.vulnerabilities,
      dataflow: DEMO_SECURITY.dataflow,
      envCheck: DEMO_SECURITY.envCheck,
      regexAudit: DEMO_SECURITY.regexAudit,
    },
    qualityResults: {
      smells: DEMO_QUALITY.smells,
      complexity: DEMO_QUALITY.complexity,
      debugLeaks: DEMO_QUALITY.debugLeaks,
      deadCode: DEMO_QUALITY.deadCode,
      a11y: DEMO_QUALITY.a11y,
    },
    performanceResults: {
      perfHints: DEMO_PERFORMANCE.perfHints,
      circular: DEMO_PERFORMANCE.circular,
    },
    cssResults: {
      cssDeep: DEMO_CSS.cssDeep,
      missingRefs: DEMO_CSS.missingRefs,
    },
    p1Results: {
      search: DEMO_P1.search,
      symbols: DEMO_P1.symbols,
      trace: DEMO_P1.trace,
      impact: DEMO_P1.impact,
      dependents: DEMO_P1.dependents,
      stackTrace: DEMO_P1.stackTrace,
      query: DEMO_P1.query,
      list: DEMO_P1.list,
    },
    p2p3Results: {
      outline: DEMO_P2P3.outline,
      diff: DEMO_P2P3.diff,
      context: DEMO_P2P3.context,
      testMap: DEMO_P2P3.testMap,
      configDrift: DEMO_P2P3.configDrift,
      typeInfer: DEMO_P2P3.typeInfer,
      ownership: DEMO_P2P3.ownership,
      entrypoints: DEMO_P2P3.entrypoints,
      apiMap: DEMO_P2P3.apiMap,
      stateMap: DEMO_P2P3.stateMap,
    },
    refactoringResults: {
      refactorSafe: DEMO_REFACTORING.refactorSafe,
      sideEffect: DEMO_REFACTORING.sideEffect,
    },
    lastScanTime: Date.now() - 120000,
    frameworks: ['Next.js', 'React', 'Tailwind CSS', 'Prisma'],
  }),
}))
