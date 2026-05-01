'use client'

import { create } from 'zustand'
import type { SidebarTab, CommandHistoryEntry, ResultTab } from '@/types/neural'

// ---- Demo Analysis Data ----
export const DEMO_SECURITY = {
  secrets: {
    findings: [
      { env_key: 'AWS_SECRET_ACCESS_KEY', file: 'src/config/aws.ts', line: 5, severity: 'critical', category: 'aws_key', match: 'AKIA***' },
      { env_key: 'STRIPE_API_KEY', file: 'src/api/payment.ts', line: 3, severity: 'high', category: 'api_key', match: 'sk_live_***' },
      { env_key: 'JWT_SECRET', file: 'src/auth/jwt.ts', line: 1, severity: 'medium', category: 'secret', match: 'super***' },
    ],
    risk: 'high',
  },
  vulnerabilities: {
    vulnerabilities: [
      { package: 'express', version: '4.17.1', cve: 'CVE-2024-29041', severity: 'high', description: 'Open redirect vulnerability' },
      { package: 'lodash', version: '4.17.20', cve: 'CVE-2024-13617', severity: 'medium', description: 'Prototype pollution' },
    ],
    risk: 'medium',
  },
  dataflow: {
    flows: [
      { source: { fn: 'handleLogin', file: 'src/auth/handler.ts', line: 8, tainted: true }, sink: { fn: 'processPayment', file: 'src/api/payment.ts', line: 10, dangerous: true } },
    ],
    risk: 'critical',
  },
  envCheck: {
    missing: ['DATABASE_URL', 'REDIS_URL', 'SMTP_HOST'],
    exposed: ['.env.local'],
    risk: 'medium',
  },
}

export const DEMO_QUALITY = {
  smells: {
    by_category: {
      long_function: [{ fn: 'processPayment', file: 'src/api/payment.ts', line: 10, severity: 'warning', message: 'Function is 85 lines (threshold: 50)' }],
      deep_nesting: [{ fn: 'validateInput', file: 'src/auth/validation.ts', line: 3, severity: 'warning', message: '4 levels of nesting' }],
      duplicate_code: [{ fn: 'formatCurrency', file: 'src/utils/format.ts', line: 1, severity: 'info', message: 'Similar block in cart.ts:5' }],
      magic_number: [{ fn: 'calculateTotal', file: 'src/api/cart.ts', line: 3, severity: 'info', message: 'Magic number 0.08 (tax rate)' }],
    },
    stats: { total_smells: 4, health_score: 72, by_severity: { critical: 0, warning: 2, info: 2 } },
    risk: 'medium',
  },
  complexity: {
    results: [
      { fn: 'processPayment', file: 'src/api/payment.ts', line: 10, cyclomatic: 18, cognitive: 12, level: 'untamable' },
      { fn: 'handleLogin', file: 'src/auth/handler.ts', line: 8, cyclomatic: 8, cognitive: 5, level: 'complex' },
      { fn: 'verify_token', file: 'src/auth/jwt.ts', line: 12, cyclomatic: 4, cognitive: 3, level: 'moderate' },
      { fn: 'formatCurrency', file: 'src/utils/format.ts', line: 1, cyclomatic: 2, cognitive: 1, level: 'simple' },
    ],
    stats: { simple: 12, moderate: 6, complex: 3, untamable: 1 },
  },
  debugLeaks: {
    findings: [
      { fn: 'handleLogin', file: 'src/auth/handler.ts', line: 15, type: 'console.log', message: 'Debug console.log in production code' },
      { fn: 'getData', file: 'src/api/data.ts', line: 22, type: 'console.debug', message: 'Leftover console.debug statement' },
    ],
  },
  deadCode: {
    results: {
      unused_exports: [{ fn: 'legacyHelper', file: 'src/utils/legacy.ts', line: 1 }],
      unreachable: [{ fn: 'oldHandler', file: 'src/api/old.ts', line: 5 }],
    },
    stats: { total_dead_code: 2 },
  },
  a11y: {
    issues: [
      { element: '#login-form', file: 'src/pages/Login.tsx', line: 12, category: 'missing_label', severity: 'error', message: 'Form input missing label' },
      { element: '#main-content', file: 'src/pages/Dashboard.tsx', line: 8, category: 'missing_alt', severity: 'warning', message: 'Image missing alt text' },
    ],
  },
}

export const DEMO_PERFORMANCE = {
  perfHints: {
    hints: [
      { fn: 'getData', file: 'src/api/data.ts', line: 5, category: 'n_plus_1', severity: 'high', message: 'N+1 query pattern detected in loop' },
      { fn: 'renderDashboard', file: 'src/pages/Dashboard.tsx', line: 20, category: 'expensive_render', severity: 'medium', message: 'Expensive re-render without memoization' },
      { fn: 'calculateTotal', file: 'src/api/cart.ts', line: 3, category: 'sync_blocking', severity: 'low', message: 'Synchronous blocking call in async context' },
    ],
    stats: { by_category: { n_plus_1: 1, expensive_render: 1, sync_blocking: 1, large_bundle: 0, memory_leak: 0, render_bottleneck: 0, unnecessary_recompute: 0, unoptimized_loop: 0 } },
  },
  circular: {
    cycles: [
      { chain: ['src/api/data.ts', 'src/utils/format.ts', 'src/api/data.ts'], length: 2 },
    ],
    risk: 'high',
  },
}

export const DEMO_CSS = {
  cssDeep: {
    unused_vars: ['--color-muted', '--spacing-xl', '--font-display'],
    orphan_keyframes: ['fadeInOut', 'slideObsolete'],
    specificity_wars: { important_count: 14, files: ['src/styles/global.css', 'src/styles/buttons.css'] },
    duplicate_properties: { count: 3, examples: ['background-color in .btn-primary', 'margin in .card-shadow'] },
    z_index_abuse: { max: 99999, count: 8, above_1000: 3 },
  },
  missingRefs: {
    css_no_html: ['.deprecated-class', '.old-layout'],
    html_no_css: ['#temp-container', '.custom-override'],
  },
}

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
  loadDemoData: () => void
}

export const useAnalysisStore = create<AnalysisState>((set, get) => ({
  // Workspace
  workspace: '/home/z/my-project',
  isScanning: false,
  lastScanTime: null,
  frameworks: [],
  registryStats: null,

  // Commands
  runningCommands: [],
  commandHistory: [],
  recentCommands: [],

  // Analysis results
  securityResults: { secrets: null, vulnerabilities: null, dataflow: null, envCheck: null },
  qualityResults: { smells: null, complexity: null, debugLeaks: null, deadCode: null, a11y: null },
  performanceResults: { perfHints: null, circular: null },
  cssResults: { cssDeep: null, missingRefs: null },

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

      const data = await res.json()

      // Add result tab
      const tabId = `${command}-${Date.now()}`
      const tab: ResultTab = {
        id: tabId,
        command,
        timestamp: Date.now(),
        content: data,
      }

      // Update specific analysis result based on command
      const updates: Partial<AnalysisState> = {}

      switch (command) {
        case 'secrets':
          updates.securityResults = { ...get().securityResults, secrets: data.raw ?? data }
          break
        case 'vuln-scan':
          updates.securityResults = { ...get().securityResults, vulnerabilities: data.raw ?? data }
          break
        case 'dataflow':
          updates.securityResults = { ...get().securityResults, dataflow: data.raw ?? data }
          break
        case 'env-check':
          updates.securityResults = { ...get().securityResults, envCheck: data.raw ?? data }
          break
        case 'smell':
          updates.qualityResults = { ...get().qualityResults, smells: data.raw ?? data }
          break
        case 'complexity':
          updates.qualityResults = { ...get().qualityResults, complexity: data.raw ?? data }
          break
        case 'debug-leak':
          updates.qualityResults = { ...get().qualityResults, debugLeaks: data.raw ?? data }
          break
        case 'dead-code':
          updates.qualityResults = { ...get().qualityResults, deadCode: data.raw ?? data }
          break
        case 'a11y':
          updates.qualityResults = { ...get().qualityResults, a11y: data.raw ?? data }
          break
        case 'perf-hint':
          updates.performanceResults = { ...get().performanceResults, perfHints: data.raw ?? data }
          break
        case 'circular':
          updates.performanceResults = { ...get().performanceResults, circular: data.raw ?? data }
          break
        case 'css-deep':
          updates.cssResults = { ...get().cssResults, cssDeep: data.raw ?? data }
          break
        case 'missing-refs':
          updates.cssResults = { ...get().cssResults, missingRefs: data.raw ?? data }
          break
        case 'scan':
          updates.lastScanTime = Date.now()
          updates.isScanning = false
          break
        case 'detect':
          if (data?.frameworks) updates.frameworks = data.frameworks
          break
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
      set(state => ({
        runningCommands: state.runningCommands.filter(c => c !== command),
        commandHistory: state.commandHistory.map(h =>
          h.timestamp === entry.timestamp ? { ...h, status: 'error', result: String(err) } : h
        ),
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

  loadDemoData: () => set({
    securityResults: {
      secrets: DEMO_SECURITY.secrets,
      vulnerabilities: DEMO_SECURITY.vulnerabilities,
      dataflow: DEMO_SECURITY.dataflow,
      envCheck: DEMO_SECURITY.envCheck,
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
    lastScanTime: Date.now() - 120000,
    frameworks: ['Next.js', 'React', 'Tailwind CSS', 'Prisma'],
  }),
}))
