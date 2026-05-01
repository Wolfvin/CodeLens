'use client'

import React from 'react'
import { Zap, RefreshCw, AlertTriangle, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { useAnalysisStore } from '@/lib/analysisStore'

interface PerformanceTabProps {
  theme: 'dark' | 'light'
}

const PERF_CATEGORIES = [
  { key: 'n_plus_1', label: 'N+1 Queries', color: '#e53e3e' },
  { key: 'expensive_render', label: 'Expensive Renders', color: '#ed8936' },
  { key: 'sync_blocking', label: 'Sync Blocking', color: '#ecc94b' },
  { key: 'large_bundle', label: 'Large Bundle', color: '#fc8181' },
  { key: 'memory_leak', label: 'Memory Leaks', color: '#e53e3e' },
  { key: 'render_bottleneck', label: 'Render Bottleneck', color: '#ed8936' },
  { key: 'unnecessary_recompute', label: 'Unnecessary Recompute', color: '#ecc94b' },
  { key: 'unoptimized_loop', label: 'Unoptimized Loop', color: '#fc8181' },
]

export function PerformanceTab({ theme }: PerformanceTabProps) {
  const { performanceResults, runCommand, workspace, runningCommands } = useAnalysisStore()
  const { perfHints, circular } = performanceResults

  const isRunning = (cmd: string) => runningCommands.includes(cmd)

  const runPerfAudit = async () => {
    await runCommand('perf-hint', [workspace])
    await runCommand('complexity', [workspace])
    await runCommand('circular', [workspace])
  }

  const hintCount = perfHints?.hints?.length ?? 0
  const circularCount = circular?.cycles?.length ?? 0
  const byCategory = perfHints?.stats?.by_category ?? {}

  const card = {
    backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
    borderRadius: '8px',
    padding: '10px',
  }

  return (
    <ScrollArea className="h-full">
      <div className="p-3 space-y-4">
        {/* Performance Audit */}
        <Button
          className="w-full h-9 text-xs gap-2 bg-amber-600 hover:bg-amber-700 text-white"
          onClick={runPerfAudit}
          disabled={isRunning('perf-hint')}
        >
          {isRunning('perf-hint') ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
          Performance Audit
        </Button>

        <div className="grid grid-cols-2 gap-1.5">
          <Button size="sm" variant="outline" className="h-7 text-[10px] gap-1" style={{ borderColor: theme === 'dark' ? '#2d3748' : '#e2e8f0', color: theme === 'dark' ? '#e2e8f0' : '#1a202c' }} onClick={() => runCommand('perf-hint', [workspace])} disabled={isRunning('perf-hint')}>
            <Zap className="h-3 w-3" /> Perf Hints
          </Button>
          <Button size="sm" variant="outline" className="h-7 text-[10px] gap-1" style={{ borderColor: theme === 'dark' ? '#2d3748' : '#e2e8f0', color: theme === 'dark' ? '#e2e8f0' : '#1a202c' }} onClick={() => runCommand('circular', [workspace])} disabled={isRunning('circular')}>
            <RefreshCw className="h-3 w-3" /> Circular
          </Button>
        </div>

        <Separator style={{ backgroundColor: theme === 'dark' ? '#2d3748' : '#e2e8f0' }} />

        {/* Summary Cards */}
        <div className="grid grid-cols-2 gap-2">
          <div style={card}>
            <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">Perf Hints</div>
            <div className="text-xl font-bold mt-1" style={{ color: hintCount > 0 ? '#ed8936' : '#48bb78' }}>{hintCount}</div>
          </div>
          <div style={card}>
            <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">Circular Deps</div>
            <div className="text-xl font-bold mt-1" style={{ color: circularCount > 0 ? '#e53e3e' : '#48bb78' }}>{circularCount}</div>
          </div>
        </div>

        {/* Performance Hints Breakdown */}
        <div className="space-y-2">
          <div className="text-xs font-semibold">Hints by Category</div>
          {PERF_CATEGORIES.map(({ key, label, color }) => {
            const count = byCategory[key as keyof typeof byCategory] ?? 0
            return (
              <div key={key} className="flex items-center gap-2 text-xs">
                <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: color }} />
                <span className="flex-1 opacity-70">{label}</span>
                <span className="font-mono" style={{ color: count > 0 ? color : '#718096' }}>{count}</span>
              </div>
            )
          })}
        </div>

        {/* Hints Detail */}
        {perfHints?.hints && perfHints.hints.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs font-semibold">Hint Details</div>
            {perfHints.hints.map((h, i) => (
              <div key={i} style={card}>
                <div className="flex items-center gap-1.5 text-xs">
                  <Badge className="text-[9px] h-4" style={{
                    backgroundColor: h.severity === 'high' ? 'rgba(229,62,62,0.2)' : h.severity === 'medium' ? 'rgba(237,137,54,0.2)' : 'rgba(236,201,75,0.2)',
                    color: h.severity === 'high' ? '#e53e3e' : h.severity === 'medium' ? '#ed8936' : '#ecc94b',
                  }}>
                    {h.severity}
                  </Badge>
                  <span className="font-medium">{h.category.replace(/_/g, ' ')}</span>
                </div>
                <div className="text-xs font-medium mt-1">{h.fn}</div>
                <div className="text-[10px] opacity-50">{h.message}</div>
                <div className="text-[10px] opacity-40 font-mono mt-0.5">{h.file}:{h.line}</div>
              </div>
            ))}
          </div>
        )}

        {/* Circular Dependencies */}
        {circular?.cycles && circular.cycles.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-3.5 w-3.5" style={{ color: '#e53e3e' }} />
              <span className="text-xs font-semibold">Circular Dependencies</span>
            </div>
            {circular.cycles.map((c, i) => (
              <div key={i} style={card}>
                <div className="flex items-center gap-1 text-xs flex-wrap">
                  {(c.chain ?? []).map((node: string, j: number) => (
                    <React.Fragment key={j}>
                      <span className="font-mono text-[10px] px-1.5 py-0.5 rounded" style={{ backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' }}>
                        {node.split('/').pop()}
                      </span>
                      {j < (c.chain ?? []).length - 1 && <span className="opacity-30">→</span>}
                    </React.Fragment>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </ScrollArea>
  )
}
