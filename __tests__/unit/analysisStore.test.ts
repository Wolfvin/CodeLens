// ============================================================
// AnalysisStore Unit Tests
// ============================================================

import { useAnalysisStore } from '@/lib/analysisStore'

// ---- Helpers ----

// Get a fresh store state for each test by calling setState
function getFreshStore() {
  const store = useAnalysisStore
  // Reset to initial state
  store.setState({
    workspace: '/home/z/my-project',
    isScanning: false,
    lastScanTime: null,
    frameworks: [],
    registryStats: null,
    runningCommands: [],
    commandHistory: [],
    recentCommands: [],
    securityResults: { secrets: null, vulnerabilities: null, dataflow: null, envCheck: null, regexAudit: null },
    qualityResults: { smells: null, complexity: null, debugLeaks: null, deadCode: null, a11y: null },
    performanceResults: { perfHints: null, circular: null },
    cssResults: { cssDeep: null, missingRefs: null },
    p1Results: { search: null, symbols: null, trace: null, impact: null, dependents: null, stackTrace: null, query: null, list: null },
    p2p3Results: { outline: null, diff: null, context: null, testMap: null, configDrift: null, typeInfer: null, ownership: null, entrypoints: null, apiMap: null, stateMap: null },
    refactoringResults: { refactorSafe: null, sideEffect: null },
    isWatchMode: false,
    resultTabs: [],
    activeResultTab: null,
    sidebarTab: 'commands',
    sidebarOpen: true,
    bottomPanelOpen: false,
    commandPaletteOpen: false,
  })
  return store
}

// ---- Test Suite ----

describe('AnalysisStore', () => {
  beforeEach(() => {
    getFreshStore()
  })

  // ============================================================
  // Initial state
  // ============================================================

  describe('initial state', () => {
    it('has all results as null', () => {
      const state = useAnalysisStore.getState()

      // Security results
      expect(state.securityResults.secrets).toBeNull()
      expect(state.securityResults.vulnerabilities).toBeNull()
      expect(state.securityResults.dataflow).toBeNull()
      expect(state.securityResults.envCheck).toBeNull()
      expect(state.securityResults.regexAudit).toBeNull()

      // Quality results
      expect(state.qualityResults.smells).toBeNull()
      expect(state.qualityResults.complexity).toBeNull()
      expect(state.qualityResults.debugLeaks).toBeNull()
      expect(state.qualityResults.deadCode).toBeNull()
      expect(state.qualityResults.a11y).toBeNull()

      // Performance results
      expect(state.performanceResults.perfHints).toBeNull()
      expect(state.performanceResults.circular).toBeNull()

      // CSS results
      expect(state.cssResults.cssDeep).toBeNull()
      expect(state.cssResults.missingRefs).toBeNull()

      // P1 results
      expect(state.p1Results.search).toBeNull()
      expect(state.p1Results.symbols).toBeNull()
      expect(state.p1Results.trace).toBeNull()
      expect(state.p1Results.impact).toBeNull()
      expect(state.p1Results.dependents).toBeNull()
      expect(state.p1Results.stackTrace).toBeNull()
      expect(state.p1Results.query).toBeNull()
      expect(state.p1Results.list).toBeNull()

      // P2/P3 results
      expect(state.p2p3Results.outline).toBeNull()
      expect(state.p2p3Results.diff).toBeNull()
      expect(state.p2p3Results.context).toBeNull()
      expect(state.p2p3Results.testMap).toBeNull()
      expect(state.p2p3Results.configDrift).toBeNull()
      expect(state.p2p3Results.typeInfer).toBeNull()
      expect(state.p2p3Results.ownership).toBeNull()
      expect(state.p2p3Results.entrypoints).toBeNull()
      expect(state.p2p3Results.apiMap).toBeNull()
      expect(state.p2p3Results.stateMap).toBeNull()

      // Refactoring results
      expect(state.refactoringResults.refactorSafe).toBeNull()
      expect(state.refactoringResults.sideEffect).toBeNull()
    })

    it('has default workspace', () => {
      const state = useAnalysisStore.getState()
      expect(state.workspace).toBe('/home/z/my-project')
    })

    it('has default sidebar tab as commands', () => {
      const state = useAnalysisStore.getState()
      expect(state.sidebarTab).toBe('commands')
    })

    it('is not scanning initially', () => {
      const state = useAnalysisStore.getState()
      expect(state.isScanning).toBe(false)
    })

    it('is not in watch mode initially', () => {
      const state = useAnalysisStore.getState()
      expect(state.isWatchMode).toBe(false)
    })
  })

  // ============================================================
  // loadDemoData
  // ============================================================

  describe('loadDemoData', () => {
    it('populates all result buckets', () => {
      useAnalysisStore.getState().loadDemoData()
      const state = useAnalysisStore.getState()

      // Security
      expect(state.securityResults.secrets).not.toBeNull()
      expect(state.securityResults.vulnerabilities).not.toBeNull()
      expect(state.securityResults.dataflow).not.toBeNull()
      expect(state.securityResults.envCheck).not.toBeNull()
      expect(state.securityResults.regexAudit).not.toBeNull()

      // Quality
      expect(state.qualityResults.smells).not.toBeNull()
      expect(state.qualityResults.complexity).not.toBeNull()
      expect(state.qualityResults.debugLeaks).not.toBeNull()
      expect(state.qualityResults.deadCode).not.toBeNull()
      expect(state.qualityResults.a11y).not.toBeNull()

      // Performance
      expect(state.performanceResults.perfHints).not.toBeNull()
      expect(state.performanceResults.circular).not.toBeNull()

      // CSS
      expect(state.cssResults.cssDeep).not.toBeNull()
      expect(state.cssResults.missingRefs).not.toBeNull()

      // P1
      expect(state.p1Results.search).not.toBeNull()
      expect(state.p1Results.symbols).not.toBeNull()
      expect(state.p1Results.trace).not.toBeNull()
      expect(state.p1Results.impact).not.toBeNull()
      expect(state.p1Results.dependents).not.toBeNull()
      expect(state.p1Results.stackTrace).not.toBeNull()
      expect(state.p1Results.query).not.toBeNull()
      expect(state.p1Results.list).not.toBeNull()

      // P2/P3
      expect(state.p2p3Results.outline).not.toBeNull()
      expect(state.p2p3Results.diff).not.toBeNull()
      expect(state.p2p3Results.context).not.toBeNull()
      expect(state.p2p3Results.testMap).not.toBeNull()
      expect(state.p2p3Results.configDrift).not.toBeNull()
      expect(state.p2p3Results.typeInfer).not.toBeNull()
      expect(state.p2p3Results.ownership).not.toBeNull()
      expect(state.p2p3Results.entrypoints).not.toBeNull()
      expect(state.p2p3Results.apiMap).not.toBeNull()
      expect(state.p2p3Results.stateMap).not.toBeNull()

      // Refactoring
      expect(state.refactoringResults.refactorSafe).not.toBeNull()
      expect(state.refactoringResults.sideEffect).not.toBeNull()
    })

    it('sets frameworks', () => {
      useAnalysisStore.getState().loadDemoData()
      const state = useAnalysisStore.getState()
      expect(state.frameworks.length).toBeGreaterThan(0)
      expect(state.frameworks).toEqual(expect.arrayContaining(['Next.js', 'React']))
    })

    it('sets lastScanTime', () => {
      useAnalysisStore.getState().loadDemoData()
      const state = useAnalysisStore.getState()
      expect(state.lastScanTime).not.toBeNull()
    })
  })

  // ============================================================
  // clearResults
  // ============================================================

  describe('clearResults', () => {
    it('resets everything to null', () => {
      useAnalysisStore.getState().loadDemoData()
      useAnalysisStore.getState().clearResults()
      const state = useAnalysisStore.getState()

      expect(state.securityResults.secrets).toBeNull()
      expect(state.qualityResults.smells).toBeNull()
      expect(state.performanceResults.perfHints).toBeNull()
      expect(state.cssResults.cssDeep).toBeNull()
      expect(state.p1Results.search).toBeNull()
      expect(state.p2p3Results.outline).toBeNull()
      expect(state.refactoringResults.refactorSafe).toBeNull()
      expect(state.resultTabs).toHaveLength(0)
      expect(state.activeResultTab).toBeNull()
    })
  })

  // ============================================================
  // setWorkspace
  // ============================================================

  describe('setWorkspace', () => {
    it('updates workspace', () => {
      useAnalysisStore.getState().setWorkspace('/custom/path')
      expect(useAnalysisStore.getState().workspace).toBe('/custom/path')
    })
  })

  // ============================================================
  // runCommand (commandHistory)
  // ============================================================

  describe('runCommand', () => {
    it('adds to commandHistory', async () => {
      // Mock fetch to avoid actual API calls
      const originalFetch = global.fetch
      global.fetch = jest.fn().mockResolvedValue({
        json: () => Promise.resolve({ status: 'ok', data: {} }),
      })

      try {
        await useAnalysisStore.getState().runCommand('scan', ['/workspace'])
        const state = useAnalysisStore.getState()
        expect(state.commandHistory.length).toBeGreaterThan(0)
        expect(state.commandHistory[0].command).toBe('scan')
        expect(state.commandHistory[0].status).toBe('success')
      } finally {
        global.fetch = originalFetch
      }
    })

    it('adds to recentCommands', async () => {
      const originalFetch = global.fetch
      global.fetch = jest.fn().mockResolvedValue({
        json: () => Promise.resolve({ status: 'ok', data: {} }),
      })

      try {
        await useAnalysisStore.getState().runCommand('scan', ['/workspace'])
        const state = useAnalysisStore.getState()
        expect(state.recentCommands).toContain('scan')
      } finally {
        global.fetch = originalFetch
      }
    })

    it('records error on fetch failure', async () => {
      const originalFetch = global.fetch
      global.fetch = jest.fn().mockRejectedValue(new Error('Network error'))

      try {
        await useAnalysisStore.getState().runCommand('scan', ['/workspace'])
        const state = useAnalysisStore.getState()
        expect(state.commandHistory.length).toBeGreaterThan(0)
        expect(state.commandHistory[0].status).toBe('error')
      } finally {
        global.fetch = originalFetch
      }
    })
  })

  // ============================================================
  // sidebarTab navigation
  // ============================================================

  describe('sidebarTab navigation', () => {
    it('switches to different tabs', () => {
      const tabs = ['commands', 'workspace', 'security', 'quality', 'performance', 'css', 'p1', 'p2p3', 'refactoring', 'watch'] as const

      for (const tab of tabs) {
        useAnalysisStore.getState().setSidebarTab(tab)
        expect(useAnalysisStore.getState().sidebarTab).toBe(tab)
      }
    })

    it('defaults to commands tab', () => {
      expect(useAnalysisStore.getState().sidebarTab).toBe('commands')
    })
  })

  // ============================================================
  // UI toggles
  // ============================================================

  describe('UI toggles', () => {
    it('toggleSidebar flips sidebarOpen', () => {
      const initial = useAnalysisStore.getState().sidebarOpen
      useAnalysisStore.getState().toggleSidebar()
      expect(useAnalysisStore.getState().sidebarOpen).toBe(!initial)
    })

    it('setSidebarOpen sets directly', () => {
      useAnalysisStore.getState().setSidebarOpen(false)
      expect(useAnalysisStore.getState().sidebarOpen).toBe(false)
      useAnalysisStore.getState().setSidebarOpen(true)
      expect(useAnalysisStore.getState().sidebarOpen).toBe(true)
    })

    it('toggleBottomPanel flips bottomPanelOpen', () => {
      const initial = useAnalysisStore.getState().bottomPanelOpen
      useAnalysisStore.getState().toggleBottomPanel()
      expect(useAnalysisStore.getState().bottomPanelOpen).toBe(!initial)
    })

    it('toggleCommandPalette flips commandPaletteOpen', () => {
      const initial = useAnalysisStore.getState().commandPaletteOpen
      useAnalysisStore.getState().toggleCommandPalette()
      expect(useAnalysisStore.getState().commandPaletteOpen).toBe(!initial)
    })

    it('setWatchMode sets watch mode', () => {
      useAnalysisStore.getState().setWatchMode(true)
      expect(useAnalysisStore.getState().isWatchMode).toBe(true)
      useAnalysisStore.getState().setWatchMode(false)
      expect(useAnalysisStore.getState().isWatchMode).toBe(false)
    })
  })

  // ============================================================
  // Result tabs
  // ============================================================

  describe('result tabs', () => {
    it('addResultTab adds tab and opens bottom panel', () => {
      useAnalysisStore.getState().addResultTab({
        id: 'tab1',
        command: 'scan',
        timestamp: Date.now(),
        content: { status: 'ok' },
      })
      const state = useAnalysisStore.getState()
      expect(state.resultTabs).toHaveLength(1)
      expect(state.activeResultTab).toBe('tab1')
      expect(state.bottomPanelOpen).toBe(true)
    })

    it('removeResultTab removes tab and adjusts activeResultTab', () => {
      useAnalysisStore.getState().addResultTab({ id: 'tab1', command: 'scan', timestamp: 1, content: {} })
      useAnalysisStore.getState().addResultTab({ id: 'tab2', command: 'query', timestamp: 2, content: {} })
      useAnalysisStore.getState().removeResultTab('tab2')
      const state = useAnalysisStore.getState()
      expect(state.resultTabs).toHaveLength(1)
      expect(state.activeResultTab).toBe('tab1')
    })

    it('clearResultTabs removes all tabs', () => {
      useAnalysisStore.getState().addResultTab({ id: 'tab1', command: 'scan', timestamp: 1, content: {} })
      useAnalysisStore.getState().clearResultTabs()
      const state = useAnalysisStore.getState()
      expect(state.resultTabs).toHaveLength(0)
      expect(state.activeResultTab).toBeNull()
    })
  })

  // ============================================================
  // runChain
  // ============================================================

  describe('runChain', () => {
    it('runs commands in sequence', async () => {
      const originalFetch = global.fetch
      global.fetch = jest.fn().mockResolvedValue({
        json: () => Promise.resolve({ status: 'ok', data: {} }),
      })

      try {
        await useAnalysisStore.getState().runChain([
          { command: 'scan', args: ['/ws'] },
          { command: 'query', args: ['fn1'] },
        ])
        const state = useAnalysisStore.getState()
        // Both commands should be in history
        const cmds = state.commandHistory.map(h => h.command)
        expect(cmds).toContain('scan')
        expect(cmds).toContain('query')
      } finally {
        global.fetch = originalFetch
      }
    })
  })
})
